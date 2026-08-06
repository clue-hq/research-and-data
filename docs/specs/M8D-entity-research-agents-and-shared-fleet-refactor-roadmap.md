# M8D — Entity research agents and shared fleet refactor roadmap
## `langchain.agents.create_agent` account/contact units over one durable fleet substrate

> **Status:** R0–R5 accepted; R6–R10 have not started.
> **Recorded:** 2026-08-06. **Working branch at record time:**
> `platform/c8-account-profiling-integration`.
>
> M8D supersedes the **entity-agent ownership and active orchestration composition** described by
> M8B/M8C for future runs. It does not rewrite their implementation history or invalidate their
> accepted provider transports, durable operations, snapshots, claim lineage, governance, replay,
> committee, contact-selection, or handoff contracts. Historical executions remain pinned to the
> exact profiles and recipes they used.

## 1. Why this roadmap exists

M8B and M8C successfully built most of the trustworthy backend needed for account and contact
research: provider contracts, external acquisition, immutable snapshots, spend settlement,
claims, evidence, identity, verification, committee materialization, contact selection,
wait/wake, and detached fleet execution.

The active composition nevertheless placed research judgment in the wrong layer:

- Exa account/contact acquisition could occur before the responsible entity agent ran;
- the account agent was a `deepagents.create_deep_agent()` unit with only
  `research_account_gaps@2` as its domain tool;
- the coverage controller could force a generic `deterministic_exact` first strategy even when a
  field had no applicable deterministic resolver;
- the agent received references and coverage status rather than the complete persisted structured
  research result needed for evidence-based follow-up judgment;
- contact acquisition/materialization was mechanical preparation inside the account-deep unit,
  rather than a separately user-launched fleet of contact research agents; and
- an account run could progress directly into contact research instead of returning the completed
  account profile and committee to the user first.

M8D corrects **orchestration ownership**, not the substrate. The durable provider and claim
infrastructure is reused behind governed agent tools.

## 2. Binding terminology and component classes

There are not two LLM agents per account. The terms are:

| Component | Nature | Responsibility |
|---|---|---|
| Head-of-ABM platform deepagent | `deepagents.create_deep_agent()` | The only user-facing conversational agent; discusses, previews, confirms, launches, steers, and presents review items |
| Shared research fleet | Mechanical engine | Queue, leases, concurrency, envelopes, checkpoints, provider limits, waiting, wake, cancellation, canary, supervision, replay |
| Account job controller / `AccountDeepOrchestrator` successor | Deterministic durable envelope | Binds one account job, agent checkpoint, directive, budget, results, waits, and finalization; contains no provider/source judgment |
| Account research agent | `langchain.agents.create_agent()` | One bounded research mind for one account; chooses governed tools, questions, safe parallel calls, follow-ups, and stopping |
| Contact research agent | `langchain.agents.create_agent()` | One bounded research mind for one explicitly selected contact; chooses governed contact tools, facets, follow-ups, and stopping |
| Facet agent | Fresh bounded child agent | Optional one-facet isolation; depth one, one or two children maximum, no child delegation, shared parent budget |
| Provider/claim/verification services | Engine | Authorization, external I/O, persistence, target-lock, merge, verification, promotion, spend, and replay |

The account/contact unit construction is exact:

```python
from langchain.agents import create_agent
```

It must not be silently substituted with `deepagents.create_deep_agent()`. The platform
Head-of-ABM remains a deepagent. Account and contact entity units are small `create_agent()`
agents with explicit tools, context, limits, checkpoints, and typed finalization.

## 3. Binding lifecycle and user-control contract

### 3.1 Account and contact research are separate launches

```text
Head-of-ABM conversation
    -> user confirms Account Research launch
    -> Account Research Run on shared fleet
         one create_agent() account agent per selected account
         account profile + organization map + buying committee
    -> all account jobs reach terminal states
    -> fleet returns results and durable review items to Head-of-ABM/user
    -> user discusses, resolves, changes, or does nothing
    -> user separately confirms Contact Research launch
    -> Contact Research Run on the same shared fleet substrate
         one create_agent() contact agent per explicitly selected contact
    -> contact claims, facets, evidence, coverage, channels where authorized
```

