"""Bake Sekiro TAE 607 into existing Actions in memory; never open/save a blend.

Source: DSAS installed SourceLink 6a2be66278e3b49362fcedda016eefab73b98935
NewAnimSkeleton.cs 407/590, NewAnimSlot.cs 230-550,
TaeActionSimulationEnvironment.cs 256/370/739/1168,
TaeViewportInteractor.cs 1259-1270. All match ver5.0-rc6.1 byte-for-byte.

Call bake_faces(arm, actions, report). Native sources are in the companion
face_hkx_60fps.bin, sampled directly from original HKX by installed SAP. The
original a000_790xxx Actions remain a fallback. Only31 face_root descendants
are written. No NLA is used. No body channels or source clips are modified.

This records one fresh, forward playback with DSAS's event-before-time-advance
order, at the original HKX frame interval. Interactive seeking and carrying a
face slot across different actions are history dependent and not one Action.
"""
from pathlib import Path
import array
import hashlib
import json
import math
import re
import struct
import numpy as np

ROOT = Path(__file__).resolve().parent
TAE_PATH = ROOT / 'character_tae.json'
SKANIM_DIR = ROOT.parent / 'out'
VERSION = 'dsas607-normal-v1'
ID_RE = re.compile(r'a(\d{3,})_(\d{6})(?!\d)')
CHANNEL_RE = re.compile(r'^pose\.bones\["([^"\\]+)"\]\.(location|rotation_quaternion|scale)$')
EXPECTED_FACE = (
    'Blink_Lower_L','Blink_Lower_R','Blink_Upper_L','Blink_Upper_R',
    'Cheek_High_L','Cheek_High_R','Cheek_Low_L','Cheek_Low_R',
    'Eyeball_L','Eyeball_R','Eyebrow_Center_L','Eyebrow_Center_R',
    'Eyebrow_Inner_L','Eyebrow_Inner_R','Eyebrow_Outer_L','Eyebrow_Outer_R',
    'Jaw_Pivot','Jaw','Lips_Corner_L','Lips_Corner_R','Lips_Lower_C',
    'Lips_Lower_Inner_L','Lips_Lower_Inner_R','Tongue_Back','Tongue_Center',
    'Tongue_Top','Lips_Upper_C','Lips_Upper_Inner_L','Lips_Upper_Inner_R',
    'Nostral_L','Nostral_R',
)
PROPS = (('location',3,0),('rotation_quaternion',4,3),('scale',3,7))


def action_id(name):
    m = ID_RE.search(name)
    return int(m[1])*1000000+int(m[2]) if m else None


def fcurves_of(action):
    try:
        return action.fcurves
    except AttributeError:
        bags = [bag for layer in action.layers for strip in layer.strips
                for bag in getattr(strip, 'channelbags', ())]
        if len(bags) != 1:
            raise ValueError(f'{action.name}: expected one action channelbag, got {len(bags)}')
        return bags[0].fcurves


def _channels(action):
    result = {}
    for fc in fcurves_of(action):
        m = CHANNEL_RE.match(fc.data_path)
        if m:
            key = (m[1],m[2],fc.array_index)
            if key in result:
                raise ValueError(f'{action.name}: duplicate fcurve {key}')
            result[key] = fc
    return result


def body_fingerprint(action, face_names=EXPECTED_FACE):
    """Include channel values, handles and interpolation; excludes only face TRS."""
    h = hashlib.sha256()
    faces = set(face_names)
    for fc in fcurves_of(action):
        m = CHANNEL_RE.match(fc.data_path)
        if m and m[1] in faces:
            continue
        h.update((fc.data_path+'|'+str(fc.array_index)).encode('utf-8'))
        for prop in ('co','handle_left','handle_right'):
            values = array.array('f',[0.0])*(2*len(fc.keyframe_points))
            fc.keyframe_points.foreach_get(prop,values)
            h.update(values.tobytes())
        h.update('|'.join(k.interpolation for k in fc.keyframe_points).encode('ascii'))
    return h.hexdigest()


def read_tae_index(path=TAE_PATH):
    result = {}
    for category in json.loads(Path(path).read_text('utf-8-sig')):
        cat = int(re.search(r'a(\d+)',category['name'])[1])
        for anim in category['animations']:
            key = cat*1000000+int(anim['id'])
            result.setdefault(key,anim)
    return result


