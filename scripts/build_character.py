"""Build a Blender character from the worker package; preserve full affine skinning."""
import bpy,sys,json,math,csv,traceback,re,gc,argparse,time,os
from pathlib import Path
import numpy as np
from mathutils import Matrix,Vector
sys.path.insert(0,str(Path(__file__).resolve().parent))
from internal_fk_verified import fk_separate_scale,DEFAULT_C
from affine_factor import factor_affine
from linear_keys import reduce_keys
from memory_budget import require_memory,peak_working_set
ap=argparse.ArgumentParser();ap.add_argument('package',type=Path);ap.add_argument('--clean-bones',action='store_true');ap.add_argument('--hierarchy',action='store_true');ap.add_argument('--helper-visibility',choices=['visible','hidden'],default='visible');ap.add_argument('--root-options',type=Path);ap.add_argument('--action-cache',type=Path);ap.add_argument('--cache-identity')
args=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);P=args.package.resolve();pkg=json.loads((P/'package.json').read_text('utf-8-sig'));started=time.monotonic()
root_options=json.loads(args.root_options.read_text('utf-8-sig')) if args.root_options else {'actions':[],'axes':[]}
if not set(root_options['actions'])<=set(c['name'] for c in pkg['clips']) or set(root_options['axes'])-set('XYZ') or (root_options['actions'] and not root_options['axes']):raise ValueError('Invalid root motion options')
root_report={'passed':True,'method':'write selected root axes directly from source anchor','actions':[]}
report={'character':pkg['character'],'passed':False,'issues':list(pkg['issues']),'missing_textures':pkg['missingTextures'],'actions':[],'meshes':0,'vertices':0,'uv_layers':0,'zero_weight_vertices':0,'max_affine_reconstruction_error':0.0}
C=DEFAULT_C;CI=np.linalg.inv(C)
def matrix(v):return C@np.asarray(v,float).reshape(4,4).T@CI
def log(*a):print(*a,flush=True)
bpy.ops.wm.read_factory_settings(use_empty=True);sc=bpy.context.scene;sc.render.fps=30
arm=bpy.data.objects.new(pkg['character']+'_Armature',bpy.data.armatures.new(pkg['character']+'_Skeleton'));sc.collection.objects.link(arm);bpy.context.view_layer.objects.active=arm;arm.select_set(True)
models=[json.loads((P/f).read_text('utf-8')) for f in pkg['models']]
if not models:raise RuntimeError('No FLVER models in this character package')
sk=pkg['skeleton'] or [];sknames={b['name']:i for i,b in enumerate(sk)}
nodes={}
for model in models:
 for n in model['nodes']:
  if n['name'] not in nodes:nodes[n['name']]={**n,'_parent_name':model['nodes'][n['parent']]['name'] if n['parent']>=0 else None}
rest={};rig_names={}
bpy.ops.object.mode_set(mode='EDIT')
for index,(name,node) in enumerate(nodes.items()):
 # A two-bone affine pair can represent any sampled 3x3 transform including shear.
 # Deform bones are not chained: DSAS has independent RT/Scale accumulation.
 m=Matrix(matrix(node['world']));loc,rot,scale=m.decompose();r=Matrix.Translation(loc)@rot.to_matrix().to_4x4();rest[name]=np.array(r);outer='AFF_'+str(index);inner='B_'+str(index)
 for bn,par in [(outer,None),(inner,outer)]:
  eb=arm.data.edit_bones.new(bn);eb.head=(0,0,0);eb.tail=(0,.06,0);eb.matrix=r
  if par:eb.parent=arm.data.edit_bones[par]
  eb.use_deform=par is not None
 rig_names[name]=(outer,inner)
bpy.ops.object.mode_set(mode='OBJECT')
for n,(outer,inner) in rig_names.items():
 # Blender orthogonalizes edit-bone roll; use its actual stored rest matrix.
 rest[n]=np.array(arm.data.bones[inner].matrix_local)
 arm.data.bones[outer].hide=True;arm.pose.bones[outer].rotation_mode='QUATERNION';arm.pose.bones[inner].rotation_mode='QUATERNION';arm.data.bones[inner]['source_name']=n;arm.data.bones[inner]['source_parent_index']=nodes[n]['parent']
