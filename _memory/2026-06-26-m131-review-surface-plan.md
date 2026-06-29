# M13.1 — Tier-1 review surface (implementation plan & decisions)

**Branch:** `m13.1/review-surface` (off `integration/m10-m11-m12-v2`, alembic head `05f66cc526ae`).
**Spec:** `docs/specs/M13-review-feedback-observability.md §M13.1`.

## Locked design decision (user, 2026-06-26) — Option B
> Tier-1 review is a **new `REVIEW` campaign phase between `verification` and `handoff`**, suspending
> via the existing `AWAITING_INPUT` mechanism; per-claim dispositions live in the review tables;
> **per-account handoff is gated on per-account session finalization.**

Chosen over Option A (a new per-account-graph `interrupt()` node) because it reuses tested, crash-safe,
idempotent machinery already reserved for M13 (`PhaseCheckpointStatus.AWAITING_INPUT` docstring names
"the review payload the surface (M13) reads back"), sits at the architecturally correct phase point,
and adds no novel primitive. **Documented divergence:** the spec's literal "interrupt() on the
per-account graph at ready_for_review" is *superseded* by the campaign-phase `AWAITING_INPUT` gate;
the `finalize → resume` seam preserves the Temporal swap. (Updating the spec note is a plan task.)
Optional hybrid (a per-account `ready_for_review` advisory `AccountRunSubPhase` marker) is **skipped**
for v1 — the `review_session` rows already give the per-account "ready/finalized" queue signal.

## Verified facts (from code, not spec)
- **Phase order = enum declaration order.** `durable/campaign.py:82 PHASE_SEQUENCE = tuple(CampaignPhase)`;
  `next_phase()` is index+1. Inserting `REVIEW="review"` between `VERIFICATION` and `HANDOFF` in
  `core/enums.py:CampaignPhase` makes the whole flow `verification→review→handoff` automatically.
- **PAUSE/resume.** Handler returns `PhaseResult(status=PAUSED, payload=...)` → state machine writes an
  `AWAITING_INPUT` checkpoint + `CampaignRunStatus.PAUSED` (campaign.py:463-474). `submit_checkpoint(
  {action:"approve"})` commits + transitions to next phase; **the paused handler is NOT re-run**.
  Precedent: `discovery_scoring/phases.py TierCheckpointPhaseHandler`.
- **REVIEW must NOT be in `_BUDGET_GATED_PHASES`** (campaign.py:107) — it's a human gate, spends nothing.
- **`review/` import boundary** (pyproject.toml:171-185 independence + comment 169-170): MAY import
  `core/config/obs` + `claimstore/identity/icp/sources`; MAY NOT import sibling workers
  (`verification/compliance/discovery_scoring/narrative/durable/...`). README is STALE — fix it.
- **Correction** = new `ExtractionMethod.HUMAN` claim, `source_tier=1` (LOWEST tier wins `merge._winner`,
  which does NOT privilege HUMAN), `VERIFIED`, `supersede_claim(target.id, c, validate_field=True)`.
  contact.facet correction → `STRONG` binding + copy `use_class` (else `can_be_promoted` False → raises).
- **Reject** = REJECTED redacted-sentinel claim, `source_tier=1`, HUMAN, `supersede_claim(...,
  validate_field=False)`; `merge._is_eligible` drops REJECTED → absent from `current_value`/handoff.
  Model on `compliance/dsar.py:212 build_tombstone`. contact.facet reject → `WEAK` binding.
- **Immutable trigger** (migration 0002): only `(superseded_by, verification_status, corroborations)`
  UPDATE-able; supersession only flips `superseded_by` → allowed even on a VERIFIED tier-4 claim.
- **Score decomposition**: read score CLAIMS by field_key STRING `account.scoring.fit`/`.intent`
  (review CANNOT import `discovery_scoring`). `value_json` IS a serialized `core.Score` + extra keys →
  filter to `{value, components}` before `Score.model_validate`. (Promote the two field-key constants
  to a shared core home as a follow-up; inline them in review/ for now.)
- **Per-claim annotations** (faithfulness verdict M9.3, use-gate M10.3, conflict_flag M9.2): NO public
  reader exists (only private `_load_cached` + write-only `_raise_conflict_flag`). review can't import
  verification/compliance → inject a **`VerificationAnnotationReader` Protocol (defined in core)**,
  concrete impl at the api root (promote the private readers to public fns there). Read OPEN
  `conflict_flag` rows, NOT `CurrentValue.conflict` (it over-flags per the M9.2 gotcha).
- **Resolve every id through `identity.surviving_id`** before reading its claims (merged-loser redirect).
- **value_narrative is BEST-EFFORT** — `account.value_narrative` claims may not exist pre-handoff; `()`.

