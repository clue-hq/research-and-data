# 2026-08-24 — Wave 3 (brand-geometry tokens in the web grammar) COMPLETE, walk-proven

Branch `integration/frontend-design-part-iv-v2`, base `8086f445b` → head `d824b1c28`
(17 commits). Plans: `docs/superpowers/plans/2026-08-20-brand-geometry-tokens-in-the-web-grammar.md`
(G1–G4, ratified with founder carve-outs) + the master plan's Wave-3 section
(adds G5). Process: subagent-driven development — Opus implementers, controller
inline review + independent Opus task review per slice, fix rounds + scoped
re-reviews, final Opus whole-branch review (verdict CLEAN) + one fix wave.
Ledger (all rulings, deferred minors, evidence paths):
`.superpowers/sdd/2026-08-20-brand-geometry-tokens-in-the-web-grammar/progress.md`
(gitignored scratch — this file is the durable summary).

## What landed (all task-reviewed, all fix rounds closed, suites green)

- **G1** (d269953b3, 096999073, 6fc2b0d0e) — ten kit-resolved geometry
  utilities are law in the web grammar: `rounded-button/card/badge`,
  `shadow-brand/card`, `border-w-card/divider`, `py-section`, `gap-stack`,
  `p-card`. `WebTheme` gains a `geometry` channel (NEVER in `tokens` — that
  map stays the colors-only lint/swatch vocabulary) + `utility_css`
  (`@utility border-w-*` — no Tailwind namespace exists for border widths;
  `border-card` would be a COLOR). Resolution = explicit chains per utility
  (e.g. shadow-card → shadow.md → shadow.sm → platform const `0 2px 8px 0
  #00000014`; shadows have NO kit fallback anywhere and `shadow.card` is never
  minted) with Advice LUMW0305 when an explicit kit exhausts a chain, silent on
  the platform path. CRITICAL FIX the plan text missed: published/exported
  pages never see `theme_block` — `web_export.py::_build_input_css` now carries
  the geometry vars + `@utility` rules, else geometry silently no-ops on every
  published page. Verified: with both `--color-card` and `--shadow-card`
  defined, the shadow namespace wins (no override needed).
- **G2** (615748adf, 27dcc8519, 53e258857, afceaca2f) — the normalizer now
  reads `evidence.geometry.background_sequence` (it NEVER did before):
  recurring measured band colors mint `surface.band.statement/tint(-N)` tokens
  (OKLab 0.03 grouping, kit-dedupe, ≥2 bands or ≥20% height, luminance naming,
  MEASURED_CONFIDENCE 0.8, gradient/image/ALPHA<1 bands refused). Stripe navy
  #0D1738 → `surface.band.statement` → author class
  `bg-surface-band-statement`. Brief agent may name bands by these tokens
  (prompt line added; token flows into brief vocabulary automatically).
- **G3** (8f61d10f7, 4f9deeefa, ed027bd21, 53acfbc89) — the authoring stack
  speaks the vocabulary: `WEB_GEOMETRY_UTILITIES` prompt constant + BRAND
  GEOMETRY author-prompt block; create-website's grammar table + rhythm
  section rewritten onto the utilities (raw px-6/max-widths stay raw by
  design); design-guidance deployment rules; recipes render
  `radius **rounded-button** (radius.button)` (chain-head map, ONE seam in
  brand_brief.py::_recipe_line — deliberately diverges from the frontend
  brand-brief.ts founder projection, documented at the docstring); reviewer's
  raw-geometry finding is PIXEL-PHRASED advisory prose. Drift guard parses
  GEOMETRY_UTILITIES from theme.rs and binds prompt + skill + Python map
  (icon-vocabulary pattern). Custom components: raw Tailwind geometry is
  CORRECT there (Tailwind 3.4.17, closed config, iframe gets only
  --lumen-color/font vars) — documented in that skill.
- **G4 code** (3122400e1, 0df7e4ab7, 683b74813, d824b1c28) — H2 phase-2 per
  carve-outs: LUMW0306 Advice when raw brand-shape geometry (all-corner stock
  radius steps minus `none`, xs–4xl+full+arbitrary; shadow scale minus
  `shadow-none`; side variants/spacing/borders excluded) appears over a
  briefed kit. `briefed` is read off the RAW kit JSON in the helper
  (`kit_is_briefed` — BrandKit stays brief-less; the pipeline's re-attach
  depends on serde dropping it), threaded via `IngestOptions` into ingest +
  fragment + WebValidate. Advice deduped per outcome (one line per raw class).
  THE ADVICE CHANNEL: warnings/advice split at every Python exit (accepted
  AND rejected envelopes — single `_rejected()` builder, `_store_rejection`
  retains work only), prompts teach "Warnings are work / Advice is not work".
  Advice can never reject (five Error-only gates) and reaches no human surface
  (GET /web/theme filters to errors — pinned non-vacuously via a DAL-published
  briefed kit; no web UI renders ingest diagnostics at all).
