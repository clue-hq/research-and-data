# M8B — Account-deep provider integration roadmap
## Exa Deep account profiling + Sumble organization map and buying committee

> **Status:** accepted requirements and implementation plan; implementation not started on this
> branch. **Recorded:** 2026-08-03. **Working branch:**
> `platform/c8-account-profiling-integration`. **Provider baseline:** commit `cb7a275`, identical to
> the current local `platform/c8-exa-sumble-discovery` branch when this plan was recorded.
>
> This is a cross-cutting composition plan. It does not replace M06A discovery, M8 profiling,
> M8A account-deep orchestration, M11 tier-4 synthesis, Doc A, or the harness requirements. Where
> they differ in level, the authority order in `docs/architecture/README.md` applies: the harness
> governs platform interaction; Doc A governs agent mechanics; M06A/M8/M8A/M11 govern their
> provider-neutral data and execution contracts; this document governs the integration work that
> joins them for the account-deep product capability.

## 1. Outcome

Deliver one production-credible account-deep capability that the platform deepagent can launch for
an explicitly selected account set after discussing and pinning the user's research direction.
For each admitted account, the existing detached fleet runs the existing
`AccountDeepOrchestrator` as the bounded per-account unit:

```text
platform deepagent
    -> confirmed project research directive + selected account set
    -> one set-scoped, governed tool invocation
    -> existing detached fleet shell
    -> one AccountDeepOrchestrator per account
         -> governed account research agent
              -> field/source waterfall
              -> Exa Deep for target-locked directional synthesis gaps
         -> Sumble organization-map and committee acquisition
         -> existing committee identity admission and role/persona logic
         -> optional bounded contact fan-out in a later authorized slice
    -> typed claims, committee graph, evidence, coverage, receipts, and run refs
```

The deliverable is not a new global phase sequence and not a provider-specific orchestrator. Exa
and Sumble are provider implementations behind existing or additive provider-neutral seams. The
platform deepagent decides whether and what to launch; the fleet schedules; the account unit
researches; the engine enforces eligibility, identity, evidence, spend, privacy, and replay.

## 2. Binding requirements

### 2.1 Harness and user-control requirements

1. Account discovery never automatically starts account-deep research.
2. After discovery or import, the user may discuss any project matter with the platform deepagent:
   inspect accounts, discover more, adjust the ICP, ask questions, research a subset, or do
   nothing. A discovery result is context, not an automatic trigger.
3. Before the first account-deep spend under a new direction, the deepagent must present a concise
   research preview: selected accounts, admitted fields/questions, product-specific hypotheses,
   source families, committee scope, exclusions, depth, expected cost, and approval needs.
4. The user may edit that direction conversationally. The main thread remains the only user-facing
   agent thread; the deepagent may delegate planning judgment to the research specialist and bring
   its report back.
5. Research direction must survive the current chat. User-stated project instructions are submitted
   through the scoped-memory write seam for future conversational assembly, while the exact
   executable direction is frozen separately as a versioned research directive and pinned into
   every launched run. Memory is advisory; the confirmed directive is execution input; neither is
   factual account truth.
6. Confirmation is an action-scoped gate, not a `DEEP_PLANNING` platform phase. The user can keep
   conversing before, during, or after it. A later edit creates a successor directive and affects
   only runs launched against the new version.
7. The user can launch the full account-deep unit or independently invoke account profiling,
   committee discovery, contact profiling, verification, or further discovery when their local
   preconditions pass.

### 2.2 Research and provider requirements

8. Account profiling is target-locked to one canonical account. Discovery provenance is not enough
   by itself; every research request carries canonical name, domain, geography/aliases where
   available, workspace/project/product/ICP identity, and the pinned directive version.
9. Exa Websets remains the M1 discovery provider. Exa Search Deep/Deep-Reasoning is a separate M2
   account-profiling capability with its own request contract, dollar receipt, snapshots, replay,
   and acceptance evidence. No Websets operation or billing semantics are reused for Search.
10. Exa structured output is used deliberately: the engine compiles a bounded JSON schema from
    registered fields and admitted research questions. Provider synthesis never defines the schema
    and never promotes itself.
11. Sumble REST v9 is used for structured organization, jobs, technology, team, people, and related-
    person data where the field/source plan selects it. Sumble is not called merely because a field
    is empty.
12. Sumble supplies provider-returned organization structure, titles, functions, levels, teams,
    reporting relationships, and candidates. The existing provider-neutral committee worker owns
    champion/economic-buyer/technical-evaluator/blocker and persona inference. Provider-returned
    facts and platform inferences are labeled separately.
