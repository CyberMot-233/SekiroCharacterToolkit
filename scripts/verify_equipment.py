"""Independent Blender validation of the final verified Sekiro weapons.

Usage:
  blender --background --python validate_weapons.py -- <final.blend>
  blender --background --python validate_weapons.py -- <final.blend> --output validation.json

Does not import bake_verified, modify files in the scene, or save the scene.
Only event_states and internal_fk_verified are reused. Tests target the final
file explicitly supplied by the caller; no fallback to an original/test file.
A failed matrix, visibility, binding, or sampled vertex check exits nonzero.
"""
import argparse
import json
import math
from pathlib import Path
import re
import sys
import traceback

import bpy
import numpy as np

SCRIPT = Path(__file__).resolve().parent
HERE = Path(sys.argv[sys.argv.index('--')+1]).parent/'equipment'
sys.path.insert(0,str(SCRIPT))
from event_states import EventStateDatabase, normalize_action_key
from internal_fk_verified import sample_internal_fk

C = np.array(((1,0,0,0),(0,0,-1,0),(0,1,0,0),(0,0,0,1)),dtype=np.float64)
CI = C.T
PARTS = [('WP_A_0300','R',0),('WP_A_0300_1','R',1),
         ('WP_A_0310','MB',0),('WP_A_0310_1','MB',1),
         ('WP_A_0730','L',0),('WP_A_0730_1','L',1)]
TIMES = {'a106_316210':[0,.1,.2,1.839,2.426,2.7],
         'a073_400000':[0,.1,.5,1,2.5333,3.9]}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def convert_row(values):
    return C @ np.asarray(values,dtype=np.float64).reshape(4,4).T @ CI


def full_id(name):
    key = normalize_action_key(name)
    ns,body = key[1:].split('_')
    return int(ns)*1000000+int(body)


def matrix(value):
    return np.asarray(value,dtype=np.float64)


def choose_internal(motion, tae_id):
    """Independent 400+i TAE resolution, preserving its full IDs."""
    if not motion:
        return None,None,[]
    animations = {full_id(a['name']):a for a in motion.get('animations',[])}
    entries = {int(a['id']):a for cat in motion.get('taes',[]) for a in cat['animations']}
    key = tae_id if tae_id in entries or tae_id in animations else 999000000
    seen = []
    while key in entries:
        if key in seen:
            raise ValueError('Internal TAE reference cycle')
        seen.append(key)
        header = entries[key]['header']
        if header['type'] == 'ImportOtherAnim' and int(header.get('ImportFromAnimID',-1)) >= 0:
            target = int(header['ImportFromAnimID'])
            if target in entries or target in animations:
                key = target
                continue
        elif header['type'] == 'Standard' and header.get('ImportsHKX') and int(header.get('ImportHKXSourceAnimID',-1)) >= 0:
            key = int(header['ImportHKXSourceAnimID'])
        break
    return animations.get(key),key,seen


def mesh_weights(data,mesh):
    indices = np.asarray(mesh['boneIndices'],dtype=np.int64).copy()
    weights = np.asarray(mesh['weights'],dtype=np.float64).copy()
    weights[np.all(weights == 0,axis=1),0] = 1
    if not mesh['usesBoneIndices']:
        indices[:,0] = mesh['normalW']
        weights[:,0] = 1
    if int(data['version']) <= 0x2000D:
        palette = np.asarray(mesh['info']['BoneIndices'],dtype=np.int64)
        invalid = (indices<0)|(indices>=len(palette))
        indices = palette[np.clip(indices,0,len(palette)-1)]
        weights[invalid] = 0
    invalid = (indices<0)|(indices>=len(data['nodes']))
    weights[invalid] = 0
    indices[invalid] = 0
    sums = weights.sum(axis=1)
    if np.any(sums <= 0):
        raise ValueError('Source mesh contains vertices without valid weights')
    return indices,weights/sums[:,None]


def sampled_indices(mesh,indices,weights,maximum):
    pos = np.asarray(mesh['pos'],dtype=np.float64)
    result = set(np.linspace(0,len(pos)-1,min(maximum,len(pos)),dtype=int).tolist())
    # Include extrema, multiweight vertices and a representative for every bone.
    result.update(np.argmin(pos,axis=0).tolist())
    result.update(np.argmax(pos,axis=0).tolist())
    multi = np.flatnonzero((weights>0).sum(axis=1)>1)
    if len(multi):
        result.update(multi[np.linspace(0,len(multi)-1,min(16,len(multi)),dtype=int)].tolist())
    for bone in np.unique(indices[weights>0]):
        candidates = np.flatnonzero(np.any((indices==bone)&(weights>0),axis=1))
        result.add(int(candidates[0]))
    return np.array(sorted(result),dtype=int)


