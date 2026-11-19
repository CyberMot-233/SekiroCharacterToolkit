"""DSAS RC6.1 internal HKX FK: accumulate RT and scale separately.

No bpy or mathutils required. NumPy only. Matrices use column vectors.

Verified source NewAnimSkeleton.cs:227-243,302-307:
    RTg[i] = RTg[parent] @ (T[i] @ R[i])
    Sg[i]  = Sg[parent] @ diag(scale[i])
    FK[i]  = RTg[i] @ Sg[i]
Child recursion receives RTg and Sg, NOT FK. Therefore parent scale does not
scale the child's translation. Installation SoulsAssetPipeline.dll reflection
also confirmed NewBlendableTransform.GetMatrix() returns RT without scale.

Quick replacement in Weapon.internal (self.motion/self.nodes/self.used exist):
    fk = sample_internal_fk(self.motion, anim, times, self.nodes, self.used)
    return {i: [Matrix(m) for m in fk[i]] for i in self.used}, aid

That function samples the unmodified HKX local tracks, uses the HKX hierarchy
and reference local tracks for unmapped tracks, then maps FK to FLVER by name.
Without an internal animation, use the FLVER reference FK (same as current
bake implementation); this helper accepts anim=None as that case.

The final sample is clamped to weapon duration. It does not take player time
modulo: callers choose whether an exported complete clip retains the end pose
or exactly reproduces DSAS's reset at the isolated player-duration endpoint.
"""
from __future__ import annotations

import numpy as np

DEFAULT_C = np.array(((1,0,0,0),(0,0,-1,0),(0,1,0,0),(0,0,0,1)), dtype=np.float64)


def _quaternion_matrices(q):
    q = np.asarray(q, dtype=np.float64)
    q = q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-20)
    x, y, z, w = np.moveaxis(q, -1, 0)
    m = np.zeros(q.shape[:-1] + (4,4), dtype=np.float64)
    m[...,3,3] = 1
    m[...,0,0] = 1-2*(y*y+z*z)
    m[...,0,1] = 2*(x*y-z*w)
    m[...,0,2] = 2*(x*z+y*w)
    m[...,1,0] = 2*(x*y+z*w)
    m[...,1,1] = 1-2*(x*x+z*z)
    m[...,1,2] = 2*(y*z-x*w)
    m[...,2,0] = 2*(x*z-y*w)
    m[...,2,1] = 2*(y*z+x*w)
    m[...,2,2] = 1-2*(x*x+y*y)
    return m


def fk_separate_scale(parents, translations, rotations_xyzw, scales, conversion=None,
                      *, return_components=False):
    """Evaluate DSAS FK for arrays [sample,bone,component].

    Also accepts [bone,component] and returns [bone,4,4] for one sample.
    conversion is an optional 4x4 basis matrix applied to final FK only.
    Parents may occur after children; cycles and invalid indices raise.
    """
    t = np.asarray(translations, dtype=np.float64)
    q = np.asarray(rotations_xyzw, dtype=np.float64)
    s = np.asarray(scales, dtype=np.float64)
    single = t.ndim == 2
    if single:
        t,q,s = t[None],q[None],s[None]
    if t.ndim != 3 or t.shape[-1] != 3 or q.shape != (*t.shape[:-1],4) or s.shape != t.shape:
        raise ValueError('Expected T/S [sample,bone,3], Q [sample,bone,4]')
    parents = [int(p) for p in parents]
    if len(parents) != t.shape[1]:
        raise ValueError('Parent count does not match bone count')
    local_rt = _quaternion_matrices(q)
    local_rt[...,:3,3] = t
    local_scale = np.zeros(t.shape[:-1] + (4,4), dtype=np.float64)
    local_scale[...,0,0] = s[...,0]
    local_scale[...,1,1] = s[...,1]
    local_scale[...,2,2] = s[...,2]
    local_scale[...,3,3] = 1
    rt = np.empty_like(local_rt)
    sg = np.empty_like(local_rt)
    done = np.zeros(len(parents), dtype=np.uint8)
    def visit(i):
        if done[i] == 2:
            return
        if done[i] == 1:
            raise ValueError(f'Bone hierarchy cycle at {i}')
        done[i] = 1
        p = parents[i]
        if p >= len(parents) or p == i:
            raise ValueError(f'Invalid parent {p} of bone {i}')
        if p >= 0:
            visit(p)
            rt[:,i] = rt[:,p] @ local_rt[:,i]
            sg[:,i] = sg[:,p] @ local_scale[:,i]
        else:
            rt[:,i],sg[:,i] = local_rt[:,i],local_scale[:,i]
        done[i] = 2
    for i in range(len(parents)):
        visit(i)
    fk = rt @ sg
    if conversion is not None:
        c = np.asarray(conversion,dtype=np.float64)
        ci = np.linalg.inv(c)
        fk = c @ fk @ ci
        rt = c @ rt @ ci
        sg = c @ sg @ ci
    if single:
        fk,rt,sg = fk[0],rt[0],sg[0]
    return (fk,rt,sg) if return_components else fk


