# 2026-08-20 — design-brief plan, slice 3: the brief agent + `BrandBrief@1` + the Design.md face

Plan: `docs/superpowers/plans/2026-08-20-brand-design-brief-and-craft-skill.md` §5 slice 3
(D1 ruling (b), D2 ruling: 6k rendered tokens). Brief:
`.superpowers/sdd/2026-08-20-brand-design-brief/slice3-brief.md`.
Branch `integration/frontend-design-part-iv-v2`. Commits `698f2993` (design), `0f120a65`
(frontend). Input contract: slice 2's evidence (`bef817cd`) — 29 shape records, 8 background
bands, mixed measured/derived provenance.

## What landed

### Design side (`698f2993`)

- `lumen_ingestion/brief.py` (new) — `BrandBrief@1`: `characterization`, `chromatic_moment`,
  `signature_compositions[]` (STRONG/SINGLE), `palette_application[]` (token + the six-value
  scope grammar), `background_rhythm`, `typographic_posture`, `imagery_posture`,
  `constraints[]`, `component_recipes[]`, plus per-entry `confidence` and a `diagnostics[]`
  channel. `kit_token_names()`, `token_references()`, `validate_brief()`, `BriefRefused`.
- `lumen_ingestion/brief_agent.py` (new) — `BriefRequest` (the agent's whole world, built
  purely), `NullBriefAgent`, `OpenRouterBriefAgent` (`create_agent` + `ToolStrategy`, over
  `lumen_agent.llm.init_model`), `resolve_brief_agent`, `generate_brief` (the fail-soft
  orchestrator), `load_brief_prompt`.
- `lumen_ingestion/pipeline.py` — `_brief_screenshots` + `_maybe_write_brief`, called in
  `_ingest` (website path only) between summarize and publish; `brief_agent` is an injectable
  parameter of `run_website_ingestion`.
- `py_lumen_config`: `lumen_ingestion_brief` (default False) + `lumen_ingestion_brief_model`;
  `.env.example` documents both.
- The controller-authored `brief_agent_prompt.md` was NOT moved and NOT edited; the harness
  loads it verbatim and a test pins that.

### Frontend (`0f120a65`)

- `model/brand-brief.ts` (new) — the Zod mirror of `BrandBrief@1` + `renderBrandBrief`
  (structured brief → the knowledge panel's markdown) + `DESIGN_BRIEF_DOCUMENT`
  (`design/Design.md`) + the 6k-token cap.
- `model/brand-kit.ts` — `brief: BrandBriefSchema.nullish().catch(null)` on `BrandKitJsonSchema`.
- `model/brand-context-mapping.ts` — `toKnowledgeFolders(kit)` replaces the hardcoded `[]`.
- `docs/api-contracts/brand-context.md` — a resolution section superseding slice 1's
  "knowledgeFolders ← honest empty in v1".

## Decisions worth remembering

- **The brief attaches to the ENGINE-VALIDATED kit, after the round-trip.** The Rust `BrandKit`
  (`crates/lumen-core/src/brand.rs:193`) has no `brief` field and no `deny_unknown_fields`, so a
  kit carrying one INTO `validate_brand_kit` comes back with the section silently dropped.
  `_ingest` attaches after `summarize_brand_kit`, immediately before `_publish_ingested_kit`.
- **No frozen-contract digest pins the kit payload shape.** Verified before minting: nothing in
  `platform/` or `tests/` hashes/compares `brand_kit_json`; the design-side goldens
  (`tests/fixtures/ingestion/expected/*.json`) are NORMALIZER output, and the brief stage runs
  after normalize, so they are untouched. The contract-delta ritual did not apply.
- **Approval cannot mutate the brief** — `clue_design.brand.update_brand_kit_approval` reads the
  stored dict, sets `approval_status`, writes it back. No engine round-trip on that path, so the
  reviewed brief rides through byte-identical (pinned by a test).
- **The token law is enforced twice.** A shape check on every token-bearing field
  (`TOKEN_NAME_PATTERN` — `#00A37A` and `8px` are not token names) and a resolution check against
  `kit_token_names(kit)`. Both refuse; neither partially keeps.
- **`TOOLS = ()` is the structural half of "evidence or silence."** An empty tool set is why the
  agent cannot fetch a second page and then write about it; the prompt is the prose half.
- **Unconfigured = silent.** No call, no diagnostic, no `brief` key — the `NullDescriber.active`
  idiom. Diagnostics only exist for LUMI0901 (refused), LUMI0902 (untrustworthy output),
  LUMI0903 (stage failed).
- **The markdown is a projection.** `renderBrandBrief` is pure; the design agent (slice 4) reads
  the structure. Only `#`/`##`/`###`, `- ` and `**bold**` exist in `parseKnowledgeMarkdown`, so
  a `1.` numbered list folds into one run-on paragraph — found in the live browser walk and now
  pinned by a test.
- **No new endpoint, no new UI.** The brief rides `GET /brand-kits/{id}`, and the Knowledge
  panel was already byte-identical to the dummy's (`clue-frontend@codex/brand-context-page`,
  worktree `.../clue-frontend/milan` — NOT port-of-spain, which carries the chat shell).

