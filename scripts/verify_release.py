"""Verify packaged program/source files; generated exports and logs are ignored."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / 'release_manifest.json').read_text(encoding='utf-8'))
    errors = []
    for record in manifest['files']:
        file = (root / record['file']).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            errors.append({'file': record['file'], 'reason': 'missing or outside root'})
            continue
        with file.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != record['sha256'] or file.stat().st_size != record['bytes']:
            errors.append({'file': record['file'], 'reason': 'content mismatch'})
    print(json.dumps({'passed': not errors, 'checked_files': len(manifest['files']), 'errors': errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
