import bpy,sys,math,json
from pathlib import Path
from mathutils import Vector
p=Path(sys.argv[sys.argv.index('--')+1]);pkg=json.loads((p/'package.json').read_text('utf-8-sig'));bpy.ops.wm.open_mainfile(filepath=str(p/(pkg['character']+'.blend')));sc=bpy.context.scene;arm=bpy.data.objects[pkg['character']+'_Armature']
argv=sys.argv[sys.argv.index('--')+1:];actions=list(bpy.data.actions);act=next((a for a in actions if 'a106_316210' in a.name),actions[0] if actions else None)
if len(argv)>1:act=next(a for a in actions if a.name.endswith(argv[1]))
if act:
 arm.animation_data.action=act
 if act.slots:arm.animation_data.action_slot=act.slots[0]
sc.frame_set(73,subframe=.78) if act and 'a106_' in act.name else sc.frame_set(1)
if len(argv)>2:sc.frame_set(int(float(argv[2])),subframe=float(argv[2])%1)
bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();points=[]
for ob in bpy.data.objects:
 if ob.type=='MESH' and not ob.hide_render and not ob.hide_get():
  ev=ob.evaluated_get(dg);points.extend(ev.matrix_world@Vector(c) for c in ev.bound_box)
lo=Vector(tuple(min(p[i] for p in points) for i in range(3)));hi=Vector(tuple(max(p[i] for p in points) for i in range(3)));center=(lo+hi)*.5;size=max(hi-lo);size=max(size,1)
cam=bpy.data.objects.new('PreviewCamera',bpy.data.cameras.new('PreviewCamera'));sc.collection.objects.link(cam);cam.location=center+(Vector((size*1.2,size*2.5,size*.45)) if pkg['character']=='c7400' else Vector((size*1.7,-size*2.5,size*.7)));cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=size*1.35;sc.camera=cam
for name,offset,power in [('Key',(2,-3,4),1500),('Fill',(-3,-1,2),1000),('Rim',(0,3,3),1800)]:
 light=bpy.data.objects.new(name,bpy.data.lights.new(name,'AREA'));sc.collection.objects.link(light);light.location=center+Vector(offset);light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler();light.data.energy=power*(.32 if pkg['character']=='c7400' else 1);light.data.shape='DISK';light.data.size=4
sc.render.engine='CYCLES';sc.cycles.samples=24;sc.cycles.use_denoising=True;sc.render.resolution_x=900;sc.render.resolution_y=1000;sc.render.resolution_percentage=100;sc.render.image_settings.file_format='PNG';sc.render.image_settings.color_mode='RGB';sc.render.filepath=str(p/(argv[3] if len(argv)>3 else 'preview.png'));sc.world.node_tree.nodes['Background'].inputs[0].default_value=(.035,.045,.065,1);bpy.ops.render.render(write_still=True)
