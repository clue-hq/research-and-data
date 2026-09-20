"""Explicit editorial corrections; preserve prior drafts and record the evidence basis."""
import copy
import re
from core import now
from knowledge import evidence_union

def revise(store,key,edit,reason):
 d=store.read('documents/'+key+'.json');old=copy.deepcopy(d)
 edit(d)
 if d==old:return
 revision=old.get('revision',1)
 store.write('history/'+key+'/'+str(revision)+'.json',old)
 d.update(revision=revision+1,edited_at=now())
 d.setdefault('editorial_reviews',[]).append({'at':now(),'reason':reason,'human_approved':False})
 d['source_ids']=sorted(evidence_union(d,store.read('sources.json',{}))|{n['source_id'] for n in d.get('evidence_notes',[])})
 d['agent_context']['source_ids']=d['source_ids']
 store.write('documents/'+key+'.json',d);store.path('documents/'+key+'.md').write_text(d['markdown'])

def initial_corrections(store):
 sources=store.read('sources.json',{})
 def sid(url):return next(k for k,s in sources.items() if s['url']==url and s['method']=='direct_html')
 def company(d):
  body=d['markdown']
  body=body.replace('| Brand | Conduit / Conduit AI; site conduit.ai | Legal entity not published in these passages |','| Brand and operating entity | Conduit / Conduit AI; the privacy notice identifies HostAI Labs, Inc. dba Conduit | [Privacy notice](https://www.conduit.ai/privacy), updated 2 December 2025; this is a company disclosure, not a registry check |')
  body=re.sub(r'## Business model\n.*?(?=\n## Market position)', '''## Business model

Conduit sells recurring software packages with monthly credits. The public pricing page lists starting rates of $18 per unit per month for Messaging, $30 for Guest, $36 for Guest + Devices and $48 for Full Suite. Included credits rise from 40 to 100 per unit per month across those tiers. A separate Startup offer is explicitly labeled for 0–25 units at $899 per month with 2,000 credits and no implementation fee. Package eligibility, the definition of a billable unit, credit consumption and any additional usage charges must be established for a real quote; a seller should not apply a per-unit headline rate to a small portfolio without checking the Startup rules. [Pricing](https://www.conduit.ai/pricing)

These packages combine capabilities: Messaging includes Inbox, Voice AI, PMS/OTA integrations, Operator, workflows, escalation and reporting; higher packages add portals, payments, devices and operational functions. They are not separately published licenses for each product guide. The site lists operational functions in Full Suite while its navigation marks Operations as coming soon. Confirm the exact feature and release availability in a proposal, rather than claiming the entire category is either fully shipped or unavailable. See [Pricing & packaging](#knowledge/pricing) and [Operator & internal AI availability](#knowledge/product-operator). [Pricing](https://www.conduit.ai/pricing)

The company uses demo and Get Started calls to action and a separate affiliate channel. Customer stories can explain economic motivation, but a customer's support-cost saving is not Conduit's subscription revenue or list price. Public evidence does not establish realized ACV, retention, total revenue or payback for a new customer. [Commercial model & market context](#knowledge/commercial-model) separates those questions from the published rate card.
''',body,flags=re.S)
  body=body.replace('Operations, devices, and leasing/housing scope are either “coming soon,” LinkedIn-only, or leftover HostAI/YC language—confirm before selling them.', 'Resolve availability at the specific feature level: devices and operational functions appear in the public packages, Operations is marked coming soon in navigation, and broader leasing/housing language comes from historical sources. Do not treat those as one uniform availability claim. [Pricing](https://www.conduit.ai/pricing)')
  d['markdown']=body
  d['open_questions']=[q for q in d.get('open_questions',[]) if not any(x in q.lower() for x in ['legal entity','list packaging'])]
  d['source_ids']=list(set(d['source_ids'])|{sid('https://www.conduit.ai/privacy'),sid('https://www.conduit.ai/pricing')})
  d['evidence_notes']=[n for n in d['evidence_notes'] if 'legal entity' not in n.get('statement','').lower()]
  if not any('HostAI Labs' in n.get('statement','') for n in d['evidence_notes']):d['evidence_notes'].append({'statement':'The privacy notice names HostAI Labs, Inc. dba Conduit.','source_id':sid('https://www.conduit.ai/privacy'),'quote':'This Privacy Notice for HostAI Labs, Inc. dba Conduit'})
 def commercial(d):
  d['markdown']=d['markdown'].replace('so it is not a billed, generally available module in the current catalog', 'while the pricing page lists tasks, workforce and operational workflows in Full Suite; the exact release and quoted feature availability need reconciliation')
  d['markdown']=re.sub(r'A 10-unit Messaging quote.*?Beyond 50 listings,', 'The page provides a separate Startup package for 0–25 units at $899/month with 2,000 credits and no implementation fee. Do not present a small-portfolio quote by multiplying the lower headline per-unit rate: eligibility and Startup package rules must be confirmed. Beyond 50 listings,',d['markdown'],flags=re.S)
 revise(store,'company-overview',company,'Read official privacy and pricing passages directly; correct missing legal identity, omitted business model and an overbroad availability inference.')
 revise(store,'commercial-model',commercial,'Remove an unestablished 10-unit quote and separate Operations navigation status from published Full Suite inclusions.')

