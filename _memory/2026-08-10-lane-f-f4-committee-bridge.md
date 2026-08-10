# Lane F / F4 — R11.5 M8D committee bridge (2026-08-10)

Branch `platform/lane-f-r11-bridge`, on top of F1–F3 (HEAD was `67a9616d`).
Authority: `docs/specs/M8D-R11-deep-phase-bridge.md` §4 R11.5, §5 AC9–10.
Closes the `[LaneE×R11/C7]` HB-1 gap.

## What shipped

`ContactEligibilityResolver` no longer hardcodes its claim-reference source. It takes a
`ClaimReferenceSource` (constructor-injectable, defaulting to the chain), and the chain is:

1. `EntityResearchCoverageReferenceSource` — the latest human-confirmed account-research fleet run
   (§6c) and its `entity_research_account_coverage` row for this account: `claim_refs` →
   claim ids, `committee_member_ids` → membership scope.
2. `AccountRunReferenceIndexSource` — today's `account_run.references_index` read, byte-identical.

Everything downstream is untouched and shared: the product-exact filter, contact liveness, survivor
redirects, `latest_use_decisions`, `_resolve_contact_claims`, the deterministic sort. Member scoping
redirects the coverage member ids through the **same** `surviving_ids` call as the claim entity ids,
so a member recorded before an identity merge still matches its survivor.

`build_contact_eligibility_resolver`'s signature is unchanged, so nothing at any call site was
edited — `ProductionHandoffCommitteeReader` (Lane E's probe), `GovernedCommitteeViewReader` (C7's
committee section), `run_composition`'s HANDOFF registration and FI-2's `frontend_read/**` all
inherit the bridge. `resolve_contact` delegates to `resolve_account`, so it is bridged by
construction.

Supporting: new `clue_api/account_research_coverage.py` holds `latest_account_research_run_id`
(now the single definition of the §6c ordering; `read_latest_account_fleet_for_project_run`
delegates to it) and `read_account_coverage_in_run`.

## Two rulings taken during implementation (both flagged to the lane owner)

**1. The M8D source claims authority only when the fleet run has published ≥1 coverage row.**
The brief asserted Lane E's E3 acceptance fixture is a pure legacy shape. It is not:
`tests/integration/test_lane_e_e3_acceptance.py::_seed` launches a real fleet run bound to the same
`project_run_id` *and* writes `save_references`, and its `_finalize` drives the job terminal through
the raw R2 lifecycle, which never runs the R5 coverage compiler — so it is a fleet run with **zero**
coverage rows. Measured: under the brief's literal rule (fleet run exists ⇒ M8D wins), E3 goes from
4 pre-existing failures to **11**. Rationale for the refinement: a run that has published nothing
has not spoken about a single account, so it cannot blank a committee an earlier completed pass
resolved. Once it *has* published, the brief's rule holds exactly — an account with no coverage row
under a producing run gets the honest `()` and never falls through to legacy (pinned by a test that
gives that uncovered account a fully populated `references_index`). No live-data downside: a real
M8D run always writes coverage at finalization, and a live M8D project run has no legacy index.

**2. `tests/api/test_c7_production_readers.py`'s composition query budget went 30 → 31.**
The bridge costs exactly one extra bounded lookup per `resolve_account` (the run-id read) — constant
in statement count, which is the thing that ceiling exists to distinguish from a per-statement
governance loop. Kept to +1 (not +3) by: reading the run **id** rather than the whole supervised
fleet row, folding the coverage existence + row reads into one statement, and redirecting members in
the same `surviving_ids` call as the claims. This is the one edit outside F4's stated file list.

## Verification (throwaway DB `clue_f4`)

- `tests/api/test_r11_committee_bridge.py` — 14 tests, green.
- `tests/api` + `tests/architecture` — green except two failures reproduced identically at baseline
  (`test_agent_registry_wiring::test_resolved_snapshot_materializes_through_c61_backend`,
  `test_agent_turn_wiring_db::test_durable_turn_history_replay_and_dsar_are_body_free_and_fail_closed`).
- `tests/integration` — identical failure set before and after the change (6, all Lane E E1/E2/E3).
- ruff (format + check), mypy (630 files), `lint-imports` (25 contracts) all clean.
- No migration. No gateway/judge dependency, so the resolver stays toggle-invariant.

## Notes / follow-ups

- `tests/api/test_frontend_read_contacts.py`'s module docstring still says every committee is empty
  on real data "until the R11 bridge lands". Now stale; FI-2-owned, not edited (out of territory).
- The C7 `GovernedCommitteeViewReader` is exercised over the M8D fixture (AC10). The FI-2 HTTP
  contacts endpoint is *not* driven over an M8D fixture — it resolves its run through
  `latest_project_run_context` + `project_account` membership, so a live-shaped test there is a
  bigger fixture and belongs with FI-2's suite.
- The M8D source applies whenever a fleet run is bound to the project run in this workspace; unlike
  R11.3's selector it cannot also check `fleet.project_id == ctx.project_id`, because
  `resolve_account` has no project id in scope. Coverage is workspace- and account-scoped, so the
  exposure is bounded, but a cross-project fleet row would describe the committee.
- The two pre-existing `tests/api` failures and the six `tests/integration` ones predate F4 and are
  unowned by this lane.
