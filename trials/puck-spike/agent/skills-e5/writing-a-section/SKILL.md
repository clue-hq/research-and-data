---
name: writing-a-section
description: Use when you have been asked to add something that no clone and no brand section can carry.
---

# Writing a new section

A new section is one small React file built only from the brand's tokens. Write it with
`write_section`, which checks it and makes it available to this page.

## What the file must have

- `export const schema`: a zod object (`z.object({...}).strict()`) of the section's props. It
  needs `id` (a string) and `surface` (one of page, card, muted, brandSubtle, brand, inverse).
  Every other prop is yours to design: whatever content this section needs.
- `export function render(props, kit)`: returns the section inside `kit.Shell`.
- Imports only from `zod`, `react` (types) and `@/puck/agent-kit` (the `Kit` type).

Design the section around what the page needs — steps, grids, comparisons, image and text — as
long as every colour, type size, corner and button comes from the brand.

## The kit

- `kit.Shell`: the section and its surface (it sets the right text colour for light and dark).
- `kit.Button`: the brand's button.
- `kit.Eyebrow`: the small label above a heading.
- `kit.Image`: an image from brand/brand.md.

## Rules

- Style only with the brand's classes; the full list is in brand/theme.css. Surfaces through
  `kit.Shell`, type through `font-<role> text-<role>`, colours through `text-ink-*`,
  `bg-surface-*` and `border-line-*`, corners through `rounded-<role>`, and spacing through
  Tailwind's scale (`mt-6`, `gap-8`). No colour values, pixel sizes, `style` or `className`
  props: write_section refuses them.
- Props are content: plain text, brand choices (surface, heading role), images from
  brand/brand.md.
- Make it look like the seller's sections around it. Render and compare.
- Place it in page.json by its name, like any other section.
