# Brand-Fit Critique

Brand fit is a quality gate. A design can compile, preflight, and export while
still failing the selected client's brand.

## Review Questions

Ask:

- Does the design use semantic tokens instead of raw style guesses?
- Are surfaces, text, borders, and accents consistent with the Brand Kit?
- Does typography hierarchy use `type.*` roles?
- Are spacing and radius consistent with tokenized rhythm?
- Is the logo variant placed on an allowed background?
- Does the medium match the artifact, especially print vs digital?
- Does the design look generic, or does it plausibly belong to this client?
- Are any Brand Kit governance diagnostics unresolved?

## Rejection Examples

Reject when:

- a branded design uses arbitrary hex colors for major surfaces
- body copy uses raw tiny font sizes instead of `type.body`
- spacing and radius look random across panels
- a logo appears on a disallowed surface
- print output relies on unsupported transparency
- generated imagery conflicts with the Brand Kit's visual style notes

## Repair Instructions

Give concrete repairs:

```text
Replace headline style with style($type.headline).
Change hero fill to fill($surface.brand).
Move logo_primary onto a surface.brand block or use logo.reversed.
Replace raw radius with rd($radius.card).
```

Do not say only "make it more on brand."
