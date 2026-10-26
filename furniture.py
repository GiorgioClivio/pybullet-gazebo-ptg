"""Compact metric furniture models and seeded room-aware placement."""
import math
import random
import settings
from styles import PALETTE
from geometry import rotated_axis


def _model_chair(name, color, box, legs):
    """Parts of chair, armchair, sofa."""
    w, d = {"chair": (.48, .48), "armchair": (.82, .80), "sofa": (2.0, .86)}[name]
    legs(w, d, .35)
    box(0, 0, .42, w, d, .18, "fabric")
    box(0, -d / 2 + .06, .73, w, .12, .6, "fabric")
    if name != "chair":
        for x in (-w / 2 + .06, w / 2 - .06):
            box(x, 0, .57, .12, d, .38, "fabric")
        for x in ((-.43, .43) if name == "sofa" else (0,)):
            box(x, .03, .53, .72 if name == "sofa" else .55, d - .22, .10,
                "fabric", [min(1, c * 1.16) for c in color[:3]] + [1])


def _model_meeting_table(name, color, box, legs):
    """Parts of meeting_table, dining_table."""
    # Long 2.4 x 1.0 m table: a glass top on a slim metal frame (meeting rooms) or solid wood (dining).
    w, d, h = 2.4, 1.0, .75
    if name == "meeting_table":
        legs(w, d, h - .06, .045)
        for y in (-d / 2 + .07, d / 2 - .07):
            box(0, y, h - .04, w - .1, .04, .04, "metal")
        for x in (-w / 2 + .07, w / 2 - .07):
            box(x, 0, h - .04, .04, d - .18, .04, "metal")
        box(0, 0, h - .01, w, d, .02, "glass")
    else:
        for x in (-w / 2 + .09, w / 2 - .09):
            for y in (-d / 2 + .09, d / 2 - .09):
                box(x, y, (h - .05) / 2, .08, .08, h - .05)
        box(0, 0, h - .025, w, d, .05)


def _model_desk(name, color, box, legs):
    """Parts of desk, table, coffee_table, side_table."""
    w, d, h = {"desk": (1.35, .65, .75), "table": (1.6, .85, .75),
               "coffee_table": (1., .55, .42), "side_table": (.5, .5, .55)}[name]
    legs(w, d, h - .05)
    box(0, 0, h - .025, w, d, .05)
    if name == "desk":
        box(0, -.15, h + .025, .28, .18, .05, "metal")
        box(0, -.245, h + .15, .045, .045, .24, "metal")
        box(0, -.19, h + .31, .46, .055, .28, "screen")
        box(0, .17, h + .015, .36, .13, .03, "plastic", (.22, .27, .31, 1))
    else:
        box(.12, 0, h + .025, .24, .17, .05, "paper", color)
        box(-.17, .04, h + .06, .08, .08, .12, "ceramic", (.80, .78, .71, 1), shape="lathe")


def _model_bed(name, color, box, legs):
    """Parts of bed."""
    box(0, 0, .22, 1.05, 2.0, .35)
    box(0, 0, .47, 1., 1.94, .18, "fabric", (.92, .91, .86, 1))
    box(0, -.72, .60, .70, .38, .14, "fabric", (.97, .95, .88, 1))
    box(0, .25, .575, 1.01, 1.30, .04, "fabric")
    box(0, -.98, .54, 1.05, .08, .94)


