"""Record the human-visible review checkpoint without promoting drafts to approval."""
from core import now, digest

REASONS={
 'hotel-fit':'Keeps hotel fit provisional; asks about PMS, buyer, channel and economics; does not transfer rental case percentages to a hotel group.',
 'small-rental-quote':'Refuses the unsupported 22 × $18 quote, identifies the published Startup offer, and asks about package eligibility and billable units.',
 'unknown-stack':'Treats an unknown PMS as research/readiness, not a reason to reject an otherwise relevant rental operator.',
 'operator-vs-operations':'Separates the workspace assistant, Internal Agents and the Operations product; avoids promising housekeeping replacement.',
 'proof-and-copy':'Produces a bounded hotel copy draft and preserves the scope of boutique-hotel proof. It is not a finished or layout-tested creative.',
 'account-logo':'Initial answer selected the safe original icon but underused the observed white-wordmark treatment. Structured asset context was improved; the focused retest names the exact SVG treatment, export dependency and missing Hyatt master.'}

OVERRIDES={
 24:'Qualified rather than merging conflicting PMS workspace-type instructions into a single guaranteed support list.',
 29:'Preserved Track’s data-sync versus marketing-copy discrepancy. Did not adopt the reviewer’s categorical OTA denial from a Coming soon badge.',
 39:'Reviewer lacked the full Flex story in its selected packet. The captured story exists; added direct attribution and distinguished build-versus-buy from a vendor replacement.',
 42:'Public pricing and the expanded Portals FAQ establish both Guest inclusion and an add-on path. Replaced the ambiguous statement without declaring all packaging unknown.',
 47:'Removed the closed navigation-label gate; did not adopt another closed four-label gate because official sources also name resorts, villas and aparthotels.',
 54:'Reviewer incorrectly said no captured directory marks OTAs Coming soon. The directory exists; linked it and preserved the conflict with marketed messaging paths.',
 66:'Disambiguated the products and required feature-level confirmation. Did not infer that a pricing bullet alone proves an operational feature is generally available.'}

NOTES={
 'company-overview':'Expanded company identity and commercial model; removed navigation-only fit gates; narrowed historical naming and customer proof.',
 'commercial-model':'Removed unsupported self-serve checkout and quote math; linked public credit consumption and explicit commercial unknowns.',
 'products-capabilities':'Separated package eligibility, catalog availability and connector paths; retained conflicting workspace setup instructions.',
 'product-agents':'Used complete FAQ and credit documentation; separated automation expectations, package availability and customer dates.',
 'product-portals':'Regenerated from full FAQ/credit evidence; added all published voice meters with unresolved relationship and narrowed portal-only proof.',
 'product-workflows':'Separated package line items; removed booking-only scope and invented typical-buyer gates; included Other channels and free inbound credits.',
 'product-developers':'Separated in-app custom tools from support-enabled REST/MCP and commercial v3-plan terminology.',
 'product-operator':'Resolved the previously unspecified Operator credit category with the official token-based guide.',
 'pricing':'Included current credit rules and the Operator/Operations distinction; preserved quote and meter questions.',
 'customer-evidence':'Corrected entities, denominators, comparison windows, staffed-support contribution and customer-adjacent tools.',
 'integrations':'Separated catalog copy, setup data sync, messaging and unestablished write actions; corrected v3 terminology.',
 'alternatives':'Distinguished security assertions, Haven metric conflict and Jurny’s web application; kept vendor comparisons attributed.',
 'brand-messaging':'Corrected customer attribution, causal/time-window overclaims, product boundaries and portfolio scope; repaired prose in a final editorial pass.',
 'brand-voice':'Attributed the VA replacement to Easy BnB and preserved Wynwood resolution rather than first-response time.',
 'message-map':'Propagated staffing, entity, timing and denominator constraints beside each usable proof statement.',
 'writing-examples':'Kept Lauderdale’s staffing contribution and HomeHop’s deployment-window conflict beside campaign examples.',
 'ideal-customers':'Separated channel readiness from account fit and corrected the scope of hiring-ratio evidence.',
 'icp-hotels':'Separated actual product mismatches from availability checks; preserved package choices, hotel-proof limits and optional PMS readiness.',
 'icp-rentals':'Separated challenge context from outcomes, expectations from measured results, and serviced-apartment operating models.',
 'buyer-roles':'Separated customer-specific stacks and staffing changes; added practical but explicitly proposed professional title/remit hypotheses.',
 'buying-triggers':'Removed urgency as a necessary fit gate and disambiguated Operator, Operations and package feature claims.',
 'customer-jobs':'Corrected Easy BnB attribution, separated STR acquisition from hotel proof and bounded connector actions.'}

