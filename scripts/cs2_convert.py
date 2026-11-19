"""Portable command-line entry point for the toolkit's CS2 conversion page."""
import argparse,sys,subprocess,hashlib,re,datetime,math
from pathlib import Path
from cs2_common import *

def node(cls,**values):return dict(_class=cls,**values)

def validation_failure(validation):
 issues=(validation or {}).get('issues',[])
 if not issues:return '编译资源回读程序未完成，请查看完整日志'
 first=issues[0]
 if isinstance(first,dict) and first.get('worst_position'):
  w=first['worst_position']
  return f"编译回读失败（{len(issues)} 项）：{first['name']} / {w['bone']} 第 {w['frame']} 帧；位置误差 {first['max_position_error_source_units']:.6g} Source 单位"
 return '编译回读失败：'+str(first)

def completed_raw_export(out,addon,completed):
 """Migrate only completed clips, never resume other source actions."""
 raw=read(out/'export_report.json');records={c['source']:c for c in raw['actions']}
 cached=read(out/'source2/resume.json')['actions'];selected=[]
 for done in completed['actions']:
  source=done['source'];item=records.get(source);prior=cached.get(source,{})
  if item is None or prior.get('source_sha256')!=item['dmx_sha256']:
   raise ValueError('旧绑定的原始动作来源无法核对：'+source)
  selected.append(item)
 raw['actions']=selected
 return raw
