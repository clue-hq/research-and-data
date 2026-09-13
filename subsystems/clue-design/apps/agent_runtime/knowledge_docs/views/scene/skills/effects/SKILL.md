---
name: effects
description: Use when a scene's inspected source treatment or communication needs a supported shadow, stroke, gradient or corner treatment.
---

# Native effects

Effects serve the chosen direction; they do not establish a default material or
lighting style. Use native paints/geometry for simple gradients, strokes and
shadows, preserving editability. Generate texture or complex imagery only when
that component calls for it; `knowledge/scene/references.md` owns that decision.

Supported examples (substitute actual kit tokens where appropriate):

```text
shadow(#000000, o(0.12), y(8), blur(24))
fill(linear(135, stop($surface.page,0), stop($surface.brand,1)))
stroke(#000000, 1)
rd(16)
```

Read `knowledge/lumen-dsl/grammar.md` and `knowledge/lumen-dsl/colors.md` for
argument forms and paint semantics. An unsupported effect must become a named
gap, not an invented property or a flattened complete ad. Inspect the final
composite for contrast and crop after applying effects.
