# M8D R4 — Governed tools and complete persisted result acceptance

> **Status:** accepted for R4 on 2026-08-06.
>
> **Scope:** semantic account/contact tool composition, agent-tool request authority,
> provider-operation causation, complete persisted result projection, lossless scoped reads,
> replay/follow-up lineage, and contact-result erasure. R5 account-agent behavior and production
> cutover remain uncomposed.

## 1. Governed semantic tool composition

`GovernedEntityResearchToolFactory` composes the exact R3 account or contact tool surface from:

- engine-owned state, plan, evidence-read, delegation, and finalization tools; and
- provider-capable semantic actions behind one provider-neutral action protocol.

The model supplies only admitted field keys, source keys, confirmed questions, and optional
complete follow-up lineage. Workspace, project, product, project run, research run, job, target,
parent account, field/source plan, budget key, agent turn, and tool-call identity come from the
active R3 runtime context. Those authority fields do not exist in the model-facing input schema.

Composition must equal the complete frozen R0 surface. Provider-capable tools cannot be smuggled
in as ordinary engine tools, provider SDKs are not exposed, and account/contact/facet calls share
the same task-local runtime seam without authority leaking between concurrent handlers.

## 2. Journal-before-dispatch causation

An admitted R3 `tool_started` event is projected into immutable
`entity_research_tool_request` state. Database enforcement proves that the request matches the
exact turn, execution, job, run, subject, target, tenant scope, tool name/version/input digest,
field axis, and journal timestamp.

The external acquisition coordinator exposes a provider-neutral `before_dispatch` seam. The
semantic action first reserves the durable provider operation, then records its unique `caused`
observation, and only then may the coordinator claim a dispatch attempt. Database triggers reject
late causes and cross-workspace/project/run/source/target operations. A failed causation callback
leaves the operation `planned`, writes no attempt, and makes zero provider calls.

Reuse and joining are observations, not causes. A later tool request records
`replay_observation` or `joined_observation`; it never claims that it caused the original spend.
Chronological reads expose agent-turn start, tool-call journal, operation reservation, and provider
dispatch timestamps.

## 3. Complete result persistence before return

A provider action returns a normalized projection draft only after the existing acquisition and
claim services finish. `EntityResearchResultStore` validates and persists, inside the governed
scope:

- the request artifact;
- raw provider response and retained provider-result artifacts;
- normalized snapshot artifact;
- settled provider receipt and both reported and settled cost;
- every requested field exactly once, including found, null, unsupported, conflict, and rejected
  outcomes;
- candidate-claim delta and exact claim/decision references;
- claim target, field, workspace, operation, snapshot, verification, and evidence provenance;
- evidence source identity, retained artifact, exact span, and digest; and
- the complete content-addressed result artifact plus any separately indexed field values.

No successful tool message is returned until those records and artifacts exist. Small results are
`inline_complete`. Large results are `indexed_complete`: the agent still receives the complete
field/outcome/claim/evidence/cost/lineage index, while `read_research_result` restores all values
losslessly and `read_evidence` pages the retained evidence. Both reads enforce the exact current
job, target, workspace, and research run.

All R4 relational history is append-only. Stable evidence identity may recur across replay results
without creating a false uniqueness failure. Result/value artifacts are subject-indexed, and
contact erasure tombstones and purges those lossless projections through the existing DSAR path.

## 4. Exa contact composition proof

The first concrete semantic action reuses the existing governed Exa contact compiler,
acquisition coordinator, immutable snapshot/receipt ledger, contact materializer, claim store, and
verification state. It narrows compilation and materialization to the exact fields and questions
selected by the tool call.

One complete R3 `create_agent()` turn was executed against real isolated Postgres with the Exa
fixture transport:

1. the model called `research_contact_deep`;
2. the R3 journal and R4 tool request were persisted;
3. Exa request reservation and causation were persisted outside provider I/O;
4. one fixture-provider call produced raw and normalized snapshots plus one settled receipt;
5. exact-contact claims and evidence were materialized;
6. the complete indexed result reached the model;
7. lossless result/evidence reads recovered the retained content;
8. a fresh turn replayed with zero new provider call or receipt; and
9. an explicit additive follow-up created a distinct operation/snapshot/receipt linked to the
   parent operation, parent result, and typed reason.

The repeated Exa observation is not represented as independent-source corroboration. It remains
an accepted candidate with explicit follow-up lineage; independent corroboration remains a claim
engine decision.

## 5. Database and migration contract

Migration `f643425d0be4` adds the request, provider-observation, result, field, and evidence tables;
cross-scope/ordering triggers; exact indexes; and append-only guards. During the fresh-database
proof, the R2/R3 migrations were corrected to use the authoritative text identifiers for
workspace, project, and product while retaining UUIDs for runs, jobs, and entities. This prevents
R4 from inventing a second identifier mapping at composition time.

The isolated database upgraded from base to the single R4 head. The R4 head downgraded to R3 and
upgraded again successfully; `alembic heads` reports only `f643425d0be4`.

## 6. Verification evidence

The focused no-database contract/runtime suite covers schema authority, exact account/contact
surfaces, provider-tool ownership, concurrent task isolation, R0 compatibility, and the retained
C3/C4 contracts.

The isolated-Postgres battery passed 63 cases spanning:

- R2 run/job scope, queue, migration, and replay;
- R3 construction, journal, checkpoint, and finalization;
- C2 external-operation durability;
- E1/E2 Exa acquisition and account materialization;
- C3/C4 contact compilation, acquisition, target rejection, crash/replay, cancellation, and
  materialization;
- R4 result projection, causation failure, replay, follow-up, append-only mutation rejection,
  scoped reads, and subject erasure; and
- the existing DSAR/retention regression surface.

Ruff and scoped mypy pass on the R4 source. The R4 migration down/up cycle and one-head check pass.

The repository-wide typecheck also passes all 549 source files and all 24 import contracts pass.
The whole-repository test run is not green for two known pre-R4 expectations: the O2 launch test
still expects a new legacy `launch_account_deep`, and the Sumble trial test still expects the
legacy DEEP handler to complete. R1 correctly makes both new-run paths fail with
`entity_research_agent_not_composed` until R5 composes the replacement. The whole-repository
format check also reports unrelated files outside R4; they were not rewritten. Neither
condition affects the focused R4 or 63-case database gate, and neither can originate a provider
operation through R4.

No credentialed provider endpoint or paid call was used in R4 acceptance. The fixture transport
executes the actual provider boundary and proves transaction/causation/settlement plumbing without
spend. Bounded live-provider acceptance remains R10. R1's fail-loud production quarantine remains
in force; R5 owns the account-agent behavior and organization-map/committee composition that will
consume these tools.
