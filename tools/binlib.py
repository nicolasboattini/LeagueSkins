"""PROP bin parse/serialize. Values:
 ('p', t, raw_bytes)          primitive (raw bytes kept)
 ('s', str)                   string (16)
 ('l', t, et, [vals])         list 0x80/0x81
 ('o', t, cls, [[fh, ft, v]]) pointer 0x82 / embed 0x83 (cls 0 => null)
 ('opt', et, [v] or [])       option 0x85
 ('m', kt, vt, [(k, v)])      map 0x86
Entries that fail to parse are kept raw: ('raw', bytes)
"""
import struct, os

def fnv(s):
    h = 0x811c9dc5
    for c in s.lower().encode():
        h = ((h ^ c) * 0x01000193) & 0xffffffff
    return h

SZ = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 4, 7: 4, 8: 8, 9: 8, 10: 4, 11: 8, 12: 12, 13: 16, 14: 64, 15: 4, 17: 4, 18: 8, 0x84: 4, 0x87: 1}

H = {}
def load_names(d=os.path.join(os.path.dirname(__file__), '..', 'h')):
    for f in ('binfields', 'bintypes', 'binhashes', 'binentries'):
        p = os.path.join(d, f'hashes.{f}.txt')
        if not os.path.exists(p): continue
        for l in open(p, encoding='utf8', errors='ignore'):
            k, _, v = l.rstrip('\n').partition(' ')
            if len(k) == 8: H[int(k, 16)] = v
def nm(h): return H.get(h, f'{h:08x}')

class _R:
    def __init__(s, d, p=0): s.d = d; s.p = p
    def u(s, f):
        v = struct.unpack_from('<' + f, s.d, s.p); s.p += struct.calcsize('<' + f)
        return v if len(v) > 1 else v[0]
    def raw(s, n): b = s.d[s.p:s.p + n]; s.p += n; return b

def _val(r, t):
    if t in SZ: return ('p', t, r.raw(SZ[t]))
    if t == 16: l = r.u('H'); return ('s', r.raw(l).decode('utf8'))
    if t in (0x80, 0x81):
        et = r.u('B'); sz = r.u('I'); st = r.p; n = r.u('I')
        v = ('l', t, et, [_val(r, et) for _ in range(n)])
        assert r.p == st + sz, 'list size'
        return v
    if t in (0x82, 0x83):
        c = r.u('I')
        if c == 0: return ('o', t, 0, [])
        sz = r.u('I'); st = r.p; n = r.u('H'); fs = []
        for _ in range(n):
            fh = r.u('I'); ft = r.u('B'); fs.append([fh, ft, _val(r, ft)])
        assert r.p == st + sz, 'struct size'
        return ('o', t, c, fs)
    if t == 0x85:
        et = r.u('B'); n = r.u('B'); return ('opt', et, [_val(r, et) for _ in range(n)])
    if t == 0x86:
        kt = r.u('B'); vt = r.u('B'); sz = r.u('I'); st = r.p; n = r.u('I')
        v = ('m', kt, vt, [(_val(r, kt), _val(r, vt)) for _ in range(n)])
        assert r.p == st + sz, 'map size'
        return v
    raise ValueError(f'type {t}')

def _w(v):
    k = v[0]
    if k == 'p': return v[2]
    if k == 's': e = v[1].encode('utf8'); return struct.pack('<H', len(e)) + e
    if k == 'l':
        body = struct.pack('<I', len(v[3])) + b''.join(_w(x) for x in v[3])
        return struct.pack('<BI', v[2], len(body)) + body
    if k == 'o':
        if v[2] == 0: return struct.pack('<I', 0)
        body = struct.pack('<H', len(v[3])) + b''.join(struct.pack('<IB', fh, ft) + _w(fv) for fh, ft, fv in v[3])
        return struct.pack('<II', v[2], len(body)) + body
    if k == 'opt': return struct.pack('<BB', v[1], len(v[2])) + b''.join(_w(x) for x in v[2])
    if k == 'm':
        body = struct.pack('<I', len(v[3])) + b''.join(_w(a) + _w(b) for a, b in v[3])
        return struct.pack('<BBI', v[1], v[2], len(body)) + body
    raise ValueError(k)

