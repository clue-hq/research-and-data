# 2026-08-20 — design-brief plan, slice 4: consumption, the coherence walk, close-out

Plan: `docs/superpowers/plans/2026-08-20-brand-design-brief-and-craft-skill.md` §5 slice 4.
Brief: `.superpowers/sdd/2026-08-20-brand-design-brief/slice4-brief.md`. Branch
`integration/frontend-design-part-iv-v2`, worked directly. Commits `f2e584eb` (design
consumption), `ec096404` (frontend breadcrumb), plus this record.

## What landed

### Design — consumption (`f2e584eb`)

- `lumen_agent/brand_brief.py` (new) — `read_brief` (envelope-strict `BrandBrief@1`
  reader), `render_brand_grammar` (measured geometry + the ten brief sections, D2-budgeted),
  `render_reviewer_brief` (the review-relevant subset), `estimate_tokens`.
  The section order and every line format MIRROR the knowledge panel's projection
  (`apps/frontend/.../model/brand-brief.ts::renderBrandBrief`) — one projection, so the
  prose the founder approves and the prose the agent designs from are the same prose.
- `brand_card.py` — `build_brand_card(..., include_brief=False)` and the new
  `render_brand_card_text(card)`. The brief lands as `card["creative_brief"]`
  (`{schema, rendered, truncated, omitted_sections, estimated_tokens, token_budget}`);
  the text form splices the prose BESIDE the JSON so no newline is escaped.
- `tools/web_substrate.py` — the web card is built with `include_brief=True` and exposes
  `reviewer_brief_text`. The SCENE substrate call is untouched (D4).
- `prompts_web.py` / `harness_web.py` — `build_web_reviewer_prompt(brief=…)`, fed from
  `tools.reviewer_brief_text`. Slice 1's dormant `review-website` hooks are now live.

### Frontend — the breadcrumb (`ec096404`)

`model/knowledge-breadcrumb.ts` + test: `knowledgeBreadcrumb(path)` derives the trail from
the selected document's path (the route's `?file=`). Folder segments humanized from their
own path segment, file segment kept verbatim, nested paths get a segment each, root-level
documents get no invented parent, empty/garbage paths get no crumbs. No filename→label
table. Non-knowledge sections carry no breadcrumb by design (dummy and ours alike).

## Decisions worth remembering

- **The brief and the geometry ride together.** `include_brief=True` adds BOTH or neither.
  A kit with measured geometry but no brief therefore gets today's card. That is what makes
  slice-4 brief-A4's byte-stability guarantee a single clean switch instead of two half
  states; the measured radii still reach the page through the THEME regardless (that is how
  the walk's 4px buttons happen), the card block is about agent judgment.
- **D2's cap is applied to the block slice 4 ADDS** (geometry + brief prose), not to the
  whole card. D2 is a statement about the brief's size; the pre-existing card is unchanged.
  Live Stripe v6: 4,063 estimated tokens of 6,000, not truncated.
- **Geometry renders FIRST inside the block.** Under the cap the first section survives, and
  the measured shape is the part that makes a generated button this brand's button.
- **`derived:` tokens are shown but never as brand facts** — separate "Platform defaults —
  engine scale steps, NOT brand facts" list, no `website:` pointer, and a test that fails if
  a `derived:` pointer ever leaks into the card.
- **The reviewer's subset is deliberately three sections** (characterization, constraints,
  background rhythm). It judges; it does not author.
- **The leg pin needed no new machinery** — `apps/api/tests/test_brand_pin_brief.py` approves
  version 2 mid-conversation and shows a leg pinned to version 1 still rendering version 1's
  characterization and constraints into the card.

## The coherence walk (live, 2026-08-19/20 UTC)

Stack restarted onto these commits: 8010 design API (`/tmp/slice4-relaunch-8010.sh` — the
slice-0 script PLUS `LUMEN_INGESTION_BRIEF=1`), istanbul `clue_api.fleet_main`
(`/tmp/slice15_fleet_worker.sh`). 8030 + 3030 already live and untouched (platform API
unchanged by this slice; Next dev hot-reloads the frontend). tunis/missoula/milan/
port-of-spain never touched.

Workspace `ws_8040294627e146ae93f753ec0d3e1726`, project `prj_79aa603b3c3853898045e3cfa414e136`,
login `onboarding+clerk_test_20260814@example.com` / `pass@123` / code `424242`.

