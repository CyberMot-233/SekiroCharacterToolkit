"""Bake selected source clips directly onto an existing SCT Blender rig."""
import argparse, gc, json, math, os, sys
from pathlib import Path
import bpy, numpy as np
from mathutils import Matrix
sys.path.insert(0,str(Path(__file__).resolve().parent))
from cs2_common import read,save
from direct_author import FinalRig,SourceMotion,converted
from restore_hierarchy import write,set_action,frame,decomp
from rig_cleanup import action_digest,curves
from face_overlay import FaceOverlay
from model_masks import ModelMasks

def geometry_digest():
 import hashlib
 h=hashlib.sha256()
 for ob in sorted(bpy.data.objects,key=lambda o:o.name):
  if ob.type!='MESH':continue
  # World transforms include the currently evaluated parent animation.
  # Protect authored local placement and parent binding independently of pose.
  h.update(ob.name.encode());h.update(np.array(ob.matrix_basis).tobytes());h.update(np.array(ob.matrix_parent_inverse).tobytes())
  h.update(repr((ob.parent.name if ob.parent else None,ob.parent_type,ob.parent_bone)).encode())
  for prop,seq,width,dtype in [('co',ob.data.vertices,3,np.float32),('vertices',ob.data.edges,2,np.int32),('vertex_index',ob.data.loops,1,np.int32)]:
   a=np.empty(len(seq)*width,dtype);seq.foreach_get(prop,a);h.update(a.tobytes())
  h.update(repr([(m.name if m else None) for m in ob.data.materials]).encode())
  h.update(repr([(g.name,g.index) for g in ob.vertex_groups]).encode())
  for v in ob.data.vertices:h.update(repr([(g.group,g.weight) for g in v.groups]).encode())
 return h.hexdigest()

