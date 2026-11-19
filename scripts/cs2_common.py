import json,re,hashlib,subprocess,os
from pathlib import Path
HEADER='<!-- kv3 encoding:text:version{e21c7f3c-8a33-41c5-9977-a76d3a32aa0d} format:generic:version{7412167c-06e9-4698-aff2-e63eb59037e7} -->'
MODEL_HEADER=HEADER.replace('generic:version{7412167c-06e9-4698-aff2-e63eb59037e7}','modeldoc41:version{12fc9d44-453a-4ae4-b4d9-7e2ac0bbd4e0}')
class SoundEvent(str):pass
def bone_name(value):
 # ModelDoc sanitizes punctuation while the DMX importer keeps it, producing
 # duplicate bones and a different animation hierarchy. Normalize both inputs.
 if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value):return value
 base=re.sub('[^A-Za-z0-9_]','_',value)
 if not base or base[0].isdigit():base='SCT_'+base
 return base+'_'+hashlib.sha256(value.encode('utf-8')).hexdigest()[:8]
def kv(v):
 if isinstance(v,SoundEvent):return 'soundevent:'+json.dumps(v)
 if isinstance(v,dict):return '{\n'+'\n'.join(json.dumps(str(k))+' = '+kv(x) for k,x in v.items())+'\n}'
 if isinstance(v,(list,tuple)):return '[\n'+',\n'.join(kv(x) for x in v)+'\n]'
 return json.dumps(v,ensure_ascii=False,allow_nan=False)
def write_kv(path,value,model=False):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text((MODEL_HEADER if model else HEADER)+'\n'+kv(value)+'\n','utf-8')
def read(path):return json.loads(Path(path).read_text('utf-8-sig'))
def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 pending=path.with_name(path.name+'.pending');pending.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8');os.replace(pending,path)
def safe_name(name):
 s=re.sub('[^a-z0-9_]+','_',name.lower()).strip('_')
 if not s:raise ValueError('Empty resource name')
 return s
def cs_root(addon):
 addon=Path(addon).resolve()
 if addon.parent.name!='csgo_addons' or addon.parent.parent.name!='content':raise ValueError('目标必须是 CS2/content/csgo_addons/ADDON 目录')
 return addon.parent.parent.parent
def compile_resource(addon,path,log):
 addon=Path(addon).resolve();root=cs_root(addon);exe=root/'game/bin/win64/resourcecompiler.exe'
 if not exe.exists():raise FileNotFoundError('请安装 CS2 Workshop Tools: '+str(exe))
 args=[str(exe),'-i',str(path),'-game',str(root/'game/csgo'),'-addon',addon.name,'-nop4']
 p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,cwd=str(Path(log).parent),encoding='utf-8',errors='replace')
 Path(log).write_text(p.stdout,'utf-8')
 rel=Path(path).resolve().relative_to(addon);ext='.vsnd_c' if rel.suffix.lower() in ('.wav','.mp3') else rel.suffix+'_c'
 output=root/'game/csgo_addons'/addon.name/rel.with_suffix(ext)
 semantic_errors=[line.strip() for line in p.stdout.splitlines() if re.search(r'Unknown mesh |missing bone|too many bones|exceed.*weights|failed to load|Error loading|No bones in animation|joint weights per vertex, max',line,re.I)]
 warnings=[line.strip() for line in p.stdout.splitlines() if 'warning' in line.lower()]
 ok=p.returncode==0 and 'RESOURCE COMPILE ERROR' not in p.stdout and not re.search(r'\b[1-9][0-9]* failed',p.stdout) and output.is_file() and not semantic_errors
 return dict(passed=ok,exit_code=p.returncode,source=str(path),output=str(output),log=str(log),bytes=output.stat().st_size if output.exists() else 0,semantic_errors=semantic_errors,warnings=warnings)