def _model_bookcase(name, color, box, legs):
    """Parts of bookcase, cabinet, tv_stand."""
    w, d, h = {"bookcase": (1.0, .35, 1.75), "cabinet": (.95, .43, 1.),
               "tv_stand": (1.4, .40, .50)}[name]
    box(0, -d / 2 + .02, h / 2, w, .04, h)
    for x in (-w / 2 + .025, w / 2 - .025):
        box(x, 0, h / 2, .05, d, h)
    shelves = 5 if name == "bookcase" else 2
    for i in range(shelves):
        z = .05 + i * (h - .10) / (shelves - 1)
        box(0, 0, z, w, d, .05)
        if name == "bookcase" and i < shelves - 1:
            for j in range(5):
                box(-.34 + j * .15, 0, z + .14, .09, .22, .23 + (j % 2) * .06,
                    "paper", PALETTE[(i + j) % len(PALETTE)])
    if name == "cabinet":
        for x in (-w / 4, w / 4):
            box(x, d / 2, h / 2, w / 2 - .025, .035, h - .12, "plastic", color)
            box(x / 3, d / 2 + .035, .6, .025, .04, .15, "metal")
    if name == "tv_stand":
        box(0, 0, h + .04, .38, .22, .08, "metal")
        box(0, -.03, h + .40, 1.02, .07, .60, "screen")


def _model_plant(name, color, box, legs):
    """Parts of plant."""
    box(0, 0, .17, .30, .30, .34, "ceramic", shape="lathe",
        profile=[[.72, -.5], [.78, -.43], [.96, .40], [1, .44], [1, .5]])
    box(0, 0, .51, .055, .055, .4, shape="lathe")
    for x, y, z, w in ((0, 0, .80, .42), (-.15, .02, .66, .28), (.15, -.03, .94, .28)):
        box(x, y, z, w, .32, .30, "leaf", shape="ellipsoid")
    for x in (-.09, .09):
        box(x, -.05, .91, .14, .18, .28, "leaf", shape="ellipsoid")


def _model_lamp(name, color, box, legs):
    """Parts of lamp."""
    box(0, 0, .035, .35, .35, .07, "metal", shape="lathe")
    box(0, 0, .72, .035, .035, 1.4, "metal", shape="lathe")
    box(0, 0, 1.46, .34, .34, .28, "fabric", (.82, .79, .70, 1), shape="lathe",
        profile=[[1, -.5], [1, -.45], [.64, .46], [.64, .5]])


def _model_boxes(name, color, box, legs):
    """Parts of boxes."""
    box(0, 0, .18, .48, .36, .36, "cardboard")
    box(.04, -.02, .49, .35, .29, .26, "plastic", color)
    box(0, .181, .20, .19, .003, .10, "paper", (.94, .88, .72, 1))


def _model_floor_book(name, color, box, legs):
    """Parts of floor_book."""
    box(0, 0, .035, .24, .17, .07, "paper", color)


def _model_toy(name, color, box, legs):
    """Parts of toy."""
    box(0, 0, .08, .16, .16, .16, "plastic", color)
    box(.04, 0, .20, .08, .08, .08, "plastic", PALETTE[2])


def _model_bin(name, color, box, legs):
    """Parts of bin, basket, crate, suitcase."""
    w, d, h = {"bin": (.28, .28, .48), "basket": (.38, .30, .26),
               "crate": (.44, .34, .35), "suitcase": (.40, .24, .58)}[name]
    box(0, 0, h / 2, w, d, h, "wood" if name in ("basket", "crate") else "plastic", color)
    box(0, 0, h + .006, w - .06, d - .06, .012, "plastic", (.10, .14, .16, 1))
    if name == "suitcase":
        box(0, 0, h + .10, .17, .035, .035, "metal")
        for x in (-.07, .07):
            box(x, 0, h + .05, .025, .035, .10, "metal")
    else:
        box(.03, 0, h + .025, w / 2, d / 2, .05, "fabric", PALETTE[4])


def _model_cart(name, color, box, legs):
    """Parts of cart."""
    legs(.65, .42, .85)
    for z in (.16, .48, .84):
        box(0, 0, z, .65, .42, .055, "metal")
    for x in (-.25, .25):
        for y in (-.14, .14):
            box(x, y, .06, .075, .06, .12, "plastic", (.12, .14, .15, 1), shape="lathe", axis=1)
    box(.10, 0, .62, .26, .28, .23, "cardboard")


