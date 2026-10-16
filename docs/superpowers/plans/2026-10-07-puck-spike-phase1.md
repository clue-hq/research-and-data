# Puck spike, phase 1: can it hold our clones, brand tokens and multipage sites?

**Date:** 2026-10-07
**Status:** draft for founder approval.
**Driver:** Claude (Opus), by hand. No agent and no model spend in this phase.
**Why:** the website agent produces acceptable pages but is slow and costly: trial 1 cost $3.20,
the staged trial $1.12, Run 3 $4.14. Small edits also take a full agent turn. The Onlook and Puck
studies (`scratchpad/oss/onlook-report.md`, `puck-report.md`) point to Puck (MIT, React) as the
page model, editor and renderer, with brand fidelity coming from our clones and brand kits.
Before building any agent around it, this phase checks by hand whether Puck's architecture can
hold a brand-coherent page and site.

## The question

Can a Puck page built from (a) our captured clone sections, (b) our own sections driven only by
brand-kit tokens, and (c) a shared site shell across several routes look native to the seller,
edit instantly, and publish cleanly, for two different brands?

If yes, phase 2 builds the agent pipeline on the same interfaces. If no, we return to the
optimized current engine (staged run, about $1 a page).

## Inputs (lane database `clue_trenton`, read only)

| Brand | Workspace | Brand kit | Clones | 1:1 page |
|---|---|---|---|---|
| Garner Health | `ws_c080123a7c434454898aa5ae1a8f698b` | `brand_kit_ing_ba0708281cb44f7c847dfb8949110103` v2 | Garner homepage and customer-story sections, kit v2 originals | Syracuse City School District, from the approved copy trial (`docs/superpowers/specs/2026-10-06-syracuse-copy-trial.md`) |
| Conduit | `ws_3c96440b557a413fa02bda3fbf90cc5e` | `brand_kit_ing_c162dc8c5b99418284b42a21a7a80298` v3 | conduit.ai sections, kit v3 originals (37) | Atrium Hospitality (researched; not Dana.AI, whose angle is an open founder decision) |

Baseline for comparison: the staged trial's Syracuse page
(`trials/web-agent/runs/syracuse-staged-1/previews/`) and the live conduit.ai sections.

## Where and how

- A self-contained Next app at `trials/puck-spike/`, with its own `package.json`. It pins the same
  stack as our frontend: Next 16.2, React 19.2, Tailwind v4, TypeScript, Zod 4. Puck core is
  pinned to `@puckeditor/core` 0.23.0. Puck's AI plugin is not used.
- A Python export script (`trials/puck-spike/export/export_brand.py`, root `.venv`) reads the
  lane DB and blob store and writes everything the app needs as files:
  - `kit.json`;
  - the font files;
  - each clone's HTML, CSS and slot manifest;
  - every referenced image or video, copied under `public/`.

  The app then needs no running stack and avoids the preview iframe's local-network
  blocking (defect E1).
- Pages and sites are saved as JSON files through a small API route. This stands in for a
  Postgres `jsonb` column.
- A local branch `spike/puck-phase1` off `website-quality/week1`. No platform code, no other
  worktree and no shared database row is touched. Nothing is pushed.
- Dev server on port 3045, started through `.claude/launch.json` and checked in the in-app
  browser.

## Contracts built in this phase (reused by phase 2)

1. **Theme generator:** brand kit → one `theme.css`, holding:
   - Tailwind v4 `@theme` variables for the colour roles, the 12 type roles (family, size,
     weight, line height, tracking), radii and spacing;
   - `@font-face` rules for the kit's fonts.
2. **`ClonedSection`:** renders a stored clone from its HTML and CSS. Each slot (text, rich
   text, link, image) becomes a Puck field. A text-replacement list covers text with no slot,
   such as baked button labels.
3. **Our own sections:** each one's props are defined once in Zod. Puck's fields are derived
   from that, and so is the JSON Schema phase 2 will validate against. Style props offer only
   token choices.
4. **Site model:** `{ theme, shell: {header, footer}, pages: { "/": PuckData, "/results": PuckData } }`.
   The shell is edited once and shared by every page.

## Tasks, risk first

### Day 1: the three things that could stop the spike

**T1. Puck in our stack.**
- Scaffold the app with an editor route `/edit/[site]/[page]` and a published route
  `/[site]/[page]`.
- Add one trivial Tailwind v4 component.
- Check that utility classes render inside Puck's editor iframe (Puck issues #1026 and #1515
  report breakage there).

**Gate G1:** editor loads, Tailwind v4 styles apply inside the preview and on the published
route, no console errors.

