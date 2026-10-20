# M8B — Account-deep provider integration roadmap
## Exa Deep account profiling + Sumble organization map and buying committee

> **Status:** implementation and live integration validation in progress. A0–A2, Exa E0–E2,
> M06A S2A–S2D, the O1 wait/wake seam, O2 production fleet composition, O3 steering behavior, and
> V0 are implemented. Real Exa, Sumble, OpenRouter, detached-fleet, verification, and zero-provider
> replay canaries passed on 2026-08-05 after six live-found defects were corrected. V1 remains open
> only for the production-composed conversational entry, promoted-output quality, and complete
> monetary-pricing gates. **Recorded:** 2026-08-05. **Working branch:**
> `platform/c8-account-profiling-integration`. **Provider baseline:** commit `cb7a275`, identical to
> the current local `platform/c8-exa-sumble-discovery` branch when this plan was recorded.
>
> This is a cross-cutting composition plan. It does not replace M06A discovery, M8 profiling,
> M8A account-deep orchestration, M11 tier-4 synthesis, Doc A, or the harness requirements. Where
> they differ in level, the authority order in `docs/architecture/README.md` applies: the harness
> governs platform interaction; Doc A governs agent mechanics; M06A/M8/M8A/M11 govern their
> provider-neutral data and execution contracts; this document governs the integration work that
> joins them for the account-deep product capability.
>
> **Successor orchestration roadmap (2026-08-06):**
> [M8D](M8D-entity-research-agents-and-shared-fleet-refactor-roadmap.md) supersedes M8B's active
> entity-agent ownership/composition for future runs: account/contact units use
> `langchain.agents.create_agent()`, providers run only through their governed tool calls, account
> and contact fleets are separately user-launched over one shared fleet substrate, and agents
> receive complete persisted research results. M8B remains authoritative historical evidence for
> its provider, durability, claim, committee, replay, and live-acceptance work.

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
    **Superseded 2026-09-22** by `docs/superpowers/specs/archive/2026-09-22-web-search-tool-design.md`
    (`web_search@1`, granted to head-of-abm@v62 and design@v3, used last, text never a claim);
    M8B's target-locked acquisition is untouched.
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

| Area | Current integrated state | Remaining delta |
|---|---|---|
| Exa Websets discovery | D1-D6 built; E1 built mechanically; discovery branch integrated | Consume only; do not rebuild or mutate the seal |
| Sumble account gaps | S1 mechanical REST-v9/snapshot/receipt integration passes; paid live gate remains open | Reuse its auth, error, snapshot, fingerprint, credit, and spend-unknown contracts where the shapes genuinely match |
| Account profiling | M8 account profiling consumed a real ready Exa snapshot through the exact effective source plan and produced two grounded verification-governed claims in the detached fleet | Obtain a promoted claim in the final quality canary; the live sample was honestly flagged/rejected |
| Exa Deep | E0–E2 and O2 produced one real coalesced two-field Deep-Reasoning operation, immutable artifacts/receipt, two materialized claims, and zero-call replay | Configure the final quality canary so at least one grounded claim survives verification |
| Committee worker | The snapshot-backed source admitted six exact-account LinkedIn identities and live model inference wrote six role plus six persona claims with honest provider/inference separation | Obtain promoted role/persona output in the final quality canary; current hypotheses were flagged/rejected |
| Sumble committee acquisition | S2A–S2D made real bounded no-reveal Teams/People calls, durably waited/polled, settled 63 credits once, materialized six candidates, and replayed without another call | Configure an honest credit-to-money policy for the final canary |
| Deep orchestrator | The provider-neutral account/committee preparation seams, short committee transaction, optional contact boundary, and detached fleet completed live for one account | Live-proven; retain regression coverage |
| Project wait state | DEEP waiting is now paired with a durable due-operation reader and fleet wake worker; a pending People operation resumed the same run/operation | Live-proven; retain restart/wake regression coverage |
| Production committee composition | Production S2D -> S2B -> S2C composition produced six candidates and completed through the real detached fleet without a provider branch in the orchestrator | Live-proven; keep default-off credential/policy gates |
| Main-agent toolbelt | Head-of-ABM v18 progressively discloses the non-linear account-deep steering skill over the existing fine-grained tools and exact O2 launch; governed descriptions distinguish draft, launch, wait, and completion | Prove the live conversational directive-to-launch path in V1 without widening engine authority |
| Research direction | A2's human-confirmed direction is consumed by launch/provider pins and O3 supplies the newest exact directive plus current launch/account state as immutable L3 context | Preserve memory as advisory and the confirmed directive as execution authority through V1 |
| Synthetic upstream state | The additive Insight Health account-deep fixture supplies deep fields, one selected sealed account, tier approval, a confirmed directive, source override, provider doubles, and the real orchestrator entry without mutating the discovery fixture; V0 adds a disposable fresh-process database harness | Retain for replay; no live proof implied |

