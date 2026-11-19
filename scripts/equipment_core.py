# -*- coding: utf-8 -*-
"""Rebuild Sekiro weapon playback from verified RC6.1 parameter/TAE/FLVER/HKX data.
The original character actions are preserved; only sample times are corrected.
Equipment roots and internal joints are baked into the SAME armature Action.
"""
import bpy, sys, json, re, math, hashlib, time
from pathlib import Path
import numpy as np
from mathutils import Matrix, Vector, Quaternion
W=Path(__file__).resolve().parent
sys.path.insert(0,str(W))
import event_states as ES
C=Matrix(((1,0,0,0),(0,0,-1,0),(0,1,0,0),(0,0,0,1)))
CI=C.transposed()
CN=np.array(C,dtype=np.float64)
TAGS=[('WP_A_0300','R',0),('WP_A_0300_1','R',1),('WP_A_0310','MB',0),('WP_A_0310_1','MB',1),('WP_A_0730','L',0),('WP_A_0730_1','L',1)]
J=lambda p:json.loads(Path(p).read_text('utf-8-sig'))
def rowmatrix(a):return C@Matrix(np.array(a).reshape(4,4).T.tolist())@CI

def trs(t,q,s):
    return Matrix.Translation(Vector(t))@Quaternion(q).normalized().to_matrix().to_4x4()@Matrix.Diagonal((*s,1))

def hkxmat(a):
    return C@trs(a[:3],(a[6],a[3],a[4],a[5]),a[7:10])@CI

def fullid(s):
    m=re.search(r'a(\d+)_(\d{6})',s)
    return int(m[1])*1000000+int(m[2])

def decomp_many(mats):
    loc=[];rot=[];scl=[]
    for m in mats:
        l,q,s=m.decompose();loc.append(l);rot.append(q);scl.append(s)
    rot=np.array(rot,dtype=np.float64)
    if len(rot)>1:
        signs=np.cumprod(np.where(np.sum(rot[:-1]*rot[1:],axis=1)<0,-1,1))
        rot[1:]*=signs[:,None]
    return np.array(loc),rot,np.array(scl)

def write_curve(action,path,idx,frames,values,group,constant=False):
    old=action.fcurves.find(path,index=idx)
    if old:action.fcurves.remove(old)
    values=np.asarray(values,dtype=float)
    if len(values)==1:keep=np.array([0])
    elif np.max(np.abs(values-values[0]))<1e-7:keep=np.array([0,len(values)-1])
    else:keep=np.arange(len(values),dtype=int)
    fc=action.fcurves.new(path,index=idx,action_group=group)
    fc.keyframe_points.add(len(keep))
    co=np.column_stack([frames[keep],values[keep]]).astype(np.float32)
    fc.keyframe_points.foreach_set('co',co.ravel())
    for k in fc.keyframe_points:k.interpolation='CONSTANT' if constant else 'LINEAR'
    # Preserve sorted boundary keys; update merges close keys.

def write_trs(action,bone,frames,loc,quat,scale,step_scale=False):
    for prop,vals in [('location',loc),('rotation_quaternion',quat),('scale',scale)]:
        for i in range(vals.shape[1]):write_curve(action,f'pose.bones["{bone}"].{prop}',i,frames,vals[:,i],bone,step_scale and prop=='scale')

