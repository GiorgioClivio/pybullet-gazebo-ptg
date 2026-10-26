"""Lumen-method numbers, fixture placement and the PBR slot manager (with a fake renderer)."""
import json
import math
import sys
import unittest
from unittest.mock import patch

import lights
from indoor import Config, generate


class FakePbr:
    POINT, SPOT = 1, 2

    class photometry:
        @staticmethod
        def ev_for_illuminance(lux, albedo=.18):
            return math.log2(lux * albedo / math.pi / (1.2 * .18))

    def __init__(self, occupied=(), active=True):
        self.slots = {s: dict(kind=k, shadows=sh) for s, k, sh in occupied}
        self.active, self.calls = active, []

    def is_active(self):
        return self.active

    def max_lights(self):
        return 8

    def get_light(self, slot):
        return self.slots.get(slot, dict(kind=0, shadows=False))

    def add_light(self, slot, **kw):
        self.calls.append(("add", slot, kw))
        self.slots[slot] = dict(kw)

    def remove_light(self, slot):
        self.calls.append(("remove", slot))
        self.slots.pop(slot)

    def set_ev(self, ev):
        self.calls.append(("ev", ev))

    def set_auto_exposure(self, *a, **kw):
        self.calls.append(("auto", a, kw))

    def set_material(self, body, **kw):
        self.calls.append(("material", body, kw))


def scene(floors=3, roof=False, seed=7):
    return generate(Config(seed=seed, floors=floors, roof=roof))


class LumenMethodTests(unittest.TestCase):
    def test_hand_checked_office(self):
        # 5 x 4 m office, 500 lx, Hm = 2 m: RI = 20 / (2 x 9) = 1.111; UF = 0.64 + 0.111/0.25 x 0.08
        # = 0.6756; N = 500 x 20 / (3600 x 0.6756 x 0.8) = 5.14 -> 6; grid 3 x 2 (1.67 x 2 m spacing,
        # <= 1.5 x 2 m); each panel dimmed to 10000 / (6 x 0.6756 x 0.8) = 3084 lm.
        r = lights.lumen_method(500, 5., 4., 2., 3600)
        self.assertAlmostEqual(r["room_index"], 1.1111, 4)
        self.assertAlmostEqual(r["uf"], .67556, 4)
        self.assertEqual((r["n_min"], r["nx"], r["ny"]), (6, 3, 2))
        self.assertAlmostEqual(r["lumens"], 3083.9, 1)

    def test_uf_table_and_render_flux(self):
        self.assertEqual(lights.utilisation_factor(1.5), .77)
        self.assertEqual(lights.utilisation_factor(9.), 1.03)
        self.assertAlmostEqual(lights.utilisation_factor(.4), .36)
        # A uniform hemisphere (inner = outer = 180 deg full angle) emits 2 pi I.
        self.assertAlmostEqual(lights.render_candela(2 * math.pi, (180., 180.)), 1.)


