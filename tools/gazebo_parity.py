"""Parity of a Gazebo export with the native PyBullet scene: same collisions, same look.

Loads <export>/scene.json with indoor.load_pybullet / fastload (native) and the exported files with
gazebo.load_export (what Gazebo reads), each in its own DIRECT client, then compares:
  aabb:   every export collision's AABB against its native parts' (gazebo.collision_groups: one part, or the merged
          objects of a storey and kind, whose union AABB is compared; Bullet pads a concave trimesh's bounds by its
          1 mm collision margin, so merged meshes are allowed MERGED_TOLERANCE), max abs difference in m;
  rays:   a vertical ray grid over the bounds (and horizontal rays at 0.3 and 1.2 m above each storey floor):
          the hit fraction must agree (two collisions sharing a surface may swap), within MERGED_TOLERANCE when a
          merged mesh is hit: Bullet casts rays at convex shapes (the native boxes and hulls) a few mm off and at
          triangles exactly, so a hull's triangles inside a merged mesh read up to 4 mm lower, and a ray within a
          few mm of a box's or hull's silhouette is hit on one side only (accepted when the ray moved sideways by
          MERGED_TOLERANCE hits the missing side above the deeper hit);
  pixels: TinyRenderer images from the spawn (mean abs RGB difference, 0-255), saved side by side with --figure.

    python3 tools/gazebo_parity.py exports/building_seed7 [--figure reports/parity.png] [--step 0.25]
Exit 1 if aabb > 1e-6 m or any ray disagrees.
"""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TOLERANCE, MERGED_TOLERANCE = 1e-6, 5e-3


def _clients(scene, export):
    """(native client, native ids), (export client, export ids), each a DIRECT PyBullet client."""
    import pybullet as p
    from fastload import load_pybullet_merged
    from gazebo import load_export
    a, b = p.connect(p.DIRECT), p.connect(p.DIRECT)
    return (a, list(load_pybullet_merged(scene, a))), (b, load_export(export, b)[0])


def _rays(scene, step):
    """(from, to) pairs: a vertical grid over the bounds, and x/y sweeps at two heights per storey floor."""
    x0, y0, x1, y1 = scene["bounds"]
    # Off any round grid: tunnel.py builds on 0.25 m cells, and a ray along a box face grazes it (Bullet's convex
    # boxes and the merged triangles disagree on grazing hits, not on the surfaces).
    x0, y0 = x0 + .113, y0 + .113
    zs = sorted({round(s.get("z", s.get("floor_z", 0.)), 3) for s in scene.get("levels", ())} or {0.}) \
        if "levels" in scene else [3. * k for k in range(scene["config"].get("floors", 1))]
    top, bottom = max(zs) + 20., min(zs) - 20.
    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
    rays = [((x0 + i * step, y0 + j * step, top), (x0 + i * step, y0 + j * step, bottom)) for i in range(nx) for j in range(ny)]
    for z in zs:
        for h in (.3, 1.2):
            rays += [((x0 - 1, y0 + j * step, z + h), (x1 + 1, y0 + j * step, z + h)) for j in range(ny)]
            rays += [((x0 + i * step, y0 - 1, z + h), (x0 + i * step, y1 + 1, z + h)) for i in range(nx)]
    return rays


def _cast(client, ids, rays):
    """[(part index or -1, hit fraction)] per ray, in batches PyBullet accepts."""
    import pybullet as p
    index, out = {body: i for i, body in enumerate(ids)}, []
    for k in range(0, len(rays), 8000):
        chunk = rays[k:k + 8000]
        hits = p.rayTestBatch([r[0] for r in chunk], [r[1] for r in chunk], numThreads=4, physicsClientId=client)
        out += [(index.get(h[0], -1), round(h[2], 9)) for h in hits]
    return out


