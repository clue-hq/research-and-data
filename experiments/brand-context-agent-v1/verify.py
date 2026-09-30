"""Integrity checks over real run artifacts; these are not semantic quality scores."""
import json
from pathlib import Path
from core import Store,digest,validate_claim
from knowledge import validate_document

def verify(s):
 sources=s.read('sources.json',{});docs=[json.loads(p.read_text()) for p in s.path('documents').glob('*.json')];assets=s.read('assets.json',{})
 checks=[]
 def check(name,ok):
  checks.append({'name':name,'passed':bool(ok)})
  if not ok:print('FAIL:',name)
 check('nine readable documents',len(docs)==9)
 check('all document citations and criterion sources resolve',all(not validate_document(d,sources) for d in docs))
 check('ICP no longer requires PMS for all buyers',not any('Already has (or is implementing) a PMS' in c['criterion'] and c['strength']=='necessary' for d in docs for c in d.get('icp_criteria',[])))
 channel=[c for d in docs for c in d.get('icp_criteria',[]) if 'guest-channel workflow' in c['criterion']]
 check('channel requirement is positively stated',bool(channel) and all('confirmed supported route' in c['criterion'] and c['dimension']=='readiness' for c in channel))
 check('unknown Operations availability is not an exclusion',not any(c['dimension']=='exclusion' and 'Operations' in c['criterion'] for d in docs for c in d.get('icp_criteria',[])))
 check('no unsupported domain industry attribution',all('conduit.xyz payments' not in d['markdown'] for d in docs))
 check('every original retains matching SHA256',all(digest(s.path(a['path']).read_bytes())==a['sha256'] for a in assets.values()))
 check('every acquired asset has classification and preview',all(a.get('analysis_status')=='completed' and s.path('previews/'+a['id']+'.png').exists() for a in assets.values()))
 check('provider logo currency is explicitly unconfirmed',all(a.get('brand_authority')=='provider_attributed_current_usage_unconfirmed' for a in assets.values() if any(o['collection']=='brand-provider' for o in a['origins'])))
 evidence=s.read('reviewed-evidence.json',{})
 check('candidate claims are not promoted',evidence.get('promotion_allowed') is False and all(c['decision']=='withheld_from_fact_promotion' for c in evidence.get('candidate_dispositions',[])))
 check('reviewed source observations retain exact spans',all(not validate_claim({'statement':o['statement'],'status':'observed','evidence':o['evidence']},sources) for o in evidence.get('observations',[])))
 check('six bounded retrieval exercises',len(s.read('retrieval-evaluation.json',{}).get('cases',[]))==6)
 s.write('integrity-checks.json',checks)
 print(sum(x['passed'] for x in checks),'/',len(checks),'artifact integrity checks passed')
 return all(x['passed'] for x in checks)
if __name__=='__main__':
 if not verify(Store(Path('runs/conduit-20260919'))):raise SystemExit(1)
