"""Render the images a Manim step scene needs.

    python -I tools/prep_assets.py [--assembly] [--art original|simple] SWF OUT STEP [STEP ...]
    python -I tools/prep_assets.py [--assembly] --art simple OUT STEP [STEP ...]

--art original (default) draws ETA/tica's artwork straight from your SWF: for private use only.
--art simple draws generated placeholders from parts.yaml (tools/simple_art.py) and needs no SWF;
    this is the version that can be published.

Writes OUT/assets/<art>/{step|asm}NN_bg.png (the movement at that step with the part removed /
not yet fitted, cropped to the movement window) and ..._part.png; for original art also the oil
overlay, the edge-on detail drawing and the unmasked "free" drawing, when the step has them.
For simple art, ..._part.json gives the image's stage bbox and a tight bbox for the highlight.
Both styles also get hero.png: the complete movement in generated art, for the title card.
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(__file__))

WINDOW = [18, 122, 432, 512]   # x0, y0, x1, y1 of SwissLab's movement window (stage px)
SCALE = 4
PAD = 4                        # stage px around a generated part (outline + shadow)
HERO = [30, 130, 430, 506]     # stage px shown on the title card: the movement and a stub of the stem


def parse_args(argv):
    asm = '--assembly' in argv
    art = 'original'
    rest = []
    it = iter(argv)
    for a in it:
        if a == '--assembly': continue
        if a == '--art': art = next(it); continue
        if a.startswith('--art='): art = a.split('=', 1)[1]; continue
        rest.append(a)
    if art not in ('original', 'simple'):
        sys.exit('--art must be original or simple')
    swf = rest.pop(0) if rest and rest[0].lower().endswith('.swf') else None
    if art == 'original' and not swf:
        sys.exit('--art original needs the SwissLab SWF')
    out = rest.pop(0)
    return asm, art, swf, out, [int(n) for n in rest]


def prep_original(swf_path, out, asm, data, steps, dst, pre):
    import render as Rn
    import swfparse as P
    swf = P.parse(swf_path)
    lo, hi = data['meta'].get('movement_depths', [44, 245])
    for n in steps:
        s = data['steps'][n - 1]; fr = s['swf']['main_frame']
        skip = {s['swf']['depth'], s['swf'].get('oil_depth')}
        hidden = set(s['swf'].get('hidden_clips', []))
        keep = lambda d, p: lo <= d <= hi and d not in skip and p.get('name') not in hidden
        sv = Rn.SVG(swf)
        body = sv.displaylist(swf['main']['frames'], fr, keep=keep)
        x0, y0, x1, y1 = WINDOW
        Rn.png(sv.document(body, [x0, x1, y0, y1], '#ffffff'), f'{dst}/{pre}{n:02d}_bg.png', SCALE)
        # drawings written by tools/steps.py / steps_assembly.py, found by their file names
        clip = s['swf']['clip_name']
        drawing = (f'{out}/parts_assembly/{n:02d}_{clip}.png' if asm else f'{out}/parts/{n:02d}_{clip}.png')
        if not os.path.exists(drawing):
            sys.exit(f'{drawing} is missing: run tools/steps.py and tools/steps_assembly.py on your SWFs first')
        shutil.copy(drawing, f'{dst}/{pre}{n:02d}_part.png')
        if asm and s.get('disassembly_step'):
            # the same part from the shared parts list, without the in-place mask: used while it flies
            d = json.load(open(f'{out}/steps.json'))['steps'][s['disassembly_step'] - 1]
            free = f"{out}/parts/{d['step']:02d}_{d['swf']['clip_name']}.png"
            if os.path.exists(free):
                shutil.copy(free, f'{dst}/{pre}{n:02d}_free.png')
                json.dump(d['bbox_stage_px'], open(f'{dst}/{pre}{n:02d}_free.json', 'w'))
        for kind in ('detail', 'oil'):
            src = f'{out}/parts_assembly/{n:02d}_{kind}.png'
            if asm and os.path.exists(src):
                shutil.copy(src, f'{dst}/{pre}{n:02d}_{kind}.png')
        print(pre, n, 'original assets written')


def tight_bbox(png_path, img_bbox):
    from PIL import Image
    im = Image.open(png_path).getchannel('A')
    b = im.getbbox()
    x0, y0, x1, y1 = img_bbox
    sx, sy = (x1 - x0) / im.width, (y1 - y0) / im.height
    return [round(x0 + b[0] * sx, 2), round(y0 + b[1] * sy, 2), round(x0 + b[2] * sx, 2), round(y0 + b[3] * sy, 2)]


def prep_simple(out, asm, data, steps, dst, pre):
    import cairosvg
    import simple_art as SA
    parts = SA.load(out)
    seq = 'assembly_step' if asm else 'disassembly_step'
    for n in steps:
        s = data['steps'][n - 1]; side = s['side_up']
        cur = s['part_id'] if asm else s['swf']['clip_name']
        if asm:   # already fitted
            ids = [k for k, p in parts.items() if p.get(seq) and p[seq] < n]
        else:     # still in the movement
            ids = [k for k, p in parts.items() if (p.get(seq) or 0) > n]
        ids = [k for k in ids if SA.on_face(parts, k, side)]
        cairosvg.svg2png(bytestring=SA.document(SA.scene(parts, ids, side), WINDOW, '#ffffff').encode(),
                         write_to=f'{dst}/{pre}{n:02d}_bg.png', scale=SCALE)
        x0, y0, x1, y1 = s['bbox_stage_px']
        ib = [x0 - PAD, y0 - PAD, x1 + PAD, y1 + PAD]
        png = f'{dst}/{pre}{n:02d}_part.png'
        cairosvg.svg2png(bytestring=SA.document(SA.part(parts, cur), ib).encode(), write_to=png, scale=SCALE)
        json.dump({'image_bbox': ib, 'highlight_bbox': tight_bbox(png, ib)}, open(png.replace('.png', '.json'), 'w'))
        print(pre, n, 'simple assets written')


def prep_hero(out, dst):
    """the complete movement, bridge side up, for the title card. Always the generated art, so the
    title card is the same in both styles."""
    import cairosvg
    import simple_art as SA
    parts = SA.load(out)
    ids = [k for k in parts if SA.on_face(parts, k, 'bridge')]
    cairosvg.svg2png(bytestring=SA.document(SA.scene(parts, ids, 'bridge'), HERO).encode(),
                     write_to=f'{dst}/hero.png', scale=SCALE)


def main():
    asm, art, swf, out, steps = parse_args(sys.argv[1:])
    data = json.load(open(f"{out}/{'assembly' if asm else 'steps'}.json"))
    dst = f'{out}/assets/{art}'
    os.makedirs(dst, exist_ok=True)
    pre = 'asm' if asm else 'step'
    if art == 'original':
        prep_original(swf, out, asm, data, steps, dst, pre)
    else:
        prep_simple(out, asm, data, steps, dst, pre)
    prep_hero(out, dst)


if __name__ == '__main__':
    main()
