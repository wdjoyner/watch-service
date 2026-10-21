"""Measure each part in the SwissLab SWF and record the numbers in parts.yaml.

    python -I tools/measure_parts.py /path/to/6497disassem.swf calibers/6497  [--force]

Only facts are taken: where a part sits (pivot, bounding box, stacking order, which face
of the movement it is on), its radius, how many teeth and arms its drawing has, where the
screw heads of a multi-screw part are, and the balance's center and rim radius. No outline
is copied. The generated drawings (tools/simple_art.py) are built from these numbers.

`geom` is always rewritten. Counts that go into `art` (teeth, arms) are only filled in when
missing, so hand corrections survive; --force overwrites them too.
Run after steps.py and steps_assembly.py (needs steps.json and assembly.json).
"""
import io
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import cairosvg
from PIL import Image

import partsfile
import render as Rn
import swfparse as P

ROUND = {'wheel', 'pinion', 'ring', 'screw', 'jewel'}
SC = 4  # render scale for measuring


def mat_mul(A, B):
    a1, b1, c1, d1, e1, f1 = A; a2, b2, c2, d2, e2, f2 = B
    return [a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1]


def app(M, p):
    return (M[0] * p[0] + M[2] * p[1] + M[4], M[1] * p[0] + M[3] * p[1] + M[5])


def leaves(swf, cid, M):
    """stage-space bounding boxes [x0, y0, x1, y1] of every shape inside a character"""
    if cid in swf['shapes']:
        x0, x1, y0, y1 = swf['shapes'][cid]['bounds']
        pts = [app(M, (x, y)) for x in (x0, x1) for y in (y0, y1)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return [[min(xs), min(ys), max(xs), max(ys)]]
    out = []
    if cid in swf['sprites']:
        dl = Rn.SVG.state(swf['sprites'][cid]['frames'], 1)
        for d in sorted(dl):
            p = dl[d]
            if 'id' in p and 'clipdepth' not in p:
                out += leaves(swf, p['id'], mat_mul(M, p.get('matrix', [1, 0, 0, 1, 0, 0])))
    return out


class Alpha:
    """the part's drawing rasterized over its bbox, used only to count teeth and arms"""
    def __init__(self, swf, step):
        sv = Rn.SVG(swf)
        x0, y0, x1, y1 = self.bb = step['bbox_stage_px']
        body = '<g transform="%s">%s</g>' % (sv.mat(step['swf']['place_matrix']), sv.char(step['swf']['sprite']))
        png = cairosvg.svg2png(bytestring=sv.document(body, [x0, x1, y0, y1]).encode(), scale=SC)
        self.a = Image.open(io.BytesIO(png)).convert('RGBA').getchannel('A')
        self.W, self.H = self.a.size

    def __call__(self, x, y):
        u, v = int((x - self.bb[0]) * SC), int((y - self.bb[1]) * SC)
        return self.a.getpixel((u, v)) >= 128 if 0 <= u < self.W and 0 <= v < self.H else False

    def runs(self, cx, cy, r, n=2880):
        """number of opaque runs met going once around a circle"""
        v = [self(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
        return sum(1 for k in range(n) if v[k] and not v[k - 1])


def stable(counts):
    """the most common nonzero count (tooth counts sampled at several radii)"""
    c = [x for x in counts if x > 0]
    return max(set(c), key=c.count) if c else 0


def face_of(clip, dis_step, asm):
    for s in asm['steps']:
        if clip in s['swf'].get('hidden_clips', []):
            # hidden while side X is up -> it lives on the other face
            return 'bridge' if s['side_up'] == 'dial' else 'dial'
    return dis_step['side_up']


def r2(v): return round(v, 2)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    force = '--force' in sys.argv
    swf = P.parse(args[0]); out = args[1]
    dis = json.load(open(os.path.join(out, 'steps.json')))
    asm = json.load(open(os.path.join(out, 'assembly.json')))
    parts = partsfile.load(out)
    # stacking order: the clip's depth in each step frame. Plate and stem sit at different
    # depths with the dial or the bridge side up, so their z is given per face.
    zs = {}
    for s in dis['steps']:
        for dep, p in Rn.SVG.state(swf['main']['frames'], s['swf']['main_frame']).items():
            if p.get('name') in parts:
                zs.setdefault(p['name'], {})[s['side_up']] = dep
    for s in dis['steps']:
        clip = s['swf']['clip_name']; p = parts[clip]
        typ = p.get('type'); art = p.setdefault('art', {})
        px, py = s['swf']['place_matrix'][4:6]
        g = {'pivot': [r2(px), r2(py)], 'bbox': [r2(v) for v in s['bbox_stage_px']], 'z': zs[clip] if len(set(zs[clip].values())) > 1 else s['swf']['depth'],
             'face': 'both' if typ in ('plate', 'stem') else face_of(clip, s, asm)}
        A = Alpha(swf, s)
        lv = leaves(swf, s['swf']['sprite'], s['swf']['place_matrix'])
        if typ in ROUND and art.get('view') != 'side':
            x0, y0, x1, y1 = s['bbox_stage_px']
            g['r'] = r2(max(px - x0, x1 - px, py - y0, y1 - py))
        if typ == 'screw':
            heads = []
            for x0, y0, x1, y1 in lv:
                w, h = x1 - x0, y1 - y0
                if abs(w - h) < 0.15 * max(w, h) and w < 40:
                    c = [(x0 + x1) / 2, (y0 + y1) / 2]
                    if not any(math.hypot(c[0] - q[0], c[1] - q[1]) < 1.5 for q in heads):
                        heads.append([r2(c[0]), r2(c[1]), r2(w / 2)])
            heads = [q for q in heads if q[2] >= 0.8 * max(h[2] for h in heads)]   # drop slots and bevels
            if len(heads) > 1:
                g['heads'] = sorted(heads)
        if typ == 'balance':
            rim = max(lv, key=lambda b: (b[2] - b[0]) * (abs((b[2] - b[0]) - (b[3] - b[1])) < 2))
            g['center'] = [r2((rim[0] + rim[2]) / 2), r2((rim[1] + rim[3]) / 2)]
            g['r'] = r2((rim[2] - rim[0]) / 2)
        if typ in ('wheel', 'pinion') and art.get('view') != 'side':
            R = g['r']
            teeth = stable([A.runs(px, py, R * f / 1000) for f in range(995, 900, -5)])
            arms = stable([A.runs(px, py, R * f, 1440) for f in (0.45, 0.6)])
            if force or 'teeth' not in art: art['teeth'] = teeth
            if typ == 'wheel' and (force or 'arms' not in art): art['arms'] = arms if arms >= 3 else 0
        if not art: p.pop('art')
        p['geom'] = g
        print('%-14s %-8s %s %s' % (clip, typ, g, art))
    partsfile.save(out, parts)


if __name__ == '__main__':
    main()
