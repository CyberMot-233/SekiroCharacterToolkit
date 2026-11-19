"""Render FEV events through the exact installed FMOD runtime, offline."""
from fmod_probe import *
import csv, collections, subprocess, wave, math, hashlib
getevent=fn(ev,'FMOD_EventSystem_GetEvent',[P,S,U,C.POINTER(P)])
update=fn(ev,'FMOD_EventSystem_Update',[P])
start=fn(ev,'FMOD_Event_Start',[P]);stop=fn(ev,'FMOD_Event_Stop',[P,I])
state=fn(ev,'FMOD_Event_GetState',[P,C.POINTER(U)])
soft=fn(core,'FMOD_System_SetSoftwareFormat',[P,I,I,I,I,I])
bufsize=fn(core,'FMOD_System_SetDSPBufferSize',[P,U,I])
class Info(C.Structure):
 _fields_=[('memoryused',I),('positionms',I),('lengthms',I),('channelsplaying',I),('instancesactive',I),('maxwavebanks',I),('wavebankinfo',P),('projectid',U),('systemid',U),('audibility',C.c_float),('numinstances',I),('instances',P),('guid',P)]
def render(entry,dest,maxseconds=15):
 es=P();ck(create(C.byref(es)));sys=P();ck(getcore(es,C.byref(sys)))
 ck(output(sys,5));ck(soft(sys,48000,2,2,0,0));ck(bufsize(sys,256,2))
 outbuf=C.create_string_buffer(str(dest).encode())
 ck(init(es,128,0,C.cast(outbuf,P),0x40));ck(media(es,(str(W)+os.sep).encode()))
 ck(fn(ev,'FMOD_EventSystem_SetLanguage',[P,S])(es,os.environ.get('SCT_LANGUAGE','jajp').encode()))
 try:
  proj=P();ck(load(es,entry['bank'].encode(),None,C.byref(proj)))
  e=P();ck(getevent(es,entry['path'].encode(),0,C.byref(e)))
  info=Info();ck(einfo(e,None,None,C.byref(info)))
  ck(fn(ev,'FMOD_Event_SetVolume',[P,C.c_float])(e,C.c_float(0.125)));ck(start(e));n=0;seen=False;finished=False;quiet=0
  # Account for one DSP block per update in non-realtime mode.
  while n<int(48000/256*maxseconds):
   ck(update(es));n+=1;s=U();ck(state(e,C.byref(s)))
   seen=seen or bool(s.value&8)
   if seen and not (s.value&8):finished=True;break
   if n>20 and not s.value&16:quiet+=1
   else:quiet=0
   if quiet>94:finished=True;break
  ck(stop(e,1))
  for _ in range(10):ck(update(es))
  return {'native_length_ms':info.lengthms,'updates':n,'natural_or_silent_end':finished,'capped':not finished,'max_seconds':maxseconds}
 finally:ck(release(es))
