"""Minimal SWF (Flash 8 / AVM1) parser: shapes -> SVG paths, sprites/timelines,
buttons, text, fonts, bitmaps, and an AVM1 disassembler.

Usage: python -I swfparse.py file.swf outdir
"""
import sys, os, zlib, struct, json, math

# ---------------------------------------------------------------- readers
class R:
    def __init__(self, data, pos=0):
        self.d = data; self.p = pos; self.bitpos = 0; self.bitbuf = 0
    def align(self):
        self.bitpos = 0
    def ub(self, n):
        v = 0
        for _ in range(n):
            if self.bitpos == 0:
                self.bitbuf = self.d[self.p]; self.p += 1; self.bitpos = 8
            self.bitpos -= 1
            v = (v << 1) | ((self.bitbuf >> self.bitpos) & 1)
        return v
    def sb(self, n):
        if n == 0: return 0
        v = self.ub(n)
        if v >> (n - 1): v -= 1 << n
        return v
    def fb(self, n):
        return self.sb(n) / 65536.0
    def u8(self):
        self.align(); v = self.d[self.p]; self.p += 1; return v
    def u16(self):
        self.align(); v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2; return v
    def s16(self):
        self.align(); v = struct.unpack_from('<h', self.d, self.p)[0]; self.p += 2; return v
    def u32(self):
        self.align(); v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v
    def f32(self):
        self.align(); v = struct.unpack_from('<f', self.d, self.p)[0]; self.p += 4; return v
    def f64(self):
        # AVM1 double: two 32-bit words swapped
        self.align(); b = self.d[self.p:self.p + 8]; self.p += 8
        return struct.unpack('<d', b[4:] + b[:4])[0]
    def s32(self):
        self.align(); v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v
    def string(self):
        self.align(); e = self.d.index(b'\0', self.p); s = self.d[self.p:e]; self.p = e + 1
        try: return s.decode('utf-8')
        except UnicodeDecodeError: return s.decode('latin-1')
    def bytes(self, n):
        self.align(); b = self.d[self.p:self.p + n]; self.p += n; return b
    def rect(self):
        self.align(); n = self.ub(5)
        v = [self.sb(n) for _ in range(4)]; self.align(); return v  # xmin,xmax,ymin,ymax twips
    def matrix(self):
        self.align()
        a = d = 1.0; b = c = 0.0
        if self.ub(1):
            n = self.ub(5); a = self.fb(n); d = self.fb(n)
        if self.ub(1):
            n = self.ub(5); b = self.fb(n); c = self.fb(n)
        n = self.ub(5); tx = self.sb(n); ty = self.sb(n)
        self.align()
        # x' = a x + c y + tx ; y' = b x + d y + ty   (SVG matrix(a,b,c,d,tx,ty))
        return [a, b, c, d, tx / 20.0, ty / 20.0]
    def cxform(self, alpha=True):
        self.align(); hasadd = self.ub(1); hasmul = self.ub(1); n = self.ub(4)
        k = 4 if alpha else 3
        mul = [self.sb(n) / 256.0 for _ in range(k)] if hasmul else [1.0] * k
        add = [self.sb(n) for _ in range(k)] if hasadd else [0] * k
        self.align()
        if not alpha: mul.append(1.0); add.append(0)
        return {'mul': mul, 'add': add}

def rgb(r): return '#%02x%02x%02x' % (r.u8(), r.u8(), r.u8())
def rgba(r):
    c = '#%02x%02x%02x' % (r.u8(), r.u8(), r.u8()); return c, r.u8() / 255.0

# ---------------------------------------------------------------- shapes
def read_fillstyle(r, ver):
    t = r.u8(); fs = {'type': t}
    if t == 0:
        if ver >= 3: fs['color'], fs['alpha'] = rgba(r)
        else: fs['color'] = rgb(r); fs['alpha'] = 1.0
    elif t in (0x10, 0x12, 0x13):
        fs['matrix'] = r.matrix()
        r.align(); spread = r.ub(2); interp = r.ub(2); n = r.ub(4)
        stops = []
        for _ in range(n):
            ratio = r.u8()
            if ver >= 3: c, a = rgba(r)
            else: c, a = rgb(r), 1.0
            stops.append((ratio / 255.0, c, a))
        fs['stops'] = stops; fs['spread'] = spread
        if t == 0x13: fs['focal'] = r.s16() / 256.0
    elif t in (0x40, 0x41, 0x42, 0x43):
        fs['bitmap'] = r.u16(); fs['matrix'] = r.matrix()
    else:
        raise ValueError('fillstyle %x' % t)
    return fs

