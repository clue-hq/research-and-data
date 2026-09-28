---
name: plan-design
description: Write the page's design plan to workspace/plan.md BEFORE building — the brief's anchors, the brand grammar audit, per-section specs with named sources, and the review tasks — then track status per section, amend in writing when direction changes, and finish against the plan. Read this before any substantial build (a fresh page, a campaign page, a multi-section brief).
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
1. Anchors          — the brief's own words; what the page may use
2. Grammar audit    — the measured visual law of this client's site
3. Sections         — one spec per band, each with a named source
4. Review & finish  — the acceptance walk, written before building
```

### 1. Anchors

Quote the user's words VERBATIM for: the audience, the offer, and the one
action. State every assumption you made where the brief was silent.

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
- Typography posture (weight, scale, tracking, case, heading length)
- Interaction temperament (restrained or playful)
- Concrete constants where you can read them: container widths, section
  padding, radius values, type sizes
- The recognizability test: what makes this page THIS brand with the
  logo removed?

These are compositional CONSTRAINTS for every band you touch, not loose
inspiration. A composed or derived band that violates the audit is
off-plan even if it looks good.

### 3. Sections

One entry per band the page will carry, in page order. Each entry:

```
## <n>. <section name>                                [status: planned]
Question:  the one visitor question this band answers
Source:    PIN frag_… | REBIND frag_… (slots: …) |
           DERIVE-VARIANT of frag_… (what changes) |
           REPAIR frag_… (the defect) |
           COMPOSE-RAW (remix ancestor frag_…) | COMPOSE-VOCAB (why)
Design:    layout / CTA treatment / surface / density vs its ancestor
Content:   the copy angle and where its facts come from
```

The argument decides WHICH sections exist and in what order — that is the
campaign-landing-page skill's job, done before this plan is written. A
section with no named source, or answering no question, does not go in
the plan. Decisions the grammar audit constrains (how many dark
intervals, where CTAs sit) are closed HERE, in writing, not at build
time.

### 4. Review & Finish tasks

Write the acceptance walk BEFORE building, so review criteria cannot be
invented afterward to match whatever got built:

- Render at 1440 / 768 / 375 — no blocking defect at any width.
- Compare against the cloned source page — it is the acceptance
  reference for grammar, rhythm, and density.
- The logo-off test on every composed or derived band.
- One primary conversion action: its CTAs use the real supported destination.
  Useful source, legal and navigation links retain their distinct purposes.
- Every factual meaning traces to the evidence inventory in the anchors section,
  at that source's strength, subject and use scope. Walk the rendered page and check.
- Re-read the finished page top to bottom as the arriving visitor
  (campaign-landing-page step 8).
- Every section's status is `verified`.

## Status tracking

Each section entry carries `[status: planned | built | verified]`.
Update it as you go — `built` when the band is on the page, `verified`
when its review tasks passed. At any moment, the plan answers "what is
done and what is left" without re-deriving it from the document.

## Amendments — a change of mind is written BEFORE it is acted on

Mid-build you will sometimes be right to deviate: a pin refuses, a band
genuinely cannot carry the argument, the render reveals a wrong guess.
The rule is not "never deviate"; it is:

> Append the amendment to plan.md FIRST, then act on it.
> `AMENDMENT: <what changes> — <why> — <which sections it affects>`

Before writing an amendment, re-read the ANCHORS and the GRAMMAR AUDIT —
the amendment must still serve both. An amendment that changes what the
page is about (a different offer, a different audience, content outside
the anchors) is not an amendment; it is a wrong turn, and re-reading the
anchors is what catches it. An unwritten deviation is drift by
definition, however reasonable it feels in the moment.

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
- **Words** — conversion-copywriting owns the copy the content specs
  gesture at.
- **Research acquisition and verification** — owned by the platform. This plan
  consumes available scoped evidence through `web-account-personalization`; it
  does not launch discovery or promote supplied assertions into verified claims.
