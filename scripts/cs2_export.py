"""Native package -> Source 2 DMX. Run with the bundled Blender Python.

Source 2 has scalar bone scales. Axial stretches are represented by two
translation-corrected skin joints with linearly split weights, not discarded.
The source anatomical hierarchy remains intact. All reconstructed vertices
are checked against source matrices before a clip is accepted.
"""
import argparse,sys,json,math,re,hashlib
from pathlib import Path
import numpy as np
from mathutils import Matrix,Vector
sys.path.insert(0,str(Path(__file__).resolve().parent))
from internal_fk_verified import DEFAULT_C as C,fk_separate_scale
from flver_mapping import mapped_fk
from face_overlay import FaceOverlay
from cs2_common import read,save,safe_name
from cs2_dmx import Model
from cs2_materials import Materials
from materials import select_primary
from audio_extract import database
from model_masks import states as mask_states
from npc_weapons import NpcWeaponPolicy
import equipment_core as E

UNIT=39.37007874015748
def matrix(v):return C@np.asarray(v,float).reshape(4,4).T@C.T
def rigid(m):
 l,q,s=Matrix(m).decompose();return np.array(Matrix.Translation(l)@q.to_matrix().to_4x4())
def decompose(m):
 l,q,s=Matrix(m).decompose();q.normalize();return list(l),[q.x,q.y,q.z,q.w],float(sum(s)/3)
