"""Small metric meshes: chamfered panels, turned objects, foliage and curved handles.

All meshes stay within their declared axis-aligned envelopes. Rounded furniture
uses conservative box collisions; turned/curved parts use convex collision hulls.
"""
from functools import lru_cache
import itertools
import json
import math


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _normal(v):
    length = math.sqrt(sum(x*x for x in v))
    return [x / length for x in v] if length else [0, 0, 1]


class _Mesh:
    """Vertex, normal, UV and index buffers being filled by one shape builder."""

    def __init__(self, period):
        self.period = period  # Texture repeat in metres: UVs are arc length / period, like box UVs.
        self.vertices, self.normals, self.uvs, self.indices = [], [], [], []

    def face(self, points, normal):
        """Append one convex planar polygon (any vertex order) with metric planar UVs."""
        center = [sum(p[a] for p in points)/len(points) for a in range(3)]
        n = _normal(normal)
        u = _normal([points[0][a]-center[a] for a in range(3)])
        v = _cross(n, u)
        points = sorted(points, key=lambda p: math.atan2(sum((p[a]-center[a])*v[a] for a in range(3)),
                                                        sum((p[a]-center[a])*u[a] for a in range(3))))
        start = len(self.vertices)
        axis = max(range(3), key=lambda a: abs(n[a]))
        axes = [a for a in range(3) if a != axis]
        # Metric planar UVs in the face's own frame: the two world axes projected onto the face
        # (Gram-Schmidt). Axis-aligned faces keep (p[a0], p[a1]); chamfers keep square texels.
        t0 = _normal([(a == axes[0]) - n[axes[0]]*n[a] for a in range(3)])
        t1 = _normal([(a == axes[1]) - n[axes[1]]*n[a] - t0[axes[1]]*t0[a] for a in range(3)])
        for p in points:
            self.vertices.append(p)
            self.normals.append(n)
            self.uvs.append([sum(p[a]*t[a] for a in range(3))/self.period for t in (t0, t1)])
        for j in range(1, len(points)-1):
            self.indices.extend((start, start+j, start+j+1))

    def grid(self, rows, cols):
        """Quads between consecutive rows of `cols + 1` vertices each."""
        for i in range(rows):
            for j in range(cols):
                a, b = i*(cols+1)+j, (i+1)*(cols+1)+j
                self.indices.extend((a, a+1, b+1, a, b+1, b))

    def flip(self, count):
        """Reverse the winding of the first `count` indices (an axis permutation changed handedness)."""
        idx = self.indices
        for i in range(0, count, 3):
            idx[i+1], idx[i+2] = idx[i+2], idx[i+1]


def _turned(x, y, z, turn):
    """(x, y, z) rotated by `turn` quarter turns about +Z."""
    return list(((x, y, z), (-y, x, z), (-x, -y, z), (y, -x, z))[turn])


def _display(m, spec, size):
    """Single textured quad on the screen face, fitting its image."""
    turn = spec.get("facing", 0)
    axis = 0 if turn % 2 else 1
    w, d, h = size[1-axis], size[axis], size[2]
    for x, y, z in ((w/2, d/2, -h/2), (-w/2, d/2, -h/2), (-w/2, d/2, h/2), (w/2, d/2, h/2)):
        m.vertices.append(_turned(x, y, z, turn))
    m.normals = [[(0, -1, 0, 1)[turn], (1, 0, -1, 0)[turn], 0]]*4
    m.uvs, m.indices = [[0, 0], [1, 0], [1, 1], [0, 1]], [0, 1, 2, 0, 2, 3]


def _cable(m, spec, size):
    """Hexagonal tube along a planar polyline given in envelope fractions."""
    turn, path, r = spec.get("facing", 0), spec["path"], size[2]/2
    w, d = size[:2] if turn % 2 == 0 else size[1::-1]
    path = [[x*(w-2*r), y*(d-2*r)] for x, y in path]
    run = [0.]
    for a, b in zip(path, path[1:]):
        run.append(run[-1] + math.dist(a, b))
    for i, (x, y) in enumerate(path):
        a, b = path[max(0, i-1)], path[min(len(path)-1, i+1)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dy)
        for j in range(7):
            co, si = math.cos(j*math.pi/3), math.sin(j*math.pi/3)
            nx, ny = -dy/length*co, dx/length*co
            m.vertices.append(_turned(x+r*nx, y+r*ny, r*si, turn))
            m.normals.append(_turned(nx, ny, si, turn))
            m.uvs.append([run[i]/m.period, j*math.pi*r/3/m.period])
    m.grid(len(path)-1, 6)


