"""Indoor catalogue: every object kind and every room purpose x style family that indoor.generate() emits.

Purpose: one reference set of figures of what the library generates: the furniture.py, household.py and details.py models, the room_styles.py
finishes (door and window frames, Lab D66 blinds and cable reels, wayfinding signs and door plates),
the seed-66 Lab D66 room, and the ceiling luminaires of lights.py (added by pybullet_pbr hosts only).

Method:
  1. Discovery (pure Python, no renderer): generate every (seed, floors) of --seeds x --floors with the
     default Config (furnished, details on), then seed 66, and collect
       - object kinds: the `label` of the parts of every scene["objects"][k] (a group such as desk + chair
         gives both), keyed by the style family of the object's room: corporate, warm, wayfinding,
         lab (the aseptic lab) or d66 (the Lab D66 variant, also seed 66); corridors count as corporate;
       - finish fixtures that are not objects: room_styles parts grouped by role (FINISH_KINDS);
       - luminaires: lights.plan_lights on every scene with a ceiling (floors > 1);
       - rooms: (purpose, family) of every room, with its first example (seed, floors, storey, room id).
     The size of both sets after each scanned building is kept (catalog_index.json "growth").
  2. catalog_assets.png: each kind alone (only its parts, scene["objects"][k]["parts"] -> scene["boxes"]),
     turned so its front (+y of the model) faces the camera, moved to the origin on a neutral floor,
     3/4 camera fitted to its bounding sphere (render.camera). catalog_assets_variants.png: the kinds that
     occur in more than one family, one example per family side by side, one shared camera per kind.
  3. catalog_rooms.png: one cut-away per (purpose, family): the room's floor, walls, finishes and objects; far
     walls (north, east) at full height, near walls (south, west, camera side) cut at --cut metres,
     wall-mounted objects above the cut on near walls removed, corridor-side parts (pictogram signs,
     outside door frames) and the Lab D66 ceiling tile layer removed; its cable reels are kept.
Renderer: PyBullet DIRECT + ER_TINY_RENDERER through indoor.load_pybullet (real textures), one client
at a time, sequential, shadow map off (tools/render.py).
Textures go to a temporary directory (surfaces.ASSETS), so assets/procedural is never pruned.

Outputs: images/catalog_assets.png, catalog_assets_variants.png (pages _p2, _p3... if needed), catalog_rooms.png;
reports/catalog_index.json (discovery) and reports/catalog_renders.csv (--out-dir, --data-dir). Existing outputs are refused unless --replace.
Every PNG carries its regenerating command in the footer and in the PNG "Source" metadata.

Regenerate:
    python3 tools/indoor_catalog.py --replace
    python3 tools/indoor_catalog.py --only index                                      # discovery only
    python3 tools/indoor_catalog.py --index reports/catalog_index.json --only rooms --replace
Self-test (logic, one Lab D66 scene, no renderer):
    python3 tools/indoor_catalog.py --self-test
"""
from pathlib import Path
import argparse
import concurrent.futures
import contextlib
import copy
import csv
import json
import math
import shlex
import sys
import tempfile
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import indoor  # noqa: E402
import room_styles  # noqa: E402
import surfaces  # noqa: E402
from details import _world  # noqa: E402
from furniture import _rotate  # noqa: E402

FAMILIES = ("corporate", "warm", "wayfinding", "lab", "d66")
FAMILY_TITLE = dict(corporate="corporate", warm="warm", wayfinding="wayfinding", lab="lab (aseptic)", d66="Lab D66")
SHORT = dict(corporate="corp", warm="warm", wayfinding="wayf", lab="lab", d66="d66", all="all")
# Finish fixtures without an object: kind -> ((role, parts per instance), ...); the first instance in the room is drawn.
FINISH_KINDS = {"door_frame": (("door", 3),), "window_frame": (("window", 4),), "roller_blind": (("blind", 1), ("blind_box", 1)),
                "cable_reel": (("cable_reel", 1), ("reel_hanger", 1), ("reel_cable", 1), ("reel_plug", 1))}
