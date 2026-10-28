"""Seeded mine tunnels: narrow winding drives between small chambers, blocky like a voxel cave.

    python3 tunnel.py --seed 7                   # PyBullet viewer (Tab: walk)
    python3 tunnel.py --seed 7 --headless --render out/tunnel_seed7.png
    python3 tunnel.py --seed 7 --roof            # closed ceilings for sensor runs
    python3 tunnel.py --seed 7 --no-steps        # level floors: no steps at all

Method (after PLUME's graph-then-geometry pipeline and voxel "worm" caves): chambers are unions of discs; a
minimum spanning tree joins them and extra tunnels join chambers that are not dead ends; each tunnel is a worm
that turns smoothly towards its target while it wanders. Everything is carved in a grid of `cell` columns, each
with a floor and a ceiling height, and emitted as boxes merged into rectangles: walls, floors and ceilings are
blocky, the layout is organic. Floors follow a gentle relief (at most `max_grade`) terraced in `floor_quantum`
steps, crossed by a few lines of 2-4 steps. The robot starts in a chamber (scene["spawn"]).
The scene uses indoor.generate's schema, so load_pybullet, fastload, the viewer, the minimap and gazebo.py work
unchanged.
"""
from dataclasses import asdict, dataclass
import argparse
import json
import math
import random
import sys
import time

import numpy as np

import settings
from styles import material_spec

ROCK, FLOOR, TIMBER, CONCRETE = [.42, .38, .34, 1], [.62, .57, .50, 1], [.55, .40, .24, 1], [.72, .71, .68, 1]
SLAB = .3          # floor and ceiling slab thickness under/above the carved space
HEADROOM = 1.9     # minimum clear height anywhere in a tunnel
TURN = .12         # largest heading change of a worm per cell step (radius about 2 m on 0.25 m cells)
PURPOSES = dict(store=("crate", "boxes", "crate", "bucket", "toolbox"),
                workshop=("workbench", "toolbox", "stool", "bucket", "cart"),
                refuge=("locker", "bench", "bin", "crate"),
                pumps=("equipment_rack", "console", "bucket", "crate"))
OFFICE = ("table_set", "table_set", "workstation", "locker", "shelving", "equipment_rack")   # rectangular rooms
FREE = {"table_set"}   # placed anywhere on the floor; everything else stands with its back to the wall


def clearance():
    """(half-width, height) the reference robot needs to drive through ([tunnel.robot] in config/tunnel.toml)."""
    r = settings.current()["tunnel"]["robot"]
    return r["width"] / 2 + r["margin"], r["height"] + r["margin"]


def _least(cell):
    """Smallest half-width of a gallery: the robot's half-width, half a cell diagonal (grid), the bulge of a body of
    the robot's length on the tightest bend (radius cell / TURN), and 5 cm for path chords and contact precision."""
    r, (half, _) = settings.current()["tunnel"]["robot"], clearance()
    bend, reach = cell / TURN, r["length"] / 2 + r["margin"]
    return half + cell * .71 + bend - math.sqrt(bend * bend - reach * reach) + .05


@dataclass(frozen=True)
class TunnelConfig:
    """Fields defaulting to None are drawn from the seed within config/tunnel.toml; explicit arguments are kept."""
    seed: int = 7
    rooms: int = None
    extent: float = None
    roof: bool = False
    furnished: bool = True
    steps: bool = True        # False: level floors, no steps and no terracing
    levels: int = None        # chamber levels 1-3 (default: config/tunnel.toml); 2-3: ramps, galleries over galleries

    def __post_init__(self):
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        rng, e = random.Random(f"{self.seed}:tunnel_envelope"), settings.current()["tunnel"]["envelope"]
        draw = dict(rooms=rng.randint(*e["rooms"]), extent=round(rng.uniform(*e["extent"]), 1))
        for name, value in draw.items():  # drawn in a fixed order: an explicit field never shifts the others
            if getattr(self, name) is None:
                object.__setattr__(self, name, value)
        if self.levels is None:
            object.__setattr__(self, "levels", settings.current()["tunnel"]["rules"]["levels"])
        if self.levels not in (1, 2, 3):
            raise ValueError("levels must be 1, 2 or 3")
        if any(type(v) is not bool for v in (self.roof, self.furnished, self.steps)):
            raise ValueError("roof, furnished and steps must be booleans")
        if not (2 <= self.rooms <= 40 and 15 <= self.extent <= 200):
            raise ValueError("rooms must be 2-40 and extent 15-200 m")
        e = settings.current()["tunnel"]["envelope"]
        if not (e["tunnel_width"][0] >= .8 and e["tunnel_height"][0] >= HEADROOM + .1 and e["room_radius"][0] >= 1):
            raise ValueError(f"tunnel.envelope: tunnel_width >= 0.8 m, tunnel_height >= {HEADROOM + .1} m, room_radius >= 1 m")


def _grid(c, rules):
    """Cell size, cells per side and cell-centre coordinate of an index."""
    cell = rules["cell"]
    return cell, int(round(c.extent / cell))


