# ARV4: generalized, parallel research-page narrative

Date: 26 September 2026

Status: **review draft; specification and examples only**. The founder authorized writing this
spec after discussing the mapping. No runtime, catalog, frontend or database changes, model
selection change, paid calls or research launches are authorized by this document alone.

Companions:

- [Exact draft prompts](../../drafts/2026-09-26-parallel-narrative/PROMPTS.md).
- [Review-only r18 input examples](../../drafts/2026-09-26-parallel-narrative/INPUT-EXAMPLES.md).
- [Full offline r18 selection and coverage report](../../../../.artifacts/narrative-selection-20260926/REVIEW.md).
- [Reproducible fixture preparation](../../drafts/2026-09-26-parallel-narrative/prepare_r18_inputs.py).

## 1. Outcome and founder decisions

Turn stored research into readable Account Overview, Account Insights and Contact pages. A
section explains a stable question; its evidence and relevance adapt to the workspace's seller,
selected products, pinned ICP/personas and project assignment. No default assumption that the
relevant team is Marketing, the offering is ABM, or the target is a venture-funded software firm.

1. Generate independent sections concurrently using prepared evidence packets. Proposed unit:
   a structured model call with no tools, not another research Deep Agent.
2. **60 seconds is the upper performance target**, measured from availability of the required
   claim/context snapshot through generation and durable storage. It is not a cancellation
   timeout, publication veto, research-job failure condition or content-suppression rule.
3. A claim and a field can contribute to multiple sections. Reuse references; do not create
   duplicate claims to support different prose.
4. Preserve useful detail and public wording. Explain uncertain, conflicting, historical,
   duplicate and wrong-entity observations honestly; their labels must not hide them from review.
5. Why-they-fit explicitly considers ICP and persona signals, operational pain, current
   strategy and initiatives against the seller's selected capabilities, including contrary evidence.
6. This phase writes presentation only. It neither changes research facts nor purchases more
   research. Research → JSON quality and research-agent efficiency remain separate work.
7. Start with an isolated replay of r18: Zafran Overview + Insights and Nick's Contact page.
   Production integration follows review of selection, output quality, latency and cost.

Existing workspace/tenant authorization, erasure and secret handling still apply. A visibility
ruling does not grant cross-workspace access. Older PoC hiding rules and relationship-proof
requirements are not reintroduced through this spec.

## 2. Verified baseline and reference limitations

### Current platform

- Resource revision 19 retains narrative prompt v15 and `record_research_finding@3` alongside
  evidence search and page publication. It is a tool-bearing specialist, not a section leaf call.
- Account/person researchers author JSON dossiers and import each entry into
  `account.research_finding` or `contact.research_finding`. Typed enrichment, jobs and committee
  mappings also populate specific fields. The importer does not classify rich findings into
  industry-pack fields. `Finding` currently has neither category IDs nor a semantic-field reference.
- r18 retained 481 claims: 341 imported entries, 56 further research-finding writes and 84 other
  claims. Narrative had 65 model calls costing $4.600252. Four page pointers persisted, but all
  six jobs ended `needs_review`; three narrative-child failures and finalization problems remain.
- `quality_pages.py` stores cited structured sections as `display_block` records and page-current
  pointers. Its advisory read path appends an all-findings section. This is reusable infrastructure,
  not proof that the proposed section keys or output extensions render in the current UI.
- Legacy `display/render.py` flattens and clips values at 1,200 characters. Do not reuse that
  transformation for rich dossier findings in this trial.
- Workspace field registration exists. The human settings path requires human authority;
  `register_agent_research_field` creates tenant-local proposed account/contact vocabulary with
  a neutral placeholder description. A richer agent description must not silently bypass this
  distinction. Current research profiles do not expose a dedicated catalog-registration tool.

Source pointers:

