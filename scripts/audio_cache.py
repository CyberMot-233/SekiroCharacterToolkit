"""User-selected shared native audio cache; never default to the system drive."""
import hashlib,json,os,shutil
from pathlib import Path
_LOCKS=[]

def sha(file):
 with Path(file).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def free_space(directory,required):
 free=shutil.disk_usage(directory).free
 if free<required+128*1024*1024:
  raise OSError(f'缓存/输出磁盘空间不足：{directory}，需要约 {required/1024**3:.2f} GiB，剩余 {free/1024**3:.2f} GiB；请在工具链设置更换缓存目录。')

def stage_banks(sound,cache):
 sound=Path(sound).resolve();base=Path(cache).resolve();base.mkdir(parents=True,exist_ok=True)
 stage=base/'audio'/hashlib.sha256(str(sound).encode()).hexdigest()[:16];stage.mkdir(parents=True,exist_ok=True)
 import msvcrt
 lock=(stage/'cache.lock').open('a+b');lock.seek(0)
 try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 except OSError:
  lock.close();raise RuntimeError('音频缓存正在被另一个任务使用，请稍后重试或选择另一个缓存目录。')
 _LOCKS.append(lock)
 banks=[f for f in sound.iterdir() if f.suffix.lower() in ('.fsb','.fev','.itl')]
 needed=[f for f in banks if not (stage/f.name).exists() or (stage/f.name).stat().st_size!=f.stat().st_size or (stage/f.name).stat().st_mtime_ns!=f.stat().st_mtime_ns]
 # Shared independent copies: output hard links must never alias original game files.
 free_space(stage,sum(f.stat().st_size for f in needed))
 for source in needed:
  dest=stage/source.name;temp=stage/(source.name+'.partial')
  try:
   shutil.copy2(source,temp)
   if sha(source)!=sha(temp):raise IOError('Audio cache copy hash mismatch: '+source.name)
   os.replace(temp,dest)
  except BaseException:
   if temp.exists():temp.unlink()
   raise
 (stage/'cache_source.json').write_text(json.dumps({'source':str(sound),'mode':'shared independent bank copies','files':len(banks)},ensure_ascii=False,indent=2),encoding='utf-8')
 return stage

def archive_banks(sound,stage,out):
 records=[]
 for source in sorted(Path(sound).iterdir()):
  if source.suffix.lower() not in ('.fsb','.fev','.itl'):continue
  snapshot=stage/source.name;dest=out/'source_native'/source.name;dest.parent.mkdir(parents=True,exist_ok=True);digest=sha(snapshot)
  if not dest.exists() or dest.stat().st_size!=snapshot.stat().st_size or sha(dest)!=digest:
   temp=dest.with_name(dest.name+'.partial')
   if temp.exists():temp.unlink()
   try:os.link(snapshot,temp);mode='shared-cache-hardlink'
   except OSError:
    free_space(dest.parent,snapshot.stat().st_size);shutil.copy2(snapshot,temp);mode='copy'
   os.replace(temp,dest)
  else:mode='verified-existing'
  records.append({'file':source.name,'bytes':source.stat().st_size,'sha256':digest,'storage':mode})
 return records