class PlacementTests(unittest.TestCase):
    def test_fixtures_inside_rooms_below_ceiling_and_clear_of_other_parts(self):
        s = scene()
        n = len(s["boxes"])
        lights.add_lights(s)
        c, spaces = s["config"], {sp["id"]: sp for sp in s["spaces"]}
        self.assertTrue(s["lights"])
        for f in s["lights"]:
            x0, y0, x1, y1 = spaces[f["space"]]["rect"]
            part = s["boxes"][f["box"]]
            half = part["size"][0] / 2
            self.assertTrue(x0 + c["wall"] / 2 + half <= f["position"][0] <= x1 - c["wall"] / 2 - half, f)
            self.assertTrue(y0 + c["wall"] / 2 + half <= f["position"][1] <= y1 - c["wall"] / 2 - half, f)
            ceiling = (f["level"] + 1) * c["storey"] - c["slab"]
            if f["level"] < c["floors"] - 1:
                from indoor import CEILING_SKIN
                ceiling -= CEILING_SKIN  # flush with the plaster skin under inter-storey slabs
            self.assertAlmostEqual(part["center"][2] + part["size"][2] / 2, ceiling)
            self.assertGreater(part["center"][2] - part["size"][2] / 2 - f["level"] * c["storey"], 2.46)
            self.assertTrue(lights._covered(s, f["level"], f["position"][0], f["position"][1], half))
            self.assertLessEqual(f["lumens"], lights.LUMINAIRES[f["kind"]]["lumens"])
            self.assertAlmostEqual(f["calculation"]["average_lux"], f["target_lux"], delta=.5)
        lo = lambda b: [b["center"][a] - b["size"][a] / 2 for a in range(3)]
        hi = lambda b: [b["center"][a] + b["size"][a] / 2 for a in range(3)]
        for f in s["lights"]:
            p = s["boxes"][f["box"]]
            for b in s["boxes"][:n]:
                if b["level"] in (f["level"], f["level"] + 1):
                    self.assertFalse(all(lo(p)[a] < hi(b)[a] - 1e-6 and lo(b)[a] < hi(p)[a] - 1e-6 for a in range(3)),
                                     (f["space"], b["kind"]))

    def test_no_fixtures_without_a_ceiling(self):
        self.assertEqual(lights.plan_lights(scene(floors=1)), [])
        open_top = lights.plan_lights(scene())
        self.assertFalse([f for f in open_top if f["level"] == 2])
        self.assertTrue({0, 1} <= {f["level"] for f in open_top})
        roofed = scene(roof=True)
        lit = {f["space"] for f in lights.plan_lights(roofed)}
        self.assertEqual(lit, {sp["id"] for sp in roofed["spaces"]})

    def test_deterministic_idempotent_and_indices_stable(self):
        a, b = scene(), scene()
        self.assertEqual(json.dumps(lights.plan_lights(a)), json.dumps(lights.plan_lights(b)))
        before = json.dumps(a["boxes"])
        lights.add_lights(a)
        count = len(a["boxes"])
        lights.add_lights(a)
        self.assertEqual(len(a["boxes"]), count)
        self.assertEqual(json.dumps(a["boxes"][:len(b["boxes"])]), before)
        self.assertNotIn("lights", b)
        self.assertFalse([x for x in b["boxes"] if x["kind"] == "light"])


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.scene = lights.add_lights(scene())

    def room_center(self, purpose, level=0):
        r = next(s for s in self.scene["spaces"] if s.get("purpose") == purpose and s["level"] == level)
        return r, [(r["rect"][0] + r["rect"][2]) / 2, (r["rect"][1] + r["rect"][3]) / 2, level * 3 + 1.6]

    def test_ranks_same_room_first_and_keeps_host_slot(self):
        pbr = FakePbr(occupied=[(0, FakePbr.POINT, True)])   # robot headlamp: 6 tiles
        m = lights.PbrLightManager(self.scene, pbr, body_ids=list(range(len(self.scene["boxes"]))))
        self.assertEqual(m.slots, list(range(1, 8)))
        self.assertEqual(len([c for c in pbr.calls if c[0] == "material"]), len(self.scene["lights"]))
        room, pos = self.room_center("living")
        lit = m.update(pos)
        own = [i for i, f in enumerate(self.scene["lights"]) if f["space"] == room["id"]]
        self.assertEqual(len(lit), 7)
        self.assertTrue(set(own) <= set(lit))
        adds = [c for c in pbr.calls if c[0] == "add"]
        self.assertEqual(len(adds), 7)
        self.assertNotIn(0, [c[1] for c in adds])
        self.assertTrue(all(c[2]["shadows"] and c[2]["direction"] == [0, 0, -1] for c in adds))
        self.assertIn(("ev", FakePbr.photometry.ev_for_illuminance(100)), pbr.calls)
        # Same space, small move: throttled, no renderer calls.
        n = len(pbr.calls)
        m.update([pos[0] + .1, pos[1], pos[2]])
        self.assertEqual(len(pbr.calls), n)
        # Another storey: everything moves to that storey's fixtures; the headlamp stays.
        room2, pos2 = self.room_center("office", 1)
        lit2 = m.update(pos2)
        self.assertTrue(all(self.scene["lights"][i]["level"] == 1 for i in lit2))
        self.assertTrue({i for i, f in enumerate(self.scene["lights"]) if f["space"] == room2["id"]} <= set(lit2)
                        or len([f for f in self.scene["lights"] if f["space"] == room2["id"]]) > 7)
        self.assertEqual(pbr.slots[0]["kind"], FakePbr.POINT)
        m.close()
        self.assertEqual(sorted(pbr.slots), [0])

    def test_shadow_budget_and_inactive_renderer(self):
        pbr = FakePbr(occupied=[(0, 1, True), (1, 1, True)])   # 12 tiles used -> 4 left
        m = lights.PbrLightManager(self.scene, pbr)
        m.update(self.room_center("living")[1])
        self.assertEqual(sum(c[2]["shadows"] for c in pbr.calls if c[0] == "add"), 4)
        off = FakePbr(active=False)
        self.assertEqual(lights.PbrLightManager(self.scene, off).update([1, 1, 1]), [])
        self.assertEqual(off.calls, [])
        with patch.dict(sys.modules, {"pybullet_pbr": None}):
            self.assertIsNone(lights.active_pbr())
            self.assertEqual(lights.PbrLightManager(self.scene).update([1, 1, 1]), [])
        bare = FakePbr()
        self.assertEqual(lights.PbrLightManager(scene(), bare).update([1, 1, 1]), [])   # no add_lights
        self.assertEqual(bare.calls, [])


if __name__ == "__main__":
    unittest.main()
