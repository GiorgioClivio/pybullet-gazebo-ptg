"""Drop test of a Gazebo export: small spheres are released 1 cm above flat surfaces in PyBullet and in Gazebo, and must rest
on the same surface (height = surface + radius) in both physics engines.

    python3 tools/gazebo_probe.py make EXPORT [--count 120]
        picks flat, open spots with native PyBullet ray casts, drops the spheres there in PyBullet (1 ms steps,
        3 s) and writes EXPORT/probe_world.sdf (world.sdf plus the spheres) and EXPORT/probes.json
    python3 tools/gazebo_probe.py gazebo EXPORT [--engine gz-physics-dartsim-plugin]   (where `gz` is installed)
        steps probe_world.sdf for 3 s of simulated time with the gz.sim8 Python bindings (writes a copy of the
        world with the chosen engine in the current folder) and prints the sphere heights as JSON
    python3 tools/gazebo_probe.py check EXPORT POSES.json [POSES2.json ...]
        rest-height error per engine; exit 1 if any sphere is more than 5 mm off or missing

Only `gazebo` runs inside a Gazebo installation; it needs nothing but the standard library.
"""
from pathlib import Path
import argparse
import json
import math
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RADIUS, MASS, SETTLE = .05, .1, 3.  # m, kg, s of simulated time
DROP, FLAT = .01, .15  # start gap above the surface; flat radius around a spot (m)
TOLERANCE = .005
PROBE = """    <model name="{name}">
      <pose>{x!r} {y!r} {z!r} 0 0 0</pose>
      <link name="link">
        <inertial><mass>{m}</mass><inertia><ixx>{i}</ixx><iyy>{i}</iyy><izz>{i}</izz></inertia></inertial>
        <collision name="collision"><geometry><sphere><radius>{r}</radius></sphere></geometry></collision>
        <visual name="visual"><geometry><sphere><radius>{r}</radius></sphere></geometry>
          <material><diffuse>1 0 0 1</diffuse></material></visual>
      </link>
    </model>
"""


def _spots(scene, client, count):
    """Seeded flat spots on top surfaces: upward-facing, same height FLAT around, 0.6 m clear above, at most one per
    part (floors would otherwise take almost every spot); [(x, y, z)]."""
    import pybullet as p
    x0, y0, x1, y1 = scene["bounds"]
    rng, spots, used = random.Random(0), [], set()
    for _ in range(count * 400):
        if len(spots) == count:
            break
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        starts = [(x, y, 60.)] + [(x + FLAT * math.cos(k * math.pi / 4), y + FLAT * math.sin(k * math.pi / 4), 60.) for k in range(8)]
        hits = p.rayTestBatch(starts, [(s[0], s[1], -60.) for s in starts], physicsClientId=client)
        z = [h[3][2] for h in hits]
        if hits[0][0] < 0 or hits[0][0] in used or hits[0][4][2] < .999 or max(z) - min(z) > 1e-3:
            continue
        up = p.rayTest((x, y, z[0] + .01), (x, y, z[0] + .6), physicsClientId=client)[0]
        if up[0] < 0:
            spots.append((x, y, z[0]))
            used.add(hits[0][0])
    return spots


def _drop(client, spots):
    """Rest height of a sphere released DROP above each spot, after SETTLE s at 1 ms steps."""
    import pybullet as p
    p.setGravity(0, 0, -9.81, physicsClientId=client)
    p.setTimeStep(.001, physicsClientId=client)
    shape = p.createCollisionShape(p.GEOM_SPHERE, radius=RADIUS, physicsClientId=client)
    balls = [p.createMultiBody(MASS, shape, basePosition=(x, y, z + RADIUS + DROP), physicsClientId=client) for x, y, z in spots]
    for ball in balls:
        p.changeDynamics(ball, -1, lateralFriction=.8, restitution=0, rollingFriction=1e-3, physicsClientId=client)
    for _ in range(int(SETTLE / .001)):
        p.stepSimulation(physicsClientId=client)
    return [p.getBasePositionAndOrientation(b, physicsClientId=client)[0][2] for b in balls]


