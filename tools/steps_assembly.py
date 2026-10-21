"""Reconstruct the ASSEMBLY sequence from a SwissLab assembly SWF.

Writes assembly.json / assembly.yaml next to the disassembly steps.json, and
parts.json / parts.yaml: one shared parts list keyed by SwissLab clip name, with
each part's step number in both sequences.

Usage: python -I tools/steps_assembly.py /path/to/6497assem.swf calibers/6497

Run tools/steps.py first. The caliber-specific values (sides and hidden parts when the
movement is turned, the movement's depth range, the oil-symbol IDs, note variables) come
from calibers/<caliber>/caliber.yaml, section swisslab.assembly.
"""
import sys, os, io, re, json, math
sys.path.insert(0, os.path.dirname(__file__))
import swfparse as P, render as Rn, caliber
from PIL import Image
import cairosvg

swf = P.parse(sys.argv[1]); out = sys.argv[2]
CFG = caliber.load(out); A = CFG['swisslab']['assembly']
VF = caliber.variant_flag(CFG)
main = swf['main']['frames']
dis = json.load(open(f'{out}/steps.json'))
dis_by_clip = {s['swf']['clip_name']: s for s in dis['steps']}
os.makedirs(f'{out}/parts_assembly', exist_ok=True)

V = {}
for a in main[0]['actions']:
    for line in a['src']:
        m = re.match(r"^(\w+) = (.*)$", line)
        if m:
            try: V[m.group(1)] = eval(m.group(2))
            except Exception: V[m.group(1)] = m.group(2)
LANGS = {'gb': 'en', 'd': 'de', 'f': 'fr', 'i': 'it', 'e': 'es', 'dk': 'da'}

step_frame = {}
for i, fr in enumerate(main):
    for a in fr['actions']:
        for line in a['src']:
            m = re.match(r'counter = (\d+)', line)
            if m: step_frame[int(m.group(1))] = i + 1
N = max(step_frame)

# ---- side up and visibility, decoded from the "turnmovement" script: going forward it
# hides/shows whole index ranges of parts when the movement is turned (caliber.yaml: sides)
clip = {i: V.get('mcname%d' % i) for i in range(1, N + 1)}
def rng(a, b): return {clip[i] for i in range(a, b + 1)}
def side_and_hidden(n):
    for row in A['sides']:
        if row.get('upto') is None or n <= row['upto']:
            hidden = set(row.get('hide_clips', []))
            for a, b in row.get('hide_steps', []):
                hidden |= rng(a, b)
            return row['side'], hidden
    raise SystemExit('caliber.yaml swisslab.assembly.sides: no row for step %d' % n)

MOVEMENT_DEPTHS = tuple(A['movement_depths'])   # main-timeline depths that hold the movement (UI lies outside)

OIL = {int(k): v for k, v in A['oil_symbols'].items()}
NOTE_RE = re.compile(A['note_pattern'])

def mat_mul(A, B):
    a1, b1, c1, d1, e1, f1 = A; a2, b2, c2, d2, e2, f2 = B
    return [a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1]
def inv(M):
    a, b, c, d, e, f = M; det = a * d - b * c
    return [d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det]
def app(M, p): return (M[0] * p[0] + M[2] * p[1] + M[4], M[1] * p[0] + M[3] * p[1] + M[5])
I = [1, 0, 0, 1, 0, 0]
W, H = swf['stage'][1], swf['stage'][3]
st = Rn.SVG.state

def export(body_fn, path_stem):
    """render a stage-coordinate SVG body; save cropped SVG + PNG; return bbox"""
    sv = Rn.SVG(swf); body = body_fn(sv)
    img = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=sv.document(body, [0, W, 0, H]).encode(), scale=4)))
    bb = img.getbbox()
    if not bb: return None
    x0, y0, x1, y1 = [v / 4 for v in bb]
    open(path_stem + '.svg', 'w').write(sv.document(body, [x0 - 1, x1 + 1, y0 - 1, y1 + 1]))
    img.crop(bb).save(path_stem + '.png')
    return [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]

def find_notes(cid, seen=None):
    seen = seen or set(); res = []
    if cid in seen: return res
    seen.add(cid)
    if cid in swf['edittexts']:
        v = swf['edittexts'][cid].get('var', '')
        m = NOTE_RE.search(v)
        if m: res.append(m.group(1))
    if cid in swf['sprites']:
        for f in swf['sprites'][cid]['frames']:
            for p in f['place']:
                if 'id' in p: res += find_notes(p['id'], seen)
    return res

