# FI — Comprehensive account, buying-committee, and contact research contract

**Status:** founder-ratified scope contract; implementation pending

**Date:** 2026-08-18

**Applies to:** the frontend-integration product path on `platform/integration-onboarding-pilot`

**Purpose:** record the required product behavior, deliberate deferrals, provider ownership, current blockers, implementation slices, and browser acceptance evidence before further account/contact research work begins.

This document is the source of truth for the next account, buying-committee, and contact-research integration work. It supersedes earlier audit recommendations wherever they conflict with the decisions recorded here. In particular, this contract does **not** authorize a broad new source waterfall, a new adaptive gap planner, provider-fallback work, or additional coverage/confidence UI.

## 0. Authority and contract deltas

- The earlier account/contact gap inventory remains useful evidence about current code, but its recommendation for a broad adaptive waterfall is superseded by this contract.
- The current M8D contact-research acceptance contract requires an exact selected-contact set. That integrity rule remains: an account-tagged request is resolved server-side into the account's exact current committee and frozen as an immutable set before launch. The user no longer needs to click every committee member individually.
- Existing default-off acquisition flags describe the current implementation, not the target integration behavior. Section 9 records the new product-path activation decision.
- The three-field account run remains valid as historical acceptance evidence only. It is not the normal definition of comprehensive account research.
- The existing frontend design remains in place. This contract adds truthful data, launch reachability, and live progress; it does not authorize a visual redesign or additional coverage diagnostics.

## 1. Product outcome

From one project conversation, a user must be able to:

1. Run comprehensive research for one or more discovered accounts.
2. Receive the complete fixed 21-field account profile wherever the permitted providers can produce supported evidence.
3. Watch truthful account-by-account progress update after the initiating chat turn has closed.
4. Discover and identity-resolve an account's buying committee through Sumble Teams/People.
5. Have the existing account agent infer each candidate's committee role from the project's existing context and evidence.
6. Select contacts directly **or** tag an account and ask to research that account's buying committee.
7. Run structured professional enrichment through Sumble and public professional deep research through Exa Deep.
8. Watch truthful contact-by-contact and channel-lookup progress.
9. See the resulting account and contact information through the C7 research views and production handoff surfaces.

No part of this flow should require the user to understand provider names, manually select every committee member, provide a LinkedIn URL, or repeatedly ask whether detached work has finished.

## 2. Ratified provider boundary

### 2.1 Providers used now

The current implementation must use only the provider capabilities already integrated into this product path:

- Existing Exa Websets discovery claims, reused without buying the same facts again.
- Exa Deep for grounded qualitative account research and public professional contact research.
- Sumble Organizations for structured organization facts and organization matching.
- Sumble Jobs for hiring and job-derived organization signals.
- Sumble Tech Stack for technology-stack facts.
- Sumble Teams/People for buying-committee discovery, person identity, and structured professional contact enrichment.

The small provider set must **not** be used as a reason to narrow the account profile to three fields or the contact profile to a small acceptance-test subset. Field breadth and provider breadth are separate decisions.

### 2.2 Deliberately deferred providers and orchestration

The following are out of scope for this integration checkpoint:

- Firecrawl and Scrapling research composition.
- Official-site research as a separate step.
- Registries, CRM, Apollo, ZoomInfo, BuiltWith, or other provider families.
- A structured-source → official-site → third-party → Exa fallback waterfall.
- An additional committee-discovery fallback after Sumble.
- A new broad, model-driven planner that dynamically chooses every missing or stale field.

Comprehensive research in this contract therefore means **the fixed profile contracts below, executed through the permitted existing providers**. It does not mean every possible provider or an open-ended search of every registered field.

## 3. Comprehensive account research

### 3.1 The fixed 21-field profile

Every comprehensive account-research request targets the existing `PROSE_ACCOUNT_FIELDS` contract in `subsystems/research/clue_research/narrative/prose.py`. No normal full-profile request may silently reduce this to only `account.strategic_moves`, `account.operational_pain`, and `account.resonance.public_frustrations`.