### 3.1 Implementation checkpoint — 2026-08-04

| Slice | State | Evidence |
|---|---|---|
| A0 | Complete mechanically; no live call | `M8B-A0-account-deep-provider-contract-acceptance.md`; pinned Exa request/response digests, strict additive-tolerant models, independent default-off settings, spend/error and future-operation decisions |
| A1 | Complete mechanically; precedence remediation closed 2026-08-04 | additive fixture; direct and composed paths use the real gate and the same frozen exact-source authority, produce all four account claims, persist explicit policy refs, and replay without provider calls/writes |
| A2 | Complete mechanically after authority remediation; no provider call | `61826eb` + `940fbc0`; human-confirmed durable directives, exact sealed membership/source authority, account overrides, future-thread/context propagation, immutable plan/run/Sumble pins, and governed erasure |
| E0 | Complete mechanically after E0-R1/R2 remediation; no live call | `M8B-E0-exa-deep-wire-acceptance.md`; provider-safe request compiler plus unchanged-golden normalization, paid all-null hard miss, exact value-schema validation, field-faithful/citation-preserving evidence disposition, and hard-disabled resolver-time HTTP. |
| E1 | Complete and live-proven 2026-08-05 | one real two-field Deep-Reasoning call; one immutable operation/attempt/snapshot/receipt, 13 result artifacts, 1.800 cents settled, zero-call replay |
| E2 | Complete and live-proven through verification | two cited artifact-backed account claims materialized from the ready snapshot; verification flagged/rejected the sample rather than promoting unsupported output |
| S2A | Complete mechanically | `2810dcf`; pinned v9 Teams/People request, response, credit, no-reveal, identity, and normalizer contract |
| S2B | Complete and live-proven | one Teams plus async People submit/poll operation, 63 credits settled once, durable wake/replay, no reveal |
| S2C | Complete and live-proven | six exact-account strong-identity candidates through the existing M8 committee worker; combined candidate cap enforced |
| S2D | Complete mechanically | `00a3e90`; immutable seven-condition decision and zero-call ineligible matrix |
| O1 | Complete and live-proven | provider-neutral wait plus the durable due-operation/fleet wake path resumed the same account run and provider operation |
| O2 — Sumble composition | Complete mechanically | `cc5b62a`; S2D -> S2B -> S2C adapter, independent default-off setting, credential failure, per-run composer injection, durable combined test |
| O2 — full capability | Complete and live fleet-proven | immutable launch/run state drove production Exa/Sumble snapshot materialization, six live role calls, verification, deep/verification checkpoints, and review pause in the detached fleet |
| O3 | Complete mechanically; no live model/provider call | Head-of-ABM v18 and research-specialist v5 resources; exact current steering card/directive L3 composition; truthful draft/launch descriptions; seven scripted non-linear conversation cases; real-Postgres context/launch regression |
| V0 | Complete mechanically; recorded fixtures only | `M8B-V0-offline-database-acceptance.md`; frozen 32-case manifest plus a fresh 2026-08-05 V0 replay/migration pass; full repository run now 3,332 passed, 23 expected skips, 0 failures; mypy/Ruff/import contracts and one Alembic head pass |

The Sumble production builder still requires an injected `SumbleCommitteeInputResolver`; O2 now
supplies its durable implementation from the production composition root. It reconstructs inputs
only from the exact launch/directive/account-run/seal/tier/S1 snapshot state. Supplying a static or
session-only object in production remains forbidden. With the feature disabled, production
performs zero S2 calls.

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
  title, function, level, location, country, and current employer. The documented list-mode
  manager/direct-report selection has no returned-related-person cap, so the first S2 release does
  not call it; bounded Teams relationships supply the initial organization map.
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

#### 4.3.1 Source-precedence ruling and remediation

