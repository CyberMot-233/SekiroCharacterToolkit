"""Read official resourceinfo blocks and compare compiled skeleton/animation to DMX."""
import argparse,sys,subprocess,struct,math,json,collections
from pathlib import Path
import numpy as np
from cs2_common import cs_root,save,read
from cs2_kvtext import loads
from cs2_dmx import d

def quat6(data):
 b=list(data);i1=b[0]+((b[1]&63)<<8);i2=b[2]+((b[3]&63)<<8);i3=b[4]+((b[5]&63)<<8);c=math.sin(math.pi/4)/16384
 x=c*(i1-16384 if b[1]&64==0 else i1);y=c*(i2-16384 if b[3]&64==0 else i2);z=c*(i3-16384 if b[5]&64==0 else i3);w=math.sqrt(max(0,1-x*x-y*y-z*z))
 if b[5]&128:w=-w
 if b[1]&128:return (y,z,w,x) if b[3]&128 else (z,w,x,y)
 return (w,x,y,z) if b[3]&128 else (x,y,z,w)

def decode(anim,key,decoders,segments,frame,metadata=None):
 result={}
 for block in anim['m_pData']['m_frameblockArray']:
  if not block['m_nStartFrame']<=frame<=block['m_nEndFrame']:continue
  fi=frame-block['m_nStartFrame']
  for si in block['m_segmentIndexArray']:
   seg=segments[si];data=seg['m_container'];di,cardinality,count,total=struct.unpack_from('<4H',data);decoder=decoders[di]['m_szName'];elements=struct.unpack_from('<'+'H'*count,data,8);start=8+2*count
   channel=key['m_dataChannelArray'][seg['m_nLocalChannel']];lookup=dict(zip(channel['m_nElementIndexArray'],channel['m_szElementNameArray']));attr=channel['m_szVariableName'];static='Static' in decoder
   for i,elem in enumerate(elements):
    if decoder=='CCompressedDeltaVector3':
     base=np.array(struct.unpack_from('<3f',data,start+i*12));delta=np.array(struct.unpack_from('<3e',data,start+count*12+(fi*count+i)*6));v=base+delta
    elif decoder=='CCompressedFullQuaternion':
     v=struct.unpack_from('<4f',data,start+(fi*count+i)*16)
    elif 'Quaternion' in decoder:
     offset=start+((0 if static else fi)*count+i)*6;v=quat6(data[offset:offset+6])
    elif 'Vector3' in decoder:
     full='Full' in decoder;size=12 if full else 6;offset=start+((0 if static else fi)*count+i)*size;v=struct.unpack_from('<3f' if full else '<3e',data,offset)
    elif 'Float' in decoder:v=struct.unpack_from('<f',data,start+((0 if static else fi)*count+i)*4)[0]
    else:raise ValueError('Unsupported decoder '+decoder)
    result[(lookup[elem],attr)]=v
    if metadata is not None:metadata[(lookup[elem],attr)]=(decoder,block['m_nStartFrame'],block['m_nEndFrame'])
 return result

