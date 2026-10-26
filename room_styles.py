"""Per-room style families: one identity, four finishes chosen from each room's use.

Families (STYLE_GUIDE.md, "Room style families"):
  corporate   today's restrained look: offices, meeting rooms, service rooms. Adds nothing.
  warm        warm paint and floor tint, walnut skirting and door architraves, dark window
              surrounds with a sill board, walnut/oak/charcoal furniture with one terracotta accent.
  wayfinding  the warm base plus a yellow band, a dark base line, yellow door architraves,
              a threshold plate with the room code and a pictogram sign beside the door.
  lab         two variants, 1 in 6 by construction (see LAB): 5 in 6 "aseptic" (white walls, light grey tile, cyan
              skirting, light grey frames; benches, fume hood, test tubes, glassware) and 1 in 6
              "d66", Lab D66, the robotics lab where PTG was born (its room sign reads "LAB D66"):
              white walls, grey vinyl-like floor, grey roller blinds, a 0.5 m tile ceiling with red
              cable reels where a ceiling exists, white desks on grey frames with dual monitors,
              cyan task chairs, a birch pegboard with robots, white cabinets.

Pipeline and determinism:
  furniture.assign_rooms -> assign_families(scene): converts at most one room per storey into a
      lab (seeded, the largest workshop/storage room) and stores space["style_family"]. It runs
      after every purpose and variant has been drawn, from its own RNG streams.
  indoor.generate -> apply_room_styles(scene): after details.enrich. Every finish part is
      APPENDED to scene["boxes"], so box indices (and the index-keyed clutter streams of
      details.enrich) of everything generated before stay the same.
A body carries one texture on every face and a wall is shared by two rooms, so per-room paint
lives on 3 mm skins on the room side of each wall segment (openings stay clear: segments already
stop at doors and windows). Wall landmarks start 4 mm in front of the wall face, in front of
the skins. New kinds ("wall_finish", "frame") are not architecture for tools/baseline.py.
"""
import math
import os
import random
import settings

# PTG_ROOM_STYLES=0/1 overrides the default (tests, A/B figures); tools may also toggle it at run time.
ENABLED = os.environ.get("PTG_ROOM_STYLES", "1") != "0"  # on by default; PTG_ROOM_STYLES=0 restores the pre-family look
SKIN = .003          # wall_finish skin thickness on the room side of a wall face
FAMILIES = ("corporate", "warm", "wayfinding", "lab")
# purpose -> {variant or "*": family, or a list of families drawn with a per-room seeded choice}, and the lab
# conversion (candidates, min_side, probability, cycle: one lab in `cycle` is Lab D66): config/rooms.toml,
# [rooms.styles] and [rooms.labs]. RULES and LAB are the shipped defaults; generation reads settings.current().
RULES = settings.defaults()["rooms"]["styles"]
LAB = settings.defaults()["rooms"]["labs"]

WALNUT, OAK, CHARCOAL, BLACK = (.47, .31, .22), (.78, .62, .43), (.26, .28, .30), (.13, .13, .14)
ACCENT, CREAM, DARK, YELLOW = (.82, .45, .32), (.93, .89, .81), (.17, .16, .15), (.90, .68, .16)
CYAN, LIGHT_GREY, LAB_WHITE = (.22, .64, .72), (.80, .82, .83), (.92, .93, .93)
FABRICS = ((.26, .28, .30), (.34, .40, .47), (.60, .55, .48), (.36, .42, .33))
FINISH = {
    "warm": dict(wall=(.90, .86, .82), planks=(.68, .50, .33), tile=(.74, .70, .64), skirting=("wood", WALNUT),
                 door=("wood", WALNUT), window=("metal", DARK)),
    "wayfinding": dict(wall=(.90, .87, .83), planks=(.68, .50, .33), tile=(.74, .70, .64), skirting=("plastic", DARK),
                       door=("plastic", YELLOW), window=("metal", DARK), band=YELLOW),
    "lab": dict(wall=(.93, .94, .94), planks=None, tile=(.83, .84, .84), skirting=("plastic", CYAN),
                door=("plastic", LIGHT_GREY), window=("plastic", LIGHT_GREY)),               # aseptic variant
    "lab_d66": dict(wall=(.95, .95, .94), planks=None, tile=(.55, .56, .57), skirting=("plastic", (.70, .71, .72)),
                    door=("plastic", LIGHT_GREY), window=("plastic", LAB_WHITE)),
}
CASE = ("bookcase", "cabinet", "tv_stand", "basket", "crate", "boxes", "bed")


def family_for(purpose, variant, rng):
    """Style family of a room purpose and variant from the active settings (seeded when a list)."""
    rule = settings.current()["rooms"]["styles"].get(purpose, {})
    choice = rule.get(variant, rule.get("*", "corporate"))
    return rng.choice(choice) if isinstance(choice, (tuple, list)) else choice