image_cache={}
weighted_names=set()
def image(key,noncolor=False):
 rel=pkg['textures'].get(key)
 if not rel:return None
 cache=(key,noncolor)
 if cache in image_cache:return image_cache[cache]
 try:
  png=P/'_internal/rgba'/(key+'.tif')
  im=bpy.data.images.load(str(png if png.exists() else P/rel),check_existing=False)
  im.alpha_mode='CHANNEL_PACKED'
  if noncolor:im.colorspace_settings.name='Non-Color'
  # Public textures are RGB PNG; TIFF with alpha is an internal material cache.
  im.pack();image_cache[cache]=im;return im
 except Exception as ex:report['issues'].append({'stage':'image','name':key,'error':str(ex)});image_cache[cache]=None;return None
from materials import build_material
from model_masks import ModelMasks
model_masks=ModelMasks(pkg,P,arm)
def material(source):return build_material(source,image)
for mi,model in enumerate(models):
 materials=[material(m) for m in model['materials']];bn=[n['name'] for n in model['nodes']]
 for k,mesh in enumerate(model['meshes']):
  pos=np.asarray(mesh['pos'],float)@C[:3,:3].T;indices=np.asarray(mesh['indices'],int).reshape(-1,3);indices=indices[np.all(indices>=0,axis=1)&np.all(indices<len(pos),axis=1)];indices=indices[(indices[:,0]!=indices[:,1])&(indices[:,1]!=indices[:,2])&(indices[:,0]!=indices[:,2])]
  indices=indices[:,[0,2,1]] # FLVER is clockwise; Blender requires outward CCW.
  if not len(pos):continue
  data=bpy.data.meshes.new(f'M{mi}_{k}');data.from_pydata(pos.tolist(),[],indices.tolist());data.update();ob=bpy.data.objects.new(data.name,data);sc.collection.objects.link(ob);ob.parent=arm
  ob['sct_winding_corrected']=True;ob['source_model']=pkg['models'][mi];ob['source_mesh_index']=k
  if 0<=mesh['material']<len(model['materials']):
   match=re.search(r'#([0-9]+)#',model['materials'][mesh['material']]['name'])
   if match:
    mask=int(match[1]);ob['source_draw_mask']=mask;model_masks.bind(ob,mask);collection=bpy.data.collections.get('VariantMask_'+str(mask)) or bpy.data.collections.new('VariantMask_'+str(mask))
    if collection.name not in sc.collection.children:sc.collection.children.link(collection)
    collection.objects.link(ob);sc.collection.objects.unlink(ob)
  if 'hd_m_9120' in pkg['models'][mi].lower():ob.hide_render=True;ob.hide_set(True)
  if 0<=mesh['material']<len(materials):data.materials.append(materials[mesh['material']])
  for poly in data.polygons:poly.use_smooth=True
  try:data.normals_split_custom_set_from_vertices((np.asarray(mesh['normal'])@C[:3,:3].T).tolist())
  except Exception as ex:report['issues'].append({'stage':'normals','mesh':ob.name,'error':str(ex)})
  loops=np.array([l.vertex_index for l in data.loops],int)
  uvcount=max((len(x) for x in mesh['uv']),default=0)
  for u in range(uvcount):
   layer=data.uv_layers.new(name='UV'+str(u));uv=np.array([v[u][:2] if len(v)>u else [0,0] for v in mesh['uv']],np.float32);uv[:,1]=1-uv[:,1];layer.data.foreach_set('uv',uv[loops].ravel());report['uv_layers']+=1
  for col in range(max((len(x) for x in mesh['colors']),default=0)):
   layer=data.color_attributes.new(name='Color'+str(col),type='FLOAT_COLOR',domain='POINT');vals=np.array([v[col] if len(v)>col else [1,1,1,1] for v in mesh['colors']],np.float32);layer.data.foreach_set('color',vals.ravel())
  for ti in range(max((len(x) for x in mesh['tangent']),default=0)):
   vals=np.array([v[ti] if len(v)>ti else [1,0,0,1] for v in mesh['tangent']],np.float32);layer=data.attributes.new(name='SourceTangent'+str(ti),type='FLOAT_VECTOR',domain='POINT');layer.data.foreach_set('vector',(vals[:,:3]@C[:3,:3].T).astype(np.float32).ravel());sign=data.attributes.new(name='TangentSign'+str(ti),type='FLOAT',domain='POINT');sign.data.foreach_set('value',vals[:,3])
  ids=np.asarray(mesh['boneIndices'],int);weights=np.asarray(mesh['weights'],float);weights[np.all(weights==0,axis=1),0]=1
  if not mesh['usesBoneIndices']:ids[:,0]=mesh['normalW'];weights[:]=0;weights[:,0]=1
  if model['version']<=0x2000D:
   palette=np.asarray(mesh['info']['BoneIndices'],int);valid=(ids>=0)&(ids<len(palette));ids=palette[np.clip(ids,0,len(palette)-1)];weights[~valid]=0
  valid=(ids>=0)&(ids<len(bn));weights[~valid]=0;ids=np.clip(ids,0,len(bn)-1);tot=weights.sum(axis=1);report['zero_weight_vertices']+=int(np.count_nonzero(tot<=0));weights/=np.maximum(tot[:,None],1e-20)
  if mesh['info'].get('Dynamic')==0:
   bind=np.array([matrix(n['world']) for n in model['nodes']]);trans=np.einsum('vbij,vj->vbi',bind[ids],np.column_stack((pos,np.ones(len(pos)))));pos=(trans[:,:,:3]*weights[:,:,None]).sum(axis=1)
   data.vertices.foreach_set('co',pos.astype(np.float32).ravel());data.update()
  groups={i:ob.vertex_groups.new(name=rig_names[n][1]) for i,n in enumerate(bn) if n in rig_names}
  missing_weighted=[bn[int(i)] for i in np.unique(ids[weights>0]) if bn[int(i)] not in sknames]
  weighted_names.update(bn[int(i)] for i in np.unique(ids[weights>0]))
  static_weapon=pkg.get('assetType')=='weapon' and not any(n['name'] in sknames for n in model['nodes'])
  if sk and missing_weighted and not static_weapon:report.setdefault('reference_fallback',[]).append({'mesh':ob.name,'bones':missing_weighted,'method':'DSAS unmapped FLVER reference local inheriting mapped ancestor'})
  for v in range(len(pos)):
   for bi,weight in zip(ids[v],weights[v]):
    if weight>0 and bi in groups:groups[bi].add([v],float(weight),'ADD')
  mod=ob.modifiers.new('OriginalSkin','ARMATURE');mod.object=arm;report['meshes']+=1;report['vertices']+=len(pos)
