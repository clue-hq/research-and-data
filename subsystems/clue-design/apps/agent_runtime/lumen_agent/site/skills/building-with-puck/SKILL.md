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
header and footer are sections too. The site has one of each, kept in `shell.json` and drawn on
every page (see The header and footer).

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
  - A text slot takes text, which may be rich text (below). Keep about the original's length and
    number of lines.
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
- Text fields take plain text, except the ones `catalog/sections.md` marks as rich text, which
  take rich text (below).

## Rhythm

- Clones keep their own backgrounds. Choose brand-section surfaces so light and dark alternate.
- Use at most one dark brand section (`brand` or `inverse`).
- Do not place two sections that make the same point.

## Buttons and links

- Every button goes to the one destination the brief names for the offer: clone `cta` slots,
  brand-section buttons, and the header button.
- A link to another page of this site is a `/route`.
- To make a button open in a new tab, set `buttonNewTab: true` on a feature split or
  call-to-action band, or `ctaNewTab: true` in the header. In a cloned section, list the button's
  name in `newTab`, as for its links.
- A button's words may hold rich text, but never a link: bold, italic and styled words only, no
  `<a>`.

## The header and footer (`shell.json`)

`shell.json` holds the site's one header and one footer. Each is a section, written like a section on
a page, with the id `header` or `footer`:

```json
{ "header": { "type": "ClonedSection", "props": { "id": "header", "fragmentId": "frag_…",
      "slots": { "account_line": "Built for Acme Health's care team", "account_logo": "/asset-store/…" },
      "replacements": [], "links": [] } },
  "footer": { "type": "ClonedSection", "props": { "id": "footer", "fragmentId": "frag_…", "slots": {},
      "replacements": [], "links": [] } } }
```

**Start from the brand's templates.** `catalog/index.md` lists them first, under "Header and footer
templates". They are made from the seller's own header and footer, so they look like the seller's
site, and they carry what a page for an account needs: the seller's logo, the account's logo, a line
for the account and one button.

- **Which header**: there are two. Use "Header template, one page" for a site with one page, which is
  the usual page for an account: the account line sits in the centre. Use "Header template, with page
  menu" only when the site has more than one page: the menu sits in the centre.
- **The account line** (`account_line`): write the account's full name after "Prepared for", for
  example "Prepared for Acme Health". Don't shorten it to fit a phone: the header shortens long lines
  on small screens by itself. On a site for several accounts, write a line for the group, or hide it.
- **The account's logo** (`account_logo`): a file from "The account's logo" in brand/brand.md. When
  there is none, or the site is for several accounts, set `account_shown` to `false`: that hides the
  logo and the thin line before it.
- **The button**: its link (`cta_href`) and its words. Point it at the one destination for the offer.
- **The menu** (the header with page menu) lists the site's pages by itself, in order, and grows when
  you add a page. Rename an item with `menuLabels`, by page name (`_home` is the home page):
  `"menuLabels": { "_home": "Overview", "analysis": "The analysis" }`. A site with one page shows no
  page links.
- **`menuExtra`** adds links after the pages: `[{ "label": "Pricing", "href": "https://…" }]`. Use it
  only on a site made for several accounts or a whole segment, when one of the seller's own pages
  helps the reader. Never on a site for one account: those links lead the reader away from a page
  written for them.
- Any other word in a template is a slot like a clone's; change it there when it reads oddly for this
  site.

**When the brand has no template**, use the plain header and footer:

```json
{ "header": { "type": "SiteHeader", "props": { "id": "header", "accountLine": "Built for Acme Health's care team",
      "accountLogo": "", "ctaLabel": "See the staffing plan", "ctaHref": "https://…" } },
  "footer": { "type": "SiteFooter", "props": { "id": "footer", "legal": "© 2026 Example Co.",
      "privacyHref": "https://…", "termsHref": "https://…" } } }
```

Their link words are `privacyLabel` and `termsLabel` (empty shows "Privacy policy" and "Terms"), and
`logo` replaces the seller's logo when the person gives you another file. `menuLabels` and `menuExtra`
work here too.

**Your own**: when neither fits, you may write the header or footer as a section of your own (the
writing-a-section skill) and use it as the header's or footer's `type`.

**Staying at the top, and over the first section.** The header can stay at the top while the page
scrolls, and can sit over the first section (the first section then starts under it). Set them on the
header's own box: `"_edits": { "root": { "sticky": true, "overlay": true } }`. Over a photo, give the
header's own box a fill with some opacity so its words stay readable, and give the first section more
top padding if its words end up under the header.

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
- `fontFamily`: a brand font, or one of brand/brand.md's "Other fonts", with a weight that font has;
- `fontSize`: 8 to 200;
- `fontWeight`: 100 to 900, a weight the font has;
- `italic` and `underline`: true or false;
- `textAlign`: left, center, right or justify.

Words styled inside rich text have their own name, the text's name plus `~` and a number
(`heading~1`).