def _bevel(m, spec, size):
    """Box with chamfered edges and corners."""
    half = [s/2 for s in size]
    r = min(spec.get("bevel", .008), min(half)*.8)

    def point(sign, full):
        return [sign[a]*(half[a] if a == full else half[a]-r) for a in range(3)]
    for axis in range(3):
        for side in (-1, 1):
            signs = [s for s in itertools.product((-1, 1), repeat=3) if s[axis] == side]
            m.face([point(s, axis) for s in signs], [side if a == axis else 0 for a in range(3)])
    for free in range(3):
        fixed = [a for a in range(3) if a != free]
        for sides in itertools.product((-1, 1), repeat=2):
            sign = [0, 0, 0]
            for a, side in zip(fixed, sides):
                sign[a] = side
            pts = []
            for side in (-1, 1):
                sign[free] = side
                pts.extend(point(sign, a) for a in fixed)
            m.face(pts, [sign[a] if a != free else 0 for a in range(3)])
    for sign in itertools.product((-1, 1), repeat=3):
        m.face([point(sign, a) for a in range(3)], sign)


def _lathe_uv_radius(profile, size, axis, radial, period):
    """(meridian arc lengths, UV reference radius) of a lathe profile, metric."""
    half = (size[radial[0]] + size[radial[1]]) / 4
    meridian = [0.]
    for (r0, h0), (r1, h1) in zip(profile, profile[1:]):
        meridian.append(meridian[-1] + math.hypot((r1-r0)*half, (h1-h0)*size[axis]))
    r_ref = half * sum((a[0]+b[0])/2*(m1-m0) for a, b, m0, m1 in zip(profile, profile[1:], meridian, meridian[1:])) / max(meridian[-1], 1e-9)
    # Cylinders: whole repeats around the circumference hide the seam when that costs <= 10 % stretch.
    repeats = 2*math.pi*r_ref/period
    if len({r for r, _ in profile}) == 1 and round(repeats) >= 1 and max(round(repeats)/repeats, repeats/round(repeats)) <= 1.10:
        r_ref *= round(repeats)/repeats
    return meridian, r_ref


def _lathe(m, spec, size, ellipsoid=False):
    """Surface of revolution (pots, wheels, clocks); lathes get flat caps."""
    axis = spec.get("axis", 2)  # Axis permutation supports upright pots, horizontal wheels and wall clocks.
    radial = [a for a in range(3) if a != axis]
    profile = spec.get("profile", [[.82, -.5], [1, -.42], [1, .42], [.82, .5]])
    if ellipsoid:
        profile = [[math.sin(math.pi*j/6), -.5*math.cos(math.pi*j/6)] for j in range(7)]
    rings, segments = len(profile), 12
    # Metric UVs: v = meridian arc length, u = arc length at the mean radius (exact on cylinders).
    meridian, r_ref = _lathe_uv_radius(profile, size, axis, radial, m.period)
    for j, (radius, height) in enumerate(profile):
        prev, nxt = profile[max(0, j-1)], profile[min(rings-1, j+1)]
        dr, dz = nxt[0]-prev[0], nxt[1]-prev[1]
        for i in range(segments+1):
            angle = 2*math.pi*i/segments
            co, si = math.cos(angle), math.sin(angle)
            p, n = [0., 0., 0.], [0., 0., 0.]
            p[radial[0]], p[radial[1]], p[axis] = radius*co*size[radial[0]]/2, radius*si*size[radial[1]]/2, height*size[axis]
            n[radial[0]], n[radial[1]], n[axis] = dz*co*2/size[radial[0]], dz*si*2/size[radial[1]], -dr/size[axis]
            m.vertices.append(p)
            m.normals.append(_normal(n))
            m.uvs.append([angle*r_ref/m.period, meridian[j]/m.period])
    m.grid(rings-1, segments)
    if not ellipsoid:
        for j, sign in ((0, -1), (rings-1, 1)):
            m.face([m.vertices[j*(segments+1)+i] for i in range(segments)], [sign if a == axis else 0 for a in range(3)])
    if axis == 1:  # Permuting the axis to Y reverses handedness.
        m.flip((rings-1)*segments*6)


