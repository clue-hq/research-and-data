---
name: plan-design
description: Use before a substantial website build, campaign page or multi-section rebuild, and when resuming an inherited page plan whose requirements, assumptions or sources need reconciliation.
---

# Plan the Design — write it down, then build against it

## Why a written plan

Design drift happens through a series of individually reasonable decisions.
The hero needs more punch, so rebuild it. The proof band looks thin, so
add a richer one. Each step made sense; at the end the page no longer
serves the brief it started from — and nobody decided that. It happened.

A written plan prevents this by closing decisions in advance. When the
plan lives only in your head, replacing it mid-build looks and feels like
planning; when it lives in a file, replacing it is a visible AMENDMENT
with a written reason. That difference is the whole mechanism.

Two more reasons the file matters on this platform:

- **You may not be the only author pass.** Author delegations start
  fresh, with no memory of earlier passes. `workspace/plan.md` is the one
  memory that survives — if it exists when you start, READ IT FIRST and
  continue it; never write a competing second plan.
- **Your own knowledge is the enemy of fidelity.** The more famous the
  client, the more your memory volunteers content the brief never asked
  for — products, events, dates, speakers. The plan's anchors section
  (below) is where you commit to what the page may actually use, before
  the building pressure starts.

The plan is a WORKING ARTIFACT, never an approval gate. You write it and
proceed — you do not stop to ask permission unless the user asked for
plan-only work. The user's explicit instruction always wins over anything
in the plan or in this skill.

## When to write one

Substantial builds: a fresh page, a campaign page, a multi-section brief,
a whole-page rebuild. Not for small scoped edits — a one-band fix or a
slot reword needs no plan file. If in doubt: if the work will span
multiple bands or multiple passes, plan it.

## The plan's structure

Write `workspace/plan.md` BEFORE your first document mutation, in this
order:

```
1. Anchors          — attributed user requirements, working choices and evidence
2. Grammar audit    — the measured visual law of this client's site
3. Sections         — one spec per band, each with a named source
4. Review & finish  — the acceptance walk, written before building
```

### 1. Anchors

Separate three kinds of input in a compact record before deciding the page:

| Input | Record | How it governs the build |
| --- | --- | --- |
| User requirement | Exact relevant quote and origin: current message, prior user message, or a user-approved plan with its approval reference | Preserve the requested audience, purpose, copy, scope and constraints; later user corrections supersede earlier ones. |
| Working choice | Proposed decision, origin (strategy brief, earlier assistant plan or this pass), reason and uncertainty | Adopt it when it serves the user and evidence; amend it when it does not. This is a design decision, not a user mandate. |
| Evidence | Source/claim reference, subject, accessible value and verification/use limits | Supports factual meaning at its actual strength. User approval of a layout does not verify its claims. |

A delegation brief is an agent-authored summary. Extract useful context without
turning its emphatic wording into a user quote. A reported prior approval whose
user source is unavailable stays reported context; it can inform a consistent
working choice but must not be described as observed approval. When the user says
"use the approved plan," follow the available approval and its scope, not later
assistant additions. Carry this distinction forward when resuming an existing plan.

Quote only what the user actually specified. A simple request for an account page
does not specify a pilot, navigation logos, a demo offer or a number of sections.
Choose any missing audience detail, offer/action and shell deliberately, with a
short reason; keep those choices revisable. Explicit requests for those treatments
remain requirements. Ordinary design choices do not need a confirmation round.
For a narrow edit, preserve its boundary and inspect only the affected assumptions.

Then close the evidence question before it can drift:

- The evidence inventory includes attributed brief material, captured library
  content, registered brand assets, pinned seller knowledge and scoped account/contact
  research returned by exposed platform reads. Record accessible values/excerpts,
  subject, source/claim references, dates, verification and allowed-use limits.
  Supplied assertions and written overviews do not become verified facts by being
  read. Preserve conflicts and truncation as gaps. **Never use your own knowledge
  of the company** to fill those gaps, however confident the memory feels.
- Never invent named customers, metrics, quotes, awards, or deadlines —
  an honest gap is correct output; a fabricated proof is the only real
  failure. Product phrasing composed from the brief and the site's own
  captured language is acceptable; say in your report where you were
  uncertain. Research may change the page's argument and section choices; it
  does not replace the seller's visual grammar or establish a relationship.

### 2. Brand Grammar Audit

Extracted from REAL bands — `view` the cloned sections and read their
actual CSS before writing this; never write a grammar audit from memory
or general brand impressions. Name, concretely:

- Hero archetype (split? centered? what carries the visual weight?)
- Section rhythm — the surface cadence down the page (light/dark/neutral
  intervals, and how many dark intervals the page tolerates)
- Image-to-copy ratio and how imagery is treated
- Surface language (borders vs shadows vs background shifts; radii)
- Color frequency (where accents appear, and how rarely)
- Typography by source role: actual face/weight, size, line-height, tracking,
  text measure and 1440/768/375 changes. An alias such as `headingFont` is not
  the face or the scale. Mark unavailable measurements instead of guessing.
- Interaction temperament (restrained or playful)
- Concrete constants where you can read them: container widths, section
  padding, radius values, type sizes
