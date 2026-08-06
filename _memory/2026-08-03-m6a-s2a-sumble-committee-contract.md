# 2026-08-03 — M6A S2A Sumble committee contract

## Outcome

- Implementation commit: `2810dcf` (`feat(committee): freeze Sumble S2 people and teams contract`).
- S2 ownership is now explicit on `platform/c8-account-profiling-integration`; the slice consumes
  S1 commit `ae05542` and does not move S2 back to the discovery/S1 branch.
- Added isolated v9 People and Teams request/response models, exact no-reveal selects, deterministic
  credit maxima, async People status semantics, exact-account normalizers, and recorded fixtures.
- Added `docs/specs/M06A-S2-sumble-committee-acceptance.md` and corrected the parent/roadmap S2
  boundary to defer all email/phone reveals.

## Provider contract decisions

- Current Sumble v9 OpenAPI SHA-256:
  `8eac8f9b74afb74f1bd4f593ee2baa4547d2ca80947feea581e91e551a97c887`.
- Teams is synchronous and bounded by team limit, related-person cap, and job-post cap.
- People is asynchronous; kickoff and pending/running/failed polls charge zero, and the first
  succeeded poll is the one settlement event. Repeated succeeded polls report zero credits.
- `email`, `phone`, `person_score`, and `"all"` are never selected. Any non-null contact value in an
  S2 snapshot fails closed.
- Sumble provider person id remains provenance only; LinkedIn is the current strong committee
  admission key.
- Team membership/confidence is labeled `provider_inferred_team_membership`, not a reporting line.
- People manager/direct-report expansion is deferred: the endpoint caps input people at 25 but has
  no returned-related-person cap, while each returned relationship costs one credit.
- Advanced query remains a prevalidated opaque expression. The published contract documents the
  wrapper and filter dimensions but not enough grammar for arbitrary user-text compilation.
- OpenAPI marks the People response envelope `id` required while async prose examples omit it;
  `request_id` is required and is the provider operation identity.

## Verification

- 27 S2A contract tests passed.
- Existing S1 Sumble plus committee/deep regression selection passed.
- Ruff passed across `libs`, `subsystems`, `platform`, and `tests`.
- Mypy passed across 486 source files.
- Import-linter: 24 contracts kept, 0 broken.
- Full pytest had two failures: the DSAR failure was sandbox-only and passed when rerun with
  localhost PostgreSQL access; the other is the pre-existing memory boundary failure in
  `tests/memory/test_memory_offline.py` caused by
  `platform/api/clue_api/trial/stage0_runtime.py` importing `clue_memory` directly.
- No live Sumble call, provider credit, migration, durable operation, contact entity, claim, or
  production source binding was created.

## Next slice

S2B owns durable acquisition: one immutable operation/request fingerprint, synchronous Teams
snapshot, asynchronous People submit/poll, exactly-once credit settlement, spend-unknown handling,
fresh replay, and provider-neutral waiting. It must remain outside the committee claim transaction.
