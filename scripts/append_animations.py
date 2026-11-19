"""Append/replace selected animations; preserve existing model and other clips."""
import argparse,copy,datetime,json,os,shutil,sys
from pathlib import Path
from cs2_common import read,save,kv,SoundEvent,cs_root,compile_resource
from append_common import stage,blend,sha,run,Transaction,commit_package,SCRIPTS

def merge_records(old,new,key='source'):
 replacements={x[key]:x for x in new};out=[replacements.pop(x[key],x) for x in old];out.extend(replacements.values());return out

def commit_metadata(tx,work,base,out,merged,mergedraw):
 # Keep repair/resume consumers in sync with the authoritative manifests.
 def put(relative,data):
  path=work/'metadata'/relative;save(path,data);tx.put(path,base/relative)
 put('export_report.json',mergedraw);put('compile_export.json',merged);put('source2/export_report.json',merged)
 for relative in ('source2/resume.json','resume.json'):
  incoming=read(out/relative);prior=read(base/relative) if (base/relative).exists() else {}
  prior['actions']={**prior.get('actions',{}),**incoming['actions']}
  # Raw fingerprint depends on the whole source package; no unsafe reuse if
  # a future full export changes its inputs. Bound fingerprint is rig-only.
  prior['fingerprint']=incoming['fingerprint'] if relative.startswith('source2/') else 'incremental-revalidate'
  put(relative,prior)
 relative='source2/bind_validation.json';incoming=read(out/relative);prior=read(base/relative) if (base/relative).exists() else incoming
 prior['actions']=merge_records(prior.get('actions',[]),incoming['actions'])
 for key in ('max_local_matrix_error','max_world_matrix_error'):prior[key]=max((x[key] for x in prior['actions']),default=0.)
 put(relative,prior)

def child_array(text,obj):
 from cs2_kvtext import TOKEN
 tokens=[m for m in TOKEN.finditer(text,obj['start'],obj['end']) if not m.group().isspace() and not m.group().startswith(('//','<!--'))]
 depth=0
 for i,t in enumerate(tokens):
  if t.group()=='{':depth+=1
  elif t.group()=='}':depth-=1
  if depth==1 and t.group().strip('"')=='children' and tokens[i+1].group()=='=' and tokens[i+2].group()=='[':
   level=1
   for q in tokens[i+3:]:
    if q.group()=='[':level+=1
    elif q.group()==']':
     level-=1
     if not level:return tokens[i+2].end(),q.start()
 raise ValueError('ModelDoc 容器缺少 children 数组')

def insert_children(text,start,end,values):
 from cs2_kvtext import TOKEN
 tokens=[m.group() for m in TOKEN.finditer(text,start,end) if not m.group().isspace() and not m.group().startswith(('//','<!--'))]
 separator=',' if tokens and tokens[-1]!=',' else ''
 return separator+'\n'+',\n'.join(kv(x) for x in values)+'\n'

