"""Seeded metric floorplans and physical models; only the loader depends on PyBullet."""
from dataclasses import asdict, dataclass
from pathlib import Path
import argparse
import json
import math
import random
import sys
import time

import settings
from styles import COLORS, PROFILE

CEILING_SKIN = .005  # plaster skin under every inter-storey slab (generate); lights mount below it


@dataclass(frozen=True)
class Config:
    """Building request; fields left at None take their value from config/building.toml (settings)."""
    seed: int = None
    rooms: int = None
    floors: int = None
    width: float = None
    depth: float = None
    min_room: float = None
    corridor: float = None
    wall: float = None
    slab: float = None
    storey: float = None
    door_width: float = None
    door_height: float = None
    window_width: float = None
    window_height: float = None
    sill: float = None
    loops: float = None
    roof: bool = None
    furnished: bool = None
    details: bool = None

    def __post_init__(self):
        for name, value in settings.current()["building"].items():
            if getattr(self, name) is None:
                object.__setattr__(self, name, value)
        if not all(math.isfinite(v) and v > 0 for k, v in asdict(self).items()
                   if k not in {"seed", "loops", "roof", "furnished", "details"}):
            raise ValueError("Dimensions and counts must be positive and finite")
        if any(type(v) is not int for v in (self.seed, self.rooms, self.floors)):
            raise ValueError("seed, rooms and floors must be integers")
        if any(type(v) is not bool for v in (self.roof, self.furnished, self.details)):
            raise ValueError("roof, furnished and details must be booleans")
        if not 1 <= self.floors <= 3 or not 0 <= self.loops <= 1:
            raise ValueError("Use 1–3 storeys and a loop probability in [0, 1]")
        if self.min_room < self.door_width + 2 * self.wall:
            raise ValueError("Rooms need room for the doorway and its jambs")
        if min(self.width, self.depth) + 1e-8 < self.min_room + self.wall:
            raise ValueError("Footprint smaller than minimum room size")
        minimum = self.min_room + self.wall
        if self.rooms > int((self.width + 1e-8) / minimum) * int((self.depth + 1e-8) / minimum):
            raise ValueError("Requested rooms do not fit; enlarge footprint or reduce rooms")
        if max(self.door_height, self.sill + self.window_height) >= self.storey - self.slab:
            raise ValueError("Openings must fit below the ceiling")
        if not 0.1 <= self.storey / math.ceil(self.storey / 0.15) <= 0.18:
            raise ValueError("Unsupported stair riser")
        if self.floors > 1 and self.depth < self.stair_length:
            raise ValueError(f"Stairwell needs depth >= {self.stair_length:.2f} m")
        if self.storey - self.slab < 2.4 or self.corridor < 1.2:
            raise ValueError("Use >=2.4 m headroom and >=1.2 m clear corridors")

    @property
    def landing(self):
        return self.corridor + self.wall

    @property
    def risers(self):
        return math.ceil(self.storey / 0.15)

    @property
    def run(self):
        return (self.risers - 1) * 0.28

    @property
    def stair_length(self):
        return 2 * self.landing + self.run


def _partition(c, rng):
    leaves, corridors = [(0., 0., c.width, c.depth)], []
    minimum = c.min_room + c.wall

    def capacity(r):
        return math.floor((r[2] - r[0] + 1e-8) / minimum) * math.floor((r[3] - r[1] + 1e-8) / minimum)

    for _ in range(c.rooms - 1):
        options = [(i, axis) for i, r in enumerate(leaves) for axis in (0, 1)
                   if r[axis + 2] - r[axis] + 1e-8 >= 2 * minimum]
        if not options:
            raise ValueError("Requested rooms do not fit; enlarge footprint or reduce rooms")
        i, axis = rng.choices(options, weights=[
            (leaves[i][2] - leaves[i][0]) * (leaves[i][3] - leaves[i][1])
            for i, _ in options])[0]
        available = sum(map(capacity, leaves))
        r = leaves.pop(i)
        length = r[axis + 2] - r[axis]
        other = math.floor((r[3 - axis] - r[1 - axis] + 1e-8) / minimum)
        slots = math.floor((length - c.landing + 1e-8) / minimum)
        gap = c.landing if slots >= 2 and available - capacity(r) + slots * other >= c.rooms and rng.random() < .65 else 0.
        slots = math.floor((length - gap + 1e-8) / minimum)
        left = rng.randrange(1, slots)
        cut = rng.uniform(r[axis] + left * minimum, r[axis + 2] - gap - (slots - left) * minimum)
        a, b, hall = list(r), list(r), list(r)
        a[axis + 2], b[axis] = cut, cut + gap
        leaves.extend((tuple(a), tuple(b)))
        if gap:
            hall[axis], hall[axis + 2] = cut, cut + gap
            corridors.append(tuple(hall))
    return [("room", r) for r in leaves] + [("corridor", r) for r in corridors]


