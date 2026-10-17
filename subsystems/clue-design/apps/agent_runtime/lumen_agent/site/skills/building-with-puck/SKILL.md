---
name: building-with-puck
description: Use when building or changing page.json or shell.json, choosing sections from the catalog, or filling a section's slots and fields.
---

# Building a page

## What a page is

`page.json` is a list of sections, in page order. This example is made up; your brand, clones and
facts are in your workspace.

```json
{
  "root": { "props": { "title": "Northwind for Lakeside Hospital" } },
  "content": [
    { "type": "ClonedSection", "props": { "id": "hero", "fragmentId": "frag_0123456789abcdef",
      "slots": { "headline": "Fill Lakeside's open shifts in hours, not days." },
      "replacements": [{ "find": "Start free trial", "replace": "See the staffing plan" }],
      "links": [] } },
    { "type": "StatsBand", "props": { "id": "proof", "surface": "brandSubtle",
      "heading": "Open shifts filled 40% faster at a 600-bed hospital.",
      "stats": [{ "value": "40%", "label": "faster to fill an open shift" }],
      "source": "Customer study, published by Northwind, 2025." } }
  ]
}
```

Every section has a unique `id` you choose (short, lowercase, for example `hero`, `proof`). The
header and footer are not sections; they live in `shell.json`.

## Reuse first

1. **A clone first.** These are the seller's own sections, exactly as captured. Keep their look
   and change their words.
2. **A brand section** (`StatsBand`, `FeatureSplit`, `ProofCard`, `CtaBand`) when no clone can
   carry the point.
3. **Leave the point out** if neither fits.

## Choosing clones

- `catalog/index.md` lists clones by source page, in page order. The home page's hero usually
  opens the page.
- Choose a clone for its layout (cards, a split, a band of numbers), not for its current words.
  You will change the words.
- Leave out clones that do not help this reader decide: navigation, newsletters, resource
  lists, general testimonials, and whole case-study articles (they make the page long and move
  the point down).

## Filling a clone (`ClonedSection`)

Open the clone's file in `catalog/clones/` first.

- **`slots`:** set only what you change. Leaving a slot out keeps the original exactly.
  - A text slot takes plain text. Keep about the original's length and number of lines.
  - A link slot takes a URL or a `/route`.
  - An image slot takes a file from `brand/brand.md` or an image you generated.
  - `visible: false` hides the whole section.
- **`replacements`:** for visible text with no slot, such as button labels. `find` must be exact
  text from the clone file's "Other visible text".
- **`links`:** for links with no slot. `find` is the exact current href, or `"*"` for every link
  in the section; `replace` is the new href. Use `"*"` for cards that point at the seller's own
  pages.

## Brand sections

Fields and choices are in `catalog/sections.md`.

- Choose `surface` and `headingRole` by name.
- Images come only from `brand/brand.md` or from `generate_image` (see `images-and-logos`).
- Text fields take plain text.

## Rhythm

- Clones keep their own backgrounds. Choose brand-section surfaces so light and dark alternate.
- Use at most one dark brand section (`brand` or `inverse`).
- Do not place two sections that make the same point.

## Buttons and links

- Every button goes to the one destination the brief names for the offer: clone `cta` slots,
  brand-section buttons, and the header button.
- A link to another page of this site is a `/route`.

## The shell (`shell.json`)

```json
{ "header": { "preparedFor": "Lakeside Hospital", "accountLogo": "",
              "ctaLabel": "See the staffing plan", "ctaHref": "https://…" },
  "footer": { "legal": "© 2026 Northwind. Prepared for Lakeside Hospital.",
              "privacyHref": "https://…", "termsHref": "https://…" } }
```

Leave `accountLogo` empty unless the workspace gives you the account's logo file.

## Styling by hand (`_edits`)

A section, and the header and footer in `shell.json`, may carry `_edits`: the marketer's own
styling of single pieces of text, set in the editor. `site.md` lists it under the section as
"styled by hand". It maps a text's name (`heading`, `body`, `stats.0.value`; in a cloned section a
number path like `0.2.1`) to its styling:

```json
"_edits": { "heading": { "color": { "token": "text.heading" }, "fontSize": 48, "fontWeight": 600, "italic": true, "textAlign": "center" } }
```

The properties are:
- `color`: a brand colour by name, or `{ "hex": "#0F59B0", "opacity": 80 }`;
- `fontFamily`: a brand font;
- `fontSize`: 8 to 200;
- `fontWeight`: 100 to 900, a weight the font has;
- `italic` and `underline`: true or false;
- `textAlign`: left, center, right or justify.

Three rules go with it:
- When you rewrite a section, keep its `_edits` unless the request asks for a different look; you
  may change or remove them when it does.
- When you add styling yourself, use the brand's colours and fonts by name first.
- `validate_page` checks the names and values; an entry for text no longer in the section does
  nothing.

## More than one page

The home page is `page.json`. Another page is `pages/<name>.json`, with the same shape, and its
address is `/<name>`: `pages/analysis.json` is the page at `/analysis`. Names use lowercase
letters, digits and dashes.

- Link to another page with its address, for example a button or a clone link set to
  `/analysis`. A link to a page that does not exist is an error.
- Add a page to the header's `nav` when visitors should reach it from every page:
  `"nav": [{ "label": "The analysis", "href": "/analysis" }]`.
- The header, the footer and the one destination for the offer are shared by every page.
- Render each page you changed: `render_page("/analysis")`.

## When validate_page says INVALID

Each line names the section, the field and the fix. For example, it lists the real slots or
says where the usable text is. Fix those lines and validate again. If a change made the page worse, fix it, or bring back an earlier saved version with `restore_version` (`site.md` lists them).