def assign_families(scene):
    """Seeded lab conversion (largest candidate room per storey) and a style family per space."""
    if not ENABLED:
        return scene
    LAB = settings.current()["rooms"]["labs"]
    for level, seed in enumerate(scene["floor_seeds"]):
        rooms = [s for s in scene["spaces"] if s["level"] == level and s["kind"] == "room"]
        rng = random.Random(f"{seed}:lab")
        candidates = [s for s in rooms if s.get("purpose") in LAB["candidates"] and
                      min(s["rect"][2] - s["rect"][0], s["rect"][3] - s["rect"][1]) >= LAB["min_side"]]
        if candidates and rng.random() < LAB["probability"]:
            lab = max(candidates, key=lambda s: ((s["rect"][2] - s["rect"][0]) * (s["rect"][3] - s["rect"][1]), -s["id"]))
            lab.update(purpose="lab")
        for space in scene["spaces"]:
            if space["level"] == level:
                pick = random.Random(f'{seed}:room_style:{space["id"]}')
                space["style_family"] = family_for(space.get("purpose"), space.get("variant"), pick) \
                    if space["kind"] == "room" else "corporate"
    offset = random.Random(f'{scene["config"]["seed"]}:lab_d66').randrange(LAB["cycle"])
    labs = sorted((s for s in scene["spaces"] if s.get("purpose") == "lab"), key=lambda s: (s["level"], s["id"]))
    for i, lab in enumerate(labs):
        lab["variant"] = "d66" if (offset + i) % LAB["cycle"] == 0 else "aseptic"
    return scene


# ---------------------------------------------------------------- finish geometry


def _lo_hi(b):
    return ([b["center"][a] - b["size"][a] / 2 for a in range(3)], [b["center"][a] + b["size"][a] / 2 for a in range(3)])


def _room_faces(scene, room, kinds=("wall",)):
    """(box, thin axis, edge value, inward sign, clipped [u0, u1]) for each wall on the room's edges."""
    c = scene["config"]
    x0, y0, x1, y1 = room["rect"]
    edges = ((1, y0, 1), (1, y1, -1), (0, x0, 1), (0, x1, -1))
    out = []
    for b in scene["boxes"]:
        if b["kind"] not in kinds or b["level"] != room["level"]:
            continue
        thin = 0 if b["size"][0] < b["size"][1] else 1
        along = 1 - thin
        lo, hi = _lo_hi(b)
        for axis, value, inward in edges:
            if axis != thin or abs(b["center"][thin] - value) > .01:
                continue
            u0 = max(lo[along], room["rect"][along] + c["wall"] / 2)
            u1 = min(hi[along], room["rect"][along + 2] - c["wall"] / 2)
            if u1 - u0 > .02:
                out.append((b, thin, value, inward, u0, u1))
    return out


def _part(kind, material, color, center, size, spec=None, **extra):
    part = dict(kind=kind, material=material, color=[*color[:3], 1], center=center, size=size, **extra)
    if spec:
        part["texture"] = spec
    return part


def _slab(thin, value, offset, depth, u0, u1, z0, z1):
    """Box on a wall face: `offset` from the wall plane toward the room (signed), `depth` thick."""
    center, size = [0., 0., (z0 + z1) / 2], [0., 0., z1 - z0]
    center[thin], size[thin] = value + offset, abs(depth)
    center[1 - thin], size[1 - thin] = (u0 + u1) / 2, u1 - u0
    return center, size


def _specs(seed):
    from styles import material_spec
    return dict(plaster=dict(style="plaster", seed=seed, period=2., label=""), tile=dict(style="tile", seed=seed, period=2., label=""),
                wood=material_spec("wood", seed), plastic=material_spec("plastic", seed), metal=material_spec("metal", seed),
                fabric=material_spec("fabric", seed))


def _recolor(scene, room, family):
    """Furniture palette of the family; texture specs stay shared, only tints change."""
    rng = random.Random(f'{scene["floor_seeds"][room["level"]]}:room_fabric:{room["id"]}')
    fabric = rng.choice(FABRICS)
    ids = {o["id"] for o in scene.get("objects", ()) if o["room"] == room["id"]}
    for b in scene["boxes"]:
        if b.get("object_id") not in ids:
            continue
        if family == "lab" and room.get("variant") == "d66":
            _lab_textures(b)
        if b.get("texture", {}).get("style") in ("art", "notice", "sign", "screen"):
            continue
        label, mat = b.get("label", ""), b["material"]
        if family == "lab":
            new = {"wood": LIGHT_GREY if not label.startswith("lab_") else None,
                   "plastic": LAB_WHITE if not label.startswith("lab_") else None,
                   "fabric": CYAN if not label.startswith("lab_") else None}.get(mat)
        else:
            new = {"wood": WALNUT if label in CASE else OAK, "metal": BLACK,
                   "fabric": CREAM if label == "lamp" else fabric,
                   "ceramic": ACCENT if label in ("plant", "vase") else None, "leaf": (.24, .40, .20)}.get(mat)
        if new:
            alpha = b.get("color", [1, 1, 1, 1])[3]
            b["color"] = [*new, alpha]