def _chambers(c, rng, e, fixed=(), keep_out=None):
    """Chambers [(centre, discs [(x, y, r)], clear height, rect or None)], each with its own size and well apart.

    The first chamber (placed at random like the others) and one in ten of the rest are rectangular rooms
    (rect [x0, y0, x1, y1], 6-10 x 5-8 m, at least 3 m high); their single disc is the half-diagonal, for spacing.
    fixed: chambers placed beforehand (tunnel_levels.py: stair landings), kept first; the others stay 4 m clear of them
    and their discs 1.5 m clear of the points keep_out (array (k, 2): stair shafts); with keep_out the first chamber
    is rectangular only if it fits in the first 3/4 of the tries.
    """
    rooms = list(fixed)
    for attempt in range(c.rooms * 200):
        if len(rooms) == c.rooms + len(fixed):
            break
        radius, room_height = rng.uniform(*e["room_radius"]), rng.uniform(*e["room_height"])
        square = (len(rooms) == len(fixed) and (keep_out is None or attempt < c.rooms * 150)) or rng.random() < .1
        if square:
            w, d = rng.uniform(6, 10), rng.uniform(5, 8)
            radius, room_height = math.hypot(w, d) / 2, max(room_height, 3.)
        margin = 2 * radius + 2
        x, y = rng.uniform(margin, c.extent - margin), rng.uniform(margin, c.extent - margin)
        if all(math.dist((x, y), r[0]) > (1.6 * (radius + r[1][0][2]) + 8 if k >= len(fixed) else radius + r[1][0][2] + 4)
               for k, r in enumerate(rooms)) and \
                (keep_out is None or np.hypot(*(keep_out - (x, y)).T).min() > radius + 1.5):   # far apart: long tunnels
            discs, rect = [(x, y, radius)], [x - w / 2, y - d / 2, x + w / 2, y + d / 2] if square else None
            for _ in range(0 if square else rng.randint(1, 3)):
                a, d = rng.uniform(0, 2 * math.pi), rng.uniform(.4, .9) * radius
                discs.append((x + d * math.cos(a), y + d * math.sin(a), radius * rng.uniform(.5, .8)))
            if keep_out is not None and any(np.hypot(*(keep_out - (u, v)).T).min() <= q + 1.5 for u, v, q in discs):
                continue
            rooms.append(((x, y), discs, room_height, rect))
    if len(rooms) - len(fixed) < 2:
        raise ValueError("extent too small for the chambers")
    return rooms


def _network(rooms, rng, rules):
    """Tunnel edges: a minimum spanning tree, then extra edges between chambers that are not kept as dead ends."""
    n, inside, edges = len(rooms), {0}, []
    while len(inside) < n:
        a, b = min(((i, j) for i in inside for j in range(n) if j not in inside),
                   key=lambda e: math.dist(rooms[e[0]][0], rooms[e[1]][0]))
        edges.append((a, b))
        inside.add(b)
    degree = [sum(i in e for e in edges) for i in range(n)]
    leaves = [i for i in range(n) if degree[i] == 1]
    rng.shuffle(leaves)
    dead = set(leaves[:max(1, round(rules["dead_end_share"] * n))])
    for i in range(n):
        if i in dead or rng.random() > rules["loop_probability"] and degree[i] > 1:
            continue
        options = sorted((j for j in range(n) if j != i and j not in dead and (i, j) not in edges and (j, i) not in edges),
                         key=lambda j: math.dist(rooms[i][0], rooms[j][0]))
        if options:
            edges.append((i, options[0]))
            degree[i] += 1
            degree[options[0]] += 1
    return edges, dead


def _blocked(region, x, y, r, cell, avoid):
    """True if a cell within r + 1 m of (x, y) is dug by an owner (chamber index or 1000 + gallery) not in `avoid`."""
    n, reach = 0 if region is None else region.shape[0], r + 1.
    i0, i1 = max(0, int((x - reach) / cell)), min(n, int((x + reach) / cell) + 1)
    j0, j1 = max(0, int((y - reach) / cell)), min(n, int((y + reach) / cell) + 1)
    if region is None:
        return False
    found = set(np.unique(region[i0:i1, j0:j1]).tolist()) - {-1}
    return bool(found - set(avoid))


def _worm(a, b, width, rng, cell, extent, region=None, own=(), ends=(), need=0.):
    """Centreline samples (x, y, half-width) from a to b: smooth wander, homing in on b in its last 8 m, turning at most
    TURN per step, steering around galleries and chambers already dug (region; owners in `own` excepted, and those in
    `ends` only while homing in), so galleries stay apart unless they are meant to meet. Half-widths only widen
    (+0-18 %) and never drop below _least; a worm that cannot reach b finishes straight (never a jump through rock).
    region may be a callable blocked(x, y, r, avoid, s, samples so far) (tunnel_levels.py: depth-aware, own trail); `need`: length the worm must
    reach before it homes in (a ramp wanders until it is long enough for its grade)."""
    least = _least(cell)
    keep = width / 2 * 1.18 + 2 * cell + least                          # stay inside the map's rock rim
    b = (min(extent - keep, max(keep, b[0])), min(extent - keep, max(keep, b[1])))
    phase, freq = [rng.uniform(0, 2 * math.pi) for _ in range(3)], [rng.uniform(.08, .25) for _ in range(3)]
    (x, y), heading = a, math.atan2(b[1] - a[1], b[0] - a[0])
    samples, s, step = [], 0., cell
    # Cells marked 4000-4999 (tunnel_levels.py: stair shafts) are never dug: the target moves out of them and a worm
    # that would still cross one is replaced by a grid route round it.
    shaft = None if region is None or callable(region) else (region >= 4000) & (region < 5000)
    if shaft is not None and shaft.any():
        b = _clear_target(a, b, _inflate(shaft, width / 2 * 1.18, cell), cell)
    for _ in range(int(max(4 * math.dist(a, b), 2 * need) / step) + 10):
        samples.append((x, y, max(least, width / 2 * (1.09 + .09 * math.sin(freq[2] * 3 * s + phase[2])))))
        left = math.dist((x, y), b)
        if left < step:
            break
        wander = sum(math.sin(f * s + p) for f, p in zip(freq[:2], phase[:2]))     # -2..2, smooth along s
        homing = left <= 8 and s + left >= need
        turn = (.35 if homing else .05) * math.remainder(math.atan2(b[1] - y, b[0] - x) - heading, 2 * math.pi) + \
            .05 * wander * min(1., left / 8)
        if s > 4 and left > 4:
            avoid, r = set(own) | (set(ends) if homing else set()), samples[-1][2]
            blocked = region if callable(region) else lambda px, py, pr, av, *_: _blocked(region, px, py, pr, cell, av)
            ahead = lambda t: not (keep <= x + (r + 1.2) * math.cos(t) <= extent - keep and keep <= y + (r + 1.2) * math.sin(t) <= extent - keep) \
                or blocked(x + (r + 1.2) * math.cos(t), y + (r + 1.2) * math.sin(t), r, avoid, s, samples)   # the map rim too
            if ahead(heading + turn):
                turn = next((d for d in (.5, -.5, 1., -1., 1.5, -1.5) if not ahead(heading + d)), turn)
        heading += max(-TURN, min(TURN, turn))
        x, y, s = x + step * math.cos(heading), y + step * math.sin(heading), s + step
        x, y = min(extent - keep, max(keep, x)), min(extent - keep, max(keep, y))
    _tail(samples, b, least, width, step)
    if shaft is not None and shaft.any():
        samples = _round_shafts(a, b, samples, shaft, max(least, width / 2), math.ceil(keep / cell), cell)
    return samples