# room_styles roles drawn only in catalog_rooms.png: room-sized surfaces, and the corridor-side copy of a wayfinding door frame.
SURFACE_ROLES = ("skin", "skirting", "band", "ceiling_tiles", "door_outside")
FRONT_TURN = {(1, 1): 0, (0, 1): 1, (1, -1): 2, (0, -1): 3}   # (axis, sign) of the front -> turns that bring it to +y
NEUTRAL = ((.86, .86, .85), (.74, .74, .73))                  # backdrop
ASSET_LIGHT, ROOM_LIGHT = dict(lightDirection=[-2, 4, 7]), dict(lightDirection=[-3, -4, 8])  # catalogue / library viewer
FIGSIZE, DPI = (12.8, 7.2), 300                               # 3840 x 2160 px pages
INK, QUIET = "#22303a", "#6b7780"


def family_of(space):
    family = space.get("style_family", "corporate")
    return "d66" if family == "lab" and space.get("variant") == "d66" else family


def possible_combos():
    """(purpose, family) pairs allowed by room_styles.RULES (lab split into its two variants), and the excluded ones."""
    allowed, excluded = [], []
    for purpose, rule in room_styles.RULES.items():
        families = set()
        for choice in rule.values():
            families.update(choice if isinstance(choice, (tuple, list)) else (choice,))
        if "lab" in families:
            families.update(("d66",))
        for family in FAMILIES:
            (allowed if family in families else excluded).append((purpose, family))
    return allowed, excluded


# ---------------------------------------------------------------- discovery (no renderer)


def scan(seed, floors):
    """Kinds and room combinations of one generated building (small JSON-able dict)."""
    import lights
    try:
        scene = indoor.generate(indoor.Config(seed=seed, floors=floors))
    except ValueError as error:
        return dict(seed=seed, floors=floors, error=str(error), kinds={}, rooms={})
    spaces, boxes, tag = scene["spaces"], scene["boxes"], dict(seed=seed, floors=floors)
    kinds, rooms = {}, {}

    def note(kind, family, example):
        slot = kinds.setdefault(kind, {})
        if family not in slot or example["single"] and not slot[family]["single"]:
            slot[family] = dict(tag, **example)

    for o in scene.get("objects", ()):
        family = family_of(spaces[o["room"]])
        for label in dict.fromkeys(boxes[i].get("label", o["kind"]) for i in o["parts"]):
            note(label, family, dict(object=o["id"], label=label, single=len(o["items"]) == 1 and o["kind"] == label,
                                     placement=o.get("placement", "floor")))
    roles = {(b.get("role"), b.get("room")) for b in boxes if "role" in b and "object_id" not in b}
    for space in (s for s in spaces if s["kind"] == "room"):
        family = family_of(space)
        for kind, parts in FINISH_KINDS.items():
            if (parts[0][0], space["id"]) in roles:
                note(kind, family, dict(finish=kind, room=space["id"], single=True, placement="ceiling" if kind == "cable_reel" else "wall"))
        key = f'{space["purpose"]}/{family}' + ("/seed66" if "easter_egg" in scene else "")
        rooms.setdefault(key, dict(tag, room=space["id"], level=space["level"], variant=space.get("variant"),
                                   objects=sum(o["room"] == space["id"] for o in scene.get("objects", ()))))
    if floors > 1:
        for f in lights.plan_lights(scene):
            note(f["kind"], "all", dict(light=f["kind"], single=True, placement="ceiling (PBR hosts)"))
    return dict(tag, kinds=kinds, rooms=rooms)


def _scan_star(args):
    return scan(*args)


def discover(seeds, floors, jobs=4):
    """Merge scan() over seeds x floors (seed-major) and seed 66; record set growth after each building."""
    configs = [(s, f) for s in seeds if s != room_styles.LAB_D66_SEED for f in floors] + [(room_styles.LAB_D66_SEED, 1)]
    kinds, rooms, first, growth, errors = {}, {}, {}, [], []
    with concurrent.futures.ProcessPoolExecutor(jobs) as pool:
        for result in pool.map(_scan_star, configs):
            if "error" in result:
                errors.append(result)
            for kind, by_family in result["kinds"].items():
                first.setdefault(kind, [result["seed"], result["floors"]])
                for family, example in by_family.items():
                    held = kinds.setdefault(kind, {}).get(family)
                    if held is None or example["single"] and not held["single"]:
                        kinds[kind][family] = example
            for key, example in result["rooms"].items():
                rooms.setdefault(key, example)
            growth.append(dict(seed=result["seed"], floors=result["floors"], kinds=len(kinds),
                               kind_families=sum(map(len, kinds.values())), rooms=len(rooms)))
    allowed, excluded = possible_combos()
    return dict(seeds=[min(seeds), max(seeds)], floors=list(floors), buildings=len(configs), kinds=kinds, first_seen=first,
                rooms=rooms, growth=growth, errors=errors, rules={k: {v: list(f) if isinstance(f, tuple) else f for v, f in r.items()}
                                                                for k, r in room_styles.RULES.items()},
                allowed=[f"{p}/{f}" for p, f in allowed], excluded=[f"{p}/{f}" for p, f in excluded])