class PoseCache:
    def __init__(self,arm,names):
        allnames=set()
        for n in names:
            b=arm.data.bones.get(n)
            while b:allnames.add(b.name);b=b.parent
        def depth(n):
            b=arm.data.bones[n];d=0
            while b.parent:b=b.parent;d+=1
            return d
        self.names=sorted(allnames,key=depth)
        self.rest={n:np.array(arm.data.bones[n].matrix_local,dtype=np.float64) for n in self.names}
        self.par={n:(arm.data.bones[n].parent.name if arm.data.bones[n].parent else None) for n in self.names}
        self.inv={n:np.linalg.inv(m) for n,m in self.rest.items()}
        self.rel={n:(self.inv[self.par[n]]@self.rest[n] if self.par[n] else self.rest[n]) for n in self.names}
    def evaluate(self,action,frames):
        channels={}
        for fc in action.fcurves:
            m=re.match(r'pose.bones\["(.+)"\]\.(location|rotation_quaternion|scale)$',fc.data_path)
            if m and m[1] in self.rest:channels[(m[1],m[2],fc.array_index)]=fc
        out={};N=len(frames)
        for n in self.names:
            p=np.zeros((N,3));q=np.zeros((N,4));q[:,0]=1;s=np.ones((N,3))
            for prop,arr in [('location',p),('rotation_quaternion',q),('scale',s)]:
                for i in range(arr.shape[1]):
                    f=channels.get((n,prop,i))
                    if f:
                        co=np.empty(len(f.keyframe_points)*2,dtype=np.float32);f.keyframe_points.foreach_get('co',co)
                        if all(k.interpolation=='LINEAR' for k in f.keyframe_points):arr[:,i]=np.interp(frames,co[::2],co[1::2])
                        else:arr[:,i]=[f.evaluate(float(t)) for t in frames]
            q/=np.maximum(np.linalg.norm(q,axis=1,keepdims=True),1e-20)
            w,x,y,z=q.T
            mat=np.zeros((N,4,4));mat[:,3,3]=1;mat[:,:3,3]=p
            mat[:,0,0]=1-2*(y*y+z*z);mat[:,0,1]=2*(x*y-z*w);mat[:,0,2]=2*(x*z+y*w)
            mat[:,1,0]=2*(x*y+z*w);mat[:,1,1]=1-2*(x*x+z*z);mat[:,1,2]=2*(y*z-x*w)
            mat[:,2,0]=2*(x*z-y*w);mat[:,2,1]=2*(y*z+x*w);mat[:,2,2]=1-2*(x*x+y*y)
            mat[:,:3,:3]*=s[:,None,:]
            mat=self.rel[n]@mat
            out[n]=out[self.par[n]]@mat if self.par[n] else mat
        return out

class Weapon:
    def __init__(self,tag,slot,index):
        self.tag,self.slot,self.index=tag,slot,index;self.data=J(W/(tag+'.json'))
        self.root='DSAS_'+slot+str(index)
        self.nodes=self.data['nodes'];self.ref=[rowmatrix(n['world']) for n in self.nodes];self.refinv=[m.inverted() for m in self.ref]
        self.locals=[rowmatrix(n['local']) for n in self.nodes]
        self.motion=J(W/(tag+'.motion.json')) if (W/(tag+'.motion.json')).exists() else None
        self.anims={};self.taes={}
        if self.motion:
            self.anims={fullid(a['name']):a for a in self.motion['animations']}
            for t in self.motion['taes']:
                self.taes.update({a['id']:a for a in t['animations']})
            for a in self.anims.values():a['_frames']=np.array(a['frames'],dtype=np.float64)
        self.used=set()
        for mesh in self.data['meshes']:
            bi,weights=self.weights(mesh)
            for i in np.unique(bi[weights>0]):
                j=int(i)
                while j>=0 and j not in self.used:self.used.add(j);j=self.nodes[j]['parent']
        self.used=sorted(self.used)
        self.bn={i:self.root+'__'+self.nodes[i]['name'] for i in self.used}
        self.objects=[]
    def weights(self,mesh):
        bi=np.array(mesh['boneIndices'],dtype=int);w=np.array(mesh['weights'],dtype=float)
        w[np.sum(w,axis=1)==0,0]=1
        if not mesh['usesBoneIndices']:bi[:,0]=mesh['normalW'];w[:,0]=1
        if self.data['version']<=0x2000D:
            pal=np.array(mesh['info']['BoneIndices'],dtype=int);bad=(bi<0)|(bi>=len(pal));bi=pal[np.clip(bi,0,len(pal)-1)];w[bad]=0
        bad=(bi<0)|(bi>=len(self.nodes));bi[bad]=0;w[bad]=0
        sm=w.sum(axis=1);assert np.all(sm>0),self.tag
        w/=sm[:,None]
        return bi,w
    def choose(self,tae_id):
        key=tae_id if tae_id in self.taes or tae_id in self.anims else 999000000
        visited=set()
        while key in self.taes:
            assert key not in visited;visited.add(key);h=self.taes[key]['header']
            if h['type']=='ImportOtherAnim' and h['ImportFromAnimID']>=0:key=h['ImportFromAnimID'];continue
            if h['type']=='Standard' and h.get('ImportsHKX') and h['ImportHKXSourceAnimID']>=0:key=h['ImportHKXSourceAnimID']
            break
        return self.anims.get(key),key
    def internal(self,tae_id,times):
        from internal_fk_verified import sample_internal_fk
        anim,aid=self.choose(tae_id)
        fk=sample_internal_fk(self.motion,anim,times,self.nodes,self.used)
        return {i:[Matrix(m) for m in fk[i]] for i in self.used},aid


