"""Continuous two-bone representation of affine matrices, using NumPy only.

    outer, inner = factor_affine(mats)  # both [sample,4,4], column-vector form
    assert max_abs(outer @ inner - mats) <= 1e-6

outer is T @ proper_rotation @ signed_diagonal_scale; inner is a proper
rotation with zero translation. Parent the original equipment root below an
identity-rest __AFFINE helper, key outer on the helper and inner on the root.
Apply visibility scale 0/1 to the OUTER helper only. Skin bones can stay direct
children of the original root. The original root's accumulated matrix retains
shear even though each keyed bone individually uses only Blender TRS channels.

No SVD is needed if the whole clip is representable as TRS within tolerance.
Otherwise factor the entire clip consistently: start at its strongest shear,
track forward and backward, select among 24 proper signed permutations, and
carry the preceding inner rotation through equal/near-equal singular values
whenever reconstruction stays within tolerance. This avoids random SVD axes in
rigid intervals and axis-order/sign flips when singular values cross.
"""
from __future__ import annotations

import itertools
import numpy as np


_PERMS = []
_SIGNS = []
for _p in itertools.permutations(range(3)):
    _inversions = sum(_p[i] > _p[j] for i in range(3) for j in range(i+1,3))
    _parity = -1 if _inversions % 2 else 1
    for _s in itertools.product((-1.0,1.0), repeat=3):
        if int(np.prod(_s)) == _parity:
            _PERMS.append(_p)
            _SIGNS.append(_s)
_PERMS = np.asarray(_PERMS, dtype=np.int64)
_SIGNS = np.asarray(_SIGNS, dtype=np.float64)


def _try_trs(a):
    """Orthogonal-column TRS approximation, with reflection in signed Z scale."""
    x,y,z = a[..., :,0],a[..., :,1],a[..., :,2]
    sx = np.linalg.norm(x,axis=-1)
    ex = x / np.maximum(sx[...,None],1e-30)
    yy = y - ex*np.sum(ex*y,axis=-1,keepdims=True)
    sy = np.linalg.norm(yy,axis=-1)
    ey = yy / np.maximum(sy[...,None],1e-30)
    ez = np.cross(ex,ey)
    sz = np.sum(ez*z,axis=-1)
    rotation = np.stack((ex,ey,ez),axis=-1)
    scales = np.stack((sx,sy,sz),axis=-1)
    reconstructed = rotation*scales[...,None,:]
    error = np.max(np.abs(reconstructed-a),axis=(-2,-1))
    valid = (sx>1e-14)&(sy>1e-14)
    return rotation,scales,reconstructed,np.where(valid,error,np.inf)


def factor_affine(mats, *, tolerance=2e-7):
    """Factor [N,4,4] affine column matrices into outer TRS and inner rotation.

    Reflections and singular scales are supported. Translation is copied to
    outer; inner is translation-free. Returned arrays are float64. Error for
    accepted near-TRS fast paths is at most tolerance in matrix max norm;
    SVD paths reconstruct to floating-point precision. No input is modified.
    """
    mats = np.asarray(mats,dtype=np.float64)
    if mats.ndim != 3 or mats.shape[1:] != (4,4):
        raise ValueError('Expected matrices with shape [N,4,4]')
    if not np.isfinite(mats).all():
        raise ValueError('Matrices must be finite')
    if tolerance < 0 or tolerance > 1e-6:
        raise ValueError('Tolerance must be between zero and 1e-6')
    count = len(mats)
    outer = np.broadcast_to(np.eye(4),(count,4,4)).copy()
    inner = outer.copy()
    if count == 0:
        return outer,inner
    if np.max(np.abs(mats[:,3,:]-[0,0,0,1])) > 1e-10:
        raise ValueError('Expected affine last row [0,0,0,1]')
    outer[:,:3,3] = mats[:,:3,3]
    linear = mats[:,:3,:3]
    rot,scale,reconstructed,error = _try_trs(linear)
    if np.all(error <= tolerance):
        outer[:,:3,:3] = reconstructed
        return outer,inner

    # Batch SVD, then force both rotation factors proper. Any reflection goes
    # into a signed scale, where Blender can preserve it.
    u,s,vh = np.linalg.svd(linear)
    du = np.where(np.linalg.det(u)<0,-1.0,1.0)
    dv = np.where(np.linalg.det(vh)<0,-1.0,1.0)
    u[:,:,2] *= du[:,None]
    vh[:,2,:] *= dv[:,None]
    s[:,2] *= du*dv

    def candidates(i):
        # U columns and Vh rows must be permuted together. Four sign choices
        # per permutation preserve proper determinants for both rotations.
        uc = u[i][:,_PERMS].transpose(1,0,2)*_SIGNS[:,None,:]
        vc = vh[i][_PERMS,:]*_SIGNS[:,:,None]
        sc = s[i][_PERMS]
        return uc,sc,vc

    # Start with a well-defined anisotropic/sheared frame; rigid endpoints then
    # inherit its basis instead of forcing an unrelated identity decomposition.
    anchor = int(np.argmax(error))
    uc,sc,vc = candidates(anchor)
    choice = int(np.argmax(np.trace(vc,axis1=1,axis2=2)))
    rotations = np.empty((count,3,3),dtype=np.float64)
    rotations[anchor] = uc[choice]
    inner[anchor,:3,:3] = vc[choice]
    outer[anchor,:3,:3] = uc[choice]*sc[choice][None,:]

    def advance(i,previous):
        prior_inner = inner[previous,:3,:3]
        # Degenerate singular values admit infinitely many equivalent bases.
        # Keeping the previous inner factor is smoother than following SVD's
        # arbitrary basis, and also handles nearly-degenerate values safely.
        target_outer = linear[i]@prior_inner.T
        rr,ss,ll,ee = _try_trs(target_outer)
        if ee <= tolerance:
            rotations[i] = rr
            outer[i,:3,:3] = ll
            inner[i,:3,:3] = prior_inner
            return
        uu,ss,vv = candidates(i)
        # Trace is 1+2*cos(relative_angle). Optimize both factor rotations,
        # selecting a continuous signed axis permutation for the same affine.
        score = np.einsum('ij,kij->k',rotations[previous],uu)
        score += np.einsum('ij,kij->k',prior_inner,vv)
        selected = int(np.argmax(score))
        rotations[i] = uu[selected]
        outer[i,:3,:3] = uu[selected]*ss[selected][None,:]
        inner[i,:3,:3] = vv[selected]

    for i in range(anchor+1,count):
        advance(i,i-1)
    for i in range(anchor-1,-1,-1):
        advance(i,i+1)
    # The residual is measured in input coordinates. Multiplication by an inner
    # rotation can turn max-component error into up to sqrt(3)*tolerance.
    # Fall back to exact tracked SVD only for frames exceeding the API bound.
    errors = np.max(np.abs(outer@inner-mats),axis=(1,2))
    for i in np.flatnonzero(errors > max(tolerance,1e-12)):
        uu,ss,vv = candidates(int(i))
        score = np.einsum('ij,kij->k',rotations[i],uu)
        score += np.einsum('ij,kij->k',inner[i,:3,:3],vv)
        selected = int(np.argmax(score))
        outer[i,:3,:3] = uu[selected]*ss[selected][None,:]
        inner[i,:3,:3] = vv[selected]
    return outer,inner