def readiness_corrections(store):
 def operator(d):
  d['markdown']=d['markdown'].replace('Sources here do not state Operator chat credit cost, a unique plan gate beyond that Messaging line, or that Operator itself sends guest messages without a configured agent or workflow.', 'The credit guide says Operator turns are metered by model and billable tokens, while internal-agent runs have a dynamic work-based cost. It gives roughly 7,000–71,000 billable tokens per credit depending on model, with possible context discounts; this is not one universal per-turn price. It does not establish that Operator autonomously sends guest messages without configured tools and permissions. [Credit guide](https://docs.conduit.ai/setting-up-conduit/credits)')
 def hotels(d):
  d['markdown']=d['markdown'].replace('Clearer mismatches: kiosk or other physical check-in hardware as the product; Operations as GA because the nav still says coming soon; using Haven-class STR percentages as hotel results; assuming every PMS card supports the same writes.', 'A physical check-in kiosk as the required deliverable is a product mismatch. Operational requirements such as housekeeping or workforce management require feature-level confirmation: navigation says Operations is coming soon while Full Suite lists operational capabilities. That conflict is a readiness question, not an automatic rejection of the hotel account. Separately, transferring STR percentages to hotels or assuming all PMS connectors support the same writes are sales errors, not negative ICP criteria. [Pricing](https://www.conduit.ai/pricing)')
 def icp(d):
  d['markdown']=d['markdown'].replace('Product language limits are not specified beyond Wynwood’s multilingual CX story','Multilingual replies are marketed, but required-language quality and channel coverage must be confirmed for the actual workflow')
  d['markdown']=d['markdown'].replace('whether multilingual operation is a product capability or only a Wynwood outcome','which required guest languages and channels are supported at the needed quality')
 def roles(d):
  marker='## Priorities and desired results'
  addition='''### Roles to test during discovery

The following title hypotheses make the committee map actionable; they are suggested search roles, not confirmed Conduit buyers or required titles.

| Buying role | Titles to test | Decision and practical question |
| --- | --- | --- |
| Independent-hotel sponsor | Owner, general manager, operations director | Owns staffing and guest-service economics. Who can approve a change to night coverage and its budget? |
| Group-level sponsor | COO, VP/Director of Operations, guest-experience leader | Owns shared service standards and rollout. Is purchasing centralized, property-led, or franchise-controlled? |
| Operational champion | Front Office Manager, reservations lead, guest-services/CX manager | Owns queues, knowledge and escalation. Who can maintain policies and measure response quality after launch? |
| Technical evaluator | IT director, business-systems/PMS administrator, integration owner | Confirms reservation data, channel routing and permitted actions. Which connection path and write permissions are actually available? |
| Risk and commercial reviewers | Security/privacy reviewer, procurement or finance owner when required | Confirms guest-data handling, contract and usage economics. Who approves access, billing assumptions and vendor onboarding? |

Role seniority and property-versus-group remit are relevant professional demographics. Age, gender and personal income are not needed for these buying decisions. Validate the role map with the account instead of assuming that every company has every department.

'''
  if '### Roles to test during discovery' not in d['markdown']:d['markdown']=d['markdown'].replace(marker,addition+marker)
 def workflow(d):
  d['markdown']=d['markdown'].replace('[Operations](#knowledge/product-operator) is listed as coming soon','Operations is listed as coming soon; it is separate from the Operator assistant')
 for key,edit,reason in [('product-operator',operator,'Add the official credit guide discovered through billing documentation.'),('icp-hotels',hotels,'Separate genuine product mismatches from readiness questions and seller claim errors.'),('ideal-customers',icp,'Do not describe multilingual capability as absent when marketed explicitly; ask about workflow-specific coverage.'),('buyer-roles',roles,'Add usable professional title hypotheses with remit and discovery questions, kept distinct from observed customer titles.'),('product-workflows',workflow,'Remove the misleading link that equated Operations with Operator.')]:revise(store,key,edit,reason)

