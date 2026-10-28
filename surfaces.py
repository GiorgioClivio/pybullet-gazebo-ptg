"""Deterministic material images and metric box UVs, shared by GUI and RGB cameras."""
from pathlib import Path
import hashlib
import json
import math
import random
import os
import tempfile
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from styles import PROFILE, building_finishes, material_spec


ASSETS = Path(__file__).resolve().parent / "assets" / "procedural"
VERSION = 5
CACHE_LIMIT = 64 * 1024 * 1024


def decorate_materials(scene):
    """Describe textures in JSON; keep generation independent of PyBullet/assets."""
    seed, spaces = scene["config"]["seed"], scene["spaces"]
    finishes = building_finishes(seed)
    scene["style"] = dict(PROFILE, palette=finishes, texture_version=VERSION)
    styles = {}
    for space in spaces:
        # Two compatible finishes per building; circulation is always tiled.
        rng = random.Random(f'{seed}:floor_finish:{space["id"]}')
        styles[space["id"]] = dict(floor="planks" if space["kind"] == "room" and space.get("purpose") not in
                                    ("bathroom", "kitchen", "laundry") and rng.random() < .75 else "tile",
                                    wall="plaster")
        space["appearance"] = styles[space["id"]]
    for box in scene["boxes"]:
        kind, center = box["kind"], box["center"]
        level = box["level"]
        candidates = [s for s in spaces if s["level"] == level and
                      s["rect"][0] - .001 <= center[0] <= s["rect"][2] + .001 and
                      s["rect"][1] - .001 <= center[1] <= s["rect"][3] + .001]
        room = next((s for s in candidates if s["kind"] == "room"), next(iter(candidates), None))
        tag = room["id"] if room else level * 1000
        if kind in ("wall", "floor", "ceiling", "stairs"):
            style = styles[tag][kind] if room and kind in ("wall", "floor") else (
                "tile" if kind in ("floor", "stairs") else "plaster")
            box["texture"] = dict(style=style, seed=seed, period=2., label="")
            if kind in ("wall", "ceiling"):
                box["color"] = finishes["wall"][:]
            elif kind == "floor":
                box["color"] = finishes[style][:]
        elif box["material"] != "glass":
            box["texture"] = material_spec(box["material"], seed)
            if box["material"] == "screen":
                box["texture"]["seed"] += box.get("object_id", 0) % 4


def _font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _texture(spec):
    """512 px texture image for one material/print spec (deterministic in seed, style and label)."""
    n, rng = 512, random.Random(f'{spec["seed"]}:{spec["style"]}:{spec.get("label", "")}')
    style = spec["style"]
    if style in METRO_STYLES:  # New styles only; existing styles never reach this branch.
        return _metro_texture(spec)
    if spec.get("pictogram") or spec.get("plate") or spec.get("lab_texture"):  # room_styles images; other specs never set these keys.
        from room_styles import sign_texture
        return sign_texture(spec)
    if style in PRINTS:
        return _print_texture(spec, rng, n)
    return _material_texture(style, rng, n)


