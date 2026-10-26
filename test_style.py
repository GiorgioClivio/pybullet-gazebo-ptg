"""Visual consistency, bounded geometry and physical curved objects."""
import json
import math
import unittest

import pybullet as p
from PIL import ImageChops, ImageStat

from geometry import mesh
from indoor import Config, generate, load_pybullet
from styles import PALETTE
from surfaces import _texture


class StyleTests(unittest.TestCase):
    def test_building_palette_and_shared_finishes(self):
        scene = generate(Config(floors=3))
        self.assertEqual(scene["style"]["id"], "apartment_office")
        walls = [b for b in scene["boxes"] if b["kind"] in ("wall", "ceiling")]
        self.assertEqual(len({tuple(b["color"]) for b in walls}), 1)
        self.assertEqual({b["texture"]["style"] for b in walls}, {"plaster"})
        floors = [b for b in scene["boxes"] if b["kind"] == "floor"]
        self.assertEqual({b["texture"]["style"] for b in floors}, {"tile", "planks"})
        for style in ("tile", "planks", "grain", "weave", "paint", "cardboard"):
            specs = {json.dumps(b["texture"], sort_keys=True) for b in scene["boxes"] if b.get("texture", {}).get("style") == style}
            self.assertEqual(len(specs), 1, style)
        self.assertTrue(all(max(c[:3])-min(c[:3]) <= .18 for c in PALETTE))
        for space in scene["spaces"]:
            if space["kind"] != "room":
                self.assertEqual(space["appearance"]["floor"], "tile")

    def test_material_images_are_neutral_and_walls_subtle(self):
        for style in ("tile", "planks", "grain", "weave", "paint", "plaster", "cardboard"):
            im = _texture(dict(style=style, seed=7))
            red, green, blue = im.split()
            self.assertIsNone(ImageChops.difference(red, green).getbbox())
            self.assertIsNone(ImageChops.difference(red, blue).getbbox())
            if style == "plaster":
                self.assertLess(max(ImageStat.Stat(im).stddev), 2.)

    def test_meshes_fit_envelopes_and_have_outward_faces(self):
        scene = generate(Config())
        seen = set()
        self.assertGreater(scene["geometry_stats"]["curved_parts"], 200)
        for box in scene["boxes"]:
            if not box.get("shape"):
                continue
            signature = json.dumps({k: box[k] for k in ("shape", "size", "axis", "profile", "bevel", "facing", "path") if k in box}, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            m = mesh(box)
            self.assertEqual(len(m["vertices"]), len(m["uvs"]))
            self.assertEqual(len(m["vertices"]), len(m["normals"]))
            for vertex, normal in zip(m["vertices"], m["normals"]):
                self.assertTrue(all(math.isfinite(x) for x in vertex+normal))
                self.assertTrue(all(abs(vertex[a]) <= box["size"][a]/2+1e-9 for a in range(3)))
                self.assertAlmostEqual(math.sqrt(sum(x*x for x in normal)), 1.)
            if box["shape"] == "bevel":
                self.assertEqual(len(m["indices"]), 44*3)
            for i in range(0, len(m["indices"]), 3):
                ids = m["indices"][i:i+3]
                a, b, c = [m["vertices"][j] for j in ids]
                u, v = [b[j]-a[j] for j in range(3)], [c[j]-a[j] for j in range(3)]
                normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
                self.assertGreaterEqual(sum(normal[j]*sum(m["normals"][k][j] for k in ids) for j in range(3)), -1e-10)
        for seed in (0, 7, 13):
            self.assertLess(generate(Config(seed=seed))["geometry_stats"]["visual_triangles"], 200_000)

    def test_curved_collision_hull_does_not_fill_box_corners(self):
        part = dict(kind="prop", level=0, material="ceramic", shape="lathe", size=[.30, .30, .40],
                    center=[0, 0, .20], profile=[[1, -.5], [1, .5]])
        client = p.connect(p.DIRECT)
        try:
            body = load_pybullet(dict(boxes=[part]), client)[0]
            shape = p.createCollisionShape(p.GEOM_SPHERE, radius=.005, physicsClientId=client)
            proxy = p.createMultiBody(baseCollisionShapeIndex=shape, basePosition=[0, 0, .2], physicsClientId=client)
            self.assertTrue(p.getClosestPoints(proxy, body, 0, physicsClientId=client))
            p.resetBasePositionAndOrientation(proxy, [.14, .14, .2], [0, 0, 0, 1], physicsClientId=client)
            self.assertFalse(p.getClosestPoints(proxy, body, 0, physicsClientId=client))
        finally:
            p.disconnect(client)


if __name__ == "__main__":
    unittest.main()
