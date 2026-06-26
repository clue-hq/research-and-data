# M13.2 — Disposition capture (implementation + decisions)

**Worktree branch:** `m13.1/review-surface-v1` (the M13.2 fork off `m13/base`, alembic base head
`c48ebe0a1e62`). **Spec:** `docs/specs/M13-review-feedback-observability.md §M13.2`. **Brief:**
`_memory/2026-06-26-m13-parallelisation.md` "BRIEF — M13.2". **Status: COMPLETE + verified.**

## What shipped
Normalizes every feedback signal (M13.1 review actions + downstream client sales outcomes) into one
append-only, idempotent `disposition` record + a frozen provenance snapshot, and exposes the single
`labeled_dataset` read view M13.3 consumes. Owned files:
- `review/disposition.py` — `FeedbackDisposition` record (named **not** `Disposition`, avoids the
  `identity.Disposition` clash) + `DispositionType`/`DispositionActor`/`DispositionOrigin` StrEnums
  (in `review`, not `core`) + `DownstreamOutcome`/`IngestReport`/`IngestRejection` + natural-key
  builders + `REVIEW_ACTION_TO_DISPOSITION`.
- `review/disposition_store.py` — conn-in primitives (`record_disposition`, `snapshot_claim_provenance`,
  `capture_review_action`, `capture_downstream`, `ingest_downstream`, `tombstone_contact_dispositions`)
  + `DispositionStore` + the concrete `ReviewDispositionEmitterImpl` (implements the frozen
  `core.ReviewDispositionEmitter`).
- `review/labeled_dataset.py` — `LabeledRow` + `read_labeled_dataset` over the SQL view.
- `alembic/versions/3b470c5fdcb4_…` (down_revision `c48ebe0a1e62`) — the 3 enums + `disposition` +
  `disposition_provenance` + the `labeled_dataset` VIEW.
- `api/disposition_wiring.py` — `build_disposition_store` / `build_review_disposition_emitter`
  (no `composition.py` edit).
- Tests: `tests/review/{conftest,test_disposition_unit,test_disposition_db}.py`,
  `tests/api/test_disposition_wiring.py`; exported the public surface from `review/__init__.py`.

## Load-bearing decisions (settled just-in-time, with the frozen seam in front of me)
1. **natural_key for review-origin = `review_surface:{review_action_id}`** — NOT the brief's
   `review_surface:{campaign_run}:{claim_id}:{type}:{round}`. The frozen `core.ReviewActionOutcome`
   carries `review_action_id` (a strictly-stronger 1:1 audit-row token) and the emitter seam carries
   **no** `review_round` (the brief pre-dated the frozen `core.review`). M13.1 guarantees one
   `review_action` row per logical action, so this dedupes correctly. Documented in
   `review_natural_key`'s docstring. Downstream-origin = `{origin}:{client_id}:{external_id}:{type}`.
2. **`entity_type` reuses the PG `entity_type` enum from migration 0002** (no 4th enum, no parity
   burden; downgrade leaves the shared type) — like `source_yield` reuses `field_class`.
3. **Provenance snapshot source:** review-origin → the single reviewed claim (`claims_by_ids`);
   account-origin → the persisted M12.2 `account_handoff.payload->'handoff'->'provenance_index'` keys
   (read via **raw SQL** — `review` can't import `narrative`), re-resolved to `source_key`/`field_key`
   via `claimstore.claims_by_ids` (`ProvenanceRef` carries neither). Frozen at `record()` time.
4. **ICP context (`client_id`/`icp_key`/`icp_spec_version`):** read `campaign_run` via **raw SQL**
   (`review` can't import `durable`). Downstream rows with no run context backfill icp_key/version from
   the account's latest handoff.
5. **Resolve-or-reject:** `ingest_downstream` resolves free-text via `identity.resolve_many`; confident
   = `method == DETERMINISTIC OR top_score >= DEFAULT_DISPOSITION_POLICY.auto_merge_threshold` (0.95) →
   `surviving_id`; else → `IngestRejection` (error queue). Per-row savepoint so a bad row never aborts
   the batch. **Never admits a new entity** for a sales outcome (unlike `identity.review.disposition`).
6. **append-only-except-tombstone:** `disposition` has a BEFORE-UPDATE guard rejecting any update that
   touches a column other than `tombstoned_at` (mirrors `icp_spec`'s immutable guard), so M10.5 can
   stamp the erasure marker but the captured signal is otherwise immutable. `labeled_dataset` excludes
   tombstoned rows. `labeled_dataset` is the **repo's first SQL VIEW**.
7. provenance arrays are `text[]` (claim ids stored as uuid-strings) — avoids uuid[] casting; the
   reader parses back to `ClaimId`.

## Deferred to the api composition root (the cross-package wiring `review` can't do — same pattern as
M9.1 AC-6 / M9.4 pre-insert stamp). Wire at **integration**:
- Inject `build_review_disposition_emitter()` into M13.1's review surface (replaces the no-op emitter).
- The **M10.5 → `DispositionStore.tombstone_for_contact` cascade**: `compliance` can't import `review`,
  so the api root calls `tombstone_for_contact(contact_entity_id)` alongside `erase`/`record_objection`/
  `sweep_expired`. Stamps `tombstoned_at` (audited); account-keyed dispositions are NOT cascaded.

## Verification (throwaway DB `clue-pg-m132` :5437)
`make check` = **1811 passed / 14 skipped / 0 failed** (ruff fmt+lint, mypy, import-linter **11/11
KEPT**, full suite — +15 over base's 1796). `make db-smoke` (up→down→up) green, single head
`3b470c5fdcb4`. 15 M13.2 tests cover: enum parity, review-action idempotent capture + provenance,
ingest resolve/reject/dedupe, account handoff-provenance snapshot + icp backfill, labeled_dataset
fit-score join + reproducible + tombstone-aware, the store class path.

## Incidental base fix (separate concern)
The base's M13.1 migration (`c48ebe0a1e62`, committed `dc2e3a6`) had **6 pre-existing E501** lint
errors — `make lint` runs `ruff check .` (includes `alembic/`), which the Stage-1 author's targeted
`ruff check src` missed, so the base's `make check` was already red on lint. Fixed those 6
COMMENT/comment lines (cosmetic wrapping; no schema change) so this branch's `make check` is honestly
green. Merge-safe (committed migration; Track A won't re-edit those lines).

## Follow-ups / caveats
- `review/__init__.py` is a known shared edit point (Track A also exports) → small union merge at
  integration. `review/README.md` is stale ("core/config/obs only") — Track A owns the fix; I left it.
- The `downstream_signal` term M13.3 wants joins dispositions to `source_yield`; if that join gets
  expensive, pre-materialize only that term (decision 4 in the parallelisation note).
- `.gitignore` is a pre-existing unstaged change (not mine) — left alone.
