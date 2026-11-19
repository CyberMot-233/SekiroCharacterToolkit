"""Restore source bone parenting and re-bake local animation, preserving skin matrices.

Keeps an affine helper only where local TRS cannot represent the source transform.
All processing is staged; the original blend is replaced only after verification.
"""
import argparse, datetime, hashlib, json, math, os, shutil, sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector, Quaternion
sys.path.insert(0, str(Path(__file__).resolve().parent))
from internal_fk_verified import DEFAULT_C, fk_separate_scale
from affine_factor import factor_affine
from flver_mapping import mapped_fk
from face_overlay import FaceOverlay
from equipment_core import PoseCache
from rig_cleanup import curves, path_bones
from linear_keys import reduce_keys
from hierarchy_math import local_basis, trs_residual, decompose_many
from internal_fk_verified import _quaternion_matrices

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def arrays(path):
    with np.load(path) as data:return {n:data[n] for n in data.files}
def converted(value): return DEFAULT_C @ np.asarray(value).reshape(4,4).T @ np.linalg.inv(DEFAULT_C)
def write(action, name, frames, values):
    for prop, start, width in [('location',0,3),('rotation_quaternion',3,4),('scale',7,3)]:
        path='pose.bones['+json.dumps(name)+'].'+prop if name else prop
        for k in range(width):
            vals=values[:,start+k]; keep=reduce_keys(frames,vals,tolerance=1e-7)
            fc=action.fcurves.new(path,index=k,action_group=name or 'RootMotion');fc.keyframe_points.add(len(keep))
            fc.keyframe_points.foreach_set('co',np.column_stack((frames[keep],vals[keep])).astype(np.float32).ravel())
            linear=bpy.types.Keyframe.bl_rna.properties['interpolation'].enum_items['LINEAR'].value
            fc.keyframe_points.foreach_set('interpolation',np.full(len(keep),linear,dtype=np.int32))
            fc.update()
def decomp(matrices):
    if trs_residual(matrices)<4e-6:
        try:
            rows=decompose_many(matrices);q=rows[:,3:7][:,[1,2,3,0]];rebuilt=_quaternion_matrices(q);rebuilt[:,:3,:3]*=rows[:,None,7:];rebuilt[:,:3,3]=rows[:,:3]
            return rows,rebuilt
        except ValueError:pass
    rows=[];reconstructed=[]
    for m in matrices:
        loc,q,scale=Matrix(m).decompose();rows.append([*loc,*q,*scale]);reconstructed.append(np.array(Matrix.LocRotScale(loc,q,scale)))
    rows=np.array(rows)
    for i in range(1,len(rows)):
        if rows[i-1,3:7]@rows[i,3:7]<0:rows[i,3:7]*=-1
    return rows, np.asarray(reconstructed)
def invariant(action, changed):
    h=hashlib.sha256()
    for _,fc in curves(action):
        if set(path_bones(fc.data_path)) & changed:continue
        h.update(repr((fc.data_path,fc.array_index)).encode())
        for prop in ('co','handle_left','handle_right'):
            values=np.empty(len(fc.keyframe_points)*2,np.float32);fc.keyframe_points.foreach_get(prop,values);h.update(values.tobytes())
        values=np.empty(len(fc.keyframe_points),np.int32);fc.keyframe_points.foreach_get('interpolation',values);h.update(values.tobytes())
    return h.hexdigest()
def set_action(arm,action):
    arm.animation_data.action=action
    if action.slots:arm.animation_data.action_slot=action.slots[0]
    arm.update_tag(refresh={'OBJECT','DATA','TIME'})
def frame(f):
    bpy.context.scene.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
