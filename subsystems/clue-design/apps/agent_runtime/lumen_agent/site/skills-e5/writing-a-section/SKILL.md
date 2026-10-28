---
name: writing-a-section
description: "Read when neither a clone (as it is, or rebuilt) nor a brand section can carry what the page needs, and you write a section of your own with write_section: the file, the kit's pieces, the brand-only styling rules, and a header or footer of your own."
---

# Writing a new section

A new section is one small React file built only from the brand's tokens. Write it with
`write_section`, which checks it and makes it available to this page.

## The file

```tsx
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.string(),
  quote: z.string().min(1).meta({ edit: "inline" }),
  attribution: z.string().meta({ edit: "inline" }),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <blockquote data-clue-el="quote" className="brand-heading max-w-[30ch] font-headline text-headline">{props.quote}</blockquote>
      <p data-clue-el="attribution" className="mt-6 font-body text-body text-ink-secondary">{props.attribution}</p>
    </kit.Shell>
  );
}
```

This is one possible section. Write whatever structure the page needs — steps, grids,
comparisons, image and text — as long as every colour, type size, corner and button comes from
the brand.

The kit gives you these pieces, with exactly these props:
- `<kit.Shell surface={...}>…</kit.Shell>`: the section and its surface (it sets the right text
  colour). `surface` is any surface in brand/brand.md.
- `<kit.Button label="…" href="…" surface={...} look="…" el="…" />`: a button. `look` is a button
  style from brand/brand.md (Buttons); leave it out for the kit's standard button. Its words go in
  `label`. Give it a name with `el` (for example `el="cta"`) so the marketer can click it and change
  its fill, stroke, corners, padding and width. Its words are then named after it with `.label`
  (`cta.label`).
- `<kit.Link href="…">…</kit.Link>`: a text link, drawn like the seller's own links.
- `<kit.Card look="…" href="…" el="…">…</kit.Card>`: a card, drawn like the seller's own cards
  (brand/brand.md, Cards). With `href` the whole card is a link. Give it a name with `el` so the
  marketer can click it and change its fill, stroke, corners, padding, gap and width.
- `<kit.Eyebrow>…</kit.Eyebrow>`: the small label above a heading.
- `<kit.Image src="…" alt="…" el="…" />`: an image by its file path, from the page's image list
  (`imagery-and-media`, "The images a page may use"). Add
  `fit="fill"` to make it cover a box you position, for a background photo, or `fit="contain"` to
  show the whole image. A logo is always shown whole. Give it a name with `el` so the marketer can
  select it, move it, and change its fit, stroke and corners. Name it after the prop that holds its
  file (`el="photo"` with `src={props.photo}`) and the marketer can replace the picture too.
  Write `alt` as a few plain words saying what the picture shows; leave it empty (`alt=""`) for a
  picture that is only decoration.
- Motion: add a class from brand/brand.md (Motion) to an element, for example
  `className="brand-motion-pulse"`. Move only through the brand's motion classes, or to rebuild
  motion the seller's own site actually has (`imagery-and-media`, "Motion and video"; on live sites,
  `making-a-section-interactive`). Invent no motion of your own.

## Rules

- Style only with the brand's classes: surfaces through `kit.Shell`, or `bg-surface-<role>` with its
  matching `text-on-surface-<role>` when a section needs panels edge to edge, type through
  `font-<role> text-<role>` (roles in brand/brand.md), colours through `text-ink-*`,
  `bg-surface-*` and `border-line-*`, corners through `rounded-<role>`, and spacing through the
  brand's spacing classes (`py-section`, `mt-stack-tight`, brand/brand.md) or Tailwind's scale
  (`mt-6`, `gap-8`). No colour values, pixel sizes, `style` or `className` props: write_section
  refuses them.
- Props are content: plain text, brand choices (surface, heading role), images from the page's
  image list.
- Mark every prop a marketer reads as words on the page (a heading, a paragraph, a quote, a button's
  words, a card's title) with `.meta({ edit: "inline" })`. The marketer can then click those words
  and type. While they do, such a prop is not text but an editable piece of the page: put it into
  the page exactly as it is (`{props.quote}`), and never change it in code (no capitals, splitting,
  cutting or joining). A marked prop may also hold a few words in bold or italic, a link, or words
  the marketer styled. Put it into the page as it is: never inside an attribute (`alt`, `title`,
  `aria-label`) and never through a text method (`.toUpperCase()`, `.split()`, `.length`). For capitals, use the `uppercase` class. For separate lines, use a list of
  items. Do not mark choices (surface, look, cardLook), links, images or `alt`: the editor offers
  those from lists and fields. write_section refuses a section that breaks these rules and says why.
- Name every heading, paragraph and label: add `data-clue-el="<name>"` to its element, for example
  `<h2 data-clue-el="headline" …>`. Use letters and digits, with dots, underscores or dashes between
  them, and give each element its own name within the section. For `kit.Eyebrow`, `kit.Link` and
  `kit.Button`, pass `el="<name>"` instead. The marketer can then click that text in the editor and change its
  colour, font, size, weight and alignment. Text without a name can still be edited as words, but
  not restyled.
  When the text is a prop you marked for editing in place, give its element the prop's own name:
  `<h2 data-clue-el="headline">{props.headline}</h2>`, and for a list item
  ``data-clue-el={`cards.${index}.title`}``. The marketer can then also style single words in it
  and make them links.
- Name the boxes a marketer may want to restyle or move: a card, a row of cards, a column. Add
  `data-clue-el="<name>"` to your own `<div>`, `<ul>` or `<li>`, or pass `el` to `kit.Card`.
  `kit.Shell` already names the section's own box (`root`, and `root.inner` for the box with its
  padding), so do not use those two names yourself.
  To let the marketer move items up or down, draw them from a list prop and name each one after the
  list and its place: ``el={`cards.${index}`}``. Name the text inside an item after the item
  (``cards.${index}.title``), so its styling moves with it. Boxes that are not drawn from a list
  keep their place.
- Make it look like the seller's sections around it. Render and compare. Its surface and
  composition follow the seller's cadence (`page-design`).
- Place it in page.json by its name, like any other section.

## A header or footer of your own

When no template fits the site, you may write the header or the footer as a section. Put it in
`shell.json` as the header's (or footer's) `type`, with the id `header` (or `footer`).

- Build it from the brand, like every section: its type roles, colours, surfaces, button styles and
  link style (brand/brand.md, Buttons and Links). Look at the seller's own header (its nav band in
  `catalog/`) and follow its layout and spacing. It must look like the seller's site, never like a
  generic header with their logo dropped in.
- The seller's logo: `kit.Image` with a logo file from brand/brand.md. On a page that names the
  account (`page-kinds`), the account's logo and line are props you fill (for example `accountLogo`
  and `accountLine`), the line marked for editing in place. The line follows the relationship words in
  `page-copy` ("Talking about the prospect"): "Prepared for", never "partner" or "working together".
  On a page with no account, leave the account's logo and line out.
- The site's pages: `kit.menu` lists them in order, each with `label`, `href` and `key`. Draw each with
  `kit.Link` and give it `el={item.key}`, so the person can style and hide them.
- One button, with `kit.Button`, to the page's primary action.
- Keep it short. A header is one row: logos, the line, the menu, the button. A footer is the
  seller's mark, the legal line and the legal links.