There is no automatic:

- discovery -> account research transition;
- account profile -> committee research merely because a stage ended;
- account fleet -> contact fleet transition; or
- committee membership -> contact research authorization.

The Head-of-ABM remains conversational and non-linear throughout. Each launch is an action-scoped,
content-addressed authorization, not a new compulsory platform phase.

### 3.2 Contact selection is not limited to committee members

The default contact-research proposal may select the most relevant buying-committee members, but
the user may explicitly select any other strongly identity-resolved person associated with the
account when local policy, source, identity, budget, and approval gates pass.

The binding rule is:

> Only contacts explicitly selected for the contact-research run receive contact agents. The
> selection may include committee members or other user-chosen contacts.

### 3.3 Account fleet output boundary

An account research agent produces:

- a target-locked account profile;
- complete structured research results and typed claim outcomes;
- structured account enrichment where useful;
- a bounded organization map;
- a rational buying committee or an explicit partial committee;
- durable coverage gaps and review items; and
- an accepted account finalization receipt.

It does not perform contact personal-facet research. The account fleet ends and returns control to
the user before any contact research run is authorized.

## 4. Provider roles and source selection

Provider responsibilities are explicit:

- **Exa Deep:** open-ended, target-locked directional account/contact research and additive
  follow-up questions;
- **Sumble:** structured organization, jobs, technology, teams, people, titles, functions, levels,
  locations, and organization-map evidence;
- **Exa Websets:** structured account/contact enrichment where its field contract is appropriate;
- **official/primary sources:** evidence inspection, independent verification, and contradiction
  resolution; and
- **claim/verification engines:** deduplication, corroboration, conflict, identity, use, and
  promotion decisions.

The waterfall is a field/question-specific engine policy, not a mandatory sequence of agent
rounds. A source family absent from a field's effective source plan is compiled out and consumes no
agent round. Trust tier labels how evidence is treated; it does not invent a nonexistent resolver
or force the agent to call an inapplicable provider.

Initial account behavior:

- qualitative account questions such as operational pain, strategic moves, and resonance/culture
  normally begin with one schema-bounded Exa Deep request;
- structured hiring/technology/organization questions may reuse or call Sumble/Websets;
- independent qualitative and structured calls may run concurrently when engine-authorized; and
- official-source inspection is additive when evidence is contradictory, weak, or needs stronger
  independent support.

One related qualitative bundle should normally be one structured Exa request, not one request per
field.

## 5. Shared research fleet contract

The fleet is one reusable mechanical substrate. Account and contact research are distinct durable
runs configured over it, not duplicate fleet implementations.

An illustrative job contract is:

```text
ResearchJob
  research_run_id
  subject_type                 account | contact
  subject_entity_id
  parent_account_id            required for contact
  workspace_id
  project_id
  product_id
  project_run_id
  directive_ref + digest
  selection_ref                exact account/contact selection
  agent_profile_ref + digest
  field_plan_ref
  source_plan_ref
  policy_refs
  budget_envelope_ref
  checkpoint_thread_id
  attempt_id
  lease_id
```

Shared responsibilities:

- durable priority queue and bounded leases;
- separate configurable account/contact concurrency ceilings;
- per-account and per-contact budget envelopes plus run-wide cap;
- provider-specific global rate limits and circuit breakers;
- LangGraph/Postgres checkpoint and resume;
- stable operation and tool idempotency identities;
- external wait without holding a process, database transaction, or fleet slot;
- wake and requeue of the exact owning job;
- cancellation without resurrection;
- canary and run-level aggregate supervision; and
- exact replay with zero additional provider spend.

Hundreds of queued subjects do not mean hundreds of resident agents. A worker constructs or
resumes an agent only for a leased job, releases the slot on durable wait, and another worker may
resume the same checkpoint later.

## 6. Shared `create_agent()` runtime

One reusable entity-agent factory supplies the role-specific context and tools:

```python
create_agent(
    model=model,
    tools=effective_tools,
    system_prompt=resolved_prompt,
    middleware=middleware,
    response_format=ResearchFinalizationProposal,
    checkpointer=postgres_checkpointer,
)
```

The runtime must provide:

