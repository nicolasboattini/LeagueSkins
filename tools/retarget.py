#!/usr/bin/env python3
"""Retarget a .fantome skin mod to another skin slot.
Usage: python tools/retarget.py IN.fantome CHAMP TO_SLOT OUT.fantome [--from N] [--name "Display name"]
Requires: pip install xxhash zstandard
"""
import sys, io, json, struct, zipfile, argparse, gzip
import xxhash, zstandard

def fnv(s):
    h = 0x811c9dc5
    for c in s.lower().encode():
        h = ((h ^ c) * 0x01000193) & 0xffffffff
    return h

def xx(p): return xxhash.xxh64(p.lower().encode()).intdigest()

def read_wad(b):
    assert b[:2] == b'RW', 'not a WAD'
    major = b[2]
    assert major == 3, f'WAD v{major} not supported'
    hdr = b[:268]
    n = struct.unpack_from('<I', b, 268)[0]
    ents = []
    for i in range(n):
        h, off, cs, us, t, dup, sub, ck = struct.unpack_from('<QIIIBBHQ', b, 272 + 32 * i)
        typ = t & 0xf
        raw = b[off:off + cs]
        if typ == 0: data = raw
        elif typ == 1: data = gzip.decompress(raw)
        elif typ in (3, 4): data = zstandard.ZstdDecompressor().decompress(raw, max_output_size=us)
        else: raise ValueError(f'entry type {typ} unsupported')
        ents.append([h, data])
    return hdr, ents

def write_wad(hdr, ents):
    ents = sorted(ents, key=lambda e: e[0])
    n = len(ents)
    toc = io.BytesIO(); body = io.BytesIO()
    base = 272 + 32 * n
    cctx = zstandard.ZstdCompressor(level=3)
    for h, data in ents:
        c = cctx.compress(data)
        toc.write(struct.pack('<QIIIBBHQ', h, base + body.tell(), len(c), len(data), 3, 0, 0, xxhash.xxh3_64(c).intdigest()))
        body.write(c)
    return hdr + struct.pack('<I', n) + toc.getvalue() + body.getvalue()

def fix_links(d, champ, a, b):
    """Rewrite PROP link strings that reference skin{a}."""
    pre = b''
    if d[:4] == b'PTCH':
        pre, d = d[:12], d[12:]
    if d[:4] != b'PROP': return pre + d
    ver = struct.unpack_from('<I', d, 4)[0]
    if ver < 2: return pre + d
    p = 8
    cnt = struct.unpack_from('<I', d, p)[0]; p += 4
    links = []
    for _ in range(cnt):
        l = struct.unpack_from('<H', d, p)[0]; p += 2
        links.append(d[p:p + l].decode()); p += l
    c = champ.lower(); new = []
    for s in links:
        for kind in ('skins', 'animations'):
            old = f'data/characters/{c}/{kind}/skin{a}.bin'
            if s.lower() == old: s = f'data/characters/{c}/{kind}/skin{b}.bin'
        new.append(s)
    out = d[:8] + struct.pack('<I', len(new))
    for s in new:
        e = s.encode(); out += struct.pack('<H', len(e)) + e
    return pre + out + d[p:]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp'); ap.add_argument('champ'); ap.add_argument('to', type=int); ap.add_argument('out')
    ap.add_argument('--from', dest='frm', type=int); ap.add_argument('--name')
    a = ap.parse_args()
    C = a.champ; c = C.lower()
    zin = zipfile.ZipFile(a.inp)
    wadname = next(n for n in zin.namelist() if n.lower().startswith('wad/'))
    hdr, ents = read_wad(zin.read(wadname))
    hashes = {e[0] for e in ents}
    found = [n for n in range(200) if xx(f'data/characters/{c}/skins/skin{n}.bin') in hashes]
    if a.frm is None:
        assert len(found) == 1, f'skin bins found: {found}; use --from'
        a.frm = found[0]
    f, t = a.frm, a.to
    rep = {}
    for tpl in ('Characters/{C}/Skins/Skin{n}', 'Characters/{C}/Skins/Skin{n}/Resources', 'Characters/{C}/Animations/Skin{n}'):
        rep[struct.pack('<I', fnv(tpl.format(C=C, n=f)))] = struct.pack('<I', fnv(tpl.format(C=C, n=t)))
    ren = {xx(f'data/characters/{c}/{k}/skin{f}.bin'): xx(f'data/characters/{c}/{k}/skin{t}.bin') for k in ('skins', 'animations')}
    assert not (set(ren.values()) & hashes - set(ren)), 'target slot already present in mod'
    log = []
    for e in ents:
        d = e[1]
        if d[:4] in (b'PROP', b'PTCH'):
            nd = fix_links(d, C, f, t)
            for k, v in rep.items(): nd = nd.replace(k, v)
            if nd != d: log.append(f'{e[0]:016x} patched'); e[1] = nd
        if e[0] in ren: log.append(f'{e[0]:016x} renamed'); e[0] = ren[e[0]]
    wad = write_wad(hdr, ents)
    with zipfile.ZipFile(a.out, 'w', zipfile.ZIP_DEFLATED) as zo:
        for n in zin.namelist():
            if n == wadname: zo.writestr(n, wad, compress_type=zipfile.ZIP_STORED); continue
            data = zin.read(n)
            if n == 'META/info.json':
                info = json.loads(data)
                if a.name: info['Name'] = a.name
                info['Description'] = (info.get('Description', '') + f' Retargeted skin{f} -> skin{t}.').strip()
                data = json.dumps(info, indent=2).encode()
            zo.writestr(n, data)
    print(f'{C}: skin{f} -> skin{t}', *log, sep='\n  ')

if __name__ == '__main__': main()