- **G4 walk** (live, 2026-08-24, 48 min; report + 27 evidence files in the SDD
  workspace) — ALL THREE PROVEN: (A) a real 34-min grok-4.6 generation on kit
  v6 produced a 168-node page with 31 utility usages across 7/10 utilities and
  ZERO raw geometry; LUMW0306 proven separately (raw classes on briefed v6 →
  2 advice entries, ok:true; unbriefed control → 0). (B) computed styles =
  measured tokens (rounded-card 6px, py-section 96px, [data-btn] 4px,
  border-w-* 1px, gap-stack 16px, shadows = the measured
  `0 15.93px 31.86px -8px #32325D1F`). (C) byte-identical markup re-renders
  different geometry when the kit payload changes (@theme diff exactly
  radius-card 6→10 / spacing-section 96→48) — geometry follows the kit pin.
- **G5** (8276e38c6, de9c23200) — web-lane retokenizer
  (`lumen_agent/web_retokenize.py`, scene precedent, LIVE-module tests):
  deterministic rebind of raw radius/spacing classes whose value is byte-equal
  (Decimal-canonical, 16px/rem) to a kit utility's resolved value —
  exact-or-nothing, tie-skip, cross-axis forbidden, variants preserved.
  Runs at the start of render_web_preview under three guards (non-platform
  kit; NOT seeded — new `seeded_from_initial_content` sharing
  `has_existing_content` with the harness; non-empty batch), applied as real
  invertible `set_node_classes` through the core, ledger-recorded,
  trace-only visibility, CoreError → silent no-op. `rounded-full` EXCLUDED:
  v4 compiles it to `calc(infinity*1px)` (compiler-verified), never byte-equal
  — the contract (a rebind never changes rendered output) beat the brief's
  9999px row. Tailwind-theme drift guard pins the stock-step table.

Final whole-branch review: CLEAN, merge-ready; advice lifecycle verified
leak-free end-to-end; carve-outs hold structurally (no new Error/Warning
anywhere, nothing human-facing, lumen-core/scene untouched); commit hygiene
pass. Suites at close: cargo workspace 1035/0; agent_runtime 800 collected
0 fail (1 pre-existing skip); apps/api exactly 22 pre-existing failures —
note the true pre-existing count is 22, not Wave-1's recorded 21 (the fifth
asset-store-family member lives in `test_workspace_seam.py`).

## Registered follow-ups (owners needed; full triage table in the ledger)

- **HIGH: `p-card` resolves 7px on Stripe** — ingestion measured a CHIP's
  padding into `space.card.padding` (the agent honestly skipped p-card in the
  walk). Ingestion measurement-quality bug, pre-existing, not a wave defect.
  G5's exact-equality contract immunises rebinding against it.
- **Chat-driven generation is BLOCKED on this branch** until rebase: the
  shared dev DB's recipe0-stage0 was superseded (v18/v19) by sibling
  worktrees; this branch pins @17 and RecipeLifecycle has no
  superseded→promoted transition. The walk used the design API's own
  `POST /documents/{id}/web/turns` (same trio/prompts/kit) — labelled
  substitution.
- **Kit v8 AND v9 are now APPROVED in the shared dev DB** (post-dating the
  founder's open R1 ruling); v9 — the latest, what a chat-born doc pins —
  carries NO BrandBrief, so brief-driven authoring + LUMW0306 are dark for
  chat generations until a briefed kit is latest-approved.
- webClassFacets (editor + frontend byte-twins) own gap-/py-/rounded-: a
  HUMAN inspector edit can replace a brand utility with a numeric step
  (silent de-branding; reading is byte-safe). Facet-level product decision.
- Pre-existing dead classes in custom-components' canonical example
  (`bg-card`, template-literal `text-${accent}`) generate no CSS under the
  component compiler config — needs an owner.
- Dev-stack noise (C15/W4 class): 8010 asset-store 404s cost walk review
  rounds; a stale queued turn failed at fleet boot.
- Deferred minors (all triaged FINE-DEFERRED by the final review): G1
  format_px negative guard / old-helper geometry-less export / LUMW0305
  subject=None; G2 white-dedupe margin, provenance truncation; G4
  variant-prefix near-duplicate advice, Rust-briefed looseness, 3 unsplit
  CoreError-fault envelopes; G5 empty-map-on-CoreError caching (cache only
  non-empty = the one worth doing opportunistically), OSError not wrapped.
- Do NOT wire LUMW0306 counts to any gate: the advice covers axes the
  retokenizer never touches (shadows, non-matching radii) — quiet ≠ handled.