def merge_modeldoc(original,generated,actions):
 from cs2_audio_volume import object_fields
 from cs2_kvtext import loads
 old=loads(original);new=loads(generated)
 nodes=old['rootNode']['children'];newnodes=new['rootNode']['children']
 groups=next(x for x in nodes if x['_class']=='BodyGroupList')
 if groups.get('disabled'):raise ValueError('请先修复已有模型的部件显隐，再追加动画')
 choices={g['name']:{bool(v['meshes']):i for i,v in enumerate(g['children'])} for g in groups['children']}
 oldanims=next(x['children'] for x in nodes if x['_class']=='AnimationList');byname={x['name']:x for x in oldanims}
 generated_anims=next(x['children'] for x in newnodes if x['_class']=='AnimationList');records={x['name']:x for x in actions}
 additions={}
 for anim in generated_anims:
  name=anim['name'];children=[c for c in anim.get('children',[]) if c.get('event_class')!='AE_BODYGROUP_SET_VALUE']
  for c in children:
   if c.get('event_class')=='AE_CL_PLAYSOUND_ATTACHMENT':c['event_keys']['name']=SoundEvent(c['event_keys']['name'])
  for e in records[name]['visibility_events']:
   if e['group'] not in choices or bool(e['value']) not in choices[e['group']]:raise ValueError('已有部件组不能表示新增动作：'+e['group'])
   children.append(dict(_class='AnimEvent',event_class='AE_BODYGROUP_SET_VALUE',event_frame=e['frame'],event_end_frame=-1,event_keys=dict(bodygroup=e['group'],value=choices[e['group']][bool(e['value'])])))
  if name in byname:
   prior=copy.deepcopy(byname[name]);oldchildren=prior.get('children',[])
   # Keep existing root-motion constraints and custom non-generated events.
   children=[c for c in children if c.get('_class')!='ExtractMotion']+[c for c in oldchildren if c.get('event_class') not in ('AE_BODYGROUP_SET_VALUE','AE_CL_PLAYSOUND_ATTACHMENT')]
   for k in ('source_filename','start_frame','end_frame','framerate','import_bone_scales'):prior[k]=anim[k]
   anim=prior
  anim['children']=children;additions[name]=anim
 objects=object_fields(original);alist=next(o for o in objects if o['fields'].get('_class',(None,))[0]=='AnimationList');start,end=child_array(original,alist)
 edits=[];remaining=dict(additions)
 for obj in objects:
  if obj['fields'].get('_class',(None,))[0]!='AnimFile':continue
  name=obj['fields'].get('name',(None,))[0]
  if name in remaining:edits.append((obj['start'],obj['end'],kv(remaining.pop(name))))
 if remaining:edits.append((end,end,insert_children(original,start,end,remaining.values())))
 # Append only missing attachment entries. Never replace user-adjusted sockets.
 attach=next((o for o in objects if o['fields'].get('_class',(None,))[0]=='AttachmentList'),None)
 oldattach=next((n.get('children',[]) for n in nodes if n['_class']=='AttachmentList'),[])
 addedattach=[n for group in newnodes if group['_class']=='AttachmentList' for n in group.get('children',[]) if n['name'] not in {x['name'] for x in oldattach}]
 if addedattach:
  if attach is None:raise ValueError('已有模型没有挂点容器，请先添加 AttachmentList')
  ast,ae=child_array(original,attach);edits.append((ae,ae,insert_children(original,ast,ae,addedattach)))
 result=original
 for a,b,value in sorted(edits,reverse=True):result=result[:a]+value+result[b:]
 merged=loads(result);kept={a['name']:a for a in next(n['children'] for n in merged['rootNode']['children'] if n['_class']=='AnimationList')}
 if any(kept[n]!=v for n,v in byname.items() if n not in additions):raise ValueError('未选择动画 ModelDoc 设置被修改')
 for oldnode,newnode in zip(nodes,merged['rootNode']['children']):
  if oldnode['_class'] not in ('AnimationList','AttachmentList') and oldnode!=newnode:raise ValueError('非动画模型设置发生变化')
 defaults={g['name']:bool(g['children'][0]['meshes']) for g in groups['children'] if g['name']!='body'}
 return result,defaults

def append_blend(a,work,selected):
 p=a.package.resolve();target=a.blend.resolve()
 if not target.is_file():raise FileNotFoundError('请选择已有 .blend 文件')
 stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f');backup=target.parent/'backups'/('append_'+stamp);tx=Transaction(backup)
 pending=target.with_name(target.stem+'.append_pending_'+stamp+'.blend');report=work/'blend_append.json'
 argv=['--package',work,'--blend',target,'--output',pending,'--clips',work/'selected.json','--report',report]
 if a.root_options:argv+=['--root-options',a.root_options]
 try:
  blend(a.blender,'blend_append_actions.py',*argv);result=read(report)
  if not result['passed']:raise ValueError('Blender 动作追加回读失败')
  tx.put(pending,target);commit_package(tx,work,p)
  result.update(backup=str(backup),blend=str(target));save(p/'append_blender_report.json',result)
 except BaseException:tx.rollback();raise
 finally:
  if pending.exists():pending.unlink()
 print('APPEND_BLEND_DONE',result['added'],result['replaced'],flush=True)

