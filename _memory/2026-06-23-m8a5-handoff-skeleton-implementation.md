# M8A.5 — Per-account handoff skeleton (references-only, (account,persona)-keyed) — implementation

**Date:** 2026-06-23 · **Branch:** `m8a/handoff-skeleton-v2` (off the M8A.1 trunk = `m8a/orchestrator-v2`
@ `b8a51cb`) · **Spec:** `docs/specs/M8A-campaign-run-deep-orchestration.md` §M8A.5 · **Brief:**
[[2026-06-23-m8a5-handoff]] · **Trunk:** [[2026-06-23-m8a1-orchestrator-implementation]].

The references-only `(account, persona)`-keyed join that proves a deep-researched account is
**M12-ready**. NOT the final `AccountHandoff` (that is M12.2's read over the claim store).

## Why a NEW branch (not `m8a/handoff-skeleton`)
- `m8a/orchestrator` has **M8A.2 being implemented in parallel** — the user asked for an independent
  branch. Created `m8a/handoff-skeleton-v2` off the current trunk (`m8a/orchestrator-v2`).
- The pre-existing `m8a/handoff-skeleton` / `-v1` branches are a **divergent older attempt** on a
  different base (the `m8/deep-profiling` composition root + Option-C gate work) — they predate
  `AccountDeepResult`, so their `build_handoff_skeleton(committee_result, contact_results,
  account_result)` 3-arg signature is the wrong shape for this trunk. NOT used as a base.
- Pulled the brief `_memory/2026-06-23-m8a5-handoff.md` from `m8a/orchestrator` into this branch.

## What shipped (one new file + exports + test; NO `orchestrator.py` edit — conflict-free with M8A.3)
- **`api/deep/handoff_skeleton.py`** — pure function `build_handoff_skeleton(result:
  AccountDeepResult) -> AccountHandoffSkeleton` (the brief's exact signature) + two frozen models:
  - `AccountHandoffSkeleton` — header `(account_entity_id, tier, account_run_id)`; `committee:
    tuple[core.handoff.CommitteeMember, ...]` (the M12-ready join — each shell from
    `CommitteeResult.committee()` with its `profile_claims` joined on by `contact_entity_id` via
    `model_copy`); `coverage: CommitteeCoverage | None`; `cost_cents`; `references_index:
    dict[str, tuple[ClaimId, ...]]` (ids-only, sections `account` / `committee` / `contact:<id>`);
    `claim_refs` flat property; `manifest()` method.
  - `DeepCompleteManifest` — the **references-only payload surface** for M8A.2's
    `PhaseResult.payload`: `account_run_id`, `committee_member_ids`, `coverage`, `cost_cents`,
    `references_index` — **no `value_json` anywhere**. `manifest()` drops the committee join (whose
    `ProfileClaimView`s carry `value_json`) down to member ids.
- **`api/deep/__init__.py`** — exports `AccountHandoffSkeleton`, `DeepCompleteManifest`,
  `build_handoff_skeleton` (additive; existing M8A.1 exports untouched).
- **`tests/api/deep/test_handoff_skeleton.py`** — 9 fake-driven tests (no DB), constructing
  `AccountDeepResult` directly with a planted `_LEAK_MARKER` in every contact `value_json`.

## Key design decision — the value_json boundary (resolves the AC2 vs AC1 tension)
- AC1 needs the committee members to carry `profile_claims` (the `core.handoff.CommitteeMember`
  shape **is** `tuple[ProfileClaimView, ...]`, which includes `value_json`) so M12.2 can JOIN.
- AC2 needs `references_index` AND the `PhaseResult.payload` to be **ids-only** (no `value_json`).
- **Resolution:** the in-memory `committee` join legitimately carries `value_json` (it is the
  M12-ready structure, already present in `AccountDeepResult.contacts[].profile_claims` — M8A.5
  re-keys, introduces no new leak). The **two ids-only surfaces** are `references_index` and
  `manifest()`. The regression test asserts the marker appears in neither (`references_index.__repr__`
  + `manifest().model_dump_json()`), and a positive test asserts the committee join DOES carry it.
- So M8A.2 MUST emit `skeleton.manifest()` into `PhaseResult.payload`, never the whole skeleton.

## Other decisions
- `references_index` mirrors the **orchestrator's handoff-relevant** persisted keys (`account` /
  `committee` / `contact:<id>`) and **omits `committee_contacts`** — that key is the orchestrator's
  internal resume work-list (member ids), not a handoff section. The skeleton's index is its own
  typed view (`tuple[ClaimId]`), recomputed from the in-memory result, not a copy of the durable
  JSONB (`list[str]`).
- **Resume / in-memory-result semantics (documented limitation):** built from THIS run's
  `AccountDeepResult`. On a resumed run a prior run's stages are `None` in the result, so the skeleton
  drops the committee + account/committee sections (it reflects only what this run produced). The
  durable, cross-run M12-ready source is the persisted `account_run.references_index` + the claim
  store, which M12.2 reads. If M8A.2 wants a complete payload on resume, it can merge the loaded
  `DeepRunState.references_index` (it holds the `io`); out of M8A.5's `build-from-AccountDeepResult`
  scope. Tested by `test_resumed_result_yields_a_partial_in_memory_skeleton`.
- **Partial, never failed:** budget-DENY / marginal-yield-stop / empty-committee all carry the
  `CommitteeCoverage` band (+ `channels_not_searched`) through; no path returns a FAILED handoff.
- **No new table, no DB read, no scores/narrative/provenance** (AC4 structurally guaranteed — the
  model has no such fields; a test asserts the exact field set).

## Adversarial review (workflow `wf_4a2e1ae9-a8e` — 6 lenses × verify, 11 agents)
- **1 confirmed (major→applied as a consistency fix):** the `references_index` contact loop
  re-iterated raw `result.contacts` while the committee JOIN used the de-duplicated `by_contact`
  dict — an asymmetry. **Fix:** iterate `by_contact.values()` for the index too, so the two surfaces
  are provably consistent. Behavior-identical under the guaranteed-unique invariant; no contrived
  duplicate-input test added (that would wrongly imply M8A.5 owns dedup).
- **4 rejected (all the same duplicate-`contact_entity_id` theme):** `discover_committee` guarantees
  unique member ids upstream (`seen_contact_ids`, `committee/worker.py:273-275`), so `result.contacts`
  is unique by construction — M8A.5 consumes M8A.1's validated output and shouldn't own input
  validation. A "whole-skeleton serialization leak" was rejected as M8A.2's integration concern (M8A.5
  documents `manifest()` as the only payload surface).

## Verification (all green)
- ruff (lint + format), mypy (199 src files, success), import-linter (**11/0** — `api/deep` composes
  `core`+`profiling`; nothing imports `api`).
- `tests/api/deep/` = **18 passed** (9 orchestrator + 9 handoff-skeleton). All pure-Python fakes, no DB.

## Follow-ups (downstream)
- **M8A.2** `DeepPhaseHandler`: call `build_handoff_skeleton(deep_result)` and put
  `skeleton.manifest()` (NOT the whole skeleton) in `PhaseResult.payload`. Optionally merge the durable
  `DeepRunState.references_index` for a complete payload on a resumed run.
- **M12.2** `HandoffAssembler`: JOIN `profile_claims` by `contact_entity_id` from the skeleton (or
  recompute on read from the durable `account_run.references_index` + claim store).
- Branch is local-only (no push, no AI attribution), per repo conventions.
