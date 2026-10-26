"""Close-up grid of every part with a given role (door plates, pictogram faces, screens...), as seen by a reader.

Loads the scene in PyBullet DIRECT (load_pybullet, real textures) and renders each part with the
TinyRenderer from the side it is meant to be read from: for floor prints (print_up) the camera stands
behind the text baseline, for wall/kiosk prints in front of the outward face of the thinnest axis.

    python3 tools/part_closeup.py --role door_plate --seed 0 --floors 2 --out images/closeup_door_plates_seed0.png
    python3 tools/part_closeup.py --scene metro --seed 1 --role pictogram_face --out images/closeup_metro_signs_seed1.png

Refuses to overwrite --out unless --replace. The figure footer records the command that made it.
"""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def reader_camera(part, distance=.9):
    """(eye, target, up) for reading one part: floor prints from behind their baseline, others head-on."""
    c, s = part["center"], part["size"]
    if "print_up" in part:
        k, sign = part["print_up"]
        eye = list(c)
        eye[k] -= sign * distance * .8
        eye[2] += distance
        return eye, list(c), [0, 0, 1]
    thin = min(range(3), key=lambda a: s[a])
    side = part.get("print_side", 1)  # outward sign of the printed face along the thin axis
    eye = list(c)
    eye[thin] += side * distance
    return eye, list(c), [0, 0, 1] if thin != 2 else [0, 1, 0]


def render(scene, parts, size=320, cols=4, label=""):
    """Contact sheet of reader-view close-ups of `parts`, one tile per part."""
    import pybullet as p
    from PIL import Image, ImageDraw
    from indoor import load_pybullet
    client = p.connect(p.DIRECT)
    try:
        load_pybullet(scene, client)
        tiles = []
        for part in parts:
            eye, target, up = reader_camera(part)
            view = p.computeViewMatrix(eye, target, up)
            proj = p.computeProjectionMatrixFOV(50, 1, .02, 20)
            _, _, rgba, _, _ = p.getCameraImage(size, size, view, proj, renderer=p.ER_TINY_RENDERER, physicsClientId=client)
            tiles.append(Image.frombytes("RGBA", (size, size), bytes(bytearray(int(v) for v in rgba)) if not hasattr(rgba, "tobytes")
                                         else rgba.tobytes()).convert("RGB"))
    finally:
        p.disconnect(client)
    rows = max(1, -(-len(tiles) // cols))
    sheet = Image.new("RGB", (cols * size, rows * size + 28), "white")
    for n, tile in enumerate(tiles):
        sheet.paste(tile, ((n % cols) * size, (n // cols) * size))
    ImageDraw.Draw(sheet).text((6, rows * size + 8), label, fill=(0, 0, 0))
    return sheet


def main():
    """Command line: close-ups of every part with the given role."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", choices=("building", "metro"), default="building")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--floors", type=int, default=1)
    ap.add_argument("--role", required=True, help="part role to show (e.g. door_plate, pictogram_face)")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()
    if args.out.exists() and not args.replace:
        sys.exit(f"{args.out} exists; pass --replace to overwrite it")
    if args.scene == "metro":
        from metro import MetroConfig, generate_metro
        scene = generate_metro(MetroConfig(seed=args.seed))
    else:
        from indoor import Config, generate
        scene = generate(Config(seed=args.seed, floors=args.floors))
    parts = [b for b in scene["boxes"] if b.get("role") == args.role][:args.limit]
    if not parts:
        sys.exit(f"no part with role {args.role!r}")
    command = "python3 tools/part_closeup.py " + " ".join(sys.argv[1:])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    render(scene, parts, label=command).save(args.out)
    print(f"{args.out}: {len(parts)} parts with role {args.role}")


if __name__ == "__main__":
    main()
