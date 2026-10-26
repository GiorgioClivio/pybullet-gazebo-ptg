"""X-ray changes only visuals of PTG bodies and restores the loaded colours exactly."""
import unittest

import pybullet as p

from indoor import Config, generate, load_pybullet
from xray import TINTS, XRay, xray_color


class XRayTests(unittest.TestCase):
    def test_every_generated_body_translucent_robot_and_collisions_untouched(self):
        client = p.connect(p.DIRECT)
        try:
            scene = generate(Config(floors=2))
            bodies = load_pybullet(scene, client)
            robot = p.createMultiBody(0, p.createCollisionShape(p.GEOM_BOX, halfExtents=[.3] * 3, physicsClientId=client),
                p.createVisualShape(p.GEOM_BOX, halfExtents=[.3] * 3, rgbaColor=[1, .2, 0, .9], physicsClientId=client),
                basePosition=scene["spawn"], physicsClientId=client)
            visual = lambda b: p.getVisualShapeData(b, physicsClientId=client)[0][7]
            before = [visual(b) for b in bodies]
            collisions = [p.getAABB(b, physicsClientId=client) for b in bodies]  # getCollisionShapeData does not support static maximal-coordinate bodies; the AABB is the collision box
            xray = XRay(scene, bodies, client)
            self.assertTrue(xray.toggle())
            self.assertTrue(any("object_id" in b for b in scene["boxes"]))
            for box, body in zip(scene["boxes"], bodies):
                self.assertLessEqual(visual(body)[3], .36, box["kind"])
                if "object_id" not in box:  # Architecture keeps the per-storey tint.
                    for got, want in zip(visual(body), TINTS[min(box["level"], 2)]):
                        self.assertAlmostEqual(got, want, 6)
            for got, want in zip(visual(robot), (1, .2, 0, .9)):
                self.assertAlmostEqual(got, want, 6)
            self.assertFalse(xray.toggle())
            # Creation stores float32 RGBA; restore sets the loaded values themselves.
            self.assertLess(max(abs(u - v) for b, old in zip(bodies, before) for u, v in zip(visual(b), old)), 1e-7)
            self.assertEqual([p.getAABB(b, physicsClientId=client) for b in bodies], collisions)
        finally:
            p.disconnect(client)

    def test_alpha_parameter_for_renderers_without_blending(self):
        boxes = {b["kind"]: b for b in generate(Config(floors=2))["boxes"]}
        self.assertEqual({xray_color(b, 0.)[3] for b in boxes.values()}, {0.})
        hide = {"floor": 1, "stairs": 1}
        self.assertEqual(xray_color(boxes["floor"], hide)[3], 1)
        self.assertEqual(xray_color(boxes["wall"], hide)[3], 0)
        self.assertEqual(xray_color(boxes["furniture"], {**hide, "other": .5})[3], .5)


if __name__ == "__main__":
    unittest.main()
