"""Reproducible coverage and cost report with explicit evaluation boundaries."""
from collections import Counter
from datetime import datetime
from pathlib import Path
import json
from core import Store,now

def report(s):
 assets=s.read('assets.json',{});spend=s.read('spend.json',[]);ads=s.read('ad-harvest-report.json',{})
 research=s.read('research-session.json',{});sources=s.read('sources.json',{})
 elapsed=(datetime.fromisoformat(research['finished_at'])-datetime.fromisoformat(research['started_at'])).total_seconds()
 start=datetime.fromisoformat(min(x['started_at'] for x in spend));end=datetime.fromisoformat(now())
 known=sum(x.get('actual_usd') or 0 for x in spend)
 counts=Counter(x['provider'] for x in spend)
 failures=[{k:x.get(k) for k in ('provider','status','http_status','error_type','retry_of')} for x in spend if x['status']!='completed']
 covers=sum(any(o.get('media_role')=='cover_only' for o in a['origins']) for a in assets.values())
 retrieval=s.read('retrieval-evaluation.json',{})
 retrieval['parent_assessment']={'catalogue_asset_count_at_test':49,'appropriate_selection_sets':6,'fully_covered_briefs':3,'partial_or_correctly_abstained':3,'method':'Parent review of selected original assets and reasons; not blind independent scoring. Later founder-post additions were not part of the six retrieval tests.','cases':{'brand-intro':'Covered: website wordmark plus restrained original background.','inbox':'Covered as a product marketing reference, not independent proof of live UI.','voice':'Partial: relevant call card; no dedicated after-hours creative.','workflows':'Partial: real published workflow reference; no end-to-end guest-journey map.','linkedin':'Covered: original static published creatives, no website stand-ins or video covers.','hyatt':'Correct partial response: Conduit logo only; no Hyatt mark or invented partnership.'}}
 s.write('retrieval-evaluation.json',retrieval)
 integration={'status':'proposal_only_requires_explicit_human_approval','principles':[
  'Separate quick onboarding identity/logo/color extraction from resumable background company, product, customer, ICP and ad research. This pilot does not establish a production onboarding latency target.',
  'One Assets collection owns original logos, website imagery and published ads. Preserve bytes, media role, deduplication, sponsor versus author, source, dates, and rights uncertainty. Classifications are versioned advisory annotations.',
  'Postgres and the existing claim-store/storage seams remain authoritative after any approved integration. Do not import another subsystem or write knowledge directly around those seams.',
  'Store atomic company facts with evidence spans and provenance; keep buyer hypotheses, qualification decisions and preferences distinct. Exact quotation matching is not sufficient entailment validation.',
  'Head of ABM consumes an approved version and proposes changes. Campaign documents do not silently become global brand governance. Human edits and approvals remain attributable, versioned and scope-aware.',
  'Publish friendly titles and typed document blocks, including tables, to the existing editor. Internal file keys and raw provider traces stay outside the normal reading interface.',
  'Review conflicts, unsupported necessities, unknown compatibility, changed logos and unverified metrics before promotion. Report gaps instead of substituting generated facts or artwork.',
  'Before integration: human acceptance of the Conduit draft, semantic claim verification, held-out multi-brand evaluation, stale-source/conflict tests, durable cancel/resume, tenancy and cost enforcement, and a fast-onboarding measurement.'
 ],'proposed_records':{
  'BrandContextRun':['workspace_id','canonical_company_id','domain','input_version','status','checkpoint','budget','source_policy','created_at','cancel_requested'],
  'Evidence':['source_id','url','retrieved_at','published_at_or_unknown','content_hash','excerpt_or_attribute','company_binding','source_type'],
  'Claim':['claim_id','field','atomic_statement','evidence_ids','epistemic_status','contradictions','freshness','promotion_decision'],
  'KnowledgeDocument':['stable_key','display_name','revision','typed_blocks','evidence_ids','open_questions','approval_state'],
  'QualificationCriterion':['criterion','fit_readiness_or_urgency','necessary_preference_or_hypothesis','basis','assessment','unknown_handling','approval'],
  'Asset':['asset_id','original_hash','storage_ref','media_format','media_role','dimensions','origins','sponsor','post_author','ad_id','actual_run_dates_or_unknown'],
  'AssetAnnotation':['asset_id','revision','literal_description','observed_properties','inferred_use','use_when','how_to_use','avoid_when','crop_background_guidance','uncertainties','evidence_ids'],
  'Approval':['object_id','revision','scope','reviewer','decision','changes_requested','approved_at']}}
 s.write('proposed-integration-contract.json',integration)
 evaluation={'status':'ready_for_human_review_not_for_integration','successes':[
  'Fresh public research reached a resumable 24-round checkpoint. Official website and LinkedIn identity agree on Conduit hospitality software; similarly named businesses were excluded.',
  'Nine readable documents with tables and resolvable evidence links, plus proposed qualification criteria separating account fit, delivery readiness and urgency.',
  f'{len(assets)} original assets acquired and classified: 32 website assets, two provider logo variants, {ads["distinct_creative_count"]} complete static LinkedIn creatives and {covers} video covers. Original hashes verified. No new creative images or replacement logos generated.',
  'Five founder-authored sponsored posts were checked against original LinkedIn pages; four distinct new creatives were added after distinguishing author from advertiser.',
  'Six asset-retrieval exercises produced appropriate existing-asset selections or explicit gaps. Three briefs fully covered; three partial, including deliberate refusal to invent a Hyatt logo.',
  'Independent consequential-claim and ICP review completed. Important findings were adjudicated; prior drafts and unapproved candidate statements were preserved.',
  '32 isolated unit tests and 12 real-artifact integrity checks passed. These validate mechanics and lineage, not commercial truth or human acceptance.'
 ],'failures':[
  'The first draft was not governance-ready: six Important independent findings included partial claim support, over-strict ICP gates, channel-readiness logic, trigger chronology, logo authority and missing evidence links. No post-correction independent score or human approval is claimed.',
  'All 41 raw candidate statements remain withheld from fact promotion. Literal source observations and corrected source-linked documents are review material. Atomic semantic entailment, conflict resolution and approval still need a production-quality pass.',
  'Vision misread white customer logos as black and confused added preview backgrounds with original artwork. Corrected against originals. Detailed OCR and every possible crop/background use were not exhaustively certified.',
  'Three classification outputs returned invented IDs; an earlier parser silently skipped them. Strict batch identity validation was added and a fresh bounded request completed the missing records.',
  'Adyntel returned HTTP 422 for two numeric page-ID requests; the contract requires a string. Six later pages succeeded. Some individual LinkedIn pages returned HTTP 403; five founder pages were verified through the normal browser. Three existing static-ad detail pages remain unconfirmed individually, while provider page binding and company advertiser labels are recorded.',
  'Ad harvest is bounded, not exhaustive. Six pages span 90- and 180-day requested windows; individual run dates are unavailable for some ads. Three video posters are not full videos. No original video/document media or complete carousel was acquired in this sample.',
  'Commercial fit, willingness to pay, actual connector behavior, marketing performance and security claims are not independently proven by public pages. Current brand approval for provider logo variants remains unresolved.',
  'This is one brand with supervised repairs. Multi-brand robustness, real onboarding latency, injected crash recovery, production tenancy and automatic publication have not been validated. Repeated caveats still need editorial consolidation.'
 ],'review_summary':'A fresh read-only GPT-6 Astra reviewer checked consequential claims, source passages, ICP criteria and selected logo originals. Six Important findings were corrected or withheld from promotion; no Critical issue was established within that inspected scope. The scores below describe the initial draft, before corrections. Later asset and UI checks were performed by the parent agent, not a human reviewer.',
 'rubric':[
  {'dimension':'Identity / supporting evidence','score':'Initial 2/4','reason':'Correct company; compound candidate claims were only partly supported by their attached spans.'},
  {'dimension':'Product understanding','score':'Initial 3/4','reason':'Useful capability mapping; connector and availability boundaries required clarification.'},
  {'dimension':'ICP decision usefulness','score':'Initial 2/4','reason':'Necessary gates and readiness logic needed correction; commercial fit remains proposed.'},
  {'dimension':'Buyer / outcome specificity','score':'Initial 3/4','reason':'Relevant roles; purchase versus expansion chronology needed correction.'},
  {'dimension':'Honest uncertainty','score':'Initial 3/4','reason':'Unknowns generally explicit; approval still required.'},
  {'dimension':'Clarity','score':'Initial 3/4','reason':'Readable structure and tables; caveats repeat.'},
  {'dimension':'Assets / retrieval','score':'No independent score','reason':'Parent reviewed original-media samples and six retrieval cases separately.'}],
 'execution_note':f'Research loop: {elapsed/60:.1f} minutes. Elapsed from first recorded provider call to this report: {(end-start).total_seconds()/60:.1f} minutes, including implementation fixes, asset work, review and packaging. Provider totals include failed requests; cached responses do not add calls. One explicit supervised retry followed an uncertain request. Some failed claim-tool submissions required schema corrections. No Clue app, database, environment or running service was changed.',
 'cost_accounting':{'reported_usd':round(known,6),'provider_calls':dict(counts),'provider_failures':failures,'adyntel_successful_pages':sum(x['provider']=='adyntel' and x['status']=='completed' for x in spend),'adyntel_failed_attempts':sum(x['provider']=='adyntel' and x['status']!='completed' for x in spend),'brandfetch_calls':counts['brandfetch'],'note':'Model and Exa returned dollar costs. Adyntel and Brandfetch dollar costs, uncertain calls, development and independent Codex review are excluded from the reported total.'},
 'verification':s.read('integrity-checks.json',[]),'browser_qa':s.read('browser-qa.json',{'status':'pending'}),'human_approved':False}
 s.write('evaluation.json',evaluation)
 body=f'''# Conduit standalone pilot — review checkpoint

No integration into Clue. Human approval is pending.

- 9 knowledge documents; {len(sources)} source records.
- {len(assets)} original assets: 32 website files, 2 provider logo variants, {ads['distinct_creative_count']} distinct complete LinkedIn creatives and {covers} video covers.
- All assets classified; hashes, source links and document citations checked.
- Reported provider spend: **${known:.4f}**, not a complete cost total. {evaluation['cost_accounting']['note']}
- Calls: {dict(counts)}. Research loop: {elapsed/60:.1f} minutes.

## Quality decision

Useful for human review; not approved for automatic brand governance. Independent review found six Important issues. Draft criteria and source links were corrected; 41 compound candidate statements remain unapproved rather than being promoted on partial evidence. Asset guidance also required supervised color, preview-matte and identity corrections. No independent post-fix score is claimed.

## Retrieval and baseline

Six campaign briefs: three covered, three partial or correctly abstained. The Hyatt exercise did not invent a target logo. Retrieval used the 49-asset catalogue before founder-post additions. The existing onboarding snapshot has 12 documents; it is a qualitative baseline only and was never research input.

## Remaining gates

Human assessment of ICP usefulness and brand/asset fidelity; atomic entailment and conflict handling; held-out brands; production durability, cancel/resume, tenant boundaries and measured onboarding latency. Full video media is unavailable. Ad coverage is bounded and per-ad dates are sometimes unknown. Public marketing claims are not independent performance evidence.

## Inspect locally

[Review viewer](http://localhost:3045/) · [Knowledge](http://localhost:3045/#knowledge) · [Assets](http://localhost:3045/#assets) · [Run and evaluation](http://localhost:3045/#evaluation)

Structured detail: `evaluation.json`, `reviewed-evidence.json`, `ad-harvest-report.json`, `retrieval-evaluation.json`, `proposed-integration-contract.json`, `integrity-checks.json`, and `browser-qa.json` in this run. Original bytes live in `originals/`; earlier drafts in `revisions/`. Do not serve the run root.
'''
 s.path('run-report.md').write_text(body)
 print(f'Report ready: ${known:.4f} reported; {len(assets)} originals; {ads["distinct_creative_count"]} complete ads')

if __name__=='__main__':report(Store(Path(__file__).parent/'runs/conduit-20260919'))
