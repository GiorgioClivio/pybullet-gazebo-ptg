"""Metro presentation figure: isometric cut-away "diorama" renders of one generated station.

Purpose: presentation figures of metro.py: elevated 3/4 views, near walls not loaded so interiors are visible, neutral backdrop, a measured stats table and
a regeneration footer. Panels: full-station section, concourse with its side rooms, stairs, spiral ramp,
platform with the tunnel mouth. Every panel is a filtered COPY of `metro.generate_metro()`; parts are
dropped or clipped to a box (metric UVs keep their world coordinates, so finishes do not shift).
Rendering: tools/render.py `camera()` and `render()` (PyBullet DIRECT + TinyRenderer).

Inputs: --seed, --layout, --no-ramp. Output (--out-dir, default images/): metro_seed<S>_<layout>_diorama.png
(1920 x 1080 at 300 dpi). Existing outputs are refused unless --replace is given.

Variety survey (no PyBullet): --survey 0-9 prints a Markdown table of the seeded envelope (layout, platform length,
column spacing, concourse height, depth, track bed, ramp, side rooms), parts, triangles, generation time and the
furnishing counts per area / room purpose; --json saves the rows. Seed views (PyBullet): --views renders the
hall view from the spawn point looking west (1.6 m eye height), a typical follow-camera view of
the robot at the spawn (FOLLOW: distance, yaw, pitch) and a
steep view from above into one side room to <out-dir>/metro_seed<S>[_<tag>]_{hall,spawn,room}.png. --metro-src loads another metro.py (e.g. a backup) for "before" data.

    python3 tools/metro_figures.py --seed 7 --layout island --replace
    python3 tools/metro_figures.py --survey 0-9 --json reports/metro_survey.json
    python3 tools/metro_figures.py --seed 0 --layout auto --views
    python3 tools/metro_figures.py --seed 0 --layout auto --breakdown     # triangles per object kind / element
    python3 tools/metro_figures.py --compare 0,1                         # before/after grids of the --views images
    python3 tools/metro_figures.py --compare 0,1 --tags before,after     # any two --views tags
    python3 tools/metro_figures.py --self-test
"""
from pathlib import Path
import argparse
import copy
import math
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import numpy as np  # noqa: E402

LIGHT = dict(lightDirection=[-2., -3., 8.], lightAmbientCoeff=.62, lightDiffuseCoeff=.45, lightSpecularCoeff=.04)
BACKDROP = ((.94, .94, .93), (.78, .80, .79))
TITLES = dict(overview="Full station, south half cut away", concourse="Street-level concourse and side rooms",
              stairs="Stairs: concourse to platform", ramp="Spiral ramp shaft (optional)",
              platform="Platform, tracks and tunnel mouth")


def clip(b, lo, hi):
    """Copy of an axis-aligned part clipped to the box [lo, hi]; None if outside. Rotated parts: kept whole if centred inside."""
    if "orientation" in b or (b.get("shape") and b.get("element") not in ("column",)):
        return copy.deepcopy(b) if all(lo[a] <= b["center"][a] <= hi[a] for a in range(3)) else None
    a0 = [max(lo[a], b["center"][a] - b["size"][a] / 2) for a in range(3)]
    a1 = [min(hi[a], b["center"][a] + b["size"][a] / 2) for a in range(3)]
    if any(a1[a] - a0[a] < 1e-4 for a in range(3)):
        return None
    out = copy.deepcopy(b)
    out["size"] = [a1[a] - a0[a] for a in range(3)]
    out["center"] = [(a0[a] + a1[a]) / 2 for a in range(3)]
    if "collision_size" in out:
        out["collision_size"] = [out["size"][0] + .002, out["size"][1] + .002, out["size"][2]]
    return out


def cut(scene, lo, hi, drop=lambda b: False):
    """Scene copy whose boxes are clipped to [lo, hi] and not matched by `drop`."""
    out = {k: v for k, v in scene.items() if k != "boxes"}
    out["boxes"] = [c for c in (clip(b, lo, hi) for b in scene["boxes"] if not drop(b)) if c is not None]
    return out