def _handle(m, spec, size):
    """Torus-like curved handle around `axis`."""
    axis = spec.get("axis", 1)
    radial = [a for a in range(3) if a != axis]
    ring = (size[radial[0]] + size[radial[1]]) / 4
    tube = (.27*ring + size[axis]/2) / 2  # Mean tube radius: u along the ring, v around the tube, metric.
    for i in range(13):
        a = i*2*math.pi/12
        for j in range(7):
            b = j*2*math.pi/6
            p, n = [0., 0., 0.], [0., 0., 0.]
            for k, trig in zip(radial, (math.cos(a), math.sin(a))):
                p[k] = size[k]/2 * trig*(.73+.27*math.cos(b))
                n[k] = trig*math.cos(b)
            p[axis], n[axis] = size[axis]/2*math.sin(b), math.sin(b)
            m.vertices.append(p)
            m.normals.append(_normal(n))
            m.uvs.append([a*.73*ring/m.period, b*tube/m.period])
    m.grid(12, 6)
    if axis != 1:
        m.flip(len(m.indices))


def _star(m, spec, size):
    """Five-arm task-chair base: arms in the top 35 mm, casters below their tips, square hub.

    Box collision (the envelope), like chamfered panels.
    """
    h = [s / 2 for s in size]
    reach = min(h[0], h[1]) - .001

    def block(radial, half_len, half_w, z0, z1, theta):
        co, si = math.cos(theta), math.sin(theta)
        corners = {(i, j, k): [(radial + i*half_len)*co - j*half_w*si, (radial + i*half_len)*si + j*half_w*co, z0 if k < 0 else z1]
                   for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)}
        for axis in range(3):
            for side in (-1, 1):
                n = ([co, si, 0.], [-si, co, 0.], [0., 0., 1.])[axis]
                m.face([v for key, v in corners.items() if key[axis] == side], [side*x for x in n])
    for k in range(5):
        theta = math.pi/2 + 2*math.pi*k/5
        block((reach - .03 + .035)/2, (reach - .03 - .035)/2, .02, h[2] - .035, h[2], theta)
        block(reach - .025, .024, .016, -h[2], -h[2] + .065, theta)
    block(0., .045, .045, h[2] - .045, h[2], 0.)


SHAPES = {"display": _display, "cable": _cable, "bevel": _bevel, "lathe": _lathe,
          "ellipsoid": lambda m, spec, size: _lathe(m, spec, size, ellipsoid=True), "handle": _handle, "star": _star}


@lru_cache(maxsize=2048)
def _mesh(key):
    """Mesh buffers for one JSON shape key (see mesh)."""
    spec = json.loads(key)
    if spec["shape"] not in SHAPES:
        raise ValueError(f"Unknown shape: {spec['shape']}")
    m = _Mesh(spec.get("period", .6))
    SHAPES[spec["shape"]](m, spec, spec["size"])
    return dict(vertices=m.vertices, normals=m.normals, uvs=m.uvs, indices=m.indices)


def mesh(part):
    """Visual mesh {vertices, normals, uvs, indices} of a shaped part, cached by shape parameters."""
    key = {k: part[k] for k in ("shape", "size", "bevel", "profile", "axis", "facing", "path") if k in part}
    if "texture" in part and part.get("shape") != "display":  # Displays fit their image; others repeat metrically.
        key["period"] = part["texture"].get("period", .6)
    return _mesh(json.dumps(key, sort_keys=True))


def rotated_axis(part, turn):
    axis = part.get("axis", 1 if part.get("shape") == "handle" else 2)
    return 1-axis if turn % 2 and axis < 2 else axis


