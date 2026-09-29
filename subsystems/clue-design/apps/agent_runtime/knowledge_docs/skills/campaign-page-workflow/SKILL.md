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

For a local change to an existing page, start with `edit-website` and perform
only the affected steps. Do not reload/replan/regenerate the whole campaign.

The steps below run in order, but real builds loop back: a render
reveals a wrong guess, a pin refuses, the copy outgrows a slot. Looping
back is fine; doing it OFF THE RECORD is not — every return to an
earlier step lands in `workspace/plan.md` as a written amendment before
you act on it (the plan-design skill's amendment law). Nothing in this
file is a gate: the user's explicit instruction always wins, and a step
that the brief has already answered is a step you skip, saying so.

## Step 1 — Establish the brief

*Skill: campaign-landing-page (steps 1–2).*

Establish the audience, offer, ONE action, traffic source and awareness stage,
distinguishing user requirements, agent-proposed working choices and source
evidence as specified in `plan-design`. The strategy brief is useful context;
its proposals are not automatically user requirements. Attribute genuine prior
approvals to available user messages; retain uncorroborated reports as reported
context. User-supplied material retains its attribution and scope; it is not
independently verified or support for invented claims. Where a decision is open,
make and state a reasonable working choice; ask
in chat only when the missing piece forks the page into two genuinely
different arguments.

The user's exact words are ANCHORS. Carry them verbatim into everything
downstream as requirements in the plan/report. Preserve supported exact copy;
do not put an unsupported requested factual claim on the page. Record that
requirement as unresolved and provide a supported narrower draft where useful. "Billing strategy session"
is not "Sessions"; one reinterpreted qualifier costs a whole wasted
build.

## Step 2 — Survey the material

*Skills: `web-source-readiness`; `web-media-composition` for media and
`web-motion-fidelity` for animation/video/custom-component requirements.*

*Tools: `search_cloned_sections(q="", limit=8)`, targeted `search_cloned_sections`,
`view("cloned_section:frag_…")`, `search_assets`; on an existing page
also `view("doc")` and `render_web_preview`.*

Know what the library actually holds and what the key bands actually
look like BEFORE deciding anything. View the bands you are likely to
keep or remix for pixels; use `inspect_cloned_section` for markup/CSS/slots.
Truncated or unavailable source remains a gap. The evidence
base for this entire build is: attributed brief material, captured library
content, registered brand assets and seller knowledge, and scoped account/contact
claims returned by the exposed shared-platform reads. Preserve each item's
subject, source, freshness and verification status; contact use also requires
the allowed-use gate. A returned claim is not automatically verified. Nothing
comes from your own memory of the client company, however famous it is.

Read `web-account-personalization` for target evidence. Consume shared platform
reads only where exposed; their verified claims can ground this plan. A named
account without research does not provide its priorities or buying intent.
Never seed a brand pack or invent a fetch/refresh tool to fill library gaps.

## Step 3 — Write the argument, copy and action before building

*Skills: `campaign-landing-page`, `conversion-copywriting`; for researched account
pages `web-decision-material`, and for a named person `web-contact-personalization`.*

Awareness stage → the shell judgment (native chrome vs the minimal
campaign shell — your call, per page, never automatic) → the argument
pattern → the evidence inventory, respecting the gaps → the section
list: one visitor question per section, ordered so the visitor's next
unanswered question is always the next band. A section answering no
question does not exist; a question with no section gets one.

Write the copy brief and useful decision material now, before choosing slots or
mutating the document. For a researched page, turn an account priority into a
concrete proposed workflow, criterion-to-product demonstration or evaluation
exhibit. An organization biography followed by generic feature labels is not
that material. Use eligible contact evidence to change the decision and exhibit,
not just the salutation. Select the action's purpose, promise and real destination
using the campaign skill's action-selection guide; a homepage demo button is not
an automatic campaign offer. Decide the copy and imagery together, then find
source components capable of carrying them. Do not build a layout and invent its
argument in step 8.

## Step 4 — Write the plan

*Skill: plan-design. Tool: `write_file` → `workspace/plan.md`.*

Attributed user anchors (verbatim), revisable working choices and evidence,
the brand grammar audit extracted from the real
bands you viewed in step 2, one spec per section with its NAMED source —
PIN · REBIND · DERIVE-VARIANT · REPAIR · COMPOSE-RAW · COMPOSE-VOCAB —
carrying the finished words, evidence references, new reader takeaway and all
retained actions from step 3; and the Review & Finish tasks, written before
building so acceptance criteria cannot be invented afterward.

From here on the plan is the reference: update each section's status
(planned → built → verified) as you go; a change of direction is a
written amendment FIRST, then an act. If a plan.md already exists from
an earlier pass, continue it — never write a competitor. Replace superseded
requirements in its active section and retain a short change note; do not leave
contradictory old instructions as simultaneous requirements.
Reclassify unsupported inherited mandates as working choices; continuation does
not turn an earlier assistant's proposal into a user-approved requirement.

For each affected existing band, record the current pin/version, intended change,
and properties to preserve: type hierarchy, background/product layers, crop/frame
and interaction states. A strong band stays pinned unless the identified defect
requires changing it. This small preservation record makes regressions visible.

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
atomic act, with the copy from step 3 bound in the same call. On an existing
document, this step is the edit-website
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
  variant**: view the original and inspect its source, remix its FULL markup and CSS,
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

## Step 8 — Check copy fit and continuity

*Skill: conversion-copywriting.*

Check the already-written argument in its actual composition: the reader test,
claim ladder (claims no stronger than their evidence), proof attribution,
action/receipt alignment, and the slot-geometry rule (match the original's
length; escalate to a variant when the argument needs more room — never
cram). Copy lands through slot rebinds or in the pinning act itself.
Keep one coherent page intent; repeat its action only where useful. Preserve
legitimate secondary resources and legal actions. In-page exploration can be
the right next step for an educational draft, but is navigation, not evidence
that a requested lead-generation flow has been delivered.

## Step 9 — Render, review, and amend

*Tools: `render_web_preview` at 1440 / 768 / 375; `review_cloned_page`;
the reviewer subagent's critique when one is dispatched.*

The rubric is the plan's own Review & Finish tasks — not criteria
invented now:

- No blocking defect at any of the three widths.
- Compare against the cloned source page: it is the acceptance
  reference for grammar, rhythm, and density.
- The logo-off test on every composed and derived band.
- Check the reader's decision, useful exhibit and every actual link/control
  destination. A working demo link can still be the wrong action for this page.
- Compare changed bands with their preservation record at desktop and phone
  widths. A lost product image/background, flattened control or changed font
  hierarchy is a regression, even if the new section compiles.
- Every claim on the page traces to its actual evidence: attributed brief
  material, captured library content, seller knowledge, or scoped platform
  account/contact claims. Keep the subject, freshness, verification and
  contact-use limits intact; user requirements alone do not verify a claim.
- Read the finished page top to bottom as the arriving visitor: at
  every scroll position — do I know what this is, why it's for me,
  what I get if I act?

Every page of a multi-page site gets this review at all three widths — an
unreviewed second page ships unreviewed. Walk the site's own links too:
each `href="/…"` names a route the plan actually created, and the visitor
can get back to the page carrying the CTA.

Group observed blocking fixes into a scoped amendment before changing anything.
Reuse unchanged source/research evidence and correct bands; do not regenerate
images or ask for a new whole page to repair copy. Fixes loop back to the affected
steps, and sections move to `verified` as their tasks pass. If a pass changes
nothing material or needs unavailable evidence/capture, stop with that gap;
another generation is not a diagnosis.

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
- **Audience modes, target evidence and contact-use gates** —
  web-account-personalization. The abm-page knowledge document adds real
  template/derivation mechanics when that route is chosen.
- **Research acquisition** — belongs to the shared platform/brand ingestion;
  consume available evidence and report coverage rather than fabricate it.