def _material_texture(style, rng, n):
    """Neutral albedo detail (tiles, planks, grain, plaster, weave), tinted by the shared palette in the renderer."""
    base = {style: (246, 246, 246) for style in ("plaster", "paint", "tile", "planks", "grain", "weave", "cardboard")}
    image = Image.new("RGB", (n, n), base.get(style, (237, 231, 212)))
    draw = ImageDraw.Draw(image)
    if style in ("tile", "planks"):
        width, height = {"tile": (128, 128), "planks": (256, 64)}[style]
        draw.rectangle((0, 0, n, n), fill=(194, 194, 194) if style == "tile" else (164, 164, 164))
        for row, y in enumerate(range(0, n, height)):
            offset = width // 2 if row % 2 and style == "planks" else 0
            for x in range(-offset, n, width):
                shade = rng.randint(-7, 3)
                color = tuple(max(0, min(255, c + shade)) for c in base[style])
                draw.rectangle((x + 1, y + 1, x + width - 1, y + height - 1), fill=color)
    if style in ("grain", "planks"):
        for _ in range(180):
            y = rng.randrange(n)
            points = [(x, y + rng.uniform(-3, 3) + 2 * math.sin(x / 45)) for x in range(0, n + 16, 16)]
            shade = rng.randint(224, 241)
            draw.line(points, fill=(shade, shade, shade), width=1)
    elif style in ("plaster", "paint", "cardboard"):
        for _ in range(3500):
            x, y = rng.randrange(n), rng.randrange(n)
            shade = rng.randint(-4, 3)
            color = tuple(max(0, min(255, c + shade)) for c in base[style])
            draw.rectangle((x, y, x + 1, y + 1), fill=color)
    elif style == "weave":
        for x in range(0, n, 4):
            draw.line((x, 0, x, n), fill=(232, 232, 232))
        for y in range(0, n, 4):
            draw.line((0, y, n, y), fill=(239, 239, 239))
        image = image.filter(ImageFilter.GaussianBlur(2))  # Suppress moire in low-resolution robot RGB views.
    if style == "grain":
        image = image.filter(ImageFilter.GaussianBlur(1.5))
    if style == "plaster":  # A small amount of broad, non-repeating variation within the material tile.
        noise = Image.new("L", (32, 32))
        noise.putdata([rng.randrange(60, 180) for _ in range(1024)])
        noise = noise.resize((n, n), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(3))
        image = Image.blend(image, Image.merge("RGB", (noise, noise, noise)), .015)
    return image


PALETTE = [(67, 85, 94), (151, 123, 93), (93, 111, 89), (130, 103, 94), (91, 91, 89)]
BACKDROPS = ((208, 211, 207), (225, 218, 202), (210, 209, 202))


def _art(draw, rng, spec, n):
    """Distinct landscapes/abstract compositions, including strong large features."""
    draw.rectangle((0, 0, n, n), fill=rng.choice(BACKDROPS))
    sun_x, sun_y = rng.randint(70, 440), rng.randint(55, 210)
    draw.ellipse((sun_x - 48, sun_y - 48, sun_x + 48, sun_y + 48), fill=rng.choice(PALETTE))
    for _ in range(5):
        x, y = rng.randint(-80, 440), rng.randint(170, 380)
        draw.polygon([(x - 130, n), (x + 80, y), (x + 260, n)], fill=rng.choice(PALETTE))
    for _ in range(12):
        x, y = rng.randrange(430), rng.randrange(450)
        draw.rectangle((x, y, x + rng.randint(12, 65), y + rng.randint(8, 34)), outline=rng.choice(PALETTE), width=4)
    theme = spec["seed"] % 4
    if theme:
        draw.rectangle((0, 0, n, n), fill=rng.choice(BACKDROPS))
    if theme == 1:  # City skyline, with windows at several scales.
        for x in range(10, n, 65):
            y = rng.randint(100, 310)
            draw.rectangle((x, y, x + 57, n), fill=rng.choice(PALETTE))
            for wx in range(x + 8, x + 50, 16):
                for wy in range(y + 15, n - 40, 26):
                    draw.rectangle((wx, wy, wx + 7, wy + 11), fill=(209, 199, 168))
    elif theme == 2:  # Botanical composition.
        for _ in range(5):
            x, y = rng.randint(75, 430), rng.randint(80, 310)
            draw.line((x, y, n / 2, n - 50), fill=(66, 89, 65), width=9)
            for angle in range(0, 360, 60):
                cx, cy = x + 27 * math.cos(math.radians(angle)), y + 27 * math.sin(math.radians(angle))
                draw.ellipse((cx - 24, cy - 24, cx + 24, cy + 24), fill=rng.choice(PALETTE))
            draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=(179, 164, 126))
    elif theme == 3:  # Large abstract shapes remain distinct at low camera resolution.
        for _ in range(8):
            x, y, size = rng.randint(10, 350), rng.randint(10, 350), rng.randint(55, 170)
            shape = draw.ellipse if rng.random() < .5 else draw.rectangle
            shape((x, y, x + size, y + size), fill=rng.choice(PALETTE))