- exact role/profile/prompt/skill version and digest;
- explicit minimal tool allowlist;
- exact entity, account, directive, selection, field, source, policy, and budget context;
- append-only model/tool history;
- durable tool-call journal and provider-operation causation;
- safe execution of multiple independent tool calls from one model response;
- suspension/resume for asynchronous operations;
- bounded rounds and marginal-yield/cost stopping backstops;
- optional bounded facet delegation; and
- engine-accepted finalization as the only successful terminal path.

Every agent-mode provider operation must be causally attributable to at least:

```text
agent_turn_id
agent_execution_id
tool_call_id
tool_name + version
tool_input_sha256
target_entity_id
parent_operation_ref / parent_observation_ref, when additive follow-up
```

No provider request may precede the responsible agent's governed tool call.

## 7. Governed tool surfaces

### 7.1 Account agent tools

```text
read_account_research_state
research_account_deep
enrich_account
inspect_account_evidence
discover_buying_committee
assess_account_coverage
delegate_account_facet        optional and policy-capped
finalize_account_research
```

Current implementations behind the semantic tools may include Exa Deep, Sumble, Exa Websets, and
official-source adapters, but provider SDKs are never exposed directly to the agent. Tool schemas
remain provider-neutral enough to replace an implementation while preserving exact source and
operation attribution in results.

### 7.2 Contact agent tools

```text
read_contact_research_state
research_contact_deep
enrich_contact
inspect_contact_evidence
reveal_contact_channel        only under exact channel authorization
validate_contact_channel      independent validator required
assess_contact_coverage
delegate_contact_facet        optional and policy-capped
finalize_contact_research
```

Email and phone remain separate operations, permissions, budgets, validations, and use decisions.
No environment toggle may substitute for an absent independent validator.

## 8. Lossless research-result lifecycle

Agents never manually copy provider output into storage. Persistence completes before a governed
tool result is returned:

```text
agent tool call journaled
    -> stable provider operation reserved
    -> external request dispatched outside claim transaction
    -> complete raw provider response stored immutably
    -> every retained result/content artifact stored
    -> complete normalized structured result stored immutably
    -> provider receipt and cost reconciled exactly once
    -> candidate claims constructed
    -> target-lock / identity / evidence / use checks
    -> compare with existing claims
    -> persist accepted, corroborating, conflicting, rejected outcomes
    -> return complete persisted research-result projection to agent
```

For every Exa call, durable state includes:

- exact request and structured-output schema;
- complete raw response and provider request identity;
- retained result/page artifacts and content hashes;
- complete normalized values, explicit nulls, and unsupported fields;
- citations, evidence spans, and source/artifact references;
- target-lock and identity findings;
- candidate-claim delta and verification/use outcomes;
- provider-reported and settled cost; and
- follow-up lineage.

Raw snapshots are retained even when no claim is admitted.

### 8.1 What returns to the agent

The agent receives the complete persisted research result, not merely claim UUIDs or a lossy
sentence summary. An illustrative projection is:

```json
{
  "status": "completed",
  "operation_ref": "exa-operation:...",
  "result_ref": "research-result:...",
  "cost_cents": "2.10",
  "fields": [
    {
      "field_key": "account.operational_pain",
      "outcome": "found",
      "value": "...",
      "claim_delta": "accepted",
      "claim_refs": ["claim:..."],
      "evidence": [
        {
          "evidence_ref": "evidence:...",
          "source_type": "official",
          "title": "...",
          "url": "https://...",
          "span": "..."
        }
      ],
      "confidence": 0.84,
      "verification_status": "supported"
    }
  ],
  "explicit_nulls": [],
  "conflicts": [],
  "rejected_findings": [],
  "unresolved_fields": ["account.resonance.culture"],
  "follow_up_questions": []
}
```

If the complete result exceeds one tool-message budget, the result contains a complete structured
index plus a durable result reference. `read_research_result` and `read_evidence` retrieve sections
losslessly. The context window remains a cache; Postgres and content-addressed artifacts remain the
source of truth.

### 8.2 Candidate claims are not automatically accepted truth

The claim engine—not the LLM—owns:

- exact and normalized equality;
- idempotent duplicates;
- independent corroboration;
- competing/conflicting claims;
- overlapping paraphrase linkage;
- verification and identity binding;
- appropriateness/use classification; and
- current-value promotion.

The agent sees accepted, corroborating, conflicting, and rejected findings so it can rationally
choose verification, a new source, a bounded follow-up, or an honest stop.

## 9. Additive follow-up research

Each follow-up is a separate immutable operation and snapshot:

```text
round 1 operation/snapshot
    -> exact agent observation
    -> additive question/reason
    -> round 2 operation/snapshot linked to round 1
    -> claim-level delta
```

The new request records what is already known and asks for an additive perspective so a provider
does not repeat work unnecessarily. The engine enforces maximum calls, remaining budget, admitted
fields/sources, and duplicate-work detection.

Follow-up reason is typed, for example:

```text
new_angle
evidence_verification
contradiction_resolution
identity_disambiguation
remaining_gap
```

## 10. Account research behavior and committee integrity

For its one account, the account agent:

1. reads the confirmed directive, account identity, existing claims, applicable field/source
   plans, evidence, gaps, limits, and budget;
2. uses one structured Exa request for related qualitative account questions;
3. may concurrently request independent structured Sumble/Websets enrichment;
4. inspects the complete persisted results, including nulls, conflicts, and rejections;
5. issues bounded additive follow-ups only when justified;
6. reasons about the organizational functions and roles involved in this product's buying
   decision;
7. declares an explicit buying-unit scope;
8. uses Sumble Teams/People and other admitted evidence to locate actual people in that scope;
9. admits a coherent committee or persists an explicit partial-coverage result; and
10. proposes finalization to the engine.

The buying-unit scope includes at least:

```text
account_id
canonical_office_or_facility_id
office city / region / address when available
business unit or facility
location evidence refs
```

Every committee member must satisfy exact account/current-employment identity, relevant buying
role, admitted office/facility/location cluster, and sufficient identity evidence. Unknown or
ambiguous office membership is excluded or produces `NEEDS_REVIEW`. A partial same-office
committee with a named gap is correct; a geographically incoherent committee is not.

## 11. Contact research behavior

After a separate user-approved contact launch, each contact agent:

1. reads the exact selected contact, account/employer identity, directive, admitted fields,
   source/use policy, channel permissions, existing claims, gaps, and budget;
2. runs target-locked Exa Deep research for admitted professional or public personal facets;
3. uses structured Sumble/Websets enrichment when useful and authorized;
4. inspects complete persisted results and claim deltas;
5. may issue bounded additive follow-ups;
6. may delegate one or two independent facets at depth one;
7. may request an exact approved channel acquisition followed by independent validation; and
8. proposes contact finalization to the engine.

An agent must not infer that committee membership is required. It acts only on the explicit
contact selection receipt and local gates.

## 12. Parallel tool execution

One model response may propose multiple tool calls. The execution layer runs them concurrently
only when it proves they are independent and separately budget-admitted.

Good parallelism:

```text
Exa qualitative account research
    ||
Sumble jobs/technology enrichment
```

```text
contact publications facet
    ||
contact public-appearances facet
```

Required sequencing:

```text
initial Exa result
    -> follow-up derived from that result
```

```text
committee discovery
    -> identity admission
    -> user contact selection
    -> separate contact fleet launch
```

```text
email/phone acquisition
    -> independent validation
```

The engine checks per-entity concurrency caps, provider rate limits, atomic budget reservations,
source policy, stable idempotency, overlapping field work, and dependencies. If one parallel
operation waits externally, completed siblings remain durable, the agent checkpoint suspends, the
worker slot is released, and the same checkpoint resumes with the settled result set.

## 13. Honest finalization and review

An ordinary final model message cannot complete an entity job. The agent must call:

```text
finalize_account_research
finalize_contact_research
```

Its proposal contains the outcome, completed and unresolved fields, claim/evidence/result refs,
remaining-gap reasons, and recommended review flags. The engine independently verifies:

- no provider operation is pending;
- claimed completions have durable evidence;
- the coverage ledger and claim delta agree;
- all spend is reconciled;
- identity/use/verification gates ran where required;
- no prohibited field/source/channel was researched; and
- the proposal targets the current state digest.