def read_styles(r, ver):
    n = r.u8()
    if n == 0xFF and ver >= 2: n = r.u16()
    fills = [read_fillstyle(r, ver) for _ in range(n)]
    n = r.u8()
    if n == 0xFF: n = r.u16()
    lines = []
    for _ in range(n):
        w = r.u16() / 20.0
        if ver == 4:
            r.align(); sc = r.ub(2); join = r.ub(2); hasfill = r.ub(1); r.ub(1); r.ub(1); r.ub(1); r.ub(5); r.ub(1); ec = r.ub(2)
            if join == 2: r.u16()
            if hasfill:
                f = read_fillstyle(r, ver); col = f.get('color', '#888888'); a = f.get('alpha', 1.0)
                if 'stops' in f: col, a = f['stops'][0][1], f['stops'][0][2]
            else: col, a = rgba(r)
            lines.append({'width': w, 'color': col, 'alpha': a, 'cap': sc, 'join': join})
        else:
            if ver >= 3: col, a = rgba(r)
            else: col, a = rgb(r), 1.0
            lines.append({'width': w, 'color': col, 'alpha': a})
    return fills, lines

def read_shape_records(r, ver, fills, lines, with_styles=True):
    """Returns list of style groups: each {'fills','lines','edges'} with edges
    (fill0, fill1, line, kind, pts) in twips."""
    r.align(); nfb = r.ub(4); nlb = r.ub(4)
    groups = [{'fills': fills, 'lines': lines, 'edges': []}]
    x = y = 0; f0 = f1 = ln = 0
    while True:
        if r.ub(1) == 0:
            newst = r.ub(1); sl = r.ub(1); sf1 = r.ub(1); sf0 = r.ub(1); mv = r.ub(1)
            if not (newst or sl or sf1 or sf0 or mv): break
            if mv:
                n = r.ub(5); x = r.sb(n); y = r.sb(n)
            if sf0: f0 = r.ub(nfb)
            if sf1: f1 = r.ub(nfb)
            if sl: ln = r.ub(nlb)
            if newst:
                fl, ll = read_styles(r, ver)
                groups.append({'fills': fl, 'lines': ll, 'edges': []})
                r.align(); nfb = r.ub(4); nlb = r.ub(4)
                f0 = f1 = ln = 0
        else:
            straight = r.ub(1); n = r.ub(4) + 2
            if straight:
                if r.ub(1): dx = r.sb(n); dy = r.sb(n)
                elif r.ub(1): dx = 0; dy = r.sb(n)
                else: dx = r.sb(n); dy = 0
                e = (f0, f1, ln, 'L', ((x, y), (x + dx, y + dy)))
                x += dx; y += dy
            else:
                cx = x + r.sb(n); cy = y + r.sb(n); ax = cx + r.sb(n); ay = cy + r.sb(n)
                e = (f0, f1, ln, 'Q', ((x, y), (cx, cy), (ax, ay)))
                x, y = ax, ay
            groups[-1]['edges'].append(e)
    r.align()
    return groups

def _rev(kind, pts): return (kind, tuple(reversed(pts)))

def chain(edges):
    """Join directed edges into closed/open subpaths."""
    edges = list(edges); paths = []
    bystart = {}
    for i, (k, p) in enumerate(edges): bystart.setdefault(p[0], []).append(i)
    used = [False] * len(edges)
    for i in range(len(edges)):
        if used[i]: continue
        used[i] = True; path = [edges[i]]; start = edges[i][1][0]; end = edges[i][1][-1]
        while end != start:
            nxt = None
            for j in bystart.get(end, []):
                if not used[j]: nxt = j; break
            if nxt is None: break
            used[nxt] = True; path.append(edges[nxt]); end = edges[nxt][1][-1]
        paths.append(path)
    return paths

def tw(v): return ('%.2f' % (v / 20.0)).rstrip('0').rstrip('.')