The original A1 production test exposed two different authorities. The planner correctly read the
workspace/ICP source-profile override, but the pre-spend gate independently read the shared
`field_definition.tier_plan`. For `account.operational_pain` and `account.strategic_moves`, the
override admitted the tier-2 official-page source before tier-4 Exa while the shared field default
listed only tier-4 sources. The gate therefore rejected a source the planner had legitimately
selected. Tier precedence itself was not broken; the planner and gate were applying different
plans.

The accepted repair is one immutable `effective_field_source_plan` per
`(workspace_id, icp_key, icp_version, field_key)`:

- the planner compiles the complete source-profile/active-capability intersection before applying
  run-specific tier, modality, LLM-ranking, fan-out, or budget narrowing;
- the first real pre-spend check reconstructs that canonical set from the pinned database state,
  rejects a merely caller-hashed substitute, and freezes the content-addressed plan;
- later planners load the frozen row, so a mutable source-profile/registry change cannot widen an
  already-pinned ICP version;
- every field request carries the exact `source_key`, tier, and plan digest; the gate checks all
  three and records them in its append-only decision row;
- field-less committee enumeration validates `sumble_teams`/`sumble_people` as exact active
  registry keys at their registered tiers; an unrelated same-tier people source is not authority;
- a rejected source is a source-local skip. The waterfall continues to another authorized
  fallback; an unsanctioned source never terminates otherwise valid research.

The global field `tier_plan` remains the legacy/static fallback for callers without a pinned ICP.
It no longer overrides a supplied, database-validated effective plan.

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

**Owns:** this spec's executable companion acceptance docs, transport-free contract models, and
fixtures; no HTTP transport, provider binding, operation, or live call.

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

**Implemented 2026-08-04 — Gate A0 mechanically closed.**

- `M8B-A0-account-deep-provider-contract-acceptance.md` records the dated official Exa reference
  review, exact request/response/URL/cost/error contracts, independent settings, operation-store
  decision, identity ruling, and decided/inferred/unresolved source map.
- Frozen request/response fixtures and transport-free models enforce deep/deep-reasoning only,
  the Clue 50-result and optional one-to-ten-additional-query caps, closed registered-field output,
  target-lock instructions, field grounding, additive response tolerance, and post-dispatch
  spend-unknown.
- Sumble retains the separately accepted S2 contract and no-reveal boundary. No HTTP request,
  provider operation, credential read, or spend occurs in A0.

### Slice A1 — Synthetic account-deep handoff fixture

**Owns:** additive trial fixture module and fixture tests only.

Deliver §6 Level A and Level B, including a separate deep ICP, selected sealed account, confirmed
directive, source override, policies, and recorded provider responses/doubles. Do not alter the
existing discovery fixture ICP.

**Gate A1:** direct profiler and full production-entry tests exercise non-empty deep gaps and real
orchestrator-created `account_run`; replay is deterministic; original discovery fixture remains
unchanged.

**Implemented 2026-08-03; critically remediated 2026-08-04 — Gate A1 closed.**

- `clue_api.trial.account_deep_fixture` now layers a separate gastroenterology account-deep ICP and
  project run over the unchanged Insight Health discovery fixture. It persists the exact sealed
  discovery generation, required-field resolutions, must-have evidence, committed discovery /
  scoring / human tier checkpoints, confirmed fixture directive and committee plan, and immutable
  Exa Deep / Sumble Jobs / Technology / Teams / People doubles. It creates no `account_run` and
  performs no network or provider operation.
- The recorded account resolvers and exact-account, no-reveal committee source implement the
  existing provider-neutral seams. Candidates carry strong LinkedIn identity keys, provider/team
  relationship labels, and immutable evidence refs; no email or phone attribute exists in the
  fixture payloads.
- DB-backed acceptance proves additive/read-only fixture replay, explicit zero-gap behavior with
  the original shallow ICP, four non-empty direct-profiler gaps, full production composition,
  orchestrator-owned durable `account_run`, two committee members, and zero-call/zero-write replay.
- The fixture directive now explicitly carries versioned budget, jurisdiction/use-class,
  freshness, recursion, source-plan, and committee-policy references. Its source-plan,
  jurisdiction, recursion, and budget values are wired into the A1 execution composition rather
  than existing only as prose.
- Both direct and production-entry paths use the real pre-spend gate and the same
  content-addressed exact-source plan. Both produce the same four governed account claims
  (`sumble_jobs` plus three `exa_deep`) with no plan mismatch or rejected sanctioned source.
