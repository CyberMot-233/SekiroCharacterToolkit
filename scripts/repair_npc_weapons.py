"""Repair only NPC mask curves, preserving all geometry and motion channels."""
import argparse, hashlib, json, os, runpy, shutil, sys, time
from pathlib import Path
import bpy
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_masks import ModelMasks, states

def curve_digest():
    h = hashlib.sha256()
    for action in sorted(bpy.data.actions, key=lambda a:a.name):
        h.update(action.name.encode())
        for fc in action.fcurves:
            if 'sct_mask_' in fc.data_path: continue
            h.update((fc.data_path + ':' + str(fc.array_index)).encode())
            for prop in ('co','handle_left','handle_right'):
                v=np.empty(len(fc.keyframe_points)*2,np.float32);fc.keyframe_points.foreach_get(prop,v);h.update(v.tobytes())
    return h.hexdigest()

def repair(folder, mode):
    pkg=json.loads((folder/'package.json').read_text('utf-8-sig'));file=folder/(pkg['character']+'.blend')
    if not file.exists(): raise FileNotFoundError(file)
    bpy.ops.wm.open_mainfile(filepath=str(file));arm=bpy.data.objects[pkg['character']+'_Armature'];sc=bpy.context.scene
    original_action=arm.animation_data.action;original_frame=sc.frame_current;original_sub=sc.frame_subframe
    backup=folder/'backups'/('npc_weapons_'+time.strftime('%Y%m%d_%H%M%S')+'_'+str(time.time_ns()%1000000));backup.mkdir(parents=True)
    shutil.copy2(file,backup/file.name);shutil.copy2(folder/'package.json',backup/'package.json')
    before=curve_digest();counts=(len(bpy.data.actions),len(arm.data.bones),sum(len(o.data.vertices) for o in bpy.data.objects if o.type=='MESH'))
    pkg.setdefault('npcAppearance',{})['weapon_policy']=mode;mask=ModelMasks(pkg,folder,arm)
    objects=[o for o in bpy.data.objects if o.type=='MESH' and 'source_draw_mask' in o]
    for ob in objects:
        for prop in ('hide_render','hide_viewport'):ob.driver_remove(prop)
        mask.bind(ob,int(ob['source_draw_mask']))
    checks=0
    for clip in pkg['clips']:
        action=bpy.data.actions.get(clip['name'])
        if action is None: raise ValueError('Missing action '+clip['name'])
        for fc in list(action.fcurves):
            if 'sct_mask_' in fc.data_path:action.fcurves.remove(fc)
        mask.bake(action,clip)
        # Evaluate newly baked curves with event boundary keys, not just count them.
        base,_=mask.weapon_policy.resolve(clip);events=mask.events(clip)
        frames={float(k.co.x) for fc in action.fcurves if 'sct_mask_' in fc.data_path for k in fc.keyframe_points}
        frames.update([1.,float(action.frame_range[1])])
        for f in frames:
            expected=states(base,events,(f-1)/30)
            for i in mask.used:
                fc=action.fcurves.find('["sct_mask_%02d"]'%i);checks+=1
                if bool(fc.evaluate(f)>.5)!=expected[i]:raise ValueError('Mask evaluation mismatch '+clip['name'])
    after=curve_digest()
    if before!=after or counts!=(len(bpy.data.actions),len(arm.data.bones),sum(len(o.data.vertices) for o in bpy.data.objects if o.type=='MESH')):
        raise ValueError('Non-mask data unexpectedly changed')
    arm.animation_data.action=original_action
    if original_action and original_action.slots:arm.animation_data.action_slot=original_action.slots[0]
    sc.frame_set(original_frame,subframe=original_sub);bpy.context.view_layer.update()
    sc['sct_npc_weapon_policy_version']='0.10.6'
    staged=file.with_name(file.stem+'.weapon_pending.blend');bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(staged),compress=True);os.replace(staged,file)
    pending=folder/'package.json.pending';pending.write_text(json.dumps(pkg,ensure_ascii=False),encoding='utf8');os.replace(pending,folder/'package.json')
    bpy.ops.wm.open_mainfile(filepath=str(file))
    if curve_digest()!=before:raise ValueError('Saved non-mask channels changed')
    old_argv=sys.argv
    try:
        sys.argv=['verify_appearance.py','--',str(folder),'--already-open']
        runpy.run_path(str(Path(__file__).with_name('verify_appearance.py')),run_name='__main__')
    finally:sys.argv=old_argv
    report=dict(passed=True,mode=mode,backup=str(backup),actions=counts[0],bones=counts[1],vertices=counts[2],
        non_mask_curves_before=before,non_mask_curves_after=after,checks=checks,records=mask.records,
        scope='Only visibility drivers and mask curves changed; source FK, mesh, bind, root motion, face, audio unchanged')
    (folder/'npc_weapon_repair.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('NPC_WEAPON_REPAIR_DONE',folder,counts[0],'actions',checks,'checks',flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('package',type=Path);parser.add_argument('--mode',choices=['auto','fixed'],default='auto')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);p=args.package.resolve();pkg=json.loads((p/'package.json').read_text('utf-8-sig'))
    targets=[]
    if (p/(pkg['character']+'.blend')).exists():targets.append(p)
    index=p/'blend_batches.json'
    if index.exists():
        for entry in json.loads(index.read_text('utf8')).get('batches',[]):
            file=Path(entry['blend']).resolve()
            if file.exists() and file.parent not in targets:
                if not file.is_relative_to(p):raise ValueError('Batch outside selected package')
                targets.append(file.parent)
    if not targets:raise ValueError('No completed Blender project found')
    lockfile=p/'_internal/pipeline.lock';lockfile.parent.mkdir(parents=True,exist_ok=True)
    with lockfile.open('a+b') as lock:
        if os.name=='nt':
            import msvcrt
            lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise RuntimeError('This package is being built or repaired by another task')
        try:
            for folder in targets:repair(folder,args.mode)
            if p not in targets:
                pkg.setdefault('npcAppearance',{})['weapon_policy']=args.mode
                (p/'package.json').write_text(json.dumps(pkg,ensure_ascii=False),encoding='utf8')
        finally:
            if os.name=='nt':lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
    print('NPC_WEAPON_REPAIR_ALL_DONE',len(targets),flush=True)

if __name__=='__main__':main()
