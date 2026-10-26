"""Seeded metro station explored top-down: a street-level concourse, stairs and an optional spiral ramp
down to the platform level with tracks and tunnels. Metric, Z up, static collision for every visible part.

The scene uses indoor.generate's schema (boxes/spaces/portals/stairs/spawn/bounds/objects), so
indoor.load_pybullet and viewer.Viewer load it unchanged; rotated parts carry an xyzw "orientation".
Levels: 1 = concourse at street level (floor z = 0, spawn); 0 = platform level (floor z = -depth).
Only the loader, the renders and the GUI need PyBullet.

    python3 metro.py --seed 7
    python3 metro.py --seed 7 --headless --export x.json --render x.png
    python3 metro.py --seed 7 --headless --figures out/metro
"""
from dataclasses import asdict, dataclass
from pathlib import Path
import argparse
import json
import math
import random
import sys
import time
from types import SimpleNamespace

import settings
from styles import COLORS, PALETTE, material_spec

# Track and structure. Sources and verification status: README.md, "Metro station".
RAIL = dict(height=.172, head=.072, head_depth=.051, foot=.150, foot_depth=.012, web=.0165)  # 60E1 (UIC 60)
SLEEPER = dict(length=2.60, width=.30, height=.22)  # B70 monoblock 2600 x 300 mm; height is a design value
SIDE_TRACK_SPACING = 4.4   # Track centres between side platforms, with a column row between the tracks.
WALL_CLEAR = 2.2           # Track centreline to the station-box wall on the far side of the track.
BORE_AXIS, LINING = 2.0, .30   # Single-track bore: axis above top of rail; segment lining thickness.
BOX_WALKWAY, BOX_SOFFIT = 1.0, 4.6  # Double-track box tunnel: walkway width; roof soffit above top of rail.
WALKWAY_MIN = .61          # NFPA 130 trainway walkway, 24 in at the walking surface.
HEADROOM = 2.03            # 80 in (IBC 1011.3; NFPA 130 walkway clear height).
ROOM_HEIGHT, DECK, WALL, PASSAGE = 3.0, .25, .30, 4.0
CEILING_SKIN = .005         # As indoor.CEILING_SKIN: finish under the slab between levels.
# Physical module of each metro finish = its texture period (512 px per period, >= 341 px/m):
# 1.2 m formwork panels, 1.5 m segment rings. TEXTURE_REV is part of the cache key of metro images.
PERIODS, TEXTURE_REV = dict(concrete=1.2, lining=1.5), 2
C = dict(concrete=[.66, .66, .64, 1], dark=[.42, .43, .43, 1], terrazzo=[.78, .76, .72, 1], tile=[.88, .87, .82, 1],
         accent=[.31, .45, .47, 1], tactile=[.80, .67, .27, 1], rail=[.33, .33, .34, 1], head=[.63, .64, .65, 1],
         sleeper=[.58, .57, .55, 1], ballast=[.55, .53, .50, 1], steel=[.52, .54, .55, 1], room=[.86, .84, .79, 1],
         trim=[.24, .26, .27, 1], buffer=[.56, .38, .30, 1])
# Seeded wall palettes (glazed tile, accent band, terrazzo floor): restrained colour-coded schemes as many lines use
# to tell stations apart. Design values, not measured from a specific network.
PALETTES = dict(white_teal=dict(tile=[.88, .87, .82, 1], accent=[.31, .45, .47, 1], terrazzo=[.78, .76, .72, 1]),
                cream_red=dict(tile=[.90, .85, .74, 1], accent=[.60, .24, .20, 1], terrazzo=[.76, .72, .66, 1]),
                blue=dict(tile=[.66, .75, .83, 1], accent=[.17, .26, .46, 1], terrazzo=[.74, .75, .75, 1]),
                green=dict(tile=[.72, .81, .71, 1], accent=[.20, .40, .28, 1], terrazzo=[.76, .76, .71, 1]),
                ochre=dict(tile=[.87, .76, .52, 1], accent=[.36, .30, .26, 1], terrazzo=[.72, .68, .62, 1]),
                grey_amber=dict(tile=[.72, .73, .74, 1], accent=[.84, .60, .20, 1], terrazzo=[.67, .67, .66, 1]))
NAMES = ("NORTH GATE", "RIVERSIDE", "OLD MARKET", "CIVIC CENTRE", "LIBRARY", "EAST PARK", "FOUNDRY",
         "OBSERVATORY", "HARBOUR", "STADIUM", "GARDENS", "MUSEUM")
# Room contents in placement order (large first); "@name" is wall-mounted at WALL_MOUNT[name]. Items that do not
# fit the room (walls, door lane, other items) are skipped. Composites (workstation, ...) are built in _furnish.
ROOMS = {"ticket_office": ("workstation", "workstation", "filing_cabinet", "cabinet", "locker", "bin", "plant",
                           "@noticeboard", "@wall_clock"),
         "kiosk": ("kitchen_counter", "kitchen_counter", "refrigerator", "refrigerator", "bookcase", "vending_machine",
                   "crate", "boxes"),
         "staff_room": ("table_set", "kitchenette", "sofa", "locker", "locker", "plant", "bin", "@lab_tv", "@noticeboard",
                        "@wall_clock"),
         "toilet": ("cubicle", "cubicle", "cubicle", "washbasin", "washbasin", "bin"),
         "storage": ("shelving", "shelving", "shelving", "boxes", "crate", "boxes"),
         "first_aid": ("bed", "lab_cupboard", "washbasin", "desk", "chair", "cabinet", "bin"),
         "equipment": ("equipment_rack", "equipment_rack", "equipment_rack", "cabinet", "workbench", "toolbox", "crate"),
         "office": ("workstation", "workstation", "filing_cabinet", "filing_cabinet", "locker", "plant", "bin", "@noticeboard",
                    "@wall_clock"),
         "control_room": ("console_station", "console_station", "equipment_rack", "equipment_rack", "filing_cabinet", "bin",
                          "@lab_tv", "@wall_clock"),
         "cleaner": ("cleaning_cart", "shelving", "washbasin", "bucket", "boxes")}
WALL_MOUNT = dict(noticeboard=1.9, wall_clock=2.45, lab_tv=0.)  # Centre height (lab_tv: its own 1.0-2.15 m).
SIGNS = dict(ticket_office="TICKETS", kiosk="KIOSK", staff_room="STAFF ONLY", toilet="TOILETS", storage="STORE",
             first_aid="FIRST AID", equipment="EQUIPMENT", office="OFFICE", cleaner="CLEANER", control_room="CONTROL ROOM")


@dataclass(frozen=True)
class MetroConfig:
    """Fields defaulting to None are drawn from the seed (_envelope); explicit arguments are always kept."""
    seed: int = 7
    layout: str = "auto"            # "island" | "side" | "auto" (seeded).
    spiral_ramp: bool = None        # Terminus: tracks end at buffer stops; helical ramp shaft at the west end.
    platform_length: float = None
    island_width: float = None
    side_width: float = None
    platform_height: float = 1.10   # Platform surface above top of rail.
    edge_offset: float = 1.50       # Track centreline to platform edge.
    tactile_width: float = .61      # ADA 705.2: 24 in detectable warning along the edge.
    gauge: float = 1.435
    sleeper_spacing: float = .60
    track_bed: str = None           # "concrete" slab track | "ballast".
    depth: float = None             # Concourse floor to platform floor (stair/ramp rise).
    slab: float = .8                # Concourse slab = station-box roof.
    concourse_height: float = None
    room_depth: float = None
    column_spacing: float = None
    column_diameter: float = 1.15   # Three 1.2 m formwork panels around: seamless concrete texture.
    stair_width: float = None       # Clear width between balustrades.
    riser: float = .16              # Maximum; the actual riser is depth / ceil(depth / riser).
    tread: float = .30
    flight_rise: float = 3.6        # Maximum vertical rise of one flight.
    landing: float = 2.0
    tunnel_length: float = 30.0
    tunnel_diameter: float = 5.8    # Internal diameter of a single-track bore.
    ramp_slope: float = 1 / 12      # Running slope at the INNER edge of the clear width.
    ramp_width: float = 1.8
    ramp_run_rise: float = .76      # ADA 405.6: 30 in maximum rise per run.
    ramp_landing: float = 1.525     # ADA 405.7.3: 60 in landings.
    roof: bool = False
    furnished: bool = True
    palette: str = None             # Key of PALETTES.

    def __post_init__(self):
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        _envelope(self)
        numbers = [v for k, v in asdict(self).items() if k not in
                   ("seed", "layout", "track_bed", "spiral_ramp", "roof", "furnished", "palette")]
        if not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in numbers):
            raise ValueError("Dimensions must be positive finite numbers")
        if any(type(v) is not bool for v in (self.spiral_ramp, self.roof, self.furnished)):
            raise ValueError("spiral_ramp, roof and furnished must be booleans")
        if self.layout not in ("auto", "island", "side") or self.track_bed not in ("concrete", "ballast"):
            raise ValueError("layout must be auto/island/side and track_bed concrete/ballast")
        if self.palette not in PALETTES:
            raise ValueError(f"palette must be one of {sorted(PALETTES)}")
        clear = min(self.island_width / 2 - self.stair_width / 2, self.side_width - self.stair_width) - .12 - self.tactile_width
        walkway = math.sqrt(max(0, (self.tunnel_diameter / 2) ** 2 - (self.platform_height - BORE_AXIS) ** 2)) - self.edge_offset
        crown = BORE_AXIS + self.tunnel_diameter / 2 + LINING - self.platform_height
        for ok, message in (
                (.9 <= self.platform_height <= 1.25, "platform_height must be 0.90-1.25 m above top of rail (high-floor metro)"),
                (1. <= self.gauge <= 1.676, "gauge must be 1.000-1.676 m"),
                (self.gauge / 2 + .6 <= self.edge_offset <= 1.8, "edge_offset must leave room for the car: gauge/2 + 0.6 to 1.8 m"),
                (.10 <= self.rise <= .178, "Stair riser must be 0.10-0.178 m (ADA 504 / IBC: 7 in maximum)"),
                (self.tread >= .279, "Stair tread must be at least 0.279 m (11 in)"),
                (3 * self.rise <= self.flight_rise <= 3.658, "flight_rise must be 3 risers to 3.658 m (IBC 1011.8: 12 ft)"),
                (self.stair_width >= 1.12, "stair_width must be at least 1.12 m (NFPA 130: 44 in)"),
                (self.landing >= min(self.stair_width, 1.22), "landing must be at least min(stair width, 1.22 m)"),
                (clear >= 1.5, "Platforms need 1.5 m clear between the stair balustrade and the tactile strip"),
                (self.tactile_width <= 1.2, "tactile_width must be at most 1.2 m"),
                (self.platform_length <= 250, "platform_length must be at most 250 m"),
                (self.platform_length >= 2 * self.stair_run + 25, f"platform_length must be >= {2 * self.stair_run + 25:.1f} m for two stairs"),
                (self.depth - self.slab >= max(3., crown + .1, BOX_SOFFIT - self.platform_height + .6),
                 "depth - slab must clear the tunnel crowns (and 3 m) above the platform"),
                (4.8 <= self.tunnel_diameter <= 7.5, "tunnel_diameter must be 4.8-7.5 m"),
                (walkway >= WALKWAY_MIN, "Bore too small for a 0.61 m walkway at platform level (NFPA 130)"),
                (5 <= self.tunnel_length <= 200, "tunnel_length must be 5-200 m"),
                (self.concourse_height >= ROOM_HEIGHT + .5, "concourse_height must be at least 3.5 m"),
                (self.room_depth >= 3, "room_depth must be at least 3 m"),
                (.4 <= self.column_diameter <= 2 and self.column_spacing >= 5, "Columns: 0.4-2.0 m diameter, >= 5 m spacing"),
                (.4 <= self.sleeper_spacing <= 1., "sleeper_spacing must be 0.4-1.0 m"),
                (self.ramp_slope <= 1 / 12 + 1e-9 and self.ramp_slope >= .02, "ramp_slope must be 1:50 to 1:12 (ADA 405.2)"),
                (self.ramp_run_rise <= .76, "ramp_run_rise must be at most 0.76 m (ADA 405.6)"),
                (self.ramp_landing >= 1.525, "ramp_landing must be at least 1.525 m (ADA 405.7.3)"),
                (.915 <= self.ramp_width <= 4, "ramp_width must be 0.915-4 m (ADA 405.5)")):
            if not ok:
                raise ValueError(message)
        if self.spiral_ramp:
            _helix_plan(self)  # Raises if no radius gives the headroom.

    @property
    def risers(self):
        return math.ceil(self.depth / self.riser - 1e-9)

    @property
    def rise(self):
        return self.depth / self.risers

    @property
    def flights(self):
        per = max(1, math.floor(self.flight_rise / self.rise + 1e-9))
        count = math.ceil(self.risers / per)
        return [self.risers // count + (i < self.risers % count) for i in range(count)]

    @property
    def stair_run(self):
        return sum(r - 1 for r in self.flights) * self.tread + (len(self.flights) - 1) * self.landing


def _envelope(c):
    """Seeded station envelope: fills the MetroConfig fields left at None, in place, and keeps explicit ones.

    Every value is drawn in a fixed order whether used or not, so an explicit field never shifts the others.
    Ranges (design values, not checked against one standard): trains of 4-8 cars of
    15-18 m plus a 5 m stopping margin, never shorter than two stairs need; column grid 7.5-10.5 m; concourse
    4.5-7 m high; platform 6-12 m below the concourse; island 8-12 m and side platforms 5.5-7.5 m wide (always
    leaving 1.5 m beside the stair); stairs 2.4-3.4 m clear; side rooms 4-6.5 m deep; 30 % ballasted track beds;
    a spiral ramp in half of the stations.
    """
    rng, e = random.Random(f"{c.seed}:envelope"), settings.current()["metro"]["envelope"]  # config/metro.toml
    cars, car = rng.randint(*e["cars"]), rng.choice(e["car_lengths"])
    draw = dict(depth=round(rng.uniform(*e["depth"]), 1), concourse_height=round(rng.uniform(*e["concourse_height"]), 1),
                column_spacing=round(rng.uniform(*e["column_spacing"]), 1), room_depth=round(rng.uniform(*e["room_depth"]), 1),
                stair_width=round(rng.uniform(*e["stair_width"]), 1), island_width=round(rng.uniform(*e["island_width"]), 1),
                side_width=round(rng.uniform(*e["side_width"]), 1),
                track_bed="ballast" if rng.random() < e["ballast_probability"] else "concrete",
                spiral_ramp=rng.random() < e["ramp_probability"], palette=rng.choice(sorted(e["palettes"])))

    def fill(name, value):
        if getattr(c, name) is None:
            object.__setattr__(c, name, value)
    for name in ("depth", "stair_width", "concourse_height", "column_spacing", "room_depth", "track_bed", "spiral_ramp",
                 "palette"):
        fill(name, draw[name])
    sw = c.stair_width if type(c.stair_width) in (int, float) else 3.
    fill("island_width", max(draw["island_width"], math.ceil((sw + 4.5) * 10) / 10))   # 1.5 m clear each side.
    fill("side_width", max(draw["side_width"], math.ceil((sw + 2.3) * 10) / 10))
    ok = all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in (c.depth, c.riser, c.tread, c.flight_rise, c.landing))
    # Capped at 140 m (8 x 18 m trains would need 149 m) to keep the concourse storey under the building's
    # 200,000-triangle budget; lift the cap when furniture gets LODs.
    fill("platform_length", max(min(cars * car + e["stopping_margin"], e["max_platform"]),
                                float(math.ceil(2 * c.stair_run + 25.)) if ok else 0.))


