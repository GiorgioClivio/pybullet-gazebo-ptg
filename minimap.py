"""Live floor-plan minimap in a separate process, so drawing never slows the simulation.

    mm = Minimap(scene)          # Spawns a tkinter window process.
    mm.update(x, y, z, yaw)      # World pose; yaw in rad, 0 = +x, CCW. At most 10 Hz, never blocks.
    mm.close()

The pose travels through a shared-memory array (latest value wins; nothing queues up), and
update() keeps working after the window is closed. The storey follows z automatically;
Up/Down (or the buttons) select another storey and A returns to automatic selection.

    python3 minimap.py --demo [--seed 7 --floors 3]   # Animate a pose along the loop routes.
    python3 minimap.py --bench 600                    # Viewer update cost with/without minimap.
"""
import math
import multiprocessing as mp
import time

PERIOD = .1  # s between pose updates sent to the window.
FILL = {"room": "#ececec", "corridor": "#f5eed6", "landing": "#f2dcc3", "annex": "#dde9f8",
        "concourse": "#f3f0e8", "platform": "#e9e4d6", "walkway": "#e4e0d4", "trackway": "#c9c4ba", "ramp_shaft": "#f2dcc3"}
INK = {"wall": "#303030", "glass": "#5aa7e0", "guard": "#b5651d"}


def level_heights(scene):
    """Floor z of every level: scene["levels"] when the generator exports it (metro), else level x storey."""
    if scene.get("levels"):
        return [lv["floor_z"] for lv in sorted(scene["levels"], key=lambda lv: lv["level"])]
    c = scene["config"]
    return [i * c["storey"] for i in range(c["floors"])]


def storey(scene, z):
    """Level of a body at height z: the highest floor at most 0.3 m above z (body origins sit above floors)."""
    heights = scene["config"].get("level_z") or level_heights(scene)
    return max([i for i, floor in enumerate(heights) if floor <= z + .3] or [0])


def plan(scene, level):
    """Simplified plan of one storey as primitives in metres (plain tuples, testable without a display).

    ("space", kind, label, rect, annex)  rect = [x0, y0, x1, y1]
    ("wall" | "glass" | "guard", rect)   wall footprints at floor level; windows; stair guards
    ("door" | "opening", p0, p1)         door clear width, or a full-width public opening
    ("stairs", rect, "up" | "down", p0, p1)  flight footprint; arrow p0 -> p1 points the travel way
    """
    c = scene["config"]
    z = level_heights(scene)[level]
    wall_h = c["storey"] - c["slab"] if "storey" in c else None  # metro: no fixed storey height
    out = [("space", s["kind"], s.get("purpose", s["kind"]), s["rect"], bool(s.get("annex")))
           for s in scene["spaces"] if s["level"] == level]
    for b in scene["boxes"]:
        if b["level"] != level or "object_id" in b or b["kind"] not in ("wall", "glass", "trim"):
            continue
        (cx, cy, cz), (sx, sy, sz) = b["center"], b["size"]
        if b["kind"] == "glass":  # Widen thin glazing to the wall thickness so it reads as a window.
            wall = c.get("wall", .16)
            sx, sy = (sx, wall) if sx > sy else (wall, sy)
        elif abs(cz - sz / 2 - z) > .01 or ("sill" in c and abs(sz - c["sill"]) < 1e-6):
            continue  # Lintels and window parapets; the window glass replaces the sill.
        out.append(("guard" if b["kind"] == "trim" else b["kind"], [cx - sx / 2, cy - sy / 2, cx + sx / 2, cy + sy / 2]))
    for portal in scene["portals"]:
        if abs(portal["center"][2] - z) < .01:
            p0, p1 = portal["center"][:2], portal["center"][:2]
            p0[portal["axis"]] -= portal["width"] / 2
            p1[portal["axis"]] += portal["width"] / 2
            door = portal["height"] < wall_h - 1e-6 if wall_h else portal["height"] < 2.5
            out.append(("door" if door else "opening", p0, p1))
    flights = [(st, "up") for st in scene["stairs"] if abs(st["start"][2] - z) < .01]
    flights += [(st, "down") for st in scene["stairs"] if st["upper_level"] == level]
    for st, direction in flights:
        (x0, y0), (x1, y1) = st["start"][:2], st["end"][:2]
        length = math.hypot(x1 - x0, y1 - y0)
        dx, dy = (x1 - x0) / length, (y1 - y0) / length
        # Exported endpoints include .5 m of landing; both flights share one footprint, side by side.
        a, b = (x0 + .5 * dx, y0 + .5 * dy), (x1 - .5 * dx, y1 - .5 * dy)
        h = st["width"] / 2
        xs, ys = [v + s * h * -dy for v in (a[0], b[0]) for s in (-1, 1)], [v + s * h * dx for v in (a[1], b[1]) for s in (-1, 1)]
        side = (-.25 if direction == "up" else .25) * st["width"] if len(flights) > 1 else 0.
        a, b = [(px - side * dy, py + side * dx) for px, py in (a, b)]
        out.append(("stairs", [min(xs), min(ys), max(xs), max(ys)], direction, *((a, b) if direction == "up" else (b, a))))
    for ramp in scene.get("ramps", ()):  # metro spiral ramp: its centreline, on both levels it joins
        if level in (ramp["upper_level"], ramp["upper_level"] - 1):
            out.append(("ramp", [pt[:2] for pt in ramp["points"]]))
    return out


