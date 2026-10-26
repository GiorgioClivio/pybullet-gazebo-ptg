"""Minimap plan primitives and the non-blocking pose channel, without a display."""
import os
import time
import unittest
from unittest.mock import patch

from indoor import Config, generate
from minimap import PERIOD, Minimap, plan, storey


def inside(point, rect):
    return rect[0] < point[0] < rect[2] and rect[1] < point[1] < rect[3]


class MinimapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = generate(Config(floors=3))

    def test_plan_has_spaces_open_doors_and_directed_stairs(self):
        scene, flights = self.scene, []
        for level in range(3):
            items = plan(scene, level)
            spaces = [i for i in items if i[0] == "space"]
            self.assertEqual(len(spaces), sum(s["level"] == level for s in scene["spaces"]))
            walls = [i[1] for i in items if i[0] == "wall"]
            doors = [i for i in items if i[0] == "door"]
            self.assertTrue(walls and doors and any(i[0] == "glass" for i in items))
            for _, a, b in doors:  # Lintels are not drawn, so every doorway stays open in plan.
                self.assertFalse(any(inside([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], r) for r in walls))
            flights.append(sorted(i[2] for i in items if i[0] == "stairs"))
            for _, rect, direction, a, b in (i for i in items if i[0] == "stairs"):
                self.assertTrue(inside(a, rect) or a[1] == rect[1] or a[1] == rect[3])
                self.assertEqual(b[1] > a[1], direction == "up")  # Flights rise towards +y.
        self.assertEqual(flights, [["up"], ["down", "up"], ["down"]])

    def test_annex_and_storey_from_height(self):
        annex = [i for i in plan(generate(Config(rooms=1)), 0) if i[0] == "space" and i[4]]
        self.assertEqual(len(annex), 2)
        self.assertEqual([storey(self.scene, z) for z in (-1, .55, 2.69, 2.71, 3.55, 6.55, 30)], [0, 0, 0, 1, 1, 2, 2])

    def test_update_is_throttled_and_survives_a_dead_window(self):
        devnull = os.open(os.devnull, os.O_WRONLY)
        saved = os.dup(2)
        try:  # No display: the window process fails at once; the host must not notice.
            os.dup2(devnull, 2)
            with patch.dict(os.environ, {"DISPLAY": ""}):
                mm = Minimap(self.scene)
        finally:
            os.dup2(saved, 2)
            os.close(saved)
            os.close(devnull)
        self.assertEqual(sum(mm.update(1, 2, 3, .5) for _ in range(1000)), 1)
        self.assertEqual(list(mm.pose), [1, 1, 2, 3, .5])
        mm.process.join(20)
        self.assertFalse(mm.process.is_alive())
        time.sleep(PERIOD)
        self.assertTrue(mm.update(4, 5, 6, 0))
        self.assertEqual(mm.pose[0], 2)
        mm.close()
        mm.close()


if __name__ == "__main__":
    unittest.main()
