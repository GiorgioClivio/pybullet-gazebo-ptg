"""Connectivity, clearances and physical support, without a locomotion controller."""
import json
import math
import unittest

import pybullet as p

from indoor import Config, generate, load_pybullet


class LayoutTests(unittest.TestCase):
    def test_seeds_and_reachability(self):
        for floors in (1, 2, 3):
            for seed in range(150):
                if seed == 66:
                    continue  # Lab D66 Easter egg: one room by design (test_room_styles covers it)
                scene = generate(Config(seed=seed, floors=floors, furnished=False, details=False))
                nodes = {s["id"]: set() for s in scene["spaces"]}
                for a, b in ([e["rooms"] for e in scene["portals"]] +
                             [[e["lower"], e["upper"]] for e in scene["stairs"]]):
                    nodes[a].add(b)
                    nodes[b].add(a)
                visited, pending = set(), [0]
                while pending:
                    node = pending.pop()
                    if node not in visited:
                        visited.add(node)
                        pending.extend(nodes[node] - visited)
                self.assertEqual(len(visited), len(nodes), (seed, floors))
                self.assertEqual(sum(s["kind"] == "room" for s in scene["spaces"]), 12 * floors)

    def test_reproducibility_and_export(self):
        scene = generate(Config(seed=-42, floors=3))
        self.assertEqual(scene, generate(Config(seed=-42, floors=3)))
        self.assertEqual(scene, json.loads(json.dumps(scene)))
        self.assertNotEqual(scene["boxes"], generate(Config(seed=43, floors=3))["boxes"])

    def test_storeys_differ_and_keep_their_own_seeds(self):
        for seed in range(100):
            if seed == 66:
                continue  # Lab D66 Easter egg: one room, one storey by design (test_room_styles covers it)
            scene = generate(Config(seed=seed, floors=3, furnished=False, details=False))
            layouts = [tuple(tuple(s["rect"]) for s in scene["spaces"] if s["level"] == level and s["kind"] == "room")
                       for level in range(3)]
            self.assertEqual(len(set(layouts)), 3)
            self.assertEqual(len(set(scene["floor_seeds"])), 3)
            shorter = generate(Config(seed=seed, floors=2, furnished=False, details=False))
            self.assertEqual([b for b in scene["boxes"] if b["level"] == 0],
                             [b for b in shorter["boxes"] if b["level"] == 0])

    def test_validation_and_dense_layout(self):
        for kwargs in ({"floors": 4}, {"rooms": 0}, {"rooms": 500}, {"width": float("nan")},
                       {"floors": 2, "depth": 6}, {"door_height": 5}, {"corridor": .5}):
            with self.assertRaises(ValueError, msg=kwargs):
                Config(**kwargs)
        for seed in range(30):
            self.assertEqual(sum(s["kind"] == "room" for s in generate(Config(seed=seed, rooms=30, furnished=False, details=False))["spaces"]), 30)
        exact = generate(Config(width=6.72, depth=3.36, rooms=2, furnished=False, details=False))
        self.assertEqual(sum(s["kind"] == "room" for s in exact["spaces"]), 2)


class PhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = p.connect(p.DIRECT)

    @classmethod
    def tearDownClass(cls):
        p.disconnect(cls.client)

    def setUp(self):
        p.resetSimulation(physicsClientId=self.client)

    def test_clear_routes_and_stairs(self):
        # Sweep a 60 cm diameter / 60 cm tall proxy along every graph edge.
        for seed in (0, 7, 101):
            p.resetSimulation(physicsClientId=self.client)
            c = Config(seed=seed, floors=3, roof=True)
            scene = generate(c)
            bodies = load_pybullet(scene, self.client)
            self.assertEqual(len(bodies), len(scene["boxes"]))
            shape = p.createCollisionShape(p.GEOM_CYLINDER, radius=.3, height=.6, physicsClientId=self.client)
            proxy = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=shape, physicsClientId=self.client)
            building = set(bodies)

            def clear(point):
                p.resetBasePositionAndOrientation(proxy, point, [0, 0, 0, 1], physicsClientId=self.client)
                for body, _ in p.getOverlappingObjects(*p.getAABB(proxy, physicsClientId=self.client), physicsClientId=self.client) or ():
                    if body not in building:
                        continue
                    hits = p.getClosestPoints(proxy, body, distance=-.001, physicsClientId=self.client)
                    self.assertFalse(hits, (seed, point, scene["boxes"][body]))

            for e in scene["portals"]:
                portal = e["center"][:]
                portal[2] += .65
                for room in e["rooms"]:
                    s = scene["spaces"][room]
                    x0, y0, x1, y1 = s["rect"]
                    center = [(x0 + x1) / 2, (y0 + y1) / 2, portal[2]]
                    approach = portal[:]
                    normal = 1 - e["axis"]
                    approach[normal] += math.copysign(.5, center[normal] - portal[normal])
                    for start, end in ((center, approach), (approach, portal)):
                        steps = math.ceil(math.dist(start, end) / .2)
                        for j in range(steps + 1):
                            point = [a + (b - a) * j / max(steps, 1) for a, b in zip(start, end)]
                            clear(point)
                            # Every route has a real slab below it, including thresholds.
                            hit = p.rayTest([*point[:2], portal[2] - .4],
                                            [*point[:2], portal[2] - .8], physicsClientId=self.client)[0]
                            self.assertNotEqual(hit[0], -1, point)
            for stair in scene["stairs"]:
                x, _, z = stair["start"]
                for i in range(1, c.risers):
                    y, top = c.landing + (i - .5) * .28, z + i * stair["rise"]
                    clear([x, y, top + .65])
                    p.resetBasePositionAndOrientation(proxy, [-100, 0, 0], [0, 0, 0, 1], physicsClientId=self.client)
                    hit = p.rayTest([x, y, top + .01], [x, y, top - .02], physicsClientId=self.client)[0]
                    self.assertAlmostEqual(hit[3][2], top, places=6)
                    head = p.rayTest([x, y, top + .02], [x, y, top + 2.4], physicsClientId=self.client)[0]
                    self.assertEqual(head[0], -1, (seed, i, "stair headroom"))
            # A released dynamic body must settle on the actual ground, not fall through.
            p.removeBody(proxy, physicsClientId=self.client)
            robot = p.createMultiBody(baseMass=10, baseCollisionShapeIndex=shape,
                                      basePosition=scene["spawn"], physicsClientId=self.client)
            p.setGravity(0, 0, -9.81, physicsClientId=self.client)
            for _ in range(240):
                p.stepSimulation(physicsClientId=self.client)
            self.assertAlmostEqual(p.getBasePositionAndOrientation(robot, physicsClientId=self.client)[0][2], .3, delta=.01)

    def test_walls_and_glazing_collide(self):
        scene = generate(Config())
        ids = load_pybullet(scene, self.client)
        for i, box in enumerate(scene["boxes"]):
            if box["kind"] not in ("wall", "glass"):
                continue
            center = box["center"]
            axis = 0 if box["size"][0] < box["size"][1] else 1
            start, end = center[:], center[:]
            start[axis] -= .3
            end[axis] += .3
            self.assertNotEqual(p.rayTest(start, end, physicsClientId=self.client)[0][0], -1)
        self.assertTrue(any(b["kind"] == "glass" for b in scene["boxes"]))


if __name__ == "__main__":
    unittest.main()
