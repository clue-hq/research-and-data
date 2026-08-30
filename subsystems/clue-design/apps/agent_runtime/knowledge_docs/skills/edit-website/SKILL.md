---
name: edit-website
description: Edit and evolve an existing page — repair, rewrite, add, remove, and recompose — choosing the smallest sufficient verb. Owns the composed-content ladder, the clone-editing ladder, the reuse ladder for additions, composing new sections that belong (grammar, ancestor, density, the logo-off test), blast radius, and scope discipline.
---

# Edit a Website That Already Exists

Between your turns, humans edit the page directly: inspector class changes,
raw-class pastes, inline text edits, undo/redo. Briefs arrive asking you to
change wording, add sections, remove sections, or reshape the page for a new
purpose. The document you receive is never quite the one you last wrote.

## The principle everything here derives from

An existing page is INVESTED STATE: human edits, node identity, history and
selections, personalization markers, clone lineage, the seller's
market-tested pixels, and a narrative a visitor walks top to bottom. Every
edit verb has a blast radius — some verbs touch one attribute, some re-mint
a section's identity, some change what other pages will resolve tomorrow.

> The craft of editing is choosing the smallest verb that fully serves the
> intent — and making every addition join the page's argument and visual
> rhythm instead of sitting beside them.

Nothing in this file is a gate. It is the judgment that makes edits good;
the user's explicit instruction always wins, and anything they supplied is
used as-is.

## Diagnose before touching anything

1. `view("doc")` — the current tree: section ids, node kinds, class strings.
2. `render_web_preview` + look at all three widths. The pixels tell you what
   the human's edits actually did; the brief tells you what they want now.
3. Classify each band you're about to touch: **is it a cloned section (a
   fragment node) or composed content?** The answer picks the ladder below.
4. Identify the delta class: broken layout (bad classes), awkward copy,
   structural damage (emptied/duplicated content), or nothing wrong (the
   brief is a new request, not a repair).

## The composed-content ladder — smallest sufficient tool

1. **`web_ops`** — one or a few surgical operations
   (`set_node_classes`, `set_text`, `set_rich_text`, `set_node_props`,
   `remove_node`, `move_node`, `insert_node`). The default for "fix this
   class", "change this wording", "swap this href", "drop this band",
   "move that section up". Ops apply checked and atomically; a batch that
   would break the document is rejected whole.
2. **`author_web_subtree`** — one section's markup is beyond patching
   (mangled structure, needs recomposition). Keep the section id.
3. **`author_web_page`** — the page as a whole no longer serves the brief.
   Rare; never for a localized complaint.

Climbing higher than needed destroys human edits you were not asked to
touch — a whole-page rewrite after a one-class complaint is a defect, even
if the result looks fine.

Rung choice is a correctness matter, not taste: if the fix is expressible
as one-to-three ops against EXISTING nodes — `set_node_classes`,
`set_text`, `set_rich_text`, `set_node_props` (including rewiring a button's
action between link and command, making a container clickable, or changing a
section/container background and scrim) — then `web_ops` is the ONLY correct
rung. Send the FULL kind payload: container link/background and section
background fields are preserved explicitly, not partial-patched. Reach for
`author_web_subtree` solely when the section's STRUCTURE must change: nodes
added, removed, or reordered beyond what a couple of ops express. A subtree
rewrite that reproduces the section just to change one attribute is a defect
even when the pixels match — it re-mints node ids that history, selections,
and future scoped turns hang off.

For a `custom_component` leaf, do not replace its enclosing section merely to
change component behavior. Load the `custom-components` skill, inspect the
slug/source/version, write and compile a new immutable version, then
`place_custom_component(action="repin")` with the explicit selected node ids.

## The clone-editing ladder — a cloned band is the seller's real work

A cloned section is not markup you wrote; it is a band of the seller's own
site, captured byte-exact, market-tested by every visitor that site ever
had. Its verbs, smallest blast radius first:

1. **Rebind its slots.** Words, links, images, visibility — the spots capture
   annotated as editable. Geometry, layout, and styling stay byte-identical
   around the new content. This is the default for "change what this band
   says", and it is an ordinary op: `set_node_props` on the fragment node
   with the FULL kind payload (fragment_id + the complete `slots` map — the
   payload replaces, never merges). The copy you bind follows the
   conversion-copywriting skill's slot-geometry rule: match the original's
   approximate length and line count; markers count at rendered size.
2. **Repair it** (`repair_cloned_section`). The change is structural — the
   slot set can't express it. The repair is a NEW lineage-tracked variant;
   the original survives untouched as evidence, and the page carries your
   variant. Use this when the argument outgrows the slots — never cram.
   Before composing a repair, read the repair-cloned-sections skill: it
   owns the faithful-repair discipline (lineage check, the behavior
   inventory, ugly-is-not-wrong, the repair-scope contract, verification
   against the original).
3. **Replace it.** A different released clone fits better
   (`insert_cloned_section` + `remove_node`), or the library lacks the job
   and you compose a new band (see "Composing a new section" below).

**Never retype a healthy clone's markup.** Reauthoring a working cloned band
by hand is not an edit — it forges the seller's work and silently loses the
spacing, responsive edge cases, and interaction hooks the capture preserved.
The slots are the door; the repair flow is the bigger door.

Two clone-specific situations you will meet mid-edit:

- **A degraded pin.** A band flagged degraded is on the page knowingly
  broken (usually at one width). Fixing it is a repair, not a slot rebind —
  and if a released repair already exists in its lineage, prefer pinning
  that over minting a duplicate.
- **A chrome swap.** Exchanging the native cloned nav/footer for the minimal
  campaign shells (or back) is an ordinary edit: remove the old bands, pin
  the new ones. WHICH chrome the page should wear is not this skill's call —
  the campaign-landing-page skill owns that judgment; you own executing it
  cleanly.

