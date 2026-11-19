"""Probe actual tempfile/Python/Blender paths, not just configured strings."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
from runtime_paths import configure

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--blender',type=Path);ap.add_argument('--child',action='store_true');a=ap.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
    base=configure();paths={'python_temp':tempfile.gettempdir(),'home':str(Path.home()),'cwd':os.getcwd()}
    for k in ('TEMP','TMP','APPDATA','LOCALAPPDATA','BLENDER_USER_CONFIG','BLENDER_USER_SCRIPTS','BLENDER_USER_DATAFILES','DOTNET_CLI_HOME','DOTNET_BUNDLE_EXTRACT_BASE_DIR','CUDA_CACHE_PATH'):
        paths[k]=os.environ[k]
    with tempfile.NamedTemporaryFile() as f:paths['created_temp']=f.name
    if a.child:
        import bpy
        paths.update(blender_temp=bpy.app.tempdir,blender_config=bpy.utils.user_resource('CONFIG'),blender_scripts=bpy.utils.user_resource('SCRIPTS'),blender_datafiles=bpy.utils.user_resource('DATAFILES'))
    errors=[k+': '+str(v) for k,v in paths.items() if not v or not Path(v).resolve().is_relative_to(base)]
    report=dict(passed=not errors,cache_root=str(base),paths=paths,errors=errors)
    if a.blender:
        child=base/'blender_probe.json'
        subprocess.run([str(a.blender),'-b','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(Path(__file__).with_name('blender_bootstrap.py')),'--python',str(Path(__file__)),'--','--child','--output',str(child)],check=True,cwd=base)
        report['blender']=json.loads(child.read_text('utf-8'));report['passed'] &= report['blender']['passed']
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)
    if not report['passed']:raise RuntimeError('Storage path escaped selected cache')
if __name__=='__main__':main()