Only an immutable accepted finalization receipt marks the job terminal. Allowed terminal outcomes:

```text
COMPLETED
EXHAUSTED
NEEDS_REVIEW
BUDGET_STOPPED
CANCELLED
FAILED
```

`WAITING_EXTERNAL` is suspended, not terminal. A model that stops without accepted finalization
leaves an incomplete/failed job; it is never silently treated as successful.

`NEEDS_REVIEW` creates a durable review item. Automated gates act first; the fleet supervisor
groups unresolved cases; after the run, the Head-of-ABM presents the review queue. Only an
authorized human/policy action can accept ambiguity, exclude a person/claim, authorize more
research, change office scope, revise the directive, or permit a governed use. Committee-integrity
review should be resolved before the user launches contact research over the affected committee.

## 14. Implementation slices

### R0 — Authority contract and forbidden-flow battery

Freeze the component classes, exact `create_agent()` requirement, lifecycle, tool/result schemas,
provider-operation causation, finalization, selection, facet, and concurrency contracts.

**Exit gate:** tests fail against every forbidden old flow and pass against contract fixtures;
implementation has not yet been widened.

**Accepted 2026-08-06:** the frozen contracts, schema fingerprints, canonical fixture, 56-case
forbidden-flow battery, verification evidence, and no-widening boundary are recorded in
`M8D-R0-authority-contract-acceptance.md`.

### R1 — Cleanup and active-path quarantine

Separate valid current work from incorrect orchestration. Remove or retire from new-run
composition:

- pre-agent account/contact provider acquisition;
- gap-only account-agent composition;
- active entity profiles using `create_deep_agent()`;
- universal `deterministic_exact` initialization;
- automatic account-to-contact progression; and
- mechanical contact preparation as the research decision-maker.

Historical profiles/recipes remain exact-replay-only. Until the replacement exists, new entity
research launches fail loudly with `entity_research_agent_not_composed`; they never fall back to
the removed flow.

**Exit gate:** no new provider operation can originate from the quarantined orchestration; valid
provider/durability/claim infrastructure remains green; unrelated worktree changes are untouched.

**Accepted 2026-08-06:** the fail-loud phase seam, exact-address replay-only tool boundary,
production composition cut, historical profile/recipe treatment, tests, and known unrelated
repository failures are recorded in `M8D-R1-active-path-quarantine-acceptance.md`.

### R2 — Subject-neutral fleet/job contract

Generalize the existing queue/lease/checkpoint/wait/budget substrate for account and contact
research runs without duplicating the fleet.

**Exit gate:** account/contact jobs share execution machinery but remain separately launched,
scoped, budgeted, cancelled, observed, and finalized.

**Accepted 2026-08-06:** the immutable run/job authority, shared queue/lease handler, exact
checkpoint wait/wake, cancellation fencing, receipt-only finalization, per-run concurrency/budget
scope, disposable-database migration proof, and R1-preserving composition boundary are recorded in
`M8D-R2-subject-neutral-fleet-acceptance.md`.

### R3 — Shared `create_agent()` runtime

Implement the role-configured entity-agent factory, Postgres checkpointer, exact context, tool
allowlists, typed finalization, journaling, and bounded facet contract.

**Exit gate:** executable evidence proves account/contact/facet units are constructed through
`langchain.agents.create_agent()` and not `create_deep_agent()`.

**Accepted 2026-08-06:** the single role-configured factory, exact resource/context/tool authority,
Postgres checkpoint and append-only history/tool journal, guarded parallel calls, external-wait
receipt, depth-one facet boundary, engine-receipt-only entity finalization, R2 driver adapter, and
executable evidence are recorded in `M8D-R3-shared-create-agent-runtime-acceptance.md`.

### R4 — Governed tools and complete persisted result projection

Compose the reusable provider/claim services behind account/contact semantic tools. Add complete
research-result projection/read surfaces and provider-operation causation.

**Exit gate:** a tool persists raw, normalized, evidence, claim-delta, cost, and lineage state
before returning a complete agent-usable result.

