# Brand Design Brief & the Design-Craft Skill — Ratified Plan (the coherence mount)

> **STATUS 2026-08-20 — COMPLETE, pending founder sign-off. All four slices landed and the
> coherence walk passed live.** The craft skill was authored into the design runtime and
> wired must-read on every web turn (slice 1); the brand's real geometry is now measured off
> its own site instead of fabricated from a scale — on stripe.com, `website:`-provenanced
> tokens went 17 → 45, `radius.button` 8px `derived:` → 4px measured, and the brand's real
> shadows exist for the first time (slice 2); an ingestion agent writes a per-brand
> `BrandBrief@1` onto the kit version, human-approved with it on `/brand-context` and given
> a face as `design/Design.md` (slice 3); and generations now CONSUME both — the web brand
> card carries the brief and the measured geometry under D2's 6,000-token cap, the visual
> reviewer receives the review-relevant subset, and the leg pin freezes the brief version
> with the kit (slice 4). The walk: Stripe kit v6 extracted and approved through the real
> UI, one chat-driven generation (4m 49s, 3 author rounds, 1 reviewer round) whose brand card
> provably carried the brief (4,063 of 6,000 tokens, untruncated), whose reviewer critique
> cited "the brief's deep-navy statement-band requirement", whose buttons computed at the
> measured `border-radius: 4px` where the pre-brief page computes 8px, and whose band
> sequence reproduced the brief's "6 white : 1 dark statement : 1 muted footer" ratio exactly
> — against a pre-brief Stripe page that opens on a full-bleed saturated violet hero the
> brief now forbids. A briefless kit still renders yesterday's card byte for byte.
> **Three findings for the founder, all recorded in
> `_memory/2026-08-20-design-brief-slice4-acceptance.md`:** the UI's Re-extract button cannot
> produce measured geometry or a brief for a well-server-rendered site (the capture never
> escalates to the rendered tier and the request carries no `force_render`);
> `LUMEN_INGESTION_BRIEF` defaults off and was missing from the launch recipe; and a
> forced-render ingestion fails reproducibly inside the API's embedded fleet worker with an
> `ImportError` that does not reproduce out of process. None is a slice-4 regression; all
> three are ahead of the next brand onboarding.
>
> **Superseded status (kept for the record):** RATIFIED SHAPE (founder, 2026-08-20
> 00:30–01:40 IST); slices not yet dispatched. The founder shared an external reference
> design-guidance file
> (preserved at `docs/specs/brand-design-brief/reference-external-design-guidance.md`)
> whose agents produce highly brand-coherent microsites, and ruled: adopt its lessons via
> a **two-layer split** — the brand-agnostic craft rules are authored ONCE by the
> controller into our design deepagent's own skill layer, and an ingestion agent
> generates ONLY the per-brand Creative Brief + measured brand geometry, riding the brand
> kit. The founder further ruled: brand geometry (corner radii, stroke widths, shadow
> language, spacing rhythm) must be **measured from the brand's real website**, "in a
> very detailed manner", replacing today's `derived:` scale defaults; and the craft skill
> must be referenced from the agent's system-prompt/AGENTS.md layer as must-read.
>
> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development,
> slice by slice on founder order. **Process rule (founder, binding): Opus agents
> implement; the orchestrating session reviews every diff INLINE itself — never via a
> reviewer subagent.** TDD throughout. Local commits only, never push, no AI attribution.
> Design-subsystem tests run WITHOUT the platform root `.env` sourced (recorded trap).
> Every file:line below was verified 2026-08-20 against the trunk at `824e5711`; line
> numbers drift — re-verify anchors before editing.

**Where it runs:** `integration/frontend-design-part-iv-v2` or its successor.

