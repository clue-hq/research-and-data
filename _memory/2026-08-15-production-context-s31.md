# Production context S3.1 — durable production composition reliability

**Date:** 2026-08-15
**Branch:** `platform/onboarding-integration`
**Status:** S3.1 implemented and verified

## Delivered and frozen decisions

- Added reversible Alembic revision `d3672ccf43cc` and append-only
  `agent_turn_scope_pin`. One row per submitted turn durably pins workspace, project identity and
  state, brand, confirmed project product, canonical client, company-wide Client-KB version,
  policy version, and database time before cards, model, or governed tools run.
- Added an atomic workspace-scoped load/create repository. Concurrent/reclaimed attempts may
  observe current state, but only the inserted row is authoritative; all retries read the winner.
  Updates and deletes are rejected by the database trigger.
- Froze `company-account-wide-v1`: the shared Client-KB card and S4 reads select only the
  `product_id IS NULL` sequence. `project.product_id` remains a separate project pin. A future
  product-specific knowledge index must introduce a new explicit policy/version rather than
  silently changing this contract.
- Wired the real `AGENT_TURN` runner to read/create the durable pin before composition and reuse it
  on retries. A committed legacy turn without a historical pin remains replayable and is not
  falsely relabelled from current state.
- Production Stage-0 card persistence now reverse-binds each exact quoted statement as well as the
  client. Statement DSAR can therefore find the card emitted by the actual fleet path.
- Extended the existing privacy closure to recognize L3 context artifacts and delete every
  LangGraph namespace under the turn's unique execution id. Fixed the replay reader's nullable
  left-join alias so an erased/empty layer returns a blocked replay instead of crashing.
- Reused the toolbelt's canonical JSON-mode result validator in the production execution adapter.
  The real S4 path exposed the prior duplicate Python-mode validation bug for strict UUID/tuple
  result contracts.
- Updated the source-of-truth spec and `CLAUDE.md` with S3.1 completion, retry semantics, DSAR
  reach, and the company-wide/product-specific scope policy.

## Verification

- Focused final production-context matrix: 70 passed. This includes real PostgreSQL receipts,
  direct UPDATE/DELETE refusal, vN retry after background vN+1, next-turn vN+1 selection,
  cross-workspace refusal, strict JSON result validation, S4 tooling, S4-E privacy/replay, and the
  existing Stage-0 card DSAR suite.
- Real-fleet acceptance uses only a deterministic external-model double around the production
  chain: `AGENT_TURN -> durable pin -> cards -> seven-layer assembler -> governed S4 tool -> real
  Postgres LangGraph checkpoint -> finalization -> cold replay -> statement DSAR`. It proves the
  original vN in the L3 card and S4 output, one finalization, zero model work on replay, exact
  statement reach, checkpoint deletion, and fail-closed post-erasure replay.
- Migration gates: sole Alembic head `d3672ccf43cc`; clean upgrade/downgrade/upgrade passed. Final
  read-only check on retained database `clue_context_s31_20260815` found the head and zero leaked
  scope-pin rows. Keep this database untouched for review.
- Static gates: Ruff format/check passed across 1,416 files; mypy passed across 666 source files;
  all 25 import contracts passed; `git diff --check` passed.
- Repository-wide pytest on separate database `clue_context_s31_full_20260815`: 4,711 passed,
  23 skipped, 40 failed. The 40 are the same separated branch baseline as S4-E: merged design
  subtree direct-logging violations, monolithic migration/source-registry fixture contamination,
  downstream seeded-state collisions, and the pre-existing workspace-token guard. No S3.1 test
  failed. That database was restored to the head and is not the accepted clean evidence database.

## Follow-up boundary

- S3.1 does not add product-specific Client-KB retrieval. S5.0/new contract work must define and
  version that scope explicitly before the platform deepagent can mix selected-product facts with
  the account-wide company index.
- S6 remains the live browser/provider context acceptance slice; S3.1 proves the production fleet
  chain with a deterministic model boundary and must not be described as a live model/browser run.