def _edges(spaces):
    """Split collinear rectangle edges at every junction; emit each wall once."""
    lines = {}
    for s in spaces:
        x0, y0, x1, y1 = s["rect"]
        for axis, fixed, lo, hi in ((0, y0, x0, x1), (0, y1, x0, x1),
                                    (1, x0, y0, y1), (1, x1, y0, y1)):
            lines.setdefault((axis, round(fixed, 8)), []).append((lo, hi, s["id"]))
    edges = []
    for (axis, fixed), intervals in sorted(lines.items()):
        cuts = sorted(set(round(v, 8) for lo, hi, _ in intervals for v in (lo, hi)))
        for lo, hi in zip(cuts, cuts[1:]):
            owners = [i for a, b, i in intervals if a - 1e-7 <= (lo + hi) / 2 <= b + 1e-7]
            if owners:
                edges.append(dict(axis=axis, fixed=fixed, lo=lo, hi=hi, owners=owners))
    return edges


def _cycle(edges):
    """Return a simple cycle (closed node list, ordered edges), if one exists."""
    graph = {}
    for edge in edges:
        a, b = edge["owners"]
        pending, previous = [a], {a: None}
        for node in pending:
            for other, link in graph.get(node, ()):
                if other not in previous:
                    previous[other] = (node, link)
                    pending.append(other)
            if b in previous:
                nodes, links = [b], []
                while nodes[-1] != a:
                    node, link = previous[nodes[-1]]
                    nodes.append(node)
                    links.append(link)
                return list(reversed(nodes)) + [a], list(reversed(links)) + [edge]
        graph.setdefault(a, []).append((b, edge))
        graph.setdefault(b, []).append((a, edge))
    return None


def _box(boxes, kind, size, center, level, material=None):
    """Append one axis-aligned part; degenerate sizes are skipped."""
    if min(size) > 1e-7:
        boxes.append(dict(kind=kind, size=list(size), center=list(center), level=level, material=material or kind))
        if kind == "floor":
            # Stitch collision seams by 1 mm; visual slabs never overlap.
            boxes[-1]["collision_size"] = [size[0]+.002, size[1]+.002, size[2]]


def _segment(boxes, c, e, lo, hi, z0, height, level, material="wall", thickness=None):
    """Append the wall (or trim, glass) part of edge e between lo and hi, from z0 up by height."""
    axis = e["axis"]
    size, pos = [thickness or c.wall] * 2 + [height], [e["fixed"]] * 2 + [z0 + height / 2]
    size[axis], pos[axis] = hi - lo, (lo + hi) / 2
    _box(boxes, material, size, pos, level)


def _storey_spaces(c, first_id, level, rng):
    """Rooms, corridors and stair landings of one storey, its edges and the edges wide enough for a door."""
    lane, landing, run = c.landing, c.landing, c.run
    local = []
    for kind, rect in _partition(c, rng):
        local.append(dict(id=first_id + len(local), kind=kind, level=level, rect=list(rect)))
    if c.floors > 1:
        for kind, rect in (("landing", (-2 * lane, 0., 0., landing)),
                           ("landing", (-2 * lane, landing + run, 0., c.stair_length)),
                           ("corridor", (-lane, landing, 0., landing + run))):
            local.append(dict(id=first_id + len(local), kind=kind, level=level, rect=list(rect)))

    def doors(edges):
        return [e for e in edges if len(e["owners"]) == 2 and e["hi"] - e["lo"] >= c.door_width + 2 * c.wall]
    edges = _edges(local)
    candidates = doors(edges)
    if not _cycle(candidates):
        # A strip/one-room partition cannot have a simple cycle. Add a physical
        # return corridor, split into two nodes, outside the east facade.
        for bottom, top in ((0., c.depth / 2), (c.depth / 2, c.depth)):
            local.append(dict(id=first_id + len(local), kind="corridor", level=level,
                              rect=[c.width, bottom, c.width + lane, top], annex=True))
        edges = _edges(local)
        candidates = doors(edges)
    return local, edges, candidates


