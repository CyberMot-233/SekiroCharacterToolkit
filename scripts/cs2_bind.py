"""Stable Source 2 bind frames without changing the skinning operator.

The importer converts bind rotations through Euler angles, which loses accuracy
near gimbal lock. Use identity world rotations in the CS2 bind skeleton and
conjugate each local animation by the corresponding constant basis change.
Original DMX files remain intact; converted files live under source2/.
"""
import copy,hashlib,json
from pathlib import Path
import numpy as np
from cs2_common import read,save
from cs2_dmx import d,Model
from hierarchy_math import decompose_many
from internal_fk_verified import _quaternion_matrices

VERSION='identity-world-bind-v4-stable-scale-parent'
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prepare(addon,name,export,fixed_bones=None):
    addon=Path(addon);base=addon/f'rawmodels/sekiro/characters/{name}';out=base/'source2';out.mkdir(exist_ok=True)
    mesh=d.load(str(addon/export['mesh_file']));joints=[j for j in mesh.root['skeleton']['jointList'] if j.type=='DmeJoint'];names=[j.name for j in joints]
    parents={c.name:j.name for j in joints for c in j['children'] if c.type=='DmeJoint'}
    old={};new={};change={};bones=[];export_parents=dict(parents);depths={}
    # Source 2 first reconstructs world poses in float32, then divides by the
    # parent's scale when rebuilding local channels. A .001 hide-scale turns
    # cancellation noise into .02+ unit offsets even with compression disabled.
    # Move children of near-zero-scale bones to the nearest stable ancestor;
    # conjugate/rebake below preserves every world skinning transform.
    small_scale=set()
    for record in export['actions']:
        dm=d.load(str(addon/record['file']))
        for ch in dm.root['animationList']['animations'][0]['channels']:
            if ch['toAttribute']=='scale' and np.min(np.abs(ch['log']['layers'][0]['values']))<.01:
                small_scale.add(ch['toElement'].name)
    for j in joints:
        p=parents.get(j.name);depths[j.name]=depths.get(p,0)+1
        if j.name.startswith('DSAS_GH') and '__' in j.name and p and '__' in p and depths[j.name]%4==0:export_parents[j.name]=j.name.split('__')[0]
        ep=export_parents.get(j.name)
        while ep in small_scale:ep=export_parents.get(ep)
        if ep!=export_parents.get(j.name):export_parents[j.name]=ep
    if fixed_bones is not None:
        if [b['name'] for b in fixed_bones]!=names:raise ValueError('新增动作源骨架与已有 CS2 模型不兼容；原件保持不变')
        export_parents={b['name']:fixed_bones[b['parent']]['name'] if b['parent']>=0 else None for b in fixed_bones}
    for j in joints:
        t=j['transform'];m=_quaternion_matrices(t['orientation']);m[:3,:3]*=t.get('scale',1.0);m[:3,3]=t['position'];p=parents.get(j.name)
        old[j.name]=old[p]@m if p else m
        n=np.eye(4);n[:3,3]=old[j.name][:3,3];new[j.name]=n;change[j.name]=np.linalg.inv(old[j.name])@n
        ep=export_parents.get(j.name);local=np.linalg.inv(new[ep])@n if ep else n
        bones.append(dict(name=j.name,parent=names.index(ep) if ep else -1,pos=local[:3,3].tolist(),rot=[0,0,0,1],scale=1.0))
    bi={b['name']:b for b in bones};report={'version':VERSION,'passed':False,'actions':[],'max_local_matrix_error':0.0,'max_world_matrix_error':0.0,'stable_parent_changes':[{'bone':n,'source_parent':parents.get(n),'export_parent':p} for n,p in export_parents.items() if p!=parents.get(n)],'scope':'Every source animation key: constant basis change, scalar TRS and world matrix reconstruction. Render geometry and named weights unchanged.'}
    if fixed_bones is not None:
        for a,b in zip(bones,fixed_bones):
            if a['parent']!=b['parent'] or np.max(abs(np.array(a['pos'])-b['pos']))>2e-4 or np.max(abs(np.array(b['rot'])-[0,0,0,1]))>1e-6:raise ValueError('已有 CS2 绑定空间不同；请先维修绑定')
        bones=copy.deepcopy(fixed_bones);bi={b['name']:b for b in bones}
    fingerprint=hashlib.sha256((VERSION+json.dumps(bones,sort_keys=True)).encode()).hexdigest()
    cachefile=out/'resume.json';cache=read(cachefile) if cachefile.exists() else {}
    if cache.get('fingerprint')!=fingerprint:cache={'fingerprint':fingerprint,'actions':{}}
    def mesh_file(src,dst):
        dm=d.load(str(src));sk=dm.root['skeleton']
        js={j.name:j for j in sk['jointList'] if j.type=='DmeJoint'}
        for j in js.values():j['children']=d.make_array([c for c in j['children'] if c.type!='DmeJoint'],d.Element)
        sk['children']=d.make_array([c for c in sk['children'] if c.type!='DmeJoint'],d.Element)
        for bn,j in js.items():
            par=export_parents.get(bn);(js[par] if par else sk)['children'].append(j)
        for joint in sk['jointList']:
            if joint.type=='DmeJoint':
                t=joint['transform'];t['position']=d.Vector3(bi[joint.name]['pos']);t['orientation']=d.Quaternion([0,0,0,1]);t['scale']=1.0
        for t in sk['baseStates'][0]['transforms']:
            if t.name in bi:t['position']=d.Vector3(bi[t.name]['pos']);t['orientation']=d.Quaternion([0,0,0,1]);t['scale']=1.0
        dst.parent.mkdir(exist_ok=True,parents=True);dm.write(str(dst),'binary',9)
    result=copy.deepcopy(export);result['bones']=bones;result['bind_encoding']=VERSION
    dest=out/'mesh.dmx';mesh_file(addon/export['mesh_file'],dest);result['mesh_file']=dest.relative_to(addon).as_posix()
    for group in result['mesh_groups']:
        src=addon/group['file'];dest=out/'meshes'/src.name;mesh_file(src,dest);group['file']=dest.relative_to(addon).as_posix()
    for ci,record in enumerate(result['actions']):
        src=addon/record['file'];dest=out/'animations'/src.name;sha=digest(src);previous=cache['actions'].get(record['source'])
        if previous and previous['source_sha256']==sha and dest.exists() and digest(dest)==previous['sha256']:
            check=previous
        else:
            dm=d.load(str(src));clip=dm.root['animationList']['animations'][0];channels={}
            for ch in clip['channels']:
                layer=ch['log']['layers'][0];channels[(ch['toElement'].name,ch['toAttribute'])]=(np.array(layer['times'],float),np.array(layer['values'],float))
            nf=record['frames'];times=np.arange(nf)/record['fps']
            ps=np.empty((nf,len(bones),3));qs=np.empty((nf,len(bones),4));ss=np.empty((nf,len(bones)));err=0.0
            globals_old={};globals_new={};world_error=0.0
            for i,j in enumerate(joints):
                vals={}
                for attr in ('position','orientation','scale'):
                    tt,v=channels[(j.name,attr)];values=np.interp(times,tt,v) if v.ndim==1 else np.column_stack([np.interp(times,tt,v[:,k]) for k in range(v.shape[1])])
                    ix=np.searchsorted(tt,times);right=np.minimum(ix,len(tt)-1);left=np.maximum(ix-1,0);near=np.where(abs(tt[left]-times)<abs(tt[right]-times),left,right);snap=abs(tt[near]-times)<=.000101
                    values[snap]=v[near[snap]];vals[attr]=values
                m=_quaternion_matrices(vals['orientation']);m[:,:3,:3]*=vals['scale'][:,None,None];m[:,:3,3]=vals['position'];p=parents.get(j.name)
                globals_old[j.name]=globals_old[p]@m if p else m
                ep=export_parents.get(j.name);m=(np.linalg.inv(globals_old[ep]@change[ep])@globals_old[j.name] if ep else globals_old[j.name])@change[j.name]
                rows=decompose_many(m);ps[:,i]=rows[:,:3];qs[:,i]=rows[:,[4,5,6,3]];ss[:,i]=rows[:,7:].mean(axis=1)
                rebuilt=_quaternion_matrices(qs[:,i]);rebuilt[:,:3,:3]*=ss[:,i,None,None];rebuilt[:,:3,3]=ps[:,i]
                err=max(err,float(np.max(abs(rebuilt-m))))
                globals_new[j.name]=globals_new[ep]@rebuilt if ep else rebuilt
                world_error=max(world_error,float(np.max(abs(globals_new[j.name]-globals_old[j.name]@change[j.name]))))
            if err>2e-5:raise ValueError(f'Bind frame scalar TRS residual: {record["source"]}: {err}')
            if world_error>2e-4:raise ValueError(f'Bind frame world reconstruction residual: {record["source"]}: {world_error}')
            dm=Model(name,bones);dm.animation(record['name'],times,ps,qs,ss,record['fps']);dm.write(dest)
            check={'source':record['source'],'source_sha256':sha,'sha256':digest(dest),'keys':nf,'max_local_matrix_error':err,'max_world_matrix_error':world_error}
            cache['actions'][record['source']]=check;save(cachefile,cache)
        record['file']=dest.relative_to(addon).as_posix();record['dmx_sha256']=check['sha256'];report['actions'].append(check);report['max_local_matrix_error']=max(report['max_local_matrix_error'],check['max_local_matrix_error'])
        report['max_world_matrix_error']=max(report['max_world_matrix_error'],check['max_world_matrix_error'])
        if ci%25==0:print('CS2_BIND',ci+1,len(result['actions']),flush=True)
    report['passed']=True;save(out/'bind_validation.json',report);save(out/'export_report.json',result);return result
