"""NPC default DrawMask and TAE 233/711/713 in the armature Action."""
from pathlib import Path
import numpy as np
from audio_extract import database
from npc_weapons import NpcWeaponPolicy

def states(default,events,time):
 result=list(default)
 for e in events:
  raw=bytes.fromhex(e['raw']);kind=e['type'];start=(float(np.float32(1+e['start']*30))-1)/30;end=(float(np.float32(1+e['end']*30))-1)/30
  if kind==233 and time>=start:
   for i,value in enumerate(raw[:32]):
    if value in (0,1):result[i]=bool(value)
  elif kind in (711,713) and start<=time<=end:
   for i,value in enumerate(raw[:32]):
    if value==1:result[i]=kind==713
 return result

class ModelMasks:
 def __init__(self,pkg,folder,arm):
  self.arm=arm;self.pkg=pkg;self.db=database(Path(folder)) if (Path(folder)/'tae.json').exists() else None
  selected=pkg.get('npcAppearance',{}).get('selected') or {};self.default=selected.get('drawMask',[True]*32)
  self.weapon_policy=NpcWeaponPolicy(pkg,folder)
  self.used=set();self.records=[]
 def bind(self,ob,mask):
  if mask<0 or mask>=32:return
  self.used.add(mask);key=f'sct_mask_{mask:02d}';self.arm[key]=float(self.default[mask])
  for prop in ('hide_render','hide_viewport'):
   driver=ob.driver_add(prop).driver;driver.type='SCRIPTED';v=driver.variables.new();v.name='visible';v.type='SINGLE_PROP';v.targets[0].id=self.arm;v.targets[0].data_path='["'+key+'"]';driver.expression='visible < 0.5'
 def events(self,clip):
  if self.db is None:return []
  resolution=self.db.resolve_action(clip['name'],key_kind='hkx')
  if resolution['ambiguous']:return []
  return [e for e in self.db.animations.get(resolution.get('source_tae_key'),{}).get('events',[]) if e['type'] in (233,711,713)]
 def bake(self,action,clip):
  if not self.used:return
  events=self.events(clip);last=np.float32(min(1+(clip['frames']-1)*clip['dt']*30,float(action.get('sct_trim_end',float('inf')))));frames={np.float32(1),last}
  for e in events:
   for t in [e['start'],e['end']]:
    f=np.float32(1+t*30)
    for x in [np.float32(f-.001),f,np.float32(f+.001)]:
     if 1<=x<=last:frames.add(x)
  default,evidence=self.weapon_policy.resolve(clip)
  frames=sorted(frames);values=[states(default,events,(float(f)-1)/30) for f in frames]
  for mask in sorted(self.used):
   key=f'sct_mask_{mask:02d}';points=[]
   for f,v in zip(frames,values):
    if not points or points[-1][1]!=float(v[mask]):points.append([f,float(v[mask])])
   fc=action.fcurves.new('["'+key+'"]',action_group='NPC model visibility');fc.keyframe_points.add(len(points));fc.keyframe_points.foreach_set('co',np.array(points,dtype=np.float32).ravel())
   for k in fc.keyframe_points:k.interpolation='CONSTANT'
   # Never update(): Blender merges close event-boundary keys.
  self.records.append({'action':clip['name'],'events':len(events),'keys_per_mask':len(frames),'weapon_policy':evidence})