def saturation(growth, key):
    """(seed, floors, scan index) of the last building that grew growth[key]."""
    last = 0
    for i, row in enumerate(growth):
        if i == 0 or row[key] > growth[i - 1][key]:
            last = i
    return growth[last]["seed"], growth[last]["floors"], last + 1


# ---------------------------------------------------------------- instances: parts of one example, front to +y


def _lo_hi(b):
    return [b["center"][a] - b["size"][a] / 2 for a in range(3)], [b["center"][a] + b["size"][a] / 2 for a in range(3)]


def _bounds(parts):
    lows, highs = zip(*(_lo_hi(b) for b in parts))
    return np.min(lows, 0), np.max(highs, 0)


def instance_parts(scene, ex):
    """Deep copies of the parts of one example and the quarter turns that bring its front to +y."""
    boxes = scene["boxes"]
    if "finish" in ex:
        parts = []
        for role, count in FINISH_KINDS[ex["finish"]]:
            parts += [b for b in boxes if b.get("role") == role and b.get("room") == ex["room"] and "object_id" not in b][:count]
        parts = copy.deepcopy(parts)
        if ex["finish"] == "cable_reel":
            return parts, 0
        lo, hi = _bounds(parts)  # frames and blinds: thin horizontal axis, front toward the room centre
        thin = 0 if hi[0] - lo[0] < hi[1] - lo[1] else 1
        rect = scene["spaces"][ex["room"]]["rect"]
        inward = math.copysign(1, (rect[thin] + rect[thin + 2]) / 2 - (lo[thin] + hi[thin]) / 2)
        return parts, FRONT_TURN[(thin, inward)]
    if "light" in ex:
        import lights
        lit = lights.add_lights(copy.deepcopy(scene))
        return [copy.deepcopy(next(b for b in lit["boxes"] if b["kind"] == "light" and b["label"] == ex["light"]))], 0
    o = scene["objects"][ex["object"]]
    parts = [boxes[i] for i in o["parts"] if boxes[i].get("label") == ex["label"]]
    items = [it for it in o["items"] if it["kind"] == ex["label"]]
    turn = round(o.get("yaw", 0) / (math.pi / 2)) % 4
    if len(items) > 1:  # several items of this kind in one group: keep the parts nearest the first one
        spots = [[o["center"][a] + v for a, v in enumerate(_rotate(*it["offset"], turn))] for it in items]
        parts = [b for b in parts if min(range(len(spots)), key=lambda k: math.dist(b["center"][:2], spots[k])) == 0]
    parts = copy.deepcopy(parts)
    if not o.get("detail"):  # furniture.furnish / Lab D66 objects: group turn + item turn, model front is +y
        return parts, (-(turn + items[0]["turn"])) % 4
    display = next((b for b in parts if b.get("shape") == "display"), None)
    if display is not None:  # clutter turned at random: its screen faces the model front
        return parts, (-display["facing"]) % 4
    if o.get("placement") in ("wall", "surface") and len(parts) > 1:  # body first, door / face / grille / handle in front
        rest = [sum(b["center"][a] for b in parts[1:]) / (len(parts) - 1) - parts[0]["center"][a] for a in (0, 1)]
        axis = (0 if parts[0]["size"][0] < parts[0]["size"][1] else 1) if o["placement"] == "wall" else \
            max((0, 1), key=lambda a: abs(rest[a]))
        if o["placement"] == "wall" or abs(rest[axis]) > .02:  # centred clutter (bottle, books) has no front
            return parts, FRONT_TURN[(axis, math.copysign(1, rest[axis]))]
    if ex["label"] == "door_plate":  # floor print: long side along x (normalise sets the text direction)
        return parts, (1 if parts[0]["print_up"][0] == 0 else 0)
    return parts, 0