def path_d(paths, close=True):
    out = []
    for path in paths:
        p0 = path[0][1][0]; out.append('M%s %s' % (tw(p0[0]), tw(p0[1])))
        for k, p in path:
            if k == 'L': out.append('L%s %s' % (tw(p[1][0]), tw(p[1][1])))
            else: out.append('Q%s %s %s %s' % (tw(p[1][0]), tw(p[1][1]), tw(p[2][0]), tw(p[2][1])))
        if close and path[-1][1][-1] == p0: out.append('Z')
    return ''.join(out)

def shape_to_layers(groups):
    """List of drawable layers in paint order: {'kind':'fill'|'line','style':..,'d':..}"""
    layers = []
    for g in groups:
        per_fill = {}
        per_line = {}
        for f0, f1, ln, k, p in g['edges']:
            if f1: per_fill.setdefault(f1, []).append((k, p))
            if f0: per_fill.setdefault(f0, []).append(_rev(k, p))
            if ln: per_line.setdefault(ln, []).append((k, p))
        for idx in sorted(per_fill):
            if idx - 1 < len(g['fills']):
                layers.append({'kind': 'fill', 'style': g['fills'][idx - 1], 'd': path_d(chain(per_fill[idx]))})
        for idx in sorted(per_line):
            if idx - 1 < len(g['lines']):
                layers.append({'kind': 'line', 'style': g['lines'][idx - 1], 'd': path_d(chain(per_line[idx]), close=True)})
    return layers

# ---------------------------------------------------------------- AVM1
ACT = {0x04: 'nextFrame', 0x05: 'prevFrame', 0x06: 'play', 0x07: 'stop', 0x08: 'toggleQuality', 0x09: 'stopSounds',
       0x0A: 'add', 0x0B: 'subtract', 0x0C: 'multiply', 0x0D: 'divide', 0x0E: 'equals', 0x0F: 'less', 0x10: 'and',
       0x11: 'or', 0x12: 'not', 0x13: 'stringEquals', 0x14: 'stringLength', 0x15: 'stringExtract', 0x17: 'pop',
       0x18: 'toInteger', 0x1C: 'getVariable', 0x1D: 'setVariable', 0x20: 'setTarget2', 0x21: 'stringAdd',
       0x22: 'getProperty', 0x23: 'setProperty', 0x24: 'cloneSprite', 0x25: 'removeSprite', 0x26: 'trace',
       0x27: 'startDrag', 0x28: 'endDrag', 0x29: 'stringLess', 0x2A: 'throw', 0x2B: 'castOp', 0x2C: 'implementsOp',
       0x30: 'randomNumber', 0x31: 'mbStringLength', 0x32: 'charToAscii', 0x33: 'asciiToChar', 0x34: 'getTime',
       0x35: 'mbStringExtract', 0x36: 'mbCharToAscii', 0x37: 'mbAsciiToChar', 0x3A: 'delete', 0x3B: 'delete2',
       0x3C: 'defineLocal', 0x3D: 'callFunction', 0x3E: 'return', 0x3F: 'modulo', 0x40: 'newObject', 0x41: 'defineLocal2',
       0x42: 'initArray', 0x43: 'initObject', 0x44: 'typeOf', 0x45: 'targetPath', 0x46: 'enumerate', 0x47: 'add2',
       0x48: 'less2', 0x49: 'equals2', 0x4A: 'toNumber', 0x4B: 'toString', 0x4C: 'pushDuplicate', 0x4D: 'stackSwap',
       0x4E: 'getMember', 0x4F: 'setMember', 0x50: 'increment', 0x51: 'decrement', 0x52: 'callMethod', 0x53: 'newMethod',
       0x54: 'instanceOf', 0x55: 'enumerate2', 0x60: 'bitAnd', 0x61: 'bitOr', 0x62: 'bitXor', 0x63: 'bitLShift',
       0x64: 'bitRShift', 0x65: 'bitURShift', 0x66: 'strictEquals', 0x67: 'greater', 0x68: 'stringGreater', 0x69: 'extends',
       0x81: 'gotoFrame', 0x83: 'getURL', 0x87: 'storeRegister', 0x88: 'constantPool', 0x8A: 'waitForFrame',
       0x8B: 'setTarget', 0x8C: 'goToLabel', 0x8D: 'waitForFrame2', 0x8E: 'defineFunction2', 0x8F: 'try', 0x94: 'with',
       0x96: 'push', 0x99: 'jump', 0x9A: 'getURL2', 0x9B: 'defineFunction', 0x9D: 'if', 0x9E: 'call', 0x9F: 'gotoFrame2'}