def attach(arm,nodes):
 r=FinalRig.__new__(FinalRig);r.arm=arm;r.nodes=nodes;r.hierarchy=bool(arm.get('sct_hierarchy_version'));r.actions=list(bpy.data.actions);r.action_count=0
 r.max_error=0.;r.checks=0;r.native_fallbacks=0;r.max_single_trs_residual=0.;r.cleanup=None
 if not r.hierarchy:raise ValueError('请先用工具修复旧版平铺骨架，再追加动作；未修改原工程')
 r.names=[n for n in nodes if n in arm.data.bones and arm.data.bones[n].get('sct_hierarchy_bone')]
 if not r.names:raise ValueError('不是可识别的 SCT 角色骨架')
 r.rest={n:np.array(arm.data.bones[n].matrix_local) for n in r.names}
 r.source={n:n for n in r.names if arm.data.bones[n].use_deform};r.original_names=set(r.source)
 # Direct authoring changes bone tails to point along the anatomy; that changes
 # final rest rotation. SourceMotion must retain the original flat-pair rest.
 temporary=bpy.data.armatures.new('SCT_APPEND_REFERENCE');obj=bpy.data.objects.new('SCT_APPEND_REFERENCE',temporary);bpy.context.scene.collection.objects.link(obj);bpy.context.view_layer.objects.active=obj;obj.select_set(True)
 bpy.ops.object.mode_set(mode='EDIT')
 for n in r.names:
  loc,q,_=Matrix(converted(nodes[n]['world'])).decompose();eb=temporary.edit_bones.new(n);eb.head=(0,0,0);eb.tail=(0,.06,0);eb.matrix=Matrix.Translation(loc)@q.to_matrix().to_4x4()
 bpy.ops.object.mode_set(mode='OBJECT');r.original_rest={n:np.array(temporary.bones[n].matrix_local) for n in r.names};bpy.data.objects.remove(obj,do_unlink=True);bpy.data.armatures.remove(temporary);bpy.context.view_layer.objects.active=arm
 r.rig_names={n:(None,n) for n in r.names};r.helpers={n for n in r.names if 'AFF::'+n in arm.data.bones}
 for n in r.names:
  bone=arm.data.bones['AFF::'+n if n in r.helpers else n];parent=bone.parent.name if bone.parent else None
  if parent!=nodes[n].get('_parent_name'):raise ValueError('已有骨架父级被修改：'+n)
  loc,q,_=Matrix(converted(nodes[n]['world'])).decompose();expected=np.array(Matrix.Translation(loc)@q.to_matrix().to_4x4())
  if np.max(abs(r.rest[n][:3,3]-expected[:3,3]))>2e-5:raise ValueError('已有骨架绑定位置被修改或角色不匹配：'+n)
 return r

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--package',type=Path,required=True);ap.add_argument('--blend',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--clips',type=Path,required=True);ap.add_argument('--root-options',type=Path);ap.add_argument('--report',type=Path,required=True);a=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
 p=a.package;pkg=read(p/'package.json');wanted=set(read(a.clips));clips={c['name']:c for c in pkg['clips']}
 if not wanted or wanted-clips.keys():raise ValueError('所选动作不存在')
 bpy.ops.wm.open_mainfile(filepath=str(a.blend));arm=bpy.data.objects.get(pkg['character']+'_Armature')
 if arm is None or arm.type!='ARMATURE':raise ValueError('Blender 工程角色与提取包不一致')
 if arm.constraints or any(b.constraints for b in arm.pose.bones):raise ValueError('自定义约束骨架需先烘焙，未改写原工程')
 arm.animation_data_create();active=arm.animation_data.action.name if arm.animation_data.action else None
 use_nla=arm.animation_data.use_nla;arm.animation_data.use_nla=False
 old_actions={x.name:action_digest(x) for x in bpy.data.actions if x.name not in wanted};geo=geometry_digest();old_names=set(bpy.data.actions.keys());old_frame=bpy.context.scene.frame_current
 nodes={}
 for f in pkg['models']:
  model=read(p/f)
  for n in model['nodes']:nodes.setdefault(n['name'],{**n,'_parent_name':model['nodes'][n['parent']]['name'] if n['parent']>=0 else None})
 rig=attach(arm,nodes);old_helpers=set(rig.helpers);faces=FaceOverlay(pkg,p);masks=ModelMasks(pkg,p,arm)
 masks.used={int(k.rsplit('_',1)[1]) for k in arm.keys() if k.startswith('sct_mask_')}
 # Record old playback before any newly required helper is inserted.
 samples={}
 for name in old_actions:
  act=bpy.data.actions[name];samples[name]=[]
  for f in sorted(set([float(act.frame_range[0]),float(sum(act.frame_range)/2),float(act.frame_range[1])])):
   set_action(arm,act);frame(f);samples[name].append((f,{n:np.array(arm.pose.bones[n].matrix) for n in rig.names}))
 equipment=None
 if (p/'equipment/profile.json').exists():
  from bake_equipment import prepare
  equipment,_=prepare(p,arm,rig.rig_names,None,direct=True,existing=True)
 report=dict(passed=False,added=sorted(wanted-old_names),replaced=sorted(wanted&old_names),actions=[],issues=[])
 options=read(a.root_options) if a.root_options else None
 for name in sorted(wanted):
  clip=clips[name];old=bpy.data.actions.get(name);axes=json.loads(old.get('sct_root_motion_axes','[]')) if old else []
  if options is not None:axes=list(options['axes']) if name in options['actions'] else []
  if set(axes)-set('XYZ'):raise ValueError('Invalid root axes')
  action=bpy.data.actions.new(name+'__append');action.use_fake_user=True
  # Source-based event/equipment resolution requires the exact action name.
  if old:old.name=name+'__backup_pending'
  action.name=name;action['source_duration']=clip['duration'];action['source_fps']=1/clip['dt']
  masks.bake(action,clip);motion=SourceMotion(p,pkg,clip,nodes,rig.original_rest,rig.original_names,faces,report);dense=rig.bake(action,motion)
  rm=np.asarray(clip['rootMotion']['samples']);values=np.zeros((len(rm),10));values[:,:3]=rm[:,1:4];values[:,3:7]=rm[:,4:8];values[:,7:]=1
  for axis in axes:values[:,'XYZ'.index(axis)]=rm[0,1+'XYZ'.index(axis)]
  if axes:action['sct_root_motion_axes']=json.dumps(axes);action['sct_root_motion_anchor']=json.dumps(rm[0,1:4].tolist());action['sct_root_motion_source']=name
  write(action,None,1+rm[:,0]*30,values)
  if equipment:equipment(action,motion.skin)
  error=rig.verify(action,motion,dense);report['actions'].append(dict(name=name,error=error,frames=clip['frames']))
  if old:
   old.user_remap(action)
   if old in rig.actions:rig.actions.remove(old)
   bpy.data.actions.remove(old,do_unlink=True)
  print('BLEND_APPEND',name,'matrix_error',error,flush=True);del motion;gc.collect()
 if report['issues'] or equipment and equipment.report['issues']:raise ValueError('追加动作源验证失败')
 helpers=rig.helpers-old_helpers
 # Without new helper requirements, every untouched Action must be byte-equivalent.
 if not helpers and any(action_digest(bpy.data.actions[n])!=h for n,h in old_actions.items()):raise ValueError('未选择动作曲线被修改')
 expected={n:action_digest(act) for n,act in bpy.data.actions.items()}
 if geometry_digest()!=geo:raise ValueError('模型几何或材质引用被修改')
 if active and active in bpy.data.actions:set_action(arm,bpy.data.actions[active])
 else:arm.animation_data.action=None
 arm.animation_data.use_nla=use_nla
 bpy.context.scene.frame_set(old_frame);bpy.context.preferences.filepaths.save_version=0
 arm_name=arm.name;bpy.ops.wm.save_as_mainfile(filepath=str(a.output),compress=True);bpy.ops.wm.open_mainfile(filepath=str(a.output));arm=bpy.data.objects[arm_name]
 if geometry_digest()!=geo:raise ValueError('重开后模型几何不一致')
 if expected!={n:action_digest(act) for n,act in bpy.data.actions.items()}:raise ValueError('动作保存回读不一致')
 arm.animation_data.use_nla=False;worst=0.
 for name,rows in samples.items():
  set_action(arm,bpy.data.actions[name])
  for f,pose in rows:
   frame(f)
   for n,m in pose.items():worst=max(worst,float(np.max(abs(np.array(arm.pose.bones[n].matrix)-m))))
 if worst>5e-4:raise ValueError('未选择动作姿态发生变化')
 report.update(passed=True,total_actions=len(bpy.data.actions),geometry_unchanged=True,other_actions_curves_unchanged=not helpers,new_helpers=sorted(helpers),other_action_pose_error=worst,saved_actions_verified=True)
 save(a.report,report)
if __name__=='__main__':main()
