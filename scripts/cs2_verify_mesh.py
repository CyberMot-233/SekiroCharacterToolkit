import sys,struct,subprocess,json,itertools,collections,argparse,re
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor/sourceio_mesh'))
import pylib
from cs2_kvtext import loads
from cs2_dmx import d
from cs2_common import save,read,cs_root
def weight_encoding_error(expected,actual,bits):
 """Compare the codec, not arbitrary relaxed weight tolerances.
 CS2 rounds each UNORM weight, then corrects the sum on a largest weight.
 Ties may be sorted differently. One half-step per other influence and the
 exact unit sum bound the correction. 16-bit keeps the original strict test.
 """
 keys=expected.keys()|actual.keys()
 error=max((abs(expected.get(k,0)-actual.get(k,0)) for k in keys),default=0)
 if bits==16:return error<=5e-5,error
 if any(k not in expected for k,v in actual.items() if v>0):return False,error
 if abs(sum(actual.values())-1)>1e-6:return False,error
 peak=max(expected.values(),default=0);count=len(expected)
 for k in keys:
  a=actual.get(k,0);e=expected.get(k,0)
  if abs(a*255-round(a*255))>1e-5:return False,error
  bound=(count*.5 if abs(e-peak)<1e-7 else .5)/255+1e-7
  if abs(a-e)>bound:return False,error
 return True,error

