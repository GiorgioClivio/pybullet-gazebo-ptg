"""Independent geometry and physics checks for furnished maps."""
import math
import unittest

import pybullet as p

from indoor import Config, generate, load_pybullet


class FurnitureTests(unittest.TestCase):
    def test_reproducible_and_architecture_unchanged(self):
        furnished = generate(Config(floors=3))
        empty = generate(Config(floors=3, furnished=False))
        self.assertEqual(furnished, generate(Config(floors=3)))
        self.assertEqual([b for b in furnished["boxes"] if "object_id" not in b], empty["boxes"])
        self.assertEqual(furnished["portals"], empty["portals"])
        self.assertGreater(len(furnished["objects"]), 100)
        models = {item["kind"] for obj in furnished["objects"] for item in obj["items"]}
        self.assertTrue({"chair", "armchair", "sofa", "bed", "desk", "plant", "bookcase", "table"} <= models)

    def test_bounds_nonoverlap_and_empty_circulation_spaces(self):
        for seed in range(20):
            scene = generate(Config(seed=seed, floors=3, details=False))
            objects = scene["objects"]
            for obj in objects:
                room = scene["spaces"][obj["room"]]
                self.assertEqual(room["kind"], "room")
                self.assertIn(room["purpose"], {"living", "office", "bedroom", "storage", "dining", "bathroom", "kitchen", "laundry", "workshop", "meeting", "lab"})
                for axis in (0, 1):
                    self.assertGreater(obj["bounds"][axis], room["rect"][axis] + .08)
                    self.assertLess(obj["bounds"][axis + 2], room["rect"][axis + 2] - .08)
                for other in objects[:obj["id"]]:
                    if other["room"] == obj["room"]:
                        self.assertFalse(all(obj["bounds"][a] < other["bounds"][a + 2] and
                                             obj["bounds"][a + 2] > other["bounds"][a] for a in (0, 1)))
                for index in obj["parts"]:
                    box = scene["boxes"][index]
                    self.assertEqual(box["object_id"], obj["id"])
                    self.assertGreaterEqual(box["center"][2] - box["size"][2] / 2, obj["level"] * 3 - 1e-8)

    def test_chairs_face_tables_and_have_physical_parts(self):
        scene = generate(Config())
        tables = [o for o in scene["objects"] if o["kind"] == "table" and len(o["items"]) > 1]
        self.assertTrue(tables)
        for table in tables:
            for item in table["items"][1:]:
                self.assertEqual(item["kind"], "chair")
                x, y = item["offset"]
                yaw = item["turn"] * math.pi / 2
                self.assertGreater(-math.sin(yaw) * -x + math.cos(yaw) * -y, 0)
        client = p.connect(p.DIRECT)
        try:
            ids = load_pybullet(scene, client)
            for obj in scene["objects"]:
                for index in obj["parts"]:
                    lo, hi = p.getAABB(ids[index], physicsClientId=client)  # getCollisionShapeData does not support static maximal-coordinate bodies; the AABB is the collision box
                    self.assertTrue(all(b > a for a, b in zip(lo, hi)))
            # Explicit furniture/robot collision, independent of the placement checks.
            part = next(b for b in scene["boxes"] if b.get("label") == "sofa")
            shape = p.createCollisionShape(p.GEOM_SPHERE, radius=.12, physicsClientId=client)
            robot = p.createMultiBody(baseCollisionShapeIndex=shape, basePosition=part["center"], physicsClientId=client)
            index = scene["boxes"].index(part)
            self.assertTrue(p.getClosestPoints(robot, ids[index], 0, physicsClientId=client))
        finally:
            p.disconnect(client)


if __name__ == "__main__":
    unittest.main()
