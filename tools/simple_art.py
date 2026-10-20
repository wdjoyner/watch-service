"""Generated ("simple") part drawings, built only from the facts in parts.yaml.

Nothing here comes from SwissLab's artwork. Each part is drawn from its type and a few
numbers: where it sits (geom: pivot, bbox, z, face, r, heads, center) and how it is made
(art: teeth, arms, tooth_form, hole, drum, holds, jewels, screws ...). The drawings use
SwissLab stage coordinates, so they line up with the step data and the SWF's motion.

    import simple_art as SA
    parts = SA.load('.')
    svg = SA.document(SA.scene(parts, ids), [x0, y0, x1, y1], '#ffffff')

Automatic types: wheel, pinion, screw, jewel, balance, ring, stem.
Interim types (until hand-made outlines exist): plate (a disc), bridge (rounded hull of
the arbors and screws it holds), lever and spring (a capsule from the pivot).
"""
import json
import math
import os

# ---- palette (flat, technical-illustration look)
LINE = 0.5               # outline width, stage px
PLATE, PLATE_EDGE = '#e4e2dd', '#8b867c'
BRIDGE, BRIDGE_EDGE = '#cdd2d9', '#5b6470'
GILT, GILT_EDGE = '#e5bd57', '#8a6614'
STEEL, STEEL_EDGE = '#aeb5bf', '#4d5562'
BLUE, BLUE_RIM, BLUE_SLOT = '#4569c0', '#283f80', '#141f45'
RUBY, RUBY_HOLE, CHATON = '#c2185b', '#f6c4d4', '#e6e8eb'
HAIRSPRING = '#30353d'
HOLE = '#6f6a62'
SHADOW = '#000000'
SHADOW_OFF = (1.0, 1.4)

INTERIM = {'plate', 'bridge', 'lever', 'spring'}


def load(out):
    return json.load(open(os.path.join(out, 'parts.json'), encoding='utf-8'))


def center(parts, pid):
    g = parts[pid]['geom']
    return tuple(g.get('center', g['pivot']))


# ---- geometry helpers
def pol(cx, cy, r, a):
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def path(pts):
    return 'M' + ' L'.join('%.2f,%.2f' % p for p in pts) + ' Z'


def circle_path(cx, cy, r, n=72):
    return path([pol(cx, cy, r, 2 * math.pi * k / n) for k in range(n)])


def gear_points(cx, cy, R, teeth, form='normal'):
    """outline of a toothed wheel of tip radius R"""
    if not teeth:
        return [pol(cx, cy, R, 2 * math.pi * k / 120) for k in range(120)]
    p = 2 * math.pi / teeth
    if form == 'escape':        # Swiss lever club teeth: long, leaning, on a thin rim
        h = 0.30 * R
        r0 = R - h
        pts = []
        for i in range(teeth):
            t = i * p
            pts += [pol(cx, cy, r0, t), pol(cx, cy, r0 + 0.35 * h, t + 0.10 * p),
                    pol(cx, cy, R, t + 0.42 * p), pol(cx, cy, R - 0.10 * h, t + 0.58 * p),
                    pol(cx, cy, r0 + 0.20 * h, t + 0.62 * p), pol(cx, cy, r0, t + 0.80 * p)]
        return pts
    m = 2 * R / (teeth + 2)                   # module from tip diameter
    h = min(2.0 * m, 0.10 * R)
    r0 = R - h
    pts = []
    for i in range(teeth):
        t = i * p
        if form == 'ratchet':                 # saw teeth: slope one way, steep face the other
            pts += [pol(cx, cy, r0, t), pol(cx, cy, R, t + 0.85 * p), pol(cx, cy, r0 + 0.1 * h, t + 0.9 * p)]
        else:                                 # trapezoid teeth, close enough to cycloidal at this size
            pts += [pol(cx, cy, r0, t - 0.25 * p), pol(cx, cy, R, t - 0.13 * p),
                    pol(cx, cy, R, t + 0.13 * p), pol(cx, cy, r0, t + 0.25 * p)]
    return pts


