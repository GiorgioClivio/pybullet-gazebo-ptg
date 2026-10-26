"""Room style families: schema, mapping, labs, clear openings, landmarks in front of skins, shared textures."""
import json
import unittest

import room_styles
from indoor import Config, generate

CONFIGS = (dict(seed=0, floors=2), dict(seed=7, floors=3), dict(seed=42, rooms=18, width=28., depth=22., floors=2),
           dict(seed=7, furnished=False, details=False), dict(seed=13, floors=3, roof=True), dict(seed=66, roof=True))


def bounds(b):
    return [b["center"][a] - b["size"][a] / 2 for a in range(3)] + [b["center"][a] + b["size"][a] / 2 for a in range(3)]


def generated(enabled=True, **kwargs):
    """Generate a building with room styles switched on or off."""
    previous, room_styles.ENABLED = room_styles.ENABLED, enabled
    try:
        return generate(Config(**kwargs))
    finally:
        room_styles.ENABLED = previous


class RoomStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenes = {json.dumps(k, sort_keys=True): generated(**k) for k in CONFIGS}

    def test_every_box_has_the_core_schema(self):
        for key, scene in self.scenes.items():
            floors = scene["config"]["floors"]
            for b in scene["boxes"]:
                for field in ("kind", "size", "center", "level", "material"):
                    self.assertIn(field, b, (key, b.get("kind"), b.get("role")))
                self.assertTrue(0 <= b["level"] <= floors, (key, b["kind"]))
                if b["kind"] in ("wall_finish", "frame", "fixture") or "role" in b:
                    # Ceiling-mounted parts (tile layer, cable reels) belong to the storey above, like the slab.
                    expected = scene["spaces"][b["room"]]["level"] + (1 if b.get("ceiling") else 0)
                    self.assertEqual(b["level"], expected, (key, b["kind"], b.get("role")))

    def test_mapping_and_determinism(self):
        for key, scene in self.scenes.items():
            for s in scene["spaces"]:
                family = s["style_family"]
                if s["kind"] != "room":
                    self.assertEqual(family, "corporate")
                    continue
                rule = room_styles.RULES[s["purpose"]]
                allowed = rule.get(s["variant"], rule.get("*"))
                self.assertIn(family, allowed if isinstance(allowed, (tuple, list)) else (allowed,), (key, s["purpose"], s["variant"]))
                if s["purpose"] == "bedroom":
                    self.assertNotEqual(family, "wayfinding")
        again = generated(**CONFIGS[1])
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.scenes[json.dumps(CONFIGS[1], sort_keys=True)], sort_keys=True))

    def test_labs_are_the_largest_candidate_and_leave_other_rooms_alone(self):
        for kwargs in CONFIGS[:3]:
            new, old = self.scenes[json.dumps(kwargs, sort_keys=True)], generated(False, **kwargs)
            labs = {s["id"] for s in new["spaces"] if s.get("purpose") == "lab"}
            area = lambda s: (s["rect"][2] - s["rect"][0]) * (s["rect"][3] - s["rect"][1])
            for lab in labs:
                before = old["spaces"][lab]
                self.assertIn(before["purpose"], room_styles.LAB["candidates"])
                peers = [s for s in old["spaces"] if s["level"] == before["level"] and s.get("purpose") in room_styles.LAB["candidates"]
                         and min(s["rect"][2] - s["rect"][0], s["rect"][3] - s["rect"][1]) >= room_styles.LAB["min_side"]]
                self.assertEqual(area(before), max(area(s) for s in peers))
            self.assertLessEqual(len(labs), new["config"]["floors"])
            self.assertEqual([s.get("purpose") for s in new["spaces"] if s["id"] not in labs],
                             [s.get("purpose") for s in old["spaces"] if s["id"] not in labs])
            furniture = lambda sc: sorted((o["room"], o["kind"], tuple(o["bounds"])) for o in sc["objects"]
                                          if not o.get("detail") and o["room"] not in labs)
            self.assertEqual(furniture(new), furniture(old))
            arch = lambda sc: [b for b in sc["boxes"] if b["kind"] in ("wall", "floor", "glass", "trim", "stairs", "ceiling")]
            self.assertEqual([{k: b[k] for k in ("kind", "size", "center", "level")} for b in arch(new)],
                             [{k: b[k] for k in ("kind", "size", "center", "level")} for b in arch(old)])
        self.assertTrue(any(s.get("purpose") == "lab" for scene in self.scenes.values() for s in scene["spaces"]))

    def test_seed_66_is_lab_d66_only(self):
        for kwargs in (dict(seed=66), dict(seed=66, roof=True, floors=3, rooms=20), dict(seed=66, furnished=False, details=False)):
            scene = generated(**kwargs)
            self.assertEqual(json.loads(json.dumps(scene)), scene)
            rooms = [s for s in scene["spaces"] if s["kind"] == "room"]
            self.assertEqual([(r["purpose"], r["variant"]) for r in rooms], [("lab", "d66")])
            self.assertEqual((scene["config"]["floors"], scene["config"]["rooms"]), (1, 1))
            for b in scene["boxes"]:
                for field in ("kind", "size", "center", "level", "material"):
                    self.assertIn(field, b)
            for p in scene["portals"]:
                self.assertEqual(len(p["rooms"]), 2)
            if not kwargs.get("furnished", True):
                continue
            x, y = scene["spawn"][:2]
            lane = [(-1.8, 2.2 - .5), (4.5, 2.2 + .5)]  # door to room centre, 1 m wide
            for o in scene["objects"]:
                x0, y0, x1, y1 = o["bounds"]
                if o.get("placement") in ("wall", "surface") or o["kind"] == "lab_mat":
                    continue  # mounted, on a support, or a 12 mm floor mat
                self.assertFalse(x0 - .3 < x < x1 + .3 and y0 - .3 < y < y1 + .3, o["kind"])
                self.assertFalse(x0 < lane[1][0] and x1 > lane[0][0] and y0 < lane[1][1] and y1 > lane[0][1] and x1 < 1.2, o["kind"])
            signs = [b for b in scene["boxes"] if b.get("label") == "room_sign" and b.get("texture", {}).get("style") == "sign"
                     and scene["objects"][b["object_id"]]["room"] == 0]
            self.assertTrue(signs and all(b["texture"]["label"] == "LAB\nD66" for b in signs))
        self.assertGreater(len(generated(seed=65)["spaces"]), 12)  # neighbours stay ordinary buildings

    def test_lab_d66_is_one_slot_in_six(self):
        d66 = labs = 0
        for seed in range(30):
            scene = generated(seed=seed, floors=3, furnished=False)
            variants = [s["variant"] for s in sorted((s for s in scene["spaces"] if s.get("purpose") == "lab"),
                                                     key=lambda s: (s["level"], s["id"]))]
            self.assertTrue(set(variants) <= {"d66", "aseptic"})
            self.assertLessEqual(variants.count("d66"), 1)  # at most 3 labs per building: one 6-slot cycle
            d66, labs = d66 + variants.count("d66"), labs + len(variants)
        self.assertTrue(0 < d66 < labs / 2, (d66, labs))
        scene = generated(seed=0, floors=3)
        lab = next(s for s in scene["spaces"] if s.get("variant") == "d66")
        signs = [b for b in scene["boxes"] if b.get("label") == "room_sign" and b.get("texture", {}).get("style") == "sign"
                 and scene["objects"][b["object_id"]]["room"] == lab["id"]]
        self.assertTrue(signs and all(b["texture"]["label"] == "LAB\nD66" for b in signs))
        kinds = {o["kind"] for o in scene["objects"] if o["room"] == lab["id"]}
        self.assertTrue({"lab_desk", "lab_pegboard", "lab_cabinet"} <= kinds, kinds)
        aseptic = [o["kind"] for o in scene["objects"] if scene["spaces"][o["room"]].get("variant") == "aseptic"]
        self.assertFalse({"lab_desk", "lab_pegboard"} & set(aseptic))

    def test_finishes_leave_doors_and_windows_clear(self):
        for key, scene in self.scenes.items():
            c = scene["config"]
            # Roller blinds deliberately cover the upper window (they are not frames); everything else stays clear.
            added = [b for b in scene["boxes"] if (b["kind"] in ("wall_finish", "frame", "fixture") or b.get("role") == "pictogram_board")
                     and b.get("role") not in ("blind", "blind_box")]
            openings = []
            for p in scene["portals"]:
                along, thin = p["axis"], 1 - p["axis"]
                lo, hi = [0.] * 3, [0.] * 3
                lo[along], hi[along] = p["center"][along] - p["width"] / 2, p["center"][along] + p["width"] / 2
                lo[thin], hi[thin] = p["center"][thin] - c["wall"] / 2 - .05, p["center"][thin] + c["wall"] / 2 + .05
                lo[2], hi[2] = p["center"][2], p["center"][2] + p["height"]
                openings.append(lo + hi)
            for g in (b for b in scene["boxes"] if b["kind"] == "glass"):
                gb, thin = bounds(g), 0 if g["size"][0] < g["size"][1] else 1
                gb[thin], gb[thin + 3] = gb[thin] - c["wall"] / 2 - .06, gb[thin + 3] + c["wall"] / 2 + .06
                openings.append(gb)
            for part in added:
                pb = bounds(part)
                for o in openings:
                    overlap = all(pb[a] < o[a + 3] - 1e-6 and pb[a + 3] > o[a] + 1e-6 for a in range(3))
                    self.assertFalse(overlap, (key, part["kind"], part.get("role"), pb, o))

    def test_wall_landmarks_stay_in_front_of_skins(self):
        scene = self.scenes[json.dumps(CONFIGS[1], sort_keys=True)]
        c = scene["config"]
        skins = [b for b in scene["boxes"] if b.get("role") == "skin"]
        self.assertTrue(skins)
        for obj in (o for o in scene["objects"] if o.get("placement") == "wall"):
            board = bounds(scene["boxes"][obj["parts"][0]])
            for skin in skins:
                sb = bounds(skin)
                self.assertFalse(all(board[a] < sb[a + 3] - 1e-9 and board[a + 3] > sb[a] + 1e-9 for a in range(3)),
                                 (obj["kind"], obj["room"]))
        for skin in skins:  # 3 mm on the room side of the wall face
            self.assertAlmostEqual(min(skin["size"][:2]), room_styles.SKIN)
        self.assertLess(room_styles.SKIN, .004)  # details.enrich mounts back boards 4 mm in front of the wall face

    def test_textures_stay_shared(self):
        kwargs = CONFIGS[1]
        new, old = self.scenes[json.dumps(kwargs, sort_keys=True)], generated(False, **kwargs)
        specs = lambda sc: {json.dumps(b["texture"], sort_keys=True) for b in sc["boxes"] if "texture" in b}
        extra = [json.loads(e) for e in specs(new) - specs(old)]
        rooms = [s for s in new["spaces"] if s.get("style_family") == "wayfinding"]
        labs = {f'LAB {s["id"]:02d}' for s in new["spaces"] if s.get("purpose") == "lab"}
        # Printed wall content is per landmark already (labels name the room purpose): a lab's art and
        # notices are new images by construction. Besides those, only wayfinding adds images: at most
        # one door plate and one pictogram sign per wayfinding room.
        signs = [e for e in extra if e.get("plate") or e.get("pictogram")]
        printed = [e for e in extra if e["style"] in ("art", "notice") and e["label"].rsplit("-", 1)[0] in labs]
        d66 = [e for e in extra if e.get("lab_texture") or e.get("label") == "LAB\nD66"]  # one each, shared by all D66 labs
        self.assertEqual(len(signs) + len(printed) + len(d66), len(extra), extra)
        self.assertLessEqual(len(d66), 3)
        self.assertLessEqual(len(signs), 2 * len(rooms))
        for style in ("plaster", "tile", "planks", "grain", "weave", "paint"):
            self.assertLessEqual(len({json.dumps(b["texture"], sort_keys=True) for b in new["boxes"]
                                      if b.get("texture", {}).get("style") == style}), 1, style)


if __name__ == "__main__":
    unittest.main()
