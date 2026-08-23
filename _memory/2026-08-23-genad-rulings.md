# 2026-08-23 — genad: founder rulings + plan authored (chat-driven ad creation)

## The two founder rulings (ratified in chat, 2026-08-23)

1. **The v1 "editor-first" scene-creation refusal is REVERSED.** A document-less
   `open_design_leg` with `doc_kind="scene"` births an ad document, with the same
   disciplines as the genweb web birth: document id derived from the leg id
   (retry-convergent), create + leg insert in ONE transaction, leg pinned at
   `document_version_guard=0`, brand kit stamped at birth (fail-closed in a multi-brand
   workspace; honestly un-branded when no approved kit exists — identical semantics to
   web). The refusal being replaced: `design_leg_scene_creation_unsupported`
   (`platform/api/clue_api/design_leg_tools.py:731`, docstring :57, seed-script comment).
2. **Ad format is a structured tool parameter** — presets + a custom width×height escape,
   REQUIRED on a document-less scene open. Head-of-ABM **infers the format from the
   conversation and states it** (correctable in chat); explicitly NO hard confirmation
   gate ("I'd let the agent infer-and-state rather than hard-gate on confirmation" —
   founder's words). Durable human intent pinned as structure, same instinct as the
   product-selection gate but lighter.

## The load-bearing discovery made while planning

**The scene turn path is preview-only today** — `execute_agent_turn_job` never persists
(the run row holds the proposal; the MVP editor is the accept seam via
`PUT /documents/{id}/scene` / `AgentChatPanel`), unlike `execute_web_turn_job`, which owns
its persist under the envelope's frozen `base_version`. Without a persist step, a
chat-born ad would generate into a run row and never reach the document/gallery/editor.
The plan treats extending the genweb executor-owns-persist posture to **leg-only** scene
turns as in-scope (non-leg editor turns stay byte-identical — the P3.7 layering rule).

## Facts verified against the checkout (for whoever executes)

- Engine surface needs NO changes: `CoreClient.new_scene(document_id, title,
  artifact_type, medium)` mints a zero-page scene; `Operation::AddPage` (serde tag
  `{"kind": "add_page", "page": …}`) adds the artboard; page-literal shape mirrors the
  engine-validated seed (`scripts/seed_ad_document.py:355-372`).
- Brand stamping today is web-only (`_stamp_approved_brand_kit_at_birth`,
  `subsystems/design/clue_design/documents.py:64`); the scene branch reads
  `meta.brand_kit` for the effective columns, so a scene stamper slots in cleanly.
- Governed persist call shape pinned at `lumen_api/main.py:984-1022`
  (`design_apply_operations` args) and the web executor's CAS pattern at :8110-8190.
- Head-of-ABM profile: registry `v37` (`agent_registry_wiring.py:48`), profile folders
  `platform/agents/catalog/profiles/head-of-abm/`, prompts `…/prompts/head-of-abm/` (v5
  current); the v36→v37 diff is the template for a tool-version bump.
- Trip-wire test that MUST be consciously rewritten:
  `tests/api/test_genweb_leg_document_birth_db.py::test_scene_document_creation_is_refused` (:461).

## State — SUPERSEDED 2026-08-23 (same day): the plan was EXECUTED in full

All 7 tasks complete; see `_memory/2026-08-23-genad-close-out.md` for the shipped
commits, live-proof evidence, founder items, and incidents. Residuals deliberately
OUT of scope (unchanged): reference attachments in platform chat (runtime supports
them; no chat UI / no envelope resolution — dormant), leg CLOSE exit-judge gateway
timeout (pre-existing, shared machinery).

## ADDENDUM 2026-08-23 (evening) — RULING SUPERSEDED: the agent authors the pages (genad2)

The founder REVERSED the format-parameter mechanism of ruling 2 after the live evidence
(the F1 page-trap saga + the registry-complexity discussion). New ratified rulings:

1. **Zero-page birth.** `open_design_leg` (scene) creates the durable document + brand
   binding but NO page and NO format/dimension parameters. `ad_format`/`ad_width`/
   `ad_height` retire; `AD_FORMAT_PRESETS`/`ad_birth_page`/`mint_empty_ad_document` are
   deleted, not generalized.
2. **The design deepagent authors every page** from the user's own words via the DSL
   (`size(w,h,pt|px|mm|in)` / `preset(...)`); the engine normalizes. No preset registry —
   the agent's knowledge is the catalog. Head-of-ABM routes and delegates verbatim; it
   never resolves presets, units, or dimensions.
3. **300 DPI** stays the design subsystem's raster default. **No-dims asks** are resolved
   inside the design leg (agent proposes-and-states, or asks).
4. Surviving unchanged: one document = one artifact (pages are components of an artifact —
   a four-pager is ONE artifact); brand stamp at birth; leg/CAS discipline; F1 = legacy
   support only. Multi-page is STAGED LATER (pager-within-one-artifact model, page-switcher
   UI needs design first); nothing in genad2 may foreclose it.

Plan: `docs/superpowers/plans/2026-08-23-agent-authored-pages.md` (fact base:
`.context/genad2-readiness-scout.md` — engine/DSL/print-export READY; the px-only code is
the aperture: 2 adapter fns, 1 inspector section, 1 export builder, 1 birth helper,
1 tool input model, 1 wire schema; the ONE data-loss bug is scene-apply.ts:1390's
hardcoded unit:"px" destroying output.physical).
