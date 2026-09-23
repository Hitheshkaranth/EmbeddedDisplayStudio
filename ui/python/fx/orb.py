"""ui/python/fx/orb.py -- Thinking Orbs: nine "thinking" states drawn from dots.

FROZEN CONTRACT (UI FX swarm, 2026-09-23). Owner: W-B. Port of libdev
packages/thinking-orbs: engine/*.ts is pure maths (no DOM) and translates
line for line; presets.ts / profiles.ts (and spec/orbs-spec.json) hold the
tuned numbers per state and size. No physics: every state is a pure
function of time. Canvas 2D only (filled circles; straight lines for
'connecting'), so QPainter reproduces it exactly.

States -> engine modes:
    working->orbits  searching->globe  solving->rubik  listening->wave
    connecting->web  weaving->braid  composing->ribbon  breathing->ring
    shaping->morph
Sizes: the presets are tuned for 64, 32 and 20 px (32 interpolated in log
space between 64 and 20, as presets.ts does); other sizes use the nearest.
Ink is greyscale from each dot's `white` (dark theme: grey = (1-white)*255,
light theme: grey = white*255), or a tint colour (see ThinkingOrb.color).
Use JS rounding (fx.js_round) where the source uses Math.round.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPen

from ui.python.fx import FxWidget, hash01, js_round

STATES = ("working", "searching", "solving", "listening", "connecting",
          "weaving", "composing", "breathing", "shaping")
LABELS = {"working": "Working…", "searching": "Searching…", "solving": "Solving…",
          "listening": "Listening…", "connecting": "Connecting…", "weaving": "Weaving…",
          "composing": "Composing…", "breathing": "Thinking…", "shaping": "Shaping…"}
SIZES = (20, 32, 64)


@dataclass
class Dot:
    x: float
    y: float
    r: float
    white: float
    a: float = 1.0
    z: float = 0.0


@dataclass
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    w: float
    white: float
    a: float = 1.0


# ------------------------------------------------------------------ engine
# engine/core.ts

_PI = math.pi


def _hash(a, b):
    return hash01(a, b)


def _frac(x):
    return x - math.floor(x)


def _lerp(a, b, f):
    return a + (b - a) * f


def _vnoise(x, y):
    xi = math.floor(x)
    yi = math.floor(y)
    fx = x - xi
    fy = y - yi
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    a = _hash(xi, yi)
    b = _hash(xi + 1, yi)
    c = _hash(xi, yi + 1)
    d = _hash(xi + 1, yi + 1)
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy


def _fib_dir(i, n):
    golden = _PI * (3 - math.sqrt(5))
    y = 1 - (2 * (i + 0.5)) / n
    rad = math.sqrt(1 - y * y)
    a = i * golden
    return (rad * math.cos(a), y, rad * math.sin(a))


def _angle_delta(a, b):
    return math.atan2(math.sin(a - b), math.cos(a - b))


def _make_proj(yaw, tilt, cx, cy, scale):
    st = math.sin(tilt)
    ct = math.cos(tilt)
    sy = math.sin(yaw)
    cyw = math.cos(yaw)

    def proj(x, y, z):
        x1 = x * cyw + z * sy
        z1 = -x * sy + z * cyw
        y1 = y * ct - z1 * st
        z2 = y * st + z1 * ct
        return cx + x1 * scale, cy - y1 * scale, z2
    return proj


def _radius_scale(size, pow_):
    return (size / 300) ** pow_


def _finalize(dots, lines, r_min=None):
    r_min = 0.3 if r_min is None else r_min
    visible = []
    for d in dots:
        if d.a < 0.02:
            continue
        if d.r < r_min:
            d.r = r_min
        visible.append(d)
    visible.sort(key=lambda d: d.z)          # stable, like Array.sort
    return visible, [ln for ln in lines if ln.a >= 0.02]


# ------------------------------------------------------------------ orbits.ts

def _frame_orbits(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.82
    pt = _make_proj(t * 0.12, 0.3, cx, cy, 1)
    rs = _radius_scale(size, o.get("rsPow", 0.6))
    dots = []
    orbit_n = o.get("orbitN", 12)
    ghost_n = o.get("ghostN", 40)
    particles = o.get("particles", 3)
    ghost_r = o.get("ghostR", 0.9) * rs
    ghost_a = o.get("ghostA", 0.5)
    part_r = o.get("partR", 1.2)
    part_rd = o.get("partRDepth", 1.6)
    for orb in range(orbit_n):
        h1 = _hash(orb, 1.7)
        h2 = _hash(orb, 5.2)
        h3 = _hash(orb, 8.9)
        ro = R * (0.45 + 0.52 * h1)
        th = h1 * 2 * _PI
        phi = math.acos(2 * h2 - 1)
        nx = math.sin(phi) * math.cos(th)
        ny = math.cos(phi)
        nz = math.sin(phi) * math.sin(th)
        ux = -ny
        uy = nx
        uz = 0.0
        ul = max(1e-6, math.sqrt(ux * ux + uy * uy))
        ux /= ul
        uy /= ul
        vx = ny * uz - nz * uy
        vy = nz * ux - nx * uz
        vz = nx * uy - ny * ux
        speed = (0.25 + 0.55 * h3) * (1 if h3 > 0.5 else -1)
        for k in range(ghost_n):
            a = (k / ghost_n) * 2 * _PI
            ca, sa = math.cos(a), math.sin(a)
            px, py, z = pt((ux * ca + vx * sa) * ro, (uy * ca + vy * sa) * ro, (uz * ca + vz * sa) * ro)
            depth = (z / ro + 1) / 2
            dots.append(Dot(px, py, ghost_r, 0.72, ghost_a * (0.4 + 0.6 * depth), z))
        for m in range(particles):
            a = t * speed + (m / particles) * 2 * _PI + h2 * 6
            ca, sa = math.cos(a), math.sin(a)
            px, py, z = pt((ux * ca + vx * sa) * ro, (uy * ca + vy * sa) * ro, (uz * ca + vz * sa) * ro)
            depth = (z / ro + 1) / 2
            dots.append(Dot(px, py, (part_r + part_rd * depth) * rs, 0.3 - 0.22 * depth, 1.0, z))
    return _finalize(dots, [], o.get("rMin"))


# ------------------------------------------------------------------ lattice.ts

def _solve_cycle(time_, count, slot_dur, rest):
    cyc = 2 * count * slot_dur + rest
    tc = math.fmod(time_, cyc)               # JS %
    amount = [0.0] * count
    active = -1
    if tc < 2 * count * slot_dur:
        slot = math.floor(tc / slot_dur)
        p = (tc - slot * slot_dur) / slot_dur
        cl = min(1.0, p / 0.7)
        ep = 1 - (1 - cl) ** 3
        if slot < count:
            for i in range(slot):
                amount[i] = 1.0
            amount[slot] = ep
            active = slot
        else:
            u = 2 * count - 1 - slot
            for i in range(u):
                amount[i] = 1.0
            amount[u] = 1 - ep
            active = u
    return amount, active


def _make_moves(count):
    moves = []
    for i in range(count):
        axis = min(2, math.floor(_hash(i, 2.3) * 3))
        lo = -1.0 + 0.5 * min(3, math.floor(_hash(i, 5.9) * 4))
        direction = 1 if _hash(i, 7.7) < 0.5 else -1
        moves.append((axis, lo, lo + 0.5, (direction * _PI) / 2))
    return moves


def _apply_moves(x, y, z, moves, amount, active):
    in_active = False
    for i, (axis, lo, hi, ang) in enumerate(moves):
        if amount[i] <= 0:
            continue
        coord = x if axis == 0 else y if axis == 1 else z
        if coord < lo or coord >= hi:
            continue
        if i == active:
            in_active = True
        a = ang * amount[i]
        ca = math.cos(a)
        sa = math.sin(a)
        if axis == 0:
            y2 = y * ca - z * sa
            z = y * sa + z * ca
            y = y2
        elif axis == 1:
            x2 = x * ca + z * sa
            z = -x * sa + z * ca
            x = x2
        else:
            x2 = x * ca - y * sa
            y = x * sa + y * ca
            x = x2
    return x, y, z, in_active


def _frame_globe(size, t, o):
    spin = 0.5
    cx = cy = size / 2
    radius = (size / 2) * 0.82
    tilt = 0.4 + 0.06 * math.sin(t * 0.35)
    pt = _make_proj(t * spin, tilt, cx, cy, radius)
    scan = t * (spin + (1.7 - spin) * o.get("scanMul", 1))
    rs = _radius_scale(size, o.get("rsPow", 0.6))
    dim_base = o.get("dimBase", 1)
    r_base, r_depth, r_boost = o.get("rBase", 0.6), o.get("rDepth", 1.7), o.get("rBoost", 1)
    ink_far, ink_span = o.get("inkFar", 0.62), o.get("inkSpan", 0.54)
    dots = []
    lat_rings = o.get("latRings", 17)
    lon_density = o.get("lonDensity", 44)
    for li in range(lat_rings + 1):
        lat = -_PI / 2 + (li / lat_rings) * _PI
        cos_lat = math.cos(lat)
        sin_lat = math.sin(lat)
        lon_count = max(1, js_round(abs(cos_lat) * lon_density))
        for lj in range(lon_count):
            lon = (lj / lon_count) * 2 * _PI
            px, py, z = pt(cos_lat * math.cos(lon), sin_lat, cos_lat * math.sin(lon))
            depth = (z + 1) / 2
            d = _angle_delta(lon + t * spin, scan)
            boost = math.exp(-(d * d) / 0.18) * max(0.0, z)
            dots.append(Dot(px, py, (r_base + r_depth * depth + r_boost * boost) * rs,
                            ink_far - ink_span * depth,
                            dim_base + (1 - dim_base) * min(1.0, boost), z))
    return _finalize(dots, [], o.get("rMin"))


def _frame_rubik(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.82
    pt = _make_proj(t * 0.55, 0.35 + 0.1 * math.sin(t * 0.9), cx, cy, R)
    rs = _radius_scale(size, o.get("rsPow", 0.6))
    move_count = o.get("moveCount", 14)
    moves = _make_moves(move_count)
    amount, active = _solve_cycle(t, move_count, 0.42, 1.2)
    r_base, r_depth, r_active = o.get("rBase", 0.6), o.get("rDepth", 1.7), o.get("rActive", 0.3)
    ink_far, ink_span = o.get("inkFar", 0.62), o.get("inkSpan", 0.54)
    dots = []
    lat_rings = o.get("latRings", 15)
    lon_density = o.get("lonDensity", 40)
    for li in range(lat_rings + 1):
        lat = -_PI / 2 + (li / lat_rings) * _PI
        cos_lat = math.cos(lat)
        sin_lat = math.sin(lat)
        lon_count = max(1, js_round(abs(cos_lat) * lon_density))
        for lj in range(lon_count):
            lon = (lj / lon_count) * 2 * _PI
            x, y, z, in_active = _apply_moves(cos_lat * math.cos(lon), sin_lat, cos_lat * math.sin(lon),
                                              moves, amount, active)
            px, py, zr = pt(x, y, z)
            depth = (zr + 1) / 2
            dots.append(Dot(px, py, (r_base + r_depth * depth + (r_active if in_active else 0)) * rs,
                            ink_far - ink_span * depth - (0.14 if in_active else 0), 1.0, zr))
    return _finalize(dots, [], o.get("rMin"))


def _frame_wave(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.874
    pt = _make_proj(t * 0.18, 0.38, cx, cy, 1)
    rs = _radius_scale(size, o.get("rsPow", 0.6))
    r_base, r_depth = o.get("rBase", 0.6), o.get("rDepth", 1.7)
    dots = []
    rings = o.get("rings", 15)
    lon_density = o.get("lonDensity", 40)
    for ri in range(rings + 1):
        lat = -_PI / 2 + (ri / rings) * _PI
        cos_lat = math.cos(lat)
        sin_lat = math.sin(lat)
        w = 0.62 * math.sin(t * 2.1 - ri * 0.52) + 0.38 * math.sin(t * 1.27 + ri * 0.83)
        rr = R * (0.88 + 0.105 * w)
        lon_count = max(1, js_round(abs(cos_lat) * lon_density))
        crest = max(0.0, w)
        for lj in range(lon_count):
            lon = (lj / lon_count) * 2 * _PI
            px, py, z = pt(cos_lat * math.cos(lon) * rr, sin_lat * rr, cos_lat * math.sin(lon) * rr)
            depth = (z / R + 1) / 2
            dots.append(Dot(px, py, (r_base + r_depth * depth) * (1 + 0.4 * crest) * rs,
                            0.66 - 0.56 * depth - 0.1 * crest, 1.0, z))
    return _finalize(dots, [], o.get("rMin"))


# ------------------------------------------------------------------ web.ts

def _frame_web(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.8 * o.get("spread", 1)
    pt = _make_proj(t * 0.12, 0.32, cx, cy, R)
    rs = _radius_scale(size, o.get("rsPow", 0.6))
    node_n = o.get("nodeN", 30)
    thr = o.get("thr", 0.72)
    node_r = o.get("nodeR", 1.4)
    node_rd = o.get("nodeRDepth", 1.8)

    nodes = []
    for i in range(node_n):
        d = _fib_dir(i, node_n)
        x = d[0] + 0.3 * (_vnoise(i * 0.31 + 9, t * 0.24) - 0.5) * 2
        y = d[1] + 0.3 * (_vnoise(i * 0.53 + 27, t * 0.21) - 0.5) * 2
        z = d[2] + 0.3 * (_vnoise(i * 0.77 + 55, t * 0.27) - 0.5) * 2
        ln = math.sqrt(x * x + y * y + z * z)
        nodes.append((x / ln, y / ln, z / ln))
    projected = [pt(*n) for n in nodes]

    lines = []
    dots = []
    line_w = max(0.6, o.get("lineW", 0.8) * rs)
    for i in range(node_n):
        ni = nodes[i]
        for j in range(i + 1, node_n):
            nj = nodes[j]
            dx = ni[0] - nj[0]
            dy = ni[1] - nj[1]
            dz = ni[2] - nj[2]
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if dist >= thr:
                continue
            x1, y1, z1 = projected[i]
            x2, y2, z2 = projected[j]
            depth = ((z1 + z2) / 2 + 1) / 2
            lines.append(Line(x1, y1, x2, y2, line_w, 0.42, (1 - dist / thr) * (0.3 + 0.55 * depth)))

    for i in range(node_n):
        px, py, z = projected[i]
        depth = (z + 1) / 2
        pulse = 1 + 0.25 * math.sin(t * 1.4 + i * 2.7)
        dots.append(Dot(px, py, (node_r + node_rd * depth) * pulse * rs, 0.55 - 0.45 * depth, 1.0, z))

    signals = o.get("signals", 5)
    for s in range(signals):
        seg = math.floor(t * 0.55 + s * 7.31)
        a = math.floor(_hash(seg, s * 3.1 + 1.7) * node_n)
        b = math.floor(_hash(seg, s * 5.7 + 4.2) * node_n)
        if a == b:
            continue
        f = _frac(t * 0.55 + s * 7.31)
        x = _lerp(nodes[a][0], nodes[b][0], f)
        y = _lerp(nodes[a][1], nodes[b][1], f)
        z = _lerp(nodes[a][2], nodes[b][2], f)
        ln = max(1e-6, math.sqrt(x * x + y * y + z * z))
        px, py, zr = pt(x / ln, y / ln, z / ln)
        depth = (zr + 1) / 2
        dots.append(Dot(px, py, (node_r * 1.5 + node_rd * depth) * rs, 0.05, 0.5 + 0.5 * depth, zr))

    return _finalize(dots, lines, o.get("rMin"))


# ------------------------------------------------------------------ braid.ts

def _ghost_sphere(dots, pt, R, n, rs):
    for i in range(n):
        d = _fib_dir(i, n)
        px, py, z = pt(d[0] * R, d[1] * R, d[2] * R)
        depth = (z / R + 1) / 2
        dots.append(Dot(px, py, 0.8 * rs, 0.78, 0.1 + 0.22 * depth, z))


def _frame_braid(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.76
    pt = _make_proj(t * 0.4, 0.3, cx, cy, 1)
    rs = _radius_scale(size, o.get("rsPow", 0.6))
    dots = []
    _ghost_sphere(dots, pt, R, o.get("ghostN", 150), rs)
    strand_n = o.get("strandN", 52)
    turns = o.get("turns", 3)
    r_base, r_depth = o.get("rBase", 1.2), o.get("rDepth", 1.8)
    for s in range(3):
        phase = (s / 3) * 2 * _PI
        for i in range(strand_n):
            u = (_frac(i / strand_n + t * 0.045) * 2 - 1) * 0.96
            surf = math.sqrt(max(0.0, 1 - u * u))
            end_fade = min(1.0, (1 - abs(u)) / 0.1)
            a = u * _PI * turns + phase
            weave = 1 + 0.075 * math.sin(u * _PI * turns * 2 + phase * 2 + t * 0.8)
            rr = surf * R * weave
            px, py, zr = pt(math.cos(a) * rr, u * R * weave, math.sin(a) * rr)
            depth = (zr / R + 1) / 2
            dots.append(Dot(px, py, (r_base + r_depth * depth) * rs, 0.55 - 0.45 * depth,
                            end_fade * (0.45 + 0.55 * depth), zr))
    return _finalize(dots, [], o.get("rMin"))


# ------------------------------------------------------------------ ribbon.ts (+ ring)

def _frame_ribbon(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.78
    spin = o.get("spin", 1)
    cam_tilt = 0.3
    pt = _make_proj(t * 0.1 * spin, cam_tilt, cx, cy, 1)
    rs = _radius_scale(size, o.get("rsPow", 0.6))
    dots = []
    _ghost_sphere(dots, pt, R, o.get("ghostN", 150), rs)

    face_on = bool(o.get("faceOn"))
    ya = t * 0.24 * spin
    ta = -cam_tilt if face_on else 0.55 + 0.3 * math.sin(t * 0.18) * spin
    ux = math.cos(ya)
    uy = 0.0
    uz = math.sin(ya)
    vx = -uz * math.sin(ta)
    vy = math.cos(ta)
    vz = ux * math.sin(ta)
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx

    wob_mul = o.get("wobMul", 1)
    wob_amp = 0.23 * wob_mul
    base_r = R / (1 + 0.85 * wob_amp) if face_on else R

    base_lanes = o.get("lanes", 5)
    segs = o.get("segs", 88)
    lanes = max(1, js_round(base_lanes * o.get("bandMul", 1)))
    r_base, r_depth = o.get("rBase", 1.1), o.get("rDepth", 1.7)
    half = (lanes - 1) / 2
    for w in range(lanes):
        lane_off = (w - half) * 0.075
        edge = abs(w - half) / max(1, half)
        for k in range(segs):
            a = (k / segs) * 2 * _PI
            wob = (0.16 * math.sin(a * 3 - t * 1.7 + w * 0.22) + 0.07 * math.sin(a * 5 + t * 1.1)) * wob_mul
            radial = 1 + wob if face_on else 1
            off = lane_off if face_on else lane_off + wob
            ca, sa = math.cos(a), math.sin(a)
            x = ux * ca + vx * sa + nx * off
            y = uy * ca + vy * sa + ny * off
            z = uz * ca + vz * sa + nz * off
            ln = math.sqrt(x * x + y * y + z * z)
            rr = base_r * radial
            px, py, zr = pt((x / ln) * rr, (y / ln) * rr, (z / ln) * rr)
            depth = (zr / R + 1) / 2
            dots.append(Dot(px, py, (r_base + r_depth * depth) * (1 - 0.25 * edge) * rs,
                            0.52 - 0.44 * depth + 0.18 * edge, 0.4 + 0.6 * depth, zr))
    return _finalize(dots, [], o.get("rMin"))


# ------------------------------------------------------------------ morph.ts

def _smooth_e(x):
    return x * x * (3 - 2 * x)


def _poly_path(verts):
    V = len(verts)
    L = []
    total = 0.0
    for i in range(V):
        a = verts[i]
        b = verts[(i + 1) % V]
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        L.append(ln)
        total += ln

    def path(f):
        target = f * total
        i = 0
        while target > L[i] and i < V - 1:
            target -= L[i]
            i += 1
        a = verts[i]
        b = verts[(i + 1) % V]
        ff = min(1.0, target / L[i]) if L[i] else 0.0
        return (a[0] + (b[0] - a[0]) * ff, a[1] + (b[1] - a[1]) * ff)
    return path


def _circle_path(f):
    a = -_PI / 2 + f * 2 * _PI
    return (math.cos(a) * 0.24, math.sin(a) * 0.24)


_CYCLE = (_circle_path,
          _poly_path(((0.0, -0.26), (0.24, 0.16), (-0.24, 0.16))),
          # 5-vertex walk so the path starts at top-centre like the others
          _poly_path(((0, -0.2), (0.2, -0.2), (0.2, 0.2), (-0.2, 0.2), (-0.2, -0.2))))
_M = 160
# The three outlines sampled once (the source samples them every frame;
# the samples are the same numbers).
_CYCLE_PTS = tuple(tuple(p(i / _M) for i in range(_M)) for p in _CYCLE)
_HOLD = 1.4
_MORPH = 0.9
_SEG = _HOLD + _MORPH


def _frame_morph(size, t, o):
    K = len(_CYCLE)
    tc = math.fmod(t, _SEG * K)
    shape = o.get("shape")
    held = math.floor(shape) if shape is not None and 0 <= shape < K else -1
    k = held if held >= 0 else math.floor(tc / _SEG)
    local = math.fmod(t, _SEG) if held >= 0 else tc - k * _SEG
    m = 0.0 if held >= 0 else (_smooth_e((local - _HOLD) / _MORPH) if local > _HOLD else 0.0)
    sprd = o.get("spread", 1)

    pa = _CYCLE_PTS[k]
    pb = pa if held >= 0 else _CYCLE_PTS[(k + 1) % K]
    pts = [((a[0] + (b[0] - a[0]) * m) * sprd, (a[1] + (b[1] - a[1]) * m) * sprd)
           for a, b in zip(pa, pb)]
    L = []
    total = 0.0
    for i in range(_M):
        a = pts[i]
        b = pts[(i + 1) % _M]
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        L.append(ln)
        total += ln

    n = max(6, js_round(34 * o.get("iconD", 1)))
    re = o.get("rDot", 0.021) * 1.35 * sprd
    pulse = 1 + 0.02 * math.sin(local * 3.1)
    dots = []
    c2 = size / 2
    seg = 0
    acc = 0.0
    r = max(0.35, re * size)
    for k2 in range(n):
        target = (k2 / n) * total
        while acc + L[seg] < target and seg < _M - 1:
            acc += L[seg]
            seg += 1
        a = pts[seg]
        b = pts[(seg + 1) % _M]
        f = min(1.0, (target - acc) / L[seg]) if L[seg] else 0.0
        x = (a[0] + (b[0] - a[0]) * f) * pulse
        y = (a[1] + (b[1] - a[1]) * f) * pulse
        dots.append(Dot(c2 + x * size, c2 + y * size, r, 0.1, 1.0, 0.0))
    return _finalize(dots, [], o.get("rMin"))


# ------------------------------------------------------------------ profiles.ts / presets.ts

_STATE_TO_MODE = {"working": "orbits", "searching": "globe", "solving": "rubik",
                  "listening": "wave", "connecting": "web", "weaving": "braid",
                  "composing": "ribbon", "breathing": "ring", "shaping": "morph"}

_MODE_FRAMES = {"orbits": _frame_orbits, "globe": _frame_globe, "rubik": _frame_rubik,
                "wave": _frame_wave, "web": _frame_web, "braid": _frame_braid,
                "ribbon": _frame_ribbon, "ring": _frame_ribbon, "morph": _frame_morph}

_COUNT_PAIRS = (("latRings", "lonDensity"), ("rings", "lonDensity"), ("lanes", "segs"))
_COUNT_KEYS = ("orbitN", "ghostN", "nodeN", "strandN", "signals")
_ICON_DENSITY_KEYS = ("iconD",)
_RADIUS_KEYS = ("rBase", "rDepth", "rActive", "rDot", "ghostR", "partR", "partRDepth",
                "nodeR", "nodeRDepth")

_BASE_PROFILES = {
    "globe": {"latRings": 17, "lonDensity": 44, "rBase": 0.6, "rDepth": 1.7, "rBoost": 1.0,
              "inkFar": 0.62, "inkSpan": 0.54, "rsPow": 0.6, "rMin": 0.3},
    "orbits": {"orbitN": 12, "ghostN": 40, "ghostR": 0.9, "ghostA": 0.5, "particles": 3,
               "partR": 1.2, "partRDepth": 1.6, "rsPow": 0.6, "rMin": 0.3},
    "rubik": {"latRings": 15, "lonDensity": 40, "moveCount": 14, "rBase": 0.6, "rDepth": 1.7,
              "rActive": 0.3, "inkFar": 0.62, "inkSpan": 0.54, "rsPow": 0.6, "rMin": 0.3},
    "wave": {"rings": 15, "lonDensity": 40, "rBase": 0.6, "rDepth": 1.7, "rsPow": 0.6, "rMin": 0.3},
    "web": {"nodeN": 30, "thr": 0.72, "signals": 5, "nodeR": 1.4, "nodeRDepth": 1.8, "lineW": 0.8,
            "rsPow": 0.6, "rMin": 0.3},
    "braid": {"strandN": 52, "turns": 3.0, "ghostN": 150, "rBase": 1.2, "rDepth": 1.8,
              "rsPow": 0.6, "rMin": 0.3},
    "ribbon": {"lanes": 5, "segs": 88, "ghostN": 150, "rBase": 1.1, "rDepth": 1.7,
               "rsPow": 0.6, "rMin": 0.3},
    # ring shares ribbon's geometry; faceOn cancels the camera tilt and moves
    # the undulation onto the radius, and there is no ghost sphere behind it
    "ring": {"lanes": 5, "segs": 88, "ghostN": 0, "faceOn": 1, "rBase": 1.1, "rDepth": 1.7,
             "rsPow": 0.6, "rMin": 0.3},
    "morph": {"rDot": 0.021, "iconD": 1, "rMin": 0.25},
}

# (speed, count, size, extra) per mode and tuned size. The 32 rows are
# presets.ts' own log-space interpolation between 64 and 20, as shipped.
_PRESETS = {
    "orbits": {64: (1.885, 1, 1, None), 32: (2.9072, 0.4251, 1.6849, None), 20: (3.9, 0.238, 2.4, None)},
    "globe": {64: (2.015, 0.42, 1.15, {"scanMul": 4.08, "dimBase": 0.45}),
              32: (2.3803, 0.1839, 1.4769, {"scanMul": 4.2301, "dimBase": 0.45}),
              20: (2.665, 0.105, 1.75, {"scanMul": 4.335, "dimBase": 0.45})},
    "rubik": {64: (1.82, 0.35, 1.05, None), 32: (1.8964, 0.1537, 1.4951, None), 20: (1.95, 0.088, 1.9, None)},
    "wave": {64: (4.388, 0.341, 1, None), 32: (4.1512, 0.169, 1.3232, None), 20: (3.998, 0.105, 1.6, None)},
    "web": {64: (3.315, 1.35, 0.95, None), 32: (5.0104, 0.4942, 1.2571, None), 20: (6.63, 0.25, 1.52, None)},
    "braid": {64: (1.625, 0.5, 1, None), 32: (2.2234, 0.2056, 1.2011, None), 20: (2.75, 0.1125, 1.36, None)},
    "ribbon": {64: (2.34, 0.25, 0.85, {"spin": 0, "bandMul": 3.9, "wobMul": 1}),
               32: (2.7776, 0.0969, 0.9766, {"spin": 0, "bandMul": 4.49, "wobMul": 1}),
               20: (3.12, 0.051, 1.073, {"spin": 0, "bandMul": 4.94, "wobMul": 1})},
    "ring": {64: (3.24, 0.25, 0.956, {"spin": 0, "bandMul": 3.627, "wobMul": 0.368}),
             32: (3.5517, 0.0678, 1.31, {"spin": 0, "bandMul": 3.8265, "wobMul": 0.4751}),
             20: (3.78, 0.028, 1.622, {"spin": 0, "bandMul": 3.968, "wobMul": 0.565})},
    "morph": {64: (2.405, 0.702, 0.395, {"spread": 1.45}),
              32: (2.2057, 0.5937, 0.6916, {"spread": 1.45}),
              20: (2.08, 0.53, 1.011, {"spread": 1.45})},
}


def _scale_counts(opts, scale):
    out = dict(opts)
    done = set()
    rt = math.sqrt(scale)
    for a, b in _COUNT_PAIRS:
        va, vb = out.get(a), out.get(b)
        if va is not None and vb is not None and a not in done and b not in done:
            out[a] = max(2, js_round(va * rt))
            out[b] = max(2, js_round(vb * rt))
            done.add(a)
            done.add(b)
    for k in _COUNT_KEYS:
        v = out.get(k)
        # 0 means the mode opted out of that layer (ring has no ghost sphere)
        if v is not None and v != 0 and k not in done:
            out[k] = max(1, js_round(v * scale))
    for k in _ICON_DENSITY_KEYS:
        v = out.get(k)
        if v is not None:
            out[k] = max(0.02, v * scale)
    return out


def _scale_radii(opts, scale):
    out = dict(opts)
    for k in _RADIUS_KEYS:
        if out.get(k) is not None:
            out[k] = out[k] * scale
    out["rSizeMul"] = out.get("rSizeMul", 1) * scale
    return out


def _preset_size(size):
    """The tuned size nearest to `size` (ties go to the larger)."""
    return min(SIZES, key=lambda s: (abs(s - size), -s))


_resolved: dict = {}


def _resolve(state, size):
    key = (state, _preset_size(size))
    hit = _resolved.get(key)
    if hit is not None:
        return hit
    if state not in _STATE_TO_MODE:
        raise ValueError(f"unknown orb state {state!r}")
    mode = _STATE_TO_MODE[state]
    speed, count, rsize, extra = _PRESETS[mode][key[1]]
    opts = dict(_BASE_PROFILES[mode])
    if count != 1:
        opts = _scale_counts(opts, count)
    if rsize != 1:
        opts = _scale_radii(opts, rsize)
    if extra:
        opts.update(extra)
    hit = (mode, speed, opts)
    _resolved[key] = hit
    return hit


def frame(state: str, size: int, t: float) -> tuple[list[Dot], list[Line]]:
    """The geometry of `state` at orb time t (already multiplied by the
    preset speed) for an orb of `size` px, after finalizeFrame: dots with
    alpha < 0.02 dropped, r >= rMin, dots sorted far to near. Coordinates are
    in px within a size x size square. Pure and deterministic."""
    mode, _speed, opts = _resolve(state, size)
    return _MODE_FRAMES[mode](size, t, opts)


def preset_speed(state: str, size: int) -> float:
    """The preset time multiplier (e.g. working@64 = 1.885)."""
    return _resolve(state, size)[1]


# ------------------------------------------------------------------ widget

def _parse_tint(color):
    if color is None or (isinstance(color, str) and not color.strip()):
        return None
    c = QColor(color) if isinstance(color, QColor) else QColor(str(color).strip())
    if not c.isValid():
        return None
    return (c.red(), c.green(), c.blue())


class ThinkingOrb(FxWidget):
    """A size x size widget drawing `state`.

    Orb time is now() * preset_speed(state, size) * speed, so all orbs on
    screen stay in phase. The still frame (not running, or animations off)
    lands on orb time 0.6 (clock t = 0.6 / preset speed), as the web
    version's reduced-motion frame.
    """

    def __init__(self, parent=None, state: str = "working", size: int = 20,
                 speed: float = 1.0, color=None):
        super().__init__(parent)
        if state not in _STATE_TO_MODE:
            raise ValueError(f"unknown orb state {state!r}")
        self._state = state
        self._size = max(1, int(size))
        self._speed = float(speed)
        self._tint = _parse_tint(color)
        self._brushes: dict = {}
        self._pens: dict = {}
        self.setFixedSize(self._size, self._size)
        self.setAccessibleName(LABELS[state])

    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        """Switch mode (ValueError for an unknown state); repaints."""
        if state not in _STATE_TO_MODE:
            raise ValueError(f"unknown orb state {state!r}")
        if state != self._state:
            self._state = state
            self.setAccessibleName(LABELS[state])
            self.update()

    def set_color(self, color) -> None:
        """A tint (QColor, '#rrggbb' or None for greyscale ink)."""
        self._tint = _parse_tint(color)
        self._brushes.clear()
        self._pens.clear()
        self.update()

    def label(self) -> str:
        """LABELS[state] -- the accessible name, also set as accessibleName."""
        return LABELS[self._state]

    # -- FxWidget
    def _time_scale(self) -> float:
        return preset_speed(self._state, self._size) * self._speed

    def still_time(self) -> float:
        # paint_frame multiplies by the time scale; this lands on orb time
        # 0.6, the web version's reduced-motion frame.
        scale = self._time_scale()
        return 0.6 / scale if scale else 0.0

    def _color(self, white: float, alpha: float, dark: bool) -> QColor:
        # core.ts inkColor: greyscale, or the depth ramp on the tint.
        w = 0.0 if white < 0.0 else 1.0 if white > 1.0 else white
        tint = self._tint
        if tint is None:
            g = js_round((1 - w if dark else w) * 255)
            r = g = b = g
        elif dark:
            r, g, b = (js_round(c * (1 - w)) for c in tint)
        else:
            r, g, b = (js_round(c + (255 - c) * w) for c in tint)
        return QColor(r, g, b, max(0, min(255, js_round(alpha * 255))))

    def paint_frame(self, painter, t: float) -> None:
        dots, lines = frame(self._state, self._size, t * self._time_scale())
        dark = self._theme != "light"
        painter.save()
        try:
            if lines:
                pens = self._pens
                if len(pens) > 4096:
                    pens.clear()
                painter.setBrush(Qt.NoBrush)
                for ln in lines:
                    key = (ln.white, js_round(ln.a * 255), ln.w, dark)
                    pen = pens.get(key)
                    if pen is None:
                        pen = QPen(self._color(ln.white, ln.a, dark), ln.w)
                        pen.setCapStyle(Qt.FlatCap)
                        pens[key] = pen
                    painter.setPen(pen)
                    painter.drawLine(QPointF(ln.x1, ln.y1), QPointF(ln.x2, ln.y2))
            painter.setPen(Qt.NoPen)
            brushes = self._brushes
            if len(brushes) > 4096:
                brushes.clear()
            for d in dots:
                # Cache brushes per (ink step, alpha step); ink is quantised
                # finer than the 8-bit channel it lands in.
                key = (js_round(d.white * 1020), js_round(d.a * 255), dark)
                brush = brushes.get(key)
                if brush is None:
                    brush = QBrush(self._color(d.white, d.a, dark))
                    brushes[key] = brush
                painter.setBrush(brush)
                painter.drawEllipse(QPointF(d.x, d.y), d.r, d.r)
        finally:
            painter.restore()
