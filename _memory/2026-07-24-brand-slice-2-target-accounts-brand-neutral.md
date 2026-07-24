# 2026-07-24 — Brand correction Slice 2: target accounts are brand-neutral

## Decision implemented

Target accounts are workspace-local research entities. They do not belong to a sender brand kit.
Brand selection belongs to the ABM project. Slice 2 removes the obsolete account→brand relationship
end to end; project-run brand derivation/pinning remains the next slice.

## Changes

- Migration `068426c5ea34` (off `799564102709`):
  - drops `account_entity_brand_fk`;
  - drops `account_entity_brand_needs_workspace`;
  - drops `account_entity.brand_id`;
  - downgrade restores the nullable column, composite FK, CHECK, and historical column comment.
- Removed `AccountEntity.brand_id` from the frozen core contract. Because the model uses
  `extra="forbid"`, attempts to assign a brand to a target account now fail validation.
- Removed `brand_id` from the account repository's selected columns, INSERT SQL, writer signature,
  and bound parameters.
- Removed brand stamping from memory account fixtures. The memory `ScopeStack.brand_id` remains
  legitimate: it is selected project context, not ownership on the target-account row.
- Updated schema/contract tests and current specs. Historical migration
  `50b778e4009a`, its old plan, and the frozen decision record remain unchanged as history.
- Marked the B3 `account_entity.brand_id` residual resolved in `CLAUDE.md`; the remaining brand
  work is project-run integration, not account localization.

## Completeness checks

- Current live code contains no `account_entity.brand_id`, `account.brand_id`, account INSERT
  brand column, or `insert_account_entity(..., brand_id=...)` dependency.
- Legitimate brand fields remain on `Brand`, `Product`, `Project`, memory scope/context, and their
  tests.
- The account workspace anchor and all contact/account workspace isolation constraints remain.

## Verification

- Initial focused run found one stale test-fixture call: `seed_spine()` still passed `brand_id` to
  `seed_account()`. Corrected it; no production code was affected.
- Focused core/entity/workspace/memory suite: `45 passed`.
- Explicit one-revision downgrade inspection restored `brand_id`,
  `account_entity_brand_fk`, and `account_entity_brand_needs_workspace`; re-upgrade removed them and
  retained `account_entity_workspace_anchor`.
- Full `make check`: ruff green, mypy 327 files green, 23 import contracts green,
  `2251 passed, 20 skipped`.
- Full `make db-smoke`: head → base → head green.
- One Alembic head/current: `068426c5ea34`.
- Final live schema: `brand_id` absent from `account_entity`; account brand FK/CHECK absent;
  `account_entity_workspace_anchor` present.