- [Narrative profile](../../../../platform/agents/catalog/research-quality/profiles/quality-research-narrative/v19/profile.yaml)
- [Current narrative prompt](../../../../platform/agents/catalog/research-quality/prompts/quality-research-narrative/v15/SYSTEM.md)
- [Dossier importer](../../../../platform/api/clue_api/arv2/dossier_import.py)
- [Finding contract](../../../../platform/api/clue_api/arv2/dossier_findings.py)
- [Page storage/read](../../../../platform/api/clue_api/arv2/quality_pages.py)
- [Registry](../../../../subsystems/research/clue_research/claimstore/registry.py)
- [r18 report](../../../../.artifacts/arv4-clue-zafran-20260926-r18/REPORT.md)
- [r18 follow-up audit](../../../../.artifacts/arv4-clue-zafran-20260926-r18/FOLLOWUP-AUDIT.md)

### PoC inspiration, not a literal template

Read together: [final research report](../../../../.context/arv2-one-account-aiark/ONE-ACCOUNT-REPORT.md),
[claim bundle](../../../../.context/arv2-one-account-aiark/claims_zafran.json),
[frontend methodology](../../../../.context/frontend-page-content/README.md),
[page examples](../../../../.context/frontend-page-content/ZAFRAN-PAGES.md),
[frontend spec](../../../../.context/frontend-page-content/FRONTEND-SPEC-ZAFRAN.md) and
[Vari example](../../../../.context/frontend-page-content/VARI-KAUR-CONTACT-PAGE.md).

Keep: distinct overview/insight/person questions, source-backed public statements, multiple
providers contributing evidence, parallel per-section writing, direct lookup rails, claim-based
citations and independently refreshable sections.

Correct: absence of a named vendor is not absence of a platform; a vacancy does not prove the
work is undone; a department label does not establish a reporting line or procurement authority;
startup-joining criteria are not automatically vendor-buying criteria. Seller integrations must
come from seller documents, not target tooling. A retrieved date is not verification of truth.
Historical PoC timings/model prices are reference measurements, not present performance promises.

## 3. Ownership and scope

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Researcher and dossier importer | Preserve findings, attribution, sources, interpretations, review links | Depend on narrative to finish extraction |
| Packet assembler | Snapshot scope, resolve categories/fields, join context and linked qualifications, track coverage | Invent relevance or truncate evidence silently |
| Section model call | Write one section from supplied evidence; label implications and advice | Browse, register fields, write claims, change review judgments |
| Narrative worker | Concurrent scheduling, per-section recovery, storage, telemetry | Treat 60 seconds as a research failure or restart research |
| Page projection/frontend | Order sections; render references, states and direct fields | Hide findings solely because of uncertain/invalid labels |

This matches Doc A's deterministic-worker-with-model-leaves vocabulary. The trial has no
Deep Agent, delegation loop or claim specialist. The existing governed model gateway and
observability are retained. No external workflow service or separate research pipeline.

Trial scope: saved inputs, local routing overlay, calls after explicit live-trial authorization,
isolated outputs and review. Not in this step: production field migrations/tools, changes to
research prompts, default model changes, UI implementation, historical claim repairs, full
account/person reconciliation, campaign sending or artifact generation.

## 4. Evidence classification and routing

### 4.1 Distinguish the dimensions

- **Subject:** entity the claim belongs to, and explicit related person/account where available.
- **Field:** registered attribute, e.g. `core.employee_count`.
- **Claim type:** observation or reported statement. Interpretation remains separate.
- **Categories:** multiple semantic retrieval tags, independent of UI layout.
- **Attribution/context:** speaker, employer/time, described organization, source type and dates.
- **Review:** supported, duplicate, wrong_entity, insufficient_context, potential_conflict and links.
- **Destination:** sections selected by a versioned recipe; never the claim's sole home.

Proposed reusable category IDs:

| Group | IDs |
| --- | --- |
| Company | `company_identity`, `offering`, `business_model`, `operating_model`, `market_context`, `published_outcomes` |
| Needs/change | `operational_needs`, `strategic_priorities`, `initiatives`, `hiring`, `organization`, `leadership_change`, `expansion`, `purchasing_requirements`, `explicit_buying_intent` |
| Resources | `funding`, `financial_performance`, `scale`, `technology`, `workflows`, `integrations` |
| People | `responsibilities`, `committee_rationale`, `career`, `education`, `certifications`, `public_statements`, `working_methods`, `evaluation_preferences`, `public_interests`, `personal_projects` |
| Context | `reputation`, `conflicting_evidence`, `historical_context` |

Tags are multi-valued, not a priority ranking or evidence of fit. `public_statements` describes
form; topic tags such as `technology` describe substance. A company press release is not a
personal statement unless an identifiable speaker is attributed. Research gaps are separately
supplied notes, never promoted into positive claims by category assignment.

### 4.2 Selection algorithm for the trial

1. Freeze an authorized r18 claim snapshot and the original pinned seller/product/ICP/persona
   documents. Record their hashes, source run, entities and snapshot cutoff. Read historical
   r18 exports; do not repin or mutate the historical run.
2. Inventory all 481 records. Mark 341 dossier imports, the 56 later finding writes and the 84
   other records so coverage cannot accidentally exclude a whole origin group.
3. Create an explicit reviewable overlay keyed by real claim ID. Existing field mappings seed
   categories; inspect free-form dossier sections/topics and findings to assign remaining tags.
   Section labels alone are insufficient. No production classifier or hidden LLM routing call.
4. Select the subject envelope: account sections use account evidence and linked selected-person
   evidence; a contact section uses that person plus relevant account evidence. Other people
   enter only through an explicit relevant relationship, not indiscriminately.
5. Apply the section recipe's field/category union. Include useful context and contrary evidence;
   do not filter by whether the claim favors the seller. Categories select candidates; the
   writer reasons about relevance from the full selected seller context.
6. Attach duplicate/conflict/supersession companions when authorized. Missing companions produce
   an explicit note. Reuse the same claim ID across sections. Never collapse distinct speakers,
   dated statements, initiatives or complementary details merely because words overlap.
7. Record for every input claim its destinations and selection reason, or its disposition:
   direct field, complete-findings-only, outside this subject's scope, or unavailable under the
   existing storage/access contract. Unmapped findings appear in the coverage review and complete
   findings view; they are not silently dropped.
8. Each section stores the exact packet and recipe/prompt versions before calling the model.

Human review of the overlay is the first trial checkpoint. Manual routing is explicitly a trial
input, not proof that future automatic categorization works.

### 4.3 Later researcher integration

After the trial: show researchers applicable global, pack and workspace fields progressively;
teach existing-field reuse, neutral field definitions, multi-category classification and semantic
relationships. Extend the versioned dossier/import contract deliberately; preserve existing
finding text and import idempotency. Retain a generic finding when a narrower field is unavailable.
Do not copy prose into an incompatible typed field to make a recipe match.

Workspace field proposals must use the existing scoped registry seam, preserve human/agent
authority distinctions, handle simultaneous identical proposals idempotently, reject cross-tenant
reuse, and avoid global registration. A full vertical pack is not created for each account.
Proposal descriptions remain distinct from approved field meaning and from evidence. Exact new
schema, agent tool, category storage and field projection rules require a separate integration
design and migration review; this spec does not invent those as already-supported capabilities.

## 5. Section contracts

Names below are proposed user-facing labels. Existing keys are reused where meaning still fits;
new keys and changed meanings require frontend contract review before integration. Fields are
examples, not exhaustive allowlists: categorized generic findings and workspace fields also enter.

### 5.1 Account Overview

