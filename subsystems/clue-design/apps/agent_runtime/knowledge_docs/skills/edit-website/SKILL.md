---
name: edit-website
description: Use when changing an existing website page, selected element, component, copy, link, layout or requested portion of a saved artifact.
---

# Edit the current artifact, at the requested scope

1. Resolve the request's artifact/version/page/element against fresh session
   context and `list_pages()`. `view("doc")` gives section/count/asset summary,
   not node props or rich text. Use an actually supplied current node snapshot;
   if unavailable, preserve the node and report the missing read capability.
   Switch only to the intended page. An old screenshot is not editable state.
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
5. Report the exact change, checks, remaining gaps and any template/library
   effects. Preserve approval boundaries and truthful draft status. An edit to
   React-rendered WebDoc does not recover the source site's original React code.

Read `campaign-landing-page` only when the audience, offer or argument changes;
`conversion-copywriting` when wording needs authorship; `web-account-personalization`
when target identity/evidence changes. Load `repair-cloned-sections` before a
repair/variant and its actual release effects. Avoid full-generation work for a
small edit; no new source acquisition or imagery spend without a need in scope.
