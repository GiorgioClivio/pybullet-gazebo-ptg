"""Metro station: determinism, validation, top-down reachability, lanes, and collision traversal."""
import json
import math
import os
import unittest

from furniture import _crosses
from metro import HEADROOM, PALETTES, MetroConfig, _helix_plan, _quat, _subtract, generate_metro

CONFIGS = [dict(layout=layout, spiral_ramp=ramp) for layout in ("island", "side") for ramp in (True, False)]
SEEDED = range(30)  # Fully seeded stations (envelope, layout, ramp) checked by the layout tests.
# Seeds of the PyBullet traversal on fully seeded stations; METRO_SEEDS=0-29 for the full sweep (about 1 s per seed).
TRAVERSE = [int(v) for item in os.environ.get("METRO_SEEDS", "0,1").split(",")
            for v in (range(int(item.split("-")[0]), int(item.split("-")[1]) + 1) if "-" in item else [item])]


def graph(scene):
    """Space adjacency through portals, stairs and ramps: {space id: neighbour ids}."""
    nodes = {s["id"]: set() for s in scene["spaces"]}
    for a, b in ([e["rooms"] for e in scene["portals"]] + [[s["lower"], s["upper"]] for s in scene["stairs"]] +
                 [[r["lower"], r["upper"]] for r in scene["ramps"]]):
        nodes[a].add(b)
        nodes[b].add(a)
    return nodes


def reachable(scene, start=0):
    """Space ids reachable from `start` in the station graph."""
    nodes, seen, pending = graph(scene), set(), [start]
    while pending:
        node = pending.pop()
        if node not in seen:
            seen.add(node)
            pending.extend(nodes[node] - seen)
    return seen