def _lab_textures(b):
    """Lab D66 Easter egg and printed parts: room sign, pegboard hole grid, space poster."""
    label, texture = b.get("label", ""), b.get("texture", {})
    if label == "room_sign" and texture.get("style") == "sign":
        b["texture"] = dict(style="sign", seed=0, period=1., label="LAB\nD66")
    elif label in ("lab_pegboard", "lab_solder_bench") and min(b["size"][:2]) < .03 and b["material"] in ("wood", "plastic") \
            and b["size"][2] > .5:
        b["texture"] = dict(texture, lab_texture="pegboard")
    elif label == "lab_pegboard" and b["material"] == "paper":
        b["texture"] = dict(style="sign", seed=0, period=1., label="", lab_texture="poster")


def _lab_extras(scene, room, specs):
    """Grey roller blinds over the top of each window; tile ceiling layer and cable reels under a ceiling."""
    from indoor import CEILING_SKIN
    c, z = scene["config"], room["level"] * scene["config"]["storey"]
    face, parts = c["wall"] / 2 + SKIN, []
    for glass, thin, value, inward, u0, u1 in _room_faces(scene, room, ("glass",)):
        lo, hi = _lo_hi(glass)
        gu0, gu1, top = lo[1 - thin], hi[1 - thin], hi[2]
        drop = .45 * (hi[2] - lo[2])
        center, size = _slab(thin, value, inward * (face + .035), .008, gu0 - .04, gu1 + .04, top - drop, top + .02)
        parts.append(_part("wall_finish", "fabric", (.47, .48, .50), center, size, dict(specs["fabric"]), room=room["id"], role="blind"))
        center, size = _slab(thin, value, inward * (face + .045), .05, gu0 - .06, gu1 + .06, top + .02, top + .08)
        parts.append(_part("wall_finish", "plastic", (.86, .87, .87), center, size, dict(specs["plastic"]), room=room["id"], role="blind_box",
                           shape="bevel", bevel=.006))
    x0, y0, x1, y1 = room["rect"]
    skin = next((b for b in scene["boxes"] if b["kind"] == "ceiling" and b["level"] == room["level"] + 1 and
                 abs(b["size"][2] - CEILING_SKIN) < 1e-9 and abs(b["center"][0] - (x0 + x1) / 2) < .01 and
                 abs(b["center"][1] - (y0 + y1) / 2) < .01), None)
    roofed = c.get("roof") and room["level"] == c["floors"] - 1  # the roof slab is the ceiling of the top storey
    if skin is None and not roofed:
        return parts
    under = skin["center"][2] - skin["size"][2] / 2 if skin else (room["level"] + 1) * c["storey"] - c["slab"]
    w = c["wall"] / 2
    parts.append(_part("wall_finish", "plastic", (.95, .95, .94), [(x0 + x1) / 2, (y0 + y1) / 2, under - .0015],
                       [x1 - x0 - 2 * w, y1 - y0 - 2 * w, .003], dict(specs["tile"]), room=room["id"], role="ceiling_tiles", ceiling=True))
    long = 0 if x1 - x0 >= y1 - y0 else 1
    for t in (1 / 3, 2 / 3):  # cable reels on the room's long centre line
        p = [(x0 + x1) / 2, (y0 + y1) / 2]
        p[long] = (x0, y0)[long] + t * ((x1, y1)[long] - (x0, y0)[long])
        reel = [.22, .22, .22]
        reel[1 - long] = .10
        parts.append(_part("fixture", "plastic", (.72, .14, .12), [*p, under - .145], reel, dict(specs["plastic"]), room=room["id"],
                           role="cable_reel", ceiling=True, shape="lathe", axis=1 - long, profile=[[1, -.5], [1, .5]]))
        parts.append(_part("fixture", "metal", BLACK, [*p, under - .0175], [.02, .02, .035], dict(specs["metal"]), room=room["id"],
                           role="reel_hanger", ceiling=True))
        bottom = z + 2.20
        parts.append(_part("fixture", "plastic", BLACK, [*p, (under - .255 + bottom) / 2], [.012, .012, under - .255 - bottom],
                           dict(specs["plastic"]), room=room["id"], role="reel_cable", ceiling=True, shape="lathe", profile=[[1, -.5], [1, .5]]))
        parts.append(_part("fixture", "plastic", BLACK, [*p, bottom - .06], [.035, .035, .12], dict(specs["plastic"]), room=room["id"],
                           role="reel_plug", ceiling=True, shape="bevel", bevel=.005))
    return parts


