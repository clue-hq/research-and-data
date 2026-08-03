# 2026-08-03 — M06A S2 account-deep integration

## Scope and decisions

- S1 remains owned by the discovery branch and is consumed through commit `ae05542`; this branch
  owns M06A S2.
- S2 is no-reveal Teams + People acquisition for one exact canonical account. Sumble provides the
  organization/team/person map; the existing M8 worker owns identity admission and committee role
  and persona inference.
- External acquisition must run outside claim transactions. The existing account-deep orchestrator
  remains provider-neutral and resumes from durable account/run/operation references.
- A2 owns the persisted research directive, committee plan, human confirmation, and governance
  authorization. S2 consumes that typed input but does not invent or store a substitute.

## Implemented checkpoints

- `2810dcf` — S2A Sumble v9 Teams/People contract, fixtures, request bounds, no-reveal normalizers.
- `0f8715b` — S2B durable async acquisition, artifacts, receipts, exact credits/spend, replay.
- `69295ee` — S2C snapshot-backed `SumbleCommitteeSource` and provider provenance fields.
- `00a3e90` — S2D immutable seven-condition eligibility decision and zero-call gate.
- `6fbf14b` — provider-neutral O1 external preparation and DEEP `WAITING_EXTERNAL` resume seam.
- `cc5b62a` — Sumble S2D -> S2B -> S2C preparation adapter, default-off production builder, and
  per-run account-deep composer injection.

## Verification

- A clean disposable database `roseau_o2_019fc72b` migrated to head.
- 13 combined S2B/S2C/S2D/O2 DB tests passed: one operation, pending/poll/ready, immutable snapshots,
  candidates, no provider call during materialization, and fresh zero-resubmit replay.
- Relevant deep/API tests passed; mypy passed across 498 source files; Ruff passed; import-linter
  kept 24/24 contracts.
- The disposable database was dropped. No live Sumble endpoint or provider credits were used.

## Remaining work

1. A1 synthetic deep-eligible fixture.
2. A2 durable directive/authorization store and production `SumbleCommitteeInputResolver`.
3. Exa Deep E0–E2 account-profile acquisition/materialization.
4. Full O2 set-scoped `launch_account_deep@1` tool/fleet composition; keep fine-grained tools.
5. O3 agent preview/steering behavior and V0 full acceptance.
6. Separately authorized S1 prerequisite ruling and capped S2/combined live canaries.

Do not claim S2 production-enabled until A2 is bound and the live gates pass. Do not add contact
reveals, a Sumble-specific orchestrator, or automatic discovery-to-deep progression.
