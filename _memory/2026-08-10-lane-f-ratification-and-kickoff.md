# 2026-08-10 — Lane F ratified and staffed: R11 §6 rulings + R11.5 committee bridge

## Rulings (founder, this session)

- (a) Branch: `platform/lane-f-r11-bridge` (this worktree), off post-Lane-E hub head
  `d9bed0d0`; merge into `platform/frontend-integration` when accepted.
- (b) No-fleet-run semantics: plain `PAUSED` (operator resumes after the confirmed launch).
- (c) Multiple fleet runs: latest human-confirmed run is current; older runs = visible history.
- (d) Budget: enforce once at fleet admission; adapter copies settled fleet spend into the M7.4
  phase ledger as DEEP `cost_cents`; never re-gated.
- (e) Interim `run_verification@1` guard: skipped — R11.3 replaces the selector now.
- (f) **R11.5 committee bridge IN**: without it the lifecycle advances while committees,
  contacts, and value narratives stay unusable on live M8D runs (the [LaneE×R11/C7] HB-1 gap).
  The product-pin fallback-run serving gap stays FI-2/C7-owned, OUT of Lane F.

## Spec state

`docs/specs/M8D-R11-deep-phase-bridge.md` is now RATIFIED: §2 gains the R11.5 scope item,
§3 re-verified 2026-08-10 at `d9bed0d0` with current line anchors + new R11.1/R11.5 facts,
§4 gains the ratified state-table semantics + the R11.5 design (claim-reference-source seam
in `ContactEligibilityResolver`; legacy source = `account_run.references_index`, M8D source =
`entity_research_account_coverage.claim_refs` scoped to `committee_member_ids`; downstream
governance shared), §5 FROZEN (ACs 1–8 + new 9–10 for R11.5), §6 records the rulings,
§7 is the worktree kickoff. Demarcation registry §2.6 amended (Lane F promoted; territory
widened to the committee-reader seam + composition sites).

## Key substrate facts re-verified (do not re-derive)

- Quarantine handler still at `run_composition.py:424`; shared high-tier resolver instance at
  `:368` feeds VERIFICATION (`:428-433`) AND the HANDOFF retention sweep (`:456`); second
  consumer `toolbelt_wiring.py:2226`.
- Phase machine: PAUSED → AWAITING_INPUT checkpoint + run PAUSED (advance no-ops until
  resume, `durable/project.py:428`); WAITING_EXTERNAL → run stays ACTIVE, wake re-enters the
  handler; DEEP payload validated at `:499-503` (R11.4 arm lands there).
- Fleet state: `AccountResearchFleetRow` (`account_research_fleet.py:122`) with state
  canary/open/waiting_external/suspended/terminal, project_run_id, diagnosis,
  source_action_ref; `entity_research_run` row carries selection_id + spent_cents.
- Wake source = `Callable[[AsyncConnection, datetime, int], Awaitable[Sequence[ProjectRunId]]]`
  (`external_research_wake.py:20`).
- `HighTierResolver = Callable[[PhaseContext], Awaitable[Sequence[AccountSpec]]]`
  (`deep/handler.py:92`); `AccountSpec` at `durable/scheduler.py:43`.
- R11.5: `ContactEligibilityResolver.resolve_account` starves only at the reference source
  (`contact_eligibility.py:183-196`); coverage rows already carry `claim_refs` +
  `committee_member_ids` (`account_entity_research.py:559-594`).
- No migration needed anywhere in the lane.

## Execution plan

Slices F1 (R11.4+R11.1) → F2 (R11.2) → F3 (R11.3) → F4 (R11.5) → F5 (frozen-AC acceptance,
both `CLUE_VERIFICATION_ENABLED` states, R1 quarantine regression re-run, live smoke with the
workspace `.env`). Implementation by Opus subagents; planning/review/debugging by the
orchestrating session (founder directive this session). Task list mirrors the slices.
