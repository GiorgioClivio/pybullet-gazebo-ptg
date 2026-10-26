"""How much geometry.separate_coplanar changed a scene: per-part growth, centre shift and walkable lips.

    python3 tools/gap_effect.py            # building seed 0 (2 storeys), metro seed 1, Lab D66

Generates each scene twice (rule on / rule off) and compares part by part.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geometry
from zfight_audit import scenes


def compare(on, off):
    """Per-part growth, centre shift and walkable lip between two versions of one scene."""
    rows = []
    for a, b in zip(on["boxes"], off["boxes"]):
        grow = max(abs(x - y) for x, y in zip(a["size"], b["size"]))
        shift = max(abs(x - y) for x, y in zip(a["center"], b["center"]))
        top = lambda p: p["center"][2] + p["size"][2] / 2
        coll_top = lambda p: p.get("collision_center", p["center"])[2] + p.get("collision_size", p["size"])[2] / 2
        lip = max(top(a) - top(b), coll_top(a) - coll_top(b)) if a["kind"] in ("floor", "stairs") else 0.
        rows.append((grow, shift, lip, a["kind"]))
    return rows


def main():
    """Print the gap rule's effect on the building, metro and Lab D66 scenes."""
    rule = geometry.separate_coplanar
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    # Materialise both lists: zipping the generators would build "on" scenes while the rule is patched out.
    for (name, on), (_, off) in zip(list(scenes("all", 0)), list(_without(rule))):
        rows = compare(on, off)
        moved = [r for r in rows if r[0] > 1e-9]
        print(f"{name}: {len(moved)}/{len(rows)} parts changed; max growth {max(r[0] for r in rows)*1000:.1f} mm, "
              f"max centre shift {max(r[1] for r in rows)*1000:.1f} mm, max walkable lip {max(r[2] for r in rows)*1000:.2f} mm, "
              f"parts grown > 10 mm: {sum(r[0] > .010 for r in rows)}")


def _without(rule):
    geometry.separate_coplanar = lambda scene, *a, **k: 0
    try:
        yield from scenes("all", 0)
    finally:
        geometry.separate_coplanar = rule


if __name__ == "__main__":
    main()
