"""Room-specific wall landmarks and supported clutter; never occupy reserved lanes."""
import math
import random

import settings
from furniture import PALETTE, _model, _rotate, _crosses
from geometry import rotated_axis
from styles import material_spec


def _bounds(parts):
    return [min(b["center"][a] - b["size"][a] / 2 for b in parts) for a in range(3)] + [
        max(b["center"][a] + b["size"][a] / 2 for b in parts) for a in range(3)]


def _overlaps(a, b, gap=.002):
    return all(a[i] < b[i + 3] + gap and a[i + 3] > b[i] - gap for i in range(3))


def _world(parts, origin, turn=0):
    result = []
    for part in parts:
        x, y = _rotate(*part["center"][:2], turn)
        size = part["size"][:]
        if turn % 2:
            size[0], size[1] = size[1], size[0]
        result.append(dict(part, size=size, axis=rotated_axis(part, turn),
                           facing=(part.get("facing", 0)+turn)%4,
                           center=[x + origin[0], y + origin[1], part["center"][2] + origin[2]]))
    return result


class _Details:
    """Shared state of enrich(): the scene, its occupied 3D bounds per storey, and object registration."""

    def __init__(self, scene):
        self.scene, self.boxes, self.objects = scene, scene["boxes"], scene["objects"]
        self.c, self.seed = scene["config"], scene["config"]["seed"]
        self.occupied = {level: [(i, _bounds([box])) for i, box in enumerate(self.boxes)
                                 if box["level"] == level and "object_id" in box] for level in range(self.c["floors"])}

    def free(self, bounds, level, skip=None):
        """True when bounds overlap no occupied part of the storey (except part index `skip`)."""
        return not any(_overlaps(bounds, b) for i, b in self.occupied[level] if i != skip)

    def register(self, parts, name, space, placement, parent=None):
        """Append the parts (textured, tagged) and their object record."""
        ident, indices = len(self.objects), []
        for part in parts:
            part = dict(part, kind="landmark" if placement == "wall" else "prop", level=space["level"],
                        object_id=ident, label=name)
            if part.get("color") is None:
                part.pop("color", None)
            if "texture" not in part and part["material"] != "glass":
                part["texture"] = material_spec(part["material"], self.seed)
                if part["material"] == "screen":
                    part["texture"]["seed"] += ident % 4
            indices.append(len(self.boxes))
            self.occupied[space["level"]].append((len(self.boxes), _bounds([part])))
            self.boxes.append(part)
        bound = _bounds(parts)
        self.objects.append(dict(id=ident, room=space["id"], level=space["level"], kind=name,
            items=[dict(kind=name, offset=[0, 0], turn=0)],
            center=[(bound[i] + bound[i + 3]) / 2 for i in range(3)], yaw=0,
            bounds=[bound[0], bound[1], bound[3], bound[4]], bounds3d=bound, parts=indices,
            placement=placement, detail=True, **({"parent_id": parent} if parent is not None else {})))


def _clutter(d):
    """Small objects on real horizontal supports (wood, lab worktops); never on monitors, books or other props."""
    c, boxes, cfg = d.c, d.boxes, settings.current()["clutter"]  # config/clutter.toml
    density = settings.current()["furniture"]["density"]
    supports = [(i, b) for i, b in enumerate(boxes[:]) if "object_id" in b and (b["material"] == "wood" or (
                b["material"] == "plastic" and b.get("label") in ("lab_desk", "lab_drawers", "lab_bench", "lab_white_desk", "fume_hood", "lab_solder_bench")))
                and b["size"][2] < .09 and min(b["size"][:2]) >= .25
                and b["center"][2] > b["level"] * c["storey"] + .35]
    for index, support in supports:
        parent = d.objects[support["object_id"]]
        room = d.scene["spaces"][parent["room"]]
        rng = random.Random(f"{d.seed}:clutter:{index}")
        top = support["center"][2] + support["size"][2] / 2
        area = support["size"][0] * support["size"][1]
        purpose = "lab_aseptic" if room.get("purpose") == "lab" and room.get("variant") != "d66" else room.get("purpose")
        names = cfg["items"].get(purpose, cfg["items"]["*"])
        slots = max(round(cfg["min"] * density), min(round(cfg["max"] * density), math.ceil(area * cfg["per_square_metre"] * density)))
        for slot in range(slots):
            for attempt in range(18):
                name = cfg["first"][support.get("label")] if slot == 0 and support.get("label") in cfg["first"] else rng.choice(names)
                if settings.disabled(name):
                    break
                turn = rng.randrange(4)
                parts = _model(name, rng.choice(PALETTE))
                dims = _bounds(_world(parts, [0, 0, 0], turn))
                low = [support["center"][a] - support["size"][a] / 2 - dims[a] + .025 for a in (0, 1)]
                high = [support["center"][a] + support["size"][a] / 2 - dims[a + 3] - .025 for a in (0, 1)]
                if any(a > b for a, b in zip(low, high)):
                    continue
                parts = _world(parts, [rng.uniform(a, b) for a, b in zip(low, high)] + [top + .004 - dims[2]], turn)
                bounds = _bounds(parts)
                if bounds[5] > (room["level"] + 1) * c["storey"] - c["slab"] - .08 or not d.free(bounds, room["level"], index):
                    continue
                d.register(parts, name, room, "surface", parent["id"])
                break


