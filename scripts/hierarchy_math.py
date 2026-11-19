"""Batch equivalents of Blender's NONE inherit-scale local pose conversion.

Column vectors. Degenerate transforms are rejected, never silently inverted.
"""
import numpy as np

def no_scale(parent):
    m=np.asarray(parent,dtype=np.float64).copy()
    y=m[:,:3,1].copy();x=m[:,:3,0].copy();z=m[:,:3,2].copy()
    yy=np.sum(y*y,axis=1,keepdims=True)
    if np.any(yy<1e-24):raise ValueError('Degenerate parent Y axis')
    x-=y*np.sum(x*y,axis=1,keepdims=True)/yy
    z-=y*np.sum(z*y,axis=1,keepdims=True)/yy
    y/=np.sqrt(yy)
    x/=np.maximum(np.linalg.norm(x,axis=1,keepdims=True),1e-30)
    z/=np.maximum(np.linalg.norm(z,axis=1,keepdims=True),1e-30)
    cos=np.sum(x*z,axis=1);mask=(abs(cos)>1e-4)&(abs(cos)<1-np.finfo(np.float32).eps)
    if np.any(mask):
        target=(np.arccos(cos[mask])+np.pi/2)*.5
        xx=x[mask]-z[mask]*cos[mask,None]
        xx*=np.sin(target)[:,None]/np.linalg.norm(xx,axis=1,keepdims=True)
        xx+=z[mask]*np.cos(target)[:,None]
        zz=np.cross(np.cross(xx,z[mask]),xx);zz/=np.linalg.norm(zz,axis=1,keepdims=True)
        x[mask]=xx;z[mask]=zz
    m[:,:3,0]=x;m[:,:3,1]=y;m[:,:3,2]=z
    return m

def local_basis(target,rest,parent_target=None,parent_rest=None):
    if parent_target is None:return np.linalg.inv(rest)@target
    offset=np.linalg.inv(parent_rest)@rest
    loc=parent_target@offset;rot=no_scale(parent_target)@offset
    result=np.linalg.inv(rot)@target
    result[:,:3,3]=(np.linalg.inv(loc)@target)[:,:3,3]
    return result

def trs_residual(m):
    """Conservative shear measure; exact TRS gives zero apart from roundoff."""
    a=m[:,:3,:3];s=np.linalg.norm(a,axis=1);r=a/np.maximum(s[:,None,:],1e-30)
    gram=np.swapaxes(r,1,2)@r
    return float(np.max(np.abs(gram-np.eye(3))*np.max(s,axis=1)[:,None,None]))

def decompose_many(matrices):
    m=np.asarray(matrices,dtype=np.float64);a=m[:,:3,:3];s=np.linalg.norm(a,axis=1)
    if np.any(s<1e-15):raise ValueError('Singular TRS: use native decomposition')
    s[np.linalg.det(a)<0]*=-1
    r=a/s[:,None,:];q=np.zeros((len(m),4));tr=np.trace(r,axis1=1,axis2=2)
    w=tr>0
    t=np.sqrt(np.maximum(1+tr[w],0))*2;q[w,0]=t/4
    q[w,1]=(r[w,2,1]-r[w,1,2])/t;q[w,2]=(r[w,0,2]-r[w,2,0])/t;q[w,3]=(r[w,1,0]-r[w,0,1])/t
    diag=np.diagonal(r,axis1=1,axis2=2);largest=diag.argmax(axis=1)
    for i in range(3):
        pick=(~w)&(largest==i);j=(i+1)%3;k=(i+2)%3
        t=np.sqrt(np.maximum(1+r[pick,i,i]-r[pick,j,j]-r[pick,k,k],0))*2
        q[pick,0]=(r[pick,k,j]-r[pick,j,k])/t;q[pick,i+1]=t/4
        q[pick,j+1]=(r[pick,j,i]+r[pick,i,j])/t;q[pick,k+1]=(r[pick,k,i]+r[pick,i,k])/t
    q/=np.maximum(np.linalg.norm(q,axis=1,keepdims=True),1e-30)
    if len(q)>1:q[1:]*=np.cumprod(np.where(np.sum(q[:-1]*q[1:],axis=1)<0,-1,1))[:,None]
    return np.column_stack((m[:,:3,3],q,s))