def _open_doors(c, rng, by_id, candidates):
    """Seeded spanning tree over the door candidates plus one extra door closing a cycle: (opened ids, cycle)."""
    parent = {i: i for i in by_id}

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i
    rng.shuffle(candidates)
    opened = set()
    for e in candidates:
        a, b = map(root, e["owners"])
        public = all(by_id[i]["kind"] != "room" for i in e["owners"])
        if a != b or public or rng.random() < c.loops:
            parent[a] = b
            opened.add(id(e))
    if len({root(i) for i in parent}) != 1:
        raise ValueError("Door clearances disconnect this layout; try another seed or larger rooms")
    if not _cycle([e for e in candidates if id(e) in opened]):
        extra = next((e for e in candidates if id(e) not in opened), None)
        if extra is None:
            raise ValueError("Dimensions cannot accommodate a traversable loop")
        opened.add(id(extra))
    return opened, _cycle([e for e in candidates if id(e) in opened])


def _storey_shell(scene, c, level, rng, local, edges, opened, by_id):
    """Floor slabs, walls, stair-void guards, doors (portals) and windows of one storey; returns {edge id: portal}."""
    boxes, z, lane, landing, run = scene["boxes"], level * c.storey, c.landing, c.landing, c.run
    wall_h, portal_ids = c.storey - c.slab, {}
    for s in local:
        x0, y0, x1, y1 = s["rect"]
        _box(boxes, "floor", (x1 - x0, y1 - y0, c.slab), ((x0 + x1) / 2, (y0 + y1) / 2, z - c.slab / 2), level)
    for e in edges:
        lo, hi = e["lo"], e["hi"]
        # These edges face the stairwell void, not another room.
        void_edge = (c.floors > 1 and len(e["owners"]) == 1 and
                     ((e["axis"] == 1 and abs(e["fixed"] + lane) < 1e-7) or
                      (e["axis"] == 0 and e["fixed"] in (round(landing, 8), round(landing + run, 8)) and hi <= -lane + 1e-7)))
        if void_edge:
            guard = e["axis"] == 1 or (e["fixed"] == round(landing, 8) and level == c.floors - 1) or (e["fixed"] == round(landing + run, 8) and level == 0)
            if guard:
                _segment(boxes, c, e, lo, hi, z, 1.1, level, "trim", .08)
            continue
        if id(e) in opened:
            public = all(by_id[i]["kind"] != "room" for i in e["owners"])
            width = hi - lo if public else c.door_width
            mid = (lo + hi) / 2
            a, b = mid - width / 2, mid + width / 2
            center = [e["fixed"], e["fixed"], z]
            center[e["axis"]] = mid
            portal_ids[id(e)] = len(scene["portals"])
            scene["portals"].append(dict(rooms=e["owners"], center=center,
                axis=e["axis"], width=width, height=wall_h if public else c.door_height))
            if public:
                continue
            _segment(boxes, c, e, lo, a, z, wall_h, level)
            _segment(boxes, c, e, b, hi, z, wall_h, level)
            _segment(boxes, c, e, a, b, z + c.door_height, wall_h - c.door_height, level)
        elif len(e["owners"]) == 1 and by_id[e["owners"][0]]["kind"] == "room" and hi - lo >= c.window_width + .6 and rng.random() < .65:
            a, b = (lo + hi - c.window_width) / 2, (lo + hi + c.window_width) / 2
            _segment(boxes, c, e, lo, a, z, wall_h, level)
            _segment(boxes, c, e, b, hi, z, wall_h, level)
            _segment(boxes, c, e, a, b, z, c.sill, level)
            _segment(boxes, c, e, a, b, z + c.sill + c.window_height, wall_h - c.sill - c.window_height, level)
            _segment(boxes, c, e, a, b, z + c.sill, c.window_height, level, "glass", .02)
        else:
            _segment(boxes, c, e, lo, hi, z, wall_h, level)
    return portal_ids


