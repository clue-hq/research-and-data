# Responsive brand type — design

Status: written 2026-10-18; the founder decided §3.4. Work happens in the trenton session, branch
`site/publish-durability` (founder: no new worktree).

## 1. Why

On a seller's own website, text changes size as the window narrows. Garner's section headings go
from 56px on a desktop to 40px below 991px and 34px on a phone; its body text goes from 18px to 16px.
The sections we copy from the seller keep that, because they carry the seller's CSS. The sections we
build from scratch (our Feature split, CTA band and the rest, and every agent-written section) do
not: their sizes come from the brand kit, which holds one size per kind of text, measured once at a
1440px window. The site-kit theme then guesses how to shrink it (exact at 1440px, sliding down to half
on small screens, and nothing at or under 24px ever changes). So on a phone our heading sits beside the
seller's at a different size, and our body text never changes at all.

The founder's point: if the seller's website follows a rule, the brand kit should take that rule and
our sections should follow it — for every seller, not tuned for one.

**Success:** on Garner, Conduit and Clue, at phone, tablet and desktop widths, a section we built
reads at the same sizes as the seller's own sections beside it.

## 2. Goals, non-goals, anti-goals

Goals
- The extraction records, for each kind of text in the kit, how its size changes with the window
  width on the seller's site.
- The kit stores that, and the site-kit theme writes it out, so every section built from the kit
  follows it with no per-section work.
- Kits that already exist can get it without redoing their whole extraction.

Non-goals
- Ads (the scene editor) and the older web lane: fixed-size canvases; they keep reading one size.
- Changing which kinds of text a kit has, or how their desktop sizes are chosen.
- Spacing, padding and other sizes that may also change with width on the seller's site (a later
  piece, if wanted; this design is type only).
- Kits built from a PDF or an uploaded style guide, which have no page to measure: they keep today's
  behaviour.

Anti-goals (a failure even if it technically works)
- Anything tuned to Garner, Webflow, or a list of known break points. The rule must come from
  measuring the seller's page.
- A change in how a kit's desktop sizes come out. Desktop must be byte-for-byte what it is today.
- Breaking a kit that has no steps, or any reader of the kit that does not know about steps (the
  ad engine, older code): steps are additive and ignorable.
- Running an extraction or a re-measure on anyone's kit without the founder's yes and a time
  estimate (standing rule).

## 3. How it works

### 3.1 Measuring (the extraction)

The extraction loads the seller's page in a real browser and, in one in-page script
(`apps/api/lumen_ingestion/capture/rendered.py`, `_EVALUATE_JS`), samples the elements that become
type evidence: the body, h1–h6 (content headings only), the first paragraphs, links, buttons,
nav/header/footer and the largest visible elements. The normalizer picks among those samples
(`normalizer/typography.py`: `resolve_anchors` chooses the headline and body samples and the prominent
section heading; `anchor_for_role` gives a role its own measured sample where one exists) and
`build_type_styles` turns them into the kit's twelve roles (`type.display` … `type.legal`): measured
roles take their sample's size, the rest are derived from the headline (H) and body (B) sizes.

**Desktop is the capture's own width.** The default (stealth) capture deliberately sets no viewport —
forcing 1440×2000 broke its fingerprint and the hero stopped painting (comment in
`_fetch_rendered_stealth`; `_memory/2026-08-30-brand-color-ingestion-poc.md`); only the plain-Chromium
fallback uses 1440×2000. So the kit's desktop sizes are whatever the capture's own width gave, and they
stay exactly as they are. *(My call.)*

The change, in the same browser session, as the **last** pass (after the screenshot, geometry and
state passes, so nothing they read changes):
1. **Remember the sampled elements.** The script marks each sampled element (an attribute holding its
   sample index) so the same elements can be read again, and records the capture's width
   (`innerWidth`).
2. **Choose the widths to measure.** Only widths narrower than the capture width: the seller's own
   break points read from the media queries in the page's stylesheets (the capture already collects
   them), plus three fixed widths so a site whose sizes slide smoothly (`vw`, `clamp()`) is also
   caught: 1024, 768 and 390 (each only if below the capture width). Bounded to a small number
   (builder's call; on the order of eight).
3. **Resize and re-read.** For each width: resize the viewport (no reload; a resize after the page has
   loaded is ordinary visitor behaviour and does not touch the load-time fingerprint), let layout
   settle, and read the font size, line height and letter spacing of every marked element.
4. **Build each width the same way as desktop.** Run the same selection and derivation at each width,
   keeping the elements chosen at the capture width (selection must not re-pick a different element at
   a narrower width, or a size would jump for the wrong reason). This gives each role's size (and line
   height) at each measured width.

Reading the drawn page, not parsing the seller's CSS, is what keeps this general: it sees Webflow
steps, `clamp()`/`vw`, CSS variables and sizes set by JavaScript the same way. The stylesheets are used
only to know where to look.

### 3.2 Storing (the kit)

