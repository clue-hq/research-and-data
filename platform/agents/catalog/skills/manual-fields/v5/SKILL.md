---
schema_version: "1"
kind: skill
name: manual-fields
version: v5
summary: "Manual: the registered claim fields by family, with value type, freshness, reuse scope and gate; the families a claims read can be narrowed to."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Fields: the claim registry

161 registered fields in 132 families across 4 namespaces, every one of them active. Every claim is about a registered field, so
this is the vocabulary every fact in the store is written in.

**How to narrow a read.** A claims read takes a `field_prefix`, matched as a plain
string against the start of the field key. Pass a value from the Family column:
`account.resonance` narrows a researched account to that family. Never guess one. The
read carries the families the account actually holds, with a count each, and a prefix
that matches nothing is refused by name and lists them. Registered is not the same as
populated: this chapter says what a field means, and the read says what an account has.

Columns: the family to narrow by; the value shape the field declares; how long a claim
of it stays fresh; whether its claims are tenant-private or a public footprint; the gate
a claim must clear; the industry pack it belongs to; and the signal it is the cheap or
the deep half of. An absent value is `—`. An inactive field is marked, and a claim is
not written for it.

## account

| Field | Family | Type | Freshness | Reuse scope | Gate | Pack | Signal | What it is |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `account.abm_program_maturity` | `account.abm_program_maturity` | object | 90 days | — | — | — | — | Evidence of the company's own ABM program: open ABM roles, named ABM tooling, stated ABM motion. |
| `account.abm_reporting_line` | `account.abm_reporting_line` | json | — | — | — | — | — | Job posting states the ABM role reports to Head of Growth Marketing; useful explicit key for org alignment. |
| `account.aed_partnerships` | `account.aed_partnerships` | json | — | — | — | — | — | Bundle shows a named, ongoing partnership with Aledade (value-based care partner) which is not captured by existing keys. |
| `account.asc_project` | `account.asc_project` | json | — | — | — | — | — | Bundle includes a detailed announcement about breaking ground on an ambulatory surgery center (ASC) with specifics (opening date, suites, equipment) which doesn't fit existing keys. |
| `account.ashc_project` | `account.ashc_project` | json | — | — | — | — | — | claimed on the unregistered key 'account.ashc_project' |
| `account.ats_open_reqs_count` | `account.ats_open_reqs_count` | json | — | — | — | — | — | Bundle context notes ATS has 26 live reqs; an explicit field for ATS live req count is useful (context was provided by caller). |
| `account.claimed_customer_logos` | `account.claimed_customer_logos` | list[str] | 90 days | — | — | — | — | Customer logos the company shows on its own site (proposed by the structuring pass). |
| `account.claimed_outcomes_metrics` | `account.claimed_outcomes_metrics` | object | 90 days | — | — | — | — | Outcome metrics the company claims for customers (proposed by the structuring pass). |
| `account.claimed_partners` | `account.claimed_partners` | json | — | — | — | — | — | Company page and jobs mention integrations and partner-like relationships (Jira, ServiceNow, OpenAI TAC) and strategic investors (Cisco, Amex); no existing key directly captures named partner programs. |
| `account.clinical_research_capacity` | `account.clinical_research_capacity` | json | — | — | — | — | — | Bundle provides details about on-site research facilities, patient chart counts, and recruitment capability that don't fit existing keys. |
| `account.committee_candidate` | `account.committee_candidate` | object | 90 days | — | — | — | — | One buying-committee candidate the account agent confirmed on a non-provider URL: name, title, persona from the ICP persona map, LinkedIn URL, what confirmed the identity. A vacant seat is recorded with vacant_seat=true and no name (R3 creates the contact). |
| `account.crm_relationship_status` | `account.crm_relationship_status` | str | 30 days | — | — | — | — | Client-CRM relationship (already a customer / open opportunity / …); M4.5. |
| `account.employee_roster_sample` | `account.employee_roster_sample` | list[object] | 90 days | — | — | — | — | A provider sample of employees (name, title) used to sketch org shape; never a committee source. |
| `account.gtm_tooling_stack` | `account.gtm_tooling_stack` | object | 90 days | — | — | — | — | CRM, outbound and ABM tools the company demonstrably uses (present) and tools explicitly named as not used (absent). |
| `account.hiring_velocity` | `account.hiring_velocity` | object | 90 days | — | — | — | — | Open roles by department and their ages, from the company's own job board. |
| `account.hiring_velocity_eng` | `account.hiring_velocity_eng` | number | 30 days | — | tier>=3 | — | — | Engineering hiring velocity (signal field; substrate §3 example). |
| `account.icp_fit_verdict` | `account.icp_fit_verdict` | object | 90 days | — | — | — | — | The agent's lenient fit verdict for one ICP hard gate, with the claim ids behind it. Information for the human; never a reason to stop research. Born outreach_safe=false. |
| `account.locations_list` | `account.locations_list` | json | — | — | — | — | — | Bundle provides multiple clinic addresses (Round Rock, Hutto, Leander). A dedicated field for locations would capture each clinic address and phone. |
| `account.media_layer_index` | `account.media_layer_index` | list[object] | 90 days | — | — | — | — | Podcasts and videos found for the account's people: media URL, duration, whether transcribed. |
| `account.media_transcript_quality_warning` | `account.media_transcript_quality_warning` | object | 90 days | — | — | — | — | A recorded defect in a media transcript (model, media, symptom). Born outreach_safe=false; context only. |
| `account.named_customers` | `account.named_customers` | list[str] | 90 days | — | — | — | — | Customers the company itself names publicly (logos, case studies, press). |
| `account.npi_numbers` | `account.npi_numbers` | json | — | — | — | — | — | Multiple NPI records for the organization and individual are present in the bundle and would be useful to store as a dedicated account field. |
| `account.open_requisitions` | `account.open_requisitions` | list[object] | 90 days | — | — | — | — | Open job requisitions read from the company's own ATS board: title, department, publish date, days open, salary band, whether still listed, URL. |
| `account.operational_pain` | `account.operational_pain` | str | 90 days | — | deep-pass | — | — | Synthesized operational pain. |
| `account.owner_background` | `account.owner_background` | json | — | — | — | — | — | Bundle includes personal/professional background of the owner relevant to the account (medical training, ER experience, acquisition date). |
| `account.product_features` | `account.product_features` | json | — | — | — | — | — | Bundle lists named product features (Fill your board automatically, Capture every lead, Clean every booking, Dispatch on autopilot) which don't fit existing keys cleanly. |
| `account.product_packaging` | `account.product_packaging` | object | 90 days | — | — | — | — | How the company packages and names its products (proposed by the structuring pass). |
| `account.proposed_fields` | `account.proposed_fields` | json | — | — | — | — | — | claimed on the unregistered key 'proposed_fields' |
| `account.recent_funding` | `account.recent_funding` | object | 90 days | — | — | — | — | Most recent funding round. |
| `account.reputation_risk` | `account.reputation_risk` | object | 90 days | — | — | — | — | A negative or contested public claim about the company with its status (confirmed, refuted, unresolved). Born outreach_safe=false. |
| `account.resonance.attrition_signal` | `account.resonance` | object | 30 days | — | deep-pass | — | — | Morale / attrition / layoff signal (Doc C §2; tier-4). |
| `account.resonance.buying_culture` | `account.resonance` | object | 90 days | — | deep-pass | — | — | 'What it's like to buy here' — procurement culture (Doc C §2; tier-4). |
| `account.resonance.culture` | `account.resonance` | str | 60 days | — | deep-pass | — | — | Cultural resonance signal (Doc C §2; tier-4, governed). |
| `account.resonance.employee_sentiment` | `account.resonance` | object | 30 days | — | deep-pass | — | — | Aggregate employee sentiment, Glassdoor-style (Doc C §2; tier-4, governed). |
| `account.resonance.eng_blog_tone` | `account.resonance` | object | 60 days | — | deep-pass | — | — | Tone/voice of the company's engineering blog (Doc C §2; tier-4). |
| `account.resonance.public_frustrations` | `account.resonance` | list[object] | 30 days | — | deep-pass | — | — | Publicly aired frustrations about the account (Doc C §2; tier-4). |
| `account.scoring.fit` | `account.scoring` | object | 30 days | tenant_private | — | — | — | Decomposed ICP fit score (Output 1; M6.3). Tenant-private (per-client ICP). |
| `account.scoring.intent` | `account.scoring` | object | 30 days | tenant_private | — | — | — | Decomposed buying-intent score (Output 1; M6.3). Tenant-private (per-client). |
| `account.scoring.tier` | `account.scoring` | object | 30 days | tenant_private | — | — | — | Approved tier assignment + cutoff version (Output 1 tiering; M6.4). Tenant-private (per-client/ICP decision). |
| `account.shared_emr_partner` | `account.shared_emr_partner` | json | — | — | — | — | — | The bundle repeatedly states Prevea shares an electronic medical record with HSHS and uses Epic/MyChart; a specific key for shared EMR/technology partner would capture this. |
| `account.strategic_moves` | `account.strategic_moves` | str | 90 days | — | deep-pass | — | — | Strategic moves / initiatives. |
| `account.summary` | `account.summary` | object | 90 days | tenant_private | faithfulness | — | — | Neutral account prose summary (Lane E E1) — a tier-4 llm_synthesis claim composed from the account's verified claims on research completion; frontend summaryParagraphs. |
| `account.total_funding` | `account.total_funding` | object | 90 days | — | — | — | — | Total funding in USD with explicit estimate semantics. |
| `account.value_narrative` | `account.value_narrative` | object | 90 days | tenant_private | faithfulness | — | — | Per-(account, persona) value narrative — Output 4 (overview §1/§3; substrate §8). A tier-4 llm_synthesis claim-with-provenance; TENANT_PRIVATE (client-tuned). |

