"""Primary DSAS material samplers -> CS2 character VMAT and RGB-only PNG."""
import hashlib,re,json,io,os,time,uuid
from pathlib import Path
import numpy as np
from PIL import Image
from materials import select_primary
def write_asset(path,payload):
 """Avoid truncating assets currently watched by Workshop Tools."""
 path=Path(path)
 if path.exists() and path.read_bytes()==payload:return
 pending=path.with_name(path.name+'.'+uuid.uuid4().hex+'.pending')
 pending.write_bytes(payload)
 try:
  for attempt in range(30):
   try:os.replace(pending,path);return
   except PermissionError:
    if attempt==29:raise
    time.sleep(.1)
 finally:
  if pending.exists():pending.unlink()

class Materials:
 def __init__(self,pkg,package,addon,name):
  self.pkg=pkg;self.package=Path(package);self.addon=Path(addon);self.base=f'materials/sekiro/characters/{name}';self.cache={};self.records=[]
 def texture(self,key):
  rgba=self.package/'_internal/rgba'/(key+'.tif')
  rgb=self.package/self.pkg['textures'].get(key,'__missing__')
  return Image.open(rgba if rgba.exists() else rgb).convert('RGBA')
 def export(self,source):
  key=hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()[:12]
  if key in self.cache:return self.cache[key]
  name=re.sub('[^a-z0-9_]+','_',source['name'].lower()).strip('_')[:35]+'_'+key
  path=self.base+'/'+name+'.vmat';folder=self.addon/self.base/'textures';folder.mkdir(parents=True,exist_ok=True)
  base=select_primary(source,1);normal=select_primary(source,3);params=[];record={'material':path,'source':source['name'],'mtd':source['mtd'],'textures':[]}
  def png(kind,im):
   fn=name+'_'+kind+'.png';buffer=io.BytesIO();im.convert('RGB').save(buffer,format='PNG');write_asset(folder/fn,buffer.getvalue());rel=self.base+'/textures/'+fn;record['textures'].append(rel);return rel
  if base:
   im=self.texture(base['resolvedName']);params.append(('TextureColor',png('color',im)))
   cfg=source.get('shader_config',{});alpha=cfg.get('EnableAlphas',any(x in source.get('mtd','').lower() for x in ('alp','hair','fur','edge','decal','eyelash','fray')))
   if alpha and im.getchannel('A').getextrema()[0]<250:
    params.extend([('F_ALPHA_TEST',1),('F_RENDER_BACKFACES',1),('g_flAlphaTestReference',.5),('TextureTranslucency',png('opacity',im.getchannel('A')))])
  if normal:
   im=self.texture(normal['resolvedName']);a=np.array(im).astype(np.float32)/255;x=a[:,:,0]*2-1;y=a[:,:,1]*2-1;z=np.sqrt(np.maximum(0,1-x*x-y*y))
   # CS2 consumes DirectX tangent normals; Sekiro R/G are also DirectX.
   n=np.stack((a[:,:,0],a[:,:,1],z*.5+.5),axis=-1)
   params.append(('TextureNormal',png('normal',Image.fromarray(np.uint8(np.clip(n,0,1)*255)))))
   params.append(('TextureRoughness',png('roughness',Image.fromarray(np.uint8(np.clip(1-a[:,:,2],0,1)*255)))))
  params.extend([('g_flMetalness',0.0),('g_flRoughnessScaleFactor',1.0)])
  text='Layer0\n{\n    shader "csgo_complex.vfx"\n'
  for k,v in params:text+='    '+k+' '+(json.dumps(v) if isinstance(v,str) else str(v))+'\n'
  text+='}\n';dst=self.addon/path;dst.parent.mkdir(parents=True,exist_ok=True);write_asset(dst,text.encode('utf-8'));self.records.append(record);self.cache[key]=path;return path
