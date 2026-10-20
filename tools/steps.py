"""Reconstruct the disassembly sequence from the SwissLab 6497 SWF and export
steps.yaml plus one SVG (and preview PNG) per part, in stage coordinates."""
import sys, os, io, re, json
sys.path.insert(0, os.path.dirname(__file__))
import swfparse as P, render as Rn
from PIL import Image

swf = P.parse(sys.argv[1]); out = sys.argv[2]
os.makedirs(f'{out}/parts', exist_ok=True)
main = swf['main']['frames']

# ---- variables set in frame 1 (part names, catalog numbers, clip names, warnings)
V = {}
for fr in main[:2]:
    for a in fr['actions']:
        for line in a['src']:
            m = re.match(r"^(\w+) = (.*)$", line)
            if m:
                k, v = m.groups()
                try: v = eval(v)
                except Exception: pass
                V[k] = v

LANGS = {'gb': 'en', 'd': 'de', 'f': 'fr', 'i': 'it', 'e': 'es', 'dk': 'da'}

# ---- which main frame shows which step (counter = N), and which side is up
side = 'dial'; label_side = {'start': 'dial', 'vend1': 'bridge', 'vend2': 'dial', 'tilbage1': 'bridge',
                            'tilbage2': 'dial', 'vend3': 'bridge', 'vend4': 'dial'}
step_frame = {}; frame_side = {}
for i, fr in enumerate(main):
    if fr['label'] in label_side: side = label_side[fr['label']]
    for a in fr['actions']:
        for line in a['src']:
            m = re.match(r'counter = (\d+)', line)
            if m: step_frame[int(m.group(1))] = i + 1
    frame_side[i + 1] = side
# frames 75..96 (vend1..tilbage1) and 97 (vend3) are bridge side; 5,6..12 etc. Use the label that
# introduced the frame's block: blocks start at labelled frames.
def side_of(frame):
    s = 'dial'
    for i in range(frame):
        lab = main[i]['label']
        if lab in label_side: s = label_side[lab]
    return s

UI_DEPTHS = set(range(0, 44)) | set(range(246, 300))

def mat_mul(A, B):  # A then B? returns A*B where (A*B)(p) = A(B(p))
    a1, b1, c1, d1, e1, f1 = A; a2, b2, c2, d2, e2, f2 = B
    return [a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1]

def render_png(svgbody, scale=4):
    sv_doc = svgbody
    import cairosvg
    return Image.open(io.BytesIO(cairosvg.svg2png(bytestring=sv_doc.encode(), scale=scale)))

