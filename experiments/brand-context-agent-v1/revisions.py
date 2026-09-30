"""Recorded pilot adjudications after independent review, never platform mutations."""
import copy,json,re
from pathlib import Path
from core import now,digest,validate_claim
from knowledge import evidence_union,validate_document

def apply_review(store):
 sources=store.read('sources.json',{})
 docs={p.stem:store.read('revisions/'+p.stem+'-v1.json') or json.loads(p.read_text()) for p in store.path('documents').glob('*.json')}
 for k,d in docs.items():
  if d.get('revision',1)>=2:continue
  store.write('revisions/'+k+'-v1.json',copy.deepcopy(d))
  # Remove an incorrect identity comparison introduced by the researcher prompt, not evidence.
  d['markdown']=d['markdown'].replace('conduit.xyz payments','similarly named companies on other domains')
  for c in d.get('icp_criteria',[]):c['approval_status']='proposed_not_approved'
 d=docs['ideal-customers']
 d['markdown']=d['markdown'].replace('Fit is a hospitality buying situation with high-volume guest conversations and a connected PMS/channel stack—not a claim of universal adoption by property count or industry.', 'Proposed fit starts with an owned guest-communication or coordination job. High volume and a connected PMS can strengthen the opportunity, but public evidence does not establish them as universal eligibility requirements.')
 start=d['markdown'].index('**Necessary fit (logical, not invented cutoffs):**')
 d['markdown']=d['markdown'][:start]+'''**Proposed fit:** an operator seeking to improve guest communication or coordination. Company size, property count, message volume and PMS ownership are not established universal eligibility gates. Public positioning defines a hospitality focus; adjacent markets need confirmation ([Pricing](https://www.conduit.ai/pricing)).

**Conditional readiness:** if the chosen job needs reservation data or write-back, verify the exact PMS, channel route, permissions and supported action. A direct OTA connector and an OTA thread relayed through a PMS are different routes. The catalog labels direct Booking.com and VRBO cards Coming soon, but its Track description includes Booking.com messages; this does not justify excluding every operator using those OTAs ([Integrations](https://www.conduit.ai/integrations)). Missing evidence remains unknown.

**Scope mismatch to confirm:** a buyer seeking only a replacement PMS, channel manager or pricing engine is asking for a different job from the advertised agent layer. Qualify that scope rather than automatically rejecting an account that also wants guest messaging ([Agents](https://www.conduit.ai/product/agents)).

**Unresolved:** Operations availability conflicts between current navigation and comparison copy. Confirm the requested capability before promising it; Operations interest is not an account exclusion. Commercial fit, willingness to pay and deployment eligibility require founder/customer evidence. Customer-count disagreements are not ICP qualification evidence.
'''
 c=d['icp_criteria'][1];c.update(criterion='For a use case requiring PMS data or write-back, the required system and action have a confirmed supported route',dimension='readiness',strength='hypothesis',rationale='Conditional implementation requirement proposed from advertised capabilities; public evidence does not make PMS ownership necessary for every package or buyer.',assessment_method='First identify the requested job; then verify read, relay and write-back separately with the operator and Conduit.',unknown_handling='Unknown compatibility stays pending; do not mark the account unfit.')
 channel={'criterion':'The required guest-channel workflow has a confirmed supported route at the intended launch date','dimension':'readiness','strength':'hypothesis','rationale':'Proposed implementation test. Direct Booking.com/VRBO cards say Coming soon while Track describes Booking.com relay. Direct connector availability is different from every way to receive OTA threads.','assessment_method':'For each required channel, distinguish direct connector, PMS relay, and requested actions; confirm support with product.','unknown_handling':'Unknown remains pending. Do not exclude an account merely because it uses Booking.com or VRBO.','source_ids':['src_a2a67d2faa01de13'],'approval_status':'proposed_not_approved'}
 d['icp_criteria'][4]=copy.deepcopy(channel)
 d['icp_criteria'][6].update(strength='hypothesis',criterion='The requested project is solely a PMS, channel-manager or pricing-engine replacement',rationale='Proposed scope mismatch, not an account-wide exclusion; confirm requested work against advertised agent capabilities.',unknown_handling='Clarify scope; retain guest-communication opportunities even when the account has a separate replacement project.')
 d=docs['customer-jobs'];d['icp_criteria'][1].update(strength='preference',rationale='Action-taking can strengthen differentiation for this job, but official capability pages do not establish it as necessary for all buyers.',unknown_handling='Reply-only use cases are not excluded; assess value and package suitability.')
 d['icp_criteria'][3].update(criterion='An owner can maintain knowledge/SOPs and address workforce implications honestly',rationale='Haven describes a no-layoff reassurance; other stories emphasize labor reduction. Do not generalize one customer policy.',assessment_method='Identify a knowledge owner and ask about planned role changes, employee concerns and desired outcomes.')
 d=docs['buying-triggers'];first=d['markdown'].index('\n\n')
 d['markdown']='''Public stories show operational pressures, implementation choices and later outcomes; they do not consistently establish what triggered the initial purchase. Haven already had Conduit before its 2025 growth-driven adoption push. Cascadia describes acquisition capacity enabled by deployed infrastructure. Growth and acquisition are therefore useful prospecting hypotheses, not proven purchase causes in those cases. Fit, readiness and urgency should be assessed separately.'''+d['markdown'][first:]
 d['markdown']=d['markdown'].replace('### Observed trigger situations (company-published)','### Observed situations and outcomes (company-published)')
 d['markdown']=d['markdown'].replace('| Trigger in the story |','| Situation in the story |')
 d['markdown']=d['markdown'].replace('**Fit (necessary):** hospitality guest-ops job on an existing PMS,', '**Proposed fit:** a hospitality guest-operations job; PMS access is a conditional readiness check when the chosen job needs it,')
 d['markdown']=d['markdown'].replace('a no-layoff or role-evolution narrative if staff fear replacement','an honest account of intended role changes and workforce effects')
 d['markdown']=d['markdown'].replace('channel list that matches live connectors (Booking.com/VRBO Coming soon on [integrations](https://www.conduit.ai/integrations))','a supported route for each required channel, separating direct connectors from PMS relay ([Integrations](https://www.conduit.ai/integrations))')
 d['icp_criteria'][0].update(strength='hypothesis',rationale='Stories show growth pressure, adoption expansion and enabled acquisitions. They do not consistently date the initial purchase to these events.',assessment_method='Ask what changed, whether it predates purchase or expanded adoption, and what operational consequence has a deadline.',unknown_handling='Unknown timing stays unknown; no dated trigger does not exclude an otherwise suitable account.')
 d['icp_criteria'][3].update(criterion='Leadership supports knowledge/SOP ownership and honest discussion of workforce effects',rationale='Knowledge ownership is an implementation consideration. Haven reassured staff about layoffs, whereas other stories emphasize reduced staffing cost; neither is universal policy.')
 d['icp_criteria'][5]=copy.deepcopy(channel)
 d['icp_criteria'][6].update(criterion='Required Operations dispatch capability and availability are confirmed before commitment',dimension='readiness',strength='hypothesis',rationale='Conflicting availability is an unresolved delivery question, not evidence of account unfitness.',assessment_method='Separate dispatch from messaging scope; verify current availability directly with product.',unknown_handling='Hold the capability promise pending confirmation, while keeping account fit separately assessed.')
 for k,d in docs.items():
  d['source_ids']=sorted(evidence_union(d,sources));d.update(revision=2,review_status='independent_findings_adjudicated_human_review_pending',updated_at=now())
  errors=validate_document(d,sources)
  if errors:raise ValueError(str(errors))
  store.write('documents/'+k+'.json',d);store.path('documents/'+k+'.md').write_text(d['markdown'])
 # Retain original candidate statements, but do not promote compound statements on partial spans.
 raw=store.read('claims.json',{});observations={};dispositions=[]
 for c in raw.values():
  dispositions.append({'candidate_claim_id':c['id'],'decision':'withheld_from_fact_promotion','reason':'Compound statement is not independently entailed by its exact attached spans; use source-only observations and reviewed documents pending claim-specific approval.'})
  for e in c.get('evidence',[]):
   if validate_claim({'statement':e['quote'],'status':'observed','evidence':[e]},sources):continue
   key='observation_'+digest(e)[:16]
   observations[key]={'id':key,'statement':e['quote'],'epistemic_status':'source_statement_only','evidence':[e],'source_url':sources[e['source_id']]['url'],'inherited_claim_id':c['id'],'not_independent_verification':True}
 store.write('reviewed-evidence.json',{'created_at':now(),'promotion_allowed':False,'observations':list(observations.values()),'candidate_dispositions':dispositions,'identity_attribute_evidence':store.read('ad-harvest-report.json',{}).get('identity')})
 assets=store.read('assets.json',{})
 wordmark='asset_761b0b47f1b7c604d186'
 for aid in [wordmark,'asset_4da0c092f8267c5adb40','asset_d4f65f4ffb224f420066']:
  a=assets.get(aid)
  if not a or not a.get('analysis'):continue
  if not store.read('revisions/'+aid+'-analysis-v1.json'):store.write('revisions/'+aid+'-analysis-v1.json',a['analysis'])
  a['analysis']=copy.deepcopy(store.read('revisions/'+aid+'-analysis-v1.json'))
  v=a['analysis'];g=v['guidance'];v['uncertainties']=v.get('uncertainties',[])
  if aid==wordmark:
   v['name']='Conduit official website wordmark'
   v['description']='Dark Conduit wordmark from the current official website SVG; the pale preview field is an inspection matte, not part of the original artwork.'
   v['observed']['colors']='Original SVG paths use the supplied dark fill. The pale inspection background was added only for preview.'
   v['observed']['composition']='Wordmark on a transparent SVG canvas; no source background rectangle.'
   g.update(use_when='Primary brand identification using the current official website mark.',how_to_use='Place the original SVG unchanged; preserve geometry, fill colors and clear space.',background_suitability='Use a light background with contrast for the supplied dark mark. Obtain an approved light variant before placing on a dark field.',crop_and_placement='Do not crop, stretch, recolor or reverse the original logo.')
   a['brand_authority']='current_official_website'
  else:
   v['name']='Provider-attributed Conduit chevron · '+('pale variant' if aid=='asset_4da0c092f8267c5adb40' else 'dark variant')
   v['description']='Chevron symbol returned by Brandfetch for conduit.ai. Current usage alongside the website wordmark has not been confirmed.'
   g.update(use_when='Reference inspection only until the brand owner confirms this variant.',how_to_use='Prefer the current website wordmark for draft concepts. Keep this provider original unchanged and pending approval.',avoid_when='Do not use as the approved primary logo, recolor it, or assume it replaces the website wordmark.',background_suitability='Inspect the original on suitable contrast; brand owner must approve actual placement and variant usage.')
   v['uncertainties'].append('Provider domain attribution is verified; currency and approved use of this chevron variant are unresolved.')
   a['brand_authority']='provider_attributed_current_usage_unconfirmed'
  a['analysis_revision']=2;a['human_approved']=False
 store.write('assets.json',assets)
 print('Independent review corrections applied; candidate facts remain unpromoted.',flush=True)
