"""Bind primary DSAS sampler roles and UV channels, not first texture order."""
import re

def select_primary(source,role):
 textures=[t for t in source['textures'] if t.get('resolvedName')]
 typed=[t for t in textures if t.get('sampler',{}).get('TexType')==role]
 if typed:return typed[0]
 candidates=[t for t in textures if 'sampler' not in t]
 word='(?:albedo|diffuse)' if role==1 else '(?:normal|bump)'
 matching=[t for t in candidates if re.search(word,t['type'],re.I)]
 primary=[t for t in matching if re.search(word+r'(?:map)?_(?:0|4)$',t['type'],re.I)]
 return (primary or matching or [None])[0]

def build_material(source,image):
 import bpy
 mat=bpy.data.materials.new(source['name']);mat.use_nodes=True;mat['source_mtd']=source['mtd']
 bs=mat.node_tree.nodes.get('Principled BSDF');bs.inputs['Roughness'].default_value=.7
 chosen={1:select_primary(source,1),3:select_primary(source,3)};nodes={}
 for i,t in enumerate(source['textures']):
  key=t.get('resolvedName','');typ=t['type'].lower();noncolor=any(x in typ for x in ('normal','bump','spec','shin','mask','metallic','reflectance'))
  im=image(key,noncolor)
  if im is None:continue
  node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=im;node.label=t['type'];node.location=(-550,250-i*220);nodes[id(t)]=node
  uv=mat.node_tree.nodes.new('ShaderNodeUVMap');uv.uv_map='UV'+str(t.get('sampler',{}).get('UVIndex',0));uv.location=(-1000,250-i*220)
  scale=t.get('uv_scale',[1,1]);vector=uv.outputs['UV']
  if scale!=[1,1]:
   mult=mat.node_tree.nodes.new('ShaderNodeVectorMath');mult.operation='MULTIPLY';mult.inputs[1].default_value=(*scale,1);mat.node_tree.links.new(vector,mult.inputs[0]);vector=mult.outputs['Vector']
  mat.node_tree.links.new(vector,node.inputs['Vector'])
 base=chosen[1];normal=chosen[3]
 if base is not None and id(base) in nodes:
  node=nodes[id(base)];mat.node_tree.links.new(node.outputs['Color'],bs.inputs['Base Color']);mat['primary_albedo']=base['resolvedName']
  cfg=source.get('shader_config',{});alpha=cfg.get('EnableAlphas',any(s in source['mtd'].lower() for s in ['alp','hair','fur','edge','decal']))
  if alpha:mat.node_tree.links.new(node.outputs['Alpha'],bs.inputs['Alpha']);mat.surface_render_method='DITHERED'
 if normal is not None and id(normal) in nodes:
  nm=mat.node_tree.nodes.new('ShaderNodeNormalMap');nm.uv_map='UV'+str(normal.get('sampler',{}).get('UVIndex',0));mat.node_tree.links.new(decode_normal(mat,nodes[id(normal)].outputs['Color']),nm.inputs['Color']);mat.node_tree.links.new(nm.outputs['Normal'],bs.inputs['Normal']);mat['primary_normal']=normal['resolvedName']
 mat['material_scope']='DSAS primary sampler + original UV scales; secondary shader layers retained as source nodes'
 return mat


def decode_normal(mat,color):
 # Sekiro packs tangent normal XY in RG; B is gloss, not normal Z.
 # Original shader reconstructs Z = sqrt(max(1-dot(XY,XY),0)).
 nodes=mat.node_tree.nodes;links=mat.node_tree.links;split=nodes.new('ShaderNodeSeparateXYZ');links.new(color,split.inputs[0])
 def calc(op,a,b=None):
  node=nodes.new('ShaderNodeMath');node.operation=op
  for i,value in enumerate([a,b]):
   if value is None:continue
   if isinstance(value,(int,float)):node.inputs[i].default_value=value
   else:links.new(value,node.inputs[i])
  return node.outputs[0]
 x=calc('SUBTRACT',calc('MULTIPLY',split.outputs['X'],2),1);y=calc('SUBTRACT',calc('MULTIPLY',split.outputs['Y'],2),1)
 z=calc('SQRT',calc('MAXIMUM',calc('SUBTRACT',1,calc('ADD',calc('MULTIPLY',x,x),calc('MULTIPLY',y,y))),0))
 out=nodes.new('ShaderNodeCombineXYZ');links.new(split.outputs['X'],out.inputs['X']);links.new(calc('SUBTRACT',1,split.outputs['Y']),out.inputs['Y']);links.new(calc('ADD',calc('MULTIPLY',z,.5),.5),out.inputs['Z']);out.label='Sekiro RG normal / reconstruct Z / DirectX Y flip'
 return out.outputs[0]
