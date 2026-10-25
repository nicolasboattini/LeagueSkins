#!/usr/bin/env python3
"""Retargeteador de skins - app web local.
Uso: python server.py [--port 8765] [--repo RUTA_AL_REPO] [--no-browser]
"""
import argparse, json, os, re, subprocess, sys, threading, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # tools/
from retarget import retarget_bytes, skin_slots  # noqa: E402

SOURCE_DIRS = [('skins', 'Repo'), ('rainbow', 'Rainbow'), ('PBE', 'PBE'), ('retargets', 'Mis retargets')]
OUT_DIR = 'retargets'
BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

def safe_name(s): return BAD.sub('', s).strip().rstrip('.')

def find_git():
    import shutil, glob
    g = shutil.which('git')
    if g: return g
    if os.name == 'nt':
        la = os.environ.get('LOCALAPPDATA', '')
        cands = sorted(glob.glob(os.path.join(la, 'GitHubDesktop', 'app-*', 'resources', 'app', 'git', 'cmd', 'git.exe')))
        cands += [r'C:\Program Files\Git\cmd\git.exe']
        for c in reversed(cands):
            if os.path.isfile(c): return c
    return None

class App:
    def __init__(self, repo):
        self.repo = os.path.abspath(repo)
        self._index = None
        self.gitexe = find_git()

    def index(self):
        if self._index is None:
            with open(os.path.join(self.repo, 'index.json'), encoding='utf8') as f:
                self._index = json.load(f)
        return self._index

    def git(self, *args, timeout=120):
        if not self.gitexe: return 1, 'git no encontrado'
        cmd = [self.gitexe, '-c', 'core.checkStat=minimal', '-c', 'core.trustctime=false',
               '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', *args]
        kw = {'creationflags': 0x08000000} if os.name == 'nt' else {}
        r = subprocess.run(cmd, cwd=self.repo, capture_output=True, text=True, timeout=timeout, encoding='utf8', errors='replace', **kw)
        return r.returncode, (r.stdout + r.stderr).strip()

    def state(self):
        rc, br = self.git('branch', '--show-current')
        rc2, brs = self.git('branch', '--format=%(refname:short)')
        return {'repo': self.repo, 'patch': self.index().get('patch'),
                'branch': br if rc == 0 else None,
                'branches': brs.splitlines() if rc2 == 0 else [],
                'champions': sorted(self.index()['champions'].keys(), key=str.lower)}

    def champ(self, name):
        champs = self.index()['champions']
        if name not in champs: raise ValueError('campeón desconocido')
        data = champs[name]
        skins = {int(k): v for k, v in data.get('skins', {}).items()}
        skins.setdefault(0, f'{name} (base / default)')
        targets = []
        for slot in sorted(skins):
            targets.append({'slot': slot, 'label': skins[slot], 'kind': 'skin', 'parent': None})
            for cs, cn in sorted(((int(a), b) for a, b in data.get('chromas', {}).get(str(slot), {}).items())):
                full = cn if skins[slot].split()[0] in cn or name.lower() in cn.lower() else f'{skins[slot]} {cn}'
                targets.append({'slot': cs, 'label': full, 'kind': 'chroma', 'parent': slot})
        sources = []
        for d, group in SOURCE_DIRS:
            root = os.path.join(self.repo, d, name)
            if not os.path.isdir(root): continue
            for dp, dn, fn in os.walk(root):
                dn.sort()
                for f in sorted(fn):
                    if not f.lower().endswith('.fantome'): continue
                    full = os.path.join(dp, f)
                    rel = os.path.relpath(full, self.repo).replace('\\', '/')
                    label = os.path.relpath(full, root).replace('\\', '/')[:-len('.fantome')]
                    sources.append({'path': rel, 'label': label, 'group': group})
        return {'champion': name, 'targets': targets, 'sources': sources}

    def resolve_source(self, rel):
        full = os.path.abspath(os.path.join(self.repo, rel))
        if not full.startswith(self.repo + os.sep) or not full.lower().endswith('.fantome') or not os.path.isfile(full):
            raise ValueError('archivo de origen inválido')
        return full

    def target_label(self, champ, slot):
        for t in self.champ(champ)['targets']:
            if t['slot'] == slot: return t['label']
        return f'slot {slot}'

    def retarget(self, req):
        champ = req['champion']; slot = int(req['slot'])
        src = self.resolve_source(req['source'])
        data = open(src, 'rb').read()
        out, info = retarget_bytes(data, champ, slot)
        src_label = os.path.splitext(os.path.basename(src))[0]
        parent = os.path.basename(os.path.dirname(src))
        if parent != champ and os.path.dirname(os.path.dirname(src)).endswith(champ):
            src_label = f'{parent} {src_label}'  # chroma: "Mecha Kingdoms Jax Ruby"
        tlabel = self.target_label(champ, slot)
        fname = req.get('filename') or f'{src_label} en {tlabel} ({slot})'
        fname = safe_name(fname) + '.fantome'
        outdir = os.path.join(self.repo, OUT_DIR, champ)
        os.makedirs(outdir, exist_ok=True)
        outpath = os.path.join(outdir, fname)
        with open(outpath, 'wb') as f: f.write(out)
        rel = os.path.relpath(outpath, self.repo).replace('\\', '/')
        res = {'ok': True, 'output': rel, 'from': info['from'], 'to': info['to'], 'log': info['log']}
        if req.get('commit'):
            rc, o = self.git('add', '--', rel)
            if rc == 0:
                rc, o = self.git('commit', '-q', '--no-verify', '-m', f'{champ}: {src_label} -> {tlabel} ({slot})', '--', rel)
            res['commit'] = {'ok': rc == 0, 'output': o}
        return res

    def inspect(self, rel, champ):
        return {'slots': skin_slots(open(self.resolve_source(rel), 'rb').read(), champ)}

    def switch(self, branch):
        rc, o = self.git('switch', branch, timeout=600)
        return {'ok': rc == 0, 'output': o, **self.state()}

    def open_folder(self, rel):
        path = os.path.join(self.repo, rel) if rel else os.path.join(self.repo, OUT_DIR)
        path = os.path.abspath(path)
        if not path.startswith(self.repo): raise ValueError('ruta inválida')
        if os.path.isfile(path):
            if os.name == 'nt': subprocess.Popen(['explorer', '/select,', path])
            return {'ok': True}
        os.makedirs(path, exist_ok=True)
        if os.name == 'nt': os.startfile(path)
        return {'ok': True}