def _colors(palette):
    """Metro tints with the scene's wall palette."""
    return dict(C, **PALETTES[palette])


def _quat(roll=0., pitch=0., yaw=0.):
    """xyzw quaternion of Rz(yaw) Ry(pitch) Rx(roll): PyBullet's getQuaternionFromEuler convention."""
    cr, sr, cp, sp, cy, sy = (f(a / 2) for a in (roll, pitch, yaw) for f in (math.cos, math.sin))
    return [sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy]


def _subtract(rect, holes):
    """Axis-aligned rectangles covering rect minus the holes."""
    holes = [h for h in holes if h[0] < rect[2] and h[2] > rect[0] and h[1] < rect[3] and h[3] > rect[1]]
    xs = sorted({rect[0], rect[2], *(v for h in holes for v in (h[0], h[2]) if rect[0] < v < rect[2])})
    out = []
    for a, b in zip(xs, xs[1:]):
        y = rect[1]
        for lo, hi in sorted((h[1], h[3]) for h in holes if h[0] < (a + b) / 2 < h[2]):
            if lo > y:
                out.append([a, y, b, lo])
            y = max(y, hi)
        if y < rect[3]:
            out.append([a, y, b, rect[3]])
    return [r for r in out if r[2] - r[0] > 1e-6 and r[3] - r[1] > 1e-6]


def _helix_plan(c):
    """Spiral ramp: radius and turns such that every runs/landings window of one turn, and the top bridge over the
    last turn, leave HEADROOM.

    The slope limit applies at the inner edge of the clear width, so the centreline is gentler.
    The total angle is snapped to whole quarter turns, so the top exit is axis-aligned.
    """
    w, rise = c.ramp_width, c.depth
    runs = math.ceil(rise / c.ramp_run_rise - 1e-9)
    per_run = rise / runs

    def layout(radius):
        slope = c.ramp_slope * (radius - w / 2) / radius
        run = per_run / slope
        return slope, run, runs * (run + c.ramp_landing)

    def height(s, slope, run):
        k, rem = divmod(s, run + c.ramp_landing)
        return min(rise, k * per_run + min(rem, run) * slope)

    def headroom(radius):
        slope, run, length = layout(radius)
        turn = 2 * math.pi * radius
        reach = length + w / 2 + .1      # The top bridge (DECK thick, at `rise`) overhangs the turn below by its half width.
        if reach <= turn:
            return math.inf
        steps = int((reach - turn) / .05) + 1
        return min(height(i * .05 + turn, slope, run) - height(i * .05, slope, run) for i in range(steps)) - DECK

    radius = w / 2 + 1.5
    while headroom(radius) < HEADROOM:
        radius += .1
        if radius > 30:
            raise ValueError("No spiral ramp radius up to 30 m gives 2.03 m headroom; disable spiral_ramp")
    quarters = int(layout(radius)[2] / radius / (math.pi / 2))
    while quarters >= 1:
        snapped = radius
        for _ in range(60):
            snapped = layout(snapped)[2] / (quarters * math.pi / 2)
        if headroom(snapped) >= HEADROOM:
            break
        quarters -= 1
    else:
        raise ValueError("Spiral ramp cannot be built with these dimensions")
    slope, run, length = layout(snapped)
    return dict(radius=snapped, width=w, quarter_turns=quarters, turns=quarters / 4, runs=runs, rise_per_run=per_run,
                run=run, landing=c.ramp_landing, slope_centre=slope, slope_inner=c.ramp_slope, length=length,
                headroom=headroom(snapped), shaft_half=snapped + w / 2 + .5)


METRO_MODELS = ("bench", "ticket_gate", "ticket_machine", "name_board", "line_map", "noticeboard", "hanging_sign",
                "departure_board", "totem", "clock", "buffer_stop", "barrier", "vending_machine", "locker", "filing_cabinet",
                "shelving", "console", "equipment_rack", "cctv", "ad_panel", "ad_billboard", "cubicle", "mirror",
                "departure_screen", "wall_clock", "map_stand", "kiosk_stand", "column_collar", "planter_box", "ad_totem",
                "departure_totem", "info_desk")
PRODUCTS = ([.80, .22, .18, 1], [.93, .76, .20, 1], [.20, .45, .70, 1], [.25, .58, .32, 1], [.90, .90, .86, 1])


def _metro_model_bench(name, label, aspect, top, color, box, face, rods):
    """Parts of bench."""
    length = 1.8
    for y in (-.13, 0, .13):
        box(0, y, .43, length, .12, .035, "wood")
    for z in (.62, .76):
        box(0, -.21, z, length, .035, .11, "wood")
    for x in (-length / 2 + .15, length / 2 - .15):  # Steel frames: plain boxes (a 5 cm bevel is not visible).
        box(x, .15, .205, .05, .05, .41, color=C["trim"], shape=None)
        box(x, -.2, .42, .05, .05, .84, color=C["trim"], shape=None)
        box(x, -.02, .395, .05, .42, .04, color=C["trim"], shape=None)


def _metro_model_ticket_gate(name, label, aspect, top, color, box, face, rods):
    """Parts of ticket_gate."""
    box(0, 0, .5, 1.6, .28, 1.0, "plastic", [.62, .64, .63, 1])
    box(0, 0, 1.01, 1.62, .30, .02, color=C["trim"])
    box(.62, 0, 1.045, .2, .2, .05, "plastic", C["accent"])
    for y in (-.141, .141):
        box(-.1, y, .75, .9, .004, .12, "plastic", C["accent"], shape=None)


def _metro_model_ticket_machine(name, label, aspect, top, color, box, face, rods):
    """Parts of ticket_machine."""
    box(0, 0, .9, .9, .5, 1.8, "plastic", [.55, .58, .58, 1])
    box(0, .26, 1.0, .32, .02, .16, color=C["trim"])
    box(0, .255, 1.32, .58, .01, .46, color=C["trim"], shape=None)
    face(0, .26, 1.32, .52, .40, 0, "line_map", "TICKETS")
    face(0, .251, 1.67, .80, .16, 0, "wide_sign", "TICKETS")


def _metro_model_name_board(name, label, aspect, top, color, box, face, rods):
    """Parts of name_board, line_map, noticeboard."""
    w, h = {"name_board": (3.0, .6), "line_map": (1.3, .95), "noticeboard": (.9, .9)}[name]
    box(0, 0, 0, w, .05, h, color=C["trim"])
    face(0, .026, 0, w - .06, h - .06, 0, {"name_board": "wide_sign", "line_map": "line_map", "noticeboard": "notice"}[name])


def _metro_model_hanging_sign(name, label, aspect, top, color, box, face, rods):
    """Parts of hanging_sign, departure_board."""
    w, h, z = (1.6, .35, 2.675) if name == "hanging_sign" else (1.3, .38, 2.69)
    rods((-w / 2 + .15, w / 2 - .15), z + h / 2)
    box(0, 0, z, w, .06, h, color=C["trim"])
    style = "wide_sign" if name == "hanging_sign" else "departures"
    face(0, .031, z, w - .04, h - .04, 0, style)
    face(0, -.031, z, w - .04, h - .04, 2, style)


def _metro_model_totem(name, label, aspect, top, color, box, face, rods):
    """Parts of totem."""
    box(0, 0, 1.2, .12, .12, 2.4, color=C["trim"])
    box(0, 0, 2.6, 1.4, .06, .5, color=C["trim"])
    face(0, .031, 2.6, 1.36, .46, 0, "wide_sign")
    face(0, -.031, 2.6, 1.36, .46, 2, "wide_sign")


def _metro_model_clock(name, label, aspect, top, color, box, face, rods):
    """Parts of clock."""
    rods((0,), 2.95)
    box(0, 0, 2.7, .46, .09, .46, color=C["trim"], shape="lathe", axis=1, profile=[[1, -.5], [1, .5]])
    box(0, 0, 2.7, .40, .10, .40, "paper", [.92, .91, .86, 1], shape="lathe", axis=1, profile=[[1, -.5], [1, .5]])
    for side in (-1, 1):
        for i in range(12):
            a = i * math.pi / 6
            box(.165 * math.sin(a), side * .0515, 2.7 + .165 * math.cos(a), .014, .003, .03 if i % 3 else .045, shape=None)
        box(0, side * .0525, 2.74, .012, .003, .1, shape=None)
        box(.05, side * .0525, 2.7, .11, .003, .012, shape=None)


def _metro_model_buffer_stop(name, label, aspect, top, color, box, face, rods):
    """Parts of buffer_stop."""
    for y in (-.75, .75):
        box(0, y, .7, .22, .22, 1.4, color=C["buffer"])
        box(.3, y, 1.05, .42, .34, .34, color=[.20, .21, .21, 1], shape="lathe", axis=0)
    box(0, 0, 1.05, .26, 1.9, .3, color=C["buffer"])
    box(-.9, 0, .45, 1.6, .14, .14, color=C["buffer"])


def _metro_model_barrier(name, label, aspect, top, color, box, face, rods):
    """Parts of barrier."""
    for z, h in ((1.03, .05), (.55, .04), (.15, .04)):
        box(0, 0, z, aspect, .05, h, color=C["steel"], shape=None)
    posts = math.ceil(aspect / 1.2)
    for k in range(posts + 1):
        box(-aspect / 2 + .03 + (aspect - .06) * k / posts, 0, .53, .06, .06, 1.06, color=C["trim"])


def _metro_model_vending_machine(name, label, aspect, top, color, box, face, rods):
    """Parts of vending_machine."""
    box(0, 0, .925, .9, .8, 1.85, "plastic", color or [.62, .16, .14, 1])
    box(-.1, .4015, 1.05, .62, .003, 1.3, "plastic", [.10, .11, .12, 1], shape=None)
    for row in range(5):
        for k in range(3):
            box(-.31 + .21 * k, .408, .55 + .24 * row, .17, .01, .15, "plastic", PRODUCTS[(row + 2 * k) % 5], shape=None)
    box(.32, .403, 1.2, .16, .006, .36, color=C["trim"], shape=None)
    box(.32, .407, 1.33, .12, .003, .07, "plastic", [.30, .62, .55, 1], shape=None)
    box(-.1, .403, .22, .55, .006, .16, "plastic", [.15, .15, .16, 1], shape=None)


def _metro_model_locker(name, label, aspect, top, color, box, face, rods):
    """Parts of locker."""
    tint = color or [.45, .52, .58, 1]
    box(0, 0, .925, .9, .5, 1.85, "metal", tint)
    for k in range(3):
        for z in (.5, 1.38):
            box(-.3 + .3 * k, .2525, z, .28, .005, .8, "metal", [v * .92 for v in tint[:3]] + [1], shape=None)
            box(-.2 + .3 * k, .2575, z + .18, .02, .01, .1, color=C["trim"], shape=None)


def _metro_model_filing_cabinet(name, label, aspect, top, color, box, face, rods):
    """Parts of filing_cabinet."""
    box(0, 0, .66, .47, .62, 1.32, "metal", [.60, .62, .62, 1])
    for i in range(4):
        box(0, .3125, .17 + .32 * i, .43, .005, .29, "metal", [.55, .57, .57, 1], shape=None)
        box(0, .3175, .25 + .32 * i, .14, .01, .025, color=C["steel"], shape=None)


def _metro_model_shelving(name, label, aspect, top, color, box, face, rods):
    """Parts of shelving."""
    for x in (-.58, .58):
        for y in (-.23, .23):
            box(x, y, 1., .04, .04, 2., color=C["steel"], shape=None)
    for i in range(4):
        z = .12 + .6 * i
        box(0, 0, z, 1.2, .5, .03, color=C["steel"], shape=None)
        for j, x in enumerate((-.36, .02, .38)):
            h = (.22, .30, .26)[(i + j) % 3]
            if (i + 2 * j) % 4 != 3 and z + h < 1.95:
                box(x, 0, z + .015 + h / 2, .32, .4, h, "cardboard", shape=None)


def _metro_model_console(name, label, aspect, top, color, box, face, rods):
    """Parts of console."""
    box(0, 0, .37, 2.4, .8, .74, "metal", [.36, .38, .40, 1])
    box(0, .05, .76, 2.44, .9, .04, "plastic", [.20, .21, .22, 1])
    for x in (-.8, 0., .8):
        box(x, -.28, 1.12, .62, .05, .38, color=C["trim"], shape=None)
        face(x, -.254, 1.12, .58, .34, 0, "screen")
        box(x, -.28, .85, .06, .04, .14, color=C["trim"], shape=None)
    box(0, .2, .79, .5, .16, .02, "plastic", [.10, .11, .12, 1], shape=None)


def _metro_model_equipment_rack(name, label, aspect, top, color, box, face, rods):
    """Parts of equipment_rack."""
    box(0, 0, 1., .8, .6, 2., "metal", [.30, .32, .34, 1])
    box(0, .3025, 1., .74, .005, 1.92, "metal", [.36, .38, .40, 1], shape=None)
    for i in range(6):
        box(0, .306, .3 + .25 * i, .6, .003, .03, color=C["trim"], shape=None)
    for k, tint in enumerate(([.2, .8, .3, 1], [.2, .8, .3, 1], [.9, .6, .1, 1], [.2, .5, .9, 1])):
        box(-.28 + .05 * k, .306, 1.85, .025, .003, .025, "plastic", tint, shape=None)


def _metro_model_cctv(name, label, aspect, top, color, box, face, rods):
    """Parts of cctv."""
    box(0, .005, .05, .1, .01, .16, color=C["trim"], shape=None)
    box(0, .07, .05, .04, .12, .04, color=C["trim"], shape=None)
    box(0, .22, 0, .11, .22, .1, "plastic", [.88, .88, .86, 1])
    box(0, .34, -.005, .07, .02, .07, "plastic", [.08, .08, .09, 1], shape="lathe", axis=1)


def _metro_model_ad_panel(name, label, aspect, top, color, box, face, rods):
    """Parts of ad_panel, ad_billboard."""
    w, h = (1.2, 1.75) if name == "ad_panel" else (3.0, 1.5)
    box(0, 0, 0, w, .07, h, color=C["trim"])
    face(0, .036, 0, w - .1, h - .1, 0, "art")


def _metro_model_cubicle(name, label, aspect, top, color, box, face, rods):
    """Parts of cubicle."""
    tint = color or [.55, .60, .62, 1]
    for x in (-.45, .45):
        box(x, 0, 1.075, .03, 1.55, 1.85, "plastic", tint)
    box(-.31, .76, 1.075, .25, .03, 1.85, "plastic", tint)
    box(.405, .45, 1.075, .03, .58, 1.75, "plastic", [v * .9 for v in tint[:3]] + [1])
    box(0, .76, 2.02, .93, .04, .04, color=C["steel"], shape=None)


def _metro_model_mirror(name, label, aspect, top, color, box, face, rods):
    """Parts of mirror."""
    box(0, 0, 0, .6, .02, .8, "metal", [.80, .84, .86, 1])


def _metro_model_departure_screen(name, label, aspect, top, color, box, face, rods):
    """Parts of departure_screen."""
    box(0, 0, 0, 1.3, .08, .42, color=C["trim"])
    face(0, .041, 0, 1.24, .36, 0, "departures")