def disasm(data, pool=None):
    """Return list of (offset, text) lines; also returns structured ops."""
    r = R(data); out = []; ops = []
    pool = pool if pool is not None else []
    while r.p < len(data):
        off = r.p; code = r.u8()
        if code == 0: out.append((off, 'end')); ops.append(('end',)); break
        ln = r.u16() if code >= 0x80 else 0
        body = data[r.p:r.p + ln]; r.p += ln
        name = ACT.get(code, 'op%02x' % code); arg = ''
        br = R(body)
        if code == 0x88:
            n = br.u16(); pool[:] = [br.string() for _ in range(n)]; arg = repr(pool)
            ops.append(('constantPool', list(pool)))
        elif code == 0x96:
            vals = []
            while br.p < len(body):
                t = br.u8()
                if t == 0: vals.append(br.string())
                elif t == 1: vals.append(br.f32())
                elif t == 2: vals.append(None)
                elif t == 3: vals.append('undefined')
                elif t == 4: vals.append('r:%d' % br.u8())
                elif t == 5: vals.append(bool(br.u8()))
                elif t == 6: vals.append(br.f64())
                elif t == 7: vals.append(br.s32())
                elif t == 8: i = br.u8(); vals.append(pool[i] if i < len(pool) else 'c%d' % i)
                elif t == 9: i = br.u16(); vals.append(pool[i] if i < len(pool) else 'c%d' % i)
                else: vals.append('?'); break
            arg = ', '.join(repr(v) for v in vals); ops.append(('push', vals))
        elif code == 0x81:
            f = br.u16(); arg = str(f); ops.append(('gotoFrame', f))
        elif code == 0x8C:
            s = br.string(); arg = repr(s); ops.append(('goToLabel', s))
        elif code == 0x8B:
            s = br.string(); arg = repr(s); ops.append(('setTarget', s))
        elif code == 0x83:
            a = br.string(); b = br.string(); arg = '%r %r' % (a, b); ops.append(('getURL', a, b))
        elif code in (0x99, 0x9D):
            o = struct.unpack('<h', body[:2])[0]; arg = '-> %d' % (r.p + o); ops.append((name, r.p + o))
        elif code == 0x9F:
            f = body[0]; arg = 'play' if f & 1 else 'stop'; ops.append(('gotoFrame2', bool(f & 1)))
        elif code == 0x9B:
            fn = br.string(); n = br.u16(); params = [br.string() for _ in range(n)]; size = br.u16()
            arg = '%s(%s) [%d bytes]' % (fn, ','.join(params), size); ops.append(('defineFunction', fn, params))
        elif code == 0x8E:
            fn = br.string(); n = br.u16(); br.u8(); br.u16(); params = []
            for _ in range(n): br.u8(); params.append(br.string())
            size = br.u16(); arg = '%s(%s) [%d bytes]' % (fn, ','.join(params), size); ops.append(('defineFunction2', fn, params))
        elif code == 0x87:
            arg = 'r%d' % body[0]; ops.append(('storeRegister', body[0]))
        else:
            ops.append((name,))
        out.append((off, (name + ' ' + arg).strip()))
    return out, ops

