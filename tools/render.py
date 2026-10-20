"""Render SWF characters / timeline frames to standalone SVG (and PNG via cairosvg)."""
import sys, os, base64, html
sys.path.insert(0, os.path.dirname(__file__))
import swfparse as P

G = 819.2  # gradient square half-size in px (16384 twips)

class SVG:
    def __init__(self, swf):
        self.swf = swf; self.defs = []; self.uid = 0; self.done = set()

    def nid(self, p='g'):
        self.uid += 1; return '%s%d' % (p, self.uid)

    def mat(self, m):
        return 'matrix(%s)' % ','.join('%.5g' % v for v in m)

    def paint(self, st):
        t = st['type']
        if t == 0:
            return st['color'], st['alpha']
        if t in (0x10, 0x12, 0x13):
            gid = self.nid('grad')
            stops = ''.join('<stop offset="%.4f" stop-color="%s" stop-opacity="%.3f"/>' % s for s in st['stops'])
            spread = ['pad', 'reflect', 'repeat'][min(st.get('spread', 0), 2)]
            a, b, c, d = st['matrix'][:4]
            if abs(a * d - b * c) < 1e-9:  # singular: Flash still draws it; make it invertible
                m = list(st['matrix'])
                if abs(a) + abs(b) < 1e-9: m[0] = 1e-4
                if abs(c) + abs(d) < 1e-9 or abs(m[0] * m[3] - m[1] * m[2]) < 1e-9:
                    # perpendicular vector of tiny length
                    m[2], m[3] = -m[1] * 1e-3 or 1e-4, m[0] * 1e-3 or 1e-4
                st = dict(st, matrix=m)
            if t == 0x10:
                # exact endpoint form: u(x) = row1(M^-1).(x - t); grad u = (d, -c)/det
                a, b, c, d, tx, ty = st['matrix']; det = a * d - b * c
                gx, gy = d / det, -c / det; n2 = gx * gx + gy * gy
                x1, y1 = tx - G * gx / n2, ty - G * gy / n2; x2, y2 = tx + G * gx / n2, ty + G * gy / n2
                self.defs.append('<linearGradient id="%s" gradientUnits="userSpaceOnUse" x1="%.3f" y1="%.3f" x2="%.3f" y2="%.3f" spreadMethod="%s">%s</linearGradient>'
                                 % (gid, x1, y1, x2, y2, spread, stops))
            else:
                fx = st.get('focal', 0) * G
                self.defs.append('<radialGradient id="%s" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="%g" fx="%g" fy="0" spreadMethod="%s" gradientTransform="%s">%s</radialGradient>'
                                 % (gid, G, fx, spread, self.mat(st['matrix']), stops))
            return 'url(#%s)' % gid, 1.0
        if t in (0x40, 0x41, 0x42, 0x43):
            bid = st['bitmap']; jpg = self.swf['bitmaps'].get(bid)
            if jpg is None: return 'none', 0
            from PIL import Image; import io
            w, h = Image.open(io.BytesIO(jpg)).size
            m = list(st['matrix']); m[0] /= 20; m[1] /= 20; m[2] /= 20; m[3] /= 20
            det = m[0] * m[3] - m[1] * m[2]
            if abs(det) > 1e-12:  # wrap translation into one tile period (pattern repeats)
                u = (m[3] * m[4] - m[2] * m[5]) / det; v = (-m[1] * m[4] + m[0] * m[5]) / det
                u %= w; v %= h
                m[4] = m[0] * u + m[2] * v; m[5] = m[1] * u + m[3] * v
            pid = self.nid('pat')
            self.defs.append('<pattern id="%s" patternUnits="userSpaceOnUse" width="%d" height="%d" patternTransform="%s"><image width="%d" height="%d" href="data:image/jpeg;base64,%s"/></pattern>'
                             % (pid, w, h, self.mat(m), w, h, base64.b64encode(jpg).decode()))
            return 'url(#%s)' % pid, 1.0
        return '#ff00ff', 1

    def shape(self, sid, sc=1.0):
        out = []
        for L in self.swf['shapes'][sid]['layers']:
            if not L['d']: continue
            if L['kind'] == 'fill':
                c, a = self.paint(L['style'])
                out.append('<path d="%s" fill="%s"%s/>' % (L['d'], c, '' if a >= 1 else ' fill-opacity="%.3f"' % a))
            else:
                s = L['style']
                out.append('<path d="%s" fill="none" stroke="%s" stroke-width="%g" stroke-linecap="round" stroke-linejoin="round"%s/>'
                           % (L['d'], s['color'], max(s['width'], 1.0 / max(sc, 1e-6)), '' if s['alpha'] >= 1 else ' stroke-opacity="%.3f"' % s['alpha']))
        return ''.join(out)

    def text(self, tid):
        t = self.swf['texts'][tid]; out = ['<g transform="%s">' % self.mat(t['matrix'])]
        for rec in t['records']:
            f = self.swf['fonts'].get(rec['font']);
            if not f: continue
            x = rec['x']; sc = rec['height'] / 1024.0
            for g, adv in rec['glyphs']:
                if g < len(f['glyphs']):
                    d = ''.join(l['d'] for l in f['glyphs'][g])
                    out.append('<path transform="translate(%g,%g) scale(%g)" d="%s" fill="%s"/>' % (x, rec['y'], sc, d, rec['color']))
                x += adv / 20.0
        out.append('</g>'); return ''.join(out)

    def edittext(self, tid, varvalues):
        e = self.swf['edittexts'][tid]; b = e['bounds']
        txt = varvalues.get(e.get('var', ''), e.get('text', ''))
        import re
        txt = html.unescape(re.sub('<[^>]+>', ' ', txt or '')).strip()
        if not txt: return ''
        return '<text x="%g" y="%g" font-family="Arial" font-size="%g" fill="%s">%s</text>' % (
            b[0] + 2, b[2] + e.get('height', 12), e.get('height', 12), e.get('color', '#000'), html.escape(txt))

    def char(self, cid, frame=1, varvalues=None, sprite_frames=None, sc=1.0):
        s = self.swf
        if cid in s['shapes']: return self.shape(cid, sc)
        if cid in s['texts']: return self.text(cid)
        if cid in s['edittexts']: return self.edittext(cid, varvalues or {})
        if cid in s['sprites']:
            fr = (sprite_frames or {}).get(cid, 1)
            return self.displaylist(s['sprites'][cid]['frames'], fr, varvalues, sprite_frames, sc=sc)
        if cid in s['buttons']:
            return ''.join('<g transform="%s">%s</g>' % (self.mat(r['matrix']), self.char(r['id'], 1, varvalues, sprite_frames, sc * self.msc(r['matrix'])))
                           for r in sorted(s['buttons'][cid]['records'], key=lambda r: r['depth']) if 'up' in r['states'])
        return ''

    @staticmethod
    def state(frames, upto):
        dl = {}
        for f in frames[:upto]:
            for d in f['remove']: dl.pop(d, None)
            for p in f['place']:
                if p.get('move') and p['depth'] in dl:
                    q = dict(dl[p['depth']]); q.update({k: v for k, v in p.items() if k != 'move'}); dl[p['depth']] = q
                else:
                    dl[p['depth']] = dict(p)
        return dl

    @staticmethod
    def msc(m):
        return abs(m[0] * m[3] - m[1] * m[2]) ** 0.5 if m else 1.0

    def displaylist(self, frames, upto, varvalues=None, sprite_frames=None, skip=(), sc=1.0, keep=None):
        dl = self.state(frames, upto); out = []; clip_until = None
        for d in sorted(dl):
            p = dl[d]
            if keep and not keep(d, p): continue
            if 'id' not in p or p.get('name') in skip: continue
            inner = self.char(p['id'], 1, varvalues, sprite_frames, sc * self.msc(p.get('matrix')))
            tr = ' transform="%s"' % self.mat(p['matrix']) if 'matrix' in p else ''
            op = ''
            if 'cx' in p and p['cx']['mul'][3] < 1: op = ' opacity="%.3f"' % max(p['cx']['mul'][3] + p['cx']['add'][3] / 255, 0)
            if 'clipdepth' in p:
                cid = self.nid('clip')
                self.defs.append('<clipPath id="%s"><g%s>%s</g></clipPath>' % (cid, tr, inner))
                if clip_until: out.append('</g>')
                out.append('<g clip-path="url(#%s)">' % cid); clip_until = p['clipdepth']; continue
            if clip_until is not None and d > clip_until:
                out.append('</g>'); clip_until = None
            nm = ' data-name="%s"' % p['name'] if 'name' in p else ''
            out.append('<g%s%s%s>%s</g>' % (tr, op, nm, inner))
        if clip_until is not None: out.append('</g>')
        return ''.join(out)

    def document(self, body, vb, bg=None):
        x0, x1, y0, y1 = vb
        bgr = '<rect x="%g" y="%g" width="%g" height="%g" fill="%s"/>' % (x0, y0, x1 - x0, y1 - y0, bg) if bg else ''
        return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="%g %g %g %g" width="%g" height="%g"><defs>%s</defs>%s%s</svg>'
                % (x0, y0, x1 - x0, y1 - y0, x1 - x0, y1 - y0, ''.join(self.defs), bgr, body))

def png(svgtext, path, scale=1.0):
    import cairosvg
    cairosvg.svg2png(bytestring=svgtext.encode(), write_to=path, scale=scale)