13. The first committee slice performs no email or phone reveal. Reveals are later operations over
    the final selected people, with separate request identities, budgets, jurisdiction/use gates,
    and independent validation. A Sumble person response is never allowed to include contact
    attributes accidentally through `"all"`.
14. Sumble Signals, Priority Signals, relevance updates, and Intelligence Briefs remain out of
    scope. They require separate trust/evidence/freshness contracts.
15. General-purpose Exa web search as an unrestricted agent tool remains out of scope. This plan
    authorizes only target-locked account-deep acquisition through the research substrate.
16. Parallel Task is excluded from the initial healthcare account-deep source profile. Do not
    delete the provider globally; omit it through a versioned workspace/ICP field/source-plan
    override. `sumble_tech_stack` is admitted only for a deliberately mapped field.
17. The waterfall is per field/question, not one universal provider order. Structured and primary
    sources run before tier-4 synthesis where they can answer the field. Exa Deep fills admitted
    synthesis gaps and searches directional pain/resonance questions; unsupported hypotheses remain
    empty and contradictions remain explicit.

### 2.3 Durability, cost, and evidence requirements

18. Every paid request is preflighted, fingerprinted, reserved, snapshotted, settled once, and
    journaled. A possible paid response without a durable receipt becomes
    `spend_outcome_unknown`; it is never blindly retried.
19. External acquisition never occurs while a claim/materialization transaction is open. Submit
    and poll outside the short claim transaction; materialize only from a ready immutable snapshot.
20. A pending Sumble People operation returns a provider-neutral waiting result. The account unit
    and project runner remain at the same logical operation, sleep/wake durably, and resume without
    duplicate submit or charge.
21. Provider raw responses are content-addressed artifacts. Claims carry the exact source key, URL,
    evidence span, artifact reference, observation time, provider request/operation reference,
    extraction method, confidence, reuse scope, and verification state.
22. Structured provider output is candidate material, not truth. No claim without target-lock and
    evidence; no tier-4 claim without the faithfulness gate; no personal claim without identity and
    use gates.
23. Provider cost is settled once at the operation/receipt boundary. Do not copy a batch's full
    cost onto every candidate or claim. Cost allocation for display may be derived, but settlement
    has one durable owner.
24. Fresh snapshot replay performs zero provider calls. Crash/restart, concurrent duplicate launch,
    webhook/poll duplication, and a fresh process all converge on the same terminal operation and
    claim set.
25. The original discovery batch, operation receipts, items, account admission, and immutable seal
    remain unchanged by account-deep work.

## 3. Current state and exact deltas

| Area | Current state at `cb7a275` | Required delta |
|---|---|---|
| Exa Websets discovery | D1-D6 built; E1 built mechanically; discovery branch integrated | Consume only; do not rebuild or mutate the seal |
| Sumble account gaps | S1 mechanical REST-v9/snapshot/receipt integration passes; paid live gate remains open | Reuse its auth, error, snapshot, fingerprint, credit, and spend-unknown contracts where the shapes genuinely match |
| Account profiling | M8 account profiler and C6.7 governed account research agent exist | Supply a deep-field ICP, directive context, real production resolver/acquisition bindings, and provider acceptance |
| Exa Deep | `ExaDeepResolver` exists but is an older synchronous, field-at-a-time Search adapter using `search_type="neural"`, highlights, and direct HTTP | Freeze the current `/search` Deep/Deep-Reasoning contract; compile structured output; coalesce bounded fields/questions; persist request/response/cost; materialize snapshot-backed fields |
| Committee worker | Provider-neutral `CommitteeSource`, admission, role plausibility, persona claims, and coverage exist | Implement Sumble-backed source and preserve provider-vs-inferred semantics |
| Sumble committee acquisition | No People/Teams production implementation; no S2 acceptance doc | Add pinned v9 models, bounded Teams/People requests, async People polling, durable snapshot/receipt, and replay |
| Deep orchestrator | `profile_account -> discover_committee -> profile_contact` exists | Add a provider-neutral prepare/wait seam; never call external sources from its committee transaction |
| Project wait state | `PhaseStatus.WAITING_EXTERNAL` exists but the durable project machine currently admits it only for discovery | Admit a DEEP provider wait and preserve account/run identity across wake-up |
| Production committee composition | `committee_sources` defaults empty and emits a warning | Bind `SumbleCommitteeSource` only when its feature flag, credentials, policy, and durable acquisition store are present |
| Main-agent toolbelt | `run_deep_account@1` invokes M2 `profile_account` only; `resolve_committee@1` is separate | Keep fine-grained tools; add an unambiguous set-scoped full-unit launcher that uses the existing fleet and `AccountDeepOrchestrator` |
| Research direction | Project-scoped memory and `project_instruction` ingestion exist; account plans currently contain only gap-field aspects | Add a versioned confirmed directive, pin it into plan/run context, and layer account-specific overrides without treating memory as authority |
| Synthetic upstream state | Existing Insight Health fixture stops at discovery and its active ICP has scoring fields only | Add a separate profiling fixture layer with deep fields, selected sealed account, tier approval, directive, source override, provider snapshots/doubles, and real orchestrator entry |