def find_action(key):
    matches=[]
    for action in bpy.data.actions:
        try:
            if normalize_action_key(action.name)==key:
                matches.append(action)
        except ValueError:
            pass
    if len(matches)!=1:
        raise ValueError(f'Expected one action for {key}, found {[a.name for a in matches]}')
    return matches[0]


def set_action(arm,action):
    arm.animation_data_create()
    arm.animation_data.action=action
    if hasattr(action,'slots') and action.slots:
        arm.animation_data.action_slot=action.slots[0]
    for pb in arm.pose.bones:
        # Clear the previous clip's unkeyed channels without changing rest data.
        pb.location=(0,0,0)
        pb.rotation_quaternion=(1,0,0,0)
        pb.scale=(1,1,1)
    bpy.context.view_layer.update()


def expected_root(dummy_id,visible,dummies,nodes,refs,arm_eval,rest_inv):
    if dummy_id not in dummies:
        raw=np.eye(4)
    else:
        d=dummies[dummy_id]
        raw=np.eye(4)
        p=int(d['parent'])
        if p>=0:
            name=nodes[p]['name']
            if name not in arm_eval.pose.bones:
                raise ValueError(f'Missing character parent bone {name}')
            raw=matrix(arm_eval.pose.bones[name].matrix)@rest_inv[name]@refs[p]
        raw=raw@convert_row(d['frame'])
        a=int(d['attach'])
        if a>=0 and d['follow']:
            name=nodes[a]['name']
            if name not in arm_eval.pose.bones:
                raise ValueError(f'Missing character attach bone {name}')
            raw=matrix(arm_eval.pose.bones[name].matrix)@rest_inv[name]@raw
    result=raw.copy()
    if not visible:
        result[:3,:3]=0
    return result


