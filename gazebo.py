"""Gazebo Sim (Harmonic, SDF 1.11) export of a generated scene, and a PyBullet loader for the same files.

One static model, one link: a collision per architectural part, chosen by indoor.collision_shape exactly as load_pybullet
does (box, the exact convex hull of the part mesh written as a mesh, or a concave trimesh for cables), and the same shapes of
the objects (furniture, landmarks, props) merged into one concave mesh per storey and kind (collision_groups), friction 0.8
and no restitution; the visuals are fastload's merged meshes (one per storey, kind, texture and colour) with their textures.

    python3 gazebo.py --seed 7 --out exports/building_seed7            # building
    python3 gazebo.py --metro --seed 7 --out exports/metro_seed7       # metro station
    gz sim -r exports/building_seed7/world.sdf                         # GZ_SIM_RESOURCE_PATH must hold exports/building_seed7

Output: world.sdf (runnable world that includes the model), <model>/model.config, <model>/model.sdf,
<model>/meshes/*.obj, <model>/textures/*.png, scene.json (spawn, spaces, clear paths, objects).
load_export(world_dir, client) builds the same bodies in PyBullet from those files: tools/gazebo_parity.py
checks that they collide and look like load_pybullet's.
"""
from pathlib import Path
import argparse
import itertools
import json
import shutil
import xml.etree.ElementTree as ET

FRICTION = .8  # load_pybullet: lateralFriction=.8, restitution=0
MERGED = ("furniture", "landmark", "prop")  # objects: one concave collision mesh per storey and kind (collision_groups)
# Gazebo's default empty world (systems, scene, sun) plus the scene model.
WORLD = """<?xml version="1.0" ?>
<sdf version="1.11">
  <world name="{name}">
    <physics name="1ms" type="bullet-featherstone">
      <max_step_size>0.001</max_step_size>
      <dart><collision_detector>bullet</collision_detector></dart>
      <real_time_factor>1.0</real_time_factor>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>
    <plugin filename="gz-sim-contact-system" name="gz::sim::systems::Contact"/>
    <gravity>0 0 -9.81</gravity>
    <scene>
      <ambient>1.0 1.0 1.0</ambient>
      <background>0.8 0.8 0.8</background>
      <grid>false</grid>
    </scene>
    <light type="directional" name="sun">
      <cast_shadows>true</cast_shadows>
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.8 0.8 0.8 1</diffuse>
      <specular>0.2 0.2 0.2 1</specular>
      <direction>-0.5 0.1 -0.9</direction>
    </light>
    <include>
      <uri>model://{model}</uri>
    </include>
  </world>
</sdf>
"""


def _num(values):
    """Space-separated floats that read back bit for bit."""
    return " ".join(repr(float(v)) for v in values)


def _vertex_normals(g):
    """Unit vertex normals: the area-weighted sum of the adjacent face normals."""
    v, sums = g["vertices"], [[0., 0., 0.] for _ in g["vertices"]]
    for i in range(0, len(g["indices"]), 3):
        a, b, c = (v[k] for k in g["indices"][i:i + 3])
        e, f = [b[j] - a[j] for j in range(3)], [c[j] - a[j] for j in range(3)]
        n = [e[1] * f[2] - e[2] * f[1], e[2] * f[0] - e[0] * f[2], e[0] * f[1] - e[1] * f[0]]
        for k in g["indices"][i:i + 3]:
            sums[k] = [s + m for s, m in zip(sums[k], n)]
    return [[x / (sum(y * y for y in n) ** .5 or 1.) for x in n] for n in sums]


def _write_obj(path, g, faces=True):
    """Wavefront OBJ of a mesh dict (vertices, indices, optional uvs/normals); 1-based v/vt/vn faces."""
    rows = ["mtllib default.mtl", "usemtl default"] + [f"v {_num(v)}" for v in g["vertices"]]
    uvs, normals = g.get("uvs"), g.get("normals") or _vertex_normals(g)  # Gazebo's DART drops meshes without normals
    rows += [f"vt {_num(t)}" for t in uvs or ()] + [f"vn {_num(n)}" for n in normals]
    tags = "/{0}/{0}" if uvs else "//{0}"
    corners = [f"{k + 1}{tags.format(k + 1)}" for k in g["indices"]] if faces else []
    rows += [f"f {' '.join(corners[i:i + 3])}" for i in range(0, len(corners), 3)]
    path.write_text("\n".join(rows) + "\n")


