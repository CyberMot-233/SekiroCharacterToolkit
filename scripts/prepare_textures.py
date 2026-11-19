"""Decode DDS (including BC7) with Pillow. Original DDS are never changed."""
import json,sys,hashlib,struct,io
from pathlib import Path
from PIL import Image
def main(folder):
 p=Path(folder);pkg=json.loads((p/'package.json').read_text('utf-8-sig'));result={'converted':{},'errors':[]}
 for key,rel in pkg['textures'].items():
  try:
   src=p/rel;rgba=p/'_internal/rgba'/(key+'.tif');rgb=p/'textures/png_rgb'/(key+'.png')
   rgba.parent.mkdir(parents=True,exist_ok=True);rgb.parent.mkdir(parents=True,exist_ok=True)
   data=bytearray(src.read_bytes())
   # Pillow omits BC1/2/3 sRGB enums; block encoding is identical to UNORM.
   # Preserve encoded channel values (no gamma transform) and keep original DDS.
   if data[:4]==b'DDS ' and data[84:88]==b'DX10' and len(data)>=148:
    fmt=struct.unpack_from('<I',data,128)[0]
    if fmt in {72:71,75:74,78:77,99:98}:struct.pack_into('<I',data,128,{72:71,75:74,78:77,99:98}[fmt])
   with Image.open(io.BytesIO(data)) as im:
    im.convert('RGBA').save(rgba,compression='tiff_deflate');im.convert('RGB').save(rgb)
    result['converted'][key]={'rgba':rgba.relative_to(p).as_posix(),'rgb':rgb.relative_to(p).as_posix(),'size':list(im.size),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest()}
  except Exception as e:result['errors'].append({'texture':key,'error':str(e)})
 (p/'texture_conversion.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print('TEXTURES',len(result['converted']),'errors',len(result['errors']),flush=True)
 if result['errors']:return 2
 return 0
if __name__=='__main__':sys.exit(main(sys.argv[1]))