def vertices(meshes):
    deps=bpy.context.evaluated_depsgraph_get();result={}
    for ob in meshes:
        if ob.hide_viewport or ob.hide_get():continue
        ev=ob.evaluated_get(deps);m=ev.to_mesh();values=np.empty(len(m.vertices)*3,np.float32);m.vertices.foreach_get('co',values)
        result[ob.name]=values.reshape(-1,3).copy();ev.to_mesh_clear()
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('package',type=Path);ap.add_argument('--no-backup',action='store_true');ap.add_argument('--resume-cache',type=Path);args=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    p=args.package.resolve();pkg=read(p/'package.json');file=p/(pkg['character']+'.blend');bpy.ops.wm.open_mainfile(filepath=str(file));arm=bpy.data.objects[pkg['character']+'_Armature']
    if arm.get('sct_hierarchy_version'):
        print('HIERARCHY_ALREADY_RESTORED',arm['sct_hierarchy_version'],flush=True);return
    if arm.data.users>1 or arm.animation_data.nla_tracks or arm.constraints or arm.animation_data.drivers or arm.data.animation_data:
        raise ValueError('Shared/custom constrained/NLA rig: use an unmodified toolkit export')
    if any(pb.constraints for pb in arm.pose.bones):raise ValueError('Custom pose constraints require manual conversion')
    actions=list(bpy.data.actions)
    if any(len(a.slots)>1 for a in actions):raise ValueError('Multi-slot Action not supported')
    for other in bpy.data.objects:
        if other==arm:continue
        if other.parent==arm and other.parent_type=='BONE':raise ValueError('External bone-parented object: rebind it after source rig conversion')
        if other.animation_data and other.animation_data.action in actions:raise ValueError('Shared action on another object')
        if other.type=='MESH':
            for mod in other.modifiers:
                if mod.type=='ARMATURE' and mod.object==arm and mod.use_bone_envelopes:raise ValueError('Envelope deformation cannot preserve rest-length edits')
    models=[read(p/f) for f in pkg['models']];nodes={}
    for model in models:
        for n in model['nodes']:nodes.setdefault(n['name'],{**n,'_parent_name':model['nodes'][n['parent']]['name'] if n['parent']>=0 else None})
    source={b['source_name']:b.name for b in arm.data.bones if b.get('source_name')}
    if not source:raise ValueError('No source_name bone mapping')
    closure=set(source)
    for name in list(closure):
        seen=set();par=nodes[name].get('_parent_name')
        while par:
            if par in seen:raise ValueError('Source parent cycle')
            seen.add(par);closure.add(par);par=nodes[par].get('_parent_name')
    def depth(n):
        result=0
        while nodes[n].get('_parent_name'):result+=1;n=nodes[n]['_parent_name']
        return result
    names=sorted(closure,key=lambda n:(depth(n),n));old_rest={n:np.array(arm.data.bones[b].matrix_local) for n,b in source.items()}
    old_helpers={arm.data.bones[b].parent.name for b in source.values() if arm.data.bones[b].parent and arm.data.bones[b].parent.name.startswith('AFF_')}
    changed=set(source.values())|old_helpers
    if any(n not in nodes for n in source):raise ValueError('Source bone missing from package')
    clips={c['name']:c for c in pkg['clips']}
    if any(a.name not in clips for a in actions):raise ValueError('Custom Action has no source clip: use source export')
    # Reject names that would collide with equipment or other custom bones.
    if any(n in arm.data.bones and n not in changed for n in names):raise ValueError('Source bone name collision')
    report={'passed':False,'version':'0.9.3','bones_before':len(arm.data.bones),'source_bones':len(names),'restored_ancestors':sorted(closure-set(source)),'actions':len(actions),'errors':[]}
    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f');work=args.resume_cache.resolve() if args.resume_cache else p/'_internal'/('hierarchy_'+stamp)
    if not work.is_relative_to(p/'_internal') or not work.name.startswith('hierarchy_'):raise ValueError('Cache must be a hierarchy directory inside package/_internal')
    work.mkdir(parents=True,exist_ok=True)
    # Legacy caches have no identity manifest: recompute every skin matrix and
    # compare the complete float32 payload before reusing even one file.
    report['cache']=str(work);report['verified_skin_cache']=0
    saved_action=arm.animation_data.action.name if arm.animation_data.action else None;saved_frame=bpy.context.scene.frame_current+bpy.context.scene.frame_subframe
    meshes=[ob for ob in bpy.data.objects if ob.type=='MESH' and any(m.type=='ARMATURE' and m.object==arm for m in ob.modifiers)]
    pc=PoseCache(arm,list(source.values()));sk=pkg['skeleton'] or [];sknames={b['name']:i for i,b in enumerate(sk)};refs=np.array([b['trs'] for b in sk]);parents=[b['parent'] for b in sk];face=FaceOverlay(pkg,p)
    invariants={a.name:invariant(a,changed) for a in actions};sampleframes={};mesh_checks={}
    # Cache actual old animation matrices, not a reset of previously processed root motion.
    for ai,action in enumerate(actions):
        clip=clips[action.name];frames=1+np.arange(clip['frames'])*clip['dt']*30
        # Eight samples per source interval reduce (not eliminate) interpolation error.
        dense=np.unique(np.concatenate([frames]+[frames[:-1]+(frames[1:]-frames[:-1])*fraction/8 for fraction in range(1,8)]));sampleframes[action.name]=dense
        old=pc.evaluate(action,dense);targets={}
        for name,bn in source.items():targets[name]=old[bn]@np.linalg.inv(old_rest[name])
        if closure-set(source):
            if sk:
                raw=np.fromfile(p/clip['file'],dtype='<f4').reshape(clip['frames'],len(clip['map']),10);local=np.broadcast_to(refs,(clip['frames'],len(sk),10)).copy()
                for ti,bi in enumerate(clip['map']):local[:,bi]=raw[:,ti]
                local=face.apply(clip,local,{'issues':[]});fk=fk_separate_scale(parents,local[:,:,:3],local[:,:,3:7],local[:,:,7:],DEFAULT_C);flver=mapped_fk(nodes,sknames,fk)
            for name in closure-set(source):
                # Restored connectors are never directly weighted. Interpolate source affine values.
                mats=flver[name]@np.linalg.inv(converted(nodes[name]['world'])) if sk else np.broadcast_to(np.eye(4),(len(frames),4,4))
                targets[name]=np.array([[np.interp(dense,frames,mats[:,i,j]) for j in range(4)] for i in range(4)]).transpose(2,0,1)
        payload={n:v.astype(np.float32) for n,v in targets.items()};cache=work/f'{ai}_skin.npz';reuse=False
        if cache.exists():
            try:
                cached=arrays(cache);reuse=cached.keys()==payload.keys() and all(np.array_equal(cached[n],v) for n,v in payload.items())
            except (OSError,ValueError,EOFError):pass
        if reuse:report['verified_skin_cache']+=1
        else:np.savez_compressed(cache,**payload)
        if ai in {0,len(actions)//2,len(actions)-1}:
            set_action(arm,action)
            for k in sorted({0,len(dense)//2,len(dense)-1}):
                frame(float(dense[k]));mesh_checks[(ai,k)]=vertices(meshes)
        if ai%25==0:print('HIERARCHY_CAPTURE',ai+1,len(actions),flush=True)
    if not args.no_backup:
        backup=p/'backups'/('hierarchy_'+stamp)/file.name;backup.parent.mkdir(parents=True);shutil.copy2(file,backup);report['backup']=str(backup)
    # Rename before rebuilding rest matrices so Blender updates vertex groups and data paths.
    for old in source.values():arm.data.bones[old].name='SCT_TMP_'+old
    for name,old in source.items():arm.data.bones['SCT_TMP_'+old].name=name
    bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT')
    for n in old_helpers:arm.data.edit_bones.remove(arm.data.edit_bones[n])
    for name in names:
        eb=arm.data.edit_bones.get(name) or arm.data.edit_bones.new(name);eb.parent=None;eb.use_connect=False
        m=Matrix(converted(nodes[name]['world']));loc,q,_=m.decompose();eb.head=loc;eb.tail=loc+q@Vector((0,.05,0));eb.matrix=Matrix.Translation(loc)@q.to_matrix().to_4x4()
        eb.length=.05;eb.use_deform=name in source;eb.inherit_scale='NONE'
    # Prefer anatomical continuation rather than short twist/corrective branches.
    children={n:[c for c in names if nodes[c].get('_parent_name')==n] for n in names};chosen={}
    special={'Master':'Root','Root':'Spine','Pelvis':'Spine','Spine':'Spine1','Spine1':'Spine2','Spine2':'Neck','Neck':'Head'}
    for side in ('L','R'):
        special.update({side+'_Clavicle':side+'_UpperArm',side+'_UpperArm':side+'_Forearm',side+'_Forearm':side+'_Hand',side+'_Thigh':side+'_Calf',side+'_Calf':side+'_Foot',side+'_Foot':side+'_Toe0',side+'_Hand':side+'_Finger2'})
    for name in names:
        eb=arm.data.edit_bones[name];candidate=special.get(name);valid=[c for c in children[name] if (arm.data.edit_bones[c].head-eb.head).length>.004]
        if candidate not in names:candidate=None
        if candidate is None and valid:candidate=min(valid,key=lambda c:('twist' in c.lower() or 'dummy' in c.lower(),(arm.data.edit_bones[c].head-eb.head).length))
        if candidate and (arm.data.edit_bones[candidate].head-eb.head).length>.004:eb.tail=arm.data.edit_bones[candidate].head;chosen[name]=candidate
        else:eb.length=.022 if depth(name)>6 else .065
    for name in names:
        eb=arm.data.edit_bones[name];par=nodes[name].get('_parent_name');eb.parent=arm.data.edit_bones.get(par) if par else None
    bpy.ops.object.mode_set(mode='OBJECT')
    rest={n:np.array(arm.data.bones[n].matrix_local) for n in names};helpers=set();max_trs=0.0
    for name in names:
        bone=arm.data.bones[name];bone['source_name']=name;bone['source_parent_name']=nodes[name].get('_parent_name') or '';bone['sct_hierarchy_bone']=True;bone.hide=False;arm.pose.bones[name].rotation_mode='QUATERNION'
    # Convert target armature-space matrices through Blender's actual inherit-scale rules.
    for ai,action in enumerate(actions):
        skin=arrays(work/f'{ai}_skin.npz');basis={};targets={n:skin[n]@rest[n] for n in names}
        for name in names:
            bone=arm.data.bones[name];par=nodes[name].get('_parent_name')
            values=local_basis(targets[name],rest[name],targets[par] if par else None,rest[par] if par else None)
            # Check batch math against Blender's real implementation on every
            # bone of every action; keep the native fallback for edge cases.
            max_native=0.0
            for k in sorted({0,len(values)//2,len(values)-1}):
                kw={'parent_matrix':Matrix(targets[par][k]),'parent_matrix_local':bone.parent.matrix_local} if par else {}
                native=np.array(bone.convert_local_to_pose(Matrix(targets[name][k]),bone.matrix_local,invert=True,**kw))
                max_native=max(max_native,float(np.max(abs(native-values[k]))))
            if max_native>2e-5:
                rows=[]
                for k,target in enumerate(targets[name]):
                    kw={'parent_matrix':Matrix(targets[par][k]),'parent_matrix_local':bone.parent.matrix_local} if par else {}
                    rows.append(np.array(bone.convert_local_to_pose(Matrix(target),bone.matrix_local,invert=True,**kw)))
                values=np.asarray(rows)
            error=trs_residual(values);max_trs=max(max_trs,error)
            if error>2e-6:helpers.add(name)
            basis[name]=values
        np.savez_compressed(work/f'{ai}_basis.npz',**{n:v.astype(np.float32) for n,v in basis.items()})
        if ai%25==0:print('HIERARCHY_LOCAL',ai+1,len(actions),'helpers',len(helpers),flush=True)
    # Most humanoid bones become a direct single-bone hierarchy. Exact affine fallback
    # is local to exceptional bones, never a flat duplicate skeleton.
    bpy.ops.object.mode_set(mode='EDIT')
    for name in sorted(helpers):
        eb=arm.data.edit_bones[name];par=eb.parent;helper=arm.data.edit_bones.new('AFF::'+name);helper.head=eb.head.copy();helper.tail=eb.tail.copy();helper.roll=eb.roll;helper.length=.025;helper.parent=par;helper.use_deform=False;helper.inherit_scale='NONE';eb.parent=helper;eb.inherit_scale='FULL'
    for name in names:
        eb=arm.data.edit_bones[name]
        # Do not enable connected translation locks: source clips may translate joints.
        eb.use_connect=False
    bpy.ops.object.mode_set(mode='OBJECT')
    helper_collection=arm.data.collections.get('SCT · Affine helpers') or arm.data.collections.new('SCT · Affine helpers');helper_collection.is_visible=True
    deform=arm.data.collections.get('SCT · Deform and sockets') or arm.data.collections.new('SCT · Deform and sockets')
    for name in names:
        deform.assign(arm.data.bones[name])
        if name in helpers:
            b=arm.data.bones['AFF::'+name];b.hide=False;b['sct_affine_helper']=True;helper_collection.assign(b);arm.pose.bones[b.name].rotation_mode='QUATERNION'
    max_error=0.;checks=0
    for ai,action in enumerate(actions):
        # Old names may have been updated by Blender rename; handle both identities.
        for collection,fc in list(curves(action)):
            if set(path_bones(fc.data_path)) & (changed|set(names)):collection.remove(fc)
        frames=sampleframes[action.name];data=arrays(work/f'{ai}_basis.npz')
        for name in names:
            if name in helpers:
                outer,inner=factor_affine(data[name]);write(action,'AFF::'+name,frames,decomp(outer)[0]);write(action,name,frames,decomp(inner)[0])
            else:write(action,name,frames,decomp(data[name])[0])
        set_action(arm,action)
        if ai%25==0:print('HIERARCHY_BAKE',ai+1,len(actions),'helpers',len(helpers),flush=True)
    arm['sct_hierarchy_version']='0.9.3';arm.data.display_type='OCTAHEDRAL';arm.show_in_front=True
    if saved_action:set_action(arm,bpy.data.actions[saved_action])
    frame(saved_frame)
    staged=p/(file.stem+'.hierarchy_pending.blend');bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.save_as_mainfile(filepath=str(staged),compress=True)
    actions.clear();meshes.clear();bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.open_mainfile(filepath=str(staged));arm=bpy.data.objects[pkg['character']+'_Armature']
    vertex_error=0.;vertex_checks=0;invariant_ok=True;rest_inverse={n:np.linalg.inv(rest[n]) for n in names}
    for ai,action in enumerate(list(bpy.data.actions)):
        invariant_ok &= invariants[action.name]==invariant(action,set(names)|{'AFF::'+n for n in helpers})
        set_action(arm,action);skin=arrays(work/f'{ai}_skin.npz');frames=sampleframes[action.name]
        if ai%25==0:print('HIERARCHY_VERIFY',ai+1,report['actions'],flush=True)
        for k in sorted(set(range(0,len(frames),8))|set(np.linspace(0,len(frames)-1,9,dtype=int))|{0,len(frames)//2,len(frames)-1}):
            frame(float(frames[k]))
            for name in names:
                expected=skin[name][k];actual=np.array(arm.pose.bones[name].matrix)@rest_inverse[name];err=float(np.max(np.abs(actual-expected)));max_error=max(max_error,err);checks+=1
            if (ai,k) in mesh_checks:
                actual=vertices([bpy.data.objects[n] for n in mesh_checks[(ai,k)]])
                for n,before in mesh_checks[(ai,k)].items():
                    if n not in actual:continue
                    error=float(np.max(np.linalg.norm(before-actual[n],axis=1)))
                    if error>vertex_error:vertex_error=error;report['worst_vertex_sample']={'action':action.name,'frame':float(frames[k]),'mesh':n}
                    vertex_checks+=len(before)
    if max_error>5e-4:report['errors'].append('Skin matrix error exceeds 5e-4')
    if vertex_error>5e-4:report['errors'].append('Evaluated vertex error exceeds 0.5mm')
    if not invariant_ok:report['errors'].append('Root/equipment/mask channels changed')
    for name in names:
        parent=arm.data.bones[name].parent
        if parent and parent.get('sct_affine_helper'):parent=parent.parent
        if (parent.name if parent else None)!=nodes[name].get('_parent_name'):report['errors'].append('Parent mismatch: '+name)
    report.update(bones_after=len(arm.data.bones),affine_helpers=len(helpers),helper_bones=sorted(helpers),matrix_checks=checks,max_skin_matrix_error=max_error,vertex_checks=vertex_checks,max_vertex_error_m=vertex_error,root_equipment_masks_unchanged=bool(invariant_ok),max_single_trs_residual=max_trs,hierarchy={n:nodes[n].get('_parent_name') for n in names},scope='all actions all native sample frames plus 9 evenly spaced bake samples; first/middle/last actions visible mesh vertices; 8 samples per source interval; fractional interpolation approximate',passed=not report['errors'])
    if report['passed']:os.replace(staged,file)
    (p/'hierarchy_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('HIERARCHY_DONE',report['passed'],'bones',report['bones_before'],'->',report['bones_after'],'helpers',len(helpers),'matrix',max_error,'vertex',vertex_error,flush=True)
    if not report['passed']:raise RuntimeError(report['errors'])
    # Only this run's generated cache is removed; the original backup is retained.
    if work.is_relative_to(p/'_internal') and work.name.startswith('hierarchy_'):shutil.rmtree(work)

if __name__=='__main__':main()