def windows(cx, cy, r_out, r_in, arms, half_w, phase=-math.pi / 2):
    """the openings between `arms` straight spokes of half-width half_w, from hub r_in to rim r_out"""
    out = []
    for k in range(arms):
        a0 = phase + 2 * math.pi * k / arms
        a1 = a0 + 2 * math.pi / arms
        do, di = math.asin(min(half_w / r_out, 0.99)), math.asin(min(half_w / r_in, 0.99))
        if a1 - di <= a0 + di:
            continue
        n = 24
        pts = [pol(cx, cy, r_out, a0 + do + (a1 - a0 - 2 * do) * j / n) for j in range(n + 1)]
        pts += [pol(cx, cy, r_in, a1 - di - (a1 - a0 - 2 * di) * j / n) for j in range(n + 1)]
        out.append(path(pts))
    return out


def hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts
    def cross(o, a, b): return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0: lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0: hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def circles_hull(circles):
    pts = [pol(x, y, r, 2 * math.pi * k / 48) for x, y, r in circles for k in range(48)]
    return hull([(round(a, 2), round(b, 2)) for a, b in pts])


def el(d, fill, stroke=None, width=LINE, rule=None, extra=''):
    s = '<path d="%s" fill="%s"' % (d, fill)
    if stroke: s += ' stroke="%s" stroke-width="%g" stroke-linejoin="round"' % (stroke, width)
    if rule: s += ' fill-rule="%s"' % rule
    return s + extra + '/>'


def shadowed(d, fill, stroke, rule=None):
    """a shape plus its drop shadow"""
    dx, dy = SHADOW_OFF
    return (el(d, SHADOW, rule=rule, extra=' fill-opacity="0.16" transform="translate(%g,%g)"' % (dx, dy)) +
            el(d, fill, stroke, rule=rule))


# ---- building blocks
def jewel(x, y, r=5.5):
    return (el(circle_path(x, y, r), CHATON, BRIDGE_EDGE, 0.4) +
            el(circle_path(x, y, 0.62 * r), RUBY, '#7d0f3a', 0.3) +
            el(circle_path(x, y, 0.16 * r), RUBY_HOLE))


def screw_head(x, y, r, slot_deg=45):
    a = math.radians(slot_deg)
    L, w = 0.80 * r, 0.14 * r
    ca, sa = math.cos(a), math.sin(a)
    slot = path([(x - L * ca - w * sa, y - L * sa + w * ca), (x + L * ca - w * sa, y + L * sa + w * ca),
                 (x + L * ca + w * sa, y + L * sa - w * ca), (x - L * ca + w * sa, y - L * sa - w * ca)])
    return (shadowed(circle_path(x, y, r), BLUE_RIM, BLUE_SLOT) +
            el(circle_path(x, y, 0.80 * r), BLUE) + el(slot, BLUE_SLOT))


def toothed(cx, cy, R, art, fill=GILT, edge=GILT_EDGE):
    teeth, arms, form = art.get('teeth', 0), art.get('arms', 0), art.get('tooth_form', 'normal')
    d = [path(gear_points(cx, cy, R, teeth, form))]
    if arms:
        rim = 0.86 * R if form != 'escape' else 0.62 * R
        if form != 'escape' and teeth:
            rim = R - min(2.0 * 2 * R / (teeth + 2), 0.10 * R) - 0.09 * R
        d += windows(cx, cy, rim, 0.24 * R, arms, 0.065 * R if form != 'escape' else 0.05 * R)
    if art.get('hole'):
        d.append(circle_path(cx, cy, art['hole'] * R))
    out = shadowed(' '.join(d), fill, edge, rule='evenodd')
    if art.get('drum'):                      # barrel: cover edge and arbor
        out += el(circle_path(cx, cy, 0.80 * R), 'none', edge, 0.4)
        out += el(circle_path(cx, cy, 0.18 * R), STEEL, STEEL_EDGE)
    elif arms:                               # pinion / arbor at the hub
        out += el(circle_path(cx, cy, max(0.09 * R, 1.6)), STEEL, STEEL_EDGE, 0.4)
    return out