## client

| Field | Family | Type | Freshness | Reuse scope | Gate | Pack | Signal | What it is |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `client.buyer_profile` | `client.buyer_profile` | object | 90 days | tenant_private | — | client | — | Likely-buyer persona / segment evidence (open-web) — persona claims only, never invented account entities (discovery doctrine). |
| `client.competitor` | `client.competitor` | object | 90 days | tenant_private | — | client | — | Named competitor / alternative to the client (open-web comparison surfaces) — one claim per competitor, grounded in a record naming the client. |
| `client.customer` | `client.customer` | list | 180 days | tenant_private | — | client | — | Existing-customer references (name/domain) from a customers page or CRM — a LIST, since a customers page yields many; these double as seed accounts for M5.4 lookalike discovery (which reads the list, not a single current_value). |
| `client.delivered_value` | `client.delivered_value` | str | 90 days | tenant_private | — | client | — | What the client's own customers say they bought it for (reviews-as-signal). |
| `client.differentiator` | `client.differentiator` | str | 90 days | tenant_private | — | client | — | What differentiates the client (owned positioning + third-party category). |
| `client.icp_evidence` | `client.icp_evidence` | object | 90 days | tenant_private | — | client | — | Industries / sizes / geos of existing customers (ICP evidence for M5.2). |
| `client.kb_version` | `client.kb_version` | object | — | tenant_private | — | client | — | Client Knowledge Base version marker {version, run_id, ...} (M5.1 ledger). |
| `client.market_reputation` | `client.market_reputation` | str | 90 days | tenant_private | — | client | — | Third-party category standing / reputation (G2 / Capterra / directories). |
| `client.pricing_posture` | `client.pricing_posture` | str | 90 days | tenant_private | — | client | — | Pricing posture / model (pricing page). |
| `client.product` | `client.product` | str | 90 days | tenant_private | — | client | — | Product / offering description (product, docs, pricing pages). |
| `client.product_capability` | `client.product_capability` | object | 90 days | tenant_private | — | client | — | One explicitly stated capability of the selected product. |
| `client.product_catalog` | `client.product_catalog` | list | 90 days | tenant_private | — | client | — | Bounded official portfolio catalog: product name, short description, and aliases. Detailed capabilities, pricing, integrations, competitors, and customer evidence belong to product-scoped knowledge. |
| `client.product_competitor` | `client.product_competitor` | object | 90 days | tenant_private | — | client | — | One grounded competitor or alternative for the selected product. |
| `client.product_customer_evidence` | `client.product_customer_evidence` | object | 90 days | tenant_private | — | client | — | One customer, testimonial, case study, or outcome for the selected product. |
| `client.product_differentiator` | `client.product_differentiator` | str | 90 days | tenant_private | — | client | — | An explicitly stated differentiator for the selected product. |
| `client.product_integration` | `client.product_integration` | object | 90 days | tenant_private | — | client | — | One explicitly supported integration or ecosystem connection. |
| `client.product_overview` | `client.product_overview` | str | 90 days | tenant_private | — | client | — | Selected product overview grounded in its official product surfaces. |
| `client.product_positioning` | `client.product_positioning` | str | 90 days | tenant_private | — | client | — | Product-specific audience, category, and positioning statement. |
| `client.product_pricing` | `client.product_pricing` | object | 90 days | tenant_private | — | client | — | Product-specific pricing posture, plan, or quote-led buying model. |
| `client.product_use_case` | `client.product_use_case` | object | 90 days | tenant_private | — | client | — | One grounded use case or workflow for the selected product. |
| `client.proof_point` | `client.proof_point` | str | 90 days | tenant_private | — | client | — | Case study / testimonial / logo proof point (positioning & proof). |
| `client.value_prop` | `client.value_prop` | str | 90 days | tenant_private | — | client | — | What the client sells and the problem it solves (owned surfaces). |

