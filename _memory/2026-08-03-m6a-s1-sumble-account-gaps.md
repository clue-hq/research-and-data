# 2026-08-03 — M6A S1 Sumble account gaps

## Outcome

- Implementation commit: `ae05542` (`feat(enrichment): add durable Sumble S1 account gaps`).
- Added seal/tier-bound `enrich_account_gaps@1` for one selected account and an explicit,
  positive-value field plan.
- Added the durable operation/snapshot/field ledger in migration `bd0b7e62a2b4`, including shared
  project-budget reservation, terminal immutability, claim-lineage checks, spend-unknown quarantine,
  and same-window field overlap rejection.
- Sumble REST v9 organization/jobs/confirmed-tech responses are stored independently, normalized
  through snapshot-only resolvers, and reconciled through the existing merge/corroborator. Exa and
  Sumble claims remain independent; neither provider overwrites the other.
- Production is default-off and requires `CLUE_SUMBLE_API_KEY`; money conversion is explicit through
  `CLUE_SUMBLE_CENTS_PER_CREDIT`. Head-of-ABM profile v14 holds the tool, while Stage 0 withholds it.
- S1 artifacts are account-indexed for DSAR. Terminal replay is DB-only and does not resurrect
  tombstoned subject edges.

## Verification

- Real PostgreSQL/filesystem acceptance: organization + jobs + technology, five provider credits,
  2.5 configured cents, hiring claim, Exa/Sumble technology conflict, three-call then zero-call
  replay, no duplicate claims, immutable terminal rows, and DSAR enumeration/tombstone/replay.
- Negative pre-spend cases: confidently resolved field, unjustified cap, and unapproved unbounded
  tech all produce zero HTTP calls and zero operation rows.
- Sumble adapter/provider/profile/authority regressions pass.
- Mypy: 484 source files, no issues. Import-linter: 24/24 contracts kept. Tracked Ruff lint: pass.
- Alembic single head `bd0b7e62a2b4`; isolated full head -> base -> head passed. The local and
  container temporary databases named `clue_s1_smoke_20260803` were verified idle and removed.

## Open gate

- No paid Sumble request was made in this round. Per the requested sequence, the separately bounded
  one-account/one-field live canary and fresh-process replay remain the next closure step.
- Full pytest has one unrelated existing failure: `tests/memory/test_memory_offline.py` detects the
  Stage-0 runtime importing `clue_memory` outside the intended seam. Thirteen unrelated tracked
  files remain outside the repository Ruff-format baseline; S1-owned files are clean.
