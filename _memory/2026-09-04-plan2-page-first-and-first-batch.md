# 2026-09-04 — Plan 2 shipped: page first, pre-spend guard, canvas on the first streamed batch

Plan: `docs/superpowers/plans/2026-09-04-page-first-and-first-batch-canvas.md` (roadmap Plan 2,
items C+D, plus Task 5 found by the live proof). Commits `2dbcf0b0e..a5c46d994`; SDD with Opus
implementers, every diff reviewed and every test re-run first-hand by the controller. Restart the
design API + fleet worker after pulling (agent runtime changed); the frontend hot-reloads.

## What changed
- `tools/substrate.py`: `PAGE_REQUIRED_CODE = "scene.page_required"` and `_refuse_without_page(tool)`
  at the TOP of `generate_image`, `generate_qr`, `fetch_logo` — a pageless scene costs one tool
  call, never a model or vendor spend; trace event `<tool>_refused_pageless`. 12 pre-existing
  tests that called those tools on a pageless fixture now plant a page first (no assertion changed).
- `prompts.py` + `linkedin-square-ad/SKILL.md`: PAGE BEFORE ASSETS (director step 3), PAGE FIRST
  (author teaching body — the plan named `_AUTHOR_HEADER`, the anchor lives in
  `_AUTHOR_TEACHING_BODY`; ruling: keep at the anchor, test repointed), the work-loop sentence,
  and the skill's "Author it in your FIRST compile". Pinned by `test_prompts_page_first.py`.
- Frontend `scene-pageless.ts`: `effectiveScenePageId(loadedPageId, drawnScene)`; the canvas draws
  and hit-tests the page of the scene it is DRAWING (`displayScene ?? scene`) and the pageless
  notice keys off the drawn scene. The editing session still receives the LOADED scene + id. The
  pair sits below every hook on purpose (the React Compiler otherwise drops `setEditingNodeId`'s
  stable-setter inference and fails lint).
- **Task 5 (found live):** `record()` now routes an op-bearing `sink_extra` through
  `_contiguous_sink_extra`, which PREPENDS every `operations_ledger` entry appended since the last
  streamed frame (`_streamed_ledger_len`), and `checkpoint_scene` advances that marker. Reason:
  the frontend cursor (`scene-stream-cursor.ts` rule 5) applies a frame only when
  `operations_total − len(operations)` equals its position; the ledger grows at ~20 sites but only
  two push frames, so a compile's auto-registered kit assets (positions 1–2, no frame) made the
  first batch begin at 2 → cursor dirty → nothing drawn until the first checkpoint. Two existing
  sink tests moved to the new contract (an unstreamed seed rides the next frame).

## Live proof (colombo, project `prj_491f5449…`)
- Attempt 1 (thread `thr_70ca2e33…`, doc `doc_94e71449…`, run `run_b891860a…`, 10:55–11:09 IST):
  item C proven — the first compile carried the page (18 ops incl. `add_page`), 0 refusals,
  0 failed registrations, run `succeeded` in 13.5 min (4 min of reading before the first
  compile). Item D FAILED and exposed Task 5: 9 `design.op_batch` frames reached the browser
  (verified with an in-page EventSource), the stage kept the notice for 9 min, the ad appeared only
  at the first checkpoint.
- Attempt 2 (thread `thr_e8b5fd4c…`, doc `doc_f8668063…`, run `run_1a3978fe…`, sent 11:17:39):
  first frame at 11:22:18 = 24 ops ending at 24, beginning with the prepended `upsert_asset`
  registrations (begins at 0); the stage swapped the notice for the fitted artboard (45%) at
  11:22:23 with the document at version 0 and zero checkpoints — the streamed draft (headline,
  stat, CTA, logo slots) is visible in `/tmp/plan2-evidence-keep/attempt2-first-batch.png`.
  Run outcome: `succeeded` at 11:30:04 (12.5 min), 0 refusals, first checkpoint (v81) at ~11:29 — 6.5 min
  AFTER the stage had shown the streamed draft. Finalized `completed_with_warnings`: the self-audit
  rejected a split proof pair and the render budget left no room for a repair round. So the
  plan's 'repair round to spare' target is NOT met — the 4.6 min reading phase before the first
  compile eats it, not asset misordering (which is gone).
- The chat flow needs TWO messages: the first opens the design session (Head-of-ABM), the second
  starts generation. The sidebar "New chat" buttons did not create a thread from the browser tool;
  `POST /api/clue/api/v1/projects/{p}/threads` from the page context did (three empty
  "Plan 2 live proof" threads exist from silent evals — harmless).

## Open
- The design turn spends ~4 min reading (brief, kit, references) before its first compile; not
  Plan 2's scope, worth a budget look.
- Test-DB hygiene ruling still open (no DB tests in this plan).
