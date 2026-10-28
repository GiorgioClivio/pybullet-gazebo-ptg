"""Mine tunnels on 2-3 levels (tunnel.py --levels 2|3), stacked like the storeys of a building.

Each level is a complete one-level mine (tunnel._layer, its own seed) on one shared relief lowered by `level_gap` per
level, with chambers and galleries at most level_gap - 1.2 m high, so 0.6 m of rock and two slabs stay between
levels. Consecutive levels are joined by 2-3 stair shafts, chosen first as a building's stair cores are: a straight
flight (stair_riser, stair_tread) of solid treads in an axis-aligned shaft that both levels reserve (no gallery digs
it, none crosses it), the level above without a floor over it and the level below without a ceiling under it, the
shaft walled to its full height, and a small landing chamber of each level behind its head and its foot, which that
level's galleries join like any chamber.
"""
import math
import random

import numpy as np

import settings
import tunnel as t
from tunnel import CONCRETE, HEADROOM, SLAB

LANDING = 1.6   # radius of a landing chamber
BACK = 1.2      # its centre behind the shaft's head or foot: the disc overlaps the shaft by 0.4 m (no rock cell between)
WIDTH = 2.0     # clear width of a stair shaft


def _stair_sites(c, rng, rules, field, cell, n):
    """2-3 straight stair shafts per pair of levels, chosen before the levels: head (top), direction (axis-aligned),
    foot (bottom), risers and riser (at most stair_riser, treads stair_tread) from the shared relief, at least 3 m from
    the other shafts. Returns [dict(level, top, bottom, u, risers, riser)]."""
    gap, riser_max, tread = rules["level_gap"], rules["stair_riser"], rules["stair_tread"]
    def z(p):
        return float(field[min(n - 1, int(p[0] / cell)), min(n - 1, int(p[1] / cell))])
    stairs, margin = [], 2 * LANDING + 2.
    for here in range(c.levels - 1):
        wanted, tries = rng.randint(2, 3), 0
        while sum(st["level"] == here for st in stairs) < wanted and tries < 500:
            tries += 1
            top, a = (rng.uniform(margin, c.extent - margin), rng.uniform(margin, c.extent - margin)), rng.randrange(4) * math.pi / 2
            u, run = (round(math.cos(a)), round(math.sin(a))), 11.   # axis-aligned shafts: treads and walls are plain boxes
            for _ in range(3):   # the drop depends on where the flight ends
                end = (top[0] + u[0] * run, top[1] + u[1] * run)
                risers = math.ceil((gap + z(top) - z(end)) / riser_max - 1e-9)
                run = risers * tread
            bottom = end
            if not (margin <= bottom[0] <= c.extent - margin and margin <= bottom[1] <= c.extent - margin):
                continue
            if any(_segment_gap(top, bottom, st["top"], st["bottom"]) < 2 * LANDING + 3. for st in stairs):
                continue
            stairs.append(dict(level=here, top=top, bottom=bottom, u=u, risers=risers, riser=(gap + z(top) - z(end)) / risers))
    return stairs


def _segment_gap(a, b, c_, d):
    """Smallest distance between segments a-b and c-d (sampled every 0.5 m)."""
    def points(p, q):
        k = max(1, int(math.dist(p, q) / .5))
        return [(p[0] + (q[0] - p[0]) * i / k, p[1] + (q[1] - p[1]) * i / k) for i in range(k + 1)]
    return min(math.dist(p, q) for p in points(a, b) for q in points(c_, d))


def _segment_gap(a, b, c_, d):
    """Smallest distance between segments a-b and c-d (sampled every 0.5 m)."""
    def points(p, q):
        k = max(1, int(math.dist(p, q) / .5))
        return [(p[0] + (q[0] - p[0]) * i / k, p[1] + (q[1] - p[1]) * i / k) for i in range(k + 1)]
    return min(math.dist(p, q) for p in points(a, b) for q in points(c_, d))


def _shaft(stair, cell, n):
    """Cells {(i, j): s} of a stair shaft (s: distance from the head along the flight)."""
    (tx, ty), (ux, uy), run = stair["top"], stair["u"], stair["risers"] * settings.current()["tunnel"]["rules"]["stair_tread"]
    cells = {}
    for i in range(1, n - 1):
        for j in range(1, n - 1):
            x, y = (i + .5) * cell - tx, (j + .5) * cell - ty
            s = x * ux + y * uy
            if 0 <= s <= run and abs(x * uy - y * ux) <= WIDTH / 2:
                cells[i, j] = s
    return cells


