"""One read-only reopen of the final output; no post-export transformations."""
import json, runpy, sys
from types import SimpleNamespace
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent))
from helper_visibility import effective_visible
p=Path(sys.argv[sys.argv.index('--')+1]);pkg=json.loads((p/'package.json').read_text('utf-8-sig'))
bpy.ops.wm.open_mainfile(filepath=str(p/(pkg['character']+'.blend')))
sys.argv.append('--already-open')
for script in ('verify_saved.py','verify_appearance.py'):
    runpy.run_path(str(Path(__file__).with_name(script)),run_name='__main__')
arm=bpy.data.objects[pkg['character']+'_Armature']
path=p/'helper_visibility_report.json';report=json.loads(path.read_text('utf-8'))
report['saved_visibility_errors']=[n for n in report['helpers'] if effective_visible(arm.data.bones[n])!=report['visible']]
report['passed'] &= not report['saved_visibility_errors']
path.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
if not report['passed']:raise ValueError('Saved helper visibility mismatch')
errors=[]
if arm.get('sct_hierarchy_version'):
    for b in arm.data.bones:
        if not b.get('sct_hierarchy_bone'):continue
        parent=b.parent
        if parent and parent.get('sct_affine_helper'):parent=parent.parent
        if (parent.name if parent else '')!=b.get('source_parent_name',''):errors.append('Parent mismatch '+b.name)
for ob in bpy.data.objects:
    if ob.type!='MESH' or not any(m.type=='ARMATURE' and m.object==arm for m in ob.modifiers):continue
    for v in ob.data.vertices:
        if any(g.weight>0 and ob.vertex_groups[g.group].name not in arm.data.bones for g in v.groups):
            errors.append('Weighted bone missing '+ob.name);break
if (p/'equipment/profile.json').exists():
    import verify_equipment as equipment
    equipment.HERE=p/'equipment'
    args=SimpleNamespace(blend=str(p/(pkg['character']+'.blend')),already_open=True,all_actions=True,
                         vertices=24,matrix_tolerance=.003,root_tolerance=.002,vertex_tolerance=.003,
                         output=str(p/'equipment_saved_validation.json'))
    if equipment.main(args):errors.append('Saved equipment validation failed')
final=dict(passed=not errors,errors=errors,method='read-only',blend_opens=1,blend_saves=0,
           weighted_bones_and_hierarchy_checked=True,equipment_checked=(p/'equipment/profile.json').exists())
(p/'direct_final_validation.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),'utf-8')
if errors:raise ValueError(errors)
print('FINAL_READONLY_VERIFY passed; opens=1 saves=0',flush=True)