def main(args):
    global PARTS
    blend=Path(args.blend).resolve()
    if not blend.is_file():
        raise FileNotFoundError(f'Final blend does not exist: {blend}')
    if not getattr(args,'already_open',False):bpy.ops.wm.open_mainfile(filepath=str(blend))
    arm=bpy.data.objects.get('c0000_Armature')
    if arm is None or arm.type!='ARMATURE':
        raise ValueError('Wolf_Armature missing')
    scene=bpy.context.scene
    char=read_json(HERE/'c0000.json')
    import event_states
    profile=read_json(HERE/'profile.json');event_states.SLOT_EQUIP_IDS=profile['slots'];PARTS=[tuple(t) for t in profile['tags']]
    names={b.get('source_name'):b.name for b in arm.data.bones if b.get('source_name')}
    nodes=char['nodes']
    for n in nodes:n['name']=names.get(n['name'],n['name'])
    refs=[convert_row(n['world']) for n in nodes]
    rest_inv={b.name:np.linalg.inv(matrix(b.matrix_local)) for b in arm.data.bones}
    dummies={}
    for d in char['dummies']:
        dummies.setdefault(int(d['id']),d)
    db=EventStateDatabase(HERE)
    assets=[]
    for tag,slot,index in PARTS:
        data=read_json(HERE/(tag+'.json'))
        mp=HERE/(tag+'.motion.json')
        motion=read_json(mp) if mp.exists() else None
        meshinfo=[]
        used=set()
        for mi,mesh in enumerate(data['meshes']):
            if int(mesh['info']['Dynamic']) not in (0,1):
                raise ValueError(f'Unknown FLVER Dynamic mode: {tag} mesh{mi}')
            bi,wt=mesh_weights(data,mesh)
            for i in np.unique(bi[wt>0]):
                i=int(i)
                while i>=0 and i not in used:
                    used.add(i)
                    i=int(data['nodes'][i]['parent'])
            ids=sampled_indices(mesh,bi,wt,args.vertices)
            obj=bpy.data.objects.get(f'{tag}_DSAS_{mi}')
            if obj is None:
                raise ValueError(f'Missing rebuilt mesh {tag}_DSAS_{mi}')
            if len(obj.data.vertices)!=len(mesh['pos']):
                raise ValueError(f'Vertex count differs in {obj.name}')
            meshinfo.append((mesh,bi,wt,ids,obj))
        assets.append({'tag':tag,'slot':slot,'index':index,'root':f'DSAS_{slot}{index}',
                       'data':data,'motion':motion,'meshinfo':meshinfo,'used':sorted(used),
                       'refinv':[np.linalg.inv(convert_row(n['world'])) for n in data['nodes']]})
    failures=[]
    report={'blend':str(blend),'passed':False,
            'tolerances':{'root_matrix_max_abs':args.matrix_tolerance,
                          'root_translation_m':args.root_tolerance,
                          'vertex_world_distance_m':args.vertex_tolerance,
                          'visibility_scale':1e-5},
            'reference':'Raw c0000 MonoGame d.frame + actual evaluated source pose; independent original mesh skinning',
            'samples':[],'failures':failures}
    worst_matrix=worst_root=worst_vertex=0.0
    vertices_checked=0
    times_by_action=TIMES
    if getattr(args,'all_actions',False):
        times_by_action={}
        for action in bpy.data.actions:
            duration=float(action['source_duration']);times={0.,duration/2,duration}
            res=db.resolve_action(action.name,key_kind='hkx')
            for event in db.animations.get(res.get('source_tae_key'),{}).get('events',[]):
                if event['type'] in (32,710,715):
                    for t in (event['start'],event['end']):
                        for delta in (-.0001,.0001):
                            if 0<=t+delta<=duration:times.add(t+delta)
            times_by_action[action.name]=sorted(times)
    for key,times in times_by_action.items():
        action=bpy.data.actions.get(key) or find_action(key)
        set_action(arm,action)
        resolution=db.resolve_action(action.name,key_kind='hkx')
        tae_id=full_id(resolution['tae_key'] or key)
        for seconds in times:
            frame=1+seconds*30
            whole=math.floor(frame)
            scene.frame_set(whole,subframe=frame-whole)
            bpy.context.view_layer.update()
            depsgraph=bpy.context.evaluated_depsgraph_get()
            arm_eval=arm.evaluated_get(depsgraph)
            arm_world=matrix(arm_eval.matrix_world)
            state=db.get_state(action.name,seconds,key_kind='hkx')
            sample={'action':action.name,'time':seconds,'frame':frame,'parts':[]}
            for asset in assets:
                tag,slot,index,rootname=asset['tag'],asset['slot'],asset['index'],asset['root']
                entry=state['slots'][slot][index]
                visible=bool(entry['visible'] and entry['dummy'] in dummies)
                root=arm_eval.pose.bones.get(rootname)
                if root is None:
                    raise ValueError(f'Missing root {rootname}')
                expected=expected_root(entry['dummy'],visible,dummies,nodes,refs,arm_eval,rest_inv)
                actual=matrix(root.matrix)
                me=float(np.max(np.abs(actual-expected)))
                pe=float(np.linalg.norm(actual[:3,3]-expected[:3,3]))
                root_scale=np.linalg.norm(actual[:3,:3],axis=0)
                expected_scale=np.linalg.norm(expected[:3,:3],axis=0)
                scale_error=float(np.max(np.abs(root_scale-expected_scale)))
                root_bone=arm.data.bones[rootname]
                affine_name=rootname+'__AFFINE'
                has_affine_parent=root_bone.parent is not None and root_bone.parent.name==affine_name
                visibility_scale=(np.asarray(arm_eval.pose.bones[affine_name].scale,dtype=float)
                                  if has_affine_parent else np.asarray(root.scale,dtype=float))
                if visible:
                    worst_matrix=max(worst_matrix,me)
                    worst_root=max(worst_root,pe)
                part={'tag':tag,'root':rootname,'dummy':entry['dummy'],'visible':visible,
                      'root_matrix_max_abs':me,'root_translation_error_m':pe,
                      'root_scale':root_scale.tolist(),'expected_root_scale':expected_scale.tolist(),
                      'visibility_control_scale':visibility_scale.tolist(),
                      'affine_parent':affine_name if has_affine_parent else None,
                      'root_scale_error':scale_error,
                      'expected_root_matrix':expected.tolist(),'actual_root_matrix':actual.tolist(),
                      'mesh_checks':[]}
                if visible and (me>args.matrix_tolerance or pe>args.root_tolerance):
                    failures.append({'action':action.name,'time':seconds,'part':tag,'check':'root_matrix','max_abs':me,'translation_m':pe})
                is_collapsed=bool(np.max(np.abs(root_scale))<=1e-5)
                if is_collapsed == visible:
                    failures.append({'action':action.name,'time':seconds,'part':tag,'check':'visibility_scale','actual_collapsed':is_collapsed,'expected_visible':visible})
                if root_bone.parent is not None and not has_affine_parent:
                    failures.append({'part':tag,'check':'root_has_unexpected_parent','parent':root_bone.parent.name})
                if has_affine_parent and arm.data.bones[affine_name].parent is not None:
                    failures.append({'part':tag,'check':'affine_helper_has_parent'})
                for i in asset['used']:
                    name=rootname+'__'+asset['data']['nodes'][i]['name']
                    bone=arm.data.bones.get(name)
                    if bone is None or bone.parent is None or bone.parent.name!=rootname:
                        failures.append({'part':tag,'check':'internal_bone_parent','bone':name})
                internal,internal_id,chain=choose_internal(asset['motion'],tae_id)
                fk=sample_internal_fk(asset['motion'],internal,[seconds],asset['data']['nodes'],asset['used'])
                part['internal_hkx_id']=internal_id
                part['internal_ref_chain']=chain
                for mi,(mesh,bi,wt,ids,obj) in enumerate(asset['meshinfo']):
                    points=np.asarray(mesh['pos'],dtype=float)[ids]
                    points_b=points@C[:3,:3].T
                    h=np.column_stack((points_b,np.ones(len(ids))))
                    if int(mesh['info']['Dynamic'])==0:
                        # Static FLVER vertices start bone-local; reproduce the
                        # independently weighted reference-to-model bind first.
                        bound=np.zeros_like(h)
                        for j in range(4):
                            for bone in np.unique(bi[ids,j]):
                                bone=int(bone);mask=(bi[ids,j]==bone)&(wt[ids,j]>0)
                                ref=convert_row(asset['data']['nodes'][bone]['world'])
                                bound[mask]+=(h[mask]@ref.T)*wt[ids[mask],j,None]
                        h=bound
                    deformed=np.zeros((len(ids),4),dtype=float)
                    for j in range(4):
                        for bone in np.unique(bi[ids,j]):
                            bone=int(bone)
                            mask=(bi[ids,j]==bone)&(wt[ids,j]>0)
                            if not np.any(mask):
                                continue
                            skin=fk[bone][0]@asset['refinv'][bone]
                            deformed[mask]+=(h[mask]@skin.T)*wt[ids[mask],j,None]
                    expected_world=deformed@(arm_world@expected).T
                    evaluated=obj.evaluated_get(depsgraph)
                    out=evaluated.to_mesh()
                    try:
                        if len(out.vertices)!=len(mesh['pos']):
                            raise ValueError(f'Evaluated vertex count differs for {obj.name}')
                        actual_local=np.array([out.vertices[int(i)].co[:] for i in ids])
                        actual_world=np.column_stack((actual_local,np.ones(len(ids))))@matrix(evaluated.matrix_world).T
                    finally:
                        evaluated.to_mesh_clear()
                    errors=np.linalg.norm(actual_world[:,:3]-expected_world[:,:3],axis=1)
                    worst=int(np.argmax(errors))
                    max_error=float(errors[worst])
                    if visible:
                        worst_vertex=max(worst_vertex,max_error)
                    vertices_checked+=len(ids)
                    detail={'mesh':obj.name,'vertices_checked':len(ids),'max_error_m':max_error,
                            'rms_error_m':float(np.sqrt(np.mean(errors*errors))),
                            'worst_vertex':int(ids[worst]),
                            'expected_world':expected_world[worst,:3].tolist(),
                            'actual_world':actual_world[worst,:3].tolist()}
                    part['mesh_checks'].append(detail)
                    if visible and max_error>args.vertex_tolerance:
                        failures.append({'action':action.name,'time':seconds,'part':tag,
                                         'check':'evaluated_vertex','mesh':obj.name,
                                         'vertex':int(ids[worst]),'error_m':max_error})
                sample['parts'].append(part)
            report['samples'].append(sample)
            print('VALIDATED_SAMPLE',action.name,seconds,'failures',len(failures),flush=True)
    report['summary']={'sample_times':len(report['samples']),
                       'root_checks':len(report['samples'])*len(PARTS),
                       'sampled_vertices_checked':vertices_checked,
                       'max_root_matrix_abs':worst_matrix,'max_root_translation_m':worst_root,
                       'max_vertex_distance_m':worst_vertex,'failure_count':len(failures)}
    report['passed']=not failures
    Path(args.output).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],**report['summary'],'report':args.output},indent=2),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('blend')
    parser.add_argument('--output',default=str(HERE/'validation.json'))
    parser.add_argument('--vertices',type=int,default=96)
    parser.add_argument('--all-actions',action='store_true')
    parser.add_argument('--matrix-tolerance',type=float,default=.003)
    parser.add_argument('--root-tolerance',type=float,default=.002)
    parser.add_argument('--vertex-tolerance',type=float,default=.003)
    options=parser.parse_args(argv)
    try:
        code=main(options)
    except Exception as exc:
        report={'passed':False,'blend':options.blend,'error':str(exc),'traceback':traceback.format_exc()}
        Path(options.output).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(report['traceback'],file=sys.stderr)
        code=2
    if code:
        # Blender can swallow Python SystemExit unless --python-exit-code is
        # supplied; explicit process exit guarantees the requested CLI contract.
        import os
        sys.stdout.flush();sys.stderr.flush()
        os._exit(code)