def apply_room_styles(scene):
    """Append skins, skirting, bands, frames, plates and signs; recolour floors and furniture."""
    if not ENABLED or not scene["config"].get("details", False):
        return scene
    c, seed = scene["config"], scene["config"]["seed"]
    specs = _specs(seed)
    new, counts = [], {f: 0 for f in FAMILIES}
    for room in [s for s in scene["spaces"] if s["kind"] == "room"]:
        family = room.get("style_family", "corporate")
        counts[family] += 1
        if family == "corporate":
            continue
        d66 = family == "lab" and room.get("variant") == "d66"
        finish, z = FINISH["lab_d66" if d66 else family], room["level"] * c["storey"]
        face = c["wall"] / 2
        for floor in (b for b in scene["boxes"] if b["kind"] == "floor" and b["level"] == room["level"] and
                      abs(b["center"][0] - (room["rect"][0] + room["rect"][2]) / 2) < .01 and
                      abs(b["center"][1] - (room["rect"][1] + room["rect"][3]) / 2) < .01):
            if d66:  # grey, joint-free vinyl look: the shared plaster image, grey tint
                floor["texture"], room["appearance"] = dict(specs["plaster"]), dict(room.get("appearance", {}), floor="vinyl")
            elif family == "lab":
                floor["texture"], room["appearance"] = dict(specs["tile"]), dict(room.get("appearance", {}), floor="tile")
            style = floor.get("texture", {}).get("style", "tile")
            floor["color"] = [*(finish.get(style) or finish["tile"]), 1]
        for wall, thin, value, inward, u0, u1 in _room_faces(scene, room):
            lo, hi = _lo_hi(wall)
            center, size = _slab(thin, value, inward * (face + SKIN / 2), SKIN, u0, u1, lo[2], hi[2])
            new.append(_part("wall_finish", "wall", finish["wall"], center, size, dict(specs["plaster"]), room=room["id"], role="skin"))
            if abs(lo[2] - z) < 1e-6:  # skirting / base line on segments that reach the floor
                material, color = finish["skirting"]
                center, size = _slab(thin, value, inward * (face + SKIN + .006), .012, u0, u1, z, z + .085)
                new.append(_part("wall_finish", material, color, center, size, dict(specs[material]), room=room["id"], role="skirting"))
            if "band" in finish and lo[2] <= z + 1.05 and hi[2] >= z + 1.17:
                center, size = _slab(thin, value, inward * (face + SKIN + .002), .004, u0, u1, z + 1.05, z + 1.17)
                new.append(_part("wall_finish", "plastic", finish["band"], center, size, dict(specs["plastic"]), room=room["id"], role="band"))
        new += _frames(scene, room, finish, specs)
        if d66:
            new += _lab_extras(scene, room, specs)
        if family == "wayfinding" and c.get("furnished", True):  # signs are landmarks: furnished scenes only, like details.enrich
            new += _wayfinding_signs(scene, room, specs)
        _recolor(scene, room, family)
    for part in new:  # storey of the room: floor cutaways and X-ray treat finishes like the room;
        # ceiling-mounted parts belong to the storey above, like the slab and its plaster skin.
        part["level"] = scene["spaces"][part["room"]]["level"] + (1 if part.get("ceiling") else 0)
    start = len(scene["boxes"])
    scene["boxes"].extend(new)
    _register_signs(scene, start)
    scene.setdefault("style", {})["room_families"] = dict(counts=counts, rules={p: {v: list(f) if isinstance(f, tuple) else f
                                                         for v, f in r.items()} for p, r in settings.current()["rooms"]["styles"].items()},
                                                         lab={k: list(v) if isinstance(v, tuple) else v
                                                              for k, v in settings.current()["rooms"]["labs"].items()})
    return scene


def _portal_faces(scene, room):
    """(portal, axis of the wall plane, wall value, inward sign, centre along the wall) for the room's doors."""
    out = []
    x0, y0, x1, y1 = room["rect"]
    for portal in scene["portals"]:
        if room["id"] not in portal["rooms"]:
            continue
        along, thin = portal["axis"], 1 - portal["axis"]
        value = portal["center"][thin]
        inward = 1 if abs(value - (x0, y0)[thin]) < .01 else -1 if abs(value - (x1, y1)[thin]) < .01 else 0
        if inward:
            out.append((portal, thin, value, inward, portal["center"][along]))
    return out


def _outside(scene, room, portal):
    """The space on the other side of a door, if it is circulation (corridor/landing), else None."""
    other = scene["spaces"][next(r for r in portal["rooms"] if r != room["id"])]
    return other if other["kind"] != "room" else None