| # | Field | Required acquisition behavior |
|---:|---|---|
| 1 | `core.account_name` | Reuse canonical identity/discovery truth. |
| 2 | `core.industry` | Reuse Exa Websets discovery truth; otherwise use a supported Exa Deep or Sumble organization action. |
| 3 | `core.company_about` | Reuse discovery truth; otherwise use Exa Deep or Sumble Organizations. |
| 4 | `core.employee_count` | Reuse discovery truth; otherwise use Sumble Organizations when available. |
| 5 | `core.employee_range` | Reuse or derive from governed employee-count evidence. |
| 6 | `core.hq_location` | Reuse discovery truth; otherwise use Sumble Organizations. |
| 7 | `core.annual_revenue` | Reuse discovery truth; otherwise attempt through the supported existing provider mapping. |
| 8 | `core.revenue_band` | Reuse or derive from governed revenue evidence. |
| 9 | `core.primary_tech_stack` | Acquire through Sumble Tech Stack. |
| 10 | `core.company_linkedin_url` | Reuse discovery truth or Sumble organization identity data. |
| 11 | `account.total_funding` | Use Sumble Organizations or Exa Deep where the existing manifest supports it. |
| 12 | `account.recent_funding` | Use Sumble Organizations or grounded Exa Deep research. |
| 13 | `account.hiring_velocity_eng` | Use Sumble Jobs. |
| 14 | `account.operational_pain` | Use Exa Deep. |
| 15 | `account.strategic_moves` | Use Exa Deep. |
| 16 | `account.resonance.culture` | Use Exa Deep. |
| 17 | `account.resonance.employee_sentiment` | Use Exa Deep. |
| 18 | `account.resonance.attrition_signal` | Use Exa Deep. |
| 19 | `account.resonance.eng_blog_tone` | Use Exa Deep. |
| 20 | `account.resonance.public_frustrations` | Use Exa Deep. |
| 21 | `account.resonance.buying_culture` | Use Exa Deep. |

The table specifies source ownership, not a new waterfall. A fresh, governed claim already produced during Exa Websets discovery satisfies the field and must be reused. Missing fields are attempted only through the permitted source mappings. A supported provider returning no defensible value is an honest empty result; the system must not fabricate a value merely to fill the profile.

### 3.2 Deterministic compilation, not a new gap planner

The launch path needs a deterministic comprehensive-profile compiler:

1. Begin with the fixed 21-field list.
2. Mark fresh, governed existing claims as already satisfied.
3. Route remaining fields by the static provider ownership above.
4. Split Exa Deep work into provider-compliant bundles when its per-request field limit is reached.
5. Submit one durable account-research job per account and preserve field-level results and failures.

This is mechanical contract expansion and batching. It is **not** a new adaptive planner or a model-authored source waterfall.

### 3.3 Explicit current blockers

| Blocker | Current effect | Required correction |
|---|---|---|
| The accepted browser directive names only three account fields. | The platform performs a three-field acceptance run and presents it as account profiling. | Full-profile commands must compile to all 21 fields unless the user explicitly requests a narrower subset. |
| `account_research_fleet_launch.py` filters launch fields to `account.*`. | All `core.*` identity, industry, employee, HQ, revenue, technology, and LinkedIn fields are dropped before execution. | Admit the fixed profile's `core.*` fields and resolve them through existing governed claims or the static provider mappings. |
| Discovery output and deep-research launch are treated as separate field universes. | Exa Websets facts can exist but still look absent to the full-profile launcher. | Count reusable fresh discovery claims before scheduling provider work. |
| Sumble organization/jobs/tech actions are composed but feature-gated or not selected for the full field set. | Known integrated capabilities do not run for the fields they own. | Enable the capabilities and register the complete static field-to-action mapping. |
| Exa Deep supports bounded field bundles. | A large field request can exceed one action's supported shape. | Deterministically chunk the Exa-owned fields behind one user-visible research task. |
| The chat task card is a turn-close snapshot. | The card may remain `Queued — 0 of N` after the fleet has finished. | Project durable detached-fleet state into a live task read and stream updates to the existing card. |

