"""Rendering and figure helpers shared by the tools: scene cameras, PyBullet TinyRenderer frames, PNG saving.

Frames come from the real loader (indoor.load_pybullet in a fresh DIRECT client), so figures show exactly what the
library builds. Figures are 1920 x 1080 px (6.4 x 3.6 in at 300 dpi) and every PNG records the command that
regenerates it (footer text and PNG "Source" metadata).
"""
from pathlib import Path
import copy
import math
import resource
import sys
import time

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import indoor  # noqa: E402
import surfaces  # noqa: E402
from geometry import geometry_stats  # noqa: E402

SIZE = (1400, 1050)
FIGSIZE, DPI = (6.4, 3.6), 300
INK, QUIET = "#22303a", "#6b7780"


def _lo_hi(b):
    return [b["center"][a] - b["size"][a] / 2 for a in range(3)], [b["center"][a] + b["size"][a] / 2 for a in range(3)]


def cutaway(scene, room_id, near=("S", "W")):
    """Copy of `scene` with one room: its floor, walls/glass on the far edges and its objects.

    Near walls are excluded from loading (TinyRenderer cannot blend transparency), and so are
    wall-mounted objects on them. Returns (room scene, far edges as [(axis, value, inward sign)]).
    """
    room = scene["spaces"][room_id]
    x0, y0, x1, y1 = room["rect"]
    edges = dict(S=(1, y0, 1), N=(1, y1, -1), W=(0, x0, 1), E=(0, x1, -1))
    far = [edges[k] for k in edges if k not in near]
    near = [edges[k] for k in near]
    kinds = {o["id"]: o for o in scene["objects"]}
    keep = []
    for b in scene["boxes"]:
        if b["level"] != room["level"]:
            continue
        lo, hi = _lo_hi(b)
        if b["kind"] == "floor":
            ok = x0 - .01 <= b["center"][0] <= x1 + .01 and y0 - .01 <= b["center"][1] <= y1 + .01
        elif b["kind"] in ("wall", "glass"):
            thin = 0 if b["size"][0] < b["size"][1] else 1
            along = 1 - thin
            span = min(hi[along], room["rect"][along + 2]) - max(lo[along], room["rect"][along])
            ok = span > .05 and any(axis == thin and abs(b["center"][thin] - value) < .01 for axis, value, _ in far)
        elif "object_id" in b and kinds[b["object_id"]]["room"] == room_id:
            on_near = kinds[b["object_id"]].get("placement") == "wall" and any(
                abs(b["center"][axis] - value) < .2 for axis, value, _ in near)
            ok = not on_near
        else:
            ok = False
        if ok:
            keep.append(copy.deepcopy(b))
    # TinyRenderer's shadow map only covers a region around the world origin (measured: no cast
    # shadows at x = 20 m). Shift by a multiple of 6 m, a common multiple of the 0.6/2/3 m texture
    # periods, so metric UVs and therefore the look are unchanged.
    shift = [-6 * round((x0 + x1) / 12), -6 * round((y0 + y1) / 12)]
    out = {k: copy.deepcopy(v) for k, v in scene.items() if k != "boxes"}
    for item in keep + out["portals"]:
        item["center"][:2] = [item["center"][0] + shift[0], item["center"][1] + shift[1]]
    far = [(axis, value + shift[axis], inward) for axis, value, inward in far]
    rect = [x0 + shift[0], y0 + shift[1], x1 + shift[0], y1 + shift[1]]
    out["boxes"], out["lab"] = keep, dict(room=room_id, level=room["level"], far=far, rect=rect, shift=shift)
    return out, far