**Accepted 2026-08-06:** exact semantic-tool authority, journal-before-dispatch provider
causation, lossless result/evidence projection, replay-versus-cause separation, additive follow-up
lineage, subject erasure, isolated-Postgres verification, and the retained R1 production boundary
are recorded in `M8D-R4-governed-tools-and-persisted-results-acceptance.md`.

### R5 — Account research agent

Implement dynamic account tool choice, bundled Exa qualitative research, independent structured
enrichment, additive follow-up, office-coherent committee formation, coverage, review, and
finalization.

**Exit gate:** one account agent demonstrably observes a first result, makes a justified runtime
decision, and finalizes account+committee without contact deep research.

**Accepted 2026-08-06:** the exact account `create_agent()` composition, result-informed dynamic
tool choice, bundled Exa qualitative research, independent Sumble structured enrichment,
provider-neutral additive follow-up, office-coherent Sumble Teams/People committee formation,
coverage/review/finalization state, operation-idempotent spend folding, isolated-Postgres proof,
and retained R1 production boundary are recorded in
`M8D-R5-account-research-agent-acceptance.md`.

### R6 — Account research fleet and user return

Compose exact-set account launches, bounded concurrency, canary/supervision, steering, terminal
aggregation, and return-to-user behavior.

**Exit gate:** all account jobs finish or suspend honestly; the account run ends and exposes its
results/review queue without starting contact research.

**Accepted 2026-08-06:** the action-scoped exact-set compiler, atomic content-addressed launch,
bounded queue concurrency, deterministic canary/supervision, scoped pause/resume/reprioritize and
cancellation, honest wait/failure suspension, terminal result/review aggregation, account-only
return, run-scoped production composition, isolated-Postgres evidence, and retained R10 live-call
boundary are recorded in `M8D-R6-account-research-fleet-acceptance.md`.

### R7 — Contact selection and independent launch

Generalize selection authority to exact user-chosen identity-resolved contacts, whether committee
members or not, with exact fields, questions, sources, facets, channel permissions, policies,
budgets, and approvals.

**Exit gate:** no contact job exists without a valid selection; a governed non-committee contact
can be selected and launched.

### R8 — Contact research agents on the shared fleet

Compose contact `create_agent()` units, contact tools, optional depth-one facets, exact identity
locking, channel operations, finalization, and run aggregation over the same fleet substrate.

**Exit gate:** the separately approved contact run profiles only its exact selected contacts and
does not widen to the rest of the account or committee.

### R9 — Parallel execution and external-wait hardening

Implement dependency-aware multi-tool execution, atomic budget admission, settled-result joining,
partial completion durability, and async wait/resume.

**Exit gate:** independent Exa/Sumble calls run concurrently; dependent follow-up remains
sequential; crash/restart produces no duplicate call or spend.

### R10 — Cutover, dead-code deletion, adversarial and live acceptance

Promote the new profiles/recipes, retain historical replay, remove unreachable compatibility code,
run the forbidden-flow and fault matrix, and perform bounded live Exa/Sumble account and contact
canaries.

**Exit gate:** all §16 release criteria pass with database, artifact, trace, tool-call, provider,
claim, cost, finalization, review, and zero-spend replay evidence.

## 15. Reuse and deletion boundary

### Preserve and reuse

- Exa Deep and Exa Websets compilers, transports, schemas, snapshots, and receipts;
- Sumble organization/jobs/technology/teams/people contracts and durable acquisition;
- external research operations, artifacts, wait/wake, spend settlement, and replay;
- claim/evidence stores, merge/corroboration/conflict, target-lock, and verification;
- identity, jurisdiction, appropriateness/use, DSAR, retention, and channel validation;
- committee candidate admission, role/persona classification, and professional claims;
- contact selection, channel authorization, handoff, and research-view projections;
- the detached fleet's queue, leases, checkpoints, limiters, supervisor, and canary; and
- historical exact profile/recipe replay.

### Remove or replace

- active pre-agent Exa/Sumble account/contact acquisition;
- the one-tool `research_account_gaps@2` account-agent surface;
- account/contact entity profiles backed by `create_deep_agent()`;
- generic strategy ladders that manufacture inapplicable source attempts;
- agent receipts that omit the complete persisted research result;
- mechanical contact preparation as the owner of research decisions;
- automatic account-run contact fan-out; and
- any provider-specific branch in the entity controller/fleet.