def _clear_target(a, b, wall, cell):
    """b pulled back towards a (5 % a step, 200 steps at most) until it leaves `wall` (a stair shaft and its clearance:
    a drift's random end may fall in one)."""
    for _ in range(200):
        if not wall[int(b[0] / cell), int(b[1] / cell)] or math.dist(a, b) < 1:
            break
        b = (b[0] + (a[0] - b[0]) * .05, b[1] + (a[1] - b[1]) * .05)
    return b


def _tail(samples, b, least, width, step):
    """Finish the worm straight to b at the least width (never a jump through rock), after dropping the samples
    that would make a hairpin where the straight tail starts (the robot could not turn in it)."""
    while len(samples) > 2 and math.dist(samples[-1][:2], b) >= step:
        (x0, y0, _), (x1, y1, _) = samples[-2], samples[-1]
        if abs(math.remainder(math.atan2(b[1] - y1, b[0] - x1) - math.atan2(y1 - y0, x1 - x0), 2 * math.pi)) <= .8:
            break
        samples.pop()
    x, y = samples[-1][:2]
    gap, k = math.dist((x, y), b), max(1, int(math.dist((x, y), b) / step))
    samples += [(x + (b[0] - x) * t / k, y + (b[1] - y) * t / k, least) for t in range(1, k + 1)] if gap >= step else \
        [(*b, max(least, width / 2))]


def _round_shafts(a, b, samples, shaft, r, rim, cell):
    """The wander only looks 2 m ahead: a worm that would still dig into a stair shaft is replaced by a grid route
    round it (`rim` cells of rock kept at the map's edge, as the wander does), r + 0.4 m wide for the robot's corners
    on the route's bends; a target walled in between a shaft and the rim is brought closer to a (75 %, 50 %, 25 % of
    the way) until a route exists."""
    wall = _inflate(shaft, max(r for *_, r in samples) + .3, cell)
    if not any(wall[int(px / cell), int(py / cell)] for px, py, _ in samples):
        return samples
    wall[:rim, :] = wall[-rim:, :] = wall[:, :rim] = wall[:, -rim:] = True
    for shrink in (1., .75, .5, .25):
        route = _around(a, (a[0] + (b[0] - a[0]) * shrink, a[1] + (b[1] - a[1]) * shrink), wall, shaft, r + .4, cell)
        if route:
            return route
    return samples


def _inflate(mask, r, cell):
    """mask grown by r (+ one cell): the cells a disc of radius r centred there would reach into mask."""
    k = math.ceil(r / cell) + 1
    out, (n, m) = mask.copy(), mask.shape
    for di in range(-k, k + 1):
        for dj in range(-k, k + 1):
            if di * di + dj * dj <= k * k:
                out[max(0, di):n + min(0, di), max(0, dj):m + min(0, dj)] |= mask[max(0, -di):n + min(0, -di), max(0, -dj):m + min(0, -dj)]
    return out


def _around(a, b, wall, core, r, cell):
    """Centreline samples (x, y, r) of a shortest 8-connected grid route from a to b outside `wall`, or None if there is
    none. Within 1.2 m of a or b (a landing chamber next to its shaft) only `core` (the shaft itself) is avoided. ponytail: plain BFS on the 0.25 m grid, ~0.05 s per route."""
    from collections import deque
    n = wall.shape[0]
    start, goal = (int(a[0] / cell), int(a[1] / cell)), (int(b[0] / cell), int(b[1] / cell))
    came, todo = {start: None}, deque([start])
    near = lambda q: min(math.dist(q, start), math.dist(q, goal)) * cell <= 1.2
    while todo:
        i, j = todo.popleft()
        if (i, j) == goal:
            break
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            q = (i + di, j + dj)
            if q not in came and 0 < q[0] < n - 1 and 0 < q[1] < n - 1 and not core[q] and (not wall[q] or near(q)):
                came[q] = (i, j)
                todo.append(q)
    if goal not in came:
        return None
    route, q = [], goal
    while q is not None:
        route.append(((q[0] + .5) * cell, (q[1] + .5) * cell, r))
        q = came[q]
    route = [(*a, r)] + route[::-1][1:-1] + [(*b, r)]
    k = 4   # rounded kinks: each centre averaged over 9 cells (ends kept)
    return route[:k] + [(sum(q[0] for q in route[i - k:i + k + 1]) / (2 * k + 1), sum(q[1] for q in route[i - k:i + k + 1]) / (2 * k + 1), r)
                        for i in range(k, len(route) - k)] + route[max(k, len(route) - k):]


def _branch(worms, rng, low=.25, high=.75):
    """(endpoint code, point, height) of a seeded point in the middle part of a seeded existing tunnel."""
    t = rng.randrange(len(worms))
    samples = worms[t][2]
    x, y, _ = samples[int(rng.uniform(low, high) * (len(samples) - 1))]
    return -(t + 1), (x, y), worms[t][3]


