"""Per-action sound events, MP3 delivery, PCM source WAV and addon registration."""
import csv,collections,subprocess,datetime,hashlib,re,wave,struct
from pathlib import Path
from cs2_common import read,save,kv,HEADER,SoundEvent,safe_name,bone_name

def export_audio(package,addon,name,ffmpeg,actions,export=None,volumes=None):
 p=Path(package);addon=Path(addon);name=safe_name(name);csvpath=p/'audio/action_sounds.csv'
 if not csvpath.exists():raise FileNotFoundError('先在导出页提取动作音频，缺少 '+str(csvpath))
 clips={a['source']:a for a in actions};report={'passed':False,'converted':[],'unresolved':[],'outside_clip':[],'native_silent':[],'source_format':'MP3 192kbps','cs2_source_format':'PCM S16LE 48000 Hz mono','registration':None,'missing_attachments':[]}
 from audio_extract import database
 tae=database(p)
 exported=export or read(addon/f'rawmodels/sekiro/characters/{name}/export_report.json');bone_names={b['name'] for b in exported['bones']}
 attachments=build_attachments(p,exported);attachment_names={a['name'] for a in attachments};report['attachments']=attachments
 rows=list(csv.DictReader(csvpath.open(encoding='utf-8-sig',newline='')));rows=[r for r in rows if r['action'] in clips]
 base=f'sounds/sekiro/characters/{name}';dst=addon/base;dst.mkdir(parents=True,exist_ok=True);definitions={};events=collections.defaultdict(list)
 for event in sorted(set(r['event'] for r in rows if r['mp3'])):
  r=next(r for r in rows if r['event']==event and r['mp3']);source=p/'audio'/r['mp3'];wav=dst/(event+'.wav');hashfile=wav.with_suffix('.source.sha256');digest=hashlib.sha256(source.read_bytes()).hexdigest()
  if not wav.exists() or not hashfile.exists() or hashfile.read_text()!=digest:
   # These inputs are MP3 emitted by our renderer. Quiet/transient clips may
   # receive a higher unrelated-video probe score in newer FFmpeg releases.
   subprocess.run([str(ffmpeg),'-nostdin','-hide_banner','-loglevel','error','-y','-f','mp3','-i',str(source),'-map','0:a:0','-ac','1','-ar','48000','-c:a','pcm_s16le',str(wav)],check=True);hashfile.write_text(digest)
  with wave.open(str(wav),'rb') as w:duration=w.getnframes()/w.getframerate()
  eventname=f'sekiro.{name}.{event}'
  definitions[eventname]=dict(type='csgo_mega',volume=1.0,pitch=1.0,mixgroup='Ambient',block_matching_events=False,block_match_entity=False,block_duration=0.0,block_distance=0.0,position_relative_to_player=False,vsnd_files_track_01=f'{base}/{event}.vsnd',distance_volume_mapping_curve=[[64.0,1.0,0.0,0.0,2.0,3.0],[2000.0,0.0,0.0,0.0,1.0,1.0]],vsnd_duration=duration)
  report['converted'].append(str(wav))
 for r in rows:
  if not r['mp3']:
   report['unresolved'].append(r);continue
  if r['status']=='native_silent':report['native_silent'].append(r)
  clip=clips[r['action']];time=float(r['start_seconds']);frame=int(time*clip['fps']+.5)
  if time<0 or time>clip['duration']+1e-4:
   report['outside_clip'].append(r);continue
  frame=min(frame,clip['frames']-1)
  attachment='sct_body' if 'sct_body' in attachment_names else 'sct_origin'
  kind=int(r['event_type']);source_events=tae.animations.get(r['source_tae'],{}).get('events',[]);event_index=int(r['event_index']);raw=bytes.fromhex(source_events[event_index]['raw']) if event_index<len(source_events) else b''
  if kind in (129,130,131) and len(raw)>=12:
   dummy=struct.unpack_from('<i',raw,8)[0];candidate='sct_dummy_'+str(dummy)
   if candidate in attachment_names:attachment=candidate
   elif dummy>=0:report['missing_attachments'].append({'action':r['action'],'dummy':dummy,'fallback':attachment})
  elif kind==132 and 'sct_weapon' in attachment_names:attachment='sct_weapon'
  events[r['action']].append(dict(_class='AnimEvent',event_class='AE_CL_PLAYSOUND_ATTACHMENT',event_frame=frame,event_end_frame=-1,event_keys=dict(name=SoundEvent(f'sekiro.{name}.{r["event"]}'),attachment=attachment,stop_on_seq_change=False,use_layer_sequence=False,tags=None)))
 from cs2_audio_volume import apply_export,alias_block
 apply_export(events,definitions,actions,volumes or {},name)
 volume_definitions={k:v for k,v in definitions.items() if k.startswith(f'sekiro.{name}.sctvol_')}
 definitions={k:v for k,v in definitions.items() if k not in volume_definitions}
 report['animation_volumes']={a['source']:volumes[a['source']] for a in actions if volumes and a['source'] in volumes}
 manifest=addon/'soundevents/soundevents_addon.vsndevts';manifest.parent.mkdir(parents=True,exist_ok=True)
 original=manifest.read_text('utf-8-sig') if manifest.exists() else HEADER+'\n{\n}\n'
 begin=f'// SCT BEGIN {name}';end=f'// SCT END {name}'
 content='\n'+begin+'\n'+'\n'.join('"'+n+'" = '+kv(v) for n,v in definitions.items())+'\n'+end+'\n'
 if begin in original:
  pattern=re.escape(begin)+'.*?'+re.escape(end);updated=re.sub(pattern,lambda m:content.strip(),original,flags=re.S)
 else:
  ix=original.rfind('}')
  if ix<0:raise ValueError('soundevents_addon.vsndevts 缺少结束括号，保留原件不修改')
  updated=original[:ix]+content+original[ix:]
 if volume_definitions:updated=alias_block(updated,name,volume_definitions)
 if original!=updated:
  if manifest.exists():
   backup=p/'cs2_backups'/('soundevents_addon_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.vsndevts');backup.parent.mkdir(parents=True,exist_ok=True);backup.write_text(original,'utf-8')
   report['backup']=str(backup)
  manifest.write_text(updated,'utf-8')
 report['registration']=str(manifest);report['events']=sum(map(len,events.values()));report['passed']=not report['unresolved']
 report['attachment_scope']='TAE 129/130/131 DummyPolyID offset +8 -> FLVER attachment; type128 torso and type132 right weapon; missing IDs recorded'
 out=addon/f'rawmodels/sekiro/characters/{name}/reports';save(out/'audio_conversion.json',report)
 return events,report

