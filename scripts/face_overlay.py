"""Apply DSAS 607 Normal face slot to local HKX channels before FK, not global TRS."""
import json,struct,re
from pathlib import Path
import numpy as np
from audio_extract import database
from face_simulation import NativeFaceSource,parse_face_events,simulate_faces
class FaceOverlay:
 def __init__(self,pkg,p):
  self.pkg=pkg;self.p=Path(p);self.sources={};self.durations={};self.db=database(self.p) if (self.p/'tae.json').exists() else None
  sk=pkg['skeleton'] or [];names=[b['name'] for b in sk];self.mask=[]
  if 'face_root' not in names:return
  root=names.index('face_root')
  for i,b in enumerate(sk):
   parent=b['parent'];seen=set()
   while parent>=0 and parent not in seen:
    if parent==root:self.mask.append(i);break
    seen.add(parent);parent=sk[parent]['parent']
  self.clips={}
  for clip in pkg.get('_face_source_clips',pkg['clips']):
   match=re.search(r'a([0-9]+)_([0-9]{6})',clip['name'])
   if match:self.clips[int(match[1])*1000000+int(match[2])]=clip
 def apply(self,clip,local,report):
  if self.db is None or not self.mask:return local
  res=self.db.resolve_action(clip['name'],key_kind='hkx')
  if res['ambiguous']:report['issues'].append({'stage':'face','action':clip['name'],'error':'ambiguous TAE identity'});return local
  rec=self.db.animations.get(res.get('source_tae_key'),{});events=parse_face_events(rec,clip['dt'])
  if not events:return local
  for e in events:
   key=e['target']
   if key in self.sources:continue
   target=self.db._solve_tae(f'a{key//1000000:03d}_{key%1000000:06d}')
   m=re.search(r'a([0-9]+)_([0-9]{6})',target['hkx_key']);hkx=int(m[1])*1000000+int(m[2]);source=self.clips.get(hkx)
   if source is None:report['issues'].append({'stage':'face','action':clip['name'],'error':'Missing face HKX '+str(hkx)});continue
   sk=self.pkg['skeleton'];raw=np.fromfile(self.p/source['file'],dtype='<f4').reshape(source['frames'],len(source['map']),10);values=np.broadcast_to(np.array([b['trs'] for b in sk]),(source['frames'],len(sk),10)).copy()
   for ti,bi in enumerate(source['map']):values[:,bi]=raw[:,ti]
   values=values[:,self.mask].copy();values[:,:,3:7]=values[:,:,[6,3,4,5]]
   self.sources[key]=NativeFaceSource(values,source['duration'],source['dt'],source['name'])
   record=self.db.animations.get(target['source_tae_key'],{});blend=next((ev for ev in record.get('events',[]) if ev['type']==16),None);self.durations[key]=blend['end']-blend['start'] if blend else 0
  if any(e['target'] not in self.sources for e in events):return local
  base=local[:,self.mask].copy();base[:,:,3:7]=base[:,:,[6,3,4,5]];result,stats=simulate_faces(base,events,clip['dt'],self.sources,self.durations);result[:,:,3:7]=result[:,:,[4,5,6,3]];local[:,self.mask]=result
  report.setdefault('face_overlay',[]).append({'action':clip['name'],'mask_bones':len(self.mask),**stats});return local
