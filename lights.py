"""Ceiling luminaires sized by the lumen method, and an 8-slot light manager for pybullet_pbr.

Nothing here runs inside generate(): scenes stay deterministic and renderer-independent.
Lighting only matters with the custom PBR renderer (pybullet_pbr), so a host adds it only
when that renderer is active:

    import lights
    if lights.active_pbr():
        lights.add_lights(scene)                  # before load_pybullet; appends parts at the END
    body_ids = load_pybullet(scene, client)
    manager = lights.PbrLightManager(scene, client=client, body_ids=body_ids)
    ...  each step: manager.update(camera_or_robot_xyz)

Lumen method: N = E x A / (F x UF x MF). E is the maintained illuminance of the space's
use (EN 12464-1 or residential guidance, table TARGETS), A the clear floor area, F the
luminaire's rated flux, UF read from a real ceiling-mounted LED downlight UF table at the
room index RI = L x W / (Hm x (L + W)), MF = 0.8. N is rounded up to a regular grid whose
spacing is at most SHR_MAX x Hm, then every fixture is dimmed to E x A / (n x UF x MF) so
the maintained average is the standard value, not more. Sources: README "Ceiling lighting".

    python3 lights.py --seed 7 --floors 3            # per-space fixture table
    python3 lights.py --seed 7 --floors 3 --render out.png --at 12 9 1.6   # PBR headless check

--render needs pybullet_pbr on PYTHONPATH (its EGL plugin has been seen to segfault in load_pybullet on the
first mesh visual, with or without luminaires).
"""
import argparse
import bisect
import math

MF = 0.8          # Maintenance factor; DIALux "design factor 1.25" = 1 / 0.8.
SHR_MAX = 1.5     # Max spacing / mounting height above the working plane. [unverified rule of thumb]
WALL_GAP = .3     # Minimum luminaire-centre distance from a wall (m).
# Use -> (maintained lux, working-plane height m, luminaire, kelvin).
TARGETS = {
    "office": (500, .85, "panel", 4000),      # EN 12464-1 writing/reading/data processing
    "meeting": (500, .85, "panel", 4000),     # EN 12464-1 conference and meeting rooms
    "lab": (500, .85, "panel", 4000),         # EN 12464-1 laboratories (education: practical rooms and laboratories) 500 lx [row number unverified]
    "workshop": (300, .85, "panel", 4000),    # [unverified] rough bench/assembly ~300 lx (secondary source)
    "laundry": (300, .85, "downlight", 4000), # EN 12464-1 textile washing/ironing 300 lx (not a domestic row)
    "kitchen": (300, .85, "downlight", 4000), # IES residential general kitchen 30-40 fc, low end
    "dining": (200, .85, "downlight", 3000),  # EN 12464-1 canteens 200 lx
    "bathroom": (150, .85, "downlight", 4000),# SLL LG9 (communal residential) bathrooms 150 lx
    "living": (100, .85, "downlight", 2700),  # IES residential ambient 10-20 fc, low end
    "bedroom": (100, .85, "downlight", 2700), # IES residential ambient 10-20 fc, low end
    "storage": (100, 0., "downlight", 4000),  # EN 12464-1 store room aisles and passages
    "corridor": (100, 0., "downlight", 3000), # EN 12464-1 circulation areas, floor level
    "landing": (150, 0., "downlight", 3000),  # EN 12464-1:2021 stairs, floor level
}
# Rated flux from real datasheets; render cone is a full-angle (inner, outer) approximation
# of the near-Lambertian distribution. Panel: 595 mm 3600 lm 4000 K (Sylvania START, search
# listing only). Downlight: Philips SmartBright DN029B, 1000 lm, 100 deg beam (datasheet).
LUMINAIRES = {
    "panel": dict(lumens=3600, size=[.595, .595, .012], beam=120, radius=.3),
    "downlight": dict(lumens=1000, size=[.15, .15, .012], beam=100, radius=.06),
}
RENDER_CONE = (60., 140.)
# UF of a ceiling-mounted Philips DN027B LED downlight, reflectances 0.70/0.50/0.20 (CalcuLuX).
UF_TABLE = ((.6, .46), (.8, .56), (1., .64), (1.25, .72), (1.5, .77), (2., .86),
            (2.5, .92), (3., .95), (4., 1.), (5., 1.03))


def utilisation_factor(room_index):
    """Linear interpolation in UF_TABLE; flat above k = 5, extrapolated below k = 0.6.

    Narrow corridors and stair landings have k ~ 0.4: the first segment's slope is
    continued down to a 0.2 floor ([unverified] extrapolation, conservative: more fixtures).
    """
    ks = [k for k, _ in UF_TABLE]
    if room_index >= ks[-1]:
        return UF_TABLE[-1][1]
    i = min(max(bisect.bisect_right(ks, room_index), 1), len(ks) - 1)
    (k0, u0), (k1, u1) = UF_TABLE[i - 1], UF_TABLE[i]
    return max(.2, u0 + (room_index - k0) / (k1 - k0) * (u1 - u0))