## contact

| Field | Family | Type | Freshness | Reuse scope | Gate | Pack | Signal | What it is |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `contact.asc_project_participation` | `contact.asc_project_participation` | json | — | — | — | — | — | Multiple sources reference his role and quotes regarding the ambulatory surgery center groundbreaking; a structured field would capture project leadership and timelines. |
| `contact.best_channel` | `contact.best_channel` | json | — | — | — | — | — | Bundle shows active, recent LinkedIn posts and invitations to DM, indicating LinkedIn DMs are the best outreach channel. |
| `contact.board_and_advisory_roles` | `contact.board_and_advisory_roles` | json | — | — | — | — | — | Multiple sources reference Dr. Pritchard participating on community advisory boards (MCW Green Bay community advisory board) and other boards; a structured field for board/advisory roles would capture these relationships. |
| `contact.board_and_committee_roles` | `contact.board_and_committee_roles` | json | — | — | — | — | — | Bundle references service as Secretary/Treasurer for the Wisconsin Allergy Society and committee membership in AAAAI; these don't map cleanly to existing keys. |
| `contact.board_memberships` | `contact.board_memberships` | json | — | — | — | — | — | Sources list multiple board and civic roles (UW Regent, Brewer Company board, AMGA Chair); a structured board membership field would capture these external roles. |
| `contact.board_president_since` | `contact.board_president_since` | json | — | — | — | — | — | Bundle explicitly states he has been board president since 2007; a dedicated structured field would capture tenure. |
| `contact.board_seats` | `contact.board_seats` | json | — | — | — | — | — | Bundle mentions Enrique Salem joined Cogent's Board but no explicit structured field exists to capture board membership; useful to record board composition related to the contact's company. |
| `contact.class` | `contact.class` | str | — | — | committee-gated | — | — | Optional pack/workspace contact-class value (C7.1 / REQ-16 A3). Separate from committee persona; an absent claim means unknown. |
| `contact.co_founder_spouse_note` | `contact.co_founder_spouse_note` | json | — | — | — | — | — | Company site states she is co-founder and married to Dr. Albert Arthur; useful contextual note tying leadership to family ownership. |
| `contact.current_employer_role_variants` | `contact.current_employer_role_variants` | json | — | — | — | — | — | Profile and company pages use slightly different titles (Marketing, Head of Growth, Head of Marketing); capture title variants explicitly. |
| `contact.current_location` | `contact.current_location` | object | 30 days | — | committee-gated | — | — | Provider-returned current professional location/country. |
| `contact.current_title` | `contact.current_title` | str | 30 days | — | committee-gated | — | — | Provider-returned current professional title for an admitted contact. |
| `contact.education` | `contact.education` | json | — | — | — | — | — | The bundle includes multiple education entries (MSN UTA 2017, BSN MTSU 2011); a dedicated education array would capture degrees and years. |
| `contact.facet.alma_mater` | `contact.facet` | list[str] | 75 days | — | committee-gated | — | — | School(s) / university the person attended (Doc C §2). |
| `contact.facet.best_channel` | `contact.facet` | str | 75 days | — | — | — | — | The channel the research judges most likely to reach this person first. |
| `contact.facet.career_history` | `contact.facet` | list[object] | 75 days | — | committee-gated | — | — | Professional history beyond the current title — prior roles (Doc C §2). |
| `contact.facet.causes` | `contact.facet` | list[object] | 60 days | — | committee-gated | — | — | Publicly supported causes — religion/politics-adjacent, so the hint is sensitive by default (Doc D §2). |
| `contact.facet.certifications` | `contact.facet` | list[str] | 75 days | — | — | — | — | Professional certifications the person lists. |
| `contact.facet.communication_style` | `contact.facet` | object | 60 days | — | committee-gated | — | — | Inferred communication style / tone from public activity (Doc C §2). |
| `contact.facet.conference_talk` | `contact.facet` | list[str] | 75 days | — | — | — | — | Conference talks the person gave, title and venue. |
| `contact.facet.education_highschool` | `contact.facet` | str | 75 days | — | — | — | — | High school, when self-published. |
| `contact.facet.excluded_lookalike` | `contact.facet` | object | 75 days | — | — | — | — | A same-name candidate the research rejected and why. Born outreach_safe=false; context only. |
| `contact.facet.hobby` | `contact.facet` | list[str] | 75 days | — | — | — | — | Hobbies the person states publicly themselves. |
| `contact.facet.hooks` | `contact.facet` | list[str] | 75 days | — | — | — | — | Specific, recent, self-published facts usable as outreach hooks, each grounded in a quote. |
| `contact.facet.nickname` | `contact.facet` | str | 75 days | — | committee-gated | — | — | Preferred / known-by name beyond the legal first name (Doc C §2). |
| `contact.facet.openers` | `contact.facet` | list[str] | 75 days | — | — | — | — | Three grounded opening lines the marketer can send, each tied to a hook. |
| `contact.facet.other_roles` | `contact.facet` | list[str] | 75 days | — | — | — | — | Board seats, advisory and side roles the person lists. |
| `contact.facet.preferred_announcement_quote` | `contact.facet` | json | — | — | — | — | — | Multiple LinkedIn posts include first-person announcement language that could serve as a preferred personal quote for outreach openers. |
| `contact.facet.public_appearances` | `contact.facet` | list[object] | 60 days | — | committee-gated | — | — | Podcasts / talks / panels the person appeared in (Doc C §2). |
| `contact.facet.publications` | `contact.facet` | list[object] | 75 days | — | committee-gated | — | — | Articles / papers / books the person authored (Doc C §2). |
| `contact.facet.recent_award` | `contact.facet` | list[str] | 75 days | — | — | — | — | Awards or recognitions the person announced. |
| `contact.facet.recent_post` | `contact.facet` | str | 14 days | — | committee-gated | — | — | Recent public post (personal hook; Doc C §2; governed by M10). |
| `contact.facet.self_summary` | `contact.facet` | str | 75 days | — | — | — | — | The person's own summary of themselves, verbatim or lightly trimmed. |
| `contact.facet.stated_interests` | `contact.facet` | list[str] | 45 days | — | committee-gated | — | — | Publicly stated interests / topics (Doc C §2; an interest tied to a religious/political cause is tagged sensitive per-claim — Doc D §2). |
| `contact.facet.stated_skills` | `contact.facet` | list[str] | 75 days | — | — | — | — | Skills the person lists on their own profile. |
| `contact.facet.voice_quote` | `contact.facet` | object | 75 days | — | — | — | — | A verbatim spoken quote with the media URL and timestamp it came from. |
| `contact.founded_companies` | `contact.founded_companies` | json | — | — | — | — | — | The bundle shows he owns 'Scott R. Coleman CPA PLLC' and other owner roles; a structured founded/owned companies field would capture this history. |
| `contact.founded_company_exit_details` | `contact.founded_company_exit_details` | json | — | — | — | — | — | Bundle contains structured exit information for Digital Shadows (acquirer and value) that doesn't map exactly to existing keys. |
| `contact.founded_company_history` | `contact.founded_company_history` | json | — | — | — | — | — | Bundle contains multiple references to founding Digital Shadows and selling it for $160m; a structured field for prior founded companies and exit details would be useful. |
| `contact.headline` | `contact.headline` | str | 60 days | — | — | — | — | The person's LinkedIn headline as published. |
| `contact.historical_officer_role` | `contact.historical_officer_role` | json | — | — | — | — | — | Bundle notes a historical officer listing (P.A. treasurer) for Karen G. Snow on CorporationWiki which doesn't map to existing keys. |
| `contact.job_function` | `contact.job_function` | str | 30 days | — | committee-gated | — | — | Provider-returned current job function for an admitted contact. |
| `contact.job_level` | `contact.job_level` | str | 30 days | — | committee-gated | — | — | Provider-returned current job level for an admitted contact. |
| `contact.jurisdiction` | `contact.jurisdiction` | object | 180 days | tenant_private | — | — | — | Resolved data-protection regime for a contact (Doc D §1; M10.1). Tenant-private; value carries {regime, region, confidence, derived_from}. |
| `contact.languages` | `contact.languages` | json | — | — | — | — | — | Multiple sources list languages she speaks (English, Hindi, Urdu); a structured languages field would be useful for outreach and patient matching. |
| `contact.license` | `contact.license` | json | — | — | — | — | — | Bundle contains her Texas APRN license number (AP135745) in a provider NPI record; a structured license field would capture licensing details. |
| `contact.licenses` | `contact.licenses` | json | — | — | — | — | — | Bundle includes state license numbers and taxonomy details (TX and NY) that don't map cleanly to existing fields. |
| `contact.locations_operated` | `contact.locations_operated` | json | — | — | — | — | — | Company and press identify multiple clinic locations (Round Rock, Hutto, Leander) relevant for outreach and operations. |
| `contact.member_badges` | `contact.member_badges` | object | 60 days | — | — | — | — | Provider-recorded profile badges (creator, premium, open-to-work). |
| `contact.network_statistics` | `contact.network_statistics` | object | 60 days | — | — | — | — | Follower and connection counts. |
| `contact.organization_relationship` | `contact.organization_relationship` | object | 30 days | — | committee-gated | — | — | Exact-account current-employment relationship with returned or modeled basis. |
| `contact.overview` | `contact.overview` | object | 90 days | tenant_private | faithfulness | — | — | Neutral contact prose overview (Lane E E2) — a tier-4 llm_synthesis claim composed from the contact's eligible claims on research completion; frontend overviewParagraphs. |
| `contact.persona` | `contact.persona` | str | — | — | committee-gated | — | — | Buying-committee persona key for (account, persona) addressing (M8.3). |
| `contact.preferred_announcement_quote` | `contact.preferred_announcement_quote` | json | — | — | — | — | — | Multiple LinkedIn posts include first-person announcement language suitable for outreach openers; a structured preferred announcement quote field would capture this. |
| `contact.preferred_official_title` | `contact.preferred_official_title` | json | — | — | — | — | — | LinkedIn and Prevea site use slightly different phrasings for Samantha's senior HR/risk title; a normalized preferred title would clarify outreach |
| `contact.reports_to` | `contact.reports_to` | object | 90 days | — | — | — | — | The committee member this person reports to (a contact entity id). |
| `contact.role_on_committee` | `contact.role_on_committee` | object | — | — | committee-gated | — | — | Inferred buying-committee role + role-plausibility verdict (Output 3; M8.3). |
| `contact.role_scope` | `contact.role_scope` | json | — | — | — | — | — | Source specifies that his role includes managing value-based care efforts across multiple locations; a separate field for role scope would capture this multi-site responsibility. |
| `contact.role_variants` | `contact.role_variants` | json | — | — | — | — | — | Multiple sources use slightly different titles (Senior Vice President and Chief Medical Information Officer; Chief Medical Information Officer; Allergist). A dedicated field would capture title variants. |
| `contact.source_confirmation_note` | `contact.source_confirmation_note` | json | — | — | — | — | — | Bundle indicates no LinkedIn URL or personal bio was confirmed; a field capturing absence of social profiles would be useful. |
| `contact.started_in_beauty_year` | `contact.started_in_beauty_year` | json | — | — | — | — | — | Bundle gives a specific start year in the beauty industry which is useful as a structured career-timeline field. |
| `contact.team_membership` | `contact.team_membership` | list[object] | 30 days | — | committee-gated | — | — | Provider-modeled organization-team membership with explicit relationship basis. |
| `contact.team_membership_board_seats` | `contact.team_membership_board_seats` | json | — | — | — | — | — | Cogent posts reference company events and hires; tracking board or advisor relationships at Cogent could be useful (bundle mentions Enrique Salem joined Cogent's Board in context notes). |
| `contact.total_experience_years` | `contact.total_experience_years` | json | — | — | — | — | — | LinkedIn lists a total experience summary which is useful as a structured career-duration field. |
| `contact.uscis_designation` | `contact.uscis_designation` | json | — | — | — | — | — | Source lists Dr. Arthur as a USCIS-designated civil surgeon; a dedicated field would capture immigration-medical eligibility. |
| `contact.uses_clinical_software` | `contact.uses_clinical_software` | json | — | — | — | — | — | Bundle notes clinicians at the practice use Aledade Daily Huddle / Aledade App, which is useful to capture as a technology usage field. |
| `contact.uses_technology` | `contact.uses_technology` | json | — | — | — | — | — | Multiple sources reference specific robotic systems (Mako, THINK Surgical TMINI) he uses in practice—a concise field for device usage would be useful. |
| `contact.value_based_care_partnerships` | `contact.value_based_care_partnerships` | json | — | — | — | — | — | Bundle contains specific information about an ongoing partnership with Aledade and use of Aledade tools which doesn't map cleanly to existing keys. |
| `contact.x_url` | `contact.x_url` | str | 180 days | — | — | — | — | The person's X/Twitter profile URL. |

## core

| Field | Family | Type | Freshness | Reuse scope | Gate | Pack | Signal | What it is |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `core.account_name` | `core.account_name` | str | 180 days | — | — | — | — | Evidence-bearing canonical account name observation. |
| `core.annual_revenue` | `core.annual_revenue` | object | 365 days | — | — | — | — | Annual revenue with currency, as-of date, and explicit reported/estimate semantics. |
| `core.claimed_customer_logos` | `core.claimed_customer_logos` | json | — | — | — | — | — | claimed on the unregistered key 'core.claimed_customer_logos' |
| `core.company_about` | `core.company_about` | str | 90 days | — | — | — | — | Provider-sourced public company description/about text. |
| `core.company_crunchbase_url` | `core.company_crunchbase_url` | str | 365 days | — | — | — | — | Crunchbase profile URL. |
| `core.company_email` | `core.company_email` | str | 30 days | — | — | — | — | Public general company contact email; not a person's work email. |
| `core.company_languages` | `core.company_languages` | list[str] | 365 days | — | — | — | — | Languages the company publishes in. |
| `core.company_linkedin_url` | `core.company_linkedin_url` | str | 90 days | — | — | — | — | Canonical public LinkedIn company page URL. |
| `core.company_phone` | `core.company_phone` | str | 30 days | — | — | — | — | Public general company contact phone; not a person's direct number. |
| `core.company_twitter_url` | `core.company_twitter_url` | str | 365 days | — | — | — | — | Company X/Twitter profile URL. |
| `core.company_type` | `core.company_type` | str | 365 days | — | — | — | — | Provider company type label (private, public, non-profit…). |
| `core.direct_phone` | `core.direct_phone` | str | 30 days | tenant_private | selected-contact-channel | — | — | Selected contact's observed direct phone. It remains delivery data and never becomes an identity key. |
| `core.employee_count` | `core.employee_count` | int | 90 days | — | — | — | — | Total headcount. |
| `core.employee_range` | `core.employee_range` | object | 90 days | — | — | — | — | Evidence-backed employee range used only when exact headcount is unavailable. |
| `core.founded_year` | `core.founded_year` | int | 365 days | — | — | — | — | Year the company was founded. |
| `core.hq_location` | `core.hq_location` | object | 180 days | — | — | — | — | Normalized headquarters or primary location plus the source's raw value. |
| `core.industries_all` | `core.industries_all` | list[str] | 180 days | — | — | — | — | Every industry label the provider records, primary first. |
| `core.industry` | `core.industry` | str | 90 days | — | — | — | — | Primary industry classification returned with account evidence. |
| `core.legal_name` | `core.legal_name` | str | 365 days | — | — | — | — | The registered legal entity name. |
| `core.logo_url` | `core.logo_url` | str | 180 days | — | — | — | — | Mark-type company logo image URL (a square symbol: LinkedIn's company mark). |
| `core.primary_domain` | `core.primary_domain` | str | 180 days | — | — | — | — | Primary web domain. |
| `core.primary_tech_stack` | `core.primary_tech_stack` | list[str] | 90 days | — | — | — | — | Detected primary technologies. |
| `core.revenue_band` | `core.revenue_band` | enum:under_1m\|1m_10m\|10m_50m\|50m_100m\|100m_500m\|500m_1b\|1b_plus | 365 days | — | — | — | — | Bounded revenue band used only when exact sourced annual revenue is absent. |
| `core.tech_stack_categorised` | `core.tech_stack_categorised` | list[object] | 90 days | — | — | — | — | Technology stack grouped by category as the provider reports it. |
| `core.total_funding` | `core.total_funding` | json | — | — | — | — | — | claimed on the unregistered key 'core.total_funding' |
| `core.work_email` | `core.work_email` | object | 30 days | tenant_private | selected-contact-channel | — | — | Selected contact's observed work email: the address with the provider's deliverability verdict and the moment it was checked. It is delivery data until independent corroboration, reachability, use permission, and optional identity promotion pass. |

What a claim's tier, verification status, use class and display gate mean is
`.deepagent/skills/manual-claims/v5/SKILL.md`. The read that serves them, and everything it can refuse with, is
`.deepagent/skills/manual-tools/v5/SKILL.md`.

