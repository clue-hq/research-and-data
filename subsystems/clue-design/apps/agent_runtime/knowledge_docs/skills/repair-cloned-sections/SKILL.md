---
name: repair-cloned-sections
description: The faithful-repair AND campaign-variant discipline for cloned sections — read the band's lineage and behavior before composing, apply the rung ladder per behavior, preserve what the capture preserved (ugly is not wrong), fix only the defect (repairs) or change only what the campaign needs while inheriting the visual system (variants), and verify against the original and its neighbors. Read this BEFORE calling repair_cloned_section for either intent.
---

# Repair a Cloned Section — surgery a returning visitor shouldn't notice

Read this before any `repair_cloned_section` call, and before deciding on
rung 2 (derive a variant) or rung 3 (repair) of the clone-editing ladder
in edit-website. The tool serves BOTH intents — fixing a broken band, and
adapting a healthy one for a campaign — and the "Adaptation is not
repair" section below says which contract binds which.

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

## Two repair lanes — pick by what the band must stay

A replacement is composed in one of two lanes, and the choice mirrors the
composing lanes in edit-website:

- **The raw lane** — `repair_cloned_section(fragment_id, …, css="…")`: your
  replacement's raw HTML plus its raw CSS, passed through the same
  sanitize-once door every captured byte passes. Compose it as a REMIX of
  the original's own markup and stylesheet — you have already viewed the
  section; keep its real class names, spacing constants, and type scale,
  and change only what the defect requires. This is the DEFAULT on a
  fidelity-critical band: the band must go on looking like the seller's
  site, and the original's own CSS is the only faithful source for that.
  The repair is minted, RELEASED, and swapped into the page in one act —
  there is no chat gate on this lane. The release duty moves into your
  report instead: state plainly that this repair now owns its lineage
  (every future pin of this band resolves to it), so the user hears the
  blast radius even though they were not asked first.
- **The vocabulary lane** — no `css` argument: the replacement is composed
  in the platform's constrained vocabulary. Choose it when the band should
  become deeply editable in the inspector or carry derivation markers —
  you are deliberately trading byte-fidelity for editability, and that
  trade is worth naming in the report. The variant is born a DRAFT;
  releasing it is the user's decision, in chat (the release-honesty
  section below).

The lane changes WHO releases and WHAT the replacement is written in —
never what quality means. Everything else in this file binds identically
in both lanes: the behavior inventory, ugly-is-not-wrong, the repair-scope
contract, and verification against the original.

## Adaptation is not repair — same door, different contract

`repair_cloned_section` serves a second intent: **deriving a campaign
variant of a HEALTHY band** whose slots can't carry the campaign — a CTA
to remove, a sub-element to hide, a new eyebrow, a different emphasis.
This is the raw lane used deliberately on a band with no defect, and it is
the RIGHT move: composing a fresh band while its ancestor sits in the
library reinvents everything — including, too easily, the truth.

The variant's contract differs from a repair's in what may change:

- **Copy and cardinality MAY change.** A variant deliberately rewords,
  removes elements, and reshapes structure to fit the campaign — the
  repair-scope contract's "no drive-by rewrites" binds REPAIRS, not
  variants.
- **The visual system MAY NOT change.** Geometry, type scale, surfaces,
  spacing rhythm, responsive behavior, and the brand's character are
  inherited from the original's real bytes — that inheritance is the
  entire reason to derive instead of compose. `view` the original first
  and remix its actual markup and CSS; never reconstruct it from memory.
- **The behavior inventory still binds.** Dropping the logo carousel or
  the second CTA is a NAMED decision in your note and report, never a
  silent loss.
- **The lineage note names the intent**: "campaign variant: …" (what
  changed and for which purpose), not a defect description. `derived_from`
  still points at the original, which survives untouched.
- **Released at mint like any raw-lane mint — but a variant NEVER replaces
  the original.** A repair becomes what future pins of the original resolve
  to; a campaign variant does not: it starts its own lineage, pins of the
  original keep resolving to the original, and later pages pin the variant
  by its own id. So derive freely from the client's canonical bands — the
  homepage hero with one CTA and an eyebrow is the textbook case — and say
  in your report that the original is untouched for every other page.

One more inheritance: the variant's own texts and links come back as
detected slots, so a well-made variant is itself a parameterized,
rebindable band — derive it once, then rebind per page for the rest of
the campaign.

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
- When the brief genuinely asks the band to change shape, you are not
  repairing anymore — say so, and treat it as deriving a campaign variant
  (the adaptation contract above) or, when no clone is structurally
  close, composing a new section (edit-website's compose sequence:
  grammar, ancestor, density, logo-off).

## Lineage, release honesty, and blast radius

- The original is never touched: your replacement takes its place on the
  page, and it is minted as a NEW section carrying `derived_from`, your
  rung, and your note. The note is permanent lineage — one line, what was
  broken and what the replacement does.
- **A vocabulary-lane repair is born UNRELEASED, and kit approval does not
  release it.** Releasing is the user's individual decision, in chat, after
  you explain what the repair is and ask. "They didn't object" is not
  approval; an unreleased draft is not lost, it is waiting. (A RAW-lane
  repair is released at mint — see the two-lanes section; its release is
  reported, not requested.)
- Report the page's true state: say which lane the repair took, whether
  the page pins the repair (raw lane) or carries your composed section
  directly (vocabulary lane), and never claim a pin that did not happen.
- **Releasing has blast radius**: a released repair becomes what future
  pins of this lineage resolve to on every page assembled afterward. In the
  vocabulary lane, say that when you ask for the release, so the user
  decides with the full picture; in the raw lane, say it unprompted in the
  report — the user must still hear it even though nobody asked them.

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
