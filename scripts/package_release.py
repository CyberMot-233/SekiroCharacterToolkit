"""Build a portable release without extracted game assets or development outputs."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import zipfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.out or root.parent / 'SekiroCharacterToolkit-0.10.1-full-win-x64.zip').resolve()
    if output.exists():
        raise FileExistsError('Choose a new ZIP path; existing releases are not overwritten: ' + str(output))
    files = []
    root_names = {'README.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE', 'build.ps1'}
    root_suffixes = {'.dll', '.exe', '.json', '.pdb'}
    folders = {'runtime', 'scripts', 'src', 'docs', 'licenses'}
    excluded = {'bin', 'obj', '__pycache__', '.git', '.vs', '.idea'}
    for file in root.rglob('*'):
        if not file.is_file():
            continue
        relative = file.relative_to(root)
        if file.name in {'release_manifest.json', '_adapt_sources.py', 'settings.json'} or {'__pycache__', '.git', '.vs', '.idea'}.intersection(relative.parts):
            continue
        if relative.parts[0] == 'src' and {'bin', 'obj'}.intersection(relative.parts):
            continue
        if len(relative.parts) == 1:
            include = file.name in root_names or file.suffix.lower() in root_suffixes
        else:
            include = relative.parts[0] in folders and file.suffix.lower() not in {'.pyc', '.dds', '.fsb', '.fev', '.hkx', '.dcx'}
            # Blender ships required startup.blend, preview resources and python/bin.
            if file.suffix.lower() == '.blend' and relative.parts[:2] != ('runtime', 'blender'):
                include = False
        if include:
            if not file.resolve().is_relative_to(root):
                raise ValueError('Release input resolves outside project: ' + str(file))
            files.append(file)
    files.sort(key=lambda x: x.relative_to(root).as_posix())
    records = [{'file': f.relative_to(root).as_posix(), 'bytes': f.stat().st_size, 'sha256': sha(f)} for f in files]
    manifest = {'version': '0.10.1', 'platform': 'win-x64',
                'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'files_count': len(records), 'uncompressed_bytes': sum(x['bytes'] for x in records),
                'excluded': ['tests', 'exports', 'cache', 'logs', 'bin', 'obj', '__pycache__', '_adapt_sources.py'],
                'external_tools': ['CS2 Workshop Tools resourcecompiler.exe and resourceinfo.exe, required only for CS2 compilation/verification; detected from selected addon installation'],
                'bundled_tools': ['Blender 4.5.5', 'Python 3.11.11 + Pillow 12.2.0 + NumPy', 'DSAS RC6.1 FMOD DLLs and SDT shaders', 'ffmpeg + ffprobe', '.NET self-contained'],
                'user_input_required': ['Own unpacked Sekiro game directory'],
                'files': records}
    manifest_path = root / 'release_manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files + [manifest_path]:
            archive.write(file, root.name + '/' + file.relative_to(root).as_posix())
    with zipfile.ZipFile(output) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError('ZIP CRC failed: ' + corrupt)
        for record in records:
            data = archive.read(root.name + '/' + record['file'])
            if hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('ZIP hash mismatch: ' + record['file'])
    checksum = sha(output)
    output.with_suffix(output.suffix + '.sha256').write_text(checksum + '  ' + output.name + '\n', encoding='ascii')
    print(json.dumps({'zip': str(output), 'bytes': output.stat().st_size, 'sha256': checksum, 'files': len(records) + 1, 'crc_and_sha256_verified': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