steps = []
for n in range(1, N + 1):
    fr = step_frame[n]; mc = clip[n]
    dl = st(main, fr)
    depth, place = [(d, p) for d, p in dl.items() if p.get('name') == mc][0]
    G = place.get('matrix', I); spr = swf['sprites'][place['id']]
    s1 = st(spr['frames'], 1)
    stem = f'{out}/parts_assembly/{n:02d}_{mc}'
    # the part at rest = the sprite's frame 1 (all its children), placed by G
    bbox = export(lambda sv: '<g transform="%s">%s</g>' % (sv.mat(G), sv.displaylist(spr['frames'], 1, sc=Rn.SVG.msc(G))), stem)

    # moving pieces: frames 2..end (frame 1 is the rest pose; Flash jumps straight to 2)
    movers = []
    for dpt, p1 in sorted(s1.items()):
        if 'clipdepth' in p1 or 'id' not in p1: continue
        kf = []
        for k in range(2, len(spr['frames']) + 1):
            s = st(spr['frames'], k)
            if dpt in s and s[dpt].get('id') == p1['id']:
                kf.append(s[dpt].get('matrix', I))
        if len(kf) > 1 and any(abs(a - b) > 1e-3 for a, b in zip(kf[0], kf[-1])):
            movers.append({'depth': dpt, 'char': p1['id'], 'rest': p1.get('matrix', I), 'kf': kf})
    path, phases = [], []
    if len(movers) == 1 and bbox:
        mv = movers[0]; c0 = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        M0i = inv(mat_mul(G, mv['rest'])); local = app(M0i, c0)
        for m in mv['kf']:
            p = app(mat_mul(G, m), local)
            path.append([round(p[0], 2), round(p[1], 2), round(Rn.SVG.msc(m) / Rn.SVG.msc(mv['rest']), 4)])
        cur = None
        for k in range(1, len(path)):
            ang = math.atan2(path[k][1] - path[k - 1][1], path[k][0] - path[k - 1][0])
            if path[k][:2] == path[k - 1][:2] and cur: cur['to'] = k; continue
            if cur and abs((ang - cur['ang'] + math.pi) % (2 * math.pi) - math.pi) < math.radians(25): cur['to'] = k
            else: cur = {'ang': ang, 'from': k - 1, 'to': k}; phases.append(cur)
        phases = [{'from': path[q['from']], 'to': path[q['to']], 'frames': q['to'] - q['from']} for q in phases]

    # detail drawings shown with the part while it waits in the panel (frame 2, removed when it
    # starts to move), e.g. the edge-on barrel the oil symbols point at
    s2 = st(spr['frames'], 2) if len(spr['frames']) > 1 else {}
    mover_depths = {m['depth'] for m in movers}
    extra = {d: p for d, p in s2.items() if d not in mover_depths and d not in s1 and 'id' in p}
    later = st(spr['frames'], 3) if len(spr['frames']) > 2 else {}
    extra = {d: p for d, p in extra.items() if d not in later}
    detail_bbox = None
    if extra:
        def _detail(sv):
            return '<g transform="%s">%s</g>' % (sv.mat(G), ''.join(
                '<g transform="%s">%s</g>' % (sv.mat(p.get('matrix', I)), sv.char(p['id'], sc=Rn.SVG.msc(G) * Rn.SVG.msc(p.get('matrix'))))
                for d, p in sorted(extra.items())))
        detail_bbox = export(_detail, f'{out}/parts_assembly/{n:02d}_detail')
    # oil points: symbols are drawn from their tip, so the child's origin is the oiling point
    oil = []; oil_depth = None; oil_bbox = None
    for d, p in dl.items():
        if p.get('name') == f'Oil{n}MC':
            oil_depth = d; Go = p.get('matrix', I)
            for od, op in sorted(st(swf['sprites'][p['id']]['frames'], 1).items()):
                if 'id' not in op or op['id'] in swf['shapes']: continue
                M = mat_mul(Go, op.get('matrix', I)); tip = app(M, (0, 0))
                oil.append({'type': OIL.get(op['id'], 'symbol %d' % op['id']),
                            'point_stage_px': [round(tip[0], 1), round(tip[1], 1)],
                            'angle_deg': round(math.degrees(math.atan2(M[1], M[0])), 1)})
            spr_o = swf['sprites'][p['id']]
            oil_bbox = export(lambda sv: '<g transform="%s">%s</g>' % (sv.mat(Go), sv.displaylist(spr_o['frames'], 1, sc=Rn.SVG.msc(Go))),
                              f'{out}/parts_assembly/{n:02d}_oil')
    # one-off markers shown only on this step's frame (step 1: asterisks with leader lines)
    markers = []
    nxt = main[fr]['remove'] if fr < len(main) else []
    for p in main[fr - 1]['place']:
        if p['depth'] in nxt and p['depth'] > MOVEMENT_DEPTHS[1] and p.get('id') in swf['sprites']:
            tip = app(p.get('matrix', I), (0, 0))
            markers.append({'char': p['id'], 'at_stage_px': [round(tip[0], 1), round(tip[1], 1)]})

    side, hidden = side_and_hidden(n)
    notes = sorted(set(find_notes(place['id'])) | {m for d, p in dl.items() if p.get('id') in swf['edittexts']
                                                   and d > MOVEMENT_DEPTHS[0] and d < MOVEMENT_DEPTHS[1]
                                                   for m in find_notes(p['id'])})
    # only notes placed on this exact frame count
    placed_now = {p.get('id') for p in main[fr - 1]['place']}
    notes = [m for m in notes if any(m in find_notes(c) for c in placed_now)]
    d = dis_by_clip.get(mc, {})
    same_drawing = bool(d.get('bbox_stage_px') and bbox and max(abs(a - b) for a, b in zip(d['bbox_stage_px'], bbox)) < 1.5)
    steps.append({
        'step': n,
        'part': V.get('name%dgb' % n, '').strip(),
        'part_id': mc,
        'disassembly_step': d.get('step'),
        'names': {LANGS[l]: str(V.get('name%d%s' % (n, l), '')).strip() for l in LANGS},
        'catalog_no': V.get('cs%d' % n) or None,
        'side_up': side,
        **({VF: d.get(VF, False)} if VF else {}),
        'note': ' '.join(V.get('name%sgb' % m, '') for m in notes) or None,
        'oil': oil,
        'markers': markers,
        'swf': {'main_frame': fr, 'clip_name': mc, 'depth': depth, 'sprite': place['id'],
                'anim_frames': len(movers[0]['kf']) - 1 if movers else 0, 'oil_depth': oil_depth,
                'hidden_clips': sorted(hidden)},
        'bbox_stage_px': bbox,
        'same_drawing_as_disassembly': same_drawing,
        'oil_bbox_stage_px': oil_bbox,
        'detail_bbox_stage_px': detail_bbox,
        'motion': phases,
        'path': path,
        'movers': [{'depth': m['depth'], 'char': m['char'],
                    'stage_matrices': [[round(v, 4) for v in mat_mul(G, k)] for k in m['kf']]} for m in movers],
    })
    s = steps[-1]
    print(n, side, s['part'][:30].ljust(30), 'dis', s['disassembly_step'], 'oil', len(oil), 'movers', len(movers),
          'same' if same_drawing else 'DIFF', 'detail' if detail_bbox else '', s['note'] and s['note'][:40])