def _hull(g):
    """Exact convex hull of a mesh's vertices, the shape Bullet collides with, wound outwards. Gazebo's own
    <mesh optimization="convex_hull"> is a voxel (V-HACD) approximation, measured up to 8 mm larger."""
    import numpy as np
    from scipy.spatial import ConvexHull, QhullError
    points = np.asarray(g["vertices"], float)
    try:
        hull = ConvexHull(points)
    except QhullError:  # flat point set: the mesh itself is its hull
        return g
    used = sorted(set(hull.simplices.ravel().tolist()))
    remap, indices = {k: i for i, k in enumerate(used)}, []
    for tri, plane in zip(hull.simplices, hull.equations):
        a, b, c = points[tri]
        indices += [remap[int(k)] for k in (tri if np.dot(np.cross(b - a, c - a), plane[:3]) > 0 else tri[[0, 2, 1]])]
    return dict(vertices=points[used].tolist(), indices=indices)


def _pose(parent, center, q=(0, 0, 0, 1)):
    """<pose> child: position and an xyzw quaternion, as PyBullet stores them (SDF >= 1.9)."""
    ET.SubElement(parent, "pose", rotation_format="quat_xyzw").text = _num([*center, *q])


def collision_groups(scene):
    """[(collision name, [part indices])] in export order: every architectural part alone (c<i>_<kind>), the MERGED
    objects of one storey and kind together (m<level>_<kind>). Gazebo's DART plugin visits every collision shape at
    every 1 ms step: 2,100 separate furniture, landmark and prop shapes cost a third of real time with a quadruped
    in the building, and merging them into a few concave meshes restores real time (README "Gazebo Sim")."""
    groups, merged = [], {}
    for i, b in enumerate(scene["boxes"]):
        if b["kind"] in MERGED:
            merged.setdefault((b["level"], b["kind"]), []).append(i)
        else:
            groups.append((f"c{i}_{b['kind']}", [i]))
    return groups + [(f"m{level}_{kind}", parts) for (level, kind), parts in sorted(merged.items())]


def _append(merged, g, center, q):
    """Add g's triangles to the merged mesh, vertices moved into the world frame (position, xyzw quaternion)."""
    import numpy as np
    from scipy.spatial.transform import Rotation
    n = len(merged["vertices"])
    merged["vertices"] += (Rotation.from_quat(q).apply(np.asarray(g["vertices"], float)) + center).tolist()
    merged["indices"] += [n + k for k in g["indices"]]


def _collisions(link, scene, root):
    """One <collision> per collision_groups entry; single parts share one OBJ file per distinct shape (hull_*: convex hulls)."""
    from indoor import collision_shape
    files = {}
    for name, parts in collision_groups(scene):
        c = ET.SubElement(link, "collision", name=name)
        geometry = ET.SubElement(c, "geometry")
        if len(parts) > 1:  # the parts' shapes (box corners' hull, convex hull, trimesh), posed, in one concave mesh
            merged = dict(vertices=[], indices=[])
            for b in (scene["boxes"][i] for i in parts):
                key, kind, data = collision_shape(b)
                g = _hull(dict(vertices=[[x * s / 2 for x, s in zip(signs, data)] for signs in itertools.product((-1, 1), repeat=3)],
                               indices=[])) if kind == "box" else _hull(data) if kind == "convex" else data
                _append(merged, g, b.get("collision_center", b["center"]), b.get("orientation", (0, 0, 0, 1)))
            _pose(c, (0, 0, 0))
            files[name] = f"meshes/{name}.obj"
            _write_obj(root / files[name], merged)
            ET.SubElement(ET.SubElement(geometry, "mesh"), "uri").text = files[name]
            _friction(c)
            continue
        b = scene["boxes"][parts[0]]
        key, kind, data = collision_shape(b)
        _pose(c, b.get("collision_center", b["center"]), b.get("orientation", (0, 0, 0, 1)))
        if kind == "box":
            ET.SubElement(ET.SubElement(geometry, "box"), "size").text = _num(data)
        else:
            if key not in files:
                files[key] = f"meshes/{'hull' if kind == 'convex' else 'collision'}_{len(files):04d}.obj"
                _write_obj(root / files[key], _hull(data) if kind == "convex" else data)
            ET.SubElement(ET.SubElement(geometry, "mesh"), "uri").text = files[key]
        _friction(c)
    return len(files)


