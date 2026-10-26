"""Regression fingerprints of generated scenes: the layout must not change unless intended.

Two SHA-256 per configuration:
  layout: spaces, portals, stairs, loop routes, spawn, bounds and every architectural box
          (wall, floor, glass, trim, stairs, ceiling). This is what a host simulation relies on.
  full:   the whole scene JSON (changes whenever objects, textures or lights change).

    python3 tools/baseline.py record reports/baseline.json   # new file only
    python3 tools/baseline.py check  reports/baseline.json   # exit 1 if a layout hash changed
    python3 tools/baseline.py check --strict PATH                       # exit 1 if any scene changed at all
    python3 tools/baseline.py --self-test
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARCHITECTURE = {"wall", "floor", "glass", "trim", "stairs", "ceiling"}
# The default building (seed 0) plus the documented examples.
CONFIGS = {
    "seed0": dict(seed=0),
    "seed0_3floors_roof": dict(seed=0, floors=3, roof=True),
    "seed7": dict(seed=7),
    "seed7_3floors": dict(seed=7, floors=3),
    "seed7_empty_plain": dict(seed=7, furnished=False, details=False),
    "seed42_18rooms": dict(seed=42, rooms=18, width=28., depth=22., floors=2),
    "lab_d66": dict(seed=66),
}
METRO_CONFIGS = {"metro_seed0": dict(seed=0), "metro_seed1": dict(seed=1), "metro_seed7": dict(seed=7)}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def fingerprints(scene):
    """SHA-256 of the scene's layout (architecture only) and of the whole scene."""
    layout = {k: scene[k] for k in ("spaces", "portals", "stairs", "loop_routes", "spawn", "bounds")}
    # Space records gain derived fields (purpose, appearance) from later stages; keep geometry only.
    layout["spaces"] = [{k: s[k] for k in ("id", "kind", "level", "rect")} for s in scene["spaces"]]
    layout["boxes"] = [{k: b[k] for k in ("kind", "size", "center", "level")} for b in scene["boxes"]
                       if b["kind"] in ARCHITECTURE]
    if "metro_stats" in scene:  # generation_s is a wall-clock measurement, not scene content
        scene = dict(scene, metro_stats={k: v for k, v in scene["metro_stats"].items() if k != "generation_s"})
    return dict(layout=digest(layout), full=digest(scene))


def compute():
    """Fingerprints of every configuration in CONFIGS and METRO_CONFIGS."""
    from indoor import Config, generate
    from metro import MetroConfig, generate_metro
    return {**{name: fingerprints(generate(Config(**kwargs))) for name, kwargs in CONFIGS.items()},
            **{name: fingerprints(generate_metro(MetroConfig(**kwargs))) for name, kwargs in METRO_CONFIGS.items()}}


def main(argv=None):
    """Command line: record or check fingerprints, or run the self-test."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?", choices=("record", "check"))
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--strict", action="store_true", help="check: also fail when a full hash changed")
    args = parser.parse_args(argv)
    if args.self_test:
        a = dict(spaces=[dict(id=0, kind="room", level=0, rect=[0, 0, 1, 1], purpose="x")], portals=[], stairs=[],
                 loop_routes=[], spawn=[0, 0, 0], bounds=[0, 0, 1, 1], boxes=[dict(kind="wall", size=[1], center=[0], level=0)])
        b = json.loads(json.dumps(a))
        b["spaces"][0]["purpose"] = "y"
        b["boxes"].append(dict(kind="furniture", size=[1], center=[0], level=0))
        fa, fb = fingerprints(a), fingerprints(b)
        assert fa["layout"] == fb["layout"] and fa["full"] != fb["full"]
        b["boxes"][0]["center"] = [1]
        assert fingerprints(b)["layout"] != fa["layout"]
        print("baseline self-test ok")
        return 0
    if not args.action or not args.path:
        parser.error("record PATH or check PATH")
    current = compute()
    if args.action == "record":
        with open(args.path, "x") as handle:  # never overwrite a recorded baseline
            json.dump(current, handle, indent=1)
        print(f"recorded {len(current)} configurations in {args.path}")
        return 0
    recorded = json.loads(args.path.read_text())
    failed = False
    for name, prints in recorded.items():
        now = current.get(name)
        layout = "same" if now and now["layout"] == prints["layout"] else "CHANGED"
        full = "same" if now and now["full"] == prints["full"] else "changed"
        failed |= layout == "CHANGED" or (args.strict and full == "changed")
        print(f"{name:28s} layout {layout:8s} full {full}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
