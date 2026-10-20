# Website quality: what Ploy does, what is wrong with ours, and where we go

**Date:** 2026-10-04
**Branch:** `integration/shashank-design-onto-research-streaming` (local only)
**Status:** direction agreed with the founder; week-1 work and the code-first lane are planned in
`docs/superpowers/plans/2026-10-04-website-quality-roadmap.md`. No code has changed for any of it yet.
**Why this document exists:** the founder asked that the Ploy study, the diagnosis of our current
output and the long-term plan be written down so the learnings are not lost.

---

## 1. Decisions taken so far (founder, 2026-10-04)

1. **Pages become a standard code project per seller** (Astro + React + Tailwind, the way Ploy
   does it), built and served by our platform, **provided the output quality is pristine**.
   Ads stay on the current Rust scene engine.
2. **Our own capture pipeline stays the evidence source** for rebuilding a seller's site. We do
   not switch to Ploy's lighter capture.
3. **Direct text editing in the preview** (Ploy's no-AI quick edit) is in the first version.
   Style editing comes later.
4. **Existing web documents and pilot pages stay on the current engine.** No migration. Only new
   pages use the new path.
5. **Framework:** Astro with static output plus React components.
6. **Week 1 improves the current engine** with work that carries over to the new path, and
   **adds copy and content quality of 1:1 ABM pages** because demos are scheduled this week.
   The demo seller this week is **garnerhealth.com**.
7. **Head of ABM offers account research** when a 1:1 page is asked for an account that has not
   been researched. It is a recommendation, never a hard gate.
8. The code-first lane is built **in a second worktree, in parallel** with week 1.
9. The new lane becomes the default only after it **beats current output side by side** on
   Conduit, Garner Health and Clue, tested in the Claude desktop in-app browser.

Earlier rulings that still apply: keep the architecture simple (pilot stage); booking is built
into the page by the agent; tracking is provided by the platform; the per-seller mini database
comes later and is agent-built; variants and scaling are dynamic, on the human's request; pages
can be hosted on our domain or the seller's.

---

## 2. What Ploy does

Sources: the Ploy skills zip (`ploy-inspiration.zip`: campaign-landing-page, copywrite,
plan-design, brand-adherence, build-site-page, redactor-and-code, and a long playbook
conversation where Ploy explains how it built a Stripe page for Cursor), the founder's live Ploy
session (project "Stripe landing page clone", read only), and `docs.ploy.ai/site-builder`.

### 2.1 Product shape and stack

- Every site is a real code project: thin **Astro 6** routes, **React 19** section components
  with typed props, **TypeScript**, **Tailwind v4**, CVA/shadcn-style primitives,
  **motion/react** for animation, **react-hook-form + zod** for forms, deployed on
  **Cloudflare Workers**.
- `AGENTS.md` in the project states the stack and the rules the agent follows.
- Each component carries registry comments: `@ployComponentId`, `@ployComponentType`,
  `@ployPattern`, `@ployDescription`, `@ployStatus`. The platform uses these to list sections
  in its design-system view.
- A hidden `.ploy/` folder holds only route metadata (`routes/build-pages.json`) and a
  publish-time asset check (`publish-asset-check.mjs`).

### 2.2 One shared theme for the whole site

`src/styles/globals.css` is the single source of visual truth. It holds:

- **Colour roles** (`--ploy-*`) bound to Tailwind: text, background, accent, button, border and
  input, each with shades.
- **Typography roles**: heading, body, eyebrow and button. Each role has its real font family,
  its **measured weight** (Stripe headings are weight 300, light), letter-spacing and
  line-height.
- **A type size scale** mapped to Tailwind's `text-xs` … `text-9xl`.
- **Radius tokens** (Stripe: 6px).
- **The real font file** loaded (Stripe: sohne-var).

Every section, cloned or new, draws from this one file. This is the single most important
difference from our system (see §3.3).

### 2.3 Cloning is a rebuild, not a copy

Ploy's agent described its clone as **reconstruction from evidence**, in five phases:

1. **Capture the page as evidence:** HTML, linked CSS, a rendered version when needed, and
   assets. It does not capture the site's JavaScript as a runnable application.
2. **Build the foundations:** the theme above, as a background step when a URL is given.
3. **Rebuild each section as a React component**, using the capture as reference only:
   - source CSS translated to Tailwind, keeping exact values as arbitrary values
     (`max-w-[79.125rem]`, a 12-column grid, responsive variants);
   - source class names kept as hooks (`hero-section__layout`);
   - SVGs extracted into components (20 in the Stripe hero);
   - text pulled out programmatically, never retyped;
   - repeated items turned into data arrays.
4. **Rebuild interactions by type:** hover becomes CSS; tabs become a stateful component; a
   carousel uses a library; scroll reveal uses motion; pinned sequences get a custom controller;
   canvas or WebGL gets a dedicated build or a stated fallback.
5. **Review and repair** visually and at runtime, from big problems to small ones.

Ploy is honest about limits: it is not an identical copy, and the Stripe hero's animated wave
became a static image.

### 2.4 New sections stay on brand

In the Cursor sections Ploy wrote from scratch (`cursor-abm-sections.tsx`):

- every colour is a theme token, except one navy (`#0d1738`) and white;
- every heading repeats **one house typography pattern taken from the source**:
  `text-4xl md:text-6xl font-light leading-[1.05] tracking-[-0.045em]`;
- each section is registered with an ID, type and pattern.

New sections look native because they use the same theme and the same type idiom as the clone,
not because the agent has taste.

### 2.5 How Ploy builds a 1:1 ABM page (Stripe → Cursor)

1. **Classify the page.** A named-account outbound page: one account, one offer, one action. That
   decides the shell: no product navigation, a minimal co-branded header, a legal-only footer,
   one CTA repeated.
2. **Ask only the questions that change the page.** Ploy asked two: who is the primary buyer
   (finance and monetization leaders) and what should they receive (a monetization strategy
   session).
3. **Research the account into a separate document.** A "Prospect Research Brief" built from
   first-party sources (Cursor's pricing, seats, usage pools, spend alerts, enterprise
   organizations, chargebacks). The account's homepage is extracted into a reference document,
   including its real SVG wordmark.
4. **Build a claim ledger.** Each message is checked through:
   `account priority → account source → seller capability → seller source → permitted page
   message → required qualification`.
5. **Use a claim ladder** and stay at the highest level the evidence supports:
   1. direct product fact ("Stripe supports usage-based billing");
   2. specific capability ("Stripe can meter usage and combine it with subscriptions");
   3. customer result, attributed ("Warp's AI overages reached 20% of its business");
   4. audience implication, in conditional words ("this could give Cursor a clearer expansion
      path");
   5. account-specific forecast ("Stripe will increase Cursor revenue by 20%"), never without a
      model and account evidence.
6. **Choose analogous proof** from customers with a similar business model (Warp, Hex,
   Chipp.ai). Each metric is written as that company's result, which is itself the
   qualification. **There is no disclaimer sentence.**
7. **Keep a missing-evidence list** that constrains the page: no verified partnership, no
   verified use, no forecast, no implementation estimate, no endorsement, no deadline. These
   stay in the plan and never appear on the page.
8. **Write a section-by-section design plan** (layout, composition, type, colour, imagery, CTA,
   spacing, interaction, animation, content and sources) before building.
9. **Build the page around the account's priorities:** three Cursor priorities, each paired with
   the Stripe capability that serves it, then proof, then one conversion path.
10. **Reuse native components with a shallow refactor.** The real Stripe `HeroSection` was given
    typed props (eyebrow, title, description, CTA, `showLogoCarousel`), with defaults unchanged
    so the homepage still renders as before. "It is the native hero, configured for a new
    purpose."
11. **Co-brand with restraint:** the account's exact wordmark and a few accent details; the
    seller's typography, gradients, spacing and cards stay dominant. The test: the page should
    feel native to the seller even with the logo removed.
12. **One conversion path:** an inline form using the platform's `submitForm`, an inline success
    state, and a tracking event (`window.ploy.track("monetization_strategy.requested",
    {account, audience})`) fired on real success, not on button clicks.
13. **Three QA checks:** a full-page screenshot compared with the source; the original routes
    re-checked after shared components change; technical validation (render, no JS errors,
    hydration, noindex).

### 2.6 Copy rules worth taking

From Ploy's copywrite skill (written in plain language with weak/strong examples):

- clarity over cleverness, specificity over adjectives, customer language over internal
  language, evidence over assertion, one action, literal meaning;
- say what the company does in the first screen;
- use the buyer's vocabulary;
- choose modal verbs deliberately (will / can / could / helps) to match the claim level;
- put a qualification next to the claim it qualifies, as part of the sentence;
- check that sections have distinct purposes and that copy fits the composition.

### 2.7 Platform features around the pages

- **Forms:** `submitForm(name, fields)` posts to `/_ploy/form-submit`; submissions are stored and
  emailed to the workspace owner.
- **Tracking:** `window.ploy.track(event, props)`, tagged with the account.
- **Scaling:** `/abm/[account]` routes filled from typed account records in PloyDB.
- **Editing:** text can be edited directly in the preview without the AI.
- **Publishing:** private/noindex campaign routes, a publish-time asset check.

### 2.8 What we take and what we do not

| Take | Do not take |
|---|---|
| One shared theme per seller with measured type roles and weights | Ploy's lighter capture: ours (multi-page, assets, geometry, measured type) is better evidence |
| Sections as editable React components rebuilt from evidence | Cloudflare Workers per site: static output served from our own page origin is simpler |
| Interactions rebuilt by type, with honest fallbacks | Their research step: our ARV2 research is deeper and claim-backed |
| Claim ledger, claim ladder, attribution as qualification, missing-evidence list kept internal | |
| Shallow refactor of native sections with typed props and unchanged defaults | |
| Platform-owned forms and tracking; account routes from records | |
| Direct text editing in the preview | |
| Screenshot comparison against the source as the quality loop | |

---

## 3. What is wrong with our output today

Evidence: the two real 1:1 pages in the lane database ("Conduit for JW Marriot",
`run_84f4a3c50ba35703b59963ba523a0dd4`; "Dana.AI landing page",
`run_e0a891ca0ef0503b919235cd794ac043`; both made on the addis-ababa lane with the skills that
existed there), their briefs, their run events and agent transcripts, plus code reading and
offline repros. Shashank's audits:
`subsystems/clue-design/docs/typography-ingestion-audit-and-plan-2026-09-29.md`,
`aws-google-typography-trace-2026-09-29.md`, `arlo-ad-trace-audit-2026-10-02.md`.

### 3.1 Capture yield

The Conduit capture minted 1 of 12 sections. Ten were refused as
`fragment.unrehosted_reference` (`/_next/image…`, `/figma/…svg?dpl=`), the requested-vs-final URL
bug Shashank fixed in `0d06cd1d1`. That fix is on this branch but not on the lane that captured,
so the agent composed 7 of 8 sections itself. **A fresh capture on this branch is still needed to
prove the fix.**

### 3.2 Typography measurement (shared by websites and ads)

All verified by code reading and an offline repro with the real normalizer:

- **Hidden headings win.** `capture/rendered.py` takes the first three elements per tag in DOM
  order with no visibility check. A hidden 96px/700 H1 before a visible 56px/400 H1 becomes the
  kit headline (AWS's headline came from a cookie-modal H2).
- **One heading family overwrites measured roles.** `normalizer/typography.py` `_family_from`
  elects one family by frequency. A serif H1 with sans H2/H3 produces a sans headline.
- **Only the entry page feeds type samples.** `capture/evidence_builder.py` `build_evidence`
  parses only the entry snapshot.
- **Computed roles are forced bold.** `build_type_styles` sets display and stat to
  `max(heading_weight, 700)`, eyebrow/label to 600 and subtitle to 500. Only h1 → headline,
  h2 → title, body/p, button → cta and caption are measured. With no H1 captured the heading
  weight defaults to 700 and headline (32px) comes out smaller than title. An all-400 source
  produces display 700 and stat 700.
- **Existing kits are never repaired.** (`scripts/rederive_kit_type_units.py` is not the tool
  for this.)

### 3.3 Composed sections do not match the brand

- The web brand card (`lumen_agent/brand_card.py`, `CARD_TYPE_ROLES`) lists only
  display/headline/body/cta/eyebrow: no title (h2), no units, no provenance. Conduit's card
  headline 32/500 is the builder default; the real headline is 56/400 and section headings
  48/400.
- Composed section CSS uses raw pixel sizes copied from that card (32/500, 20, 16, 12).
- `crates/lumen-web/src/theme.rs` emits `@theme` with colours, two font families and geometry
  only. **There are no type tokens.**
- Kit type rules use `:not(:where([data-lumen-fragment="true"] *))`, so they never apply inside
  fragments, and composed sections are fragments. **The kit's type scale never reaches them.**
- The source's type scale (Conduit `text-heading-1` 56px and its rem variable) lives only inside
  each clone's scoped CSS island. `compose_web_section` mints without `source_fragment_id`
  (`apps/api/lumen_api/agent_cloned_sections.py` ~1391; repairs do pass it), so clone CSS pasted
  into a composed section goes dead.
- `web_typography_reference.py` only downgrades `accepted` to `completed_with_warnings`.
- Skills disagree: brand-and-tokens says "use type.*"; create-website says "source measurements
  win".

**Root cause:** each section is a frozen, isolated CSS island. There is no shared theme for a
composed section to use. Ploy has exactly that shared theme (§2.2).

### 3.4 Dynamic (JavaScript-driven) source pages

- `capture/rendered.py` `_harvest_page` scrolls to the bottom, scrolls back to the top, waits 3s
  and serializes. There is no step that lets reveal animations finish (no
  `getAnimations().finish()`, no settle-to-final-state), so blur-to-clear or fade-in text is
  captured in its start state.
- Scripts are dropped; inline styles written by JavaScript are kept.
- `sections/cssmatch.py` keeps a CSS rule only if all its classes exist in the captured subtree,
  so reveal-state rules (`.is-visible` and similar) are dropped.
- Segmentation treats only `display` and `visibility` as hidden (not opacity 0 or blur).
- The stealth capture backend has no viewport override, while everything downstream renders at
  1440px.
- The runtime rebuilds tabs and carousels only; it has no reveal logic.
- (Correction recorded: the `opacity:1 !important` styles on the Conduit hero are SVG paint
  baking, not a force-visible step.)

### 3.5 Copy and content of 1:1 pages

1. **Internal notes reach the page word for word.** Head of ABM writes the brief in a cautious
   analyst voice and the design agent lifts its wording:

   | Brief (internal) | Page (visitor) |
   |---|---|
   | "vendor case studies, not independent causal proof" | "These are vendor-published case studies, not JW Marriott results, and not independent causal proof." |
   | "not a generic startup signup" | "No generic startup signup." |
   | "not a new-logo hotel-operator sale" | "No hotel-operator pitch." / "Not a hotel-operator pitch." |
   | "Opera Cloud named in product research" | "(Opera Cloud is one Conduit names)" |

2. **The copy instructions contradict each other.** `conversion-copywriting/references/copy-craft.md`
   says analogous proof is "labeled as what it is … the qualification sits BESIDE the claim, in
   body text"; `conversion-copywriting/SKILL.md`, `web-account-personalization` and
   `review-website` say internal caveats stay out of visitor copy. The agent follows the first
   literally.
3. **Contacts are named in body copy and the prospect is knocked.** The Dana brief said "address
   him as economic buyer", so the page has steps titled "Alon, the overlap", "Yaniv, the stack"
   and "Neta, onboarding", and describes Dana's own CRM as "a disconnected CRM".
4. **No research means a name swap.** JW Marriott was never researched (no account linked), so
   nothing on the page is about Marriott beyond the name.
5. **The instructions are compressed rules with no examples.** About 5,500 words across the copy
   skills, mostly about what not to claim. Ploy's are longer but plain, with weak-versus-strong
   examples. The result is safe, telegraphic, lifeless copy.
6. **The agent does not open the guidance that matters.** In the Dana run it read seven skill
   files in 200-line chunks and never opened `web-account-personalization`, `copy-craft.md`,
   `website-copy-brief.md`, `account-argument.md` or `identity-and-evidence.md`. The guidance
   lives in reference files the agent must choose to open.

Note: this branch now carries Shashank's rewritten website skills (`3cf57bf12`, `b81feb554`,
`635a10805`, `f6b3ddb7e`), which already say "keep caveats out of visitor copy" and give audit
phrases to avoid. They were not live when these two pages were made and have not been tested in
a live run. They are still compressed and still contain the contradiction in item 2.

### 3.6 What research the website agent can see

The founder's concern is correct: the website agent sees far less research than Head of ABM.

- **Tools it has** (only on design-leg turns, `lumen_agent/platform_reads.py`; the web agent runs
  solo, `LUMEN_AGENT_WEB_SOLO=1`): `read_project_accounts`, `read_account_research`
  (`overview` or `claims`), `read_claims`, `web_search`.
- **What `overview` serves:** only the account **overview** page
  (`platform/api/clue_api/arv2/read_tools.py` `_overview_sections`): what they do, why they fit,
  why now, buying committee.
- **What it cannot see:** the account **insights** page (watch-outs, context), the **contact
  pages** (why this person), **person research**, and it has **no way to list an account's
  contacts**. `read_claims` works on a contact only if the agent already knows the contact's
  entity id. The lane database has insights pages and contact pages written, but design cannot
  reach them.
- **Head of ABM can see more** (`get_research_view`, `read_claims`, account and person research
  runs), so the design agent depends on Head of ABM's summary in the brief, which is written in
  the cautious voice of §3.5.
- **In the Dana run** (older code) the overview read came back truncated with no way to page:
  4 sections, `truncated: true`, `next_offset: null`. The agent read it once, never read claims
  and never read a contact. Overview paging is fixed on this branch (`a46fce640`).

### 3.7 Ads

- The forced-bold display and stat roles (§3.2), combined with the scene brand card putting
  `type.display` first and `SCENE_TYPE_SIZE_NOTE` telling the agent to use
  `style($type.display)`, make every ad headline bold.
- `logo_policy.py` `LIGHT_SURFACES` always allows page and card surfaces.
- The reference-fidelity gate (`substrate.py` `_reference_fidelity_error`) only switches on when
  an image is generated, so reuse-only ads finalize with no fidelity check.
- Scene ads have no typography check.

---

## 4. Target architecture: the code-first website lane

The goal is Ploy's model built on our capture and our research. Pilot stage: keep it simple.

### 4.1 Pieces

1. **Seller theme generator.** Brand kit (with the §3.2 measurement fixes) → one theme file per
   seller: colour roles, typography roles with real weights, letter-spacing and line-height, a
   type scale, radius tokens, real font files. The same generator feeds week 1's page-wide theme
   in the current engine, so that work is not wasted.
2. **Seller project.** A versioned file tree per web document, started from a fixed template:
   Astro routes, React sections, Tailwind v4, our primitives, motion/react. Dependencies are
   pinned in the template; the agent cannot install packages.
3. **Build.** Static Astro build inside the existing offline Docker sandbox
   (`clue_api/sandbox`, the image `run_python` uses, extended with Node and the template's
   `node_modules`). Output is static files.
4. **Hosting.** Static files served from our existing page origin and custom-domain registry.
   No server per seller. Forms and tracking call the platform API.
5. **Agent tools** (design agent, new web toolset): list, read, write and edit project files;
   build; screenshot at 1440 and 390 wide; compare a section with the source section's
   screenshot; read research (with the §3.6 gaps closed); publish.
6. **Rebuild skill.** Captured section → React component: text extracted by code, exact values
   kept as Tailwind arbitrary values, source class names kept as hooks, SVGs extracted,
   repeated items as data, each interaction rebuilt by type with a stated fallback.
7. **Compose skill.** New sections use only theme tokens plus the source's house type idiom,
   following the claim ledger and claim ladder for copy.
8. **Preview with click-to-edit text.** The build tags each text node with its source location
   (file and position); an edit in the preview replaces that string in the source file, records
   a new project version and rebuilds.
9. **Later (week 4 onwards):** per-account pages from a template plus account records
   (`/abm/[account]`, our scaling model); platform forms (`submitForm`) and tracking
   (`track`) tied to accounts; agent-built booking; style editing in the inspector; the
   per-seller mini database.

### 4.2 What stays as it is

- Ads on the Rust scene engine.
- The capture pipeline (improved in week 1) as the evidence source.
- ARV2 research and its governed reads.
- Head of ABM, design legs, the delegation bundle, the gallery and publishing records.
- Existing web documents on the current engine.

### 4.3 Safety

- Agent-written code runs only in the offline sandbox at build time; the browser gets static
  files plus small platform scripts.
- Each seller's pages are served from their own tenant subdomain or custom domain (the existing
  ruling), so one seller's page script cannot read another's origin.
- No secrets in client bundles; the platform's form and tracking endpoints authenticate by page
  and account, not by keys in the page.
- The dependency set is fixed by the template.

### 4.4 Quality gate before it becomes the default

The new lane must beat current output side by side on Conduit, Garner Health and Clue, judged on
visual fidelity to the source, on-brand new sections, copy quality and working interactions,
tested in the in-app browser. Until then both lanes run.

---

## 5. Week-1 bridge in the current engine

Chosen because it carries over to the code-first lane (or to ads, which stay):

| Work | Carries over? |
|---|---|
| Copy and brief fixes (§3.5) | Yes: the same agent instructions drive both lanes |
| Research visibility for the website agent (§3.6) | Yes: the same reads serve both lanes |
| Typography measurement fixes (§3.2) | Yes: both lanes and ads read the kit |
| Ad bold-heading fix (§3.7) | Yes: ads stay on this engine |
| Page-wide seller theme with type tokens, used by composed sections (§3.3) | Yes: the generator writes the code project's theme |
| Capture settles to final state and keeps reveal rules; fresh Conduit capture (§3.1, §3.4) | Yes: this is the rebuild's evidence |
| Tweaks to fragment CSS isolation | No, so kept to the minimum |

---

## 6. Risks and open questions

- **Quality loop.** The screenshot-compare loop decides rebuild quality; it is prototyped first.
- **Text-to-source mapping.** Click-to-edit must survive components, props and data arrays; it is
  prototyped first.
- **Three weeks is tight** for the code-first first version. Confidence: medium.
- **Model choice.** Both agents run on grok-4.6. Copy quality may be partly a model limit; the
  week-1 before/after runs will show it. Changing the model is an env change, not a profile
  version.
- **Live tests spend money** and are the founder's to start.
- **Open:** which Garner Health target accounts the demos use, and whether they are researched.

---

## 7. Evidence index

- Runs: `run_84f4a3c50ba35703b59963ba523a0dd4` (JW Marriott, session
  `dsess_878be79d25305fe4a9da17be9949de31`), `run_e0a891ca0ef0503b919235cd794ac043` (Dana.AI,
  session `dsess_d388264bcbea53329b8ccb01ead19277`) in `clue_trenton`.
- Documents: `doc_28084f01fd645305a2ae5e2e4c6afafb`, `doc_c0c22f0184cd54798451cf07904fdc24`.
- Commits on this branch: `6841e7f24` (merge), `a46fce640` (overview paging), `6676607ac` (Head of
  ABM v71), `cf132b77a` (discovery on by default).
- Session record: `_memory/2026-10-04-shashank-design-integration.md`.