| Key / label | Purpose | Candidate evidence | Required distinction |
| --- | --- | --- | --- |
| `what-they-do` / What they do | Explain the target business and operations | Company identity, offering, business/operating model, published outcomes; `core.company_about`, industry, headcount, HQ, founded year | Target description vs seller proposition; reported outcomes vs proven outcomes |
| `why-they-fit` / Why they fit | Relate ICP/persona signals, pain, strategy and initiatives to selected products | Needs, priorities, responsibilities, requirements, relevant scale/geography/technology and contrary evidence; operational pain/strategic moves/workspace fields | Observed fact → selected seller capability → qualified relevance; no invented overall score |
| `why-now` / Why now | Explain timely reasons to engage | Dated initiatives, hiring, expansion, leadership, financing and explicit intent | Event timing vs actual buying timeline; old context stays labeled |
| `buying-committee` / Relevant people and buying committee | Explain responsibility and potential influence | Committee selection, titles, functions, observed remit, statements and ownership | Source-reported role vs hypothesized deal role; no hierarchy inference from department alone |
| `how-to-approach` / How to approach | Ground conversation themes and demonstrations | Relevant needs/initiatives, working methods, public wording, seller capabilities | Advice vs fact; no unprovided integration or delivery promises |
| `research-notes` / Qualifications and open questions | Explain limitations and disputed observations | Review companions, reputation, historical records, unresolved research notes | A research gap is not evidence of absence; disputed observations stay visible |

### 5.2 Account Insights

| Key / label | Purpose | Candidate evidence | Required distinction |
| --- | --- | --- | --- |
| `buying-signals` / Operational needs and buying signals | Expose concrete needs and changes | Pain, frustrations, hiring mandates, constraints, purchasing requirements, explicit intent | Observed issue vs potential buying signal; strengths need not become problems |
| `strategy-and-initiatives` / Strategy and initiatives | Explain objectives and active programs | Strategy, launches, expansion, partnerships and transformation, named owners | Stated objective vs accomplished outcome |
| `organization-and-teams` / Organization and relevant teams | Describe the affected function | Hiring, org structure, responsibilities, leadership and contractor involvement | Relevant function comes from seller/personas, never a fixed GTM assumption |
| `tools-they-already-use` / Systems, tools and workflows | Describe systems and how work happens | Technology/workflows/integrations; primary tech stack, applicable specialized tooling fields, attributed mentions | Current target use vs job requirement, earlier employer or target customer's tool |
| `money-and-momentum` / Financial and organizational momentum | Explain resources and scale | Funding, financial performance, growth, headcount, facility expansion | Provider estimate vs company statement; revenue vs ARR vs funding; no inferred allocated budget |
| `contact-insights` / People and public statements | Retain useful voices and perspectives | Voice quotes, recent posts, publications, talks, working methods and responsibilities | Author vs quoted third party; preserve distinctive wording and attribution |
| `business-context` / Business and operating context | Add useful contextual detail | Offering, operating model, ecosystem, market context, outcomes, named customers when relevant | No mandatory customer-of-customer investigation; do not promote broad context to buyer pain |

The former `how-they-sell` and `context-only` recipes are not silently renamed in code. Their
content maps respectively to business context/strategy and visible qualifications as appropriate.
Insights keeps qualifications beside each finding; the complete findings section remains available.

### 5.3 Contact

| Key / label | Purpose and evidence |
| --- | --- |
| `why-this-person` / Why this person | Role, observed remit, relevant career, initiative ownership and committee rationale, compared with pinned personas. Title is not spending authority. |
| `problem-right-now` / Current priorities and challenges | Their statements plus relevant account needs, workflows and initiatives. Do not attribute every account issue to them. |
| `experience-and-perspective` / Experience and perspective | Career, education, certifications, publications, voice, self-disclosed projects/interests. No invented personality or vendor preferences. |
| `openers` / Conversation openers | Specific sourced hooks and optional proposed lines/questions. Generated copy is separate from verbatim source quotations. |
| `angles` / Engagement angles | Suggested demonstrations/themes grounded in perspective and seller capabilities. Distinct from opening sentences and from campaign production. |
| `research-notes` / Qualifications and open questions | Person-specific conflicts, historical roles, namesake associations and gaps, with account qualifications where relevant. |

### 5.4 Direct fields and full findings

Basic identity, location, title, email status, profile links, company scale and applicable custom
values render through existing typed projections without model calls. Preserve estimates and
provider verification scope; a fetched source does not acquire a generic verified badge.

