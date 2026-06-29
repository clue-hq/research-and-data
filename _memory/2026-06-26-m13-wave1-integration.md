# M13 Wave-1 integration (M13.1 + M13.2 + M13.4) — branch `integration/m13`

**Date:** 2026-06-26. **Base:** `m13/base` (6ab925c). **DB for checks:** throwaway `clue-pg-m13int` :5439 (`CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:5439/clue`).

## What the three branches actually were
Despite the names, the Conductor parallel workspaces built the three Wave-1 milestones:
- `m13.1/review-surface` → **M13.1** review surface (3 commits)
- `m13.1/review-surface-v1` → **M13.2** disposition capture (2 commits)
- `m13.1/review-surface-v2` → **M13.4** observability surface (1 commit)

All three forked clean off `m13/base`; each was self-verified green. Integration-readiness review (3-agent) → all ready; the load-bearing checks pass (M13.1 correction wins `current_value` at tier-1; M13.2 `labeled_dataset` view tri-scoped; M13.4 uses the at-rest strong-binding scan, never summed).

## Merge (done)
- `git merge --no-ff` M13.1 → M13.2 → M13.4 into `integration/m13`.
- Conflicts only in 3 shared files (union/superset merges): `review/__init__.py` (all exports), `tests/review/conftest.py` (kept the M13.2 `enum_labels`+`text` and M13.4's richer `rollback_conn` docstring), `tests/review/__init__.py` (empty).
- M13.2's E501 re-wrap of the M13.1 migration auto-applied (one-sided, benign). M13.4's additive `core/observability.py`, `api/__init__.py` (observability exports), `claimstore.claims_for_runs`, `config` fields auto-applied (no collision).
- `review/README.md` was already corrected on the M13.1 branch (M13.4 reviewer saw its own stale base) — no action.

## alembic merge (done)
Two parallel heads off `c48ebe0a1e62`: `3b470c5fdcb4` (M13.2) + `0f2f5df21591` (M13.4). One merge revision `f9483ab9aafa` (no-op join, two down_revisions). `alembic heads`==1; up→base→up reversible on :5439.

## API composition-root wiring (the integration join) — PLAN
The deferred cross-package joins each branch left for the api root (the established "interface in `core`, concrete impl injected at `api`" pattern — M9.1 AC6 / M9.4 stamp / M12.3 readiness reader):

1. **Make the disposition emitter injectable (edit M13.1 `api/review/composition.py`).** `build_review_surface` / `build_review_phase_handler` / `register_review_phase_handler` hardcode `NoopReviewDispositionEmitter()`. Add an optional `disposition_emitter: ReviewDispositionEmitter | None` (default → Noop, back-compat). Minimal, backward-compatible; lets the production path inject M13.2's concrete emitter without duplicating surface construction.

2. **New `api/review_feedback_wiring.py` — the M13 join** (api is the import-exempt seam; may import `review` + `compliance`):
   - `register_reviewed_phase_handler(...)` — registers the REVIEW handler whose surface emits **real** dispositions (`register_review_phase_handler(disposition_emitter=build_review_disposition_emitter(), …)`). The M13.1↔M13.2 emitter join.
   - `ContactDispositionTombstoner` Protocol (`tombstone_for_contact`); `DispositionStore` satisfies it structurally.
   - `TombstoneCascadingDataSubjectRights` — wraps `compliance.DataSubjectRights`, proxies `access`/`rectify`, and on `erase`/`record_objection` cascades `tombstone_for_contact(contact_entity_id)` (the M10.5→M13.2 cascade; `compliance` can't import `review`, so it lands here). Idempotent; runs after the claim erase commits.
   - `build_dsar_with_disposition_cascade(*, dsar, disposition_store)` → the wrapper.

3. **Handoff gate** — `require_finalized_review` flag already exists on `build_handoff_readiness_reader` / `build_handoff_phase_handler` (M13.1 shipped it, default OFF). The production HANDOFF registration passes `True`. No new code; covered by a test.

4. **Exports** — `api/__init__.py` re-exports the review wiring (`build_review_phase_handler`, `register_review_phase_handler`, `build_review_surface`, `DbVerificationAnnotationReader`, `CampaignRunResumeHook`, `NoopReviewDispositionEmitter`), the disposition wiring (`build_disposition_store`, `build_review_disposition_emitter`), and the new join (`register_reviewed_phase_handler`, `TombstoneCascadingDataSubjectRights`, `build_dsar_with_disposition_cascade`).

5. **Tests** `tests/api/test_review_feedback_wiring.py` — fakes for the cascade (erase/record_objection → tombstone_for_contact; access/rectify pass through) + `require_finalized_review=True` gating; a DB-gated end-to-end (review action through the concrete emitter writes a `disposition` row) reusing `tests/review/conftest.py`.

## Scoped decision (documented divergence)
The disposition tombstone cascade is wired at the **per-subject DSAR events** (`erase`/`record_objection`) where the contact is exactly identified — this satisfies M13.2 AC5 ("tombstoning a contact removes its dispositions"). The pre-handoff bulk sweeps (`RetentionSweepHandoffHandler`'s `sweep_expired`/`sweep_objections`) are **not** re-cascaded to dispositions: `SweepResult` exposes no per-contact breakdown, and a retention-TTL age-out of a claim is not a data-subject erasure (over-cascading would silently drop labeled training data). Residual gap: a disposition ingested *after* an objection, before re-sweep — narrow; follow-up if a per-contact sweep breakdown is added.

## Critical review (2 adversarial agents) + fixes applied
- **Merge resolutions: SOUND** (agent A, AST-diffed). No dropped exports/fixtures; single alembic head; all one-sided M13.4/M13.2 files byte-identical to source branches.
- **Wiring review (agent B) found one real correctness defect — FIXED:**
  - **Emitter transaction boundary (was: broken in 2-connection production wiring).** `surface.apply_action` emitted the disposition INSIDE its own uncommitted write txn, while the concrete `ReviewDispositionEmitterImpl` opens a SEPARATE txn and reads the `review_action` row back → under READ COMMITTED it's invisible → `_read_review_action` fell back to `(None, now())`, losing the reject reason + stamping a wrong `occurred_at`, plus an orphan-disposition risk on rollback. **Fix:** moved the emit to AFTER the write txn commits in `surface.py` (mirrors `finalize`'s resume-hook-outside-txn pattern; matches M13.2's `_read_review_action` docstring "written before the emitter runs"). The single-connection DB test masked it; strengthened it to a REJECT asserting the disposition preserves the real `reason_code`.
  - Added the missing `_STORE_IS_A_TOMBSTONER: type[ContactDispositionTombstoner] = DispositionStore` static assertion; fixed the "asserted below" docstring; noted the cascade's two legs are non-atomic (fail-safe by ordering).
  - **`require_finalized_review=True` was prose-only → added a real gate test** (`tests/api/test_handoff_wiring.py::test_require_finalized_review_gates_handoff_readiness`: un-finalized → gated out, finalize → through, default reader unaffected). Docstring corrected to "production must opt in", not "passes True".

## Tracked follow-ups (documented, not blocking — recorded for the close-out)
- **[M13.2×M10.5] cross-tenant disposition tombstone.** `DispositionStore.tombstone_for_contact` has no `client_id` predicate, so erasing a contact shared between two clients tombstones BOTH clients' dispositions, while `DataSubjectRights` is per-controller. Fix = scope the tombstone by `client_id` (M13.2-owned). Documented in `review_feedback_wiring.py`.
- **[M13.2×M10.5] sweep not cascaded.** Pre-handoff `sweep_expired`/`sweep_objections` aren't re-cascaded to dispositions (no per-contact `SweepResult` breakdown); a disposition ingested after an erase/objection before re-sweep is not re-tombstoned.
- **[M13 assembly] no committed process-wide app-assembly.** The REVIEW handler register, the `require_finalized_review=True` handoff opt-in, and the DSAR cascade are exported, discoverable builders/registrants — the deploying caller wires them (same as every other milestone's `register_*`). A single `register_m13_*` assembly + the M13.3 Wave-2 work are the next steps.

## Verification (DONE)
- `ruff format`/`ruff check` clean; `mypy` clean (256 src files); import-linter **11/11 KEPT**.
- Full suite **1857 passed / 14 skipped / 0 failed** (exit 0) on a pristine DB; `db-smoke` up→base→up single head `f9483ab9aafa`.
- New tests: `tests/api/test_review_feedback_wiring.py` (6, cascade + emitter-wiring, no DB), `tests/review/test_review_feedback_integration_db.py` (1, DB end-to-end reject→disposition), `test_handoff_wiring.py::test_require_finalized_review_gates_handoff_readiness` (1, DB gate).

## Next (Wave-2)
M13.3 (learning loop) off the integrated base — `labeled_dataset` + `get_source_yield` are now real; settle the 3 locked decisions (config_revision full schema; `core.BacktestGate` injected at api; extend `SourceYieldStat`).