def panels(scene):
    """name -> (scene subset, camera kwargs for render.camera)."""
    c = scene["config"]
    L, Lt, zp = c["platform_length"], c["tunnel_length"], scene["levels"][0]["floor_z"]
    halls = [s for s in scene["spaces"] if s["kind"] == "concourse"]
    X0, X1 = min(s["rect"][0] for s in halls), max(s["rect"][2] for s in halls)
    Hh = halls[0]["rect"][3]
    gate = halls[0]["rect"][0]
    rooms = [s for s in scene["spaces"] if s["kind"] == "room"]
    outer = max(s["rect"][3] for s in rooms)
    big = 1e3
    south = lambda b: b["level"] == 1 and b["center"][1] < 0
    inner = -min(b["center"][1] for b in scene["boxes"] if b.get("element") == "station_wall") - .3
    # Near walls are not loaded, and neither is what hangs on them (boards would float, seen from the back).
    near_box = lambda b: (b.get("element") in ("station_wall", "shaft_wall", "accent_band") and b["center"][1] < -1 or
                          b["kind"] == "landmark" and b["level"] == 0 and b["center"][1] < -inner + .3)
    out = dict(overview=(cut(scene, [-big, -big, -big], [big, big, 3.2],
                             lambda b: south(b) or near_box(b) or (b["level"] == 1 and b["kind"] == "ceiling" and b["center"][2] > 1)),
                         dict(azimuth=-62, elevation=38, fov=22, margin=.98, lift=.4)))
    out["concourse"] = (cut(scene, [gate - 30, -big, -big], [X1 + .4, big, 3.2],
                            lambda b: b["level"] != 1 and not b.get("element", "").startswith("stair") or b.get("element") == "facade" and b["center"][0] > X1 - 1 or
                            (b.get("element") == "wall" and b["center"][1] < -outer + .5)),
                        dict(azimuth=-55, elevation=42, fov=24, margin=1.0, lift=.2))
    stair = min(scene["stairs"], key=lambda s: s["top"][0])
    out["stairs"] = (cut(scene, [stair["bottom"][0] - 4, -big, -big], [stair["top"][0] + 3, big, 1.2],
                         lambda b: south(b) or near_box(b)),
                     dict(azimuth=-70, elevation=24, fov=26, margin=.95, lift=.45))
    if scene["ramps"]:
        r = scene["ramps"][0]
        x0, x1 = r["centre"][0] - r["shaft_half"] - .7, r["centre"][0] + r["shaft_half"] + 1.2
        out["ramp"] = (cut(scene, [x0, -big, -big], [x1, big, 1.2], lambda b: south(b) or near_box(b)),
                       dict(azimuth=-60, elevation=36, fov=26, margin=.95, lift=.4))
    south_track = min((b["center"][1] for b in scene["boxes"] if b.get("element") == "conductor_rail"), default=0) + 1.2
    out["platform"] = (cut(scene, [L - 22, -big, -big], [L + Lt + .6, big, big],
                           lambda b: b["level"] != 0 or near_box(b) or (b.get("element") == "tunnel_lining" and b["center"][1] < south_track - .5
                                                                         and b["center"][2] > zp - 1.5) or
                           (b.get("element") in ("tunnel_wall",) and b["center"][1] < 0) or
                           (b["kind"] == "ceiling" and b["center"][0] > L)),
                       dict(azimuth=-125, elevation=30, fov=26, margin=.9, lift=.35))
    return out