## Staged implementation (each a green `make check` checkpoint)
1. **Core contract-delta + migration** (FOUNDATION):
   - `core/enums.py`: insert `REVIEW` between VERIFICATION/HANDOFF; add `ReviewAction(approve|correct|
     reject)`, `ReviewSessionStatus(open|finalized|abandoned)`, `ReviewRejectReason(...)`.
   - `core/review.py` (NEW): value types (`ReviewClaimRow`, `ReviewCommitteeMember`, `ReviewSession`,
     `ClaimAnnotation`, `FieldConflict`, `ReviewActionOutcome`, `ReviewSessionId`) + Protocols
     (`ReviewSurface`, `VerificationAnnotationReader`, `ReviewResumeHook`, `ReviewDispositionEmitter`).
   - `core/__init__.py`: export all.
   - Migration `<hash>_m13_1_review_surface.py` (down_revision `05f66cc526ae`):
     `ALTER TYPE campaign_phase ADD VALUE IF NOT EXISTS 'review' BEFORE 'handoff'`; create
     `review_session_status`/`review_action_kind`/`review_reject_reason` enums; `review_session`
     (UNIQUE(account_entity_id,campaign_run_id,review_round); INDEX(campaign_run_id,status);
     CHECK (status='finalized')=(finalized_at IS NOT NULL)) + `review_action` (append-only;
     CHECK (action='correct')=(corrected_value_json NOT NULL)) tables. Do NOT edit shipped ce08… ;
     ALTER ADD VALUE is irreversible (downgrade drops tables/enums, leaves the label — documented).
   - Update drift literals: `tests/durable/test_campaign_phase_sequence.py:_EXPECTED`,
     `tests/test_obs_spans.py`. (parity `tests/durable/test_campaign_run_db.py` auto-passes via ADD
     VALUE BEFORE 'handoff'.) Register a REVIEW handler in any state-machine test that loops
     PHASE_SEQUENCE (else `NoPhaseHandlerRegistered`).
2. **`review/` impl**: `review/projection.py` (ReviewProjector — store reads + injected annotation
   reader), `review/surface.py` (ReviewSurfaceImpl: open_session/apply_action/finalize + correction/
   reject claim writes + review_session/review_action repo), `review/repository.py` (DB rows). Fix README.
3. **`api/review/`**: `handler.py` (ReviewPhaseHandler — opens a session per ready account, returns
   PAUSED), `composition.py` (build/register), `__init__.py`. `api/review_wiring.py`
   (production `VerificationAnnotationReader` over verification/compliance + the `ReviewResumeHook`
   over `CampaignRun.submit_checkpoint` + no-op `ReviewDispositionEmitter`). Register at composition root.
4. **Handoff gate**: `finalized_review_account_ids(conn, campaign_run_id)` + extend
   `api/handoff_wiring.py DurableHandoffReadinessReader.ready_accounts` with `require_finalized_review`.
5. **Tests**: phase-handler unit (fakes, tests/api/test_review_handler.py); projection/surface unit;
   DB-gated integration (correction wins current_value; reject absent from handoff+provenance;
   suspend→submit_checkpoint→handoff; finalize gates per-account handoff; enum parity; append-only).
6. **Docs**: update M13.1 spec note re Option B divergence; close-out `_memory` entry.

## M13.2 seam (deferred, do NOT build here)
`ReviewDispositionEmitter` Protocol in core; api root wires a **no-op** default. M13.2 supplies the
`DispositionStore`-backed emitter + the disposition taxonomy/tables. AC5 ("emits the disposition") is
met by the seam call; review_action rows are the durable audit M13.2 reads/mirrors. See [[2026-06-25-m10-m11-m12-integration-plan]].

## Status — M13.1 COMPLETE (all stages done & committed on `m13.1/review-surface`)
- **Stage 1** (`dc2e3a6`): core contract-delta (`REVIEW` phase + `ReviewAction`/`ReviewSessionStatus`/
  `ReviewRejectReason` + `core/review.py` value types/protocols + exports) + migration `c48ebe0a1e62`.
- **Stage 2** (`8b4693c`): `review/` impl — `repository.py` (review_session/review_action
  DB), `projection.py` (ReviewProjector + InMemory annotation reader), `surface.py` (ReviewSurfaceImpl:
  open/apply/finalize + correction=tier-1-human-supersede, reject=REJECTED-supersede). README fixed.
- **Stages 3-5** (`bb2bda8`): `api/review/` (ReviewPhaseHandler → PAUSED; DbVerificationAnnotationReader
  over the 3 side tables; CampaignRunResumeHook; NoopReviewDispositionEmitter; build/register) +
  handoff gate (`DurableHandoffReadinessReader.require_finalized_review`, default OFF + back-compat) +
  `finalized_review_account_ids` + tests (fake-only handler + 5 DB integration proofs).
- **Stage 6**: spec divergence note (Option B supersedes the per-account `interrupt()` framing) in
  `docs/specs/M13-review-feedback-observability.md §M13.1`; this close-out.
- **Verified:** ruff, mypy (248 src files), import-linter 11/11 KEPT, db-smoke reversible (single head),
  **full suite 1806 passed / 14 skipped / 0 failed** on a fresh DB.

### Follow-ups / deferred (not blocking M13.1)
- `value_narrative` is `()` in the projection (M12 narrative is assembled at HANDOFF, *after* REVIEW —
  the reviewer reviews the claims that *feed* it; populate once narrative claims exist pre-handoff).
- The M9/M10 annotation reads are raw SQL at the api root (`DbVerificationAnnotationReader`) — could be
  promoted to public reader fns in `verification`/`compliance` later.
- `ReviewDispositionEmitter` is a no-op until **M13.2** supplies the `DispositionStore`-backed emitter;
  `review_action` rows are the durable audit M13.2 reads. The handoff-gate `require_finalized_review` is
  default OFF — the full-flow wiring (app composition root) must opt in `True` for HANDOFF + register
  the REVIEW handler (the end-to-end suspend→submit_checkpoint→handoff is covered at the unit/surface
  level; a full state-machine integration test is a good add when the app root is wired).
- Score field-key constants (`account.scoring.fit`/`.intent`) are inlined in `review/projection.py`
  (decision: don't import discovery_scoring); promoting them to a shared `core` home is a DRY follow-up.

### Infra
- Throwaway DB: `docker` container `clue-pg-m131` on **:5436** (worktree's `make db-up`/:5432 taken by a
  sibling). DSN `postgresql+asyncpg://clue:clue@localhost:5436/clue` — pass inline to alembic/pytest.
