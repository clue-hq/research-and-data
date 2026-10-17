---
name: writing-a-section
description: Use when you have been asked to add something that no clone and no brand section can carry.
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
- `<kit.Card look="…" href="…">…</kit.Card>`: a card, drawn like the seller's own cards
  (brand/brand.md, Cards). With `href` the whole card is a link.
- `<kit.Eyebrow>…</kit.Eyebrow>`: the small label above a heading.
- `<kit.Image src="…" alt="…" />`: an image from brand/brand.md, by its file path. Add
  `fit="fill"` to make it cover a box you position, for a background photo, or `fit="contain"` to
  show the whole image. A logo is always shown whole.
- Motion: add a class from brand/brand.md (Motion) to an element, for example
  `className="brand-motion-pulse"`. Write no transition or animation of your own.

## Rules

- Style only with the brand's classes: surfaces through `kit.Shell`, or `bg-surface-<role>` with its
  matching `text-on-surface-<role>` when a section needs panels edge to edge, type through
  `font-<role> text-<role>` (roles in brand/brand.md), colours through `text-ink-*`,
  `bg-surface-*` and `border-line-*`, corners through `rounded-<role>`, and spacing through the
  brand's spacing classes (`py-section`, `mt-stack-tight`, brand/brand.md) or Tailwind's scale
  (`mt-6`, `gap-8`). No colour values, pixel sizes, `style` or `className` props: write_section
  refuses them.
- Props are content: plain text, brand choices (surface, heading role), images from
  brand/brand.md.
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
- Make it look like the seller's sections around it. Render and compare.
- Place it in page.json by its name, like any other section.