def modeldoc(addon,name,export,axes,audio_events,attachments=None):
 if not export.get('bind_encoding'):raise ValueError('CS2 模型必须先完成统一绑定换算；不能生成覆盖 DMX 绑定的显式 Skeleton')
 children=[node('BoneMarkupList',bone_cull_type='None',primary_root_bone='sct_motion')]
 render=[]
 for group in export['mesh_groups']:
  # CS2's current shader path misreads the 8 x 16-bit blend stream. The same
  # DMX renders correctly with 8 x 8-bit weights. Keep every influence; never
  # silently clamp the affine helper weights to four. Mixed 4x16 and 8x8
  # groups also displaced equipment in ModelDoc; keep one UNORM8 profile.
  from cs2_dmx import d
  mesh=d.load(str(Path(addon)/group['file']));influences=0
  import numpy as np
  for dag in mesh.root['model']['children']:
   if dag.type!='DmeDag':continue
   state=dag['shape']['bindState'];w=np.array(state['blendweights$0']).reshape(-1,state['jointCount'])
   influences=max(influences,int(np.max(np.count_nonzero(w>0,axis=1))))
  if influences>8:raise ValueError(f'{group["name"]}: {influences} weights exceed the supported eight')
  render.append(node('RenderMeshFile',name=group['name'],filename=group['file'],import_scale=1.0,import_filter=dict(exclude_by_default=False,exception_list=[]),children=[node('RenderMeshMarkup',blend_weights_per_vertex='8',high_precision_blendweights=False,high_high_precision_texcoords=True)]))
 children.append(node('RenderMeshList',children=render))
 groups={}
 for m in export['mesh_groups']:groups[m['name']]=[m['name']]
 bodygroups=[]
 for g,meshes in groups.items():
  choices=[node('BodyGroupChoice',name='visible',meshes=meshes)] if g=='body' else [node('BodyGroupChoice',name='hidden',meshes=[]),node('BodyGroupChoice',name='visible',meshes=meshes)]
  bodygroups.append(node('BodyGroup',name=g,children=choices,hidden_in_tools=False,non_bodygroup_single_choice=False,suppress_missing_warnings=False))
 children.append(node('BodyGroupList',children=bodygroups))
 children.append(node('AttachmentList',children=[node('Attachment',name='sct_origin',parent_bone='sct_motion',relative_origin=[0.0,0.0,0.0],relative_angles=[0.0,0.0,0.0],weight=1.0,ignore_rotation=False)]+[{**x,'parent_bone':bone_name(x['parent_bone'])} for x in (attachments or [])]))
 animations=[]
 for c in export['actions']:
  modifiers=[]
  if axes:modifiers.append(node('ExtractMotion',extract_tx='x' in axes,extract_ty='y' in axes,extract_tz='z' in axes,extract_rz='r' in axes,linear=False,quadratic=False,extract_initial_offset=False,root_bone_name='sct_motion',motion_type='Uniform'))
  modifiers.extend(audio_events.get(c['source'],[]))
  for e in c['visibility_events']:modifiers.append(node('AnimEvent',event_class='AE_BODYGROUP_SET_VALUE',event_frame=e['frame'],event_end_frame=-1,event_keys=dict(bodygroup=e['group'],value=e['value'])))
  animations.append(node('AnimFile',name=c['name'],children=modifiers,is_default_idle_anim=False,activity_name='',activity_weight=1,weight_list_name='',fade_in_time=.2,fade_out_time=.2,looping=False,delta=False,worldSpace=False,hidden=False,anim_markup_ordered=False,disable_compression=True,animgraph_additive=False,delete_from_compiled_model=False,source_filename=c['file'],import_bone_scales=True,start_frame=0,end_frame=c['frames']-1,framerate=c['fps'],reverse=False,additional_anim_files=[]))
 children.append(node('AnimationList',children=animations))
 # Import the one shared skeleton from the normalized mesh/animation DMX.
 # A disabled explicit Skeleton deletes its entire bone subtree at compile
 # time; deleting that *override node* is not deleting the imported rig.
 from cs2_visibility import apply as apply_visibility
 document=dict(rootNode=node('RootNode',children=children,model_archetype='',primary_associated_entity='prop_dynamic',document_sub_type='ModelDocSubType_None'))
 visibility=apply_visibility(document,export)
 print('CS2_VISIBILITY',visibility,flush=True)
 vmdl=Path(addon)/f'models/sekiro/characters/{name}/{name}.vmdl';write_kv(vmdl,document,model=True);return vmdl

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--package',required=True,type=Path);ap.add_argument('--addon',required=True,type=Path);ap.add_argument('--name',default='wolf');ap.add_argument('--motion-axes',default='xy');ap.add_argument('--blender',required=True);ap.add_argument('--ffmpeg',required=True);ap.add_argument('--clip-list',type=Path);ap.add_argument('--audio',action='store_true');ap.add_argument('--audio-volumes',type=Path);ap.add_argument('--compile',action='store_true');ap.add_argument('--reuse-export',action='store_true');ap.add_argument('--reuse-bound-export',action='store_true',help='Repair only completed normalized DMX; do not resume full extraction/binding');ap.add_argument('--limit',type=int,default=0);a=ap.parse_args()
 p=a.package.resolve();addon=a.addon.resolve();name=safe_name(a.name);root=cs_root(addon);pkg=read(p/'package.json');axes=a.motion_axes.lower()
 if set(axes)-set('xyzr'):raise ValueError('motion-axes accepts x y z r only')
 out=addon/f'rawmodels/sekiro/characters/{name}'
 from cs2_destination import prepare_destination
 destination=prepare_destination(addon,name,p)
 out.mkdir(parents=True,exist_ok=True);reports=out/'reports';reports.mkdir(exist_ok=True)
 if a.reuse_bound_export and not (out/'compile_export.json').exists():raise ValueError('没有已完成的统一绑定清单 compile_export.json；请先转换所选动作，不能用半成品恢复全量')
 owner=out/'sct_owner.json';identity={'package':str(p),'character':pkg['character'],'tool':'SekiroCharacterToolkit'}
 if owner.exists() and read(owner)['package']!=str(p):raise ValueError('模型名已属于另一个导出目录，请更换名称：'+name)
 save(owner,identity)
 import shutil
 stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f');backup=out/'backups'/stamp
 vmdl_existing=addon/f'models/sekiro/characters/{name}/{name}.vmdl'
 compiled_existing=root/f'game/csgo_addons/{addon.name}/models/sekiro/characters/{name}/{name}.vmdl_c'
 for existing in (vmdl_existing,compiled_existing,reports/'conversion.json',out/'compile_export.json'):
  if existing.exists():backup.mkdir(parents=True,exist_ok=True);shutil.copy2(existing,backup/existing.name)
 report={'passed':False,'status':'running','version':'0.10.10','repair_completed_only':a.reuse_bound_export,'backup':str(backup),'package':str(p),'addon':str(addon),'name':name,'extract_motion':axes,'compile_requested':a.compile,'compiled':[],'runtime_validation':'not_run','modeldoc_visual_validation':'not_run'};save(reports/'conversion.json',report)
 try:
  if any(not (p/'_internal/rgba'/(key+'.tif')).is_file() for key in pkg['textures']):
   from prepare_textures import main as prepare_textures
   if prepare_textures(p):raise RuntimeError('贴图预转换失败，详见 texture_conversion.json')
  if not a.reuse_export and not a.reuse_bound_export:
   cmd=[a.blender,'--background','--factory-startup','--disable-autoexec','--threads','4','--python-exit-code','1','--python',str(Path(__file__).with_name('blender_bootstrap.py')),'--python',str(Path(__file__).with_name('cs2_export.py')),'--','--package',str(p),'--addon',str(addon),'--name',name]
   if a.clip_list:cmd+=['--clip-list',str(a.clip_list.resolve())]
   if a.limit:cmd+=['--limit',str(a.limit)]
   subprocess.run(cmd,check=True)
  export=read(out/('compile_export.json' if a.reuse_bound_export else 'export_report.json'))
  if (a.reuse_export or a.reuse_bound_export) and a.clip_list:
   selected=set(read(a.clip_list));available={c['source'] for c in export['actions']}
   if not selected or selected-available:raise ValueError('复用导出所选动作不存在或列表为空')
   export['actions']=[c for c in export['actions'] if c['source'] in selected]
  if (a.reuse_export or a.reuse_bound_export) and a.limit:export['actions']=export['actions'][:a.limit]
  from cs2_bind import VERSION
  migrate=a.reuse_bound_export and export.get('bind_encoding')!=VERSION
  if migrate:
   report['bind_migration']={'from':export.get('bind_encoding'),'to':VERSION,'completed_actions':len(export['actions'])}
   export=completed_raw_export(out,addon,export)
   shutil.copytree(out/'source2',backup/'source2',dirs_exist_ok=True)
   print('CS2_BIND_MIGRATE',len(export['actions']),'已完成动作；从原始 DMX 修复，不重新提取',flush=True)
  if not export['passed']:raise RuntimeError('DMX 导出验证未通过')
  if Path(export['source_package']).resolve()!=p:raise RuntimeError('DMX 导出报告不属于当前提取包')
  for clip in export['actions']:
   file=addon/clip['file']
   if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest()!=clip['dmx_sha256']:raise RuntimeError('动作 DMX 不完整或被改写：'+str(file))
  from cs2_bind import prepare as prepare_bind
  if not a.reuse_bound_export or migrate:export=prepare_bind(addon,name,export)
  save(out/'compile_export.json',export)
  audio_events={};audio=None
  if a.audio:
   from cs2_audio import export_audio
   from cs2_audio_volume import read_volumes
   volumes=read_volumes(out/'audio_volumes.json') if (out/'audio_volumes.json').exists() else {}
   if a.audio_volumes:volumes.update(read_volumes(a.audio_volumes))
   audio_events,audio=export_audio(p,addon,name,a.ffmpeg,export['actions'],export=export,volumes=volumes)
   if volumes:save(out/'audio_volumes.json',volumes)
  vmdl=modeldoc(addon,name,export,axes,audio_events,audio['attachments'] if audio else None);report.update(vmdl=str(vmdl),actions=len(export['actions']),bones=len(export['bones']),max_vertex_error_m=export['max_vertex_error_m'],audio=audio,source_export_passed=export['passed'],skinning_encoding='uniform 8xUNORM8; no influence truncation',quantization_note='Lossy compiled weights. max_vertex_error_m describes pre-quantization export only; it is not the compiled GPU skinning error. ModelDoc and game validation remain separate.')
  if a.compile:
   targets=[addon/m['material'] for m in export['materials']]
   if audio:targets+=[Path(x) for x in audio['converted']]+[Path(audio['registration'])]
   targets+=[vmdl]
   for i,target in enumerate(dict.fromkeys(targets)):
    item=compile_resource(addon,target,reports/(f'compile_{i:04d}_{target.stem}.log'));report['compiled'].append(item);save(reports/'conversion.json',report);print('CS2_COMPILE',i,target.name,item['passed'],flush=True)
    if not item['passed']:raise RuntimeError('编译失败：'+item['log'])
   verify_log=reports/'compiled_verify.log'
   with verify_log.open('w',encoding='utf-8') as log:
    result=subprocess.run([sys.executable,str(Path(__file__).with_name('cs2_verify_compiled.py')),'--addon',str(addon),'--name',name,'--all-frames'],stdout=log,stderr=subprocess.STDOUT)
   report['compiled_validation']=read(reports/'compiled_validation.json') if (reports/'compiled_validation.json').exists() else None
   if result.returncode or not report['compiled_validation'] or not report['compiled_validation']['passed']:
    print('CS2_VERIFY_LOG',str(verify_log),flush=True)
    if verify_log.exists():print(verify_log.read_text('utf-8',errors='replace')[-16000:],flush=True)
    raise RuntimeError(validation_failure(report['compiled_validation']))
   quantized=[x for x in report['compiled_validation']['actions'] if x.get('static_half_quantization')]
   if quantized:
    print('CS2_PRECISION_NOTE',len(quantized),'个动作包含已核对的静态半精度通道；具体骨骼、区段和误差见 compiled_validation.json',flush=True)
   from cs2_verify_mesh import verify as verify_mesh
   report['compiled_mesh_validation']=verify_mesh(addon,name)
   if not report['compiled_mesh_validation']['passed']:raise RuntimeError('编译网格/蒙皮回读不一致，详见 compiled_mesh_validation.json')
   from cs2_dependencies import verify as verify_dependencies
   report['dependencies']=verify_dependencies(addon,name)
   if not report['dependencies']['passed']:raise RuntimeError('编译依赖缺失：'+str(reports/'dependencies.json'))
  report['passed']=not audio or audio['passed'];report['status']='complete_with_audio_gaps' if audio and not audio['passed'] else ('compiled_offline' if a.compile else 'source_ready')
  files=[]
  for base in [addon/f'models/sekiro/characters/{name}',addon/f'rawmodels/sekiro/characters/{name}',addon/f'materials/sekiro/characters/{name}',addon/f'sounds/sekiro/characters/{name}']:
   if base.exists():files.extend(str(f.relative_to(addon)).replace('\\','/') for f in base.rglob('*') if f.is_file())
  save(reports/'files.json',files);save(reports/'conversion.json',report);save(p/'cs2_conversion.json',report);print('CS2_DONE',report['status'],str(vmdl),flush=True)
 except Exception as e:
  report.update(status='failed',error=str(e));save(reports/'conversion.json',report);save(p/'cs2_conversion.json',report);raise
if __name__=='__main__':main()