**A kit section of its own, outside the engine** *(my call)*. Saving a kit runs it through the Rust
engine (`core.validate_brand_kit`, `pipeline.py` ~1097) and stores what comes back, which drops any
field the engine's types do not have — steps inside the typography tokens would be lost on the first
save and on every later re-validation (logo choice and other routes in `main.py`). The kit already
keeps non-engine data the same way: `KIT_SECTIONS_OUTSIDE_ENGINE` (`brief`, `grammar_audit`,
`measured_components`, `lumen_api/brand_kit_sections.py`) is put back after every validation. A new
section, `responsive_type`, joins that list and is attached after validation in ingestion as
`measured_components` is. No engine change, no helper or wasm rebuild; the ad engine never sees it.

Its shape (field names are the builder's): the width it was measured from (the capture width), the
widths measured, the source page and when, and for each role a list of steps from widest to narrowest —
the width at and below which a step applies, and the size (and line height when it changes) there. A
step is stored only where the size changes from the wider one.

**Measured but unchanged is not the same as not measured** *(my call)*. A kit with a `responsive_type`
section has been measured: a role with an empty step list keeps its desktop size at every width (drawn
fixed, with no shrink rule). A kit without the section draws as today.

### 3.3 Drawing (the site-kit theme)

`apps/frontend/packages/site-kit/src/theme.ts` writes each role's size as `--brand-text-<role>`
(today `fluid(size)`). For a kit with a `responsive_type` section, it writes the desktop size plus one
`@media (max-width: …)` rule per step setting the same variable, and a role with no steps is a fixed
size. Where the measured sizes fall on a straight line between two widths
(a seller using `vw` or `clamp()`), the builder may write that stretch as a matching `clamp()` instead
of several steps; either way the drawn size at every measured width equals the measured size. A kit
without the section is written as today (`fluid`), so every existing kit draws exactly as before until
it is re-measured.

Because the editor's canvas is an iframe, the same rules respond to the editor's Desktop / Tablet /
Mobile preview; the published page responds to the visitor's window.

`brand.md` (what the agent reads about the brand) shows, for a role with steps, its sizes at each
width in one short line, so the agent knows the type is responsive and does not fight it.

### 3.4 Sizes set by hand in the inspector (founder, 2026-10-18)

A size set in the site inspector follows the steps of the nearest kind of text — at or above the kit's
title size, the headline's; smaller, the body's — written as a share of that role's variable, e.g.
`calc(var(--brand-text-headline) * N / H)`. On desktop it is exactly N; on a phone it shrinks the way
the seller's headings (or body) do. The same rule applies on copied sections. With no
`responsive_type` section in the kit it behaves as today (one size at every width).

Why (the founder): marketers editing the page will not think about phones and will not check the
mobile view; we do not rely on them to. The brand's site must stay consistent across device types
whatever they set by hand.

This replaces the site element inspector design's non-goal "responsive styling — one value at every
width" for font size only (`2026-10-17-site-element-inspector-design.md` §3; recorded in its §7).

### 3.5 Bringing existing kits up to date

A small job (a script, like `scripts/rederive_kit_type_units.py`) re-measures only the type for one
kit: it loads the kit's source page (the kit's website source), samples the type the same way, and
writes a new kit version that differs from the old one only in the added `responsive_type` section.

The live page may no longer give the stored desktop sizes (the page changed, the capture width
differs, or the kit was edited by hand). So the job stores each role's steps as the measured
narrowing applied to the **stored** desktop size (measured size at a width ÷ measured size at the
capture width × stored desktop size), and a role whose re-measured desktop size is far from the stored
one (builder's tolerance) gets no steps and is named in the job's report. *(My call.)*

Kit versions are immutable and sites pin an exact version, so a new version changes nothing on a
site until the site is moved to it. Like the re-derive script, the job can also move the sites pinned
to the old version onto the new one (`--repin-documents`). The job, and that option, run only with the
founder's yes and a time estimate. A full re-extraction also produces the section, through the normal
path.

## 4. Proof

- Unit and scenario tests through the real code: measuring a fixture page that steps (media
  queries), one that slides (`clamp()`/`vw`) and one that never changes; storing steps; the theme's
  output for each (a measured role with no steps drawn fixed); a kit without the section drawing
  exactly as today; the `responsive_type` section surviving a kit's re-validation (e.g. a logo
  choice); the re-measure job on a kit whose page changed.
- Live check (after the founder's yes for each re-measure): Garner, Conduit and Clue at phone (390),
  tablet (768) and desktop (1440; the kit's desktop size holds from its capture width up). At each width, the computed font size of our section's heading and
  body beside the seller's copied section's heading and body. They should match the seller's sizes at
  every width measured. Clue has no microsite in the lane today; the check needs one (the founder asks
  the agent for it), or, failing that, compares our sections against Clue's own website at the same
  widths.

## 5. Left to the builder

- The exact cap on measured widths, the settle wait after a resize, and the tolerance for treating two
  sizes as equal.
- The exact field names of the steps in the kit token, and whether a straight stretch is written as
  `clamp()` or as steps.
- How the re-measure job is triggered (a script, like the existing kit re-derive scripts, is enough).