class Bin:
    def __init__(s, d):
        s.pre = b''
        if d[:4] == b'PTCH': s.pre, d = d[:16], d[16:]
        assert d[:4] == b'PROP', d[:4]
        r = _R(d, 4); s.ver = r.u('I'); s.links = []
        if s.ver >= 2:
            for _ in range(r.u('I')): l = r.u('H'); s.links.append(r.raw(l).decode())
        n = r.u('I'); types = [r.u('I') for _ in range(n)]
        s.entries = []  # [type, key, fields] or [type, key, ('raw', bytes)]
        for t in types:
            l = r.u('I'); st = r.p; key = r.u('I')
            try:
                c = r.u('H'); fs = []
                for _ in range(c):
                    fh = r.u('I'); ft = r.u('B'); fs.append([fh, ft, _val(r, ft)])
                assert r.p == st + l
                s.entries.append([t, key, fs])
            except Exception:
                s.entries.append([t, key, ('raw', d[st + 4:st + l])])
            r.p = st + l
        s.tail = d[r.p:]
    def dumps(s):
        o = b'PROP' + struct.pack('<I', s.ver)
        if s.ver >= 2:
            o += struct.pack('<I', len(s.links))
            for l in s.links: e = l.encode(); o += struct.pack('<H', len(e)) + e
        o += struct.pack('<I', len(s.entries)) + b''.join(struct.pack('<I', e[0]) for e in s.entries)
        for t, key, fs in s.entries:
            if isinstance(fs, tuple): body = struct.pack('<I', key) + fs[1]
            else: body = struct.pack('<IH', key, len(fs)) + b''.join(struct.pack('<IB', fh, ft) + _w(fv) for fh, ft, fv in fs)
            o += struct.pack('<I', len(body)) + body
        return s.pre + o + s.tail
    def entry(s, key):
        if isinstance(key, str): key = fnv(key)
        for e in s.entries:
            if e[1] == key: return e
    def raw_count(s): return sum(isinstance(e[2], tuple) for e in s.entries)

def get(fs, name):
    h = fnv(name) if isinstance(name, str) else name
    for f in fs:
        if f[0] == h: return f
def P(t, fmt, *v): return ('p', t, struct.pack('<' + fmt, *v))
def u32(v): return struct.unpack('<I', v[2])[0]

def fmt(v, ind=0):
    sp = '  ' * ind; k = v[0]
    if k == 'p':
        t, b = v[1], v[2]
        if t in (17, 0x84): return nm(struct.unpack('<I', b)[0])
        if t == 10: return f'{struct.unpack("<f", b)[0]:g}'
        if t in (1, 3, 0x87): return str(b[0])
        if t == 6: return str(struct.unpack('<i', b)[0])
        if t == 7: return str(struct.unpack('<I', b)[0])
        return b.hex()
    if k == 's': return repr(v[1])
    if k == 'l': return '[' + ''.join('\n' + sp + '  ' + fmt(x, ind + 1) for x in v[3]) + ']'
    if k == 'o':
        if v[2] == 0: return 'null'
        tag = '' if v[1] == 0x82 else '(embed)'
        return nm(v[2]) + tag + ' {' + ''.join('\n' + sp + '  ' + f'{nm(fh)} = ' + fmt(fv, ind + 1) for fh, ft, fv in v[3]) + '}'
    if k == 'opt': return 'opt(' + ', '.join(fmt(x, ind) for x in v[2]) + ')'
    if k == 'm': return '{' + ''.join('\n' + sp + '  ' + fmt(a, ind + 1) + ': ' + fmt(b, ind + 1) for a, b in v[3]) + '}'
def dump(b):
    out = [f'link {l}' for l in b.links]
    for t, key, fs in b.entries:
        if isinstance(fs, tuple): out.append(f'ENTRY {nm(key)} : {nm(t)} <raw {len(fs[1])}b>'); continue
        out.append(f'ENTRY {nm(key)} : {nm(t)}' + ''.join(f'\n  {nm(fh)} = ' + fmt(fv, 1) for fh, ft, fv in fs))
    return '\n'.join(out)