def _friction(collision):
    """<surface><friction> of a collision: FRICTION for ODE (mu, mu2) and bullet."""
    friction = ET.SubElement(ET.SubElement(collision, "surface"), "friction")
    ode = ET.SubElement(friction, "ode")
    ET.SubElement(ode, "mu").text = ET.SubElement(ode, "mu2").text = repr(FRICTION)
    ET.SubElement(ET.SubElement(friction, "bullet"), "friction").text = repr(FRICTION)


def _visuals(link, scene, root, textures=None):
    """fastload's merged meshes, world frame; colour as diffuse, texture as PBR albedo map."""
    from fastload import merge_groups
    for n, g in enumerate(merge_groups(scene, textures)):
        level, kind = g["key"][:2]
        v = ET.SubElement(link, "visual", name=f"v{n}_{kind}_L{level}")
        _write_obj(root / f"meshes/visual_{n:04d}.obj", g)
        ET.SubElement(ET.SubElement(ET.SubElement(v, "geometry"), "mesh"), "uri").text = f"meshes/visual_{n:04d}.obj"
        material = ET.SubElement(v, "material")
        ET.SubElement(material, "ambient").text = ET.SubElement(material, "diffuse").text = _num(g["color"])
        ET.SubElement(material, "specular").text = "0 0 0 1"
        if g["texture"] is not None:
            name = f"textures/{g['texture'].name}"
            if not (root / name).exists():
                shutil.copyfile(g["texture"], root / name)
            metal = ET.SubElement(ET.SubElement(material, "pbr"), "metal")
            ET.SubElement(metal, "albedo_map").text = name
            ET.SubElement(metal, "metalness").text, ET.SubElement(metal, "roughness").text = "0", "1"
        if g["color"][3] < 1:
            ET.SubElement(v, "transparency").text = repr(1 - g["color"][3])
            ET.SubElement(v, "cast_shadows").text = "false"


def export_sdf(scene, out, name="ptg_scene", textures=None):
    """Write the scene as a Gazebo model plus a world that includes it (layout in the module docstring); returns out."""
    out = Path(out)
    root = out / name
    for sub in ("meshes", "textures"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "meshes/default.mtl").write_text("newmtl default\nKd 1 1 1\n")  # the SDF <material> sets the look
    model = ET.Element("model", name=name)
    ET.SubElement(model, "static").text = "true"
    link = ET.SubElement(model, "link", name="link")
    shapes = _collisions(link, scene, root)
    _visuals(link, scene, root, textures)
    sdf = ET.Element("sdf", version="1.11")
    sdf.append(model)
    ET.indent(sdf)
    (root / "model.sdf").write_text('<?xml version="1.0" ?>\n' + ET.tostring(sdf, encoding="unicode") + "\n")
    (root / "model.config").write_text(f'<?xml version="1.0" ?>\n<model>\n  <name>{name}</name>\n  <version>1.0</version>\n'
                                       f'  <sdf version="1.11">model.sdf</sdf>\n  <description>Procedural scene '
                                       f'({len(scene["boxes"])} parts, {shapes} collision meshes)</description>\n</model>\n')
    (out / "world.sdf").write_text(WORLD.format(name=name, model=name))
    (out / "scene.json").write_text(json.dumps(scene, indent=1) + "\n")
    return out


def _sdf_pose(element):
    """(position, xyzw quaternion) of an element's <pose> written by _pose."""
    values = [float(v) for v in element.find("pose").text.split()]
    return values[:3], values[3:]


def _read_obj(path):
    """(vertices, indices, uvs, normals) of an OBJ written by _write_obj (v/vt/vn share one index)."""
    rows = {"v": [], "vt": [], "vn": [], "f": []}
    for line in path.read_text().splitlines():
        tag, *values = line.split()
        if tag in rows:
            rows[tag].append([int(v.split("/")[0]) - 1 for v in values] if tag == "f" else [float(v) for v in values])
    return rows["v"], [k for face in rows["f"] for k in face], rows["vt"], rows["vn"]