def _door(room, towards):
    """Where a tunnel meets a chamber: its centre, or for a rectangular room a doorway in the wall facing `towards`
    (0.3 m inside), so tunnels do not cross the room and its floor stays free for tables."""
    (x, y), _, _, rect = room
    if not rect:
        return x, y
    dx, dy = towards[0] - x, towards[1] - y
    if abs(dx) * (rect[3] - rect[1]) > abs(dy) * (rect[2] - rect[0]):     # leaves through an x wall
        return (rect[2] - .3 if dx > 0 else rect[0] + .3), min(rect[3] - 1.5, max(rect[1] + 1.5, y + dy * (rect[2] - rect[0]) / 2 / abs(dx)))
    return min(rect[2] - 1.5, max(rect[0] + 1.5, x + dx * (rect[3] - rect[1]) / 2 / abs(dy))), (rect[3] - .3 if dy > 0 else rect[1] + .3)


def _carve(rooms, cell, n):
    """Per cell: region (-1 rock, chamber index, later 1000 + gallery index), clear height, cell-centre grids X, Y."""
    region, height = np.full((n, n), -1), np.zeros((n, n))
    centre = (np.arange(n) + .5) * cell
    X, Y = np.meshgrid(centre, centre, indexing="ij")
    for k, (_, discs, room_height, rect) in enumerate(rooms):
        mask = np.zeros((n, n), bool)
        if rect:
            mask = (X >= rect[0]) & (X <= rect[2]) & (Y >= rect[1]) & (Y <= rect[3])
        for x, y, r in discs if not rect else ():
            mask |= (X - x) ** 2 + (Y - y) ** 2 <= r * r
        region[mask], height[mask] = k, room_height
    return region, height, X, Y


def _dig(grid, samples, tunnel_height, owner, cell):
    """Dig a gallery's discs into the rock cells of grid = (region, height, X, Y): earlier spaces keep their cells."""
    region, height, X, Y = grid
    n = region.shape[0]
    for x, y, r in samples:
        i0, i1 = max(0, int((x - r) / cell) - 1), min(n, int((x + r) / cell) + 2)
        j0, j1 = max(0, int((y - r) / cell) - 1), min(n, int((y + r) / cell) + 2)
        mask = ((X[i0:i1, j0:j1] - x) ** 2 + (Y[i0:i1, j0:j1] - y) ** 2 <= r * r) & (region[i0:i1, j0:j1] < 0)
        region[i0:i1, j0:j1][mask], height[i0:i1, j0:j1][mask] = owner, tunnel_height


def _galleries(c, rng, e, rooms, edges, dead, grid, cell):
    """Dig, in order, chamber-to-chamber galleries, links between two galleries (8-30 m apart, from their middle
    parts) and dead-end drives (from a through chamber or a gallery); each draws its own width and height (never
    above the chambers it joins) and steers around what is already dug. Returns [(a, b, samples, height)]; an endpoint
    is a chamber index or -(gallery index + 1), b is None for a drive. The map keeps a rock rim."""
    worms = []
    def dig(a, b, pa, pb, high):
        owner, target = 1000 + len(worms), () if b is None else {b if b >= 0 else 1000 - b - 1}
        samples = _worm(pa, pb, rng.uniform(*e["tunnel_width"]), rng, cell, c.extent, grid[0], {owner}, target)
        for k, end in ((0, a), (-1, b)):   # a junction with another gallery widens: a robot turning in overhangs it
            if end is not None and end < 0:
                samples[k] = (*samples[k][:2], samples[k][2] + .5)
        _dig(grid, samples, high, owner, cell)
        worms.append((a, b, samples, high))
    for a, b in edges:
        dig(a, b, _door(rooms[a], rooms[b][0]), _door(rooms[b], rooms[a][0]),
            min(rng.uniform(*e["tunnel_height"]), rooms[a][2], rooms[b][2]))
    wanted = rng.randint(*e["links"])
    for _ in range(wanted * 20):
        if wanted == 0 or len(worms) < 2:
            break
        (a, pa, ha), (b, pb, hb) = _branch(worms, rng), _branch(worms, rng)
        if a != b and 8 <= math.dist(pa, pb) <= 30:
            dig(a, b, pa, pb, min(ha, hb, rng.uniform(*e["tunnel_height"])))
            wanted -= 1
    through = [k for k in range(len(rooms)) if k not in dead and not rooms[k][3]] or [0]
    for _ in range(rng.randint(*e["drifts"])):
        if rng.random() < .5:
            k = rng.choice(through)
            start, roof = rooms[k][0], rooms[k][2]
        else:
            k, start, roof = _branch(worms, rng)
        a, length = rng.uniform(0, 2 * math.pi), rng.uniform(*e["drift_length"])
        dig(k, None, start, (start[0] + length * math.cos(a), start[1] + length * math.sin(a)), min(roof, rng.uniform(*e["tunnel_height"])))
    region = grid[0]
    region[[0, -1], :], region[:, [0, -1]] = -1, -1   # a rock rim all round
    return worms


def _floor(c, rng, rules, X, Y):
    """Floor height: smooth relief (slope <= max_grade) plus lines of steps, terraced in floor_quantum; 0 without steps."""
    z, grade = np.zeros_like(X), rules["max_grade"] / 3
    if not c.steps:
        return z, []
    for _ in range(3):
        a, wavelength = rng.uniform(0, math.pi), c.extent * rng.uniform(.7, 1.5)
        amplitude = grade * wavelength / (2 * math.pi)
        z += amplitude * np.sin(2 * math.pi * (X * math.cos(a) + Y * math.sin(a)) / wavelength + rng.uniform(0, 2 * math.pi))
    # Step lines are parallel (one seeded direction) with 0.5 m between their flights: two crossing flights would add
    # their risers into one step.
    lines, a = [], rng.uniform(0, math.pi)
    normal, run = (math.cos(a), math.sin(a)), 4 * rules["tread"]
    for _ in range(rng.randint(*settings.current()["tunnel"]["envelope"]["step_lines"]) * 20):
        if len(lines) == settings.current()["tunnel"]["envelope"]["step_lines"][1]:
            break
        offset = rng.uniform(0, c.extent * math.sqrt(2))
        risers, sign = rng.randint(2, 4), rng.choice((-1, 1))
        if any(abs(offset - other["offset"]) < run + .5 for other in lines):
            continue
        d = X * normal[0] + Y * normal[1] - offset
        z += sign * rules["riser"] * np.clip(np.floor(d / rules["tread"]) + 1, 0, risers)
        lines.append(dict(offset=offset, normal=list(normal), risers=risers, rise=sign * risers * rules["riser"]))
    q = rules["floor_quantum"]
    return np.round(z / q) * q, lines


