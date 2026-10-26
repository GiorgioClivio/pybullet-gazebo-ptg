"""Texel audit: texel density, anisotropy, motif size and image sharpness of every textured part.

Purpose: find textures that look blurred, smeared over large surfaces or distorted.

Method, per textured part, from its ACTUAL visual mesh (geometry.mesh / surfaces.box_mesh, the same
data indoor.load_pybullet uploads) and the actual image size:
  * per triangle, the Jacobian J = dPosition / dPixel (3 x 2, metres per texel) from positions and UVs;
    its singular values s1 >= s2 give the worst texel density 1 / s1 (px/m) and the anisotropy s1 / s2
    (1 = square texels; 5 = a texel 5x longer in one direction, i.e. streaks). Area-weighted per part.
  * motif size: for styles with a physical motif (tiles, planks, panels, rings, domes), the motif's
    size on the surface = motif pixels x |J e_u| (or e_v); it must match the real size within 10 %.
  * sharpness of each image (grayscale): contrast C = std(I), high-frequency energy H = std(I - G2 * I)
    (G2 = Gaussian, sigma 2 px), ratio H / C and var(Laplacian). A visible pattern (C >= 2 grey levels)
    with H / C < 0.30 is mostly low-frequency blotches: flagged "blurred" for styles meant to look sharp.

Thresholds (justification in README "Texel audit"):
  density >= 256 px/m for architecture and parts >= 1 m (one texel per camera pixel at 4 m for a
  1280 px, 70 deg camera: 1280 / (2 * 4 * tan 35 deg) = 229 px/m); anisotropy <= 1.25 for all parts whose
  image has visible structure (contrast >= 2 grey levels; raw anisotropy is still reported in the CSV).

    python3 tools/texel_audit.py --tag before --out reports/texel_audit_before.csv
    python3 tools/texel_audit.py --self-test
Outputs: CSV per part (new file; refuses to overwrite unless --replace), and a summary table on stdout.
"""
from pathlib import Path
import argparse
import csv
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

DENSITY_MIN, ANISO_MAX, MOTIF_TOL, BLUR_RATIO, CONTRAST_MIN = 256., 1.25, .10, .30, 2.
ARCHITECTURE = {"wall", "floor", "ceiling", "stairs", "trim", "track"}
# style: (motif repeats per image along u, along v, real motif size u, v in metres). Printed/fit styles: none.
MOTIFS = {"tile": (4, 4, .5, .5), "planks": (2, 8, 1.0, .25), "terrazzo": (2, 2, .6, .6), "metro_tile": (4, 8, .30, .15),
          "tactile": (12, 12, .05, .05), "concrete": (1, 1, 1.2, 1.2), "lining": (1, 1, 1.5, 1.5)}
# Styles whose images must not be blurred: every material except deliberately smooth ones.
SMOOTH = {"weave": "2 px Gaussian on purpose (anti-moire on fabric)", "plaster": "near-uniform paint, contrast < 2"}
FIT = {"art", "notice", "sign", "screen", "wide_sign", "departures", "line_map"}
CAMERA = dict(width_px=1280, fov_deg=70)


def jacobian_stats(vertices, uvs, indices, size):
    """Per-triangle (area, min density px/m, anisotropy, m per px along u, along v) of a UV-mapped mesh."""
    P = np.asarray(vertices, float)
    T = np.asarray(uvs, float) * np.asarray(size, float)  # pixels
    tri = np.asarray(indices, int).reshape(-1, 3)
    out = []
    for a, b, c in tri:
        dP = np.stack([P[b] - P[a], P[c] - P[a]], 1)            # 3 x 2
        dT = np.stack([T[b] - T[a], T[c] - T[a]], 1)            # 2 x 2
        area = .5 * np.linalg.norm(np.cross(dP[:, 0], dP[:, 1]))
        if area < 1e-12:
            continue
        if abs(np.linalg.det(dT)) < 1e-9:
            out.append((area, 0., math.inf, math.inf, math.inf))  # Degenerate UV: the image is smeared.
            continue
        J = dP @ np.linalg.inv(dT)                              # metres per pixel
        s = np.linalg.svd(J, compute_uv=False)
        out.append((area, 1 / s[0], s[0] / max(s[1], 1e-12), np.linalg.norm(J[:, 0]), np.linalg.norm(J[:, 1])))
    return out