def _flight_parts(scene, stair, floors, rules, cell, gap):
    """Solid treads (one box each, from under the lower floor to the tread) and the shaft's side walls and end walls,
    full height between the two levels."""
    (tx, ty), (ux, uy), here = stair["top"], stair["u"], stair["level"]
    tread, risers, riser = rules["stair_tread"], stair["risers"], stair["riser"]
    z_up = float(floors[here][int(tx / cell), int(ty / cell)])
    z_low = z_up - risers * riser
    cap = gap - 1.2
    concrete = dict(style="concrete", seed=scene["config"]["seed"], period=1.2, label="", rev=2)
    def box(kind, along, across, z0, z1, s0, s1, w0, w1):
        cx, cy = tx + ux * (s0 + s1) / 2 + uy * (w0 + w1) / 2, ty + uy * (s0 + s1) / 2 - ux * (w0 + w1) / 2
        size = [abs(ux) * (s1 - s0) + abs(uy) * (w1 - w0), abs(uy) * (s1 - s0) + abs(ux) * (w1 - w0), z1 - z0]
        scene["boxes"].append(dict(kind=kind, element=along, size=size, center=[cx, cy, (z0 + z1) / 2], level=here + (kind == "floor"),
                                   material="floor" if kind == "floor" else "wall", color=list(CONCRETE), texture=concrete))
    box("floor", "tread", 0, z_low - SLAB, z_up, -.3, 0., -WIDTH / 2, WIDTH / 2)   # the head: the upper floor stops on whole cells
    for k in range(1, risers + 1):
        box("floor", "tread", 0, z_low - SLAB, z_up - k * riser, (k - 1) * tread, k * tread + .01, -WIDTH / 2, WIDTH / 2)   # 1 cm overlap: no seam
    run = risers * tread
    for side in (-1, 1):   # side walls, full height
        box("wall", "shaft_wall", 0, z_low - SLAB, z_up + cap + SLAB, 0., run, side * WIDTH / 2 if side > 0 else -WIDTH / 2 - .25,
            WIDTH / 2 + .25 if side > 0 else -WIDTH / 2)
    box("wall", "shaft_wall", 0, z_low + cap, z_up - SLAB, run, run + .25, -WIDTH / 2, WIDTH / 2)   # above the foot landing
    return z_up, z_low


def _points(stair, z_up, z_low, rules):
    """Clear path: landing chamber behind the head, down the flight (tread tops), landing chamber behind the foot."""
    (tx, ty), (ux, uy) = stair["top"], stair["u"]
    tread, risers, riser = rules["stair_tread"], stair["risers"], stair["riser"]
    run = risers * tread
    path = [(tx - ux * BACK, ty - uy * BACK, z_up), (tx, ty, z_up)]
    path += [(tx + ux * (k - .5) * tread, ty + uy * (k - .5) * tread, z_up - k * riser) for k in range(1, risers + 1)]
    return path + [(tx + ux * run, ty + uy * run, z_low), (tx + ux * (run + BACK), ty + uy * (run + BACK), z_low)]


def _plan_stairs(scene, stairs, bases, landings):
    """A space, two portals (its landing chambers) and a clear path per staircase, and its record in scene["stairs"]."""
    tread = settings.current()["tunnel"]["rules"]["stair_tread"]
    for k, stair in enumerate(stairs):
        here, points = stair["level"], stair["points"]
        ident = len(scene["spaces"])
        xs, ys = [v[0] for v in points], [v[1] for v in points]
        upper, lower = bases[here] + landings[k][0], bases[here + 1] + landings[k][1]
        scene["spaces"].append(dict(id=ident, kind="stairs", level=here, rect=[min(xs), min(ys), max(xs), max(ys)],
                                    floor_z=float(points[-1][2]), traversable=True, levels=[here, here + 1], joins=[upper, lower]))
        for space, v in ((upper, points[0]), (lower, points[-1])):
            scene["portals"].append(dict(rooms=[space, ident], center=list(v), axis=0, width=2 * t._least(.25), height=HEADROOM))
        scene["clear_paths"].append(dict(room=ident, width=round(2 * t._least(.25) - .3, 2), points=[list(v) for v in points]))
        scene["stairs"].append(dict(space=ident, levels=[here, here + 1], start=list(points[0]), end=list(points[-1]),
                                    risers=stair["risers"], riser=round(stair["riser"], 3), tread=tread))


