# 2026-09-02 — scene-ad live streaming, rung B SHIPPED (op-batch live reveal + late join)

Plan: `docs/superpowers/plans/2026-09-02-scene-live-streaming.md` (rung B = Tasks 6–11). Rung A
memo: `_memory/2026-09-02-scene-streaming-rung-a.md`. Regime: Opus implementers, Fable
orchestrates/reviews/verifies/decides (founder rule). Ledger:
`.superpowers/sdd/2026-09-02-scene-live-streaming/progress.md`.

## Commits (local, `design/scene-ad`, base a4207c775 → 7dc5ba0b4)
- 4ac0cb630 — runtime: `dsl_compiled`/`asset_placed` sink events carry `operations_total`
  (ledger POSITION after the batch — non-streamed ledger ops exist).
- cd6490209 — platform: `design.op_batch` frames `{document_id, operations, operations_total,
  iteration}` (256 KiB → position-only); forwarder extracted to `design_event_forwarder.py`;
  migration f506a1210f0c widens the turn-event CHECK again.
- 51993084a — frontend: `design.op_batch` parse + pure `SceneStreamCursor` (contiguity =
  `operations_total − batch length === position`; gap/position-only/malformed → dirty until an
  anchor; anchors re-seat).
- 61f06088e + a10f2c61a — the ported MVP reveal pump (timings verbatim; engine-ahead, held
  display swap; display-state only; resume-by-sequence); anchor reload = `!(cursorInSync &&
  pumpClean)`, unknown health → reload.
- 4da86a9ee + da705c8f4 + b0fb407a7 + 7dc5ba0b4 — late join: seed from the in-flight TURN's
  checkpoint (exact version match or dirty); cursor + seed scoped per (document, turn) — a new
  turn is a fresh ledger on the loaded base; join replays the turn's logged applies through the
  seeded cursor (never seeks past them); turn-less seeds defer/adopt; `appliedThrough` dedup.

## Proven live (Apollo ws, thread thr_f8fbbbfa…, doc_1c35a98d…, walks #3–#9)
- Primary path: the FIRST op batch of a fresh run reveals on the open tab (CTA text changes)
  with ZERO document refetches, before any checkpoint (~75s after send).
- Late join: mid-run page reload → exactly one refetch (the committed version) → the streamed
  backlog replays onto it (canvas shows the streamed state) → the next checkpoint anchors IN
  SYNC with no refetch (two instrumented samples: cursor {pos 1, clean}, pump clean, reload:false).
- Lock engages on join from the durable wire; unlock at terminal; text session with typed changes
  open at send time blur-commits BEFORE the lock; killed worker → run orphaned, lock held (no
  reaper outside the worker); worker back → platform RETRIES the same turn (no turn.failed) and
  the re-driven ledger re-emits identical frames (P0.4 replay guard holds the version).
- Gate at close: frontend 2445/2445 (baseline 2246); backend rung B files 42/42; lint clean.

## Rulings that corrected MY plan (recorded so nobody re-learns them)
1. Ledger positions are PER RUN → cursor/seed scoped per (document, turn); new turn = reset.
2. Seeding from a checkpoint with version < loaded version re-applies ops the document holds →
   exact-match-or-dirty is the honest rule (implementer's correction, ratified).
3. A join must REPLAY the in-flight turn's backlog through the seeded cursor, not seek past it.
4. Contiguity must use `operations_total − len(ops) === position` (non-streamed ledger ops).
5. Anchor reload composes cursor sync with pump health; unknown health → reload.
6. Walk #7's one anchor reload occurred while TEMP-DIAG edits were hot-reloaded mid-run (Fast
   Refresh churn) — not reproduced from clean loads; classified residual, breadcrumbs documented.

## Deferred minors (none block merge)
T6: `apply_operations` runtime path un-streamed (anchors catch it). T7: forwarder log event
names still say checkpoint_*. T8: cursors keyed by the frame's document id. T9: health probe read
one tick before the pump acts (same-commit refusal → one extra reload); no drawn-box chrome
(paced materialization only). T10: backlog boundary = one consume pass; pump may apply before its
first seed; StrictMode double-seed in dev; two log records per turn crossing; `turnId === null`
join replays nothing until the next load.

## Founder-visible
- Worker down → orphaned run stays `running`, editor locked, no terminal frame until a worker
  returns and RETRIES (never fails) the turn. Decide: a reaper/timeout outside the worker?
- Test suites still seed real runs into the shared dev DB (fixed twice tonight by failing
  `ws_test_%` rows); the claim-query exclusion / disposable DSN ruling is still open.
- Rung C (web lane) needs the web `_LegSceneCommitter` equivalent first.