## Adding to an existing page

**The reuse ladder** — before composing anything, walk down:

1. A released cloned section already does the job → pin it as-is.
2. A clone has the right bones, wrong words → pin it and rebind slots.
3. A clone is structurally close → repair-variant it.
4. The library genuinely lacks the job → compose a new section (next
   section of this file).

Never compose what the library already holds — a composed imitation of an
existing clone is always less faithful than the clone.

**Narrative integration** — a requested module never gets bolted on. "Add a
form", "add a comparison", "add a proof band" means: find where the
visitor's next unanswered question lives in the page's argument (the
campaign-landing-page skill's section logic) and place the module THERE,
then re-read the page top to bottom — the story must still hold around it.
The module serves the page; the page is not a demo stand for the module.

## Composing a new section that belongs

When the ladder bottoms out and you must compose, the danger is the generic
section: three icon cards that would fit any SaaS site, wearing this brand's
colors. Follow this sequence:

1. **Extract the page's design grammar first.** Read the surrounding bands
   and name, to yourself, what makes this site recognizable beyond its logo:
   its composition habits (split heroes? asymmetric two-column? linear rows
   vs card grids?), its spacing rhythm (dense or airy? wide or narrow
   container?), its typographic posture (heading weight, length, case), its
   surface language (borders vs shadows vs background shifts), and its
   interaction temperament (restrained or playful). That grammar is the
   spec your new section is written against.
2. **Name one structural ancestor.** Pick the existing band — cloned or
   composed — whose JOB is closest to the new section's, and inherit its
   visual sentence structure: its split, its row anatomy, its CTA placement,
   its background treatment. New content, familiar sentence structure. A
   section with no ancestor is where generic design sneaks in.
3. **Make the surface-hierarchy judgment.** Not everything becomes a card.
   Ask what THIS site uses for this kind of content: a bordered row? a
   background shift? whitespace alone? Is the accent surface functional
   here (the way a conversion panel earns its supporting color) or would it
   be decoration? Inherit the ancestor's answer.
4. **Match the content density.** Heading length, paragraph measure, number
   of items, image-to-copy ratio, whitespace between phases — a section can
   use every correct token and still feel foreign because it holds six
   dense paragraphs on a site that speaks in short lines. Count the
   ancestor's items and lengths; land near them.
5. **Build in the right lane.** Fidelity-critical (the normal case on a
   cloned page): `compose_web_section` — raw HTML + raw CSS through the same
   sanitize-once door every captured byte passes — and your ancestor from
   step 2 is not just inspiration, it is *source material*: view it and
   reuse its real CSS constants verbatim where they fit. Platform-native
   (deep editability, derivation markers): the constrained vocabulary, where
   theme tokens and geometry utilities carry the brand's measurements. In
   both lanes, steps 1–4 (grammar, ancestor, surfaces, density) carry the
   judgment no mechanism can.
6. **Apply the logo-off test at review.** Look at the rendered section
   between its neighbors and ask: with the logo removed, does this page
   still look like this brand — and does the new section look like it was
   always there? If it resembles a generic component with the brand's
   colors applied, it fails, even if every class is technically valid.
   Rework from step 2.

## Blast radius beyond this page

Some edits reach further than the document in front of you. Say so in your
report when they do:

- **Releasing a repair** changes what future pins of that lineage resolve
  to, on every page assembled after the release.
- **Editing a template** (a page that ABM derivations are minted from)
  changes every FUTURE derivation; already-derived pages are separate
  documents and stay frozen — tell the user which side of that line their
  request falls on, and never silently re-derive existing pages.
- **Minting or releasing library content** (sections, shells, repairs) adds
  to what every later page in this workspace can reuse.

## Respect the human's intent

- Human edits are signal, not noise. If someone tightened a section's
  spacing, do not "normalize" it back while fixing something else.
- Preserve node ids wherever possible — history, selections, and future
  scoped turns hang off them.
- **Structured body text is authored state.** A Body or Small node can
  contain multiple paragraph and list blocks. Before changing its wording,
  read the node's canonical `content` from `view("doc")` and use
  `set_rich_text` with the full typed document, changing only the requested
  inline or block. Never use `set_text` on a structured node: it replaces
  the whole document and can flatten a human-authored list. Heading variants
  stay one paragraph; simplify structured content explicitly before changing
  one into a heading.
- **Personalization markers are load-bearing.** `data-var` spans,
  `data-slot` keys, and `data-slot-when` gates make the page derivable per
  account — treat them like ids. Never strip one while rewording text or
  recomposing a section; a subtree rewrite reproduces every marker the old
  subtree carried unless the brief explicitly removes that personalization.
- If a human edit conflicts with the brand grammar (e.g. pasted classes the
  lint would reject), fix the conflict and say so in the summary.

## Scope discipline — generalize by asking, not by doing

Make the edit you were asked for, and nothing else silently "improved"
along the way. When a scoped fix reveals a page-wide inconsistency (one
card fixed, five siblings share the flaw), fix ONLY what the brief covers,
then offer in the finalize summary: "The other five cards have the same
spacing issue — want me to apply this everywhere?" Never silently mass-edit
beyond the brief. The same goes for flaws you merely notice: report them,
offer, and leave them until asked.

## Ship bar

Same as always, plus two lines: re-render, look at 1440/768/375, no
blocking issues, no invented facts or endpoints; the finalize summary
states exactly what changed (section ids + what kind of edit), what was
deliberately left alone, and **the blast radius** of anything that reaches
beyond this page; and any newly composed section has passed the logo-off
test between its real neighbors.