def load_export(out, client=0):
    """Build the exported model in PyBullet from its files (what Gazebo loads); returns (collision ids, visual ids).

    OBJ files are parsed here and passed as vertex lists, as load_pybullet does: PyBullet's own OBJ loader builds
    concave meshes differently (1 mm larger bounds), which would hide whether the files themselves match."""
    import pybullet as p
    root = next(Path(out).glob("*/model.sdf")).parent
    link = ET.parse(root / "model.sdf").getroot().find("model/link")
    ids, shapes, images, visuals = [], {}, {}, []
    # Without a visual, PyBullet draws collision bodies itself (z-fighting the meshes): share one hidden visual.
    hidden = p.createVisualShape(p.GEOM_BOX, halfExtents=[1e-4] * 3, rgbaColor=[0, 0, 0, 0], physicsClientId=client)
    for c in link.iter("collision"):
        geometry, (center, q) = c.find("geometry"), _sdf_pose(c)
        mesh = geometry.find("mesh")
        key = mesh.find("uri").text if mesh is not None else geometry.find("box/size").text
        if key not in shapes and mesh is None:
            shapes[key] = p.createCollisionShape(p.GEOM_BOX, halfExtents=[float(v) / 2 for v in key.split()], physicsClientId=client)
        elif key not in shapes:
            vertices, indices = _read_obj(root / key)[:2]
            shapes[key] = p.createCollisionShape(p.GEOM_MESH, vertices=vertices, physicsClientId=client) if "/hull_" in key \
                else p.createCollisionShape(p.GEOM_MESH, vertices=vertices, indices=indices, flags=p.GEOM_FORCE_CONCAVE_TRIMESH,
                                            physicsClientId=client)
        body = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=shapes[key], baseVisualShapeIndex=hidden, basePosition=center,
                                 baseOrientation=q, useMaximalCoordinates=True, physicsClientId=client)
        p.changeDynamics(body, -1, lateralFriction=float(c.find("surface/friction/ode/mu").text), restitution=0,
                         physicsClientId=client)
        ids.append(body)
    for v in link.iter("visual"):
        color = [float(x) for x in v.find("material/diffuse").text.split()]
        vertices, indices, uvs, normals = _read_obj(root / v.find("geometry/mesh/uri").text)
        shape = p.createVisualShape(p.GEOM_MESH, vertices=vertices, indices=indices, uvs=uvs, normals=normals, rgbaColor=color,
                                    physicsClientId=client)
        body = p.createMultiBody(baseMass=0, baseVisualShapeIndex=shape, useMaximalCoordinates=True, physicsClientId=client)
        albedo = v.find("material/pbr/metal/albedo_map")
        if albedo is not None:
            if albedo.text not in images:
                images[albedo.text] = p.loadTexture(str(root / albedo.text), physicsClientId=client)
            p.changeVisualShape(body, -1, textureUniqueId=images[albedo.text], physicsClientId=client)
        visuals.append(body)
    return ids, visuals


def main():
    """Command line: generate a building or a metro station and export it for Gazebo."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metro", action="store_true", help="Metro station instead of a building")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--floors", type=int, help="Building storeys (default: config/building.toml)")
    parser.add_argument("--config", type=Path, help="settings override: a folder like config/ or one .toml file")
    parser.add_argument("--textures", type=Path)
    parser.add_argument("--name", help="Gazebo model and world name (default: ptg_<building|metro>_seed<seed>)")
    parser.add_argument("--out", type=Path, required=True, help="New or empty output folder")
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        parser.error(f"{args.out} is not empty: export into a new folder")
    import settings
    settings.use(args.config)
    if args.metro:
        from metro import MetroConfig, generate_metro
        scene = generate_metro(MetroConfig(seed=args.seed))
    else:
        from indoor import Config, generate
        scene = generate(Config(seed=args.seed, floors=args.floors))
    name = args.name or f"ptg_{'metro' if args.metro else 'building'}_seed{args.seed}"
    export_sdf(scene, args.out, name, args.textures)
    print(f"{args.out}/world.sdf: {len(scene['boxes'])} parts, spawn {scene['spawn']}; "
          f"run with GZ_SIM_RESOURCE_PATH={args.out.resolve()}")


if __name__ == "__main__":
    main()