def resolve_tae(index,key):
    seen = set()
    while key in index:
        if key in seen:
            raise ValueError(f'cyclic TAE reference: {key}')
        seen.add(key)
        anim = index[key]
        hdr = anim.get('header') or {}
        if hdr.get('type') == 'ImportOtherAnim':
            nxt = int(hdr.get('ImportFromAnimID',-1))
            if nxt >= 0 and nxt != key:
                key = nxt
                continue
        return key,anim
    return key,None


def resolve_hkx(index,key):
    _,anim = resolve_tae(index,key)
    if anim is None:
        return key
    hdr = anim.get('header') or {}
    if hdr.get('ImportsHKX') and int(hdr.get('ImportHKXSourceAnimID',-1)) >= 0:
        return int(hdr['ImportHKXSourceAnimID'])
    return resolve_tae(index,key)[0]


def read_skanim_metadata(directory=SKANIM_DIR):
    """Read only headers; skip payloads and the misnamed -1-frame 'reference'."""
    result = {}
    for path in sorted(Path(directory).glob('*.skanim')):
        with path.open('rb') as f:
            if f.read(4) != b'SKA1':
                continue
            count, = struct.unpack('<I',f.read(4))
            for _ in range(count):
                n, = struct.unpack('<I',f.read(4))
                name = f.read(n).decode('utf-8')
                duration,dt,frames,tracks = struct.unpack('<ffII',f.read(16))
                f.seek(tracks*44,1)
                size, = struct.unpack('<I',f.read(4))
                f.seek(size,1)
                key = action_id(name)
                if key is not None:
                    result.setdefault(key,{'duration':duration,'dt':dt,'frames':frames,'file':str(path)})
    return result


def _normalize(q):
    lengths = np.linalg.norm(q,axis=-1,keepdims=True)
    if np.any(lengths < 1e-12) or not np.isfinite(q).all():
        raise ValueError('zero/nonfinite quaternion in original action')
    return q/lengths


def _slerp(a,b,w):
    a,b = _normalize(a),_normalize(b)
    dot = np.sum(a*b,axis=-1,keepdims=True)
    b = np.where(dot<0,-b,b)
    dot = np.clip(np.abs(dot),0.0,1.0)
    angle = np.arccos(dot)
    sine = np.sin(angle)
    safe = np.where(sine>1e-8,sine,1.0)
    spherical = (a*np.sin((1-w)*angle)+b*np.sin(w*angle))/safe
    linear = (1-w)*a+w*b
    return _normalize(np.where(dot>0.999999,linear,spherical))


def blend_trs(a,b,w):
    out = (1-w)*a+w*b
    out[:,3:7] = _slerp(a[:,3:7],b[:,3:7],w)
    return out


def sample_action(action,bones,frames):
    channels = _channels(action)
    out = np.zeros((len(frames),len(bones),10),dtype=np.float64)
    out[:,:,3] = 1
    out[:,:,7:10] = 1
    for bi,bone in enumerate(bones):
        for prop,size,start in PROPS:
            for component in range(size):
                fc = channels.get((bone,prop,component))
                if fc is not None:
                    out[:,bi,start+component] = [fc.evaluate(float(frame)) for frame in frames]
    out[:,:,3:7] = _normalize(out[:,:,3:7])
    return out


class FaceSource:
    def __init__(self,action,bones,meta,scene_fps=30.0):
        self.name = action.name
        self.dt = float(meta['dt'])
        self.duration = float(meta['duration'])
        self.start = float(action.frame_range[0])
        if self.dt <= 0 or self.duration <= 0:
            raise ValueError(f'{action.name}: invalid clip timing')
        frames = np.arange(int(meta['frames']),dtype=np.float64)*self.dt*scene_fps+self.start
        self.values = sample_action(action,bones,frames)

    def sample(self,elapsed):
        phase = elapsed % self.duration
        frame = phase/self.dt
        lo = min(int(math.floor(frame)),len(self.values)-1)
        hi = min(lo+1,len(self.values)-1)
        # Original imported Actions use linear quaternion component curves;
        # normalize their evaluation before DSAS's inter-animation SLERP.
        result = (1-(frame-lo))*self.values[lo]+(frame-lo)*self.values[hi]
        result[:,3:7] = _normalize(result[:,3:7])
        return result


