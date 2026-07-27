# Phase C7.1 closeout — research-view prerequisite hardening

**Date:** 2026-07-27
**Branch:** `platform/c7-research-views`
**State:** C7.1 complete; C7.2 derivation/entailment substrate next

## Outcome

- Added joint DB tests proving field-registry `numeric_tol`/`semantic` equality produces the same
  conflict result in corroboration, `current_value`, and the provisional C7 item-state mapping;
  genuine disagreement remains `review_required`.
- Made consumer-visible selectors fail closed on
  `lawful_basis_record.retention_until <= read_time` before the retention sweep runs:
  `current_value`, `current_values`, and default live `claims_by_ids` all exclude the claim.
  Audit/history mode still resolves it. Fresh-but-expired and stale-but-not-expired remain distinct.
- Added hash migration `4dad5551c2f7`: `faithfulness_verdict.rationale` is nullable and paired with
  coherent `rationale_redacted_at`/`rationale_redaction_reason` metadata. The existing DSAR
  tombstone transaction nulls rationale while retaining verdict/model/prompt/cost metadata.
  Downgrade never reconstructs erased text.
- Added core `EvidenceAccessRequest`/decision/result and
  `EvidenceAccessAuthorizer`/`EvidenceAccessService` protocols. Access refs are opaque and
  caller-controlled TTLs, URLs, paths, and storage keys are absent. An architecture test reserves
  direct `StorageBackend.presign` use to the future API-root `evidence_access.py` implementation.
- Made scoring output product-exact at its authority: `score_account` receives the pinned
  `product_id`, stamps both fit and intent claims, returns it on `AccountScore`, and supersedes only
  within `(ICP, product)`. Neutral input facts remain reusable as evidence across product scores.
  C7 score references require evidence claim ids and an exact product id; C7 still does not score.
- Registered optional open-vocabulary `contact.class` beside fixed committee persona/role.
  It is a provenance-backed `contact.*` claim, not a Python enum and not inferred from persona or
  title. Missing remains unknown.

## Verification

- `uv run ruff check` over every modified/new C7.1 file: passed.
- `uv run mypy`: 422 source files, no issues.
- `uv run lint-imports`: 24 contracts kept, 0 broken.
- C7.1 selected DB suite: all 80 tests passed.
- Full DB-enabled suite: all 2,661 collected tests completed (2,639 passed, 22 skipped).
- Isolated PostgreSQL at port `55439`: Alembic head → base → head passed.
- A seeded redacted-rationale row also survived `downgrade -1` safely as empty text, then upgraded
  back to the nullable/redaction-metadata shape; erased text was not reconstructed.
- `uv run alembic heads`: exactly `4dad5551c2f7`.
- `git diff --check`: passed.

The first product-scope DB test correctly failed on the existing
`claim_product_workspace_fk` because synthetic product ids were not spine rows. The fixture was
fixed to create real same-workspace brand/product rows; no production constraint was weakened.

## Important boundaries

- C7.1 adds no research-view composer, route, tool, evidence-access implementation, snapshot table,
  or derived-claim storage.
- `claims_for(... include_superseded=True)` and DSAR access remain audit/history reads and retain
  append-only claim history; only consumer-visible selectors fail closed on recorded expiry.
- The current direct claim-id reachability redacts legacy faithfulness rationale. C7.2 support
  edges must extend subject reachability to derived claims without copying rationale.
- The evidence service implementation and the sole authorized storage-presign call remain C7.4.
- Pre-existing untracked `.claude/`, `.codex/`, and
  `docs/architecture/clue-hq-research-model-surface.md` remain untouched.

## Next exact entry

C7.2 may now add the immutable derived-claim/claim-support substrate and bounded entailment path:

1. add `ClaimFlavor.DERIVED` with enum parity and a hash migration;
2. add immutable ordered support edges, scope/product/subject checks, and cycle prevention;
3. add the governed entailment adapter and accepted/rejected write path;
4. use retention-aware default `claims_by_ids` for support resolution;
5. extend DSAR reachability through support edges without persisting free-form rationale;
6. prove missing/superseded/rejected/expired/erased support invalidates the derivation.