def _grazes(client, bodies, ray, far):
    """True if the ray moved sideways by MERGED_TOLERANCE (axis-aligned rays) hits one of bodies before the hit
    fraction far (less MERGED_TOLERANCE): a silhouette is steep, so the depth beside the ray is not bounded."""
    import pybullet as p
    start, end = ray
    span = [e - s for s, e in zip(start, end)]
    tolerance = MERGED_TOLERANCE / sum(v * v for v in span) ** .5
    for axis in (k for k in range(3) if abs(span[k]) < 1e-9):
        for sign in (-1, 1):
            shift = [MERGED_TOLERANCE * sign if k == axis else 0. for k in range(3)]
            hit = p.rayTest([s + d for s, d in zip(start, shift)], [e + d for e, d in zip(end, shift)], physicsClientId=client)[0]
            if hit[0] in bodies and hit[2] < far - tolerance:
                return True
    return False


def _image(client, scene):
    """640x480 TinyRenderer RGB from the spawn, looking along -x (the metro hall) or across the building."""
    import numpy as np
    import pybullet as p
    sx, sy, sz = scene["spawn"]
    view = p.computeViewMatrix([sx + 1, sy + .5, sz + 1.1], [sx - 6, sy - 1, sz + .6], [0, 0, 1])
    proj = p.computeProjectionMatrixFOV(70, 640 / 480, .05, 200)
    rgba = p.getCameraImage(640, 480, view, proj, renderer=p.ER_TINY_RENDERER, physicsClientId=client)[2]
    return np.reshape(rgba, (480, 640, 4))[:, :, :3].astype(np.int16)


def main():
    """Compare the export folder with the native scene; print one line per check."""
    import pybullet as p
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", type=Path)
    parser.add_argument("--step", type=float, default=.25, help="Ray grid spacing (m)")
    parser.add_argument("--figure", type=Path, help="Save native | export | difference images here (new file)")
    args = parser.parse_args()
    scene = json.loads((args.export / "scene.json").read_text())
    from gazebo import collision_groups
    (a, native), (b, exported) = _clients(scene, args.export)
    groups = collision_groups(scene)
    group = {i: g for g, (_, parts) in enumerate(groups) for i in parts}
    worst = {False: 0., True: 0.}  # single parts, merged meshes
    for j, (_, parts) in zip(exported, groups):
        boxes = [p.getAABB(native[i], physicsClientId=a) for i in parts]
        union = [min(box[0][k] for box in boxes) for k in range(3)], [max(box[1][k] for box in boxes) for k in range(3)]
        worst[len(parts) > 1] = max(worst[len(parts) > 1], *(abs(u - v) for box_a, box_b in zip(union, p.getAABB(j, physicsClientId=b))
                                                             for u, v in zip(box_a, box_b)))
    print(f"aabb   parts {len(native)} in {len(groups)} collisions vs {len(exported)}  max diff {worst[False]:.2e} m, "
          f"merged {worst[True]:.2e} m")
    rays = _rays(scene, args.step)
    ha, hb = _cast(a, native, rays), _cast(b, exported, rays)
    merged = {g for g, (_, parts) in enumerate(groups) if len(parts) > 1}
    bad = sum(1 for ray, (pa, fa), (pb, fb) in zip(rays, ha, hb)
              if abs(fa - fb) > (MERGED_TOLERANCE if pb in merged and group.get(pa, -1) == pb else TOLERANCE)
              and not (group.get(pa, -1) in merged and fb > fa and _grazes(b, {exported[group[pa]]}, ray, fb))
              and not (pb in merged and fa > fb and _grazes(a, {native[i] for i in groups[pb][1]}, ray, fa)))
    print(f"rays   {len(rays)} cast, {sum(h[0] >= 0 for h in ha)} hits, {bad} disagree")
    ia, ib = _image(a, scene), _image(b, scene)
    print(f"pixels mean abs RGB diff {abs(ia - ib).mean():.3f} / 255, max {abs(ia - ib).max()}")
    if args.figure:
        import numpy as np
        from PIL import Image
        if args.figure.exists():
            sys.exit(f"{args.figure} exists: choose a new file")
        Image.fromarray(np.hstack([ia, ib, np.clip(abs(ia - ib) * 4, 0, 255)]).astype(np.uint8)).save(args.figure)
    sys.exit(1 if len(groups) != len(exported) or worst[False] > TOLERANCE or worst[True] > MERGED_TOLERANCE or bad else 0)


if __name__ == "__main__":
    main()
