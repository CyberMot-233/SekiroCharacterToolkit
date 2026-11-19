"""Copy the verified Wolf profile; normalize formats without changing the source."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from PIL import Image
EXPECTED='e1faf6efa4dc2d10b8543325d3eac5e95bfb166e56cb8e0ff2a420a05cc75e7b'

def sha(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def normalize_formats(dst,ffmpeg):
 dst=Path(dst).resolve();report={'png_rgb':[],'wav_to_mp3':[]}
 # Include weapon_extra_* textures, not only folders whose name starts with tex.
 for texture in sorted(dst.rglob('*.png')):
  with Image.open(texture) as im:rgb=im.convert('RGB')
  rgb.save(texture);report['png_rgb'].append(texture.relative_to(dst).as_posix())
 for wav in sorted((dst/'audio').rglob('*.wav')):
  mp3=wav.with_suffix('.mp3')
  subprocess.run([str(ffmpeg),'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(wav),'-ar','48000','-ac','2','-codec:a','libmp3lame','-b:a','192k',str(mp3)],check=True)
  original=dst/'_internal/audio_wav'/wav.relative_to(dst/'audio');original.parent.mkdir(parents=True,exist_ok=True)
  shutil.move(str(wav),str(original))
  report['wav_to_mp3'].append({'mp3':mp3.relative_to(dst).as_posix(),'original_wav':original.relative_to(dst).as_posix(),'mp3_sha256':sha(mp3)})
 (dst/'copy_format_conversion.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 return report

def main():
 if len(sys.argv)!=4:raise SystemExit('Usage: copy_verified.py SOURCE OUTPUT FFMPEG')
 src,dst=map(Path,sys.argv[1:3]);ffmpeg=Path(sys.argv[3]);file=src/'Wolf_Sekiro.blend'
 if sha(file)!=EXPECTED:raise RuntimeError('Verified Wolf source hash differs; source not copied')
 if not ffmpeg.is_file():raise FileNotFoundError(ffmpeg)
 if dst.resolve()==src.resolve() or dst.resolve().is_relative_to(src.resolve()):raise ValueError('Output must not be inside source')
 dst.mkdir(parents=True,exist_ok=True)
 if any(dst.iterdir()):raise RuntimeError('Output must be empty')
 for item in src.iterdir():
  if item.name.startswith('.') or item.name.startswith('backup'):continue
  print('COPY',item.name,flush=True)
  if item.is_dir():shutil.copytree(item,dst/item.name)
  else:shutil.copy2(item,dst/item.name)
 conversion=normalize_formats(dst,ffmpeg)
 if sha(dst/file.name)!=EXPECTED:raise RuntimeError('Copied blend hash mismatch')
 (dst/'verified_copy.json').write_text(json.dumps({'passed':True,'source':str(src),'blend_sha256':EXPECTED,'mode':'copy existing verified profile; not fresh export','rgb_png_count':len(conversion['png_rgb']),'wav_to_mp3_count':len(conversion['wav_to_mp3']),'note':'Original copied reports describe the source profile; see copy_format_conversion.json for format changes.'},ensure_ascii=False,indent=2),encoding='utf-8')
 print('VERIFIED_COPY_OK',flush=True)

if __name__=='__main__':main()