def lumen_method(lux, lx, ly, hm, rated):
    """Fixture count, regular grid and dimmed flux for one clear lx x ly room."""
    area, ri = lx * ly, lx * ly / (hm * (lx + ly))
    uf = utilisation_factor(ri)
    n_min = math.ceil(lux * area / (rated * uf * MF))
    smax = SHR_MAX * hm
    best = None
    for nx in range(max(1, math.ceil(lx / smax)), n_min + math.ceil(lx / smax) + 1):
        ny = max(math.ceil(n_min / nx), math.ceil(ly / smax), 1)
        # Half-spacing wall offsets must leave WALL_GAP; narrow rooms take fewer columns.
        if nx > 1 and lx / nx / 2 < WALL_GAP or ny > 1 and ly / ny / 2 < WALL_GAP:
            continue
        key = (nx * ny, abs(lx / nx - ly / ny))
        if best is None or key < best[0]:
            best = key, nx, ny
    _, nx, ny = best
    lumens = lux * area / (nx * ny * uf * MF)
    return dict(area=area, room_index=ri, uf=uf, mf=MF, n_min=n_min, nx=nx, ny=ny,
                lumens=min(lumens, rated), rated=rated)


def _covered(scene, level, x, y, half):
    """True if slabs of the storey above (or the roof) lie over the luminaire's centre and corners.

    Upper slabs are one rectangle per space, so a luminaire may straddle a seam between two.
    """
    slabs = [b for b in scene["boxes"] if b["kind"] in ("floor", "ceiling") and b["level"] == level + 1]
    return all(any(abs(px - b["center"][0]) <= b["size"][0] / 2 + 1e-9 and abs(py - b["center"][1]) <= b["size"][1] / 2 + 1e-9
                   for b in slabs)
               for px, py in ((x, y), (x - half, y - half), (x + half, y - half), (x - half, y + half), (x + half, y + half)))


def plan_lights(scene):
    """Deterministic fixture list for every space that has a ceiling."""
    c, fixtures = scene["config"], []
    for s in scene["spaces"]:
        use = s.get("purpose", s["kind"])
        if use not in TARGETS:
            continue
        lux, plane, kind, kelvin = TARGETS[use]
        lum = LUMINAIRES[kind]
        x0, y0, x1, y1 = (v + d * c["wall"] / 2 for v, d in zip(s["rect"], (1, 1, -1, -1)))
        level, floor_z = s["level"], s["level"] * c["storey"]
        ceiling_z = floor_z + c["storey"] - c["slab"]
        if level < c["floors"] - 1:
            from indoor import CEILING_SKIN
            ceiling_z -= CEILING_SKIN  # mount below the plaster skin of inter-storey slabs
        calc = lumen_method(lux, x1 - x0, y1 - y0, ceiling_z - floor_z - plane, lum["lumens"])
        sx, sy = (x1 - x0) / calc["nx"], (y1 - y0) / calc["ny"]
        points = [(x0 + (i + .5) * sx, y0 + (j + .5) * sy) for j in range(calc["ny"]) for i in range(calc["nx"])]
        points = [q for q in points if _covered(scene, level, *q, lum["size"][0] / 2)]
        if not points:
            continue
        lumens = min(lum["lumens"], lux * calc["area"] / (len(points) * calc["uf"] * MF))
        average = len(points) * lumens * calc["uf"] * MF / calc["area"]
        calc.update(n=len(points), lumens=round(lumens, 1), average_lux=round(average, 1),
                    room_index=round(calc["room_index"], 3), uf=round(calc["uf"], 4),
                    area=round(calc["area"], 3), working_plane=plane)
        for x, y in points:
            fixtures.append(dict(space=s["id"], level=level, use=use, kind=kind,
                position=[round(x, 4), round(y, 4), round(ceiling_z, 4)], size=lum["size"],
                lumens=calc["lumens"], kelvin=kelvin, beam_angle=lum["beam"], radius=lum["radius"],
                target_lux=lux, calculation=calc))
    return fixtures