def _notice(draw, rng, spec, n):
    """Notice board: nine pinned sheets with text lines."""
    draw.rectangle((0, 0, n, n), fill=(141, 125, 102))
    for i in range(9):
        x, y = 20 + (i % 3) * 164, 22 + (i // 3) * 164
        draw.rectangle((x, y, x + 140, y + 144), fill=rng.choice(((231, 226, 207), (213, 220, 219), (224, 216, 205))))
        for j in range(5):
            draw.line((x + 10, y + 35 + j * 17, x + rng.randint(65, 125), y + 35 + j * 17), fill=(74, 80, 85), width=3)
        draw.ellipse((x + 65, y + 4, x + 75, y + 14), fill=(105, 88, 78))


def _screen(draw, rng, spec, n):
    """Monitor content: list, chart, document or calendar, by seed."""
    draw.rectangle((0, 0, n, n), fill=(31, 40, 46))
    draw.rectangle((12, 12, 500, 58), fill=(62, 72, 76))
    mode = spec["seed"] % 4
    draw.text((28, 22), ("WORKSPACE", "REPORT", "FILES", "SCHEDULE")[mode], fill=(209, 211, 205), font=_font(22))
    if mode == 0:
        for i in range(11):
            draw.text((25, 86+i*35), f'{i+1:02d}', fill=(132, 145, 145), font=_font(18))
            draw.rectangle((75, 91+i*35, rng.randint(210, 470), 99+i*35), fill=PALETTE[i % 5])
    elif mode == 1:
        for y in range(130, 460, 65):
            draw.line((60, y, 470, y), fill=(78, 88, 90), width=2)
        draw.line((60, 90, 60, 460, 470, 460), fill=(182, 190, 184), width=4)
        draw.line([(70+i*49, rng.randint(150, 420)) for i in range(9)], fill=(151, 165, 139), width=9)
    elif mode == 2:
        draw.rectangle((18, 80, 145, 490), fill=(50, 60, 64))
        for i in range(7):
            y = 95+i*54
            draw.rectangle((35, y, 65, y+24), fill=(151, 139, 111))
            draw.rectangle((170, y, 460, y+11), fill=(167, 175, 169))
            draw.rectangle((170, y+22, 340, y+29), fill=(100, 116, 120))
    else:
        for i in range(6):
            for j in range(7):
                x, y = 20+j*69, 95+i*65
                draw.rectangle((x, y, x+63, y+58), outline=(93, 106, 108), width=2)
                draw.text((x+7, y+5), str(i*7+j+1), fill=(196, 201, 193), font=_font(17))
                if (i+j) % 3 == 0:
                    draw.rectangle((x+5, y+33, x+57, y+45), fill=(108, 132, 135))


def _sign(draw, rng, spec, n):
    """Room sign: framed label on a dark plate."""
    draw.rectangle((0, 0, n, n), fill=(60, 68, 69))
    draw.rounded_rectangle((15, 15, n - 15, n - 15), radius=15, outline=(211, 208, 195), width=9)
    draw.text((n / 2, n / 2), spec.get("label", "ROOM"), fill=(255, 249, 225), font=_font(68), anchor="mm", align="center")


PRINTS = {"art": _art, "notice": _notice, "screen": _screen, "sign": _sign}


def _print_texture(spec, rng, n):
    """Printed images (art, notices, screens, signs); a label strip at the bottom except on signs."""
    image = Image.new("RGB", (n, n), (237, 231, 212))
    draw = ImageDraw.Draw(image)
    PRINTS[spec["style"]](draw, rng, spec, n)
    if spec.get("label") and spec["style"] != "sign":
        draw.rectangle((14, n - 64, n - 14, n - 15), fill=(240, 232, 212))
        draw.text((n / 2, n - 40), spec["label"], fill=(34, 47, 56), font=_font(24), anchor="mm")
    return image


METRO_STYLES = ("concrete", "lining", "terrazzo", "tactile", "ballast", "metro_tile",
                "wide_sign", "departures", "line_map", "rock")


def _fit_text(draw, text, box_w, box_h, start):
    """Largest font (from `start`, steps of 4 px, at least 8) whose text fits box_w x box_h."""
    size = start
    while size > 8:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=_font(size))
        if right - left <= box_w and bottom - top <= box_h:
            break
        size -= 4
    return _font(size)