### 3.4 Explicit Account selection is not tier-gated

**Founder ruling, 2026-08-19:** fit/intent scores and their numeric `high` / `low` tier are
prioritization metadata, not research eligibility. When an attributable user turn explicitly
selects an Account and the confirmed research directive includes that Account, account research
and buying-committee discovery may launch whether the signal tier is high, low, or absent. The
directive's execution-effort vocabulary (for example `standard`) is also independent of the signal
tier and must not be required to equal it.

This ruling removes only the tier eligibility check. Exact user-selected scope, directive lineage,
privacy policy, provider availability, durable authority receipts, provider spend accounting, and
configured budget ceilings remain enforced. Automatic broad-run tiering may still order work or
suggest depth, but it cannot invalidate an explicit Account research request.

## 4. Truthful live progress without extra diagnostics UI

The existing research task card must stop behaving as a frozen acknowledgement. It must reflect durable backend state after the initiating chat turn finishes.

For an account batch, the card must at minimum expose:

- total accounts;
- queued accounts;
- running accounts;
- settled accounts;
- completed, needs-review, and failed/suspended terminal outcomes;
- enough field progress to distinguish not started, in progress, partially complete, and settled.

For contact research, the equivalent projection must report per-contact and channel-lookup progress. The frontend may aggregate the rows behind one task, but its counts and progress bar must be derived from backend events or reads—not a timer and not the original assistant message.

This requirement does **not** authorize a new provider-coverage dashboard. The UI does not need to list searched/unsearched provider families, rejected identities, stopping reasons, or confidence-floor diagnostics at this checkpoint. Live task progress and provider-coverage exposition are separate concerns.

## 5. Buying-committee discovery and role inference

### 5.1 Acquisition path

Sumble Teams/People is the only committee-discovery provider required now. It must be enabled, supplied with a valid key, and allowed to use the already resolved Sumble organization binding for the account.

No fallback to Exa people search, official leadership pages, Apollo, ZoomInfo, or other sources is required in this scope. A Sumble miss remains an honest miss.

### 5.2 Role-inference contract

The expected flow is:

1. Sumble discovers and identity-resolves professional people associated with the account.
2. The existing account agent receives the candidates.
3. The agent uses the existing account research, approved ICP, product context, buying-unit scope, and each candidate's professional evidence.
4. For each candidate, the agent proposes:
   - committee role;
   - confidence;
   - reasoning;
   - exact supporting evidence references.
5. The backend stores the result honestly as an agent-derived inference.

There is no new standalone role-classifier service, separate approval tool, plausibility gate, or secondary backend decision in this scope. The frontend may show every discovered member and the inferred role regardless of confidence; it does not need a new confidence-blocking UX.

The current audit found historical/fallback writes that can label weak inference as `HUMAN`. A broad historical cleanup is deferred, but the completed path described here must not create new false human provenance. Agent-derived role writes must remain identified as agent-derived.

## 6. Contact selection and launch authority

Two user journeys must reach the same exact, durable contact-research launch:

### 6.1 Explicit-contact journey

1. The user selects one or more contacts.
2. The user adds them to the project chat and requests research.
3. The frontend/controller records the user's action as the human authority for that exact selected set.
4. The backend creates or reuses the exact selection receipt and launches contact research.

The existing `approve_contact_research_selection` capability is not enough while no active UI/controller path can invoke the human-only operation. That reachability defect must be corrected.

### 6.2 Account-tagged committee journey

1. The user tags an account and asks to research that account's buying committee.
2. The backend resolves the account's current governed committee snapshot.
3. It freezes the exact member IDs and research scope in the same durable selection receipt used by explicit selection.
4. It launches research for that set without requiring the user to select every member manually.

This is convenient expansion from an explicit account reference—not an unbounded agent widening. Replay and audit still use the exact frozen contact set.