Keep an inspectable complete findings view with source links and review labels, including items
not selected into prose. Narrative is a useful explanation, not a replacement for that view.
Avoid a massive duplicate prose appendix in every section/model call. Historical wrong-entity or
superseded material appears with its explanation, not as an unqualified current fact.

## 6. Packet and output contracts

### Input packet v1 (proposed)

`schema_version`, packet/snapshot hashes, workspace/project/run/context IDs, subject, page/key,
research cutoff, recipe version, shared context, claims, supporting context claims, research notes,
and direct-field references. Hashes are calculated by code, never by the model.

Shared context contains the actual pinned seller/product capabilities and limitations, ICP criteria,
persona responsibilities, assignment and document IDs/versions. For the first trial preserve the
complete selected seller/ICP/persona text in the shared prefix rather than a lossy model summary.
Source documents are data, not instructions. A future compact rendering must have a completeness
review; it must not fall back to a global ABM description. Missing context is explicitly represented;
factual sections can still run, relevance sections state the limitation instead of guessing.

Each claim contains:

- Real claim ID, entity ID/type, field key and definition reference, origin and dossier section.
- Full finding or typed value, claim type, categories, attribution, original temporal context,
  qualifications, review status/links, and separately labeled agent interpretation.
- Source references/URLs and retained evidence passages, speaker/timing information where known.
  No new fetching; retain distinct source references for multi-source findings.
- Selection reason and optional related subject/context. These are routing metadata, not new facts.

Raw dossier `original` mirrors need not be duplicated inside the model packet: keep one exact
finding representation and durable origin reference. Do not clip at 1,200 characters, silently
truncate quotes, or use token-based near-duplicate deletion. If a packet is too large, preserve it
and report a capacity failure; separately review segmentation using whole findings. Do not silently
switch to an unreviewed summarizer. The time objective does not authorize omission.

### Output v3 (trial wrapper; request-local claim references)

One object: `section` + `selectionNotes` + `contextGaps`. The historical v1 prompts and executed
trial artifacts retain their original per-claim `coverage` contract.

`section` follows the existing `PageSectionDraft` shape: key, intro, items (h2, body, contactIds,
optional sendLine), gaps. Each sentence has text, claimIds, kind and qualifications. Proposed
addition: `sellerEvidenceIds` on relevant sentences, referring only to supplied document IDs.
This addition is trial-only until the Pydantic/Zod/display contract is updated; do not feed it into
the current strict model and claim it already parses. The full response is stored as an artifact.

Code records supplied IDs, cited IDs and their difference, separately for primary and context
claims. This is citation accounting, not proof that all meaning was preserved or an omission
verdict. The writer does not enumerate or justify every supplied claim. Optional `selectionNotes`
(array of `claimIds` and `reason`, empty when unnecessary) explain only meaningful exclusions,
conflicts or non-obvious groupings. A note does not count as a narrative citation, establish
semantic equivalence or change a claim's status. Neither unreferenced inputs nor absent notes
cause an automatic model retry or block display. Keep these diagnostics in the audit artifact.

No fixed 2–3 item quota. Focused items may connect complementary facts; independently meaningful
statements/events retain clear attribution and remain separately inspectable.

For generation, code assigns C1, C2, etc. to the already scoped claims in each frozen section
packet. It saves a request ID, canonical packet hash and alias-to-UUID map; the model sees only
local claim references in citation fields and structured duplicate/conflict/supersession links.
Finding text, attribution and qualifications are unchanged. The exact packet's aliases constrain
the reference schema from the first call. Seller-document and contact IDs are unchanged.

Validate returned aliases against that request, then resolve sentence and selection-note references
to durable UUIDs before storing or rendering the section. Mapping checks precede paid execution;
no global alias lookup, approximate ID matching or source refetching. Retries reuse the saved map.
A new prepared request has its own identity/map, even if some aliases repeat. Retain raw model
responses, the original packet and map for audit. These temporary aliases grant no data access
and are not frontend labels. The v1/v2 prompts and paid artifacts remain historical references.

