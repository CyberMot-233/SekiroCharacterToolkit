"""DSAS NewAnimSkeleton.WalkTree mapping and reference fallback for unmapped descendants."""
import numpy as np
from mathutils import Matrix
from internal_fk_verified import DEFAULT_C
def mapped_fk(nodes,sknames,hkx):
 C=DEFAULT_C;CI=np.linalg.inv(C);rt={};scale={};out={};visiting=set();count=len(hkx)
 def visit(name):
  if name in out:return
  if name in visiting:raise ValueError('FLVER parent cycle: '+name)
  visiting.add(name);n=nodes[name];parent=n.get('_parent_name')
  if name in sknames:
   rt[name]=hkx[:,sknames[name]];scale[name]=np.broadcast_to(np.eye(4),(count,4,4));out[name]=rt[name]
  else:
   m=C@np.asarray(n['local'],float).reshape(4,4).T@CI;l,q,s=Matrix(m).decompose();local=np.array(Matrix.Translation(l)@q.to_matrix().to_4x4());ls=np.diag([*s,1])
   if parent and parent in nodes:visit(parent);rt[name]=rt[parent]@local;scale[name]=scale[parent]@ls
   else:rt[name]=np.broadcast_to(local,(count,4,4));scale[name]=np.broadcast_to(ls,(count,4,4))
   out[name]=rt[name]@scale[name]
  visiting.remove(name)
 for name in nodes:visit(name)
 return out