def normalise(parts, turn):
    """Turn about the vertical axis, centre on the origin, bottom at z = 0, render-only fields."""
    lo, hi = _bounds(parts)
    for b in parts:
        b["center"] = [b["center"][0] - (lo[0] + hi[0]) / 2, b["center"][1] - (lo[1] + hi[1]) / 2, b["center"][2] - lo[2]]
    parts = _world(parts, [0., 0., 0.], turn)
    for b in parts:
        b.pop("collision_center", None)
        b.pop("collision_size", None)
        b["level"] = 0
        if "print_up" in b:  # _world does not turn floor prints: text along the long side, read from +y (the camera side)
            b["print_up"] = [0 if b["size"][0] < b["size"][1] else 1, -1]
    return parts


def asset_scene(parts):
    """One object's parts on a neutral floor tile."""
    lo, hi = _bounds(parts)
    floor = dict(kind="floor", size=[max(.6, hi[0] - lo[0] + .6), max(.6, hi[1] - lo[1] + .6), .02], center=[0, 0, -.011],
                 level=0, material="paper", color=[.82, .82, .80, 1])
    return dict(boxes=parts + [floor])


def asset_camera(parts, size):
    """3/4 camera fitted to one object, with clip planes scaled to its size."""
    import render
    cam = render.camera(dict(boxes=parts), azimuth=60, elevation=25, fov=30, size=size, margin=1.05, lift=.5)
    distance = math.dist(cam["eye"], cam["target"])
    return dict(cam, near=.05 * distance, far=10 * distance)


# ---------------------------------------------------------------- rooms: cut-away of one room


def clip_top(b, top):
    """b cut at height `top` (in place), or None if it lies entirely above."""
    lo, hi = b["center"][2] - b["size"][2] / 2, b["center"][2] + b["size"][2] / 2
    if lo >= top - 1e-6:
        return None
    if hi > top:
        b["size"][2], b["center"][2] = top - lo, (lo + top) / 2
    return b


def room_cutaway(scene, room_id, cut=1.2):
    """Scene with one room seen from the south-west: far walls full, near (south, west) walls cut at `cut` m."""
    c, room = scene["config"], scene["spaces"][room_id]
    x0, y0, x1, y1 = room["rect"]
    z = room["level"] * c["storey"]
    edges, near = ((1, y0), (1, y1), (0, x0), (0, x1)), ((1, y0), (0, x0))
    objects = {o["id"]: o for o in scene.get("objects", ()) if o["room"] == room_id}

    def on_near(b, tol):
        return any(abs(b["center"][a] - v) < tol and b["size"][a] < .3 for a, v in near)

    keep = []
    for b in scene["boxes"]:
        lo, hi = _lo_hi(b)
        if "object_id" in b:
            o = objects.get(b["object_id"])
            ok = o is not None and x0 <= o["center"][0] <= x1 and y0 <= o["center"][1] <= y1 and not (
                o.get("placement") == "wall" and o["bounds3d"][5] > z + cut and
                any(abs(o["center"][a] - v) < .2 for a, v in near))
        elif b["kind"] == "floor":
            ok = b["level"] == room["level"] and abs(b["center"][0] - (x0 + x1) / 2) < .01 and abs(b["center"][1] - (y0 + y1) / 2) < .01
        elif b["kind"] in ("wall", "glass"):
            thin = 0 if b["size"][0] < b["size"][1] else 1
            span = min(hi[1 - thin], room["rect"][3 - thin]) - max(lo[1 - thin], room["rect"][1 - thin])
            ok = b["level"] == room["level"] and span > .05 and any(a == thin and abs(b["center"][a] - v) < .01 for a, v in edges)
        else:
            ok = b.get("room") == room_id and b.get("role") not in ("ceiling_tiles", "door_outside")
        if not ok:
            continue
        b = copy.deepcopy(b)
        if b["kind"] in ("wall", "glass", "wall_finish", "frame") and on_near(b, .2) and clip_top(b, z + cut) is None:
            continue
        keep.append(b)
    # TinyRenderer's shadow map covers a region around the origin (render.cutaway); move there by 6 m steps.
    shift = [-6 * round((x0 + x1) / 12), -6 * round((y0 + y1) / 12), -z]
    for b in keep:
        b["center"] = [v + s for v, s in zip(b["center"], shift)]
        b.pop("collision_center", None)
        b.pop("collision_size", None)
        b["level"] = 0
    return dict(boxes=keep)


