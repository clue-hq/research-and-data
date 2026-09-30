"""Integrity checks on the revised corpus, separate from semantic/human approval."""
import json
import re
from core import Store, digest
from rework import ROOT, RUN, SPECS, validate_rich_document

def verify(store):
 sources=store.read('sources.json',{});assets=store.read('assets.json',{})
 manifest=store.read('document-manifest.json',{})
 docs={d['key']:store.read('documents/'+d['key']+'.json') for d in manifest.get('documents',[])}
 checks=[]
 def check(name,ok,detail=None):
  checks.append({'name':name,'passed':bool(ok),'detail':detail})
  print(('PASS ' if ok else 'FAIL ')+name,flush=True)
 check('Every declared document is available',bool(docs) and all(docs.values()))
 check('Required product, audience, identity and organization deliverables exist',set(x['key'] for x in SPECS)|{'visual-identity','library-guide'} <= set(docs))
 errors={s['key']:validate_rich_document(docs.get(s['key']) or {},s,sources) for s in SPECS}
 check('Document schemas, critical evidence spans and source references resolve',not any(errors.values()),{k:v for k,v in errors.items() if v})
 invalid_links=[]
 for key,d in docs.items():
  for target in re.findall(r'\]\(#knowledge/([^\)]+)\)',(d or {}).get('markdown','')):
   if target not in docs:invalid_links.append({'from':key,'to':target})
 check('Every internal document link resolves',not invalid_links,invalid_links)
 check('Every document has an organized Markdown export',all(store.path('knowledge/'+d['folder']+'/'+key+'.md').exists() for key,d in docs.items() if d))
 check('Every original asset retains its SHA256',all(digest(store.path(a['path']).read_bytes())==a['sha256'] for a in assets.values()))
 check('Every asset has human description, agent context and preview',all(a.get('analysis',{}).get('description') and a.get('agent_context') and store.path('previews/'+a['id']+'.png').exists() for a in assets.values()))
 check('Asset analysis does not silently grant campaign approval',all(a.get('agent_context',{}).get('approved_for_campaign') is False for a in assets.values()))
 check('Related asset documents resolve',all(k in docs for a in assets.values() for k in a.get('agent_context',{}).get('related_document_keys',[])))
 originals=store.read('rework-lineage.json',{})
 previous=Store(ROOT/'runs'/originals['previous_run'])
 check('Previous run source and original-asset hashes remain unchanged',all(previous.read('sources.json')[k]['sha256']==h for k,h in originals['reused_source_hashes'].items()) and all(digest(previous.path(previous.read('assets.json')[k]['path']).read_bytes())==h for k,h in originals['reused_asset_hashes'].items()))
 slots=store.read('brand-pack.json',{}).get('slots',[])
 check('Four logo placement slots distinguish source availability',len(slots)==4 and all(s.get('status') and s.get('note') and s.get('asset_id') in assets for s in slots))
 check('Public package contains no raw provider response or environment file',not any(p.name.startswith('.env') or p.name=='spend.json' or 'cache' in p.relative_to(store.path('public')).parts or 'raw' in p.relative_to(store.path('public')).parts for p in store.path('public').rglob('*')))
 store.write('integrity-checks.json',checks)
 return all(c['passed'] for c in checks)

if __name__=='__main__':
 if not verify(Store(ROOT/'runs'/RUN)):raise SystemExit(1)