def _metro_model_wall_clock(name, label, aspect, top, color, box, face, rods):
    """Parts of wall_clock."""
    for y, w, material, tint in ((.03, .40, "metal", C["trim"]), (.035, .34, "paper", [.92, .91, .86, 1])):
        box(0, y, 0, w, .06, w, material, tint, shape="lathe", axis=1, profile=[[1, -.5], [1, .5]])
    for i in range(12):
        a = i * math.pi / 6
        box(.14 * math.sin(a), .067, .14 * math.cos(a), .012, .003, .026 if i % 3 else .04, shape=None)
    box(0, .068, .035, .01, .003, .09, shape=None)
    box(.04, .068, 0, .09, .003, .01, shape=None)


def _metro_model_map_stand(name, label, aspect, top, color, box, face, rods):
    """Parts of map_stand."""
    box(0, 0, .05, 1.2, .3, .1, color=C["trim"])
    for x in (-.55, .55):
        box(x, 0, .95, .06, .06, 1.9, color=C["trim"])
    box(0, 0, 1.25, 1.04, .05, 1.1, color=C["trim"])
    face(0, .026, 1.25, 1.0, 1.06, 0, "line_map")
    face(0, -.026, 1.25, 1.0, 1.06, 2, "line_map")


def _metro_model_kiosk_stand(name, label, aspect, top, color, box, face, rods):
    """Parts of kiosk_stand."""
    tint = color or [.30, .42, .36, 1]
    box(0, -.1, .55, 2.4, 1.2, 1.1, "wood")
    box(0, 0, 1.125, 2.5, 1.42, .05, "plastic", [.85, .84, .80, 1])
    box(0, -.66, 1.88, 2.4, .08, 1.45, "plastic", tint)
    for x in (-1.16, 1.16):
        box(x, -.66, 1.88, .08, .08, 1.45, color=C["trim"], shape=None)
    box(0, 0, 2.66, 2.6, 1.6, .12, "plastic", tint)
    face(0, .8, 2.66, 2.3, .1, 0, "wide_sign")
    box(-.7, -.3, 1.33, .4, .35, .36, color=C["trim"])
    for k in range(3):
        box(.2 + .3 * k, .3, 1.2, .24, .3, .1, "paper", PRODUCTS[k], shape=None)


def _metro_model_planter_box(name, label, aspect, top, color, box, face, rods):
    """Parts of planter_box."""
    box(0, 0, .225, aspect, .5, .45, "plastic", color or [.36, .38, .37, 1])
    box(0, 0, .44, aspect - .06, .44, .02, "cardboard", [.30, .24, .18, 1], shape=None)
    n = max(2, round(aspect / .9))
    for k in range(n):
        box(-aspect / 2 + aspect * (k + .5) / n, 0, .62, min(.75, aspect / n), .44, .42 + .1 * (k % 2), "leaf", shape="ellipsoid")


def _metro_model_ad_totem(name, label, aspect, top, color, box, face, rods):
    """Parts of ad_totem."""
    box(0, 0, .05, 1.3, .4, .1, color=C["trim"])
    box(0, 0, 1.25, 1.3, .12, 1.9, color=C["trim"])
    face(0, .0605, 1.25, 1.2, 1.75, 0, "art")
    face(0, -.0605, 1.25, 1.2, 1.75, 2, "art")


def _metro_model_departure_totem(name, label, aspect, top, color, box, face, rods):
    """Parts of departure_totem."""
    box(0, 0, .05, .6, .4, .1, color=C["trim"])
    box(0, 0, 1.0, .1, .1, 1.9, color=C["trim"], shape=None)
    box(0, 0, 2.1, 1.3, .1, .5, color=C["trim"])
    face(0, .0505, 2.1, 1.24, .44, 0, "departures")
    face(0, -.0505, 2.1, 1.24, .44, 2, "departures")


def _metro_model_info_desk(name, label, aspect, top, color, box, face, rods):
    """Parts of info_desk."""
    box(0, 0, .52, 2.0, .7, 1.04, "wood")
    box(0, .02, 1.065, 2.1, .78, .05, "plastic", [.85, .84, .80, 1])
    box(0, .3505, .62, 1.6, .003, .3, "plastic", color or C["accent"], shape=None)
    face(0, .3525, .62, 1.5, .24, 0, "wide_sign", "INFORMATION")
    box(.5, -.12, 1.27, .5, .04, .32, color=C["trim"], shape=None)
    face(.5, -.1415, 1.27, .46, .28, 2, "screen")
    box(-.85, -.3, 1.7, .06, .06, 1.25, color=C["trim"], shape=None)
    box(-.85, -.3, 2.45, .5, .06, .5, color=C["trim"])
    face(-.85, -.2695, 2.45, .46, .46, 0, "wide_sign", "i")
    face(-.85, -.3305, 2.45, .46, .46, 2, "wide_sign", "i")


def _metro_model_column_collar(name, label, aspect, top, color, box, face, rods):
    """Parts of column_collar."""
    w = aspect + .1
    box(0, 0, 0, w, w, .36, color=C["trim"])
    for facing, text in ((0, label.split("|")[0]), (2, label.split("|")[-1])):
        face(0, (w / 2 + .0005) * (1 if facing == 0 else -1), 0, w - .06, .3, facing, "wide_sign", text)


METRO_KITS = {"bench": _metro_model_bench, "ticket_gate": _metro_model_ticket_gate,
              "ticket_machine": _metro_model_ticket_machine, "name_board": _metro_model_name_board,
              "line_map": _metro_model_name_board, "noticeboard": _metro_model_name_board,
              "hanging_sign": _metro_model_hanging_sign, "departure_board": _metro_model_hanging_sign,
              "totem": _metro_model_totem, "clock": _metro_model_clock, "buffer_stop": _metro_model_buffer_stop,
              "barrier": _metro_model_barrier, "vending_machine": _metro_model_vending_machine,
              "locker": _metro_model_locker, "filing_cabinet": _metro_model_filing_cabinet,
              "shelving": _metro_model_shelving, "console": _metro_model_console,
              "equipment_rack": _metro_model_equipment_rack, "cctv": _metro_model_cctv,
              "ad_panel": _metro_model_ad_panel, "ad_billboard": _metro_model_ad_panel,
              "cubicle": _metro_model_cubicle, "mirror": _metro_model_mirror,
              "departure_screen": _metro_model_departure_screen, "wall_clock": _metro_model_wall_clock,
              "map_stand": _metro_model_map_stand, "kiosk_stand": _metro_model_kiosk_stand,
              "planter_box": _metro_model_planter_box, "ad_totem": _metro_model_ad_totem,
              "departure_totem": _metro_model_departure_totem, "info_desk": _metro_model_info_desk,
              "column_collar": _metro_model_column_collar}


def _metro_model(name, label="", aspect=1., top=4., color=None):
    """Local parts (front +y, back -y, floor z = 0). Hanging models use top = soffit height above the floor.

    Wall-mounted models without a floor (boards, screens, clocks, cameras, adverts) are centred at local z = 0 and
    placed at their mount height. `color` tints the body of vending machines, lockers, cubicles and kiosks.
    """
    parts = []

    def box(x, y, z, w, d, h, material="metal", color=None, shape="bevel", **extra):
        parts.append(dict(center=[x, y, z], size=[w, d, h], material=material, color=color, shape=shape,
                          **({"bevel": min(.008, min(w, d, h) * .2)} if shape == "bevel" else {}), **extra))

    def face(x, y, z, w, h, facing, style, text=label):
        offset = .0005 if facing == 0 else -.0005
        parts.append(dict(center=[x, y + offset, z], size=[w, .001, h], material="paper", color=[1, 1, 1, 1],
                          shape="display", facing=facing,
                          texture=dict(style=style, seed=0, period=1., label=text, aspect=round(w / h, 3))))

    def rods(xs, z0):
        for x in xs:
            box(x, 0, (z0 + top) / 2, .025, .025, top - z0, color=C["trim"], shape=None)

    if name in METRO_KITS:
        METRO_KITS[name](name, label, aspect, top, color, box, face, rods)
    else:
        raise ValueError(f"Unknown metro model: {name}")
    for part in parts:
        if part["shape"] is None:
            del part["shape"]
    return parts


def generate_metro(c=None):
    """Seeded metro station scene (concourse, stairs, ramp, platforms, tracks) in the indoor schema."""
    c = MetroConfig() if c is None else c  # built now, so it sees the active settings
    start = time.perf_counter()
    C = _colors(c.palette)
    rng = random.Random(f"{c.seed}:metro")
    layout = c.layout if c.layout != "auto" else rng.choice(("island", "side"))
    name = rng.choice(NAMES)
    L, e, H, tw, sw = c.platform_length, c.edge_offset, c.concourse_height, c.tactile_width, c.stair_width
    zp = -c.depth
    zr = zp - c.platform_height                  # Top of rail.
    zs = zr - RAIL["height"]                     # Sleeper top = rail foot.
    zb = zs - .15                                # Track bed top; sleepers embedded 7 cm.
    zbase, soffit = zb - .6, -c.slab
    terminus = c.spiral_ramp
    scene = dict(config=dict(asdict(c), floors=2), generator=dict(name="metro_station", version=1), layout=layout,
                 station_name=name, levels=[dict(level=0, name="platform", floor_z=zp), dict(level=1, name="concourse", floor_z=0.)],
                 spaces=[], portals=[], stairs=[], ramps=[], boxes=[], objects=[], clear_paths=[], loop_routes=[],
                 floor_seeds=[c.seed, c.seed + 0x9E3779B97F4A7C15])
    if settings.signature():  # non-default config/ settings: record which (reproducibility)
        scene["settings"] = settings.signature()
    boxes, spaces, portals = scene["boxes"], scene["spaces"], scene["portals"]
    lanes, blocked = {0: [], 1: []}, {0: [], 1: []}

    s = SimpleNamespace(c=c, start=start, C=C, rng=rng, layout=layout, name=name, L=L, e=e, H=H, tw=tw, sw=sw, zp=zp, zr=zr,
                        zs=zs, zb=zb, zbase=zbase, soffit=soffit, terminus=terminus, scene=scene, boxes=boxes, spaces=spaces,
                        portals=portals, lanes=lanes, blocked=blocked,
                        y_door=None, passage=None, direction=None, entry=None, ux=None, uy=None)  # set at a terminus only
    for phase in (_metro_build_helpers, _metro_plan_helpers, _metro_cross_section, _metro_spaces, _metro_concourse,
                  _metro_platform_level, _metro_stairs, _metro_tunnels):
        phase(s)
    if terminus:
        _metro_ramp(s)
        _metro_ramp_bridge(s)
    _metro_concourse_lanes(s)
    _metro_platform_lanes(s)
    _metro_finish(s)
    return scene