def part_mesh(b):
    """Visual mesh of a part exactly as the loader builds it."""
    from geometry import mesh
    from surfaces import box_mesh
    return mesh(b) if b.get("shape") else box_mesh(b)


def image_stats(spec, cache={}):
    """(width, height), contrast of the image the loader would use for this spec."""
    key = json.dumps(spec, sort_keys=True)
    if key not in cache:
        from PIL import Image
        from surfaces import texture_path
        path = texture_path(spec)
        with Image.open(path) as image:
            cache[key] = image.size, sharpness(path)["contrast"]
    return cache[key]


def audit_part(b):
    """Texel density, anisotropy and motif error of one textured part."""
    spec = b["texture"]
    size, contrast = image_stats(spec)
    m = part_mesh(b)
    rows = jacobian_stats(m["vertices"], m["uvs"], m["indices"], size)
    if not rows:
        return None
    area = sum(r[0] for r in rows)
    big = [r for r in rows if r[0] >= 1e-3 * area] or rows  # Ignore slivers below 0.1 % of the part area.
    density = min(r[1] for r in big)
    aniso = max(r[2] for r in big)
    style = spec["style"]
    motif = None
    if style in MOTIFS:
        ru, rv, mu, mv = MOTIFS[style]
        meas_u = np.average([r[3] for r in big], weights=[r[0] for r in big]) * size[0] / ru
        meas_v = np.average([r[4] for r in big], weights=[r[0] for r in big]) * size[1] / rv
        motif = max(abs(meas_u / mu - 1), abs(meas_v / mv - 1))
    large = b["kind"] in ARCHITECTURE or max(b["size"]) >= 1.
    fails = []
    if large and style not in FIT and density < DENSITY_MIN * (1 - 1e-3):
        fails.append("density")
    visible = contrast >= CONTRAST_MIN  # Stretching an image with no visible structure cannot be seen.
    if aniso > ANISO_MAX and visible:
        fails.append("anisotropy")
    if motif is not None and motif > MOTIF_TOL and visible:
        fails.append("motif")
    return dict(style=style, kind=b["kind"], element=b.get("element", b.get("label", "")), shape=b.get("shape", "box"),
                area_m2=round(area, 3), density_px_m=round(density, 1), anisotropy=round(aniso, 2), image_contrast=contrast,
                motif_error=None if motif is None else round(motif, 3), large=large, fails=";".join(fails))


def sharpness(path):
    """Contrast and high-frequency ratio of one texture image."""
    from PIL import Image, ImageFilter
    with Image.open(path) as image:
        g = image.convert("L")
        a = np.asarray(g, float)
        blurred = np.asarray(g.filter(ImageFilter.GaussianBlur(2)), float)
    lap = a[1:-1, 1:-1] * -4 + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    contrast, high = a.std(), (a - blurred).std()
    return dict(contrast=round(contrast, 2), high_freq=round(high, 2), ratio=round(high / max(contrast, 1e-9), 3),
                laplacian_var=round(lap.var(), 1))


def scenes(which):
    """Generate the scenes named indoor:<seed> or metro:<seed>[:layout][:noramp]."""
    import indoor
    import metro
    out = []
    for name in which:
        kind, seed, *opts = name.split(":")
        if kind == "indoor":
            out.append((name, indoor.generate(indoor.Config(seed=int(seed)))))
        else:
            layout = opts[0] if opts else "island"
            out.append((name, metro.generate_metro(metro.MetroConfig(seed=int(seed), layout=layout, spiral_ramp="noramp" not in opts))))
    return out


