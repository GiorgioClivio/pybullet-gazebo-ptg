"""Count actual instances, inspect material images, and check detail geometry independently."""
import math
import unittest

import pybullet as p
from PIL import Image, ImageStat

from indoor import Config, generate, load_pybullet
from surfaces import box_mesh, texture_path


def bounds(box):
    return [box["center"][a] - box["size"][a] / 2 for a in range(3)] + [
        box["center"][a] + box["size"][a] / 2 for a in range(3)]


class DetailTests(unittest.TestCase):
    def test_at_least_double_instances_and_same_floorplan(self):
        for seed, floors in ((0, 1), (7, 1), (13, 1), (0, 3), (7, 3)):
            plain = generate(Config(seed=seed, floors=floors, details=False))
            detailed = generate(Config(seed=seed, floors=floors))
            before = sum(len(o["items"]) for o in plain["objects"])
            after = sum(len(o["items"]) for o in detailed["objects"])
            self.assertGreaterEqual(after, 2 * before, (seed, floors))
            self.assertEqual(detailed["detail_stats"]["baseline_items"], before)
            self.assertEqual(detailed["portals"], plain["portals"])
            self.assertEqual(detailed["stairs"], plain["stairs"])
            self.assertEqual([s["rect"] for s in detailed["spaces"]], [s["rect"] for s in plain["spaces"]])

    def test_props_are_supported_and_no_wall_decoration_covers_openings(self):
        scene = generate(Config())
        for obj in scene["objects"]:
            if obj.get("placement") == "surface":
                parent = scene["objects"][obj["parent_id"]]
                support_z = obj["bounds3d"][2] - .004
                self.assertTrue(any(abs(bounds(scene["boxes"][i])[5] - support_z) < 1e-6 for i in parent["parts"]))
            if obj.get("placement") == "wall":
                space = scene["spaces"][obj["room"]]
                self.assertGreater(obj["bounds3d"][2], space["level"] * 3)
                # The back board's width and height must be supported by a physical wall.
                board = scene["boxes"][obj["parts"][0]]
                axis = min((0, 1), key=lambda a: board["size"][a])
                u, bb = 1 - axis, bounds(board)
                self.assertTrue(any(w["kind"] == "wall" and w["level"] == obj["level"] and
                    abs(w["center"][axis] - board["center"][axis]) < .15 and
                    bounds(w)[u] <= bb[u] + 1e-7 and bounds(w)[u + 3] >= bb[u + 3] - 1e-7 and
                    bounds(w)[2] <= bb[2] and bounds(w)[5] >= bb[5] for w in scene["boxes"]))

    def test_materials_have_real_images_and_metric_uvs(self):
        scene = generate(Config())
        styles = {b["texture"]["style"] for b in scene["boxes"] if "texture" in b}
        self.assertEqual(styles, {"tile", "planks", "plaster", "grain", "weave", "paint", "cardboard", "screen", "art", "notice", "sign"})
        painting = next(b for b in scene["boxes"] if b.get("texture", {}).get("style") == "art")
        path = texture_path(painting["texture"])
        with Image.open(path) as image:
            self.assertEqual(image.size, (512, 512))
            self.assertGreater(min(ImageStat.Stat(image).stddev), 25)
            self.assertGreater(len(image.getcolors(512 * 512)), 8)
        self.assertEqual(path, texture_path(painting["texture"]))
        box = dict(size=[4., 2., 3.], center=[8., 5., 1.5], texture=dict(style="tile", period=2.))
        mesh = box_mesh(box)
        self.assertEqual(len(mesh["vertices"]), 24)
        self.assertEqual(len(mesh["indices"]), 36)
        for i in range(0, 24, 4):
            a, b = mesh["vertices"][i:i + 2]
            uv_a, uv_b = mesh["uvs"][i:i + 2]
            self.assertAlmostEqual(math.dist(a, b), 2 * math.dist(uv_a, uv_b))

    def test_textures_preserve_physical_box_collisions(self):
        client = p.connect(p.DIRECT)
        try:
            scene = generate(Config(furnished=False))
            ids = load_pybullet(scene, client)
            for box, body in zip(scene["boxes"], ids):  # getCollisionShapeData does not support static maximal-coordinate bodies; the AABB is the collision box
                lo, hi = p.getAABB(body, physicsClientId=client)
                size = box.get("collision_size", box["size"])
                for a in range(3):
                    self.assertAlmostEqual(hi[a] - lo[a], size[a], 6)
                    self.assertAlmostEqual((hi[a] + lo[a]) / 2, box.get("collision_center", box["center"])[a], 6)
            self.assertTrue(any(p.getVisualShapeData(b, physicsClientId=client)[0][2] == p.GEOM_MESH for b in ids))
        finally:
            p.disconnect(client)


if __name__ == "__main__":
    unittest.main()