def _loop_route(scene, level, z, by_id, cycle, portal_ids, cycle_rank):
    """Ground-truth closed route of one storey: hubs, door approaches and portal centres around the cycle."""
    cycle_nodes, cycle_edges = cycle
    points = []
    for a, b, edge in zip(cycle_nodes, cycle_nodes[1:], cycle_edges):
        portal = scene["portals"][portal_ids[id(edge)]]
        hubs = [[(by_id[i]["rect"][0] + by_id[i]["rect"][2]) / 2,
                 (by_id[i]["rect"][1] + by_id[i]["rect"][3]) / 2, z] for i in (a, b)]
        approaches = []
        for hub in hubs:
            approach = portal["center"][:]
            normal = 1 - portal["axis"]
            approach[normal] += math.copysign(.5, hub[normal] - approach[normal])
            approaches.append(approach)
        points.extend(([hubs[0]] if not points else []) + [approaches[0], portal["center"][:], approaches[1], hubs[1]])
    scene["loop_routes"].append(dict(level=level, rooms=cycle_nodes,
        portals=[portal_ids[id(e)] for e in cycle_edges], points=points,
        length_m=round(sum(math.dist(a, b) for a, b in zip(points, points[1:])), 3), cycle_rank=cycle_rank))


def _stairwell(scene, c, level, local):
    """Stairwell wall, ground slab, treads and the stair record of one storey (multi-storey buildings only)."""
    boxes, z, lane, landing, run = scene["boxes"], level * c.storey, c.landing, c.landing, c.run
    _box(boxes, "wall", (c.wall, run, c.storey), (-2 * lane, landing + run / 2, z + c.storey / 2), level)
    if level == 0:
        _box(boxes, "floor", (lane, run, c.slab), (-1.5 * lane, landing + run / 2, -c.slab / 2), level)
    if level < c.floors - 1:
        rise = c.storey / c.risers
        for i in range(1, c.risers):
            _box(boxes, "stairs", (lane, .28, rise), (-1.5 * lane, landing + (i - .5) * .28, z + (i - .5) * rise), level)
        lower = next(s["id"] for s in local if s["kind"] == "landing")
        scene["stairs"].append(dict(lower=lower, upper_level=level + 1, start=[-1.5 * lane, landing - .5, z],
                                    end=[-1.5 * lane, landing + run + .5, z + c.storey],
                                    risers=c.risers, rise=rise, tread=.28, width=lane - c.wall))


def _ceilings(scene, c):
    """Roof slabs (with --roof) and the 5 mm plaster skin under every inter-storey slab."""
    boxes, spaces, lane = scene["boxes"], scene["spaces"], c.landing
    if c.roof:
        z = c.floors * c.storey - c.slab / 2
        _box(boxes, "ceiling", (c.width, c.depth, c.slab), (c.width / 2, c.depth / 2, z), c.floors, "wall")
        if c.floors > 1:
            _box(boxes, "ceiling", (2 * lane, c.stair_length, c.slab), (-lane, c.stair_length / 2, z), c.floors, "wall")
        for level in range(c.floors):
            if any(s.get("annex") and s["level"] == level for s in spaces) and not any(
                    s.get("annex") and s["level"] == level + 1 for s in spaces):
                _box(boxes, "ceiling", (lane, c.depth, c.slab),
                     (c.width + lane / 2, c.depth / 2, (level + 1) * c.storey - c.slab / 2), level + 1, "wall")
    # A body carries one texture on every face, so the slab of the storey above would show its
    # tiles or planks as the ceiling. Add a 5 mm plaster skin under it for every covered space;
    # it belongs to the storey above, like the slab, so floor cutaways hide both.
    skin = CEILING_SKIN
    for s in [s for s in spaces if s["level"] < c.floors - 1]:
        upper_annex = any(t.get("annex") and t["level"] == s["level"] + 1 for t in spaces)
        if s.get("annex") and not (upper_annex or c.roof):
            continue  # nothing above this annex section
        x0, y0, x1, y1 = s["rect"]
        _box(boxes, "ceiling", (x1 - x0, y1 - y0, skin),
             ((x0 + x1) / 2, (y0 + y1) / 2, (s["level"] + 1) * c.storey - c.slab - skin / 2), s["level"] + 1, "wall")


