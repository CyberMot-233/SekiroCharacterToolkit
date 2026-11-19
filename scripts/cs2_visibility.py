"""Keep Source2 bodygroup defaults, event values and compiled masks coherent."""
from collections import Counter

VERSION='bodygroup-defaults-v1'

def default_visibility(export):
 if 'preserved_bodygroup_defaults' in export:return export['preserved_bodygroup_defaults']
 groups=[g['name'] for g in export['mesh_groups'] if g['name']!='body']
 states=[]
 for action in export['actions']:
  initial={e['group']:bool(e['value']) for e in action['visibility_events'] if e['frame']==0}
  if set(groups)-initial.keys():raise ValueError('Missing initial visibility: '+action['name'])
  states.append(tuple(initial[g] for g in groups))
 if not states:raise ValueError('No completed actions for bodygroup defaults')
 # Use a real, most common selected-clip state rather than showing every
 # variant, or hiding all clothing until frame-zero events have executed.
 state=Counter(states).most_common(1)[0][0]
 return dict(zip(groups,state))

def apply(doc,export):
 defaults=default_visibility(export);nodes=doc['rootNode']['children']
 groups=next((n for n in nodes if n['_class']=='BodyGroupList'),None)
 if groups is None:groups={'_class':'BodyGroupList','children':[]};nodes.append(groups)
 was_disabled=bool(groups.get('disabled'));groups['disabled']=False
 old={n['name']:n for n in groups['children']};choices={};new=[]
 for entry in export['mesh_groups']:
  name=entry['name'];visible={'_class':'BodyGroupChoice','name':'visible','meshes':[name]};hidden={'_class':'BodyGroupChoice','name':'hidden','meshes':[]}
  options=[visible] if name=='body' else ([visible,hidden] if defaults[name] else [hidden,visible])
  group=old.get(name,{'_class':'BodyGroup','name':name});group.update(disabled=False,children=options,hidden_in_tools=False,non_bodygroup_single_choice=False,suppress_missing_warnings=False);new.append(group)
  choices[name]={bool(o['meshes']):i for i,o in enumerate(options)}
 groups['children']=new
 actions={a['name']:a for a in export['actions']};count=0
 alist=next(n for n in nodes if n['_class']=='AnimationList')
 for anim in alist['children']:
  if anim['name'] not in actions:raise ValueError('Unknown action in visibility repair: '+anim['name'])
  other=[e for e in anim.get('children',[]) if e.get('event_class')!='AE_BODYGROUP_SET_VALUE']
  for event in actions[anim['name']]['visibility_events']:
   other.append(dict(_class='AnimEvent',event_class='AE_BODYGROUP_SET_VALUE',event_frame=event['frame'],event_end_frame=-1,event_keys=dict(bodygroup=event['group'],value=choices[event['group']][bool(event['value'])])))
   count+=1
  anim['children']=other
 return dict(version=VERSION,previously_disabled=was_disabled,default_visible=['body']+[g for g,v in defaults.items() if v],events=count)

def validate(doc,export,data,ctrl=None):
 issues=[];nodes=doc['rootNode']['children'];container=next((n for n in nodes if n['_class']=='BodyGroupList'),None)
 if container is None or container.get('disabled'):return ['BodyGroupList missing/disabled: inactive weapon variants would render together']
 groups={g['name']:g for g in container['children']};compiled=data.get('m_meshGroups',[]);default_mask=data.get('m_nDefaultMeshGroupMask',0)
 expected_defaults=default_visibility(export);masks=data.get('m_refMeshGroupMasks',[]);mesh_names=[g['name'] for g in export['mesh_groups']]
 for name in mesh_names:
  group=groups.get(name)
  if group is None or group.get('disabled'):issues.append('Missing/disabled bodygroup '+name);continue
  options=group['children']
  if bool(options[0]['meshes'])!=(True if name=='body' else expected_defaults[name]):issues.append('Incorrect default visibility '+name)
  for i,option in enumerate(options):
   encoded=f"{name}_@{i}_#&{option['name']}"
   if encoded not in compiled:issues.append('Missing compiled bodygroup choice '+encoded);continue
   bit=1<<compiled.index(encoded)
   if bool(default_mask&bit)!=(i==0):issues.append('Incorrect compiled default bit '+encoded)
   # Embedded meshes have no m_refMeshes paths. CTRL carries the compiled
   # name/index mapping; never assume the compiler retained source ordering.
   indices=[m['m_nMeshIndex'] for m in (ctrl or {}).get('embedded_meshes',[]) if m['m_Name']==name]
   if ctrl is not None and not indices:issues.append('Missing compiled mesh group '+name)
   for j in indices:
    if bool(masks[j]&bit)!=(name in option['meshes']):issues.append('Incorrect compiled mesh visibility '+encoded)
 actions={a['name']:a for a in export['actions']}
 for anim in next(n for n in nodes if n['_class']=='AnimationList')['children']:
  expected=Counter((e['group'],e['frame'],bool(e['value'])) for e in actions[anim['name']]['visibility_events']);actual=Counter()
  for e in anim.get('children',[]):
   if e.get('event_class')!='AE_BODYGROUP_SET_VALUE':continue
   keys=e['event_keys'];group=groups.get(keys['bodygroup']);value=int(keys['value'])
   if group is None or not 0<=value<len(group['children']):issues.append('Invalid bodygroup event '+anim['name']);continue
   actual[(keys['bodygroup'],e['event_frame'],bool(group['children'][value]['meshes']))]+=1
  if actual!=expected:issues.append('Bodygroup event meaning mismatch '+anim['name'])
 return issues
