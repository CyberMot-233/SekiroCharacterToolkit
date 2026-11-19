"""Process-local storage routing. Never changes Windows paging or global settings."""
import os
from pathlib import Path

def configure(cache=None):
    base=Path(cache or os.environ.get('SCT_CACHE_ROOT') or Path(__file__).resolve().parents[1]/'cache').resolve()
    paths={'TEMP':'temp','TMP':'temp','TMPDIR':'temp','APPDATA':'profile/AppData/Roaming',
           'LOCALAPPDATA':'profile/AppData/Local','USERPROFILE':'profile','HOME':'profile',
           'XDG_CACHE_HOME':'xdg/cache','XDG_CONFIG_HOME':'xdg/config','XDG_DATA_HOME':'xdg/data',
           'BLENDER_USER_CONFIG':'blender/config','BLENDER_USER_SCRIPTS':'blender/scripts',
           'BLENDER_USER_DATAFILES':'blender/datafiles','BLENDER_USER_EXTENSIONS':'blender/extensions',
           'DOTNET_CLI_HOME':'dotnet','DOTNET_BUNDLE_EXTRACT_BASE_DIR':'dotnet/bundles',
           'NUGET_PACKAGES':'nuget','PIP_CACHE_DIR':'pip','PYTHONUSERBASE':'python',
           'MPLCONFIGDIR':'matplotlib','NUMBA_CACHE_DIR':'numba','CUDA_CACHE_PATH':'cuda',
           'OPTIX_CACHE_PATH':'optix'}
    for key,rel in paths.items():
        p=base/rel;p.mkdir(parents=True,exist_ok=True);os.environ[key]=str(p)
    os.environ.update(SCT_CACHE_ROOT=str(base),SCT_AUDIO_CACHE=str(base),PYTHONNOUSERSITE='1',
                      PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',DOTNET_CLI_TELEMETRY_OPTOUT='1')
    import sys,tempfile
    sys.dont_write_bytecode=True;tempfile.tempdir=str(base/'temp')
    return base