- The original tier-only acceptance was reopened rather than preserved as expected failure.
  §4.3.1 now owns the source-precedence ruling; E1/O2 consume this seam instead of re-solving it.
- No paid call was authorized or made. Current verification evidence is recorded in the matching
  session memory note and local commits rather than freezing transient test counts here.

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

**Implemented and critically remediated 2026-08-04 — Gate A2 closed.**

- A bounded, immutable, content-addressed directive contract now covers research questions,
  sealed or explicit account scope, source/committee/privacy/effort policy, account overrides,
  supersession, and exact effective-account composition. Canonical JSON is bounded by UTF-8 bytes
  at both directive and effective-account boundaries, and the L3 account-research context policy
  has matching headroom for the directive plus the other required project artifacts.
- A sealed scope is an exact `discovery-seal:<batch_uuid>:<seal_sha256>` lineage pin. It resolves
  once to durable immutable account membership; overrides, account-run pins, production DEEP
  selection, and Sumble preparation all enforce that same membership relationally. Missing or
  malformed launch pins fail closed with zero selected accounts and zero Sumble transport.
- Directive sources must belong to the pinned ICP's canonical effective field-source plans or be
  active contact-yielding committee sources. Account overrides may narrow but never widen source
  authority; an active registry entry alone is not authorization.
- `draft_account_research_directive@2` persists the trusted user instruction to project-scoped
  user-stated memory and returns the complete bounded review payload: resolved accounts,
  hypotheses, field/source/committee/privacy/effort policy, effective per-account overrides,
  exclusions, unresolved gates, preview digest, and an explicit memory outcome. Human-only
  `confirm_account_research_directive@2` accepts only the reviewed directive id/digest and derives
  confirmation attribution from the trusted invocation context. Agents retain no confirmation
  authority. Historical v1 contracts remain replayable but are neither default nor granted to the
  active Head-of-ABM profile v16.
- Confirmed directive ref/digest pins now flow through account specs, research plans,
  `account_run`, account-profile execution, Sumble committee requests and authorizations, and run
  journal state. A pin can be attached only before an account run starts and is immutable
  thereafter; a confirmed successor supersedes the old directive for future work without changing
  the exact directive used by an already-running or replayed operation.
- Fresh account-agent turns materialize the effective directive at
  `context/project/research-directive.json`. Research-specialist delegations receive both that exact
  file reference and the typed directive domain ref automatically, independent of model wording.
  Fresh-thread project memory assembly also exposes the original user-stated direction.
- Every account-research context artifact carries a reverse project binding. Project deletion is
  database-blocked until the privacy service tombstones and purges exclusively owned bytes and
  releases those bindings, preventing orphaned directive/context artifacts.
- DB-backed acceptance covers durable draft/confirm replay, human-only confirmation, future-thread
  memory visibility and the disabled-memory outcome, exact sealed membership, canonical source
  authorization, account override composition, fail-closed production launch, exact plan/run and
  Sumble pinning, automatic delegation, project erasure, size ceilings, and frozen replay after
  supersession. Alembic revision `5330703a78a3` adds the membership and reverse-artifact bindings
  and passes head-to-base-to-head smoke. A2 performs no provider call, reveal, credential read, or
  spend; Exa E0 resolver files remain outside this slice.

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
prompt; non-null values require schema-valid content and field-faithful cited evidence; all-null
paid misses retain reported cost; provider errors classify retryable, hard, budget, and
spend-unknown outcomes correctly; resolver-time live HTTP is disabled until E1.

**Corrected 2026-08-04 — E0-R1 and E0-R2 closed mechanically; no live call.**

- `resolvers/exa` now compiles only explicit `deep`/`deep-reasoning` non-streaming requests. It
  consumes admitted field keys plus exact effective-registry value schemas, sorts and closes the
  output contract deterministically, target-locks the canonical account, and bounds result/query
  depth independently of A2 storage.
- E0-R1 hex-encodes each dotted registry key into one reversible path-safe provider alias and pins
  the exact readable map in the fixed system prompt. Provider responses decode back to the original
  field key before entering the provider-neutral seam.
- The compiler now enforces Exa's documented maximum of ten total properties and two named
  property levels across nested schemas. It rejects unsafe property names, unsupported composition,
  over-budget bundles and malformed schemas before dispatch; E1 must use this failure boundary when
  splitting/coalescing work.