def create_image(base,kind,texout):
    fn=base+'_'+kind
    name='DSAS_'+fn+'.png'
    got=bpy.data.images.get(name)
    if got:return got
    dds=W.parent/'wex_tex'/(fn+'.dds')
    if not dds.exists():return None
    im=bpy.data.images.load(str(dds),check_existing=False)
    if kind!='a':im.colorspace_settings.name='Non-Color'
    # Generated PNG avoids display/view transforms (save_render would bake them).
    w,h=im.size;px=np.empty(w*h*4,dtype=np.float32);im.pixels.foreach_get(px)
    out=bpy.data.images.new(name,width=w,height=h,alpha=False,float_buffer=False)
    out.colorspace_settings.name='sRGB' if kind=='a' else 'Non-Color'
    out.pixels.foreach_set(px);out.file_format='PNG';out.filepath_raw=str(texout/(fn+'.png'));out.save();out.pack()
    bpy.data.images.remove(im)
    return out

def newmaterial(tag,mat,oldmats,texout):
    if tag.startswith('WP_A_0300'):
        got=oldmats.get((tag,mat['name']))
        if got:return got
    mtd=Path(mat['mtd'].replace('\\','/')).stem
    nm='DSAS_'+mtd
    got=bpy.data.materials.get(nm)
    if got:return got
    m=bpy.data.materials.new(nm);m.use_nodes=True;nt=m.node_tree;p=nt.nodes.get('Principled BSDF')
    p.inputs['Roughness'].default_value=.58;p.inputs['Metallic'].default_value=0;p.inputs['IOR'].default_value=1.45
    p.inputs['Specular IOR Level'].default_value=.35
    for kind in ('a','n','m'):
        image=create_image(mtd,kind,texout)
        if not image:continue
        t=nt.nodes.new('ShaderNodeTexImage');t.image=image;t.label={'a':'Albedo','n':'Normal','m':'Reflectance (original)'}[kind]
        t.location=(-600,300-250*('anm'.index(kind)))
        if kind=='a':nt.links.new(t.outputs['Color'],p.inputs['Base Color'])
        elif kind=='n':
            normal=nt.nodes.new('ShaderNodeNormalMap');normal.uv_map='UV0';normal.location=(-220,0)
            nt.links.new(t.outputs['Color'],normal.inputs['Color']);nt.links.new(normal.outputs['Normal'],p.inputs['Normal'])
    m['source_mtd']=mat['mtd'];return m