PAGE = open(os.path.join(HERE, 'index.html'), 'rb').read()  # cached: survives branch switches

def make_handler(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def send(self, code, body, ctype='application/json; charset=utf-8'):
            if not isinstance(body, bytes): body = json.dumps(body, ensure_ascii=False).encode('utf8')
            self.send_response(code); self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store')
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ('/', '/index.html'):
                    return self.send(200, PAGE, 'text/html; charset=utf-8')
                if u.path == '/api/state': return self.send(200, app.state())
                if u.path == '/api/champ': return self.send(200, app.champ(q['name']))
                if u.path == '/api/inspect': return self.send(200, app.inspect(q['path'], q['champion']))
                self.send(404, {'error': 'not found'})
            except Exception as e:
                self.send(400, {'error': str(e)})
        def do_POST(self):
            if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
                return self.send(403, {'error': 'origin'})
            n = int(self.headers.get('Content-Length') or 0)
            try:
                req = json.loads(self.rfile.read(n) or b'{}')
                if self.path == '/api/retarget': return self.send(200, app.retarget(req))
                if self.path == '/api/switch': return self.send(200, app.switch(req['branch']))
                if self.path == '/api/open': return self.send(200, app.open_folder(req.get('path')))
                self.send(404, {'error': 'not found'})
            except Exception as e:
                self.send(400, {'error': str(e)})
    return H

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--repo', default=os.path.dirname(os.path.dirname(HERE)))
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    app = App(a.repo)
    app.index()
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), make_handler(app))
    url = f'http://127.0.0.1:{a.port}/'
    print(f'Retargeteador en {url}  (repo: {app.repo})  - Ctrl+C para cerrar')
    if not a.no_browser: threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

if __name__ == '__main__': main()