def _finish(scene, c):
    """Room purposes, furniture, materials, details, room styles, z-fighting gaps, semantics and statistics."""
    from furniture import assign_rooms, furnish
    from geometry import geometry_stats, separate_coplanar
    from room_styles import apply_room_styles
    from semantics import annotate
    assign_rooms(scene)
    if c.furnished:
        furnish(scene)
    if c.details:
        from surfaces import decorate_materials
        decorate_materials(scene)
        if c.furnished:
            from details import enrich
            enrich(scene)
    apply_room_styles(scene)  # per-room finishes, appended after every other part
    separate_coplanar(scene)  # a 5 mm gap between coplanar faces: no z-fighting
    scene.setdefault("style", dict(PROFILE))
    annotate(scene)
    scene["geometry_stats"] = geometry_stats(scene)
    return scene


def generate(c=None):
    """Seeded building scene (rooms, doors, stairs, furniture, finishes) as backend-neutral JSON."""
    c = Config() if c is None else c  # built now, so it sees the active settings
    import room_styles
    if c.seed == room_styles.LAB_D66_SEED and room_styles.ENABLED:  # Easter egg: seed 66 is Lab D66 itself
        return room_styles.lab_d66_scene(c)
    scene = dict(config=asdict(c), spaces=[], portals=[], stairs=[], boxes=[], loop_routes=[],
                 floor_seeds=[c.seed + level * 0x9E3779B97F4A7C15 for level in range(c.floors)])
    if settings.signature():  # non-default config/ settings: record which (reproducibility)
        scene["settings"] = settings.signature()
    spaces = scene["spaces"]
    for level in range(c.floors):
        rng = random.Random(scene["floor_seeds"][level])
        local, edges, candidates = _storey_spaces(c, len(spaces), level, rng)
        spaces.extend(local)
        by_id = {s["id"]: s for s in local}
        opened, cycle = _open_doors(c, rng, by_id, candidates)
        portal_ids = _storey_shell(scene, c, level, rng, local, edges, opened, by_id)
        _loop_route(scene, level, level * c.storey, by_id, cycle, portal_ids, len(opened) - len(local) + 1)
        if c.floors > 1:
            _stairwell(scene, c, level, local)
    for stair in scene["stairs"]:
        stair["upper"] = next(s["id"] for s in spaces if s["level"] == stair["upper_level"] and
                              s["kind"] == "landing" and s["rect"][1] > c.landing)
    x0, y0, x1, y1 = next(s for s in spaces if s["kind"] == "room")["rect"]
    scene["spawn"] = [(x0 + x1) / 2, (y0 + y1) / 2, .55]
    scene["bounds"] = [-2 * c.landing if c.floors > 1 else 0., 0., max(s["rect"][2] for s in spaces), c.depth]
    _ceilings(scene, c)
    return _finish(scene, c)


def texture_file(box, textures=None):
    """Image a loaded box shows: the user's <material>.png if given, else its procedural texture, else None."""
    from surfaces import texture_path
    path = Path(textures) / f'{box["material"]}.png' if textures else None
    if path is None or not path.is_file():
        path = Path(texture_path(box["texture"])) if "texture" in box else None
    return path if path is not None and path.is_file() else None


def collision_shape(b):
    """(key, kind, data) of a part's collision: ("concave", mesh) for cables, ("convex", mesh) for turned and
    rounded parts (the hull of the mesh vertices), else ("box", collision size). Parts with equal keys share a shape.
    load_pybullet and gazebo.export_sdf both read this, so the two simulators collide with the same shapes."""
    from geometry import mesh
    kind = {"cable": "concave", "lathe": "convex", "ellipsoid": "convex", "handle": "convex"}.get(b.get("shape"), "box")
    if kind == "box":
        size = tuple(b.get("collision_size", b["size"]))
        return size, kind, size
    return json.dumps({k: b[k] for k in ("shape", "size", "profile", "axis", "facing", "path") if k in b}, sort_keys=True), kind, mesh(b)