**Goal (the founder's sentence):** when the brand-kit ingestion pipeline runs at
onboarding, an agent behind the scenes also produces a very detailed design-system
record — the per-brand Creative Brief plus measured design tokens (radius, stroke,
shadow, spacing, background rhythm — the brand's *geometry*, not just its palette) — and
every design-deepagent generation for that brand consumes it, so generated microsites
come out deeply brand-coherent, the way the reference file's agents do.

---



## 1. The architecture ruling: three tiers, two owners

The reference file fuses two documents. We deliberately split them (founder-ratified,
2026-08-20), and the "how to use tokens / where to use them" question splits with it:


| Tier                                        | Content                                                                                                                                                                                                                                                                                                                                                        | Owner / producer                                                                                                                                   | Lifecycle                                                                                                                                |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **1 — the craft skill** (`design-guidance`) | Brand-agnostic grammar: squint test, composition vocabulary by page type, micro-composition spacing intent, token-ROLE discipline ("accent is punctuation, not volume"), contrast chains, split-layout grammar, flex-image safety, logo discipline, composable primitives over placeholder rectangles, anti-AI-slop rules, adherence-priority ladder, final QA | **Authored by the controller** (this session), inspired by the reference but **translated into OUR engine's vocabulary**                           | Versioned with the design runtime (a `knowledge_docs` skill; code review, no per-brand variance)                                         |
| **2 — the per-brand Creative Brief**        | Characterization (2–3 words), chromatic brand moment, signature compositions, palette **allocation** rules, background rhythm, typographic posture, imagery posture, hard constraints, **component recipes** (the measured shape of the brand's real buttons/cards in our token terms)                                                                         | **The ingestion design-brief agent** (a `langchain.agents.create_agent`-style agent, per founder), running as a stage of the website-ingestion job | Part of the kit version: drafted with it, **human-approved on** `/brand-context` with it, frozen with it, pinned by the leg (D5) with it |
| **3 — the kit tokens** (exists today)       | The values: colors, typography, fonts, logos — now **plus measured geometry** (radii, stroke widths, shadows, spacing) with `website:` provenance instead of `derived:` scale defaults                                                                                                                                                                         | The existing normalizer + the new measurement pass                                                                                                 | Unchanged (the existing kit lifecycle)                                                                                                   |


Why the split is load-bearing: craft rules improve centrally for every brand at once and
can never be corrupted by one bad extraction; the brief stays small, extracted, and
human-gated; and a generated design.md that duplicated the craft layer per brand would
drift forever. (The reference file's own evidence: ~70% of it is true for any brand.)

## 2. What is ALREADY BUILT (verified — build on, never rebuild)

- **The skill mechanism exists.** `subsystems/clue-design/apps/agent_runtime/ knowledge_docs/skills/<name>/SKILL.md` — 13 skills today (`create-website`,
`edit-website`, `review-website`, `brand-and-tokens`, `visual-review`, …), loaded via
`lumen_agent/knowledge.py` (self-contained tree: AGENT.md + per-skill SKILL.md + topic
reference files), referenced by path from `prompts_web.py` (e.g. the reviewer's
"Read your skill: review-website"; recipe pointers to `knowledge_docs/knowledge/web/ landing-page.md` / `abm-page.md`).
- **The consumption seam exists.** `lumen_agent/brand_card.py::build_brand_card` →
`web_substrate.py:569` `brand_card_text` → injected into the orchestrator prompt
(`build_web_orchestrator_prompt(brand_card=…)`) and servable as a view block
(`web_substrate.py:3903`). The leg pins `{brand_kit_id, version}` fail-closed (D5),
and slice 2 of the genweb plan made birth stamp + pin read-back automatic.
- **The ingestion pipeline exists and already drives Playwright.**
`POST /brand-kits/ingest/website` (`lumen_api/main.py:1544`) offers a
`design_ingest_website` job (job row + `design_job` fleet task in ONE transaction, D5
Round C — a worker claims it; never BackgroundTasks). The executor is
`apps/api/lumen_ingestion/` — `capture/` (incl. `rendered.py`, Playwright),
`normalizer/` (cluster/emit/font_metrics), `assist.py` (vision), `pipeline.py`
(`_publish_ingested_kit` publishes the draft version). Vision flags
`LUMEN_INGESTION_VISION/DESCRIBE` are already in the launch recipes.
- **The kit schema has empty homes.** `brand_kit_json` today: `id, name, modes, assets, tokens, sources, version, provenance, constraints, description, approval_status, compatibility_policy`. `description` is empty; `constraints` is thin (tone,
contrast_pairs). Tokens carry per-token `provenance.source` + `confidence` — the
Stripe kit measured **17** `website:` **tokens (5 colors + 12 type roles) vs 96**
`derived:`, with `shadows: {}` — the exact gap this plan closes.
- **Approval + first-time auto-enqueue exist** (brand-kit onboarding plan, merged
`81e961ce`): drafts on `/brand-context`, Approve/Re-extract controls, the frozen
creation contract stamps the latest APPROVED kit at web-doc birth.



## 3. The gap (why generated pages feel "close but not the brand")

1. **No grammar travels with the vocabulary.** The kit says mint = `#30d8a7`; nothing
  says "mint is punctuation — one saturated card per composition, never a second
   accent." The agent gets tokens and invents allocation per run.
2. **Geometry is fabricated.** Radius/stroke/spacing are `derived:` scale defaults
  (confidence 0.6); shadows are empty. The brand's button shape — "a brand-identity
   component, not a raw UI primitive" (the reference's sharpest rule) — is never
   captured, so every brand gets platform-default geometry.
3. **The reviewer has no brand bar.** It checks layout/contrast/overflow but cannot ask
  "would this section only make sense for THIS brand?" — brand-genericness is not a
   reportable finding today.



## 4. Design decisions (settled here; D-numbered ones need the founder)

- **The craft skill is a translation, never a copy.** The reference is written for a
different editor (its text-variant names, `variant:` API, `PLACEHOLDER:` format,
`lg:`-only breakpoints, Tailwind-version quirks). Teaching our agent APIs it does not
have produces blind churn (the recorded 2026-07-29 failure class). The skill authored
here keeps the *wisdom* and re-states every rule in OUR grammar: the WebDoc node
vocabulary, the authoring contract's class rules, our theme-token hard law ("every
color must be a theme token" — already stronger than the reference's palette rule),
our breakpoints, our preview/QA loop. A short translation table rides the slice-1
brief so the implementer never imports foreign vocabulary.
- **The brief is a first-class kit section** (`brand_kit_json.brief`, `BrandBrief@1`),
not a loose file: extracted with the kit, approved with the kit, frozen with the kit,
pinned by the leg with the kit. Structured JSON with fixed sections (characterization,
chromatic_moment, signature_compositions[], palette_application[], background_rhythm,
typographic_posture, imagery_posture, constraints[], component_recipes[]) — rendered
to prose at injection time, so consumption stays deterministic and size-capped.
- **Geometry lands as tokens, allocation lands as brief.** The measurement pass writes
real `radii/stroke_widths/shadows/spacing` tokens with `website:` provenance +
measured confidence (falling back to today's `derived:` scale when a surface yields
nothing — honestly, provenance intact). The brief's component recipes then reference
those tokens by name.
- **Fail-soft, like the rest of ingestion:** a brief/measurement failure never blocks
the kit — the kit publishes without a brief (with a diagnostic), generation falls
back to today's behavior. Empty is correct; fabricated is the failure.
- **The reviewer consumes the brief too** — the characterization check ("point at one
element that would only make sense for THIS characterization") becomes a review
checklist item; brand-genericness becomes a reportable advisory.
- **The ingestion agent is a plain tool-calling agent** (`create_agent` style, per the
founder's explicit instruction) inside the existing job — not a deepagent, no leg, no
HITL; its tools are the capture session (navigate/screenshot/measure computed styles)
and nothing else. It runs where the ingestion worker already runs.
- **D1 — RULED (founder, 2026-08-20): option (b).** The brief gets a visible face on
  `/brand-context`. Load-bearing fact from the founder: **the dummy frontend already
  carries an md-rendering panel on the brand-context page** — it just isn't explicitly
  named for a Design.md. Slice 3 therefore surfaces the brief through that EXISTING
  designed slot (verify the dummy panel's exact shape before wiring; no new UI is
  being invented — this is naming + feeding an existing slot, dummy-presentation-truth
  compliant).
  **Grounding (founder-supplied, verified live 2026-08-20):** the dummy's designed
  slot is the brand-context *knowledge* section — route vocabulary
  `/brand-context?section=knowledge&file=company%2FOverview.md&mode=preview`
  (`section` / `file` = an md path / `mode=preview`). Live dummy on
  `http://localhost:3002` (HTTP 200 on that exact route); dummy SOURCE =
  `/Users/aryankeshri/conductor/workspaces/clue-frontend/milan`
  (`clue-frontend@codex/brand-context-page` — CORRECTED by slice 3's implementer;
  the controller's original note said port-of-spain/`codex/chat-shell`, which has
  no brand-context page. Another session's checkout either way: inspect read-only,
  NEVER restart it). Slice 3 lifts this section per the standing re-lift discipline
  and serves the kit's brief as a file in it (e.g. `design/Design.md`), rendered
  from `brand_kit_json.brief` — the md is a projection of the structured brief,
  never a second source of truth.
- **D2 — RULED (founder, 2026-08-20): the budget is denominated in TOKENS, never KB,
  and the brief may be as large as the founder's reference file** (the full reference
  ≈ 25KB ≈ **~6,000 tokens**; adopt **6k tokens rendered** as the v1 cap, honest
  truncation past it). The founder offered further reference briefs on request.
- **D3 — RULED (founder, 2026-08-20): as recommended, plus "everything that comes as
  part of brand-geometry."** Home + up to 3 same-origin pages the capture already
  visits, 1440 viewport; measure buttons (all variants found), cards, inputs, nav,
  section backgrounds in DOM order (→ background rhythm), heading/body computed type,
  shadows, radii, border widths, vertical spacing scale — and any further measurable
  geometry surface the implementer finds (dividers, chips, badges, focus rings,
  image corner treatment): the founder's instruction is exhaustiveness.
- **D4 — RULED (founder, 2026-08-20): as recommended.** Web documents only in v1; the
  scene/ad path keeps its current brand card until the ad-editor lane rules.



## 5. Slices



### Slice 1 — the craft skill (design-guidance) + wiring (no extraction yet)

- The controller AUTHORS `knowledge_docs/skills/design-guidance/SKILL.md` (tier 1):
every brand-agnostic rule from the reference translated to our grammar — anchor
characterization + squint test; composition vocabulary by page type; micro-composition
relationships (caption gaps, nav horizontal budget, spotlight padding, editorial
breathing); token-role discipline; contrast chains; split-layout grammar; image/flex
safety in OUR node terms; logo discipline; composable primitives + the anti-slop
geometry rule; adherence-priority ladder; final QA. The implementer wires, the
controller writes the skill text itself (founder: "authored by you").
- Wiring: orchestrator + author prompts name it must-read (the same pattern as the
existing recipe pointers); `review-website/SKILL.md` gains the characterization
recheck + squint items; the design runtime's AGENT.md/AGENTS.md reference it.
- Tests: knowledge-tree load test (the skill resolves); prompt-content assertions
(must-read reference present, both roles); review checklist addition present; scene
prompts byte-untouched.
- Verification: one live web generation on the existing approved kit; the trace shows
the skill being read; the reviewer's critique cites the characterization item.
- Commit: `feat(design): the design-guidance craft skill — brand-agnostic grammar, wired must-read (tier 1)`.



### Slice 2 — measured brand geometry (tier 3; kills the `derived:` defaults)

- A measurement pass inside the website capture (`capture/rendered.py`'s live page):
computed-style harvesting per D3's page set → candidate clusters (the normalizer's
existing clustering idiom) → `radii/stroke_widths/shadows/spacing` tokens with
`website:<url> :: <selector-class>` provenance and measured confidence; section
background sequence recorded for the brief's background rhythm; button/card/input
shape captures retained as structured evidence for slice 3's recipes.
- Honest fallbacks: a surface with no measurable value keeps today's `derived:` token
(provenance says so); `shadows` stays `{}` only when the site truly has none.
- Tests (ingestion suite idiom, fixtures from captured HTML/CSS): measured tokens carry
`website:` provenance; derived fallback preserved; the Stripe fixture yields a
non-empty radius/stroke/shadow set; normalizer merge respects existing color/type
extraction byte-for-byte.
- Commit: `feat(design): brand geometry measured from the live site — radii, strokes, shadows, spacing (tier 3)`.



> **Slice 2 OUTCOME (2026-08-20): DONE, reviewed clean** (commit `bef817cd`; record
> `_memory/2026-08-20-design-brief-slice2.md`). Live-proven on stripe.com:
> **`website:`-provenanced tokens 17 → 45** (derived 96 → 71); measured
> `radius.button=4`, `radius.card=6`, `stroke.width.focus=3`, `space.section=96`,
> and Stripe's real `shadow.brand` (`rgba(50,50,93,.12)`); 29 component shape
> records + 8 background bands retained as slice-3 evidence. The merge is
> claim-based (measured claims a step or the base stays `derived:` — binary, never
> fabricated); the probe runs post-screenshot and fail-softs. **Notes for slices
> 3/4:** token groups now MIX measured and derived rungs — consumers read
> provenance per token; `tokens.shadows` has no consumer until slice 3/4 wire it.
> **Follow-ups registered:** multi-page capture (the capture visits one page today,
> so D3's "up to 3 pages" awaits a capture-layer change); card-padding clustering
> refinement (small nav tiles outvote real cards in the frequency vote — shape
> records carry the true per-variant paddings meanwhile). **Repo trap recorded:**
> all ~20 worktrees share one `.git` → `refs/stash` is GLOBAL — never `git stash`
> here; `git worktree add --detach` for baselines.

### Slice 3 — the design-brief agent (tier 2) + kit schema + approval ride-along

- `BrandBrief@1` schema + the `create_agent`-style brief agent as a pipeline stage
after normalize: inputs = the capture's screenshots + measured evidence + the emitted
tokens; output = the structured brief (validated; refused → diagnostic + kit publishes
briefless). Component recipes reference kit tokens by name (never raw hex — the
engine's token law extends to the brief).
- `brand_kit_json.brief` rides the draft version; approval/freeze/pin unchanged
(verify the frozen-contract digests don't pin the kit payload shape — if they do,
the contract-delta ritual applies); `/brand-context` per D1's ruling.
- Tests: schema validation + refusal path; brief rides draft→approved→frozen; a kit
approved pre-brief-era still serves (back-compat); DSAR/erasure posture unchanged
(the brief contains brand copy, not personal data — assert no contact fields).
- Commit: `feat(design): the ingestion brief agent — per-brand creative brief on the kit (tier 2)`.



> **Slice 3 OUTCOME (2026-08-20): DONE, reviewed clean — the brand has a Creative
> Brief and a face** (commits `698f2993` design + `0f120a65` frontend + `13d64618`
> record). Live-proven on stripe.com (shipped pipeline, out-of-process): Stripe
> **v4 DRAFT** published carrying a real `BrandBrief@1` — characterization
> "precise, expansive, iridescent"; constraints like "surface.brand violet is the
> sole solid saturated CTA fill"; recipes in token names (`radius.button`,
> `space.md`, `surface.brand`, `text.inverse`); zero refusal diagnostics. The
> knowledge panel renders **Design → Design.md** headed `version 4 · Draft` on
> :3030 (browser-proven). Token law enforced twice (shape + kit-resolution);
> every branch fail-soft; the digest-pin STOP condition checked — nothing hashes
> the kit payload, no contract-delta needed. **NOTHING approved — the Stripe v4
> draft awaits the founder on `/brand-context`; approving it is slice 4's
> precondition.** Notes: D2's 6k cap governs the md projection — slice 4 re-applies
> it to the INJECTED brand-card form; bands whose color has no kit token carry
> `token: null` + a diagnostic (the token law working — a slice-2-side
> surface-token follow-up would let briefs name them); website-path only
> (PDF/upload have no screenshots/geometry); ~27k gateway tokens per ingestion,
> stage off unless configured. **Founder ruling wanted (small):** the brand-context
> breadcrumb hardcodes "Company / brand-kit.md" over every document — hardcoded
> identically in the dummy, so left alone per presentation-truth; a one-line fix
> once the dummy names it.

### Slice 4 — consumption + the coherence walk

- `build_brand_card` renders brief + geometry tokens (D2 cap enforced, truncation
honest) for web turns (D4 scope); reviewer prompt consumes the characterization;
the leg pin already freezes the brief version — assert it.
- The walk (the founder can run it themselves): re-extract Stripe → approve v4 (now
with brief + measured geometry) → new chat → generate → compare against today's v3
output: button shape/radius from measured tokens, background rhythm followed,
allocation constraints respected; reviewer critique cites the characterization.
Counter-walk: a briefless kit (approved pre-brief) generates exactly as today.
- Close-out: plan status header, `_memory/` record, founder walkthrough.
- Commit: `feat(design): generations consume the brand brief — the coherence walk (close-out)`.



> **Slice 4 OUTCOME (2026-08-20): DONE — the brief reaches the pixels** (commits `f2e584eb`
> design + `ec096404` frontend; record `_memory/2026-08-20-design-brief-slice4-acceptance.md`,
> screenshots `.playwright-mcp/brief-walk-*.png`). `build_brand_card(include_brief=True)`
> renders the brief (the panel's own projection, mirrored) plus the measured geometry split
> by provenance — `website:` tokens as brand facts, `derived:` ones labelled platform
> defaults and never as brand facts — under D2's 6k cap with honest, named truncation;
> `render_brand_card_text` splices the prose beside the card's JSON; the visual reviewer gets
> the characterization + constraints + rhythm subset deterministically from the harness,
> waking slice 1's dormant hooks; and a DB-gated test proves a leg pinned to kit version N
> keeps designing against N's brief after N+1 is approved mid-conversation. D4 and
> back-compat are byte-pinned: the scene card is untouched, and a briefless kit yields the
> pre-slice-4 card — verified live against the brand card the founder's pre-brief Stripe run
> actually materialized. **Live walk:** Stripe **v6** (28 measured geometry tokens, a real
> brief) approved in the UI; one generation in **4m 49s** (3 author / 1 reviewer round)
> whose materialized `brand_card.json` carries `creative_brief` at 4,063 of 6,000 tokens,
> whose author brief quotes "controls radius 4px, cards 6px, no pills" and "one deep navy
> (#0D1738) statement band", whose reviewer cited *"the brief's deep-navy statement-band
> requirement"*, whose buttons compute `border-radius: 4px` (pre-brief page: 8px), and whose
> bands reproduce the brief's 6-white : 1-dark : 1-muted ratio. The founder-ordered
> breadcrumb fix shipped with it: `Design / Design.md`, derived from route state, no
> filename table. **Three findings carried out of the walk** (UI re-extraction cannot reach
> the rendered tier → no geometry/brief; `LUMEN_INGESTION_BRIEF` off by default and missing
> from the recipe; forced-render ingestion `ImportError` inside the embedded fleet worker) —
> all in the acceptance record, none a slice-4 regression, all ahead of the next onboarding.



## 6. Constraints & traps (bind every slice)

1. **Never import the reference's vocabulary** — translate (§4). The reference file is
  preserved read-only at `docs/specs/brand-design-brief/reference-external-design-guidance.md`
   as inspiration, not as source.
2. **The engine's theme-token law is senior to everything** — recipes and brief rules
  speak in token names; any rule that would push raw values into nodes is mis-translated.
3. **Design tests without the platform** `.env` (recorded trap); ingestion suites live
  design-side; the fleet worker executes ingestion jobs — recipe env applies.
4. **The kit payload may be digest-pinned somewhere** — slice 3 verifies before adding
  the `brief` section and follows the contract-delta ritual if so.
5. **Dummy-frontend presentation truth** governs any `/brand-context` UI (D1).
6. **Fail-soft ingestion discipline** — no stage of this plan may make a kit publish
  fail where it succeeds today.
7. **Bounded injection** — the brand card is per-turn context; D2's cap is a hard cap
  with honest truncation, never silent.



## 7. Out of scope (registered, never silently dropped)

1. Re-theming/upgrading documents born before their kit's brief existed.
2. Multi-brand workspaces (the creation contract already fails closed).
3. Scene/ad-path brief consumption (D4 — the ad-editor lane's call).
4. Motion/interaction grammar (the reference's `svg-and-motion` analog) — future skill.
5. Per-page-type briefs (landing vs email vs deck) — one brief per brand in v1.
6. The hybrid tiled review (G3) and other genweb-plan residuals — separate track.

