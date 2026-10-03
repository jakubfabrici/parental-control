#!/usr/bin/env python3
"""Publikuje verziu PC agenta na OMV.

Pouzitie (na OMV ako root):
    pc-agent-publish.py <verzia> <adresar so subormi windows-remote-control>

Co robi:
  1. skopiruje subory do /var/www/pc-agent/releases/<verzia>/  (bez config.json,
     logov, zaloh a stavu - tie su lokalne na PC),
  2. vytvori manifest.json (verzia, base, sha256 + velkost kazdeho suboru),
  3. podpise ho HMAC-SHA256 klucom /root/.pc-agent-update.key -> manifest.sig,
  4. atomicky prepne /var/www/pc-agent/current/ (rename adresara).

Klient (Update-PcAgent.ps1) stahuje current/manifest.json + manifest.sig a
subory z base=releases/<verzia>/, takze prepnutie current je jedina "zmena"
a klient, ktory prave stahuje starsiu verziu, dostane konzistentne subory.
"""
import hashlib, hmac, json, os, shutil, sys, time

ROOT = '/var/www/pc-agent'
KEY_FILE = '/root/.pc-agent-update.key'
EXCLUDE_NAMES = {'config.json', 'agent.log', 'state.json'}
EXCLUDE_SUFFIX = ('.bak', '.b64', '.tmp', '.log')
EXCLUDE_PREFIX = ('PcAgent.ps1.bak-',)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def wanted(name):
    if name in EXCLUDE_NAMES: return False
    if name.startswith(EXCLUDE_PREFIX): return False
    if name.endswith(EXCLUDE_SUFFIX): return False
    return True


def main():
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(2)
    version, src = sys.argv[1], os.path.abspath(sys.argv[2])
    if not os.path.isdir(src): sys.exit(f'chyba adresar {src}')
    if not os.path.exists(KEY_FILE):
        sys.exit(f'chyba {KEY_FILE} - vytvor ho: openssl rand -hex 32 > {KEY_FILE}; chmod 600 {KEY_FILE}')
    key = open(KEY_FILE).read().strip().encode()

    rel_dir = os.path.join(ROOT, 'releases', version)
    if os.path.exists(rel_dir): shutil.rmtree(rel_dir)
    files = []
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in ('.git', 'telegram-bot')]
        for fn in sorted(filenames):
            if not wanted(fn): continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, src).replace(os.sep, '/')
            dst = os.path.join(rel_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(full, dst)
            files.append({'path': rel, 'sha256': sha256(dst), 'size': os.path.getsize(dst)})
    if not any(f['path'] == 'ha-agent/PcAgent.ps1' for f in files):
        sys.exit('v zdroji chyba ha-agent/PcAgent.ps1 - zly adresar?')

    manifest = {
        'version': version,
        'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'base': f'releases/{version}/',
        'files': files,
    }
    man_bytes = json.dumps(manifest, ensure_ascii=True, indent=1).encode('ascii')  # cisto ASCII: HMAC na klientovi nezavisi od charsetu
    sig = hmac.new(key, man_bytes, hashlib.sha256).hexdigest()

    new_cur = os.path.join(ROOT, 'current.new')
    old_cur = os.path.join(ROOT, 'current.old')
    cur = os.path.join(ROOT, 'current')
    for d in (new_cur, old_cur):
        if os.path.exists(d): shutil.rmtree(d)
    os.makedirs(new_cur)
    with open(os.path.join(new_cur, 'manifest.json'), 'wb') as f: f.write(man_bytes)
    with open(os.path.join(new_cur, 'manifest.sig'), 'w') as f: f.write(sig + '\n')
    for d in (new_cur, rel_dir):
        for dirpath, _, filenames in os.walk(d):
            os.chmod(dirpath, 0o755)
            for fn in filenames: os.chmod(os.path.join(dirpath, fn), 0o644)
    if os.path.exists(cur): os.rename(cur, old_cur)
    os.rename(new_cur, cur)
    if os.path.exists(old_cur): shutil.rmtree(old_cur)
    print(f'publikovane {version}: {len(files)} suborov, sig {sig[:12]}...')
    print(f'  http://192.168.1.185/pc-agent/current/manifest.json')


if __name__ == '__main__':
    main()