def load_pybullet(scene, client=0, textures=None, view_floor=None, visuals=True):
    """Add static collision AND visual bodies to an existing client; never reset it.

    Return box-aligned body IDs; segmentation pixels can be mapped to semantic kinds.
    Optional textures: directory containing wall/floor/stairs/trim/glass.png files.
    view_floor is for cutaway inspection only: higher bodies still collide.
    visuals=False creates the same collision bodies with one shared hidden visual (fastload.py
    then draws the scene as a few merged meshes).
    """
    import pybullet as p
    from surfaces import box_mesh, texture_path, prepare_textures
    from geometry import mesh
    prepare_textures(scene)
    ids, shapes, images = [], {}, {}
    # Maximal-coordinate bodies with no visual shape get an auto-generated collision graphic in
    # PyBullet's default palette (it z-fights the fastload meshes): give them one shared, hidden one.
    hidden = None if visuals else p.createVisualShape(p.GEOM_BOX, halfExtents=[1e-4] * 3, rgbaColor=[0, 0, 0, 0],
                                                       physicsClientId=client)
    for b in scene["boxes"]:
        material, size = b["material"], tuple(b["size"])
        geometry = mesh(b) if b.get("shape") else None
        shape_key, kind, data = collision_shape(b)
        if shape_key not in shapes:
            shapes[shape_key] = (p.createCollisionShape(p.GEOM_MESH, vertices=data["vertices"], indices=data["indices"],
                                flags=p.GEOM_FORCE_CONCAVE_TRIMESH, physicsClientId=client) if kind == "concave" else
                                p.createCollisionShape(p.GEOM_MESH, vertices=data["vertices"], physicsClientId=client)
                                 if kind == "convex" else p.createCollisionShape(p.GEOM_BOX, halfExtents=[v / 2 for v in data], physicsClientId=client))
        color = list(b.get("color", COLORS[material]))
        if view_floor is not None and b["level"] > view_floor:
            color[3] = 0
        # Visual centre relative to the body (the collision box): non-zero only for parts set apart by
        # geometry.separate_coplanar, which are axis-aligned.
        offset = [v - w for v, w in zip(b["center"], b.get("collision_center", b["center"]))]
        visual = hidden if not visuals else (p.createVisualShape(p.GEOM_MESH, **(geometry or box_mesh(b)), rgbaColor=color, visualFramePosition=offset, physicsClientId=client)
                  if geometry or "texture" in b else p.createVisualShape(p.GEOM_BOX, halfExtents=[v / 2 for v in size], rgbaColor=color, visualFramePosition=offset, physicsClientId=client))
        body = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=shapes[shape_key],
            baseVisualShapeIndex=visual, basePosition=b.get("collision_center", b["center"]),
            baseOrientation=b.get("orientation", [0, 0, 0, 1]),  # optional xyzw quaternion
            # Static rigid bodies, not fixed-base multibodies: Bullet updates every multibody each step
            # (2.93 ms/step for a 2-storey building in DIRECT vs 0.49 ms with maximal coordinates).
            useMaximalCoordinates=True, physicsClientId=client)
        p.changeDynamics(body, -1, lateralFriction=.8, restitution=0, physicsClientId=client)
        path = texture_file(b, textures) if visuals else None
        if path is not None:
            key = str(path.resolve())
            if key not in images:
                images[key] = p.loadTexture(key, physicsClientId=client)
            p.changeVisualShape(body, -1, textureUniqueId=images[key], physicsClientId=client)
        ids.append(body)
    return ids