def compose(images, rows, summary, path, command, replace):
    """Overview on top-left, stats table top-right, the detail panels along the bottom row."""
    import matplotlib.pyplot as plt
    from render import FIGSIZE, DPI, INK, QUIET, save
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
    fig.text(.02, .965, f"PTG metro station: seed {summary['seed']}, {summary['layout']} platform, \"{summary['station']}\"",
             fontsize=8, color=INK, fontweight="bold", va="top")
    fig.text(.02, .915, summary["subtitle"], fontsize=4.6, color=QUIET, va="top")

    def show(ax, image, frame, title):
        x0, y0, x1, y1 = frame["bbox"]
        pad = 10
        arr = np.asarray(image)[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
        ax.imshow(arr)
        ax.set_title(title, fontsize=4.8, color=INK, pad=1.5)
        ax.axis("off")
    names = [r["panel"] for r in rows]
    show(fig.add_axes([.02, .43, .60, .44]), images[0], rows[0], TITLES[names[0]])
    rest = list(zip(images[1:], rows[1:]))
    width = .96 / max(1, len(rest))
    for i, (image, row) in enumerate(rest):
        show(fig.add_axes([.02 + i * width, .05, width - .01, .29]), image, row, TITLES[row["panel"]])
    table = fig.add_axes([.64, .43, .34, .44])
    table.axis("off")
    cols = [("panel", "View"), ("triangles", "Triangles"), ("parts", "Parts"), ("textures", "Textures"), ("render_s", "Render s")]
    short = dict(overview="Full station", concourse="Concourse", stairs="Stairs", ramp="Spiral ramp", platform="Platform + tunnel")
    cells = [[short[r[k]] if k == "panel" else f"{r[k]:,}" for k, _ in cols] for r in rows]
    t = table.table(cellText=cells, colLabels=[c for _, c in cols], loc="upper center", cellLoc="right", colLoc="right",
                    colWidths=[.42, .17, .13, .14, .14])
    t.auto_set_font_size(False)
    t.set_fontsize(4.0)
    t.scale(1, 1.1)
    for (r, c), cell in t.get_celld().items():
        cell.set_edgecolor("#c9ced2")
        cell.set_linewidth(.3)
        if c == 0:
            cell.set_text_props(ha="left")
            cell._loc = "left"
    table.text(0, .17, summary["notes"], fontsize=3.6, color=QUIET, va="top", transform=table.transAxes, linespacing=1.35)
    return save(fig, path, command, replace=replace)


def run(seed, layout, ramp, out_dir, replace):
    """Render the cut-away diorama panels of one station and compose them into one figure."""
    import metro
    import render
    from geometry import geometry_stats
    out_dir = Path(out_dir)
    t0 = time.perf_counter()
    scene = metro.generate_metro(metro.MetroConfig(seed=seed, layout=layout, spiral_ramp=ramp))
    gen_s = time.perf_counter() - t0
    subsets = panels(scene)
    cams, scenes = [], []
    for name, (subset, view) in subsets.items():
        cam = render.camera(subset, size=(1400, 1050), **view)
        cam.update(near=.5, far=400)
        cams.append((name, cam))
        scenes.append(subset)
    images, rows = [], []
    for (name, cam), subset in zip(cams, scenes):
        imgs, stats = render.render(subset, [cam], LIGHT, BACKDROP, shadow=0)
        frame = stats["frames"][0]
        images.append(imgs[0])
        rows.append(dict(panel=name, triangles=geometry_stats(subset)["visual_triangles"], parts=stats["parts"],
                         textures=stats["textures"], render_s=frame["render_s"], bbox=frame["bbox"]))
        print(name, rows[-1])
    total = scene["geometry_stats"]["visual_triangles"]
    command = f"python3 tools/metro_figures.py --seed {seed} --layout {scene['layout']}{'' if ramp else ' --no-ramp'} --replace"
    c = metro.MetroConfig(seed=seed, layout=layout, spiral_ramp=ramp)
    notes = (f"Whole scene: {len(scene['boxes']):,} parts, {len(scene['objects'])} objects, {total:,} triangles,\n"
             f"generated in {gen_s:.2f} s (metro.generate_metro, no PyBullet).\n"
             f"Depth {c.depth} m: {c.risers} risers of {c.rise * 1000:.0f} mm, tread {c.tread * 1000:.0f} mm, flights {c.flights}.\n"
             + (f"Spiral ramp: radius {scene['ramps'][0]['radius']:.2f} m, {scene['ramps'][0]['turns']:g} turns, "
                f"{scene['ramps'][0]['length']:.0f} m long, headroom {scene['ramps'][0]['headroom']:.2f} m.\n" if scene["ramps"] else "")
             + "Triangles/parts: geometry_stats of each cut-away subset (boxes count 12).\n"
               "Render s: one TinyRenderer frame, 1400 x 1050, shadow map off.\n"
               "Near walls and the south half of the concourse are not loaded.")
    summary = dict(seed=seed, layout=scene["layout"], station=scene["station_name"],
                   subtitle="PyBullet TinyRenderer, elevated 3/4 cut-away views of one generated station; "
                            "backdrop is presentation only. Robot view is unchanged (all parts load in metro.py).",
                   notes=notes)
    print("wrote", compose(images, rows, summary, out_dir / f"metro_seed{seed}_{scene['layout']}_diorama.png", command, replace))


def load_metro(src=None):
    """metro module from PTG, or from another metro.py file (its imports still resolve against PTG)."""
    if src is None:
        import metro
        return metro
    import importlib.util
    spec = importlib.util.spec_from_file_location("metro_src", src)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seeds_arg(text):
    """'0-9' or '0,3,5' -> list of ints."""
    out = []
    for item in text.split(","):
        a, _, b = item.partition("-")
        out.extend(range(int(a), int(b) + 1) if b else [int(a)])
    return out


def area(scene, obj):
    """Furnishing bucket of an object: hall, platform, track, or the side-room purpose."""
    s = scene["spaces"][obj["room"]]
    return s.get("purpose") or {"concourse": "hall", "platform": "platform"}.get(s["kind"], s["kind"])


def spawn_view_objects(scene, near=2., far=15.):
    """Objects (centre) 2-15 m from the eye inside the horizontal field of the demo's initial follow camera."""
    a = math.radians(FOLLOW["yaw"])
    look = (-math.sin(a), math.cos(a))
    half = math.atan(math.tan(math.radians(FOLLOW["fov"] / 2)) * 4 / 3)   # 1024 x 768 window.
    target = [scene["spawn"][0], scene["spawn"][1], scene["spawn"][2] + FOLLOW["z_bias"]]
    sx, sy, _ = follow_eye(target, FOLLOW["dist"], FOLLOW["yaw"], FOLLOW["pitch"])
    out = []
    for o in scene["objects"]:
        if o["level"] != 1:
            continue
        dx, dy = o["center"][0] - sx, o["center"][1] - sy
        dist = math.hypot(dx, dy)
        if near <= dist <= far and (dx * look[0] + dy * look[1]) / dist >= math.cos(half):
            out.append(o["kind"])
    return out


def survey(seeds, src=None, layout="auto"):
    """One row per seed: envelope, size, timing, objects per area (kind -> count)."""
    from collections import Counter, defaultdict
    from geometry import geometry_stats
    metro = load_metro(src)
    rows = []
    for seed in seeds:
        scene = metro.generate_metro(metro.MetroConfig(seed=seed, layout=layout))
        c = scene["config"]
        furnishing = defaultdict(Counter)
        for obj in scene["objects"]:
            furnishing[area(scene, obj)][obj["kind"]] += 1
        rooms = [s for s in scene["spaces"] if s["kind"] == "room"]
        rows.append(dict(seed=seed, layout=scene["layout"], station=scene["station_name"], platform_length=c["platform_length"],
                         column_spacing=c["column_spacing"], concourse_height=c["concourse_height"], depth=c["depth"],
                         track_bed=c["track_bed"], ramp=bool(scene["ramps"]), side_rooms=len(rooms),
                         room_depth=c["room_depth"], palette=c.get("palette", "-"), bounds=[round(v, 1) for v in scene["bounds"]],
                         parts=len(scene["boxes"]), objects=len(scene["objects"]),
                         triangles=scene["geometry_stats"]["visual_triangles"], generation_s=scene["metro_stats"]["generation_s"],
                         triangles_by_level={lv: geometry_stats(dict(boxes=[b for b in scene["boxes"] if b["level"] == lv]))["visual_triangles"]
                                             for lv in (0, 1)},
                         furnishing={k: dict(sorted(v.items())) for k, v in sorted(furnishing.items())},
                         rooms_by_purpose=dict(Counter(s["purpose"] for s in rooms)),
                         spawn_view=dict(Counter(spawn_view_objects(scene)))))
    return rows


def survey_markdown(rows):
    """Envelope table, then objects per area summed over the seeds (and per room of that purpose)."""
    from collections import Counter
    cols = ("seed", "layout", "platform_length", "column_spacing", "concourse_height", "depth", "track_bed", "ramp",
            "side_rooms", "palette", "parts", "triangles", "tri_platform", "tri_concourse", "spawn_view", "generation_s")
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        r = dict(r, tri_platform=r["triangles_by_level"][0], tri_concourse=r["triangles_by_level"][1],
                 spawn_view=sum(r.get("spawn_view", {}).values()))
        out.append("| " + " | ".join(f"{r[k]:,}" if isinstance(r[k], int) and not isinstance(r[k], bool) else str(r[k])
                                     for k in cols) + " |")
    totals, rooms = {}, Counter()
    for r in rows:
        for name, kinds in r["furnishing"].items():
            totals.setdefault(name, Counter()).update(kinds)
        rooms.update(r["rooms_by_purpose"])
    out += ["", f"Objects per area, summed over {len(rows)} seeds (per room = total / rooms of that purpose):", "",
            "| area | rooms | objects | per room | kinds |", "|---|---|---|---|---|"]
    for name, kinds in sorted(totals.items()):
        n = sum(kinds.values())
        per = f"{n / rooms[name]:.1f}" if rooms.get(name) else "-"
        out.append(f"| {name} | {rooms.get(name, '-')} | {n} | {per} | " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()) + " |")
    return "\n".join(out)