def _metro_texture(spec):
    """Metro finishes: neutral albedo detail (tinted by the part colour) and printed signs/screens.

    Printed styles take spec["aspect"] = face width / height: the image keeps that aspect (256 px high), so a
    fit-to-face display quad has square texels. Concrete and lining are 1.2 / 1.5 m modules with crisp
    joints over fine grain (no large blurred blotches).
    """
    n, style = 512, spec["style"]
    rng = random.Random(f'{spec["seed"]}:{style}:{spec.get("label", "")}')
    if style in ("wide_sign", "departures", "line_map"):
        return _metro_print(spec, rng, n)
    if style in ("concrete", "lining"):
        return _metro_cement(style, rng, n)
    base = {"ballast": 150, "metro_tile": 170}.get(style, 236)
    image = Image.new("RGB", (n, n), (base, base, base))
    draw = ImageDraw.Draw(image)
    if style == "terrazzo":
        for _ in range(5000):
            x, y, r = rng.randrange(n), rng.randrange(n), rng.choice((1, 1, 2, 2, 3))
            s = rng.choice((rng.randint(150, 200), rng.randint(242, 255), rng.randint(205, 230)))
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(s, s, s))
        for v in (0, n // 2):
            draw.line((v, 0, v, n), fill=(196, 196, 196), width=2)
            draw.line((0, v, n, v), fill=(196, 196, 196), width=2)
    elif style == "tactile":  # Truncated domes: about 50 mm spacing at a 0.6 m period.
        step = n // 12
        for i in range(12):
            for j in range(12):
                x, y = i * step + step // 2, j * step + step // 2
                draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=(196, 196, 196))
                draw.ellipse((x - 10, y - 11, x + 8, y + 7), fill=(250, 250, 250))
    elif style == "ballast":
        for _ in range(1400):
            x, y, r = rng.randrange(n), rng.randrange(n), rng.randint(5, 13)
            s = rng.randint(105, 215)
            draw.polygon([(x + r * math.cos(a) * rng.uniform(.7, 1.2), y + r * math.sin(a) * rng.uniform(.7, 1.2))
                          for a in (k * math.pi / 3 for k in range(6))], fill=(s, s, s))
    elif style == "rock":  # Mine rock (tunnel.py): blocky grey patches.
        for x in range(0, n, 32):
            for y in range(0, n, 32):
                v = rng.randint(150, 235)
                draw.rectangle((x, y, x + 31, y + 31), fill=(v, v, v))
    elif style == "metro_tile":  # Glazed 0.30 x 0.15 m wall tiles in running bond at a 1.2 m period.
        for row, y in enumerate(range(0, n, 64)):
            for x in range(-64 * (row % 2), n, 128):
                s = 238 + rng.randint(-6, 4)
                draw.rectangle((x + 2, y + 2, x + 125, y + 61), fill=(s, s, s))
                draw.line((x + 4, y + 4, x + 123, y + 4), fill=(250, 250, 250), width=2)
    return image