- The recognizability test: what makes this page THIS brand with the
  logo removed?

These are compositional CONSTRAINTS for every band you touch, not loose
inspiration. A composed or derived band that violates the audit is
off-plan even if it looks good.

### 3. Sections

For a campaign or account page, read
[website copy brief](../conversion-copywriting/references/website-copy-brief.md)
before writing these records. Carry its finished copy into this plan, not a
second copy brief. Keep each evidence excerpt once in Anchors and reference it
from the sentences it supports.

One entry per band the page will carry, in page order. Each entry:

```
## <n>. <section name>                                [status: planned]
Question:  the one visitor question this band answers
Source:    PIN frag_… | REBIND frag_… (slots: …) |
           DERIVE-VARIANT of frag_… (what changes) |
           REPAIR frag_… (the defect) |
           COMPOSE-RAW (remix ancestor frag_…) | COMPOSE-VOCAB (why)
Design:    layout / CTA treatment / surface / density vs its ancestor
Preserve:  source hierarchy / layout / spacing / media frame / responsive rules
Type:      source node/role and measured face, weight, size, line height,
           tracking and measure at each available width; name unknowns
Adds:      what the reader learns here beyond the preceding bands
Words:     actual heading, explanation and card/panel copy, or an exact reference
           to inspected source copy deliberately retained unchanged
Evidence:  anchor references for factual sentences; distinguish proposed application
Actions:   each retained button's label, destination/behavior and purpose; name
           inherited buttons to replace/remove, or state that the band has none
```

The argument decides WHICH sections exist and in what order — that is the
campaign-landing-page skill's job, done before this plan is written. A
section with no named source, or answering no question, does not go in
the plan. Decisions the grammar audit constrains (how many dark
intervals, where CTAs sit) are closed HERE, in writing, not at build
time. The builder receives words it can place, not instructions such as
"personalize the feature cards" or "explain portfolio value." A missing source
detail is an explicit unresolved dependency; inspect it before writing its copy.
A second product exhibit earns space by answering a different question, not
because the library has another attractive screenshot. Merge repeated arguments
while preserving useful explanation; do not solve length by making type smaller.

For a selected component, `Preserve` starts with its complete structure and format.
List only the explicit requested differences. New wording fits those roles through
slots or exact text leaves; it does not silently authorize a new component.

### 4. Review & Finish tasks

Write the acceptance walk BEFORE building, so review criteria cannot be
invented afterward to match whatever got built:

- Render at 1440 / 768 / 375 — no blocking defect at any width.
- Compare against the cloned source page — it is the acceptance
  reference for grammar, rhythm, and density.
- The logo-off test on every composed or derived band.
- The chosen primary action, if any, has the planned label, purpose and real
  destination. Check every retained source button, including unslotted ones.
  Useful source, legal and navigation links retain their distinct purposes.
- Every factual meaning traces to the evidence inventory in the anchors section,
  at that source's strength, subject and use scope. Walk the rendered page and check.
- Re-read the finished page top to bottom as the arriving visitor
  (campaign-landing-page step 8).
- Every section has a recorded review result. Mark `verified` only after its
  required checks pass; keep failed or missing checks explicit as unfinished work.

## Status tracking

Each section entry carries `[status: planned | built | verified]`.
Update it as you go — `built` when the band is on the page, `verified`
when its review tasks passed. At any moment, the plan answers "what is
done and what is left" without re-deriving it from the document.

## Amendments — a change of mind is written BEFORE it is acted on

Mid-build you will sometimes be right to deviate: a pin refuses, a band
genuinely cannot carry the argument, the render reveals a wrong guess.
The rule is not "never deviate"; it is:

> Update the active section record in plan.md FIRST, retain a short change note,
> then act on it.
> `AMENDMENT: <what changes> — <why> — <which sections it affects>`

Before writing an amendment, re-read the ANCHORS and the GRAMMAR AUDIT —
the amendment must serve the current user requirements and preserve applicable
brand constraints. Replace superseded requirements in the active record and keep
a short change note. Reclassify inherited assistant choices that were incorrectly
listed as user requirements. An inferred offer can change for a documented reason;
an explicit user offer cannot silently become a different one. Repeating a choice
in several plans does not establish its approval. Unrecorded deviation is drift.

If something fails mid-turn, amend the plan and continue against it —
never abandon the file and improvise the rest of the page.

## Finish against the plan

Your finalize report states plan-vs-built: which sections shipped as
planned, every amendment with its reason, and the final status of every
section. A page that matches its amended plan is a controlled build; a
page that quietly diverged from an unamended plan is a failed process
even when it looks good.

## What this skill does NOT own

- **The argument** — which sections deserve to exist, the shell
  judgment, the pattern: campaign-landing-page, read BEFORE planning.
- **Mechanics** — assembly, lanes, variants, repairs: edit-website and
  repair-cloned-sections; the plan names the source, those skills own
  executing it.
- **Words** — conversion-copywriting owns the wording; this plan carries its
  resolved copy and evidence references through assembly and review.
- **Research acquisition and verification** — owned by the platform. This plan
  consumes available scoped evidence through `web-account-personalization`; it
  does not launch discovery or promote supplied assertions into verified claims.