## 4. Provider roles and field-level waterfall

### 4.1 Exa

- **Websets:** wide grounded account discovery, criteria evaluation, cheap enrichments, identity
  admission inputs. It stops before deep account facts.
- **Search Deep/Deep-Reasoning:** bounded target-locked account research. It searches scattered
  evidence and synthesizes admitted account-level questions that structured/official sources cannot
  answer alone.
- **Structured response:** the request `outputSchema` is compiled from registered field schemas and
  the confirmed directive. `systemPrompt` carries source/novelty/target-lock rules; bounded
  `additionalQueries` express approved directional questions. The response's `results`, text,
  highlights, synthesized output, grounding citations, request id, and cost report are all retained.
- **Trust:** Exa synthesis remains tier 4 even when its output is well structured. Structure is not
  evidence. A synthesized value without field-level citations and an inspectable span is dropped or
  retained unverified for review; it is never promoted.

### 4.2 Sumble

- **Organizations / existing S1 snapshots:** canonical Sumble organization id and selected
  organization attributes.
- **Jobs:** job descriptions and extracted technologies, teams, functions, levels, projects, and
  bounded related people where the plan calls for them.
- **Teams:** organization-scoped hierarchy, breadcrumbs, activity, technologies, functions,
  locations, related people, and job-post references.
- **People:** organization-scoped non-contact attributes first: person id, name, LinkedIn URL,
  title, function, level, location, country, and current employer. A later bounded list-mode request
  may retrieve managers/direct reports for shortlisted people without revealing email/phone.
- **Signals/briefs:** not part of this plan.

### 4.3 Initial healthcare effective source plan

Implement this as a versioned workspace/ICP override; do not mutate the shared
`healthcare_practice` pack:

| Field/question family | Initial ordered source families | Notes |
|---|---|---|
| Hiring velocity and role pressure | `sumble_jobs` -> official careers page -> `exa_deep` when synthesis is required | Jobs remain atomic; Exa explains the pattern only when admitted |
| Technology stack | `sumble_tech_stack` -> official primary source -> optional `exa_deep` | Include only when the field mapping is deliberate and bounded |
| Strategic moves | official site/filing/news -> `exa_deep` | Contradictions route to primary sources |
| Operational pain | available structured/job evidence -> reputable third-party evidence -> `exa_deep` | Directional hypotheses must be confirmed or left empty |
| Resonance/culture/frustrations | reputable public reviews/interviews -> `exa_deep` | Account-scoped only; no personal/sensitive facet leakage |
| Committee organization map | `sumble_teams` -> `sumble_people` -> bounded related-person/job evidence -> official leadership/careers page if unclear | No whole-list search; exact account only |

The override authorizes `sumble_jobs`, the chosen official-page resolver (`firecrawl_site` or the
configured `scrapling_site` manifest, never an unnamed fetcher), `exa_deep`, and only deliberate
`sumble_tech_stack`. It excludes `parallel_task` for this first integration.

## 5. Durable user research direction

### 5.1 Two different persistence species

The user's instructions have two correct homes with different authority:

1. **Project-scoped memory:** user-stated preferences such as “when researching gastro practices,
   inspect fax/referral/DAC coordination burden” enter the existing memory write seam as active,
   project-scoped advisory memory. This makes the preference available in future conversations.
2. **Confirmed research directive:** the exact fields, questions, accounts, source constraints,
   exclusions, budget/depth, and committee plan authorized for execution are frozen in an
   append-only versioned directive. This is the input pinned to a run. It is not memory and not a
   claim.

Memory never authorizes provider spend. A directive never becomes factual evidence. The claim store
remains the only account/contact truth substrate.

### 5.2 `ResearchDirective` contract

