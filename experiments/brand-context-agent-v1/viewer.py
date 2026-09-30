"""Build an allow-listed static review package; never serve the run directory."""
import hashlib
import json
import shutil
import re
from pathlib import Path
from markdown_it import MarkdownIt
from core import now
from knowledge import GROUPS

def reader_markdown(body):
 # A model sometimes appends a source cell without declaring its table column.
 # Markdown renderers silently discard it: preserve every source visibly.
 lines=re.sub(r'^# [^\n]+\n+', '', body, count=1).splitlines()
 i=0
 while i<len(lines)-1:
  if lines[i].lstrip().startswith('|') and re.fullmatch(r'[\s|:\-]+',lines[i+1]) and '-' in lines[i+1]:
   end=i+2
   while end<len(lines) and lines[end].lstrip().startswith('|'):end+=1
   count=lambda line:len(re.split(r'(?<!\\)\|',line.strip().strip('|')))
   widths=[count(line) for line in lines[i:end]]
   if max(widths)>widths[0]:
    for _ in range(max(widths)-widths[0]):
     lines[i]=lines[i].rstrip()+' Source |'
     lines[i+1]=lines[i+1].rstrip()+' --- |'
   i=end
  else:i+=1
 return '\n'.join(lines)

def public_payload(store):
 sources=store.read('sources.json',{})
 docs=[]
 md=MarkdownIt('commonmark',{'html':False,'breaks':False}).enable('table')
 manifest=store.read('document-manifest.json',{})
 groups=([[(d['key'],d['title']) for d in manifest['documents']]] if manifest.get('documents') else GROUPS)
 for group in groups:
  for key,title in group:
   d=store.read('documents/'+key+'.json')
   if d:
    docs.append({**d,'html':md.render(reader_markdown(d['markdown']))})
 assets=[]
 for a in store.read('assets.json',{}).values():
  preview='previews/'+a['id']+'.png'
  assets.append({**a,'preview':preview if store.path(preview).exists() else None})
 report=store.read('evaluation.json',{})
 spend=store.read('spend.json',[])
 report.update(generated_at=now(),source_count=len(sources),document_count=len(docs),asset_count=len(assets),
  analysed_assets=sum(a.get('analysis_status')=='completed' for a in assets),
  known_cost_usd=round(sum(r.get('actual_usd') or 0 for r in spend),5),
  unresolved_reserved_usd=round(sum(r.get('reserved_usd',0) for r in spend if r.get('actual_usd') is None),5),
  provider_calls={p:sum(r['provider']==p for r in spend) for p in sorted({r['provider'] for r in spend})},
  provider_failures=[{k:r.get(k) for k in ('provider','operation','status','http_status','error_type','duration_s')} for r in spend if r.get('status')!='completed'],
  cost_note=report.get('cost_note','Reported Exa and model charges only. Brandfetch/Adyntel dollar charges are not returned. Uncertain calls may be billable. Development and Codex review cost is not included.'),
  ads=store.read('ad-harvest-report.json',{}),brandfetch=store.read('brandfetch-report.json',{}),website=store.read('website-assets-report.json',{}),
  research_started=store.read('research-session.json',{}).get('started_at'),research_finished=store.read('research-session.json',{}).get('finished_at'))
 return {'documents':docs,'assets':assets,'sources':list(sources.values()),'report':report,
   'folders':manifest.get('folders',[]),'brand_pack':store.read('brand-pack.json',{}),
   'lineage':store.read('rework-lineage.json',{}),'quality':store.read('quality-review.json',{}),
   'sales_exercises':store.read('sales-exercises.json',{}),
   'sales_retest':store.read('sales-exercises-logo-retest.json',{}),
   'review_dispositions':store.read('review-dispositions.json',{}),
   'retrieval':store.read('retrieval-evaluation.json',{}),'baseline':store.read('baseline-comparison.json',{}),
   'integration':store.read('proposed-integration-contract.json',{})}

def build(store):
 public=store.path('public'); public.mkdir(exist_ok=True)
 data=public_payload(store)
 for a in data['assets']:
  for key in ('path','preview'):
   if a.get(key):
    target=public/a[key];target.parent.mkdir(exist_ok=True)
    shutil.copy2(store.path(a[key]),target)
 (public/'data.json').write_text(json.dumps(data,ensure_ascii=False))
 for name in ('index.html','style.css','app.js'):shutil.copy2(Path(__file__).parent/'viewer'/name,public/name)
 (public/'manifest.json').write_text(json.dumps({str(p.relative_to(public)):hashlib.sha256(p.read_bytes()).hexdigest() for p in public.rglob('*') if p.is_file() and p.name!='manifest.json'},indent=2))
 print('Review package:',public,flush=True)