def _model_bottle(name, color, box, legs):
    """Parts of bottle, vase, small_plant."""
    w, h = (.075, .20) if name == "bottle" else (.13, .17)
    box(0, 0, h / 2, w, w, h, "ceramic", color, shape="lathe",
        profile=[[.68, -.5], [.9, -.44], [1, -.25], [1, .22], [.72, .4], [.6, .5]])
    if name == "bottle":
        box(0, 0, h + .025, .035, .035, .05, "plastic", (.8, .8, .75, 1), shape="lathe")
        box(0, 0, h + .06, .04, .04, .025, "metal", shape="lathe")
        box(0, 0, .11, w+.001, w+.001, .07, "paper", (.85, .83, .76, 1), shape="lathe",
            profile=[[1, -.5], [1, .5]])
    elif name == "small_plant":
        box(0, 0, .25, .02, .02, .18, "leaf", shape="lathe")
        for x, y, z in ((-.07, 0, .28), (.05, .03, .33), (0, -.04, .39)):
            box(x, y, z, .13, .10, .09, "leaf" if name == "small_plant" else "fabric",
                None if name == "small_plant" else color, shape="ellipsoid")


def _model_mug(name, color, box, legs):
    """Parts of mug."""
    box(0, 0, .05, .085, .085, .10, "ceramic", color, shape="lathe",
        profile=[[.82, -.5], [.97, -.4], [1, .5]])
    box(0, 0, .101, .069, .069, .002, "plastic", (.10, .08, .06, 1), shape="lathe")
    box(.051, 0, .054, .07, .021, .076, "ceramic", color, shape="handle")


def _model_book_stack(name, color, box, legs):
    """Parts of book_stack, magazine."""
    for i in range(3 if name == "book_stack" else 1):
        box((i % 2) * .015, 0, .02 + i * .038, .25, .18, .038, "paper", PALETTE[(i + 1) % 6])
        box((i % 2) * .015, .003, .022 + i * .038, .23, .182, .023, "paper", (.91, .88, .77, 1))


def _model_laptop(name, color, box, legs):
    """Parts of laptop."""
    box(0, 0, .012, .28, .21, .024, "metal")
    box(0, -.09, .13, .28, .025, .23, "screen")
    box(0, .02, .026, .21, .10, .005, "plastic", (.25, .29, .33, 1))


def _model_printer(name, color, box, legs):
    """Parts of printer."""
    box(0, 0, .115, .38, .30, .23, "plastic", (.78, .80, .77, 1))
    box(0, .152, .14, .27, .008, .075, "screen")
    box(0, .16, .07, .24, .17, .015, "paper", (.94, .93, .85, 1))


MODELS = {"chair": _model_chair, "armchair": _model_chair, "sofa": _model_chair,
          "meeting_table": _model_meeting_table, "dining_table": _model_meeting_table, "desk": _model_desk,
          "table": _model_desk, "coffee_table": _model_desk, "side_table": _model_desk, "bed": _model_bed,
          "bookcase": _model_bookcase, "cabinet": _model_bookcase, "tv_stand": _model_bookcase,
          "plant": _model_plant, "lamp": _model_lamp, "boxes": _model_boxes, "floor_book": _model_floor_book,
          "toy": _model_toy, "bin": _model_bin, "basket": _model_bin, "crate": _model_bin, "suitcase": _model_bin,
          "cart": _model_cart, "bottle": _model_bottle, "vase": _model_bottle, "small_plant": _model_bottle,
          "mug": _model_mug, "book_stack": _model_book_stack, "magazine": _model_book_stack,
          "laptop": _model_laptop, "printer": _model_printer}