from direct_author import FinalRig,SourceMotion
final_rig=FinalRig(arm,models,nodes,rig_names,rest,args.clean_bones,args.hierarchy)
rig_names=final_rig.rig_names
models.clear();del model,mesh;gc.collect()
def write(action,name,frames,values):
 for prop,offset,width in [('location',0,3),('rotation_quaternion',3,4),('scale',7,3)]:
  path=f'pose.bones["{name}"].{prop}' if name else prop
  for j in range(width):
   vals=values[:,offset+j];keep=reduce_keys(frames,vals,tolerance=1e-7);fc=action.fcurves.new(path,index=j,action_group=name or 'RootMotion');fc.keyframe_points.add(len(keep));fc.keyframe_points.foreach_set('co',np.column_stack((frames[keep],vals[keep])).astype(np.float32).ravel())
   linear=bpy.types.Keyframe.bl_rna.properties['interpolation'].enum_items['LINEAR'].value;fc.keyframe_points.foreach_set('interpolation',np.full(len(keep),linear,dtype=np.int32))
   fc.update()
def decompose(ms):
 rows=[]
 for m in ms:
  t,q,s=Matrix(m).decompose();rows.append([*t,*q,*s])
 result=np.asarray(rows,float)
 for i in range(1,len(result)):
  if result[i-1,3:7]@result[i,3:7]<0:result[i,3:7]*=-1
 return result