def make(export, count):
    """Choose the spots, run the PyBullet drop, write probe_world.sdf and probes.json."""
    import pybullet as p
    from indoor import load_pybullet
    scene = json.loads((export / "scene.json").read_text())
    client = p.connect(p.DIRECT)
    load_pybullet(scene, client, visuals=False)
    spots = _spots(scene, client, count)
    rest = _drop(client, spots)
    # Keep only spots where the PyBullet reference rests on its surface (a sphere on an edge may roll off).
    kept = [(spot, r) for spot, r in zip(spots, rest) if abs(r - spot[2] - RADIUS) <= TOLERANCE]
    probes = [dict(name=f"probe_{k}", x=x, y=y, surface=z, pybullet=r) for k, ((x, y, z), r) in enumerate(kept)]
    world = (export / "world.sdf").read_text()
    models = "".join(PROBE.format(name=q["name"], x=q["x"], y=q["y"], z=q["surface"] + RADIUS + DROP, m=MASS, r=RADIUS,
                                  i=.4 * MASS * RADIUS ** 2) for q in probes)
    # Collisions only: drop the rendering-based Sensors system (software ogre2 in a GPU-less container is the load).
    world = "\n".join(line for line in world.splitlines() if "sensors-system" not in line and "render_engine" not in line
                       and "</plugin>" not in line) + "\n"
    (export / "probe_world.sdf").write_text(world.replace("  </world>", models + "  </world>"))
    (export / "probes.json").write_text(json.dumps(probes, indent=1) + "\n")
    print(f"{len(probes)} probes written to {export}/probe_world.sdf and probes.json "
          f"({len(spots) - len(probes)} spots dropped: the sphere did not rest there in PyBullet)")


def gazebo(export, engine):
    """Step probe_world.sdf in-process (gz.sim8 TestFixture, no transport) for SETTLE s; print {probe: z} as JSON.

    The engine goes into the Physics system's <engine> element of a copy of the world in the current folder."""
    import gz.math7  # noqa: F401  registers Pose3d, the return type of Link.world_pose
    from gz.sim8 import Link, Model, TestFixture, World, world_entity
    names = [q["name"] for q in json.loads((export / "probes.json").read_text())]
    plugin = '<plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>'
    world = (export / "probe_world.sdf").read_text()
    assert world.count(plugin) == 1, "Physics system line not found"
    Path("probe_world.sdf").write_text(world.replace(plugin, plugin[:-2] + f"><engine><filename>{engine}</filename></engine></plugin>"))
    steps, z, sim = int(SETTLE / .001), {}, [0.]

    def record(info, ecm):
        """After the last step: every probe's link height."""
        if info.iterations < steps:
            return
        w = World(world_entity(ecm))
        for name in names:
            pose = Link(Model(w.model_by_name(ecm, name)).link_by_name(ecm, "link")).world_pose(ecm)
            if pose is not None:
                z[name] = pose.pos().z()
        sim[0] = info.sim_time.total_seconds()

    fixture = TestFixture(str(Path("probe_world.sdf").resolve()))
    fixture.on_post_update(record)
    fixture.finalize()
    clock = time.perf_counter()
    fixture.server().run(True, steps, False)
    wall = time.perf_counter() - clock   # the world asks for real time: wall > sim time means the physics is too slow
    print(json.dumps(dict(engine=engine, sim_time=sim[0], wall_s=round(wall, 2), rtf=round(sim[0] / wall, 3), z=z)))


def check(export, results):
    """Rest-height error |z - (surface + radius)| per engine (PyBullet first); exit 1 above TOLERANCE."""
    probes = json.loads((export / "probes.json").read_text())
    runs = [("pybullet", {q["name"]: q["pybullet"] for q in probes})]
    runs += [(r["engine"], r["z"]) for r in (json.loads(Path(f).read_text()) for f in results)]
    failed = False
    print(f"{'engine':40} {'probes':>6} {'missing':>7} {'median mm':>9} {'max mm':>7} {'> 5 mm':>6}")
    for engine, z in runs:
        errors = sorted(abs(z[q["name"]] - q["surface"] - RADIUS) for q in probes if q["name"] in z)
        missing, bad = len(probes) - len(errors), sum(e > TOLERANCE for e in errors)
        failed |= bool(missing or bad)
        median = errors[len(errors) // 2] * 1e3 if errors else float("nan")
        print(f"{engine:40} {len(probes):6d} {missing:7d} {median:9.2f} {max(errors, default=0) * 1e3:7.2f} {bad:6d}")
    sys.exit(1 if failed else 0)


def main():
    """Command line (see the module docstring)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("make", "gazebo", "check"))
    parser.add_argument("export", type=Path)
    parser.add_argument("results", nargs="*", help="check: JSON files printed by `gazebo`")
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--engine", default="gz-physics-dartsim-plugin", help="gazebo: physics plugin")
    args = parser.parse_args()
    if args.action == "make":
        make(args.export, args.count)
    elif args.action == "gazebo":
        gazebo(args.export, args.engine)
    else:
        check(args.export, args.results)


if __name__ == "__main__":
    main()