def _metro_print(spec, rng, n):
    """Wide sign, departures board or line map at the face aspect, rendered at 2x and downsampled."""
    style = spec["style"]
    w = int(n * min(8., max(1., float(spec.get("aspect", 1.)))))
    ink, paper = (236, 232, 218), (46, 57, 62)
    image = Image.new("RGB", (w, n), paper if style != "line_map" else (232, 229, 218))
    draw = ImageDraw.Draw(image)
    label = spec.get("label", "")
    if style == "wide_sign":
        draw.rectangle((0, n - 70, w, n), fill=(78, 116, 118))
        draw.rectangle((10, 10, w - 10, n - 80), outline=(120, 132, 132), width=6)
        draw.text((w / 2, (n - 70) / 2), label, fill=ink, anchor="mm", font=_fit_text(draw, label, w * .88, (n - 70) * .62, 300))
    elif style == "departures":
        draw.rectangle((0, 0, w, n), fill=(24, 30, 33))
        draw.text((30, 20), "DEPARTURES", fill=(212, 180, 104), font=_font(70))
        for i, name in enumerate((label or "CENTRAL").split("|")[:3]):
            y = 130 + i * 120
            draw.text((30, y), f"{i + 1}", fill=(212, 180, 104), font=_font(80))
            draw.text((150, y), name, fill=ink, font=_font(80))
            draw.text((w - 30, y), f"{2 + 4 * i + rng.randint(0, 2)} min", fill=ink, anchor="ra", font=_font(80))
    else:
        for k, colour in enumerate(((78, 116, 118), (151, 112, 84), (96, 108, 141), (128, 134, 88))):
            y0 = int(n * (.2 + .2 * k))
            points = [(40, y0)]
            for x in range(140, w - 40, 160):
                points.append((x, max(40, min(n - 40, points[-1][1] + rng.choice((-60, 0, 0, 60))))))
            draw.line(points, fill=colour, width=16)
            for x, y in points[1::2]:
                draw.ellipse((x - 14, y - 14, x + 14, y + 14), fill=(250, 248, 240), outline=(40, 40, 40), width=4)
        draw.text((40, 20), label, fill=(34, 47, 56), font=_font(54))
    return image.resize((round(w / 2), n // 2), Image.Resampling.LANCZOS)


def _metro_cement(style, rng, n):
    """Concrete formwork panels or tunnel lining: fine grain, faint tone (+-2 levels), pores and crisp joints."""
    import numpy as np
    gen = np.random.default_rng(rng.randrange(2 ** 32))
    tone = Image.fromarray(np.uint8(128 + gen.normal(0, 2, (8, 8)))).resize((n, n), Image.Resampling.BICUBIC)
    grain = np.clip(224 + gen.normal(0, 4.5, (n, n)) + np.asarray(tone, float) - 128, 0, 255)
    image = Image.fromarray(np.uint8(grain)).convert("RGB")
    draw = ImageDraw.Draw(image)
    for _ in range(700):
        x, y, r = rng.randrange(n), rng.randrange(n), rng.choice((1, 1, 1, 2))
        s = rng.randint(168, 196)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(s, s, s))
    if style == "concrete":  # 1.2 m formwork panels: crisp joints, tie holes on a 0.6 m grid.
        draw.rectangle((0, 0, n - 1, n - 1), outline=(184, 184, 184), width=2)
        for x in (n // 4, 3 * n // 4):
            for y in (n // 4, 3 * n // 4):
                draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=(196, 196, 196), outline=(150, 150, 150), width=2)
    else:  # 1.5 m segment rings: circumferential and longitudinal joints, bolt pockets beside the ring joint.
        draw.line((1, 0, 1, n), fill=(158, 158, 158), width=4)
        draw.line((0, 1, n, 1), fill=(176, 176, 176), width=3)
        for y in range(64, n, 128):
            for x in (14, n - 26):
                draw.rectangle((x, y - 14, x + 12, y + 14), fill=(186, 186, 186), outline=(146, 146, 146), width=2)
    return image


def _write_texture(key):
    spec = json.loads(key)
    digest = hashlib.sha256(f"{VERSION}:{key}".encode()).hexdigest()[:20]
    path = ASSETS / f'{spec["style"]}_{digest}.png'
    if not path.exists():
        ASSETS.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=ASSETS, suffix=".png", delete=False) as temporary:
            _texture(spec).save(temporary, format="PNG")
        os.replace(temporary.name, path)
    return str(path)


def texture_path(spec):
    return _write_texture(json.dumps(spec, sort_keys=True))


def prepare_textures(scene):
    """CLI calls this before opening the window; no construction appears on screen."""
    paths = {texture_path(box["texture"]) for box in scene["boxes"] if "texture" in box}
    prune_cache(paths)
    return paths


def prune_cache(keep=(), limit=CACHE_LIMIT):
    """Bound generated PNGs on disk; preserve the current scene and all user assets."""
    pinned = {Path(path).resolve() for path in keep}
    files = [p for p in ASSETS.glob("*.png") if re.fullmatch(r"[a-z_]+_[0-9a-f]{20}\.png", p.name)]
    # Count allocated blocks too: thousands of tiny PNGs otherwise exceed the
    # advertised disk budget through filesystem allocation overhead.
    def cost(path):
        stat = path.stat()
        return max(stat.st_size, getattr(stat, "st_blocks", 0) * 512)
    sizes = {p: cost(p) for p in files}
    if sum(size for p, size in sizes.items() if p.resolve() in pinned) > limit:
        raise ValueError(f"This scene exceeds the {limit / 2**20:.1f} MiB texture budget; reduce its room/floor count")
    total = sum(sizes.values())
    for path in sorted(files, key=lambda p: p.stat().st_mtime_ns):
        if total <= limit:
            break
        if path.resolve() not in pinned:
            path.unlink()
            total -= sizes[path]
    return dict(cache_bytes=total, limit_bytes=limit, active_texture_bytes=sum(
        p.stat().st_size for p in pinned if p.exists()), active_textures=len(pinned))


def box_mesh(box):
    """24 vertices: per-face UVs in metres, or fit-to-face artwork without stretching tiles."""
    vertices, uvs, normals, indices = [], [], [], []
    half = [s / 2 for s in box["size"]]
    spec = box["texture"]
    period, fit = spec.get("period", 2.), spec["style"] in ("art", "notice", "sign", "screen")
    for axis in range(3):
        u, v = ((1, 2), (0, 2), (0, 1))[axis]
        for side in (-1, 1):
            start = len(vertices)
            corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
            if (axis == 1) == (side == 1):
                corners.reverse()
            for a, b in corners:
                point = [0., 0., 0.]
                point[axis], point[u], point[v] = side * half[axis], a * half[u], b * half[v]
                vertices.append(point)
                normal = [0., 0., 0.]
                normal[axis] = side
                normals.append(normal)
                uv = [(a + 1) / 2, (b + 1) / 2] if fit else [
                    (point[u] + box["center"][u]) / period, (point[v] + box["center"][v]) / period]
                if fit and ((axis == 0 and side < 0) or (axis == 1 and side > 0)):
                    uv[0] = 1 - uv[0]
                if fit and axis == 2 and "print_up" in box:  # floor print: text up = (axis, sign), read facing it
                    k, sign = box["print_up"]
                    right = 1 - k  # the reader's right: +x when up is +y, -y when up is +x
                    r_sign = sign if k == 1 else -sign
                    uv = [.5 + r_sign * point[right] / box["size"][right], .5 + sign * point[k] / box["size"][k]]
                thin = min(range(3), key=lambda k: box["size"][k])
                if fit and axis != thin:  # Edges of a print keep the face's texel size (no squeezed image).
                    edge = max(box["size"][k] for k in range(3) if k != thin)
                    uv = [(point[k] + half[k]) / (edge if k == thin else box["size"][k]) for k in (u, v)]
                uvs.append(uv)
            indices.extend([start, start + 1, start + 2, start, start + 2, start + 3])
    return dict(vertices=vertices, indices=indices, uvs=uvs, normals=normals)