def _connect(layer, head, back_dir, rng, e, cell, extent, reserved, cap):
    """Dig a landing chamber BACK behind a shaft's head or foot and a gallery from its back door to the nearest point
    of the level's galleries (those behind the landing first), round every shaft. Returns the landing's room index,
    or None if no gallery could be reached without crossing a shaft."""
    (hx, hy), (ux, uy), region, floor, ceiling = head, back_dir, layer["region"], layer["floor"], layer["ceiling"]
    x, y = hx + ux * BACK, hy + uy * BACK
    door = (hx + ux * (BACK + LANDING - .25), hy + uy * (BACK + LANDING - .25))
    room, owner, worms = len(layer["rooms"]), 1000 + len(layer["worms"]), layer["worms"]
    disc = [(i, j) for i in range(int((x - LANDING) / cell), int((x + LANDING) / cell) + 1)
            for j in range(int((y - LANDING) / cell), int((y + LANDING) / cell) + 1)
            if ((i + .5) * cell - x) ** 2 + ((j + .5) * cell - y) ** 2 <= LANDING ** 2 and region[i, j] < 0]
    seen = region.copy()
    seen[tuple(np.array(sorted(reserved)).T)] = 4500
    seen[tuple(np.array(disc).T)] = room
    ahead = lambda px, py: (px - hx) * ux + (py - hy) * uy < 0   # beyond the head: the shaft is in the way
    targets = sorted(((math.dist(door, w[2][k][:2]) + (40 if ahead(*w[2][k][:2]) else 0), ti, k)
                      for ti, w in enumerate(worms) for k in range(2, len(w[2]) - 2, 2)))
    for _, ti, k in targets[:6]:
        target = worms[ti][2][k][:2]
        width, high = rng.uniform(*e["tunnel_width"]), min(rng.uniform(*e["tunnel_height"]), cap)
        samples = t._worm(door, target, width, rng, cell, extent, seen, {owner, room}, {1000 + ti})
        if not any((int(px / cell), int(py / cell)) in reserved for px, py, _ in samples):
            break
    else:
        return None
    for i, j in disc:
        region[i, j], ceiling[i, j] = room, floor[i, j] + 2.6
    for px, py, r in samples:
        for i in range(max(1, int((px - r) / cell)), int((px + r) / cell) + 1):
            for j in range(max(1, int((py - r) / cell)), int((py + r) / cell) + 1):
                if region[i, j] < 0 and (i, j) not in reserved and ((i + .5) * cell - px) ** 2 + ((j + .5) * cell - py) ** 2 <= r * r:
                    region[i, j], ceiling[i, j] = owner, floor[i, j] + high
    layer["rooms"].append(((x, y), [(x, y, LANDING)], 2.6, None))
    worms.append((room, -(ti + 1), [(x, y, LANDING)] + samples, high))   # the path starts at the landing's centre
    return room