def _frames(scene, room, finish, specs):
    """Door architraves and window surrounds on the room face, entirely outside the openings.
    Wayfinding rooms also frame the corridor side of their corridor doors (rooms own no other face)."""
    c, z = scene["config"], room["level"] * scene["config"]["storey"]
    face, parts, w = c["wall"] / 2 + SKIN, [], .07
    material, color = finish["door"]
    for portal, thin, value, inward, u in _portal_faces(scene, room):
        half, top = portal["width"] / 2, z + portal["height"]
        sides = [(inward, face)] + ([(-inward, c["wall"] / 2)] if "band" in finish and _outside(scene, room, portal) else [])
        for sign, plane in sides:
            for u0, u1, z0, z1 in ((u - half - w, u - half, z, top), (u + half, u + half + w, z, top),
                                   (u - half - w, u + half + w, top, top + w)):
                center, size = _slab(thin, value, sign * (plane + .01), .02, u0, u1, z0, z1)
                parts.append(_part("frame", material, color, center, size, dict(specs[material]), room=room["id"],
                                   role="door" if sign == inward else "door_outside", shape="bevel", bevel=.004))
    material, color = finish["window"]
    for glass, thin, value, inward, u0, u1 in _room_faces(scene, room, ("glass",)):
        lo, hi = _lo_hi(glass)
        gu0, gu1 = lo[1 - thin], hi[1 - thin]
        for a0, a1, z0, z1, depth, off in ((gu0 - .06, gu0, lo[2], hi[2], .02, .01), (gu1, gu1 + .06, lo[2], hi[2], .02, .01),
                                           (gu0 - .06, gu1 + .06, hi[2], hi[2] + .06, .02, .01),
                                           (gu0 - .08, gu1 + .08, lo[2] - .03, lo[2], .05, .025)):
            center, size = _slab(thin, value, inward * (face + off), depth, a0, a1, z0, z1)
            parts.append(_part("frame", material, color, center, size, dict(specs[material]), room=room["id"], role="window",
                               shape="bevel", bevel=.004))
    return parts


def _wayfinding_signs(scene, room, specs):
    """Threshold plate (room code) just inside each door; a pictogram sign on the CORRIDOR side of the
    first corridor door, where it is seen while navigating (room-to-room doors get no sign)."""
    c, z = scene["config"], room["level"] * scene["config"]["storey"]
    code = f'R{room["id"]:02d}'
    parts = []
    walls = _room_faces(scene, room)
    signed = False
    for portal, thin, value, inward, u in _portal_faces(scene, room):
        outside = _outside(scene, room, portal)
        near = {room["id"], outside["id"] if outside else room["id"]}
        obstacles = [_lo_hi(b) for b in scene["boxes"] if b.get("object_id") is not None and
                     scene["objects"][b["object_id"]]["room"] in near]
        along = 1 - thin
        center, size = [0., 0., z + .001], [0., 0., .002]
        center[thin], size[thin] = value + inward * (c["wall"] / 2 + .17), .30
        center[along], size[along] = u, portal["width"]
        parts.append(_part("landmark", "paper", (1, 1, 1), center, size,
                           dict(style="sign", seed=0, period=1., label=f'{code} {room["purpose"].upper()}', plate=True),
                           room=room["id"], role="door_plate", print_up=[thin, -inward]))  # text reads toward the door
        if signed or not outside:
            continue
        out = -inward  # the sign faces the corridor
        for side in (-1, 1):
            su = u + side * (portal["width"] / 2 + .07 + .06 + .20)
            sz = z + 1.55
            if not any(wall[0]["center"][2] - wall[0]["size"][2] / 2 <= sz - .25 and wall[0]["center"][2] + wall[0]["size"][2] / 2 >= sz + .25
                       and wall[4] <= su - .22 and wall[5] >= su + .22 and abs(wall[2] - value) < .01 for wall in walls):
                continue
            board_c, board_s = _slab(thin, value, out * (c["wall"] / 2 + .004 + .015), .03, su - .20, su + .20, sz - .20, sz + .20)
            lo = [board_c[a] - board_s[a] / 2 for a in range(3)]
            hi = [board_c[a] + board_s[a] / 2 for a in range(3)]
            sight_lo, sight_hi = lo[:], hi[:]
            if out > 0:
                sight_hi[thin] += .6
            else:
                sight_lo[thin] -= .6
            if any(all(sight_lo[a] < h[a] and sight_hi[a] > l[a] for a in range(3)) for l, h in obstacles):
                continue
            face_c, face_s = _slab(thin, value, out * (c["wall"] / 2 + .004 + .032), .004, su - .18, su + .18, sz - .18, sz + .18)
            parts.append(_part("landmark", "metal", (.15, .15, .16), board_c, board_s, dict(specs["metal"]), room=room["id"],
                               role="pictogram_board", shape="bevel", bevel=.006))
            parts.append(_part("landmark", "paper", (1, 1, 1), face_c, face_s,
                               dict(style="sign", seed=0, period=1., label=code, pictogram=room["purpose"]),
                               room=room["id"], role="pictogram_face"))
            signed = True
            break
    return parts