**T2. Export script.**
- Read both kits, the clone rows (approved originals of the named kit version, skipping nav,
  footer, consent and agent-composed rows), their stored payloads (HTML, CSS, slot manifest,
  asset references), the asset bytes, and the font files.
- Write them under `trials/puck-spike/data/<brand>/` and `public/<brand>/`.
- First, study how the current engine scopes clone CSS and fills slots, and copy that behaviour
  rather than invent a new one.

**T3. `ClonedSection` v0.**
- Render Garner's video hero and one Conduit section, in the editor and on the published route.
- Choose the CSS isolation (Shadow DOM or a scoped container) from how the stored CSS is
  actually scoped.

**Gate G2:**
- Both sections match today's engine render.
- Images and the hero video load and play.
- Clone CSS does not change anything outside the section, and page CSS does not change the clone.

**T4. Theme generator v0.**
- Garner kit → `theme.css` plus fonts, loaded in the editor iframe and on the published route.

**Gate G3:** computed styles of a test element equal the kit's values (for example the
headline's family, size, weight and line height; `surface.brand` colour).

**Stop rule:** if any gate fails and has no fix within the day, stop and report with evidence
before going further.

### Days 2–4: the full shape

**T5. `ClonedSection`, complete.**
- Slot fields generated from each clone's manifest.
- The image slot uses the brand-asset picker.
- A text-replacement field covers baked text.
- A fragment picker lists the brand's clones by section and source page.

**T6. Our own sections (3–4), token-only.**
- The sections: `StatsBand`, `FeatureSplit`, `ProofCard` (case study or study with source
  line) and `CtaBand`.
- Variant fields offer only token choices: surface page, card, brand or inverse; heading
  display, headline or title; button style from the kit.
- A custom brand-asset picker shows the kit's logos and images with their descriptions.
- Every section is responsive at 1440, 768 and 375.

**T7. Site shell and multipage.**
- A campaign header (seller logo, "Prepared for <account>", optional account logo, one CTA)
  and a legal footer, shared by all routes. The header is built so the prepared-for line sits
  beside the logo, not under it; that is the shell bug found today.
- Two routes per site, with links between them.
- Edit the header once and confirm every route changes.

**T8. Build the pages by hand.** I record every decision and step as I go.
- **Garner / Syracuse `/`:** the five sections of the approved trial copy.
- **Garner / Syracuse `/results`:** built from Garner's customer-story clones.
- **Conduit / Atrium `/`:** copy written with the `account-page-copy` skill from Atrium's
  research, shown to the founder before it is final.
- **Conduit / Atrium second route.**
- Each page mixes clones and our own sections, so the clone-versus-token seam is tested.

**T9. Human editing.**
- Inline text edit, rich text, reorder, variant switch, image swap, undo and redo, save and
  reload, on both sites.

**T10. Publishing.**
- Published routes render on the server with no editor code shipped.
- Full-page screenshots at 1440 and 375, side by side:
  - the Syracuse page against the staged trial render;
  - the Conduit page against the conduit.ai sections it uses.
- Record page weight, and any console errors.

### Day 5: findings

**T11.** Write `trials/puck-spike/FINDINGS.md` and a `_memory` note covering:
- every gate and test with pass or fail and evidence (screenshots, computed-style checks);
- what broke and how it was fixed or worked around;
- my step counts per page;
- the list of Puck limits we would hit in production;
- a go or no-go recommendation for phase 2.

The founder reviews before phase 2 starts.

## Pass criteria for the phase

1. **Gates G1–G3** pass.
2. **Brand coherence**, judged by the founder:
   - both pages look native to their brand, with logos removed;
   - our own sections are indistinguishable in feel from the clones beside them;
   - Garner and Conduit look clearly different from the same section library.
3. **Editing:** every T9 action works and feels instant, with no model call.
4. **Multipage:** one shell edit reaches every route, and routes share the theme.
5. **Publishing:** published pages match the editor, fonts and media load, no console errors.

## Out of scope for phase 1

- Any agent or model call (phase 2).
- Login, tenancy, Head of ABM, design legs.
- Real publishing to the page origin or custom domains.
- Forms and tracking.
- Migrating existing pages.
- Capture improvements (A6).
- Agent-written section code.

## Known risks

- **Tailwind v4 inside Puck's iframe** (G1). The fallback is injecting the compiled CSS into
  the iframe ourselves.
- **Clone CSS isolation** (G2). Each Garner clone carries about 100 KB of CSS; some clones may
  rely on page-level context the engine supplies.
- **Puck is pre-1.0** with one main maintainer. Pinned version; MIT lets us fork if needed.
- **Puck has no validation.** Covered by the Zod-first section contracts.
- **Image upload is not built into Puck** (issue #13). Covered by the brand-asset picker.
