# Site headers and footers as editable templates (plan 6) — design

Status: written 2026-10-18 from the founder conversation in the trenton session (branch
`site/publish-durability`); builder-checked and the founder's four answers folded in; awaiting the
founder's review. This is **plan 6** of the site element
inspector (`docs/superpowers/specs/2026-10-17-site-element-inspector-design.md` §7.2, §7.3): that
document's §7 stays the source of truth for status and scope.

## 1. Why

A microsite's header and footer are fixed code today (`apps/frontend/packages/site-kit/src/shell.tsx`).
The site stores only a few values for them (`ShellSchema`, `site-kit/src/schemas.ts`): the header's
account name, account logo, page links and one button; the footer's legal line and two link
addresses. So the agent refused when the founder asked it for a header layout change. A marketer can
restyle, reorder and hide the parts plans 1–5 keyed, but cannot change the words "Prepared for",
"Privacy policy" or "Terms", cannot style single words, and cannot change the layout.

The founder, during plan 1's live check: "i dont want a hardcoded header version… standardised
headers could be made and kept but should also be acceptable of change from human and agent both
here, just like the rest of the site." And in this conversation: the header must look like the seller's
own site, and the best starting point is the seller's real header.

**Success:** on Garner and Conduit, each microsite's header and footer read as the seller's own (their
layout, fonts, colours, buttons and spacing) while carrying the ABM parts. The agent can pick one,
change it, or write a new one, and the marketer can change any word, style and logo in place, make the
header sit see-through over the hero and stay at the top while scrolling. All of it is saved, undone and
published like any section.

## 2. What "ABM-focused" means (founder)

Today's header and footer already are what ABM-focused means: the seller's logo beside the account's
logo, a line addressing the account, links to the microsite's own pages, and one call to action; a
footer with the seller's mark, a legal line and legal links. What changes: they take the seller's own
look instead of our fixed one, and every word and format is editable.

- **The account line is creative**, not the fixed "Prepared for <account>". The agent writes what fits
  ("Built for Carmel Clay's benefits team"); the marketer can retype it.
- **The seller's own menu links** (Pricing, Careers, Blog) never appear on a 1:1 page (a site asked for
  one account): they are escape routes away from a page written for that company. On a one-to-few or
  one-to-many page they may stay. This is the agent's judgement, steered by its skill — no code rule,
  no recorded campaign type (founder: "we can leave that to agent's understanding").

## 3. Goals, non-goals, anti-goals

