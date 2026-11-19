"""Read resourceinfo text dumps (including #[] binary blobs). No engine DLL dependency."""
import re,json
TOKEN=re.compile(r'\s+|//[^\n]*|<!--.*?-->|#\[.*?\]|"(?:\\.|[^"\\])*"|[{}\[\]=,:]|[^\s{}\[\]=,:]+',re.S)
def loads(text):
 tokens=[x.group() for x in TOKEN.finditer(text) if not x.group().isspace() and not x.group().startswith(('//','<!--'))];i=0
 def value():
  nonlocal i
  t=tokens[i];i+=1
  if t=='{':
   out={}
   while tokens[i]!='}':
    if tokens[i]==',':i+=1;continue
    key=tokens[i];i+=1;key=json.loads(key) if key.startswith('"') else key
    if tokens[i]!='=':raise ValueError('Expected = after '+key)
    i+=1;out[key]=value()
   i+=1;return out
  if t=='[':
   out=[]
   while tokens[i]!=']':
    if tokens[i]==',':i+=1;continue
    out.append(value())
   i+=1;return out
  if t.startswith('#['):return bytes.fromhex(t[2:-1])
  if t.startswith('"'):return json.loads(t)
  if i<len(tokens) and tokens[i]==':':i+=1;return value()
  if t in ('true','false','null'):return {'true':True,'false':False,'null':None}[t]
  try:return int(t,0)
  except ValueError:
   try:return float(t)
   except ValueError:return t
 result=value()
 if i!=len(tokens):raise ValueError('Trailing tokens '+str(tokens[i:i+4]))
 return result