def verify(addon,name,capture=False):
 addon=Path(addon).resolve();root=cs_root(addon);base=addon/f'rawmodels/sekiro/characters/{name}';reports=base/'reports'
 reports.mkdir(parents=True,exist_ok=True)
 model=root/f'game/csgo_addons/{addon.name}/models/sekiro/characters/{name}/{name}.vmdl_c'
 exported=read(base/'compile_export.json') if (base/'compile_export.json').exists() else read(base/'export_report.json')
 group_files={g['name']:addon/g['file'] for g in exported['mesh_groups']}
 data=model.read_bytes();size,version,rversion,offset,count=struct.unpack_from('<IHHII',data);assert version==12
 blocks=[]
 for i in range(count):
  at=8+offset+12*i;tag,rel,length=struct.unpack_from('<4sII',data,at);blocks.append((tag.decode(),data[at+4+rel:at+4+rel+length]))
 def info(block):
  run=subprocess.run([str(root/'game/bin/win64/resourceinfo.exe'),'-i',str(model),'-b',block,'-baremode','-maxelements','99999999'],capture_output=True,check=True,encoding='utf-8');return loads(run.stdout)
 ctrl=info('CTRL');doc=info('DATA');names=doc['m_modelSkeleton']['m_boneName'];report={'passed':False,'meshes':[],'issues':[]}
 from internal_fk_verified import _quaternion_matrices
 source=d.load(str(addon/exported['mesh_file']));bones=[j for j in source.root['skeleton']['jointList'] if j.type=='DmeJoint'];parents={c.name:j.name for j in bones for c in j['children'] if c.type=='DmeJoint'};world={}
 for b in bones:
  t=b['transform'];m=_quaternion_matrices(t['orientation']);m[:3,:3]*=t.get('scale',1.0);m[:3,3]=t['position'];p=parents.get(b.name);world[b.name]=world[p]@m if p else m
 inv={n:np.linalg.inv(m) for n,m in world.items()};vmdl=loads((addon/f'models/sekiro/characters/{name}/{name}.vmdl').read_text('utf-8'))
 for container in vmdl['rootNode']['children']:
  if container['_class']=='RenderMeshList':
   for m in container['children']:
    marks=[x for x in m.get('children',[]) if x['_class']=='RenderMeshMarkup']
    if not marks or any(x.get('high_precision_blendweights') or x.get('blend_weights_per_vertex')!='8' for x in marks):report['issues'].append({'group':m['name'],'gpu_profile_mismatch':'Toolkit requires uniform 8xUNORM8 for current CS2 shaders'})
 attachments={x['name']:x for node in vmdl['rootNode']['children'] if node['_class']=='AttachmentList' for x in node['children']}
 output=subprocess.run([str(root/'game/bin/win64/resourceinfo.exe'),'-i',str(model),'-b','MDAT','-baremode','-maxelements','99999999'],capture_output=True,check=True,encoding='utf-8').stdout
 chunks=[loads(x) for x in re.split(r'(?m)(?=^\{)',output) if x.strip()];attachment_checks=0;bind_error=0.0
 for mi,meshdata in enumerate(chunks):
  for b in meshdata['m_skeleton']['m_bones']:
   if b['m_boneName'] not in inv:report['issues'].append({'unknown_mesh_bind':b['m_boneName']});continue
   error=float(np.max(abs(np.array(b['m_invBindPose']).reshape(3,4)-inv[b['m_boneName']][:3])));bind_error=max(bind_error,error)
   if error>1e-3:report['issues'].append({'mesh':mi,'bone':b['m_boneName'],'inverse_bind_error':error})
  actual={x['key']:x['value'] for x in meshdata.get('m_attachments',[])}
  for an,expected in attachments.items():
   got=actual.get(an)
   if not got:report['issues'].append({'mesh':mi,'missing_attachment':an});continue
   attachment_checks+=1
   error=float(np.max(abs(np.array(got['m_vInfluenceOffsets'][0])-expected['relative_origin'])))
   if got['m_influenceNames'][0]!=expected['parent_bone'] or error>1e-3 or got['m_nInfluences']!=1 or abs(got['m_influenceWeights'][0]-1)>1e-6:report['issues'].append({'mesh':mi,'attachment':an,'offset_error':error,'parent':got['m_influenceNames'][0]})
 report.update(attachment_checks=attachment_checks,max_inverse_bind_error=bind_error)
 formats={6:('<f4',3),16:('<f4',2),42:('<u4',1),30:('u1',4),11:('<u2',4),12:('<u2',4),13:('<i2',4),14:('<i2',4),4:('<i4',4),3:('<u4',4),28:('u1',4)}
 captured=[]
 for mesh in ctrl['embedded_meshes']:
  group=mesh['m_Name'];dm=d.load(str(group_files[group]));joints=dm.root['model']['jointList'];pool=[];grid=collections.defaultdict(list)
  for dag in dm.root['model']['children']:
   if dag.type!='DmeDag':continue
   v=dag['shape']['bindState'];pos=np.array(v['position$0']);uv=np.array(v['texcoord$0']);uv[:,1]=1-uv[:,1]
   weights=np.array(v['blendweights$0']).reshape(len(pos),v['jointCount']);ids=np.array(v['blendindices$0']).reshape(weights.shape)
   used=set(v['position$0Indices'])
   for i in used:
    w=collections.defaultdict(float)
    for bi,bw in zip(ids[i],weights[i]):
     if bw>0:w[joints[bi].name]+=float(bw)
    idx=len(pool);pool.append((pos[i],uv[i],dict(w)));grid[tuple(np.floor(pos[i]*1000).astype(int))].append(idx)
  remap=doc['m_remappingTable'][doc['m_remappingTableStarts'][mesh['m_nMeshIndex']]:];maxpos=maxuv=maxw=0.;checks=0;missing=0;max_influences=0;badweights=0;encodings=set()
  for buffer_index,desc in enumerate(mesh['m_vertexBuffers']):
   payload=blocks[desc['m_nBlockIndex']][1];stride=desc['m_nElementSizeInBytes'];n=desc['m_nElementCount']
   if len(payload)!=stride*n:payload=pylib.mesh.decode_vertex_buffer(payload,stride,n)
   attrs={}
   for field in desc['m_inputLayoutFields']:
    fmt,width=formats[field['m_Format']];a=np.ndarray((n,width),dtype=fmt,buffer=payload,offset=field['m_nOffset'],strides=(stride,np.dtype(fmt).itemsize));attrs[field['m_pSemanticName'].upper()]=(a,field['m_Format'])
   pos=attrs['POSITION'][0];uv=attrs['TEXCOORD'][0];indices,iformat=attrs['BLENDINDICES'];eight=iformat in (12,4)
   bits=(attrs['BLENDWEIGHT'][0].dtype.itemsize*8//(2 if eight else 1)) if 'BLENDWEIGHT' in attrs else 16;encodings.add(bits)
   if eight and bits==16:report['issues'].append({'group':group,'unsupported_gpu_blend_stream':'8x16-bit; ModelDoc spike regression'})
   if 'BLENDWEIGHT' not in attrs:
    # The compiler omits weights on rigid single-bone meshes. Validate the
    # resulting named weight against DMX just like an explicit stream.
    weights=np.zeros(indices.shape,dtype=float);weights[:,0]=1.0;eight=False
   elif eight:
    weights,wformat=attrs['BLENDWEIGHT']
    indices=np.ascontiguousarray(indices).view('u1' if iformat==12 else '<u2').reshape(n,8)
    weights=np.ascontiguousarray(weights).view('u1' if weights.dtype.itemsize==2 else '<u2').reshape(n,8).astype(float)/(255 if weights.dtype.itemsize==2 else 65535)
   else:
    weights,wformat=attrs['BLENDWEIGHT'];weights=weights.astype(float)/(65535 if weights.dtype.itemsize==2 else 255)
   matched=[]
   for i in range(n):
    actual=collections.defaultdict(float)
    for bi,bw in zip(indices[i],weights[i]):
     if bw>0:actual[names[remap[bi]]]+=float(bw)
    max_influences=max(max_influences,len(actual));key=np.floor(pos[i]*1000).astype(int);candidate=[]
    for delta in itertools.product((-1,0,1),repeat=3):candidate.extend(grid.get(tuple(key+delta),()))
    best=None
    for ci in candidate:
     pp,uu,ww=pool[ci];pe=float(np.max(abs(pp-pos[i])));ue=float(np.max(abs(uu-uv[i])))
     if pe>1e-3 or ue>1e-4:continue
     we=max((abs(ww.get(bn,0)-actual.get(bn,0)) for bn in ww.keys()|actual.keys()),default=0)
     item=(we,pe,ue,ci)
     if best is None or item<best:best=item
    if best is None:
     missing+=1
     if missing<4:
      nearest=int(np.argmin(np.linalg.norm(np.array([p[0] for p in pool])-pos[i],axis=1)));candidate=[nearest]
      report['issues'].append({'group':group,'vertex':i,'position':pos[i].tolist(),'uv':uv[i].tolist(),'missing_match':True,'candidates':[(pool[ci][0].tolist(),pool[ci][1].tolist(),float(np.max(abs(pool[ci][1]-uv[i])))) for ci in candidate[:6]]})
    else:
     we,pe,ue,ci=best;maxpos=max(maxpos,pe);maxuv=max(maxuv,ue);maxw=max(maxw,we);checks+=1;matched.append(ci)
     valid,_=weight_encoding_error(pool[ci][2],actual,bits)
     if not valid:
      badweights+=1
      if len(report['issues'])<20:report['issues'].append({'group':group,'vertex':i,'weight_error':we,'encoding_bits':bits,'expected':pool[ci][2],'actual':dict(actual)})
   if capture and len(matched)==n:
    positions=np.array([pool[i][0] for i in matched]);source_indices=np.zeros((n,8),dtype=np.int32);source_weights=np.zeros((n,8))
    for vi,ci in enumerate(matched):
     for wi,(bn,bw) in enumerate(pool[ci][2].items()):source_indices[vi,wi]=names.index(bn);source_weights[vi,wi]=bw
    target=reports/f'vertices_{group}_{buffer_index}.npz';np.savez_compressed(target,position=pos,uv=uv,indices=np.array(remap)[indices],weights=weights,source_position=positions,source_indices=source_indices,source_weights=source_weights);captured.append(str(target))
  item=dict(group=group,checked=checks,missing=missing,max_position_error= maxpos,max_uv_error=maxuv,max_weight_error=maxw,max_influences=max_influences,invalid_encoded_weights=badweights,weight_bits=sorted(encodings));report['meshes'].append(item);print(item,flush=True)
 report['captured_vertex_buffers']=captured
 report['passed']=not report['issues'] and all(m['missing']==0 and m['invalid_encoded_weights']==0 for m in report['meshes']);report['scope']='Every compiled MVTX vertex: position, UV and named weights; UNORM8 rounding/sum correction or strict UNORM16. Rejects GPU-incompatible 8x16 streams. Quantization error is reported, not equated to lossless skinning; runtime visual checks remain separate.';save(reports/'compiled_mesh_validation.json',report);print('MESH_VERIFY',report['passed']);return report

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--addon',required=True,type=Path);ap.add_argument('--name',required=True);ap.add_argument('--capture',action='store_true');a=ap.parse_args()
 if not verify(a.addon,a.name,a.capture)['passed']:raise SystemExit(1)
