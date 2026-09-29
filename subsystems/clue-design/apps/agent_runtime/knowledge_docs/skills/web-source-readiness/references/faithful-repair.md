# Faithful repair and variant reference

Read after the repair-cloned-sections skill when choosing a repair lane or
working through behavior fallback, scope and lineage.

## Prefer bounded edits before reconstructing a band

Existing slots are the first choice. For unbound plain feature/FAQ copy, use
`inspect_cloned_section(text_only=True)` and exact `text_edits_json` through
`repair_cloned_section`; for anchors use its exact href/label arguments. Read
the parent repair skill for bounds, stored coordinates and refusal handling.
These paths retain the library's HTML/CSS/assets and existing pin without
transcribing source. Copy-only adaptation needs neither a raw remix nor a
new visual composition. It still needs research-grounded copy and render review.

## Two reconstruction lanes — pick by what the band must stay

A replacement is composed in one of two lanes, and the choice mirrors the
composing lanes in edit-website:

- **The raw lane** — `repair_cloned_section(fragment_id, html, rung, note, css="…")`: your
  replacement's raw HTML plus its raw CSS, passed through the same
  sanitize-once door every captured byte passes. Compose it as a REMIX of
  the original's own markup and stylesheet — you have already viewed the
  section; keep its real class names, spacing constants, and type scale,
  and change only what the defect requires. Use this when a
  fidelity-critical band needs structural or CSS changes: it must keep looking like the seller's
  site, and the original's own CSS is the only faithful source for that.
  On success, the repair is minted, RELEASED, and swapped into the page
  in one call — there is no chat gate on this lane. Mint/release precedes
  the page swap: if that swap fails, report the released library repair and
  unchanged page exactly as the tool returns them. The release duty moves into your
  report instead: state plainly that this repair now owns its lineage
  (every future pin of this band resolves to it), so the user hears the
  blast radius even though they were not asked first.
- **The vocabulary lane** — no `css` argument: the replacement is composed
  in the platform's constrained vocabulary. Choose it when the band should
  become deeply editable in the inspector or carry typed `data-var` /
  `data-slot` attributes that raw slot values cannot express —
  you are deliberately trading byte-fidelity for editability, and that
  trade is worth naming in the report. The variant is born a DRAFT;
  releasing it is the user's decision, in chat (the release-honesty
  section below).

  Typed **tabs** now retain their approved platform controller and base styles
  when saved as a reusable repair. Each pin has independent tab/panel identities.
  This preserves native behavior; it does not recover the source site's JavaScript
  or prove that its image mapping, timing or visual treatment match the source.
  `behavior_evidence.controller_status="declared_native_runtime"` is a dependency
  declaration, not a test pass. Render the actual pin and inspect its desktop,
  phone and keyboard state receipts. Other native component dependencies currently
  refuse library minting explicitly while retaining the typed section on the page.
  Do not switch to raw HTML/CSS to bypass that refusal: raw repairs of a native
  artifact cannot preserve its declared dependencies. Exact text/link edits retain
  them; the ordinary release rules still apply.

  Portable custom class rules also travel with the repair. Global CSS, cascade
  layers and ID-dependent styles that cannot survive independent pins refuse
  minting while leaving the typed section available. For card labels and product
  image switching, read [rich card controls](../../web-motion-fidelity/references/rich-card-controls.md).

The lane changes WHO releases and WHAT the replacement is written in —
never what quality means. Everything else in this file binds identically
in both lanes: the behavior inventory, ugly-is-not-wrong, the repair-scope
contract, and verification against the original.

## Adaptation is not repair — same door, different contract

`repair_cloned_section` serves a second intent: **deriving a campaign
variant of a HEALTHY band** whose slots can't carry the campaign — a CTA
to remove, a sub-element to hide, a new eyebrow, a different emphasis.
Use exact edits for copy-only changes; use the raw lane when structure must
change. Composing a fresh band while its ancestor sits in the
library reinvents everything — including, too easily, the truth.

The variant's contract differs from a repair's in what may change:

- **Copy and cardinality MAY change.** A variant deliberately rewords,
  removes elements, and reshapes structure to fit the campaign — the
  repair-scope contract's "no drive-by rewrites" binds REPAIRS, not
  variants.
- **The visual system MAY NOT change.** Geometry, type scale, surfaces,
  spacing rhythm, responsive behavior, and the brand's character are
  inherited from the original's real bytes — that inheritance is the
  entire reason to derive instead of compose. `view` the original preview;
  structural/raw variants inspect complete actual markup/CSS first. Copy-only
  variants use the bounded text inventory instead; never reconstruct styling
  from memory or request a whole stylesheet merely to change one sentence.
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

For a raw variant, its own texts and links come back as
detected slots, so a well-made variant is itself a parameterized,
rebindable band — derive it once, then rebind per page for the rest of
the campaign. Exact text edits retain the original manifest; they do not
create new slots. Their stored expected-text inventory is the editing surface.

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
  grammar, ancestor, density, logo-off). Follow `create-website` for the
  callable composition path.

## Lineage, release honesty, and blast radius

- The original is never touched: your replacement takes its place on the
  page, and it is minted as a NEW section carrying `derived_from`, your
  rung, and your note. The note is permanent lineage — one line, what was
  broken and what the replacement does.
- **A vocabulary-lane repair is born UNRELEASED, and kit approval does not
  release it.** Releasing is the user's individual decision, in chat, after
  you explain why it exists, which rung it uses, what changed or was lost,
  and its effect on future pins. Show `view("cloned_section:<id>")` evidence
  before asking to release that specific repair; if the preview is missing,
  obtain it through the supported role/tool path. There is no approval button.
  Wait for an explicit yes before `release_repair(fragment_id)`; an author
  unable to ask hands the explanation/request to the director. Existing approval
  for this specific repair stands; do not ask again. "They didn't object" is not
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

1. Have the director/solo agent call `render_web_preview()`, then inspect
   `view("preview:1440")`, `view("preview:768")`, `view("preview:375")` and any
   returned `state:<n>` captures. An author without the render tool returns
   to the director instead of inventing a call. At 1440 / 768 / 375 — the defect you diagnosed must be GONE at
   the width where it lived, with no new defect at the others.
2. Judge the band BETWEEN ITS REAL NEIGHBORS, not in isolation — rhythm,
   spacing, and surface treatment must flow through it.
3. Compare against the original's preview wherever one exists: same
   hierarchy, same density, same story, same brand character — the
   returning-visitor bar from the top of this file.
4. Your report states: the intent, the defect or requested adaptation,
   the rung reached, every behavior dropped and why, preserved properties,
   source/output comparison limits, returned release/pin state, and lineage
   effect. Ask for release only for an individually reviewed vocabulary
   draft where approval has not already been given; a raw campaign variant
   starts its own lineage and does not replace future pins of the original.