def geometry_stats(scene):
    """Visual triangle count and curved-part count of a scene (plain boxes count 12 triangles)."""
    triangles = sum(len(mesh(b)["indices"])//3 if b.get("shape") else 12 for b in scene["boxes"])
    return dict(visual_triangles=triangles, curved_parts=sum(b.get("shape") in ("lathe", "ellipsoid", "handle", "cable") for b in scene["boxes"]),
                max_radial_segments=12)


ZFIGHT_GAP = .005  # Same as indoor.CEILING_SKIN: closer same-facing faces flicker in the depth buffer.
ZFIGHT_NEAR = .0025  # Detection: closer faces z-fight; designed offsets (3 mm skins, 4 mm boards) are kept.
ARCHITECTURE = ("wall", "floor", "ceiling", "stairs")  # never moved to make room for objects or finishes


def flat_faces(part):
    """Planar axis-aligned outer faces of a part: [(axis, side, plane, lo, hi)], lo/hi over the other two axes.
    Curved and rotated parts have none (their surfaces are not coplanar with flat ones)."""
    if tuple(part.get("orientation", (0, 0, 0, 1))) != (0, 0, 0, 1) or part.get("shape") not in (None, "bevel", "display"):
        return []
    c, s = part["center"], part["size"]
    if part.get("shape") == "display":  # One quad on the envelope face it looks out of.
        t = part.get("facing", 0) % 4
        sides = [((1, 0, 1, 0)[t], (1, -1, -1, 1)[t])]
    else:
        sides = [(a, d) for a in range(3) for d in (-1, 1)]
    faces = []
    for a, d in sides:
        other = [k for k in range(3) if k != a]
        faces.append((a, d, c[a] + d*s[a]/2, [c[k] - s[k]/2 for k in other], [c[k] + s[k]/2 for k in other]))
    return faces


def coplanar_pairs(scene, gap=ZFIGHT_NEAR):
    """Parts whose same-facing flat faces are closer than gap and share visible area, i.e. z-fight.
    Shared areas pressed against or inside another part (a wall foot on a slab) are hidden and skipped.
    Only parts of the same storey are compared, so a storey never depends on the storeys above it.
    Returns [(small, big, axis, side)]: small is the part with the smaller face."""
    boxes, planes = scene["boxes"], {}
    for i, part in enumerate(scene["boxes"]):
        for f in flat_faces(part):
            planes.setdefault(f[:2], []).append((f[2], i, f))
    for faces in planes.values():
        faces.sort(key=lambda x: x[0])

    # Solid boxes (plain and chamfered, axis-aligned) on a 1 m grid: a shared area that lies on or inside
    # one of them, on the side the faces look at, is never seen (wall tops inside a slab, feet on a floor).
    solids, cell = {}, 1.
    for i, part in enumerate(scene["boxes"]):
        if part.get("shape") in (None, "bevel") and tuple(part.get("orientation", (0, 0, 0, 1))) == (0, 0, 0, 1):
            lo3 = [c - h/2 for c, h in zip(part["center"], part["size"])]
            hi3 = [c + h/2 for c, h in zip(part["center"], part["size"])]
            for gx in range(math.floor(lo3[0]/cell), math.floor(hi3[0]/cell) + 1):
                for gy in range(math.floor(lo3[1]/cell), math.floor(hi3[1]/cell) + 1):
                    solids.setdefault((part["level"], gx, gy), []).append((i, lo3, hi3))

    def covered(a, d, z, lo, hi, pair, level):
        other = [k for k in range(3) if k != a]
        mid = [0., 0., 0.]
        mid[a], mid[other[0]], mid[other[1]] = z, (lo[0] + hi[0])/2, (lo[1] + hi[1])/2
        for k, l3, h3 in solids.get((level, math.floor(mid[0]/cell), math.floor(mid[1]/cell)), []):
            if k in pair:
                continue
            outward = h3[a] > z + 1e-4 and l3[a] <= z + 1e-4 if d > 0 else l3[a] < z - 1e-4 and h3[a] >= z - 1e-4
            if outward and all(l3[o] <= lo[m] + 1e-4 and h3[o] >= hi[m] - 1e-4 for m, o in enumerate(other)):
                return True
        return False
    pairs = []

    def sweep(run, a, d):
        run.sort(key=lambda x: x[2][3][0])  # sweep along the first in-plane axis
        for n, (z, i, f) in enumerate(run):
            for z2, j, g in run[n+1:]:
                if g[3][0] >= f[4][0] - 1e-4:
                    break
                lo = [max(f[3][m], g[3][m]) for m in range(2)]
                hi = [min(f[4][m], g[4][m]) for m in range(2)]
                if i != j and boxes[i]["level"] == boxes[j]["level"] and abs(z2 - z) < gap - 1e-6 and hi[1] - lo[1] > 1e-4 and hi[0] - lo[0] > 1e-4 and \
                        not covered(a, d, max(z, z2) if d > 0 else min(z, z2), lo, hi, (i, j), boxes[i]["level"]):
                    # Objects and finishes give way to architecture; otherwise the smaller face moves.
                    rank = [(boxes[k]["kind"] not in ARCHITECTURE, -(h[4][0]-h[3][0])*(h[4][1]-h[3][1])) for k, h in ((i, f), (j, g))]
                    pairs.append((i, j, a, d) if rank[0] >= rank[1] else (j, i, a, d))
    for (a, d), faces in planes.items():
        run = [faces[0]] if faces else []
        for prev, item in zip(faces, faces[1:]):  # runs of planes chained closer than gap
            if item[0] - prev[0] >= gap - 1e-6:  # a face set exactly gap apart by separate_coplanar is fine
                sweep(run, a, d)
                run = []
            run.append(item)
        sweep(run, a, d)
    return pairs


def separate_coplanar(scene, gap=ZFIGHT_GAP, passes=8):
    """Leave a gap between z-fighting faces (coplanar_pairs). Larger faces (and architecture) are placed
    first; a smaller part's main face steps out to gap in front of every face it overlaps, so stacks
    (skin, frame, sign) step out instead of trading places. Edge and horizontal faces, and the tops of
    walkable parts (floor, stairs), step back gap behind instead: openings stay clear, floors never rise.
    Only visuals change: moved parts keep their generated collision box (collision_center/_size).
    Returns the number of parts adjusted."""
    boxes, moved = scene["boxes"], 0
    generated = [(list(p["center"]), list(p["size"])) for p in boxes]
    start = lambda i, a, d: generated[i][0][a] + d * generated[i][1][a] / 2  # face plane as generated
    walkable = lambda p: p["kind"] in ("floor", "stairs")
    for _ in range(passes):
        # Pairs already set apart (within 2 gaps) stay in the graph: a smaller face follows a larger
        # one that moves, instead of becoming coplanar with it again (growth cascades over passes).
        pairs = coplanar_pairs(scene, 2 * gap)
        plane = lambda i, a, d: boxes[i]["center"][a] + d * boxes[i]["size"][a] / 2
        if not any(abs(plane(i, a, d) - plane(j, a, d)) < ZFIGHT_NEAR - 1e-6 for i, j, a, d in pairs):
            break
        bigs = {}
        for small, big, a, d in pairs:
            bigs.setdefault((small, a, d), []).append(big)
        final = {}

        def place(i, a, d, seen=()):
            """Final plane of part i's (a, d) face: larger overlapping faces are placed first."""
            if (i, a, d) not in final:
                z = plane(i, a, d)
                for b in bigs.get((i, a, d), []):
                    if b in seen:
                        continue  # equal-area cycle: keep it as is
                    zb = place(b, a, d, seen + (i,))
                    # Only a part's main face (normal along its thinnest axis: a sign's front, a skin's
                    # face) steps out; edge faces step back, so door and window openings stay clear.
                    main = a < 2 and a == min((0, 1), key=lambda k: boxes[i]["size"][k])  # horizontal faces step back
                    floor = a == 2 and d > 0 and walkable(boxes[i])  # floors and treads never rise (collision never moves)
                    # Too thin to step back (a 5 mm ceiling skin): it steps out instead, except on floors.
                    back = floor or (not main and boxes[i]["size"][a] > 2 * gap)
                    offset = d * (start(i, a, d) - start(b, a, d))  # as generated: + in front, - behind
                    if abs(offset) < ZFIGHT_NEAR:
                        need = gap  # z-fighting pair: set it apart
                    elif (offset < 0) == back:
                        need = abs(offset)  # designed offset on the right side: keep it if b moved
                    else:
                        continue
                    z = min(z * d, zb * d - need) * d if back else max(z * d, zb * d + need) * d
                if abs(z - start(i, a, d)) > 3 * gap + 1e-9:
                    z = plane(i, a, d)  # would move more than 3 gaps from where it was generated: leave it
                final[(i, a, d)] = z
            return final[(i, a, d)]
        for i, a, d in sorted(bigs, key=lambda k: -boxes[k[0]]["size"][(k[1] + 1) % 3] * boxes[k[0]]["size"][(k[1] + 2) % 3]):
            t = d * (place(i, a, d) - plane(i, a, d))  # signed growth along the outward normal
            p = boxes[i]
            if abs(t) < 1e-9 or p["size"][a] + t <= gap / 2:
                continue
            p.setdefault("collision_size", list(p["size"]))  # physics keeps the generated box exactly
            p.setdefault("collision_center", list(p["center"]))
            p["size"] = [v + t if k == a else v for k, v in enumerate(p["size"])]
            p["center"] = [v + d * t / 2 if k == a else v for k, v in enumerate(p["center"])]
            moved += 1
    return moved