### 1. Breadcrumb, live

`/brand-context?section=knowledge&file=design%2FDesign.md&mode=preview` renders
**Design / Design.md** (was `Company / brand-kit.md`).
Screenshot `brief-walk-01-breadcrumb-design-designmd.png`.

### 2. Re-extraction → Stripe kit **v6**, approved in the UI

- **The UI's Re-extract button produced a briefless, geometry-less v5** — see the blocker
  below. v5 is left as a DRAFT and must not be approved.
- A forced-render re-extraction of https://stripe.com through the shipped pipeline
  (`run_website_ingestion`, out of process — the deviation is the blocker below) published
  **v6** in 2m58s: **28 measured geometry tokens**, a real `BrandBrief@1` —
  characterization `precise, product-led, infrastructural`, 9 constraints, 12 component
  recipes, 8 background bands, 6 honest "no kit token" observations — and one gateway call
  (grok-4.5, `role=ingestion-brief`, 22,801 prompt / 5,476 completion tokens, 116.6s).
- **v6 approved through the real UI** (founder-sanctioned) on `/brand-context`; the panel
  then reads `version 6 · Approved`. Screenshots `brief-walk-02-v6-draft-designmd.png`,
  `brief-walk-03-v6-approved-designmd.png`.

### 3. The generation — doc `doc_2543706b1da856eab16f0e9f2bcfcc42`

New chat `thr_1922bfdabace5edb8d9fbd1aa2e8a8d5`; message 1 opened the design leg, message 2
started generation. The document was born pinned to **kit v6**.
Run `run_6fb134c34ef85a028709588fef29137a`, **4m 48.7s**, outcome
`completed_with_warnings`, **3 author rounds (cap 4), 1 reviewer round (cap 6)**, 2 preview
iterations.

**Verdict 1 — the brief reached the brand card. PROVEN, directly.** The run's own
materialized card, `subsystems/clue-design/.deepagent-workspace/run_358bd4a52bb348cea877c38bb386e211/workspace/brand_card.json`,
carries `creative_brief` = `{schema: BrandBrief@1, truncated: false, omitted_sections: [],
estimated_tokens: 4063, token_budget: 6000}` with the rendered geometry + brief prose. The
orchestrator's author delegation (recovered from the LangGraph checkpoint) then reads:
`Brand anchor (use verbatim): "precise, product-led, infrastructural." … controls radius
4px, cards 6px, no pills … saturated #533AFD only for filled primary CTA controls … one
deep navy (#0D1738) statement/technical band; cool muted footer … Flat surfaces with
restrained shadow. Product-UI-led, not stock-photo-led.` Every one of those is a brief
section or a measured geometry token; #0D1738 exists ONLY in the brief's diagnostics.

**Verdict 2 — the reviewer cited the brief. PROVEN.** The `VisualCritique`
(`clue_role=design_reviewer`, gpt-5.6-luna): *"The page also misses **the brief's
deep-navy statement-band requirement** by rendering the backbone as pure black. Brand
anchor: the hero's stacked Checkout / Order review / Payment activity UI composition is a
concrete expression of 'precise, product-led, infrastructural'"*, plus
`reference_fidelity.reasons` — *"The page adopts **the brief's** white-dominant, restrained
violet-control, product-UI-led structure and a single dark backbone."* Honest caveat: the
citation is OVER-DETERMINED on this run — the director also quoted the brief into the
delegation. That the reviewer's own SYSTEM prompt carried the subset is proven
deterministically (harness wiring + `test_the_reviewer_prompt_carries_the_brief_when_one_is_passed`
+ the live `reviewer_brief_text` for this kit), not by this trace.

**Verdict 3 — the buttons carry the measured shape. PROVEN.** Computed styles on the
rendered page: every `[data-btn]` control at **`border-radius: 4px`**, primary fill
`rgb(83, 58, 253)` = `#533AFD` (`surface.brand`), secondary black — i.e. one saturated
fill, the brief's constraint. The theme base rule is `[data-btn] { … border-radius: 4px … }`.
The pre-brief page's identical rule is `border-radius: 8px`. Kit deltas: `radius.button`
8px `derived:` → 4px `website:… button border-radius`; `radius.card` 12 → 6;
`space.section` 64 → 96; `stroke.width.focus` 2 → 3; `shadows` 0 → 3.