def _draw_level(canvas, xy, rect, items):
    """Draw one storey's plan items (see plan) on a cleared canvas."""
    canvas.delete("all")
    for item in items:
        kind = item[0]
        if kind == "space":
            _, space, text, r, annex = item
            rect(r, fill=FILL.get("annex" if annex else space, "#ececec"), outline="")
            if min(r[2] - r[0], r[3] - r[1]) > 2.5 and space == "room" or annex:
                canvas.create_text(*xy((r[0] + r[2]) / 2, (r[1] + r[3]) / 2), text="annex" if annex else text,
                                   fill="#808080", font=("TkDefaultFont", 8))
        elif kind == "ramp":
            canvas.create_line(*[v for pt in item[1] for v in xy(*pt)], fill="#c77d00", width=3)
        elif kind in INK:
            rect(item[1], fill=INK[kind], outline="")
        elif kind == "stairs":
            _, r, direction, a, b = item
            rect(r, fill="#ffd54a", outline="#c77d00", width=2)
            color = "#c62828" if direction == "up" else "#1565c0"
            canvas.create_line(*xy(*a), *xy(*b), arrow="last", width=3, arrowshape=(12, 14, 5), fill=color, tags="arrow")
            canvas.create_text(*xy(*a), text="UP" if direction == "up" else "DN", fill=color,
                               anchor="n" if b[1] > a[1] else "s", font=("TkDefaultFont", 9, "bold"), tags="arrow")
        else:
            canvas.create_line(*xy(*item[1]), *xy(*item[2]), fill="#2a9d4b" if kind == "door" else "#a0a0a0",
                               width=4 if kind == "door" else 1, dash=() if kind == "door" else (4, 3))
    canvas.tag_raise("arrow")  # Both flights share a footprint: keep each arrow above it.


def _draw_pose(canvas, px, py, yaw, scale, same):
    """Pose arrow at canvas point (px, py): filled on its own storey, outlined when another storey is shown."""
    c, s = math.cos(yaw), math.sin(yaw)
    tip = [(.9, 0), (-.5, .45), (-.25, 0), (-.5, -.45)]
    points = [v for u, w in tip for v in (px + (u * c - w * s) * scale * .8, py - (u * s + w * c) * scale * .8)]
    canvas.create_polygon(points, fill="#d81b60" if same else "", outline="#d81b60", width=2, tags="pose")


def _window(levels, bounds, config, pose, size=640):
    """Child process: draw levels[storey] and poll the shared pose every 50 ms."""
    import tkinter as tk
    root = tk.Tk()
    root.title("PTG minimap")
    x0, y0, x1, y1 = bounds
    pad, scale = 18, min(size / (x1 - x0), size / (y1 - y0))
    canvas = tk.Canvas(root, width=(x1 - x0) * scale + 2 * pad, height=(y1 - y0) * scale + 2 * pad, bg="white")
    canvas.pack()
    state = dict(level=0, auto=True, drawn=None)
    bar = tk.Frame(root)
    bar.pack(fill="x")
    label = tk.Label(bar)
    label.pack(side="left", padx=6)

    def xy(x, y):
        return pad + (x - x0) * scale, pad + (y1 - y) * scale

    def rect(r, **style):
        canvas.create_rectangle(*xy(r[0], r[1]), *xy(r[2], r[3]), **style)

    def pick(step=None):
        if step is None:
            state["auto"] = True
        else:
            state["auto"], state["level"] = False, max(0, min(len(levels) - 1, state["level"] + step))
        poll(repeat=False)

    for text, step in (("Auto (A)", None), ("Down ↓", -1), ("Up ↑", 1)):
        tk.Button(bar, text=text, command=lambda s=step: pick(s)).pack(side="right")
    root.bind("<Up>", lambda _: pick(1))
    root.bind("<Down>", lambda _: pick(-1))
    root.bind("<a>", lambda _: pick())

    def draw(level):
        _draw_level(canvas, xy, rect, levels[level])
        state["drawn"] = level

    def poll(repeat=True):
        parent = mp.parent_process()
        if parent is not None and not parent.is_alive():
            root.destroy()
            return
        seq, x, y, z, yaw = pose[:]
        here = storey({"config": config}, z) if seq else 0
        if state["auto"]:
            state["level"] = here
        if state["drawn"] != state["level"]:
            draw(state["level"])
        canvas.delete("pose")
        if seq:
            _draw_pose(canvas, *xy(x, y), yaw, scale, same=here == state["level"])
        label.config(text=f"Storey {state['level']} of {len(levels)}" + (" (auto)" if state["auto"] else "")
                     + ("" if not seq or here == state["level"] else f"  pose on storey {here}"))
        if repeat:
            root.after(50, poll)

    poll()
    root.mainloop()


