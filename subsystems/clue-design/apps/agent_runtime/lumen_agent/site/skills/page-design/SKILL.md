---
name: page-design
description: "Read when you choose a section's surface, place a brand section or a new section, pick the hero, or judge how the page looks as a whole: following the seller's own rhythm of surfaces and density, which of the seller's page heroes opens the page and how to adapt it, varying composition, the seller's heading and body fonts, and headings across the page."
---

# Page design

The page should look like a page the seller made. Its clones already carry the seller's look; your
choices (brand-section surfaces, new sections, the hero, the order) should follow the seller's own
habits rather than a fixed rule.

## The seller's cadence

Before you choose surfaces, read the clones of the seller's source page in order (`catalog/index.md`
lists them by page, in page order) and note the seller's cadence in one line in your plan: its rhythm
of surfaces and of density, for example "light hero, dense details, product visual, proof, a rare
dark band, light close". Then remix it for this page rather than copying it section for section.

- Dark or strong sections appear about as often as on the seller's site, and where the seller puts
  them. They are not limited to one, and may sit next to each other if the seller does that.
- A brand section or a new section takes the surface and density that fit between its neighbours, as
  the seller would choose. It must not look foreign next to the clones; if it does, choose another
  surface.
- Avoid uniform sections: not every section as three equal cards, and no layout the seller's site has
  no precedent for.
- When you cannot read a cadence (too few clones, one surface throughout), alternate light and dark,
  and use the strongest surface sparingly.

Surfaces and heading sizes are chosen by name (`brand/brand.md`; how to set them:
`building-with-puck`).

## Which hero

Decide which of the seller's pages' hero sections suits this page's job, and open with it: a hero
section, never another kind of section. The hero is the first clone of a source page in
`catalog/index.md`.
- The home page's hero for a broad page (one account, a whole audience).
- A product page's hero for a product campaign.
- An event or webinar page's hero for an event, when the seller has one.

Adapt that hero rather than replace it: keep its composition and its visual, and change its words.
Write a new hero only when none of the seller's heroes fits. Its composition follows the seller's own
hero shape (split, centred, a full-width visual), with the weight where the seller puts it; centre it
only when the seller's heroes are centred.

Write the hero you chose in the plan, in one line.

## Composition

Name each section's composition in the plan in one or two words (split, centred statement, editorial
stack, proof strip, three cards), and vary it where the content varies. Sections that do different
jobs should not all share one arrangement.

## The seller's fonts

Before you build, note in your plan, in one line, the font the seller uses for headings and the font it
uses for body text, from `brand/brand.md` (the type roles) and the seller's own sections, for example
"headings: Season, serif, regular; body: Inter". Then keep to them:
- In every section you write or rebuild, headings use the seller's heading font and body text uses its
  body font, through the brand's type roles (`font-headline`, `font-title`, `font-body`; the
  writing-a-section skill).
- A section you reuse whose headings or body text are in another font (for example one composed for an
  earlier page) gets the seller's fonts back: set `fontFamily` (and the weight the seller uses) in its
  `_edits` for that text (`building-with-puck`, "Styling by hand").

## Headings across the page

- Judge headings across the whole page, not section by section. The hero's headline is the largest on
  the page, unless the seller's own pages do otherwise.
- A brand section picks its heading size so it sits right against the clones around it.
- Never shrink type to fit more words; edit the words.