def _register_signs(scene, start):
    """Semantic instances for the wayfinding parts (unmapped in COCO), appended after all others."""
    objects = scene.setdefault("objects", [])
    groups = {}
    for i in range(start, len(scene["boxes"])):
        b = scene["boxes"][i]
        if b["kind"] != "landmark":
            continue
        key = (b["room"], "pictogram_sign") if b["role"].startswith("pictogram") else (b["room"], f"door_plate_{i}")
        groups.setdefault(key, []).append(i)
    for (room, name), indices in groups.items():
        ident = len(objects)
        lows, highs = zip(*(_lo_hi(scene["boxes"][i]) for i in indices))
        bound = [min(v[a] for v in lows) for a in range(3)] + [max(v[a] for v in highs) for a in range(3)]
        kind = "pictogram_sign" if name == "pictogram_sign" else "door_plate"
        for i in indices:
            scene["boxes"][i].update(object_id=ident, label=kind)
        space = scene["spaces"][room]
        objects.append(dict(id=ident, room=room, level=space["level"], kind=kind, items=[dict(kind=kind, offset=[0, 0], turn=0)],
                            center=[(bound[a] + bound[a + 3]) / 2 for a in range(3)], yaw=0, bounds=[bound[0], bound[1], bound[3], bound[4]],
                            bounds3d=bound, parts=indices, placement="wall" if kind == "pictogram_sign" else "floor", detail=True))