Citations reference claims and seller documents; the backend resolves display links. Do not let
the model generate/retarget URLs. Missing sources are visibly qualified; no new requirement that
every recommendation have a factual proof. Proposed advice cites its basis and is labeled inference.

Structural checks: parseable JSON, expected section key, valid packet references, authorized
contact/document references and schema shape. Quote/coverage/meaning checks are review diagnostics,
not new hard gates for uncertain findings. Malformed output cannot masquerade as published prose:
retry only the affected section and retain a recoverable failure state plus the underlying findings.

## 7. Parallel execution, persistence and freshness

### Trial

Prepare packets before paid authorization. Initial experiment uses the configured narrative
model (`RESEARCH_NARRATIVE_AGENT_MODEL`, currently Grok 4.6), not an unapproved model change.
Use structured output through the existing gateway where supported; otherwise strict JSON parsing
with explicit repair feedback. No assumption that JSON mode alone guarantees evidence quality.

Run all nonempty sections within a subject page-set concurrently under a shared concurrency
limit, initially at most eight in-flight calls for the isolated three-page trial. This is a
reviewable experiment parameter, not a new production env flag. Empty sections return an honest
empty-state payload without a paid call. One immediate structural retry per failed section is the
initial trial policy; exhausted retries remain recoverable and do not repeat research. Do not
cancel valid in-flight calls at the 60-second mark.

Save successful sections independently. No second model merge/judge in the page critical path.
Code orders sections and adds direct fields/findings. A malformed sibling does not roll back saved
sections. Trace every attempt, including retries and failures. Partial output is labeled partial.

### Later platform integration

Use the existing fleet/job and display-block substrate. Replace the narrative responsibilities of
the current specialist for newly pinned runs; do not run both owners or rewrite old resources.
Publish idempotently per `(workspace, project, context, subject, page, section, input_digest,
recipe_version, prompt_version, model_config)`. This is a proposed key contract, not a new table
mandate. Atomic pointer updates must reject obsolete generation writes without blocking newer ones.

Section freshness depends on **all selected inputs and recipe selection**, not merely cited IDs:
a new relevant claim, previously omitted claim correction, seller/product/ICP/persona change or
category change can alter the section. Do not invalidate unrelated sections indiscriminately.
Preserve prior text/history and label stale/refreshing appropriately; never display stale content
as freshly complete. Read-triggered refresh must deduplicate with existing scheduled work.

Account pages can publish from account-ready evidence while person research continues. Mark
person-dependent sections as awaiting further findings, then refresh affected sections when each
person import becomes durable. No all-person barrier before account prose and no account-narrative
barrier before person research. This is display refresh, not a redesign of claim reconciliation.
Narrative failures must not undo claim import or turn completed research acquisition into failed
research. Carry distinct research/import/display status; integrate only after existing finalization
and child-error reporting gaps are understood.

## 8. Latency, cost and observability

Two clocks: page-set latency from input readiness (including queue/preparation/retries/storage),
and per-section model latency. Record time to first section, last required section, partial failure,
queue time, input preparation, provider time, persistence and full page-set readiness. Do not claim
success by timing only the fastest section or precomputing packets outside the measured interval.

Acceptance target: each tested ready page-set completes within 60 seconds. Above 60 seconds emits
a target-miss event and keeps running. It is not a timeout or gate. Existing unrelated provider
transport timeouts remain; report them separately. Retry/pending/error UI must be truthful.

Use existing `clue_obs`/model-gateway/OpenRouter and Langfuse composition, not a second tracing
client. Parent narrative job → packet-preparation → parallel section attempts → storage spans.
Include workspace/project/run/job/subject/context, recipe/prompt/model versions, packet hash,
claim counts, elapsed time, retry reason, tokens/cache, known cost and outcome. Record provider
request/generation IDs when supplied. Correlate persistence failures after paid success so recovery
reuses the saved response rather than buying it again. There are no agent tool calls in the trial;
governed tools used by later integration retain existing tool observations.