### 6.3 LinkedIn is optional

A LinkedIn URL must not be a hard prerequisite for contact research. A contact is eligible when the backend has a sufficiently strong durable identity through the canonical contact entity and at least one supported binding, such as:

- Sumble person plus organization identity;
- an existing strong account/contact binding;
- a governed professional email identity;
- another existing provider identity accepted by the contact identity service.

LinkedIn remains a useful identity attribute and source URL, but its absence alone cannot exclude the contact.

## 7. Comprehensive contact research

### 7.1 The fixed 15-field profile

The normal comprehensive contact-research command targets all 15 existing `PROSE_CONTACT_FIELDS`, with provider ownership split as follows.

#### Sumble structured professional enrichment

- `contact.current_title`
- `contact.job_function`
- `contact.job_level`
- `contact.team_membership`
- `contact.current_location`
- `contact.organization_relationship`

#### Exa Deep public professional research

- `contact.facet.career_history`
- `contact.facet.publications`
- `contact.facet.public_appearances`
- `contact.facet.communication_style`
- `contact.facet.alma_mater`
- `contact.facet.stated_interests`
- `contact.facet.nickname`
- `contact.facet.causes`
- `contact.facet.recent_post`

The provider boundary is explicit: structured professional enrichment routes to Sumble Teams/People; deep public professional research routes to Exa Deep. Both slots must not point at the same Exa-only builder.

The legacy defaults of three contacts and eight fields may remain internal batch-size limits, but they may not truncate a user's comprehensive request. The backend must create additional bounded batches behind the same durable user task until the exact selected contact set and 15-field profile are settled.

## 8. Contact channels and real-provider validation

Contact-channel acquisition must be enabled for the integration/pilot product path. At minimum:

- email lookup must be reachable from the selected-contact and account-tagged committee journeys;
- any configured phone/channel provider must run through its real adapter rather than a deterministic double;
- provider responses and durable channel state must remain honest about observed, deliverable, verified, unavailable, or failed outcomes;
- missing strict validation must not silently turn a real observed address into fake verified data;
- one paid successful provider canary must be proven through the real browser flow, platform API, provider call, and database result.

The product-path default must resolve channel/email lookup to **on** without an ad hoc shell override. Tests may explicitly turn it off when testing the disabled state.

## 9. Required capability state

The integration/pilot runtime must resolve the following capabilities to enabled and must fail visibly when a required credential or composition is missing. These capabilities are currently disabled because their `Settings` defaults were intentionally conservative deployment authorizations; the blocker is activation/composition, not an absence of the named provider adapters.

| Capability | Current setting or seam | Current default/state | Required product-path state |
|---|---|---|---|
| Exa Websets discovery | `exa_websets_lifecycle_enabled` + `exa_websets_acquisition_enabled` | Off | On; reuse its governed account claims. |
| Exa account deep research | `exa_account_deep_acquisition_enabled` | Off | On. |
| Sumble account organization/jobs/tech enrichment | `sumble_account_gap_enrichment_enabled` | Off | On. |
| Sumble committee discovery | `sumble_committee_acquisition_enabled` | Off | On. |
| Exa contact deep research | `exa_contact_deep_acquisition_enabled` | Off | On. |
| Sumble structured contact enrichment | production contact action routing | Routed through the Exa builder | Route to Sumble Teams/People. |
| Validated contact channels | `contact_channel_enrichment_enabled` | Off | On with a concrete validator/provider binding. |
| Frontend contact email lookup | `frontend_contact_email_lookup_enabled` | Off | On by product-path default. |
| C7 research-view reads | `c7_research_view_read_enabled` | Off | On. |
| C7 snapshot composition | `c7_snapshot_compose_enabled` | Off | On where required to expose newly completed research. |
| Production handoff | `c7_production_handoff_enabled` | Off | On. |
| Frontend read integration | `frontend_read_enabled` | Off | On for the admitted workspace. |

