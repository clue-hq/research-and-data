# M06A D5 — Discovery batch seal and hard project-phase barrier

**Status:** implementation acceptance contract, including the 2026-08-03 post-review repair

**Parent:** `M06A-exa-websets-sumble-discovery-integration.md`, Slice D5

**Boundary:** D5 consumes the D1 lifecycle and D4 terminal identity/field ledger. It performs no
provider call and does not discover or enrich another account. The post-review repair also defines
the explicit no-numeric-scoring path immediately after the seal, because preserving the phase and
human barrier is part of making D5 non-bypassable. D6 remains unimplemented and owns the first
complete live production-composition acceptance.

## 1. Outcome

A project run that owns at least one durable discovery batch cannot move from `discovery` to
`scoring` unless its exact current generation is sealed. Completion has three mutually reinforcing
proofs:

1. D1's fourteen SQL predicates are true in the transaction that inserts the seal;
2. one immutable relational manifest bundle exactly matches the terminal candidate, claim, and raw
   artifact ledgers and is mirrored into content-addressed artifacts; and
3. the committed discovery checkpoint names that batch and seal hash before the database permits
   the project-run phase transition.

Runs with no durable discovery batch retain the pre-M6A discovery path. This compatibility clause
is not a bypass: creating the first durable batch permanently places that run under the D5 guard.
Production phase composition therefore remains seal-aware even when the Exa provider activation
flag is later disabled; that flag may stop new provider work but cannot strand or bypass a batch
that already exists.

## 2. Scope and ownership

| Concern | Owner | Rule |
|---|---|---|
| Fourteen readiness predicates and seal insert | `clue_research.durable.discovery` | Extend the D1 writer; do not create a second barrier |
| Manifest contract and sealed-account reader protocol | `clue_core.discovery` | Provider-neutral, body-free cross-package seam |
| Relational manifest bundle and generation controls | `clue_research.durable.discovery` | Workspace-scoped, immutable, replay-safe |
| Storage mirroring, discovery handler, concrete reader | `clue_api.discovery_seal` | API-root composition may combine durable, storage, and phase packages |
| Project phase transition enforcement | PostgreSQL migration | Direct SQL and alternative callers cannot bypass it |
| Scoring account input | `ScoringPhaseHandler` through the core reader seam | Durable runs read the sealed account manifest; no mutable discovery re-query |

No provider adapter imports the manifest builder or decides whether a batch is complete.

## 3. Current-generation rule

For `(workspace_id, project_run_id)`, the current batch is the row with the greatest generation.
All generations remain queryable and no durable batch generation can be deleted; this prevents a
caller from turning a durable run back into a legacy/no-batch run. The repository serializes
generation creation on the project-run row and applies these rules:

- exact replay of the same `(batch id, plan, generation)` is a no-op;
- a sealed current generation cannot be replaced;
- an active current generation requires the explicit replace operation before another generation
  can be created;
- a failed or cancelled current generation may be followed by a strictly greater generation and
  receives a one-time `replacement_batch_id` lineage edge; and
- a replacement uses the same project run, workspace, project, and ICP lineage, a newer immutable
  plan version, and the next generation number.

`failed_terminal` and `cancelled_unsealed` freeze their provider, item, candidate, field, and cost
children. The sole allowed post-terminal mutation is attaching the one-time replacement edge.

## 4. Pause, resume, cancel, and replace

- **Pause:** set only the batch to `paused_by_user`; due provider wakes for that batch are not
  claimable. Provider artifacts already received remain evidence.
- **Resume:** lock the paused batch and derive its truthful active state from its existing operation
  rows; no operation identity or receipt is reset.
- **Cancel:** atomically set `cancelled_unsealed`, record a reason, and retire unprocessed wakes.
  It can never seal or permit scoring.
- **Replace:** atomically cancel/freeze the old generation, create the new plan-bound generation,
  and attach the replacement lineage. The old facts remain immutable evidence.

Pause is resumable. Cancel and replace are terminal for the old generation.

## 5. Immutable manifest bundle

The relational bundle is one immutable row per batch with:

- contract version and exact workspace/run/plan/generation lineage;
- ordered canonical account ids;
- ordered supporting claim ids from the discovery field ledger;
- ordered provider/request/event/page/item artifact keys referenced by the batch;
- the four final artifact keys and SHA-256 values; and
- the coverage report payload used to create its artifact.

The four artifacts are canonical compact JSON:

1. `discovery-account-manifest-v1` — exact account membership and lineage;
2. `discovery-claim-manifest-v1` — every D4 claim rooted in the exact admitted item artifacts,
   including the discovery-provenance/evaluation claim, plus every field-resolution evidence claim;
3. `discovery-raw-artifact-manifest-v1` — exact durable raw receipt/evidence references; and
4. `discovery-coverage-report-v1` — requested, observed, admitted, excluded, and unsearched-channel
   counts without an exhaustiveness claim.

The bundle can be created only when readiness conditions 1–13 are true. The seal transaction then
proves condition 14 by checking that:

- all four artifacts exist in the same workspace, are live, and match their recorded hashes;
- manifest account ids equal the distinct admitted/merged survivor ids;
- manifest claim ids equal the discovery field-claim edges;
- manifest raw keys equal the operation/event/page/item artifact references; and
- the seal draft exactly matches the immutable bundle.

An exact replay reuses the bundle and artifacts. Different content for the same batch fails.

## 6. Discovery phase handler

The API-root handler first looks up the exact current batch for the phase context:

- no durable batch: delegate to the pre-M6A grounded discovery handler;
- active but not ready: return reference-only `WAITING_EXTERNAL` with blocker codes;
- `paused_by_user`, `failed_terminal`, or `cancelled_unsealed`: return a human-owned `PAUSED`
  result; never call it completed;
