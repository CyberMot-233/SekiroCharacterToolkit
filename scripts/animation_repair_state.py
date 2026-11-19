"""Capture root-motion choices read-only, or restore them to a rebuilt copy."""
import bpy, json, sys, math
from pathlib import Path
args=sys.argv[sys.argv.index('--')+1:]; mode, folder, state_file=args
p=Path(folder); pkg=json.loads((p/'package.json').read_text(encoding='utf-8-sig'))
bpy.ops.wm.open_mainfile(filepath=str(p/(pkg['character']+'.blend')))
arm=bpy.data.objects[pkg['character']+'_Armature']
if mode=='capture':
    state={'hierarchy':bool(arm.get('sct_hierarchy_version')), 'clean':(p/'bone_cleanup.json').exists(),
           'action':arm.animation_data.action.name if arm.animation_data.action else None,
           'frame':bpy.context.scene.frame_current+bpy.context.scene.frame_subframe,
           'root':{a.name:{'axes':json.loads(a.get('sct_root_motion_axes','[]')),
                           'anchor':json.loads(a.get('sct_root_motion_anchor','[]'))} for a in bpy.data.actions}}
    Path(state_file).write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
else:
    state=json.loads(Path(state_file).read_text(encoding='utf-8'))
    for name,settings in state['root'].items():
        action=bpy.data.actions.get(name)
        if action is None:raise ValueError('Missing original action '+name)
        if not settings['axes']:continue
        for axis in settings['axes']:
            i='XYZ'.index(axis);fc=action.fcurves.find('location',index=i)
            if fc is None:raise ValueError('Missing root curve')
            for k in fc.keyframe_points:k.co.y=k.handle_left.y=k.handle_right.y=settings['anchor'][i]
            fc.update()
        action['sct_root_motion_axes']=json.dumps(settings['axes']);action['sct_root_motion_anchor']=json.dumps(settings['anchor']);action['sct_root_motion_source']=name
    if state['action'] in bpy.data.actions:
        arm.animation_data.action=bpy.data.actions[state['action']]
        if arm.animation_data.action.slots:arm.animation_data.action_slot=arm.animation_data.action.slots[0]
        bpy.context.scene.frame_end=math.ceil(arm.animation_data.action.frame_range[1]-1e-4)
    f=state['frame'];bpy.context.scene.frame_set(math.floor(f),subframe=f%1)
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(p/(pkg['character']+'.blend')),compress=True)
print('REPAIR_STATE',mode,flush=True)