def _cables(d):
    """Loose static power leads under/along equipment, never across travel lanes."""
    for parent in d.objects[:]:
        if parent["kind"] not in ("desk", "workbench", "tv_stand", "washing_machine"):
            continue
        room = d.scene["spaces"][parent["room"]]
        rng = random.Random(f'{d.seed}:cable:{parent["id"]}')
        for attempt in range(12):
            turn = rng.randrange(4)
            origin = [parent["center"][0] + (rng.uniform(-1., 1.) if attempt else 0),
                      parent["center"][1] + (rng.uniform(-.8, .8) if attempt else 0), room["level"] * d.c["storey"] + .001]
            parts = _world(_model("cable", PALETTE[4]), origin, turn)
            bounds = _bounds(parts)
            footprint = [bounds[0], bounds[1], bounds[3], bounds[4]]
            if any(footprint[a] < room["rect"][a]+.10 or footprint[a+2] > room["rect"][a+2]-.10 for a in (0, 1)):
                continue
            if any(_crosses(footprint, a[:2], b[:2], path["width"]/2) for path in d.scene["clear_paths"]
                   if path["room"] == room["id"] for a, b in zip(path["points"], path["points"][1:])):
                continue
            if not d.free(bounds, room["level"]):
                continue
            d.register(parts, "cable", room, "floor", parent["id"])
            break


LANDMARK_SIZE = {"sign": (.46, .28), "art": (.72, .52), "notice": (.65, .65),
                 "vent": (.55, .22), "clock": (.34, .34), "switch": (.10, .16)}
LANDMARK_NAME = {"art": "painting", "notice": "noticeboard", "sign": "room_sign",
                 "vent": "air_vent", "switch": "light_switch", "clock": "wall_clock"}


def _landmark_parts(style, width, height, spec):
    """Wall-object parts in model coordinates (front +y): framed print, or vent, switch, clock."""
    if style not in ("vent", "switch", "clock"):
        return [dict(center=[0, 0, 0], size=[width, .05, height], material="wood", shape="bevel", bevel=.006),
                dict(center=[0, .028, 0], size=[width - .045, .006, height - .045], material="paper", color=[1, 1, 1, 1], texture=spec)]
    parts = [dict(center=[0, 0, 0], size=[width, .05, height], material="plastic", shape="bevel", bevel=.008, color=[.70, .70, .66, 1])]
    if style == "vent":
        parts.append(dict(center=[0, .028, 0], size=[width-.04, .008, height-.04], material="metal"))
        for i in range(6):
            parts.append(dict(center=[0, .038, -.075+i*.03], size=[width-.05, .018, .012],
                              material="metal", shape="bevel", bevel=.003, color=[.53, .54, .52, 1]))
    elif style == "switch":
        parts.append(dict(center=[0, .033, 0], size=[.05, .02, .095], material="plastic", shape="bevel", bevel=.004, color=[.81, .80, .76, 1]))
    else:
        parts[0].update(shape="lathe", axis=1, profile=[[1, -.5], [1, .5]])
        parts.append(dict(center=[0, .029, 0], size=[.302, .008, .302], material="paper",
                          shape="lathe", axis=1, profile=[[1, -.5], [1, .5]], color=[.89, .88, .83, 1]))
        for i in range(12):
            angle = i*math.pi/6
            parts.append(dict(center=[.13*math.sin(angle), .035, .13*math.cos(angle)], size=[.012, .006, .012], material="metal"))
        for x, zz, w, hh in ((0, .04, .009, .09), (.04, 0, .085, .009)):
            parts.append(dict(center=[x, .041, zz], size=[w, .006, hh], material="metal"))
    return parts


