"""Extract a caliber's step facts from a screen recording of SwissLab, for calibers whose
SWF files are not available (e.g. the 2892-A2).

    python -I tools/steps_video.py /path/to/recording.mp4 calibers/2892a2 [--debug DIR]

Reads the caliber's transcript.yaml (what each screen says, transcribed by hand, with each
step's start and end in the recording) and catalog.yaml (ETA's parts list), measures in the
recording where each part sits and how it moves, and writes steps.json / steps.yaml,
assembly.json / assembly.yaml and parts.yaml / parts.json, in the same form as the
SWF-based calibers. Positions are in SwissLab stage px: the recording's movement window
(transcript meta.window_video_px) is mapped onto the standard window [18, 122, 432, 512].

What is measured (only positions, sizes and timing: no outline is taken):
  bbox_stage_px      disassembly: what disappears from the movement window during the step;
                     assembly: what appears in it
  pointer_stage_px   disassembly: center of SwissLab's green arrow
  path, motion       the part's center while it moves, one entry per SwissLab frame (12 fps),
                     split into straight phases; empty when the part vanishes in place
  oil_marks_stage_px assembly: centers of the colored marks drawn on the movement before the
                     part is fitted (approximate; which oil is not read yet)

--debug DIR writes, for each step, the first and last frames with the measured box drawn on
them. Those images show ETA/tica's drawings: keep DIR outside the repository.

Needs ffmpeg, numpy, Pillow, PyYAML. The recording, like the SWFs, must never be committed.
"""
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(__file__))
import caliber  # noqa: E402
import partsfile  # noqa: E402

FPS = 12                       # SwissLab's frame rate: one sample per Flash frame
VW, VH = 640, 360
WINDOW = [18, 122, 432, 512]   # SwissLab's movement window, stage px
DIFF = 40                      # a pixel "changed" if a channel differs by more than this
PARTBOX_V = (350, 163, 557, 305)   # lower box of the info panel, video px
CODE_V = (83, 290, 97, 314)    # SwissLab's step code (A01, B12 ...) in the window's corner, video px
LOOK_AHEAD = 1.6               # s of the next step that show where an assembly step's part ended


class Mapping:
    """video px <-> stage px, from the movement window's frame lines"""
    def __init__(self, win_v):
        x0, y0, x1, y1 = win_v
        self.sx = (WINDOW[2] - WINDOW[0]) / (x1 - x0)
        self.window_mask = None
        self.sy = (WINDOW[3] - WINDOW[1]) / (y1 - y0)
        self.x0, self.y0 = x0, y0
        self.win_v = (int(math.ceil(x0)) + 2, int(math.ceil(y0)) + 2, int(x1) - 1, int(y1) - 1)

    def pt(self, x, y):
        return [round(WINDOW[0] + (x - self.x0) * self.sx, 1), round(WINDOW[1] + (y - self.y0) * self.sy, 1)]

    def box(self, b):
        return self.pt(b[0], b[1]) + self.pt(b[2], b[3])

    def inv(self, p):
        """stage px -> video px"""
        return ((p[0] - WINDOW[0]) / self.sx + self.x0, (p[1] - WINDOW[1]) / self.sy + self.y0)


def frames(video, t0, t1):
    """RGB frames (n, VH, VW, 3) of [t0, t1] at FPS"""
    cmd = ['ffmpeg', '-v', 'error', '-ss', '%.3f' % t0, '-t', '%.3f' % (t1 - t0), '-i', video,
           '-vf', 'fps=%d,scale=%d:%d' % (FPS, VW, VH), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, VH, VW, 3).astype(np.int16)


def region(box):
    m = np.zeros((VH, VW), bool)
    x0, y0, x1, y1 = box
    m[y0:y1, x0:x1] = True
    return m


def green(F):
    """SwissLab's green pointer arrow"""
    r, g, b = F[..., 0], F[..., 1], F[..., 2]
    return (g - r > 40) & (g - b > 10)


def colored(F):
    """saturated pixels (oil marks are red, orange or yellow; parts are grey or gilt)"""
    r, g, b = F[..., 0], F[..., 1], F[..., 2]
    return (r - b > 90) & (r - g > 50)