def review_corrections_first(store):
 def agents(d):
  b=d['markdown'].replace('customer, internal, and voice agents','external (guest-facing), internal, and voice agents')
  b=b.replace('The product page FAQ “How much can Conduit\'s agents resolve on their own?” has no published answer in the captured page.', 'The complete product FAQ says resolution depends on the guest requests, knowledge base, integrations and escalation rules; track resolved conversations and human handoffs. It does not prescribe a universal automation percentage.')
  b=b.replace('Higher bundles (Guest $30, Guest + Devices $36, Full Suite $48 per unit per month) add portals/devices/ops—not a separate agent meter.', 'Guest ($30/unit/month) adds the stay/portal layer; Guest + Devices ($36) adds devices; Full Suite ($48) lists workforce and operational features. Operations remains marked coming soon in navigation, so confirm the specific operational feature before promising availability. These are package rates, not a separate Agents license.')
  b=b.replace('Unknown from these pages: credit cost of ordinary agent replies outside [workflow credit rules](#knowledge/product-workflows), overage rates, and whether voice minutes inside Agents match the workflow Voice Agent Call rate (6 credits/minute) or the non-workflow voice rate (1 credit/minute).', 'The credit guide says inbox AI replies use no credits, regular voice costs 1 credit/minute and AI voice costs 8 credits/minute. The workflow action guide separately lists Voice Agent Call at 6 credits/minute. Confirm the applicable call path and how these meters relate before quoting; do not silently substitute or add the rates. Dollar overage pricing remains unestablished. [Credit guide](https://docs.conduit.ai/setting-up-conduit/credits) [Workflow usage](https://docs.conduit.ai/workflows/workflow-usage)')
  b=b.replace('Deployed March; story dated around December 2024 usage','Start date unresolved: header says December 2024; body describes a March deployment')
  b=b.replace('CEO: “70% automation of customer service is very realistic”; page hero also says 90% of guest communication automated | Preserve 70% vs 90%; using since December 2023','CEO describes 70% automation as “very realistic”; the hero also claims 90% | The hero and body differ, and 80–90% also appears as a future ambition. Do not use 90% as a verified outcome; using-since header says December 2023')
  d['markdown']=b
 def workflows(d):
  b=d['markdown'].replace('Conduit Workflows is the product for automating the guest journey after a booking exists—not the live reply engine itself.', 'Conduit Workflows provides visual automations for proactive messages, routing and triage. Hospitality examples follow the stay journey, but triggers can also involve a new contact, a tag or an AI tool call; an existing booking is not a universal prerequisite. Agents supply the live reply behavior.')
  b=b.replace('Buyers are typically founders, revenue/guest-services leads, or ops owners','Buyer-role hypotheses include founders, revenue/guest-services leads and operations owners, informed by named stories rather than a required title map')
  b=b.replace('Workspace with hospitality type so PMS connections appear','Confirm that the workspace industry setting exposes the selected PMS; follow that provider’s setup instructions')
  b=b.replace('Higher bundles (Guest from $30, Guest + Devices from $36, Full Suite from $48 per unit per month) nest Messaging and add portals/devices/operations features—including “Device management workflows” and “Agentic operations workflows” on those SKUs, which are not the same as a Workflows-only fee.', 'Guest starts at $30/unit/month and adds portals, waivers and upsells. Guest + Devices starts at $36 and adds device management workflows. Full Suite starts at $48 and lists agentic operations workflows, tasks/workforce, scheduling/dispatch and inventory. Confirm exact availability because navigation still labels Operations as coming soon. None is a Workflows-only fee.')
  b=b.replace('| Voice Agent Call (workflow action) | 6 per minute |','| Other-channel outbound message (non-AI / AI-generated) | 0 / 3 |\n| Voice Agent Call (workflow action) | 6 per minute |')
  b=b.replace('How far 40 credits per unit goes for a typical stay sequence is not published;', 'Inbound messages use no credits. The general credit guide separately lists regular voice at 1/minute and AI voice at 8/minute, versus the workflow action table’s 6/minute; confirm the applicable meter for the actual call path. [Credit guide](https://docs.conduit.ai/setting-up-conduit/credits) How far 40 credits per unit goes for a typical stay sequence is not published;')
  b=b.replace('Dan Mitchen called using AI in workflows with SuiteOP “an absolute game changer.”', 'Dan Mitchen said using AI in workflows with SuiteOP “is going to be an absolute game changer”—a forward-looking expectation, not a measured workflow result.')
  d['markdown']=b
 def developer(d):
  d['markdown']=d['markdown'].replace('Only (2)–(4) require a developer and v3 API/MCP enablement.', 'Custom code needs someone able to implement and maintain it, but in-app custom tools are separate from external REST/MCP enablement. REST/MCP access is described as requiring support-enabled v3 access; that wording does not establish a separately priced package. Connecting an existing MCP client may be an administrator task, while building a custom integration needs engineering. Do not require API access merely to use a visual workflow or in-app tool.')
 def operator(d):
  d['markdown']=d['markdown'].replace('Credit consumption for Operator sessions, default enabled tools, whether Operator can take write actions on guest conversations without an agent, and how Messaging “Operator” maps to V3 UI for every plan remain unspecified in these captures.', 'Operator credit metering is documented above; there is no single flat per-turn price. Remaining questions concern default enabled tools, guest-conversation write permissions, and how Messaging’s Operator inclusion maps to each workspace version.')
 def voice_bound(d):
  marker='## Choosing a package' if d['key']=='pricing' else '## Differentiation'
  addition='The [workflow action guide](https://docs.conduit.ai/workflows/workflow-usage) separately lists Voice Agent Call at **6 credits/minute**, while the general guide lists AI voice at **8** and regular voice at **1**. Confirm which meter applies to the actual call path and whether any usage overlaps; these sources do not justify silently substituting or adding the rates.\n\n'
  if addition not in d['markdown']:d['markdown']=d['markdown'].replace(marker,addition+marker)
  if d['key']=='product-portals':d['markdown']=d['markdown'].replace('Published customer stories in this source set (Haven, Cascadia, Lauderdale, Cosmica, Bali Luxury Stays, and others)', 'The broader [customer evidence library](#knowledge/customer-evidence), which includes Haven, Cascadia, Lauderdale, Cosmica and Bali Luxury Stays,')
 for key,edit in [('product-agents',agents),('product-workflows',workflows),('product-developers',developer),('product-operator',operator),('pricing',voice_bound),('product-portals',voice_bound)]:revise(store,key,edit,'Resolve source-checked content review findings: factual scope, pricing meter distinctions, product availability, and attribution.')