def _metro_build_helpers(s):
    """part/block/wall/guard: scene-part helpers bound to this station's boxes and tints."""
    C, boxes, c = s.C, s.boxes, s.c
    def part(kind, size, center, level, material, color, style=None, period=2., element=None, **extra):
        if min(size) <= 1e-6:
            return None
        b = dict(kind=kind, size=[float(v) for v in size], center=[float(v) for v in center], level=level,
                 material=material, color=list(color), **({"element": element} if element else {}), **extra)
        if style:
            b["texture"] = dict(style=style, seed=c.seed, period=PERIODS.get(style, period), label="", rev=TEXTURE_REV)
        if kind == "floor" and "orientation" not in b:
            b["collision_size"] = [b["size"][0] + .002, b["size"][1] + .002, b["size"][2]]
        boxes.append(b)
        return b

    def block(rect, level, z0, z1, kind="floor", style="terrazzo", color=C["terrazzo"], period=1.2, element=None, material="floor"):
        part(kind, (rect[2] - rect[0], rect[3] - rect[1], z1 - z0), ((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2, (z0 + z1) / 2),
             level, material, color, style, period, element)

    def wall(axis, fixed, lo, hi, z0, z1, level, openings=(), t=WALL, style="concrete", color=C["concrete"], element="wall"):
        """Straight wall along X (axis 0) or Y (axis 1); openings (a, b, bottom, top[, glazed])."""
        def segment(a, b, za, zz, glazed=False):
            size, center = [.03 if glazed else t] * 2 + [zz - za], [fixed, fixed, (za + zz) / 2]
            size[axis], center[axis] = b - a, (a + b) / 2
            if glazed:
                part("glass", size, center, level, "glass", COLORS["glass"], element="glazing")
            else:
                part("wall", size, center, level, "wall", color, style, 2.4 if style == "concrete" else 1.2, element)
        x = lo
        for a, b, bottom, top, *glazed in sorted(openings):
            segment(x, a, z0, z1)
            segment(a, b, z0, bottom)
            segment(a, b, top, z1)
            if glazed:
                segment(a, b, bottom, top, True)
            x = b
        segment(x, hi, z0, z1)

    def guard(a, b, height=1.1, level=1, glazed=True):
        """Balustrade between 2D points a and b on floor z (axis-aligned), glass panel + rail or solid trim."""
        (x0, y0, z), (x1, y1, _) = a, b
        axis = 0 if abs(y1 - y0) < 1e-9 else 1
        size = [abs(x1 - x0), .1, height] if axis == 0 else [.1, abs(y1 - y0), height]
        center = [(x0 + x1) / 2, (y0 + y1) / 2, z + height / 2]
        if glazed:  # Railing: posts, mid rail and handrail (TinyRenderer cannot blend glass).
            length = max(size[0], size[1])
            for zz, hh in ((z + height - .03, .06), (z + .5, .04)):
                part("trim", [s if s != .1 else .05 for s in size[:2]] + [hh], center[:2] + [zz], level, "metal", C["steel"],
                     element="handrail")
            for k in range(math.ceil(length / 1.5) + 1):
                f = k / math.ceil(length / 1.5)
                part("trim", [.05, .05, height - .06], [x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, z + (height - .06) / 2], level,
                     "metal", C["steel"], element="railing_post")
        else:
            part("trim", size, center, level, "trim", [.74, .73, .70, 1], "concrete", 2.4, "parapet")
    s.block, s.guard, s.part, s.wall = block, guard, part, wall


def _metro_plan_helpers(s):
    """space/portal/lane: plan helpers bound to this station's scene."""
    lanes, portals, scene, spaces, zp = s.lanes, s.portals, s.scene, s.spaces, s.zp
    def space(kind, rect, level, **extra):
        spaces.append(dict(id=len(spaces), kind=kind, level=level, rect=[float(v) for v in rect],
                           floor_z=0. if level else zp, traversable=kind != "trackway", **extra))
        return spaces[-1]["id"]

    def portal(a, b, center, axis, width, height):
        portals.append(dict(rooms=[a, b], center=[float(v) for v in center], axis=axis, width=float(width), height=float(height)))

    def lane(level, space_id, *points):
        z = 0. if level else zp
        for a, b in zip(points, points[1:]):
            lanes[level].append((a, b))
        scene["clear_paths"].append(dict(room=space_id, width=.9, points=[[*p, z] for p in points]))
    s.lane, s.portal, s.space = lane, portal, space


def _metro_cross_section(s):
    """Platform cross-section, ramp shaft and the seeded stair and concourse extents."""
    L, c, e, layout, rng, sw = s.L, s.c, s.e, s.layout, s.rng, s.sw
    terminus = s.terminus
    # ---- Platform-level cross-section ----
    if layout == "island":
        hw = c.island_width / 2
        tracks = [(hw + e, -1), (-hw - e, 1)]     # (track centre y, platform side relative to the track)
        hb = hw + e + WALL_CLEAR
        platform_rects = [[0, -hw, L, hw]]
        trackways = [[hw - .35, hb], [-hb, -hw + .35]]
    else:
        st = SIDE_TRACK_SPACING / 2
        tracks = [(st, 1), (-st, -1)]
        hb = st + e + c.side_width
        platform_rects = [[0, st + e, L, hb], [0, -hb, L, -st - e]]
        trackways = [[-st - e + .35, st + e - .35]]
    plan = _helix_plan(c) if terminus else None
    hs = plan["shaft_half"] if plan else 0.
    xbox0 = -PASSAGE if terminus else 0.
    sx1 = -PASSAGE - .6                                   # Shaft interior east face.
    sx0, cx = sx1 - 2 * hs, sx1 - hs

    # ---- Stairs: seeded positions; tops face the gateline in the east ----
    run = c.stair_run
    top_b = L - 6 - rng.uniform(0, 3)
    top_a = rng.uniform(8 + run, top_b - run - 8)
    if layout == "island":
        stairs = [(top_a, 0.), (top_b, 0.)]
    else:
        y_s = hb - .02 - (sw / 2 + .08)
        stairs = [(top_b, y_s), (top_a, -y_s)]
    gate_x = max(t for t, _ in stairs) + 4.5
    X1 = gate_x + round(rng.uniform(8., 13.), 1)  # Seeded unpaid hall depth, gateline to street facade.
    X0 = sx0 - 3.5 if terminus else -4.
    Hh = max(hb + (2.5 if layout == "side" else 0), hs + 2.5)
    voids = [[t - run, y - sw / 2 - .12, t, y + sw / 2 + .12] for t, y in stairs]
    hole = [sx0, -hs, sx1, hs] if terminus else None
    s.Hh, s.X0, s.X1, s.cx, s.gate_x, s.hb = Hh, X0, X1, cx, gate_x, hb
    s.hole, s.hs, s.plan, s.platform_rects, s.run = hole, hs, plan, platform_rects, run
    s.stairs, s.sx0, s.sx1, s.tracks, s.trackways, s.voids = stairs, sx0, sx1, tracks, trackways, voids
    s.xbox0 = xbox0


def _metro_spaces(s):
    """Concourse halls, the seeded room strips, platforms and trackways."""
    Hh, L, X0, X1, c, gate_x = s.Hh, s.L, s.X0, s.X1, s.c, s.gate_x
    platform_rects, rng, space, terminus, trackways = s.platform_rects, s.rng, s.space, s.terminus, s.trackways
    # ---- Spaces ----
    unpaid = space("concourse", [gate_x, -Hh, X1, Hh], 1, name="concourse_unpaid")
    paid = space("concourse", [X0, -Hh, gate_x, Hh], 1, name="concourse_paid")
    rd, rooms = c.room_depth, []
    lo = rng.uniform(4.5, 6.5)                   # Seeded room module: widths lo..hi along each strip.
    hi = lo + rng.uniform(2.5, 4.5)
    for strip in (1, -1):
        cuts, x = [X1, gate_x], gate_x
        while x - X0 > hi:
            x -= rng.uniform(lo, min(hi, x - X0 - lo)) if x - X0 >= 2 * lo else (x - X0) / 2
            cuts.append(x)
        cuts.append(X0)
        purposes = ["office", "office", "control_room", "staff_room", "toilet", "storage", "storage", "first_aid", "equipment",
                    "equipment", "cleaner"]
        rng.shuffle(purposes)
        for i, (a, b) in enumerate(zip(cuts[1:], cuts)):
            purpose = ("kiosk" if strip > 0 else "ticket_office") if i == 0 else purposes[(i - 1) % len(purposes)]
            y0, y1 = sorted((strip * Hh, strip * (Hh + rd)))
            ident = space("room", [a, y0, b, y1], 1, purpose=purpose, name=purpose)
            rooms.append(dict(id=ident, strip=strip, rect=[a, y0, b, y1], purpose=purpose))
    platforms = [space("platform", r, 0, name=f"platform_{i + 1}") for i, r in enumerate(platform_rects)]
    for (lo, hi) in trackways:
        space("trackway", [0. if terminus else -c.tunnel_length, lo, L + c.tunnel_length, hi], 0,
              name="trackway", reason="track pit 1.4 m below the platform; no access steps are modelled")
    s.paid, s.platforms, s.rd, s.rooms, s.unpaid = paid, platforms, rd, rooms, unpaid


def _metro_concourse(s):
    """Concourse floor, room walls and doors, facades, roof and void guards."""
    C, H, Hh, X0, X1, block = s.C, s.H, s.Hh, s.X0, s.X1, s.block
    c, gate_x, guard, hole, lane, paid = s.c, s.gate_x, s.guard, s.hole, s.lane, s.paid
    part, portal, rd, rng, rooms, scene = s.part, s.portal, s.rd, s.rng, s.rooms, s.scene
    soffit, stairs, unpaid, voids, wall = s.soffit, s.stairs, s.unpaid, s.voids, s.wall
    # ---- Concourse: floor, walls, rooms, facades, roof ----
    for r in _subtract([X0, -Hh, X1, Hh], voids + ([hole] if hole else [])):
        block(r, 1, soffit, 0., element="concourse_floor")
        # One body has one texture on all faces: a 5 mm skin gives the platform ceiling its own finish.
        block(r, 1, soffit - CEILING_SKIN, soffit, kind="ceiling", style="concrete", color=C["concrete"], period=2.4,
              element="ceiling_skin", material="wall")
    for room in rooms:
        wet = room["purpose"] in ("toilet", "kiosk", "first_aid", "cleaner")
        block(room["rect"], 1, soffit, 0., style="tile" if wet else "terrazzo", period=2. if wet else 1.2,
              color=[.72, .71, .67, 1] if wet else C["terrazzo"], element="room_floor")
    for strip in (1, -1):
        openings, signs = [], []
        for room in (r for r in rooms if r["strip"] == strip):
            a, b = room["rect"][0], room["rect"][2]
            width = 2.4 if room["purpose"] == "kiosk" else 1.0
            door = (a + b) / 2 + rng.uniform(-1, 1) * max(0., (b - a) / 2 - width / 2 - 1.2)
            openings.append((door - width / 2, door + width / 2, 0., 2.1 if width < 2 else 2.4))
            if room["purpose"] == "ticket_office":
                window = door + (1.6 if door + 3 < b else -1.6)
                openings.append((min(window, window + .0) - .55, window + .55, .95, 2.1, True))
                room["window"] = window
            room["door"], room["door_width"] = door, width
            portal(paid if door < gate_x else unpaid, room["id"], [door, strip * Hh, 0.], 0, width, 2.1)
            inside = strip * (Hh + .6)
            lane(1, room["id"], (door, strip * (Hh - 1.4)), (door, strip * Hh), (door, inside),
                 ((a + b) / 2, strip * (Hh + rd / 2)))
            signs.append((room, door))
        wall(0, strip * Hh, X0, X1, 0., H, 1, openings, style="metro_tile", color=C["tile"])
        part("trim", [X1 - X0, .02, .3], [(X0 + X1) / 2, strip * (Hh - WALL / 2 - .01), 3.0], 1, "trim", C["accent"],
             element="accent_band")
        wall(0, strip * (Hh + rd), X0, X1, 0., ROOM_HEIGHT, 1, t=.2, style="plaster", color=C["room"])
        for x in sorted({r["rect"][0] for r in rooms if r["strip"] == strip} | {X1}):
            wall(1, x, *sorted((strip * Hh, strip * (Hh + rd))), 0., ROOM_HEIGHT, 1, t=.15, style="plaster", color=C["room"])
        scene.setdefault("_room_signs", []).extend(signs)
    piers = [(y + .25, y + 4.25, .3, H - .8, True) for y in [-Hh + .25 + 4.5 * k for k in range(int((2 * Hh - .5) / 4.5))]]
    wall(1, X1, -Hh, Hh, 0., H, 1, [o for o in piers if o[1] < Hh - .25], element="facade")
    wall(1, X0, -Hh, Hh, 0., H, 1, element="facade")
    if c.roof:
        block([X0 - WALL / 2, -Hh, X1 + WALL / 2, Hh], 2, H, H + .3, kind="ceiling", style="concrete", color=C["concrete"], period=2.4)
        for strip in (1, -1):
            block([X0, *sorted((strip * Hh, strip * (Hh + rd)))[:1], X1, sorted((strip * Hh, strip * (Hh + rd)))[1]],
                  1, ROOM_HEIGHT, ROOM_HEIGHT + .15, kind="ceiling", style="plaster", color=C["room"], period=2.)
    # Void guards: open only at the stair top (east end).
    for (t, y), v in zip(stairs, voids):
        guard((v[0], v[1] - .05, 0.), (t, v[1] - .05, 0.))
        guard((v[0], v[3] + .05, 0.), (t, v[3] + .05, 0.))
        guard((v[0] - .05, v[1] - .1, 0.), (v[0] - .05, v[3] + .1, 0.))


def _metro_platform_level(s):
    """Platforms, edges, track beds, station-box walls, terminus passage and columns."""
    C, L, block, blocked, c, guard = s.C, s.L, s.block, s.blocked, s.c, s.guard
    hb, hs, layout, part, platform_rects, run = s.hb, s.hs, s.layout, s.part, s.platform_rects, s.run
    soffit, stairs, sx0, sx1, terminus, trackways = s.soffit, s.stairs, s.sx0, s.sx1, s.terminus, s.trackways
    tw, wall, xbox0, y_door, zb, zbase = s.tw, s.wall, s.xbox0, s.y_door, s.zb, s.zbase
    zp = s.zp
    # ---- Platform level: box, platforms, track beds, walls ----
    for r in platform_rects:
        body = [r[0], r[1] + (.35 if (layout == "island" or r[1] > 0) else 0), r[2], r[3] - (.35 if (layout == "island" or r[3] < 0) else 0)]
        block(body, 0, zbase, zp, element="platform")
        edge_ys = [(r[3], -1), (r[1], 1)] if layout == "island" else ([(r[1], 1)] if r[1] > 0 else [(r[3], -1)])
        for y, inward in edge_ys:
            block([r[0], min(y, y + inward * .35), r[2], max(y, y + inward * .35)], 0, zp - .25, zp, style="concrete",
                  color=[.74, .73, .70, 1], period=2.4, element="platform_coping")
            block([r[0], min(y, y + inward * tw), r[2], max(y, y + inward * tw)], 0, zp, zp + .006, style="tactile",
                  color=C["tactile"], period=.6, element="tactile_strip", material="plastic")
    bed_style, bed_color = ("ballast", C["ballast"]) if c.track_bed == "ballast" else ("concrete", C["concrete"])
    for lo, hi in trackways:
        block([0. if terminus else 0., lo, L, hi], 0, zbase, zb, style=bed_style, color=bed_color, period=1. if bed_style == "ballast" else 2.4,
              element="track_bed")
    for side in (1, -1):
        wall(0, side * (hb + .3), xbox0 - .6, L + .6, zbase, soffit, 0, t=.6, style="metro_tile", color=C["tile"], element="station_wall")
        part("trim", [L - xbox0, .02, .3], [(L + xbox0) / 2, side * (hb - .01), zp + 2.9], 0, "trim", C["accent"], element="accent_band")
    if terminus:
        block([-PASSAGE, -hb, 0., hb], 0, zbase, zp, element="passage_floor")
        for lo, hi in trackways:
            guard((-.05, lo, zp), (-.05, hi, zp), level=0)
        y_door = -1.5
        span = max(hb, hs) + .6
        wall(1, -PASSAGE - .3, -span, span, zbase, soffit, 0, [(y_door - .9, y_door + .9, zp, zp + 2.4)], t=.6, element="shaft_wall")
        for side in (1, -1):
            wall(0, side * (hs + .3), sx0 - .6, sx1, zbase, soffit, 0, t=.6, element="shaft_wall")
        wall(1, sx0 - .3, -hs - .6, hs + .6, zbase, soffit, 0, t=.6, element="shaft_wall")
        block([sx0, -hs, sx1, hs], 0, zbase, zp, element="shaft_floor")
    # Platform columns.
    d_col = min(c.column_diameter, .8)
    for k in range(int(L / c.column_spacing) + 1):
        x = 4.5 + k * c.column_spacing
        # Island: clear of the stair and of its bottom lane, which turns 1.6 m west of the bottom (0.6 m to the shaft).
        if x > L - 4.5 or any(t - run - 2.6 < x < t + 1.5 for t, _ in stairs if layout == "island"):
            continue
        z0 = zp if layout == "island" else zb
        part("wall", [d_col, d_col, soffit - z0], [x, 0., (z0 + soffit) / 2], 0, "wall", C["concrete"], "concrete", 2.4,
             "column", shape="lathe", profile=[[1, -.5], [1, .5]])
        blocked[0].append([x - d_col / 2, -d_col / 2, x + d_col / 2, d_col / 2])
    s.bed_color, s.bed_style, s.y_door = bed_color, bed_style, y_door


def _metro_stairs(s):
    """Stair flights with landings, handrails and posts; records each stair."""
    C, blocked, c, paid, part, platforms = s.C, s.blocked, s.c, s.paid, s.part, s.platforms
    run, scene, spaces, stairs, sw, voids = s.run, s.scene, s.spaces, s.stairs, s.sw, s.voids
    zp = s.zp
    # ---- Stairs ----
    for (t, y), v in zip(stairs, voids):
        lower = next(i for i in platforms if spaces[i]["rect"][1] - 1e-6 <= y <= spaces[i]["rect"][3] + 1e-6)
        x, z = t, 0.
        width = sw + .16
        for k, count in enumerate(c.flights):
            x_f, z_f = x, z
            for _ in range(count - 1):
                z -= c.rise
                part("stairs", [c.tread, width, z - zp], [x - c.tread / 2, y, (z + zp) / 2], 0, "stairs", C["terrazzo"],
                     "terrazzo", 1.2, "stair_tread")
                x -= c.tread
            z -= c.rise
            length = math.hypot(x_f - x, z_f - (z + c.rise))
            pitch = -math.atan2(c.rise, c.tread)
            posts = max(1, math.ceil((x_f - x) / 1.5))
            for side in (1, -1):
                yb = y + side * (sw / 2 + .05)
                for lift, thick in ((.9, .05), (.45, .035)):  # Pitched handrail and mid rail along the nosing line.
                    part("trim", [length, thick, thick], [(x_f + x) / 2, yb, (z_f + z + c.rise) / 2 + lift], 0, "metal",
                         C["steel"], element="stair_handrail", orientation=_quat(pitch=pitch))
                for j in range(posts + 1):
                    xp = x_f - (x_f - x) * j / posts
                    zn = z_f - (x_f - xp) * c.rise / c.tread
                    part("trim", [.045, .045, .9 + c.rise], [xp, yb, zn + (.9 - c.rise) / 2], 0, "metal", C["steel"],
                         element="stair_post")
            if k < len(c.flights) - 1:
                part("stairs", [c.landing, width, z - zp], [x - c.landing / 2, y, (z + zp) / 2], 0, "stairs", C["terrazzo"],
                     "terrazzo", 1.2, "stair_landing")
                for side in (1, -1):
                    for lift, thick in ((.9, .05), (.45, .035)):
                        part("trim", [c.landing, thick, thick], [x - c.landing / 2, y + side * (sw / 2 + .05), z + lift], 0, "metal",
                             C["steel"], element="stair_handrail")
                x -= c.landing
        bottom = x
        blocked[0].append([bottom - .3, y - width / 2, t, y + width / 2])
        blocked[1].append(v)
        scene["stairs"].append(dict(lower=lower, upper=paid, upper_level=1, kind="straight",
                                    start=[bottom - .5, y, zp], end=[t + .5, y, 0.], top=[t, y, 0.], bottom=[bottom, y, zp],
                                    risers=c.risers, rise=c.rise, tread=c.tread, width=sw, flights=c.flights,
                                    landing=c.landing, run=run, pitch_deg=round(math.degrees(math.atan2(c.rise, c.tread)), 2)))


def _metro_headwall(s, x0, x1, holes):
    """Wall across the box at x0..x1 with circular ("c", y, z, r) / rectangular ("r", y0, y1, z0, z1) holes."""
    C, hb, part, soffit, zbase = s.C, s.hb, s.part, s.soffit, s.zbase
    y0, y1, z0, z1 = -hb - .6, hb + .6, zbase, soffit
    cuts = {z0, z1}
    for h in holes:
        if h[0] == "c":
            cuts.update(min(z1, max(z0, h[2] + h[3] * k / 10)) for k in range(-10, 11))
        else:
            cuts.update((min(z1, max(z0, h[3])), min(z1, max(z0, h[4]))))
    cuts = sorted(cuts)
    rows = []
    for lo, hi in zip(cuts, cuts[1:]):
        gaps = []
        for h in holes:
            if h[0] == "c":
                d = 0. if lo <= h[2] <= hi else min(abs(lo - h[2]), abs(hi - h[2]))
                if d < h[3]:
                    half = math.sqrt(h[3] ** 2 - d ** 2)
                    gaps.append((h[1] - half, h[1] + half))
            elif lo < h[4] and hi > h[3]:
                gaps.append((h[1], h[2]))
        pieces = [(r[1], r[3]) for r in _subtract([0, y0, 1, y1], [[0, a, 1, b] for a, b in gaps])]
        if rows and rows[-1][2] == pieces:
            rows[-1][1] = hi
        else:
            rows.append([lo, hi, pieces])
    for lo, hi, pieces in rows:
        for a, b in pieces:
            part("wall", [x1 - x0, b - a, hi - lo], [(x0 + x1) / 2, (a + b) / 2, (lo + hi) / 2], 0, "wall",
                 C["concrete"], "concrete", 2.4, "headwall")


def _metro_track(s, y, xa, xb, far):
    """Sleepers, running rails, conductor rail and insulators of one track."""
    C, c, part, zr, zs = s.C, s.c, s.part, s.zr, s.zs
    n = int((xb - xa) / c.sleeper_spacing)
    for i in range(n):
        x = xa + (i + .5) * (xb - xa) / n
        part("track", [SLEEPER["width"], SLEEPER["length"], SLEEPER["height"]], [x, y, zs - SLEEPER["height"] / 2], 0,
             "wall", C["sleeper"], "concrete", 1., "sleeper")
    length, xm = xb - xa, (xa + xb) / 2
    for side in (1, -1):
        yr = y + side * (c.gauge / 2 + RAIL["head"] / 2)
        web = RAIL["height"] - RAIL["head_depth"] - RAIL["foot_depth"]
        part("track", [length, RAIL["foot"], RAIL["foot_depth"]], [xm, yr, zs + RAIL["foot_depth"] / 2], 0, "metal", C["rail"], element="rail")
        part("track", [length, RAIL["web"], web], [xm, yr, zs + RAIL["foot_depth"] + web / 2], 0, "metal", C["rail"], element="rail")
        part("track", [length, RAIL["head"], RAIL["head_depth"]], [xm, yr, zr - RAIL["head_depth"] / 2], 0, "metal", C["head"], element="rail")
    y3 = y + far * 1.2                                     # Conductor rail on the side away from the platform.
    part("track", [length, .08, .09], [xm, y3, zr + .005], 0, "metal", C["steel"], element="conductor_rail")
    for k in range(int(length / 4)):
        part("track", [.1, .1, zr - .04 - zs], [xa + 2 + 4 * k, y3, (zs + zr - .04) / 2], 0, "ceramic", [.70, .66, .55, 1],
             element="insulator", shape="lathe", profile=[[1, -.5], [.7, .1], [1, .5]])


def _metro_tunnel_island(s, sign, xf, xa, xb, far_x, wa, wb):
    """Bored single-track tunnels (island layout); yields (platform, walkway, y_walk, y_track), returns headwall holes."""
    C, R, bed_color, bed_style, block, e = s.C, s.R, s.bed_color, s.bed_style, s.block, s.e
    part, platforms, portal, space, spaces, tracks = s.part, s.platforms, s.portal, s.space, s.spaces, s.tracks
    za, zb, zp = s.za, s.zb, s.zp
    holes = []
    for yt, toward in tracks:
        holes.append(("c", yt, za, R))
        for i in range(24):
            phi = 2 * math.pi * i / 24
            if za + R * math.cos(phi) < zb - .3:
                continue
            rr = R + LINING / 2
            part("wall", [xb - xa + .6, 2 * (R + LINING) * math.tan(math.pi / 24), LINING],
                 [(xa + xb) / 2 - sign * .3, yt + rr * math.sin(phi), za + rr * math.cos(phi)], 0, "wall", C["concrete"],
                 "lining", 3., "tunnel_lining", orientation=_quat(roll=-phi))
        half_b = math.sqrt((R + LINING) ** 2 - (zb - za) ** 2)
        block([xa - (sign > 0) * .6, yt - half_b, xb + (sign < 0) * .6, yt + half_b], 0, za - R - LINING, zb,
              style=bed_style, color=bed_color, period=2.4, element="tunnel_invert")
        half_p = math.sqrt(R ** 2 - (zp - za) ** 2)
        y_in, y_out = yt + toward * e, yt + toward * (half_p + .05)
        walk = [min(y_in, y_out), max(y_in, y_out)]
        block([wa, walk[0], wb, walk[1]], 0, zb, zp, style="concrete", color=C["concrete"], period=2.4, element="walkway")
        block([wa, min(y_in, y_in + toward * .1), wb, max(y_in, y_in + toward * .1)], 0, zp, zp + .004,
              color=C["tactile"], style=None, element="walkway_edge_line", material="plastic")
        part("trim", [xb - xa, .35, .08], [(xa + xb) / 2, yt - toward * (R - .3), za + .4], 0, "trim", C["steel"],
             element="cable_tray")
        part("wall", [.5, 2 * (R + LINING), 2 * (R + LINING)], [far_x + sign * .25, yt, za], 0, "wall", C["concrete"],
             "concrete", 2.4, "tunnel_end_bulkhead")
        y_walk = yt + toward * (e + (half_p - e) / 2)
        ident = space("walkway", [wa, walk[0], wb, walk[1]], 0, name="tunnel_walkway",
                      clear_width=round(half_p - e, 3), end="east" if sign > 0 else "west")
        plat = next(i for i in platforms if spaces[i]["rect"][1] - 1e-6 <= y_walk <= spaces[i]["rect"][3] + 1e-6)
        portal(plat, ident, [xf, y_walk, zp], 1, half_p - e, HEADROOM)
        yield plat, ident, y_walk, yt
    return holes


def _metro_tunnel_box(s, sign, xf, xa, xb, far_x, wa, wb):
    """Cut-and-cover double-track box (side layout); yields (platform, walkway, y_walk, y_track), returns headwall holes."""
    C, bed_color, bed_style, block, e, part = s.C, s.bed_color, s.bed_style, s.block, s.e, s.part
    platforms, portal, space, st, wall, zb = s.platforms, s.portal, s.space, s.st, s.wall, s.zb
    zbase, zp, zr = s.zbase, s.zp, s.zr
    wi = st + e + BOX_WALKWAY
    zt = zr + BOX_SOFFIT
    holes = [("r", -wi, wi, zbase, zt)]
    for side in (1, -1):
        wall(0, side * (wi + .3), xa, xb, zbase, zt + .5, 0, t=.6, element="tunnel_wall")
    block([xa, -wi - .6, xb, wi + .6], 0, zt, zt + .5, kind="ceiling", style="concrete", color=C["concrete"], period=2.4)
    block([wa, -st - e, wb, st + e], 0, zbase, zb, style=bed_style, color=bed_color, period=2.4, element="track_bed")
    part("wall", [.5, 2 * wi + 1.2, zt + .5 - zbase], [far_x + sign * .25, 0., (zt + .5 + zbase) / 2], 0, "wall",
         C["concrete"], "concrete", 2.4, "tunnel_end_bulkhead")
    for side in (1, -1):
        walk = sorted((side * (st + e), side * wi))
        block([wa, walk[0], wb, walk[1]], 0, zbase, zp, style="concrete", color=C["concrete"], period=2.4, element="walkway")
        y_walk = side * (st + e + BOX_WALKWAY / 2)
        ident = space("walkway", [wa, walk[0], wb, walk[1]], 0, name="tunnel_walkway", clear_width=BOX_WALKWAY,
                      end="east" if sign > 0 else "west")
        plat = platforms[0 if side > 0 else 1]
        portal(plat, ident, [xf, y_walk, zp], 1, BOX_WALKWAY, zt - zp)
        yield plat, ident, y_walk, side * st
    return holes


def _metro_ramp(s):
    """Terminus: cross passage, ramp shaft and the helical ramp deck with parapets."""
    C, c, cx, hb, hs, part = s.C, s.c, s.cx, s.hb, s.hs, s.part
    plan, platforms, portal, soffit, space, spaces = s.plan, s.platforms, s.portal, s.soffit, s.space, s.spaces
    sx0, sx1, y_door, zp = s.sx0, s.sx1, s.y_door, s.zp
    passage = space("corridor", [-PASSAGE, -hb, 0., hb], 0, name="cross_passage")
    shaft = space("ramp_shaft", [sx0, -hs, sx1, hs], 0, name="ramp_shaft")
    for plat in platforms:
        r = spaces[plat]["rect"]
        portal(passage, plat, [0., (r[1] + r[3]) / 2, zp], 1, r[3] - r[1], soffit - zp)
    portal(shaft, passage, [-PASSAGE - .3, y_door, zp], 1, 1.8, 2.4)
    Rh, w = plan["radius"], plan["width"]
    rate = plan["quarter_turns"] * math.pi / 2 / plan["length"]
    period = plan["run"] + plan["landing"]

    def height(s):
        k, rem = divmod(s, period)
        return zp + min(c.depth, k * plan["rise_per_run"] + min(rem, plan["run"]) * plan["slope_centre"])
    theta_top = plan["quarter_turns"] * math.pi / 2
    direction = (round(math.cos(theta_top)), round(math.sin(theta_top)))
    bounds_s = sorted({0., plan["length"], *(k * period + d for k in range(plan["runs"]) for d in (plan["run"], period))})
    bounds_s = [s for s in bounds_s if s <= plan["length"] + 1e-9]
    path = []
    for s0, s1 in zip(bounds_s, bounds_s[1:]):
        n = math.ceil((s1 - s0) / .8)
        for i in range(n):
            sa, sb = s0 + (s1 - s0) * i / n, s0 + (s1 - s0) * (i + 1) / n
            ta, tb = sa * rate, sb * rate
            tm, zt = (ta + tb) / 2, (height(sa) + height(sb)) / 2
            pitch = -math.atan2(height(sb) - height(sa), Rh * (tb - ta))
            rot = _quat(pitch=pitch, yaw=tm + math.pi / 2)
            chord = lambda r: 2 * r * math.sin((tb - ta) / 2) + .03
            thick = zt - zp + .05 if zt - zp < HEADROOM + DECK else DECK
            part("stairs", [chord(Rh + w / 2 + .1), w + .2, thick],
                 [cx + Rh * math.cos(tm), Rh * math.sin(tm), zt - thick / 2], 0, "stairs", C["terrazzo"], "terrazzo", 1.2,
                 "ramp_deck", orientation=rot)
            for rad, skip in ((Rh - w / 2 - .05, False), (Rh + w / 2 + .05, tm > theta_top - (w / 2 + .3) / Rh)):
                if not skip:
                    part("trim", [chord(rad), .1, 1.07], [cx + rad * math.cos(tm), rad * math.sin(tm), zt + .535], 0, "trim",
                         [.74, .73, .70, 1], "concrete", 2.4, "ramp_parapet", orientation=rot)
            path.append([cx + Rh * math.cos(tm), Rh * math.sin(tm), zt])
    s.Rh, s.direction, s.passage, s.path, s.shaft, s.w = Rh, direction, passage, path, shaft, w


def _metro_ramp_bridge(s):
    """Terminus: bridge from the ramp top to the concourse, shaft guards, ramp record."""
    C, Rh, blocked, cx, direction, guard = s.C, s.Rh, s.blocked, s.cx, s.direction, s.guard
    hole, hs, lane, paid, part, path = s.hole, s.hs, s.lane, s.paid, s.part, s.path
    plan, scene, shaft, sx0, sx1, w = s.plan, s.scene, s.shaft, s.sx0, s.sx1, s.w
    y_door, zp = s.y_door, s.zp
    # Bridge from the top landing to the concourse edge (axis-aligned, along `direction`).
    ux, uy = direction
    tx, ty = -uy, ux                                         # Tangent direction at the top.
    r0, r1 = Rh - w / 2 - .1, hs + .05
    mid = (r0 + r1) / 2
    half = w / 2 + .1
    sx, sy = (r1 - r0) if ux else 2 * half, (r1 - r0) if uy else 2 * half
    part("stairs", [sx, sy, DECK], [cx + ux * mid, uy * mid, -DECK / 2], 0, "stairs", C["terrazzo"], "terrazzo", 1.2, "ramp_bridge")
    for t_off, ra in ((half - .05, r0), (-(half - .05), Rh + w / 2 + .1)):
        a = (cx + ux * ra + tx * t_off, uy * ra + ty * t_off, 0.)
        b = (cx + ux * r1 + tx * t_off, uy * r1 + ty * t_off, 0.)
        guard(a, b, level=0, glazed=False)
    a = (cx + ux * (Rh - w / 2 - .05), uy * (Rh - w / 2 - .05), 0.)
    guard(a, (a[0] + tx * half, a[1] + ty * half, 0.), level=0, glazed=False)
    # Concourse guards around the shaft hole, open where the bridge lands.
    entry = (cx + ux * hs, uy * hs)
    corners = [(sx0, -hs), (sx1, -hs), (sx1, hs), (sx0, hs), (sx0, -hs)]
    for (ax, ay), (bx, by) in zip(corners, corners[1:]):
        out = (0 if ax != bx else (.05 if ax == sx1 else -.05), 0 if ay != by else (.05 if ay > 0 else -.05))
        segs = [((ax, ay), (bx, by))]
        on_edge = abs((ax if ax == bx else ay) - (entry[0] if ax == bx else entry[1])) < 1e-6
        if on_edge:
            k = 1 if ax == bx else 0
            lo, hi = sorted(((ay, by) if k else (ax, bx)))
            gap = (entry[k] - half, entry[k] + half)
            segs = [tuple((ax if k else v, v if k else ay) for v in pair) for pair in ((lo, gap[0]), (gap[1], hi))]
        for p0, p1 in segs:
            guard((p0[0] + out[0], p0[1] + out[1], 0.), (p1[0] + out[0], p1[1] + out[1], 0.))
    scene["ramps"].append(dict(kind="spiral", lower=shaft, upper=paid, upper_level=1, centre=[cx, 0., zp],
                               bottom=[cx + Rh, 0., zp], top=[cx + ux * hs, uy * hs, 0.], points=path,
                               **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in plan.items()}))
    # Lanes: bottom of the helix -> door -> passage -> platforms; concourse -> bridge.
    lane(0, shaft, (cx + Rh, -.3), (cx + Rh, y_door), (sx1 - .2, y_door))
    scene["clear_paths"].append(dict(room=shaft, width=w, points=path, kind="ramp_centreline"))
    blocked[1].append(hole)
    s.entry, s.ux, s.uy = entry, ux, uy