def grow(mask, px):
    im = Image.fromarray(mask.astype(np.uint8) * 255)
    return np.asarray(im.filter(ImageFilter.MaxFilter(2 * px + 1))) > 0


def clean(mask, need=3):
    """drop specks (compression noise): pixels with fewer than `need` changed neighbors.
    Thin parts (a wire spring, a lever's arm) survive, unlike with a morphological opening."""
    m = mask.astype(np.int16)
    p = np.pad(m, 1)
    n = sum(p[1 + dy:1 + dy + m.shape[0], 1 + dx:1 + dx + m.shape[1]]
            for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)
    return mask & (n >= need)


def blinking(F, mask, times=5):
    """pixels that keep switching back and forth: SwissLab's blinking arrow and oil marks"""
    flips = np.zeros(mask.shape, np.int16)
    for t in range(1, len(F)):
        flips += changed(F[t], F[t - 1])
    return grow((flips >= times) & mask, 2)


def changed(a, b):
    return np.abs(a - b).max(axis=-1) > DIFF


def bbox(mask):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def centroid(mask):
    ys, xs = np.nonzero(mask)
    return (float(xs.mean()), float(ys.mean())) if len(xs) else None


def phases_of(path):
    """split a path into straight runs (direction changes of more than 25 degrees), as steps.py"""
    phases, cur = [], None
    for k in range(1, len(path)):
        dx, dy = path[k][0] - path[k - 1][0], path[k][1] - path[k - 1][1]
        if dx == 0 and dy == 0 and cur:
            cur['to'] = k
            continue
        ang = math.atan2(dy, dx)
        if cur and abs((ang - cur['ang'] + math.pi) % (2 * math.pi) - math.pi) < math.radians(25):
            cur['to'] = k
        else:
            cur = {'ang': ang, 'from': k - 1, 'to': k}
            phases.append(cur)
    return [{'from': path[q['from']], 'to': path[q['to']], 'frames': q['to'] - q['from']} for q in phases]


def track(F, start, after, area, exclude, M, min_px):
    """the moving part's center (stage px) and size in each frame from `start` on, as long as
    enough of it differs from the final frame"""
    pts = []
    for t in range(start, len(F)):
        d = clean(changed(F[t], after) & area & ~exclude)
        if d.sum() < min_px:
            break
        c, b = centroid(d), bbox(d)
        pts.append((M.pt(*c), math.hypot(b[2] - b[0], b[3] - b[1])))
    return pts


def to_path(pts):
    if not pts:
        return []
    d0 = pts[0][1] or 1
    return [[p[0], p[1], round(d / d0, 3)] for p, d in pts]


def moves(path, tol=6.0):
    return bool(path) and max(math.dist(p[:2], path[0][:2]) for p in path) > tol


def plateaus(F, mask, still=10, min_len=3):
    """runs of frames in which (almost) nothing in `mask` changes: [(first, last), ...]"""
    runs, a = [], 0
    for t in range(1, len(F) + 1):
        if t == len(F) or (changed(F[t], F[t - 1]) & mask).sum() > still:
            if t - a >= min_len:
                runs.append((a, t - 1))
            a = t
    return runs


def rep(F, run):
    return np.median(F[run[0]:run[1] + 1], axis=0)


def views(F, mask):
    """[first, last] frame of each view shown (split where much of the window changes at once)"""
    cuts = [0]
    n = mask.sum()
    for t in range(1, len(F)):
        if (changed(F[t], F[t - 1]) & mask).sum() > 0.3 * n:
            cuts.append(t)
    cuts.append(len(F))
    return [(a, b - 1) for a, b in zip(cuts, cuts[1:]) if b > a]


def before_after(F, win, ignore, a, b):
    """the stable states just before and just after the part moves, within frames [a, b] of
    one view: the last stable stretch, and the latest one before it that differs from it by
    a good part of the largest difference. Returns (before, after, motion start, motion end)"""
    G = F[a:b + 1]
    runs = plateaus(G, win & ~ignore)
    if len(runs) < 2:
        return None
    end = runs[-1]
    after = rep(G, end)
    d = [(changed(rep(G, r), after) & win & ~ignore).sum() for r in runs[:-1]]
    top = max(d)
    if top <= 15:
        return None
    k = max(i for i, v in enumerate(d) if v >= 0.5 * top)
    return rep(G, runs[k]), after, a + runs[k][1] + 1, a + end[0]


