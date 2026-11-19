"""Small shared staging/transaction helpers for incremental animation work."""
import datetime, hashlib, os, shutil, subprocess, uuid
from pathlib import Path
from cs2_common import read, save

SCRIPTS=Path(__file__).resolve().parent
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(args):
 print('APPEND_RUN',*map(str,args),flush=True);subprocess.run(list(map(str,args)),check=True)
def blend(exe,script,*args):
 run([exe,'--background','--factory-startup','--disable-autoexec','--threads','4','--python-exit-code','1','--python',SCRIPTS/'blender_bootstrap.py','--python',SCRIPTS/script,'--',*args])
def stage(package,cache,worker,game,selected):
 p=Path(package).resolve();pkg=read(p/'package.json');dest=Path(cache).resolve()/('append_'+uuid.uuid4().hex);dest.mkdir(parents=True)
 for folder in ('models','animations','textures','_internal/rgba','equipment','source_native'):
  for f in (p/folder).rglob('*'):
   if not f.is_file() or 'backups' in f.parts or f.suffix in ('.blend','.blend1','.log'):continue
   out=dest/f.relative_to(p);out.parent.mkdir(parents=True,exist_ok=True)
   try:os.link(f,out)
   except OSError:shutil.copy2(f,out)
 for file in ('package.json','tae.json','weapon_motion.json','root_motion_options.json','source_manifest.json'):
  if (p/file).exists():shutil.copy2(p/file,dest/file)
 save(dest/'selected.json',selected)
 missing=set(selected)-{c['name'] for c in pkg['clips']}
 # Decode only selected clips when archives/game are available. An existing
 # sampled clip remains usable offline if its original binder was removed.
 source=Path(game or pkg.get('root',''))
 available=all((dest/'source_native/chr'/(n.split('/')[0]+'.anibnd.dcx')).exists() or (source/'chr'/(n.split('/')[0]+'.anibnd.dcx')).exists() for n in selected)
 if available:run([worker,'append-animations','--root',source,'--package',dest,'--clip-list',dest/'selected.json'])
 elif missing:raise FileNotFoundError('新增动作需要游戏解包目录或 source_native 动画包：'+', '.join(sorted(missing)))
 return dest

class Transaction:
 def __init__(self,backup):
  self.backup=Path(backup);self.backup.mkdir(parents=True);self.records=[]
 def capture(self,path):
  p=Path(path)
  if any(p==r[0] for r in self.records):return
  exists=p.exists();copy=self.backup/str(len(self.records))
  if exists:shutil.copy2(p,copy)
  self.records.append((p,copy,exists));save(self.backup/'index.json',[dict(path=str(p),backup=str(c),existed=e) for p,c,e in self.records])
 def put(self,source,dest):
  dest=Path(dest);self.capture(dest);dest.parent.mkdir(parents=True,exist_ok=True);pending=dest.with_name(dest.name+'.'+uuid.uuid4().hex+'.pending')
  try:shutil.copy2(source,pending);os.replace(pending,dest)
  finally:
   if pending.exists():pending.unlink()
 def rollback(self):
  for p,c,exists in reversed(self.records):
   if exists:shutil.copy2(c,p)
   elif p.is_file():p.unlink()

def commit_package(tx,stage,package):
 stage=Path(stage);p=Path(package);old=read(p/'package.json');new=read(stage/'package.json')
 for c in new['clips']:
  src=stage/c['file'];dst=p/c['file']
  if not dst.exists() or sha(src)!=sha(dst):tx.put(src,dst)
 for key in ('package.json','tae.json'):
  if sha(stage/key)!=sha(p/key):tx.put(stage/key,p/key)
 if (stage/'audio/action_sounds.csv').exists():
  import csv
  incoming=stage/'audio/action_sounds.csv';selected=set(read(stage/'selected.json'))
  with incoming.open(encoding='utf-8-sig',newline='') as f:
   reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
  existing=p/'audio/action_sounds.csv';oldrows=[]
  if existing.exists():
   with existing.open(encoding='utf-8-sig',newline='') as f:oldrows=[r for r in csv.DictReader(f) if r['action'] not in selected]
  output=stage/'merged_action_sounds.csv'
  with output.open('w',encoding='utf-8-sig',newline='') as f:
   writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(oldrows+rows)
  tx.put(output,existing)
  for row in rows:
   if row['mp3']:
    src=stage/'audio'/row['mp3'];dst=p/'audio'/row['mp3']
    if not dst.exists():tx.put(src,dst)
  for name in selected:
   for src in (stage/'audio/by_action'/name).rglob('*'):
    if src.is_file():tx.put(src,p/src.relative_to(stage))
  tx.put(stage/'audio/audio_report.json',p/'audio/append_audio_report.json')
