"""Toggle affine helpers without rebaking, changing topology, or touching motion."""
import argparse,datetime,hashlib,json,os,re,shutil,sys
from pathlib import Path
import bpy
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from rig_cleanup import curves,action_digest,path_bones

def is_helper(b):
    return bool(b.get('sct_affine_helper')) or b.name.startswith('AFF::') or bool(re.fullmatch(r'AFF_[0-9]+',b.name)) or b.name.endswith('__AFFINE')

def set_visibility(arm,visible):
    helpers=[b for b in arm.data.bones if is_helper(b)]
    if visible:
        # Solo on an unrelated collection can override the helper collection's eye.
        for c in arm.data.collections_all:c.is_solo=False
    collection=arm.data.collections.get('SCT · Affine helpers')
    if collection:collection.is_visible=visible
    for b in helpers:
        b.hide=not visible
        if visible:
            b.hide_select=False
            for c in b.collections:
                while c:
                    c.is_visible=True;c=c.parent
    arm['sct_helpers_visible']=visible
    if visible:
        for screen in bpy.data.screens:
            for area in screen.areas:
                for space in area.spaces:
                    if space.type=='VIEW_3D':space.overlay.show_bones=True
    return [b.name for b in helpers]

def effective_visible(b):
    return not b.hide and (not b.collections or any(c.is_visible_effectively for c in b.collections))

def invariant():
    h=hashlib.sha256()
    def add(value):h.update(repr(value).encode('utf-8'))
    for ob in bpy.data.objects:
        add((ob.name,ob.type,ob.parent.name if ob.parent else None,tuple(tuple(row) for row in ob.matrix_world)))
        if ob.type=='ARMATURE':
            for b in ob.data.bones:add((b.name,b.parent.name if b.parent else None,b.use_deform,b.inherit_scale,tuple(tuple(row) for row in b.matrix_local)))
        elif ob.type=='MESH':
            data=np.empty(len(ob.data.vertices)*3,np.float32);ob.data.vertices.foreach_get('co',data);h.update(data.tobytes())
            add([(g.name,g.index) for g in ob.vertex_groups])
            for v in ob.data.vertices:add([(g.group,g.weight) for g in v.groups])
    return {'actions':{a.name:action_digest(a) for a in bpy.data.actions},'rig_mesh_weights':h.hexdigest()}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('package',type=Path);ap.add_argument('--visibility',choices=['visible','hidden'],default='visible');ap.add_argument('--output',type=Path);ap.add_argument('--no-backup',action='store_true');a=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    p=a.package.resolve();pkg=json.loads((p/'package.json').read_text(encoding='utf-8-sig'));source=p/(pkg['character']+'.blend');output=a.output.resolve() if a.output else source
    if output!=source and output.exists():raise FileExistsError('Do not overwrite existing copy: '+str(output))
    bpy.ops.wm.open_mainfile(filepath=str(source));arm=bpy.data.objects[pkg['character']+'_Armature'];before=invariant();visible=a.visibility=='visible';names=set_visibility(arm,visible)
    report={'passed':False,'visible':visible,'helper_count':len(names),'helpers':names,'source':str(source),'output':str(output)}
    if output==source and not a.no_backup:
        backup=p/'backups'/('visibility_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))/source.name;backup.parent.mkdir(parents=True);shutil.copy2(source,backup);report['backup']=str(backup)
    output.parent.mkdir(parents=True,exist_ok=True);staged=output.with_name(output.stem+'.visibility_pending.blend');bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(staged),compress=True);bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.wm.open_mainfile(filepath=str(staged));arm=bpy.data.objects[pkg['character']+'_Armature']
    bad=[n for n in names if effective_visible(arm.data.bones[n])!=visible or (visible and arm.data.bones[n].hide_select)]
    after=invariant();report.update(actions_unchanged=before['actions']==after['actions'],rig_mesh_weights_unchanged=before['rig_mesh_weights']==after['rig_mesh_weights'],visibility_errors=bad,action_count=len(bpy.data.actions))
    report['passed']=report['actions_unchanged'] and report['rig_mesh_weights_unchanged'] and not bad
    if report['passed']:os.replace(staged,output)
    report_file=p/'helper_visibility_report.json' if output==source else output.with_suffix('.visibility.json')
    report_file.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('HELPER_VISIBILITY',json.dumps(report,ensure_ascii=False),flush=True)
    if not report['passed']:raise RuntimeError('Display-only verification failed; original unchanged')
if __name__=='__main__':main()
