"""Repair materials and NPC visibility in an existing blend; body curves unchanged."""
import bpy,sys,json,shutil,hashlib,time
import numpy as np
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from internal_fk_verified import DEFAULT_C
from materials import build_material
from model_masks import ModelMasks

p=Path(sys.argv[sys.argv.index('--')+1]).resolve();pkg=json.loads((p/'package.json').read_text(encoding='utf-8-sig'))
file=p/(pkg['character']+'.blend');backup=p/'backups'/('appearance_'+time.strftime('%Y%m%d_%H%M%S'))/file.name;backup.parent.mkdir(parents=True,exist_ok=False);shutil.copy2(file,backup)
bpy.ops.wm.open_mainfile(filepath=str(file));arm=bpy.data.objects[pkg['character']+'_Armature'];sc=bpy.context.scene
models=[json.loads((p/f).read_text(encoding='utf-8-sig')) for f in pkg['models']];images={}
def image(key,noncolor=False):
 if key not in pkg['textures']:return None
 cache=key,noncolor
 if cache not in images:
  path=p/'_internal/rgba'/(key+'.tif');im=bpy.data.images.load(str(path if path.exists() else p/pkg['textures'][key]),check_existing=False)
  im.alpha_mode='CHANNEL_PACKED'
  if noncolor:im.colorspace_settings.name='Non-Color'
  im.pack();images[cache]=im
 return images[cache]
materials=[[build_material(m,image) for m in model['materials']] for model in models];mask=ModelMasks(pkg,p,arm);meshes=0
for ob in bpy.data.objects:
 if ob.type!='MESH' or 'source_model' not in ob:continue
 mi=pkg['models'].index(ob['source_model']);k=ob['source_mesh_index'];material_index=models[mi]['meshes'][k]['material'];ob.data.materials.clear();ob.data.materials.append(materials[mi][material_index]);meshes+=1
 if not ob.get('sct_winding_corrected',False):
  ob.data.flip_normals();ob.data.normals_split_custom_set_from_vertices((np.array(models[mi]['meshes'][k]['normal'])@DEFAULT_C[:3,:3].T).tolist());ob['sct_winding_corrected']=True
 if 'source_draw_mask' in ob:
  for prop in ('hide_viewport','hide_render'):ob.driver_remove(prop)
  mask.bind(ob,int(ob['source_draw_mask']))
for clip in pkg['clips']:
 action=bpy.data.actions.get(clip['name'])
 if action is None:raise ValueError('Missing source Action: '+clip['name'])
 for fc in list(action.fcurves):
  if 'sct_mask_' in fc.data_path:action.fcurves.remove(fc)
 mask.bake(action,clip)
for material in list(bpy.data.materials):
 if material.users==0:bpy.data.materials.remove(material)
for im in list(bpy.data.images):
 if im.users==0:bpy.data.images.remove(im)
act=next((a for a in bpy.data.actions if a.name.endswith('a000_003022')),bpy.data.actions[0]);arm.animation_data.action=act
if act.slots:arm.animation_data.action_slot=act.slots[0]
sc.frame_set(20);sc.frame_end=round(act.frame_range[1]);bpy.context.view_layer.update()
report={'passed':True,'backup':str(backup),'meshes':meshes,'actions':len(mask.records),'npc':pkg.get('npcAppearance',{}).get('selected'),'primary_materials':[{'name':m.name,'albedo':m.get('primary_albedo'),'normal':m.get('primary_normal')} for row in materials for m in row],'scope':'Material sampler/UV and NPC+TAE masks only; original body/face/root-motion transforms retained'}
bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.save_as_mainfile(filepath=str(file),compress=True)
(p/'appearance_repair.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('APPEARANCE_REPAIR_DONE',meshes,len(mask.records),flush=True)