# ---- one function per type
def draw_wheel(parts, pid):
    g, art = parts[pid]['geom'], parts[pid].get('art', {})
    if art.get('view') == 'side':
        return draw_pinion(parts, pid)
    return toothed(*g['pivot'], g['r'], art)


def draw_pinion(parts, pid):
    g, art = parts[pid]['geom'], parts[pid].get('art', {})
    if art.get('view') == 'side':            # seen along the stem: a ribbed cylinder
        x0, y0, x1, y1 = g['bbox']
        d = path([(x0 + 1, y0 + 1), (x1 - 1, y0 + 1), (x1 - 1, y1 - 1), (x0 + 1, y1 - 1)])
        out = shadowed(d, STEEL, STEEL_EDGE)
        n = max(3, int((y1 - y0) / 3))
        for k in range(1, n):
            yy = y0 + (y1 - y0) * k / n
            out += el('M%.2f,%.2f L%.2f,%.2f' % (x0 + 1, yy, x1 - 1, yy), 'none', STEEL_EDGE, 0.3)
        return out
    return toothed(*g['pivot'], g['r'], art, STEEL, STEEL_EDGE)


def draw_screw(parts, pid):
    g = parts[pid]['geom']
    heads = g.get('heads') or [g['pivot'] + [g['r']]]
    return ''.join(screw_head(x, y, r) for x, y, r in heads)


def draw_ring(parts, pid):
    g = parts[pid]['geom']; x, y = g['pivot']; r = g['r']
    return shadowed(circle_path(x, y, r) + ' ' + circle_path(x, y, 0.5 * r), STEEL, STEEL_EDGE, 'evenodd')


def draw_jewel(parts, pid):
    g = parts[pid]['geom']
    return jewel(*g['pivot'], g.get('r', 5.5))


def screw_heads(parts, ids):
    out = []
    for sid in ids or []:
        g = parts[sid]['geom']
        out += g.get('heads') or [g['pivot'] + [g['r']]]
    return out


def enclosing_polygon(pts, k=4, min_angle=65.0, step=5.0, avoid=(), avoid_polys=()):
    """smallest k-gon around the points whose interior angles are all >= min_angle.
    Each side lies on a supporting line of the point set, so nothing sticks out; the angle
    limit keeps the bridge from turning into a near-triangle with needle corners.
    `avoid` circles (x, y, r) must stay outside (other bridges' arbors and screws),
    and `avoid_polys` (bridges already placed) must not be overlapped (GAP apart)."""
    dirs = [math.radians(a) for a in [i * step for i in range(int(360 / step))]]
    h = [max(x * math.cos(t) + y * math.sin(t) for x, y in pts) for t in dirs]
    max_turn = math.radians(180 - min_angle)

    def corner(i, j):  # where support lines i and j meet
        a1, b1, c1 = math.cos(dirs[i]), math.sin(dirs[i]), h[i]
        a2, b2, c2 = math.cos(dirs[j]), math.sin(dirs[j]), h[j]
        det = a1 * b2 - a2 * b1
        return ((c1 * b2 - c2 * b1) / det, (a1 * c2 - a2 * c1) / det)

    n, best = len(dirs), None
    def search(chosen):
        nonlocal best
        if len(chosen) == k:
            turn = dirs[chosen[0]] + 2 * math.pi - dirs[chosen[-1]]
            if not 0 < turn <= max_turn + 1e-9:
                return
            for x, y, r in avoid:   # circle overlaps the polygon (slightly conservative at corners)
                if max(x * math.cos(dirs[m]) + y * math.sin(dirs[m]) - h[m] for m in chosen) < r:
                    return
            v = [corner(chosen[m], chosen[(m + 1) % k]) for m in range(k)]
            for P in avoid_polys:
                if overlaps(v, P):
                    return
            area = abs(sum(v[m][0] * v[(m + 1) % k][1] - v[(m + 1) % k][0] * v[m][1] for m in range(k))) / 2
            if best is None or area < best[0]:
                best = (area, v)
            return
        start = chosen[-1] + 1 if chosen else 0
        for i in range(start, n):
            if chosen and dirs[i] - dirs[chosen[-1]] > max_turn + 1e-9:
                break
            if not chosen and dirs[i] > max_turn + 1e-9:   # the closing turn back to side 1 must fit too
                break
            search(chosen + [i])
    search([])
    if best is None and min_angle > 30:          # too tight: accept sharper corners first
        return enclosing_polygon(pts, k, min_angle - 10, step, avoid, avoid_polys)
    if best is None and (avoid or avoid_polys):   # still nothing: allow overlap rather than fail
        return enclosing_polygon(pts, k, 65.0, step)
    return best[1]