def camera(scene, azimuth=225., elevation=35., fov=24., size=SIZE, margin=1.06, lift=.32):
    """Elevated 3/4 view of the room bounds; distance fits the bounding sphere into the vertical FOV."""
    lows, highs = zip(*(_lo_hi(b) for b in scene["boxes"]))
    lo, hi = np.min(lows, 0), np.max(highs, 0)
    target = (lo + hi) / 2
    target[2] = lo[2] + lift * (hi[2] - lo[2])
    radius = np.linalg.norm(hi - lo) / 2
    distance = margin * radius / math.sin(math.radians(fov / 2))
    a, e = math.radians(azimuth), math.radians(elevation)
    eye = target + distance * np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    return dict(eye=eye.tolist(), target=target.tolist(), fov=fov, size=list(size))


def _connect():
    import pybullet as p
    cid = p.connect(p.DIRECT)
    if cid < 0:
        raise RuntimeError("PyBullet DIRECT connection failed")
    return p, cid


def render(scene, cams, light, backdrop, shadow=1, seg=False):
    """Load once into a fresh DIRECT client, render each camera with TinyRenderer, composite the backdrop.

    A camera is dict(eye, target, fov, size) or, for the library orbit framing, dict(ypr=True, target,
    distance, yaw, pitch, fov, size); optional near/far. Returns (images, stats with per-frame times).
    """
    t0 = time.perf_counter()
    textures = {surfaces.texture_path(b["texture"]) for b in scene["boxes"] if "texture" in b}
    t1 = time.perf_counter()
    p, cid = _connect()
    images, frames = [], []
    try:
        ids = indoor.load_pybullet(scene, cid)
        t2 = time.perf_counter()
        for cam in cams:
            w, h = cam["size"]
            if cam.get("ypr"):
                view = p.computeViewMatrixFromYawPitchRoll(cam["target"], cam["distance"], cam["yaw"], cam["pitch"], 0, 2,
                                                           physicsClientId=cid)
            else:
                view = p.computeViewMatrix(cam["eye"], cam["target"], [0, 0, 1], physicsClientId=cid)
            proj = p.computeProjectionMatrixFOV(cam["fov"], w / h, cam.get("near", .5), cam.get("far", 60), physicsClientId=cid)
            t3 = time.perf_counter()
            _, _, rgba, _, seg_buffer = p.getCameraImage(w, h, view, proj, shadow=shadow, renderer=p.ER_TINY_RENDERER,
                                                         physicsClientId=cid, **light)
            render_s = time.perf_counter() - t3
            rgb = np.reshape(np.array(rgba, np.uint8), (h, w, 4))[..., :3].astype(np.float32)
            mask = np.reshape(np.array(seg_buffer), (h, w))
            top, bottom = np.array(backdrop[0]) * 255, np.array(backdrop[1]) * 255
            yy, xx = np.mgrid[0:h, 0:w]
            r = np.clip(np.hypot((xx - w / 2) / w, (yy - h * .45) / h) * 1.6, 0, 1)[..., None]
            rgb = np.where((mask < 0)[..., None], top * (1 - r) + bottom * r, rgb)
            ys, xs = np.nonzero(mask >= 0)
            frames.append(dict(render_s=round(render_s, 2), bbox=[int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
                               **({"seg": mask} if seg else {})))
            images.append(Image.fromarray(np.uint8(np.clip(rgb, 0, 255))))
    finally:
        p.disconnect(cid)
    stats = dict(parts=len(scene["boxes"]), triangles=geometry_stats(scene)["visual_triangles"],
                 textures=len(textures), texture_s=round(t1 - t0, 2), load_s=round(t2 - t1, 2), frames=frames,
                 peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024), **({"ids": ids} if seg else {}))
    return images, stats


def save(fig, path, command, replace=False):
    """Stamp the regeneration command (footer + PNG metadata) and write a NEW file unless replace=True."""
    path = Path(path)
    if path.exists() and not replace:
        raise FileExistsError(f"{path} exists; use a new --out-dir or --replace")
    fig.text(.02, .008, f"Regenerate: {command}", fontsize=3.8, color=QUIET, ha="left", va="bottom")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, metadata={"Source": command, "Software": "PTG"})
    import matplotlib.pyplot as plt
    plt.close(fig)
    return path