def generate_levels(c, rng, rules, e, cell, n, start):
    """tunnel.generate_tunnel for c.levels > 1 (module docstring)."""
    gap = rules["level_gap"]
    centre = (np.arange(n) + .5) * cell
    X, Y = np.meshgrid(centre, centre, indexing="ij")
    field, _ = t._floor(c, random.Random(f"{c.seed}:tunnel_field"), rules, X, Y)   # one relief for every level
    stairs = _stair_sites(c, rng, rules, field, cell, n)
    shafts = [_shaft(st, cell, n) for st in stairs]
    layers, landings = [], [[None, None] for _ in stairs]
    for here in range(c.levels):
        mine = [k for k, st in enumerate(stairs) if here in (st["level"], st["level"] + 1)]
        shaft_cells = {k for s in mine for k in shafts[s]}
        # The shaft and 2 cells of rock round it (its walls): no gallery digs or crosses them.
        reserved = {(i + di, j + dj) for i, j in shaft_cells for di in range(-2, 3) for dj in range(-2, 3)}
        rooms, dead, worms, region, floor, ceiling, _ = t._layer(c, rng if here == 0 else random.Random(f"{c.seed}:tunnel:{here}"),
                                                                 rules, e, cell, n, (), reserved)
        ring = reserved - shaft_cells
        region[tuple(np.array(sorted(ring)).T)] = np.where(region[tuple(np.array(sorted(ring)).T)] == 4500, -1,
                                                           region[tuple(np.array(sorted(ring)).T)]) if ring else None
        layer = dict(rooms=rooms, dead=dead, worms=worms, region=region, floor=floor, ceiling=ceiling, rooms_own=len(rooms),
                     no_floor={k for s in mine if stairs[s]["level"] == here for k in shafts[s]},
                     no_ceiling={k for s in mine if stairs[s]["level"] + 1 == here for k in shafts[s]})
        for k in mine:
            st = stairs[k]
            side = 0 if st["level"] == here else 1   # landing behind the head (side 0) or the foot (side 1)
            head, sign = (st["top"], st["bottom"])[side], (-1, 1)[side]
            landings[k][side] = _connect(layer, head, (st["u"][0] * sign, st["u"][1] * sign), rng, e, cell, c.extent, reserved, gap - 1.2)
            if landings[k][side] is None:
                raise ValueError(f"seed {c.seed}: no gallery reachable from a landing on level {here}")
        height = ceiling - floor
        floor = field.copy()
        t._level_rooms(rooms, rules, region, floor, np.zeros_like(floor), X, Y)   # this level's rectangular rooms
        floor -= here * gap
        layer["floor"], layer["ceiling"] = floor, np.clip(np.ceil((floor + height) * 4) / 4, floor + HEADROOM, floor + gap - 1.2)
        layers.append(layer)
    return _assemble(c, rng, rules, layers, stairs, landings, cell, start)


def _assemble(c, rng, rules, layers, stairs, landings, cell, start):
    """The scene: each level's shell (its level tag), the shafts, spaces, stairs, spawn, timber, objects."""
    gap = rules["level_gap"]
    scene = dict(config=dict(t.asdict(c), floors=c.levels), generator=dict(name="mine_tunnels", version=1),
                 levels=[dict(level=here, name=f"level {here}", floor_z=float(layer["floor"][layer["region"] >= 0].min()))
                         for here, layer in enumerate(layers)], spaces=[], portals=[], stairs=[], ramps=[], boxes=[], objects=[],
                 clear_paths=[], loop_routes=[], floor_seeds=[c.seed], gazebo_merge=dict(kinds=["floor", "wall", "ceiling", "trim"], tile=10.))
    if settings.signature():
        scene["settings"] = settings.signature()
    for here, layer in enumerate(layers):
        t._shell(scene, c, layer["region"], layer["floor"], layer["ceiling"], cell,
                 {k for k, r in enumerate(layer["rooms"]) if r[3]}, here, layer["no_floor"], layer["no_ceiling"])
    floors = [layer["floor"] for layer in layers]
    for stair in stairs:
        z_up, z_low = _flight_parts(scene, stair, floors, rules, cell, gap)
        stair["points"] = _points(stair, z_up, z_low, rules)
    bases = []
    for here, layer in enumerate(layers):
        bases.append(len(scene["spaces"]))
        t._plan(scene, c, layer["rooms"], layer["dead"], layer["worms"], layer["region"], layer["floor"], cell, bases[-1], here)
    _plan_stairs(scene, stairs, bases, landings)
    top = layers[0]
    home = rng.choice([k for k in range(top["rooms_own"]) if k not in top["dead"]] or [0])
    hx, hy = top["rooms"][home][0]
    scene["spawn"] = [hx, hy, float(top["floor"][int(hx / cell), int(hy / cell)]) + .55]
    if c.furnished:
        flights = [stair["points"] for stair in stairs]
        for here, layer in enumerate(layers):
            t._timber(scene, c, layer["worms"], layer["region"], layer["floor"], layer["ceiling"], cell, flights, here)
            t._furnish(scene, c, rng, layer["rooms"], layer["region"], layer["floor"], layer["ceiling"], cell,
                       set(range(layer["rooms_own"])), bases[here])   # landing chambers stay clear
    scene = t._finish(scene, c, start)
    scene["tunnel_stats"]["stairs"] = len(stairs)
    return scene