def review_corrections_company(store):
 def company(d):
  d['summary']='Conduit builds AI agents and a shared workspace for hospitality guest operations: answering messages and calls, coordinating handoffs, and connecting the stay journey to property systems. This overview explains its product system, commercial model, customer situations and market position, with source disagreements kept visible where they affect a claim.'
  d['markdown']=d['markdown'].replace('Qualify on whether the account is actually in the three published industries, already drowning in guest conversations, and willing to put knowledge/SOPs into the agent', 'Qualify the actual hospitality operating model and guest-communication workload, including the marketed hotel/rental segments and FAQ serviced apartments; resorts, villas and aparthotels are not excluded merely because the navigation groups them differently. Establish willingness to maintain property knowledge and procedures')
  d['markdown']=d['markdown'].replace('Phone redacted in the PitchBook scrape','Third-party location listing; confirm current business address if needed')
  d['markdown']=d['markdown'].replace('CEO: 70% CS automation “very realistic”; 17 tools in the prior stack','CEO assessment: 70% CS automation is “very realistic,” not an independently measured result; 17 tools in the prior stack. The story’s 90% hero and 70%+ results copy differ')
  d['markdown']=d['markdown'].replace('onboarding copy still says “HostAI”','the historical customer setup quote uses “HostAI”; this does not describe today’s onboarding UI')
  d['markdown']=d['markdown'].replace('story claims ≥$3,400/mo NOI and >$500k asset value at an 8% cap','story claims ≥$3,400/mo NOI and >$500k modeled asset value at an 8% cap; it also describes staffed support, so the software-only contribution is unresolved')
 def commercial(d):
  for k in ['markdown','summary']:
   d[k]=d[k].replace('sold mainly through demos and self-serve starts','presented through Book demo, Get Started and Talk to Sales calls to action; self-serve checkout is not established')
  d['markdown']=d['markdown'].replace('What a credit consumes, whether unused credits roll, and overage rates are not on the pricing page.', 'The rate card gives included credits; the documentation explains consumption for voice, Operator, internal agents and paid workflow actions, while inbox AI replies use no credits. Included credits reset monthly. Dollar overage rates and contractual treatment of unused credits still need confirmation. [Credit guide](https://docs.conduit.ai/setting-up-conduit/credits) [Detailed pricing guide](#knowledge/pricing)')
 def catalog(d):
  d['markdown']=d['markdown'].replace('Coming soon / incomplete: Operations in the product nav; Booking.com and VRBO on the integrations directory.', 'Availability conflicts to resolve: Operations is marked coming soon in navigation while Full Suite lists operational features. The integration directory marks Booking.com and VRBO coming soon, but industry pages and release notes describe OTA messaging paths. Confirm whether each target account uses a direct connection, a PMS-mediated path or an unavailable action; neither a directory badge nor a marketing logo establishes the complete workflow.')
  d['markdown']=d['markdown'].replace('For 0–25 units, the site offers a Startup full-feature monthly price rather than the per-unit ladder; above that, talk-to-sales language applies to Full Suite and scale beyond 50 listings.', 'Startup is a published $899/month path for 0–25 units. Messaging, Guest and Guest + Devices show per-unit starting rates with Get Started; Full Suite has Talk to Sales. The site says pricing scales beyond 50 listings without publishing the curve. Confirm package eligibility rather than making 25 or 50 a universal sales-process gate.')
  d['markdown']=d['markdown'].replace('## Choosing the entry point', 'PMS visibility also depends on workspace industry configuration. The setup documentation uses STR/LTR in general instructions and STR/Hotel in a provider-specific passage. Confirm the selected PMS and workspace setting; this is implementation readiness, not a negative ICP rule. [PMS setup](https://docs.conduit.ai/setting-up-conduit/connect-pms)\n\n## Choosing the entry point') if 'PMS visibility also depends' not in d['markdown'] else d['markdown']
 for key,edit in [('company-overview',company),('commercial-model',commercial),('products-capabilities',catalog)]:revise(store,key,edit,'Resolve reviewed company, commercial and catalog scope errors against the public evidence; distinguish marketing groups from qualification gates.')