class LayoutTests(unittest.TestCase):
    def test_determinism_and_export(self):
        scene = generate_metro(MetroConfig(seed=-3))
        again = generate_metro(MetroConfig(seed=-3))
        scene["metro_stats"].pop("generation_s"), again["metro_stats"].pop("generation_s")
        self.assertEqual(scene, again)
        self.assertEqual(scene, json.loads(json.dumps(scene)))
        self.assertNotEqual(scene["boxes"], generate_metro(MetroConfig(seed=4))["boxes"])

    def test_validation(self):
        for kwargs in ({"riser": .2}, {"tread": .25}, {"platform_height": .5}, {"layout": "loop"}, {"track_bed": "grass"},
                       {"platform_length": 30.}, {"depth": 3.}, {"stair_width": 1.}, {"island_width": 6.},
                       {"ramp_slope": .1}, {"ramp_run_rise": .9}, {"ramp_width": .8}, {"tunnel_diameter": 4.},
                       {"seed": 1.5}, {"roof": 1}, {"depth": float("nan")}, {"flight_rise": 4.}):
            with self.assertRaises(ValueError, msg=kwargs):
                MetroConfig(**kwargs)

    def test_reachability_from_top_spawn(self):
        for kwargs in CONFIGS:
            for seed in range(25):
                scene = generate_metro(MetroConfig(seed=seed, **kwargs))
                spawn = scene["spaces"][0]
                self.assertEqual(spawn["level"], 1)
                x0, y0, x1, y1 = spawn["rect"]
                self.assertTrue(x0 < scene["spawn"][0] < x1 and y0 < scene["spawn"][1] < y1)
                seen = reachable(scene)
                for s in scene["spaces"]:
                    if s["traversable"]:
                        self.assertIn(s["id"], seen, (seed, kwargs, s))
                    else:
                        self.assertNotIn(s["id"], seen)
                self.assertTrue(any(scene["spaces"][i]["kind"] == "platform" for i in seen))
                self.assertEqual(len(scene["stairs"]), 2)
                self.assertEqual(len(scene["ramps"]), int(kwargs["spiral_ramp"]))

    def test_dimensions_within_limits(self):
        c = MetroConfig()
        self.assertLessEqual(c.rise, .178)
        self.assertGreaterEqual(c.tread, .279)
        self.assertLessEqual(max(c.flights) * c.rise, 3.658)
        plan = _helix_plan(c)
        self.assertGreaterEqual(plan["headroom"], HEADROOM)
        self.assertLessEqual(plan["slope_inner"], 1 / 12 + 1e-9)
        self.assertLess(plan["slope_centre"], plan["slope_inner"])
        self.assertAlmostEqual(plan["rise_per_run"] * plan["runs"], c.depth)
        self.assertLessEqual(plan["rise_per_run"], .76)

    def test_seeded_envelope(self):
        """Seeded fields stay in their ranges, explicit ones are kept and do not shift the others, seeds differ."""
        configs = [MetroConfig(seed=s) for s in SEEDED]
        for c in configs:
            self.assertTrue(65 <= c.platform_length <= 140 and 7.5 <= c.column_spacing <= 10.5, c)
            self.assertTrue(4.5 <= c.concourse_height <= 7 and 6 <= c.depth <= 12 and 4 <= c.room_depth <= 6.5, c)
            self.assertTrue(2.4 <= c.stair_width <= 3.4 and c.palette in PALETTES and c.track_bed in ("concrete", "ballast"), c)
        for field in ("platform_length", "column_spacing", "concourse_height", "depth", "palette"):
            self.assertGreater(len({getattr(c, field) for c in configs}), 4, field)
        for field in ("spiral_ramp", "track_bed"):
            self.assertEqual(len({getattr(c, field) for c in configs}), 2, field)
        explicit = MetroConfig(seed=3, platform_length=90., depth=7.5, spiral_ramp=True, track_bed="concrete", palette="blue")
        self.assertEqual((explicit.platform_length, explicit.depth, explicit.spiral_ramp, explicit.track_bed, explicit.palette),
                         (90., 7.5, True, "concrete", "blue"))
        seeded = MetroConfig(seed=3)
        for field in ("column_spacing", "concourse_height", "room_depth", "stair_width", "island_width", "side_width"):
            self.assertEqual(getattr(explicit, field), getattr(seeded, field), field)
        a, b = generate_metro(MetroConfig(seed=0)), generate_metro(MetroConfig(seed=1))
        self.assertNotEqual(a["bounds"], b["bounds"])
        self.assertNotEqual(a["config"]["palette"], b["config"]["palette"])

    def test_objects_inside_bounds_and_off_lanes(self):
        for kwargs in CONFIGS + [dict(seed=s) for s in SEEDED]:
            kwargs = dict(dict(seed=11), **kwargs)
            scene = generate_metro(MetroConfig(**kwargs))
            bx0, by0, bx1, by1 = scene["bounds"]
            lanes = {0: [], 1: []}
            for path in scene["clear_paths"]:
                if path.get("kind") == "ramp_centreline":
                    continue
                level = scene["spaces"][path["room"]]["level"]
                lanes[level].extend(zip([p[:2] for p in path["points"]], [p[:2] for p in path["points"][1:]]))
            floor = {0: scene["levels"][0]["floor_z"], 1: 0.}
            for obj in scene["objects"]:
                r = obj["bounds"]
                self.assertTrue(bx0 <= r[0] and r[2] <= bx1 and by0 <= r[1] and r[3] <= by1, obj["kind"])
                room = scene["spaces"][obj["room"]]["rect"]
                if obj["kind"] in ("ticket_gate", "barrier"):  # The gateline straddles paid/unpaid.
                    halls = [s["rect"] for s in scene["spaces"] if s["kind"] == "concourse"]
                    room = [min(h[0] for h in halls), min(h[1] for h in halls), max(h[2] for h in halls), max(h[3] for h in halls)]
                self.assertTrue(room[0] - .01 <= r[0] and r[2] <= room[2] + .01 and room[1] - .01 <= r[1] and r[3] <= room[3] + .01,
                                (obj["kind"], r, room))
                if obj["z_range"][0] < floor[obj["level"]] + 2.0:
                    for a, b in lanes[obj["level"]]:
                        self.assertFalse(_crosses(r, a, b, .45), (kwargs, obj["kind"], r, a, b))
                    if obj["level"] == 1:  # Spawn clear: 1 m around the robot drop point.
                        self.assertFalse(_crosses(r, scene["spawn"][:2], scene["spawn"][:2], 1.), (kwargs, obj["kind"]))
            # No two objects intersect in 3D (wall items never cut into furniture); the gateline is one assembly.
            solid = [o for o in scene["objects"] if o["kind"] not in ("ticket_gate", "barrier")]
            for i, o in enumerate(solid):
                for q in solid[i + 1:]:
                    a, b = o["bounds"], q["bounds"]
                    if o["level"] == q["level"] and a[0] < b[2] - .01 and b[0] < a[2] - .01 and a[1] < b[3] - .01 and b[1] < a[3] - .01:
                        self.assertFalse(o["z_range"][0] < q["z_range"][1] - .01 and q["z_range"][0] < o["z_range"][1] - .01,
                                         (kwargs, o["kind"], q["kind"], a, b))

    def test_helpers(self):
        self.assertEqual(_subtract([0, 0, 4, 4], [[1, 1, 2, 2]]), [[0, 0, 1, 4], [1, 0, 2, 1], [1, 2, 2, 4], [2, 0, 4, 4]])
        self.assertEqual(sum((r[2] - r[0]) * (r[3] - r[1]) for r in _subtract([0, 0, 10, 5], [[2, 1, 4, 3], [3, 2, 6, 6]])),
                         50 - 4 - 9 + 1)


class PhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pybullet as p
        cls.p = p
        cls.client = p.connect(p.DIRECT)

    @classmethod
    def tearDownClass(cls):
        cls.p.disconnect(cls.client)

    def test_quaternion_convention(self):
        from metro import _extent
        p, cid = self.p, self.client
        for rpy in ((.3, 0, 0), (0, -.4, 1.2), (.1, .2, -2.5)):
            for a, b in zip(_quat(*rpy), p.getQuaternionFromEuler(rpy)):
                self.assertAlmostEqual(a, b, places=9)
            part = dict(size=[3., .4, .2], center=[1., 2., 3.], orientation=_quat(*rpy))
            shape = p.createCollisionShape(p.GEOM_BOX, halfExtents=[s / 2 for s in part["size"]], physicsClientId=cid)
            body = p.createMultiBody(0, shape, basePosition=part["center"], baseOrientation=part["orientation"], physicsClientId=cid)
            lo, hi = p.getAABB(body, physicsClientId=cid)
            for a, v in enumerate(_extent(part)):
                self.assertAlmostEqual(v, (lo + hi)[a], delta=.03)  # Bullet pads AABBs by a small margin.

    def _check_stairs(self, scene, kwargs, support, clear):
        """Walk every flight tread by tread: support at each tread, clearance and 2.4 m headroom above it."""
        p, cid = self.p, self.client
        for stair in scene["stairs"]:
            x, y, _ = stair["top"]
            z = 0.
            for k, count in enumerate(stair["flights"]):
                for _ in range(count - 1):
                    z -= stair["rise"]
                    x -= stair["tread"]
                    xm = x + stair["tread"] / 2
                    hit = support(xm, y, z)
                    self.assertAlmostEqual(hit[3][2], z, places=5, msg=(kwargs, xm, y, k))
                    clear([xm, y, z + .65], "stair")
                    up = p.rayTest([xm, y, z + .02], [xm, y, z + 2.4], physicsClientId=cid)[0]
                    self.assertEqual(up[0], -1, (kwargs, "stair headroom", xm))
                z -= stair["rise"]
                if k < len(stair["flights"]) - 1:
                    x -= stair["landing"]
            self.assertAlmostEqual(z, stair["bottom"][2], places=6)
            self.assertAlmostEqual(x, stair["bottom"][0], places=6)

    def test_traversal_with_proxy(self):
        """Sweep a 60 cm wide/tall proxy along every lane, stair and the ramp; check support and headroom."""
        p, cid = self.p, self.client
        from indoor import load_pybullet
        for kwargs in [dict(seed=5, **k) for k in CONFIGS] + [dict(seed=s) for s in TRAVERSE]:
            p.resetSimulation(physicsClientId=cid)
            scene = generate_metro(MetroConfig(**kwargs))
            bodies = load_pybullet(scene, cid)
            self.assertEqual(len(bodies), len(scene["boxes"]))
            shape = p.createCollisionShape(p.GEOM_CYLINDER, radius=.3, height=.6, physicsClientId=cid)
            proxy = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=shape, physicsClientId=cid)
            built = set(bodies)

            def clear(point, what):
                p.resetBasePositionAndOrientation(proxy, point, [0, 0, 0, 1], physicsClientId=cid)
                for body, _ in p.getOverlappingObjects(*p.getAABB(proxy, physicsClientId=cid), physicsClientId=cid) or ():
                    if body in built:
                        hits = p.getClosestPoints(proxy, body, distance=-.001, physicsClientId=cid)
                        self.assertFalse(hits, (kwargs, what, point, scene["boxes"][bodies.index(body)].get("element"),
                                                scene["boxes"][bodies.index(body)].get("label")))
                p.resetBasePositionAndOrientation(proxy, [0, 0, 100], [0, 0, 0, 1], physicsClientId=cid)

            def support(x, y, z):
                p.resetBasePositionAndOrientation(proxy, [0, 0, 100], [0, 0, 0, 1], physicsClientId=cid)
                return p.rayTest([x, y, z + .3], [x, y, z - .3], physicsClientId=cid)[0]

            for path in scene["clear_paths"]:
                points = path["points"]
                for a, b in zip(points, points[1:]):
                    steps = max(1, math.ceil(math.dist(a, b) / .2))
                    for j in range(steps + 1):
                        q = [u + (v - u) * j / steps for u, v in zip(a, b)]
                        hit = support(*q)
                        self.assertNotEqual(hit[0], -1, (kwargs, path["room"], q))
                        self.assertAlmostEqual(hit[3][2], q[2], delta=.03 if path.get("kind") else .012,
                                               msg=(kwargs, scene["spaces"][path["room"]]["name"], q,
                                                    scene["boxes"][bodies.index(hit[0])].get("element") if hit[0] in bodies else hit[0]))
                        clear([q[0], q[1], hit[3][2] + .65], path.get("kind", "lane"))
                        if path.get("kind"):
                            up = p.rayTest([q[0], q[1], hit[3][2] + .02], [q[0], q[1], hit[3][2] + HEADROOM], physicsClientId=cid)[0]
                            self.assertEqual(up[0], -1, (kwargs, "ramp headroom", q))
            self._check_stairs(scene, kwargs, support, clear)
            p.removeBody(proxy, physicsClientId=cid)
            robot = p.createMultiBody(baseMass=10, baseCollisionShapeIndex=shape, basePosition=scene["spawn"], physicsClientId=cid)
            p.setGravity(0, 0, -9.81, physicsClientId=cid)
            for _ in range(240):
                p.stepSimulation(physicsClientId=cid)
            self.assertAlmostEqual(p.getBasePositionAndOrientation(robot, physicsClientId=cid)[0][2], .3, delta=.01)


if __name__ == "__main__":
    unittest.main()
