"""The z-fighting gap rule (geometry.separate_coplanar): visuals set apart, physics untouched."""
import unittest

import geometry
from indoor import Config, generate


def without_rule(**kwargs):
    """Generate a building with geometry.separate_coplanar disabled."""
    rule, geometry.separate_coplanar = geometry.separate_coplanar, lambda scene, *a, **k: 0
    try:
        return generate(Config(**kwargs))
    finally:
        geometry.separate_coplanar = rule


class ZFightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.new, cls.old = generate(Config(seed=7, floors=2)), without_rule(seed=7, floors=2)

    def test_pairs_are_set_apart(self):
        before, after = len(geometry.coplanar_pairs(self.old)), len(geometry.coplanar_pairs(self.new))
        self.assertGreater(before, 100)
        self.assertLess(after, .05 * before)

    def test_physics_is_unchanged(self):
        for new, old in zip(self.new["boxes"], self.old["boxes"]):
            self.assertEqual(new.get("collision_center", new["center"]), old.get("collision_center", old["center"]))
            self.assertEqual(new.get("collision_size", new["size"]), old.get("collision_size", old["size"]))

    def test_no_part_moves_more_than_three_gaps_and_floors_never_rise(self):
        for new, old in zip(self.new["boxes"], self.old["boxes"]):
            for a in range(3):
                for d in (-1, 1):
                    shift = d * ((new["center"][a] + d * new["size"][a] / 2) - (old["center"][a] + d * old["size"][a] / 2))
                    self.assertLessEqual(abs(shift), 3 * geometry.ZFIGHT_GAP + 1e-9)
            if new["kind"] in ("floor", "stairs"):
                self.assertLessEqual(new["center"][2] + new["size"][2] / 2, old["center"][2] + old["size"][2] / 2 + 1e-9)


if __name__ == "__main__":
    unittest.main()