def review_corrections_brand(store):
 def catalog(d):
  d['markdown']=d['markdown'].replace('**Coming soon / incomplete:** Operations in the product nav; Booking.com and VRBO on the integrations directory.', '**Availability conflicts:** Operations is marked coming soon in navigation while Full Suite lists operational features. The integration directory labels Booking.com and VRBO coming soon, but industry pages and release notes describe OTA messaging paths. Confirm direct versus PMS-mediated connections and the exact enabled actions; do not promise or deny the complete workflow from one directory badge.')
 def alternatives(d):
  b=d['markdown'].replace('Haven runs 95 percent automation across 270 properties','Haven runs 95 percent automation across 270 properties, according to that comparison page; Haven’s own customer story says 90%, so the conflicting 95% must not become a proof claim')
  b=b.replace('adds 120+ countries, HIPAA, GDPR, ISO 27001','adds reach and security assertions including HIPAA/GDPR/ISO language; the homepage specifically says SOC 2 Type II and support for HIPAA workflows. These are different assertions, and current attestations must be confirmed before repeating comparison-page certification language')
  b=b.replace('branded guest app','branded guest web app (no download required)')
  d['markdown']=b
 def messaging(d):
  b=d['markdown'].replace('Lauderdale reports support cost falling from $4,000 to $600 per month','Lauderdale’s story describes support spend beginning at $4,000, later reaching $1,200 on prior services, then $600/month with Conduit; the $4,000-to-$600 headline is not a clean immediate before/after')
  b=b.replace('HomeHop reports growing from 40 to 108 listings without extra guest-support hires','HomeHop describes portfolio growth from 40 to 108 listings without extra guest-support hires, but the customer-since header and two-year narrative disagree; do not present that growth as a verified Conduit-period result')
  b=b.replace('Flex’s decision not to rebuild conversational AI are named displacements','Flex’s stated choice not to rebuild conversational AI are different evidence types: Bocobay is a named replacement, while Flex is an operator’s build-versus-buy account. [Flex story](https://www.conduit.ai/customers/the-flex)')
  b=b.replace('Stay inside hospitality guest operations (the three published industries, plus FAQ language for serviced-apartment operators)','Stay inside the supported hospitality guest-operations use case: the site’s main industry groups plus serviced apartments, aparthotels, resorts and villas where their operating model fits')
  b=b.replace('Portals are packaged separately on the public site','Portals is a distinct product surface; the Guest bundle includes portals and the Portals FAQ also describes a paid add-on with negotiated listing-based pricing. [Pricing](https://www.conduit.ai/pricing) [Portals FAQ](https://www.conduit.ai/product/portals.md)')
  if 'Internal Agents, connector actions and Operations' not in b:b+='\n\n**Internal Agents, connector actions and Operations are separate.** Internal Agents are marketed for internal tasks; an action such as creating a housekeeping task depends on the connected system and permissions. Operations is a separately named product marked coming soon in navigation, even though Full Suite lists operational capabilities. Confirm the exact workflow and release availability before using it as a campaign promise. [Agents](https://www.conduit.ai/product/agents) [Pricing](https://www.conduit.ai/pricing)\n'
  d['markdown']=b
 def voice(d):
  d['markdown']=d['markdown'].replace('Bali’s VA-replacement story is a named exit narrative','Easy BnB’s VA-replacement story, published on the Bali Luxury Stays page, is a named exit narrative; Bali Luxury Stays is the founder’s subsequent venture')
  d['markdown']=d['markdown'].replace('Ads retell Wynwood (15 minutes → about 3)','Ads retell Wynwood’s guest resolution time (14–15 minutes → 3), which is different from first-response time')
  d['markdown']=d['markdown'].replace('“faster answers”','“faster guest resolution”')
 for key,edit in [('products-capabilities',catalog),('alternatives',alternatives),('brand-messaging',messaging),('brand-voice',voice)]:revise(store,key,edit,'Resolve brand/proof review findings with specific source attribution; preserve conflicting results and separate product, packaging and target-entity meanings.')