def rounded_path(v, radius):
    """closed polygon with its corners filleted"""
    n = len(v); seg = []
    for i in range(n):
        p, q, r = v[i - 1], v[i], v[(i + 1) % n]
        lp, lr = math.dist(p, q), math.dist(q, r)
        f = min(radius, 0.3 * lp, 0.3 * lr)
        a = (q[0] + (p[0] - q[0]) * f / lp, q[1] + (p[1] - q[1]) * f / lp)
        b = (q[0] + (r[0] - q[0]) * f / lr, q[1] + (r[1] - q[1]) * f / lr)
        seg.append((a, q, b))
    d = 'M%.2f,%.2f' % seg[0][0]
    for k, (a, q, b) in enumerate(seg):
        if k: d += ' L%.2f,%.2f' % a
        d += ' Q%.2f,%.2f %.2f,%.2f' % (q + b)
    return d + ' Z'


ARBOR_MARGIN, SCREW_MARGIN, GAP = 11.0, 5.0, 2.0


def overlaps(A, B, gap=GAP):
    """do two convex polygons come closer than `gap`? (separating-axis test)"""
    for P, Q in ((A, B), (B, A)):
        c = (sum(x for x, _ in P) / len(P), sum(y for _, y in P) / len(P))
        for i in range(len(P)):
            a, b = P[i], P[(i + 1) % len(P)]
            nx, ny = b[1] - a[1], a[0] - b[0]
            L = math.hypot(nx, ny) or 1.0
            nx, ny = nx / L, ny / L
            if nx * (c[0] - a[0]) + ny * (c[1] - a[1]) > 0:   # make the normal point outward
                nx, ny = -nx, -ny
            if min(nx * (q[0] - a[0]) + ny * (q[1] - a[1]) for q in Q) > gap:
                return False
    return True


_OUTLINES = {}


def bridge_outlines(parts):
    """all bridge outlines at once, placed in stacking order. Each stays clear of the bridges
    already placed, of the hull of the arbors and screws every other bridge must cover, and of
    the parts listed in its art.avoid. (Where a bridge runs past the main plate it is clipped
    to the plate's edge when drawn, see bridge_shape.)"""
    key = id(parts)
    if key in _OUTLINES:
        return _OUTLINES[key]
    bridges = [k for k, p in parts.items() if p['type'] == 'bridge']
    face = lambda k: parts[k]['geom']['face']
    done = {}
    for k in sorted(bridges, key=lambda k: z(parts, k, face(k) if face(k) != 'both' else 'bridge')):
        art = parts[k].get('art', {})
        mine = bridge_circles([center(parts, h) for h in art.get('holds', [])], screw_heads(parts, art.get('screws')))
        avoid = [c for o in bridges if o != k and face(o) == face(k) for c in _held(parts, o)]
        for a in art.get('avoid', []):
            g = parts[a]['geom']
            avoid += [(x, y, r + GAP) for x, y, r in (g.get('heads') or [g['pivot'] + [g.get('r', 6.0)]])]
        # bridges already placed, plus the least area each other bridge must still cover
        polys = [done[o] if o in done else circles_hull(_held(parts, o))
                 for o in bridges if o != k and face(o) == face(k)]
        done[k] = enclosing_polygon(circles_hull(mine), art.get('corners', 4), avoid=avoid,
                                    avoid_polys=polys)
    _OUTLINES[key] = done
    return done