def _metro_concourse_lanes(s):
    """Clear paths on the concourse: spawn, gateline, stairs and ramp."""
    X1, direction, entry, gate_x, hs, lane = s.X1, s.direction, s.entry, s.gate_x, s.hs, s.lane
    layout, paid, run, stairs, sw, sx1 = s.layout, s.paid, s.run, s.stairs, s.sw, s.sx1
    terminus, unpaid, ux, uy = s.terminus, s.unpaid, s.ux, s.uy
    # ---- Lanes: concourse ----
    spawn = (X1 - 3., 0.)
    aisle = (gate_x + 1.6, 0.), (gate_x - 1.6, 0.)
    y_spine = -(sw / 2 + .12 + 1.6) if layout == "island" else 0.
    west = (sx1 + 1.6) if terminus else min(t - run for t, _ in stairs) - 1.
    lane(1, unpaid, spawn, aisle[0], aisle[1])
    lane(1, paid, aisle[1], (gate_x - 1.6, y_spine), (west, y_spine))
    for t, y in stairs:
        lane(1, paid, (t + 1.6, y_spine), (t + 1.6, y), (t, y))
    if terminus:
        ex, ey = entry
        out = (ex + ux * 1.6, ey + uy * 1.6)
        p0 = (sx1 + 1.6, y_spine)
        route = {(1, 0): [p0, (sx1 + 1.6, ey), (ex, ey)],
                 (0, 1): [p0, (sx1 + 1.6, out[1]), (ex, out[1]), (ex, ey)],
                 (0, -1): [p0, (sx1 + 1.6, out[1]), (ex, out[1]), (ex, ey)],
                 (-1, 0): [p0, (sx1 + 1.6, hs + 1.6), (out[0], hs + 1.6), (out[0], ey), (ex, ey)]}[direction]
        lane(1, paid, *route)
    s.spawn = spawn