Add one typed core/API contract and durable record, provisionally named `ResearchDirective`:

```text
directive_id, workspace_id, project_id, product_id
icp_key, icp_version, version, status(draft|confirmed|superseded)
account_scope: explicit ids or sealed selection reference
field_keys: registered deep fields only
questions[]: id, text, target field/facet, priority, source-family hints, stop rule
committee_plan: functions, levels, teams, personas, candidate cap, relationship depth
source_policy: allowed, preferred, excluded, primary-source contradiction rules
privacy_policy: contact/profile/reveal exclusions
effort_policy: tier/depth/fan-out and budget envelope refs
memory_refs[]: advisory inputs used when compiling the directive
created_by, confirmed_by, confirming_turn_ref, predecessor_id
canonical_json_sha256, created_at, confirmed_at
```

Rules:

- append-only versions; confirmation and supersession are journaled;
- same workspace/project/product/ICP lineage is enforced by foreign keys/checks;
- user text is stored as an immutable input artifact or turn reference, not smuggled into a claim;
- only registered field keys and allowed source keys compile;
- a user question may guide search without asserting its answer;
- account-specific overrides layer over the confirmed project directive and are pinned separately;
- a launched operation stores directive id/version/digest and cannot silently pick up later edits;
- DSAR and project deletion include directives, turn/artifact refs, and associated project memories.

### 5.3 Conversational tools and preview

Expose provider-neutral, human-agent-parity tools:

- `draft_account_research_directive@1` — non-spending; compiles current project context, account
  refs, memory labels, registered fields, and research-specialist strategy into a typed draft.
- `confirm_account_research_directive@1` — a human gate; records the actual human actor and source
  turn/action. The agent cannot self-approve or impersonate the user.
- `launch_account_deep@1` — set-scoped spending tool; requires one confirmed directive, explicit
  account selection, estimates, policy/budget approval, and provider eligibility.

The deepagent renders a human-readable preview from the typed draft before confirmation. The
preview includes accounts, standard fields, user-added questions, product/vertical hypotheses,
source plan, committee functions/levels/teams, exclusions, cost/depth, and unresolved prerequisites.
This is conversational behavior around tools, not a fixed workflow stage.

## 6. Synthetic upstream fixture

Create `seed_insight_health_account_deep_fixture` as an additive layer over
`seed_insight_health_discovery_fixture`. Never change the existing fixture's active ICP or make its
discovery-only tests deep-aware.

### 6.1 Level A — account-unit fixture

For resolver, governed account-agent, committee-source, and direct-orchestrator tests seed:

1. loaded research packs and source manifests;
2. one workspace-local canonical account with name, domain, LinkedIn URL, location/identity hints,
   active status, and an optional Sumble organization id observation;
3. a separate ICP version containing bounded deep fields:
   `account.hiring_velocity_eng`, `core.primary_tech_stack`, `account.operational_pain`,
   `account.strategic_moves`, `account.resonance.culture`, and
   `account.resonance.public_frustrations` when registered;
4. a workspace/ICP source override matching §4.3, with no `parallel_task`;
5. baseline identity/firmographic claims and content-addressed evidence so context assembly is real;
6. one confirmed directive containing standard fields plus representative healthcare directional
   questions (referral/fax/phone/DAC/administrative coordination), explicitly phrased as hypotheses;
7. immutable recorded Exa Deep and Sumble Teams/People responses or injectable acquisition
   doubles behind the same production seams;
8. budget, jurisdiction, use-class, freshness, recursion, and committee policy;
9. no pre-created `account_run`; the real orchestrator creates/resumes it.

### 6.2 Level B — complete production entry fixture

For `ProjectRun`/fleet/toolbelt acceptance additionally seed or construct through real handlers:

- workspace, brand, product, project, Client KB, product context, and confirmed ICP lineage;
- canonical account admitted into the exact current discovery generation;
- every must-have evaluation passed with evidence and every required discovery field terminal;
- durable plan, batch, provider operations/pages/items, manifest, artifacts, and immutable seal;
- committed discovery and scoring checkpoints;
- human-approved committed tier checkpoint;
- one live workspace-private `account.scoring.tier` claim carrying project run, batch, exact seal,
  ICP, selection-policy, selected disposition, and approved tier;
- confirmed research directive and explicit committee plan;
- project run ready for the deep tool/recipe without manually bypassing database invariants.

The fixture must prove that using the original shallow ICP would be a loud precondition failure or
an explicit zero-gap result, never a misleading “successful deep profile.”