def add_lights(scene):
    """Append luminaire parts at the END of scene["boxes"]; store scene["lights"]. Idempotent."""
    if "lights" in scene:
        return scene
    scene["lights"] = plan_lights(scene)
    for f in scene["lights"]:
        x, y, z = f["position"]
        part = dict(kind="light", size=list(f["size"]), center=[x, y, z - f["size"][2] / 2],
                    level=f["level"], material="plastic", color=[.96, .96, .94, 1], label=f["kind"])
        if f["kind"] == "downlight":
            part.update(shape="lathe", axis=2, profile=[[1, -.5], [1, .5]])
        f["box"] = len(scene["boxes"])
        scene["boxes"].append(part)
    from geometry import geometry_stats
    scene["geometry_stats"] = geometry_stats(scene)
    return scene


def render_candela(lumens, cone=RENDER_CONE):
    """Intensity so the renderer's smoothstep cone emits `lumens` in total.

    pybullet_pbr converts lumens over the full sphere (L / 4 pi) for every spot, which would
    make a downward ceiling luminaire ~3x too dim; this conserves the real flux instead.
    """
    ci, co = (math.cos(math.radians(a / 2)) for a in cone)
    return lumens / (2 * math.pi * (1 - (ci + co) / 2))


def active_pbr():
    """The pybullet_pbr module if it is importable AND active, else None. Lazy import."""
    try:
        import pybullet_pbr
    except ImportError:
        return None
    return pybullet_pbr if pybullet_pbr.is_active() else None