def _model(name, color):
    parts = []

    def box(x, y, z, w, d, h, material="wood", tint=None, shape="bevel", **geometry):
        if material == "screen":
            box(x, y, z, w, d, h, "metal")
            # A single printed face, 2 mm beyond the bezel: never coplanar.
            parts.append(dict(center=[x, y+d/2+.0015, z], size=[w-.02, .001, h-.02],
                              material="screen", color=[1, 1, 1, 1], shape="display", facing=0))
            return
        parts.append(dict(center=[x, y, z], size=[w, d, h], material=material,
                          color=list(tint or color) if material == "fabric" or tint else None,
                          shape=shape, **({"bevel": min(.035 if material == "fabric" else .008, min(w, d, h)*.2)}
                                          if shape == "bevel" else {}), **geometry))

    def legs(w, d, top, thickness=.055):
        for x in (-w / 2 + .07, w / 2 - .07):
            for y in (-d / 2 + .07, d / 2 - .07):
                box(x, y, top / 2, thickness, thickness, top, "metal", shape="lathe")

    if name in MODELS:
        MODELS[name](name, color, box, legs)
    else:
        from household import build
        build(name, box, legs, color)
    return parts


def _rotate(x, y, turn):
    return ((x, y), (-y, x), (-x, -y), (y, -x))[turn % 4]


def _crosses(rect, a, b, margin):
    """Intersection of a segment and an inflated footprint (conservative clearance)."""
    lo, hi = 0., 1.
    for axis in (0, 1):
        low, high, delta = rect[axis] - margin, rect[axis + 2] + margin, b[axis] - a[axis]
        if abs(delta) < 1e-10:
            if not low <= a[axis] <= high:
                return False
        else:
            start, end = sorted(((low - a[axis]) / delta, (high - a[axis]) / delta))
            lo, hi = max(lo, start), min(hi, end)
            if lo > hi:
                return False
    return True


def assign_rooms(scene):
    """Plan room uses independently of furniture visibility and material generation."""
    cfg = settings.current()["rooms"]  # config/rooms.toml
    for level, seed in enumerate(scene["floor_seeds"]):
        rooms = [s for s in scene["spaces"] if s["level"] == level and s["kind"] == "room"]
        types = list(cfg["purposes"])
        rng = random.Random(f"{seed}:room_types")
        rng.shuffle(types)
        for i, room in enumerate(rooms):
            room["purpose"] = types[i % len(types)]
        # Wet rooms occupy smaller rooms, never the spawn room when alternatives exist.
        if len(rooms) >= 3:
            small = sorted(rooms[1:], key=lambda s: (s["rect"][2]-s["rect"][0])*(s["rect"][3]-s["rect"][1]))
            for target, purpose in zip(small[:len(cfg["small_rooms"])], cfg["small_rooms"]):
                donor = next((s for s in rooms if s["purpose"] == purpose and s is not target), None)
                if donor:
                    donor["purpose"] = target["purpose"]
                target["purpose"] = purpose
        largest = cfg["largest_room"]
        communal = [s for s in rooms if s["purpose"] not in cfg["small_rooms"] and
                    min(s["rect"][a+2]-s["rect"][a] for a in (0, 1)) > largest["min_side"]]
        if communal and largest["purpose"]:
            max(communal, key=lambda s: (s["rect"][2]-s["rect"][0])*(s["rect"][3]-s["rect"][1]))["purpose"] = largest["purpose"]
        for room in rooms:
            room["variant"] = rng.choice(cfg["variants"][room["purpose"]])
    # Labs and per-room style families: own RNG streams, after every purpose/variant above is drawn.
    from room_styles import assign_families
    assign_families(scene)


def _turned(part, turn, offset=None):
    """Copy of a model part turned by `turn` quarter turns about z, then shifted by offset (dx, dy) if given."""
    x, y = _rotate(*part["center"][:2], turn)
    if offset is not None:
        x, y = x + offset[0], y + offset[1]
    size = part["size"][:]
    if turn % 2:
        size[0], size[1] = size[1], size[0]
    return dict(part, center=[x, y, part["center"][2]], size=size, axis=rotated_axis(part, turn),
                facing=(part.get("facing", 0)+turn)%4)