def run(which, out, replace, tag):
    """Audit every textured part of the named scenes; return the rows."""
    from surfaces import texture_path
    rows, images = [], {}
    for name, scene in scenes(which):
        for i, b in enumerate(scene["boxes"]):
            if "texture" not in b:
                continue
            r = audit_part(b)
            if r:
                rows.append(dict(scene=name, part=i, **r))
                images.setdefault(b["texture"]["style"], set()).add(texture_path(b["texture"]))
    blur = {}
    for style, paths in images.items():
        stats = [sharpness(p) for p in sorted(paths)[:6]]
        worst = min(stats, key=lambda s: s["ratio"] if s["contrast"] >= CONTRAST_MIN else math.inf)
        flagged = style not in SMOOTH and style not in FIT and worst["contrast"] >= CONTRAST_MIN and worst["ratio"] < BLUR_RATIO
        blur[style] = dict(worst, blurred=flagged, images=len(paths))
    if out:
        out = Path(out)
        if out.exists() and not replace:
            raise FileExistsError(f"{out} exists; use --replace or a new name")
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    summary = summarize(rows, blur)
    print(f"Texel audit [{tag}] scenes={','.join(which)} parts={len(rows)} failing={sum(bool(r['fails']) for r in rows)}")
    print(f"{'style':12s} {'parts':>6s} {'fail':>6s} {'min px/m':>9s} {'max aniso':>9s} {'motif err':>9s} {'H/C':>6s} {'blur':>5s}")
    for s in summary:
        print(f"{s['style']:12s} {s['parts']:6d} {s['failing']:6d} {s['min_density']:9.0f} {s['max_anisotropy']:9.2f} "
              f"{'' if s['max_motif_error'] is None else format(s['max_motif_error'], '.2f'):>9s} {s['blur_ratio']:6.2f} {'YES' if s['blurred'] else '':>5s}")
    worst = sorted((r for r in rows if r["fails"]), key=lambda r: (-r["area_m2"] * (r["anisotropy"] if r["anisotropy"] != math.inf else 99)))[:12]
    print("worst offenders (area x anisotropy):")
    for r in worst:
        print(f"  {r['scene']:18s} part {r['part']:5d} {r['style']:10s} {r['shape']:9s} {r['element'][:18]:18s} "
              f"{r['area_m2']:8.2f} m2 {r['density_px_m']:7.0f} px/m aniso {r['anisotropy']:6.2f} [{r['fails']}]")
    return rows, summary


def summarize(rows, blur):
    """Per-style summary rows of an audit."""
    out = []
    for style in sorted({r["style"] for r in rows}):
        sel = [r for r in rows if r["style"] == style]
        motifs = [r["motif_error"] for r in sel if r["motif_error"] is not None]
        large = [r["density_px_m"] for r in sel if r["large"]] or [r["density_px_m"] for r in sel]
        out.append(dict(style=style, parts=len(sel), failing=sum(bool(r["fails"]) for r in sel), min_density=min(large),
                        max_anisotropy=max(r["anisotropy"] for r in sel), max_motif_error=max(motifs) if motifs else None,
                        blur_ratio=blur.get(style, {}).get("ratio", float("nan")), blurred=blur.get(style, {}).get("blurred", False)))
    return out


def views():
    """Robot-eye (1.6 m) cameras: name -> (scene key, eye, target, caption)."""
    import indoor
    import metro
    m = metro.generate_metro(metro.MetroConfig(seed=7, layout="island"))
    cams = metro.views(m)
    col = min((b for b in m["boxes"] if b.get("element") == "column" and b["level"] == 1),
              key=lambda b: math.dist(b["center"][:2], m["spawn"][:2]))
    cx, cy = col["center"][:2]
    room = indoor.generate(indoor.Config(seed=7))
    lamp = next(o for o in room["objects"] if o["kind"] in ("lamp", "plant"))
    r = room["spaces"][lamp["room"]]["rect"]
    hub = [(r[0] + r[2]) / 2, (r[1] + r[3]) / 2]
    lx, ly = lamp["center"][:2]
    d = math.dist(hub, (lx, ly)) or 1.
    eye = [lx + (hub[0] - lx) / d * min(2.2, d + 1.), ly + (hub[1] - ly) / d * min(2.2, d + 1.), 1.6]
    return dict(
        concourse_columns=("metro", [cx + 3.2, cy - 2.2, 1.6], [cx - 6, cy + 1.5, 2.2], "Metro concourse columns, eye 1.6 m"),
        platform=("metro", cams["platform"]["eye"], cams["platform"]["target"], "Metro platform: walls, ceiling, track"),
        tunnel=("metro", cams["tunnel"]["eye"], cams["tunnel"]["target"], "Metro tunnel mouth and lining"),
        indoor_room=("indoor", eye, [lx, ly, .7], f"Indoor seed 7 room {lamp['room']}: turned objects")), dict(metro=m, indoor=room)