def _level_rooms(rooms, rules, region, floor, ceiling, X, Y):
    """Rectangular rooms: one floor height inside (blended into the relief over 3 m around) and a flat ceiling."""
    q = rules["floor_quantum"]
    for k, ((x, y), _, room_height, rect) in enumerate(rooms):
        if rect:
            i, j = np.unravel_index(np.argmin((X - x) ** 2 + (Y - y) ** 2), X.shape)
            z = float(floor[i, j])
            outside = np.hypot(np.maximum(0, np.maximum(rect[0] - X, X - rect[2])), np.maximum(0, np.maximum(rect[1] - Y, Y - rect[3])))
            t = np.clip(1 - outside / 3, 0, 1)
            floor[:] = np.round((floor + (z - floor) * t) / q) * q
            ceiling[region == k] = math.ceil((z + room_height) * 4) / 4


def _rectangles(key):
    """Greedy merge of equal, non-None cells of a 2D object array into (i0, j0, i1, j1, key) rectangles."""
    n0, n1 = key.shape
    done, out = np.zeros(key.shape, bool), []
    for i in range(n0):
        for j in range(n1):
            k = key[i, j]
            if k is None or done[i, j]:
                continue
            j1 = j + 1
            while j1 < n1 and not done[i, j1] and key[i, j1] == k:
                j1 += 1
            i1 = i + 1
            while i1 < n0 and all(not done[i1, jj] and key[i1, jj] == k for jj in range(j, j1)):
                i1 += 1
            done[i:i1, j:j1] = True
            out.append((i, j, i1, j1, k))
    return out


def _shell(scene, c, region, floor, ceiling, cell, built, level=0, no_floor=(), no_ceiling=()):
    """Floor slabs, ceiling slabs (roof) and wall columns, merged into rectangles of equal heights and finish.

    built: indices of the rectangular rooms, whose floors and walls are concrete instead of rock. level: tag of every
    part; no_floor / no_ceiling: dug cells left without floor slab / ceiling (tunnel_levels.py: stair shafts).
    """
    n = region.shape[0]
    carved, made = region >= 0, np.isin(region, list(built))
    floors, ceilings, walls = (np.full((n, n), None, object) for _ in range(3))
    # With a roof, a cell's ceiling slab rises to its neighbours' highest ceiling (+ slab): where a low gallery meets
    # a higher one or a chamber, the step in the ceiling is closed instead of open to the sky.
    over = np.where(carved, ceiling, -np.inf)
    padded = np.pad(over, 1, constant_values=-np.inf)
    top = np.max([padded[1 + di:n + 1 + di, 1 + dj:n + 1 + dj] for di in (-1, 0, 1) for dj in (-1, 0, 1)], axis=0)
    for i, j in zip(*np.nonzero(carved)):
        if (i, j) not in no_floor:
            floors[i, j] = (round(float(floor[i, j]), 3), bool(made[i, j]))
        if (i, j) not in no_ceiling:
            ceilings[i, j] = (round(float(ceiling[i, j]), 3), round(float(top[i, j]) + SLAB, 3), bool(made[i, j]))
    for i, j in zip(*np.nonzero(~carved)):
        near = [(a, b) for a in range(max(0, i - 1), min(n, i + 2)) for b in range(max(0, j - 1), min(n, j + 2)) if carved[a, b]]
        if near:
            lo = min(floor[a, b] for a, b in near) - SLAB
            hi = max(ceiling[a, b] for a, b in near) + (SLAB if c.roof else 0.)
            walls[i, j] = (math.floor(lo * 2) / 2, math.ceil(hi * 2) / 2, any(made[a, b] for a, b in near))
    rock = dict(style="rock", seed=c.seed, period=2., label="", rev=2)
    concrete = dict(style="concrete", seed=c.seed, period=1.2, label="", rev=2)
    def emit(kind, rect, z0, z1, color, finished):
        i0, j0, i1, j1 = rect
        b = dict(kind=kind, size=[(i1 - i0) * cell, (j1 - j0) * cell, z1 - z0], center=[(i0 + i1) * cell / 2, (j0 + j1) * cell / 2,
                 (z0 + z1) / 2], level=level, material="floor" if kind == "floor" else "wall",
                 color=list(CONCRETE if finished else color), texture=concrete if finished else rock)
        if kind == "floor":
            b["collision_size"] = [b["size"][0] + .002, b["size"][1] + .002, b["size"][2]]
        scene["boxes"].append(b)
    for *rect, (z, finished) in _rectangles(floors):
        emit("floor", rect, z - SLAB, z, FLOOR, finished)
    for *rect, (z0, z1, finished) in _rectangles(walls):
        emit("wall", rect, z0, z1, ROCK, finished)
    if c.roof:
        for *rect, (z, z1, finished) in _rectangles(ceilings):
            emit("ceiling", rect, z, z1, ROCK, finished)


