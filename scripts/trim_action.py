"""Trim a selected Action across ALL channel bags, including hidden affine bones."""
import argparse,datetime,json,math,os,shutil,sys
from pathlib import Path
import bpy,numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from rig_cleanup import curves,action_digest

def set_frame(arm,action,f):
    arm.animation_data.action=action
    if action.slots:arm.animation_data.action_slot=action.slots[0]
    arm.update_tag(refresh={'OBJECT','DATA','TIME'})
    bpy.context.scene.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
def matrices(arm):return np.array([np.array(arm.matrix_world)]+[np.array(b.matrix) for b in arm.pose.bones])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('package',type=Path);ap.add_argument('--action',required=True);ap.add_argument('--end',required=True,type=float);a=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    p=a.package.resolve();pkg=json.loads((p/'package.json').read_text(encoding='utf-8-sig'));file=p/(pkg['character']+'.blend')
    bpy.ops.wm.open_mainfile(filepath=str(file));arm=bpy.data.objects[pkg['character']+'_Armature'];action=bpy.data.actions.get(a.action)
    if action is None:raise ValueError('Action not found')
    if arm.animation_data.nla_tracks or arm.constraints or arm.animation_data.drivers or any(b.constraints for b in arm.pose.bones):raise ValueError('Custom NLA/constraints/drivers not supported')
    if len(action.slots)>1:raise ValueError('Multi-slot Action not supported')
    start,end=action.frame_range
    if not math.isfinite(a.end) or a.end<start or a.end>end:raise ValueError('End must be within current action range')
    if any(fc.modifiers or fc.sampled_points or fc.mute for _,fc in curves(action)):raise ValueError('Modified/sampled/muted channels: use unmodified toolkit curves')
    if any(k.interpolation not in {'LINEAR','CONSTANT'} for _,fc in curves(action) for k in fc.keyframe_points):raise ValueError('Only toolkit linear/constant curves are supported; custom Bezier curves require manual editing')
    original={x.name:action_digest(x) for x in bpy.data.actions if x!=action}
    set_frame(arm,action,a.end);expected=matrices(arm);values={(fc.data_path,fc.array_index):fc.evaluate(a.end) for _,fc in curves(action)}
    backup=p/'backups'/('trim_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))/file.name;backup.parent.mkdir(parents=True);shutil.copy2(file,backup)
    removed=0;channels=0;hidden=0
    for _,fc in curves(action):
        for k in list(fc.keyframe_points)[::-1]:
            if k.co.x>=a.end-1e-5:fc.keyframe_points.remove(k,fast=True);removed+=1
        # Freeze every channel at the chosen cut, including those hidden by the UI.
        k=fc.keyframe_points.insert(a.end,values[(fc.data_path,fc.array_index)],options={'FAST'});k.interpolation='LINEAR';fc.extrapolation='CONSTANT';fc.update();channels+=1
        if 'AFF' in fc.data_path:hidden+=1
    action['sct_trim_end']=a.end;action['sct_trim_original_end']=action.get('sct_trim_original_end',float(end));action.use_frame_range=True;action.frame_start=start;action.frame_end=a.end
    bpy.context.scene.frame_end=max(1,math.ceil(a.end-1e-5));set_frame(arm,action,a.end)
    staged=p/(file.stem+'.trim_pending.blend');bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.save_as_mainfile(filepath=str(staged),compress=True);bpy.ops.wm.open_mainfile(filepath=str(staged))
    arm=bpy.data.objects[pkg['character']+'_Armature'];action=bpy.data.actions[a.action];error=0.;keys_after=0;channel_error=0.
    for f in (a.end,a.end+.125,a.end+1,a.end+30):
        set_frame(arm,action,f);error=max(error,float(np.max(abs(matrices(arm)-expected))))
        for _,fc in curves(action):channel_error=max(channel_error,abs(fc.evaluate(f)-values[(fc.data_path,fc.array_index)]))
    for _,fc in curves(action):keys_after+=sum(k.co.x>a.end+1e-4 for k in fc.keyframe_points)
    unchanged=original=={x.name:action_digest(x) for x in bpy.data.actions if x!=action}
    report={'passed':error<5e-4 and channel_error<1e-5 and keys_after==0 and unchanged,'action':a.action,'end':a.end,'backup':str(backup),'curves':channels,'affine_curves':hidden,'removed_keys':removed,'keys_after_cut':keys_after,'max_matrix_error':error,'max_channel_error':channel_error,'other_actions_unchanged':unchanged,'scope':'all selected action channels incl hidden helpers, root/equipment/masks; end pose and extrapolation at +0.125/+1/+30 frames; other action digests'}
    if report['passed']:os.replace(staged,file)
    (p/'action_trim_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('ACTION_TRIM',report,flush=True)
    if not report['passed']:raise RuntimeError('Trim verification failed; original unchanged')
if __name__=='__main__':main()
