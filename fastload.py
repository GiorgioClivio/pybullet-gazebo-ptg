"""Fast PyBullet loading: per-part invisible collision bodies + a few merged visual meshes.

load_pybullet() creates one visual body per part (about 5,000 for a 2-storey building), and a
renderer pays a draw call per body every frame, plus one per shadow map. Here every part keeps
its own static collision body (same shapes, friction and ids as load_pybullet, so physics and
the box-aligned ids are unchanged), while visuals are merged into one mesh per
(storey, part kind, texture image, RGBA), split below PyBullet's per-mesh limits.

    from fastload import load_pybullet_merged
    ids = load_pybullet_merged(scene, client)   # ids[i] <-> scene["boxes"][i] (collision bodies)
    ids.visuals                                 # [{body, level, kind, color, boxes}] merged meshes

Trade-off: segmentation masks show merged groups, not individual parts. xray.XRay accepts
these ids and recolours the groups.
"""
import math

MAX_VERTICES = 30000   # PyBullet truncates silently above 131072 per mesh (Linux) and the
MAX_INDICES = 120000   # shared-memory stream also carries UVs and normals: stay well below.


class BodyIds(list):
    """Box-aligned collision body ids, plus .visuals: the merged visual bodies."""
    visuals = ()


def _rotate(q, v):
    """Rotate vector v by unit quaternion q = (x, y, z, w)."""
    x, y, z, w = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return [v[0] + w * tx + y * tz - z * ty, v[1] + w * ty + z * tx - x * tz, v[2] + w * tz + x * ty - y * tx]


def part_geometry(box):
    """Local visual mesh of one part, exactly as load_pybullet draws it (plain boxes get box UVs)."""
    from geometry import mesh
    from surfaces import box_mesh
    if box.get("shape"):
        return mesh(box)
    return box_mesh(box if "texture" in box else dict(box, texture=dict(style="paint", period=2.)))


def merge_groups(scene, textures=None, view_floor=None):
    """Group parts into merged meshes: [{key, color, texture, boxes, vertices, indices, uvs, normals}]."""
    from indoor import COLORS, texture_file
    groups, open_group = [], {}
    for i, box in enumerate(scene["boxes"]):
        color = list(box.get("color", COLORS[box["material"]]))
        if view_floor is not None and box["level"] > view_floor:
            color[3] = 0
        path = texture_file(box, textures)
        key = (box["level"], box["kind"], str(path) if path else None, tuple(round(c, 5) for c in color))
        g = part_geometry(box)
        group = open_group.get(key)
        if group is None or len(group["vertices"]) + len(g["vertices"]) > MAX_VERTICES or \
                len(group["indices"]) + len(g["indices"]) > MAX_INDICES:
            group = dict(key=key, color=color, texture=path, boxes=[], vertices=[], indices=[], uvs=[], normals=[])
            groups.append(group)
            open_group[key] = group
        q, c, base = box.get("orientation", (0, 0, 0, 1)), box["center"], len(group["vertices"])
        turned = tuple(q) != (0, 0, 0, 1)
        for v, n in zip(g["vertices"], g["normals"]):
            v, n = (_rotate(q, v), _rotate(q, n)) if turned else (v, n)
            group["vertices"].append([v[0] + c[0], v[1] + c[1], v[2] + c[2]])
            group["normals"].append(list(n))
        group["uvs"] += [list(uv) for uv in g["uvs"]]
        group["indices"] += [base + k for k in g["indices"]]
        group["boxes"].append(i)
    return groups


def load_pybullet_merged(scene, client=0, textures=None, view_floor=None):
    """Collision bodies as load_pybullet(visuals=False) + merged visual bodies; returns BodyIds."""
    import pybullet as p
    from indoor import load_pybullet
    ids = BodyIds(load_pybullet(scene, client, textures, view_floor, visuals=False))
    images, visuals = {}, []
    for g in merge_groups(scene, textures, view_floor):
        shape = p.createVisualShape(p.GEOM_MESH, vertices=g["vertices"], indices=g["indices"], uvs=g["uvs"],
                                    normals=g["normals"], rgbaColor=g["color"], physicsClientId=client)
        body = p.createMultiBody(baseMass=0, baseVisualShapeIndex=shape, useMaximalCoordinates=True,
                                 physicsClientId=client)
        if g["texture"] is not None:
            key = str(g["texture"].resolve())
            if key not in images:
                images[key] = p.loadTexture(key, physicsClientId=client)
            p.changeVisualShape(body, -1, textureUniqueId=images[key], physicsClientId=client)
        level, kind = g["key"][:2]
        visuals.append(dict(body=body, level=level, kind=kind, color=g["color"], boxes=g["boxes"]))
    ids.visuals = visuals
    return ids


def _self_test():
    q = (0, 0, math.sin(math.pi / 4), math.cos(math.pi / 4))  # 90 degrees about z
    assert all(abs(a - b) < 1e-12 for a, b in zip(_rotate(q, [1, 0, 0]), [0, 1, 0]))
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from indoor import Config, generate
    scene = generate(Config(seed=7, floors=2))
    groups = merge_groups(scene)
    covered = sorted(i for g in groups for i in g["boxes"])
    assert covered == list(range(len(scene["boxes"]))), "every part drawn exactly once"
    assert all(len(g["vertices"]) <= MAX_VERTICES and len(g["indices"]) <= MAX_INDICES for g in groups)
    assert all(max(g["indices"]) < len(g["vertices"]) == len(g["uvs"]) == len(g["normals"]) for g in groups)
    print(f"fastload self-test ok: {len(scene['boxes'])} parts -> {len(groups)} merged meshes")


if __name__ == "__main__":
    _self_test()