def append_cs2(a,work,selected):
 from cs2_bind import prepare,VERSION
 from cs2_convert import modeldoc
 from cs2_kvtext import loads
 from cs2_audio_volume import inspect,read_volumes,alias_block,verify_compiled
 addon=a.addon.resolve();root=cs_root(addon);name=a.name;p=a.package.resolve();base=addon/f'rawmodels/sekiro/characters/{name}';reports=base/'reports'
 old=read(base/'compile_export.json');raw=read(base/'export_report.json');owner=read(base/'sct_owner.json');pkg=read(p/'package.json')
 if owner['character']!=pkg['character']:raise ValueError('已有 CS2 模型不是该角色')
 if old.get('bind_encoding')!=VERSION:raise ValueError('请先修复旧模型绑定，再追加动作')
 vmdl=addon/f'models/sekiro/characters/{name}/{name}.vmdl';original=vmdl.read_text('utf-8-sig')
 staged=work/'cs2';staged.mkdir();out=staged/f'rawmodels/sekiro/characters/{name}'
 blend(a.blender,'cs2_export.py','--package',work,'--addon',staged,'--name',name,'--clip-list',work/'selected.json','--rig-template',base/'export_report.json')
 newraw=read(out/'export_report.json');new=prepare(staged,name,newraw,fixed_bones=old['bones'])
 if not newraw['passed']:raise ValueError('新增动作 DMX 源验证失败')
 if new['bones']!=old['bones']:raise ValueError('新增动作绑定骨架不一致')
 audio_events={};audio=None;manifest=addon/'soundevents/soundevents_addon.vsndevts';registration=manifest.read_text('utf-8-sig') if manifest.exists() else None
 values=read_volumes(base/'audio_volumes.json') if (base/'audio_volumes.json').exists() else {}
 if a.audio:
  # Preserve actual manual gain on overwritten actions, not just settings.json.
  if registration:
   for c in inspect(addon,name)['clips']:
    if c['source'] in selected:
     if c['mixed']:raise ValueError('覆盖动作含混合音量，请先用音量页统一设置：'+c['source'])
     if c['volume'] is not None:values[c['source']]=c['volume']
  if a.audio_volumes:values.update(read_volumes(a.audio_volumes))
  for c in selected:values.setdefault(c,1.0)
  run([sys.executable,SCRIPTS/'audio_extract.py','--package',work,'--root',a.game or pkg['root'],'--dsas',a.dsas,'--ffmpeg',a.ffmpeg,'--cache',a.cache,'--render','--clip-list',work/'selected.json'])
  from cs2_audio import export_audio
  audio_events,audio=export_audio(work,staged,name,a.ffmpeg,new['actions'],export=new,volumes=values)
  if not audio['passed']:raise ValueError('新增动作音频提取不完整；已有模型保持不变')
 else:
  doc=loads(original);existing={x['name']:x for x in next(n['children'] for n in doc['rootNode']['children'] if n['_class']=='AnimationList')}
  for c in new['actions']:
   audio_events[c['source']]=[e for e in copy.deepcopy(existing.get(c['name'],{}).get('children',[])) if e.get('event_class')=='AE_CL_PLAYSOUND_ATTACHMENT']
 model=modeldoc(staged,name,new,a.motion_axes,audio_events,audio['attachments'] if audio else None)
 updated,defaults=merge_modeldoc(original,model.read_text('utf-8'),new['actions']);model.write_text(updated,'utf-8')
 merged=copy.deepcopy(old);merged['actions']=merge_records(old['actions'],new['actions']);merged['preserved_bodygroup_defaults']=defaults
 mergedraw=copy.deepcopy(raw);mergedraw['actions']=merge_records(raw['actions'],newraw['actions']);mergedraw['source_package']=str(p)
 merged['source_package']=str(p);selectedset=set(selected)
 protected={str(addon/c['file']):sha(addon/c['file']) for c in old['actions'] if c['source'] not in selectedset}
 for folder in ('materials','models'):
  for file in (addon/f'{folder}/sekiro/characters/{name}').rglob('*'):
   if file.is_file() and file!=vmdl:protected[str(file)]=sha(file)
 for m in old['mesh_groups']:protected[str(addon/m['file'])]=sha(addon/m['file'])
 stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f');tx=Transaction(base/'backups'/('append_'+stamp));result=dict(passed=False,added=sorted(selectedset-{c['source'] for c in old['actions']}),replaced=sorted(selectedset&{c['source'] for c in old['actions']}),backup=str(tx.backup),compiled=[])
 try:
  for item in newraw['actions']+new['actions']:tx.put(staged/item['file'],addon/item['file'])
  commit_metadata(tx,work,base,out,merged,mergedraw);tx.put(model,vmdl)
  if audio:
   for src in audio['converted']:
    src=Path(src);dest=addon/src.relative_to(staged)
    # Shared existing audio stays untouched; only event references/gain change.
    if not dest.exists():tx.put(src,dest)
   definitions=loads((staged/'soundevents/soundevents_addon.vsndevts').read_text('utf-8'));aliases={k:v for k,v in definitions.items() if k.startswith(f'sekiro.{name}.sctvol_')}
   from cs2_common import HEADER
   reg=alias_block(registration or HEADER+'\n{\n}\n',name,aliases);savefile=work/'registration.vsndevts';savefile.write_text(reg,'utf-8');tx.put(savefile,manifest)
   save(work/'volumes.json',values);tx.put(work/'volumes.json',base/'audio_volumes.json')
   audio_report=read(reports/'audio_conversion.json') if (reports/'audio_conversion.json').exists() else {}
   audio_report['converted']=list(dict.fromkeys(audio_report.get('converted',[])+[str(addon/Path(s).relative_to(staged)) for s in audio['converted']]))
   audio_report.update(passed=True,registration=str(manifest),events=sum(1 for group in loads(updated)['rootNode']['children'] if group['_class']=='AnimationList' for c in group['children'] for e in c.get('children',[]) if e.get('event_class')=='AE_CL_PLAYSOUND_ATTACHMENT'),animation_volumes=values)
   audio_report['last_append']={**audio,'converted':[str(addon/Path(s).relative_to(staged)) for s in audio['converted']],'registration':str(manifest)}
   save(work/'audio_conversion.json',audio_report);tx.put(work/'audio_conversion.json',reports/'audio_conversion.json')
  if a.compile:
   targets=([addon/Path(src).relative_to(staged) for src in audio['converted']]+[manifest] if audio else [])+[vmdl]
   for i,target in enumerate(targets):
    rel=target.relative_to(addon);ext='.vsnd_c' if rel.suffix=='.wav' else rel.suffix+'_c';compiled=root/'game/csgo_addons'/addon.name/rel.with_suffix(ext)
    tx.capture(compiled)
    item=compile_resource(addon,target,reports/f'append_compile_{i:04d}.log');result['compiled'].append(item)
    if not item['passed']:raise RuntimeError('追加动画编译失败：'+item['log'])
   run([sys.executable,SCRIPTS/'cs2_verify_compiled.py','--addon',addon,'--name',name,'--all-frames'])
   result['compiled_validation']=read(reports/'compiled_validation.json')
   if audio:
    result['audio_validation']=verify_compiled(addon,name,updated,manifest.read_text('utf-8'))
    if not result['audio_validation']['passed']:raise ValueError('追加声音事件回读失败')
  if not all(sha(Path(f))==h for f,h in protected.items()):raise ValueError('未选择动作/模型/材质被修改')
  commit_package(tx,work,p);result.update(passed=True,total_actions=len(merged['actions']),protected_files_unchanged=True,runtime_validation='not_run')
 except BaseException as e:
  tx.rollback();result['error']=str(e);result['rolled_back']=True;save(reports/'append_animations.json',result);raise
 save(reports/'append_animations.json',result);save(p/'append_cs2_report.json',result);print('APPEND_CS2_DONE',result['added'],result['replaced'],flush=True)

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--package',required=True,type=Path);ap.add_argument('--clips',required=True,type=Path);ap.add_argument('--worker',required=True);ap.add_argument('--game',default='');ap.add_argument('--blender',required=True);ap.add_argument('--cache',required=True,type=Path);ap.add_argument('--blend',type=Path);ap.add_argument('--addon',type=Path);ap.add_argument('--name',default='wolf');ap.add_argument('--compile',action='store_true');ap.add_argument('--audio',action='store_true');ap.add_argument('--ffmpeg');ap.add_argument('--dsas');ap.add_argument('--audio-volumes',type=Path);ap.add_argument('--root-options',type=Path);ap.add_argument('--motion-axes',default='xy');a=ap.parse_args()
 selected=read(a.clips)
 if not selected or not isinstance(selected,list) or len(selected)!=len(set(selected)):raise ValueError('请选择需要新增/覆盖的动作')
 if bool(a.blend)==bool(a.addon):raise ValueError('请选择 Blender 或 CS2 其中一个目标')
 import re
 if a.addon and not re.fullmatch('[a-z][a-z0-9_]*',a.name):raise ValueError('无效模型名')
 work=stage(a.package,a.cache,a.worker,a.game,selected)
 if a.blend:append_blend(a,work,selected)
 else:append_cs2(a,work,selected)
 # Success only; failures retain task cache for diagnosis. No broad deletion.
 if work.parent!=a.cache.resolve() or not work.name.startswith('append_') or work.is_symlink():raise ValueError('Unexpected task cache path')
 shutil.rmtree(work)
if __name__=='__main__':main()