Content follows existing permitted trace/artifact policy; ordinary logs carry IDs and counts, not
full personal dossiers. Verify concurrent span parentage and distinguish local capture from cloud
export. Unknown cost stays unknown. Compare against r18's $4.60/65-call narrative baseline without
claiming an equivalent corpus or a guaranteed saving.

## 9. Trial deliverables and review

1. Snapshot manifest: all source export hashes, original context, selected entities and origin counts.
2. Full routing overlay and per-claim coverage table, reviewed before calling a model.
3. Exact prompts and rendered packets with hashes, model settings and concurrency/retry parameters.
4. Per-section raw response, parsed output, timing/cost/trace receipt and local rendered Markdown.
5. Comparison: claim/source passage → section prose/citation; record omission, compression,
   unsupported addition, attribution drift, repetition and unresolved qualification.
6. Separate import/packet fidelity, narrative quality, UI readiness and performance conclusions.

Examples in the companion are small faithful slices for review. The separately prepared offline
selection contains all 19 section packets and a disposition for each of the 481 claims, with full
original values and pinned context documents. It is not a rendered live request or generated prose.
The founder reviews the actual selection and prose; passing schema checks is insufficient for promotion.

### Offline selection checkpoint, 26 September

336 distinct claims enter candidate section packets; 24 remain direct fields and 121 remain in
complete findings outside the three selected pages. All 481 have explicit mapping annotations;
none is currently unmapped. 321 claims serve more than one section. These numbers describe the
reviewable fixture overlay, not a production classifier or a completeness/accuracy verdict.
All three selected document bodies match their original pinned SHA-256 hashes. Original claim
values and evidence spans match the retained snapshot exactly; linked review references resolve
inside that snapshot. No historical claim was edited or reclassified in the database.

The first pass is intentionally broad and exposes an unresolved selection-efficiency question:
why-they-fit has 235 primary records plus four companions. The JSON also retains repeated original
entry metadata. Do not send these audit packets uncritically or assert the 60-second target is
already feasible. Before a model trial, review semantic relevance, construct a lossless model view
without repeated structural copies, and measure token counts. Any narrower selection must retain
an explicit per-claim disposition and complete-findings access; it must not silently drop evidence.

Acceptance cases:

| ID | Evidence / scenario | Expected result |
| --- | --- | --- |
| N01 | Exact seller and project-variant context | No global ABM substitution; selected-product limits preserved |
| N02 | Same hiring finding in several sections | One stored claim, distinct uses with identical provenance |
| N03 | Nick's mixed original/quoted-third-party post | Own statement and relayed practices remain distinguishable |
| N04 | Job mentions HubSpot; seller integration unspecified | Describe target workflow; do not promise an integration |
| N05 | Vendor absent from inspected pages | Say not established, not no installed platform |
| N06 | Vacancy and department label | No invented work abandonment, manager or procurement authority |
| N07 | Funding estimate, ARR, operational metrics | Preserve metric meaning, dates, units and attribution |
| N08 | Conflict, duplicate, wrong-entity, superseded record | Visible context; no unsupported current-fact assertion or automatic hiding |
| N09 | Source-only public statement stored outside narrow field | Categories route it; useful wording survives |
| N10 | Claim with no category or field mapping | Accounted for in review/complete findings; no silent discard |
| N11 | One malformed response / storage failure | Sibling sections survive; only failed work retries; no research relaunch |
| N12 | New relevant claim or context after first synthesis | Refresh affected sections even if new input was not previously cited |
| N13 | Cross-workspace/person reference | Not injected into packet or citations; report routing defect |
| N14 | Concurrent page sets and >60s completion | Correct traces; target miss reported; no timer-based pipeline blocker |
| N15 | No supporting claims | Honest empty state; no filler or paid call |
| N16 | Unmapped workspace field and concurrent registration | Existing scoped seam retained; no global vocabulary pollution |
| N17 | Insight Health/Premier dry packet contrast | Clinical workflow/persona categories work without GTM assumptions |

