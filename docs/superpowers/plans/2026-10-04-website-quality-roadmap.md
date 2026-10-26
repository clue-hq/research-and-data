# Website Quality Roadmap: Week-1 Fixes and the Code-First Lane

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This is a roadmap plan.** It covers several independent pieces of work. Each workstream below
> names its files, its acceptance tests and its gates; **before a workstream starts, it gets its own
> step-by-step implementation plan** (`docs/superpowers/plans/2026-10-0X-<workstream>.md`) written
> against the code as it is that day. Agent-facing text (skills, prompts, tool descriptions) is
> drafted in chat and approved by the founder before it is written.

**Goal:** Make 1:1 ABM website output demo-quality this week (copy, research use, typography, ads,
theme, capture) and, in parallel, build the first version of a code-first website lane modelled on
Ploy.

**Architecture:** Week 1 improves the current engine only where the work carries over: agent
instructions, research reads, kit measurement, a seller theme generator, capture evidence. The
code-first lane turns our capture into one shared seller theme plus editable Astro/React/Tailwind
sections, built offline in our sandbox and served as static files from our page origin.

**Tech Stack:** Python (platform API, ARV2 read tools, design agent runtime on deepagents/LangGraph,
ingestion), Rust (`lumen-web` theme), Postgres + Alembic, Docker sandbox, Astro 6 + React 19 +
Tailwind v4 (new lane), Next.js frontend shell.

**Spec:** `docs/superpowers/specs/archive/2026-10-04-website-quality-and-code-first-lane-design.md`

## Global Constraints

- Never push. Local commits only, on a feature branch, with no AI or Claude attribution (project CLAUDE.md).
- Discuss before editing: each workstream starts only after the founder approves it in chat.
- Agent-facing skills and prompts: plain, simple language with examples; never compressed. Substance is shown to the founder before writing.
- No code length limits on agent prose; code checks only correctness (refs, quotes, sections, private topics).
- Free-flowing harness: no new kind enums or refusals for judgement calls; judgement goes in the prompt.
- Head of ABM changes ship as a new immutable profile version with a new manual version (`make manual`, sha256 pins, registry pin, composer pin, resource-manifest digest test).
- Every new runtime flag goes into `.env.example` (and the subsystem's own `.env.example`) with its default the moment it is introduced.
- Alembic: hash revision ids, one head, reversible migrations, `make db-smoke` on a throwaway DB.
- Live tests spend money: never broad pytest with real keys (`--ignore-glob='*_live.py'`, run without sourcing `.env`). Live generations and dry runs are the founder's to start.
- The clue-design full suite is too slow to run inline: focused files only; `apps/agent_runtime/tests` and `apps/api/tests` run in separate pytest sessions; design DB suites need the lane stack down.
- Browser testing uses the Claude desktop in-app browser; every design-quality change is checked on Conduit, Garner Health and Clue.
- Existing web documents stay on the current engine; no migration.

## Review Focus

- An account with **no research**: Head of ABM offers research once; if the human declines, the page is still built from seller facts and says nothing invented about the account.
- An account with research but **no contacts or no contact pages written**: the design agent's reads return an honest empty list, and the page is still account-specific.
- A brief whose notes outnumber its facts: no note wording ("not independent proof", "no generic signup") appears in visible copy.
- A source page with **no H1, or all text at weight 400**: the kit's computed display/stat roles keep weight 400, and ad headlines are not bold.
- A source page whose content **fades or blurs in on scroll**: the captured section shows the final, readable state.

---

## Part A — Week 1 (current engine), in priority order for the Garner Health demos

> **Status 2026-10-06:** A1–A4 shipped (Head of ABM v72 / manual v18, design-agent copy rules, research
> reads, typography). Website-agent context clearing shipped (plan `2026-10-06-web-agent-context-clearing.md`;
> Syracuse page $7.71 → $4.14). Defects found in the first three website runs are tracked one at a time
> in **`2026-10-06-website-run-defects.md`**.

### Workstream A1: Brief format and research offer (Head of ABM)

**Why:** spec §3.5 items 1, 3, 4. Internal notes reach the page because the brief mixes notes and
facts; Head of ABM builds name-swap pages for unresearched accounts.

**Files:**
- Modify: `platform/api/clue_api/design_leg_tools.py` (the `open_design_leg` description, ~lines 600–620)
- Create: `platform/agents/catalog/skills/manual-siblings/v18/SKILL.md` (copy of v17 plus the brief format and the research offer)
- Modify: `platform/agents/catalog/manual/tool_notes.yaml` (`open_design_leg` notes)
- Modify: `platform/agents/clue_agents/manual/build.py` (`MANUAL_VERSION = "v18"`, `PROFILE_VERSION = "v72"`)
- Create: `platform/agents/catalog/profiles/head-of-abm/v72/profile.yaml` (v71 plus new pins)
- Modify: `platform/api/clue_api/agent_registry_wiring.py`, `platform/api/clue_api/chat/composer_context.py` (pin v72)
- Test: `tests/agents/` catalog/manual/registry tests, `tests/api/test_agent_registry_wiring.py` (resource-manifest digest)

**What changes (substance to approve in chat first):**
1. The brief has two labelled parts:
   - **"For the page"**: facts in the buyer's language, each with its source (claim id, research
     section or seller file), the angle, the offer and the CTA.
   - **"Notes for Design, never shown on the page"**: what not to claim, evidence limits, internal
     analysis, who the buying committee is.