def _held(parts, pid):
    art = parts[pid].get('art', {})
    return [(x, y, r + GAP) for x, y, r in bridge_circles(
        [center(parts, h) for h in art.get('holds', [])], screw_heads(parts, art.get('screws')))]


def bridge_circles(centers, heads):
    return [(x, y, ARBOR_MARGIN) for x, y in centers] + [(x, y, r + SCREW_MARGIN) for x, y, r in heads]


def plate_circle(parts):
    plate = next((p for p in parts.values() if p['type'] == 'plate'), None)
    if not plate:
        return None
    x0, y0, x1, y1 = plate['geom']['bbox']
    return (x0 + x1) / 2, (y0 + y1) / 2, min(x1 - x0, y1 - y0) / 2


_clip_ids = iter(range(10 ** 9))


def bridge_shape(parts, centers, heads, jewels, corners=4, outline=None):
    """interim bridge: a plate with `corners` vertices (rounded) that encloses the arbors it
    holds and its screws, each with a margin; trimmed to the main plate's edge"""
    if outline is None:
        outline = enclosing_polygon(circles_hull(bridge_circles(centers, heads)), corners)
    body = shadowed(rounded_path(outline, 5.0), BRIDGE, BRIDGE_EDGE)
    pc = plate_circle(parts)
    if pc and any(math.dist(q, pc[:2]) > pc[2] - 3 for q in outline):
        cid = 'plateclip%d' % next(_clip_ids)
        out = ('<defs><clipPath id="%s"><path d="%s"/></clipPath></defs><g clip-path="url(#%s)">%s</g>'
               % (cid, circle_path(pc[0], pc[1], pc[2] - 3, 180), cid, body))
        out += el(circle_path(pc[0], pc[1], pc[2] - 3, 180), 'none', BRIDGE_EDGE, LINE,
                  extra=' clip-path="url(#%sb)"' % cid)
        # redraw the outline along the trimmed edge: clip the plate-edge circle by the bridge
        out = out.replace('</clipPath></defs>', '</clipPath><clipPath id="%sb"><path d="%s"/></clipPath></defs>'
                          % (cid, rounded_path(outline, 5.0)), 1)
    else:
        out = body
    for x, y, r in heads:                    # screw holes (seen once the screws are out)
        out += el(circle_path(x, y, 0.55 * r), HOLE)
    for x, y in jewels:
        out += jewel(x, y)
    return out


def draw_bridge(parts, pid):
    art = parts[pid].get('art', {})
    return bridge_shape(parts, [center(parts, h) for h in art.get('holds', [])],
                        screw_heads(parts, art.get('screws')),
                        [center(parts, j) for j in art.get('jewels', [])], art.get('corners', 4),
                        bridge_outlines(parts)[pid])


def draw_plate(parts, pid):
    g, art = parts[pid]['geom'], parts[pid].get('art', {})
    x0, y0, x1, y1 = g['bbox']
    cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, min(x1 - x0, y1 - y0) / 2
    out = el(circle_path(cx, cy, r, 180), PLATE, PLATE_EDGE, 0.8)
    out += el(circle_path(cx, cy, r - 5, 180), 'none', PLATE_EDGE, 0.3)
    for j in art.get('jewels', []):
        out += jewel(*center(parts, j), 4.5)
    return out


