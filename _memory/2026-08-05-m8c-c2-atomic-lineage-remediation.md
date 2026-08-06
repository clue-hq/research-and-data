# 2026-08-05 — M8C C2 atomic reservation and Exa-lineage remediation

## Outcome

C2 is closed after the two audited blockers were fixed. C3 may begin from a provider-neutral
external-research ledger whose public reservation API is atomic and whose Exa claims cannot bypass
durable snapshot lineage.

## Changes

- `reserve_external_research_operation(...)` now owns the transaction-scoped semantic reuse lock,
  repeats reuse/replay/capacity checks under that lock, and is the only public reservation path.
- Production keeps an unlocked reusable lookup only as an artifact-capture optimization.
- Fresh-process concurrency drives the public reserve call directly and proves one operation for
  exact and semantic-alias requests.
- Alembic `f9281fac77e1` requires every `exa_deep` claim to carry operation, snapshot, provider
  request, and result-artifact lineage; upgrade fails rather than inventing missing legacy refs.
- The claim trigger validates the complete tuple against the exact account/contact snapshot and
  indexed result artifact.
- Pre-E1 contact, account, resolver, and verification doubles now use explicit fixture sources;
  they no longer forge `exa_deep` provenance.

## Verification

- Focused C2 + E1/E2 + A1 + contact governance + resolver + verification regressions: passed.
- Fresh isolated database migrated to `f9281fac77e1`; complete pytest suite reached 100% with exit
  code 0; 3,398 tests collected.
- Migration downgrade to `26eaa6262063`, re-upgrade, and single-head check passed.
- Mypy: 525 source files clean. Import-linter: 24 contracts kept, 0 broken.
- Ruff passed on every changed Python file. Repository-wide `ruff check .` also inspected untracked
  user-owned `.claude/` and `.codex/` skill copies and reported their existing CLI `print` calls;
  those unrelated untracked files were not changed.
- No live Exa or Sumble provider call and no paid spend occurred; C2 remains a mechanical durability
  slice.

## Handoff

C3 owns the exact-contact Exa request/schema/compiler. It must use the C2 public reservation API in
later acquisition work and materialize only claims carrying the now-mandatory lineage tuple.