def _metro_platform_lanes(s):
    """Clear paths on the platforms: tunnel walkways, passage and stair bottoms."""
    L, c, lane, layout, passage, platforms = s.L, s.c, s.lane, s.layout, s.passage, s.platforms
    run, spaces, stairs, sx1, terminus, tw = s.run, s.spaces, s.stairs, s.sx1, s.terminus, s.tw
    walk_links, y_door = s.walk_links, s.y_door
    # ---- Lanes: platform level ----
    for plat in platforms:
        r = spaces[plat]["rect"]
        edges = [r[3], r[1]] if layout == "island" else [r[1] if r[1] > 0 else r[3]]
        for y_edge in edges:
            inward = 1 if (r[1] + r[3]) / 2 > y_edge else -1
            y_l = y_edge + inward * (tw + .55)
            links = [l for l in walk_links if l[1] == plat and abs(l[3] - y_l) < 1.5]
            east = next(l for l in links if l[0] > 0)
            points = [(L - 2., y_l), (L - .3, east[3]), (L + c.tunnel_length - 1.5, east[3])]
            if terminus:
                points = [(-PASSAGE + 1., y_door if layout == "island" else y_l), (-PASSAGE + 1., y_l), (1., y_l)] + points
                lane(0, passage, (sx1 - .2, y_door), (-PASSAGE + 1., y_door))
            else:
                wl = next(l for l in links if l[0] < 0)
                points = [(-c.tunnel_length + 1.5, wl[3]), (.3, wl[3]), (2., y_l)] + points
            lane(0, plat, *points)
            for t, y in stairs:
                bottom = t - run
                if r[1] <= y <= r[3]:
                    # Starts 5 cm off the lowest tread: a sample exactly on its riser face is ambiguous.
                    lane(0, plat, (bottom - .05, y), (bottom - 1.6, y), (bottom - 1.6, y_l))


def _metro_finish(s):
    """Furniture, columns, bounds, style, coplanar gaps, semantics and statistics."""
    H, Hh, L, X0, X1, blocked = s.H, s.Hh, s.L, s.X0, s.X1, s.blocked
    boxes, c, gate_x, hb, lanes, layout = s.boxes, s.c, s.gate_x, s.hb, s.lanes, s.layout
    name, paid, platforms, portals, rng, rooms = s.name, s.paid, s.platforms, s.portals, s.rng, s.rooms
    run, scene, soffit, spaces, spawn, stairs = s.run, s.scene, s.soffit, s.spaces, s.spawn, s.stairs
    start, terminus, tracks, unpaid, walk_links, zb = s.start, s.terminus, s.tracks, s.unpaid, s.walk_links, s.zb
    zp = s.zp
    # ---- Objects ----
    scene["spawn"] = [spawn[0], spawn[1], .55]
    if c.furnished:
        _furnish(scene, c, rng, dict(layout=layout, stairs=stairs, run=run, hb=hb, Hh=Hh, L=L, X0=X0, X1=X1, gate_x=gate_x,
                 zp=zp, zb=zb, soffit=soffit, tracks=tracks, rooms=rooms, unpaid=unpaid, paid=paid, platforms=platforms,
                 lanes=lanes, blocked=blocked, terminus=terminus, name=name, spawn=spawn, H=H, walk_links=walk_links))
    else:
        scene.pop("_room_signs", None)
    _columns(scene, c, dict(X0=X0, X1=X1, Hh=Hh, H=H, gate_x=gate_x, lanes=lanes, blocked=blocked, spawn=spawn, paid=paid,
                            unpaid=unpaid))
    extent = [_extent(b) for b in boxes]
    scene["bounds"] = [min(v[0] for v in extent), min(v[1] for v in extent), max(v[3] for v in extent), max(v[4] for v in extent)]
    scene["z_bounds"] = [min(v[2] for v in extent), max(v[5] for v in extent)]
    scene["style"] = dict(id="metro_station", version=1, units="metres", finish="restrained_semirealistic", radial_segments=12,
                          wall_finish="metro_tile", floor_finishes=["terrazzo", "tactile", "concrete", c.track_bed],
                          texture_version=__import__("surfaces").VERSION)
    from geometry import separate_coplanar, geometry_stats  # 5 mm gap between coplanar faces: no z-fighting
    separate_coplanar(scene)
    _annotate(scene)
    scene["geometry_stats"] = geometry_stats(scene)
    scene["metro_stats"] = dict(parts=len(boxes), objects=len(scene["objects"]), spaces=len(spaces), portals=len(portals),
                                sleepers=sum(b.get("element") == "sleeper" for b in boxes),
                                generation_s=round(time.perf_counter() - start, 3))


def _metro_tunnel(s, sign):
    """Tunnel beyond one platform end (sign +1 east, -1 west) and its headwall; yields the walkway links."""
    xf = s.L if sign > 0 else 0.
    xa, xb = sorted((xf + sign * .6, xf + sign * s.c.tunnel_length))
    far_x = xf + sign * s.c.tunnel_length
    wa, wb = min(xa, xf), max(xb, xf)  # Walkways and beds also run through the headwall thickness.
    build = _metro_tunnel_island if s.layout == "island" else _metro_tunnel_box
    holes = yield from build(s, sign, xf, xa, xb, far_x, wa, wb)
    _metro_headwall(s, *sorted((xf, xf + sign * .6)), holes)


def _metro_tunnels(s):
    """Tunnels at both platform ends (east only at a terminus) and the tracks through station and tunnels."""
    c = s.c
    s.R, s.za, s.st = c.tunnel_diameter / 2, s.zr + BORE_AXIS, SIDE_TRACK_SPACING / 2
    s.walk_links = []
    for sign in ((1,) if s.terminus else (1, -1)):
        s.walk_links.extend((sign, *link) for link in _metro_tunnel(s, sign))
    xt0 = .6 if s.terminus else -c.tunnel_length + .3
    for yt, toward in s.tracks:
        _metro_track(s, yt, xt0, s.L + c.tunnel_length - .3, -toward)


