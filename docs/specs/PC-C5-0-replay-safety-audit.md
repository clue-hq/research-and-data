# Phase C5.0 — Versioned Tool Contract and Replay-Safety Audit

**Status:** implemented on `platform/c5-recipe-execution` (2026-07-24)

**Parent:** [`PC-C5-run-graph-recipes-executor.md`](./PC-C5-run-graph-recipes-executor.md)

## 1. What this checkpoint freezes

C5.0 is the contract-only prerequisite to durable execution. It adds no execution tables,
migration, journal repository, recipe loader, scheduler, or executor.

It freezes:

- exact tool addresses as `(name, version)`, with a composition-declared name-only default;
- immutable input and output JSON-schema digests on `ToolDescriptor`;
- strict, reference-only `ToolOutput` models for every currently registered tool;
- a stable `operation_id` on every `ToolContext`;
- replay policy, effect class, external-boundary residual, safe journal fields, pin requirements,
  and steering-snapshot capability per exact tool version;
- closed execution/recipe/pin/event/control vocabulary in `clue_execution`, without persistence.

`ToolRegistry` never guesses a default by lexically or numerically sorting versions. A caller
either requests an exact version or receives the single default explicitly selected by the
composition root. Idempotency records include `name@version`, so one key cannot replay a result
from a different implementation version. C4's narrow `RecipeStep` now requires `tool_version` and
passes it through exact resolution; only ad-hoc name-only callers use the declared default.

The runner validates a tool's result against the descriptor's strict output model before marking
the short-lived A9 invocation complete. A schema mismatch releases the reservation and fails
loudly; it cannot become a cached successful result.

## 2. Replay vocabulary

- `effect_free`: no durable or external effect; safe to recompute.
- `domain_idempotent`: the domain already has a natural key, phase ledger, desired-state guard, or
  immutable equality check that makes a repeated call converge.
- `operation_idempotent`: identities that were previously minted inside the tool now derive from
  the caller-stable `operation_id`.
- `at_least_once`: the tool has no confirmed duplicate database write, but a provider call may be
  accepted more than once across the provider-accept/commit crash window. C5 does not claim
  exactly-once behavior at that boundary.

The external-boundary column is independent of database replay safety. `at_least_once` there is an
explicit residual, not a failure to audit the tool.

## 3. Standing Recipe #0/#1 audit

The table below is generated conceptually from
`clue_api.recipe_contracts.build_replay_safety_audit`. The architecture test resolves every
address exactly and fails if any standing tool lacks a typed output, schema digest, pin
requirements, replay certification, or required steering snapshot.

