import ctypes as C, os, json
from pathlib import Path
W=Path(os.environ['SCT_AUDIO_STAGE'])
DLL=Path(os.environ['SCT_DSAS'])
SOUND=Path(os.environ['SCT_SOUND'])
_dir=os.add_dll_directory(str(DLL))
core=C.WinDLL(str(DLL/'fmodex64.dll'));ev=C.WinDLL(str(DLL/'fmod_event64.dll'))
P=C.c_void_p;I=C.c_int;U=C.c_uint;S=C.c_char_p
def fn(lib,name,args):
 f=getattr(lib,name);f.argtypes=args;f.restype=I;return f
def ck(r):
 if r:raise RuntimeError('FMOD result '+str(r))
create=fn(ev,'FMOD_EventSystem_Create',[C.POINTER(P)])
getcore=fn(ev,'FMOD_EventSystem_GetSystemObject',[P,C.POINTER(P)])
output=fn(core,'FMOD_System_SetOutput',[P,I])
init=fn(ev,'FMOD_EventSystem_Init',[P,I,U,P,U])
media=fn(ev,'FMOD_EventSystem_SetMediaPath',[P,S])
load=fn(ev,'FMOD_EventSystem_Load',[P,S,P,C.POINTER(P)])
pgcount=fn(ev,'FMOD_EventProject_GetNumGroups',[P,C.POINTER(I)])
pgget=fn(ev,'FMOD_EventProject_GetGroupByIndex',[P,I,I,C.POINTER(P)])
ggcount=fn(ev,'FMOD_EventGroup_GetNumGroups',[P,C.POINTER(I)])
ggget=fn(ev,'FMOD_EventGroup_GetGroupByIndex',[P,I,I,C.POINTER(P)])
ginfo=fn(ev,'FMOD_EventGroup_GetInfo',[P,C.POINTER(I),C.POINTER(S)])
gecount=fn(ev,'FMOD_EventGroup_GetNumEvents',[P,C.POINTER(I)])
geget=fn(ev,'FMOD_EventGroup_GetEventByIndex',[P,I,U,C.POINTER(P)])
einfo=fn(ev,'FMOD_Event_GetInfo',[P,C.POINTER(I),C.POINTER(S),P])
release=fn(ev,'FMOD_EventSystem_Release',[P])
def count(f,p):
 n=I();ck(f(p,C.byref(n)));return n.value
def enumerate_events():
 es=P();ck(create(C.byref(es)));sys=P();ck(getcore(es,C.byref(sys)));ck(output(sys,4));ck(init(es,128,0,None,0x40));ck(media(es,(str(W)+os.sep).encode()));ck(fn(ev,'FMOD_EventSystem_SetLanguage',[P,S])(es,os.environ.get('SCT_LANGUAGE','jajp').encode()))
 result=[];errors=[]
 def group(g,path,bank):
  idx=I();nm=S();ck(ginfo(g,C.byref(idx),C.byref(nm)));path=path+'/'+nm.value.decode('utf-8','replace')
  for i in range(count(gecount,g)):
   e=P();ck(geget(g,i,4,C.byref(e)));n=S();ix=I();ck(einfo(e,C.byref(ix),C.byref(n),None))
   name=n.value.decode('utf-8','replace');result.append({'bank':bank,'name':name,'path':path+'/'+name})
  for i in range(count(ggcount,g)):
   child=P();ck(ggget(g,i,0,C.byref(child)));group(child,path,bank)
 for p in sorted(SOUND.glob('*.fev')):
  print('LOAD',p.name,flush=True);proj=P();r=load(es,p.name.encode(),None,C.byref(proj))
  if r:errors.append([p.name,r]);continue
  for i in range(count(pgcount,proj)):
   g=P();ck(pgget(proj,i,0,C.byref(g)));group(g,p.stem,p.name)
  ck(fn(ev,'FMOD_EventProject_Release',[P])(proj))
 print('EVENTS',len(result),'errors',errors,flush=True)
 (W/'fmod_events.json').write_text(json.dumps({'events':result,'errors':errors},indent=2),encoding='utf-8')
 ck(release(es))
if __name__=='__main__':enumerate_events()
