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

## The page you are editing

A site is one document with several pages, and every verb in the ladders below
works on the ACTIVE page. `list_pages` names the site's pages, their routes, and
which one is active — read it before you diagnose, so you edit the page the brief
means.

The page verbs are separate, and they are the director's: `add_page` (a new empty
page at its own route), `switch_page` (move the editing focus), `remove_page`
(drop a page and everything on it). No section verb can make a page; "add a
pricing page" is `add_page` then an ordinary build, not a section bolted onto the
home page.

Links between the site's own pages are routes: `<a href="/pricing">`. Publishing
turns the route into the live address.

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
2. **Derive a campaign variant** (`repair_cloned_section(..., css=…)`).
   The band is HEALTHY but its shape can't carry the campaign: a second
   CTA to remove, a logo carousel to hide, a new eyebrow, a different
   emphasis. Do not abandon the clone and do not compose its replacement
   from nothing — `view` the original and remix its FULL markup and CSS,
   changing exactly the content and structure the campaign needs while
   keeping its geometry, type scale, surfaces, and responsive behavior.
   You inherit everything you don't touch, because you started from the
   original's real bytes. The canonical example: the cloned hero with one
   CTA instead of two, the carousel dropped, and a campaign eyebrow —
   every visual property inherited. The variant is lineage-tracked
   (`derived_from`), the original survives untouched, and the variant's
   own texts and links come back as rebindable slots — so one well-made
   variant becomes a reusable, parameterized band for every later page of
   the campaign. Before deriving, read the repair-cloned-sections skill's
   adaptation contract: the visual system is what's preserved, and every
   removed element is a named decision.
3. **Repair it** (`repair_cloned_section`). The band is BROKEN — a defect
   you diagnosed. A repair has two lanes: the RAW lane (pass `css=`)
   remixes the original's own markup and stylesheet — the default when
   the band must keep looking like the seller's site — and is released
   and swapped into the page in one act; the VOCABULARY lane (no `css`)
   recomposes in the constrained vocabulary and births a draft the user
   releases in chat. Before composing a repair in either lane, read the
   repair-cloned-sections skill: it owns the lane choice and the
   faithful-repair discipline (lineage check, the behavior inventory,
   ugly-is-not-wrong, the repair-scope contract, verification against the
   original).
4. **Replace it.** A different released clone fits better
   (`insert_cloned_section` + `remove_node`), or the library lacks the job
   and you compose a new band (see "Composing a new section" below).

**Never retype a healthy clone's markup as ordinary authored content.**
Reauthoring a working cloned band by hand is not an edit — it forges the
seller's work and silently loses the spacing, responsive edge cases, and
interaction hooks the capture preserved. The slots are the first door; a
derived variant is the bigger door (it keeps the original's bytes and
lineage); the repair flow is for defects.

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

## A fresh page in a clone-bearing workspace

An empty document is not an empty library. When the page you're building is
NEW but the workspace holds released cloned sections, assembly comes before
authorship: the campaign-landing-page skill decides WHICH sections the
argument keeps and in what order, the plan-design skill writes that
decision into `workspace/plan.md` before anything mutates, and
`assemble_cloned_sections` then pins the chosen ordered subset in one
atomic act, with slot rebinds for the new words in the same call. Only after the clone skeleton stands do you compose the
bands the library lacks — using this file's "Composing a new section"
sequence — and place them into the gaps. Building a fresh page from scratch
while ten released clones sit unused is the same defect as retyping a
healthy clone: it discards the seller's real, market-tested work.

## Adding to an existing page

**The reuse ladder** — before composing anything, walk down:

1. A released cloned section already does the job → pin it as-is
   (`insert_cloned_section`; on an empty page, `assemble_cloned_sections`
   pins the whole keeper set at once — see the fresh-page section above).
2. A clone has the right bones, wrong words → pin it and rebind slots.
3. A clone has the right bones, wrong shape → derive a campaign variant
   (the clone-editing ladder's rung 2: remix its real bytes, inherit its
   visual system).
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
   (deep inspector editability, attribute-level derivation markers): the
   constrained vocabulary, where theme tokens and geometry utilities carry
   the brand's measurements — the LAST RESORT, chosen only when the raw lane
   and a derived variant genuinely cannot serve, and said so in the plan. In
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
- **Removing a page or changing its route** breaks every link that named the
  old route. Fix those links in the same edit and say which pages you touched.
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