def summarize_actions(ops):
    """Very small decompiler for the common Flash 8 idioms:
    push args; push target; getVariable/getMember...; callMethod -> target.method(args)"""
    stack = []; res = []
    for op in ops:
        n = op[0]
        if n == 'push': stack.extend(op[1])
        elif n == 'getVariable':
            v = stack.pop() if stack else '?'; stack.append(str(v))
        elif n == 'getMember':
            m = stack.pop() if stack else '?'; o = stack.pop() if stack else '?'; stack.append('%s.%s' % (o, m))
        elif n == 'setVariable':
            v = stack.pop() if stack else '?'; k = stack.pop() if stack else '?'; res.append('%s = %r' % (k, v))
        elif n == 'setMember':
            v = stack.pop() if stack else '?'; m = stack.pop() if stack else '?'; o = stack.pop() if stack else '?'
            res.append('%s.%s = %r' % (o, m, v))
        elif n in ('callMethod', 'callFunction'):
            if n == 'callMethod':
                m = stack.pop() if stack else '?'; o = stack.pop() if stack else '?'; fn = '%s.%s' % (o, m) if m not in (None, 'undefined', '') else str(o)
            else:
                fn = str(stack.pop() if stack else '?')
            k = stack.pop() if stack else 0
            try: k = int(k)
            except Exception: k = 0
            args = [stack.pop() for _ in range(min(k, len(stack)))]
            stack.append('%s(%s)' % (fn, ', '.join(repr(a) for a in args)))
        elif n == 'pop':
            if stack: res.append(str(stack.pop()))
        elif n in ('stop', 'play', 'nextFrame', 'prevFrame'): res.append(n + '()')
        elif n == 'gotoFrame': res.append('gotoFrame(%d)' % (op[1] + 1))
        elif n == 'goToLabel': res.append('gotoLabel(%r)' % op[1])
        elif n == 'setTarget': res.append('setTarget(%r)' % op[1])
        elif n == 'gotoFrame2':
            f = stack.pop() if stack else '?'; res.append('goto%s(%r)' % ('AndPlay' if op[1] else 'AndStop', f))
        elif n == 'getURL': res.append('getURL(%r, %r)' % (op[1], op[2]))
        elif n in ('defineFunction', 'defineFunction2'): res.append('function %s(%s) {...}' % (op[1], ','.join(op[2])))
        elif n in ('if', 'jump'): res.append('%s ->%d' % (n, op[1]))
        elif n in ('equals2', 'less2', 'add2', 'greater', 'strictEquals', 'subtract', 'multiply', 'divide', 'and', 'or'):
            b = stack.pop() if stack else '?'; a = stack.pop() if stack else '?'; stack.append('(%s %s %s)' % (a, n, b))
        elif n == 'not':
            a = stack.pop() if stack else '?'; stack.append('!(%s)' % (a,))
        elif n == 'getProperty':
            p = stack.pop() if stack else '?'; t = stack.pop() if stack else '?'; stack.append('getProperty(%s,%s)' % (t, p))
        elif n == 'setProperty':
            v = stack.pop() if stack else '?'; p = stack.pop() if stack else '?'; t = stack.pop() if stack else '?'
            res.append('setProperty(%s,%s,%r)' % (t, p, v))
        elif n == 'end': pass
        elif n == 'constantPool': pass
        else: res.append(n)
    return res

# ---------------------------------------------------------------- top level
TAGNAMES = {0: 'End', 1: 'ShowFrame', 2: 'DefineShape', 4: 'PlaceObject', 5: 'RemoveObject', 6: 'DefineBits',
            9: 'SetBackgroundColor', 10: 'DefineFont', 11: 'DefineText', 12: 'DoAction', 21: 'DefineBitsJPEG2',
            22: 'DefineShape2', 24: 'Protect', 26: 'PlaceObject2', 28: 'RemoveObject2', 32: 'DefineShape3',
            33: 'DefineText2', 34: 'DefineButton2', 37: 'DefineEditText', 39: 'DefineSprite', 43: 'FrameLabel',
            48: 'DefineFont2', 69: 'FileAttributes', 73: 'DefineFontAlignZones', 74: 'CSMTextSettings',
            75: 'DefineFont3', 83: 'DefineShape4'}

def read_tags(data, pos):
    tags = []
    while pos < len(data):
        h = struct.unpack_from('<H', data, pos)[0]; pos += 2
        code, ln = h >> 6, h & 63
        if ln == 63: ln = struct.unpack_from('<I', data, pos)[0]; pos += 4
        tags.append((code, data[pos:pos + ln])); pos += ln
        if code == 0: break
    return tags

