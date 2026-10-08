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
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  quote: z.string().min(1),
  attribution: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <blockquote className="brand-heading max-w-[30ch] font-headline text-headline">{props.quote}</blockquote>
      <p className="mt-6 font-body text-body text-ink-secondary">{props.attribution}</p>
    </kit.Shell>
  );
}
```

This is one possible section. Write whatever structure the page needs — steps, grids,
comparisons, image and text — as long as every colour, type size, corner and button comes from
the brand.

The kit gives you:
- `kit.Shell`: the section and its surface (it sets the right text colour for light and dark).
- `kit.Button`: the brand's button.
- `kit.Eyebrow`: the small label above a heading.
- `kit.Image`: an image from brand/brand.md.

## Rules

- Style only with the brand's classes: surfaces through `kit.Shell`, type through
  `font-<role> text-<role>` (roles in brand/brand.md), colours through `text-ink-*`,
  `bg-surface-*` and `border-line-*`, corners through `rounded-<role>`, and spacing through
  Tailwind's scale (`mt-6`, `gap-8`). No colour values, pixel sizes, `style` or `className`
  props: write_section refuses them.
- Props are content: plain text, brand choices (surface, heading role), images from
  brand/brand.md.
- Make it look like the seller's sections around it. Render and compare.
- Place it in page.json by its name, like any other section.
