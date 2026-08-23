---
name: custom-components
description: Create, repair, compile, reuse, attach, and explicitly repin durable account-scoped TSX custom components when the website capability ladder proves one is necessary.
---

# Custom Components

Custom components are the last rung of the website capability ladder, not the
default way to author a page:

1. ordinary palette nodes and theme classes;
2. a platform component (`dialog`, `accordion`, `marquee`, `nav_menu`,
   `carousel`, or `tabs`);
3. an allowlisted embed when a real third-party endpoint is the irreducible
   capability;
4. a custom component only for behavior or visualization none of those can
   express.

Before the first source write, state the concrete gap at each lower rung in the
`ladder_gap` argument. The tool records it as durable demand evidence. A vague
"needs custom code" is not a gap. Keep separation of concerns: the typed tree
still owns layout, visibility, triggers, links, and surrounding content; custom
source owns only the irreducible behavior.

## Durable filesystem and discovery

The current account's registry is projected read-only at:

```
/custom_components/<slug>/
```

The required entry is `<slug>.tsx`; helpers stay under the same slug directory
and use relative imports such as `./lib/format`. The directory name is lowercase
kebab-case and is the durable component identity.

Use ordinary filesystem `ls`/`read` to inspect the projection. Never write or
edit it with filesystem tools: those calls are rejected because they cannot
carry an expected source version, endpoint evidence, or provenance. Use:

- `list_custom_components()` for components with attachable compiled artifacts;
- `inspect_custom_component(slug)` for source, schema, defaults, diagnostics,
  immutable versions, and exact usages;
- `write_custom_component_source(...)` for a complete CAS-protected source tree.

Source is registry-backed, not conversation-backed. A later run and a restarted
process rematerialize the same current source. Reuse never changes source.
Never create `-2` or renamed duplicates merely because a slug exists: inspect
and reuse it, or deliberately update it with its exact current version.

## Author contract

```tsx
import React from "react";

type Props = {
  headline?: string;
  accent?: "primary" | "accent";
  count?: number;
  showBadge?: boolean;
};

export const meta = {
  name: "Metric Card",
  description: "Interactive account metric summary.",
};

export default function MetricCard({
  props: {
    headline = "Performance",
    accent = "primary",
    count = 3,
    showBadge = true,
  },
  theme,
  overrideVariables,
}: {
  props: Props;
  theme: {
    colors: Record<string, string>;
    fonts: Record<string, string>;
  };
  overrideVariables?: Record<string, string>;
}) {
  return (
    <section className="rounded-xl bg-card p-6 text-dark">
      <h2 className="font-heading text-2xl">{headline}</h2>
      <p>{count}</p>
      {showBadge ? <span className={`text-${accent}`}>Current</span> : null}
    </section>
  );
}
```

**Custom-component CSS is its own world — the page's brand-geometry utilities
do NOT reach it.** A component compiles in an isolated Tailwind build whose
theme carries the four colors and two font families above and nothing else, so
`rounded-card`, `p-card`, `py-section`, `shadow-brand` and the rest of
`create-website`'s geometry vocabulary produce NO CSS here and would silently
drop the shape they were meant to set. Inside custom source, raw Tailwind
geometry (`rounded-xl`, `p-6`) is the correct spelling — the one place in the
web grammar where that is true. Match the brand's measured numbers by eye from
the brand card instead, and keep the surrounding layout in the typed tree, where
the utilities do work.

The default export is required. `meta` gives the picker label/description.
Declare props as optional `string`, `number`, `boolean`, or string-literal
unions and provide destructuring defaults; the compiler turns them into the
editor's generated inspector schema. Unsupported prop shapes are not editable
through generated controls.

Use Tailwind utilities and page theme tokens. Never hard-code an account's
colors/fonts when `theme` supplies them. The browser runtime injects `props`,
the resolved `theme`, and optional `overrideVariables`. The component is a leaf:
it cannot own tree children.

Allowed imports are:

- `react` (the sandbox's host singleton);
- `components/<slug>` (another account-local component pinned as a dependency);
- relative paths that remain inside this component directory;
- `@visx/shape`, `@visx/curve`, `@visx/group`, `@visx/scale`;
- `motion/react`, `gsap`, and `@gsap/react`.

Other bare imports fail compilation. `eval`, `new Function`, dynamic `import`,
`document.write`, source escape, and dynamic Tailwind class construction are
compile errors. Use static complete class strings so the compiler can generate
CSS.

For drawings, use real SVG and Visx generators rather than handcrafted complex
path strings. Prefer `motion/react` for springs/gestures and GSAP for timelines.
Required structure and content must be visible in the server first frame; do
not hide essential content at opacity zero until a client-only effect runs.
Respect reduced motion and clean up listeners/effects. Pointer animation writes
through motion values or GSAP setters, not React state on every pointer event.

## Endpoint honesty

Never invent a booking URL, form action, API endpoint, webhook, integration, or
external asset URL. Every literal endpoint in source needs one exact claim in
`endpoint_claims_json`:

```json
[
  {
    "endpoint": "https://customer.example/api/submit",
    "provenance": "user_provided"
  },
  {
    "endpoint": "https://vendor.example/widget",
    "provenance": "grounded_source",
    "source_id": "page_..."
  },
  {
    "endpoint": "https://example.com/PLACEHOLDER-booking",
    "provenance": "placeholder"
  }
]
```

`user_provided` must occur literally in this turn's prompt.
`grounded_source` must match a URL returned by that `fetch_page` source.
`placeholder` must be unmistakable (`example.com/PLACEHOLDER` or
`example.invalid`). Placeholder endpoints are automatically surfaced in the
final summary; ask the user for the real value. When revising source in a later
turn, preserve the exact claim already present in the inspected source
revision's provenance; that durable evidence is accepted without making the
user repeat the endpoint.

## Safe source → compile → placement workflow

These are three separate state transitions:

1. Inspect. Read the exact current source version and usages.
2. Write source. Send the complete file map with `expected_version`. New slug:
   `0`; update: the current version from inspection. A stale value is rejected.
3. Compile that exact new source version with `compile_custom_component`.
   Compile success creates an immutable artifact but places nothing.
4. Attach or repin with `place_custom_component` and the exact artifact id.
   Placement changes document operations but never source.

On deterministic diagnostics (TypeScript, forbidden syntax/import, schema,
static CSS), repair source and write a new version. Recompiling the unchanged
failed version is refused. On transient infrastructure failure the compile tool
automatically makes at most three total attempts; if exhausted, stop and report
the temporary failure. Never add whitespace or cosmetic source changes to force
a retry.

`action="attach"` requires an explicit parent node and index.
`action="repin"` requires a non-empty explicit node-id array. Preserve existing
props unless the new schema requires a deliberate update. When the human
selected nodes for this turn, repin may touch only those nodes and attach may
occur only inside their enclosing section. Never use a whole-page rewrite to
place or repin a component.

Each edit creates a new immutable artifact and repins only the named nodes on
the current page. Other nodes, pages, and existing publishes keep their prior
pin. Reuse an old artifact when no source change is needed. A new pin does not
change a live publish until the user explicitly republishes it.

## Completion check

Before reporting success, verify:

- the lower-rung gap was concrete and recorded;
- source exists under the durable slug and the returned version is current;
- compile status is successful and the exact immutable artifact id is known;
- no endpoint lacks user/grounded/obvious-placeholder provenance;
- attach/repin targeted only the intended page nodes;
- the final operation ledger, preview, and diagnostics show the component;
- placeholder endpoints and any remaining warnings are named honestly.