**Verdict 4 — the background rhythm holds. PROVEN.** The brief's
`ratio_summary` is *"6 white page bands : 1 deep navy statement : 1 cool muted footer
sliver — white dominates by height"*. The generated page's band sequence is
`surface.page ×6 → bg-dark (why-stripe) → bg-surface-muted (footer)` — the ratio exactly.
The one honest miss is the brief's #0D1738 navy: no kit token carries it (the brief SAYS so
in its diagnostics), the agent used `bg-dark` (#121212) and reported the shortfall as its
`ladder_gap` and its `completed_with_warnings` summary rather than faking it.

**Side by side** (both are the run's own 1440 previews, so both are generation output,
not later edits):
- `brief-walk-05-generated-page-1440-brief-era.png` — kit v6, WITH brief.
- `brief-walk-07-pre-brief-stripe-page-1440-kitv3.png` — the founder's earlier Stripe page
  `doc_316aafa468c459f28c088c43598c8ff3` at v1, kit v3, NO brief (run
  `run_9b72e2123e164bbc97988086377d910b`; its materialized `brand_card.json` has no
  `creative_brief` key).
  The pre-brief page opens on a **full-bleed saturated violet hero** and closes on a second
  full-width violet CTA band — precisely what v6's constraint forbids ("do not use
  surface.brand as a full-width mid-page section background"); 8px controls; 2 white bands
  of 6. The brief-era page keeps violet at control scale on a white canvas with one dark
  statement band, 4px controls.
- `brief-walk-04-generated-stripe-page-v6-brief.png` — the artifact route in the shell.
- `brief-walk-06-generated-page-375-brief-era.png` — the 375 preview.

### 4. Counter-walk — a briefless kit behaves exactly as today

Taken at the brief's sanctioned lighter gate (envelope-level live assertion + the DB-gated
byte-stability tests), NOT a second full generation. On slice-4 code, kit **v3** (briefless):
`creative_brief` key absent; `reviewer_brief_text` is `None`; `render_brand_card_text(card)
== json.dumps(card, indent=2)`; and the card is **byte-identical to the brand card the
pre-brief run actually materialized and used** (`run_9b72e2…/workspace/brand_card.json`) —
that run produced the working page above, so identical inputs mean identical behaviour. Plus
`test_a_pre_brief_era_pinned_kit_still_resolves_and_carries_no_brief` (DB-gated) and four
offline byte-stability tests.

## BLOCKERS AND FINDINGS (the walk's real yield)

1. **No UI re-extraction can ever produce measured geometry or a brief for a
   server-rendered site — HIGH, unowned.** Three facts compose: (a) slice 2's geometry probe
   and slice 3's screenshots exist only on the RENDERED capture tier; (b) the static→rendered
   escalation gate (`capture/quality_gate.py::evaluate`) escalates only on evidence poverty,
   and stripe.com's static HTML is rich, so it never escalates; (c) the frontend's
   `ReExtractRequest` is `{url, brand_kit_id}` — it never sends `force_render`. Result:
   the UI Re-extract of Stripe finished in **10s** and published **v5 with 0 geometry tokens
   and no brief**. Every brand whose site server-renders well is in the same position. Fix
   candidates (needs a ruling): always force render for website ingestion; or escalate when
   the geometry/brief stages are enabled; or a UI affordance. Slice 4 changed nothing here.
2. **`LUMEN_INGESTION_BRIEF` defaults OFF and was absent from the recorded launch recipe** —
   so even a rendered re-extraction publishes briefless until it is set. Added to
   `/tmp/slice4-relaunch-8010.sh` with a comment. Belongs in the durable recipe.
3. **A `force_render` ingestion FAILS in the API's embedded fleet worker — reproducible.**
   Two attempts, both terminal in ~0.2s with
   `LUMI0401 ImportError: cannot import name 'GeometryEvidence' from 'lumen_ingestion.evidence'`
   (jobs `ingest_abb0ad58…`, `ingest_3a5a8005…`, `leased_by=lumen-api-embedded:…`). The same
   `_default_capture(..., force_render=True)` succeeds in a plain process, after importing
   `lumen_api.main`, and under `asyncio.to_thread` — so it is specific to the embedded
   worker's runtime, not to the module graph (the symbol exists; the `.pyc` carries it).
   Untested: the DETACHED fleet worker. This is why v6 was published by calling the shipped
   `run_website_ingestion` out of process — the deviation from "through the real UI", stated
   plainly. Root cause is unowned.