- `contents.text` and query-guided highlights now use explicit account-deep product budgets of
  `maxCharacters=10000` and `maxCharacters=2000`; these are not represented as provider maxima.
  Deprecated `numSentences` and ignored `highlightsPerUrl` are absent and forbidden.
- Directive-derived intent and directional questions can alter bounded query text only; they
  cannot add output properties. Constrained registry schemas retain their exact semantics when the
  compiler adds a standard nullable type union; nullable enums include an explicit null member and
  caller schemas are never mutated.
- Successful parsing requires the A0 request id, reported dollars and exact structured field
  exchange. Every non-null field additionally requires retained result URLs, field grounding and
  inspectable evidence; an all-null paid miss may return no results or grounding. Deprecated or
  additive response members are ignored. Spanless candidates are omitted and malformed successes
  produce no result.
- The doubles-only one-field response harness performs exactly one explicitly injected dispatch
  with zero adapter retries. Missing schema/credential/invalid request is a pre-dispatch hard
  failure; transport ambiguity or malformed success after dispatch is `spend_unknown`. It does not
  reserve, persist, settle, replay, materialize claims, or bind production composition; those remain
  E1/E2.
- A0 request/response fixtures and digests were deliberately amended because provider property
  aliases are part of both wire directions. Acceptance is recorded in
  `M8B-E0-exa-deep-wire-acceptance.md`; all tests use recorded fixtures or provider doubles and no
  credential read or paid provider request occurs.
- E0-R2 recursively validates every returned value against the admitted request schema. The
  unchanged golden normalizes without fixture mutation; all-null/no-grounding output is an empty
  paid hard miss with reported cost rather than `spend_unknown`.
- Passage selection scores all retained highlights/text for support of the exact field value/key,
  so an unrelated first highlight cannot become evidence. Every citation retains a typed
  attribution/disposition and every supported citation retains its own candidate.
- Production Exa registration is now a hard pre-dispatch placeholder until E1 supplies durable
  acquisition and a ready-snapshot backend. The live resolver-time HTTP function/default was
  removed; E0 provider traffic remains doubles-only.

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

**Implemented 2026-08-04 — Gate E1 closed without a live paid call.**

- The provider-neutral `external_research_operation` ledger now records exact workspace/project /
  account / ICP / confirmed-directive lineage, immutable request content and digests, shared-budget
  reservation, dispatch lease, attempts, raw/result/normalization artifacts, ready snapshots and a
  separately immutable provider-reported cost receipt. Alembic revision `bc0612c57713` has one
  head and passed a clean isolated head-to-base-to-head migration smoke.
- The Exa acquisition compiler deterministically packs admitted registry fields under the E0
  eight-field, ten-property and two-level schema limits. Directional questions remain query-only;
  one two-field account bundle produces one request fingerprint and one transport call.
- The coordinator captures and binds the request before dispatch, calls only an injected zero-retry
  transport outside database transactions, and makes `ready` unrepresentable until the response,
  provider request id, retained result artifacts, grounding normalization, snapshot and receipt are
  durable. The dormant real HTTP transport resolves `CLUE_EXA_API_KEY` only at call time and forces
  the shared HTTP wrapper to zero retries; it is not composed or invoked in this slice. E1 itself
  writes no claim; independent field materialization remains E2-owned.
- Active dispatch leases cause concurrent callers to join. An expired/crashed lease, unexpected
  post-dispatch exception, malformed success, missing settlement data or reported cost above the
  reservation becomes terminal `spend_outcome_unknown` with no automatic retry. Proven 400/401 /
  402/403/404 and pre-dispatch failures terminate as not charged.
- Exact-operation replay and exact-wire/exact-directive freshness reuse return the stored snapshot
  with zero transport. The offline snapshot loader has no transport dependency, preserving the
  rule that resolver/materializer reads cannot perform network calls.
- Provider-free DB acceptance covers coalescing, exactly-once seven-cent settlement, immutable
  attempts/snapshots/receipts, two retained result artifacts, two independently retained normalized
  fields, all-null paid misses, zero claim writes, fresh-process replay, freshness reuse, active
  join, crash quarantine and pre/post-dispatch failure classification.

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

**Implemented 2026-08-04 — Gate E2 closed mechanically; successful live canary remains V1 work.**