def build_rigs(arm,weapons,texout):
    oldmats={}
    for tag,slot,ix in TAGS:
        for ob in list(bpy.data.objects):
            if ob.type=='MESH' and (ob.name.startswith(tag+'_')):
                for mat in ob.data.materials:
                    if mat:oldmats[(tag,mat.name)]=mat
    oldobjs=[o for o in bpy.data.objects if o.type=='MESH' and any(o.name.startswith(p) for p in ['WP_A_0300_','WP_A_0310_','WP_A_0730_'])]
    for ob in oldobjs:bpy.data.objects.remove(ob,do_unlink=True)
    col=bpy.data.collections.get('DSAS_Weapons') or bpy.data.collections.new('DSAS_Weapons')
    if col.name not in [c.name for c in bpy.context.scene.collection.children]:bpy.context.scene.collection.children.link(col)
    bpy.context.view_layer.objects.active=arm;arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for wp in weapons:
        outer=arm.data.edit_bones.new(wp.root+'__AFFINE');outer.head=(0,0,0);outer.tail=(0,.1,0);outer.use_deform=False
        eb=arm.data.edit_bones.new(wp.root);eb.head=(0,0,0);eb.tail=(0,.1,0);eb.use_deform=False;eb.parent=outer
        for i in wp.used:
            n=wp.nodes[i];e=arm.data.edit_bones.new(wp.bn[i]);e.matrix=wp.ref[i];e.length=.1
            e.parent=eb;e.use_connect=False
    bpy.ops.object.mode_set(mode='OBJECT')
    for wp in weapons:
        wp.blref={i:arm.data.bones[wp.bn[i]].matrix_local.copy() for i in wp.used}
        wp.blinv={i:m.inverted() for i,m in wp.blref.items()}
        wp.rel_inv={i:wp.blref[i].inverted() for i in wp.used}
        arm.pose.bones[wp.root+'__AFFINE'].rotation_mode='QUATERNION'
        arm.pose.bones[wp.root].rotation_mode='QUATERNION';arm.pose.bones[wp.root]['slot']=wp.slot;arm.pose.bones[wp.root]['model_index']=wp.index
        for i in wp.used:arm.pose.bones[wp.bn[i]].rotation_mode='QUATERNION'
        for mi,md in enumerate(wp.data['meshes']):
            bi,wt=wp.weights(md);pos=np.array(md['pos'],dtype=float);norm=np.array(md['normal'],dtype=float)
            if md['info']['Dynamic']==0:
                rawref=np.array([m for m in wp.ref]);cvpos=pos@CN[:3,:3].T
                trans=np.einsum('vbij,vj->vbi',rawref[bi],np.column_stack((cvpos,np.ones(len(pos)))))
                vpos=(trans[:,:,:3]*wt[:,:,None]).sum(axis=1)
            else:vpos=pos@CN[:3,:3].T
            vn=norm@CN[:3,:3].T;tri=np.array(md['indices'],dtype=int).reshape(-1,3)
            cr=np.cross(vpos[tri[:,1]]-vpos[tri[:,0]],vpos[tri[:,2]]-vpos[tri[:,0]])
            agree=np.einsum('ij,ij->i',cr,vn[tri].mean(axis=1))
            if np.median(agree[np.abs(agree)>1e-14])<0:tri=tri[:,[0,2,1]]
            me=bpy.data.meshes.new(wp.tag+'_Mesh'+str(mi));me.from_pydata(vpos.tolist(),[],tri.tolist());me.update()
            for poly in me.polygons:poly.use_smooth=True
            try:me.normals_split_custom_set_from_vertices(vn.tolist())
            except AttributeError:me.normals_split_custom_set([vn[l.vertex_index] for l in me.loops])
            for ui in range(max(map(len,md['uv']),default=0)):
                layer=me.uv_layers.new(name='UV'+str(ui));uv=np.array([(v[ui][0],1-v[ui][1]) if len(v)>ui else (0,0) for v in md['uv']],dtype=np.float32)
                loopidx=np.array([l.vertex_index for l in me.loops]);layer.data.foreach_set('uv',uv[loopidx].ravel())
            for ci in range(max(map(len,md['colors']),default=0)):
                co=me.color_attributes.new(name='Col'+str(ci),type='FLOAT_COLOR',domain='POINT');cs=np.array([v[ci] if len(v)>ci else (1,1,1,1) for v in md['colors']],dtype=np.float32);co.data.foreach_set('color',cs.ravel())
            ob=bpy.data.objects.new(wp.tag+'_DSAS_'+str(mi),me);col.objects.link(ob);ob.parent=arm
            for i in wp.used:ob.vertex_groups.new(name=wp.bn[i])
            for vi in range(len(bi)):
                for bn,weight in zip(bi[vi],wt[vi]):
                    if weight>0:ob.vertex_groups[wp.bn[int(bn)]].add([vi],float(weight),'ADD')
            mod=ob.modifiers.new('DSAS Skeleton','ARMATURE');mod.object=arm
            me.materials.append(newmaterial(wp.tag,wp.data['materials'][md['material']],oldmats,texout))
            ob['source_flver']=wp.data['source'];ob['dsas_slot']=wp.slot;ob['dsas_model_index']=wp.index
            wp.objects.append(ob)
    return len(oldobjs)

def rescale_actions(actions,timing):
    count=0
    for a in actions:
        info=timing.get(a.name)
        if not info:continue
        factor=info['frame_duration']*30
        if abs(factor-1)>1e-5 and not a.get('dsas_body_rebaked'):
            for f in a.fcurves:
                for p in ['co','handle_left','handle_right']:
                    arr=np.empty(len(f.keyframe_points)*2,dtype=np.float32);f.keyframe_points.foreach_get(p,arr);arr[::2]=1+(arr[::2]-1)*factor;f.keyframe_points.foreach_set(p,arr)
                f.update()
            count+=1
        a['source_duration_seconds']=info['duration'];a['source_fps']=info['fps'];a['dsas_verified_bake']=True
    return count