arm.animation_data_create();arm.rotation_mode='QUATERNION'
refs=np.asarray([b['trs'] for b in sk],float);parents=[b['parent'] for b in sk]
from face_overlay import FaceOverlay
face_overlay=FaceOverlay(pkg,P)
from flver_mapping import mapped_fk
report['unmapped_flver_bones']=[n for n in nodes if n not in sknames]
report['weighted_bone_mapping']={'weighted':len(weighted_names),'direct_hkx_matches':sum(n in sknames for n in weighted_names),'reference_fallback':sorted(weighted_names-set(sknames))}
if sk and weighted_names and not any(n in sknames for n in weighted_names):report['issues'].append({'stage':'skeleton_mapping','error':'No weighted model bone matches chosen animation skeleton'})
if not pkg['models']:report['issues'].append({'stage':'model','error':'No models were extracted'})
report['limited_export']=pkg.get('limited',False)
report['validation_scope']='Source FK and Blender stored pose matrices; not complete engine shader/physics equivalence'
from action_disk_cache import ActionCache
spool=ActionCache(args.action_cache,args.cache_identity) if args.action_cache else None
equipment_run=equipment_finish=None
if (P/'equipment/profile.json').exists():
 from bake_equipment import prepare
 equipment_run,equipment_finish=prepare(P,arm,rig_names,material,direct=True)
for ci,clip in enumerate(pkg['clips']):
 require_memory(256*1024**2)
 if not sk:report['issues'].append({'stage':'animation','error':'Missing skeleton'});break
 cached=spool.get(ci,clip['name']) if spool else None
 if cached:
  final_rig.add_helpers(cached['helpers']);e=cached['evidence'];report['actions'].append(e['action'])
  final_rig.max_error=max(final_rig.max_error,e['action']['matrix_error']);final_rig.checks+=e['matrix_checks'];final_rig.action_count+=1
  report['max_affine_reconstruction_error']=max(report['max_affine_reconstruction_error'],e['action']['matrix_error'])
  report.setdefault('face_overlay',[]).extend(e['face']);model_masks.records.extend(e['masks']);root_report['actions'].extend(e['roots'])
  if equipment_run:equipment_run.report['actions'].extend(e['equipment']);equipment_run.report['max_affine_error']=max(equipment_run.report['max_affine_error'],e['equipment_error'])
  log('ACTION_CACHE_REUSED',ci+1,len(pkg['clips']),clip['name']);continue
 before=(len(report.get('face_overlay',[])),len(model_masks.records),len(root_report['actions']),len(equipment_run.report['actions']) if equipment_run else 0,final_rig.checks)

 motion=SourceMotion(P,pkg,clip,nodes,final_rig.original_rest,final_rig.original_names,face_overlay,report)
 action=bpy.data.actions.new(clip['name']);action.use_fake_user=True;action['source_duration']=clip['duration'];action['source_fps']=1/clip['dt']
 model_masks.bake(action,clip)
 dense=final_rig.bake(action,motion)
 rm=np.asarray(clip['rootMotion']['samples'],float);rv=np.zeros((len(rm),10));rv[:,:3]=rm[:,1:4];rv[:,3:7]=rm[:,4:8];rv[:,7:]=1
 if clip['name'] in root_options['actions']:
  axes=sorted(set(root_options['axes']))
  for axis in axes:rv[:,'XYZ'.index(axis)]=rm[0,1+'XYZ'.index(axis)]
  action['sct_root_motion_axes']=json.dumps(axes);action['sct_root_motion_anchor']=json.dumps(rm[0,1:4].tolist());action['sct_root_motion_source']=clip['name']
  root_report['actions'].append({'name':clip['name'],'removed_axes':axes,'anchor':rm[0,1:4].tolist()})
 write(action,None,1+rm[:,0]*30,rv)
 if equipment_run:equipment_run(action,motion.skin)
 maxerr=final_rig.verify(action,motion,dense)
 report['max_affine_reconstruction_error']=max(report['max_affine_reconstruction_error'],maxerr)
 report['actions'].append({'name':action.name,'frames':clip['frames'],'duration':clip['duration'],'matrix_error':maxerr})
 log('DIRECT_ACTION',ci+1,len(pkg['clips']),action.name,'error',maxerr)
 if spool:
  evidence={'action':report['actions'][-1],'face':report.get('face_overlay',[])[before[0]:],'masks':model_masks.records[before[1]:],
            'roots':root_report['actions'][before[2]:],'equipment':equipment_run.report['actions'][before[3]:] if equipment_run else [],
            'equipment_error':equipment_run.report['max_affine_error'] if equipment_run else 0.,'matrix_checks':final_rig.checks-before[4]}
  if report['issues'] or (equipment_run and equipment_run.report['issues']):raise ValueError('Do not cache an invalid action')
  spool.put(ci,action,final_rig.helpers,evidence);spool.release(action,final_rig);del action
  log('ACTION_CACHED_RELEASED',ci+1,'live_actions',len(bpy.data.actions),'folder',spool.folder)
 del motion,dense;gc.collect()