def parse_timeline(tags, swf, pool):
    frames = []; cur = {'place': [], 'remove': [], 'actions': [], 'label': None}
    for code, body in tags:
        if code == 1:
            frames.append(cur); cur = {'place': [], 'remove': [], 'actions': [], 'label': None}
        elif code == 26:
            r = R(body); fl = r.u8(); p = {'depth': r.u16()}
            p['move'] = bool(fl & 1)
            if fl & 2: p['id'] = r.u16()
            if fl & 4: p['matrix'] = r.matrix()
            if fl & 8: p['cx'] = r.cxform(True)
            if fl & 16: p['ratio'] = r.u16()
            if fl & 32: p['name'] = r.string()
            if fl & 64: p['clipdepth'] = r.u16()
            if fl & 128: p['clipactions'] = True
            cur['place'].append(p)
        elif code == 28:
            cur['remove'].append(struct.unpack('<H', body[:2])[0])
        elif code == 5:
            cur['remove'].append(struct.unpack('<H', body[2:4])[0])
        elif code == 43:
            cur['label'] = body.split(b'\0')[0].decode('latin-1')
        elif code == 12:
            lines, ops = disasm(body, pool)
            cur['actions'].append({'asm': [l for _, l in lines], 'src': summarize_actions(ops)})
        elif code != 0:
            swf['unhandled_in_timeline'].add(TAGNAMES.get(code, str(code)))
    if cur['place'] or cur['remove'] or cur['actions']: frames.append(cur)
    return frames

