"""Read and write the shared parts list (parts.yaml + parts.json).

parts.yaml is written by the extraction scripts, but three keys per part are kept
across re-extraction because they are maintained by hand or by measure_parts.py:

    type   what kind of part it is, which picks its placeholder drawing
           (wheel, pinion, screw, jewel, balance, plate, bridge, lever, spring, ring, stem)
    art    parameters for the placeholder drawing (tooth count, arms, ...); hand-editable
    geom   where the part sits: pivot, bounding box, stacking order, which face of the
           movement it is on, radius, screw-head positions (written by measure_parts.py)
"""
import json
import os

KEEP = ('type', 'art', 'geom')
ORDER = ('part', 'catalog_no', 'disassembly_step', 'assembly_step', 'differs_6497_1_vs_2', 'oils',
         'type', 'art', 'geom')


def load(out):
    p = os.path.join(out, 'parts.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}


def merge_kept(new, old):
    """carry the hand-maintained keys of `old` over to the freshly extracted `new`"""
    for k, p in new.items():
        for f in KEEP:
            if f in old.get(k, {}) and f not in p:
                p[f] = old[k][f]
    return new


def _y(v):
    if v is None: return 'null'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, float): return ('%.2f' % v).rstrip('0').rstrip('.')
    if isinstance(v, int): return repr(v)
    if isinstance(v, list): return '[' + ', '.join(_y(x) for x in v) + ']'
    if isinstance(v, dict): return '{' + ', '.join('%s: %s' % (k, _y(x)) for k, x in v.items()) + '}'
    return json.dumps(v, ensure_ascii=False)


def save(out, parts, header='# ETA 6497 parts (SwissLab), keyed by SwissLab clip name'):
    json.dump(parts, open(os.path.join(out, 'parts.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    L = [header,
         '# type/art/geom drive the generated ("simple") drawings; see tools/simple_art.py.',
         '# Stage coordinates are SwissLab px (800 x 600, y down).',
         'parts:']
    for k, p in sorted(parts.items(), key=lambda kv: kv[1].get('disassembly_step') or 99):
        L.append('  %s:' % k)
        for f in ORDER:
            if p.get(f) is not None:
                L.append('    %s: %s' % (f, _y(p[f])))
        L.append('    names: %s' % _y(p['names']))
    open(os.path.join(out, 'parts.yaml'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
