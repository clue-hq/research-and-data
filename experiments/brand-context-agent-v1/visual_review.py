"""Explicit parent-review corrections backed by inspected originals and pixel colors."""
import copy
from core import now

def apply(store):
 assets=store.read('assets.json',{})
 changes=[]
 def remember(a):
  path='revisions/'+a['id']+'-before-visual-review.json'
  if store.read(path) is None:store.write(path,copy.deepcopy(a['analysis']))
 for aid in ['asset_653acfef353a9e12a1fb','asset_154e27913c93e4817589','asset_112d359150dd4a238122']:
  a=assets[aid];remember(a);v=a['analysis'];g=v['guidance']
  name=v['name']
  v['description']=name+' in white original artwork on a transparent canvas. The inspection matte is not part of the source asset.'
  v['observed']['colors']='White original artwork; transparent canvas. Verified against original pixels/SVG, not inferred from the preview matte.'
  g['background_suitability']='Use the supplied white mark on a dark, contrasting field. It disappears on white. Do not recolor it or invent a reverse variant.'
  g['use_when']='Referencing the customer brand shown on the official Conduit website, subject to permission for the intended use.'
  v['inferred_audience']='Viewers of the Conduit customer references. Do not infer the customer industry from its name or logo.'
  v['tags']=[x for x in v.get('tags',[]) if x!='black']+['white','transparent']
  a['analysis_revision']=a.get('analysis_revision',1)+1
  changes.append({'asset_id':aid,'correction':'Original is white/transparent; incorrect black or baked-in matte removed.'})
 for a in assets.values():
  v=a.get('analysis',{});desc=v.get('description','')
  if any(x in desc.lower() for x in ['defocused photograph','blurred photograph','out-of-focus photograph']):
   remember(a)
   for key in ['description','name']:
    v[key]=v.get(key,'').replace('photograph','image')
   v['uncertainties']=list(dict.fromkeys(v.get('uncertainties',[])+['The source is an existing published image; photographic versus generated authorship is not established.']))
   changes.append({'asset_id':a['id'],'correction':'Do not infer photographic authorship from appearance.'})
  if v.get('category')=='product-screenshot':
   v['uncertainties']=list(dict.fromkeys(v.get('uncertainties',[])+['Official-site product marketing visual; it does not independently establish live functionality or measured results.']))
  if any(o.get('post_author') for o in a['origins']):
   remember(a)
   v['uncertainties']=[x for x in v.get('uncertainties',[]) if 'untrusted' not in x]
   v['uncertainties'].append('The accompanying original sponsored-post copy is captured separately as an advertiser statement, not independently verified performance evidence.')
   if a['id']=='asset_92a6dbd1d1c90d7c41a7':v['guidance']['use_when']='As a published marketing reference for conversational guest portals and local dining recommendations. The visual is a phone mockup, not a verified live product demonstration.'
   changes.append({'asset_id':a['id'],'correction':'Preserve original sponsor/author copy separately; do not confuse unsafe instructions with unusable factual evidence.'})
 store.write('assets.json',assets)
 store.write('visual-review.json',{'at':now(),'reviewer':'parent agent; direct inspection, not independent human approval','scope':'Contact sheets of all acquired originals, selected full previews, original logo alpha/pixel inspection; not pixel-by-pixel OCR certification.','corrections':changes,'human_approved':False})
 print('Visual review corrections:',len(changes))