## 7. Provider-neutral acquisition and wait contract

### 7.1 Contract freeze before schema work

The first implementation slice inventories D6, E1, and S1's operation/snapshot/receipt stores and
extracts the smallest shared provider-operation protocol. Do not add a fourth independent copy of
fingerprinting, reservation, spend-unknown, artifact persistence, or replay logic.

Recommended contract:

```python
class ExternalResearchAcquirer(Protocol):
    async def prepare(request: AcquisitionRequest) -> AcquisitionPreparation: ...

class AcquisitionPreparation:
    outcome: READY | WAITING_EXTERNAL | INELIGIBLE | FAILED
    operation_ref: str | None
    snapshot_refs: tuple[str, ...]
    retry_after: datetime | None
    cost_receipt_ref: str | None
    reason_code: str | None
```

The API/composition layer owns concrete storage and provider imports. Profiling and committee
workers receive only ready snapshot readers. If the existing D6/E1/S1 records cannot represent
subject kind, directive identity, synchronous Search, and asynchronous People without semantic
overloading, add one generic `external_research_operation`/snapshot ledger rather than Sumble-only
or Exa-only lifecycle tables. New Alembic revisions use random hashes and retain one head.

### 7.2 Orchestrator split

Replace the current transaction-spanning committee acquisition path with:

```text
Stage 1  profile account
Stage 2A prepare external committee sources OUTSIDE claim transaction
         - ineligible -> zero call + typed reason
         - waiting -> persist operation ref, return WAITING_EXTERNAL
         - ready -> immutable snapshot refs
Stage 2B short committee materialization transaction
         - SumbleCommitteeSource reads snapshots only
         - identity admission, role/persona claims, refs, cost fold
Stage 3  optional bounded contact profiling
```

Extend the DEEP project handler/state machine so `PhaseStatus.WAITING_EXTERNAL` is legal for DEEP,
not discovery-only. Preserve the same project run, account run, operation, directive, and sub-phase
on wake-up. A provider wait is not a human pause and does not block unrelated conversation.

## 8. Implementation slices

Every slice has a strict exit gate. Unit tests alone do not close a provider slice. No live paid
call occurs without separate authorization.

### Slice A0 — Contract and authority freeze

**Owns:** this spec's executable companion acceptance docs and fixtures; no provider code.

Deliver:

- pinned Exa `/search` Deep/Deep-Reasoning request/response fixtures and current docs/OpenAPI digest;
- pinned Sumble v9 Organizations/Jobs/Teams/People/related-person filters, select fields, async
  states, pagination, limits, error classes, and credit rules;
- decision record for operation-store reuse/generalization;
- strong identity decision for Sumble `person_id` versus LinkedIn/verified email;
- exact provider/source/evidence URL semantics;
- exact feature flags and environment variable names, with secret-presence checks only;
- source map separating decided, inferred, and unresolved provider behavior.

**Gate A0:** request builders and recorded response models fail loudly on breaking drift, tolerate
documented additive fields, and the acceptance document names the exact charging/settlement event.

### Slice A1 — Synthetic account-deep handoff fixture

**Owns:** additive trial fixture module and fixture tests only.

Deliver §6 Level A and Level B, including a separate deep ICP, selected sealed account, confirmed
directive, source override, policies, and recorded provider responses/doubles. Do not alter the
existing discovery fixture ICP.

**Gate A1:** direct profiler and full production-entry tests exercise non-empty deep gaps and real
orchestrator-created `account_run`; replay is deterministic; original discovery fixture remains
unchanged.

### Slice A2 — Research directive, preview, and context binding

**Owns:** typed directive contract, durable store/migration, draft/confirm tools, projections, and
context materialization. It does not call a provider.

Deliver:

- append-only directive versions and human confirmation gate;
- project-scoped user-stated memory submission for durable preferences;
- directive preview projection;
- directive ref/digest on account specs, account plan, provider requests, and run journal;
- `context/project/research-directive.json` and delegated research-specialist task refs;
- account-specific override composition and supersession.

**Gate A2:** a user instruction is visible in a future fresh thread, compiles to a confirmed typed
directive, reaches a fresh account research agent by reference, and a later edit does not mutate an
already-running operation.

### Slice E0 — Exa Deep structured wire contract

**Owns:** `resolvers/exa` request/response types and recorded fixtures; no composition edits.

Modernize the existing adapter:

- explicit configured `deep` or `deep-reasoning`, never the old hardcoded `neural` default;
- bounded `numResults` and `additionalQueries` from the directive/policy;
- deterministic `outputSchema` generated from field registry value schemas;
- target-lock/source instructions in `systemPrompt`;
- contents text/highlights and synthesized output with grounding;
- tolerant additive parsing; do not branch on deprecated `resolvedSearchType` or `context`;
- separate reported dollar cost, internal reservation, and settlement classification.

**Gate E0:** golden requests are stable by digest; schema fields cannot be injected by free-text
prompt; missing URLs/grounding/spans are dropped; provider errors classify retryable, hard, budget,
and spend-unknown outcomes correctly.

### Slice E1 — Durable Exa account acquisition

**Owns:** Exa acquisition coordinator and operation/snapshot adapter; no committee code.

Deliver one bounded request per admitted aspect/account bundle rather than one paid call per field:

- coalesce fresh deep gap fields and directive questions under policy limits;
- reserve before dispatch and persist request artifact/fingerprint;
- persist raw response, request id, result artifacts, grounding and cost receipt before success;
- quarantine post-dispatch ambiguity;
- terminal replay and freshness reuse;
- expose ready snapshot refs to the resolver; no network call from `resolve()`.

**Gate E1:** two requested fields share one authorized call, settle once, materialize independently,
and fresh-process replay makes zero HTTP calls and writes no duplicate equivalent claim.

### Slice E2 — Snapshot-backed Exa materialization and verification

**Owns:** Exa snapshot resolver/normalizer, field-plan override, account-agent integration tests.

Deliver:

- map structured output and retrieved spans to registered field value schemas;
- preserve per-field grounding and provider request/artifact refs;
- target-lock before claim construction;
- run shared merge/corroboration and tier-4 faithfulness gate;
- route unsupported or contradicted hypotheses to terminal coverage outcomes honestly;
- bind the healthcare workspace/ICP source override with no Parallel Task;
- make both the mechanical profiler and governed account agent consume the same snapshot seam.

**Gate E2:** the full account research agent produces verified/non-promoted-as-appropriate Exa claims
for real deep fields, an unsupported field remains empty with terminal coverage, and no provider
name appears in the account orchestrator or worker control flow.

### Slice S2A — Sumble Teams/People contract and normalizers

**Owns:** new isolated `resolvers/sumble/teams.py` and `resolvers/sumble/people.py` (or equivalent
provider-local files) plus fixtures. Existing S1 organization/jobs/technology behavior is frozen.

Deliver:

- resolve/reuse canonical Sumble organization id;
- bounded Teams request selecting only required breadcrumbs/activity/functions/technology/location;
- bounded related people/job-post selects with explicit caps;
- organization-scoped People search selecting non-contact fields only;
- async People submit/poll status model and exact first-success charging semantics;
- optional bounded manager/direct-report lookup for shortlisted provider ids, still no reveals;
- normalized provider-neutral organization-map records with returned-vs-inferred labels.

**Gate S2A:** request snapshots contain no email/phone selection; max rows/related people/jobs are
bounded; recorded responses normalize titles/functions/levels/teams/relationships and exact credits
without dropping a charged row silently.

### Slice S2B — Durable Sumble committee acquisition

**Owns:** Sumble acquirer over the shared external-operation seam.

Flow:

1. reuse fresh S1 organization identity when valid;
2. acquire relevant teams and job evidence;
3. compile team/function/level filters from the confirmed committee plan;
4. submit one bounded People operation;
5. poll durably outside transactions;
6. optionally acquire bounded related-person relationships for the shortlist;
7. persist immutable snapshots and one operation-level credit receipt.

**Gate S2B:** eligible submit returns `WAITING_EXTERNAL` while pending; crash/restart does not
resubmit; first successful poll charges/settles once; subsequent polls and fresh replay charge zero;
failed work is uncharged; spend-unknown is quarantined.

### Slice S2C — Snapshot-backed `SumbleCommitteeSource`

**Owns:** the API-composition adapter implementing the stable committee enumeration seam and any
minimal additive candidate fields proven necessary.

Deliver candidates with provider id, name, title, LinkedIn URL, function, level, team, location,
relationship/evidence refs, and returned-vs-inferred labels. The source reads ready snapshots only.
Do not put batch cost on every candidate. Prefer LinkedIn or verified email as the current strong
identity key. If only `person_id` is available, follow A0's governed provider-identity decision;
never silently weaken the admission gate.

**Gate S2C:** candidates resolve under the exact account; candidates without an approved strong key
are dropped or reviewed; existing role/persona logic writes grounded claims; provider relationships
are distinguishable from platform committee-role inference.

