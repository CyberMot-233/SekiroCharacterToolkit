import json,sys,argparse,subprocess,shutil,struct
from pathlib import Path
from prepare_textures import main as textures
def main():
 a=argparse.ArgumentParser();a.add_argument('--package',required=True);a.add_argument('--worker',required=True);a.add_argument('--left',type=int,default=73000);a=a.parse_args()
 p=Path(a.package);pkg=json.loads((p/'package.json').read_text('utf-8-sig'));root=pkg['root'];w=p/'equipment';w.mkdir(exist_ok=True)
 if pkg['character']!='c0000':raise ValueError('Wolf equipment profile requires c0000; do not apply to NPCs')
 subprocess.run([a.worker,'params','--root',root,'--out',str(w)],check=True)
 rows={x['id']:x for x in json.loads((w/'EquipParamWeapon.param.json').read_text('utf-8-sig'))};slots={'R':8000000,'L':a.left,'MB':9700000,'GH':9500000};tags=[]
 for slot,eid in slots.items():
  model=struct.unpack_from('<h',bytes.fromhex(rows[eid]['raw']),0xB8)[0];part=f'wp_a_{model:04d}';dest=w/part
  subprocess.run([a.worker,'part','--root',root,'--part',part,'--out',str(dest)],check=True);textures(dest)
  data=json.loads((dest/'package.json').read_text('utf-8-sig'));motions=json.loads((dest/'weapon_motion.json').read_text('utf-8-sig'))
  for key,rel in data['textures'].items():
   pkg['textures'][key]=(dest/rel).relative_to(p).as_posix()
  for rel in data['models']:
   stem=Path(rel).name.removesuffix('.flver.json');index=int(stem.rsplit('_',1)[1]) if len(stem.split('_'))>3 else 0
   shutil.copy2(dest/rel,w/(stem+'.json'));motion=motions.get(stem.lower())
   if motion:(w/(stem+'.motion.json')).write_text(json.dumps(motion),encoding='utf-8')
   tags.append([stem,slot,index])
 shutil.copy2(p/'tae.json',w/'character_tae.json')
 body=next(x for x in pkg['models'] if 'c0000' in x);shutil.copy2(p/body,w/'c0000.json')
 (w/'profile.json').write_text(json.dumps({'slots':slots,'tags':tags,'source':'DSAS RC6.1 PARAM + TAE 32/710/715','limitations':['Cross-clip combo history, procedural grappling chain and dynamics are not included']}),encoding='utf-8')
 (p/'package.json').write_text(json.dumps(pkg),encoding='utf-8')
 print('EQUIPMENT_READY',tags,flush=True)
if __name__=='__main__':main()
