"""Verify the compiled addon dependency closure without extracting game VPK data."""
import argparse, re, struct, subprocess
from pathlib import Path
from cs2_common import cs_root, read, save


def vpk_index(path):
    with Path(path).open('rb') as stream:
        sig, version, size = struct.unpack('<III', stream.read(12))
        if sig != 0x55AA1234 or version not in (1, 2):
            raise ValueError('Unsupported VPK header: ' + str(path))
        if version == 2:
            stream.read(16)
        tree = stream.read(size)
    at = 0
    result = set()
    def string():
        nonlocal at
        end = tree.index(b'\0', at)
        value = tree[at:end].decode('utf-8')
        at = end + 1
        return value
    while True:
        ext = string()
        if not ext: break
        while True:
            folder = string()
            if not folder: break
            while True:
                name = string()
                if not name: break
                crc, preload, archive, offset, length, end = struct.unpack_from('<IHHIIH', tree, at)
                if end != 0xFFFF: raise ValueError('Invalid VPK directory entry')
                at += 18 + preload
                result.add(((folder + '/' if folder != ' ' else '') + name + ('.' + ext if ext != ' ' else '')).lower())
    return result


def verify(addon, name):
    addon = Path(addon).resolve(); root = cs_root(addon)
    game = root / 'game/csgo_addons' / addon.name
    reports = addon / f'rawmodels/sekiro/characters/{name}/reports'
    exe = root / 'game/bin/win64/resourceinfo.exe'
    roots = [f'models/sekiro/characters/{name}/{name}.vmdl_c']
    audio_path = reports / 'audio_conversion.json'
    if audio_path.exists():
        audio = read(audio_path)
        roots.extend(str(Path(x).relative_to(addon).with_suffix('.vsnd_c')).replace('\\', '/') for x in audio['converted'])
        roots.append(str(Path(audio['registration']).relative_to(addon)).replace('\\', '/') + '_c')
    seen = set(); external = {}; local = []; issues = []; edges = {}; archives = None
    pending = list(roots)
    while pending:
        relative = pending.pop().replace('\\', '/')
        if relative.lower() in seen: continue
        seen.add(relative.lower())
        path = (game / relative).resolve()
        if not path.is_relative_to(game.resolve()):
            issues.append('Invalid dependency path ' + relative); continue
        if not path.exists():
            # Only official base-game packages are external dependencies; a missing
            # toolkit-created asset must not silently resolve from another addon.
            if '/sekiro/' in relative:
                issues.append('Missing addon resource ' + relative); continue
            loose = next((root / 'game' / folder / relative for folder in ('csgo', 'core') if (root / 'game' / folder / relative).is_file()), None)
            if loose:
                external[relative] = str(loose); continue
            if archives is None:
                archives = {str(p): vpk_index(p) for folder in ('csgo', 'core') for p in (root / 'game' / folder).glob('*_dir.vpk')}
            container = next((p for p, entries in archives.items() if relative.lower() in entries), None)
            if container: external[relative] = container
            else: issues.append('Missing base resource ' + relative)
            continue
        local.append(relative)
        if path.suffix in ('.vtex_c', '.vsnd_c'): continue
        run = subprocess.run([str(exe), '-i', str(path), '-b', 'RERL', '-baremode'], capture_output=True, encoding='utf-8', errors='replace')
        if run.returncode:
            issues.append({'resource': relative, 'error': run.stdout + run.stderr}); continue
        refs = re.findall(r'->\s*"([^"]+)"', run.stdout)
        edges[relative] = refs
        pending.extend(r if r.endswith('_c') else r + '_c' for r in refs)
    result = dict(passed=not issues, local=sorted(local), external=external, issues=issues, edges=edges,
                  scope='Recursive custom compiled RERL, local WAV/VSND and registration roots; base resources checked against official loose files/VPK directory entries. No game runtime validation.')
    save(reports / 'dependencies.json', result)
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--addon', required=True, type=Path); ap.add_argument('--name', default='wolf'); args = ap.parse_args()
    result = verify(args.addon, args.name)
    print('CS2_DEPENDENCIES', result['passed'], len(result['local']), len(result['external']), result['issues'])
    raise SystemExit(0 if result['passed'] else 1)