class Minimap:
    """Host-side handle: cheap, non-blocking, safe after the window or process has gone."""

    def __init__(self, scene, period=PERIOD):
        ctx = mp.get_context("spawn")
        self.pose = ctx.RawArray("d", 5)  # seq, x, y, z, yaw: torn reads only mix two recent poses.
        self.period, self.last = period, -math.inf
        heights = level_heights(scene)
        levels = [plan(scene, level) for level in range(len(heights))]
        self.process = ctx.Process(target=_window, name="ptg-minimap", daemon=True,
                                   args=(levels, scene["bounds"], dict(scene["config"], level_z=heights), self.pose))
        self.process.start()

    def update(self, x, y, z, yaw):
        """Publish a pose if PERIOD has elapsed; return whether it was sent."""
        now = time.monotonic()
        if now - self.last < self.period:
            return False
        self.last = now
        self.pose[1:] = x, y, z, yaw
        self.pose[0] += 1
        return True

    def close(self):
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(1)


def _main():
    import argparse
    from indoor import Config, generate
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--floors", type=int, default=3)
    parser.add_argument("--demo", action="store_true", help="Open the window and follow the loop routes")
    parser.add_argument("--seconds", type=float, default=8.)
    parser.add_argument("--bench", type=int, metavar="N", help="Time N walking viewer updates (PyBullet DIRECT)")
    args = parser.parse_args()
    scene = generate(Config(seed=args.seed, floors=args.floors))
    if args.demo:
        mm, route = Minimap(scene), [pt for r in scene["loop_routes"] for pt in r["points"]]
        start = time.monotonic()
        while (t := time.monotonic() - start) < args.seconds:
            i = min(int(t / args.seconds * (len(route) - 1)), len(route) - 2)
            a, b = route[i], route[i + 1]
            mm.update(a[0], a[1], a[2] + .55, math.atan2(b[1] - a[1], b[0] - a[0]))
            time.sleep(.01)
        mm.close()
    if args.bench:
        import pybullet as p
        from indoor import load_pybullet
        from viewer import Viewer
        client = p.connect(p.DIRECT)
        bodies = load_pybullet(scene, client)
        keys = {ord("w"): p.KEY_IS_DOWN, p.B3G_LEFT_ARROW: p.KEY_IS_DOWN}  # Walk in a circle.
        mm, viewer = None, Viewer(scene, bodies, client)
        viewer.update(1 / 60, {9: p.KEY_WAS_TRIGGERED}, [])  # One walker for every run.
        for name in ("no minimap process", *("with minimap", "minimap open, not sent") * 3):
            mm = mm or (Minimap(scene) if name == "with minimap" else None)
            viewer.minimap = mm if name == "with minimap" else None
            start = time.perf_counter()
            for _ in range(args.bench):
                viewer.update(1 / 60, keys, [])
            elapsed = time.perf_counter() - start
            print(f"viewer.update {name}: {elapsed / args.bench * 1e6:.1f} us/call over {args.bench}")
        start = time.perf_counter()
        sent = sum(mm.update(0, 0, 0, 0) for _ in range(100000))
        print(f"Minimap.update alone: {(time.perf_counter() - start) / 100000 * 1e6:.2f} us/call, {sent} sent")
        mm.close()
        p.disconnect(client)


if __name__ == "__main__":
    _main()