class NativeFaceSource:
    def __init__(self,values,duration,dt,name):
        self.values = values
        self.duration = duration
        self.dt = dt
        self.name = name
    def sample(self,elapsed):
        phase = elapsed % self.duration
        frame = phase/self.dt
        if abs(frame-round(frame)) < 2e-4:
            frame = float(round(frame))
        lo = min(int(math.floor(frame)),len(self.values)-1)
        hi = min(lo+1,len(self.values)-1)
        alpha = frame-lo
        result = (1-alpha)*self.values[lo]+alpha*self.values[hi]
        result[:,3:7] = _normalize(result[:,3:7])
        return result


def read_native_face_sources(arm,bones,path=None):
    """NORMAL HKX local TRS -> restLocal^-1 @ axisConvertedLocal.

    Requires the verified same-parent Wolf face hierarchy. DSAS normal local
    transforms have no delta/reference multiplication. Quaternion order changes
    from XYZW to Blender WXYZ; axes (x,y,z) become (x,-z,y).
    """
    from mathutils import Matrix,Vector,Quaternion
    path = Path(path) if path is not None else ROOT/'face_hkx_60fps.bin'
    if not path.exists():
        return {}
    data = memoryview(path.read_bytes());off = 0
    def unpack(fmt):
        nonlocal off
        vals = struct.unpack_from(fmt,data,off);off += struct.calcsize(fmt)
        return vals
    def text():
        nonlocal off
        n, = unpack('<I');s = bytes(data[off:off+n]).decode('utf-8');off += n
        return s
    magic,version,count = unpack('<4sII')
    if magic!=b'F60A' or version!=1:
        raise ValueError('bad face_hkx_60fps.bin header')
    names=[];inverse=[]
    for _ in range(count):
        name,parent=text(),text();names.append(name)
        bone=arm.data.bones.get(name)
        if bone is None or bone.parent is None or bone.parent.name!=parent:
            raise ValueError(f'Native face hierarchy mismatch: {name} expected {parent}')
        rest=bone.parent.matrix_local.inverted()@bone.matrix_local
        inverse.append(rest.inverted())
    if list(names)!=list(bones):
        raise ValueError('native face mask does not match verified31 bone order')
    clips,=unpack('<I');result={}
    for _ in range(clips):
        key,duration,dt,frames,hint=unpack('<IffII')
        if hint!=0:raise ValueError(f'non-NORMAL face binding {key}')
        raw=np.frombuffer(data,dtype='<f4',count=frames*count*10,offset=off).reshape(frames,count,10)
        off += raw.nbytes
        values=np.empty(raw.shape,dtype=np.float64)
        for fi in range(frames):
            for bi in range(count):
                tr=raw[fi,bi]
                p=Vector((float(tr[0]),-float(tr[2]),float(tr[1])))
                q=Quaternion((float(tr[6]),float(tr[3]),-float(tr[5]),float(tr[4])));q.normalize()
                s=Vector((float(tr[7]),float(tr[9]),float(tr[8])))
                local=Matrix.LocRotScale(p,q,s)
                loc,rot,scale=(inverse[bi]@local).decompose()
                values[fi,bi,:3]=loc;values[fi,bi,3:7]=rot;values[fi,bi,7:]=scale
        values[:,:,3:7]=_normalize(values[:,:,3:7])
        for fi in range(1,frames):
            signs=np.where(np.sum(values[fi-1,:,3:7]*values[fi,:,3:7],axis=-1)<0,-1.0,1.0)
            values[fi,:,3:7]*=signs[:,None]
        result[key]=NativeFaceSource(values,float(duration),float(dt),f'rawHKX60:a000_{key:06d}')
    if off!=len(data):raise ValueError('trailing native face data')
    return result