| Exact tool | Recipe | Typed output | Effect / replay | Durable replay identity | External residual |
|---|---|---|---|---|---|
| `adjust_budget@1` | #1 | `ProjectRunBudgetOutput` | steering / domain | project run + desired budget-cap diff guard | none |
| `compose_handoff@1` | #1 | `HandoffOutput` | read / effect-free | project-run handoff projection | none |
| `confirm_icp@1` | #0, #1 | `ConfirmIcpOutput` | write / domain | workspace + ICP key + compiled-selection equality | none |
| `confirm_project_product@1` | #0 | `ProjectProductOutput` | steering / domain | immutable project product selection | none |
| `discover_accounts@1` | #1 | `DiscoverAccountsOutput` | spend / domain | project run + discovery phase ledger + deterministic discovery run | provider at-least-once |
| `estimate_project@1` | #1 | `ProjectEstimateOutput` | read / effect-free | validated inputs + pinned estimate policy | none |
| `evaluate_stage0_readiness@1` | #0 | `Stage0ReadinessOutput` | write / operation | `ReadinessDecisionId(operation_id)` | none |
| `import_accounts@1` | #1 | `ImportAccountsOutput` | spend / operation | import-batch id derived from `operation_id` | resolver at-least-once |
| `override_stage0_readiness@1` | #0 | `Stage0OverrideOutput` | steering / domain | unique readiness-decision override | none |
| `pause_run@1` | #1 | `ProjectRunStatusOutput` | steering / domain | desired project-run status `PAUSED` | none |
| `profile_contact@1` | #1 | `ContactProfileOutput` | spend / operation | contact + account + `RunId(operation_id)` | provider at-least-once |
| `record_interview_answer@1` | #0 | `InterviewAnswerOutput` | spend / operation | onboarding input + deterministic statement ids + `RunId(operation_id)` | extraction at-least-once |
| `resolve_committee@1` | #1 | `CommitteeOutput` | spend / operation | account + `RunId(operation_id)` | provider at-least-once |
| `resume_run@1` | #1 | `ProjectRunResumeOutput` | steering / domain | desired status `ACTIVE` + queue single-flight | none |
| `reverse_profile@1` | #1 | `ReverseProfileOutput` | spend / operation | workspace client identity + `RunId(operation_id)` | resolver at-least-once |
| `run_deep_account@1` | #1 | `DeepAccountOutput` | spend / operation | account + `RunId(operation_id)` + project/account ledgers | provider at-least-once |
| `run_verification@1` | #1 | `PhaseAccountsOutput` | spend / domain | project run + verification phase/account ledgers | provider at-least-once |
| `score_accounts@1` | #1 | `PhaseAccountsOutput` | write / domain | project run + scoring phase ledger | none |
| `start_confirmed_project_run@1` | #0 | `ConfirmedProjectRunOutput` | write / operation | `ProjectRunId(operation_id)` | none |
| `start_project_run@1` | #1 | `ProjectRunStartOutput` | write / operation | `ProjectRunId(operation_id)` | none |
| `start_recon@1` | #0 | `ReconOutput` | spend / at-least-once, operation-bound | `ReconRunId(operation_id)` when newly created; a live equivalent recon may be shared | resolver at-least-once |
| `submit_onboarding_input@1` | #0 | `OnboardingInputOutput` | write / operation | `OnboardingInputId(operation_id)` | none |
| `submit_tier_checkpoint@1` | #1 | `TierCheckpointOutput` | steering / domain | project run + tier-checkpoint phase ledger | none |
| `synthesize_icps@1` | #0, #1 | `SynthesizeIcpsOutput` | spend / at-least-once | reference-only completion; no confirmed ICP write | model at-least-once |

## 4. Important boundary findings

The audit changed the actual capability contracts:

1. Run-, recon-, input-, interview-, import-, readiness-, deep-, committee-, and contact-start
   identities no longer come from a fresh UUID inside a retryable tool body.
2. `start_recon` and readiness evaluation accept an explicit durable id and return the existing
   immutable result on an exact replay. Recon also retains its cross-operation live-dedupe rule:
   when it shares an older equivalent row, the new operation id is not that row's primary key.
   Its overall certificate is therefore honestly `at_least_once` until C5.1 durably journals the
   shared completion.
3. Pause, resume, product confirmation, readiness override, tier checkpoint, and budget adjustment
   expose display-safe before/after snapshot hooks. A steering descriptor without one is rejected.
4. Provider-facing tools retain an honest at-least-once residual. Stable database identities do
   not turn a provider without an idempotency key into exactly-once infrastructure.
5. `synthesize_icps@1` is the weakest standing contract: it makes no confirmed database write, but
   its model call can repeat until C5.1 can durably replay a completed invocation. That limitation
   is explicit and is not hidden behind the 24-hour HTTP cache.

## 5. Gate

- every registered tool has a strict typed output descriptor;
- every standing Recipe #0/#1 address resolves exactly;
- every standing address has non-empty pin requirements and a replay certificate;
- all operation-idempotent tools declare `operation_id_required`;
- all steering tools provide a snapshot hook;
- contradictory replay/external-boundary combinations fail at construction;
- no Alembic file or executor/runtime route is added by C5.0.

The next allowed slice is C5.1: the append-only journal and required production toolbelt writer.
