"""Repair Source2 bodygroup defaults/events without rewriting DMX or materials."""
import argparse,datetime,hashlib,shutil,subprocess,sys
from pathlib import Path
from cs2_common import read,save,write_kv,cs_root,compile_resource
from cs2_kvtext import loads
from cs2_visibility import apply

def sha(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--addon',type=Path,required=True);ap.add_argument('--name',required=True);ap.add_argument('--compile',action='store_true');a=ap.parse_args()
 from cs2_common import safe_name
 if safe_name(a.name)!=a.name:raise ValueError('Invalid model resource name')
 addon=a.addon.resolve();root=cs_root(addon);base=addon/f'rawmodels/sekiro/characters/{a.name}';reports=base/'reports'
 if not (base/'sct_owner.json').exists():raise ValueError('目标不是本工具管理的角色资源')
 export=read(base/'compile_export.json')
 if not export.get('passed'):raise ValueError('已完成 DMX 校验未通过')
 for action in export['actions']:
  if sha(addon/action['file'])!=action['dmx_sha256']:raise ValueError('动作 DMX 被改写：'+action['name'])
 vmdl=addon/f'models/sekiro/characters/{a.name}/{a.name}.vmdl';compiled=root/f'game/csgo_addons/{addon.name}/models/sekiro/characters/{a.name}/{a.name}.vmdl_c'
 original=vmdl.read_text('utf-8');doc=loads(original);changes=apply(doc,export)
 stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f');backup=base/'backups'/('visibility_'+stamp);backup.mkdir(parents=True)
 for path in [vmdl,compiled,reports/'compiled_validation.json',reports/'compiled_mesh_validation.json',reports/'dependencies.json']:
  if path.exists():shutil.copy2(path,backup/path.name)
 protected={str(addon/item['file']):sha(addon/item['file']) for item in export['actions']+export['mesh_groups']}
 protected[str(addon/export['mesh_file'])]=sha(addon/export['mesh_file'])
 report=dict(version='0.10.8',passed=False,changes=changes,actions=len(export['actions']),backup=str(backup),runtime_validation='not_run',render_scope='compiled-pose reconstruction is separate from ModelDoc/game playback',vmdl=str(vmdl))
 try:
  write_kv(vmdl,doc,model=True)
  if a.compile:
   report['compile']=compile_resource(addon,vmdl,reports/'visibility_compile.log')
   if not report['compile']['passed']:raise RuntimeError('部件显隐编译失败：'+report['compile']['log'])
   logpath=reports/'visibility_verify.log'
   with logpath.open('w',encoding='utf-8') as log:
    result=subprocess.run([sys.executable,str(Path(__file__).with_name('cs2_verify_compiled.py')),'--addon',str(addon),'--name',a.name,'--all-frames'],stdout=log,stderr=subprocess.STDOUT)
   if result.returncode:raise RuntimeError('部件显隐回读失败：'+str(logpath))
   report['compiled_validation']=read(reports/'compiled_validation.json')
   from cs2_verify_mesh import verify as mesh_verify
   from cs2_dependencies import verify as dependencies_verify
   report['mesh_validation']=mesh_verify(addon,a.name);report['dependencies']=dependencies_verify(addon,a.name)
   if not report['mesh_validation']['passed'] or not report['dependencies']['passed']:raise RuntimeError('网格或依赖校验失败')
  report['dmx_unchanged']=all(sha(path)==value for path,value in protected.items())
  if not report['dmx_unchanged']:raise RuntimeError('维修期间 DMX 被改写')
  report.update(passed=True,status='compiled_offline' if a.compile else 'source_ready',compiled_sha256=sha(compiled) if a.compile else None)
 except Exception as e:
  report.update(status='failed',error=str(e));save(reports/'visibility_repair.json',report);raise
 save(reports/'visibility_repair.json',report)
 print('CS2_VISIBILITY_REPAIRED',changes,'DMX unchanged:',report['dmx_unchanged'],'Report:',str(reports/'visibility_repair.json'),flush=True)

if __name__=='__main__':main()
