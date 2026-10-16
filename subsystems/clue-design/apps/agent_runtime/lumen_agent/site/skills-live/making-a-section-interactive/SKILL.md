---
name: making-a-section-interactive
description: Use when a section needs to respond to the visitor — tabs, an accordion, a carousel, a calculator, something that appears as the visitor scrolls.
---

# Making a section interactive

This site's published pages run your section's React code in the visitor's browser. A section can
keep state, respond to clicks and run effects.

## What you can use

- React's hooks, imported from "react": useState, useEffect, useRef, useMemo and the rest.
- Event handlers on any element: onClick, onChange, onKeyDown and the rest.
- Timers: setTimeout, setInterval, requestAnimationFrame. Clear them when the effect ends.
- The page itself, inside an effect: window and document, to read the scroll position, the window's
  size or a media query, or to watch an element with IntersectionObserver.

## Three rules

1. **Draw the same thing on the server and in the browser.** The page is drawn first on the server,
   then the browser takes it over. If the two drawings differ, the browser redraws and the visitor
   sees the page jump. So never read window, document, the time, random numbers or storage while
   drawing: read them in an effect. The first drawing is the section's first state (the first tab
   open, the first slide shown).
2. **Stay still while the marketer edits.** `kit.editing` is true in the editor's Edit mode. Then
   show the first state and start no timers, so a click selects the section instead of driving it.
3. **Stay on the brand.** Colours, type, corners, surfaces and motion come from the brand, as in
   writing-a-section. No eval or new Function, no dangerouslySetInnerHTML, no <script>, <iframe> or
   <form>, and no cookies.

## Example: an accordion

```tsx
import { useState } from "react";
import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.string(),
  heading: z.string().min(1).meta({ edit: "inline" }),
  items: z.array(z.object({
    question: z.string().min(1).meta({ edit: "inline" }),
    answer: z.string().meta({ edit: "inline" }),
  })),
}).strict();

function Items({ items, editing }: { items: z.infer<typeof schema>["items"]; editing: boolean }) {
  const [open, setOpen] = useState(0);
  return (
    <div className="mt-stack-default divide-y divide-line-subtle border-y border-line-subtle">
      {items.map((item, index) => (
        <div key={index} className="py-4">
          <button
            className="w-full text-left font-title text-title"
            aria-expanded={open === index}
            onClick={() => (editing ? undefined : setOpen(open === index ? -1 : index))}
          >
            {item.question}
          </button>
          {open === index ? <p className="mt-2 font-body text-body text-ink-secondary">{item.answer}</p> : null}
        </div>
      ))}
    </div>
  );
}

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="brand-heading font-headline text-headline">{props.heading}</h2>
      <Items items={props.items} editing={kit.editing} />
    </kit.Shell>
  );
}
```

render_page shows the page after it has come alive, and its notes name any place where the server
and the browser drew different things ("hydration"). Fix those before you finish.
