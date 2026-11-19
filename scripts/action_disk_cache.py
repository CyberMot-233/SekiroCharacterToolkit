"""Lossless final FCurve spool: one live Action during authoring, one final save.

Caches contain data only (no pickle/code). Each committed action has SHA-256.
Late-discovered affine helpers are mapped on load, not rebaked.
"""
import hashlib,json,os,gc
from pathlib import Path
import bpy,numpy as np
from memory_budget import require_memory

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def plain(v):
    if hasattr(v,'to_list'):return v.to_list()
    if hasattr(v,'to_dict'):return v.to_dict()
    return v

class ActionCache:
    def __init__(self,folder,identity):
        if not identity or len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('Invalid cache identity')
        self.folder=Path(folder)/'actions'/identity;self.folder.mkdir(parents=True,exist_ok=True)
        self.identity=identity;self.entries=[];self.reused=0;self.max_live_actions=0

    def get(self,index,name):
        manifest=self.folder/f'{index:05d}.json'
        try:
            record=json.loads(manifest.read_text('utf-8'))
            path=self.folder/record['file']
            if record['identity']!=self.identity or record['name']!=name or path.resolve().parent!=self.folder.resolve() or path.is_symlink() or sha(path)!=record['sha256']:return None
            self.entries.append(record);self.reused+=1;return record
        except (OSError,ValueError,KeyError):return None

    def put(self,index,action,helpers,evidence):
        arrays={};curves=[];keys=0
        for i,fc in enumerate(action.fcurves):
            if fc.modifiers:raise ValueError('Cannot spool generated curve with modifiers')
            n=len(fc.keyframe_points);keys+=n
            for prop,width,dtype in [('co',2,np.float32),('handle_left',2,np.float32),('handle_right',2,np.float32),
                                     ('interpolation',1,np.int32),('handle_left_type',1,np.int32),('handle_right_type',1,np.int32)]:
                a=np.empty(n*width,dtype);fc.keyframe_points.foreach_get(prop,a);arrays[f'{i}_{prop}']=a
            curves.append(dict(path=fc.data_path,index=fc.array_index,group=fc.group.name if fc.group else '',
                               extrapolation=fc.extrapolation,mute=fc.mute,keys=n))
        meta=dict(name=action.name,properties={k:plain(v) for k,v in action.items()},curves=curves,helpers=sorted(helpers))
        arrays['metadata']=np.frombuffer(json.dumps(meta,ensure_ascii=False).encode('utf-8'),dtype=np.uint8)
        file=self.folder/f'{index:05d}.npz';pending=file.with_suffix('.pending')
        with pending.open('wb') as f:np.savez(f,**arrays);f.flush();os.fsync(f.fileno())
        os.replace(pending,file)
        record=dict(identity=self.identity,name=action.name,file=file.name,sha256=sha(file),helpers=sorted(helpers),
                    keys=keys,curves=len(curves),evidence=evidence)
        manifest=self.folder/f'{index:05d}.json';pending=manifest.with_suffix('.pending')
        pending.write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8');os.replace(pending,manifest)
        self.entries.append(record);self.max_live_actions=max(self.max_live_actions,len(bpy.data.actions))
        return record

    def release(self,action,rig):
        rig.arm.animation_data.action=None
        rig.actions.remove(action)
        bpy.data.actions.remove(action,do_unlink=True);gc.collect()

    def assemble(self,rig):
        for i,record in enumerate(self.entries):
            require_memory(256*1024**2)
            path=self.folder/record['file']
            if sha(path)!=record['sha256']:raise ValueError('Action cache corrupted: '+str(path))
            with np.load(path,allow_pickle=False) as data:
                meta=json.loads(data['metadata'].tobytes().decode('utf-8'));a=bpy.data.actions.new(meta['name']);a.use_fake_user=True
                for k,v in meta['properties'].items():a[k]=v
                late=rig.helpers-set(meta['helpers'])
                remap={'pose.bones['+json.dumps(n)+'].':'pose.bones['+json.dumps('AFF::'+n)+'].' for n in late}
                for j,c in enumerate(meta['curves']):
                    path=c['path'];group=c['group']
                    for old,new in remap.items():
                        if path.startswith(old):path=new+path[len(old):];group='AFF::'+group;break
                    fc=a.fcurves.new(path,index=c['index'],**({'action_group':group} if group else {}))
                    fc.extrapolation=c['extrapolation'];fc.mute=c['mute'];fc.keyframe_points.add(c['keys'])
                    for prop in ('co','interpolation','handle_left_type','handle_right_type','handle_left','handle_right'):
                        fc.keyframe_points.foreach_set(prop,data[f'{j}_{prop}'])
                    # Do not update(): event-boundary keys must not be merged.
                if late:
                    from restore_hierarchy import write
                    for name in late:write(a,name,np.array([1.]),np.array([[0,0,0,1,0,0,0,1,1,1]],float))
                rig.actions.append(a)
            print('ACTION_CACHE_LOAD',i+1,len(self.entries),record['name'],flush=True)
        return dict(enabled=True,folder=str(self.folder),actions=len(self.entries),reused=self.reused,
                    max_live_actions_during_authoring=self.max_live_actions,
                    bytes=sum((self.folder/r['file']).stat().st_size for r in self.entries),
                    format='lossless final FCurve arrays + SHA256; no intermediate blend',
                    assembly='all final actions must reside in Blender memory for single-file save')
