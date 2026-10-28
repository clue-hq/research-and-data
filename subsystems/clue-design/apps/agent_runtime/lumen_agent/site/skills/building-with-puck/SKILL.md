---
name: building-with-puck
description: "Read when you build or change page.json or shell.json: the order for choosing sections (clone, rebuilt clone, brand section, your own), filling a clone's slots, brand sections, buttons and links, the header and footer, styling by hand, alt text, rich text and pages."
---

# Building a page

## What a page is

`page.json` is a list of sections, in page order. This example is made up (an imaginary seller,
Northwind, whose software approves supplier invoices, and an imaginary account, Lakeside Group) to show
the format only; your brand, clones and facts are in your workspace.

```json
{
  "root": { "props": { "title": "Northwind for Lakeside Group" } },
  "content": [
    { "type": "ClonedSection", "props": { "id": "hero", "fragmentId": "frag_0123456789abcdef",
      "slots": { "headline": "Get Lakeside's supplier invoices approved in days, not weeks." },
      "replacements": [{ "find": "Start free trial", "replace": "See the approval plan" }],
      "links": [] } },
    { "type": "StatsBand", "props": { "id": "proof", "surface": "brandSubtle",
      "heading": "Invoices approved three times faster at a 40-store retailer.",
      "stats": [{ "value": "3x", "label": "faster invoice approval" }],
      "source": "Customer study, published by Northwind, 2025." } }
  ]
}
```

Every section has a unique `id` you choose (short, lowercase, for example `hero`, `proof`). The
header and footer are sections too. The site has one of each, kept in `shell.json` and drawn on
every page (see The header and footer).

## Reuse first

Choose each section in this order, and take the first that can carry what the section must explain:

1. **A clone, as it is.** These are the seller's own sections, exactly as captured. Keep their look
   and change their words.
2. **A clone rebuilt as a component**, when the seller's section is right for the page but its slots
   cannot carry what the page needs (more words or items, a changed layout), or its motion must be
   carried into an editable section: the rebuilding-a-section skill.
3. **A brand section** (`StatsBand`, `FeatureSplit`, `ProofCard`, `CtaBand`), when neither can carry
   it.
4. **A section of your own**, when none of these can: the writing-a-section skill.

If none of the four fits, leave the point out and say why in `plan.md`. Never cut material the
decision needs just because a slot is short; move down this list instead.

## Choosing clones

- `catalog/index.md` lists clones by source page, in page order. Which page's hero opens the page:
  `page-design` ("Which hero").
- Choose a clone for its layout (cards, a split, a band of numbers), not for its current words.
  You will change the words.
- Leave out clones that do not help this reader decide (`planning-a-page`, question 8).

## Filling a clone (`ClonedSection`)

Open the clone's file in `catalog/clones/` first.

- **`slots`:** set only what you change. Leaving a slot out keeps the original exactly.
  - A text slot takes text, which may be rich text (below). How to rewrite it: `page-copy`
    ("Rewriting a clone's words").
  - A link slot takes a URL or a `/route`.
  - An image slot takes an image file from the page's image list (`imagery-and-media`, "The images a
    page may use").
  - `visible: false` hides the whole section.
- **`replacements`:** for visible text with no slot, such as button labels. `find` must be exact
  text from the clone file's "Other visible text".
- **`links`:** for links with no slot. `find` is the exact current href, or `"*"` for every link
  in the section; `replace` is the new href. Use `"*"` for cards that point at the seller's own
  pages.
- **Every button the clone brings is decided on purpose**: keep it with its real purpose, change its
  words and its destination together, or remove it. A button's words never promise what its
  destination does not deliver.

## Brand sections

Fields and choices are in `catalog/sections.md`.

- Choose `surface` and `headingRole` by name.
- Images come from the page's image list (`imagery-and-media`, "The images a page may use").
- Text fields take plain text, except the ones `catalog/sections.md` marks as rich text, which
  take rich text (below).

## Surfaces and rhythm

Clones keep their own backgrounds. Choose the surfaces of brand sections and your own sections from
the seller's cadence: `page-design`.

## Buttons and links

- Every button for the page's primary action (`planning-a-page`, question 5) goes to the same
  destination: clone `cta` slots, brand-section buttons, and the header button. Their words:
  `page-copy` ("Buttons and the offer").
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
      "slots": { "account_line": "Prepared for Acme Logistics", "account_logo": "/asset-store/…" },
      "replacements": [], "links": [] } },
  "footer": { "type": "ClonedSection", "props": { "id": "footer", "fragmentId": "frag_…", "slots": {},
      "replacements": [], "links": [] } } }
