# 2026-08-08 — FI-2 slice 3, Task 1: §6.4 project-scoped supersede predicates

Branch `platform/frontend-integration`. Spec: `docs/specs/FI-2-workspace-account-layer.md` §6.4;
plan: `docs/specs/FI-2-slice3-implementation-plan.md` Task 1. No migration (head `870fe4f2af87`).

## The change

A second project researching a shared account no longer destroys the first project's lens.

- **One shared rule**, `claimstore/run_lineage.py::project_supersedable(prior, mine)` — the
  *write-side* half of the project dimension (`project_run_ids` is the read-side half). Same
  project → supersedable; different project → never; **unstamped prior → supersedable** (the
  legacy rule, argued below).
- **Narrative** (`narrative/positioner.py`): `position(..., project_id=None)` stamps
  `value_json["project_id"]`; `_live_for_persona` gained the project leg. `_write_narrative` now
  uses `supersede_claims` (many→one) instead of `supersede_claim(live[0])`, so a legacy claim
  sitting alongside this project's own prior is collapsed rather than left live.
- **Tier** (`discovery_scoring/tiering/engine.py::persist_tier`): new optional `project_id`
  stamped into the payload; `ctx.project_id` threaded at the one call site (`phases.py`).
- **Predicate home** = `discovery_scoring/claim_writes.py` (`claim_project_id` + the predicate leg
  in `write_icp_scoped_claim`), NOT duplicated in the tiering engine — that module owns the shared
  score-family write protocol. The scoring engine writes through the same protocol and is unaffected
  today (it stamps no `project_id`), but is now protected the moment it does.
- **Value schemas** documented the new key: `narrative/fields.py` + `account.scoring.tier` in
  `claimstore/packs.py`.

## Decisions

**Pin on `project_id`, not `project_run_id`.** The score family already pins `project_run_id`; the
tier must not — a project re-tiers across successive runs and must keep exactly one live tier
(within-project supersession is required to behave exactly as before §6.4). `project_id` is the
right granularity for both tier and narrative.

**Legacy (unstamped) claims are absorbed by the FIRST project that touches them.** The alternative
(never supersede an unstamped claim) leaves a permanently live, unattributable claim competing in
every project's `current_value` forever. Absorbing keeps the one-live-winner invariant, is a no-op
for a single-project workspace, and costs the legacy claim only its liveness (the row is retained,
superseded — append-only history intact). All databases hold synthetic dev data (B3 ruling), so no
real lens can be harmed. Rationale is written into `project_supersedable`'s docstring.

**Committee: no §6.4 write work remains.** Verified — `profiling/committee/` contains **zero**
`supersede` calls and no supersede exists on `contact.persona` / `contact.role_on_committee`
anywhere; the writes are pure `insert_claim` append-per-run. Cross-project destruction is
structurally impossible, so the spec §11 item-2 "optional within-project supersede refinement" was
deliberately NOT built (nothing is broken without it, and adding a supersede would introduce the
very hazard §6.4 removes).

## Consumer fix + known gaps

- **Fixed:** `platform/api/clue_api/deep/composition.py::build_high_tier_resolver` read
  `live[0]` = "the most recent live tier claim". With coexistence that can be another project's, so
  a P1 phase would have silently skipped the account. New `_live_tier_for_project` helper picks this
  project's live tier (an unstamped legacy tier is honoured by any project). Unit-tested.
- **Documented gap (NOT fixed):** `narrative/handoff.py::_value_narratives` has no project filter,
  so an account targeted by two projects would put both projects' narratives in one handoff.
  Unreachable today (M12.1 positioner uncomposed; HANDOFF parked fail-closed) and closing it needs a
  contract decision — the sibling `_read_score` filters on `project_run_id` while the narrative pins
  the coarser `project_id`. Note lives in the method docstring; do it when the positioner is
  composed / handoff is unparked.
