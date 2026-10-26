"""Check walking against real collisions, including stairs and X-ray rendering."""
import unittest
import ctypes
import math
from types import SimpleNamespace
from unittest.mock import patch

import pybullet as p

from indoor import Config, generate, load_pybullet
from viewer import XRAY_KEY, Viewer, Walker, tab_pressed


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.client = p.connect(p.DIRECT)

    def tearDown(self):
        p.disconnect(self.client)

    def box(self, center, size):
        shape = p.createCollisionShape(p.GEOM_BOX, halfExtents=[s / 2 for s in size], physicsClientId=self.client)
        return p.createMultiBody(baseMass=0, baseCollisionShapeIndex=shape,
                                 basePosition=center, physicsClientId=self.client)

    def travel(self, walker, dx=0, dy=0, seconds=1):
        for _ in range(round(seconds * 60)):
            walker.move(dx / 60, dy / 60, 1 / 60)

    def test_linux_tab_does_not_accept_other_unknown_keys(self):
        state = ctypes.create_string_buffer(32)
        native = SimpleNamespace(XQueryKeymap=lambda *_: None), None, 23, state
        with patch("viewer._x11_keyboard", return_value=native):
            self.assertFalse(tab_pressed({-1: p.KEY_WAS_TRIGGERED}))
            state[2] = bytes([1 << 7])
            self.assertTrue(tab_pressed({-1: p.KEY_WAS_TRIGGERED}))
            self.assertFalse(tab_pressed({-1: p.KEY_IS_DOWN}))
        self.assertTrue(tab_pressed({9: p.KEY_WAS_TRIGGERED}))

    def test_walls_slide_and_large_motion_does_not_tunnel(self):
        self.box([0, 0, -.1], [20, 20, .2])
        self.box([2, 0, 1.5], [.16, 20, 3])
        walker = Walker(self.client, [0, 0, .002])
        self.travel(walker, 1.4, .8, 3)
        self.assertLess(walker.feet[0], 1.71)
        self.assertGreater(walker.feet[1], 2.3)
        self.assertAlmostEqual(walker.feet[2], .002, delta=.005)
        walker.move(20, 0, .1)
        self.assertLess(walker.feet[0], 1.71)
        self.assertGreater(walker.feet[0], 1.6)

    def test_falls_and_cannot_step_onto_tall_obstacles(self):
        self.box([0, 0, -.1], [20, 20, .2])
        self.box([2, 0, .4], [1, 5, .8])
        walker = Walker(self.client, [0, 0, 1])
        self.travel(walker, seconds=1)
        self.assertAlmostEqual(walker.feet[2], .002, delta=.005)
        self.travel(walker, 1.4, seconds=3)
        self.assertLess(walker.feet[0], 1.3)
        self.assertAlmostEqual(walker.feet[2], .002, delta=.005)

    def test_climbs_both_flights_and_descends(self):
        c = Config(floors=3, roof=True)
        scene = generate(c)
        load_pybullet(scene, self.client)
        stair = scene["stairs"][0]
        walker = Walker(self.client, [*stair["start"][:2], .002])
        distance = c.run + 1
        self.travel(walker, dy=1, seconds=distance)
        self.assertAlmostEqual(walker.feet[2], c.storey + .002, delta=.01)
        # Return along the protected corridor to the next flight's bottom landing.
        self.travel(walker, dx=1, seconds=c.landing)
        self.travel(walker, dy=-1, seconds=distance)
        self.travel(walker, dx=-1, seconds=c.landing)
        self.travel(walker, dy=1, seconds=distance)
        self.assertAlmostEqual(walker.feet[2], 2 * c.storey + .002, delta=.01)
        self.travel(walker, dy=-1, seconds=distance)
        self.assertAlmostEqual(walker.feet[2], c.storey + .002, delta=.01)

    def test_low_ceiling_blocks_step_up(self):
        self.box([0, 0, -.1], [20, 20, .2])
        self.box([1.5, 0, .075], [1, 4, .15])
        self.box([1.5, 0, 1.84], [2, 4, .1])
        walker = Walker(self.client, [0, 0, .002])
        self.travel(walker, dx=1, seconds=3)
        self.assertLess(walker.feet[0], 1)
        self.assertLess(walker.feet[2], .01)

    def test_tab_restores_camera_and_xray_keeps_collisions(self):
        scene = generate(Config(floors=3))
        bodies = load_pybullet(scene, self.client, view_floor=0)
        viewer = Viewer(scene, bodies, self.client, view_floor=0)
        camera = [0] * 8 + [37, -55, 30, [11, 9, 2]]
        with patch.object(p, "getDebugVisualizerCamera", return_value=camera), patch.object(p, "resetDebugVisualizerCamera") as reset:
            viewer.update(.01, {9: p.KEY_WAS_TRIGGERED}, [])
            self.assertTrue(viewer.walking)
            distance, yaw, pitch, target = reset.call_args.args
            matrix = p.computeViewMatrixFromYawPitchRoll(target, distance, yaw, pitch, 0, 2)
            eye = [-sum(matrix[i * 4 + j] * matrix[12 + j] for j in range(3)) for i in range(3)]
            expected = [*viewer.walker.feet[:2], viewer.walker.feet[2] + Walker.eye_height]
            self.assertLess(math.dist(eye, expected), 1e-5)
            upper = next(i for i, b in enumerate(scene["boxes"]) if b["level"] == 2)
            self.assertGreater(p.getVisualShapeData(bodies[upper], physicsClientId=self.client)[0][7][3], 0)
            item = next(i for i, b in enumerate(scene["boxes"]) if "object_id" in b)
            furniture_color = p.getVisualShapeData(bodies[item], physicsClientId=self.client)[0][7]
            viewer.update(.01, {ord("x"): p.KEY_WAS_TRIGGERED}, [])
            self.assertFalse(viewer.xray.on)  # X/Z stay free for a host's camera zoom.
            viewer.update(.01, {XRAY_KEY: p.KEY_WAS_TRIGGERED}, [])
            self.assertTrue(viewer.xray.on)
            xray_furniture = p.getVisualShapeData(bodies[item], physicsClientId=self.client)[0][7]
            self.assertLess(xray_furniture[3], .5)
            self.assertNotEqual(xray_furniture[:3], furniture_color[:3])
            wall = next(i for i, b in enumerate(scene["boxes"]) if b["kind"] == "wall")
            self.assertLess(p.getVisualShapeData(bodies[wall], physicsClientId=self.client)[0][7][3], .2)
            walker = viewer.walker
            collision_before = p.getAABB(bodies[0], physicsClientId=self.client)  # getCollisionShapeData does not support static maximal-coordinate bodies; the AABB is the collision box
            viewer.update(.01, {9: p.KEY_WAS_TRIGGERED}, [])
            self.assertFalse(viewer.walking)
            reset.assert_called_with(30, 37, -55, [11, 9, 2], physicsClientId=self.client)
            self.assertEqual(p.getAABB(bodies[0], physicsClientId=self.client), collision_before)
            self.assertEqual(p.getVisualShapeData(bodies[upper], physicsClientId=self.client)[0][7][3], 0)
            viewer.update(.01, {9: p.KEY_WAS_TRIGGERED}, [])
            self.assertIs(viewer.walker, walker)


if __name__ == "__main__":
    unittest.main()