def room_camera(sub, size):
    """Elevated camera fitted to one room cut-away (ceilings ignored)."""
    import render
    lo, hi = _bounds([b for b in sub["boxes"] if not b.get("ceiling")])
    frame = dict(boxes=[dict(center=list((lo + hi) / 2), size=list(hi - lo))])
    return dict(render.camera(frame, azimuth=225, elevation=52, fov=24, size=size, margin=.98, lift=.2), near=.3, far=80)


# ---------------------------------------------------------------- rendering and pages


@contextlib.contextmanager
def texture_cache():
    """Procedural textures in a temporary directory for the duration of a run."""
    previous = surfaces.ASSETS
    with tempfile.TemporaryDirectory(prefix="ptg_catalog_") as tmp:
        surfaces.ASSETS = Path(tmp)
        try:
            yield
        finally:
            surfaces.ASSETS = previous


class Scenes:
    """Generated buildings, one kept at a time (examples are processed sorted by (seed, floors))."""
    def __init__(self):
        self.key, self.scene = None, None

    def get(self, seed, floors):
        if self.key != (seed, floors):
            self.key, self.scene = (seed, floors), indoor.generate(indoor.Config(seed=seed, floors=floors))
        return self.scene


def shoot(scene, cam, light, log, figure, name, floor_last=False):
    """(image, pixel bbox of the content); floor_last: the last box is the neutral floor, left out of the bbox."""
    import render
    images, stats = render.render(scene, [cam], light, NEUTRAL, shadow=0, seg=floor_last)
    frame = stats["frames"][0]
    log.append(dict(figure=figure, name=name, parts=stats["parts"], triangles=stats["triangles"], textures=stats["textures"],
                    load_s=stats["load_s"], render_s=frame["render_s"], peak_rss_mb=stats["peak_rss_mb"]))
    print(json.dumps(log[-1]), flush=True)
    if not floor_last:
        return np.asarray(images[0]), frame["bbox"]
    ys, xs = np.nonzero((frame["seg"] >= 0) & (frame["seg"] != stats["ids"][-1]))
    return np.asarray(images[0]), [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def crop(image, box, pad):
    """Image cut to a pixel box grown by `pad` x its longer side (camera unchanged: framing rule stays the same)."""
    x0, y0, x1, y1 = box
    m = int(pad * max(x1 - x0, y1 - y0))
    return image[max(0, y0 - m):y1 + m, max(0, x0 - m):x1 + m]


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def pages(tiles, cols, rows, title, subtitle, path, command, replace, fontsize=4.6):
    """Grid pages of (image or None, title) tiles: path, then path_p2, ...; footer + PNG metadata = command."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    per, out = cols * rows, []
    count = max(1, -(-len(tiles) // per))
    lines = max(t.count("\n") + 1 for _, t in tiles)
    title_h = lines * fontsize * 1.3 / 72 / FIGSIZE[1]
    top, bottom = .91, .025
    cell_w, cell_h = .98 / cols, (top - bottom) / rows
    for n in range(count):
        target = path if n == 0 else path.with_name(f"{path.stem}_p{n + 1}{path.suffix}")
        fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
        fig.text(.01, .985, title + (f" (page {n + 1} of {count})" if count > 1 else ""), fontsize=8, color=INK,
                 fontweight="bold", va="top")
        fig.text(.01, .955, subtitle, fontsize=4.8, color=QUIET, va="top", linespacing=1.4)
        for i, (image, text) in enumerate(tiles[n * per:(n + 1) * per]):
            r, k = divmod(i, cols)
            if image is None:
                continue
            ax = fig.add_axes([.01 + k * cell_w, top - (r + 1) * cell_h, cell_w * .98, cell_h - title_h - .004])
            ax.imshow(image)
            ax.set_title(text, fontsize=fontsize, color=INK, pad=1.5, linespacing=1.15)
            ax.axis("off")
        fig.text(.01, .006, f"Regenerate: {command}", fontsize=4, color=QUIET, ha="left", va="bottom")
        if target.exists() and not replace:
            raise FileExistsError(f"{target} exists; pass --replace")
        fig.savefig(target, dpi=DPI, metadata={"Source": command, "Software": "PTG tools/indoor_catalog.py"})
        plt.close(fig)
        out.append(target)
    return out


def _storeys(n):
    return f"{n} storey" + ("s" if n > 1 else "")


def _size_text(parts):
    lo, hi = _bounds(parts)
    return " × ".join(f"{v:.2f}" for v in hi - lo) + " m"


def _families(by_family):
    return [f for f in FAMILIES + ("all",) if f in by_family]


def render_assets(index, out_dir, command, replace, log, size=(720, 560), limit=None):
    """catalog_assets.png: one tile per kind, its first family in FAMILIES order; returns the page paths."""
    scenes, tiles = Scenes(), []
    kinds = sorted(index["kinds"])[:limit]
    jobs = sorted(kinds, key=lambda k: (lambda e: (e["seed"], e["floors"]))(index["kinds"][k][_families(index["kinds"][k])[0]]))
    images = {}
    for kind in jobs:
        by_family = index["kinds"][kind]
        family = _families(by_family)[0]
        ex = by_family[family]
        parts = normalise(*instance_parts(scenes.get(ex["seed"], ex["floors"]), ex))
        image = crop(*shoot(asset_scene(parts), asset_camera(parts, size), ASSET_LIGHT, log, "assets", kind, True), .1)
        where = ex["placement"].split(" (")[0]
        images[kind] = (image, f"{kind.replace('_', ' ')}\n{_size_text(parts)}, {where}\n"
                               f"{', '.join(SHORT[f] for f in _families(by_family))}")
    tiles = [images[k] for k in kinds]
    subtitle = (f"{len(kinds)} kinds found in {index['buildings']} generated buildings (seeds {index['seeds'][0]} to "
                f"{index['seeds'][1]}, {', '.join(map(str, index['floors']))} storeys, furnished, details on, plus seed 66 Lab D66). "
                "Each object alone, front toward the camera, size W × D × H, placement (floor, wall, surface = on furniture, ceiling).\n"
                "Third line: room style families it occurs in (corp = corporate, wayf = wayfinding, lab = aseptic lab, d66 = Lab D66, "
                "all = independent of the family); the drawn example is the first family listed. Colour variants: assets_variants.png. "
                f"Not drawn: architecture (walls, floors, glass, stairs, ceilings) and room surfaces ({', '.join(SURFACE_ROLES)}): see catalog_rooms.png.")
    return pages(tiles, 12, 8, "PTG indoor catalogue: every object kind indoor.generate() emits", subtitle,
                 out_dir / "catalog_assets.png", command, replace)


def render_variants(index, out_dir, command, replace, log, size=(600, 470), limit=None):
    """assets_variants.png: kinds found in 2+ families, one example per family, same camera per kind."""
    scenes = Scenes()
    kinds = [k for k in sorted(index["kinds"]) if len(set(index["kinds"][k]) - {"all"}) > 1][:limit]
    jobs = sorted(((k, f) for k in kinds for f in _families(index["kinds"][k])),
                  key=lambda kf: (index["kinds"][kf[0]][kf[1]]["seed"], index["kinds"][kf[0]][kf[1]]["floors"]))
    parts = {}
    for kind, family in jobs:
        ex = index["kinds"][kind][family]
        parts[kind, family] = normalise(*instance_parts(scenes.get(ex["seed"], ex["floors"]), ex))
    images = {}
    for kind in kinds:
        present = [f for f in FAMILIES if (kind, f) in parts]
        cam = asset_camera([b for f in present for b in parts[kind, f]], size)
        shots = {f: shoot(asset_scene(parts[kind, f]), cam, ASSET_LIGHT, log, "variants", f"{kind}/{f}", True) for f in present}
        box = union([b for _, b in shots.values()])  # one crop per kind: the families stay comparable
        for family, (image, _) in shots.items():
            ex = index["kinds"][kind][family]
            images[kind, family] = (crop(image, box, .1),
                                    f"{kind.replace('_', ' ')}: {FAMILY_TITLE[family]}\nseed {ex['seed']}, {_storeys(ex['floors'])}")
    rows = 8
    tiles = []
    for page in range(0, len(kinds), 2 * rows):  # two blocks of 5 family columns per page
        block = kinds[page:page + 2 * rows]
        for r in range(rows):
            for half in (0, 1):
                k = half * rows + r
                tiles += [images.get((block[k], f), (None, "")) if k < len(block) else (None, "") for f in FAMILIES]
    subtitle = (f"{len(kinds)} kinds found in two or more room style families (room_styles._recolor: warm and wayfinding use walnut, "
                "oak, black metal and one fabric per room; labs use light grey, white and cyan; Lab D66 adds its printed textures; "
                "some kinds, e.g. bowl, look the same everywhere). "
                "Columns in each half: " + ", ".join(FAMILY_TITLE[f] for f in FAMILIES) + ".\nWithin a family colours still vary per "
                "group (furniture PALETTE draw); the first example found is shown. Same camera for every family of a kind.")
    return pages(tiles, 10, rows, "PTG indoor catalogue: style family variants of the same kind", subtitle,
                 out_dir / "catalog_assets_variants.png", command, replace)


def render_rooms(index, out_dir, command, replace, log, cut=1.2, size=(1200, 1000), limit=None):
    """Render catalog_rooms.png: one cut-away per room purpose and style family."""
    order = [f"{p}/{f}" for p, f in possible_combos()[0]] + ["lab/d66/seed66"]
    keys = [k for k in order if k in index["rooms"]][:limit]
    scenes, images = Scenes(), {}
    for key in sorted(keys, key=lambda k: (index["rooms"][k]["seed"], index["rooms"][k]["floors"])):
        ex = index["rooms"][key]
        sub = room_cutaway(scenes.get(ex["seed"], ex["floors"]), ex["room"], cut)
        purpose, family = key.split("/")[:2]
        head = "Lab D66 room (seed 66 Easter egg)" if key.endswith("seed66") else f"{purpose} / {FAMILY_TITLE[family]}"
        images[key] = (crop(*shoot(sub, room_camera(sub, size), ROOM_LIGHT, log, "rooms", key), .03),
                       f"{head}\n(example seed {ex['seed']}, {_storeys(ex['floors'])}, storey {ex['level']})\n"
                       f"room R{ex['room']:02d}, variant {ex['variant']}")
    missing = sorted(set(order) - set(index["rooms"]))
    subtitle = (f"{len(keys)} room purpose × style family combinations found in {index['buildings']} buildings; families from "
                "room_styles.RULES (purpose, variant) and the lab conversion (largest workshop or storage room, 1 lab in 6 is Lab D66).\n"
                f"Cut-away from the south-west: far walls full height, near walls cut at {cut:.1f} m, wall objects above the cut on near walls "
                "and the corridor side removed. Allowed by RULES but not found: " + (", ".join(missing) if missing else "none") +
                f". Excluded by RULES: {len(index['excluded'])} pairs (reports/catalog_index.json).")
    return pages([images[k] for k in keys], 6, 3, "PTG indoor catalogue: every room purpose × style family", subtitle,
                 out_dir / "catalog_rooms.png", command, replace, fontsize=5)


# ---------------------------------------------------------------- CLI


def _range(text):
    lo, _, hi = text.partition("-")
    return list(range(int(lo), int(hi or lo) + 1))


def self_test():
    """Check the cut-away, orientation and combination logic without rendering."""
    b = dict(center=[0, 0, 1.5], size=[1, .1, 3])
    assert clip_top(copy.deepcopy(b), 1.2)["size"][2] == 1.2 and clip_top(dict(center=[0, 0, 2], size=[1, 1, .2]), 1.2) is None
    for (axis, sign), turn in FRONT_TURN.items():  # the turn brings the front vector to +y
        v = [0, 0]
        v[axis] = sign
        assert _rotate(*v, turn) == (0, 1), (axis, sign, turn)
    allowed, excluded = possible_combos()
    assert ("bedroom", "wayfinding") in excluded and ("office", "wayfinding") in allowed and ("lab", "d66") in allowed
    assert len(allowed) + len(excluded) == len(room_styles.RULES) * len(FAMILIES)
    result = scan(room_styles.LAB_D66_SEED, 1)
    for kind in ("lab_tv", "lab_solder_bench", "door_frame", "window_frame", "roller_blind"):
        assert "d66" in result["kinds"].get(kind, {}), kind
    assert "lab/d66/seed66" in result["rooms"]
    scene = indoor.generate(indoor.Config(seed=room_styles.LAB_D66_SEED))
    desk = next(o for o in scene["objects"] if o["kind"] == "lab_desk" and round(o["yaw"] / (math.pi / 2)) == 2)
    parts = normalise(*instance_parts(scene, dict(object=desk["id"], label="lab_desk")))
    assert all(p["facing"] == 0 for p in parts if p.get("shape") == "display"), "lab desk screens must face +y"
    sign = next(o for o in scene["objects"] if o.get("placement") == "wall" and len(o["parts"]) > 1)
    parts = normalise(*instance_parts(scene, dict(object=sign["id"], label=scene["boxes"][sign["parts"][0]]["label"])))
    assert all(p["center"][1] > parts[0]["center"][1] for p in parts[1:]), "wall landmark face must be in front (+y)"
    sub = room_cutaway(scene, 0)
    assert any(b["kind"] == "floor" for b in sub["boxes"]) and not any(b.get("role") == "ceiling_tiles" for b in sub["boxes"])
    tops = [b["center"][2] + b["size"][2] / 2 for b in sub["boxes"] if b["kind"] == "wall"]
    assert min(tops) <= 1.2 + 1e-6 < max(tops), "near walls cut, far walls full"
    print("indoor_catalog self-test ok")


def main(argv=None):
    """Command line: discovery, then the selected catalogue figures."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=_range, default=_range("0-60"), help="seed range, e.g. 0-60")
    ap.add_argument("--floors", type=_range, default=_range("1-3"), help="storey counts, e.g. 1-3")
    ap.add_argument("--jobs", type=int, default=4, help="discovery worker processes (no renderer in them)")
    ap.add_argument("--index", type=Path, help="reuse this catalog_index.json instead of running the discovery")
    ap.add_argument("--only", nargs="+", choices=("index", "assets", "variants", "rooms"), default=("index", "assets", "variants", "rooms"))
    ap.add_argument("--cut", type=float, default=1.2, help="near-wall cut height in catalog_rooms.png (m)")
    ap.add_argument("--limit", type=int, help="render only the first N tiles of each figure (trial runs)")
    ap.add_argument("--out-dir", type=Path, default=Path("images"), help="figures (catalog_*.png)")
    ap.add_argument("--data-dir", type=Path, default=Path("reports"), help="catalog_index.json and catalog_renders.csv")
    ap.add_argument("--replace", action="store_true", help="overwrite existing outputs")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    command = "python3 tools/indoor_catalog.py " + shlex.join(sys.argv[1:] if argv is None else argv)
    out = args.out_dir
    data = args.data_dir
    names = dict(index=[data / "catalog_index.json"], assets=[out / "catalog_assets*.png"],
                 variants=[out / "catalog_assets_variants*.png"], rooms=[out / "catalog_rooms*.png"])
    wanted = [n for k in args.only if not (k == "index" and args.index) for n in names[k]] + [data / "catalog_renders.csv"]
    clash = [p for pattern in wanted for p in pattern.parent.glob(pattern.name)
             if not (pattern.name == "catalog_assets*.png" and "variants" in p.name)]
    if clash and not args.replace:
        sys.exit(f"{', '.join(map(str, clash))} exist; pass --replace or another --out-dir")
    out.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    if args.index:
        index = json.loads(args.index.read_text())
    else:
        index = discover(args.seeds, args.floors, args.jobs)
        index["command"] = command
        (data / "catalog_index.json").write_text(json.dumps(index, indent=1) + "\n")
    growth = [r for r in index["growth"] if r["seed"] != room_styles.LAB_D66_SEED]  # seed 66 is one fixed room, added last
    print(f"{len(index['kinds'])} kinds ({growth[-1]['kinds']} without seed 66), {sum(map(len, index['kinds'].values()))} kind x "
          f"family pairs, {len(index['rooms'])} room combinations in {index['buildings']} buildings ({time.perf_counter() - t0:.0f} s)")
    for key in ("kinds", "kind_families", "rooms"):
        s, f, n = saturation(growth, key)
        print(f"  {key}: last grew at seed {s}, {f} storeys (building {n} of {len(growth)})")
    log = []
    with texture_cache():
        for key, fn in (("assets", render_assets), ("variants", render_variants), ("rooms", render_rooms)):
            if key in args.only:
                t1 = time.perf_counter()
                for path in fn(index, out, command, args.replace, log, **({"cut": args.cut} if key == "rooms" else {}), limit=args.limit):
                    print(f"{path}  ({time.perf_counter() - t1:.0f} s)")
    if log:
        with open(data / "catalog_renders.csv", "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(log[0]))
            writer.writeheader()
            writer.writerows(log)


if __name__ == "__main__":
    main()