- **Operational:** both value-schema edits change `field_definition.value_schema`, and the registry
  compares it — so re-running pack load against a **pre-existing seeded database** raises
  `FieldRedefinitionError`. Per the B3 synthetic-dev-data ruling the remedy is a DB reset/re-seed
  (same class as slice 0's FieldDef contract-delta). Fresh DBs are unaffected.

## Tests / gate

Red-first: today's cross-project destruction reproduced (2 live tier writes → **1** live claim).
Added 3 tier tests (`tests/discovery_scoring/test_tiering.py`), 3 narrative tests
(`tests/narrative/test_positioner.py`), 1 resolver unit test (`tests/api/deep/test_deep_composition.py`)
— coexistence asserted **through the `run_lineage` predicate**, same-project supersession unchanged,
legacy-absorb proven in both families.

Gate: `tests/narrative tests/discovery_scoring tests/claimstore` green; `tests/api/deep tests/durable`
green; mypy (577 files) clean; ruff + ruff-format clean; `lint-imports` 24/24. Full-suite run on a
per-branch throwaway DB: 32 failures vs a 30-failure clean-HEAD baseline on its own fresh DB; the
2-item delta is `tests/test_workspace_rename_guard.py` (untracked `subsystems/clue-design/.context/`
attachments — the known clue-design guard-exclusion follow-up) and one order-dependent
`tests/resolvers/test_resolvers.py` case that passes in isolation. Everything else is the documented
shared-DB pollution class (all pass on a fresh DB in isolation).

## Fix round (task review, same day — commit follows `5fa0403c`)

Review approved the predicate (verified strictly narrowing on both families; six other tier readers
structurally immune). Three rulings applied:

1. **"Unstamped ⇒ pre-§6.4" was factually wrong.** `persist_discovery_selection_tier` stamped
   `project_run_id` but no `project_id` — it wrote unstamped tiers *today*, not historically. The
   unstamped class is **open**, not a frozen leftover. Consequences fixed:
   - `_live_tier_for_project` is now **two-pass**: prefer a payload stamped for this project
     (regardless of recency), fall back to an unstamped one only when this project stamped none. The
     single-pass version let a *newer* unstamped selection tier from P2 shadow P1's own stamped M6.4
     tier → silent account drop from the deep set. Test:
     `test_live_tier_for_project_prefers_own_stamp_over_a_newer_unstamped_tier`.
   - The three "legacy (pre-§6.4)" docstrings (`deep/composition.py`, `claim_writes.py`,
     `run_lineage.py`) now say **unstamped**, with the open-class caveat spelled out.
   - **Ruled YES on shrinking the class:** `persist_discovery_selection_tier` gained an optional
     `project_id`, passed at both call sites (`phases.py` → `ctx.project_id`; the trial fixture →
     `PROJECT_ID`). It changes no supersession there (that path is already pinned to the exact
     project run, strictly narrower) — it keeps the writer out of the absorbable class and lets the
     read side distinguish it. Asserted in `test_tier_checkpoint_phase.py`.
2. **Absorb-rule rationale corrected** (`run_lineage.py`). The old text called unstamped claims
   "unattributable" — false: P2 `run_lineage` attributes most of them via `run_id`, and the
   read-side lens uses exactly that. The honest statement now in the docstring: the predicate stays
   pure/sync (no connection, no await — it sits in a hot supersede loop) and therefore does *not*
   consult lineage, so **the rule can absorb a claim lineage would attribute to another project**.
   Acceptable only under the B3 synthetic-data ruling while the unstamped class is drained by
   teaching writers to stamp. Also corrected the "at most one claim" undercount — the narrative path
   uses `supersede_claims` over **all** matching lives.
3. **Minor:** noted at `write_icp_scoped_claim` that coexisting tier/score claims can now flip
   `current_value.conflict = True` (exact-equality `merge._conflict`). Cosmetic — no consumer reads
   `CurrentValue.conflict`; the authoritative surface is M9.2's `conflict_flag`. Cross-referenced to
   the existing [M9.2×M1.2] backlog item, with the open question recorded there: whether two lenses
   coexisting should count as a conflict at all.

Fix-round gate: `tests/narrative tests/discovery_scoring tests/claimstore tests/api/deep` green;
`tests/durable tests/integration` green on a fresh DB; mypy 577 clean; ruff/format clean on all
touched files; `lint-imports` 24/24. No migration.