```

Write the header and footer you chose, and why, in `plan.md`. This part says which to use and how to
build them.

**The header: the seller's own, by page kind.** The header looks and behaves like the header on the
seller's own site: its layout, where the logo, links and button sit, and how it sits on the page
(floating at the top centre, full width, over the hero). The seller's header is a clone in
`catalog/index.md` (role `nav`, usually the first section of the home page).

- **A page for a whole audience: the seller's header, cloned as it is.** Put it in `shell.json` as the
  header's `ClonedSection`. Point its button at the page's primary action; its menu keeps its links to
  the seller's real pages.
- **A page for one account, one person or a few named accounts: the seller's header, trimmed.**
  Rebuild it (the rebuilding-a-section skill) keeping its look and layout: remove the dropdown menus
  and other links, keep the seller's logo and one button to the page's primary action, and add a short
  line where the seller's layout has room for one, usually where the menu was ("Prepared for Acme
  Logistics"; for a few accounts, a line for the group, or none). On a page for one account or one
  person, the account's logo sits beside the seller's. Then use the component as the header's `type`.
- **An event or a product campaign: the seller's header, trimmed** the same way to its logo and one
  button, with no line.
- **When the seller has no header clone**, use the brand's header templates (below), then the plain
  header (below), then a header of your own (below).

The line follows the relationship words in `page-copy` ("Talking about the prospect"): "Prepared for",
"A proposal for", never "partner" or "working together".

**Never a sign-in button.** A visitor to a landing page has no account to sign in to. Even in a header
cloned as it is, replace a "Sign in" or "Log in" link or button with the page's primary action: change
its words with `replacements` and its link with `links`, so it reads and goes like the page's other
buttons. In a rebuilt header, leave sign-in out.

**The brand's header templates.** `catalog/index.md` lists them first, under "Header and footer
templates".

- **Which template**: there are two. Use "Header template, one page" for a site with one page: the line
  sits in the centre. Use "Header template, with page menu" only when the site has more than one page:
  the menu sits in the centre.
- **The line** (`account_line`):
  - on a page for one account or one person, write the account's full name after "Prepared for", for
    example "Prepared for Acme Logistics". Don't shorten it to fit a phone: the header shortens long
    lines on small screens by itself;
  - on a page for a few named accounts, write a line for the group ("Prepared for regional retail
    chains");
  - on a page for an audience, an event or a product campaign, there is no account. A template cannot
    hide its line (left empty, it shows "Prepared for you"), so prefer the seller's own header there,
    as it is or rebuilt. If you use a template, write a short line for the page's audience, event or
    offer ("For freight brokers"), never an account's name.
- **The account's logo** (`account_logo`): a file from "The account's logo" in brand/brand.md, only on
  a page for one account or one person. Otherwise, or when there is none, set `account_shown` to
  `false`: that hides the logo and the thin line before it.
- **The button**: its link (`cta_href`) and its words. Point it at the page's primary action.
- **The menu** (the header with page menu) lists the site's pages by itself, in order, and grows when
  you add a page. Rename an item with `menuLabels`, by page name (`_home` is the home page):
  `"menuLabels": { "_home": "Overview", "analysis": "The analysis" }`. A site with one page shows no
  page links.
- **`menuExtra`** adds links after the pages: `[{ "label": "Pricing", "href": "https://…" }]`. Use it
  only on a page for a whole audience, when one of the seller's own pages helps the reader decide. Every
  other kind of page has a trimmed header with no links: on a page for one account, one person or a
  few named accounts they lead the reader away from a page written for them, and an event's or a
  product campaign's links go in the page.
- Any other word in a template is a slot like a clone's; change it there when it reads oddly for this
  site.

**The footer.** Which footer depends on the kind of page:
- **A page for a whole audience: the seller's own footer, as it is.** It is a clone in
  `catalog/index.md` (role `footer`, usually the last section of the home page). Put it in
  `shell.json` as the footer's `ClonedSection` and leave it as captured. If the seller has no footer
  clone, use the plain footer.
- **Every other page** (one account, one person, a few named accounts, an event, a product campaign):
  **the plain footer** (`SiteFooter`): the seller's logo, the legal line, and the privacy and terms
  links in one row, in the brand's styles. Fill in the legal line and the two links.
- The person's explicit request wins, for example a richer footer or one of your own.

**When the brand has no header template**, use the plain header. On a page with no account, hide
its line and the divider with `_edits` (`"accountLine": { "hidden": true }`, `"divider": { "hidden": true }`)
and leave `accountLogo` empty:

```json
{ "header": { "type": "SiteHeader", "props": { "id": "header", "accountLine": "Prepared for Acme Logistics",
      "accountLogo": "", "ctaLabel": "See the approval plan", "ctaHref": "https://…" } },
  "footer": { "type": "SiteFooter", "props": { "id": "footer", "legal": "© 2026 Example Co.",
      "privacyHref": "https://…", "termsHref": "https://…" } } }
```

Their link words are `privacyLabel` and `termsLabel` (empty shows "Privacy policy" and "Terms"), and
`logo` replaces the seller's logo when the person gives you another file. `menuLabels` and `menuExtra`
work here too.

**Your own**: when nothing above fits, you may write the header or footer as a section of your own
(the writing-a-section skill) and use it as the header's or footer's `type`.

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
- The header, the footer and the page's primary action are shared by every page.
- For a link that opens in a new tab, set `linkNewTab: true` on a proof card, `"newTab": true` on a
  `menuExtra` link, or `privacyNewTab` / `termsNewTab` in the footer. In a cloned section, list the link's
  text name in `newTab`, for example `"newTab": ["0.2"]`.
- Render each page you changed: `render_page("/analysis")`.

## When validate_page says INVALID

Each line names the section, the field and the fix. For example, it lists the real slots or
says where the usable text is. Fix those lines and validate again. If a change made the page worse, fix it, or bring back an earlier saved version with `restore_version` (`site.md` lists them).