def breakdown(seed, layout="auto", src=None, top=25):
    """Visual triangles per object kind (label) or architecture element of one seed, largest first."""
    from collections import Counter
    from geometry import geometry_stats
    metro = load_metro(src)
    scene = metro.generate_metro(metro.MetroConfig(seed=seed, layout=layout))
    tris, count = Counter(), Counter()
    for b in scene["boxes"]:
        key = b.get("label") or b.get("element") or b["kind"]
        tris[key] += geometry_stats(dict(boxes=[b]))["visual_triangles"]
        count[key] += 1
    total = sum(tris.values())
    lines = [f"seed {seed} ({scene['layout']}, L={scene['config']['platform_length']}): {total:,} triangles", "| part group | parts | triangles | share |", "|---|---|---|---|"]
    lines += [f"| {k} | {count[k]} | {v:,} | {100 * v / total:.1f} % |" for k, v in tris.most_common(top)]
    return "\n".join(lines)


# Follow camera 2.4 m behind the robot, pitch -25 deg, yaw = robot heading (0) - 45 deg, look-at point 0.1 m above
# the base, 76 deg vertical FOV.
FOLLOW = dict(dist=2.4, yaw=-45., pitch=-25., z_bias=.1, fov=76.)


def follow_eye(target, dist, yaw, pitch):
    """Eye of a PyBullet debug camera (resetDebugVisualizerCamera convention: yaw 0 looks along +y)."""
    a, b = math.radians(yaw), math.radians(pitch)
    return [target[0] + dist * math.cos(b) * math.sin(a), target[1] - dist * math.cos(b) * math.cos(a),
            target[2] - dist * math.sin(b)]