def _plan(scene, c, rooms, dead, worms, region, floor, cell, base=0, level=0):
    """Spaces (chambers and tunnels), portals where a tunnel leaves a chamber, and clear paths along the worms.
    base: space id of this level's first chamber; level: its storey index (tunnel_levels.py)."""
    n = region.shape[0]
    def z_at(x, y):
        return float(floor[min(n - 1, int(x / cell)), min(n - 1, int(y / cell))])
    for k, ((x, y), discs, room_height, square) in enumerate(rooms):
        rect = square or [min(d[0] - d[2] for d in discs), min(d[1] - d[2] for d in discs), max(d[0] + d[2] for d in discs),
                          max(d[1] + d[2] for d in discs)]
        scene["spaces"].append(dict(id=base + k, kind="room" if square else "chamber", level=level, rect=rect, floor_z=z_at(x, y),
                                    traversable=True, dead_end=k in dead, center=[x, y], radius=discs[0][2],
                                    height=round(room_height, 2)))
    first = base + len(rooms)    # space id of tunnel t is first + t; an endpoint -(t + 1) is tunnel t
    for t, (a, b, samples, tunnel_height) in enumerate(worms):
        xs, ys = [s[0] for s in samples], [s[1] for s in samples]
        ident = len(scene["spaces"])
        ends = [e for e in (a, b) if e is not None]
        scene["spaces"].append(dict(id=ident, kind="tunnel", level=level, rect=[min(xs), min(ys), max(xs), max(ys)],
                                    floor_z=z_at(xs[0], ys[0]), traversable=True, rooms=[base + e for e in ends if e >= 0],
                                    joins=[first - e - 1 for e in ends if e < 0], dead_end=b is None,
                                    width=round(2 * float(np.median([s[2] for s in samples])), 2), height=round(tunnel_height, 2)))
        for e, path in ((a, samples), (b, samples[::-1])):
            if e is None:
                continue
            code = e if e >= 0 else 1000 - e - 1    # region value of that chamber or tunnel
            exit_ = next((s for s in path if region[min(n - 1, int(s[0] / cell)), min(n - 1, int(s[1] / cell))] != code), path[-1])
            scene["portals"].append(dict(rooms=[base + e if e >= 0 else first - e - 1, ident], center=[exit_[0], exit_[1], z_at(*exit_[:2])],
                                         axis=0, width=2 * min(s[2] for s in samples), height=tunnel_height))
        points = samples[::2] + [samples[-1]]   # 0.5 m chords: within 2 cm of the centreline on the tightest bend
        scene["clear_paths"].append(dict(room=ident, width=round(2 * min(s[2] for s in samples) - .3, 2),
                                         points=[[s[0], s[1], z_at(s[0], s[1])] for s in points]))


def _timber(scene, c, worms, region, floor, ceiling, cell, extra_paths=(), level=0):
    """Timber sets (two posts and a cap) across the tunnels, every 4-6 m where the section is regular. A post stands
    at least _least + 0.1 m (the robot's half-width, its bulge on a bend, a chord's sag) from every centreline (the
    tunnels' and extra_paths': stair flights), so crossing tunnels never get a post in their way, and half the robot's
    length + margin + 0.15 m from every path's ends (a robot standing at a tunnel mouth overhangs it)."""
    from metro import _quat
    n, wood = region.shape[0], material_spec("wood", c.seed)
    paths = [samples for *_, samples, _ in worms] + [list(p) for p in extra_paths]
    lines, keep = np.array([s[:2] for path in paths for s in path]), _least(cell) + .1
    robot = settings.current()["tunnel"]["robot"]
    mouths, reach = np.array([path[k][:2] for path in paths for k in (0, -1)]), robot["length"] / 2 + robot["margin"] + .15
    for _, _, samples, _ in worms:
        k = 12
        while k < len(samples) - 12:
            (x0, y0, _), (x, y, r), (x1, y1, _) = samples[k - 2], samples[k], samples[k + 2]
            heading = math.atan2(y1 - y0, x1 - x0)
            nx, ny, w = -math.sin(heading), math.cos(heading), r - .05   # posts against the rock, outside the clearance disc
            cells = [(int((x + t * nx) / cell), int((y + t * ny) / cell)) for t in np.linspace(-w, w, 7)]
            posts = [(x + side * w * nx, y + side * w * ny) for side in (-1, 1)]
            clear = all(np.min(np.hypot(*(lines - post).T)) >= keep and np.min(np.hypot(*(mouths - post).T)) >= reach for post in posts)
            if clear and all(0 <= i < n and 0 <= j < n and 1000 <= region[i, j] < 4000 for i, j in cells):
                z = max(float(floor[i, j]) for i, j in cells)
                top = min(float(ceiling[i, j]) for i, j in cells) - .05
                if top - z >= HEADROOM + .2 and max(float(floor[i, j]) for i, j in cells) - min(float(floor[i, j]) for i, j in cells) <= .1:
                    q = _quat(yaw=heading)
                    for px, py in posts:
                        post = dict(kind="trim", element="timber_post", size=[.14, .14, top - .14 - z],
                                    center=[px, py, (z + top - .14) / 2], orientation=q)
                        scene["boxes"].append(dict(post, level=level, material="wood", color=list(TIMBER), texture=wood))
                    scene["boxes"].append(dict(kind="trim", element="timber_cap", size=[.16, 2 * w + .14, .14],
                                               center=[x, y, top - .07], orientation=q, level=level, material="wood",
                                               color=list(TIMBER), texture=wood))
            k += int((4 + 2 * ((k * 2654435761) % 1000) / 1000) / cell)   # 4-6 m apart


def _object(name, rng):
    """(parts, items) of a furnishing: a metro composite or model, or a building-catalogue model."""
    from furniture import _model
    from metro import METRO_MODELS, PALETTE, _group, _metro_model
    color = rng.choice(PALETTE)
    if name == "table_set":   # as the metro staff room: two chairs along the front, one at each end
        return _group([("table", _model("table", color), 0, 0, 0)] + [("chair", _model("chair", color), x, .72, 2) for x in (-.4, .4)] +
                      [("chair", _model("chair", color), side * 1.1, 0, 1 if side > 0 else 3) for side in (1, -1)])
    if name == "workstation":
        return _group([("lab_desk", _model("lab_desk", color), 0, 0, 0), ("lab_chair", _model("lab_chair", color), 0, .66, 2)])
    return (_metro_model(name) if name in METRO_MODELS else _model(name, color)), None


