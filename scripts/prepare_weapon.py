"""Namespaced submodel rigs prevent collisions between weapon variants."""
import json,sys,array
from pathlib import Path
p=Path(sys.argv[1]);pkg=json.loads((p/'package.json').read_text('utf-8-sig'))
if pkg.get('weaponPrepared'):sys.exit(0)
motions=json.loads((p/'weapon_motion.json').read_text('utf-8-sig'));skeleton=[];clips=[]
for rel in pkg['models']:
 m=json.loads((p/rel).read_text('utf-8'));tag=Path(rel).name.removesuffix('.flver.json');prefix=tag+'::';motion=motions.get(tag.lower(),motions.get(tag.lower().removesuffix('_m').removesuffix('_l'),{}));base=len(skeleton)
 for n in m['nodes']:n['name']=prefix+n['name']
 (p/rel).write_text(json.dumps(m),encoding='utf-8')
 for b in motion.get('bones',[]):skeleton.append({'name':prefix+b['name'],'parent':base+b['parent'] if b['parent']>=0 else -1,'trs':b['t'][:3]+b['q']+b['s'][:3]})
 for a in motion.get('animations',[]):
  out='animations/'+tag+'_'+a['name']+'.bin';(p/out).parent.mkdir(exist_ok=True);flat=array.array('f',(v for frame in a['frames'] for track in frame for v in track));(p/out).write_bytes(flat.tobytes())
  clips.append({'name':tag+'/'+a['name'],'file':out,'frames':len(a['frames']),'map':[base+x for x in a['map']],'duration':a['duration'],'dt':a['frameDuration'],'sampling':a.get('sampling','legacy'),'rootMotion':{'hasReference':False,'samples':[[0,0,0,0,1,0,0,0],[a['duration'],0,0,0,1,0,0,0]]}})
pkg.update(skeleton=skeleton,clips=clips,weaponPrepared=True);(p/'package.json').write_text(json.dumps(pkg),encoding='utf-8');print('WEAPON_PREPARED',len(clips),'actions')
