"""Serial native/Blender export for every wp_* part, with per-part failures retained."""
import argparse,json,subprocess,sys,time
from pathlib import Path
def main():
 a=argparse.ArgumentParser();a.add_argument('--root',required=True);a.add_argument('--worker',required=True);a.add_argument('--out',required=True);a.add_argument('--blender');a.add_argument('--ids');a.add_argument('--dsas');a.add_argument('--clean-bones',action='store_true');a.add_argument('--hierarchy',action='store_true');a.add_argument('--helper-visibility',choices=['visible','hidden'],default='visible');a=a.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True);scripts=Path(__file__).parent
 if (out/'batch_report.json').exists():raise ValueError('Existing batch output: choose a new directory')
 subprocess.run([a.worker,'weapons','--root',a.root,'--out',str(out/'weapons.json')],check=True);rows=json.loads((out/'weapons.json').read_text('utf-8-sig'))['weapons'];rows=[r for r in rows if not a.ids or r['id'] in a.ids.split(',')];report={'passed':False,'total':len(rows),'results':[]}
 for i,row in enumerate(rows):
  p=out/row['id'];record={'part':row['id'],'passed':False};start=time.time()
  try:
   with (out/(row['id']+'.log')).open('w',encoding='utf-8') as log:
    def run(args):subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,check=True)
    run([a.worker,'part','--root',a.root,'--part',row['id'],'--out',str(p)])
    run([sys.executable,str(scripts/'prepare_weapon.py'),str(p)]);
    if a.dsas:run([a.worker,'metadata','--root',a.root,'--package',str(p),'--dsas',a.dsas])
    run([sys.executable,str(scripts/'prepare_textures.py'),str(p)])
    if a.blender:
     run([sys.executable,str(scripts/'build_pipeline.py'),str(p),'--blender',a.blender,'--batch-size','8','--helper-visibility',a.helper_visibility]+(['--clean-bones'] if a.clean_bones else [])+(['--hierarchy'] if a.hierarchy else []))
    pkg=json.loads((p/'package.json').read_text('utf-8-sig'));record.update(models=len(pkg['models']),animations=len(pkg['clips']),textures=len(pkg['textures']),issues=pkg['issues'],missingTextures=pkg['missingTextures']);record['passed']=not pkg['issues'] and not pkg['missingTextures']
    if a.blender:record['passed']&=json.loads((p/'blend_batches.json').read_text('utf-8'))['passed']
  except Exception as e:record['error']=str(e)
  record['seconds']=round(time.time()-start,2);report['results'].append(record);report['passed']=len(report['results'])==len(rows) and all(r['passed'] for r in report['results']);(out/'batch_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('BATCH',i+1,len(rows),row['id'],record['passed'],flush=True)
 print('BATCH_DONE',sum(r['passed'] for r in report['results']),'/',len(rows),flush=True)
if __name__=='__main__':main()
