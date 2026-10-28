"""Mine tunnels (tunnel.py), seeds 0-9: seeded, dead ends and through chambers, galleries crossing over others, walkable
floors with headroom, the reference robot drives through every gallery, the viewer's walker walks every gallery."""
import json
import math
import unittest

import pybullet as p

from indoor import load_pybullet
from tunnel import HEADROOM, TunnelConfig, clearance, generate_tunnel
from viewer import Walker
import settings

SEEDS = range(10)
STEP = .21   # 0.1 m samples: a cell edge rises at most 0.15 m (riser + terrace); a diagonal through a cell corner
             # meets two 0.10 m edges at once (0.20 m), still under a mid-size quadruped's 0.3 m step


def _same(a, b):
    a, b = dict(a, tunnel_stats=None), dict(b, tunnel_stats=None)
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _samples(path, spacing):
    """(x, y, path z) every `spacing` metres along a clear path."""
    out = []
    for a, b in zip(path["points"], path["points"][1:]):
        k = max(1, math.ceil(math.dist(a[:2], b[:2]) / spacing))
        out += [tuple(a[i] + (b[i] - a[i]) * t / k for i in range(3)) for t in range(k)]
    return out + [tuple(path["points"][-1])]


class TunnelTests(unittest.TestCase):
    LEVELS = 1

    @classmethod
    def setUpClass(cls):
        cls.scenes = {seed: generate_tunnel(TunnelConfig(seed=seed, levels=cls.LEVELS)) for seed in SEEDS}

    def _client(self, scene):
        cid = p.connect(p.DIRECT)
        self.addCleanup(p.disconnect, cid)
        return cid, load_pybullet(scene, cid, visuals=False)

    def test_seeded(self):
        self.assertTrue(_same(self.scenes[7], generate_tunnel(TunnelConfig(seed=7, levels=self.LEVELS))))
        self.assertFalse(_same(self.scenes[0], self.scenes[7]))

    def test_dead_ends_and_through_chambers(self):
        for seed, scene in self.scenes.items():
            chambers = [s for s in scene["spaces"] if s["kind"] in ("chamber", "room")]
            tunnels = [s for s in scene["spaces"] if s["kind"] == "tunnel"]
            degree = {c["id"]: sum(c["id"] in t["rooms"] for t in tunnels) for c in chambers}
            self.assertTrue(any(c["dead_end"] for c in chambers), f"seed {seed}")
            self.assertTrue(any(degree[c["id"]] >= 2 for c in chambers), f"seed {seed}")
            self.assertTrue(all(degree[c["id"]] >= 1 for c in chambers), f"seed {seed}")

    def test_galleries_cross_over_each_other(self):
        if self.LEVELS == 1:
            self.skipTest("one level: no gallery over another")
        crossing = 0
        for scene in self.scenes.values():
            points = [(path["room"], q) for path in scene["clear_paths"] for q in _samples(path, .5)]
            crossing += any(r1 != r2 and math.dist(a[:2], b[:2]) < .5 and abs(a[2] - b[2]) > 2.5
                            for k, (r1, a) in enumerate(points) for r2, b in points[k + 1:])
        self.assertGreaterEqual(crossing, len(SEEDS) // 2, "galleries pass over other galleries in at least half the seeds")

    def test_galleries_are_walkable(self):
        for seed, scene in self.scenes.items():
            cid, _ = self._client(scene)
            for path in scene["clear_paths"]:
                points = _samples(path, .1)
                # From 1.2 m above the path: below the timber caps (>= 2 m up), above anything left on the floor.
                down = p.rayTestBatch([(x, y, z + 1.2) for x, y, z in points], [(x, y, z - 2.) for x, y, z in points],
                                      physicsClientId=cid)
                self.assertTrue(all(h[0] >= 0 for h in down), f"seed {seed}: hole in gallery {path['room']}")
                floors = [h[3][2] for h in down]
                worst = max(abs(u - v) for u, v in zip(floors, floors[1:]))
                self.assertLessEqual(worst, STEP, f"seed {seed}: {worst:.2f} m step along gallery {path['room']}")

    def test_robot_drives_through(self):
        """A box of the robot's footprint plus margin (body from 0.35 m above the floor to its height + margin),
        turned along the path, placed every 0.25 m of every gallery touches nothing but the floor."""
        robot = settings.current()["tunnel"]["robot"]
        half, height = clearance()
        length = robot["length"] / 2 + robot["margin"]
        for seed, scene in self.scenes.items():
            cid, ids = self._client(scene)
            shape = p.createCollisionShape(p.GEOM_BOX, halfExtents=[length, half, (height - .35) / 2], physicsClientId=cid)
            probe = p.createMultiBody(0, shape, basePosition=[0, 0, -50], physicsClientId=cid)
            dead = {s["id"] for s in scene["spaces"] if s.get("dead_end") and s["kind"] == "tunnel"}
            for path in scene["clear_paths"]:
                points = _samples(path, .25)
                if path["room"] in dead:   # the robot's centre stops half a body short of a dead end's rock face
                    points = points[:max(2, len(points) - math.ceil(length / .25))]
                for (x, y, z), (x1, y1, _) in zip(points, points[1:]):
                    p.resetBasePositionAndOrientation(probe, [0, 0, -50], [0, 0, 0, 1], physicsClientId=cid)  # off the ray
                    floor = p.rayTest((x, y, z + 1.2), (x, y, z - 2.), physicsClientId=cid)[0][3][2]
                    yaw = math.atan2(y1 - y, x1 - x)
                    p.resetBasePositionAndOrientation(probe, [x, y, floor + .35 + (height - .35) / 2],
                                                      p.getQuaternionFromEuler([0, 0, yaw]), physicsClientId=cid)
                    # Bullet reports no contacts between static bodies: query distances instead.
                    near = {o for o, _ in p.getOverlappingObjects(*p.getAABB(probe, physicsClientId=cid), physicsClientId=cid) or ()
                            if o != probe and scene["boxes"][ids.index(o)]["kind"] != "floor"}   # steps: legs' business
                    touching = [o for o in near if min((c[8] for c in p.getClosestPoints(probe, o, 0., physicsClientId=cid)),
                                                       default=1.) < -1e-4]
                    self.assertFalse(touching, f"seed {seed}: the robot cannot pass ({x:.2f}, {y:.2f}) in gallery {path['room']}: "
                                               f"touches {[scene['boxes'][ids.index(o)].get('element', scene['boxes'][ids.index(o)]['kind']) for o in touching]}")

    def test_walker_walks_every_gallery(self):
        """The viewer's walk mode follows every gallery end to end (steps, terraces and ramps included)."""
        for seed, scene in self.scenes.items():
            cid, _ = self._client(scene)
            for path in scene["clear_paths"]:
                (x, y, z), *rest = path["points"]
                floor = p.rayTest((x, y, z + 1.2), (x, y, z - 2.), physicsClientId=cid)[0][3][2]
                walker = Walker(cid, [x, y, floor + .002])
                for target in rest:
                    for _ in range(400):
                        dx, dy = target[0] - walker.feet[0], target[1] - walker.feet[1]
                        gap = math.hypot(dx, dy)
                        if gap < .15:
                            break
                        walker.move(dx / gap * min(.05, gap), dy / gap * min(.05, gap), 1 / 60)
                    self.assertLess(math.dist(walker.feet[:2], target[:2]), .3,
                                    f"seed {seed}: the walker got stuck at {[round(v, 2) for v in walker.feet]} in gallery {path['room']}")
                p.removeBody(walker.body, physicsClientId=cid)

    def test_headroom(self):
        for seed in SEEDS:
            scene = generate_tunnel(TunnelConfig(seed=seed, roof=True, furnished=False, levels=self.LEVELS))
            cid, _ = self._client(scene)
            for path in scene["clear_paths"]:
                for x, y, z in path["points"]:
                    floor = p.rayTest((x, y, z + 1.), (x, y, z - 1.), physicsClientId=cid)[0][3][2]
                    ceiling = p.rayTest((x, y, floor + .05), (x, y, floor + 10.), physicsClientId=cid)[0]
                    self.assertGreaterEqual(ceiling[0], 0, f"seed {seed}: roof=True closes every gallery")
                    self.assertGreaterEqual(ceiling[3][2] - floor, HEADROOM - 1e-6, f"seed {seed}")

    def test_roof_is_closed(self, roof=True):
        """With roof=True no ray escapes to the sky from inside: from 1.5 m above every gallery and chamber path point,
        8 rays climbing at 45 degrees all hit rock (ceiling steps between a low gallery and a higher one included)."""
        rays = [(math.cos(k * math.pi / 4), math.sin(k * math.pi / 4), 1.) for k in range(8)]
        escaped = 0
        for seed in SEEDS:
            scene = generate_tunnel(TunnelConfig(seed=seed, roof=roof, furnished=False, levels=self.LEVELS))
            cid, _ = self._client(scene)
            starts = [(x, y, z + 1.5) for path in scene["clear_paths"] for x, y, z in _samples(path, .5)]
            froms = [s for s in starts for _ in rays]
            tos = [(x + 30 * dx, y + 30 * dy, z + 30 * dz) for x, y, z in starts for dx, dy, dz in rays]
            for k in range(0, len(froms), 8000):
                escaped += sum(h[0] < 0 for h in p.rayTestBatch(froms[k:k + 8000], tos[k:k + 8000], physicsClientId=cid))
        if roof:
            self.assertEqual(escaped, 0, f"{escaped} rays reach the sky through the roof")
        return escaped

    def test_rectangular_room_with_tables(self):
        for seed, scene in self.scenes.items():
            rooms = [s for s in scene["spaces"] if s["kind"] == "room"]
            self.assertGreaterEqual(len(rooms), 1)
            kinds = {o["kind"] for o in scene["objects"] if o["room"] in {r["id"] for r in rooms}}
            self.assertTrue(kinds & {"table_set", "workstation"}, f"seed {seed}: no table or desk in the rectangular room: {kinds}")

    def test_level_floors_option(self):
        if self.LEVELS > 1:
            self.skipTest("several levels: floors at several depths")
        scene = generate_tunnel(TunnelConfig(seed=7, steps=False, furnished=False))
        self.assertEqual({round(b["center"][2] + b["size"][2] / 2, 3) for b in scene["boxes"] if b["kind"] == "floor"}, {0.})

    def test_levels_joined_by_stairs(self):
        if self.LEVELS == 1:
            self.skipTest("one level")
        several = 0
        for seed, scene in self.scenes.items():
            for level in range(self.LEVELS - 1):
                count = sum(s["levels"] == [level, level + 1] for s in scene["stairs"])
                self.assertGreaterEqual(count, 1, f"seed {seed}: levels {level} and {level + 1} are not joined")
                several += count >= 2
            for stair in scene["stairs"]:
                self.assertLessEqual(stair["riser"], .15 + 1e-9, f"seed {seed}")
        self.assertGreaterEqual(several, .8 * len(SEEDS) * (self.LEVELS - 1), "most pairs of levels have 2-3 staircases")

    def test_ramps_are_gentle(self):
        for seed, scene in self.scenes.items():
            for ramp in scene["ramps"]:
                self.assertLessEqual(ramp["grade"], .12 + 1e-9, f"seed {seed}: ramp {ramp}")

    def test_sizes_vary(self):
        for seed, scene in self.scenes.items():
            tunnels = [s for s in scene["spaces"] if s["kind"] == "tunnel"]
            self.assertGreaterEqual(max(t["width"] for t in tunnels) - min(t["width"] for t in tunnels), .3, f"seed {seed}")
            self.assertGreaterEqual(max(t["height"] for t in tunnels) - min(t["height"] for t in tunnels), .2, f"seed {seed}")


class TwoLevelTunnelTests(TunnelTests):
    LEVELS = 2


class ThreeLevelTunnelTests(TunnelTests):
    LEVELS = 3


if __name__ == "__main__":
    unittest.main()
