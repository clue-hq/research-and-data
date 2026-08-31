# 2026-08-26 — Ploy deep study II: the skill layer behind their quality (Stripe→Cursor ABM walkthrough)

Analysis-only session (no code changes, no plan finalized — founder explicitly asked to learn first,
discuss before executing). Sources: `ploy-inspiration/` — six extracted skill operating models
(Research, Campaign Landing Page, Plan Design, Brand Adherence, Build Site Page, Refactor+Code,
Copywriting) + the full 301KB conversation where Ploy's agent built and then explained a
Stripe-branded ABM landing page for target account Cursor (`/abm/cursor`). Supersedes nothing;
extends `_memory/2026-08-25-ploy-study-brand-coherence.md` (the clone-substrate study). The
laddered logo-fetch tool from the 2026-08-25 plan is reported DEVELOPED by the founder (verify in
tree before relying on it).

## The one-line mechanism

Ploy = (1) a cloned site as the component/code substrate (prior study) + (2) a **stack of process
skills with explicit precedence and handoffs** governing a code agent (Astro/React/TS/Tailwind/CVA)
+ (3) claim-controlled research that decides what the page is ALLOWED to say + (4) a closed
written design plan that prevents drift + (5) two-track QA (full-page screenshot brand review
AGAINST the reference + route/runtime validation incl. regression on affected routes) + (6) a
Learn phase writing durable brand rules to a living guidelines doc. Their own summary: "evidence
determines the story, campaign strategy determines the argument, the existing site determines the
visual system, and shallow refactoring connects personalization to native components without
breaking the source page."

## The four-layer precedence stack

1. Personalized ABM workflow — what may be personalized, what evidence is required, what must not
   be invented (exact account logo, seller visual dominance, noindex, no relationship implication).
2. Campaign Landing Page strategy — conversion argument (9 named patterns, chosen by campaign
   conditions: search-intent-mirror / conversion-scent / radical-simplification / complex-made-
   simple / proof-stack / deadline-urgency / video-led / visual-product-led / incentive-capture),
   campaign shell (minimal header, legal-only footer, no escape routes), ONE offer/action,
   success-time measurement event. "Campaign strategy wins on conversion architecture."
3. Build Site Page — reuse-first implementation: Design System returns a page-build plan (priority
   reads / closest page family / direct-reuse / adapt / style anchors / bespoke list / suggested
   files / FORBIDDEN write paths); bounded reading; reuse ladder (direct → shallow refactor with
   source-preserving defaults → new native-looking module → deep refactor last resort); route-first
   completion ("the route is the deliverable").
4. Brand Adherence — visual governance: Ground→Map→Define→Build→Review→Learn; brand-as-grammar
   (vocabulary/grammar/syntax/rhythm); recognizability test ("would it still look like the seller's
   site with the logo removed?"); preserved/adapted/new/EXCLUDED contract; final full-page
   screenshot comparison vs the ONE authoritative reference.

Run phases observed live: Thought/Seasoned(skill load + 2 blocking clarifying questions: buyer?
offer?)/Tempered(research brief)/Sifted(design plan)/Steeped(code)/Whisked(QA). Total ~13 min.

## Research = a claim-control system (their words) — WE HAVE THIS AS INFRASTRUCTURE

Their research skill is prompt-discipline that mirrors our claim store's philosophy almost 1:1:
decision-first scoping; evidence-per-question; workspace-sources-first; distinct search angles;
source hierarchy PER CLAIM TYPE; fact/inference/implication separation; confidence bands with
hedging vocabulary; cross-referencing; contradiction records; exact-metric discipline (subject/
unit/timeframe preserved — "overages became 20% of business" ≠ "revenue +20%"); causality
discipline; EXPLICIT UNKNOWNS list that shapes the page ("strategy-session starting point", never
"the architecture Cursor should implement"); proof selected by ANALOGY not fame; citation adjacent
to claim; one-document rule; stop conditions. Output artifacts: "First-Party Site Reference"
(structured extraction of prospect site incl. canonical nav SVG logo → provenance chain to local
asset) + "Prospect Research Brief" (decision / buyer context / 2-4 verified priorities /
need→capability matrix / proof w/ exact metrics+sources / co-brand refs / campaign argument /
CTA+measurement / unknowns). The five-column evidence matrix (priority | account evidence | seller
capability | seller evidence | permitted message) is "the bridge between research and page content."

## Editing quality mechanism

Shallow-refactor contract (7 preservation rules: source files, routes, call sites, DOM, classes,
defaults, ownership boundaries); "thread configuration through the existing tree before replacing
the tree"; interaction engines are part of the source contract; edits observed were surgical (a
`{" "}` JSX insertion; a default-string restore). Two defects self-caught: text-boundary bug via
SCREENSHOT review ("the visual review caught it even though the component was otherwise
functioning"), default-prop regression via validating the ORIGINAL route `/` after touching the
shared hero. "Avoid claiming completion before validation passes."

## Copywriting rules (codified, buyer-facing)

Claim ladder (product fact → capability → attributed customer result → conditional implication →
NEVER account forecast); modal-verb discipline (will/can/could/supports/helps); buyer vocabulary
from the account's own sources; one page one goal; pyramid structure; section-purpose discipline
(each section answers exactly one question); qualification adjacent to claim ("These are results
reported for each named Stripe customer… not promises about Cursor's outcome"; "does not imply an
existing Stripe–Cursor partnership"); relationship-language rules (Prepared-for/proposal-for OK;
partner/customer/trusted-by FORBIDDEN without evidence); positive framing; copy must fit the
hero's visual geometry; anti-slop blacklists (transformation verbs, superlatives, mystery-box
headlines, redundant subheadlines).

