# M8D R5 — Account research agent acceptance

> **Status:** accepted for R5 on 2026-08-06.
>
> **Scope:** one bounded account `langchain.agents.create_agent()` unit, governed account
> research/enrichment/committee tools, result-informed runtime decisions, account+committee
> coverage/review/finalization, and the persistence needed to prove the R5 exit gate. R6 still
> owns production-fleet cutover, and R10 owns credentialed live-provider acceptance.

## 1. Exact account-agent composition

`AccountResearchDefinitionResolver` constructs one role-specific R3 definition only for an exact
leased account job and the content-addressed `agent-profile:account-research:v1` resource. Its
model-facing surface is exactly:

- account state and evidence reads;
- `research_account_deep`;
- `enrich_account`;
- `discover_buying_committee`;
- coverage assessment; and
- account finalization.

The unit is constructed through `langchain.agents.create_agent()`. It has no contact-research,
contact-enrichment, channel-reveal, or contact-finalization tool. Workspace, project, product,
project run, research run, job, account identity, directive, effective field/source plan, budget,
and approval authority remain hidden in the R2/R3 context. R5 does not restore any R1-quarantined
legacy orchestration and is deliberately not registered as the production fleet resolver; R6
owns that cutover.

## 2. Dynamic, result-informed account research

The executable acceptance model follows the same observation loop required of a production
account mind:

1. read the current durable account-research state;
2. call Exa Deep for the selected qualitative fields;
3. inspect the complete persisted field, evidence, claim-delta, lineage, and cost result;
4. identify that the independent structured hiring field remains unresolved;
5. call Sumble structured enrichment only for that field;
6. use grounded account evidence to define the same-office buying-unit scope;
7. call Sumble committee discovery;
8. assess complete account+committee coverage; and
9. submit a typed finalization proposal.

The test model records why it chose the second provider: the first result resolved operational
pain and strategic moves but not hiring velocity. This proves that the next action is based on the
observed result, rather than a hard-coded universal source ladder.

## 3. Exa qualitative research and additive follow-up

`ExaAccountSemanticResearchAction` reuses the E1 acquisition coordinator, immutable Exa snapshot
and receipt state, E2 snapshot resolver/materializer, field registry, effective source plan,
claim store, and R4 complete-result projection.

The first Exa call must bundle every selected Exa-applicable account field. The engine rejects a
single-field first call when another selected Exa field is eligible, eliminating the old
field-by-field mechanical progression. The action submits only the exact fields and sources
authorized by the content-addressed field/source relation. A normalized field that does not
materialize a claim fails loudly instead of being represented as successful research.

An explicit follow-up remains additive: it carries the parent operation, parent result digest,
typed reason, bounded prior-result context, and a distinct observation window. Reuse is still
zero-call/zero-charge and is recorded as an observation of the original provider operation, not a
new cause.

## 4. Independent Sumble enrichment and office-coherent committee formation

Structured account enrichment is a separate semantic choice. The Sumble account action reuses the
S1 organization/jobs/technology acquisition and materialization services, records R4 causation
before dispatch, preserves exact snapshot/claim/source lineage, and returns a complete persisted
field projection. Sumble People is separately authorized as a committee source; it is not
manufactured into every account field's source set.

The committee action reuses durable Teams/People acquisition and the provider-neutral committee
worker. The agent must provide a grounded `AccountBuyingUnitScope`. Candidate selection compares
location, facility, business unit, team, and job function as separate dimensions, so a matching
word in one dimension cannot satisfy another. A candidate is admitted only when current
People-derived professional facts support the exact office/buying unit. Wrong functions are
excluded; wrong-office or ungrounded-office candidates remain ambiguous and create review work.

The complete result projects each identity-admitted contact and its account association without
launching contact research. A genuinely empty provider response is represented by the explicit,
persisted `confirmed_empty_discovery` state; an absent or incomplete result cannot masquerade as
a grounded empty committee.

## 5. Coverage, review, and finalization

`AccountResearchStateStore` derives current state from persisted R4 results rather than model
prose. Coverage assessment must include the complete current result set and refuses to close over
pending provider work or any contact-research request. It records:

- selected and unresolved account fields;
- exact account and committee result references;
- committee status and buying-unit scope;
- unresolved reasons, exclusions, and ambiguity; and
- current state and spend references.

Coverage and finalization intent are append-only. Ambiguity produces durable review items; model
text cannot authorize ambiguity away. `AccountResearchFinalizationEngine` re-reads the exact job,
current-state digest, results, evidence, claims, provider settlements, coverage, and contact-call
count before issuing the engine-owned receipt. A completed receipt requires grounded selected
fields, a complete or explicitly confirmed-empty committee, consistent settled spend, and zero
contact deep research.

## 6. Persistence and spend correctness

Migration `85595185f793` adds:

- provider-reported and settled cost plus explicit-empty state to complete research results;
- subject-aware result-field uniqueness for multi-person committee projections;
- immutable Sumble normalized projections;
- account buying-unit scope, coverage, review, and finalization-intent records; and
- an append-only provider-settlement fold keyed by provider operation.

The settlement fold is operation-idempotent. A replay result may point to the same immutable
provider settlement, but it cannot charge the entity job or run a second time. A different job,
run, or cost attempting to reuse that fold fails. The result row, fold record, and mutable budget
counters commit atomically.

The dedicated database upgraded to the single `85595185f793` head, downgraded to `5764311c620d`,
and upgraded to the head again successfully.

## 7. Verification evidence and boundary

The focused pure R0–R5 contract/runtime battery passed 92 tests. The full R2–R5 Postgres battery
passed 12 tests. A retained Exa/Sumble/R4 compatibility matrix passed 22 tests, covering R4
causation/replay/follow-up, E2 account materialization, S1 Sumble account gaps, and S2 committee
acquisition/source behavior. The final post-migration R5/replay smoke passed four tests.

The R5 exit test proves one account agent:

- was built through `create_agent()` exactly once;
- observed a complete first Exa result;
- made and recorded a justified second provider choice;
- used one bundled Exa request and separate structured/committee operations;
- finalized three selected account fields and a two-person same-office committee;
- settled 8.75 cents across three distinct provider operations; and
- created zero contact-research tool requests.

Ruff passes on the R5 set. Scoped mypy passes, repository-wide mypy passes all 553 source files,
and all 24 import contracts are kept. One unrelated pre-existing whitespace error in
`docs/architecture/clue-hq-content-and-artifact-scaling.md` prevents a clean whole-worktree
`git diff --check`; R5 does not modify or normalize that user-owned edit.

No credentialed or paid provider endpoint was called for R5. The acceptance uses real Postgres,
the production acquisition/materialization/claim/causation/result plumbing, and deterministic
fixture transports at the provider boundary. This is implementation acceptance, not live-provider
acceptance. R10 remains the separately authorized bounded live Exa/Sumble canary.