- ready through condition 13: build/reuse the manifest bundle and call the D1 seal writer in the
  same transaction; and
- sealed: return `COMPLETED` with only the batch id, seal hash, and four manifest references.

The D4 worker re-enqueues the owning project run after materialization. It does not itself seal or
advance the run.

## 7. Database project-run guard

A `BEFORE UPDATE OF phase` trigger on `project_run` rejects every attempt to skip one of the three
post-discovery phases:

- `discovery` may move only to `scoring`;
- `scoring` may move only to `tier_checkpoint`; and
- `tier_checkpoint` may move only to `deep`.

The original D5 seal trigger still guards `discovery -> scoring`. When the run has a durable
discovery batch, it rejects that transition unless:

1. the greatest generation belongs to the same workspace/project/run/ICP lineage;
2. that batch is `sealed` and has one matching `discovery_batch_seal`;
3. no replacement generation supersedes it; and
4. the immutable relational bundle and all four final artifact rows still exist, are live, match
   their recorded hashes, and match the seal; and
5. the committed discovery checkpoint payload contains the exact current batch id and seal hash.

This guard protects calls that bypass `ProjectRun`, direct repository calls, and crash replay
between checkpoint commit and phase transition. The sequence trigger additionally requires a
committed scoring checkpoint before `scoring -> tier_checkpoint`, and an approved, resumed,
committed human checkpoint before `tier_checkpoint -> deep`.

## 8. Sealed manifest reader and scoring

The concrete reader:

1. finds the exact current batch for `(workspace, run, ICP)`;
2. requires its seal and immutable manifest bundle;
3. loads the account-manifest artifact;
4. verifies its content hash and all lineage/count fields against the seal and relational bundle;
5. loads and verifies the claim manifest and exact claim ids;
6. verifies the relational survivor set still equals the immutable account-id list;
7. loads the immutable plan's required criteria and required account fields; and
8. returns the ordered account ids, claim ids, plan criteria, and terminal required-field
   resolutions plus seal references.

`ScoringPhaseHandler` uses this reader when a durable batch exists. It falls back to the historical
discovery-provenance query only when the reader reports that the run has no durable batch. An
unsealed, stale, cross-workspace, replaced, erased, or tampered manifest fails closed.

## 9. Explicit no-numeric-scoring policy

The agreed temporary bypass is policy-as-data on the pinned ICP version:

```json
{
  "scoring_mode": "disabled",
  "selection_mode": "discovery_criteria",
  "must_have_criteria": ["..."],
  "approved_tier": "high"
}
```

Both mode values must be present together. The normalized `must_have_criteria` set must equal the
criteria frozen in the exact discovery plan; an omitted or additional criterion fails the phase
instead of selecting too broadly.

Under this policy, `SCORING` remains a real, durable phase but performs no Pass-A waterfall,
provider call, or numeric fit/intent write. It classifies only the exact sealed account set:

| Observation | Disposition |
|---|---|
| Every required criterion is `yes` and every required field is `resolved` | `selected` |
| Any required criterion is `no` | `excluded` |
| Any required criterion is `unclear` or absent | `hold` |
| Any required field is terminal missing or conflict | `hold` |

The checkpoint exposes every criterion observation, provider reasoning, reference URL, evidence
claim id, and required-field terminal state. Human approval may select all eligible accounts or an
explicit subset. A hold/excluded/unknown account cannot be approved. Approved accounts receive a
human-source `account.scoring.tier` claim whose `decision_basis` is `discovery_criteria`, bound to
the exact project run, ICP version, discovery batch, seal, policy version, and decision version.
No fit or intent number is synthesized. Deep composition consumes only those current-run approved
tier claims.

`ScoreAccountsTool` requires the persisted run itself to be active in `scoring`, both during
precondition evaluation and immediately before invocation. Possessing a valid seal while the run
is still in `discovery` is insufficient.

## 10. Acceptance matrix

| Case | Required proof |
|---|---|
| Each of fourteen blockers | Production seal call fails and DB rejects the same run's scoring transition |
| Final blocker resolved | Handler commits one manifest bundle and one seal; same run reaches scoring once |
| Handler replay | Same seal/artifact refs; no additional rows or content |
| Direct transition bypass | PostgreSQL rejects it without the exact committed checkpoint payload |
| Batch deletion bypass | PostgreSQL rejects deletion of active and terminal generations |
| Late event | Born `late_after_seal`; membership, fields, manifests, and seal remain byte-identical |
| Manifest tamper/erasure | Reader and transition fail closed |
| Scoring input | Exact sealed account ids are read; mutable/unsealed candidates are invisible |
| Policy/plan drift | Missing or extra must-have criterion fails closed |
| Criteria bypass | No numeric claims or provider calls; yes/unclear/no and required-field states map to selected/hold/excluded |
| Human subset | Only selected accounts receive current-run, seal-bound tier claims |
| Scoring tool crash window | Tool refuses while the persisted run remains in discovery, even when the seal already exists |
| Later phase skips | DB rejects discovery -> deep, scoring -> deep, and tier checkpoint -> later phases without their committed gates |
| Pause/resume | No paused wake is claimed; resume preserves operation identity and derives state |
| Cancel | Old generation is terminal, unsealable, and child-immutable |
| Replace | Old generation keeps evidence and points to the new current generation |
| Concurrent/restarted seal | One identical bundle and seal |
| Migration | One Alembic head; clean head -> base -> head |

## 11. Gate D5

D5 passes only when real PostgreSQL and filesystem storage prove the entire matrix. Unit fixtures
alone cannot close it. No Exa or Sumble call is required or permitted for this slice; already-paid
D2/D3 artifacts may be consumed only through their durable references.