def parse(path):
    raw = open(path, 'rb').read()
    sig = raw[:3]
    body = zlib.decompress(raw[8:]) if sig == b'CWS' else raw[8:]
    r = R(body); stage = r.rect(); r.u8(); fps = r.u8(); nframes = r.u16()
    swf = {'version': raw[3], 'stage': [v / 20 for v in stage], 'fps': fps, 'frames_declared': nframes,
           'shapes': {}, 'sprites': {}, 'buttons': {}, 'texts': {}, 'edittexts': {}, 'fonts': {}, 'bitmaps': {},
           'unhandled_in_timeline': set(), 'bg': None}
    tags = read_tags(body, r.p)
    pool = []
    main_tags = []
    for code, b in tags:
        if code in (2, 22, 32, 83):
            ver = {2: 1, 22: 2, 32: 3, 83: 4}[code]
            rr = R(b); sid = rr.u16(); bounds = rr.rect()
            if ver == 4: rr.rect(); rr.u8()
            fills, lines = read_styles(rr, ver)
            groups = read_shape_records(rr, ver, fills, lines)
            swf['shapes'][sid] = {'bounds': [v / 20 for v in bounds], 'layers': shape_to_layers(groups)}
        elif code == 39:
            sid, fc = struct.unpack('<HH', b[:4])
            swf['sprites'][sid] = {'framecount': fc, 'frames': parse_timeline(read_tags(b, 4), swf, pool)}
        elif code == 34:
            rr = R(b); bid = rr.u16(); rr.u8(); aoff = rr.u16(); start = rr.p
            recs = []
            while True:
                rr.align(); f = rr.u8()
                if f == 0: break
                rec = {'states': [s for s, bit in (('hit', 8), ('down', 4), ('over', 2), ('up', 1)) if f & bit]}
                rec['id'] = rr.u16(); rec['depth'] = rr.u16(); rec['matrix'] = rr.matrix(); rec['cx'] = rr.cxform(True)
                if f & 16: raise ValueError('button filters')
                if f & 32: rr.u8()
                recs.append(rec)
            conds = []
            if aoff:
                p = start + aoff - 2
                while True:
                    size, cond = struct.unpack_from('<HH', b, p)
                    end = p + size if size else len(b)
                    lines, ops = disasm(b[p + 4:end], pool)
                    ev = [n for n, bit in (('release', 8), ('press', 4), ('rollOut', 2), ('rollOver', 1), ('releaseOutside', 64), ('dragOver', 16), ('dragOut', 32)) if cond & bit]
                    key = (cond >> 9) & 0x7F
                    if key: ev.append('key%d' % key)
                    conds.append({'events': ev, 'asm': [l for _, l in lines], 'src': summarize_actions(ops)})
                    if not size: break
                    p = end
            swf['buttons'][bid] = {'records': recs, 'actions': conds}
        elif code == 75 or code == 48:
            rr = R(b); fid = rr.u16(); fl = rr.u8(); rr.u8(); nl = rr.u8(); name = rr.bytes(nl).decode('latin-1').rstrip('\0')
            ng = rr.u16(); wide = fl & 8; wcodes = fl & 4
            base = rr.p
            offs = [rr.u32() if wide else rr.u16() for _ in range(ng)]
            cto = (rr.u32() if wide else rr.u16()) if ng else 0
            glyphs = []
            for i in range(ng):
                g0 = base + offs[i]; g1 = base + (offs[i + 1] if i + 1 < ng else cto)
                gr = R(b, g0)
                try:
                    grp = read_shape_records(gr, 1, [{'type': 0, 'color': '#000000', 'alpha': 1.0}], [])
                    for g in grp:
                        g['edges'] = [(e[0], e[1] if (e[0] or e[1]) else 1, e[2], e[3], e[4]) for e in g['edges']]
                    glyphs.append(shape_to_layers(grp))
                except Exception:
                    glyphs.append([])
            rr.p = base + cto
            codes = [rr.u16() if wcodes else rr.u8() for _ in range(ng)]
            swf['fonts'][fid] = {'name': name, 'bold': bool(fl & 1), 'italic': bool(fl & 2), 'codes': codes,
                                 'glyphs': glyphs, 'units': 1024 * 20 if code == 75 else 1024}
        elif code == 11 or code == 33:
            rr = R(b); tid = rr.u16(); bounds = rr.rect(); m = rr.matrix(); gb = rr.u8(); ab = rr.u8()
            recs = []; font = None; color = '#000000'; h = 12; xo = yo = 0
            while True:
                rr.align(); f = rr.u8()
                if f == 0: break
                if f & 8: font = rr.u16()
                if f & 4:
                    if code == 33: color, _ = rgba(rr)
                    else: color = rgb(rr)
                if f & 1: xo = rr.s16()
                if f & 2: yo = rr.s16()
                if f & 8: h = rr.u16()
                n = rr.u8(); gl = []
                for _ in range(n): gl.append((rr.ub(gb), rr.sb(ab)))
                rr.align()
                recs.append({'font': font, 'color': color, 'height': h / 20, 'x': xo / 20, 'y': yo / 20, 'glyphs': gl})
                xo += sum(a for _, a in gl)
            swf['texts'][tid] = {'bounds': [v / 20 for v in bounds], 'matrix': m, 'records': recs}
        elif code == 37:
            rr = R(b); tid = rr.u16(); bounds = rr.rect(); f1 = rr.u8(); f2 = rr.u8(); e = {'bounds': [v / 20 for v in bounds]}
            if f1 & 1: e['font'] = rr.u16()
            if f2 & 128: e['fontclass'] = rr.string()
            if f1 & 1: e['height'] = rr.u16() / 20
            if f1 & 4: e['color'], e['alpha'] = rgba(rr)
            if f1 & 2: rr.u16()
            if f2 & 32: e['align'] = rr.u8(); rr.u16(); rr.u16(); rr.u16(); rr.s16()
            e['var'] = rr.string()
            if f1 & 128: e['text'] = rr.string()
            e['html'] = bool(f2 & 2)
            swf['edittexts'][tid] = e
        elif code == 21:
            bid = struct.unpack('<H', b[:2])[0]; jpg = b[2:]
            if jpg[:4] == b'\xff\xd9\xff\xd8': jpg = jpg[4:]
            swf['bitmaps'][bid] = jpg
        elif code == 9:
            swf['bg'] = '#%02x%02x%02x' % tuple(b[:3])
        else:
            main_tags.append((code, b))
    swf['main'] = {'framecount': nframes, 'frames': parse_timeline(main_tags, swf, pool)}
    return swf

def text_string(swf, tid):
    t = swf['texts'][tid]; s = []
    for rec in t['records']:
        f = swf['fonts'].get(rec['font'])
        if f: s.append(''.join(chr(f['codes'][g]) if g < len(f['codes']) else '?' for g, _ in rec['glyphs']))
    return ' / '.join(s)

if __name__ == '__main__':
    swf = parse(sys.argv[1])
    print(json.dumps({k: (len(v) if isinstance(v, dict) else v) for k, v in swf.items() if k not in ('main', 'unhandled_in_timeline')}, default=str))
    print('unhandled:', swf['unhandled_in_timeline'])