N17 is first a read-only packet review using available retained context; it does not authorize an
additional live model run. Historical healthcare evidence is not silently presented as current.

## 10. Integration boundaries and sequence

1. Review this spec, exact prompts, output shape, model choice and sample selection.
2. Implement isolated packet assembly and narrative replay only; perform meaningful offline checks
   of exact payload preservation, routing, references, parallel/error behavior and observability.
3. Obtain live-trial authorization for the actual rendered inputs; run three pages, assess and iterate.
4. Once accepted, separately design researcher categories/field references and proposal tools;
   immutable resource revisions and reversible migrations follow repository conventions.
5. Reconcile frontend contract changes with the founder: new/renamed section keys, sentence seller
   references, review labels, partial/refresh status and complete findings. Update Pydantic/Zod,
   repositories and `apps/frontend/docs/api-contracts/accounts.md` together. No transport in TSX.
6. Integrate one narrative owner, durable per-section retries/refresh, and honestly separate research
   from display completion. Test frontend display and source-chip resolution with saved data before
   deciding whether another end-to-end paid research run is useful.

Review decisions still open: final UI labels/key compatibility; model after comparison (retain
current config initially); inline vs expandable detail presentation; exact durable category/field
schema and authority for richer agent-proposed field meanings. None prevents the isolated trial.

Binding architecture references: [Doc A](../../../architecture/clue-hq-platform-agent-runtime.md),
[shared seams](../../../specs/_conventions.md), and the existing
[frontend contract](../../../../apps/frontend/docs/api-contracts/accounts.md). This focused spec
supersedes no runtime behavior until implemented and explicitly activated.

## 11. Isolated execution checkpoint — 2026-09-26

Founder authorized `openai/gpt-6-luna` for the local r18 three-page trial. The isolated runner is
`scripts/trial_parallel_narrative.py`; exact inputs, outputs and the review are retained at
`.artifacts/parallel-narrative-trial-20260926/REVIEW.md`.

All 19 sections passed structural/reference validation after six targeted recovery calls (32
calls total). Provider-reported BYOK upstream inference cost was $0.47973107. Initial generation
took 368.09 seconds; recovery took another 129.59 seconds. The 60-second target was missed.
Reference-enumeration recovery helped, but excessive length/repetition and incomplete coverage
ledgers remain. This is an isolated trial result, not production integration or content acceptance.

Prompt refinement after review: draft v4 sharpens each section's writing purpose and includes
one explicitly fictional bad/better example. Evidence may recur across sections, but each section
should develop its own question; overview synthesis and detailed insights retain distinct emphasis.
Public wording and meaningful qualifications remain intact. This is instruction guidance for parallel
writers, not a new sequential reviewer, word cap or output gate. The JSON contract remains v3.

Follow-up trial, largest four account + four person inputs: prompt v4, ledger-free output and
request-local references completed all eight first-attempt calls in 51.375 seconds with no repairs.
Provider-reported upstream inference cost: $0.117255525. Original claim packets unchanged.
See `.artifacts/parallel-narrative-trial-20260926/run-02-largest-eight/REVIEW.md` for section timings,
readable outputs and remaining selection/wording issues. This validates the isolated subset's
latency, not full 19-section or production pipeline performance; content acceptance remains open.

Current instruction ruling after the eight-section trial: the founder requested reverting the
last section-focus refinement. `PROMPTS.md` is restored byte-for-byte to draft v3, retaining
ledger removal and request-local claim aliases. Draft v4 (including its teaching example) is
preserved in `PROMPTS-v4.md` only as historical evidence; it is not the active prompt for fresh
preparation. Existing prepared/paid v4 artifacts stay frozen. A future trial must prepare fresh
inputs from the restored prompt rather than reuse the earlier v4 preview. No rerun is implied by
this rollback, and no single cause of the observed selection differences has been established.