ROOM_PREFERENCE = ("office", "control_room", "staff_room", "ticket_office", "storage", "toilet")


def seed_views(seed, layout, src, tag, out_dir, replace, command):
    """Hall view from the spawn point and a steep view from above into one side room (no ceiling unless roof=True)."""
    import pybullet as p
    from indoor import load_pybullet
    from surfaces import prepare_textures
    metro = load_metro(src)
    scene = metro.generate_metro(metro.MetroConfig(seed=seed, layout=layout))
    rooms = [s for s in scene["spaces"] if s["kind"] == "room"]
    room = min(rooms, key=lambda s: (ROOM_PREFERENCE.index(s["purpose"]) if s["purpose"] in ROOM_PREFERENCE else 99, s["id"]))
    x0, y0, x1, y1 = room["rect"]
    outer = y1 if y1 > 0 else y0
    side = 1 if y1 > 0 else -1
    inner = y0 if side > 0 else y1  # Hall wall (concourse_height tall): look over it toward the back wall.
    cam_room = dict(eye=[(x0 + x1) / 2, inner - side * 1.5, 11.], target=[(x0 + x1) / 2, outer - side * 1.2, 0.], fov=55)
    sx, sy, _ = scene["spawn"]
    target = [sx, sy, scene["spawn"][2] + FOLLOW["z_bias"]]
    cams = dict(hall=dict(eye=[sx, sy, 1.6], target=[sx - 30., sy, 1.2], fov=70),  # Hall: from the spawn, west.
                spawn=dict(eye=follow_eye(target, FOLLOW["dist"], FOLLOW["yaw"], FOLLOW["pitch"]), target=target, fov=FOLLOW["fov"]),
                room=cam_room)
    paths = {k: Path(out_dir) / f"metro_seed{seed}{'_' + tag if tag else ''}_{k}.png" for k in cams}
    for path in paths.values():
        if path.exists() and not replace:
            raise FileExistsError(f"{path} exists; use --replace")
    prepare_textures(scene)
    cid = p.connect(p.DIRECT)
    try:
        bodies = load_pybullet(scene, cid)
        for k, cam in cams.items():
            size = (1024, 768) if k == "spawn" else (1280, 800)   # spawn: the demo GUI window size.
            metro.render(cid, bodies, scene, paths[k], cam["eye"], cam["target"], cam["fov"], None, size, command)
            print("wrote", paths[k], f"({room['purpose']} room {room['id']})" if k == "room" else "")
    finally:
        p.disconnect(cid)
    return paths


