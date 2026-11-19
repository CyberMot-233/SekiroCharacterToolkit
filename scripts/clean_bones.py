"""Clean generated unused bones; back up and validate before atomic replacement."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import sys

import bpy
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rig_cleanup import plan, apply_cleanup, action_digest, snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('package', type=Path)
    ap.add_argument('--audit', action='store_true')
    ap.add_argument('--no-backup', action='store_true')
    ap.add_argument('--recover-staged', action='store_true', help='Validate an existing staged cleanup against the original without saving again')
    args = ap.parse_args(sys.argv[sys.argv.index('--') + 1:])
    folder = args.package.resolve()
    pkg = json.loads((folder / 'package.json').read_text(encoding='utf-8-sig'))
    file = folder / (pkg['character'] + '.blend')
    bpy.ops.wm.open_mainfile(filepath=str(file))
    arm = bpy.data.objects[pkg['character'] + '_Armature']
    if arm.data.users > 1:
        raise ValueError('Shared armature data: make single-user before cleanup')
    models = [json.loads((folder / rel).read_text(encoding='utf-8-sig')) for rel in pkg['models']]
    report, meshes = plan(arm, models)
    report.update(passed=False, character=pkg['character'], mode='audit' if args.audit else 'cleanup', errors=[])
    if args.audit:
        report['passed'] = True
        (folder / 'bone_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('BONE_AUDIT', report['before'], report['after'], flush=True)
        return
    actions = list(bpy.data.actions)
    if arm.animation_data and arm.animation_data.nla_tracks:
        raise ValueError('NLA tracks present: use a fresh toolkit export for cleanup')
    for other in bpy.data.objects:
        ad = other.animation_data
        if other != arm and ad and (ad.action in actions or any(strip.action in actions for track in ad.nla_tracks for strip in track.strips)):
            raise ValueError('Shared actions on another object: cleanup requires a single-rig toolkit export')
    # Multi-slot/shared user animation cannot safely be edited without owner mapping.
    if any(len(a.slots) > 1 for a in actions):
        raise ValueError('Multiple action slots: cleanup requires a toolkit single-rig export')
    removed = {r['bone'] for r in report['removed']}
    names = sorted(set(arm.data.bones.keys()) - removed)
    before_hashes = {a.name: action_digest(a, removed) for a in actions}
    print('BONE_CLEANUP_PLAN', report['before'], '->', report['after'], 'actions', len(actions), flush=True)
    before_pose = snapshot(arm, actions, names)
    if not args.no_backup:
        backup = folder / 'backups' / ('bones_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')) / file.name
        backup.parent.mkdir(parents=True)
        shutil.copy2(file, backup)
        report['backup'] = str(backup)
    staged = folder / (file.stem + '.cleanup_pending.blend')
    if not args.recover_staged:
        apply_cleanup(arm, report, meshes, actions)
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(staged), compress=True)
    elif not staged.exists():
        raise FileNotFoundError(staged)
    # open_mainfile loads the new Main before freeing the current one. Explicitly
    # release the 1,434-action Main first to avoid doubling committed memory.
    actions.clear(); meshes.clear()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.open_mainfile(filepath=str(staged))
    arm = bpy.data.objects[pkg['character'] + '_Armature']
    after = snapshot(arm, list(bpy.data.actions), names)
    report['matrix_checks'] = int(np.prod(before_pose.shape[:-2]))
    report['max_retained_matrix_error'] = float(np.max(np.abs(before_pose - after))) if before_pose.size else 0.0
    report['retained_curves_unchanged'] = before_hashes == {a.name: action_digest(a) for a in bpy.data.actions}
    report['actions'] = len(bpy.data.actions)
    if set(arm.data.bones.keys()) != set(names):
        report['errors'].append('Staged cleanup bone set differs from the dependency plan')
    report['scope'] = 'all retained curve keys/handles unchanged; all actions first/middle/last evaluated bone and object matrices; saved file reopened'
    if report['max_retained_matrix_error'] > 1e-6 or not report['retained_curves_unchanged']:
        report['errors'].append('Retained animation changed; original blend was not replaced')
    report['passed'] = not report['errors']
    if report['passed']:
        os.replace(staged, file)
    (folder / 'bone_cleanup.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('BONE_CLEANUP', report['before'], '->', report['after'], 'removed', report['removed_count'], 'passed', report['passed'], flush=True)
    if not report['passed']:
        raise RuntimeError(report['errors'])


if __name__ == '__main__':
    main()
