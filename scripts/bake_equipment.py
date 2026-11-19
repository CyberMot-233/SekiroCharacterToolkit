"""Equipment adapter for the generic affine character rig, based on verified RC6.1."""
import json,math
from pathlib import Path
import bpy,numpy as np
from mathutils import Matrix
import equipment_core as E
from affine_factor import factor_affine
def prepare(folder,arm,rig_names,make_material,direct=False,existing=False):
 p=Path(folder);w=p/'equipment';profile=json.loads((w/'profile.json').read_text('utf-8'));E.W=w;E.TAGS=[tuple(x) for x in profile['tags']];E.ES.SLOT_EQUIP_IDS=profile['slots']
 E.newmaterial=lambda tag,mat,oldmats,texout:make_material(mat)
 weapons=[E.Weapon(*tag) for tag in E.TAGS]
 if existing:
  for wp in weapons:
   for n in [wp.root,wp.root+'__AFFINE',*wp.bn.values()]:
    if n not in arm.data.bones:raise ValueError('已有工程缺少装备骨：'+n)
   wp.blref={i:arm.data.bones[wp.bn[i]].matrix_local.copy() for i in wp.used}
   wp.blinv={i:m.inverted() for i,m in wp.blref.items()};wp.rel_inv=dict(wp.blinv)
 else:E.build_rigs(arm,weapons,p/'textures/png_rgb')
 db=E.ES.EventStateDatabase(w)
 character=E.J(w/'c0000.json');dummies={}
 for d in character['dummies']:dummies.setdefault(d['id'],d)
 used={character['nodes'][d[k]]['name'] for d in dummies.values() for k in ('parent','attach') if 0<=d[k]<len(character['nodes'])}
 pc=None if direct else E.PoseCache(arm,[rig_names[n][1] for n in used if n in rig_names]);refs=[np.array(E.rowmatrix(n['world'])) for n in character['nodes']];report={'actions':[],'issues':[],'limitations':profile['limitations'],'max_affine_error':0.0}
 def bake_action(action,skin=None):
  duration=action['source_duration'];fps=action['source_fps'];resolution=db.resolve_action(action.name,key_kind='hkx')
  if resolution.get('ambiguous'):report['issues'].append({'action':action.name,'error':'Ambiguous TAE identity; equipment not guessed'});return
  taeid=E.fullid(resolution['tae_key']) if resolution.get('tae_key') else E.fullid(action.name)
  events=db.animations.get(resolution.get('source_tae_key'),{}).get('events',[]);byframe={}
  for t in list(np.arange(0,duration,1/240))+[duration]:byframe[float(np.float32(1+t*30))]=t
  for ev in events:
   if ev['type'] in (32,710,715):
    for t in (ev['start'],ev['end']):
     for v in [max(0,t-1e-5),min(duration,t+1e-5),t]:
      if 0<=v<=duration:byframe[float(np.float32(1+v*30))]=v
  frames=np.array(sorted(byframe));times=np.array([byframe[f] for f in frames]);states=[db.get_state(action.name,float(t),key_kind='hkx') for t in times];poses=pc.evaluate(action,frames) if pc else {rig_names[n][1]:skin(n,frames) for n in used if n in rig_names};cache={}
  def dummy(rid):
   if rid in cache:return cache[rid]
   d=dummies[rid];m=np.broadcast_to(np.eye(4),(len(times),4,4)).copy()
   if d['parent']>=0:
    name=character['nodes'][d['parent']]['name'];bn=rig_names.get(name,('',None))[1];ref=refs[d['parent']];m=(poses[bn]@pc.inv[bn] if pc else poses[bn])@ref if bn in poses else np.broadcast_to(ref,m.shape).copy()
   m=m@np.array(E.rowmatrix(d['frame']))
   if d['attach']>=0 and d['follow']:
    name=character['nodes'][d['attach']]['name'];bn=rig_names.get(name,('',None))[1]
    if bn in poses:m=(poses[bn]@pc.inv[bn] if pc else poses[bn])@m
   cache[rid]=m;return m
  rec={'action':action.name,'samples':len(frames),'weapons':{}}
  for wp in weapons:
   ss=[s['slots'][wp.slot][wp.index] for s in states];ids=[s['dummy'] for s in ss];visible=np.array([s['visible'] and s['dummy'] in dummies for s in ss]);mats=np.array([dummy(rid)[k] if rid in dummies else np.eye(4) for k,rid in enumerate(ids)])
   outer,inner=factor_affine(mats);report['max_affine_error']=max(report['max_affine_error'],float(np.max(np.abs(outer@inner-mats))))
   loc,q,scale=E.decomp_many([Matrix(m) for m in outer]);scale*=visible[:,None];E.write_trs(action,wp.root+'__AFFINE',frames,loc,q,scale)
   loc,q,scale=E.decomp_many([Matrix(m) for m in inner]);E.write_trs(action,wp.root,frames,loc,q,scale)
   internal,aid=wp.internal(taeid,times)
   for i in wp.used:
    basis=[wp.rel_inv[i]@m@wp.refinv[i]@wp.blref[i] for m in internal[i]];loc,q,scale=E.decomp_many(basis);E.write_trs(action,wp.bn[i],frames,loc,q,scale)
   rec['weapons'][wp.tag]={'dummies':sorted(set(ids)),'visible_samples':int(visible.sum()),'internal_hkx':aid}
  report['actions'].append(rec);print('EQUIPMENT_BAKED',len(report['actions']),action.name,flush=True)
 def finish():
  report['passed']=not report['issues'] and report['max_affine_error']<1e-5
  (p/'equipment_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return report
 bake_action.report=report
 return bake_action,finish

def bake(folder,arm,rig_names,make_material):
 run,finish=prepare(folder,arm,rig_names,make_material)
 for action in list(bpy.data.actions):run(action)
 return finish()