### Slice S2D — Complete seven-condition eligibility and privacy gate

**Owns:** one provider-neutral committee eligibility service, tests, and gate/audit projection.

Before any Teams/People/related-person request prove:

1. exact sealed-batch membership;
2. Pass A completion for the exact account and ICP;
3. evidence-backed pass for every must-have criterion;
4. human-approved committee-eligible tier;
5. confirmed committee plan/directive;
6. personal-data, jurisdiction, use-class, identity, pre-spend, and budget approval; and
7. no fresh reusable snapshot for the same fingerprint.

**Gate S2D:** a matrix flips each condition independently and every ineligible case produces zero
Sumble calls and zero paid operation rows. No whole-list people search is constructible.

### Slice O1 — Provider-neutral wait seam in account-deep orchestration

**Owns:** `api/deep` orchestration/handler and the smallest durable enum/migration delta.

Deliver §7.2 without any `if provider == "sumble"` branch. Extend DEEP waiting semantics, account
result refs, wake scheduling, projection/narration, and crash tests. Keep claim transactions short.

**Gate O1:** a pending provider returns `WAITING_EXTERNAL`, commits no partial committee claims,
holds no transaction during polling, wakes into the same account operation, and resumes at
materialization without re-running account profiling or resubmitting the provider job.

### Slice O2 — Full account-deep toolbelt and fleet composition

**Owns:** serial API composition work after Exa and Sumble adapters pass independently.

Deliver:

- `launch_account_deep@1` as a set-scoped campaign/project operation over the existing scheduler
  and `AccountDeepOrchestrator`;
- explicit account-set/directive/budget inputs and estimates;
- preserve separately invokable M2 `run_deep_account@1`, M3 `resolve_committee@1`, and M4 tools;
- do not silently change the existing ambiguous tool's semantics; deprecate/alias only under a
  versioned tool-contract decision;
- bind Exa acquisition/snapshot resolution into account profiling;
- bind `SumbleCommitteeSource` into `committee_sources` under default-off flags;
- one account fleet, one per-account orchestrator, no provider-specific fleet or phase;
- all entry surfaces use the same toolbelt, gates, and journal.

**Gate O2:** the platform deepagent launches a selected set into the detached fleet; each account
uses the full orchestrator; zero committee sources is a typed precondition for a full-unit request
rather than a warning and silent empty output; fine-grained account-only research remains valid.

### Slice O3 — Main-deepagent planning and steering behavior

**Owns:** Head-of-ABM/research-specialist skills, context assembly, tool descriptions, and behavior
evals. It does not weaken engine gates.

Deliver behavior that:

- discusses freely after discovery instead of advancing automatically;
- previews admitted account/committee research before first spend;
- distinguishes standard schema fields from user-added directional questions;
- lets the user add/remove accounts, questions, sources, committee roles, contact work, and reveals;
- persists project direction and pins the confirmed directive;
- can recommend more discovery instead of deep research;
- launches work, narrates durable refs/status, and remains conversational while the fleet runs;
- never reports launched/waiting work as completed research.

**Gate O3:** scripted conversation evals cover “show accounts only,” “discover more,” “research these
five with special fax/referral direction,” “remove phone reveals,” edit-before-confirm, and
edit-after-launch. No case auto-launches from discovery completion.

### Slice V0 — Offline and database acceptance

Run the full fault matrix with recorded provider fixtures, real Postgres, real artifact storage,
real claims/verification, and provider HTTP replaced only at the external boundary:

- every eligibility condition false;
- duplicate/concurrent launch;
- process crash before dispatch, after dispatch, after response before snapshot, after snapshot
  before materialization, and after claim write before fold;
- People pending/running/succeeded/failed and repeated successful poll;
- Exa missing grounding, additive drift, timeout, 4xx, 429, 5xx, and spend-unknown;
- Sumble charged unknown row/schema drift;
- stale versus fresh snapshot;
- source contradiction and merge preservation;
- account identity drift and same-name contact collision;
- budget/jurisdiction/use-class rejection;
- DSAR enumeration/tombstoning/replay;
- fresh-process replay.

**Gate V0:** targeted tests, full test suite, mypy, Ruff, import-linter, one Alembic head, and isolated
`head -> base -> head` all pass; claims, receipts, artifacts, gates, projections, and run refs are
inspectable from a new process.

### Slice V1 — Separately authorized live canaries

Run in increasing scope, each with a hard cap and explicit approval:

