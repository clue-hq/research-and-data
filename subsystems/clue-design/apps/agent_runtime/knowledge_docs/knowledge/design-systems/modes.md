# Brand Modes

Brand modes let the same scene resolve differently for digital, print, dark
theme, compact density, or accessibility requirements.

## Required Axes

Product-ready Brand Kits should declare:

- `theme`: `light`, `dark`
- `density`: `comfortable`, `compact`
- `accessibility`: `standard`, `high_contrast`, `large_text`
- `medium`: `digital`, `print`

Default mode is usually:

```text
theme.light
density.comfortable
accessibility.standard
medium.digital
```

## Authoring Rules

DSL should not hard-code mode-specific values. Use semantic tokens and let
preflight resolve the active mode:

```text
fill($surface.page)
style($type.headline)
g($space.stack.default)
```

For print or direct-mail scenes, set the scene medium and let preflight choose
`medium.print` when no explicit override is supplied.

## Compatibility

Removing a mode axis or value can break old templates. A compatibility report
should flag mode coverage changes, for example removing `medium.print`.

Agents should treat mode compatibility diagnostics as product safety issues,
not as visual preferences.