class PbrLightManager:
    """Keeps the renderer's light slots on the fixtures most relevant to a position.

    Ranking: same storey, then same space, then 3D distance. Each slot is a downward spot
    with shadows (1 atlas tile), so walls and slabs block it. Slots in use by the host
    (e.g. a robot headlamp) at construction are never touched; their tiles are subtracted
    from the 16-tile budget. Exposure: "room" sets a fixed EV for the current space's
    maintained lux (immune to the luminaires in shot), "auto" uses the renderer's
    whole-frame meter, None leaves exposure alone. Does nothing without an active renderer.
    """

    def __init__(self, scene, pbr=None, client=0, body_ids=None, slots=None, exposure="room", min_move=.25,
                 shadows=None, light_range=8.):
        """shadows: max shadowed slots (None = as many as the 16-tile atlas allows). Each shadowed
        spot re-renders the scene every frame while anything moves: measured with a headless PBR benchmark
        (seed 0, 2 storeys, moving body) 42.6 ms/frame without lights, 65.0 with 8 unshadowed, 166.0 with 8 shadowed."""
        self.pbr = pbr if pbr is not None else active_pbr()
        self.fixtures = scene.get("lights") or []
        if self.pbr is None or not self.pbr.is_active() or not self.fixtures:
            self.pbr = None
            return
        c = scene["config"]
        self.storey, self.floors, self.spaces = c["storey"], c["floors"], scene["spaces"]
        self.exposure, self.min_move, self.client = exposure, min_move, client
        own = [s for s in range(self.pbr.max_lights()) if self.pbr.get_light(s)["kind"] == 0]
        self.slots = [s for s in (own if slots is None else slots) if s in own]
        used = sum((6 if light["kind"] == self.pbr.POINT else 1) for light in
                   (self.pbr.get_light(s) for s in range(self.pbr.max_lights()) if s not in own)
                   if light["shadows"])
        self.shadow_tiles = max(0, 16 - used) if shadows is None else max(0, min(shadows, 16 - used))
        self.light_range = light_range
        self.assigned, self.last, self.space = {}, None, None
        if exposure == "auto":
            ev = self.pbr.photometry.ev_for_illuminance
            self.pbr.set_auto_exposure(True, key=.18, min_ev=ev(20), max_ev=15.)
        for f in self.fixtures if body_ids else ():
            area = math.pi * f["size"][0] ** 2 / 4 if f["kind"] == "downlight" else f["size"][0] * f["size"][1]
            self.pbr.set_material(body_ids[f["box"]], base_color=[1, 1, 1, 1],
                                  emissive=f["lumens"] * MF / (math.pi * area), physicsClientId=client)

    def locate(self, position):
        level = min(self.floors - 1, max(0, int(position[2] // self.storey)))
        space = next((s["id"] for s in self.spaces if s["level"] == level and
                      s["rect"][0] <= position[0] <= s["rect"][2] and s["rect"][1] <= position[1] <= s["rect"][3]), None)
        return level, space

    def rank(self, position):
        level, space = self.locate(position)
        order = sorted(range(len(self.fixtures)), key=lambda i: (
            self.fixtures[i]["level"] != level, self.fixtures[i]["space"] != space,
            math.dist(position, self.fixtures[i]["position"]), i))
        return order[:len(self.slots)]

    def update(self, position, force=False):
        """Reassign slots if the position moved >= min_move or changed space; returns lit fixture indices."""
        if self.pbr is None:
            return []
        position = list(position)
        space = self.locate(position)[1]
        if not force and self.last is not None and space == self.space and math.dist(position, self.last) < self.min_move:
            return sorted(self.assigned.values())
        chosen = self.rank(position)
        if self.exposure == "room" and space != self.space and space is not None:
            f = next((f for f in self.fixtures if f["space"] == space), None)
            if f:
                self.pbr.set_ev(self.pbr.photometry.ev_for_illuminance(f["target_lux"]))
        self.last, self.space = position, space
        keep = {s: i for s, i in self.assigned.items() if i in chosen}
        free = [s for s in self.slots if s not in keep]
        for s in [s for s in self.assigned if s not in keep]:
            self.pbr.remove_light(s)
        new = [i for i in chosen if i not in keep.values()]
        for s, i in zip(free, new):
            f = self.fixtures[i]
            x, y, z = f["position"]
            self.pbr.add_light(kind=self.pbr.SPOT, slot=s, position=[x, y, z - f["size"][2] - .01],
                direction=[0, 0, -1], candela=render_candela(f["lumens"] * MF), kelvin=f["kelvin"],
                radius=f["radius"], range=self.light_range, cone_angle=RENDER_CONE[1],
                cone_softness=1 - RENDER_CONE[0] / RENDER_CONE[1],
                shadows=chosen.index(i) < self.shadow_tiles)
            keep[s] = i
        self.assigned = keep
        return sorted(keep.values())

    def close(self):
        for s in list(getattr(self, "assigned", {})):
            self.pbr.remove_light(s)
        self.assigned = {}


def _render(scene, path, eye, target):
    """One headless PBR frame (needs pybullet_pbr built)."""
    import pybullet_pbr
    pybullet_pbr.activate()
    import pybullet as p
    from PIL import Image
    from indoor import load_pybullet
    client = p.connect(p.DIRECT)
    pybullet_pbr.enable_headless(client)
    pybullet_pbr.set_scene("earth_night")   # no usable sun: only the luminaires light the rooms
    add_lights(scene)
    bodies = load_pybullet(scene, client)
    manager = PbrLightManager(scene, pybullet_pbr, client, bodies)
    lit = manager.update(eye)
    view = p.computeViewMatrix(eye, target, [0, 0, 1])
    w, h, rgba = p.getCameraImage(640, 480, view, p.computeProjectionMatrixFOV(75, 4 / 3, .05, 60),
                                  renderer=p.ER_BULLET_HARDWARE_OPENGL, physicsClientId=client)[:3]
    Image.frombytes("RGBA", (w, h), bytes(rgba) if not hasattr(rgba, "tobytes") else rgba.tobytes()).convert("RGB").save(path)
    print(f"{path}: {len(lit)} slots lit, EV {pybullet_pbr.get_ev():.2f}")
    p.disconnect(client)


def main():
    """Command line: print the fixture plan per space, optionally render one headless PBR frame."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--floors", type=int, default=1)
    parser.add_argument("--roof", action="store_true")
    parser.add_argument("--render", help="PNG path for a headless pybullet_pbr frame")
    parser.add_argument("--at", type=float, nargs=3, metavar=("X", "Y", "Z"), help="Camera position (default: spawn, 1.6 m eye)")
    parser.add_argument("--look", type=float, nargs=3, metavar=("X", "Y", "Z"), help="Camera target")
    args = parser.parse_args()
    from indoor import Config, generate
    scene = generate(Config(seed=args.seed, floors=args.floors, roof=args.roof))
    print("space level use        area_m2  lux  RI    UF    grid  n  lm/fixture  avg_lux kind      K")
    seen = set()
    for f in plan_lights(scene):
        k = f["calculation"]
        if f["space"] not in seen:
            seen.add(f["space"])
            print(f'{f["space"]:5d} {f["level"]:5d} {f["use"]:10s} {k["area"]:7.2f} {f["target_lux"]:4d} {k["room_index"]:5.2f} '
                  f'{k["uf"]:5.3f} {k["nx"]}x{k["ny"]:<3d} {k["n"]:2d} {f["lumens"]:10.1f} {k["average_lux"]:8.1f} {f["kind"]:9s} {f["kelvin"]}')
    lit = [s for s in scene["spaces"] if s["id"] in seen]
    print(f"{len(plan_lights(scene))} fixtures in {len(lit)} of {len(scene['spaces'])} spaces")
    if args.render:
        x0, y0, x1, y1 = next(s for s in scene["spaces"] if s["kind"] == "room")["rect"]
        eye = args.at or [x0 + .5, y0 + .5, 1.6]
        _render(scene, args.render, eye, args.look or [(x0 + x1) / 2, (y0 + y1) / 2, 1.])


if __name__ == "__main__":
    main()