Deletion is dependency-guided and staged after replay protection. No blanket reset or removal of
shared provider/substrate code is authorized by this roadmap.

## 16. Combined release criteria

M8D is complete only when:

1. The Head-of-ABM remains the only user-facing deepagent.
2. Every account/contact research unit is created with `langchain.agents.create_agent()`.
3. Account and contact research are separately confirmed and separately launched runs.
4. Both run kinds use one shared mechanical fleet substrate without duplicate implementations.
5. No provider request occurs before the responsible entity agent's governed tool call.
6. Every provider operation carries exact agent/tool/target causation.
7. Qualitative fields are not forced through nonexistent deterministic attempts.
8. Agents receive the complete persisted structured result or a complete index plus lossless read
   tools—not merely claim ids or a lossy summary.
9. Raw provider responses remain immutable even when all candidate claims are rejected.
10. Accepted, corroborating, conflicting, rejected, and null outcomes are visible to the agent.
11. Additive follow-ups carry exact parent operation/observation lineage and claim-level delta.
12. Independent tools may run concurrently; dependent calls cannot.
13. Account research produces an office-coherent committee or an explicit partial/review result.
14. The account fleet performs no contact deep research and returns control to the user.
15. Contact selection may include committee or non-committee identity-resolved contacts.
16. Contact agents run only for the exact selected contacts.
17. Optional facets are depth one, one or two children, non-recursive, and share the parent budget.
18. Channel reveal and independent validation remain separate and exact-contact/channel approved.
19. Only an accepted engine finalization receipt marks a job complete.
20. `NEEDS_REVIEW` is durable and human-resolved; it is not transcript-only state.
21. Waiting releases fleet slots and database transactions and resumes the same checkpoint.
22. Crash, concurrent duplicate, cancellation, and fresh-process replay perform no duplicate paid
    call or settlement.
23. Provider implementations remain behind replaceable seams; controllers and fleet contain no
    provider branches.
24. Live bounded account and contact canaries prove tool choice, follow-up, persistence, claims,
    committee/contact scope, finalization, cost, and replay using real providers and Postgres.

## 17. Expected effort and sequence

The working estimate is **12–18 focused engineering days** for one engineer, including bounded
live-provider acceptance. A provider contract surprise—especially Sumble entitlement or schema
drift—may add 2–4 days.

Indicative allocation:

| Work | Estimate |
|---|---:|
| R0–R1 contract, forbidden tests, cleanup/quarantine | 2–3 days |
| R2–R4 shared fleet/runtime/tools/result contract | 4–6 days |
| R5–R6 account agent and fleet | 2–3 days |
| R7–R8 contact selection, agents, and fleet composition | 2–3 days |
| R9–R10 concurrency, regression, crash/replay, live acceptance | 3–5 days |

The sequence is binding:

```text
R0 contract
  -> R1 cleanup/quarantine
  -> R2 shared fleet
  -> R3 create_agent runtime
  -> R4 governed tools + lossless results
  -> R5 account agent
  -> R6 account fleet and user return
  -> R7 contact selection/launch
  -> R8 contact agents on shared fleet
  -> R9 concurrency/wait hardening
  -> R10 cutover + adversarial/live acceptance
```

No implementation slice may claim completion from unit tests alone. Provider slices require the
appropriate bounded live call authorization and durable database/artifact evidence; replay must
prove zero additional provider traffic and spend.

## 18. Explicitly out of scope

- replacing the Head-of-ABM deepagent with `create_agent()`;
- an agentic scheduler or middle-orchestrator inside the fleet;
- a second duplicated fleet implementation for contacts;
- automatic discovery-to-account or account-to-contact progression;
- whole-account or whole-committee contact research without exact selection;
- unbounded recursive subagents;
- provider SDK access from prompts/agents;
- arbitrary general-purpose Exa browsing outside target-locked governed tools;
- treating an LLM final message as durable completion;
- bypassing identity, use, channel validation, spend, or human approval with configuration toggles;
- deleting historical exact-run resources before replay compatibility is proved; and
- rebuilding provider, claim, evidence, verification, identity, or governance infrastructure that
  already satisfies its contract.
