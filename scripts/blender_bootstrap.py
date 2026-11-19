"""Executed before the actual Blender task, including interactive model opening."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from runtime_paths import configure
base=configure()
import bpy
bpy.context.preferences.filepaths.temporary_directory=str(base/'temp')
bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
# No preferences save: the launcher reapplies routing for each process.
print('SCT_STORAGE',base,'blender_temp',bpy.app.tempdir,flush=True)