# ---------------------------------------------------------------- pictogram texture (surfaces._texture branch)


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def sign_texture(spec):
    """Room style images: wayfinding pictogram sign and door plate; Lab D66 pegboard and poster."""
    from PIL import Image, ImageDraw
    n = 512
    image = Image.new("RGB", (n, n), (34, 38, 42))
    draw = ImageDraw.Draw(image)
    yellow = tuple(int(v * 255) for v in YELLOW)
    if spec.get("lab_texture") == "pegboard":  # neutral birch board, 25 mm hole grid (period 0.6 m = 24 holes)
        image = Image.new("RGB", (n, n), (238, 238, 238))
        draw = ImageDraw.Draw(image)
        rng = random.Random(7)
        for _ in range(3000):
            x, y, v = rng.randrange(n), rng.randrange(n), rng.randint(228, 246)
            draw.point((x, y), fill=(v, v, v))
        for i in range(24):
            for j in range(24):
                cx, cy = (i + .5) * n / 24, (j + .5) * n / 24
                draw.ellipse((cx - 3.2, cy - 3.2, cx + 3.2, cy + 3.2), fill=(70, 70, 70))
        return image
    if spec.get("lab_texture") == "poster":  # dark framed space poster: stars, Martian horizon, rover
        image = Image.new("RGB", (n, n), (14, 14, 18))
        draw = ImageDraw.Draw(image)
        rng = random.Random(66)
        for _ in range(160):
            x, y, r = rng.randrange(n), rng.randrange(300), rng.choice((1, 1, 2))
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(220, 220, 230))
        draw.ellipse((-200, 330, n + 200, 900), fill=(120, 62, 40))
        draw.rectangle((150, 300, 330, 360), fill=(232, 232, 228))
        draw.rectangle((290, 220, 302, 300), fill=(232, 232, 228))
        draw.rectangle((270, 200, 330, 228), fill=(232, 232, 228))
        for x in (165, 240, 315):
            draw.ellipse((x - 26, 360, x + 26, 412), fill=(70, 70, 74), outline=(200, 200, 200), width=4)
        draw.rectangle((0, 0, n - 1, n - 1), outline=(40, 40, 44), width=14)
        return image
    if spec.get("plate"):
        image = Image.new("RGB", (n, n // 4), yellow)  # 4:1, close to the 1.0 x 0.30 m plate
        draw = ImageDraw.Draw(image)
        draw.rectangle((6, 6, n - 6, n // 4 - 6), outline=(34, 38, 42), width=6)
        draw.text((n / 2, n // 8), spec["label"], fill=(34, 38, 42), font=_font(56), anchor="mm")
        return image
    draw.rectangle((0, 0, n, 150), fill=yellow)
    draw.text((n / 2, 78), spec["label"], fill=(34, 38, 42), font=_font(104), anchor="mm")
    purpose, ink = spec.get("pictogram", ""), (240, 236, 226)
    x0, y0, x1, y1 = 130, 185, 382, 395
    w, h = x1 - x0, y1 - y0
    if purpose == "living":  # sofa
        draw.rounded_rectangle((x0 + .12 * w, y0 + .25 * h, x1 - .12 * w, y0 + .62 * h), int(.06 * w), fill=ink)
        draw.rounded_rectangle((x0, y0 + .45 * h, x1, y0 + .80 * h), int(.06 * w), fill=ink)
        for lx in (x0 + .12 * w, x1 - .22 * w):
            draw.rectangle((lx, y0 + .80 * h, lx + .10 * w, y0 + .92 * h), fill=ink)
    elif purpose == "office":  # monitor on a desk
        draw.rectangle((x0 + .20 * w, y0 + .10 * h, x1 - .20 * w, y0 + .50 * h), outline=ink, width=14)
        draw.rectangle((x0 + .45 * w, y0 + .50 * h, x1 - .45 * w, y0 + .62 * h), fill=ink)
        draw.rectangle((x0, y0 + .62 * h, x1, y0 + .70 * h), fill=ink)
        for lx in (x0 + .05 * w, x1 - .12 * w):
            draw.rectangle((lx, y0 + .70 * h, lx + .07 * w, y0 + .98 * h), fill=ink)
    else:  # initial letter for purposes without a drawn pictogram
        draw.text(((x0 + x1) / 2, (y0 + y1) / 2), purpose[:1].upper(), fill=ink, font=_font(int(h * .8)), anchor="mm")
    draw.text((n / 2, 450), purpose.upper(), fill=ink, font=_font(46), anchor="mm")
    return image


# ---------------------------------------------------------------- seed 66: Lab D66 itself (Easter egg)

LAB_D66_SEED = 66
D66_SIZE = (9.0, 8.6)               # room, metres (x east, y north); the lab's floor plan, roughly square
D66_CORRIDOR = (1.8, 2.0)           # corridor stub outside the door, so the doorway leads somewhere walkable
D66_DOOR_Y = 2.2                    # door centre on the west wall (lower part of the sketch's west side)
D66_WINDOWS_Y = (2.0, 4.3, 6.6)     # east wall, facing the door (photos: blinds opposite the entrance)
# (model, wall or None, along-wall position or (x, y), turn for free-standing items)
D66_LAYOUT = [
    ("lab_solder_bench", "N", 1.40, None), ("lab_tv", "N", 5.90, None),
    ("lab_printer", "W", 3.30, None), ("lab_cupboard", "W", 4.52, None), ("lab_cupboard", "W", 5.54, None),
    ("lab_cabinet", "S", .66, None), ("lab_cabinet", "S", 1.69, None),
    ("lab_pegboard", "S", 4.60, None), ("lab_pegboard", "S", 7.05, None),
    ("lab_rolling_drawers", "S", 4.05, None), ("lab_rolling_drawers", "S", 6.45, None),
    ("lab_drawers", "E", 1.10, None),
    ("lab_desk", None, (5.40, 4.75), 0), ("lab_desk", None, (7.00, 4.75), 0),
    ("lab_desk", None, (5.40, 3.95), 2), ("lab_desk", None, (7.00, 3.95), 2),
    ("lab_chair", None, (4.75, 5.52), 2), ("lab_chair", None, (6.20, 5.52), 2), ("lab_chair", None, (7.65, 5.52), 2),
    ("lab_chair", None, (5.40, 3.18), 0), ("lab_chair", None, (7.00, 3.18), 0), ("lab_chair", None, (1.30, 7.55), 0),
    ("lab_mat", None, (1.40, 3.60), 0), ("lab_bin", None, (8.30, 2.60), 0),
]
WALL_TURN = dict(S=0, N=2, W=3, E=1)  # model front (+y) faces into the room


def lab_d66_scene(c):
    """Seed 66: one room, Lab D66 (the lab's floor plan), plus a corridor stub; full scene schema.

    rooms, floors, width and depth are replaced (1 room, 1 storey, the lab's size); the effective
    configuration is exported in scene["config"]. roof, furnished and details behave as usual.
    """
    import dataclasses
    W, D = D66_SIZE
    c = dataclasses.replace(c, rooms=1, floors=1, width=W, depth=D)
    cw, ch = D66_CORRIDOR
    scene = dict(config=dataclasses.asdict(c), spaces=[], portals=[], stairs=[], boxes=[], loop_routes=[], floor_seeds=[c.seed],
                 easter_egg="Lab D66: the robotics lab where PTG was born (seed 66 builds only this room)")
    if settings.signature():  # non-default config/ settings: record which (reproducibility)
        scene["settings"] = settings.signature()
    room = dict(id=0, kind="room", level=0, rect=[0., 0., W, D], purpose="lab", variant="d66", style_family="lab")
    corridor = dict(id=1, kind="corridor", level=0, rect=[-cw, D66_DOOR_Y - ch / 2, 0., D66_DOOR_Y + ch / 2], style_family="corporate")
    scene["spaces"] = [room, corridor]
    _d66_shell(scene, c, corridor["rect"])
    scene["portals"] = [dict(rooms=[0, 1], center=[0., D66_DOOR_Y, 0.], axis=1, width=c.door_width, height=c.door_height)]
    scene["spawn"] = [3.0, 2.8, .55]
    scene["bounds"] = [-cw, 0., W, D]
    _d66_finish(scene, c)
    return scene


def _d66_shell(scene, c, corridor_rect):
    """Floors, walls with the door and windows, glass and ceilings of Lab D66 and its corridor stub."""
    W, D = D66_SIZE
    cw = D66_CORRIDOR[0]
    wall_h, t = c.storey - c.slab, c.wall
    boxes = scene["boxes"]

    def box(kind, size, center, material=None, level=0):
        if min(size) > 1e-7:
            boxes.append(dict(kind=kind, size=list(size), center=list(center), level=level, material=material or kind))
            if kind == "floor":
                boxes[-1]["collision_size"] = [size[0] + .002, size[1] + .002, size[2]]

    def wall(axis, fixed, lo, hi, z0=0., z1=wall_h):  # axis: 0 = wall runs along x at y = fixed, 1 = along y at x = fixed
        if axis == 0:
            size, center = [hi - lo, t, z1 - z0], [(lo + hi) / 2, fixed, (z0 + z1) / 2]
        else:
            size, center = [t, hi - lo, z1 - z0], [fixed, (lo + hi) / 2, (z0 + z1) / 2]
        box("wall", size, center)

    for s in scene["spaces"]:
        x0, y0, x1, y1 = s["rect"]
        box("floor", (x1 - x0, y1 - y0, c.slab), ((x0 + x1) / 2, (y0 + y1) / 2, -c.slab / 2))
    wall(0, 0., 0., W)
    wall(0, D, 0., D)
    d0, d1 = D66_DOOR_Y - c.door_width / 2, D66_DOOR_Y + c.door_width / 2
    wall(1, 0., 0., d0)
    wall(1, 0., d1, D)
    wall(1, 0., d0, d1, c.door_height, wall_h)
    edges = [0.]
    for y in D66_WINDOWS_Y:
        w0, w1 = y - c.window_width / 2, y + c.window_width / 2
        wall(1, W, edges[-1], w0)
        wall(1, W, w0, w1, 0., c.sill)
        wall(1, W, w0, w1, c.sill + c.window_height, wall_h)
        box("glass", (.02, w1 - w0, c.window_height), (W, y, c.sill + c.window_height / 2))
        edges.append(w1)
    wall(1, W, edges[-1], D)
    cy0, cy1 = corridor_rect[1], corridor_rect[3]
    wall(0, cy0, -cw, 0.)
    wall(0, cy1, -cw, 0.)
    wall(1, -cw, cy0, cy1)
    if c.roof:
        for s in scene["spaces"]:
            x0, y0, x1, y1 = s["rect"]
            box("ceiling", (x1 - x0, y1 - y0, c.slab), ((x0 + x1) / 2, (y0 + y1) / 2, c.storey - c.slab / 2), "wall", level=1)


def _d66_finish(scene, c):
    """Furniture, details, room styles, coplanar gaps, semantics and geometry stats, as in indoor.generate."""
    if c.furnished:
        _d66_furnish(scene, c)
    if c.details:
        from surfaces import decorate_materials
        decorate_materials(scene)
        if c.furnished:
            from details import enrich
            enrich(scene)
    apply_room_styles(scene)
    from geometry import separate_coplanar  # a 5 mm gap between coplanar faces: no z-fighting
    separate_coplanar(scene)
    from styles import PROFILE
    scene.setdefault("style", dict(PROFILE))
    from semantics import annotate
    annotate(scene)
    from geometry import geometry_stats
    scene["geometry_stats"] = geometry_stats(scene)


def _d66_furnish(scene, c):
    """Place D66_LAYOUT with the library models and record objects and the door lane like furniture.furnish."""
    from furniture import _model
    from details import _world
    W, D = D66_SIZE
    face = c.wall / 2
    scene["objects"], boxes = [], scene["boxes"]
    for name, wall, where, turn in D66_LAYOUT:
        turn = WALL_TURN[wall] if wall else turn
        parts = _world(_model(name, FABRICS[0] + (1,)), [0., 0., 0.], turn)
        lo = [min(p["center"][a] - p["size"][a] / 2 for p in parts) for a in (0, 1)]
        hi = [max(p["center"][a] + p["size"][a] / 2 for p in parts) for a in (0, 1)]
        if wall:  # back flush with the wall face (+1 cm), centred at `where` along the wall
            x = {"W": face + .01 - lo[0], "E": W - face - .01 - hi[0]}.get(wall, where - (lo[0] + hi[0]) / 2)
            y = {"S": face + .01 - lo[1], "N": D - face - .01 - hi[1]}.get(wall, where - (lo[1] + hi[1]) / 2)
        else:
            x, y = where[0] - (lo[0] + hi[0]) / 2, where[1] - (lo[1] + hi[1]) / 2
        ident, indices = len(scene["objects"]), []
        for part in parts:
            indices.append(len(boxes))
            entry = dict(kind="furniture", size=part["size"], center=[part["center"][0] + x, part["center"][1] + y, part["center"][2]],
                         material=part["material"], level=0, object_id=ident, label=name,
                         **{k: part[k] for k in ("shape", "bevel", "profile", "axis", "facing", "path") if k in part and part[k] is not None})
            if part.get("color"):
                entry["color"] = list(part["color"])
            boxes.append(entry)
        scene["objects"].append(dict(id=ident, room=0, level=0, kind=name, items=[dict(kind=name, offset=[0, 0], turn=0)],
                                     center=[x, y, 0.], yaw=turn * math.pi / 2, bounds=[lo[0] + x, lo[1] + y, hi[0] + x, hi[1] + y],
                                     parts=indices))
    door = [0., D66_DOOR_Y]
    scene["clear_paths"] = [dict(room=0, width=.9, points=[[W / 2, D / 2, 0.], [door[0] + .5, door[1], 0.], [*door, 0.]])]
    scene["baseline_items"] = len(scene["objects"])
