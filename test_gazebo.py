"""Gazebo export (gazebo.py): one collision per group (part, or merged objects), exact hulls, and the exported files collide like load_pybullet."""
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import pybullet as p

from fastload import load_pybullet_merged
from gazebo import MERGED, _hull, _read_obj, collision_groups, export_sdf, load_export
from indoor import Config, generate


class GazeboExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = generate(Config(seed=7, floors=1))
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = export_sdf(cls.scene, cls.tmp.name, "ptg_test")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_layout(self):
        root = Path(self.out) / "ptg_test"
        for name in ("model.sdf", "model.config", "meshes/default.mtl"):
            self.assertTrue((root / name).is_file(), name)
        self.assertIn("model://ptg_test", (Path(self.out) / "world.sdf").read_text())
        link = ET.parse(root / "model.sdf").getroot().find("model/link")
        groups = collision_groups(self.scene)
        self.assertEqual([c.get("name") for c in link.findall("collision")], [name for name, _ in groups])
        self.assertEqual(sorted(i for _, parts in groups for i in parts), list(range(len(self.scene["boxes"]))))
        self.assertTrue(all((len(parts) == 1) == (self.scene["boxes"][parts[0]]["kind"] not in MERGED) for _, parts in groups))
        self.assertIsNone(link.find(".//mesh[@optimization]"), "Gazebo's V-HACD hull is not exact")

    def test_hull_contains_only_mesh_vertices(self):
        square = dict(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1],
                                [.5, .5, .5]], indices=[])
        hull = _hull(square)
        self.assertEqual(len(hull["vertices"]), 8)  # the interior point is dropped
        self.assertEqual(len(hull["indices"]), 36)  # 12 triangles
        for path in (Path(self.out) / "ptg_test/meshes").glob("hull_*.obj"):
            vertices, indices = _read_obj(path)[:2]
            self.assertEqual(len(indices) % 3, 0)
            self.assertLess(max(indices), len(vertices))

    def test_export_collides_like_native(self):
        a, b = p.connect(p.DIRECT), p.connect(p.DIRECT)
        try:
            native, exported = list(load_pybullet_merged(self.scene, a)), load_export(self.out, b)[0]
            groups = collision_groups(self.scene)
            self.assertEqual(len(groups), len(exported))
            for j, (_, parts) in zip(exported, groups):
                boxes = [p.getAABB(native[i], physicsClientId=a) for i in parts]
                union = [min(box[0][k] for box in boxes) for k in range(3)], [max(box[1][k] for box in boxes) for k in range(3)]
                for u, v in zip(union, p.getAABB(j, physicsClientId=b)):
                    for x, y in zip(u, v):  # Bullet pads a concave trimesh's bounds by its 1 mm collision margin
                        self.assertAlmostEqual(x, y, delta=1.5e-3 if len(parts) > 1 else 0)
        finally:
            p.disconnect(a)
            p.disconnect(b)


if __name__ == "__main__":
    unittest.main()