The implementation must resolve this through checked-in configuration/defaults appropriate to the integration product path, not through undocumented local terminal state. Credentials remain secrets and must never be recorded in repository documentation or memory.

For the current manual acceptance environment, budget prompts and verification gates remain disabled as previously ruled. Their absence must not disable acquisition, research, committee discovery, contact research, or frontend display.

## 10. Deliberate deferrals and non-goals

The following must not be pulled into these slices unless the founder changes the scope:

- Adding providers outside Exa and Sumble.
- Building the complete source-order waterfall.
- Building a new broad adaptive gap planner.
- Adding committee-provider fallback.
- Adding a provider coverage or unsearched-channel UI.
- Adding a low-confidence committee-role blocker or review flow.
- Adding a standalone role classifier, separate approval tool, plausibility gate, or secondary decision.
- Repairing all historical weak-role provenance rows as an independent cleanup project.
- Requiring LinkedIn before contact research.
- Reintroducing budget or verification interruptions into this acceptance journey.

These deferrals are intentional product decisions, not accidental omissions and not blockers to the required flow.

## 11. Implementation slices

Work must proceed in independently verifiable slices rather than as one large change.

### Slice A — capability and contract activation

- Make the required product-path flags resolve on.
- Fail visibly for missing provider configuration.
- Freeze the fixed 21-field and 15-field request contracts in tests.
- Keep excluded providers absent from composition.

### Slice B — comprehensive account execution

- Reuse fresh Exa Websets claims.
- Admit `core.*` fields to the account launch path.
- Route every remaining fixed field to Exa Deep or the correct Sumble action.
- Internally batch Exa field bundles.
- Prove all 21 fields reach a settled attempted/satisfied state for each account.

### Slice C — live account progress

- Add a durable task projection over detached fleet state.
- Stream or refresh the existing task card from that projection.
- Prove the progress bar advances as individual accounts settle.

### Slice D — Sumble committee and agent role inference

- Enable Sumble Teams/People committee discovery.
- Preserve organization/person identity lineage.
- Have the account agent persist role, confidence, reasoning, and evidence references as agent-derived inference.
- Show the resulting committee without a new confidence gate or coverage UI.

### Slice E — contact launch reachability

- Complete the explicit selected-contact approval/launch path.
- Add account-tagged committee expansion into an exact immutable contact set.
- Remove LinkedIn as the single eligibility prerequisite.

### Slice F — comprehensive contact execution and progress

- Correct Sumble-versus-Exa provider-slot routing.
- Run all 15 fields across the exact selected set using internal batching.
- Enable real contact-channel lookup.
- Add contact/channel progress to the live task projection.

### Slice G — frontend reads, handoff, and real-provider acceptance

- Enable C7 reads and production handoff.
- Render account, committee, contact, and channel results in existing frontend surfaces.
- Run paid provider canaries and capture browser → API → provider → database evidence.

Each slice must be reviewed and manually tested before the next slice is treated as accepted.

## 12. Browser acceptance matrix

Acceptance is not satisfied by unit tests, provider doubles, a direct curl, or fixture-only frontend data. Each required journey needs linked evidence.

| Journey | Browser evidence | API/event evidence | Provider evidence | Database evidence |
|---|---|---|---|---|
| Full account profile | User requests comprehensive research; task progresses; profile/gallery shows results. | Exact 21-field scope and live task counts. | Real Exa Deep and relevant Sumble calls. | Claims or honest empty outcomes for all 21 fields, pinned to account/run. |
| Committee discovery | User requests or proceeds to committee; members appear. | Exact account and committee operation. | Real Sumble Teams/People response. | Identity-resolved contacts plus agent-derived roles, confidence, reasoning, and evidence refs. |
| Explicit contact research | Selected contacts are added to chat and research starts. | Human authority and exact selection receipt. | Real Sumble structured and Exa Deep calls. | Results for the exact selected contact set and all 15 fields. |
| Account-tagged committee research | User tags one account and asks to research its committee. | Server resolves and freezes the current committee set. | Same real providers as explicit contact research. | Exact derived selection receipt; no unrequested contacts. |
| Contact channels | User requests/uses contact lookup and sees truthful state. | Channel operation and progress events. | Paid real-provider canary. | Observed/validated/deliverable/failed state stored honestly. |
| Live progress | Progress advances while detached jobs finish. | Durable reads/events change after turn close. | Correlatable operation IDs where applicable. | Per-account/contact settled state agrees with the UI. |
| C7 and handoff | Existing account/contact screens show governed results. | C7 reads and production handoff succeed. | N/A beyond upstream correlations. | Returned values resolve to the same pinned claims and identities. |

