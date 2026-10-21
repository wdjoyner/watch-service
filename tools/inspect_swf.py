"""Print what a SwissLab SWF holds, to fill in a new caliber's caliber.yaml.

    python -I tools/inspect_swf.py /path/to/2824disasm.swf
    python -I tools/inspect_swf.py /path/to/6497assem.swf --check calibers/6497

Reports:
  - whether it is a step animation at all (SwissLab's menu file, e.g. 2892A2.swf, only
    loads <caliber>disasm.swf / <caliber>asm.swf / <caliber>tools.swf; it names them)
  - the number of steps (frames that set `counter = N`) and the clip name of each step
  - the main timeline's frame labels and the steps between them (side_labels: the label
    that starts a block of steps sets the side up for that block)
  - the depth range of the step clips on the main timeline (movement_depths)
  - text variables that are not part names: notes (name214gb ...)
  - in an assembly file: the character IDs used inside the Oil<n>MC clips, with how
    often each occurs (oil_symbols: look at the legend to name them)

--check compares what can be derived (step count, depth range, note variables, oil-symbol
IDs) with the caliber's caliber.yaml and lists the differences.
"""
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import render as Rn  # noqa: E402
import swfparse as P  # noqa: E402


def variables(main):
    V = {}
    for fr in main[:2]:
        for a in fr['actions']:
            for line in a['src']:
                m = re.match(r"^(\w+) = (.*)$", line)
                if m:
                    V[m.group(1)] = m.group(2).strip("'\"")
    return V


def inspect(path):
    swf = P.parse(path)
    main = swf['main']['frames']
    rep = {'file': os.path.basename(path), 'frames': len(main), 'stage': swf['stage'], 'fps': swf['fps']}
    loads = set()
    for b in swf['buttons'].values():
        for c in b['actions']:
            loads |= {s for line in c['asm'] for s in re.findall(r"'([\w.-]+\.swf)'", line)}
    for fr in main:
        for a in fr['actions']:
            for line in a['asm']:
                loads |= set(re.findall(r"'(\w+(?:asm|disasm|tools))'", line))
    rep['loads'] = sorted(loads)

    V = variables(main)
    step_frame = {}
    for i, fr in enumerate(main):
        for a in fr['actions']:
            for line in a['src']:
                m = re.match(r'counter = (\d+)', line)
                if m:
                    step_frame[int(m.group(1))] = i + 1
    rep['steps'] = len(step_frame)
    if not step_frame:
        return rep
    N = max(step_frame)
    rep['clips'] = {n: V.get('mcname%d' % n) for n in sorted(step_frame)}

    # frame labels, and the steps that follow each label until the next one
    labels = [(i + 1, fr['label']) for i, fr in enumerate(main) if fr['label']]
    blocks = []
    for k, (f, lab) in enumerate(labels):
        f_next = labels[k + 1][0] if k + 1 < len(labels) else len(main) + 1
        blocks.append((lab, f, sorted(n for n, sf in step_frame.items() if f <= sf < f_next)))
    rep['labels'] = blocks

    # depth range of the step clips
    depths = []
    for n, f in step_frame.items():
        for d, p in Rn.SVG.state(main, f).items():
            if p.get('name') == V.get('mcname%d' % n):
                depths.append(d)
    rep['step_clip_depths'] = [min(depths), max(depths)] if depths else None

    # text variables beyond the per-step names: notes
    per_step = re.compile(r'^(name|cs|warn|mcname)(\d+)')
    notes = {}
    for k, v in V.items():
        m = re.match(r'^name(\d+)gb$', k)
        if m and int(m.group(1)) > N and len(v) >= 25:     # shorter ones are the interface's words
            notes['name' + m.group(1)] = v
    rep['note_vars'] = notes
    rep['edit_text_vars'] = sorted({e.get('var', '') for e in swf['edittexts'].values()
                                    if e.get('var') and not per_step.match(e['var'])})

    # oil symbols inside Oil<n>MC clips (assembly files)
    oil = collections.Counter()
    for n, f in step_frame.items():
        for d, p in Rn.SVG.state(main, f).items():
            if p.get('name') == 'Oil%dMC' % n and p.get('id') in swf['sprites']:
                for od, op in Rn.SVG.state(swf['sprites'][p['id']]['frames'], 1).items():
                    if 'id' in op and op['id'] not in swf['shapes']:
                        oil[op['id']] += 1
    rep['oil_symbol_ids'] = dict(sorted(oil.items()))
    return rep


def show(rep):
    print('%s: %d main frames, stage %s, %d fps' % (rep['file'], rep['frames'], rep['stage'], rep['fps']))
    if rep.get('loads'):
        print('  loads / names other files:', ', '.join(rep['loads']))
    if not rep['steps']:
        print('  no step animation here (no frame sets `counter = N`): this is not a disassembly or assembly file')
        return
    print('  steps: %d' % rep['steps'])
    print('  frame labels (label @ frame: steps that follow it):')
    for lab, f, steps in rep['labels']:
        rng = '%d-%d' % (steps[0], steps[-1]) if steps else '-'
        print('    %-12s @ %4d: %s' % (lab, f, rng))
    print('  depth range of the step clips:', rep['step_clip_depths'])
    if rep['note_vars']:
        print('  note variables:')
        for k, v in rep['note_vars'].items():
            print('    %s: %s' % (k, v[:90]))
    if rep['edit_text_vars']:
        print('  other edit-text variables:', ', '.join(rep['edit_text_vars']))
    if rep['oil_symbol_ids']:
        print('  oil-symbol character IDs (id: times used):', rep['oil_symbol_ids'])


def check(rep, cal):
    import caliber
    cfg = caliber.load(cal)['swisslab']
    sec = 'assembly' if rep['oil_symbol_ids'] else 'disassembly'
    c = cfg.get(sec, {})
    diffs = []
    lo, hi = c.get('movement_depths', [None, None])
    d = rep.get('step_clip_depths')
    if d and lo is not None and not (lo <= d[0] and d[1] <= hi):
        diffs.append('step clips at depths %s lie outside movement_depths %s' % (d, [lo, hi]))
    if sec == 'disassembly':
        want = set(c.get('notes', {}).values()) | ({c['assembly_note']} if c.get('assembly_note') else set())
        if want != set(rep['note_vars']):
            diffs.append('note variables: caliber.yaml %s, SWF %s' % (sorted(want), sorted(rep['note_vars'])))
        labs = {lab for lab, _, _ in rep['labels']}
        missing = labs - set(c.get('side_labels', {}))
        if missing:
            diffs.append('frame labels without a side in side_labels: %s' % sorted(missing))
    else:
        ids = {int(k) for k in c.get('oil_symbols', {})}
        if not set(rep['oil_symbol_ids']) <= ids:
            diffs.append('oil-symbol IDs not in oil_symbols: %s' % sorted(set(rep['oil_symbol_ids']) - ids))
    print('check against %s (%s):' % (os.path.join(cal, 'caliber.yaml'), sec))
    print('  ' + ('\n  '.join(diffs) if diffs else 'no differences'))


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--check']
    rep = inspect(args[0])
    show(rep)
    if '--check' in sys.argv and rep['steps']:
        check(rep, args[1])
