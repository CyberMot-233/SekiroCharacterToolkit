"""Small self-contained Source 2 model DMX writer (MIT datamodel dependency)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
import datamodel as d
from cs2_common import bone_name

def arr(values, kind): return d.make_array(values, kind)

class Model:
    def __init__(self, name, bones):
        self.dm = d.DataModel('model', 22)
        self.root = self.dm.add_element(name, 'DmElement')
        self.model = self.dm.add_element(name, 'DmeModel')
        self.root['skeleton'] = self.model
        self.model['transform'] = self.transform(name, [0,0,0], [0,0,0,1], 1.0)
        self.model['children'] = arr([], d.Element)
        self.model['jointList'] = arr([self.model], d.Element)
        axis = self.dm.add_element('axisSystem','DmeAxisSystem')
        axis['upAxis']=3;axis['forwardParity']=1;axis['coordSys']=0
        self.model['axisSystem']=axis
        base = self.dm.add_element('base','DmeTransformList')
        base['transforms']=arr([],d.Element)
        self.model['baseStates']=arr([base],d.Element)
        self.bones=[]
        for b in bones:
            bn=bone_name(b['name'])
            el=self.dm.add_element(bn,'DmeJoint')
            el['transform']=self.transform(bn,b['pos'],b['rot'],b.get('scale',1.0))
            el['children']=arr([],d.Element)
            self.bones.append(el)
            self.model['jointList'].append(el)
            base['transforms'].append(self.transform(bn,b['pos'],b['rot'],b.get('scale',1.0)))
        for i,b in enumerate(bones):
            (self.bones[b['parent']] if b['parent']>=0 else self.model)['children'].append(self.bones[i])

    def transform(self,name,pos,rot,scale):
        t=self.dm.add_element(name,'DmeTransform')
        t['position']=d.Vector3(list(map(float,pos)))
        t['orientation']=d.Quaternion(list(map(float,rot)))
        t['scale']=float(scale) if isinstance(scale,(float,int)) else d.Vector3(list(map(float,scale)))
        return t

    def mesh(self,name,positions,normals,uv,triangles,weights,material):
        self.root['model']=self.model
        v=self.dm.add_element('bind','DmeVertexData')
        v['vertexFormat']=arr(['position$0','normal$0','texcoord$0','blendweights$0','blendindices$0'],str)
        count=max(1,max(map(len,weights),default=1))
        v['flipVCoordinates']=True;v['jointCount']=count
        v['position$0']=arr([d.Vector3(list(map(float,p))) for p in positions],d.Vector3)
        loops=[int(i) for tri in triangles for i in tri]
        v['position$0Indices']=arr(loops,int)
        v['normal$0']=arr([d.Vector3(list(map(float,n))) for n in normals],d.Vector3)
        v['normal$0Indices']=arr(loops,int)
        v['texcoord$0']=arr([d.Vector2(list(map(float,u))) for u in uv],d.Vector2)
        v['texcoord$0Indices']=arr(loops,int)
        ji=[];jw=[]
        for w in weights:
            w=sorted(w,key=lambda x:-x[1])
            if len(w)>8:raise ValueError('More than eight vertex influences')
            ji.extend([int(x[0])+1 for x in w]+[0]*(count-len(w)))
            jw.extend([float(x[1]) for x in w]+[0.0]*(count-len(w)))
        v['blendweights$0']=arr(jw,float);v['blendindices$0']=arr(ji,int)
        mesh=self.dm.add_element(name,'DmeMesh')
        mesh['visible']=True;mesh['bindState']=v;mesh['currentState']=v;mesh['baseStates']=arr([v],d.Element)
        mat=self.dm.add_element(material,'DmeMaterial');mat['mtlName']=material
        faces=self.dm.add_element(name,'DmeFaceSet');faces['material']=mat
        faces['faces']=arr([j for i in range(len(triangles)) for j in (3*i,3*i+1,3*i+2,-1)],int)
        mesh['faceSets']=arr([faces],d.Element)
        dag=self.dm.add_element(name,'DmeDag');dag['shape']=mesh
        dag['transform']=self.transform(name,[0,0,0],[0,0,0,1],1.0)
        dag['children']=arr([],d.Element)
        self.model['children'].append(dag);self.model['jointList'].append(dag)
        self.model['baseStates'][0]['transforms'].append(self.transform(name,[0,0,0],[0,0,0,1],1.0))

    def animation(self,name,times,positions,rotations,scales,fps):
        clip=self.dm.add_element(name,'DmeChannelsClip')
        al=self.dm.add_element(name,'DmeAnimationList');al['animations']=arr([clip],d.Element)
        self.root['animationList']=al
        tf=self.dm.add_element('timeframe','DmeTimeFrame');tf['start']=d.Time(0);tf['duration']=d.Time(float(times[-1]));tf['scale']=1.0
        clip['timeFrame']=tf;clip['frameRate']=float(fps);clip['channels']=arr([],d.Element)
        for i,b in enumerate(self.bones):
            for prop,typ,cls,values in [('position','Vector3',d.Vector3,positions[:,i]),('orientation','Quaternion',d.Quaternion,rotations[:,i]),('scale','Float',float,scales[:,i])]:
                ch=self.dm.add_element(b.name+'_'+prop,'DmeChannel');ch['toElement']=b['transform'];ch['toAttribute']=prop;ch['mode']=1
                log=self.dm.add_element(prop,'Dme'+typ+'Log');layer=self.dm.add_element(prop,'Dme'+typ+'LogLayer')
                keep=list(range(len(times)))
                if len(times)>1 and all((v==values[0]).all() if hasattr(v,'__len__') else v==values[0] for v in values):keep=[0,len(times)-1]
                layer['times']=arr([d.Time(float(times[k])) for k in keep],d.Time)
                layer['values']=arr([cls(float(values[k])) if cls is float else cls(list(map(float,values[k]))) for k in keep],cls)
                log['layers']=arr([layer],d.Element);ch['log']=log;clip['channels'].append(ch)

    def write(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.dm.write(str(path),'binary',9)
