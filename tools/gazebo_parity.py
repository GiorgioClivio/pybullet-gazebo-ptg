"""Parity of a Gazebo export with the native PyBullet scene: same collisions, same look.

Loads <export>/scene.json with indoor.load_pybullet / fastload (native) and the exported files with
gazebo.load_export (what Gazebo reads), each in its own DIRECT client, then compares:
  aabb:   every part's collision AABB (part i <-> collision c<i>), max abs difference in m;
  rays:   a vertical ray grid over the bounds (and horizontal rays at 0.3 and 1.2 m above each storey floor):
          hit fraction and hit part must agree;
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
TOLERANCE = 1e-6


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
    (a, native), (b, exported) = _clients(scene, args.export)
    worst = max(abs(u - v) for i, j in zip(native, exported) for box_a, box_b in
                zip(p.getAABB(i, physicsClientId=a), p.getAABB(j, physicsClientId=b)) for u, v in zip(box_a, box_b))
    print(f"aabb   parts {len(native)} vs {len(exported)}  max diff {worst:.2e} m")
    rays = _rays(scene, args.step)
    ha, hb = _cast(a, native, rays), _cast(b, exported, rays)
    bad = sum(1 for (pa, fa), (pb, fb) in zip(ha, hb) if pa != pb or abs(fa - fb) > TOLERANCE)
    print(f"rays   {len(rays)} cast, {sum(h[0] >= 0 for h in ha)} hits, {bad} disagree")
    ia, ib = _image(a, scene), _image(b, scene)
    print(f"pixels mean abs RGB diff {abs(ia - ib).mean():.3f} / 255, max {abs(ia - ib).max()}")
    if args.figure:
        import numpy as np
        from PIL import Image
        if args.figure.exists():
            sys.exit(f"{args.figure} exists: choose a new file")
        Image.fromarray(np.hstack([ia, ib, np.clip(abs(ia - ib) * 4, 0, 255)]).astype(np.uint8)).save(args.figure)
    sys.exit(1 if len(native) != len(exported) or worst > TOLERANCE or bad else 0)


if __name__ == "__main__":
    main()