- Ready-snapshot selection is exact on workspace, project run, canonical account, source, and the
  complete confirmed directive pin. Materialization has no credential or HTTP fallback and
  revalidates the immutable wire request, response, normalization, request id, reported cost,
  all-null state, result URL, and artifact reference before constructing any candidate.
- Claims preserve the exact provider operation, snapshot, request id, result artifact, source URL,
  evidence span, target account, and zero per-field cost. The operation receipt remains the single
  owner of provider spend; materializing one snapshot into several fields does not duplicate cost.
- A task-scoped resolver binding lets both the mechanical profiler and governed account agent read
  the same immutable snapshot without mutating the process-global registry or introducing an Exa
  branch in worker/orchestrator control flow. Nested and concurrent task isolation is regression
  tested.
- The coverage tool and mechanical profiler now compile and enforce the same canonical effective
  source plan per field. The healthcare workspace/ICP override selects Sumble Jobs or Technology
  only where deliberate, then the official-page source, then Exa Deep; Parallel Task is absent.
- DB-backed acceptance runs E1 acquisition into both account-research paths, keeps an unsupported
  resonance field empty with terminal coverage, promotes a supported tier-4 claim only after the
  shared faithfulness gate, rejects a contradicted claim, proves exact gate/source-plan decisions,
  and replays from a fresh resolver with zero HTTP and no additional spend.
- Alembic revision `2e6920101a1b` adds the immutable external-research lineage columns to claims and
  passes isolated head-to-base-to-head smoke. The 2026-08-04 explicitly authorized live request
  reached `POST /search` once but Exa returned HTTP 401. The durable operation correctly ended
  `failed_terminal` / `not_charged` with no automatic retry or snapshot; therefore it proves the
  credential-failure boundary, not the successful V1 snapshot/materialization canary.

### Slice S2A — Sumble Teams/People contract and normalizers

**Owns:** new isolated `resolvers/sumble/teams.py` and `resolvers/sumble/people.py` (or equivalent
provider-local files) plus fixtures. Existing S1 organization/jobs/technology behavior is frozen.

Deliver:

- resolve/reuse canonical Sumble organization id;
- bounded Teams request selecting only required breadcrumbs/activity/functions/technology/location;
- bounded related people/job-post selects with explicit caps;
- organization-scoped People search selecting non-contact fields only;
- async People submit/poll status model and exact first-success charging semantics;
- no People manager/direct-report lookup until Sumble exposes a returned-row cap or governance
  approves a separately bounded spend contract; still no reveals;
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
6. retain the bounded provider-inferred person/team relationships from the Teams response;
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

**Implemented 2026-08-04 — Gate O2 closed mechanically; successful paid canaries remain later
acceptance work.**

- `launch_account_deep@1` is the only set-scoped full-unit authority. Tier approval leaves the run
  active at DEEP without enqueuing research; launch requires an action reference, an exact
  human-confirmed directive, 1–500 exact approved accounts, a recomputed estimate, remaining run
  headroom, and a composed committee capability.
- The immutable `account_deep_launch` receipt and account membership rows pin the project run,
  directive version/digest, sorted selected set, per-account effective pins, approved budget,
  estimate, actor, action, and source operation. Exact replay survives directive supersession and
  state-machine advancement; a changed set, directive, or budget conflicts. Decimal wire scale is
  not part of the request identity.
- DEEP selection reads only that receipt and rechecks the live human-approved tier evidence. The
  selected account's effective cap is persisted on `account_run` and governs account profiling,
  committee discovery, and contact admission; ephemeral phase params cannot widen the launch.
- Production Exa preparation compiles each field through the canonical source planner, presents
  that exact authority to the real pre-spend gate, acquires through E1 outside claim transactions,
  and supplies only E2 immutable snapshot resolvers to account profiling. Pending work maps to the
  existing provider-neutral DEEP wait and ready replay performs zero HTTP.
- Production Sumble preparation derives its organization id from a verified successful S1
  snapshot and compiles the no-reveal Teams/People request from the exact launch, A2 committee
  plan, sealed membership, human tier, privacy policy, and account budget. No session-only input
  object or provider branch was added to `AccountDeepOrchestrator`.
- The existing scheduler/fleet and one `AccountDeepOrchestrator` per account remain the execution
  unit. Fine-grained account, committee, and contact tools are unchanged. Head-of-ABM v17 receives
  launch authority; conversational preview/steering behavior and its evals remain O3-owned.
