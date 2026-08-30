---
name: repair-cloned-sections
description: The faithful-repair discipline for cloned sections — read the band's lineage and behavior before composing, apply the rung ladder per behavior, preserve what the capture preserved (ugly is not wrong), fix only the defect, and verify the repair against the original and its neighbors. Read this BEFORE calling repair_cloned_section.
---

# Repair a Cloned Section — surgery a returning visitor shouldn't notice

Read this before any `repair_cloned_section` call, and before deciding on
rung 2 of the clone-editing ladder in edit-website.

## Why this is the highest-fidelity-risk edit

Every other clone edit leaves the seller's captured work intact: a slot
rebind changes words inside their geometry; a pin places their band whole.
A repair is the one edit where THEIR work comes off the page and YOURS
takes its place. The bar, stated as an experience:

> A visitor who knew the original site should not notice the surgery. They
> should see the same band, telling the same story, at the same density and
> rhythm — now working.

Everything below serves that bar. None of it is a gate: the user's explicit
instruction always wins, and a repair they asked for is composed the way
they asked for it.

## Read before repairing

Never compose a replacement from memory of the band. First:

1. **View the section** (`view("cloned_section:frag_…")`) — its markup, its
   slot manifest, its preview. The preview is what "correct" looks like.
2. **Read its lineage.** If a repair of this band already exists and is
   RELEASED, pin that instead of minting a duplicate — one lineage should
   carry one chosen replacement, and a second parallel repair creates
   exactly the ambiguity the assembly refuses later. If a draft repair
   exists, say so and ask whether to reuse or replace it rather than
   silently minting a competitor.
3. **Look at the neighbors on the page.** The repair must sit between the
   bands above and below it; their rhythm is your layout brief.
4. **Name the defect precisely.** "Broken at 375 — desktop-only rows run
   off the viewport" is repairable; "looks off" is not yet a diagnosis.

## The behavior inventory — every loss is a decision

Before composing, list what the original band DOES, not just what it shows:

```
hovers?      reveals on scroll?     carousels / cycles?
navigates?   expands / collapses?   plays or animates?
filters?     counts / ticks?        sticks while scrolling?
```

…and for each behavior, what it does for the STORY (a logo carousel says
"many customers"; a hover-reveal says "there's depth here"; a sticky intro
holds context while rows scroll).

Then apply the rung ladder PER BEHAVIOR, not per band:

1. **Reproduce** it with supported primitives — often unreachable, and
   that's by design: the interaction vocabulary is deliberately bounded.
2. **Replace** it with an equivalent from the platform's vocabulary that
   serves the same storytelling purpose (a cycling carousel can become a
   marquee; a hover-reveal grid can become an accordion; "many customers"
   can be said by a static logo row that shows them all).
3. **Drop** it — consciously, with the loss named in your repair note and
   the artificial space it occupied removed ENTIRELY. Dead scroll height is
   never an acceptable outcome at any rung.

A behavior nobody inventoried gets lost silently; a behavior on the list
gets reproduced, replaced, or deliberately let go. That difference is the
whole point of this section. Report the rung you reached and what each
dropped behavior cost.

## Ugly is not wrong

Captured markup is often generated, deep, repetitive, and unpleasant to
read — AND visually correct precisely because of that structure. Exact
spacing, responsive edge cases, blend effects, and layering frequently
depend on the parts that look redundant. Two consequences:

- **You are rebuilding what the band DOES, not tidying how it was
  written.** A repair is judged by its render, never by the elegance of
  its markup. Resist every instinct to "clean up" while repairing.
- **What the capture preserved, the repair preserves**: content hierarchy
  and order, typography and colors, image treatment, proportions and
  density, spacing and section rhythm, the interaction's storytelling
  purpose, and the brand's character. The brand's Grammar Audit is the
  measured law of this seller's own site — a repair that ignores it stops
  looking like the client.

Real imagery only: the band's own captured assets and the registered brand
library. A repair never introduces invented or generic stand-in imagery for
a band that showed the seller's real product.

## The repair-scope contract

A repair fixes THE DEFECT. It is not a redesign opportunity:

- The defect you diagnosed defines the change. Everything else about the
  band — its copy, its images, its order, its density — carries over as-is
  unless the brief asked for more.
- **No drive-by copy rewrites.** If the band's words should also change,
  that is a slot decision or an explicit part of the brief, said in your
  report — never something that "came along" with the repair.
- Density and geometry come FROM the original band: same heading lengths,
  same item counts, same image-to-copy ratio, same container behavior. If
  the original showed six customer stories, the repair does not show three
  bigger cards because they were easier to lay out.
- When the brief genuinely asks for a redesign of the band, you are not
  repairing anymore — say so, and treat it as composing a new section
  (edit-website's compose sequence: grammar, ancestor, density, logo-off).

## Lineage, release honesty, and blast radius

- The original is never touched: your replacement takes its place on the
  page, and the engine's own render of it is minted as a NEW section
  carrying `derived_from`, your rung, and your note. The note is permanent
  lineage — one line, what was broken and what the replacement does.
- **A repair is born UNRELEASED, and kit approval does not release it.**
  Releasing is the user's individual decision, in chat, after you explain
  what the repair is and ask. "They didn't object" is not approval; an
  unreleased draft is not lost, it is waiting.
- Report the page's true state: the page carries your composed section
  directly (it renders identically); do not claim it pins a repair it does
  not.
- **Releasing has blast radius**: a released repair becomes what future
  pins of this lineage resolve to on every page assembled afterward. Say
  that when you ask for the release, so the user decides with the full
  picture.

## Verify the repair

1. Render at 1440 / 768 / 375 — the defect you diagnosed must be GONE at
   the width where it lived, with no new defect at the others.
2. Judge the band BETWEEN ITS REAL NEIGHBORS, not in isolation — rhythm,
   spacing, and surface treatment must flow through it.
3. Compare against the original's preview wherever one exists: same
   hierarchy, same density, same story, same brand character — the
   returning-visitor bar from the top of this file.
4. Your report states: the defect, the rung reached, every behavior
   dropped and why, what the replacement preserves, and the release ask
   with its blast radius.