if spool:
 author_peak=peak_working_set()
 report['action_disk_cache']=spool.assemble(final_rig)
 report['action_disk_cache']['authoring_peak_working_set_bytes']=author_peak
if equipment_finish:
 equipment=equipment_finish();report['equipment']=equipment;report['issues'].extend(equipment['issues'])
if args.clean_bones:(P/'bone_cleanup.json').write_text(json.dumps(final_rig.cleanup,ensure_ascii=False,indent=2),encoding='utf-8')
if args.hierarchy:(P/'hierarchy_report.json').write_text(json.dumps(final_rig.report(),ensure_ascii=False,indent=2),encoding='utf-8')
if root_report['actions']:(P/'root_motion_report.json').write_text(json.dumps(root_report,ensure_ascii=False,indent=2),encoding='utf-8')
from helper_visibility import set_visibility,effective_visible
helper_names=set_visibility(arm,args.helper_visibility=='visible')
helper_report={'passed':all(effective_visible(arm.data.bones[n])==(args.helper_visibility=='visible') for n in helper_names),'visible':args.helper_visibility=='visible','helpers':helper_names,'helper_count':len(helper_names),'method':'set on final rig before first save'}
(P/'helper_visibility_report.json').write_text(json.dumps(helper_report,ensure_ascii=False,indent=2),encoding='utf-8')
if bpy.data.actions:
 arm.animation_data.action=bpy.data.actions[0]
 if arm.animation_data.action.slots:arm.animation_data.action_slot=arm.animation_data.action.slots[0]
 sc.frame_end=max(1,round(arm.animation_data.action.frame_range[1]))
sc.frame_set(1);arm.show_in_front=args.hierarchy;arm.data.display_type='OCTAHEDRAL' if args.hierarchy else 'STICK'
sc.world=bpy.data.worlds.new('World');sc.world.use_nodes=True;sc.world.node_tree.nodes['Background'].inputs[0].default_value=(.16,.18,.22,1)
for screen in bpy.data.screens:
 for area in screen.areas:
  if area.type=='VIEW_3D':area.spaces.active.shading.type='MATERIAL';area.spaces.active.region_3d.view_distance=4
sc['pipeline']='Direct final rig/actions; DSAS independent scale FK; source preserved';sc['limitations']='External equipment slots, event-driven mesh masks and dynamics require character-specific evaluation; see report.'
report['model_masks']={'npc':pkg.get('npcAppearance',{}).get('selected'),'used_masks':sorted(model_masks.used),'actions':model_masks.records}
report['packed_images']=sum(bool(im.packed_file) for im in bpy.data.images);report['bones']=len(arm.data.bones);report['passed']=not report['issues'] and not report['missing_textures'] and report['zero_weight_vertices']==0 and report['max_affine_reconstruction_error']<5e-4
if not report['passed']:raise RuntimeError('Direct authoring validation failed: '+str(report['issues'][:5]))
sc['sct_direct_export_version']='0.10.4';bpy.context.preferences.filepaths.save_version=0
staged=P/(pkg['character']+'.direct_pending.blend');bpy.ops.wm.save_as_mainfile(filepath=str(staged),compress=True)
os.replace(staged,P/(pkg['character']+'.blend'))
report.update(method='direct-final',blend_saves=1,intermediate_blends=0,author_seconds=time.monotonic()-started,peak_working_set_bytes=peak_working_set())
(P/'blender_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');log('BLEND_DONE',report['meshes'],len(report['actions']),'passed',report['passed'])