def _slerp(q0, q1, a):
    q0 = q0 / np.maximum(np.linalg.norm(q0, axis=-1, keepdims=True),1e-20)
    q1 = q1 / np.maximum(np.linalg.norm(q1, axis=-1, keepdims=True),1e-20)
    dot = (q0*q1).sum(axis=-1,keepdims=True)
    q1 = np.where(dot < 0,-q1,q1)
    dot = np.clip(np.abs(dot),0,1)
    a = np.asarray(a,dtype=np.float64)[...,None]
    theta = np.arccos(dot)
    sine = np.sin(theta)
    safe_sine = np.where(sine < 1e-12,1,sine)
    spherical = (np.sin((1-a)*theta)*q0 + np.sin(a*theta)*q1)/safe_sine
    linear = (1-a)*q0+a*q1
    result = np.where(dot > 0.9995,linear,spherical)
    return result / np.maximum(np.linalg.norm(result,axis=-1,keepdims=True),1e-20)


def sample_hkx_fk(motion, anim, times, conversion=DEFAULT_C, *, return_components=False):
    """Sample exported motion JSON, using independent HKX reference locals.

    Returns [sample,hkx_bone,4,4]. No FLVER hierarchy/rest is used here.
    Untracked HKX bones keep their original reference T/Q/S.
    """
    bones = motion['bones']
    times = np.asarray(times,dtype=np.float64)
    if times.ndim != 1:
        raise ValueError('times must be a one-dimensional seconds array')
    n = len(times)
    tr = np.broadcast_to(np.array([b['t'][:3] for b in bones]),(n,len(bones),3)).copy()
    qr = np.broadcast_to(np.array([b['q'][:4] for b in bones]),(n,len(bones),4)).copy()
    sr = np.broadcast_to(np.array([b['s'][:3] for b in bones]),(n,len(bones),3)).copy()
    if anim is not None:
        frames = anim.get('_frames')
        if frames is None:
            frames = np.asarray(anim['frames'],dtype=np.float64)
        else:
            frames = np.asarray(frames,dtype=np.float64)
        duration = float(anim['duration'])
        fd = float(anim['frameDuration'])
        if fd <= 0 or len(frames) == 0:
            raise ValueError('Invalid weapon animation sample interval/count')
        ff = np.clip(times,0,duration)/fd
        ff = np.clip(ff,0,len(frames)-1)
        i0 = np.floor(ff).astype(int)
        i1 = np.minimum(i0+1,len(frames)-1)
        alpha = ff-i0
        v0,v1 = frames[i0],frames[i1]
        vals = (1-alpha[:,None,None])*v0 + alpha[:,None,None]*v1
        quat = _slerp(v0[:,:,3:7],v1[:,:,3:7],alpha[:,None])
        for ti,hi in enumerate(anim['map']):
            hi = int(hi)
            if hi < 0:
                continue
            if hi >= len(bones):
                raise ValueError(f'Animation track {ti} maps outside skeleton: {hi}')
            tr[:,hi] = vals[:,ti,:3]
            qr[:,hi] = quat[:,ti]
            sr[:,hi] = vals[:,ti,7:10]
    return fk_separate_scale([b['parent'] for b in bones],tr,qr,sr,conversion,
                             return_components=return_components)


def sample_internal_fk(motion, anim, times, flver_nodes, used_indices=None,
                       conversion=DEFAULT_C):
    """Return {flver_index: ndarray[sample,4,4]} for the baker.

    If no internal animation is selected, return FLVER reference FK. When an
    animation exists, matched FLVER bones take HKX FK by name exactly. Unmatched
    FLVER bones use their reference local transform under their FLVER parent;
    the current six weapon models have no used untracked/mismatched bones.
    """
    times = np.asarray(times,dtype=np.float64)
    count = len(times)
    c = np.asarray(conversion,dtype=np.float64) if conversion is not None else np.eye(4)
    ci = np.linalg.inv(c)
    use = list(range(len(flver_nodes))) if used_indices is None else list(used_indices)
    if anim is None or not motion or not motion.get('bones'):
        return {i:np.broadcast_to(c@np.array(flver_nodes[i]['world']).reshape(4,4).T@ci,
                                  (count,4,4)).copy() for i in use}
    fk = sample_hkx_fk(motion,anim,times,conversion)
    byname = {b['name']:i for i,b in enumerate(motion['bones'])}
    result = {}
    active = set()
    def visit(i):
        if i in result:
            return result[i]
        if i in active:
            raise ValueError(f'FLVER hierarchy cycle at {i}')
        active.add(i)
        node = flver_nodes[i]
        hi = byname.get(node['name'])
        if hi is not None:
            out = fk[:,hi]
        else:
            local = c @ np.array(node['local']).reshape(4,4).T @ ci
            p = int(node['parent'])
            out = visit(p)@local if p>=0 else np.broadcast_to(local,(count,4,4)).copy()
        result[i] = out
        active.remove(i)
        return out
    for i in use:
        visit(i)
    return {i:result[i] for i in use}