2. Contacts are named in notes only. A 1:1 account page does not address individuals by name;
   a contact page is a separate request.
3. The prospect's own product is never described negatively.
4. Before opening a leg for a 1:1 page on an account that has no research, Head of ABM offers to
   run account research first and explains why. If the human declines, it opens the leg anyway.
   No hard gate.

**Acceptance:**
- [ ] `make manual` regenerates without drift; `python -m clue_api.manual_build --check` passes.
- [ ] Catalog, manual, registry and wiring tests pass with the new pins.
- [ ] Offline check: the v72 composed context contains the two-part brief instruction and the research offer (assert on the rendered manual chapter text, not on model behaviour).
- [ ] Founder live check (founder-run): a 1:1 request for an unresearched Garner account gets the research offer; declining still opens the leg.

### Workstream A2: Copy instructions for the design agent

**Why:** spec §3.5 items 1, 2, 5, 6. Contradictory, compressed copy guidance; the key reference
files go unread.

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts_web.py` (`WEB_ACCOUNT_EVIDENCE`: the brief's notes are for the writer and its wording is never copied; read `web-account-personalization` and `conversion-copywriting/references/copy-craft.md` in full before writing copy)
- Modify: `subsystems/clue-design/apps/agent_runtime/knowledge_docs/skills/conversion-copywriting/SKILL.md`
- Modify: `.../conversion-copywriting/references/copy-craft.md` (remove the "qualification BESIDE the claim, in body text" contradiction; attribution is the qualification; add the claim ladder and weak/strong examples)
- Modify: `.../conversion-copywriting/references/website-copy-brief.md`
- Modify: `.../web-account-personalization/SKILL.md` and `references/account-argument.md` (the 1:1 page pattern: account priorities, each paired with the seller capability that serves it, then attributed proof, then one CTA; contacts not named on account pages; no negative description of the prospect's product)
- Modify: `.../review-website/SKILL.md` (copy review with concrete examples of leaked notes, named contacts and name-swap pages)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/` prompt-composition tests that load these skills (focused files only)

**What changes (substance to approve in chat first):**
1. Plain language, with weak-versus-strong pairs taken from our own two pages (JW Marriott, Dana).
2. One rule for proof: name the customer and the person, state the result as theirs, no
   disclaimer sentence. Real conditions (time window, requirement) stay in the sentence.
3. The claim ladder (spec §2.5 item 5), with our modal-verb guidance.
4. Never copy wording from the brief's notes or from research caveats.

**Acceptance:**
- [ ] No sentence in the edited skills tells the agent to add a visible disclaimer for attributed proof (grep check recorded in the commit).
- [ ] Focused agent-runtime tests that read the skill tree pass.
- [ ] Founder before/after run on one researched Garner account (founder-run): no leaked notes, no named contacts, at least one research-backed reason specific to the account.

### Workstream A3: Research the website agent can read

**Why:** spec §3.6. The design agent sees only the overview page; it cannot see insights, contact
pages or list contacts.