## Mapping to us (headline conclusions, for the founder discussion)

- **~70% of their quality edge is the PROCESS layer, and it is architecture-agnostic** — adoptable
  onto our deepagent trio as skills/prompts/recipes + a couple of artifacts, without touching the
  engine or giving up human-parity editing. The clone substrate (other ~30%) is already planned
  (Waves A/C/K).
- **We are structurally AHEAD on research**: they enforce claim control by prompt; we enforce it
  by substrate (typed claims, provenance, faithfulness judge, use gates, value narrative). The gap
  is the SEAM: our design leg receives a free-text `brief` + claim REFS (ids, never values) — no
  structured Prospect-Research-Brief / evidence-matrix / permitted-messages artifact reaches the
  design agent. Their research→design bridge is richer than ours today.
- **Genuinely missing on our side**: campaign-argument layer (9 patterns, argument-selection not
  component-selection); closed per-page design plan artifact (design/content split, 9 design
  fields, explicit exclusions, review tasks = acceptance criteria fixed BEFORE implementation);
  copywriting claim-ladder skill; ABM page governance (seller dominance, noindex, relationship
  language, analogous-proof-not-forecast disclaimers); reference-compare review is planned (Wave V)
  but their version also fixes review CRITERIA in the plan; Learn phase → our scoped-memory
  subsystem is the natural home (design lane doesn't write brand learnings today); success-time
  conversion events + form capture on published pages (product gap, unowned).
- **Their HITL moment**: 2 blocking clarifying questions (buyer? offer?) = "smallest set of
  decisions that materially affect the page" — maps to our leg turn contract's
  clarification_rounds: 1.
- **Do NOT naively copy**: file-editing agent. Our ops/document model is mechanically stronger
  (invertible, human-editable, validated). The analog mapping: their cloned components ↔ our
  planned seeded sections (Wave K); their theme tokens ↔ our kit tokens (already law); their
  shallow refactor ↔ derive/variant on seeded components; their component registry ↔ Wave K's
  registration + search_assets.

## Founder scoping ruling (2026-08-26, this session)

Three inspiration angles identified: research / copywriting / visual design. **Research is DEFERRED**
(the other co-founder is reworking the research side; do not build on it now). **Copywriting comes
LATER** (content is easier to change than design). **DESIGN GOES FIRST** — specifically: Ploy's
exact mechanism for extracting the client site's CSS/components, building base native components
that look like the client's official components (hero decoration set included), and assembling the
campaign landing page visually. Study first, discuss before any plan/execution.

## Founder rulings 2026-08-27 (RATIFIED — direction for the clone replication)

1. **Two-lane model RATIFIED**: cloned sections are stored VERBATIM (preserved subtree + scoped CSS
   + rehosted assets) and are **slot-editable only** (text/image/CTA/visibility slots threaded
   through the preserved tree, Ploy's shallow-refactor move done mechanically). New sections stay
   in the token-bound web grammar, fully editable. End-to-end editability of cloned sections is
   explicitly FUTURE work — priority now is Ploy-grade output quality.
2. **Capture scope**: homepage first; architecture must keep provisions for more pages.
   Checkpoints in order: (1) one perfect cloned homepage; (2) target-account campaign landing pages
   reachable ONLY via explicit URL routes (never in nav); (3) new navigable pages.
3. **The 2026-08-25 brand-fidelity waves plan gets REWRITTEN around the clone approach** (not
   patched). Wave L (logo ladder) reportedly built; verify in-tree. Old Waves A/C/K/V are
   superseded by the four-phase shape: clone capture → section harvesting (verbatim + slots) →
   grammar extraction/authoring law → campaign assembly + screenshot-vs-reference review gate.
4. Feasibility scout dispatched 2026-08-27 on THE hard question: rendering scoped verbatim
   HTML/CSS fragments through web render/export/publish — extend `design_custom_component` channel
   vs new web node kind. Two Opus explorers (engine side; platform/publish/editor side).

## Feasibility verdict + plan rewrite (2026-08-27, scouts complete)

Two-agent scout finished. **Verdict: NEW web node kind (`Fragment`), not the custom-component
channel** — that channel forbids exactly what fragments need (TSX-only, no dangerouslySetInnerHTML
CCC0116, no <style> CCC0117, closed Tailwind v3, opaque-origin iframe out of page flow). Fragment =
immutable content-addressed artifact (sanitized HTML + scoped CSS + asset digests + slot manifest)
+ leaf node `Fragment{fragment_id, slots}` rendered IN-FLOW via a render-options map (custom-
component frame-map precedent); CSS spliced via a `WebThemeOptions.fragment_css` seam (font_face_css
precedent); slots substituted via a `substitute_vars`-style walk; account derive binds them.
Sanitize ONCE at artifact creation (export path has NO sanitizer; published CSP allows inline
scripts — 'unsafe-inline'). Key traps found: **ingested fonts are hardcoded embeddable:False
(emit.py:255-266) and the publish license gate silently drops them** (preview shows them — publish
loses them); publish discards the font-exclusions list (web_export.py:966); slug charset forbids
`/` so `/abm/x` needs Part-IV item 5 (tenant-subdomain, ruled unbuilt) — CP2 ships as flat slugs
`abm-<account>` at `/w/{ws}/p/{slug}` via the EXISTING one-doc-per-account batch derive+publish;
CP3 multi-page blocked at 4 layers (no AddPage op, agent replay gate, hardcoded "home" in 6 sites,
one-slug-one-doc). New plan: `docs/superpowers/plans/2026-08-27-clone-fidelity-master-plan.md`
(F0 capture → F1 fragment engine → F2 harvesting → F3 CP1 homepage → F4 CP2 ABM pages → F5 CP3
provision). Old waves plan marked superseded (Wave L spec of record only). Founder decision points
D-F1..D-F5 pending (storage shape, font attestation, mobility, sanitizer strictness, slug shape).
**Status: plan DRAFTED, paused for founder review. Nothing dispatched.**

**Update (same day, later): founder RULED all decision points.** D-F1 artifact-pinned; D-F2 font
embed permission rides the platform Terms of Use (ingestion stamps `{embeddable:true,
basis:"platform-terms"}` for workspace-brand fonts, license name kept honest, gate honors basis,
manifest reports exclusions; ToU text itself is a founder/legal deliverable outside the plan);
D-F3 fragments top-level-reorderable ONLY (never resizable/droppable/internally editable);
D-F4 sanitizer fail-closed strict adopted by default (not explicitly ruled, reversible);
D-F5 flat pilot slugs `/w/{ws}/p/abm-<account>`, one derived doc per account, explicit-URL-only,
noindex, batch-manifest tracked. Plan marked RATIFIED-COMPLETE in its status header.
**Awaiting explicit founder dispatch order before ANY implementation.**

## Open discussion points (NOT decided)

1. Re-sequencing: a new "skill/process wave" (research-brief seam + argument patterns + design-plan
   contract + copy rules + ABM governance + Learn phase) is cheap (no Rust) and plausibly higher
   leverage than Wave K; could run before/parallel to A/C.
2. The research→design seam shape: does the evidence-matrix/permitted-messages artifact ride the
   delegation bundle (bounded, by-value) or a governed tool the design agent calls?
3. Form capture + success events on published pages — new product scope, needs an owner.
4. Verify the reported logo-ladder implementation state in-tree before building on it.