def _place_landmark(d, space, rng, wall_span, style, spec, lateral):
    """Try the style's mounting heights on one wall; True when a landmark was registered."""
    axis, u, fixed, inward, turn, bottom, top = wall_span
    width, height = LANDMARK_SIZE[style]
    elevations = {"switch": (1.1,), "vent": (2.35,), "clock": (2.05,)}.get(style, (1.55, 1.95))
    for elevation in rng.sample(elevations, len(elevations)):
        center_z = space["level"] * d.c["storey"] + elevation
        if center_z - height / 2 < bottom + .04 or center_z + height / 2 > top - .04:
            continue
        origin = [0., 0., center_z]
        origin[axis], origin[u] = fixed + inward * (d.c["wall"] / 2 + .029), lateral
        parts = _world(_landmark_parts(style, width, height, spec), origin, turn)
        bounds = _bounds(parts)
        if not d.free(bounds, space["level"]):
            continue
        # Avoid putting a landmark behind a tall wardrobe/bookcase.
        sight = bounds[:]
        if inward > 0:
            sight[axis + 3] += .6
        else:
            sight[axis] -= .6
        if any(_overlaps(sight, b, 0) for i, b in d.occupied[space["level"]]
               if d.boxes[i]["kind"] == "furniture" and d.boxes[i]["center"][2] + d.boxes[i]["size"][2] / 2 > bounds[2]):
            continue
        d.register(parts, LANDMARK_NAME[style], space, "wall")
        return True
    return False


def _landmarks(d):
    """Room signs, paintings, notices, vents, clocks and switches on full wall segments (never over openings)."""
    c, seed = d.c, d.seed
    walls = [b for b in d.boxes if b["kind"] == "wall"]
    for space in d.scene["spaces"]:
        rng = random.Random(f'{seed}:landmarks:{space["id"]}:{space["level"]}')
        number = f'F{space["level"] + 1}\nR{space["id"]:02d}'
        count = 0
        for axis, edge, inward, turn in ((1, 1, 1, 0), (0, 2, -1, 1), (1, 3, -1, 2), (0, 0, 1, 3)):
            u, fixed = 1 - axis, space["rect"][edge]
            for wall in walls:
                if wall["level"] != space["level"] or wall["size"][axis] > c["wall"] + .001 or abs(wall["center"][axis] - fixed) > .001:
                    continue
                lo = max(space["rect"][u], wall["center"][u] - wall["size"][u] / 2) + .13
                hi = min(space["rect"][u + 2], wall["center"][u] + wall["size"][u] / 2) - .13
                span = (axis, u, fixed, inward, turn, wall["center"][2] - wall["size"][2] / 2, wall["center"][2] + wall["size"][2] / 2)
                if hi - lo < .4:
                    continue
                slots = max(1, math.ceil((hi - lo) / 2.2))
                for slot in range(slots):
                    style = "sign" if count == 0 else ("art", "vent", "notice", "clock", "switch", "art")[(count + slot) % 6]
                    width = LANDMARK_SIZE[style][0]
                    if width > hi - lo:
                        continue
                    lateral = lo + (slot + .5) * (hi - lo) / slots + rng.uniform(-.1, .1)
                    lateral = max(lo + width / 2, min(hi - width / 2, lateral))
                    label = number if style == "sign" else f'{space.get("purpose", "HALL").upper()} {space["id"]:02d}-{slot}'
                    spec = dict(style=style, seed=seed + space["id"] * 65537 + count * 137 + slot, period=1., label=label)
                    count += _place_landmark(d, space, rng, span, style, spec, lateral)


def enrich(scene):
    """Add surface clutter, power cables and wall landmarks to a furnished scene, off the travel lanes."""
    d = _Details(scene)
    _clutter(d)
    _cables(d)
    _landmarks(d)
    objects = scene["objects"]
    total = sum(len(o["items"]) for o in objects)
    scene["detail_stats"] = dict(baseline_items=scene["baseline_items"], items=total,
        factor=round(total / max(1, scene["baseline_items"]), 3),
        wall_landmarks=sum(o.get("placement") == "wall" for o in objects),
        supported_props=sum(o.get("placement") == "surface" for o in objects),
        cables=sum(o["kind"] == "cable" for o in objects))
    return scene
