import sys,json
from pathlib import Path
import bpy
args=sys.argv[sys.argv.index('--')+1:]
bpy.ops.wm.open_mainfile(filepath=args[0])
Path(args[1]).write_text(json.dumps({'actions':sorted(bpy.data.actions.keys())}),encoding='utf-8')