def static_half_quantization(actual,times,values,start,end,fps):
 """Identify the legacy compiler's constant half-vector encoding explicitly.

 It may discard <= .006 source-unit motion per 31-frame block and truncate
 to half precision even when disable_compression is true. Never use this
 exception for animated vectors, rotations, scales, or large hidden-bone errors.
 """
 indices=[int(np.argmin(abs(times-f/fps))) for f in range(start,end+1)]
 v=values[indices];extent=float(np.max(np.ptp(v,axis=0)))
 first=v[0];half=np.abs(first).astype(np.float16)
 ulp=np.nextafter(half,np.float16(np.inf)).astype(float)-half.astype(float)
 first_error=np.abs(actual-first);error=float(np.max(np.abs(v-actual)))
 passed=extent<=.006 and error<=.01 and bool(np.all(first_error<=ulp+3e-5))
 return dict(passed=passed,block=[start,end],source_extent=extent,first_sample_error=first_error.tolist(),half_ulp=ulp.tolist(),max_block_error=error)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--addon',required=True,type=Path);ap.add_argument('--name',default='wolf');ap.add_argument('--limit',type=int,default=0);ap.add_argument('--all-frames',action='store_true');a=ap.parse_args();addon=a.addon.resolve();root=cs_root(addon);base=addon/f'rawmodels/sekiro/characters/{a.name}';out=base/'reports';out.mkdir(exist_ok=True);exe=root/'game/bin/win64/resourceinfo.exe';model=root/f'game/csgo_addons/{addon.name}/models/sekiro/characters/{a.name}/{a.name}.vmdl_c'
 blocks={}
 for b in ('DATA','ANIM','AGRP','CTRL'):
  run=subprocess.run([str(exe),'-i',str(model),'-b',b,'-baremode','-maxelements','99999999'],capture_output=True,encoding='utf-8',errors='replace',check=True)
  (out/f'compiled_{b}.kv3').write_text(run.stdout,'utf-8');blocks[b]=loads(run.stdout)
 doc=loads((addon/f'models/sekiro/characters/{a.name}/{a.name}.vmdl').read_text('utf-8'));alist=next(n['children'] for n in doc['rootNode']['children'] if n['_class']=='AnimationList');sources={x['name']:x for x in alist};data=blocks['DATA'];sk=data['m_modelSkeleton'];names=sk['m_boneName'];parents=sk['m_nParent'];report={'passed':False,'compiled':str(model),'bone_count':len(names),'animation_count':len(blocks['ANIM']['m_animArray']),'issues':[],'actions':[],'root_motion':[]}
 compile_export=read(base/'compile_export.json') if (base/'compile_export.json').exists() else None
 if compile_export:
  from cs2_visibility import validate as validate_visibility
  visibility_issues=validate_visibility(doc,compile_export,data,blocks['CTRL'])
  report['bodygroup_visibility']={'passed':not visibility_issues,'issues':visibility_issues}
  report['issues'].extend(visibility_issues)
 first=d.load(str(addon/compile_export['mesh_file'] if compile_export else base/'mesh.dmx'));joints=first.root['skeleton']['jointList'];sourcebones={x.name:x for x in joints if x.type=='DmeJoint'}
 sourceparents={n:None for n in sourcebones}
 for n,b in sourcebones.items():
  for child in b['children']:
   if child.type=='DmeJoint':sourceparents[child.name]=n
 report['issues'].extend('Missing compiled bone '+n for n in sorted(set(sourcebones)-set(names)))
 compiled_names=[x['m_name'] for x in blocks['ANIM']['m_animArray']]
 if collections.Counter(compiled_names)!=collections.Counter(sources.keys()):report['issues'].append({'animation_set_mismatch':True,'missing':sorted(set(sources)-set(compiled_names)),'extra':sorted(set(compiled_names)-set(sources))})
 for i,n in enumerate(names):
  if n not in sourcebones:report['issues'].append('Unexpected compiled bone '+n);continue
  t=sourcebones[n]['transform'];pos=np.array(t['position']);q=np.array(t['orientation']);cpos=np.array(sk['m_bonePosParent'][i]);cq=np.array(sk['m_boneRotParent'][i]);err=float(np.linalg.norm(pos-cpos));ang=1-abs(float(q@cq))
  if err>1e-3 or ang>1e-5:report['issues'].append({'bone':n,'bind_position_error':err,'bind_quaternion_error':ang})
  actual_parent=names[parents[i]] if parents[i]>=0 else None
  if actual_parent!=sourceparents[n]:report['issues'].append({'bone':n,'parent':actual_parent,'expected_parent':sourceparents[n]})
  scale=float(t.get('scale',1.0));actual_scale=sk.get('m_boneScaleParent',[1.0]*len(names))[i]
  if abs(scale-actual_scale)>1e-5:report['issues'].append({'bone':n,'bind_scale':actual_scale,'expected_scale':scale})
 animations=blocks['ANIM']['m_animArray'];key=blocks['AGRP']['m_decodeKey']
 for anim in animations[:a.limit or None]:
  if anim['m_name'] not in sources:continue
  source=sources[anim['m_name']];dm=d.load(str(addon/source['source_filename']));clip=dm.root['animationList']['animations'][0];channels={}
  for ch in clip['channels']:
   layer=ch['log']['layers'][0];channels[(ch['toElement'].name,{'position':'Position','orientation':'Angle','scale':'Scale'}[ch['toAttribute']])]=(np.array(layer['times'],float),np.array(layer['values'],float))
  nf=anim['m_pData']['m_nFrames'];fps=anim['fps'];checks=list(range(nf)) if a.all_frames else sorted(set([0,nf//2,nf-1]));mxp=mxq=mxs=0.0;roots=[];root_yaws=[];worst=None;unexplained_position=0.0;quantized={}
  pos_limit=.002 if source.get('disable_compression') else .05;quat_limit=1e-8 if source.get('disable_compression') else 1e-4
  for frame in checks:
   metadata={};decoded=decode(anim,key,blocks['ANIM']['m_decoderArray'],blocks['ANIM']['m_segmentArray'],frame,metadata);t=frame/fps
   for (bn,attr),(times,values) in channels.items():
    if bn not in names:continue
    actual=np.array(decoded[(bn,attr)])
    # DmeTime uses integer 1/10000 s. The importer snaps a source key within
    # one tick of a frame boundary; comparing to interpolated rounded times
    # would incorrectly report fast facial motions as compiler distortion.
    nearest=int(np.argmin(abs(times-t)));snap=abs(times[nearest]-t)<=.000101
    expected=values[nearest].copy() if snap else (np.interp(t,times,values) if values.ndim==1 else np.array([np.interp(t,times,values[:,i]) for i in range(values.shape[1])]))
    if bn=='sct_motion' and attr=='Position':
     roots.append(actual.tolist());extract=next((x for x in source['children'] if x['_class']=='ExtractMotion'),None)
     if extract:
      if extract.get('extract_rz'):
       qt,qv=channels[('sct_motion','Angle')];qi=int(np.argmin(abs(qt-t)));qq=qv[qi]/np.linalg.norm(qv[qi]);q0=qv[0]/np.linalg.norm(qv[0])
       def yaw(q):
        x,y,z,w=q;return math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
       angle=-(yaw(qq)-yaw(q0));co,si=math.cos(angle),math.sin(angle);xx,yy=expected[:2];expected[:2]=[co*xx-si*yy,si*xx+co*yy]
      for axis,k in enumerate(['extract_tx','extract_ty','extract_tz']):
       if extract[k]:expected[axis]=actual[axis]
    if bn=='sct_motion' and attr=='Angle' and any(x.get('extract_rz') for x in source['children']):
     x,y,z,w=actual/np.linalg.norm(actual);root_yaws.append(math.atan2(2*(w*z+x*y),1-2*(y*y+z*z)));continue
    if attr=='Position':
     err=float(np.max(np.abs(actual-expected)))
     if err>mxp:mxp=err;worst=dict(bone=bn,frame=frame,actual=actual.tolist(),expected=expected.tolist(),time=t)
     explained=False;decoder,start,end=metadata[(bn,attr)]
     if err>pos_limit and bn!='sct_motion' and decoder=='CCompressedStaticVector3':
      precision=static_half_quantization(actual,times,values,start,end,fps)
      if precision['passed']:
       explained=True;quantized[(bn,start)]=dict(bone=bn,decoder=decoder,**precision)
     if not explained:unexplained_position=max(unexplained_position,err)
    elif attr=='Scale':mxs=max(mxs,float(np.max(np.abs(actual-expected))))
    else:
     expected/=np.linalg.norm(expected);actual/=np.linalg.norm(actual);mxq=max(mxq,1-abs(float(expected@actual)))
  record=dict(name=anim['m_name'],frames=nf,expected_frames=source['end_frame']+1,checked_frames=checks,max_position_error_source_units=mxp,max_quaternion_dot_error=mxq,max_scale_error=mxs,root_samples=roots,worst_position=worst)
  report['actions'].append(record)
  record['max_unexplained_position_error']=unexplained_position;record['static_half_quantization']=list(quantized.values())
  if nf!=source['end_frame']+1 or unexplained_position>pos_limit or mxq>quat_limit or mxs>1e-4:report['issues'].append(record)
  def event_signature(cls,frame,end,keys):return (cls,int(frame),int(end),json.dumps(keys,sort_keys=True,separators=(',',':')))
  expected_events=collections.Counter(event_signature(e['event_class'],e['event_frame'],e['event_end_frame'],e['event_keys']) for e in source['children'] if e['_class']=='AnimEvent')
  actual_events=collections.Counter(event_signature(e['m_sEventName'],e['m_nFrame'],e['m_nEndFrame'],e['m_EventData']) for e in anim.get('m_eventArray',[]))
  record['expected_events']=sum(expected_events.values());record['compiled_events']=sum(actual_events.values())
  if actual_events!=expected_events:report['issues'].append({'name':anim['m_name'],'missing_events':list((expected_events-actual_events).elements()),'extra_events':list((actual_events-expected_events).elements())})
  if abs(float(source['framerate'])-fps)>1e-4:report['issues'].append({'name':anim['m_name'],'fps_mismatch':[source['framerate'],fps]})
  extract=next((x for x in source['children'] if x['_class']=='ExtractMotion'),None)
  if extract and roots:
   for axis,keyname in enumerate(['extract_tx','extract_ty','extract_tz']):
    if extract[keyname] and np.ptp(np.array(roots)[:,axis])>.02:report['issues'].append({'name':anim['m_name'],'root_not_removed':axis,'values':roots})
  if root_yaws and np.ptp(np.unwrap(root_yaws))>1e-4:report['issues'].append({'name':anim['m_name'],'root_yaw_not_removed':root_yaws})
  print('CS2_VERIFY',anim['m_name'],mxp,mxq,mxs,flush=True)
 report['scope']='All named bind bones and parents, animation set; '+('all frames' if a.all_frames else 'first/middle/last frames')+' and exact event payloads of checked actions. Not render-mesh or runtime visual validation.'
 report['all_frames']=a.all_frames
 report['quantization_policy']='Strict .002 position limit with explicit legacy CCompressedStaticVector3 exception: source block variation <= .006, first-sample truncation <= one half ULP + .00003 and max error <= .01 Source units. Every exception is reported; animated vectors retain strict limit.'
 report['checked_actions']=len(report['actions']);report['passed']=not report['issues'];save(out/'compiled_validation.json',report);print('CS2_COMPILED_VERIFY',report['passed'],flush=True)
 if not report['passed']:
  for issue in report['issues']:print('CS2_VERIFY_ISSUE',json.dumps(issue,ensure_ascii=False),flush=True)
  print('CS2_VERIFY_REPORT',str(out/'compiled_validation.json'),flush=True)
  raise SystemExit(1)
if __name__=='__main__':main()