The test record must name the database and artifact root and distinguish pre-existing seed state from state created by the browser journey. Provider keys, tokens, addresses, and private payloads must not be copied into evidence documents.

## 13. Annotation decision ledger

This ledger makes the disposition of every founder annotation explicit.

| Annotation | Recorded decision |
|---:|---|
| 1 | Exa Deep and Sumble are the only active research providers now, but provider breadth does not limit field breadth. |
| 2 | The complete source-order waterfall is deferred; the existing Exa/Sumble composition is sufficient for this checkpoint. |
| 3 | No new broad adaptive gap planner is required. Use fixed profile expansion and static provider ownership. |
| 4 | Replace the turn-close progress snapshot with a live durable task projection. |
| 5 | Full account research means the complete existing 21-field account profile, never the three-field acceptance subset unless explicitly requested. |
| 6 | Reuse Exa Websets discovery facts; invoke the already integrated Sumble technology and other applicable structured actions. Remove the launch-path blockers that discard or fail to route those fields. |
| 7 | Do not add Firecrawl, Scrapling, registries, CRM, Apollo, ZoomInfo, BuiltWith, or other providers now. |
| 8 | Enable and configure Sumble committee acquisition rather than leaving it default-off. |
| 9 | Sumble Teams/People is the only committee provider required; no fallback is required. |
| 10 | Keep provider-coverage distinctions out of the current frontend. |
| 11 | Defer a standalone historical weak-provenance cleanup. |
| 12 | Do not block frontend committee display on role-confidence thresholds in this scope. |
| 13 | Sumble resolves people; the existing account agent infers role, confidence, reasoning, and evidence; persist it as agent-derived with no extra classifier, approval, plausibility gate, or secondary decision. |
| 14 | Make explicit-contact research reachable and add account-tagged buying-committee research without requiring manual select-all. |
| 15 | Remove LinkedIn as a hard eligibility prerequisite. |
| 16 | Make contact lookup product-default-on and prove it with a paid real-provider browser canary rather than provider doubles. |
| 17 | Add granular, live contact-research progress to the required work. |
| 18 | Route deep public professional research to Exa Deep and structured professional enrichment to Sumble. |
| 19 | Enable Exa account deep research. |
| 20 | Enable Sumble committee discovery. |
| 21 | Enable contact channels. |
| 22 | Enable C7 research-view reads. |
| 23 | Enable production handoff. |

## 14. Definition of done

This scope is complete only when all of the following are true:

- A normal comprehensive account request attempts or reuses all 21 account fields through only the permitted provider set.
- The UI's account task card advances from durable work and settles truthfully.
- Sumble discovers committee members and the existing account agent stores honest agent-derived role inferences.
- Users can launch contact research by selecting contacts or by tagging an account's committee.
- LinkedIn absence alone does not block a strongly identified contact.
- Sumble owns the six structured contact fields and Exa Deep owns the nine public professional fields.
- A comprehensive contact request covers all 15 fields without user-visible truncation.
- Contact/channel progress is visible and live.
- Account Exa Deep, Sumble committee, contact channels, C7 reads, and production handoff are enabled in the integration product path.
- A paid real-provider browser journey proves each provider-dependent path through browser, API/events, provider operation, and durable database state.
- None of the explicitly deferred providers, fallback systems, planners, gates, or diagnostic UI has been added as hidden scope.