- Real-Postgres acceptance covers explicit launch/enqueue, no enqueue at tier approval, immutable
  and exact replay, directive supersession, account-run budget propagation, canonical-plan Exa
  acquisition plus zero-call replay, S1-backed Sumble inputs, and the combined prerequisite
  regression set. The new Alembic revision passes a clean head-to-base-to-head round trip.

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

**Implemented 2026-08-04 — Gate O3 closed mechanically; live conversational/provider acceptance
remains V1-owned.**

- Head-of-ABM v18 progressively discloses one provider-neutral account-deep steering skill beside
  Stage 0. It treats discovery and tier results as conversational context, never launch consent,
  and keeps working-plan edits conversational until the human asks for an immutable draft.
- The preview contract separates registered standard fields from directional hypotheses, maps Exa
  Deep to structured cited account evidence and Sumble Teams/People to the bounded organization
  map, and makes the current no-contact-reveal boundary explicit.
- A current-state compiler reads the exact project run, tier approval, newest directive and
  overrides, immutable O2 launch receipt, canonical account identities, and account-run cursors.
  It materializes content-addressed project context and the exact directive without transitioning
  a phase, confirming, launching, calling a provider, or claiming completion.
- Model-facing tool descriptions now state that drafting is non-spending and non-confirming, while
  launch success means receipt/enqueue/replay rather than completed research. Tool schemas and
  existing recipe/profile pins remain unchanged.
- Research-specialist v5 distinguishes pre-launch plan review from admitted execution and receives
  the exact directive artifact and current steering card through the existing fresh-wake
  delegation seam. It cannot confirm, launch, promote claims, or bypass
  budget/privacy/evidence gates.
- Scripted coverage includes show-only, discover-more, five-account fax/referral direction,
  no-reveal, edit-before-confirm, edit-after-launch, and explicit-go-ahead cases. Real-Postgres
  acceptance proves the card before/after the immutable launch and its exact project/subject-bound
  artifact materialization.

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

**Implemented 2026-08-04 — Gate V0 closed mechanically; live success remains V1 work.** The frozen
coverage manifest and detailed evidence are in `M8B-V0-offline-database-acceptance.md`. V0 fixed a
real Sumble durability gap by recording and binding a raw charged response before row
normalization. A new process can now recover the committed response without dispatch, while
malformed charged rows retain exact evidence/cost and enter no-retry spend-unknown quarantine. The
disposable database harness runs `head -> base -> head`, races two launch processes, materializes
through the existing committee worker, verifies artifacts/claims/gates/projection/run refs, and
replays in another process whose transport forbids every provider call. Recorded-fixture V0 made
no live provider request.

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

**Live partial pass 2026-08-05 — Gate V1 remains narrowly open.** Starting from the synthetic
discovery-only database, one real selected account produced one Exa Deep-Reasoning operation, one
bounded Sumble Teams/People operation with durable pending/wake/poll, two grounded account claims,
six admitted committee identities, six live-model role/persona classifications, verification, a
successful detached-fleet DEEP -> VERIFICATION -> REVIEW run, and fresh-process zero-provider
replay. The live run exposed and drove fixes for the missing provider wake worker, absent production
role model, combined-candidate cap leak, ignored contact-profiling prohibition, transaction-
invisible gate reads, and stale S2 OpenAPI pin. V1 remains open because the user-facing O3
conversation-to-launch surface was not executed live, the sample claims were honestly
flagged/rejected rather than promoted, and Sumble/OpenRouter monetary pricing was not configured.
The durable ids, receipts, claims, test evidence, and exact remaining gates are recorded in
`M8B-V1-live-acceptance.md`.

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

The first two contact-oriented follow-ons now have a dedicated technical roadmap:
[M8C — Contact-deep research and selected-contact enrichment](M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md).
M8B remains the implementation and live-acceptance record for account profiling and no-reveal
Sumble committee discovery; M8C begins at that boundary.

- contact email/phone reveal and independent validation — owned by M8C;
- broad M4 contact facets at fleet scale — owned by M8C;
- Sumble Signals, Priority Signals, relevance feedback, and Intelligence Briefs;
- general-purpose Exa Search tool for arbitrary agent web search;
- Parallel Task in the healthcare source profile;
- frontend-specific design beyond the existing chat/tabs/projection contracts;
- a Sumble-specific orchestrator, second account fleet, or provider-specific phase;
- automatic handoff from discovery to deep research.
