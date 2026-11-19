"""Check actual PNG channel layout and decode/probe exported native MP3 events."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from PIL import Image


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package', required=True, type=Path)
    ap.add_argument('--ffmpeg', required=True, type=Path)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    job = args.package.resolve()
    pkg = read(job / 'package.json')
    conversion = read(job / 'texture_conversion.json')
    report = {'job': str(job), 'passed': True, 'textures': [], 'audio': [], 'errors': []}
    for file in sorted(job.rglob('*.png')):
        if '_internal' in file.relative_to(job).parts or 'png_rgb' not in file.relative_to(job).parts:
            continue
        try:
            with Image.open(file) as im:
                im.load()
                record = {'file': file.relative_to(job).as_posix(), 'mode': im.mode,
                          'size': list(im.size), 'png_color_type': file.read_bytes()[25],
                          'transparency_metadata': 'transparency' in im.info}
            record['passed'] = record['mode'] == 'RGB' and record['png_color_type'] == 2 and not record['transparency_metadata']
            report['textures'].append(record)
            report['passed'] &= record['passed']
        except Exception as error:
            report['errors'].append({'file': str(file), 'error': str(error)})
    for key, rel in pkg['textures'].items():
        item = conversion['converted'].get(key)
        if not item:
            report['errors'].append({'texture': key, 'error': 'missing conversion record'})
            continue
        file = job / item['rgb']
        with Image.open(file) as im:
            if list(im.size) != item['size']:
                report['errors'].append({'texture': key, 'error': 'size mismatch'})
        with (job / rel).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != item['source_sha256']:
                report['errors'].append({'texture': key, 'error': 'source DDS hash mismatch'})
    report['errors'].extend(conversion['errors'])
    report['texture_count_matches'] = len(conversion['converted']) == len(pkg['textures']) == len(list((job / 'textures/png_rgb').glob('*.png')))
    audio_file = job / 'audio/audio_report.json'
    if audio_file.exists():
        for event in read(audio_file)['events'].values():
            file = job / 'audio' / event['mp3']
            try:
                data = subprocess.check_output([str(args.ffmpeg.with_name('ffprobe.exe')), '-v', 'error',
                    '-select_streams', 'a:0', '-show_entries', 'stream=codec_name,sample_rate,channels,bit_rate',
                    '-of', 'json', str(file)], text=True)
                record = json.loads(data)['streams'][0]
                record['file'] = file.relative_to(job).as_posix()
                with file.open('rb') as stream:
                    record['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
                decode = subprocess.run([str(args.ffmpeg), '-v', 'error', '-nostdin', '-i', str(file), '-f', 'null', '-'], capture_output=True, text=True)
                record['decode_exit'] = decode.returncode
                record['passed'] = decode.returncode == 0 and record['codec_name'] == 'mp3' and record['sample_rate'] == '48000' and record['channels'] == 2 and record['bit_rate'] == '192000' and record['sha256'] == event['sha256']
                report['audio'].append(record)
                report['passed'] &= record['passed']
            except Exception as error:
                report['errors'].append({'file': str(file), 'error': str(error)})
    report['counts'] = {'textures': len(report['textures']), 'mp3_events': len(report['audio']),
                        'mp3_action_links': len(list((job / 'audio/by_action').rglob('*.mp3')))}
    report['passed'] &= report['texture_count_matches'] and not report['errors']
    output = args.out or job / 'format_validation.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('textures', 'audio')}, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