meta = {'source': A['source'],
        'stage_px': [W, H], 'fps': swf['fps'], 'movement_depths': list(MOVEMENT_DEPTHS),
        'oil_legend': list(A['oil_legend'])}
json.dump({'meta': meta, 'steps': steps}, open(f'{out}/assembly.json', 'w'), indent=1, ensure_ascii=False)

# ---- shared parts list
parts = {}
for s in dis['steps']:
    parts[s['swf']['clip_name']] = {'part': s['part'], 'catalog_no': s['catalog_no'], 'names': s['names'],
                                    **({VF: s[VF]} if VF else {}),
                                    'disassembly_step': s['step'], 'assembly_step': None}
for s in steps:
    parts.setdefault(s['part_id'], {'part': s['part'], 'catalog_no': s['catalog_no'], 'names': s['names'],
                                    **({VF: False} if VF else {}), 'disassembly_step': None})
    parts[s['part_id']]['assembly_step'] = s['step']
    if s['oil']:
        parts[s['part_id']]['oils'] = sorted({o['type'] for o in s['oil'] if o['type'].startswith('Moebius')})
import partsfile
parts = partsfile.merge_kept(parts, partsfile.load(out))   # keep type/art/geom

def y(v):
    if v is None: return 'null'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (int, float)): return repr(v)
    if isinstance(v, list): return '[' + ', '.join(y(x) for x in v) + ']'
    if isinstance(v, dict): return '{' + ', '.join('%s: %s' % (k, y(x)) for k, x in v.items()) + '}'
    return json.dumps(v, ensure_ascii=False)
L = ['# %s assembly sequence, extracted from the SwissLab assembly SWF' % CFG['name'],
     '# (idea and animation: tica international, www.tica.dk). part_id keys into parts.yaml.',
     'meta:'] + ['  %s: %s' % (k, y(v)) for k, v in meta.items()] + ['steps:']
for s in steps:
    L.append('  - step: %d' % s['step'])
    for k in ('part', 'part_id', 'disassembly_step', 'catalog_no', 'side_up', VF, 'note', 'bbox_stage_px'):
        if s.get(k) is not None: L.append('    %s: %s' % (k, y(s[k])))
    if s['oil']:
        L.append('    oil:')
        for o in s['oil']: L.append('      - %s' % y(o))
    if s['markers']: L.append('    markers: %s' % y(s['markers']))
open(f'{out}/assembly.yaml', 'w').write('\n'.join(L) + '\n')
partsfile.save(out, parts, '# %s parts (SwissLab), keyed by SwissLab clip name' % CFG['name'], VF)