def review_corrections_proof(store):
 def pricing(d):
  note='Operator in Messaging is the workspace assistant, not the Operations product. Operations is separately marked coming soon in navigation; confirm individual Full Suite operational features before promising them. [Operator guide](#knowledge/product-operator)\n\n'
  if note not in d['markdown']:d['markdown']=d['markdown'].replace('## Choosing a package',note+'## Choosing a package')
 def proof(d):
  b=d['markdown'].replace('Email, SMS, OTA, voice AI 1–7 AM, SuiteOP workflows','Email, SMS, OTA and voice AI 1–7 AM; SuiteOP is the customer’s adjacent tool, not a Conduit SKU')
  b=b.replace('~1,500 messages/week, 60% handled by AI; index headline 150% growth','~1,500 messages sent/week, 60% handled by AI; unexplained 150% headline excluded from usable results')
  b=b.replace('Bali Luxury Stays / Easy BnB','Easy BnB (published in the Bali Luxury Stays story)')
  b=b.replace('### Hotel and hotel-like proof','### Boutique hotel and separate multi-market CX proof')
  b=b.replace('“AI-powered support platform and 24/7 staffed support team” replacing a call center','“AI-powered support platform and 24/7 staffed support team” replacing a call center; neither software-only savings nor a public $600 software price')
  b=b.replace('Bali ~$22k/mo and 75 units','Easy BnB ~$22k/mo and 75 units')
  b=b.replace('(Bali/Easy BnB)','(Easy BnB, in the Bali Luxury Stays story)').replace('Bali: eleven VAs replaced','Easy BnB: eleven VAs replaced')
  b=b.replace('Haven; HomeHop; Canbnb 60% of ~1,500 msgs/week','Haven and HomeHop; Canbnb is separate message-volume evidence, not proof of flat headcount')
  if 'Easy BnB is the business behind' not in b:b=b.replace('## What the results do and do not establish','Easy BnB is the business behind the eleven-VA replacement, approximately $22k/month savings and 75 additional units. Bali Luxury Stays is the founder’s subsequent venture, although the page is branded with that name. HomeHop’s portfolio growth period and its customer-since header disagree, so do not claim all 40-to-108 growth occurred during a verified Conduit deployment window. Lauderdale’s cost narrative includes an intermediate $1,200/month provider before $600 and a staffed-support component; keep those boundaries beside any campaign claim.\n\n## What the results do and do not establish')
  d['markdown']=b
 def integrations(d):
  b=d['markdown'].replace('Track card also mentions routing Airbnb/Booking.com messages','Track’s card mentions Airbnb/Booking.com routing, but setup docs classify Track as non-messaging PMS sync. Confirm the actual separate OTA messaging path; neither the card nor a coming-soon directory label settles current availability')
  b=b.replace('Opera public page: read context only through that connector','Opera’s public page documents property/reservation/profile sync and no messaging through that connector. Other write actions are unestablished, not proven impossible')
  b=b.replace('Confirm v3 entitlement before API/MCP; confirm Devices or Portals add-ons before those tool groups.', 'Confirm support-enabled REST/MCP access; the documentation’s “v3 plan” wording is not mapped to public package names. Do not equate a V3 interface or Full Suite with automatic API access. Confirm Devices or Portals entitlements before those tool groups.')
  d['markdown']=b
 def messages(d):
  b=d['markdown'].replace('**Audiences Conduit already names:** Short-term rentals, Independent Hotels, and Hotel Groups. Do not invent extra segments.', '**Published audience:** short-term rentals, independent hotels and hotel groups are the main landing-page groups. Serviced apartments are also explicitly named, and resorts/villas/aparthotels may fit the guest-stay operating model. Navigation labels are not a closed qualification list.')
  b=b.replace('owner models ≥$3,400/mo NOI and >$500k asset value at 8% cap—not an appraisal or closed sale','the story also describes an intermediate $1,200 provider and a 24/7 staffed support team. The owner models ≥$3,400/mo NOI and >$500k at an 8% cap—not an appraisal, closed sale or Agents-only result')
  b=b.replace('Bali ~$22k/mo labor, 75 units, 0 extra FTE','Easy BnB ~$22k/mo labor, 75 units, 0 extra FTE, reported on the Bali Luxury Stays page').replace('Bali (11 VAs replaced)','Easy BnB (11 VAs replaced)')
  b=b.replace('Canbnb ~1,500 messages/week with 60% handled by AI','Canbnb ~1,500 messages sent/week with 60% handled by AI; that send-volume denominator is not interchangeable with another customer’s resolution metric')
  b=b.replace('HomeHop: ~40→108 listings without extra guest-support hires; 70% automation; voice 1–7 AM','HomeHop: ~40→108 listings and 70% automation in its story; the stated growth period and customer-since date disagree, so the full growth cannot be attributed to a verified deployment window; voice 1–7 AM')
  d['markdown']=b
 def writing(d):
  d['markdown']=d['markdown'].replace('support costs reported from $4,000 to $600/month;', 'the cost path includes $4,000, an intermediate $1,200 provider, and $600/month with the described AI platform and 24/7 staffed support team; not an Agents-only result;')
  d['markdown']=d['markdown'].replace('HomeHop’s path from about 40 to 108 listings without extra guest-support hires and 70 percent automation is a separate story;', 'HomeHop’s reported 40-to-108 listing growth and 70 percent automation are a separate story; its June 2025 customer-since header and “approximately two years” narrative conflict, so do not attribute the entire growth window to Conduit;')
 def icp(d):
  d['markdown']=d['markdown'].replace('Haven, HomeHop, and Canbnb describe scale without proportional guest-support hiring','Haven and HomeHop describe scale without proportional guest-support hiring; Canbnb separately describes message volume and AI handling, not a proven flat-headcount result')
  for c in d.get('icp_criteria',[]):
   if c['criterion']=='Guest communication that can be organized by property or team across connected channels':
    c.update(criterion='Guest conversations can use a confirmed Conduit channel path',dimension='readiness',strength='preference',rationale='A supported channel path enables the intended workflow; property/team views are product capabilities, not a minimum portfolio-size rule.',assessment_method='Identify actual guest channels and confirm their connection path. Single-property and multi-property operators can both qualify.',unknown_handling='Research unknown channels. Do not reject a single-property operator or an account whose current inbox is not segmented.')
 for key,edit in [('pricing',pricing),('customer-evidence',proof),('integrations',integrations),('message-map',messages),('writing-examples',writing),('ideal-customers',icp)]:revise(store,key,edit,'Resolve reviewed proof attribution, buying-role and connector readiness issues; preserve unknowns without manufacturing exclusions.')

