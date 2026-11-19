"""Bound Blender memory with independent, resumable complete action-batch projects.

No animation is silently removed or merged into a memory-heavy final Blender process.
The parent package remains the authoritative full input for CS2 and audio export.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from memory_budget import require_memory

VERSION = '0.10.6'
SCRIPTS = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def save(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + '.pending')
    pending.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(pending, path)


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def partition(clips, count, frames=8000):
    if count < 1 or frames < 1:
        raise ValueError('Batch size and frame budget must be positive')
    batches = []; current = []; used = 0
    for clip in clips:
        if current and (len(current) >= count or used + clip['frames'] > frames):
            batches.append(current); current = []; used = 0
        current.append(clip); used += clip['frames']
    if current or not batches:
        batches.append(current)
    return batches


def input_files(p):
    for folder in ('models', 'animations', 'textures', 'equipment', '_internal/rgba'):
        base = p / folder
        if base.exists():
            for f in sorted(base.rglob('*')):
                if f.is_file() and f.suffix.lower() not in ('.blend', '.blend1', '.log') and 'backups' not in f.relative_to(base).parts:
                    yield f
    for name in ('package.json', 'tae.json', 'weapon_motion.json', 'texture_conversion.json'):
        f = p / name
        if f.exists():
            yield f


def fingerprint(p, options):
    h = hashlib.sha256(json.dumps(options, sort_keys=True).encode())
    for f in [*input_files(p), *sorted(SCRIPTS.glob('*.py'))]:
        h.update(str(f.relative_to(p) if f.is_relative_to(p) else f.name).encode('utf-8'))
        h.update(bytes.fromhex(sha(f)))
    return h.hexdigest()


def stage(p, dest, pkg, clips, root_options):
    dest.mkdir(parents=True, exist_ok=True)
    for f in input_files(p):
        rel = f.relative_to(p)
        if rel.as_posix() in ('package.json', 'texture_conversion.json'):
            continue
        target = dest / rel; target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        # Read-only inputs on the same drive share disk blocks; generated reports do not.
        try:
            os.link(f, target)
        except OSError:
            shutil.copy2(f, target)
    subset = dict(pkg); subset['clips'] = clips
    # Facial TAE may reference an HKX outside this batch. Keep that source table,
    # but do not export those dependencies as extra user-visible Actions.
    subset['_face_source_clips'] = pkg.get('_face_source_clips', pkg['clips'])
    subset['batch_source_package'] = str(p)
    save(dest / 'package.json', subset)
    if root_options:
        names = {c['name'] for c in clips}
        options = {**root_options, 'actions': [n for n in root_options['actions'] if n in names]}
        save(dest / 'root_motion_options.json', options)


def run_stage(blender, folder, script, extra=()):
    available = require_memory()
    print('STAGE', script, folder.name, 'commit_available_MB', None if available is None else available//1024**2, flush=True)
    logs = folder / '_internal/pipeline_logs'; logs.mkdir(parents=True, exist_ok=True)
    cmd = [str(blender), '--background', '--factory-startup', '--disable-autoexec', '--threads', '4',
           '--python-exit-code', '1', '--python', str(SCRIPTS/'blender_bootstrap.py'), '--python', str(SCRIPTS / script), '--', str(folder), *map(str, extra)]
    memory = False; detail = ''
    with (logs / (script + '.log')).open('w', encoding='utf-8') as log:
        child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',cwd=os.environ.get('SCT_CACHE_ROOT'))
        try:
            for line in child.stdout:
                log.write(line); log.flush(); print(line, end='', flush=True)
                memory |= any(s in line for s in ('MemoryError', 'ArrayMemoryError', 'Malloc returns null', 'Unable to allocate', 'SCT_MEMORY'))
                if 'Error:' in line or 'Exception:' in line: detail = line.strip()
            code = child.wait()
        except BaseException:
            child.terminate(); child.wait(); raise
    if code:
        if memory:
            raise MemoryError('SCT_MEMORY: Blender 系统可提交内存不足；减少每批动作数或关闭大内存程序后“继续已有提取包”。已完成批次不重跑。')
        raise RuntimeError(detail or f'{script} exited {code}; see {logs}')


def build(args):
    p = args.package.resolve(); pkg = read(p / 'package.json')
    from runtime_paths import configure
    cache_root=Path(getattr(args,'cache_root',None) or os.environ.get('SCT_CACHE_ROOT') or SCRIPTS.parent/'cache').resolve()
    runtime_cache=configure(os.environ.get('SCT_CACHE_ROOT') or cache_root)
    selected = pkg['clips']
    if args.clip_list:
        names = set(read(args.clip_list)); available = {c['name'] for c in selected}
        if not names or names - available:
            raise ValueError('Selected action list is empty or contains unknown names')
        selected = [c for c in selected if c['name'] in names]
    root_options = read(args.root_options) if args.root_options else None
    if root_options and (not set(root_options['actions']) <= {c['name'] for c in pkg['clips']} or
                         not root_options.get('axes') or set(root_options['axes']) - set('XYZ')):
        raise ValueError('Invalid root-motion action selection or axes')
    options = dict(version=VERSION, clean=args.clean_bones, hierarchy=args.hierarchy, helpers=args.helper_visibility,
                   batch_size=args.batch_size, roots=root_options, clips=[c['name'] for c in selected], action_cache=getattr(args,'action_cache',False))
    identity = fingerprint(p, options)
    groups = partition(selected, args.batch_size) if args.batch_size else [selected]
    # A subset is always a separate project, never overwrite the full package's blend.
    batched = len(groups) > 1 or args.clip_list is not None
    report_path = p / 'blend_batches.json'
    previous = read(report_path) if report_path.exists() else {}
    same = previous.get('identity') == identity
    report = dict(version=VERSION, identity=identity, mode='action_batches' if batched else 'single',
                  passed=False, status='running', source_actions=len(pkg['clips']), selection_only=bool(args.clip_list), expected_actions=len(selected), completed_actions=0,
                  options=options, batches=[], errors=[], source_unchanged=True)
    save(report_path, report)
    try:
        for i, clips in enumerate(groups):
            dest = p / 'animation_batches' / identity[:12] / f'batch_{i+1:04d}' if batched else p
            blend = dest / (pkg['character'] + '.blend')
            cache_id=hashlib.sha256((identity+'|'+str(dest)).encode('utf-8')).hexdigest()
            action_folder=cache_root/'actions'/cache_id
            prior = next((b for b in previous.get('batches', []) if b['index']==i), {}) if same else {}
            checkpoint = dest / '_internal/build_checkpoint.json'
            if checkpoint.exists():
                cached = read(checkpoint)
                if cached.get('identity') == identity: prior = cached
            if prior.get('passed') and blend.exists() and sha(blend)==prior.get('sha256'):
                rec = dict(prior); rec['resumed'] = True
                print('BATCH_REUSED', i+1, len(clips), flush=True)
            else:
                if shutil.disk_usage(p).free < 1024**3:
                    raise OSError('输出磁盘剩余空间不足 1 GB；请释放空间后继续。已完成批次保留。')
                if batched: stage(p, dest, pkg, clips, root_options)
                if blend.exists():
                    backup = dest / 'backups' / datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                    backup.mkdir(parents=True, exist_ok=True); shutil.copy2(blend, backup / blend.name)
                roots = (dest/'root_motion_options.json') if batched else args.root_options
                direct_options = ['--helper-visibility', args.helper_visibility]
                if args.clean_bones: direct_options.append('--clean-bones')
                if args.hierarchy: direct_options.append('--hierarchy')
                if getattr(args,'action_cache',False): direct_options += ['--action-cache',str(cache_root),'--cache-identity',cache_id]
                if roots and roots.exists() and read(roots)['actions']: direct_options += ['--root-options', str(roots)]
                steps = [('build_character.py', direct_options), ('verify_final.py', [])]
                for script, extra in steps: run_stage(args.blender, dest, script, extra)
                reports = ['blender_validation.json', 'saved_validation.json', 'appearance_validation.json', 'helper_visibility_report.json', 'direct_final_validation.json']
                if args.clean_bones: reports.append('bone_cleanup.json')
                if args.hierarchy: reports.append('hierarchy_report.json')
                validations = {name: read(dest/name) for name in reports}
                if roots and roots.exists() and read(roots)['actions']:
                    validations['root_motion_report.json'] = read(dest/'root_motion_report.json')
                failed = [name for name, value in validations.items() if not value.get('passed')]
                if failed: raise RuntimeError('Validation failed: '+', '.join(failed)+'; '+str(dest))
                rec = dict(index=i, passed=True, folder=str(dest), blend=str(blend), sha256=sha(blend),
                           actions=[c['name'] for c in clips], validations={k:True for k in validations}, resumed=False, identity=identity)
                save(checkpoint, rec)
            if getattr(args,'action_cache',False) and not getattr(args,'keep_action_cache',False) and action_folder.exists():
                # Delete only the exact input/options/batch namespace, never cache root.
                resolved=action_folder.resolve();expected=(cache_root/'actions').resolve()
                if resolved.parent!=expected or resolved.name!=cache_id or action_folder.is_symlink():raise ValueError('Unsafe action-cache cleanup path')
                for item in action_folder.iterdir():
                    if item.is_symlink() or not item.is_file() or item.suffix not in ('.npz','.json','.pending'):raise ValueError('Unexpected cache entry; preserved '+str(item))
                shutil.rmtree(action_folder);rec['action_cache_cleaned']=True
                print('ACTION_CACHE_CLEANED',action_folder,flush=True)
            report['batches'].append(rec); report['completed_actions'] += len(clips); save(report_path, report)
            print('BATCH_COMPLETE', i+1, len(groups), report['completed_actions'], '/', len(selected), flush=True)
        report.update(passed=True, status='complete')
        old = p / 'execution_validation.json'
        if old.exists() and not args.clip_list: old.rename(p / ('execution_failure_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json'))
    except BaseException as e:
        report.update(status='incomplete', errors=[str(e)]); raise
    finally:
        save(report_path, report)
    print('BLEND_PIPELINE_DONE', len(selected), 'actions', len(groups), 'projects', flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('package', type=Path); ap.add_argument('--blender', required=True, type=Path)
    ap.add_argument('--batch-size', type=int, default=8, help='0: single large blend; default 8: bounded complete batch projects')
    ap.add_argument('--clip-list', type=Path); ap.add_argument('--root-options', type=Path)
    ap.add_argument('--clean-bones', action='store_true'); ap.add_argument('--hierarchy', action='store_true')
    ap.add_argument('--helper-visibility', choices=['visible','hidden'], default='visible')
    ap.add_argument('--cache-root',type=Path)
    ap.add_argument('--action-cache',action='store_true',help='Spool final actions to selected local cache, assemble only at end')
    ap.add_argument('--keep-action-cache',action='store_true',help='Keep successful action caches; failure always preserves them')
    args = ap.parse_args()
    if args.batch_size < 0: ap.error('batch-size must be non-negative')
    lockfile=args.package.resolve()/'_internal/pipeline.lock';lockfile.parent.mkdir(parents=True,exist_ok=True)
    # Prevent same-package authoring/cleanup races, including separate GUI instances.
    with lockfile.open('a+b') as lock:
        if os.name=='nt':
            import msvcrt
            lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise RuntimeError('This package is already being built; its cache is in use')
        try:build(args)
        finally:
            if os.name=='nt':lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


if __name__ == '__main__': main()