def build_attachments(package,export):
 import numpy as np
 from internal_fk_verified import DEFAULT_C as C,_quaternion_matrices
 p=Path(package);pkg=read(p/'package.json');names={b['name'] for b in export['bones']};world={}
 for b in export['bones']:
  m=_quaternion_matrices(np.array(b['rot']));m[:3,3]=np.array(b['pos'])/39.37007874015748;world[b['name']]=world[export['bones'][b['parent']]['name']]@m if b['parent']>=0 else m
 result=[];seen=set()
 def add(name,bone,pos):
  if bone not in names or name in seen:return
  result.append(dict(_class='Attachment',name=name,parent_bone=bone,relative_origin=list(map(float,pos)),relative_angles=[0.0,0.0,0.0],weight=1.0,ignore_rotation=False));seen.add(name)
 add('sct_body','Spine2',[0,0,0]);add('sct_weapon','DSAS_R0',[0,0,0])
 for file in pkg['models']:
  model=read(p/file)
  for d in model.get('dummies',[]):
   bone=bone_name(model['nodes'][d['attach']]['name'] if d['attach']>=0 and d['follow'] else (model['nodes'][d['parent']]['name'] if d['parent']>=0 else 'sct_motion'))
   if bone not in names:continue
   parent=C@np.array(model['nodes'][d['parent']]['world']).reshape(4,4).T@C.T if d['parent']>=0 else np.eye(4);frame=C@np.array(d['frame']).reshape(4,4).T@C.T
   local=np.linalg.inv(world[bone])@parent@frame;add('sct_dummy_'+str(d['id']),bone,local[:3,3]*39.37007874015748)
 return result