def capsule(p, q, w):
    a = math.atan2(q[1] - p[1], q[0] - p[0])
    pts = [pol(*q, w, a - math.pi / 2 + math.pi * k / 16) for k in range(17)]
    pts += [pol(*p, w, a + math.pi / 2 + math.pi * k / 16) for k in range(17)]
    return path(pts)


def draw_lever(parts, pid, width=0.22):
    g = parts[pid]['geom']; x0, y0, x1, y1 = g['bbox']; p = g['pivot']
    far = max(((x, y) for x in (x0, x1) for y in (y0, y1)), key=lambda c: math.hypot(c[0] - p[0], c[1] - p[1]))
    w = max(2.0, width * min(x1 - x0, y1 - y0) / 2)
    return shadowed(capsule(p, far, w), STEEL, STEEL_EDGE) + el(circle_path(*p, 0.45 * w), HOLE)


def draw_spring(parts, pid):
    return draw_lever(parts, pid, width=0.12)


def draw_stem(parts, pid):
    g = parts[pid]['geom']; x0, y0, x1, y1 = g['bbox']
    yc, h = (y0 + y1) / 2, (y1 - y0) / 2
    tip = x0 + 0.12 * (x1 - x0)
    d = path([(x0, yc - 0.35 * h), (tip, yc - 0.35 * h), (tip, yc - 0.8 * h), (x1, yc - 0.8 * h),
              (x1, yc + 0.8 * h), (tip, yc + 0.8 * h), (tip, yc + 0.35 * h), (x0, yc + 0.35 * h)])
    return shadowed(d, STEEL, STEEL_EDGE)


def draw_balance(parts, pid):
    g, art = parts[pid]['geom'], parts[pid].get('art', {})
    cx, cy = g['center']; R = g['r']
    out = toothed(cx, cy, R, {'teeth': 0, 'arms': art.get('arms', 3)})
    # rim inner edge (the toothless "wheel" above leaves a rim of 0.14 R)
    turns, r_in, r_out = art.get('hairspring_turns', 11), 0.11 * R, art.get('hairspring_r', 0.46) * R
    n = turns * 64
    spiral = ['%.2f,%.2f' % pol(cx, cy, r_in + (r_out - r_in) * k / n, 2 * math.pi * k / 64) for k in range(n + 1)]
    out += '<polyline points="%s" fill="none" stroke="%s" stroke-width="0.35"/>' % (' '.join(spiral), HAIRSPRING)
    br = art.get('bridge', {})
    heads = screw_heads(parts, br.get('screws'))
    out += bridge_shape(parts, [(cx, cy)], heads, [], br.get('corners', 4))
    out += el(circle_path(cx, cy, 7.5), STEEL, STEEL_EDGE, 0.4) + jewel(cx, cy, 4.8)   # shock setting
    return out


DRAW = {'wheel': draw_wheel, 'pinion': draw_pinion, 'screw': draw_screw, 'ring': draw_ring,
        'jewel': draw_jewel, 'bridge': draw_bridge, 'plate': draw_plate, 'lever': draw_lever,
        'spring': draw_spring, 'stem': draw_stem, 'balance': draw_balance}


def part(parts, pid):
    return '<g data-part="%s">%s</g>' % (pid, DRAW[parts[pid]['type']](parts, pid))


def z(parts, pid, side):
    v = parts[pid]['geom']['z']
    return v[side] if isinstance(v, dict) else v


def scene(parts, ids, side):
    """several parts stacked in SwissLab's depth order for that side up"""
    return ''.join(part(parts, i) for i in sorted(ids, key=lambda i: z(parts, i, side)))


def on_face(parts, pid, side):
    return parts[pid]['geom']['face'] in (side, 'both')


def document(body, bbox, bg=None):
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    rect = '<rect x="%g" y="%g" width="%g" height="%g" fill="%s"/>' % (x0, y0, w, h, bg) if bg else ''
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%g %g %g %g" width="%g" height="%g">%s%s</svg>'
            % (x0, y0, w, h, w, h, rect, body))
