# 2026-08-27 — Phase F1 (Fragment engine substrate) COMPLETE

Plan: `docs/superpowers/plans/2026-08-27-clone-fidelity-master-plan.md` (status header updated).
Commits `1d04b46df..5b68e1b13` (23) on `integration/frontend-design-part-iv-v2`, LOCAL ONLY.
Process: SDD — Opus implementers, Opus-ONLY reviewers (founder standing rule since F0 close),
5 task-level fix rounds + ONE final fix wave; full evidence + rulings in
`.superpowers/sdd/2026-08-27-clone-fidelity-master-plan/progress.md` (preserved).
STANDING RULES added mid-phase (founder): (1) Fable hand-fixes ONLY if Opus genuinely cannot;
(2) do NOT stop colombo-worktree processes (its tests run concurrently — throwaway-DB isolation
is our side of the contract); (3) NO full apps/api suite at phase close (≈1h) — focused
fragment-family gate instead.

## What F1 delivered
- **F1.1 (Rust, lumen-web)**: `WebNodeKind::Fragment { fragment_id, slots }` leaf;
  `FragmentSlotValue` serde-TAGGED `{"text"|"asset"|"visible"}` (untagged collapses Asset→Text);
  id shape `frag_<16 lowercase hex>` injection-load-bearing, checked on BOTH write paths + again
  in the render arm; slot keys `[a-z0-9_-]` ≤64, ≤64 slots, values ≤8KB; LUMW0033/0034.
- **F1.2 (Python)**: `design_web_fragment` (migration `611add94c5a4`, design lane, single head;
  DAL `clue_design/web_fragments.py`); immutable content-addressed artifact
  {html, css, asset_digests, slot_manifest, preview_digest}; TWO-STAGE addressing (id hashes
  pre-scoping identity — plan's literal wording was self-referential); D-F4 sanitizer
  fail-closed (survived two adversarial Opus reviews: `</style>` CSS breakout defused+refused,
  SMIL+`<discard>` dropped, `<template>` dropped, image-set() gated, planted data-lumen-*
  stripped, bad-url refused INCLUDING at-rule preludes/selectors); CSS scoper under
  `.lumen-frag-<16hex>` (wrapper class = `fragment_wrapper_class()` — the frag_ prefix is
  STRIPPED; one definition, every speller imports it); reference-integrity gate beside the
  custom-component gate (fail-closed on write, fail-soft on read).
- **F1.3**: render-options fragment map KEYED BY FRAGMENT ID (not node id); in-flow wrapper;
  `WebThemeOptions.fragment_css` before compiled site.css; both preview paths (editor route +
  agent render_web_preview); placeholder on missing/invalid (LUMW0411/0412); TS/Python surfaces
  tolerate kind "fragment".
- **F1.4**: substitution walk (quick_xml, verbatim-copy, markers preserved; text HTML-escaped,
  href scheme-allowlisted, asset via doc.assets only — LUMW0413-0417); RULED: asset slots must
  resolve in doc.assets (LUMW0035/0415 mirror LUMW0014); derive `apply_fragment_slots` with
  {{…}} substitution — account name/domain/logo personalize through the REAL derive route with
  zero new Python plumbing (claim verified); backstop drops slots, never renders templates.
- **F1.5**: export ZIP + publish thread the same map; `_node_asset_ids` class fix (image +
  background + fragment slots + artifact digests — the "recorded background-image ZIP gap" =
  WebBackgroundImage, adjudicated); `_sweep_fragment_asset_custody` symmetric loud
  missing-bytes on both paths via custody_states (ROW_ONLY = missing); manifest lists fragment
  ids + missing digests + FONT EXCLUSIONS (stops discarding); D-F2: real `FontLicense.basis`
  (lumen-core — stamp moved to `2f8c4edaf3b6`), emit migrated off the restrictions line, publish
  gate honors platform-terms basis; cross-path parity test.
- **Fix wave**: artifact-internal `/asset-store/<digest>` refs rebased vs asset_base_url at the
  API layer ONLY (engine fix PROHIBITED — would silently break ZIP's assets/<digest> rewrite;
  recorded at the function); FragmentRefused caught → missing+placeholder (4-path pin).

## Acceptance (live walk, task-10-walk-report.md, evidence /tmp/f1_walk 35 artifacts)
All 7 PASS: in-flow render; fragment markup digest `7605ef0736c7ccd6` + CSS digest
`7c8929ed5f7689f5` IDENTICAL across all four paths; slots substitute; derive personalizes;
red-cases refuse/strip live; HANDSHAKE OK. The walk FOUND the asset_base_url gap (fixed in the
wave — the old preflight self-built the URL it was probing, so it could never catch the class).

## Suite gate (founder-ruled focused)
API: 8 fragment-family files exit 0 (clue_f1_gate). Agent-runtime: test_web_fragment_preview
11/11 junit. Known environmental families NOT re-run: 17 custom-component (typescript dep),
2 canvaskit-wasm. All clue_f1_* throwaway DBs dropped.

## Carry-forward register (owners assigned in the final review's triage, in the ledger)
- **F2**: status-gate wiring (draft/approved/deprecated READ BY NOTHING — kit-approval filter);
  agent-facing naming collision (`insert_fragment` vs unrelated `web_ingest_fragment` — rename
  to "cloned section" vocabulary before F2.3); Tailwind-scanner amplification RULING (export
  compiles site.css from post-fragment HTML → cloned class tokens generate utilities; exclude
  fragment subtrees from scan input OR layer fragment CSS); prelude fail-closed false positives
  (@supports url() probe / @document / image-set — documented, relax-is-a-decision); srcset
  comma-URL mis-parse (errs closed; real pages will hit it); FragmentRefused corrupt-vs-gone
  indistinguishable in logs; annotator slot-in-slot detection guidance (LUMW0417 warns, doesn't
  personalize); rebase-regex docstring over-claim; F0 carries (page-list producer, light-
  preferred picture rung, data-URI font custody, LUMI0231 wording, dark-side declared roles).
- **F3**: fragment inspector card + D-F3 bridge allowlists (NOT done in F1 — deliberately);
  LUMW0011 wrap-in-section on insertion; diagnostic id escaping at surfacing layer; LUMW0413
  noise on un-derived template pages; collision-warning specificity wording; LUMW0606 double
  duty; `alt` not rewritten on bound image slots (needs a T5-contract vocabulary ruling).
- **F4**: protocol-relative `//host/x` passes href_is_allowed (matters when account-derived
  hrefs bind); og:image ignores background-only pages.
- **F5**: `_page` vs `page_fragment_ids` page-fallback divergence (multi-page only).
- **SECURITY register**: publish serves harvested third-party bytes via workspace-unscoped
  `/asset-store/{digest}` — filed beside the standing [B2×presign] policy bullet.
- **Environment**: golden-PNG trap — `cargo test --workspace` regenerates untracked PNGs (not
  gitignored); never `git add -A` in clue-design.