class FaceSlot:
    """Direct translation of Normal NewAnimSlot state, DebugWeight=SlotWeight=1."""
    def __init__(self,sources):
        self.sources = sources
        self.request_id = None
        self.foreground = None
        self.background = []
        self.desired = 1.0
        self.blend_duration = 0.0
        self.starts = 0
        self.transitions = 0
        self.clears = 0

    def request(self,key,desired=1.0,blend_duration=0.0):
        old_id = self.request_id
        self.request_id = key
        self.desired = desired
        self.blend_duration = blend_duration
        if key is None or key not in self.sources:
            if self.foreground is not None:
                self.clears += 1
            self.foreground = None
            self.background.clear()
            return
        if key != old_id:
            self.starts += 1
            if blend_duration <= 0:
                self.background.clear()
            elif self.foreground is not None:
                self.transitions += 1
                self.background = [b for b in self.background if b['weight']>=0.01]
                for bg in self.background:
                    bg['snapshot'] = bg['weight']
                self.foreground['snapshot'] = self.foreground['weight']
                self.background.append(self.foreground)
            self.foreground = {'id':key,'elapsed':0.0,'weight':0.0,'snapshot':0.0}
        self.advance(0.0)

    def advance(self,delta):
        if self.foreground is None:
            return
        self.foreground['elapsed'] += delta
        elapsed = self.foreground['elapsed']
        blend = min(1.0,max(0.0,elapsed/self.blend_duration)) if self.blend_duration>0 else 1.0
        # SekiroFaceAnim has IgnoreBlendFromInvalid=true.
        if not self.background:
            blend = 1.0
        self.foreground['weight'] = blend*self.desired
        total = sum(bg['snapshot'] for bg in self.background)
        for bg in self.background:
            bg['elapsed'] += delta
            bg['weight'] = bg['snapshot']/total*(1-blend) if total>0 else 0.0

    def evaluate(self,base):
        if self.foreground is None:
            return base.copy()
        entries = self.background+[self.foreground]
        result = base.copy()
        cumulative = 0.0
        for entry in entries:
            weight = entry['weight']
            if weight <= 0:
                continue
            cumulative += min(1.0,max(0.0,weight))
            final = weight/cumulative if len(entries)>1 and cumulative>0 else weight
            result = blend_trs(result,self.sources[entry['id']].sample(entry['elapsed']),final)
        return result


def parse_face_events(anim,dt):
    events = []
    def snap(t):
        # Both event times and original HKX intervals are float32. Recover
        # an intended integer source frame within their serialization error.
        n = round(t/dt)
        return n*dt if abs(n*dt-t)<2e-6 else t
    for order,event in enumerate(anim.get('events',())):
        if event['type'] != 607:
            continue
        raw = bytes.fromhex(event['raw'])
        if len(raw)<16:
            raise ValueError('truncated FaceAnimation 607 parameters')
        unk,kind,a,b = struct.unpack('<iiff',raw[:16])
        if unk != 0:
            continue
        events.append({'start':snap(float(event['start'])),'end':snap(float(event['end'])),
                       'target':790000+10*min(15,max(0,kind)),
                       'w0':float(a),'w1':float(b),'order':order})
    return events


def process_events(slot,events,time,previous,blend_durations):
    request = None
    desired = 1.0
    # Store-order last active request wins, just as DSAS's shared request.
    for ev in events:
        start,end = ev['start'],ev['end']
        entered = previous<start<=time
        exited = previous<=end<time
        if start<=time<=end or entered or exited:
            length = end-start
            ratio = min(1.0,max(0.0,(time-start)/length)) if length else (1.0 if time>start else float('nan'))
            raw_weight = ev['w0']+(ev['w1']-ev['w0'])*ratio
            desired = 1.0 if raw_weight>0 else 0.0
            request = ev['target']
    slot.request(request,desired,blend_durations.get(request,0.0))


def simulate_faces(base,events,dt,sources,blend_durations):
    result = np.empty_like(base)
    slot = FaceSlot(sources)
    previous_event_time = 0.0
    process_events(slot,events,0.0,previous_event_time,blend_durations)
    result[0] = slot.evaluate(base[0])
    for frame in range(1,len(base)):
        current_event_time = (frame-1)*dt
        process_events(slot,events,current_event_time,previous_event_time,blend_durations)
        previous_event_time = current_event_time
        slot.advance(dt)
        result[frame] = slot.evaluate(base[frame])
    for frame in range(1,len(result)):
        dots = np.sum(result[frame-1,:,3:7]*result[frame,:,3:7],axis=-1)
        result[frame,:,3:7] *= np.where(dots<0,-1.0,1.0)[:,None]
    return result,{'starts':slot.starts,'transitions':slot.transitions,'clears':slot.clears}