class _Room:
    """Placement state of one room: its travel lanes (from the centre to every door) and the footprints used."""

    def __init__(self, scene, room, rng):
        self.scene, self.room, self.rng, self.c = scene, room, rng, scene["config"]
        x0, y0, x1, y1 = self.rect = room["rect"]
        center, self.z = [(x0 + x1) / 2, (y0 + y1) / 2], room["level"] * self.c["storey"]
        self.routes, self.occupied = [], []
        for portal in (e for e in scene["portals"] if room["id"] in e["rooms"]):
            door, approach = portal["center"][:2], portal["center"][:2]
            normal = 1 - portal["axis"]
            approach[normal] += math.copysign(.5, center[normal] - door[normal])
            self.routes.extend(((center, approach), (approach, door)))
            scene["clear_paths"].append(dict(room=room["id"], width=.9,
                                             points=[[*point, self.z] for point in (center, approach, door)]))
        self.routes.append((center, center))  # A clear hub, including the robot spawn.

    def place(self, items, wall=None, align=None):
        """Place a coherent group atomically, against a wall or in free space; True when placed."""
        rng, rect = self.rng, self.rect
        color = rng.choice(PALETTE)
        parts = [dict(_turned(part, turn, (px, py)), label=name) for name, px, py, turn in items for part in _model(name, color)]
        for _ in range(36):
            turn = wall if wall is not None else rng.randrange(4)
            rotated = [_turned(part, turn) for part in parts]
            bounds = [min(p["center"][a] - p["size"][a] / 2 for p in rotated) for a in (0, 1)] + [
                max(p["center"][a] + p["size"][a] / 2 for p in rotated) for a in (0, 1)]
            margin = self.c["wall"] / 2 + .09
            low, high = [rect[a] + margin - bounds[a] for a in (0, 1)], [rect[a + 2] - margin - bounds[a + 2] for a in (0, 1)]
            if any(a > b for a, b in zip(low, high)):
                continue
            offset = [rng.uniform(a, b) for a, b in zip(low, high)]
            if wall is not None:
                axis = 1 if turn % 2 == 0 else 0
                offset[axis] = (low if turn in (0, 3) else high)[axis]
                if align is not None:
                    offset[1 - axis] = max(low[1 - axis], min(high[1 - axis], align[1 - axis]))
            footprint = [bounds[a] + offset[a % 2] for a in range(4)]
            if any(_crosses(footprint, a, b, .45) for a, b in self.routes):
                continue
            if any(all(footprint[a] < r[a + 2] + .12 and footprint[a + 2] > r[a] - .12 for a in (0, 1)) for r in self.occupied):
                continue
            self._commit(items, rotated, offset, footprint, turn)
            return True
        return False

    def _commit(self, items, rotated, offset, footprint, turn):
        """Append the placed parts (scene boxes) and the object record."""
        scene, level, z = self.scene, self.room["level"], self.z
        ident, indices = len(scene["objects"]), []
        for part in rotated:
            indices.append(len(scene["boxes"]))
            tint = part["color"]
            scene["boxes"].append(dict(kind="furniture" if part["label"] not in ("toy", "floor_book", "boxes") else "prop",
                size=part["size"], center=[part["center"][0] + offset[0], part["center"][1] + offset[1], z + part["center"][2]],
                material=part["material"], level=level, object_id=ident, label=part["label"],
                **{key: part[key] for key in ("shape", "bevel", "profile", "axis", "facing", "path") if key in part},
                **({"color": tint} if tint else {})))
        scene["objects"].append(dict(id=ident, room=self.room["id"], level=level, kind=items[0][0],
            items=[dict(kind=name, offset=[px, py], turn=t) for name, px, py, t in items],
            center=[*offset, z], yaw=turn * math.pi / 2, bounds=footprint, parts=indices))
        self.occupied.append(footprint)