def review_corrections_audience(store):
 def hotels(d):
  b=d['markdown'].replace('do not assume every OTA thread is live (other catalog pages still mark some OTAs coming soon)', 'confirm each OTA’s actual messaging versus reservation-context path. The integration directory has coming-soon labels, while other public pages describe OTA messaging; resolve that conflict for this account. [Integration directory](https://www.conduit.ai/integrations)')
  b=b.replace('A group whose RFP is enterprise CRM, labor/payroll, or portfolio housekeeping as the must-have. Group use-case pages describe those themes, while the product nav labels Operations coming soon.', 'A group whose RFP requires labor/payroll or portfolio housekeeping as the must-have needs feature-level availability confirmation. An enterprise guest-CRM, loyalty or shared-inbox requirement is a different discovery path and must not be treated as the same coming-soon Operations question.')
  b=b.replace('with Opera or Mews already in use, and a GM willing to maintain property policies','and a GM willing to maintain property policies. Opera or Mews would be readiness examples to investigate, not mandatory fit criteria')
  b=b.replace('Portals is a paid add-on by listing count and is not evidenced in the hotel story','Guest includes portals at a published starting package rate, while the Portals FAQ also describes a listing-based add-on; confirm the applicable commercial path. No Portals outcome is isolated in the hotel story')
  b=b.replace('[Workflows](#knowledge/product-workflows), [Guest Portals](#knowledge/product-portals) |','[Workflows](#knowledge/product-workflows); [Guest Portals](#knowledge/product-portals) is a package/workflow option to investigate, not a proven hotel case outcome |')
  d['markdown']=b
 def rentals(d):
  b=d['markdown'].replace('Canbnb: 7→170 properties; ~1,500 messages/week, 60% handled by AI.', 'Canbnb’s 7→170 properties describes the scaling challenge, not proven hire avoidance; its reported outcome is ~1,500 messages sent/week, 60% AI-handled.')
  b=b.replace('first PM acquisition without extra guest-service staff','leadership expected to absorb its first PM acquisition without extra guest-service staff; a completed staffing outcome is not established')
  b=b.replace('STR / vacation-rental / serviced-apartment manager vs hotel brand. Mixed portfolios: split motions.', 'STR/vacation-rental manager versus hotel-led operation. For serviced apartments and mixed portfolios, establish staffed front-desk versus distributed listing operations before selecting the hotel or rental motion; do not transfer STR case metrics automatically.')
  d['markdown']=b
  for c in d.get('icp_criteria',[]):
   if 'serviced-apartment' in c['criterion']:c['unknown_handling']='For serviced apartments or mixed portfolios, confirm staffed front-desk versus distributed listing operations before applying hotel or rental proof. Unknown operating model means research, not rejection.'
 def roles(d):
  b=d['markdown'].replace('CEOs or partners owning a homegrown PMS, prior AI vendor, or SuiteOP wiring (The Flex, HomeHop, Bali)','The Flex: homegrown PMS, with communications AI bought separately; HomeHop: SuiteOP as an adjacent system; Easy BnB founder: abandoned in-house messaging AI (story on Bali Luxury Stays page)')
  b=b.replace('Haven ~25 people → two per shift','Haven’s support staffing need ~25 people → two per shift, alongside its no-AI-layoff pledge and staff retraining')
  b=b.replace('Bali/Easy BnB is the contrary case','Easy BnB, in the Bali Luxury Stays story, is the contrary case')
  d['markdown']=b
 def triggers(d):
  d['markdown']=d['markdown'].replace('In-category stays + connectable path + named knowledge/escalation owner + at least one confirmed timing situation','In-category stays + connectable path + named knowledge/escalation owner. Timing evidence prioritizes the conversation; it is not a required fit gate')
  d['markdown']=d['markdown'].replace('devices, or Full Suite operations lines?', 'devices, or Full Suite operational features? Operator is the workspace assistant; Operations is a separate coming-soon product label. Confirm the exact operational feature before quoting a delivery commitment.')
 def jobs(d):
  b=d['markdown'].replace('Bali ~$22k/month and 11 VAs replaced','Easy BnB ~$22k/month and 11 VAs replaced, reported on the Bali Luxury Stays page')
  b=b.replace('Cascadia’s adjacent job after buying a PM company: 60% automation and a 4.9 communication score across 100 properties, with leadership saying they could add that company’s properties without extra guest-service hires.', '**Separate STR acquisition example — Cascadia Getaways.** The vacation-rental manager reports 60% automation and a 4.9 communication score across 100 properties. During acquisition integration, leadership expressed confidence about adding properties without extra guest-service hires; this is an expectation, not a completed staffing result or hotel proof.')
  b=b.replace('Agents on voice, chat, email, WhatsApp, OTA with reservation context','Agents on connected voice/chat/email/WhatsApp/OTA paths with available reservation context; confirm channel routing and supported actions per connector')
  b=b.replace('Cap-rate math is the owner’s model, not an appraisal.', 'The write-up describes an AI platform plus a 24/7 staffed support team, so the software-only contribution is not isolated. Cap-rate math is the owner’s model, not an appraisal.')
  d['markdown']=b
 for key,edit in [('icp-hotels',hotels),('icp-rentals',rentals),('buyer-roles',roles),('buying-triggers',triggers),('customer-jobs',jobs)]:revise(store,key,edit,'Resolve final audience review: optional urgency, hotel versus rental evidence, named-customer attribution, and conditional connector readiness.')