def compare(seeds, out_dir, replace, command, tags=("before", "after")):
    """Grid of existing --views images: one row per seed, one column per tag, for the hall and the room views."""
    from PIL import Image, ImageDraw
    from PIL.PngImagePlugin import PngInfo
    out = []
    for view in ("hall", "spawn", "room"):
        tiles = [[Image.open(Path(out_dir) / f"metro_seed{s}_{t}_{view}.png").convert("RGB") for t in tags] for s in seeds]
        w, h = tiles[0][0].size
        sheet = Image.new("RGB", (w * len(tags), h * len(seeds)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(tiles):
            for j, tile in enumerate(row):
                sheet.paste(tile, (j * w, i * h))
                draw.rectangle((j * w, i * h, j * w + 260, i * h + 34), fill="white")
                draw.text((j * w + 8, i * h + 8), f"seed {seeds[i]}  {tags[j]}", fill="black")
        suffix = "" if tuple(tags) == ("before", "after") else "_" + "-".join(tags)
        path = Path(out_dir) / f"metro_compare_{view}{suffix}.png"
        if path.exists() and not replace:
            raise FileExistsError(f"{path} exists; use --replace")
        info = PngInfo()
        info.add_text("Source", command)
        sheet.resize((sheet.width // 2, sheet.height // 2)).save(path, pnginfo=info)
        print("wrote", path)
        out.append(path)
    return out


def _self_test():
    b = dict(size=[10, 2, 2], center=[0, 0, 1], kind="wall", level=0)
    c = clip(b, [-1, -5, -5], [3, 5, 1.5])
    assert c["size"] == [4, 2, 1.5] and c["center"] == [1, 0, .75], c
    assert clip(b, [6, -5, -5], [9, 5, 5]) is None
    r = dict(b, orientation=[0, 0, 0, 1])
    assert clip(r, [-1, -1, -1], [1, 1, 2]) is not None and clip(r, [2, -1, -1], [3, 1, 2]) is None
    assert seeds_arg("0-2,5") == [0, 1, 2, 5]
    eye = follow_eye([0, 0, 0], 2.4, -45, -25)  # Matches pybullet.computeViewMatrixFromYawPitchRoll.
    assert all(abs(a - b) < 1e-3 for a, b in zip(eye, (-1.538, -1.538, 1.014))), eye
    print("metro_figures self-test ok")


def main(argv=None):
    """Command line: diorama, survey, breakdown, views or compare mode."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--layout", choices=("auto", "island", "side"), default="island")
    parser.add_argument("--no-ramp", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "images")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--survey", type=seeds_arg, help="Seeds (e.g. 0-9): envelope/furnishing table, no PyBullet")
    parser.add_argument("--breakdown", action="store_true", help="Triangles per object kind / element of --seed")
    parser.add_argument("--json", type=Path, help="With --survey: save the rows (refused if it exists)")
    parser.add_argument("--views", action="store_true", help="Hall and side-room views of --seed (--layout auto: seeded)")
    parser.add_argument("--tag", default="", help="With --views: optional file tag, e.g. before/after")
    parser.add_argument("--compare", type=seeds_arg, help="Seeds (e.g. 0,1): before/after grids of existing --views images")
    parser.add_argument("--tags", default="before,after", help="With --compare: the two --views tags to put side by side")
    parser.add_argument("--metro-src", type=Path, help="Use this metro.py instead of PTG/metro.py (e.g. a backup)")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    command = "python3 tools/metro_figures.py " + " ".join(argv if argv is not None else sys.argv[1:])
    if args.compare:
        return compare(args.compare, args.out_dir, args.replace, command, tuple(args.tags.split(",")))
    if args.breakdown:
        return print(breakdown(args.seed, args.layout, args.metro_src))
    if args.survey is not None:
        import json
        rows = survey(args.survey, args.metro_src, args.layout)
        print(survey_markdown(rows))
        if args.json:
            if args.json.exists():
                raise FileExistsError(f"{args.json} exists; choose a new path")
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(dict(command=command, rows=rows), indent=1) + "\n")
            print("wrote", args.json)
        return
    if args.views:
        return seed_views(args.seed, args.layout, args.metro_src, args.tag, args.out_dir, args.replace, command)
    run(args.seed, args.layout, not args.no_ramp, args.out_dir, args.replace)


if __name__ == "__main__":
    main()