def render_figure(tag, out_dir, replace):
    """Render the robot-eye views with the CURRENT library (tag = before/after)."""
    sys.path.insert(0, str(ROOT / "tools"))
    import render
    cams, scenes_by_key = views()
    light = dict(lightDirection=[-2., -3., 8.], lightAmbientCoeff=.6, lightDiffuseCoeff=.45, lightSpecularCoeff=.05)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for key in ("metro", "indoor"):
        names = [n for n, v in cams.items() if v[0] == key]
        shots = [dict(eye=cams[n][1], target=cams[n][2], fov=70, size=(1280, 800), near=.05, far=300) for n in names]
        images, _ = render.render(scenes_by_key[key], shots, light, ((.9, .9, .9), (.8, .8, .8)), shadow=0)
        for name, image in zip(names, images):
            path = out_dir / f"{tag}_{name}.png"
            if path.exists() and not replace:
                raise FileExistsError(f"{path} exists; use --replace")
            image.save(path)
            print("wrote", path)


def compose(out_dir, before_csv, after_csv, replace):
    """One figure per view (before | after) and one before/after table per style."""
    sys.path.insert(0, str(ROOT / "tools"))
    import matplotlib.pyplot as plt
    from PIL import Image
    from render import FIGSIZE, DPI, INK, QUIET, save
    out_dir = Path(out_dir)
    command = "python3 tools/texel_audit.py --compose --replace"
    tables = {}
    for tag, path in (("before", before_csv), ("after", after_csv)):
        with open(path) as handle:
            rows = list(csv.DictReader(handle))
        tables[tag] = {s: [r for r in rows if r["style"] == s] for s in {r["style"] for r in rows}}
    rescore(tables)
    cams, _ = views()
    for name, (_, _, _, caption) in cams.items():
        fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
        fig.text(.02, .965, f"Texture audit: {caption}", fontsize=8, color=INK, fontweight="bold", va="top")
        fig.text(.02, .905, "PyBullet TinyRenderer 1280 x 800, 70 deg FOV, same camera; left: library before the fix, right: after.",
                 fontsize=4.6, color=QUIET, va="top")
        for i, tag in enumerate(("before", "after")):
            ax = fig.add_axes([.02 + i * .49, .08, .47, .76])
            ax.imshow(Image.open(out_dir / f"{tag}_{name}.png"))
            ax.set_title(tag, fontsize=6, color=INK, pad=2)
            ax.axis("off")
        save(fig, out_dir / f"{name}_before_after.png", command, replace=replace)
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
    fig.text(.02, .965, "Texel audit per texture style: before / after", fontsize=8, color=INK, fontweight="bold", va="top")
    fig.text(.02, .915, f"Scenes: indoor seeds 7, 0, 13; metro seed 7 island, seed 3 side no ramp. Pass: density >= {DENSITY_MIN:.0f} px/m "
             f"(architecture, parts >= 1 m), anisotropy <= {ANISO_MAX} where the image has visible structure, motif within 10 %.",
             fontsize=4.2, color=QUIET, va="top")
    styles = sorted(set(tables["before"]) | set(tables["after"]))

    def cell(tag, style):
        rows = tables[tag].get(style, [])
        if not rows:
            return ["", "", "", ""]
        fail = sum(bool(r["fails"]) for r in rows)
        dens = min(float(r["density_px_m"]) for r in rows if r["large"] == "True") if any(r["large"] == "True" for r in rows) else math.nan
        an = max(float(r["anisotropy"]) for r in rows)
        return [f"{fail}/{len(rows)}", "" if math.isnan(dens) else f"{dens:.0f}", "inf" if math.isinf(an) else f"{an:.2f}"]
    cells = [[s] + cell("before", s)[:3] + cell("after", s)[:3] for s in styles]
    ax = fig.add_axes([.02, .06, .96, .80])
    ax.axis("off")
    t = ax.table(cellText=cells, colLabels=["Style", "Fail (before)", "Min px/m", "Max aniso", "Fail (after)", "Min px/m", "Max aniso"],
                 loc="upper center", cellLoc="right", colLoc="right")
    t.auto_set_font_size(False)
    t.set_fontsize(3.6)
    t.scale(1, .82)
    for (r, c), cl in t.get_celld().items():
        cl.set_edgecolor("#c9ced2")
        cl.set_linewidth(.3)
    save(fig, out_dir / "audit_table_before_after.png", command, replace=replace)
    print("composed figures in", out_dir)