## Verification

- `apps/api/tests/test_ingestion_brief.py` — 25 tests: schema + refusal, the token law on all
  five token-bearing sections, absence-is-correct, the DSAR posture (no contact/person word
  anywhere in the JSON schema), the four fail-soft branches, the prompt-file pin, the pipeline
  ride-along end to end through the real route, approval non-mutation, pre-brief-era back-compat.
- Ingestion suites green: normalizer / capture / geometry / describe / font_metrics / jobs /
  routes / ui_api / pdf / uploads / pdf_route / uploads_route.
- Frontend: 882/882 (`npm test`, `tsx --test`), 13 new; `design-system:build`, `lint`, `build`
  all clean.

### Live proof (2026-08-20)

8010 still holds a pre-slice-2/3 module and may not be restarted, so both proofs ran the SHIPPED
code out-of-process.

1. Brief stage alone against live https://stripe.com: 29 shape records, 8 bands, 1 screenshot,
   119 tokens in → a grounded brief, **zero diagnostics**, 7 compositions / 10 palette rules /
   10 constraints / 11 recipes / 6 honest "no token for this" observations.
2. Full `run_website_ingestion` into workspace `ws_8040294627e146ae93f753ec0d3e1726` publishing
   **Stripe v4 DRAFT** (v3 approved untouched; nothing approved). One gateway call:
   22,804 prompt / 4,268 completion tokens, 95s, `role=ingestion-brief`.
   Characterization `precise, expansive, iridescent`; constraint "surface.brand violet is the
   sole solid saturated CTA fill"; recipe `button/solid.primary → radius.button, space.md,
   surface.brand, text.inverse`.
3. Browser (Playwright MCP, 3030, login `onboarding+clerk_test_20260814@example.com`):
   `/brand-context?section=knowledge&file=design%2FDesign.md&mode=preview` lists **Design →
   Design.md** and renders all ten sections with `Brand kit: brand_kit_ing_813d… · version 4 ·
   Draft`. Draft chip + Approve button present and NOT pressed.

## Open concerns (carried to slice 4)

1. **The knowledge breadcrumb is hardcoded** — `components/brand-context-header.tsx:47,51` render
   the literals `Company` / `brand-kit.md` regardless of the selected document, so the page now
   shows "Company / brand-kit.md" above a document titled Design.md. It is hardcoded IDENTICALLY
   in the dummy (`.../clue-frontend/milan/.../brand-context-header.tsx:39,43`), so per
   dummy-presentation-truth it was left alone. One-line fix (read `controller.selectedDocument`)
   pending a founder ruling.
2. **Website path only.** PDF and asset-upload ingestion do not run the brief stage — they have
   no measured geometry or screenshots to ground one. Deliberate; revisit if a PDF kit ever needs
   a brief.
3. **`brief` is design-side only so far.** `build_brand_card` does not read it yet — that is
   slice 4, where D2's cap must also be applied to the injected (not just rendered) form.
4. **The brief's `unmapped` / `diagnostics` channels are load-bearing.** Stripe's real navy
   statement band (#0D1738) and cool-gray footer (#F8FAFD) have NO kit token, so bands carry
   `token: null` + a note. If slice 4 wants those bands reproducible, the kit needs the tokens —
   the brief is correctly refusing to mint them.
5. **A second gateway call per website ingestion** (~27k tokens on Stripe). Bounded by
   `MAX_AGENT_STEPS = 6` and `MAX_SCREENSHOTS = 3`, off by default.