def _slots(cfg, purpose, variant, area):
    """Furniture slots of a room from config/furniture.toml: each slot lists alternative groups of items."""
    groups = cfg["groups_by_variant"].get(f"{purpose}/{variant}", cfg["groups"][purpose])
    # A slot is one group, or {any = [group, ...]}: alternatives tried in order until one is placed.
    slots = [entry["any"] if isinstance(entry, dict) else [entry] for entry in groups]
    slots = [[[it for it in map(settings.item, group) if not settings.disabled(it[0])] for group in slot] for slot in slots]
    slots = [slot for slot in ([group for group in slot if group] for slot in slots) if slot]
    if purpose in cfg["repeat"]["purposes"] and slots:
        copies = max(1, min(cfg["repeat"]["max"], int(area / cfg["repeat"]["area_per_copy"])))
        slots = [slots[0]] * copies + slots[1:]
    return slots


def _place_groups(space, slots, wall_order, free_kinds):
    """Place each slot's first fitting group; a TV faces the first group (e.g. the sofa) from the opposite wall."""
    primary_wall, primary_center = None, None
    for index, slot in enumerate(slots):
        for group in slot:
            tv = group[0][0] == "tv_stand" and primary_wall is not None
            opposite = (primary_wall + 2) % 4 if tv else None
            order = [opposite] + [w for w in wall_order if w != opposite] if tv else wall_order
            free = group[0][0] in free_kinds  # e.g. long tables: anywhere off the lanes, not against a wall
            # Free groups shed trailing items down to the first item and two more (a table never stands
            # without chairs); other groups fall back to their first item alone.
            variants = [group[:n] for n in range(len(group), min(len(group), 3) - 1, -1)] if free else \
                ((group, [group[0]]) if len(group) > 1 else (group,))
            wall = next((w for variant in variants for w in ([None] if free else order)
                         if space.place(variant, w, primary_center if tv and w == opposite else None)), False)
            if wall is not False:
                if index == 0:
                    primary_wall, primary_center = wall, space.scene["objects"][-1]["center"]
                break


def _place_singles(space, names):
    """Place single items against seeded walls; disabled kinds are skipped (their draw is kept)."""
    for name in names:
        if not settings.disabled(name):
            any(space.place([(name, 0, 0, 0)], wall) for wall in space.rng.sample(range(4), 4))


def furnish(scene):
    """Append physical parts and semantic instances; reserve 90 cm travel lanes."""
    if "objects" in scene:
        return scene
    scene["objects"], scene["clear_paths"] = [], []
    cfg = settings.current()["furniture"]  # config/furniture.toml
    for room in (s for s in scene["spaces"] if s["kind"] == "room"):
        rng = random.Random(f'{scene["floor_seeds"][room["level"]]}:furniture:{room["id"]}')
        space = _Room(scene, room, rng)
        x0, y0, x1, y1 = room["rect"]
        area = (x1 - x0) * (y1 - y0)
        # Labs: one in six is Lab D66 (variant "d66"), the others the aseptic lab ("lab_aseptic" tables).
        purpose = "lab_aseptic" if room["purpose"] == "lab" and room.get("variant") != "d66" else room["purpose"]
        wall_order = rng.sample(range(4), 4)
        _place_groups(space, _slots(cfg, purpose, room.get("variant"), area), wall_order, cfg["free"])
        # The "*" choices are drawn in every room (as before the settings existed), then the room's own list.
        fallback = [settings.pick(rng, v) for v in cfg["extras"]["*"]]
        _place_singles(space, [settings.pick(rng, v) for v in cfg["extras"][purpose]] if purpose in cfg["extras"] else fallback)
        scene["baseline_items"] = scene.get("baseline_items", 0) + sum(
            len(obj["items"]) for obj in scene["objects"] if obj["room"] == room["id"])
        if scene["config"].get("details", False):
            fill, density = cfg["fill"], cfg["density"]
            count = max(round(fill["min"] * density), min(round(fill["max"] * density), int(area / fill["area_per_item"] * density)))
            for _ in range(count):  # draw, then place, one at a time (the draw order is part of the seed contract)
                _place_singles(space, [rng.choice(fill["items"][purpose])])
    return scene
