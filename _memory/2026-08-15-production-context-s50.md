# Production context S5.0 — product-knowledge consumption decision

**Date:** 2026-08-15
**Branch:** `platform/onboarding-integration`
**Status:** S5.0 contract gate implemented; S5 runtime not started

## Ratified decisions

- Company facts remain in the account-wide Client-KB scope (`product_id IS NULL`). Detailed
  product facts use the independently versioned scope for one exact spine product.
- A selected product is consumed through both `ProductKnowledgeCard@1` and separate governed
  `list_product_knowledge@1` / `inspect_product_claim@1` tools. The S4 company tool addresses stay
  company-only.
- Product tool schemas expose only bounded filters or `claim_id`. Workspace, client, confirmed
  product, and product-KB version are injected from the trusted durable turn pin.
- S5 adds `ClientKnowledgeCard@2` for a bounded typed product catalog. V1 remains immutable for
  historical receipts/replay. The catalog never carries detailed product facts.
- The target new-turn policy is `company-and-selected-product-v2`: pin company version and the
  optional selected-product version in one DB snapshot, reuse the exact pair on retry, and let
  only a later turn observe background updates. Equal version numbers are not required because the
  two sequences are independent.
- A confirmed product with no product KB is valid: `ProductProfileCard@1` is available, while the
  Product-KB card/tools are honestly absent.

## Delivered

- Added authoritative child contract
  `docs/specs/FI-production-deepagent-context-S50-product-knowledge-contract.md` with card
  ownership, context states, version/retry semantics, catalog synchronization, privacy/injection,
  and S5-A–F checkpoint ownership.
- Added provider/DB-free executable constants and state invariants in
  `platform/api/clue_api/product_knowledge_decision.py`.
- Added exact decision fixture
  `tests/fixtures/production_context/s50_product_knowledge_decision.json` and adversarial guards in
  `tests/api/test_product_knowledge_decision_s50.py`.
- Updated the parent context-composition spec and `CLAUDE.md` authority note. They explicitly say
  S5.0 is contract-complete, while V1 remains production until S5-A–F pass.

## Verification

- New S5.0 suite: 12 passed.
- Adjacent production-context/S4/tool/profile/recipe/guidance matrix: 66 passed total, including
  the 12 new tests.
- Ruff format/check passed across 1,418 files; mypy passed across 667 source files; all 25 import
  contracts passed; `git diff --check` passed.
- Alembic still has the sole unchanged head `d3672ccf43cc`; S5.0 intentionally adds no migration or
  database state.

## Next implementation boundary

- Start with S5-A only when requested: freeze/register the product catalog/knowledge field shapes,
  V2/V1 card schemas, cursors, caps, refusal taxonomy, and provider/DB-free fixtures.
- Do not register product tools, migrate the turn pin, or claim production product context before
  their assigned S5-D/S5-E checkpoints pass.
