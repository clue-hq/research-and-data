# 2026-10-14 — editor sync fix: review findings fixed, close-out

Continues `_memory/2026-10-13-wave2-integration.md` (sync-fix entry). Branch `puck/integration-wave1`.

- Independent review of the sync fix (`.superpowers/review/2026-10-13-wave2/reports/sync-fix-review.md`,
  2 Important / 6 Minor) — all eight fixed, each from a test proven RED on the previous code:
  - F1 `bb6b4bb40` superseded working copy (typing between a landed undo / refused save and its reload is
    never saved); F2 `89ff94296` a proposal overtaken by an app patch is re-proposed; F3 (in F1 commit)
    deferred reload survives a transport failure; F5/F8 `07ac8b66c` browser assertions on canvas state.
  - F4 `6aad60d34` save controllers kept per document across visits (registry in `use-site-saves.ts`);
    a detached controller still sends in-flight/queued work but fires no reload/superseded notices
    (they hit the shared working copy, which holds the OTHER document — found while fixing F4, own test).
    Bridge now takes `otherDocument` (one fake server per document).
  - F6 `161477099` `keys.ts`: every ⌘/Ctrl chord on physical KeyZ/KeyY/KeyI is stopped (Puck matches
    `code`, ignores left Alt); ours acts only on the real character without Alt; editable check reads
    `composedPath()[0]` (open shadow roots). Puck hotkeys inventory: meta/ctrl + z, shift+z, y, i;
    plus bare Backspace/Delete (not touched — Puck deletes the selected item; worth a look later).
  - F7 `29580ee78` CloneEditor: a blur that moves to a sibling slot remembers its key; after the one
    rebuild that follows a write (React's, or the deferred S1-4 redraw, cancelled if React rebuilds
    first) the slot with that key gets the focus back, caret at end.
- Ledger + docs: 12 findings marked fixed (S1-1, S1-2, S1-4, S2a-1, S2a-4, S2b-2, S2b-3, S2b-4, S3-3,
  K1-4, K3-3, K3-5) in FINDINGS.md and both verification docs. Review now **83 open: 4C / 29I / 50M**
  (Criticals left: K1-1, K3-1 [founder picking fix], K4-2 [parked], S7-1).
- Gates (final): frontend gate green (lint 0 errors / 7 old warnings, build ok); app tests 3409 —
  3404 pass, 0 fail, 5 skipped, 0 cancelled; site-kit 170/0; site-editor 54/0; browser harness 17/17
  (`CLUE_SITE_EDITOR_BROWSER=1 uv run pytest tests/site_editor`); new F7 browser tests passed 3 extra runs.
  Design API not touched since its green run.
- Owed: live walk on trenton (no site document in clue_trenton: agent run or a fixture site write —
  founder's choice, unanswered); Phase 2 instant undo (optimistic undo + prefetched snapshots; measure
  the validator first); founder calls K3-1 / K1-7 / K6-4 / S7-1; remaining fix-pass groups (§5 of the
  area doc).

## Live walk (founder, 2026-10-14) and its one finding
- Setup: trenton `.env` `CLUE_DESIGN_SITE_ENGINE_WORKSPACES` now lists Conduit AI, Garner Health,
  Stripe, AltCarbon (it was empty = every website born a legacy `web` doc; the first run built a web
  page and was stopped). Agent built `doc_5dc514b3…` (site, Garner → Syracuse City School District):
  one page, five ClonedSections, shell; ~9 min, 22 LLM calls, one `design_write_site`, no errors.
  Account record's domain `syracusecityschools.com` has no DNS → no logo (data issue, handled).
- Founder ran the 9-step checklist: 8 pass. Step 5 failed: typing then reloading without leaving the
  box lost the text. Cause: clone text slots wrote only on blur; no unload warning anywhere.
- Fixed (test-first, red proven): `48f71eb06` protocol `pending` message + frame `noteTyping` +
  app beforeunload while frame pending or any site's save in flight (`useSiteSaves.allIdle`);
  `afb213420` CloneEditor writes 500 ms after the last keystroke, holds the clone's markup while a
  slot has focus (no redraw under the caret; F7 refocus code removed as unnecessary).
- Gates: site-kit 171, site-editor 60, app site-editor 92, browser 19/19, frontend gate green
  (app 3407 pass / 0 fail / 5 skipped).
- Owed: founder re-check of step 5 on the live stack (reload the app page first — the editor frame
  bundle was rebuilt). Saves take 2.2–2.7 s each (validator) — measure in Phase 2.
