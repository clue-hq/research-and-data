"""Resolve sponsored-post author versus advertiser using each original LinkedIn ad page."""
import concurrent.futures,json,re
from urllib.parse import urlsplit
from core import now
from assets import AssetPipeline,media_entries,distinct_creative_count

FOUNDER_REVIEW_IDS=['1538381626','1514101346','1538267846','1519521556','1538238086']

def verified_sponsor(source,page_id):
 return any(urlsplit(u).hostname in ('www.linkedin.com','linkedin.com') and urlsplit(u).path.rstrip('/')=='/company/'+str(page_id) for u in source.get('links',[])) and bool(re.search(r'Advertiser\s+Conduit\s+Paid for by\s+HostAI Labs',source.get('text',''),re.I))

def enrich(store,p,only_ids=None):
 pipeline=AssetPipeline(store,p);report=store.read('ad-harvest-report.json');page_id=report['identity']['page_id']
 raw={}
 for path in store.path('cache').glob('adyntel-*.json'):
  d=json.loads(path.read_text())
  if d.get('status')=='completed':raw.update({a['ad_id']:a for a in d['response'].get('ads',[])})
 # One page per distinct static creative, plus five specific high-relevance sponsored posts.
 originals={}
 for a in report['ads']:
  if a['media_status']=='saved':originals.setdefault(tuple(sorted(a['asset_ids'])),a['id'])
 ids=only_ids or list(dict.fromkeys(list(originals.values())+FOUNDER_REVIEW_IDS))
 detail_results=[x for x in store.read('ad-details-verification.json',[]) if x['ad_id'] not in ids]
 def fetch(adid):
  try:
   url='https://www.linkedin.com/ad-library/detail/'+adid
   source=next((s for s in store.read('sources.json',{}).values() if s['url']==url and s.get('method')=='browser_dom_capture'),None) or p.fetch_page(url)
   if not verified_sponsor(source,page_id):return adid,None,'Sponsor not confirmed in ad detail evidence'
   return adid,source,None
  except Exception as e:return adid,None,type(e).__name__
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for adid,source,error in pool.map(fetch,ids):
   if error:
    detail_results.append({'ad_id':adid,'status':'unresolved','reason':error});continue
   date_match=re.search(r'Ran from (.+?) to ([A-Z][a-z]+ \d{1,2}, \d{4})',' '.join(source['text'].split()))
   details={'ad_details_source_id':source['id'],'verified_sponsor':'Conduit','payer':'HostAI Labs, Inc.',
     'sponsor_page_id':page_id,'source_text':source['text'],'run_dates_label':date_match.group(0) if date_match else None}
   detail_results.append({'ad_id':adid,'status':'verified',**details})
   existing=next((e for e in report['ads'] if e['id']==adid),None)
   if existing:
    existing['detail_evidence']=details
    for aid in existing['asset_ids']:
     with store.lock:
      assets=store.read('assets.json');assets[aid]['ad_detail_evidence']=[x for x in assets[aid].get('ad_detail_evidence',[]) if x['ad_id']!=adid]+[{'ad_id':adid,**details}];store.write('assets.json',assets)
    continue
   ad=raw.get(adid)
   if not ad:continue
   entry={'id':adid,'advertiser':{'name':'Conduit','promoted':True},'post_author':ad['advertiser']['name'],
    'source_url':source['url'],'headline':ad.get('headline'),'commentary':ad.get('commentary'),
    'format':ad.get('type'),'retrieved_at':now(),'detail_evidence':details,'asset_ids':[],'media_status':'pending'}
   for index,m in enumerate(media_entries(ad)):
    asset=pipeline.ingest(m['url'],{'collection':'linkedin','ad_id':adid,'source_page':source['url'],'source_id':source['id'],
     'advertiser':'Conduit','post_author':ad['advertiser']['name'],'payer':'HostAI Labs, Inc.','page_id':page_id,
     'format':m['format'],'media_role':m['role'],'slide':index+1,'headline':ad.get('headline'),'commentary':ad.get('commentary'),
     'published_or_run_dates':details['run_dates_label'],'identity_evidence':source['id']})
    entry['asset_ids'].append(asset['id'])
    prior=store.read('assets.json')[asset['id']].get('ad_detail_evidence',[])
    pipeline.patch(asset['id'], ad_detail_evidence=[x for x in prior if x['ad_id']!=adid]+[{'ad_id':adid,**details}])
   entry['media_status']='saved' if entry['asset_ids'] else 'metadata_only';report['ads'].append(entry)
 report['verified_founder_posts']=[x['ad_id'] for x in detail_results if x['ad_id'] in FOUNDER_REVIEW_IDS and x['status']=='verified']
 report['dropped']=[x for x in report['dropped'] if x['ad_id'] not in report['verified_founder_posts']]
 report['distinct_creative_count']=distinct_creative_count(report['ads'])
 report['unique_media_count']=len({aid for a in report['ads'] for aid in a['asset_ids']})
 report['status']='completed' if report['distinct_creative_count']>=15 else 'partial'
 report['identity_note']='Provider advertiser field sometimes contains post author. Five selected founder posts were reconsidered only after individual original ad pages confirmed Conduit as advertiser and HostAI Labs as payer. Other unverified author-labelled entries remain excluded.'
 store.write('ad-details-verification.json',detail_results);store.write('ad-harvest-report.json',report)
 print('Ad detail verification:',sum(x['status']=='verified' for x in detail_results),'/',len(detail_results),'pages; complete distinct creatives:',report['distinct_creative_count'],flush=True)
