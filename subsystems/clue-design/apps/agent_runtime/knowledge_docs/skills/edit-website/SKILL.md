---
name: edit-website
description: Use when changing an existing website page, selected element, component, copy, link, layout or requested portion of a saved artifact.
---

# Edit the current artifact, at the requested scope

Apply the [source and format contract](../create-website/references/source-format-contract.md).
Retain the selected component's structure and format through copy/typography
edits; use an exact-text variant for unbound copy before changing markup.

1. Resolve the request's artifact/version/page/element against fresh session
   context and `list_pages()`. Switch only to the intended page. `view("doc")`
   gives the section/count/asset summary; `view("node:<id>")` reads one exact
   active-page node with current props/rich text and parent/child IDs. Require
   `complete: true` before a full-payload edit. This is turn-local state, not a
   checked persisted revision. On refusal, preserve the node and report the gap.
   Match the reported symptom to that section in the current preview at the failing
   width before editing; a remembered or recently edited product panel may be a
   different section. Record its visible neighbors so the after-check targets the same area.
   In the existing plan, name the current pin/version, intended change and keeper
   properties: fonts/hierarchy, background and product asset, crop/radius/layers,
   and interaction states. Preserve unaffected pins; a stronger source band is
   not expendable because another band needs better copy.
2. Read [scoped editing](references/scoped-editing.md), using the relevant ladder:
   `web_ops` for a few existing-node changes; clone slots for supported content;
   a campaign variant for healthy cloned structure; repair for a real defect;
   `author_web_subtree` only for needed section recomposition. A localized request
   never justifies `author_web_page`, which drops standing pins.
3. Send complete replacement payloads and preserve unaffected fields. Use
   `set_rich_text` for structured body content, retaining lists/variables/marks.
   For `custom_component`, load `custom-components` and update/repin the intended
   immutable version; do not rewrite its enclosing page.
4. Re-render after changes and inspect affected content, neighboring layout and
   relevant states at returned widths. Load `review-website`; keep the judgment
   scoped unless the change affects the larger page. Reuse unchanged current
   evidence. Report unrelated findings without silently expanding the edit.
   Compare the keeper properties before/after at the affected widths. A changed
   background, missing phone product UI or weaker type hierarchy fails the repair
   even if its original symptom disappeared. Batch diagnosed fixes; do not spend
   another authoring round on unchanged evidence or speculative polish.
5. Report the exact change, checks, remaining gaps and any template/library
   effects. Preserve approval boundaries and truthful draft status. An edit to
   React-rendered WebDoc does not recover the source site's original React code.

Read `campaign-landing-page` only when the audience, offer or argument changes;
`conversion-copywriting` when wording needs authorship; `web-account-personalization`
when target identity/evidence changes. Load `repair-cloned-sections` before a
repair/variant and its actual release effects. Avoid full-generation work for a
small edit; no new source acquisition or imagery spend without a need in scope.