def drawn(F, win, a, b):
    """bbox of everything drawn in the window, in the longest stable stretch of a view"""
    runs = plateaus(F[a:b + 1], win) or [(0, b - a)]
    r = max(runs, key=lambda r: r[1] - r[0])
    img = rep(F[a:b + 1], r)
    return bbox(clean((img.min(axis=-1) < 235) & win))


def heads(mask, M):
    """separate pieces of a step with several screws: their centers and radii (stage px)"""
    out = []
    for x, y, n in blobs(mask, gap=2):
        r = math.sqrt(n / math.pi)
        out.append(M.pt(x, y) + [round(r * M.sx, 1)])
    return sorted(out) if len(out) > 1 else None


def window(M):
    """the movement window, without the step code in its corner"""
    return region(M.win_v) & ~region(CODE_V)


def measure_disassembly(F, M):
    win = window(M)
    arrow = grow(np.any(np.stack([green(f) for f in F]), axis=0), 2)
    a, b = max(views(F, win), key=lambda v: v[1] - v[0])     # the view the step is shown in
    ignore = arrow | blinking(F[a:b + 1], win)
    ba = before_after(F, win, ignore, a, b)
    out = {'pointer_v': bbox(arrow & win)}
    if not ba:
        # the last piece of a view (the main plate, a unit's base): nothing stays behind
        out['bbox_v'] = drawn(F, win, a, b)
        return out
    before, after, start, stop = ba
    removed = clean(changed(before, after) & win & ~ignore)
    out['bbox_v'] = bbox(removed)
    out['heads'] = heads(removed, M)
    if not out['bbox_v']:
        return out
    area = win | region(PARTBOX_V)
    pts = track(F[:stop + 1], max(start - 1, 0), after, area, ignore, M, max(6, removed.sum() // 6))
    path = to_path(pts)
    out.update(start=start, path=path if moves(path) else [])
    return out


def measure_assembly(F, M, own=None):
    """F covers the step and, unless it is the last step, LOOK_AHEAD s of the next one: the
    caption fades over about a second while the part is still flying in, so the part may
    come to rest only after the next step's caption has appeared"""
    own = own or len(F)
    win = window(M)
    box = region(PARTBOX_V)
    # the view the part is fitted in: the one on screen at the end of the step (the next step
    # may already show another side)
    a, b = next(v for v in views(F, win) if v[0] <= own - 3 <= v[1])
    marks_all = np.any(np.stack([colored(f) for f in F[a:b + 1]]), axis=0) & win
    ignore = grow(marks_all, 1) | blinking(F[a:b + 1], win)
    ba = before_after(F, win, ignore, a, b)
    out = {}
    if not ba:
        # the first piece of a view (a unit's base) arrives with the view itself
        out['bbox_v'] = drawn(F, win, a, b)
        return out
    before, after, start, stop = ba
    appeared = changed(before, after) & ~(after.min(axis=-1) > 235)      # not where it became background
    fitted = clean(appeared & win & ~ignore)
    out['bbox_v'] = bbox(fitted)
    out['heads'] = heads(fitted, M)
    if not out['bbox_v']:
        return out
    # oil marks: colored pixels on the movement while the part waits
    marks = np.zeros((VH, VW), bool)
    for t in range(a, start):
        marks |= colored(F[t]) & win & ~colored(before) & ~colored(after)
    out['oil_v'] = blobs(clean(marks, 2))
    # the moving part: what differs from the waiting state, away from its waiting place
    waiting = clean(changed(before, after) & box)
    exclude = grow(waiting, 3) | grow(marks_all, 2) | ignore
    pts = []
    for t in range(start, stop + 1):
        d = clean(changed(F[t], before) & (win | box) & ~exclude)
        if d.sum() < 6:
            continue
        c, bb = centroid(d), bbox(d)
        pts.append((M.pt(*c), math.hypot(bb[2] - bb[0], bb[3] - bb[1])))
    c = centroid(fitted)
    pts.append((M.pt(*c), math.hypot(out['bbox_v'][2] - out['bbox_v'][0], out['bbox_v'][3] - out['bbox_v'][1])))
    path = to_path(pts[::-1])[::-1]          # scale relative to the fitted size
    out.update(start=start, path=path if moves(path) else [])
    return out


def blobs(mask, gap=4):
    """centers of separate marks (pixels closer than `gap` belong together)"""
    ys, xs = np.nonzero(mask)
    pts = list(zip(xs.tolist(), ys.tolist()))
    groups = []
    for p in pts:
        for g in groups:
            if any(abs(p[0] - q[0]) <= gap and abs(p[1] - q[1]) <= gap for q in g[-40:]):
                g.append(p)
                break
        else:
            groups.append([p])
    return [(sum(x for x, _ in g) / len(g), sum(y for _, y in g) / len(g), len(g)) for g in groups if len(g) >= 3]


# ---------------------------------------------------------------- facts from the transcript
def part_id(tr):
    """SwissLab's clip naming (MC + catalog number), as in the 6497 files"""
    if tr.get('cs'):
        return 'MC' + tr['cs'].replace('.', '_')
    return {'Automatic device': 'MCAutomaticDevice',
            'Balance complete with bridge and ETACHRON system': 'MCBalanceComp',
            'Barrel bridge, assembled': 'MCBarrelBridgeComp'}.get(tr['part'], 'MC' + tr['code'])


def tc_row(catalog, cs):
    """the Technical Communication's row for a CS number shown on screen"""
    if not cs:
        return None
    rows = {r['cs']: r for r in catalog}
    if cs in rows:
        return rows[cs]
    stem = cs.rsplit('.', 1)[0]
    if cs.count('.') == 2 and stem in rows:          # e.g. 31.046.06 on screen, 31.046 in the TC
        return rows[stem]
    longer = [r for k, r in rows.items() if k.startswith(cs + '.')]
    return longer[0] if len(longer) == 1 else None   # e.g. 91.440 on screen, 91.440.22 in the TC


def names(tr, row):
    n = {'en': tr['part']}
    if row:
        a2 = row.get('a2', {})
        same = row['cs'] == tr['cs']
        if a2.get('en') == tr['part']:                # the A2 sheet's own wording (hour wheel)
            n.update(fr=a2['fr'], de=a2['de'])
        elif same or row['en'] == tr['part']:
            n.update(fr=row['fr'], de=row['de'])
    return n


def components(tr, catalog, units):
    key = tr['part'] if tr['part'] in units else tr.get('cs')
    if key not in units:
        return None
    rows = {r['cs']: r for r in catalog}
    return [{'item': rows[c]['item'], 'catalog_no': c, 'part': rows[c]['en']} for c in units[key] if c in rows]


def step_record(n, tr, m, M, catalog, units):
    if tr.get('shows'):                       # no caption on screen: the part it shows
        row = tc_row(catalog, tr['shows'])
        tr = dict(tr, cs=tr['shows'], part=row['en'])
    row = tc_row(catalog, tr.get('cs'))
    s = {'step': n, 'code': tr['code'], 'part': tr['part'], 'part_id': part_id(tr),
         'catalog_no': tr.get('cs'), 'names': names(tr, row)}
    if row:
        s['tc'] = {'item': row.get('a2', {}).get('item', row['item'])}
        if row['cs'] != tr.get('cs'):
            s['tc']['catalog_no'] = row['cs']
    comp = components(tr, catalog, units)
    if comp:
        s['components'] = comp
    s['side_up'] = tr['view']
    for k in ('note', 'prompt', 'remark'):
        if tr.get(k):
            s[k] = tr[k]
    s['bbox_stage_px'] = M.box(m['bbox_v']) if m.get('bbox_v') else None
    if m.get('heads') and row and row.get('qty', 1) > 1:      # screws ETA lists more than once
        hs = [h for h in m['heads'] if h[2] >= 0.6 * max(q[2] for q in m['heads'])]
        if len(hs) > 1:
            s['heads_stage_px'] = hs
    if m.get('pointer_v'):
        p = m['pointer_v']
        s['pointer_stage_px'] = M.pt((p[0] + p[2]) / 2, (p[1] + p[3]) / 2)
    if 'oil_v' in m:
        s['oil_marks_stage_px'] = [M.pt(x, y) for x, y, _ in m['oil_v']]
    s['path'] = m.get('path', [])
    s['motion'] = phases_of(s['path']) if s['path'] else []
    s['video'] = {'t': tr['t'], 'motion_start_s': round(tr['t'][0] + m['start'] / FPS, 2) if m.get('start') else None,
                  'bbox_measured_stage_px': s['bbox_stage_px']}
    return s


# ---------------------------------------------------------------- writing
def y(v):
    if v is None: return 'null'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (int, float)): return repr(v)
    if isinstance(v, list): return '[' + ', '.join(y(x) for x in v) + ']'
    if isinstance(v, dict): return '{' + ', '.join('%s: %s' % (k, y(x)) for k, x in v.items()) + '}'
    return json.dumps(v, ensure_ascii=False)


def write(out, name, meta, steps, keys, header):
    json.dump({'meta': meta, 'steps': steps}, open(os.path.join(out, name + '.json'), 'w'), indent=1, ensure_ascii=False)
    L = header + ['meta:'] + ['  %s: %s' % (k, y(v)) for k, v in meta.items()] + ['steps:']
    for s in steps:
        L.append('  - step: %d' % s['step'])
        for k in keys:
            if s.get(k) is not None:
                L.append('    %s: %s' % (k, y(s[k])))
    open(os.path.join(out, name + '.yaml'), 'w').write('\n'.join(L) + '\n')


def area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def geom(s, z, face):
    x0, y0, x1, y1 = s['bbox_stage_px']
    g = {'pivot': [round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)], 'bbox': s['bbox_stage_px'],
         'z': z, 'face': face, 'r': round(max(x1 - x0, y1 - y0) / 2, 2)}
    if s.get('heads_stage_px'):
        g['heads'] = s['heads_stage_px']
    return g


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    video, out = args[0], args[1]
    debug = sys.argv[sys.argv.index('--debug') + 1] if '--debug' in sys.argv else None
    if debug:
        args.remove(debug)
        os.makedirs(debug, exist_ok=True)
    import yaml
    cfg = caliber.load(out)
    tr = yaml.safe_load(open(os.path.join(out, 'transcript.yaml'), encoding='utf-8'))
    catalog = yaml.safe_load(open(os.path.join(out, 'catalog.yaml'), encoding='utf-8'))['parts']
    units = tr.get('units', {})
    M = Mapping(tr['meta']['window_video_px'])
    meta = {'source': 'screen recording of ETA SwissLab (idea and animation: tica international): %s' % tr['meta']['video'],
            'stage_px': [800, 600], 'fps': FPS,
            'coordinates': 'measured in the recording, movement window mapped onto SwissLab window %s' % WINDOW,
            'video_window_px': tr['meta']['window_video_px']}

    seqs = {}
    for seq in ('disassembly', 'assembly'):
        steps = []
        for n, t in enumerate(tr[seq], 1):
            nxt = tr[seq][n] if n < len(tr[seq]) else None
            if seq == 'assembly' and nxt and nxt['view'] == t['view'] and not t.get('prompt'):
                F = frames(video, t['t'][0], t['t'][1] + LOOK_AHEAD)
                own = min(len(F), int(round((t['t'][1] - t['t'][0]) * FPS)))
                m = measure_assembly(F, M, own)
                F = F[:own]
            else:
                F = frames(video, *t['t'])
                m = measure_disassembly(F, M) if seq == 'disassembly' else measure_assembly(F, M)
            s = step_record(n, t, m, M, catalog, units)
            steps.append(s)
            print(seq[:3], t['code'], s['side_up'][:10].ljust(10), (s['part'] or '(no caption)')[:34].ljust(34),
                  s['bbox_stage_px'], 'moves' if s['motion'] else 'fades', len(s.get('oil_marks_stage_px', [])) or '')
            if debug:
                f = F[0] if seq == 'disassembly' else F[-1]
                im = Image.fromarray(f.astype(np.uint8))
                d = ImageDraw.Draw(im)
                if m.get('bbox_v'):
                    d.rectangle(m['bbox_v'], outline=(255, 0, 255))
                pts = [M.inv(p) for p in m.get('path', [])]
                if len(pts) > 1:
                    d.line(pts, fill=(0, 150, 255), width=2)
                for x, y, _ in m.get('oil_v', []):
                    d.ellipse((x - 3, y - 3, x + 3, y + 3), outline=(0, 200, 0), width=2)
                d.text((90, 322), '%s %s' % (t['code'], 'moves' if s['motion'] else 'fades'), fill=(255, 255, 0))
                im.save(os.path.join(debug, '%s.png' % t['code']))
        seqs[seq] = steps

    dis, asm = seqs['disassembly'], seqs['assembly']
    by_id = {s['part_id']: s for s in dis}
    for s in asm:
        d = by_id.get(s['part_id'])
        s['disassembly_step'] = d['step'] if d else None
        if s['bbox_stage_px'] is None and d:   # already in place when the step starts (the main plate)
            s['bbox_stage_px'] = d['bbox_stage_px']
    head = ['# %s %%s sequence, from a screen recording of ETA SwissLab' % cfg['name'],
            '# (idea and animation: tica international, www.tica.dk); transcript.yaml says what each',
            '# screen shows, tools/steps_video.py measured positions and motion. part_id keys into parts.yaml.']
    keys = ('code', 'part', 'part_id', 'catalog_no', 'tc', 'side_up', 'note', 'prompt', 'remark', 'bbox_stage_px')

    # ---- shared parts list. Stacking order: what comes off earlier lies on top.
    parts = {}
    for s in dis:
        p = parts.setdefault(s['part_id'], {})
        p.update(part=s['part'], catalog_no=s['catalog_no'], disassembly_step=s['step'], assembly_step=None,
                 names=s['names'])
        if s.get('tc'): p['tc'] = s['tc']
        if s.get('components'): p['components'] = s['components']
        if s['bbox_stage_px']:
            p['geom'] = geom(s, 100 - s['step'], s['side_up'])
    for s in asm:
        p = parts.setdefault(s['part_id'], {'part': s['part'], 'catalog_no': s['catalog_no'], 'disassembly_step': None,
                                            'names': s['names']})
        p['assembly_step'] = s['step']
        if not s['bbox_stage_px']:
            continue
        g = geom(s, p['geom']['z'] if 'geom' in p else s['step'], s['side_up'])
        # measured twice (once each way, same view): the tighter box is the better one, since
        # whatever else changed on screen can only make a box larger
        if 'geom' not in p or (p['geom']['face'] == g['face'] and area(g['bbox']) < area(p['geom']['bbox'])):
            p['geom'] = g
    old = partsfile.load(out)
    for k, p in parts.items():                 # hand-kept keys survive re-extraction
        for f in ('type', 'art', 'components'):
            if f in old.get(k, {}):
                p[f] = old[k][f]
        if 'geom' in old.get(k, {}) and old[k]['geom'].get('hand'):
            p['geom'] = old[k]['geom']
        if p.get('type') in ('plate', 'stem') and p.get('geom', {}).get('face') in ('dial', 'bridge'):
            p['geom']['face'] = 'both'          # seen from either side of the movement
    # each step uses its part's best box (in the same view); the raw measurement stays in "video"
    for s in dis + asm:
        g = parts[s['part_id']].get('geom')
        if g and g['face'] == s['side_up']:
            s['bbox_stage_px'] = g['bbox']
            if g.get('heads'):
                s['heads_stage_px'] = g['heads']
    write(out, 'steps', meta, dis, keys, [h % 'disassembly' if '%s' in h else h for h in head])
    write(out, 'assembly', dict(meta, oil_legend=tr['meta']['oil_legend']), asm,
          keys[:3] + ('disassembly_step',) + keys[3:] + ('oil_marks_stage_px',),
          [h % 'assembly' if '%s' in h else h for h in head])
    partsfile.save(out, parts, '# %s parts, keyed by SwissLab clip name (MC + catalog number)' % cfg['name'],
                   extra=('tc',))


if __name__ == '__main__':
    main()