def skin_weights(model,mesh):
 ids=np.array(mesh['boneIndices'],int);w=np.array(mesh['weights'],float);w[w.sum(axis=1)==0,0]=1
 if not mesh['usesBoneIndices']:ids[:,0]=mesh['normalW'];w[:]=0;w[:,0]=1
 if model['version']<=0x2000D:
  pal=np.array(mesh['info']['BoneIndices']);ok=(ids>=0)&(ids<len(pal));ids=pal[np.clip(ids,0,len(pal)-1)];w[~ok]=0
 ok=(ids>=0)&(ids<len(model['nodes']));w[~ok]=0;ids=np.clip(ids,0,len(model['nodes'])-1)
 total=w.sum(axis=1)
 if np.any(total<=0):raise ValueError('Unweighted vertices in source')
 return ids,w/total[:,None]

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--package',required=True,type=Path);ap.add_argument('--addon',required=True,type=Path);ap.add_argument('--name',default='wolf');ap.add_argument('--clip-list',type=Path);ap.add_argument('--limit',type=int,default=0);ap.add_argument('--rig-template',type=Path)
 args=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);p=args.package.resolve();addon=args.addon.resolve();name=safe_name(args.name);pkg=read(p/'package.json')
 report={'passed':False,'issues':[],'actions':[],'meshes':[],'unit_scale':UNIT,'scale_encoding':'two-anchor axial-stretch / scalar-scale hierarchy','max_vertex_error_m':0.0,'normals_scope':'skin normals use uniform-scale proxy rotations; original nonuniform inverse transpose is not reproduced'}
 out=addon/f'rawmodels/sekiro/characters/{name}';out.mkdir(parents=True,exist_ok=True);selected=set(read(args.clip_list)) if args.clip_list else None
 clips=[c for c in pkg['clips'] if selected is None or c['name'] in selected]
 if args.limit:clips=clips[:args.limit]
 if not clips:raise ValueError('No selected clips')
 if selected and selected-{c['name'] for c in clips}:raise ValueError('Unknown clip selection')
 nodes={};models=[]
 for file in pkg['models']:
  model=read(p/file)
  for n in model['nodes']:
   if n['name'] not in nodes:nodes[n['name']]={**n,'_parent_name':model['nodes'][n['parent']]['name'] if n['parent']>=0 else None}
  if 'hd_m_9120' not in file.lower():models.append((file,model,None))
 sk=pkg['skeleton'];sknames={b['name']:i for i,b in enumerate(sk)};refs=np.array([b['trs'] for b in sk]);parents=[b['parent'] for b in sk]
 source_rest={n:matrix(v['world']) for n,v in nodes.items()};rests={n:rigid(m) for n,m in source_rest.items()};parent={n:v['_parent_name'] for n,v in nodes.items()}
 weapons=[];profile_file=p/'equipment/profile.json';edb=None;dummies={};character=None
 if profile_file.exists():
  profile=read(profile_file);E.W=p/'equipment';E.TAGS=[tuple(x) for x in profile['tags']];E.ES.SLOT_EQUIP_IDS=profile['slots'];weapons=[E.Weapon(*x) for x in E.TAGS];edb=E.ES.EventStateDatabase(E.W);character=read(E.W/'c0000.json')
  for d in character['dummies']:dummies.setdefault(d['id'],d)
  for w in weapons:
   models.append((w.tag,w.data,w));rests[w.root]=np.eye(4);source_rest[w.root]=np.eye(4);parent[w.root]=None
   depths={}
   def chain_depth(i):
    if i not in depths:
     pi=w.nodes[i]['parent'];depths[i]=1+chain_depth(pi) if pi in w.used else 0
    return depths[i]
   for i in w.used:
    n=w.bn[i];source_rest[n]=np.array(w.ref[i]);rests[n]=rigid(source_rest[n]);pi=w.nodes[i]['parent'];parent[n]=w.bn[pi] if pi in w.bn and chain_depth(i)%16 else w.root
    if pi in w.bn and chain_depth(i)%16==0:report.setdefault('deep_chain_reparenting',[]).append({'bone':n,'original_parent':w.bn[pi],'export_parent':w.root,'reason':'ModelDoc 64-level document limit; preserve world bind and baked world poses'})
 # Extract geometry first, so only actually weighted bones need stretch proxies.
 meshes=[];weighted=set();mat=Materials(pkg,p,addon,name)
 for file,model,weapon in models:
  for mi,m in enumerate(model['meshes']):
   pos=np.array(m['pos'],float)@C[:3,:3].T;normal=np.array(m['normal'],float)@C[:3,:3].T;ids,weights=skin_weights(model,m)
   if not len(pos):continue
   if m['info'].get('Dynamic')==0:
    bind=np.array([matrix(n['world']) for n in model['nodes']]);vp=np.einsum('vbij,vj->vbi',bind[ids],np.column_stack((pos,np.ones(len(pos)))));pos=(vp[:,:,:3]*weights[:,:,None]).sum(axis=1)
   tri=np.array(m['indices'],int).reshape(-1,3);tri=tri[np.all(tri>=0,axis=1)&np.all(tri<len(pos),axis=1)];tri=tri[(tri[:,0]!=tri[:,1])&(tri[:,1]!=tri[:,2])&(tri[:,0]!=tri[:,2])]
   cross=np.cross(pos[tri[:,1]]-pos[tri[:,0]],pos[tri[:,2]]-pos[tri[:,0]]);agree=np.einsum('ij,ij->i',cross,normal[tri].mean(axis=1));nonzero=agree[np.abs(agree)>1e-14]
   if len(nonzero) and np.median(nonzero)<0:tri=tri[:,[0,2,1]]
   ns=[weapon.bn.get(i) if weapon else n['name'] for i,n in enumerate(model['nodes'])]
   vw=[[(ns[int(i)],float(w)) for i,w in zip(ii,ww) if w>0] for ii,ww in zip(ids,weights)]
   weighted.update(n for row in vw for n,w in row)
   material=model['materials'][m['material']];base=select_primary(material,1);uvindex=base.get('sampler',{}).get('UVIndex',0) if base else 0;uvscale=base.get('uv_scale',[1,1]) if base else [1,1]
   uv=np.array([v[uvindex][:2] if len(v)>uvindex else [0,0] for v in m['uv']],float)*uvscale;uv[:,1]=1-uv[:,1]
   meshname=safe_name((weapon.tag if weapon else Path(file).stem)+'_'+str(mi));mask=re.search(r'#([0-9]+)#',material['name']);group=weapon.root if weapon else ('mask_'+mask[1] if mask else 'body')
   meshes.append(dict(name=meshname,pos=pos,normal=normal,uv=uv,tri=tri,weights=vw,material=mat.export(material),group=group))
 # Scan local channel scales: single exceptional axis becomes two anchor joints.
 scale_min=refs[:,7:].copy();scale_max=scale_min.copy()
 for c in pkg['clips']:
  raw=np.fromfile(p/c['file'],dtype='<f4').reshape(c['frames'],len(c['map']),10)[:,:,7:]
  for ti,bi in enumerate(c['map']):scale_min[bi]=np.minimum(scale_min[bi],raw[:,ti].min(axis=0));scale_max[bi]=np.maximum(scale_max[bi],raw[:,ti].max(axis=0))
 axial=set()
 for i,b in enumerate(sk):
  if max(np.ptp(scale_min[i]),np.ptp(scale_max[i]))>1e-4:
   axial.add(b['name'])
   for n in nodes:
    par=nodes[n].get('_parent_name');seen=set()
    while par and par not in seen:
     if par==b['name']:axial.add(n);break
     seen.add(par);par=nodes.get(par,{}).get('_parent_name')
 # Bind-space small nonuniform scales also need compensation.
 axial|={n for n,m in source_rest.items() if np.ptp(np.linalg.norm(m[:3,:3],axis=0))>1e-4}
 axial &= weighted
 tetra_names={w.bn[i] for w in weapons if w.slot!='GH' for i in w.used}&weighted
 axial-=tetra_names
 anchors={};tetra={}
 for n in sorted(axial):
  vals=[]
  for mesh in meshes:
   vi=[i for i,row in enumerate(mesh['weights']) if any(b==n and w>0 for b,w in row)]
   if vi:vals.extend((np.column_stack((mesh['pos'][vi],np.ones(len(vi))))@np.linalg.inv(rests[n]).T)[:,0])
  lo,hi=float(min(vals)),float(max(vals));anchors[n]=(lo,hi if hi-lo>1e-8 else lo+1e-8)
 for n in sorted(tetra_names):
  points=[]
  for mesh in meshes:
   vi=[i for i,row in enumerate(mesh['weights']) if any(b==n and w>0 for b,w in row)]
   if vi:points.extend((np.column_stack((mesh['pos'][vi],np.ones(len(vi))))@np.linalg.inv(rests[n]).T)[:,:3])
  points=np.array(points);lo=points.min(axis=0)-1e-5;span=np.maximum(points.max(axis=0)-lo,1e-5)*3.001
  tetra[n]=np.array([lo,lo+[span[0],0,0],lo+[0,span[1],0],lo+[0,0,span[2]]])
 if args.rig_template:
  template=read(args.rig_template);anchors={n:tuple(v) for n,v in template['stretch_anchors'].items()};tetra={n:np.array(v) for n,v in template.get('tetra_anchors',{}).items()}
 # Preserve ancestors; discard truly unused control branches.
 keep=set(weighted)
 for n in list(keep):
  par=parent.get(n);seen=set()
  while par in rests and par not in seen:keep.add(par);seen.add(par);par=parent.get(par)
 order=[]
 def visit(n):
  if n in order:return
  par=parent.get(n)
  if par in keep:visit(par)
  order.append(n)
 for n in sorted(keep):visit(n)
 names=['sct_motion']+order;bind={'sct_motion':np.eye(4)};bind.update({n:rests[n] for n in order});parnames={'sct_motion':None};parnames.update({n:parent.get(n) if parent.get(n) in keep else 'sct_motion' for n in order})
 for n in sorted(anchors):
  for suffix in ('lo','hi'):
   hn='SCT_STRETCH_'+safe_name(n)+'_'+suffix;names.append(hn);bind[hn]=rests[n].copy();parnames[hn]=n
 for n in sorted(tetra):
  for i in range(4):
   hn='SCT_AFF_'+safe_name(n)+'_'+str(i);names.append(hn);bind[hn]=rests[n].copy();parnames[hn]=n
 index={n:i for i,n in enumerate(names)};bones=[]
 for n in names:
  par=parnames[n];local=np.linalg.inv(bind[par])@bind[n] if par else bind[n];pos,rot,scale=decompose(local);bones.append(dict(name=n,parent=index[par] if par else -1,pos=[x*UNIT for x in pos],rot=rot,scale=scale))
 def remap_weights(mesh):
  result=[]
  for v,row in zip(mesh['pos'],mesh['weights']):
   rw=[]
   for n,w in row:
    if n in tetra:
     point=(np.linalg.inv(rests[n])@np.r_[v,1])[:3];t=tetra[n];bary=(point-t[0])/np.diag(t[1:]-t[0]);values=np.r_[1-bary.sum(),bary]
     if values.min()<-1e-8:raise ValueError('Tetra weights outside hull')
     for i,f in enumerate(values):
      if f>1e-12:rw.append((index['SCT_AFF_'+safe_name(n)+'_'+str(i)],w*f))
    elif n in anchors:
     x=(np.linalg.inv(rests[n])@np.r_[v,1])[0];lo,hi=anchors[n];alpha=np.clip((x-lo)/(hi-lo),0,1)
     for suffix,f in [('lo',1-alpha),('hi',alpha)]:
      if f>1e-12:rw.append((index['SCT_STRETCH_'+safe_name(n)+'_'+suffix],w*f))
    else:rw.append((index[n],w))
   result.append(rw)
  return result
 model=Model(name,bones)
 for mesh in meshes:
  mesh['export_weights']=remap_weights(mesh);model.mesh(mesh['name'],mesh['pos']*UNIT,mesh['normal'],mesh['uv'],mesh['tri'],mesh['export_weights'],mesh['material']);report['meshes'].append({'name':mesh['name'],'vertices':len(mesh['pos']),'triangles':len(mesh['tri']),'group':mesh['group'],'material':mesh['material'],'max_influences':max(map(len,mesh['export_weights']))})
 model.write(out/'mesh.dmx');del model
 report['mesh_groups']=[]
 for group in sorted({m['group'] for m in meshes}):
  dm=Model(name,bones)
  for mesh in meshes:
   if mesh['group']==group:dm.mesh(mesh['name'],mesh['pos']*UNIT,mesh['normal'],mesh['uv'],mesh['tri'],mesh['export_weights'],mesh['material'])
  path=out/'meshes'/(safe_name(group)+'.dmx');dm.write(path)
  report['mesh_groups'].append({'name':safe_name(group),'file':path.relative_to(addon).as_posix()})
 for mesh in meshes:
  mesh['v4']=np.column_stack((mesh['pos'],np.ones(len(mesh['pos']))))
  for src,key in [('weights','source_groups'),('export_weights','export_groups')]:
   groups={}
   for vi,row in enumerate(mesh[src]):
    for bone,weight in row:
     entry=groups.setdefault(bone,[[],[]]);entry[0].append(vi);entry[1].append(weight)
   mesh[key]={bone:(np.array(v,int),np.array(w,float)[None,:,None]) for bone,(v,w) in groups.items()}
 report['bones']=bones;report['stretch_anchors']=anchors;report['tetra_anchors']={n:t.tolist() for n,t in tetra.items()};report['materials']=mat.records
 face=FaceOverlay(pkg,p);db=database(p);weapon_policy=NpcWeaponPolicy(pkg,p)
 invsource={n:np.linalg.inv(m) for n,m in source_rest.items()};invbind={n:np.linalg.inv(m) for n,m in bind.items()}
 # Resume only when the complete source package and converter code match.
 hasher=hashlib.sha256((p/'package.json').read_bytes())
 for dep in ['cs2_export.py','cs2_dmx.py','cs2_materials.py','internal_fk_verified.py','flver_mapping.py','face_overlay.py','face_simulation.py','equipment_core.py','event_states.py','model_masks.py','npc_weapons.py','vendor/datamodel.py']:
  hasher.update((Path(__file__).parent/dep).read_bytes())
 inputs={p/f for f in pkg['models']}|{p/c['file'] for c in pkg['clips']}
 if (p/'tae.json').exists():inputs.add(p/'tae.json')
 if (p/'equipment').exists():inputs.update((p/'equipment').rglob('*.json'))
 for file in sorted(inputs):
  hasher.update(file.relative_to(p).as_posix().encode('utf-8'))
  with file.open('rb') as stream:hasher.update(hashlib.file_digest(stream,'sha256').digest())
 fingerprint=hasher.hexdigest();resume_file=out/'resume.json';resume=read(resume_file) if resume_file.exists() else {}
 if resume.get('fingerprint')!=fingerprint:resume={'fingerprint':fingerprint,'actions':{}}
 for ci,c in enumerate(clips):
  default,weapon_evidence=weapon_policy.resolve(c)
  previous=resume['actions'].get(c['name'])
  if previous and (addon/previous['file']).exists() and hashlib.sha256((addon/previous['file']).read_bytes()).hexdigest()==previous.get('dmx_sha256'):
   report['actions'].append(previous);report['max_vertex_error_m']=max(report['max_vertex_error_m'],previous['vertex_error_m']);print('CS2_RESUME',ci+1,c['name'],flush=True);continue
  nf=c['frames'];times=np.arange(nf)*c['dt'];raw=np.fromfile(p/c['file'],dtype='<f4').reshape(nf,len(c['map']),10);local=np.broadcast_to(refs,(nf,len(sk),10)).copy()
  for ti,bi in enumerate(c['map']):local[:,bi]=raw[:,ti]
  local=face.apply(c,local,report);fk=fk_separate_scale(parents,local[:,:,:3],local[:,:,3:7],local[:,:,7:],C);global_source=mapped_fk(nodes,sknames,fk)
  resolution=db.resolve_action(c['name'],key_kind='hkx');events=db.animations.get(resolution.get('source_tae_key'),{}).get('events',[]);visibility={}
  if weapons:
   er=edb.resolve_action(c['name'],key_kind='hkx');taeid=E.fullid(er['tae_key']) if er.get('tae_key') else E.fullid(c['name']);states=[edb.get_state(c['name'],float(t),key_kind='hkx') for t in times];dcache={}
   def dummy(rid):
    if rid in dcache:return dcache[rid]
    d=dummies[rid];m=np.broadcast_to(np.eye(4),(nf,4,4)).copy()
    if d['parent']>=0:m=global_source[character['nodes'][d['parent']]['name']].copy()
    m=m@matrix(d['frame'])
    if d['attach']>=0 and d['follow']:
     n=character['nodes'][d['attach']]['name'];m=global_source[n]@invsource[n]@m
    dcache[rid]=m;return m
   for w in weapons:
    ss=[s['slots'][w.slot][w.index] for s in states];ids=[s['dummy'] for s in ss];vis=[bool(s['visible'] and s['dummy'] in dummies) for s in ss];visibility[w.root]=vis
    mats=np.array([dummy(rid)[i] if rid in dummies else np.eye(4) for i,rid in enumerate(ids)]);global_source[w.root]=mats
    internal,aid=w.internal(taeid,times)
    for i in w.used:global_source[w.bn[i]]=mats@np.array(internal[i])
  for group in {m['group'] for m in meshes if m['group'].startswith('mask_')}:
   mask=int(group[5:]);visibility[group]=[mask_states(default,[e for e in events if e['type'] in (233,711,713)],float(t))[mask] for t in times]
  # Convert each affine target to rigid+uniform base and axial translation helpers.
  target={};export_global={};max_matrix=0.0
  for n in order:
   target[n]=global_source[n]@invsource[n]@rests[n]
   g=target[n].copy();a=g[:,:3,:3];sx=np.linalg.norm(a[:,:,0],axis=1);sy=np.linalg.norm(a[:,:,1],axis=1);sz=np.linalg.norm(a[:,:,2],axis=1);su=(sy+sz)*.5;rotation=a/np.maximum(np.stack((sx,sy,sz),axis=1)[:,None,:],1e-20)
   # Project all base joints (including unweighted equipment roots) onto
   # proper similarity transforms. A sheared parent followed by a local TRS
   # decomposition would otherwise silently lose the residual downstream.
   u,sv,vt=np.linalg.svd(a);rot=u@vt;negative=np.linalg.det(rot)<0
   u[negative,:,-1]*=-1;rot=u@vt
   base=g.copy();base[:,:3,:3]=rot*su[:,None,None]
   export_global[n]=base
   if n in tetra:
    residual=g[:,:3,:3]-base[:,:3,:3]
    for i,point in enumerate(tetra[n]):
     hn='SCT_AFF_'+safe_name(n)+'_'+str(i);h=base.copy();h[:,:3,3]+=residual@point;export_global[hn]=h
   elif n in anchors:
    for suffix,x in zip(('lo','hi'),anchors[n]):
     hn='SCT_STRETCH_'+safe_name(n)+'_'+suffix;h=base.copy();h[:,:3,3]+=rotation[:,:,0]*(sx-su)[:,None]*x;export_global[hn]=h
   elif n in weighted:max_matrix=max(max_matrix,float(np.max(np.abs(base-g))))
  # Check the entire linear skinning operator on EVERY frame. The anchor
  # weights are affine functions of the bind-space X coordinate.
  operator_error=0.0;displacement_bound=0.0;worst_operator=None
  for n in weighted:
   wanted=(target[n]@invbind[n])[:,:3,:]
   if n in tetra:
    t=tetra[n];hs=[export_global['SCT_AFF_'+safe_name(n)+'_'+str(i)]@invbind[n] for i in range(4)];predicted=hs[0][:,:3,:].copy()
    for axis in range(3):
     row=invbind[n][axis].copy();row[3]-=t[0,axis];row/=(t[axis+1,axis]-t[0,axis])
     predicted+=(hs[axis+1][:,:3,3]-hs[0][:,:3,3])[:,:,None]*row[None,None,:]
   elif n in anchors:
    lo,hi=anchors[n];a=export_global['SCT_STRETCH_'+safe_name(n)+'_lo']@invbind[n];b=export_global['SCT_STRETCH_'+safe_name(n)+'_hi']@invbind[n]
    row=invbind[n][0].copy()/(hi-lo);row[3]-=lo/(hi-lo)
    predicted=a[:,:3,:]+(b[:,:3,3]-a[:,:3,3])[:,:,None]*row[None,None,:]
   else:predicted=(export_global[n]@invbind[n])[:,:3,:]
   difference=np.abs(wanted-predicted);err=float(difference.max())
   if err>operator_error:operator_error=err;worst_operator=n
   # Bound the affine residual on the ACTUAL influenced bind-space domain,
   # across every source frame. Coefficients alone mix meters and dimensionless values.
   for mesh in meshes:
    if n not in mesh['source_groups']:continue
    vi,_=mesh['source_groups'][n];bounds=np.abs(mesh['v4'][vi]).max(axis=0)
    displacement_bound=max(displacement_bound,float(np.max(np.linalg.norm(difference@bounds,axis=1))))
  if displacement_bound>2e-4:raise ValueError(f'Unsupported affine deformation in {c["name"]}: bone {worst_operator}, bound {displacement_bound} m, operator {operator_error}')
  # Also validate all vertices at first/mid/last against the actual weights.
  max_vertex=0.0
  for mesh in meshes:
   checks=sorted(set([0,nf//2,nf-1]));v=mesh['v4'];expected=np.zeros((len(checks),len(v),3));actual=np.zeros_like(expected)
   for n,(vi,ws) in mesh['source_groups'].items():expected[:,vi]+=np.einsum('fij,vj->fvi',(target[n]@invbind[n])[checks],v[vi])[:,:,:3]*ws
   for ni,(vi,ws) in mesh['export_groups'].items():
    n=names[ni];actual[:,vi]+=np.einsum('fij,vj->fvi',(export_global[n]@invbind[n])[checks],v[vi])[:,:,:3]*ws
   max_vertex=max(max_vertex,float(np.max(np.linalg.norm(expected-actual,axis=2))))
  report['max_vertex_error_m']=max(report['max_vertex_error_m'],max_vertex)
  if max_vertex>2e-4:raise ValueError(f'CS2 scale reconstruction error {max_vertex:.6f}m in {c["name"]}; export stopped rather than losing deformation')
  # Source root samples already use the pipeline's Blender Z-up coordinates.
  rm=np.array(c['rootMotion']['samples']);motion=np.tile(np.eye(4),(nf,1,1))
  if len(rm):
   for k in range(3):motion[:,k,3]=np.interp(times,rm[:,0],rm[:,k+1])
   for i,t in enumerate(times):
    vals=[np.interp(t,rm[:,0],rm[:,k]) for k in range(4,8)];from mathutils import Quaternion
    motion[i,:3,:3]=np.array(Quaternion(vals).normalized().to_matrix())
  export_global['sct_motion']=motion
  # anatomical children are relative to motion, but the body's raw transform
  # is local to that motion: include it once, never double-transform children.
  for n in names[1:]:export_global[n]=motion@export_global[n]
  positions=np.empty((nf,len(names),3));rotations=np.empty((nf,len(names),4));scales=np.empty((nf,len(names)));local_error=0.0
  for ni,n in enumerate(names):
   par=parnames[n];m=np.linalg.inv(export_global[par])@export_global[n] if par else export_global[n]
   for fi,mm in enumerate(m):
    pos,rot,scale=decompose(mm);positions[fi,ni]=np.array(pos)*UNIT;rotations[fi,ni]=rot;scales[fi,ni]=scale
    from internal_fk_verified import _quaternion_matrices
    rebuilt=_quaternion_matrices(np.array(rot));rebuilt[:3,:3]*=scale;rebuilt[:3,3]=pos;local_error=max(local_error,float(np.max(np.abs(rebuilt-mm))))
   for fi in range(1,nf):
    if rotations[fi-1,ni]@rotations[fi,ni]<0:rotations[fi,ni]*=-1
  if local_error>2e-5:raise ValueError(f'Local scalar TRS reconstruction failed: {c["name"]} {local_error}')
  animname=safe_name(c['name']);dm=Model(name,bones);dm.animation(animname,times,positions,rotations,scales,1/c['dt']);dst=out/'animations'/(animname+'.dmx');dm.write(dst)
  vis_events=[]
  for group,vals in visibility.items():
   last=None
   for fi,v in enumerate(vals):
    if v!=last:vis_events.append({'group':safe_name(group),'frame':fi,'value':int(v)});last=v
  rec=dict(source=c['name'],name=animname,file=dst.relative_to(addon).as_posix(),frames=nf,fps=1/c['dt'],duration=float(times[-1]),vertex_error_m=max_vertex,all_frame_operator_error=operator_error,all_frame_displacement_bound_m=displacement_bound,local_trs_error=local_error,worst_operator_bone=worst_operator,visibility_events=vis_events);report['actions'].append(rec)
  rec['dmx_sha256']=hashlib.sha256(dst.read_bytes()).hexdigest();resume['actions'][c['name']]=rec;save(resume_file,resume)
  save(out/'export_report.json',report);print('CS2_ACTION',ci+1,len(clips),animname,'vertex_error_m',max_vertex,flush=True)
 report.update(passed=not report['issues'],source_package=str(p),mesh_file=(out/'mesh.dmx').relative_to(addon).as_posix(),limited=bool(args.limit),selected=len(clips),total=len(pkg['clips']))
 save(out/'export_report.json',report);print('CS2_EXPORT_DONE',len(clips),len(bones),flush=True)
if __name__=='__main__':main()