**Files:**
- Modify: `platform/api/clue_api/arv2/read_tools.py` (`read_account_research`: add `section="insights"` serving the insights page by whole section, and `section="contacts"` listing the account's contacts with name, title, committee role, person entity id and their contact-page sections, paged)
- Modify: `platform/api/clue_api/design_platform_reads.py` (pass the new sections through)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/platform_reads.py` (tool description)
- Modify: `platform/agents/catalog/manual/tool_notes.yaml` and the `read_account_research` model descriptions (Head of ABM gets the same sections; ships in A1's v72/v18)
- Test: `tests/arv2/test_read_tools_db.py` (insights paging, contacts list, account with no contacts, contact page not written)

**Design:** improve `read_account_research@2` in place (the earlier founder ruling), additive
section values only. Reads use the same project-scoped selection as the account screen
(`select_quality_context`, `quality_pages.read_page` with `page="insights"` and `page="contact"`).
A contact whose page is not written appears in the list with an empty sections array and a
`page_written: false` flag.

**Acceptance:**
- [ ] New DB tests pass on a throwaway DB; existing 76 read-tool tests still pass.
- [ ] On `clue_trenton`, the read returns the 1 written insights page and the 3 written contact pages (manual check through the tool function, no model call).

### Workstream A4: Typography measurement and ad headings

**Why:** spec §3.2 and §3.7. Shared by websites and ads.

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/rendered.py` (sample only visible elements: non-zero box, not `display:none`/`visibility:hidden`/`opacity:0`, inside the viewport-width page, not inside a dialog/cookie overlay; record the sample's area)
- Modify: `.../capture/parse.py` (keep area and locator)
- Modify: `.../capture/evidence_builder.py` (type samples from supporting pages too, weighted below the entry page)
- Modify: `.../normalizer/typography.py` (pick each measured role's family from its own samples; computed roles derive from measured weights: display = headline weight, stat = headline weight, eyebrow/label = body or cta weight, subtitle = body weight; keep `_DEFAULT_HEADING_WEIGHT` only when nothing was measured)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/brand_card.py` (scene card: list measured roles first and show weights; `SCENE_TYPE_SIZE_NOTE` tells the agent to use the measured headline weight)
- Create: `subsystems/clue-design/scripts/repair_kit_typography.py` (re-derive type styles from saved evidence into a new kit version; dry-run default; `--apply`)
- Test: `subsystems/clue-design/apps/api/tests/` normalizer and capture parse tests (hidden 96/700 H1 before visible 56/400; serif H1 + sans H2; all-400 source; no H1)

**Deferred until after the demos (spec §3.7), unless the founder pulls them in:** the logo
surface policy (`lumen_ingestion/logo_policy.py` `LIGHT_SURFACES`), the reference-fidelity gate
for reuse-only ads (`lumen_agent/tools/substrate.py` `_reference_fidelity_error`), and a
typography check for scene ads.

**Acceptance:**
- [ ] The four repro cases above produce the visible/measured values (red first, then green).
- [ ] Repair script dry run on the Garner Health and Conduit kits prints the before/after roles; `--apply` writes a new kit version (founder approves applying).

### Workstream A6: Capture the final state of dynamic pages

**Why:** spec §3.1 and §3.4.

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/capture/rendered.py` (scroll down in steps so intersection observers fire; at the end call `document.getAnimations().forEach(a => a.finish())`, wait for transitions, then serialize; set a 1440×900 viewport on every backend including stealth)
- Modify: `.../sections/segment.py` (treat `opacity:0` and heavy `filter: blur()` as hidden for segmentation decisions only after the settle step)
- Modify: `.../sections/cssmatch.py` (keep rules whose extra classes were present on any element in the settled DOM)
- Test: `apps/api/tests/` with a local fixture page that reveals text on scroll (blur → clear) and a fade-in grid

**Acceptance:**
- [ ] The fixture page's captured section shows readable text (screenshot and serialized HTML).
- [ ] Founder-approved fresh Conduit capture on this branch: more than 1 of 12 sections minted; no `fragment.unrehosted_reference` for `/_next/image` URLs.

### Workstream A5: Seller theme with type tokens, used by composed sections

**Why:** spec §3.3. Composed sections have no shared type scale to use.

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/seller_theme.py` (brand kit → theme tokens: colour roles, type roles with family/weight/size/line-height/tracking, type scale, radius; one function used here and by the code-first lane)
- Modify: `subsystems/clue-design/crates/lumen-web/src/theme.rs` (emit type tokens in `@theme`: `--text-*` sizes with line-height, `--font-*` roles, role weights)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/brand_card.py` (web card: all type roles including title, with units and the source each came from)
- Modify: `subsystems/clue-design/apps/api/lumen_api/agent_cloned_sections.py` (~1391: `compose_web_section` passes `source_fragment_id` when the agent names a source clone)
- Modify: `.../knowledge_docs/skills/brand-and-tokens/SKILL.md` and `create-website/SKILL.md` (one rule: composed sections use the theme's type tokens; source measurements feed those tokens)
- Test: `crates/lumen-web` cargo tests for emitted tokens; `apps/api/tests` for `seller_theme`; agent-runtime brand-card tests

**Open decision for the founder:** should a composed section whose type does not match the theme
be sent back to the agent as a must-fix (today it only becomes `completed_with_warnings`)?

**Acceptance:**
- [ ] A composed section using `text-heading-1` renders at the source's 56px/400 for Conduit (in-app browser check on Conduit, Garner Health, Clue).
- [ ] Cargo tests for `theme.rs` and the new Python tests pass; vendored wasm rebuilt only if `lumen-wasm` depends on the change.

### Workstream A7: Garner Health demo walk

**Files:** none (operational), plus a run record in `_memory/`.

- [ ] Re-derive the Garner Health kit (A4 repair script, founder approves `--apply`).
- [ ] Confirm the demo target accounts are researched (Head of ABM or the accounts screen); research any that are not (founder-run, spends).
- [ ] Prepare the exact prompts for one 1:1 page per demo account.
- [ ] Founder runs the pages; review each in the in-app browser against the review focus list; record findings and fixes.

### Week-1 schedule (adjusted to demo dates once known)

| Day | Work |
|---|---|
| Mon 5 Oct | A1 + A2 substance in chat for approval; A4 tests and fixes; code-first spikes start (Part B, C0) |
| Tue 6 Oct | A1 + A2 written, versioned and tested; A3 |
| Wed 7 Oct | A6 (moved ahead of A5, founder 2026-10-05: A4 skips headings still animating in until capture waits for reveals); Garner prompts ready |
| Thu 8 Oct | A5; founder before/after runs on Conduit, Garner Health, Stripe, AltCarbon |
| Fri 9 Oct | Fixes from the runs; fresh Conduit capture; week record in `_memory/` |

Order (founder 2026-10-05): A4 done → A6 → A5. Test sample: Conduit, Stripe, Garner Health, AltCarbon in the trenton lane.

---

## Part B — The code-first lane (second worktree, weeks 1–3, then later)

Built in a separate worktree on its own branch off this one. Nothing here changes the current
engine's behaviour.

### Phase C0: Spikes (days 1–3) — the two risks first

- [ ] **Offline build spike:** a pinned Astro 6 + React 19 + Tailwind v4 template builds to static files inside the existing sandbox (`platform/api/clue_api/sandbox/docker_runner.py`, no network), with `node_modules` baked into the image (`docker/agent-sandbox/`). Measure build time for a 10-section page.
- [ ] **Text-to-source spike:** a build-time plugin tags each rendered text node with `data-src="file:start:end"`; clicking a text node in the preview and editing it rewrites exactly that string, including text in props and in data arrays. Prove on the Stripe-like hero shape (props + array).
- [ ] **Screenshot-compare spike:** render one rebuilt section at 1440 and 390, compare with the captured section's screenshot, return a diff score and a short list of the biggest differences the agent can act on.
- [ ] Write findings to `_memory/`; the founder decides go/no-go on the lane shape.

### Phase C1: Seller project and versions

- Storage: a versioned file tree per web document (new doc kind `site`), files in object storage by digest, a manifest row per version in Postgres (new table via Alembic, hash id, reversible).
- Every agent edit and every preview text edit is a new version; undo is "go to previous version".
- Template versioned too; a project records the template version it started from.

### Phase C2: Seller theme

- Reuse `seller_theme.py` from A5 to write `src/styles/theme.css` (Tailwind v4 `@theme`), plus font files from the kit.
- Rule in the template: sections use theme tokens; raw values only for exact rebuilt measurements.

### Phase C3: Agent toolset and skills

- New web-code harness variant in `lumen_agent` (same runtime, solo agent): file list/read/write/edit, `build_site`, `screenshot_site`, `compare_to_source`, research reads (A3), `publish_site`.
- Skills: `rebuild-section` (capture → component, rules from spec §2.3), `compose-section` (tokens + house type idiom), shared copy skills from A2, `review-site` (screenshot compare + copy review).
- Each skill's substance approved by the founder before writing.

### Phase C4: Preview and click-to-edit text

- Preview route in the frontend design editor shell (`apps/frontend`), serving the latest build in an iframe on the tenant preview origin.
- Click a text node → inline edit → save writes a new version and rebuilds; the agent sees human edits in its next turn.

### Phase C5: Publish

- Static output uploaded to the page origin under the seller's tenant subdomain or custom domain (existing registry); noindex for 1:1 pages by default.

### Phase C6: Side-by-side evaluation and default switch

- Same briefs on Conduit, Garner Health and Clue through both lanes; founder judges visual fidelity, on-brand new sections, copy, interactions. The new lane becomes the default only if it wins.

### Later (week 4 onwards, each its own spec)

- Per-account pages from a template plus account records (`/abm/[account]`), scaled on the human's request.
- Platform forms (`submitForm`) and tracking (`track`) tied to accounts; attribution reporting.
- Agent-built booking/calendar pages.
- Style editing in the inspector.
- The per-seller mini database.

### Code-first effort and confidence

| Phase | Estimate | Confidence |
|---|---|---|
| C0 spikes | 3 days | high |
| C1 project + versions | 2–3 days | high |
| C2 theme | 1 day (shares A5) | high |
| C3 tools + skills | 4–5 days | medium |
| C4 preview + text edit | 3 days | medium |
| C5 publish | 1–2 days | high |
| C6 evaluation | 1–2 days | — |

About three weeks in total; medium confidence overall, driven by C3 and C4.