1. one account, one Exa Deep request, one or two deep fields;
2. one eligible account, bounded Sumble Teams + People without contact reveals;
3. one combined account-deep canary through the platform tool/fleet/orchestrator;
4. fresh-process replay of each with zero additional provider calls/spend.

Record provider request ids, request/response artifacts, timings, reported/settled cost, credits,
claims, evidence, target-lock, identity decisions, committee roles, coverage, verification, run refs,
and replay evidence. A mock-only or exit-zero result does not close the gate.

**Gate V1:** the combined canary proves conversational directive -> launch -> Exa account claims ->
Sumble organization map/committee -> verification -> projections, with exact cost and replay, and no
contact reveal.

## 9. Sequencing and parallel ownership

```text
A0 contract freeze
    +-> A1 synthetic fixture
    +-> A2 directive/context
    +-> E0 -> E1 -> E2          Exa lane
    +-> S2A -> S2B -> S2C       Sumble lane
    |                -> S2D
    +-> O1 wait seam
    -> O2 serial composition    joins A1, A2, E2, S2C, S2D, O1
    -> O3 agent behavior
    -> V0 offline/DB acceptance
    -> V1 live canaries
```

A1 and A2 may proceed after A0. Exa E0-E2 and Sumble S2A-S2D may build in parallel against frozen
seams. O1 may build against acquisition doubles after A0. O2 is the single serial integration
commit and must wait for E2, S2C/S2D, and O1. O3 follows stable tool schemas. V0 precedes spend.
The Sumble lane may begin from S1's mechanical acceptance, but S2 live release and the combined V1
canary remain blocked until the S1 paid live canary passes or a separately recorded governance
decision explicitly changes that gate.

| Area | Exa lane | Sumble lane | Serial integration |
|---|---|---|---|
| Existing Websets and S1 account code | Consume; do not edit | Consume; do not edit | Reconcile shared helper extraction once |
| Provider models | `resolvers/exa` | new Sumble People/Teams files | Export/register only after adapter tests |
| Durable operation adapter | Exa request/receipt mapping | Sumble async mapping | Shared store/protocol migration owned once |
| Account profiling | snapshot resolver tests | no edits | bind through account research composition |
| Committee worker | no edits | source adapter tests | only minimal additive candidate contract if proven |
| `api/deep` | no provider branches | no provider branches | O1/O2 owner only |
| Toolbelt/profiles/skills | no parallel edits | no parallel edits | O2/O3 owner only |
| Migrations | none unless A2 owns directive | none in adapter lane | one-head merge/serial revisions only |
| Provider live calls | none during build | none during build | V1 only with approval |

## 10. Release acceptance

The account-deep integration is releasable only when all are true:

1. Discovery completion causes zero account-deep calls without a later explicit launch.
2. A user can inspect the account table, discuss anything, discover more, or research a subset.
3. The deepagent previews and pins a user-editable research directive before first spend.
4. A future fresh thread receives the user-stated project direction; an old run retains its old
   directive version.
5. The full-unit tool launches the existing fleet and `AccountDeepOrchestrator`, not a new fleet.
6. A non-eligible account causes zero Exa Deep and Sumble committee requests as applicable.
7. Exa Deep uses target-locked, registry-shaped structured output and writes only grounded,
   verification-governed claims.
8. Sumble builds a bounded organization/team/person map and the existing worker classifies the
   committee with provider-returned versus inferred semantics visible.
9. No contact reveal occurs in the first release.
10. Pending People acquisition returns DEEP `WAITING_EXTERNAL` without an open claim transaction.
11. Crash/restart and concurrent replay create no duplicate submit, charge, operation, candidate,
    contact, or equivalent claim.
12. Provider cost/credits settle exactly once and remain distinct units.
13. The original discovery seal and claims are unchanged.
14. Coverage names unsearched channels and never promises completeness.
15. One combined live account canary and fresh-process replay prove request, polling, snapshots,
    claims, evidence, identity, committee, cost, projections, and zero-spend replay.

## 11. Explicitly deferred follow-ons

- contact email/phone reveal and independent validation;
- broad M4 contact facets at fleet scale;
- Sumble Signals, Priority Signals, relevance feedback, and Intelligence Briefs;
- general-purpose Exa Search tool for arbitrary agent web search;
- Parallel Task in the healthcare source profile;
- frontend-specific design beyond the existing chat/tabs/projection contracts;
- a Sumble-specific orchestrator, second account fleet, or provider-specific phase;
- automatic handoff from discovery to deep research.