def final_editorial_pass(store):
 def company(d):
  d['markdown']=d['markdown'].replace('Primary go-to-market motion on the site is “Book demo,” not self-serve checkout.', 'The site prominently uses “Book demo” and “Get Started” calls to action; these captures do not establish an unattended self-serve checkout.')
  d['markdown']=d['markdown'].replace('| Bali / Easy BnB | Exit-oriented PM |','| Easy BnB (story published as Bali Luxury Stays) | Exit-oriented PM; Bali is the founder’s subsequent venture |')
 def messaging(d):
  b=d['markdown'].replace('Cascadia reports absorbing a first property-management acquisition without hiring more guest-service staff.', 'During its first property-management acquisition, Cascadia’s leadership expected to absorb the additional work without more guest-service hires; the story does not establish a completed staffing outcome.')
  b=b.replace('the $4,000-to-$600 headline is not a clean immediate before/after and average response from 57 minutes to 2 minutes. Those are Conduit-attributed outcomes, not a rate card.', 'the $4,000-to-$600 headline is not a clean immediate before/after. Its reported response time fell from 57 to 2 minutes with an AI platform and 24/7 staffed support team; the software-only contribution is not isolated. These stories mix attributed results and expectations, not a rate card or guaranteed outcomes.')
  b=b.replace('[Flex story](https://www.conduit.ai/customers/the-flex), not proof that Conduit beats every competitor on the “Conduit vs.” list.', 'Neither establishes that Conduit beats every competitor. [Flex story](https://www.conduit.ai/customers/the-flex)')
  b=b.replace('Flex, Bali/Easy BnB |','Flex, Easy BnB (Bali Luxury Stays page) |')
  d['markdown']=b
 def alternatives(d):
  if 'The Canary page repeats 50M+' not in d['markdown']:return
  start=d['markdown'].index('The Canary page repeats 50M+')
  end=d['markdown'].index('Do not convert those figures',start)
  d['markdown']=d['markdown'][:start]+'''The Canary comparison adds security language beyond the homepage’s SOC 2 Type II and HIPAA-workflow assertions. Confirm current attestations before repeating its HIPAA/GDPR/ISO certification language. It also claims 95% automation for Haven, while Haven’s own customer story says 90%; keep the conflicting 95% out of campaign proof. [Comparison](https://www.conduit.ai/alternatives/canary-technologies) [Haven story](https://www.conduit.ai/customers/haven-2026) [Homepage](https://www.conduit.ai/) '''+d['markdown'][end:]
  d['open_questions']=[q.replace('Haven 95% across 270 properties, ', '').replace('How are Agents, Inbox, Portals, and Workflows packaged and priced relative to suite or all-in-one PMS alternatives?', 'Which equivalent competitor package and implementation scope should be compared with Conduit’s published bundles for this account?') for q in d['open_questions']]
 for key,edit in [('company-overview',company),('brand-messaging',messaging),('alternatives',alternatives)]:
  revise(store,key,edit,'Cross-document editorial pass: propagate Easy BnB attribution and Cascadia expectation boundaries, clarify security comparisons, and repair prose after source corrections.')
