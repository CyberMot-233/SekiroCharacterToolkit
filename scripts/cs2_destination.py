"""Distinguish live models from toolkit leftovers when reusing a resource name."""
import datetime,os,re,shutil,stat
from pathlib import Path
from cs2_common import read,save,cs_root

def remove_registration(text,name):
 lines=text.splitlines(keepends=True);result=[];inside=None;seen=set()
 markers={f'// SCT BEGIN {name}':f'// SCT END {name}',f'// SCT AUDIO VOLUME BEGIN {name}':f'// SCT AUDIO VOLUME END {name}'}
 ends=set(markers.values())
 for line in lines:
  token=line.strip()
  if token in markers:
   if inside or token in seen:raise ValueError('声音注册块重复或嵌套，未修改任何资源')
   inside=markers[token];seen.add(token);continue
  if token in ends:
   if token!=inside:raise ValueError('声音注册块不完整，未修改任何资源')
   inside=None;continue
  if not inside:result.append(line)
 if inside:raise ValueError('声音注册块缺少结束标记，未修改任何资源')
 return ''.join(result),bool(seen)

def safe_path(path,root):
 path=Path(path);root=Path(root)
 for p in [path,*path.parents]:
  if p==root:break
  if p.is_symlink() or (p.exists() and getattr(p.lstat(),'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT):raise ValueError('资源路径包含链接：'+str(p))
 if not path.resolve().is_relative_to(root.resolve()):raise ValueError('资源路径越界：'+str(path))

def prepare_destination(addon,name,package):
 if not re.fullmatch('[a-z][a-z0-9_]*',name):raise ValueError('无效模型名')
 addon=Path(addon).resolve();package=Path(package).resolve();root=cs_root(addon);game=root/'game/csgo_addons'/addon.name
 base=addon/f'rawmodels/sekiro/characters/{name}';owner=base/'sct_owner.json';vmdl=addon/f'models/sekiro/characters/{name}/{name}.vmdl'
 plan=[]
 for scope,source in [('content',addon),('game',game)]:
  for k in ('models','rawmodels','materials','sounds'):
   p=source/f'{k}/sekiro/characters/{name}';safe_path(p,source)
   if p.exists():plan.append((scope,source,p))
 manifest=addon/'soundevents/soundevents_addon.vsndevts';safe_path(manifest,addon)
 old=read(owner) if owner.is_file() else {};text=manifest.read_text('utf-8-sig') if manifest.exists() else ''
 updated,tagged=remove_registration(text,name)
 if vmdl.exists():
  if old.get('tool')=='SekiroCharacterToolkit' and Path(old.get('package','')).resolve()==package:return dict(mode='owned')
  raise ValueError('已有同名模型：'+str(vmdl)+'；追加动作请使用“追加/覆盖动画”。重建请先备份并删除该模型的源模型目录。')
 collisions=[p for _,_,p in plan if not p.is_dir() or any(p.iterdir())]
 if not collisions and not tagged:return dict(mode='new')
 if old.get('tool')!='SekiroCharacterToolkit' and not tagged:
  raise ValueError('同名残留无法确认属于本工具，未覆盖：'+', '.join(map(str,collisions)))
 backup=addon/'_sct_backups'/(name+'_recreate_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'));safe_path(backup,addon);backup.mkdir(parents=True)
 moved=[];manifest_changed=False;pending=backup/'registration.pending'
 if manifest.exists():shutil.copy2(manifest,backup/manifest.name)
 try:
  for scope,source,p in plan:
   dest=backup/scope/p.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True)
   p.rename(dest);moved.append(dict(source=str(p),backup=str(dest)))
  if tagged:
   pending.write_text(updated,'utf-8');os.replace(pending,manifest);manifest_changed=True
  result=dict(mode='recreate_after_deletion',backup=str(backup),moved=moved,registration_removed=tagged)
  save(backup/'recreate.json',result)
 except BaseException:
  if manifest_changed:shutil.copy2(backup/manifest.name,manifest)
  for record in reversed(moved):
   src=Path(record['source']);src.parent.mkdir(parents=True,exist_ok=True);Path(record['backup']).rename(src)
  raise
 finally:
  if pending.exists():pending.unlink()
 print('CS2_RECREATE',str(backup),flush=True);return result