def _parser():
    """Command-line options of indoor.py."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="settings override: a folder like config/ or one .toml file")
    for name in ("seed", "rooms", "floors"):
        parser.add_argument(f"--{name}", type=int, help="default: config/building.toml")
    for name in ("width", "depth"):
        parser.add_argument(f"--{name}", type=float, help="default: config/building.toml")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--roof", action="store_true", help="Close the top storey for sensor runs")
    parser.add_argument("--export", type=Path, help="Save backend-neutral scene JSON")
    parser.add_argument("--render", type=Path, help="Save overview PNG (requires Pillow)")
    parser.add_argument("--textures", type=Path)
    parser.add_argument("--view-floor", type=int, choices=range(3), help="Hide higher storeys for inspection")
    parser.add_argument("--xray", action="store_true", help="Start with every generated body translucent")
    parser.add_argument("--minimap", action="store_true", help="Live floor-plan window (GUI viewer only)")
    parser.add_argument("--empty", action="store_true", help="Generate architecture without furniture")
    parser.add_argument("--plain", action="store_true", help="Disable automatic textures and extra detail")
    parser.add_argument("--loops", type=float, help="Extra door probability; one loop per floor is always guaranteed")
    return parser


def _save_overview(p, cid, path, target, distance, headless):
    """Overview PNG from the orbit camera; the PNG "Source" metadata records the command."""
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    path.parent.mkdir(parents=True, exist_ok=True)
    view = p.computeViewMatrixFromYawPitchRoll(target, distance, 35, -60, 0, 2)
    projection = p.computeProjectionMatrixFOV(52, 1, .1, 150)
    rgba = p.getCameraImage(1400, 1400, view, projection, shadow=1, lightDirection=[-3, -4, 8],
                            renderer=p.ER_TINY_RENDERER if headless else p.ER_BULLET_HARDWARE_OPENGL, physicsClientId=cid)[2]
    pixels = rgba.tobytes() if hasattr(rgba, "tobytes") else bytes(rgba)
    info = PngInfo()
    info.add_text("Source", "python3 indoor.py " + " ".join(sys.argv[1:]))
    Image.frombytes("RGBA", (1400, 1400), pixels).convert("RGB").save(path, pnginfo=info)


def _session(scene, c, args):
    """Load the scene into PyBullet (GUI or DIRECT), optionally save the overview, then run the viewer loop."""
    import pybullet as p
    from surfaces import prepare_textures
    prepare_textures(scene)
    minimap = None
    if args.minimap and not args.headless:
        from minimap import Minimap
        minimap = Minimap(scene)  # Separate process: starts while PyBullet loads.
    cid = p.connect(p.DIRECT if args.headless else p.GUI)
    if cid < 0:
        raise RuntimeError("Unable to connect to PyBullet; use --headless without a display")
    try:
        # The complete scene is generated above; hide body upload until it is ready.
        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 0, physicsClientId=cid)
        bodies = load_pybullet(scene, cid, args.textures, args.view_floor)
        p.setGravity(0, 0, -9.81, physicsClientId=cid)
        p.setTimeStep(1 / 240, physicsClientId=cid)
        x0, y0, x1, y1 = scene["bounds"]
        target = [(x0 + x1) / 2, (y0 + y1) / 2,
                  ((args.view_floor + .5) if args.view_floor is not None else c.floors / 2) * 3]
        distance = math.hypot(x1 - x0, y1 - y0) * 1.35
        p.resetDebugVisualizerCamera(distance, 35, -60, target, physicsClientId=cid)
        if not args.headless or args.xray:
            from viewer import Viewer
            viewer = Viewer(scene, bodies, cid, args.view_floor, args.xray, minimap)
        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 1, physicsClientId=cid)
        print(f'Seed {c.seed}: {c.rooms} rooms × {c.floors} storeys, '
              f'{len(scene["boxes"])} collision bodies; spawn={scene["spawn"]}')
        print('Closed routes per floor (m):', [r['length_m'] for r in scene['loop_routes']])
        if args.render:
            _save_overview(p, cid, args.render, target, distance, args.headless)
        if not args.headless:
            print("Tab: walk/orbit | T: X-ray | WASD: walk | arrows/right-drag: look | 0: all floors, 1–3: cutaway")
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
        if minimap:
            minimap.close()
        if p.isConnected(cid):
            p.disconnect(cid)


def main():
    """Command line: generate a building, optionally export/render it, and open the PyBullet viewer."""
    parser = _parser()
    args = parser.parse_args()
    try:
        settings.use(args.config)
        # Flags left unset keep the settings' values.
        c = Config(furnished=False if args.empty else None, details=False if args.plain else None, roof=True if args.roof else None,
                   **{k: getattr(args, k) for k in ("seed", "rooms", "floors", "width", "depth", "loops")})
        from banner import splash
        splash("seeded indoor building", f"seed {c.seed}, {c.floors} storey{'s' * (c.floors > 1)}"
               f", {'furnished' if c.furnished else 'empty'}" + (f", settings {args.config}" if args.config else ""))
        scene = generate(c)
    except ValueError as error:
        parser.error(str(error))
    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(json.dumps(scene, indent=2) + "\n")
    _session(scene, c, args)


if __name__ == "__main__":
    main()
