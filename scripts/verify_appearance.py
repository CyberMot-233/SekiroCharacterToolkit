"""Reopen and check shader roles, source UV references and driven NPC visibility."""
import bpy,sys,json,math
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).parent))
from materials import select_primary
from model_masks import ModelMasks,states
p=Path(sys.argv[sys.argv.index('--')+1]);pkg=json.loads((p/'package.json').read_text(encoding='utf-8-sig'))
if '--already-open' not in sys.argv:bpy.ops.wm.open_mainfile(filepath=str(p/(pkg['character']+'.blend')))
arm=bpy.data.objects[pkg['character']+'_Armature'];sc=bpy.context.scene;mask=ModelMasks(pkg,p,arm);errors=[];checks=0
models=[json.loads((p/f).read_text(encoding='utf-8-sig')) for f in pkg['models']]
objects=[o for o in bpy.data.objects if o.type=='MESH' and 'source_model' in o]
for ob in objects:
 if not ob.get('sct_winding_corrected'):errors.append({'mesh':ob.name,'error':'FLVER winding not corrected'})
 model=models[pkg['models'].index(ob['source_model'])];source=model['materials'][model['meshes'][ob['source_mesh_index']]['material']];mat=ob.data.materials[0]
 for role,prop in [(1,'primary_albedo'),(3,'primary_normal')]:
  expected=select_primary(source,role)
  if expected and mat.get(prop)!=expected['resolvedName']:errors.append({'mesh':ob.name,'property':prop,'expected':expected['resolvedName'],'actual':mat.get(prop)})
 for node in mat.node_tree.nodes:
  if node.type=='TEX_IMAGE' and node.image and node.image.alpha_mode!='CHANNEL_PACKED':errors.append({'material':mat.name,'error':'packed channel alpha mode missing'})
  if node.type=='UVMAP' and node.uv_map not in ob.data.uv_layers:errors.append({'mesh':ob.name,'missing_uv':node.uv_map})
for clip in pkg['clips']:
 action=bpy.data.actions[clip['name']];arm.animation_data.action=action
 if action.slots:arm.animation_data.action_slot=action.slots[0]
 events=mask.events(clip);last=min(1+(clip['frames']-1)*clip['dt']*30,float(action.get('sct_trim_end',float('inf'))));times={0,max(0,(last-1)/60),max(0,(last-1)/30)}
 for e in events:
  for t in [e['start'],e['end']]:
   for delta in [-.0001,0,.0001]:
    if 0<=t+delta<=(last-1)/30:times.add(t+delta)
 for t in sorted(times):
  f=float(np.float32(1+t*30));sc.frame_set(math.floor(f),subframe=f-math.floor(f));bpy.context.view_layer.update();expected=states(mask.weapon_policy.resolve(clip)[0],events,(f-1)/30)
  for ob in objects:
   if 'source_draw_mask' not in ob:continue
   m=int(ob['source_draw_mask']);visible=expected[m];checks+=1
   if bool(ob.hide_render)==visible or bool(ob.hide_viewport)==visible:errors.append({'action':action.name,'frame':f,'mesh':ob.name,'mask':m,'expected_visible':visible,'hide_render':ob.hide_render,'hide_viewport':ob.hide_viewport})
report={'passed':not errors,'checks':checks,'actions':len(pkg['clips']),'materials_checked':len(objects),'errors':errors[:80],'error_count':len(errors),'scope':'primary sampler/UV and actual evaluated visibility at all action starts/middles/ends and TAE mask boundaries'}
(p/'appearance_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('APPEARANCE_VERIFY',report,flush=True)
if errors:raise RuntimeError('Appearance verification failed')