def closeout(store):
 review=store.read('quality-review.json',{})
 dispositions=[]
 for n,i in enumerate(review.get('issues',[]),1):
  d=store.read('documents/'+i['document_key']+'.json')
  dispositions.append({'id':n,'document_key':i['document_key'],'severity':i['severity'],
   'reviewer_problem':i['problem'],'disposition':'Qualified or partially rejected' if n in OVERRIDES else 'Editorially addressed',
   'reason':OVERRIDES.get(n,NOTES[i['document_key']]),'current_revision':d['revision'],'current_body_sha256':digest(d['markdown']),
   'verification':'Parent-agent source and draft review; not a blind re-score or human approval.'})
 store.write('review-dispositions.json',{'at':now(),'findings':dispositions,'human_approved':False})
 tests=store.read('sales-exercises.json')
 for c in tests['cases']:
  c['assessment']={'verdict':'Partial on first pass' if c['id']=='account-logo' else 'Passed bounded case',
   'reason':REASONS[c['id']],'reviewer':'Parent agent; not human approval'}
 store.write('sales-exercises.json',tests)
 retest=store.read('sales-exercises-logo-retest.json',{})
 if retest.get('cases'):
  retest['cases'][0]['assessment']={'verdict':'Passed focused retest','reason':REASONS['account-logo'],'reviewer':'Parent agent; not human approval'}
  store.write('sales-exercises-logo-retest.json',retest)
 lineage=store.read('rework-lineage.json')
 receipts=store.read('spend.json',[])
 store.write('research-session.json',{'started_at':lineage['started_at'],'finished_at':now()})
 store.write('evaluation.json',{
  'successes':[
   '25 documents in seven folders: two company, nine product/capability, four brand/messaging, six audience, two proof, one identity and one library guide.',
   'Product guides now explain buyers, workflows, limits, integration paths, package fit, differentiation, proof and sales questions. ICP follows product/proof research.',
   '56 original assets have human descriptions and separate Agent context. Existing website and LinkedIn originals are retained with source hashes.',
   'Six bounded downstream-use cases: five passed on the first attempt; logo handoff was partial, then passed a focused retest after the context contract was improved.',
   'The current Clue contracts and cloned database were inspected read-only. No platform, database or environment changes were made.'
  ],
  'failures':[
   'The logo pack is not four approved transparent masters. The transparent dark icon remains unavailable; reverse wordmark uses the official website treatment, not a separate white source file.',
   'Some public product availability, credit rates, customer measurement windows and package paths conflict. The library preserves these rather than manufacturing certainty.',
   'Target-company logos such as Hyatt are not present. No finished Conduit × Hyatt creative was produced in this research task.',
   'This is a Conduit-specific experiment with selected input bundles and manual editorial corrections, not a proven autonomous multi-brand system. New prompt safeguards have not been benchmarked end to end on another brand.',
   'Original ad-harvest coverage limitations remain; this rework reused the earlier verified originals instead of claiming a fresh exhaustive recent-ad harvest.',
   'Human approval, live-platform integration, production refresh/retry behavior and performance validation remain separate future gates.'
  ],
  'review_summary':f"Separate critic calls reviewed 23 generated documents and raised {len(dispositions)} suggestions, including repeated issues and several overreaching corrections. Each has an editorial disposition and revision hash. Manual identity/organization guides were inspected separately. These are model and parent-agent judgments, not an independent human quality pass.",
  'execution_note':'The rework reused the original public corpus, added official documentation/FAQ/identity evidence, generated dependency-ordered documents, then ran content review and six downstream-use exercises. Prior drafts remain in history. One focused logo test hit a connection error and was retried once; its original reservation remains explicitly uncertain. No image generation or new paid ad harvest occurred.',
  'cost_note':f"Current-run reported model charges only. Reused V1 evidence previously incurred ${lineage['previous_reported_cost_usd']:.2f} in reported provider charges, plus unreported Brandfetch/Adyntel costs. Development/Codex costs are excluded. Unresolved reservations are not reported as actual spend.",
  'human_approved':False,'production_ready':False,
 })
 baseline=store.read('baseline-comparison.json',{})
 baseline.setdefault('original_pilot_summary',baseline.get('summary'))
 baseline['summary']='Read-only platform comparison: existing Conduit onboarding already had separate detailed product reports, while the first pilot collapsed them. This rework restores product-specific depth, adds commercial and messaging guides, and makes audience decisions depend on product/proof evidence. The current platform has title/description/usage_note but no separate structured Agent context field; that remains a proposed integration contract.'
 store.write('baseline-comparison.json',baseline)
 print('Editorial dispositions:',len(dispositions))
