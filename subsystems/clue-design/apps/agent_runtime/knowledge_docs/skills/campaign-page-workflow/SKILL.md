---
name: campaign-page-workflow
description: The end-to-end roadmap for building any campaign landing page — the ordered steps from brief to finalize, naming the skill and the tools each step uses. Generic across sellers and campaign types. Read this FIRST when a page exists to convert someone; the specialist skills own the depth of each step.
---

# Campaign Page Workflow — the roadmap from brief to finalize

You are building a page whose job is to move a visitor toward one
decision. This file is the ORDER of that work: which step comes when,
which skill owns each step's judgment, and which tools do each step's
work. The depth lives in the specialist skills; the sequence lives here.

## A roadmap, not a rail

The steps below run in order, but real builds loop back: a render
reveals a wrong guess, a pin refuses, the copy outgrows a slot. Looping
back is fine; doing it OFF THE RECORD is not — every return to an
earlier step lands in `workspace/plan.md` as a written amendment before
you act on it (the plan-design skill's amendment law). Nothing in this
file is a gate: the user's explicit instruction always wins, and a step
that the brief has already answered is a step you skip, saying so.

## Step 1 — Establish the brief

*Skill: campaign-landing-page (steps 1–2).*

From the user's words, the design brief, and anything they supplied,
establish: the audience, the offer, the ONE action, the traffic source,
and the visitor's awareness stage. Material the user supplied is trusted
as-is. Where the brief is silent, assume and state the assumption; ask
in chat only when the missing piece forks the page into two genuinely
different arguments.

The user's exact words are ANCHORS. Carry them verbatim into everything
downstream — the plan, the copy, your report. "Billing strategy session"
is not "Sessions"; one reinterpreted qualifier costs a whole wasted
build.

## Step 2 — Survey the material

*Tools: `list_cloned_sections`, targeted `search_cloned_sections`,
`view("cloned_section:frag_…")`, `search_assets`; on an existing page
also `view("doc")` and `render_web_preview`.*

Know what the library actually holds and what the key bands actually
look like BEFORE deciding anything. View the bands you are likely to
keep or remix — their markup, their slots, their previews. The evidence
base for this entire build is: what the brief supplied + what this
library captured + registered brand assets. Nothing from your own
memory of the client company, however famous it is.

(When the platform's research spine plugs in, its verified claims join
this step's material. Until then, this step is the whole of research.)

## Step 3 — Construct the argument

*Skill: campaign-landing-page (steps 2–6).*

Awareness stage → the shell judgment (native chrome vs the minimal
campaign shell — your call, per page, never automatic) → the argument
pattern → the evidence inventory, respecting the gaps → the section
list: one visitor question per section, ordered so the visitor's next
unanswered question is always the next band. A section answering no
question does not exist; a question with no section gets one.

## Step 4 — Write the plan

*Skill: plan-design. Tool: `write_file` → `workspace/plan.md`.*

Anchors (verbatim), the brand grammar audit extracted from the real
bands you viewed in step 2, one spec per section with its NAMED source —
PIN · REBIND · DERIVE-VARIANT · REPAIR · COMPOSE-RAW · COMPOSE-VOCAB —
and the Review & Finish tasks, written before building so acceptance
criteria cannot be invented afterward.

From here on the plan is the reference: update each section's status
(planned → built → verified) as you go; a change of direction is a
written amendment FIRST, then an act. If a plan.md already exists from
an earlier pass, continue it — never write a competitor.

Most campaigns are one page. When this one is a small SITE, the plan says so
first: the pages it needs, each with a name and a route (`/`, `/pricing`,
`/security/soc-2`), and what job each page does. Then one section plan per
page, exactly as above. A page nobody can name a job for does not belong in
the plan.

## Step 5 — Build the skeleton

*Tools: `assemble_cloned_sections` (empty page — the paved verb);
the edit-website ladders (existing page); `mint_campaign_shells` +
`assemble_abm_page` (when the shell judgment chose minimal chrome on an
account page).*

On an empty document, pin the plan's keeper set in argument order in ONE
atomic act, with slot rebinds riding the same call wherever the copy is
already written. On an existing document, this step is the edit-website
discipline instead: smallest sufficient verbs, pinned clones preserved
by id, no whole-page reauthor over standing work.

On a multi-page site the director creates every page the plan names
(`add_page`) before the first author brief, then builds them ONE AT A TIME:
`switch_page`, one author brief for that whole page, render, review, amend.
An author brief covers one page — never two.

## Step 6 — Adapt the clones (the props step)

*Skills: edit-website (clone ladder), repair-cloned-sections
(adaptation contract). Tools: `set_node_props` full-payload rebinds,
`repair_cloned_section(..., css=…)`.*

Walk the clone ladder PER BAND:

- Words wrong → **rebind slots** (`set_node_props` with the full
  fragment payload; copy per the slot-geometry rule).
- Shape wrong on a HEALTHY band — a CTA to remove, a sub-element to
  hide, a new eyebrow, restructured emphasis → **derive a campaign
  variant**: `view` the original, remix its FULL markup and CSS,
  change exactly what the campaign needs, inherit the geometry, type
  scale, surfaces, and responsive behavior you didn't touch. This is
  the shallow-refactor move: the canonical example is the cloned hero
  with one CTA instead of two, the logo carousel dropped, and a
  campaign eyebrow — every visual property inherited because you
  started from the original's real bytes. **Derive once, rebind
  forever**: the variant's own texts and links come back as detected
  slots, so later pages of this campaign PIN the variant and rebind —
  they do not re-derive it.
- Band actually BROKEN → **repair** (same tool, different contract —
  the defect defines the change; repair-cloned-sections owns both
  contracts and the lane choice).

Composing a fresh imitation of a band whose ancestor sits in the
library is the failure this step exists to prevent.

## Step 7 — Compose the gaps

*Skill: edit-website ("Composing a new section that belongs").
Tools: `compose_web_section`, then `insert_cloned_section` to pin.*

Only the bands the library genuinely lacks. The sequence is
edit-website's: extract the page's design grammar (already written in
your plan's audit — re-read it) → name ONE structural ancestor → make
the surface-hierarchy judgment → match the content density → build in
the right lane (in a workspace with released clones, raw is the default
and the vocabulary lane is the last resort; remix the ancestor's real CSS,
never imagine) → pin into the gap between real bands. Every composed band is checked against the plan's grammar audit
before it counts as built.

## Step 8 — The copy pass

*Skill: conversion-copywriting.*

The reader test, the claim ladder (claims no stronger than their
evidence), proof attribution, receipt CTAs ("Book the strategy
session", never "Submit"), the slot-geometry rule (match the original's
length; escalate to a variant when the argument needs more room — never
cram). Copy lands through slot rebinds or in the pinning act itself.
ONE action: every CTA on the page leads to the same place, wording
flexing by position, destination never.

## Step 9 — Render, review, and amend

*Tools: `render_web_preview` at 1440 / 768 / 375; `review_cloned_page`;
the reviewer subagent's critique when one is dispatched.*

The rubric is the plan's own Review & Finish tasks — not criteria
invented now:

- No blocking defect at any of the three widths.
- Compare against the cloned source page: it is the acceptance
  reference for grammar, rhythm, and density.
- The logo-off test on every composed and derived band.
- One-action check across every CTA.
- Every claim on the page traces to the anchors (brief or library).
- Read the finished page top to bottom as the arriving visitor: at
  every scroll position — do I know what this is, why it's for me,
  what I get if I act?

Every page of a multi-page site gets this review at all three widths — an
unreviewed second page ships unreviewed. Walk the site's own links too:
each `href="/…"` names a route the plan actually created, and the visitor
can get back to the page carrying the CTA.

Fixes loop back to steps 5–8; each loop-back is a written amendment,
and sections move to `verified` as their tasks pass.

## Step 10 — Finalize honestly

*Tool: `finalize_web_run`.*

The report states plan-vs-built: which sections shipped as planned;
every amendment and its reason; each band's source and lane
(PIN / REBIND / DERIVE-VARIANT / REPAIR / COMPOSE-RAW / COMPOSE-VOCAB);
what this turn RELEASED into the shared library (compositions and
variants are born released — future pages can reuse them, say so);
blast radius beyond this page; assumptions made in step 1; and anything
deliberately left undone. A page that matches its amended plan is a
controlled build regardless of how many loop-backs it took.

## What this workflow does NOT own

- **The argument's depth** — campaign-landing-page (brief, awareness,
  shell, pattern, evidence, sections).
- **The plan's shape and the amendment law** — plan-design.
- **Editing and composing mechanics** — edit-website, create-website.
- **Repair and variant contracts** — repair-cloned-sections.
- **The words** — conversion-copywriting.
- **Account-personalization depth** (markers, `data-slot-when`,
  noindex, derivation) — the abm-page knowledge doc and create-website's
  Personalization section; this workflow's steps apply to ABM pages
  unchanged, with that material layered on.
- **Research** — deliberately absent; it will slot in alongside step 2
  when the platform's research spine feeds design. Until then, step 2's
  evidence base is the whole policy.
