"""Pack the complete redistributable runtime behind the native Win32 launcher."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import zipfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--app-dir', type=Path, help='Use a freshly published GUI without replacing a running installed application')
    args = p.parse_args()
    root = args.root.resolve()
    out = args.out.resolve()
    if out.exists():
        raise FileExistsError(out)
    # No root settings, game assets, exports, screenshots, caches, or developer evidence.
    files = []
    for folder in ('runtime', 'scripts', 'docs', 'licenses'):
        for f in (root / folder).rglob('*'):
            if not f.is_file() or {'__pycache__', '.git', '.vs'}.intersection(f.parts):
                continue
            if f.suffix.lower() in ('.pyc', '.pdb', '.dcx', '.hkx', '.fsb', '.fev') or f.name == '_adapt_sources.py':
                continue
            files.append(f)
    for f in root.iterdir():
        if f.is_file() and (f.suffix.lower() in ('.dll', '.exe') or f.name in (
            'SekiroCharacterToolkit.deps.json', 'SekiroCharacterToolkit.runtimeconfig.json',
            'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md')):
            files.append(f)
    files.sort(key=lambda f: f.relative_to(root).as_posix())
    records = []
    inputs=[]
    app=args.app_dir.resolve() if args.app_dir else None
    if app and not (app/'SekiroCharacterToolkit.dll').is_file():raise ValueError('Published app DLL missing')
    for original in files:
        relative=original.relative_to(root)
        f=app/relative if app and len(relative.parts)==1 and (app/relative).is_file() else original
        if not f.resolve().is_relative_to(root) and not (app and f.resolve().is_relative_to(app)):
            raise ValueError('Input resolves outside project: ' + str(f))
        inputs.append(f)
        records.append({'path': relative.as_posix(), 'size': f.stat().st_size, 'sha256': sha(f)})
    manifest = ''.join(f"{r['sha256']}\t{r['size']}\t{r['path']}\n" for r in records).encode('utf-8')
    cache = root / 'cache/single_exe'
    cache.mkdir(parents=True, exist_ok=True)
    payload = cache / 'payload.zip'
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f, r in zip(inputs, records):
            z.write(f, r['path'])
        z.writestr('payload.sha256', manifest)
    with zipfile.ZipFile(payload) as z:
        for r in records:
            with z.open(r['path']) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != r['sha256']:
                    raise ValueError('Payload verification failed: ' + r['path'])
    out.parent.mkdir(parents=True, exist_ok=True)
    launcher = root / 'src/Launcher/launcher.exe'
    payload_hash = sha(payload)
    with out.open('xb') as target, launcher.open('rb') as bootstrap, payload.open('rb') as stream:
        shutil.copyfileobj(bootstrap, target)
        offset = target.tell()
        shutil.copyfileobj(stream, target)
        target.write(struct.pack('<8sQQ64s', b'SCTPKG02', offset, payload.stat().st_size, payload_hash.encode('ascii')))
    report = {'version': '0.10.10', 'exe': str(out), 'bytes': out.stat().st_size,
              'sha256': sha(out), 'payload_sha256': payload_hash, 'payload_files': len(records),
              'uncompressed_bytes': sum(r['size'] for r in records), 'payload_readback_sha256_verified': True}
    evidence = root / 'tests/single_exe_110'
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'package.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (evidence / 'payload_files.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
