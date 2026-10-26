"""Count coplanar same-facing face pairs (z-fighting) per part-kind pair in generated scenes.

    python3 tools/zfight_audit.py                      # building seed 0 (2 storeys), metro seed 1, Lab D66
    python3 tools/zfight_audit.py --scene metro --seed 7

Uses geometry.coplanar_pairs on the finished scene: after the generators apply the gap rule,
every count should be 0.
"""
import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def scenes(which, seed):
    """Yield (name, scene) for the requested scene set."""
    from indoor import Config, generate
    from metro import MetroConfig, generate_metro
    if which in ("all", "building"):
        yield f"building seed {seed if which != 'all' else 0}", generate(Config(seed=seed if which != "all" else 0, floors=2))
    if which in ("all", "metro"):
        yield f"metro seed {seed if which != 'all' else 1}", generate_metro(MetroConfig(seed=seed if which != "all" else 1))
    if which in ("all", "d66"):
        yield "Lab D66 (seed 66)", generate(Config(seed=66))


def audit(scene):
    """Count z-fighting pairs per (kind, shape, other kind, face)."""
    from geometry import coplanar_pairs
    boxes = scene["boxes"]
    return collections.Counter((boxes[i]["kind"], boxes[i].get("shape") or "box", boxes[j]["kind"], "xyz"[a] + "-+"[d > 0])
                               for i, j, a, d in coplanar_pairs(scene))


def main():
    """Command line: print the z-fighting pairs of each scene."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", choices=("all", "building", "metro", "d66"), default="all")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    for name, scene in scenes(args.scene, args.seed):
        counts = audit(scene)
        print(f"{name}: {sum(counts.values())} z-fighting pairs, {len(scene['boxes'])} parts")
        for (k1, s1, k2, face), n in counts.most_common(15):
            print(f"  {n:5d}  {k1}/{s1} on {k2}, face {face}")


if __name__ == "__main__":
    main()