def _extent(b):
    """Axis-aligned envelope [x0, y0, z0, x1, y1, z1] of a part, exact for rotated boxes."""
    half = [s / 2 for s in b["size"]]
    if "orientation" in b:
        x, y, z, w = b["orientation"]
        rows = [(1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
                (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
                (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y))]
        half = [sum(abs(r[k]) * half[k] for k in range(3)) for r in rows]
    return [b["center"][a] - half[a] for a in range(3)] + [b["center"][a] + half[a] for a in range(3)]


def _crosses(rect, a, b, margin):
    from furniture import _crosses as crosses
    return crosses(rect, a, b, margin)


def _overlap(a, b, gap=0.):
    return a[0] < b[2] + gap and a[2] > b[0] - gap and a[1] < b[3] + gap and a[3] > b[1] - gap


def _world(parts, origin, turn=0):
    from details import _world as world
    return world(parts, origin, turn)


def _group(members):
    """One local model from (name, parts, dx, dy, turn[, dz]) members, and its items for the COCO hints."""
    parts, items = [], []
    for name, model, dx, dy, turn, *dz in members:
        parts += _world(model, (dx, dy, dz[0] if dz else 0.), turn)
        items.append(dict(kind=name, offset=[dx, dy], turn=turn))
    return parts, items


def _register(scene, c, parts, name, space, placement, center, turn, items=None):
    boxes, objects = scene["boxes"], scene["objects"]
    ident, indices = len(objects), []
    for p in parts:
        p = dict(p, kind={"floor": "furniture", "wall": "landmark", "hanging": "landmark"}.get(placement, "prop"),
                 level=scene["spaces"][space]["level"], object_id=ident, label=name)
        if p.get("color") is None:
            p.pop("color", None)
        if "texture" in p:
            p["texture"] = dict(p["texture"], seed=c.seed, rev=TEXTURE_REV)
        elif p["material"] != "glass":
            p["texture"] = material_spec(p["material"], c.seed)
            if p["material"] == "screen":
                p["texture"]["seed"] += ident % 4
        indices.append(len(boxes))
        boxes.append(p)
    ext = [_extent(b) for b in (boxes[i] for i in indices)]
    bounds = [min(v[0] for v in ext), min(v[1] for v in ext), max(v[3] for v in ext), max(v[4] for v in ext)]
    objects.append(dict(id=ident, room=space, level=scene["spaces"][space]["level"], kind=name,
                        items=[dict(item, turn=(item["turn"] + turn) % 4) for item in items] if items else
                        [dict(kind=name, offset=[0, 0], turn=turn)], center=list(center), yaw=turn * math.pi / 2,
                        bounds=bounds, z_range=[min(v[2] for v in ext), max(v[5] for v in ext)], parts=indices, placement=placement))


class _Placer:
    """Placement state of one metro furnishing pass: occupied footprints per level, wall spans, placed solids.

    Floor objects never cross a 0.9 m lane; every object is checked in 3D (footprint and height) against those
    already placed, so wall-mounted items never cut into furniture.
    """

    def __init__(self, scene, c, rng, g):
        self.scene, self.c, self.rng, self.g = scene, c, rng, g
        spaces, lanes, blocked = scene["spaces"], g["lanes"], g["blocked"]
        occupied = {0: [r[:] for r in blocked[0]], 1: [r[:] for r in blocked[1]]}
        # Concourse column sites first (0.6 m clear, as _columns asks): furniture never takes a column's place.
        occupied[1] += [[f[0] - .48, f[1] - .48, f[2] + .48, f[3] + .48] for _, _, f in _column_sites(c, g)]
        walls = {0: [], 1: []}
        solids = {0: [], 1: []}                      # (footprint, z0, z1) of every placed object.
        zfloor = {0: g["zp"], 1: 0.}
        self.spaces, self.lanes, self.occupied = spaces, lanes, occupied
        self.walls, self.solids, self.zfloor = walls, solids, zfloor
        self.wc = rng.choice(([.55, .60, .62, 1], [.62, .55, .45, 1], [.40, .47, .55, 1], [.75, .74, .70, 1]))
        self.vend = rng.choice(([.62, .16, .14, 1], [.16, .34, .55, 1], [.20, .45, .28, 1], [.85, .52, .12, 1]))

    def put(self, name, parts, x, y, turn, space, placement="floor", z=None, items=None):
        """Place `parts` at (x, y) if the footprint fits its space and clears lanes, solids and the spawn."""
        c, g, lanes, occupied, scene, solids = self.c, self.g, self.lanes, self.occupied, self.scene, self.solids
        spaces, walls, zfloor = self.spaces, self.walls, self.zfloor
        level = spaces[space]["level"]
        world = _world(parts, (x, y, zfloor[level] if z is None else z), turn)
        ext = [_extent(b) for b in world]
        fp = [min(v[0] for v in ext), min(v[1] for v in ext), max(v[3] for v in ext), max(v[4] for v in ext)]
        z0, z1 = min(v[2] for v in ext), max(v[5] for v in ext)
        r = spaces[space]["rect"]
        if not (r[0] + .02 <= fp[0] and fp[2] <= r[2] - .02 and r[1] + .02 <= fp[1] and fp[3] <= r[3] - .02):
            return False
        if any(_overlap(fp, o, .02) and z0 < o1 and o0 < z1 for o, o0, o1 in solids[level]):
            return False
        if level == 1 and z0 < 2. and _crosses(fp, g["spawn"], g["spawn"], 1.05):  # 1 m clear around the spawn.
            return False
        if placement == "floor":
            if any(_crosses(fp, a, b, .45) for a, b in lanes[level]) or any(_overlap(fp, o, .12) for o in occupied[level]):
                return False
            occupied[level].append(fp)
        elif placement == "wall":
            if any(_overlap(fp, o, .1) for o in walls[level]):
                return False
            walls[level].append(fp)
        solids[level].append((fp, z0, z1))
        _register(scene, c, world, name, space, placement, [x, y, zfloor[level] if z is None else z], turn, items)
        return True

    def catalogue(self, name):
        """A building-catalogue model (furniture.py) in a seeded palette colour."""
        from furniture import _model
        return _model(name, self.rng.choice(PALETTE))

    def model(self, name):
        """(parts, items): a composite of library models, a metro model, or the building catalogue (furniture.py)."""
        catalogue, g, vend, wc = self.catalogue, self.g, self.vend, self.wc
        if name == "workstation":  # Desk with two monitors and a task chair.
            return _group([("lab_desk", catalogue("lab_desk"), 0, 0, 0), ("lab_chair", catalogue("lab_chair"), 0, .66, 2)])
        if name == "console_station":
            return _group([("console", _metro_model("console"), 0, 0, 0)] +
                          [("lab_chair", catalogue("lab_chair"), x, .82, 2) for x in (-.6, .6)])
        if name == "table_set":  # Staff table, two chairs along the front and one at each end.
            return _group([("table", catalogue("table"), 0, 0, 0)] + [("chair", catalogue("chair"), x, .72, 2) for x in (-.4, .4)] +
                          [("chair", catalogue("chair"), side * 1.1, 0, 1 if side > 0 else 3) for side in (1, -1)])
        if name == "kitchenette":  # Two base units, a fridge and a microwave on the worktop.
            return _group([("kitchen_counter", catalogue("kitchen_counter"), x, 0, 0) for x in (-.575, .575)] +
                          [("refrigerator", catalogue("refrigerator"), 1.5, -.025, 0),
                           ("microwave", catalogue("microwave"), -.6, -.05, 0, .8925)])
        if name == "cubicle":
            return _group([("cubicle", _metro_model("cubicle", color=wc), 0, 0, 0), ("toilet", catalogue("toilet"), 0, -.44, 0)])
        if name == "washbasin":
            return _group([("sink", catalogue("sink"), 0, 0, 0), ("mirror", _metro_model("mirror"), 0, -.225, 0, 1.55)])
        if name == "cleaning_cart":
            return _group([("cart", catalogue("cart"), 0, 0, 0), ("bucket", catalogue("bucket"), .56, 0, 0)])
        if name in METRO_MODELS:
            return _metro_model(name, label=g["name"], color=vend if name == "vending_machine" else None), None
        return catalogue(name), None

    def against(self, name, parts, space, turn, lateral, face, z=None, placement="floor", items=None):
        """Back of the model on the wall face (turn: 0 -y wall, 1 +x, 2 +y, 3 -x)."""
        put = self.put
        lb = _world(parts, (0, 0, 0), turn)
        ext = [_extent(b) for b in lb]
        lo = [min(v[a] for v in ext) for a in (0, 1)]
        hi = [max(v[a + 3] for v in ext) for a in (0, 1)]
        if turn % 2 == 0:
            y = face - (lo[1] if turn == 0 else hi[1])
            return put(name, parts, lateral, y, turn, space, placement, z, items)
        x = face - (hi[0] if turn == 1 else lo[0])
        return put(name, parts, x, lateral, turn, space, placement, z, items)


def _furnish(scene, c, rng, g):
    """Objects against walls/columns and on reserved slots; floor objects never cross a 0.9 m lane.

    Every object is also checked in 3D (footprint and height) against those already placed, so wall-mounted items
    never cut into furniture; door and ticket-window spans on the hall walls stay free of wall-mounted items.
    """
    p = _Placer(scene, c, rng, g)
    zp = g["zp"]
    top_p = g["soffit"] - zp
    others = [n for n in NAMES if n != g["name"]]
    rng.shuffle(others)
    _furnish_rooms(p)
    _furnish_concourse(p)
    _entrance(g, rng, p.put, p.against, p.catalogue, others, p.vend)
    _furnish_hall(p, others)
    for i, plat in enumerate(g["platforms"]):  # name boards, benches, bins, hanging signs, clocks, departures
        _furnish_platform(p, i, plat, others, top_p)
    # Buffer stops at the terminus.
    if g["terminus"]:
        for yt, _ in g["tracks"]:
            _register(scene, c, _world(_metro_model("buffer_stop"), (2.2, yt, g["zb"]), 0), "buffer_stop",
                      next(s["id"] for s in scene["spaces"] if s["kind"] == "trackway" and s["rect"][1] <= yt <= s["rect"][3]),
                      "floor", [2.2, yt, g["zb"]], 0)


def _furnish_rooms(p):
    """Room furniture against back and side walls; door signs; door and window spans kept free."""
    Hh = p.g["Hh"]
    against, g, model, rng, scene, walls = p.against, p.g, p.model, p.rng, p.scene, p.walls
    # Rooms: furniture against the back and side walls, clear of the door-to-hub lane.
    for room in g["rooms"]:
        x0, y0, x1, y1 = room["rect"]
        back = 2 if room["strip"] > 0 else 0
        back_face = y1 - .1 if room["strip"] > 0 else y0 + .1
        for item in ROOMS[room["purpose"]]:
            name = item.lstrip("@")
            parts, items = model(name)
            placement, z = ("wall", WALL_MOUNT[name]) if item[0] == "@" else ("floor", None)
            options = [(back, back_face, x0 + .2, x1 - .2), (3, x0 + .08, y0 + .2, y1 - .2), (1, x1 - .08, y0 + .2, y1 - .2)]
            for turn, face, a, b in options:
                if any(against(name, parts, room["id"], turn, a + (b - a) * (k + .5) / 10, face, z, placement, items)
                       for k in rng.sample(range(10), 10)):
                    break
    for room, door in scene.pop("_room_signs", []):
        strip = room["strip"]
        label = SIGNS[room["purpose"]]
        parts = [dict(center=[0, 0, 0], size=[1.1, .04, .3], material="metal", color=C["trim"], shape="bevel", bevel=.006),
                 dict(center=[0, .0205, 0], size=[1.06, .001, .26], material="paper", color=[1, 1, 1, 1], shape="display",
                      facing=0, texture=dict(style="wide_sign", seed=0, period=1., label=label, aspect=round(1.06 / .26, 3)))]
        hall = g["paid"] if door < g["gate_x"] else g["unpaid"]
        against("room_sign", parts, hall, 2 if strip > 0 else 0, door, strip * (Hh - WALL / 2),
                z=2.75 if room["purpose"] == "kiosk" else 2.45, placement="wall")   # Kiosk opening is 2.4 m high.
    for room in g["rooms"]:  # Door and ticket-window spans on the hall walls stay free of wall-mounted items.
        y = room["strip"] * (Hh - WALL / 2)
        for x, half in [(room["door"], room["door_width"] / 2)] + ([(room["window"], .55)] if "window" in room else []):
            walls[1].append([x - half - .1, y - .3, x + half + .1, y + .3])


def _furnish_concourse(p):
    """Ticket machines, plants, benches, maps, totems, name board and the gateline."""
    Hh = p.g["Hh"]
    against, c, catalogue, g, put, rng = p.against, p.c, p.catalogue, p.g, p.put, p.rng
    scene, solids = p.scene, p.solids
    # Concourse: ticket machines, benches, bins, plants, maps, totems, gateline.
    for k in range(4):
        x = g["gate_x"] + 2.5 + 1.2 * k
        against("ticket_machine", _metro_model("ticket_machine"), g["unpaid"], 2, x, Hh - WALL / 2)
    for side in (1, -1):
        put("plant", catalogue("plant"), g["gate_x"] + 1.5, side * (Hh - 1.2), 0, g["unpaid"])
    for k in range(int((g["gate_x"] - g["X0"]) / 11)):
        x = g["X0"] + 6 + 11 * k
        for side in (1, -1):
            if against("bench", _metro_model("bench"), g["paid"], 2 if side > 0 else 0, x, side * (Hh - WALL / 2)):
                put("bin", catalogue("bin"), x + 1.4, side * (Hh - .45), 0, g["paid"])
            against("line_map" if k % 2 else "noticeboard", _metro_model("line_map" if k % 2 else "noticeboard", label=g["name"]),
                    g["paid"], 2 if side > 0 else 0, x + 3.5, side * (Hh - WALL / 2), z=1.6, placement="wall")
    for side in (1, -1):
        y = side * rng.uniform(3.6, min(6., Hh - 2.))
        put("totem", _metro_model("totem", "TO PLATFORMS"), g["gate_x"] + rng.uniform(2.2, 3.5), y, 0, g["unpaid"])
        put("totem", _metro_model("totem", "WAY OUT"), g["gate_x"] - rng.uniform(2.2, 3.5), y, 0, g["paid"])
    put("name_board", _metro_model("name_board", label=g["name"]), g["X1"] - .2, 0., 1, g["unpaid"], "wall", z=g["H"] - .5)
    # Gateline: one 1.0 m wide aisle (robot route) and 3-5 gates (0.6 m aisles) each side, glazed fence to the hall walls.
    ys = [.64 + .88 * k for k in range(rng.randint(3, 5))]
    gx = g["gate_x"]
    for side in (1, -1):
        for y in ys:
            _register(scene, c, _world(_metro_model("ticket_gate"), (gx, side * y, 0.), 0), "ticket_gate", g["paid"], "floor", [gx, side * y, 0.], 0)
        y0 = ys[-1] + .14
        length = Hh - WALL / 2 - y0
        _register(scene, c, _world(_metro_model("barrier", aspect=length), (gx, side * (y0 + length / 2), 0.), 1), "barrier",
                  g["paid"], "floor", [gx, side * (y0 + length / 2), 0.], 1)
    solids[1] += [(o["bounds"], *o["z_range"]) for o in scene["objects"] if o["kind"] in ("ticket_gate", "barrier")]
    scene["portals"].append(dict(rooms=[g["unpaid"], g["paid"]], center=[gx, 0., 0.], axis=1, width=1.0, height=2.5, kind="wide_gate"))


def _furnish_hall(p, others):
    """Vending machines, seating, kiosk, map stands; adverts, screens, clocks and CCTV."""
    Hh = p.g["Hh"]
    gx = p.g["gate_x"]
    against, c, catalogue, g, put, rng = p.against, p.c, p.catalogue, p.g, p.put, p.rng
    vend = p.vend
    # Hall: vending machines, seating clusters between the columns, a kiosk, map stands; on the walls adverts,
    # departure screens, clocks and CCTV. Each is skipped where it would block a lane, a door or another object.
    X0, X1 = g["X0"], g["X1"]
    hall = lambda x: g["paid"] if x < gx else g["unpaid"]
    for x in (gx + 3., gx + 4.1):
        against("vending_machine", _metro_model("vending_machine", color=vend), g["unpaid"], 0, x, -(Hh - WALL / 2))
    against("kiosk_stand", _metro_model("kiosk_stand", rng.choice(("COFFEE", "NEWS", "SNACKS"))), g["unpaid"], 0, gx + 6.4,
            -(Hh - WALL / 2))
    for k in range(int((gx - X0 - 8) / 23)):
        for side in (1, -1):
            x = X0 + 12 + 23 * k + rng.uniform(-2, 2)
            if against("vending_machine", _metro_model("vending_machine", color=vend), g["paid"], 2 if side > 0 else 0, x,
                       side * (Hh - WALL / 2)):
                put("bin", catalogue("bin"), x + .8, side * (Hh - .45), 0, g["paid"])
    cs = c.column_spacing
    for k in range(int((gx - X0) / cs)):
        x = X0 + cs * (k + 1)                    # Mid-bay of the concourse column rows (see _columns).
        y = Hh / 2 if k % 2 else -Hh / 2         # One back-to-back pair per bay, alternating rows.
        if rng.random() < .65 and put("bench", _metro_model("bench"), x, y + .33, 0, g["paid"]) + put(
                "bench", _metro_model("bench"), x, y - .33, 2, g["paid"]):
            put("bin", catalogue("bin"), x + 1.4, y, 0, g["paid"])
            if k % 4 == 0:                       # Planters are the costliest model (about 930 triangles).
                put("plant", catalogue("plant"), x - 1.5, y, 0, g["paid"])
    for x, y in ((gx - 4.5, Hh - 2.5), (gx - 4.5, -(Hh - 2.5)), (gx - 12, Hh - 2.5), (gx - 12, -(Hh - 2.5))):
        put("map_stand", _metro_model("map_stand", label=g["name"]), x, y, 1, g["paid"])
    for side in (1, -1):
        face = side * (Hh - WALL / 2)
        turn = 2 if side > 0 else 0
        for k, x in enumerate(np_range(X0 + 3 + rng.uniform(0, 3), X1 - 2, 6.5)):
            against("ad_panel", _metro_model("ad_panel", f"AD {k % 4}"), hall(x), turn, x, face, z=1.75, placement="wall")
        for x in (gx - 2.4, gx - 2.4 - 30):
            against("departure_screen", _metro_model("departure_screen", "|".join(others[:3])), hall(x), turn, x, face, z=2.55,
                    placement="wall")
        against("wall_clock", _metro_model("wall_clock"), hall(gx + 1.5), turn, gx + 1.5, face, z=2.5, placement="wall")
        for x in np_range(X0 + 5, X1 - 2, 16):
            against("cctv", _metro_model("cctv"), hall(x), turn, x, face, z=3.6, placement="wall")


def _furnish_platform(p, i, plat, others, top_p):
    """Benches, bins, wall boards, adverts, CCTV and hanging signs of one platform."""
    zp, hb, L = p.g["zp"], p.g["hb"], p.g["L"]
    against, c, catalogue, g, put, spaces = p.against, p.c, p.catalogue, p.g, p.put, p.spaces
    vend = p.vend
    r = spaces[plat]["rect"]
    if g["layout"] == "island":
        for k in range(int(L / c.column_spacing)):
            x = 4.5 + (k + .5) * c.column_spacing
            for side, turn in ((1, 0), (-1, 2)):
                if put("bench", _metro_model("bench"), x, side * .33, turn, plat) and side > 0:
                    put("bin", catalogue("bin"), x + 1.4, 0., 0, plat)
    else:
        north = r[1] > 0
        face = r[3] - .03 if north else r[1] + .03
        for k in range(int(L / 10)):
            x = 5 + 10 * k
            if against("bench", _metro_model("bench"), plat, 2 if north else 0, x, face):
                put("bin", catalogue("bin"), x + 1.4, face - (.45 if north else -.45), 0, plat)
            if k % 4 == 2:
                against("vending_machine", _metro_model("vending_machine", color=vend), plat, 2 if north else 0, x + 4.6, face)
    for k in range(int(L / 12)):
        x = 6 + 12 * k
        if g["layout"] == "island":
            targets = [(1, hb), (-1, -hb)] if i == 0 else []
        else:
            targets = [(1, hb)] if r[1] > 0 else [(-1, -hb)]
        for side, y_wall in targets:
            turn = 2 if side > 0 else 0
            y_wall -= side * .03
            against("name_board", _metro_model("name_board", label=g["name"]), wall_space(spaces, g, y_wall), turn, x, y_wall,
                    z=zp + (1.7 if g["layout"] == "island" else 2.35), placement="wall")
            against("line_map", _metro_model("line_map", label=g["name"]), wall_space(spaces, g, y_wall), turn, x + 6, y_wall,
                    z=zp + 1.6, placement="wall") if g["layout"] == "side" else None
            against("ad_billboard", _metro_model("ad_billboard", f"AD {4 + k % 4}"), wall_space(spaces, g, y_wall), turn,
                    x + 3.5, y_wall, z=zp + 2.25, placement="wall")   # Cross-track advertising.
            if k % 2 == 0:
                against("cctv", _metro_model("cctv"), wall_space(spaces, g, y_wall), turn, x - 3, y_wall, z=zp + 3.6,
                        placement="wall")
    y_signs = [((r[1] + r[3]) / 2 + d) for d in ((-2.6, 2.6) if g["layout"] == "island" else (0.,))]
    for k, x in enumerate(np_range(10, L - 8, 18)):
        for j, y in enumerate(y_signs):
            put("hanging_sign", _metro_model("hanging_sign", f"PLATFORM {2 * i + j + 1}" if k % 2 == 0 else "WAY OUT", top=top_p),
                x, y, 1, plat, "hanging")
    for t, y in g["stairs"]:
        if r[1] <= y <= r[3]:
            bottom = t - g["run"]
            put("departure_board", _metro_model("departure_board", "|".join(others[:3]), top=top_p), bottom - 4., y, 1, plat, "hanging")
            put("clock", _metro_model("clock", top=top_p), bottom - 7., y, 1, plat, "hanging")


def _entrance(g, rng, put, against, catalogue, others, vend):
    """Street end of the unpaid hall, the robot's first view (a follow camera, 2-15 m ahead of the spawn).

    Per side, all seeded: a line along the glazed facade of planters, advertising and departures totems and map
    stands; a row of benches in front of it facing the hall; one interior group off the column rows (seating,
    information desk, map stand or planters); one wall group beside the facade (vending machines or a bench). put() keeps lanes, the gateline and 1 m around the spawn clear.
    """
    X1, Hh, unpaid = g["X1"], g["Hh"], g["unpaid"]
    xf = X1 - WALL / 2 - .3                      # Line along the facade: 5 cm off the glazing sill.
    groups = rng.sample(("seating", "info_desk", "map", "planters", "seating"), 2)
    departures = "|".join(others[:3])
    for side, group in zip((1, -1), groups):
        y, end, k = side * 1.6, Hh - .9, 0
        while abs(y) < end:
            kind = rng.choice(("planter_box", "planter_box", "ad_totem", "departure_totem" if k == 1 else "map_stand"))
            width = rng.choice((1.8, 2.4, 3.0)) if kind == "planter_box" else 1.3
            mid = y + side * width / 2
            if abs(mid) + width / 2 > end:
                break
            if kind == "planter_box":
                put(kind, _metro_model(kind, aspect=width), xf, mid, 1, unpaid)
            else:
                label = departures if kind == "departure_totem" else (g["name"] if kind == "map_stand" else "")
                put(kind, _metro_model(kind, label), xf - .05, mid, 1, unpaid)
            y = mid + side * (width / 2 + rng.uniform(.2, .6))
            k += 1
        for yb in np_range(2.6 + rng.uniform(0, 1.), Hh - 2.5, 2.9):   # Window seating facing the hall.
            if rng.random() < .75:
                if put("bench", _metro_model("bench"), X1 - 1.6, side * yb, 1, unpaid) and rng.random() < .5:
                    put("bin", catalogue("bin"), X1 - 1.6, side * (yb + 1.3), 0, unpaid)
        x, yc = X1 - rng.uniform(4.5, 7.), side * (Hh / 2 - 2.4)   # Between the central lane and the column row.
        if group == "seating":
            if put("bench", _metro_model("bench"), x, yc + .33, 0, unpaid) + put("bench", _metro_model("bench"), x, yc - .33, 2, unpaid):
                put("bin", catalogue("bin"), x + 1.4, yc, 0, unpaid)
        elif group == "info_desk":
            parts, items = _group([("info_desk", _metro_model("info_desk"), 0, 0, 0),
                                   ("lab_chair", catalogue("lab_chair"), .5, -.75, 0)])
            put("info_desk", parts, x, yc, 2 if side > 0 else 0, unpaid, items=items)  # Counter faces the central lane.
        elif group == "map":
            put("map_stand", _metro_model("map_stand", label=g["name"]), x, yc, 1, unpaid)
            put("bin", catalogue("bin"), x, yc + side * .9, 0, unpaid)
        else:
            put("planter_box", _metro_model("planter_box", aspect=2.4), x, yc + side * .55, 0, unpaid)
            put("bench", _metro_model("bench"), x, yc - side * .1, 0 if side < 0 else 2, unpaid)
        face, turn = side * (Hh - WALL / 2), 2 if side > 0 else 0
        if rng.random() < .6:
            for xv in (X1 - 1.45, X1 - 2.55):
                against("vending_machine", _metro_model("vending_machine", color=vend), unpaid, turn, xv, face)
        elif against("bench", _metro_model("bench"), unpaid, turn, X1 - 2.2, face):
            put("bin", catalogue("bin"), X1 - 3.6, side * (Hh - .45), 0, unpaid)


def wall_space(spaces, g, y):
    """Space touching the station-box wall at y: the trackway (island) or the side platform."""
    return next(s["id"] for s in spaces if s["level"] == 0 and s["kind"] in ("trackway", "platform") and
                s["rect"][1] - 1e-6 <= y <= s["rect"][3] + 1e-6 and s["rect"][0] <= 1)


def np_range(a, b, step):
    """Values from a to b inclusive in steps of step (floats, without numpy)."""
    out = []
    while a <= b:
        out.append(a)
        a += step
    return out


def _column_sites(c, g):
    """Concourse column grid (two rows) minus voids, the gateline, lanes and the spawn: (x, y, footprint)."""
    d, out = c.column_diameter, []
    x = g["X0"] + c.column_spacing / 2
    while x < g["X1"] - 2:
        for y in (g["Hh"] / 2, -g["Hh"] / 2):
            fp = [x - d * .75, y - d * .75, x + d * .75, y + d * .75]
            if not (abs(x - g["gate_x"]) < 2.5 or any(_overlap(fp, o, .6) for o in g["blocked"][1])
                    or any(_crosses(fp, a, b, .45) for a, b in g["lanes"][1]) or math.dist((x, y), g["spawn"]) < 2):
                out.append((x, y, fp))
        x += c.column_spacing
    return out


def _columns(scene, c, g):
    """Concourse columns on _column_sites (_furnish keeps them free, so furniture never removes one); furnished halls
    get a wayfinding sign collar on each column ("TO PLATFORMS" walking in from the street, "WAY OUT" walking back)."""
    d, H = c.column_diameter, g["H"]
    occupied = [o["bounds"] for o in scene["objects"] if o["level"] == 1 and o["kind"] != "column_collar"]
    for x, y, fp in _column_sites(c, g):
        if any(_overlap(fp, o, .6) for o in occupied):   # Only objects placed outside _furnish's checks (gateline).
            continue
        scene["boxes"].append(dict(kind="wall", size=[d, d, H - .6], center=[x, y, (H - .6) / 2], level=1, material="wall",
                                   color=C["concrete"], texture=dict(style="concrete", seed=c.seed, period=PERIODS["concrete"], label="", rev=TEXTURE_REV),
                                   element="column", shape="lathe", profile=[[1, -.5], [1, .5]]))
        # Flare 0.8 -> 1 (4 cm collar over the shaft): metric lathe UVs stay within 1.25 anisotropy.
        scene["boxes"].append(dict(kind="wall", size=[1.35 * d, 1.35 * d, .6], center=[x, y, H - .3], level=1, material="wall",
                                   color=C["concrete"], texture=dict(style="concrete", seed=c.seed, period=PERIODS["concrete"], label="", rev=TEXTURE_REV),
                                   element="column_capital", shape="lathe", profile=[[.8, -.5], [1, .5]]))
        if c.furnished:
            hall = g["paid"] if x < g["gate_x"] else g["unpaid"]
            _register(scene, c, _world(_metro_model("column_collar", "TO PLATFORMS|WAY OUT", d), (x, y, 2.75), 3),
                      "column_collar", hall, "wall", [x, y, 2.75], 3)


def _annotate(scene):
    """COCO80 hints (semantics.CLASSES plus bench/clock); ground truth only, never detector output."""
    from collections import Counter
    from semantics import CLASSES
    classes = dict(CLASSES, bench=(13, "bench"), clock=(74, "clock"))
    counts, unmapped = Counter(), set()
    for obj in scene["objects"]:
        for item in obj["items"]:
            ident, label = classes.get(item["kind"], (None, None))
            item.update(coco_id=ident, coco_class=label)
            if label:
                counts[label] += 1
            else:
                unmapped.add(item["kind"])
    scene["perception"] = dict(taxonomy="COCO80", source="semantic_ground_truth_only",
                               class_counts=dict(sorted(counts.items())), unmapped_models=sorted(unmapped))


# ---- Rendering and CLI (PyBullet) ----
def views(scene):
    """Standard inspection cameras: name -> dict(eye, target, fov, hide_level)."""
    x0, y0, x1, y1 = scene["bounds"]
    zp = scene["levels"][0]["floor_z"]
    L = scene["config"]["platform_length"]
    plat = next(s for s in scene["spaces"] if s["kind"] == "platform")
    r = plat["rect"]
    y_l = (r[1] + r[3]) / 2 + (r[3] - r[1]) * (.3 if scene["layout"] == "island" else 0)
    concourse = next(s for s in scene["spaces"] if s["kind"] == "concourse")
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    span = max(x1 - x0, y1 - y0)
    out = dict(
        overview=dict(eye=[cx + .35 * span, cy - .55 * span, .55 * span], target=[cx, cy, -2.], fov=50, hide_level=None),
        overview_platform=dict(eye=[cx + .35 * span, cy - .55 * span, .55 * span + zp], target=[cx, cy, zp - 1.], fov=50, hide_level=1),
        platform=dict(eye=[.18 * L, y_l, zp + 1.6], target=[.75 * L, y_l + (2.5 if y_l > 0 else -2.5), zp + .9], fov=70, hide_level=None),
        concourse=dict(eye=[scene["spawn"][0] + 1., concourse["rect"][1] + 3., 1.6],
                       target=[scene["spawn"][0] - 30., 1., 1.2], fov=70, hide_level=None))
    walk = next((s for s in scene["spaces"] if s["kind"] == "walkway" and s.get("end") == "east"), None)
    if walk:
        yw = (walk["rect"][1] + walk["rect"][3]) / 2
        out["tunnel"] = dict(eye=[L - 6., yw, zp + 1.6], target=[L + 20., yw * .8, zp + .9], fov=70, hide_level=None)
    if scene["ramps"]:
        ramp = scene["ramps"][0]
        cxr = ramp["centre"][0]
        out["spiral_ramp"] = dict(eye=[cxr + ramp["shaft_half"] + 2.5, -ramp["shaft_half"] - 1.5, 4.5],
                                  target=[cxr, 0., zp + 1.], fov=75, hide_level=None)
    return out


def render(client, bodies, scene, path, eye, target, fov=60, hide_level=None, size=(1280, 800), command=""):
    """Headless TinyRenderer PNG with the regeneration command stored in its metadata."""
    import pybullet as p
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    hidden = [i for i, b in enumerate(scene["boxes"]) if hide_level is not None and b["level"] >= hide_level]
    saved = {i: p.getVisualShapeData(bodies[i], physicsClientId=client)[0][7] for i in hidden}
    for i in hidden:
        p.changeVisualShape(bodies[i], -1, rgbaColor=[*saved[i][:3], 0], physicsClientId=client)
    w, h = size
    view = p.computeViewMatrix(eye, target, [0, 0, 1])
    projection = p.computeProjectionMatrixFOV(fov, w / h, .05, 500)
    rgba = p.getCameraImage(w, h, view, projection, shadow=0, lightDirection=[-.4, -.6, 1.], lightAmbientCoeff=.55,
                            lightDiffuseCoeff=.5, lightSpecularCoeff=.05, renderer=p.ER_TINY_RENDERER, physicsClientId=client)[2]
    for i in hidden:
        p.changeVisualShape(bodies[i], -1, rgbaColor=saved[i], physicsClientId=client)
    pixels = rgba.tobytes() if hasattr(rgba, "tobytes") else bytes(rgba)
    info = PngInfo()
    info.add_text("Source", command or " ".join(sys.argv))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("RGBA", (w, h), pixels).convert("RGB").save(path, pnginfo=info)
    return path


def _parser():
    """Command-line options of metro.py."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=MetroConfig().seed)
    parser.add_argument("--config", type=Path, help="settings override: a folder like config/ or one .toml file")
    parser.add_argument("--layout", choices=("auto", "island", "side"), default="auto")
    parser.add_argument("--no-ramp", action="store_true", help="Through station with tunnels at both ends")
    parser.add_argument("--ramp", action="store_true", help="Force the spiral ramp (default: seeded)")
    parser.add_argument("--length", type=float, help="Platform length (m; default: seeded)")
    parser.add_argument("--depth", type=float, help="Concourse floor to platform floor (m; default: seeded)")
    parser.add_argument("--track-bed", choices=("concrete", "ballast"), help="Default: seeded")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--roof", action="store_true", help="Close the concourse for sensor runs")
    parser.add_argument("--empty", action="store_true", help="Architecture and track only")
    parser.add_argument("--export", type=Path, help="Save backend-neutral scene JSON")
    parser.add_argument("--render", type=Path, help="Save overview PNG")
    parser.add_argument("--figures", type=Path, help="Save the standard views (overview, platform, concourse, ...) here")
    parser.add_argument("--textures", type=Path)
    parser.add_argument("--view-floor", type=int, choices=(0, 1), help="Hide the concourse (0) for inspection")
    parser.add_argument("--xray", action="store_true")
    return parser


def _session(args, scene, argv):
    """PyBullet session: load the scene, optional render/figures, then the interactive viewer."""
    import pybullet as p
    from indoor import load_pybullet
    from surfaces import prepare_textures
    prepare_textures(scene)
    cid = p.connect(p.DIRECT if args.headless else p.GUI)
    if cid < 0:
        raise RuntimeError("Unable to connect to PyBullet; use --headless without a display")
    try:
        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 0, physicsClientId=cid)
        bodies = load_pybullet(scene, cid, args.textures, args.view_floor)
        p.setGravity(0, 0, -9.81, physicsClientId=cid)
        cams = views(scene)
        x0, y0, x1, y1 = scene["bounds"]
        target = [(x0 + x1) / 2, (y0 + y1) / 2, scene["levels"][0]["floor_z"] if args.view_floor == 0 else 0.]
        p.resetDebugVisualizerCamera(max(x1 - x0, y1 - y0) * .9, 35, -55, target, physicsClientId=cid)
        if not args.headless or args.xray:
            from viewer import Viewer
            viewer = Viewer(scene, bodies, cid, args.view_floor, args.xray)
        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 1, physicsClientId=cid)
        stats = scene["metro_stats"]
        print(f"Seed {args.seed}: {scene['layout']} platform{'s' if scene['layout'] == 'side' else ''}, station {scene['station_name']}, "
              f"{stats['parts']} parts, {stats['objects']} objects, {scene['geometry_stats']['visual_triangles']} triangles, "
              f"generated in {stats['generation_s']} s; spawn={scene['spawn']}")
        command = " ".join(["python3 metro.py"] + (argv if argv is not None else sys.argv[1:]))
        if args.render:
            cam = cams["overview_platform" if args.view_floor == 0 else "overview"]
            render(cid, bodies, scene, args.render, cam["eye"], cam["target"], cam["fov"], None, (1400, 1000), command)
        if args.figures:
            for view_name, cam in cams.items():
                print("wrote", render(cid, bodies, scene, args.figures / f"seed{args.seed}_{scene['layout']}_{view_name}.png",
                                      command=command, **cam))
        if not args.headless:
            print("Tab: walk/orbit | X: X-ray | WASD: walk | arrows/right-drag: look | 0: all, 1: platform level only")
            previous = time.perf_counter()
            while p.isConnected(cid):
                now = time.perf_counter()
                viewer.update(min(now - previous, 1 / 30))
                previous = now
                p.stepSimulation(physicsClientId=cid)
                time.sleep(1 / 240)
    except KeyboardInterrupt:
        pass
    finally:
        if p.isConnected(cid):
            p.disconnect(cid)



def main(argv=None):
    """Command line: generate a station, optionally export/render it, and open the PyBullet viewer."""
    parser = _parser()
    args = parser.parse_args(argv)
    from banner import splash
    splash("seeded metro station", f"seed {args.seed}, {args.layout} layout" + (f", settings {args.config}" if args.config else ""))
    try:
        settings.use(args.config)
        scene = generate_metro(MetroConfig(seed=args.seed, layout=args.layout,
                                           spiral_ramp=False if args.no_ramp else (True if args.ramp else None),
                                           platform_length=args.length, depth=args.depth, track_bed=args.track_bed,
                                           roof=args.roof, furnished=not args.empty))
    except ValueError as error:
        parser.error(str(error))
    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(json.dumps(scene, indent=1) + "\n")
    _session(args, scene, argv)


if __name__ == "__main__":
    main()