CHANGED_STYLES = {"concrete", "lining", "wide_sign", "departures", "line_map"}  # Images repainted by the fix.


def rescore(tables):
    """Apply the visible-structure rule to rows audited before the image contrast was recorded.

    Styles whose images did not change (identical image bytes) take the contrast measured
    after; repainted styles are visible by measurement of the old cached images (concrete 9.1, lining 11.6).
    """
    contrast = {}
    for rows in tables["after"].values():
        for r in rows:
            contrast[r["style"]] = max(contrast.get(r["style"], 0.), float(r["image_contrast"]))
    for rows in tables["before"].values():
        for r in rows:
            if r.get("image_contrast"):
                continue
            visible = r["style"] in CHANGED_STYLES or contrast.get(r["style"], math.inf) >= CONTRAST_MIN
            fails = [f for f in r["fails"].split(";") if f]
            if not visible:
                fails = [f for f in fails if f not in ("anisotropy", "motif")]
            if float(r["density_px_m"]) >= DENSITY_MIN * (1 - 1e-3):  # Same float tolerance as audit_part (CSV rounds to .1).
                fails = [f for f in fails if f != "density"]
            r["fails"] = ";".join(fails)


def _self_test():
    # A 1 x 1 m square mapped to a 512 px image once: 512 px/m, isotropic.
    v = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
    uv = [[0, 0], [1, 0], [1, 1], [0, 1]]
    idx = [0, 1, 2, 0, 2, 3]
    r = jacobian_stats(v, uv, idx, (512, 512))
    assert all(abs(t[1] - 512) < 1e-6 and abs(t[2] - 1) < 1e-9 for t in r), r
    # Stretch u over 3 m: density 512/3 px/m, anisotropy 3.
    r = jacobian_stats([[x * 3, y, z] for x, y, z in v], uv, idx, (512, 512))
    assert all(abs(t[1] - 512 / 3) < 1e-6 and abs(t[2] - 3) < 1e-9 for t in r), r
    # Degenerate UVs are reported as infinitely anisotropic.
    assert jacobian_stats(v, [[0, 0]] * 4, idx, (512, 512))[0][2] == math.inf
    # A blurred noise image is flagged by the H/C ratio; a sharp one is not.
    from PIL import Image, ImageFilter
    import tempfile
    rng = np.random.default_rng(0)
    with tempfile.TemporaryDirectory() as tmp:
        sharp = Image.fromarray(np.uint8(rng.integers(100, 160, (128, 128))))
        sharp.save(f"{tmp}/s.png")
        sharp.filter(ImageFilter.GaussianBlur(6)).point(lambda x: (x - 130) * 8 + 130).save(f"{tmp}/b.png")
        assert sharpness(f"{tmp}/s.png")["ratio"] > .8 and sharpness(f"{tmp}/b.png")["ratio"] < BLUR_RATIO
    print("texel_audit self-test ok")


def main(argv=None):
    """Command line: audit, render views, or compose before/after figures."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenes", nargs="+", default=["indoor:7", "indoor:0", "indoor:13", "metro:7:island", "metro:3:side:noramp"],
                        help="indoor:<seed> or metro:<seed>[:island|side][:noramp]")
    parser.add_argument("--out", type=Path, help="CSV per part (new file)")
    parser.add_argument("--tag", default="current")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--render", metavar="TAG", help="Render the 1.6 m views with the current library as TAG_<view>.png")
    parser.add_argument("--compose", action="store_true", help="Compose before/after figures and the audit table")
    parser.add_argument("--fig-dir", type=Path, default=ROOT / "reports" / "texture_audit")
    parser.add_argument("--before", type=Path, default=ROOT / "reports" / "texel_audit_before.csv")
    parser.add_argument("--after", type=Path, default=ROOT / "reports" / "texel_audit_after.csv")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.render:
        return render_figure(args.render, args.fig_dir, args.replace)
    if args.compose:
        return compose(args.fig_dir, args.before, args.after, args.replace)
    run(args.scenes, args.out, args.replace, args.tag)


if __name__ == "__main__":
    main()