def _spot(parts, i, j, turn, cell, free):
    """(x, y, local extents): free objects centred on the cell, the others with their back on its rock face."""
    from metro import _extent, _world
    local = [_extent(b) for b in _world(parts, (0, 0, 0), turn)]
    lo, hi = [min(v[a] for v in local) for a in (0, 1)], [max(v[a + 3] for v in local) for a in (0, 1)]
    x, y = (i + .5) * cell, (j + .5) * cell
    if not free:
        x = {1: (i + 1) * cell - hi[0] - .02, 3: i * cell - lo[0] + .02}.get(turn, x)
        y = {0: j * cell - lo[1] + .02, 2: (j + 1) * cell - hi[1] - .02}.get(turn, y)
    return x, y, local


def _furnish(scene, c, rng, rooms, region, floor, ceiling, cell, only=None, base=0):
    """A few objects in each chamber (tables and desks in the rectangular rooms), on a flat footprint inside the
    room, under its ceiling, clear of the paths, the spawn and each other."""
    from furniture import _crosses
    from metro import _register, _world
    n, placed = region.shape[0], []
    paths = [(a, b) for path in scene["clear_paths"] for a, b in zip(path["points"], path["points"][1:])]
    spawn, robot = scene["spawn"][:2], settings.current()["tunnel"]["robot"]
    reach = robot["length"] / 2 + robot["margin"] + .1   # a robot at a path's end sticks out half its length
    for k in range(len(rooms)) if only is None else sorted(only):
        purpose = "office" if rooms[k][3] else rng.choice(sorted(PURPOSES))
        scene["spaces"][base + k]["purpose"] = purpose
        cells = [(int(i), int(j)) for i, j in zip(*np.nonzero(region == k))]
        rng.shuffle(cells)
        wanted, tries = rng.randint(4, 7) if rooms[k][3] else rng.randint(2, 5), 0
        for i, j in cells:
            if wanted == 0 or tries > 400:
                break
            placed_here = [o["kind"] for o in scene["objects"] if o["room"] == base + k]
            name = "table_set" if rooms[k][3] and "table_set" not in placed_here and tries < 300 else \
                rng.choice(OFFICE if rooms[k][3] else PURPOSES[purpose])   # a rectangular room tries a table first
            rock = [t for t, (di, dj) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0))) if region[i + di, j + dj] < 0]
            if name not in FREE and not rock:
                continue
            tries += 1
            parts, items = _object(name, rng)
            turn = rng.randrange(4) if name in FREE else rock[0]
            x, y, local = _spot(parts, i, j, turn, cell, name in FREE)
            fp = [x + min(v[0] for v in local), y + min(v[1] for v in local), x + max(v[3] for v in local), y + max(v[4] for v in local)]
            under = [(a, b) for a in range(int(fp[0] / cell), int(fp[2] / cell) + 1) for b in range(int(fp[1] / cell), int(fp[3] / cell) + 1)]
            if any(not (0 <= a < n and 0 <= b < n) or region[a, b] != k for a, b in under):
                continue
            z = max(float(floor[a, b]) for a, b in under)
            if z - min(float(floor[a, b]) for a, b in under) > .05 or \
                    min(float(ceiling[a, b]) for a, b in under) - z < max(v[5] for v in local) + .1:
                continue
            if any(_crosses(fp, a[:2], b[:2], reach) for a, b in paths if c.levels == 1 or abs(a[2] - z) < 2.5) or \
                    _crosses(fp, spawn, spawn, 1.2) or \
                    any(fp[0] < o[2] + .1 and o[0] < fp[2] + .1 and fp[1] < o[3] + .1 and o[1] < fp[3] + .1 for o in placed):
                continue
            placed.append(fp)
            _register(scene, c, _world(parts, (x, y, z), turn), name, base + k, "floor", [x, y, z], turn, items)
            wanted -= 1


def _layer(c, rng, rules, e, cell, n, fixed=(), obstacles=()):
    """One level of the mine: chambers, galleries, floor relief and ceilings on a grid (z = 0 at the first chamber).
    fixed: chambers placed beforehand; obstacles: cells no gallery may dig (tunnel_levels.py: stair landings and
    flights). Returns (rooms, dead ends, worms, region, floor, ceiling, step lines)."""
    rooms = _chambers(c, rng, e, fixed, (np.array(sorted(obstacles)) + .5) * cell if obstacles else None)
    edges, dead = _network(rooms, rng, rules)
    region, height, X, Y = grid = _carve(rooms, cell, n)
    for i, j in obstacles:
        if region[i, j] < 0:
            region[i, j], height[i, j] = 4500, settings.current()["tunnel"]["rules"]["level_gap"] - 1.2
    worms = _galleries(c, rng, e, rooms, edges, dead, grid, cell)   # 4500: a stair shaft, dug by nobody else
    floor, step_lines = _floor(c, rng, rules, X, Y)
    ceiling = np.ceil((floor + height + .15 * np.sin(X * 1.7) * np.cos(Y * 1.3)) * 4) / 4   # blocky, 0.25 m
    _level_rooms(rooms, rules, region, floor, ceiling, X, Y)
    return rooms, dead, worms, region, floor, np.maximum(ceiling, floor + HEADROOM), step_lines


def generate_tunnel(c=None):
    """Seeded mine tunnel scene in the indoor schema (see the module docstring)."""
    c = TunnelConfig() if c is None else c
    start, rules = time.perf_counter(), settings.current()["tunnel"]["rules"]
    rng = random.Random(f"{c.seed}:tunnel")
    cell, n = _grid(c, rules)
    e = settings.current()["tunnel"]["envelope"]
    if c.levels > 1:
        from tunnel_levels import generate_levels
        return generate_levels(c, rng, rules, e, cell, n, start)
    rooms, dead, worms, region, floor, ceiling, step_lines = _layer(c, rng, rules, e, cell, n)
    scene = dict(config=dict(asdict(c), floors=1), generator=dict(name="mine_tunnels", version=1),
                 levels=[dict(level=0, name="mine", floor_z=float(floor[region >= 0].min()))], spaces=[], portals=[], stairs=[],
                 ramps=[], boxes=[], objects=[], clear_paths=[], loop_routes=[], floor_seeds=[c.seed], step_lines=step_lines)
    if settings.signature():
        scene["settings"] = settings.signature()
    # Gazebo (gazebo.collision_groups): rock, floors, ceilings and timber as one concave mesh per kind and 10 m tile,
    # about a hundred collision shapes instead of thousands of boxes.
    scene["gazebo_merge"] = dict(kinds=["floor", "wall", "ceiling", "trim"], tile=10.)
    _shell(scene, c, region, floor, ceiling, cell, {k for k, r in enumerate(rooms) if r[3]})
    _plan(scene, c, rooms, dead, worms, region, floor, cell)
    home = rng.choice([k for k in range(len(rooms)) if k not in dead] or [0])
    hx, hy = rooms[home][0]
    scene["spawn"] = [hx, hy, float(floor[int(hx / cell), int(hy / cell)]) + .55]
    if c.furnished:
        _timber(scene, c, worms, region, floor, ceiling, cell)
        _furnish(scene, c, rng, rooms, region, floor, ceiling, cell)
    return _finish(scene, c, start)


