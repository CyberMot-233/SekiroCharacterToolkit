"""Reopen saved file and compare stored action curves against original HKX FK."""
import bpy,sys,json,math
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).parent))
from internal_fk_verified import fk_separate_scale,DEFAULT_C
p=Path(sys.argv[sys.argv.index('--')+1]);pkg=json.loads((p/'package.json').read_text('utf-8-sig'))
if '--already-open' not in sys.argv:bpy.ops.wm.open_mainfile(filepath=str(p/(pkg['character']+'.blend')))
arm=bpy.data.objects[pkg['character']+'_Armature'];sc=bpy.context.scene;C=DEFAULT_C;CI=np.linalg.inv(C);nodes={}
for rel in pkg['models']:
 model=json.loads((p/rel).read_text('utf-8'))
 for n in model['nodes']:nodes.setdefault(n['name'],{**n,'_parent_name':model['nodes'][n['parent']]['name'] if n['parent']>=0 else None})
bones={b.get('source_name'):b for b in arm.data.bones if b.get('source_name')};sk=pkg['skeleton'] or [];sknames={b['name']:i for i,b in enumerate(sk)};refs=np.array([b['trs'] for b in sk]);parents=[b['parent'] for b in sk];errors=[];maxerr=0;checks=0;root_checks=0;root_error=0
from face_overlay import FaceOverlay
from flver_mapping import mapped_fk
face=FaceOverlay(pkg,p);face_report={'issues':[]}
for ci,clip in enumerate(pkg['clips']):
 a=bpy.data.actions.get(clip['name'])
 if not a:errors.append('Missing action '+clip['name']);continue
 expected_end=min(1+(clip['frames']-1)*clip['dt']*30,float(a.get('sct_trim_end',float('inf'))))
 if abs(a.frame_range[1]-expected_end)>.02:errors.append('Duration mismatch '+a.name)
 removed_axes=json.loads(a.get('sct_root_motion_axes','[]'))
 anchor=json.loads(a.get('sct_root_motion_anchor','[]'))
 if removed_axes and (not set(removed_axes)<=set('XYZ') or len(anchor)!=3):raise ValueError('Invalid root-motion processing metadata')
 for sample in clip['rootMotion']['samples']:
  f=1+sample[0]*30
  if f>expected_end+1e-4:continue
  for prop,start,width in [('location',1,3),('rotation_quaternion',4,4)]:
   for k in range(width):
    expected=anchor[k] if prop=='location' and 'XYZ'[k] in removed_axes else sample[start+k]
    curve=a.fcurves.find(prop,index=k);err=abs(curve.evaluate(f)-expected) if curve else 999
    root_error=max(root_error,err);root_checks+=1
    if err>1e-4:errors.append({'action':a.name,'root_motion':prop,'frame':f,'error':err})
 if not sc.get('sct_direct_export_version') and ci not in sorted(set([0,len(pkg['clips'])//2,len(pkg['clips'])-1])):continue
 arm.animation_data.action=a
 if a.slots:arm.animation_data.action_slot=a.slots[0]
 raw=np.fromfile(p/clip['file'],dtype='<f4').reshape(clip['frames'],len(clip['map']),10)
 last_index=min(clip['frames']-1,max(0,int((expected_end-1)/(clip['dt']*30)+1e-4)))
 indices=sorted(set([0,last_index//2,last_index]));local=np.broadcast_to(refs,(clip['frames'],len(sk),10)).copy()
 for ti,bi in enumerate(clip['map']):local[:,bi]=raw[:,ti]
 local=face.apply(clip,local,face_report)[indices]
 fk=fk_separate_scale(parents,local[:,:,:3],local[:,:,3:7],local[:,:,7:],C)
 flver_fk=mapped_fk(nodes,sknames,fk)
 for si,ix in enumerate(indices):
  f=1+ix*clip['dt']*30;sc.frame_set(math.floor(f),subframe=f%1);bpy.context.view_layer.update()
  for name,b in bones.items():
   bind=C@np.array(nodes[name]['world']).reshape(4,4).T@CI;expected=flver_fk[name][si]@np.linalg.inv(bind)@np.array(b.matrix_local);actual=np.array(arm.pose.bones[b.name].matrix);err=float(np.max(np.abs(expected-actual)));maxerr=max(maxerr,err);checks+=1
   if err>5e-4:errors.append({'action':a.name,'frame':f,'bone':name,'error':err})
report={'passed':not errors,'errors':errors,'checks':checks,'max_matrix_error':maxerr,'root_checks':root_checks,'max_root_channel_error':root_error,'actions':len(bpy.data.actions),'meshes':sum(o.type=='MESH' for o in bpy.data.objects),'packed_images':sum(bool(i.packed_file) for i in bpy.data.images),'scope':'all action existence/duration/root samples; source first/middle/last clips and frames; not exhaustive DSAS viewport equality'}
report['root_motion_processing']={a.name:json.loads(a['sct_root_motion_axes']) for a in bpy.data.actions if 'sct_root_motion_axes' in a}
report['trimmed_actions']={a.name:float(a['sct_trim_end']) for a in bpy.data.actions if 'sct_trim_end' in a}
report['scope']+='; trimmed clips checked only within retained interval, see action_trim_report.json for all-channel hold verification'
if sc.get('sct_direct_export_version'):report['scope']='Direct export: ALL actions source start/middle/end FK, all root samples, duration/existence; validates earlier actions after late helper insertion; fractional interpolation approximate'
(p/'saved_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print('REOPEN_VERIFY',report['passed'],checks,maxerr,flush=True)
if errors:raise RuntimeError('Saved validation failed; see saved_validation.json')