steps = []
W, H = swf['stage'][1], swf['stage'][3]
for n in sorted(step_frame):
    fr = step_frame[n]; mcname = V.get('mcname%d' % n)
    dl = Rn.SVG.state(main, fr)
    hit = [(d, p) for d, p in dl.items() if p.get('name') == mcname]
    if not hit: print('no clip for step', n, mcname); continue
    depth, place = hit[0]
    spr = swf['sprites'][place['id']]
    # child "first" (the part itself) and its per-frame matrices
    child = [p for p in spr['frames'][0]['place'] if p.get('name') == 'first'][0]
    st = Rn.SVG.state
    mats = []
    for k in range(1, len(spr['frames']) + 1):
        s = st(spr['frames'], k)
        if child['depth'] in s: mats.append(s[child['depth']].get('matrix', [1, 0, 0, 1, 0, 0]))
    G = place.get('matrix', [1, 0, 0, 1, 0, 0])
    # ---- export the part alone, in stage coordinates
    sv = Rn.SVG(swf)
    inner = sv.char(child['id'], sc=Rn.SVG.msc(G) * Rn.SVG.msc(child.get('matrix')))
    body = '<g transform="%s"><g transform="%s">%s</g></g>' % (sv.mat(G), sv.mat(child.get('matrix', [1, 0, 0, 1, 0, 0])), inner)
    doc = sv.document(body, [0, W, 0, H])
    img = render_png(doc, 4); bb = img.getbbox()
    bbox = [round(v / 4, 2) for v in bb] if bb else None  # x0,y0,x1,y1 stage px
    if bbox:
        x0, y0, x1, y1 = bbox; pad = 1
        doc_c = sv.document(body, [x0 - pad, x1 + pad, y0 - pad, y1 + pad])
        open(f'{out}/parts/{n:02d}_{mcname}.svg', 'w').write(doc_c)
        img.crop(bb).save(f'{out}/parts/{n:02d}_{mcname}.png')
    end = mats[-1] if mats else [1, 0, 0, 1, 0, 0]
    # path of the part's bbox center (stage px) and relative scale, one entry per SWF frame;
    # frame 1 = at rest, frame 2 = the destination copy appears, frames 3.. = the motion
    import math
    def inv(M):
        a, b, c, d, e, f = M; det = a * d - b * c
        return [d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det]
    def app(M, p): return (M[0] * p[0] + M[2] * p[1] + M[4], M[1] * p[0] + M[3] * p[1] + M[5])
    c0 = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2) if bbox else (0, 0)
    M0 = mat_mul(G, mats[0]); M0i = inv(M0)
    path = []
    for k, m in enumerate(mats):
        if k == 1: continue
        Mt = mat_mul(G, m); p = app(Mt, app(M0i, c0))
        path.append([round(p[0], 2), round(p[1], 2), round(Rn.SVG.msc(m) / Rn.SVG.msc(mats[0]), 4)])
    # split into phases where the direction of travel changes by more than 25 degrees
    phases = []; cur = None
    for k in range(1, len(path)):
        dx, dy = path[k][0] - path[k - 1][0], path[k][1] - path[k - 1][1]
        ang = math.atan2(dy, dx)
        if cur and abs((ang - cur['ang'] + math.pi) % (2 * math.pi) - math.pi) < math.radians(25):
            cur['to'] = k
        else:
            cur = {'ang': ang, 'from': k - 1, 'to': k}; phases.append(cur)
    phases = [{'from': path[q['from']], 'to': path[q['to']], 'frames': q['to'] - q['from']} for q in phases]
    lift = phases[0]['frames'] if len(phases) > 1 else 0
    # every clip in the part's sprite whose matrix changes = a moving piece (e.g. each screw)
    movers = []
    s1 = st(spr['frames'], 1)
    for dpt, p1 in sorted(s1.items()):
        if 'clipdepth' in p1 or 'id' not in p1: continue
        kf = []
        for k in range(1, len(spr['frames']) + 1):
            if k == 2: continue
            s = st(spr['frames'], k)
            if dpt in s and s[dpt].get('id', p1['id']) == p1['id']:
                kf.append([round(v, 4) for v in mat_mul(G, s[dpt].get('matrix', [1, 0, 0, 1, 0, 0]))])
        if len(kf) > 1 and any(abs(a - b) > 1e-3 for a, b in zip(kf[0], kf[-1])):
            movers.append({'depth': dpt, 'char': p1['id'], 'stage_matrices': kf})
    if not path or len(path) < 2 or (movers and all(m['depth'] != child['depth'] for m in movers)):
        phases = []; path = []
    steps.append({
        'step': n,
        'part': V.get('name%dgb' % n, '').strip(),
        'names': {LANGS[l]: str(V.get('name%d%s' % (n, l), '')).strip() for l in LANGS},
        'catalog_no': V.get('cs%d' % n) or None,
        'side_up': side_of(fr),
        'differs_6497_1_vs_2': bool(V.get('warn%d' % n)),
        'swf': {'main_frame': fr, 'clip_name': mcname, 'depth': depth, 'sprite': place['id'],
                'anim_frames': max(len(mats) - 2, 0), 'lift_frames': lift,
                'place_matrix': [round(v, 5) for v in G],
                'end_matrix': [round(v, 5) for v in end]},
        'bbox_stage_px': bbox,
        'motion': phases,
        'path': path,
        'movers': movers,
    })
    print(n, steps[-1]['side_up'], steps[-1]['part'], bbox)

notes = {3: V.get('name214gb'), 32: V.get('name215gb')}
for s in steps:
    if notes.get(s['step']): s['note'] = notes[s['step']]

meta = {'source': '6497disassem.swf (ETA SwissLab, idea and animation: tica international)',
        'stage_px': [W, H], 'fps': swf['fps'],
        'assembly_note_before_pallet_fork': V.get('name216gb')}
json.dump({'meta': meta, 'steps': steps}, open(f'{out}/steps.json', 'w'), indent=1, ensure_ascii=False)

# YAML (hand-rolled, no dependency)
def y(v):
    if v is None: return 'null'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (int, float)): return repr(v)
    if isinstance(v, list): return '[' + ', '.join(y(x) for x in v) + ']'
    return json.dumps(v, ensure_ascii=False)
L = ['# ETA 6497 disassembly sequence, extracted from the SwissLab SWF', '# (idea and animation: tica international, www.tica.dk)',
     'meta:'] + ['  %s: %s' % (k, y(v)) for k, v in meta.items()] + ['steps:']
for s in steps:
    L.append('  - step: %d' % s['step'])
    for k in ('part', 'catalog_no', 'side_up', 'differs_6497_1_vs_2', 'note', 'bbox_stage_px'):
        if k in s: L.append('    %s: %s' % (k, y(s[k])))
    L.append('    names: {%s}' % ', '.join('%s: %s' % (k, y(v)) for k, v in s['names'].items()))
    L.append('    swf: {%s}' % ', '.join('%s: %s' % (k, y(v)) for k, v in s['swf'].items()))
open(f'{out}/steps.yaml', 'w').write('\n'.join(L) + '\n')