Goals
- One shared header and one shared footer for the whole microsite (founder: "primarily a shared header
  for all the pages").
- At brand extraction, one header template and one footer template per brand kit, derived from the
  seller's real header and footer and made ABM-focused (§2).
- The agent starts a site from those templates, may change them, or may write a fresh header and footer
  of its own when the site needs one.
- The marketer edits the header and footer in place exactly like any section: every word (word-level
  styling and links included), every part's style, the logos (replaced from the asset library — the
  seller's logo too), the order and visibility of parts, the header's opacity over the hero, and
  whether it stays at the top while scrolling.
- Everything plans 1–5 built works in the header and footer, because they are sections.

Non-goals
- A different header per page (nothing should rule it out later).
- A library of generic header designs to choose from.
- Mega-menus, mobile drawer menus beyond what the seller's own header does, or animated headers.

Anti-goals (a failure even if it technically works)
- A header that looks generic with the seller's logo dropped in — "AI slop". Templates and agent-written
  headers must be built from the brand kit's own tokens and the seller's measured components (buttons,
  links, type), as our sections are.
- Arbitrary CSS or script reaching the published page outside the existing checks: an agent-written
  header goes through the same check and hardened render as an agent section.
- A header change that silently breaks pages: the header is drawn on every page, so a refused or broken
  header must refuse the save, never publish a broken page.
- The seller's escape-route menu on a 1:1 page as the default.

## 4. How it works (decided parts; my calls are marked)

### 4.1 Where the header and footer live

*My call:* the site keeps its one header and one footer in `site.shell`, but each becomes a **section
entry** (a type and its props, as on a page) instead of today's fixed props: a template section, a copied
(cloned) section, or an agent section. They are drawn by the same section machinery as page sections
(their own scope for `_edits`, keys, rich text, slots), around every page, in the editor and on the
published page alike. The editor lists them in Layers as today (Header first, Footer last) and selects
them like any section; clicking blank space in them selects them (plan 4's rules).

### 4.2 Templates derived at extraction (founder: once per brand kit)

The extraction already finds the seller's top bar (`nav`) and footer (`footer`) when it splits a page
into sections (`lumen_ingestion/sections/segment.py`), but never offers them as copied sections
(`lumen_api/fragments/abm_page.py`, "escape routes"). An older lane composed an ABM header and footer
as minted fragments with slots, one pair per brand kit (`lumen_api/fragments/campaign_shell.py`).

Plan 6 joins the two: from the captured top bar and footer, the extraction makes **one header template
and one footer template per brand kit** that keep the seller's look (layout, spacing, logo treatment,
nav and button style) and carry the ABM parts of §2 through placeholders. **No approval gate** (founder
2026-10-18): a derived template is offered to the agent as soon as it is made, with no draft or release
step. Garner's and Conduit's already-approved kits get theirs from their existing captures, offline (no
new extraction run). *My call:* they are copied sections (fragments with slots), so the marketer edits
them with plans 1–5's clone tools unchanged. Today's fixed header and footer stay as the fallback
template when the extraction found no usable top bar or footer.

**On phones** (founder 2026-10-18): a copied seller header keeps its markup but not its JavaScript, so a
copied menu button would do nothing. Below a set width the header hides its menu and shows a compact
header (logos, account line, button), as today's header does. No drawer menu is built.

**The older ABM pair** (founder 2026-10-18): `campaign_shell.py`'s minted header and footer, and the
seller's own top bar and footer offered as ordinary page sections (`list_site_clones`), stay offered for
now. Once the founder is satisfied with how the new templates perform, they are retired in one step — not
part of plan 6.

### 4.3 Placeholders

The kit's stored template holds placeholders for **the seller's logo, the account's logo and the
account's name**, so one template serves every account. **They are filled once** (founder 2026-10-18):
when the agent starts a site's header from the template, it puts the account's real name and logo in
(or, on a one-to-few or one-to-many site, whatever group line and logos it judges right). From then on
they are ordinary words and an ordinary image in the site, edited like any other; renaming the account
later does not change the site. Markers that stay live inside a site, and one site copied per account as
the web-doc does (`{{account.*}}` + derive), come later with site templating — not plan 6.

*My call:* the menu of the site's own pages is the one thing filled when the site is drawn, so the header
always lists the site's real pages without the agent rewriting it when a page is added.

### 4.4 The agent

- Starts a new site's header and footer from the kit's templates.
- May change them (words, parts, order, styling) or rewrite them as its own section code — including a
  fresh header when the site needs one. It must be built from the brand kit's tokens and measured
  components; its skill says how, and that it must not look generic.
- Writes the account line creatively (§2) and decides whether the seller's menu links stay (§2).
- Its header and footer code is checked and rendered exactly like an agent section (the same
  check-section rules, the hardened render, the same `_edits`).
- Skill text (`writing-a-section`, `building-with-puck`) is shown to the founder before it is written.

### 4.5 The marketer

Everything plans 1–5 offer, in the header and footer:
- text: any word, word-level styling, links;
- buttons, boxes, images: their panels; logos replaced from the asset library (the seller's logo too —
  plan 5's "comes from the brand kit" note no longer applies in the header and footer);
- Arrange and Visibility for any part;
- *new:* **see-through over the hero** (the header's fill opacity, and the header drawn over the first
  section instead of above it) and **sticky** (stays at the top while scrolling). *My call:* both are
  properties of the header itself, set in its panel, saved, undone and published like any change.

### 4.6 Sites that already exist

Nothing to migrate (founder: no real customer yet). A site with today's fixed shell may simply be
re-created.

## 5. Proof

- Unit and business-logic scenario tests through the real routes, as plans 1–5: a template header and
  footer saved, edited (words, a logo replaced, see-through, sticky), undone, published; an agent-written
  header checked and refused for a forbidden prop; one template filled for two accounts by the agent at
  site start (no marker left in either site); the menu listing the site's pages
  after a page is added.
- Extraction: the derived templates for Garner and Conduit from their captures (offline first; a live
  extraction only with the founder's yes and a time estimate, standing rule).
- Live check in the in-app browser on Garner and Conduit (and Clue once it has a microsite).

## 6. Left to the builder

- The exact shape of a header/footer section entry in `site.shell`, and how today's `ShellSchema`
  is retired.
- How the derived template is composed from the captured top bar (which parts are slots, how the
  seller's menu is replaced by the site's pages, how a missing part degrades).
- The placeholder syntax inside the stored template, and how the agent fills it at site start.
- How "see-through over the hero" is drawn (positioning, the hero's top spacing) and how sticky
  interacts with the editor's canvas.
- Test layout, and the order of tasks.