def _finish(scene, c, start):
    """Bounds, style, coplanar gaps, semantics and statistics."""
    from geometry import geometry_stats, separate_coplanar
    from metro import _annotate, _extent
    extent = [_extent(b) for b in scene["boxes"]]
    scene["bounds"] = [min(v[0] for v in extent), min(v[1] for v in extent), max(v[3] for v in extent), max(v[4] for v in extent)]
    scene["z_bounds"] = [min(v[2] for v in extent), max(v[5] for v in extent)]
    scene["style"] = dict(id="mine_tunnels", version=1, units="metres", finish="blocky_rock",
                          texture_version=__import__("surfaces").VERSION)
    separate_coplanar(scene)
    _annotate(scene)
    scene["geometry_stats"] = geometry_stats(scene)
    chambers = [s for s in scene["spaces"] if s["kind"] in ("chamber", "room")]
    scene["tunnel_stats"] = dict(parts=len(scene["boxes"]), objects=len(scene["objects"]), chambers=len(chambers),
                                 rectangular_rooms=sum(s["kind"] == "room" for s in chambers),
                                 dead_ends=sum(s["dead_end"] for s in chambers),
                                 tunnels=sum(s["kind"] == "tunnel" for s in scene["spaces"]),
                                 generation_s=round(time.perf_counter() - start, 3))
    return scene


def _parser():
    """Command-line options of tunnel.py."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--config", help="settings override: a folder like config/ or one .toml file")
    parser.add_argument("--rooms", type=int, help="Chambers per level (default: seeded, config/tunnel.toml)")
    parser.add_argument("--levels", type=int, choices=(1, 2, 3), help="Levels of galleries, joined by stair shafts (default: config)")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--roof", action="store_true", help="Close the ceilings for sensor runs")
    parser.add_argument("--empty", action="store_true", help="Rock only: no timber sets or objects")
    parser.add_argument("--no-steps", action="store_true", help="Level floors: no steps and no terracing")
    parser.add_argument("--export", help="Save backend-neutral scene JSON")
    parser.add_argument("--render", help="Save an overview PNG")
    parser.add_argument("--xray", action="store_true")
    return parser


def main(argv=None):
    """Command line: generate the tunnels, optionally export/render them, and open the PyBullet viewer."""
    import pybullet as p
    from metro import render
    from surfaces import prepare_textures
    args = _parser().parse_args(argv)
    settings.use(args.config)
    from banner import splash
    splash("seeded mine tunnels", f"seed {args.seed}" + (f", settings {args.config}" if args.config else ""))
    scene = generate_tunnel(TunnelConfig(seed=args.seed, rooms=args.rooms, levels=args.levels, roof=args.roof, furnished=not args.empty,
                                                steps=not args.no_steps))
    if args.export:
        with open(args.export, "w") as handle:
            json.dump(scene, handle, indent=1)
    stats = scene["tunnel_stats"]
    print(f"Seed {args.seed}: {stats['chambers']} chambers ({stats['dead_ends']} dead ends), {stats['tunnels']} tunnels, "
          f"{stats['parts']} parts, {stats['objects']} objects, generated in {stats['generation_s']} s; spawn={scene['spawn']}")
    prepare_textures(scene)
    cid = p.connect(p.DIRECT if args.headless else p.GUI)
    try:
        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 0, physicsClientId=cid)
        # One visual shape per part loses textures in PyBullet's OpenGL renderer (thousands of shapes): collisions per
        # part, visuals as a few merged meshes (fastload).
        from fastload import load_pybullet_merged
        bodies = load_pybullet_merged(scene, cid)
        p.setGravity(0, 0, -9.81, physicsClientId=cid)
        x0, y0, x1, y1 = scene["bounds"]
        centre = [(x0 + x1) / 2, (y0 + y1) / 2, scene["levels"][0]["floor_z"]]
        p.resetDebugVisualizerCamera(max(x1 - x0, y1 - y0) * .8, 35, -60, centre, physicsClientId=cid)
        if args.render:
            span = max(x1 - x0, y1 - y0)
            render(cid, bodies, scene, args.render, [centre[0] - .3 * span, centre[1] - .8 * span, centre[2] + 1.1 * span], centre,
                   50, None, (1400, 1000), " ".join(["python3 tunnel.py"] + (argv if argv is not None else sys.argv[1:])))
        if not args.headless:
            from viewer import Viewer
            viewer = Viewer(scene, bodies, cid, None, args.xray)
            p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 1, physicsClientId=cid)
            print("Tab: walk/orbit | T: X-ray | WASD: walk | arrows/right-drag: look")
            previous = time.perf_counter()
            while p.isConnected(cid):
                now = time.perf_counter()
                viewer.update(min(now - previous, 1 / 30))
                previous = now
                p.stepSimulation(physicsClientId=cid)
                time.sleep(1 / 240)
    except KeyboardInterrupt:
        pass
    finally:
        if p.isConnected(cid):
            p.disconnect(cid)


if __name__ == "__main__":
    main()
