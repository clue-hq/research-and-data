---
name: edit-website
description: Repair and evolve a page a human has been editing — diagnose the live tree first, fix with the smallest sufficient tool, and ask before generalizing a local change site-wide.
---

# Edit a Website Someone Else Touched

Between your turns, humans edit the page directly: inspector class changes,
raw-class pastes, inline text edits, undo/redo. The document you receive is
therefore not the one you last wrote. Never assume — diagnose.

## Diagnose before touching anything

1. `view("doc")` — the current tree: section ids, node kinds, class strings.
2. `render_web_preview` + look at all three widths. The pixels tell you what
   the human's edits actually did; the brief tells you what they want now.
3. Identify the delta class: broken layout (bad classes), awkward copy,
   structural damage (emptied/duplicated content), or nothing wrong (the
   brief is a new request, not a repair).

## The repair ladder — smallest sufficient tool

1. **`web_ops`** — one or a few surgical operations
   (`set_node_classes`, `set_text`, `set_node_props`). The default for
   "fix this class", "change this wording", "swap this href". Ops apply
   checked and atomically; a batch that would break the document is
   rejected whole.
2. **`author_web_subtree`** — one section's markup is beyond patching
   (mangled structure, needs recomposition). Keep the section id.
3. **`author_web_page`** — the page as a whole no longer serves the brief.
   Rare; never for a localized complaint.

Climbing higher than needed destroys human edits you were not asked to
touch — a whole-page rewrite after a one-class complaint is a defect, even
if the result looks fine.

Rung choice is a correctness matter, not taste: if the fix is expressible
as one-to-three ops against EXISTING nodes — `set_node_classes`,
`set_text`, `set_node_props` (including rewiring a button's action between
link and command) — then `web_ops` is the ONLY correct rung. Reach for
`author_web_subtree` solely when the section's STRUCTURE must change:
nodes added, removed, or reordered beyond what a couple of ops express. A
subtree rewrite that reproduces the section just to change one attribute
is a defect even when the pixels match — it re-mints node ids that
history, selections, and future scoped turns hang off.

## Respect the human's intent

- Human edits are signal, not noise. If someone tightened a section's
  spacing, do not "normalize" it back while fixing something else.
- Preserve node ids wherever possible — history, selections, and future
  scoped turns hang off them.
- **Personalization markers are load-bearing.** `data-var` spans, `data-slot`
  keys, and `data-slot-when` gates make the page derivable per account —
  treat them like ids. Never strip one while rewording text or recomposing a
  section; a subtree rewrite reproduces every marker the old subtree carried
  unless the brief explicitly removes that personalization.
- If a human edit conflicts with the brand grammar (e.g. pasted classes the
  lint would reject), fix the conflict and say so in the summary.

## Generalize by asking, not by doing

When a scoped fix reveals a page-wide inconsistency (one card fixed, five
siblings share the flaw), fix ONLY what the brief covers, then offer in the
finalize summary: "The other five cards have the same spacing issue — want
me to apply this everywhere?" Never silently mass-edit beyond the brief.

## Ship bar

Same as always: re-render, look at 1440/768/375, no blocking issues, no
invented facts or endpoints, and the finalize summary states exactly what
changed (section ids + what kind of edit) and what was deliberately left
alone.