A button's own name (`button` in a feature split or call-to-action band, `cta` for the header's
button, the `el` you gave `kit.Button`, a number path in a cloned section) also takes:
- `fill` and `borderColor`: a colour, as for `color`;
- `borderWidth`: 0 to 200;
- `radius`: 0 to 200, `"pill"`, or four corners `[top-left, top-right, bottom-right, bottom-left]`;
- `padding`: 0 to 200, or `{ "y": 12, "x": 22 }`;
- `width`: `"fit"` (as wide as its words), `"fill"` (the full width) or 1 to 2000.

Its words are named `<button>.label` (`button.label`, `cta.label`) and take the text properties. A
fill or stroke set this way also holds when the button is hovered.

A box's name also takes the button's properties above (fill, stroke, corners, padding, width).
Boxes are: in our sections `root` (the section's own box) and `root.inner` (the box holding its
padding), `card`, `row`, `column`, `lead`, `stats` and each `stats.<n>`; the `el` you gave
`kit.Card` or a `data-clue-el` you wrote; any number path in a cloned section (a header or footer
template too); in the plain header `brand`, `actions`, `menu` and `ctaArea`, in the plain footer
`links`. A box also takes:
- `gap`: 0 to 200, the space between its children (rows and grids only);
- `contentAlign`: `{ "along": "row", "to": "center" }`, how its contents line up across it.
  `along` says how the box lays them out: `row` (side by side), `stack` (one under another),
  `grid`, or `text` (plain text); `to` is `start`, `center` or `end`.

Two more, for cloned sections and the header and footer only:
- `order`: the order of a box's children, as the list of their names
  (`"0.2": { "order": ["0.2.1", "0.2.0"] }`). A child left out keeps its place. In our sections and
  yours, items move by reordering their list prop instead.
- `hidden`: `true` hides a header or footer part: the seller's logo (`logo`), the account's logo
  (`accountLogo`), the divider (`divider`), a menu item (`menu.analysis` for a page, `menu._home` for
  the home page, `menu._0` for the first `menuExtra` link), the button (`ctaArea`), a footer link
  (`privacy`, `terms`), or any number path in a template. It is refused on a page section; rewrite
  the section instead.

An image's name (`image` in a feature split; `logo` and `accountLogo` in the header, `logo` in the
footer; the `el` you gave `kit.Image`; a number path in a cloned section) takes the stroke and corner
properties above (`borderColor`, `borderWidth`, `radius`) and:
- `imageFit`: `"fill"` (the picture fills its box and may be cropped) or `"fit"` (the whole picture
  shows inside its box).

Three rules go with it:
- When you rewrite a section, keep its `_edits` unless the request asks for a different look; you
  may change or remove them when it does.
- When you add styling yourself, use the brand's colours and fonts by name first.
- `validate_page` checks the names and values; an entry for text no longer in the section does
  nothing.

## Alt text

Alt text says what a picture shows, for people who cannot see it: plain text, at most 300
characters, no line breaks; empty for a picture that is only decoration. It is written in
`imageAlt` (feature split), `logoAlt` and `accountLogoAlt` (header), `logoAlt` (footer), and for a
cloned section's pictures in its `alts`, by the picture's name (`"alts": { "0.2.1": "Hotel lobby" }`).

## Rich text

Some text holds a little HTML, so single words can be bold, linked or styled: our sections' fields
that `catalog/sections.md` marks as rich text, your sections' marked props, and a cloned section's
text slots. Only these tags:
- `<strong>`, `<em>`, `<u>` and `<s>` for bold, italic, underlined and struck words;
- `<br>` for a new line (one paragraph only, no lists);
- `<a href="…">` for a link to a page of this site (`/analysis`), an `https://` address, a
  `#section` or `mailto:`. Add `data-new-tab` for a link that opens in a new tab;
- `<span data-s="heading~1">` for words styled by hand. The name is the text's own name plus `~`
  and a number, and its look is that name's entry in `_edits`.

No other tag or attribute, and no `style`. Write `&amp;`, `&lt;` and `&gt;` for &, < and >.
`site.md` shows rich text as its words, with what is bold, linked or styled named in brackets.
When you rewrite text, keep its links and styled words unless the request changes them.

## More than one page

The home page is `page.json`. Another page is `pages/<name>.json`, with the same shape, and its
address is `/<name>`: `pages/analysis.json` is the page at `/analysis`. Names use lowercase
letters, digits and dashes.

- Link to another page with its address, for example a button or a clone link set to
  `/analysis`. A link to a page that does not exist is an error.
- A page you add joins the header's menu by itself; rename it there with `menuLabels`.
- The header, the footer and the one destination for the offer are shared by every page.
- For a link that opens in a new tab, set `linkNewTab: true` on a proof card, `"newTab": true` on a
  `menuExtra` link, or `privacyNewTab` / `termsNewTab` in the footer. In a cloned section, list the link's
  text name in `newTab`, for example `"newTab": ["0.2"]`.
- Render each page you changed: `render_page("/analysis")`.

## When validate_page says INVALID

Each line names the section, the field and the fix. For example, it lists the real slots or
says where the usable text is. Fix those lines and validate again. If a change made the page worse, fix it, or bring back an earlier saved version with `restore_version` (`site.md` lists them).