4. **The Design.md body does not refresh on Approve** — the chip flips to `Approved`
   immediately but the rendered markdown still says `version 6 · Draft` until a reload.
   Cosmetic, frontend-owned.
5. **The brief still cannot name Stripe's real navy or its cool-gray footer.** Both bands
   carry `token: null` + a diagnostic, and the generated page consequently used `bg-dark`
   instead of #0D1738. Slice 3 registered this; the walk confirms it is the single largest
   remaining fidelity gap. The fix is a slice-2-side surface-token extraction, not a brief
   change — the brief is correctly refusing to mint a token.
6. Known standing red, untouched: `apps/api/tests/test_agent_custom_components.py`
   (`compile_status == transient_error`, the node_modules family).

## Verification

- `apps/agent_runtime/tests` — **612 passed, 2 skipped** (+23 new in
  `test_brand_brief_consumption.py`), run WITHOUT the platform root `.env`.
- `apps/api/tests/test_brand_pin_brief.py` — 2 new DB-gated tests, green.
- Ingestion set green: brief / geometry / normalizer / capture / routes / ui_api / jobs /
  describe / font_metrics / raster / deployment_config.
- Frontend: **890/890** (`npm test`, was 882) + `design-system:build`, `lint`, `build` clean.

## Founder walkthrough (~15 min, copy-pasteable)

Stack must be up: 8010 (`zsh /tmp/slice4-relaunch-8010.sh`), the istanbul fleet worker
(`zsh /tmp/slice15_fleet_worker.sh`), 8030 and 3030 as in
`_memory/2026-08-19-genweb-slice0-preflight.md`. Login above.

1. Open `http://localhost:3030/brand-context?section=knowledge&file=design%2FDesign.md&mode=preview`.
   **See:** the breadcrumb reads **Design / Design.md** (not `Company / brand-kit.md`), and
   the document is headed `Brand kit: brand_kit_ing_813df… · version 6 · Approved`.
   Scroll: characterization `precise, product-led, infrastructural`, the constraints, the
   component recipes in token names, and the "Observations with no token" section naming the
   navy #0D1738 the kit cannot express.
2. Open `http://localhost:3030/projects/prj_79aa603b3c3853898045e3cfa414e136/artifacts/doc_2543706b1da856eab16f0e9f2bcfcc42`.
   **See:** the page this brief produced — white canvas, violet only on controls, one dark
   statement band, a cool muted footer, tight corners. Scroll the canvas to the bottom.
3. Compare with the pre-brief page:
   `http://localhost:3030/projects/prj_79aa603b3c3853898045e3cfa414e136/artifacts/doc_316aafa468c459f28c088c43598c8ff3`.
   **See:** a full-bleed saturated violet hero and a second violet CTA band — the allocation
   the brief now forbids. (This document also carries 9 later manual inspector edits; the
   untouched generation pixels are `.playwright-mcp/brief-walk-07-pre-brief-stripe-page-1440-kitv3.png`.)
4. The measured button shape, if you want it in numbers — in either page's browser console:
   `await (await fetch('/api/clue/design/documents/doc_2543706b1da856eab16f0e9f2bcfcc42/web/render?mode=editor')).json()`
   then search the returned `html` for `[data-btn] {` → `border-radius: 4px`. The same search
   on `doc_316aafa4…` gives `8px`.
5. What the agent actually read:
   `cat subsystems/clue-design/.deepagent-workspace/run_358bd4a52bb348cea877c38bb386e211/workspace/brand_card.json | python3 -m json.tool | less`
   → the `creative_brief` block, its `estimated_tokens: 4063` against `token_budget: 6000`.
6. Generate one yourself: new chat in **Untitled project** → *"I want a landing page for
   Stripe Payments — hero, product capabilities, proof, and a clear primary CTA."* → then a
   second message *"Yes — build it now."* **Expect ~5 minutes.** The rail's gallery gains the
   artifact and it opens itself.
7. The one thing NOT to do: do not approve Stripe kit **v5** on `/brand-context`. It is the
   briefless draft the UI's Re-extract produced (blocker 1) and approving it would take the
   workspace back to the pre-brief behaviour.
