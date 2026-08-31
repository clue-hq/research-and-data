Recorded your three rulings. Both inventories are control-level, so I can give you the complete web-editor comparison right now — every parity, every disparity, numbered so you can rule item by item. Statuses: **PARITY** (maps cleanly, just wiring), **MAPPABLE** (works with a value translation), **NO BACKING** (dummy control has nothing real behind it), **ENGINE GAP** (real support requires adding a facet/field), **NO SLOT** (real capability the dummy UI has no control for).

## A. Already ruled by you (restated for completeness)

- **R1. Font family select** — NO BACKING (no font-family facet; theme owns fonts) → *ruled: keep visible, stays dummy.*
- **R2. Colors** — real facets take theme tokens, dummy offers hex + custom picker → *ruled: theme tokens only.* (Concretely: the dummy's ColorControl already has a Theme mode with 6 tokens — we bind that; the Custom/hex tab --> my answer -- it stays dummy for now.)
- **R3. Padding** — real is `px-`/`py-` axis facets; dummy is per-side L/T/R/B → *ruled: X/Y only.* (Sub-call: collapse the four inputs to two, or keep four boxes where L/R mirror each other? Fewer boxes is the honest UI.) --> my call collapse the 4 boxes to 2.

## B. Dummy controls → real backing, schema by schema

**Canvas (page root)**
1. Background → Color: **MAPPABLE** — `bg-{token}` facet on the page root, tokens per R2.
2. Color opacity input: **NO BACKING** (already inert in dummy; no opacity facet). Keep-inert / hide? --> keep inert. dont hide for now.

**Text**
3. "Link to" (URL + new-tab): **NO BACKING** — a web text *node* has no href. (Links on text exist only as rich-text range links via the canvas toolbar.) Hide, or leave inert? --> I get that the link to was a web text node that has no href, right? Only the rich text had the ability to get hyperlinked. In that scenario, whenever a text node or a rich text is hyperlinked, or a rich text format is selected, only in that case will you have to display the Link2 section in the UI. When it is not selected, it will be hidden, something like that.Only when you select a rich text range, may I make it very clear: only when a rich text range is selected will the link to be displayed and its functionality will be available. 
4. Typography → Color: **MAPPABLE** — `text-{token}` facet (tokens per R2).
5. Size select (12…32): **MAPPABLE with translation** — real is the Tailwind ramp. Clean map: 12→xs, 14→sm, 16→base, 18→lg, 20→xl, 24→2xl. Two orphans: **13 (no ramp value)** and **32 (nearest is 3xl=30)**. My rec: drop 13 from the options, map 32→3xl. Your call. --> drop for now. 
6. Weight select: **PARITY** — Regular/Medium/Semi Bold/Bold → normal/medium/semibold/bold, exact.
7. Horizontal alignment (L/C/R): **PARITY** — `textAlign` facet (real also has justify; no dummy button — fine).
8. Vertical alignment (top/middle/bottom): **NO BACKING** — text flows in the document; no vertical alignment exists for web text. Hide? --> Hide it.
9. Stroke → Color: already a disabled "None" in the dummy; Width input: **NO BACKING** (no border facets). Hide section, or leave as-is (it's already 90% inert)? --> leave as is.
10. *Note:* real also has **line-spacing** and **text style/variant** (h1–h4/body/etc.) selects, and **B/I/U/S** toggles — see items 24–26.

**Image**
11. "Link to": **PARITY** — real image has href + new-tab props. --> It's linked to four image select. When an image is selected, link to in that case make it appear and functional, okay. Not necessary that all the images will have links, but the user should be able to avail the option of adding a link to an image. 
12. Replace image: **MAPPABLE** — dummy is a direct file upload; real flow is upload-to-asset-store then a replace operation. Wiring is straightforward; dummy's direct-upload UX is preserved. 
13. Mode select: **MAPPABLE minus one** — Fit→`contain`, Fill→`cover`, Stretch→`fill`; **Tile has no real equivalent.** Drop Tile from options? --> yes drop the tile option
14. Shape → Radius (all + 4 corners): **ENGINE GAP** — no radius facet; today only raw CSS classes. Options: (a) add a radius facet to the translator (bounded, my rec), (b) hide the section. --> add the radius facet to the translator for now.

**Button**
15. "Link to": **PARITY** (href + new-tab).
16. Style select (Primary/Secondary/Transparent/Critical): **MAPPABLE minus one** — real variants are primary/secondary/outline/ghost/link. Primary→primary, Secondary→secondary, Transparent→ghost; **Critical doesn't exist** in the engine. Drop Critical, or add a variant engine-side?  --> drop
17. Background/Text color token buttons: **MAPPABLE** — real `bg-`/`text-` token facets; we give the dummy's token buttons a real token list popover (the pattern already exists in its ColorControl Theme tab).

**Icon** — the weakest schema
18. Icon select / color tokens / size / stroke: **NO BACKING across the board** — the engine has an icon *kind* but zero icon controls (name hardcoded at insert; styling via raw classes only). Options: (a) whole schema stays inert (icons are agent-authored), (b) hide the icon-specific sections and show only Layout/padding, (c) small engine work to add icon-name + size facets. My rec: (a) for now. --> go with only (b) for now.

**Container**
19. Style text/bg tokens: **MAPPABLE** (same as 17). 
20. Alignment segmented Flex/Grid/Hide: **MAPPABLE** — display facet (flex/grid/hidden; real also has block/inline-flex with no dummy slot — fine).
21. *Reverse gap:* the real container also has **direction, h/v alignment, wrap, grid columns, gap, and a Click-action link** — the dummy gives direction/gap/wrap only to *section*. Expose any of these on container (UI change → your call), or leave agent-only? Ah. --> make a special note for things that are not there in frontend, we will work on this. 

**Section**
22. Direction / Gap / Wrap: **PARITY** — exact facets exist (gap is an enumerated step scale 0–24 vs the dummy's free input; I'd coerce typed values to the nearest step).
23. "Link to" on section: **NO BACKING** — real sections deliberately have no link (only containers do). Hide? --> hide.

**Canvas-level text editing (not inspector, but part of the web editor)**
24. Real **rich-text toolbar** (bold/italic/underline/strike on ranges, lists, indent, range links, highlight, personalization variables, clear formatting) appears on double-click today. The dummy has no equivalent — but this is canvas UI, not inspector chrome. My rec: **keep it as-is** (it doesn't violate the inspector minimalism; the marketer needs *some* way to edit text). Your call: keep / restyle later / drop.
25. Real **text style/variant** select (display/h1/h2/h3/h4/body/small/overline): NO SLOT in dummy typography. This is semantically important (headings vs body). Expose (UI change) or agent-only? --> add them
26. Real **line-spacing** select: NO SLOT. Agent-only, or add? --> add them

## C. Real inspector capabilities with **no dummy slot** — keep-invisible / defer / drop

These exist and work today; per your minimalism rule none get UI unless you say so. "Keep-invisible" = the capability survives (agent can use it; data round-trips safely); "drop" = we accept losing it in the new surface.

27. **Slot key + personalization** (per-node slot marking, "show only when bound", per-account batch generation): keep-invisible (agent-managed) is my strong rec — it's the ABM personalization spine.  --> keep invisible for now.
28. **Raw CSS-classes escape hatch**: no dummy slot. Keep-invisible (agent uses it heavily) — effectively automatic; confirm. --> keep invisible
29. **Move up/down, duplicate, delete** node actions: dummy inspector has none (deletion presumably via canvas/keyboard). Decide: keyboard-only, or later canvas context menu? --> keyboard-only for now.
30. **Margin X/Y controls**: no dummy slot (dummy has padding only). Agent-only? --> agent only for now.
31. **Computed-layout read-only card** (real size/position/constraints): drop from UI (it's a dev tool) — confirm. --> drop for now
32. **Embed nodes** (URL/snippet, Calendly): no dummy schema. When an embed is selected, show nothing? A minimal fallback? Rec: selection shows Layout-only for unknown kinds. --> for now show only layout. make note as to do for this thing
33. **Interactive components** (dialog/accordion/marquee/carousel/tabs/nav-menu prop cards): no dummy schema. Same fallback question as 32; the components themselves keep working — only their prop-tuning becomes agent-only. --> for now show only layout. make note as to do for this thing
34. **Custom components**: render works untouched; the **schema-driven props form** is portable and clean. Include it when a custom component is selected (my rec — it's exactly the "simple controls" your persona can handle), or agent-only? --> Include it when a custom component is selected (my rec — it's exactly the "simple controls" your persona can handle)
35. **Background-image + scrim system on section/container** (asset, fit, position, scrim color/opacity): no dummy slot. Keep-invisible/agent-only, or is this important enough to marketers to deserve a future UI slot? (No UI now either way.). --> keep agent only and invisible to user for now.
36. **Button dialog actions** (open/close dialog, target picker): keep-invisible — inspector edits only the link mode; agent wires dialogs. Confirm. -> confirm
37. **Alt text on images**: real control exists, dummy has none. Accessibility matters for published pages — expose (one input, small UI addition → your explicit call per the minimalism rule) or agent-only? --> agent-only for now.
38. **`tag`/`anchor_id` on sections**: never had UI; must be *preserved* through our writes (silent data-integrity requirement — I'll guarantee it, no decision needed, listed for transparency).

## D. Cross-cutting

39. **Lock toggle** (dummy header): **NO BACKING** on web nodes (only scene nodes have `locked`). Inert or hidden?
40. **Visibility eye** (dummy header): **MAPPABLE, one option** — could map to the display facet's `hidden` value (a real hide/show). Wire it, or keep inert? -> wire it.
41. **Layer tree**: dummy shows authored fixtures; real doc gives the true node hierarchy. **PARITY** — will be built from the real document (names, kinds, nesting). One choice: the dummy caps nesting display at depth 1; real pages nest deeper. Flatten beyond depth 1, or allow deeper indentation (minor UI behavior call)? --> cap it at 1 for now.
42. **409/422 save-failure surfacing**: the four failure-feedback points from before — deferred to Phase 4's one-question decision as agreed. No call needed now.

---

That's the complete list — 42 items, nothing omitted from either inventory. Go through them at whatever pace suits you ("5: drop 13 and map 32→3xl; 8: hide; 14a…" works fine). Once you've ruled, I'll freeze the web-editor mapping table with your decisions and that becomes the Phase-3/4/5 contract for the website-editor flows.
