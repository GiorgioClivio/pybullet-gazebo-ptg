"""User settings: rooms, furniture, density, styles, metro and tunnel ranges, from the TOML files in config/.

config/ holds the defaults (building, rooms, furniture, clutter, metro, tunnel .toml). To change them, pass an
override: a folder with any of those files, or one .toml file whose top-level tables are those names,
holding only the keys to change. Tables merge key by key; lists and values replace the default.

    python3 indoor.py --config my_config/          # CLI
    PTG_CONFIG=my_config.toml python3 ...          # any host simulator, read on first use
    settings.use("my_config/")                     # library

Unknown keys, unknown object kinds and inconsistent tables raise ValueError naming the culprit.
"""
from pathlib import Path
import difflib
import hashlib
import json
import os

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

DEFAULTS = Path(__file__).resolve().parent / "config"
FILES = ("building", "rooms", "furniture", "clutter", "metro", "tunnel")
# Tables whose keys are names the user may add (purposes, variants, kinds); all others are fixed schemas.
OPEN = {("rooms", "variants"), ("rooms", "styles"), ("furniture", "groups"), ("furniture", "groups_by_variant"),
        ("furniture", "extras"), ("furniture", "fill", "items"), ("clutter", "first"), ("clutter", "items")}
FAMILIES = ("corporate", "warm", "wayfinding", "lab")
_current = None


def _read(path):
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def defaults():
    """The shipped config/ files, one table per file name."""
    data = {}
    for name in FILES:
        data.update(_read(DEFAULTS / f"{name}.toml"))
    return data


def _merge(base, override, where=()):
    opened = any(where[:i] in OPEN for i in range(len(where) + 1))  # inside a table of user-defined names
    for key, value in override.items():
        here = (*where, key)
        if key not in base and not opened:
            close = difflib.get_close_matches(key, list(base), 1)
            raise ValueError(f"unknown setting {'.'.join(here)}" + (f" (did you mean {close[0]}?)" if close else ""))
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value, here)
        else:
            base[key] = value


def load(path=None):
    """Defaults merged with the override at path (folder or .toml file), validated."""
    data = defaults()
    if path:
        path = Path(path).expanduser()
        if path.is_dir():
            override = {}
            for name in FILES:
                if (path / f"{name}.toml").is_file():
                    override.update(_read(path / f"{name}.toml"))
        elif path.is_file():
            override = _read(path)
        else:
            raise ValueError(f"settings not found: {path}")
        _merge(data, override)
        data["source"] = str(path)
    _validate(data)
    return data


def _validate(s):
    from furniture import PALETTE, _model
    rooms, furniture = s["rooms"], s["furniture"]
    bad = []

    def kinds(value):
        """Every kind in an item, group, list or seeded choice."""
        if isinstance(value, str):
            yield value
        elif isinstance(value, list) and value and isinstance(value[0], str) and len(value) == 4 and \
                all(isinstance(v, (int, float)) for v in value[1:]):
            yield value[0]  # ["kind", dx, dy, turn]
        elif isinstance(value, list):
            for v in value:
                yield from kinds(v)
        elif isinstance(value, dict):  # {any = [group, ...]}
            yield from kinds(value.get("any", []))
    used = set()
    for table in (furniture["groups"], furniture["groups_by_variant"], furniture["extras"], furniture["fill"]["items"],
                  s["clutter"]["items"], s["clutter"]["first"]):
        for value in table.values():
            used.update(kinds(value))
    used.update(furniture["disabled"], furniture["free"])
    for kind in sorted(used):
        try:
            _model(kind, PALETTE[0])
        except ValueError:
            bad.append(f"unknown object kind {kind!r}")
    def group_ok(group):
        return isinstance(group, list) and group and all(isinstance(v, str) or (isinstance(v, list) and _is_item(v)) for v in group)
    for table in (furniture["groups"], furniture["groups_by_variant"]):
        for purpose, groups in table.items():
            for entry in groups:
                for group in (entry.get("any", []) if isinstance(entry, dict) else [entry]):
                    if not group_ok(group):
                        bad.append(f"furniture groups of {purpose!r}: {group!r} is not a list of \"kind\" or [\"kind\", dx, dy, turn]")
    for purpose in rooms["purposes"] + rooms["small_rooms"] + [rooms["largest_room"]["purpose"]] * bool(rooms["largest_room"]["purpose"]):
        if purpose not in furniture["groups"]:
            bad.append(f"room purpose {purpose!r} has no [furniture.groups] entry")
        if purpose not in rooms["variants"]:
            bad.append(f"room purpose {purpose!r} has no [rooms.variants] entry")
    for purpose, rule in rooms["styles"].items():
        for family in kinds(list(rule.values())):
            if family not in FAMILIES:
                bad.append(f"rooms.styles.{purpose}: unknown family {family!r} (use {', '.join(FAMILIES)})")
    for key in furniture["groups_by_variant"]:
        if key.count("/") != 1:
            bad.append(f"furniture.groups_by_variant key {key!r} must be \"purpose/variant\"")
    if "*" not in furniture["extras"] or "*" not in s["clutter"]["items"]:
        bad.append('furniture.extras and clutter.items need a "*" entry')
    from metro import PALETTES
    envelope = s["metro"]["envelope"]
    bad += [f"metro.envelope.palettes: unknown palette {p!r} (use {', '.join(sorted(PALETTES))})"
            for p in envelope["palettes"] if p not in PALETTES]
    bad += [f"metro.envelope.{k} must be [low, high] with low <= high" for k, v in envelope.items()
            if k not in ("car_lengths", "palettes") and isinstance(v, list) and not (len(v) == 2 and v[0] <= v[1])]
    bad += [f"tunnel.envelope.{k} must be [low, high] with 0 < low <= high" for k, v in s["tunnel"]["envelope"].items()
            if not (isinstance(v, list) and len(v) == 2 and 0 < v[0] <= v[1])]
    bad += [f"tunnel.{table}.{k} must be positive" for table in ("rules", "robot") for k, v in s["tunnel"][table].items() if not 0 < v]
    if not 0 < furniture["density"] <= 10:
        bad.append("furniture.density must be in (0, 10]")
    if bad:
        raise ValueError("settings: " + "; ".join(bad))


def current():
    """The active settings: use(path), else PTG_CONFIG, else the defaults (loaded once)."""
    global _current
    if _current is None:
        _current = load(os.environ.get("PTG_CONFIG") or None)
    return _current


def use(path=None):
    """Activate an override (None: the defaults) for the scenes generated from now on."""
    global _current
    _current = load(path)
    return _current


def signature():
    """None with the default settings, else {source, sha256} to record in a scene (reproducibility)."""
    s = current()
    if "source" not in s:
        return None
    clean = {k: v for k, v in s.items() if k != "source"}
    return dict(source=s["source"], sha256=hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest())


def pick(rng, value):
    """An item from a seeded-choice list, or the value itself."""
    return rng.choice(value) if isinstance(value, list) and value and not _is_item(value) else value


def _is_item(value):
    return len(value) == 4 and isinstance(value[0], str) and all(isinstance(v, (int, float)) for v in value[1:])


def item(value):
    """("kind", dx, dy, turn) from "kind" or ["kind", dx, dy, turn]."""
    return (value, 0, 0, 0) if isinstance(value, str) else tuple(value)


def disabled(value):
    return value in current()["furniture"]["disabled"]


if __name__ == "__main__":
    import sys
    s = load(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"settings ok: {s.get('source', 'defaults')}")
