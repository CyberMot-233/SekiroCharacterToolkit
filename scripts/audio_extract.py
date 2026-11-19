"""Resolve TAE identities, enumerate full FEV event names, render MP3 with native FMOD."""
import os,sys,json,csv,re,struct,collections,subprocess,shutil,hashlib,argparse,wave,array
from pathlib import Path
from event_states import EventStateDatabase,anim_key
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def database(p):
 db=EventStateDatabase.__new__(EventStateDatabase);db.animations={};db._resolved={};db.hkx_to_tae=collections.defaultdict(list);db.reference_errors=[]
 for cat in read(p/'tae.json'):
  m=re.search(r'a([0-9]+)[.]tae$',cat['name'],re.I);namespace=int(m[1]) if m else 0
  for a in cat['animations']:
   aid=a['id']+namespace*1000000 if a['id']<1000000 else a['id'];key=anim_key(aid);db.animations[key]={**a,'key':key}
 for key in db.animations:
  try:db.hkx_to_tae[db._solve_tae(key)['hkx_key']].append(key)
  except ValueError as e:db.reference_errors.append(str(e))
 return db
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cache');ap.add_argument('--package',required=True);ap.add_argument('--root',required=True);ap.add_argument('--dsas',required=True);ap.add_argument('--ffmpeg',required=True);ap.add_argument('--language',default='jajp');ap.add_argument('--render',action='store_true');ap.add_argument('--limit',type=int,default=0);ap.add_argument('--clip-list',type=Path);a=ap.parse_args()
 p=Path(a.package).resolve();a.root=str(Path(a.root).resolve());a.dsas=str(Path(a.dsas).resolve());a.ffmpeg=str(Path(a.ffmpeg).resolve());out=p/'audio';out.mkdir(exist_ok=True);sound=Path(a.root)/'sound';pkg=read(p/'package.json');db=database(p)
 if a.clip_list:
  chosen=set(read(a.clip_list));pkg['clips']=[c for c in pkg['clips'] if c['name'] in chosen]
 from audio_cache import stage_banks,archive_banks
 cache=a.cache or os.environ.get('SCT_AUDIO_CACHE') or str(Path(__file__).resolve().parents[1]/'cache')
 stage=stage_banks(sound,cache)
 # FMOD only sees ASCII relative filenames. Windows itself changes cwd via Unicode.
 os.chdir(stage)
 os.environ.update(SCT_AUDIO_STAGE='.',SCT_DSAS=a.dsas,SCT_SOUND=str(sound.resolve()),SCT_LANGUAGE=a.language)
 print('AUDIO_CACHE',stage,flush=True)
 from fmod_probe import enumerate_events
 enumerate_events();lookup=collections.defaultdict(list)
 for e in read(stage/'fmod_events.json')['events']:lookup[e['name']].append(e)
 report={'passed':False,'settings':{'language':a.language,'floor_material':1,'armor_material':0,'volume_gain':.125,'mp3_bitrate':'192k','sample_rate':48000,'random_choice':'one native render, not all variants'},'events':{},'unresolved':[],'errors':list(db.reference_errors),'limited':bool(a.limit)}
 prefix={0:'a',1:'c',2:'f',3:'o',4:'p',5:'s',6:'m',7:'v',8:'c',9:'c',10:'g'};rows=[];mappings=[]
 for clip in pkg['clips']:
  resolution=db.resolve_action(clip['name'],key_kind='hkx');mappings.append(resolution)
  if resolution['ambiguous']:report['errors'].append({'action':clip['name'],'error':'ambiguous TAE identity'});continue
  for index,e in enumerate(db.animations.get(resolution['source_tae_key'],{}).get('events',[])):
   if e['type'] not in (128,129,130,131,132):continue
   raw=bytes.fromhex(e['raw'])
   if len(raw)<8:report['errors'].append({'action':clip['name'],'event':index,'error':'sound payload truncated'});continue
   st,sid=struct.unpack_from('<ii',raw);name=f'{prefix[st]}{sid:09d}' if st in prefix and sid>=0 else ''
   rows.append({'action':clip['name'],'source_tae':resolution['source_tae_key'],'event_index':index,'event_type':e['type'],'start_seconds':e['start'],'end_seconds':e['end'],'sound_type':st,'sound_id':sid,'event':name,'status':'not_rendered','mp3':''})
 save(out/'action_resolution.json',mappings);needed=sorted({r['event'] for r in rows if r['event']});selected=needed[:a.limit] if a.limit else needed
 if a.render:
  from fmod_render import render
  for name in selected:
   hits=lookup.get(name,[])
   # Use the active model/animation bank context, not all other character projects.
   # Full event names can legitimately repeat in unrelated FEV projects.
   if len(hits)>1:
    for bank in [pkg['character']+'.fev',pkg['animationSource']+'.fev','main.fev']:
     scoped=[h for h in hits if h['bank'].lower()==bank.lower()]
     if scoped:hits=scoped;break
   if len(hits)!=1:report['unresolved'].append({'event':name,'reason':'missing' if not hits else 'ambiguous','candidates':hits});continue
   entry=hits[0];wav=Path(name+'_'+str(os.getpid())+'.wav');mp3=out/'native_events'/(name+'.mp3');mp3.parent.mkdir(exist_ok=True)
   try:
    stats=render(entry,wav)
    with wave.open(str(wav),'rb') as f:stats.update(channels=f.getnchannels(),rate=f.getframerate(),frames=f.getnframes());pcm=array.array('h',f.readframes(f.getnframes()))
    stats['peak_pcm16']=max(map(abs,pcm),default=0)
    subprocess.run([a.ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(wav),'-codec:a','libmp3lame','-b:a','192k',str(mp3)],check=True)
    report['events'][name]={**entry,**stats,'mp3':mp3.relative_to(out).as_posix(),'sha256':hashlib.sha256(mp3.read_bytes()).hexdigest()};print('MP3',name,stats['peak_pcm16'],flush=True)
   except Exception as e:report['errors'].append({'event':name,'error':str(e)})
   finally:
    if wav.exists():wav.unlink()
   save(out/'audio_report.json',report)
 for r in rows:
  hit=report['events'].get(r['event']);r['status']='rendered' if hit else ('missing_or_unrendered');r['mp3']=hit['mp3'] if hit else ''
  if hit and hit['peak_pcm16']==0:r['status']='native_silent'
  if hit:
   dst=out/'by_action'/r['action']/f"{r['event_index']:04d}_{r['start_seconds']:.5f}_{r['event']}.mp3";dst.parent.mkdir(parents=True,exist_ok=True)
   if dst.exists():dst.unlink()
   try:os.link(out/hit['mp3'],dst)
   except OSError:shutil.copy2(out/hit['mp3'],dst)
 fields=['action','source_tae','event_index','event_type','start_seconds','end_seconds','sound_type','sound_id','event','status','mp3']
 def csvwrite(file,items):
  file.parent.mkdir(parents=True,exist_ok=True)
  with file.open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(items)
 csvwrite(out/'action_sounds.csv',rows)
 for clip in pkg['clips']:csvwrite(out/'by_action'/clip['name']/'events.csv',[r for r in rows if r['action']==clip['name']])
 # Preserve original banks separately, including parameterized and random variants.
 manifest=archive_banks(sound,stage,out)
 save(out/'source_manifest.json',manifest);report.update(actions=len(pkg['clips']),selected_events=len(rows),needed_events=len(needed),rendered_events=len(report['events']));report['passed']=a.render and not report['errors'] and not report['unresolved'] and len(report['events'])==len(needed)
 save(out/'audio_report.json',report);print('AUDIO_DONE',report['rendered_events'],'MP3; unresolved',len(report['unresolved']),flush=True)
if __name__=='__main__':main()
