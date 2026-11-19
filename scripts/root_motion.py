"""Apply per-action in-place translation masks without touching source HKX data."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import bpy
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rig_cleanup import curves


def untouched_digest(action, axes):
    h = hashlib.sha256()
    for _, fc in curves(action):
        if fc.data_path == 'location' and fc.array_index in axes:
            continue
        h.update(repr((fc.data_path, fc.array_index, fc.extrapolation)).encode())
        for prop in ('co', 'handle_left', 'handle_right'):
            v = np.empty(len(fc.keyframe_points) * 2, np.float32)
            fc.keyframe_points.foreach_get(prop, v)
            h.update(v.tobytes())
        h.update(repr([k.interpolation for k in fc.keyframe_points]).encode())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('package', type=Path)
    ap.add_argument('--options', type=Path, required=True)
    ap.add_argument('--no-backup', action='store_true')
    args = ap.parse_args(sys.argv[sys.argv.index('--') + 1:])
    folder = args.package.resolve()
    pkg = json.loads((folder / 'package.json').read_text(encoding='utf-8-sig'))
    options = json.loads(args.options.read_text(encoding='utf-8-sig'))
    selection = set(options.get('actions', []))
    axes = sorted(set(options.get('axes', '')))
    if not set(axes) <= set('XYZ'):
        raise ValueError('Axes must be Blender X/Y/Z')
    file = folder / (pkg['character'] + '.blend')
    bpy.ops.wm.open_mainfile(filepath=str(file))
    arm = bpy.data.objects[pkg['character'] + '_Armature']
    if arm.constraints or (arm.animation_data and arm.animation_data.drivers):
        raise ValueError('Root object has constraints/drivers; in-place edits require unmodified toolkit root')
    if arm.animation_data and arm.animation_data.nla_tracks:
        raise ValueError('NLA tracks present: use a fresh toolkit export before root-motion processing')
    clips = {c['name']: c for c in pkg['clips']}
    missing = selection - set(clips)
    if missing:
        raise ValueError('Unknown selected actions: ' + ', '.join(sorted(missing)))
    if any(name not in bpy.data.actions for name in selection):
        raise ValueError('Selected action missing from blend')
    if selection and not axes:
        raise ValueError('Select at least one translation axis')
    report = {'passed': False, 'axes': axes, 'coordinate_system': 'Blender (game X,-Z,Y); Z is vertical',
              'mode': 'hold selected translations at source first sample; keep root rotation',
              'actions': [], 'errors': [], 'source_package_unchanged': True}
    axis_indices = {'XYZ'.index(axis) for axis in axes}
    originals = {a.name: untouched_digest(a, axis_indices if a.name in selection else set()) for a in bpy.data.actions}
    if selection and not args.no_backup:
        backup = folder / 'backups' / ('rootmotion_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')) / file.name
        backup.parent.mkdir(parents=True)
        shutil.copy2(file, backup)
        report['backup'] = str(backup)
    for name in sorted(selection):
        action = bpy.data.actions[name]
        samples = clips[name]['rootMotion']['samples']
        if not samples:
            raise ValueError('No source root samples: ' + name)
        previous = json.loads(action.get('sct_root_motion_axes', '[]'))
        combined = sorted(set(previous) | set(axes))
        for axis in axis_indices:
            fc = action.fcurves.find('location', index=axis)
            if fc is None or fc.modifiers:
                raise ValueError('Missing or modified root curve: ' + name + '/' + 'XYZ'[axis])
            anchor = float(samples[0][axis + 1])
            # Keep timing/handles; flatten only the selected translation component.
            for key in fc.keyframe_points:
                key.co.y = anchor
                key.handle_left.y = anchor
                key.handle_right.y = anchor
            fc.update()
        action['sct_root_motion_axes'] = json.dumps(combined)
        action['sct_root_motion_anchor'] = json.dumps(samples[0][1:4])
        action['sct_root_motion_source'] = name
        report['actions'].append({'name': name, 'removed_axes': combined, 'anchor': samples[0][1:4]})
    staged = folder / (file.stem + '.rootmotion_pending.blend')
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(staged), compress=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.open_mainfile(filepath=str(staged))
    report['unselected_channels_unchanged'] = originals == {a.name: untouched_digest(a, axis_indices if a.name in selection else set()) for a in bpy.data.actions}
    checks = 0
    max_error = 0.0
    for name in selection:
        action = bpy.data.actions[name]
        for sample in clips[name]['rootMotion']['samples']:
            for axis in axis_indices:
                fc = action.fcurves.find('location', index=axis)
                error = abs(fc.evaluate(1 + 30 * sample[0]) - clips[name]['rootMotion']['samples'][0][axis + 1])
                checks += 1
                max_error = max(max_error, error)
    report.update(checks=checks, max_axis_error=max_error)
    if not report['unselected_channels_unchanged'] or max_error > 1e-6:
        report['errors'].append('Saved root-motion validation failed; original file unchanged')
    report['passed'] = not report['errors']
    if report['passed']:
        os.replace(staged, file)
    (folder / 'root_motion_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ROOT_MOTION', len(selection), axes, checks, 'passed', report['passed'], flush=True)
    if not report['passed']:
        raise RuntimeError(report['errors'])


if __name__ == '__main__':
    main()
