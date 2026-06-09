# Brand Tokens And Design Systems

Status: supported now, recognized but not lowered, and future scaffold.

## Supported Now

Use tokens when the design should adapt to an uploaded, generated, or platform
default Brand Kit:

```text
fill($surface.brand)
fill($surface.card)
stroke($stroke.subtle,$stroke.width.firm)
g($space.md)
pad($space.lg)
rd($radius.lg)
style($type.headline)
style($type.body)
```

If a scene contains token references, preflight must receive an effective Brand
Kit. The platform default Brand Kit is valid when the user has not supplied
one.

## Recognized But Not Lowered

Avoid ambiguous tokenized font calls where no precise scene carrier exists,
such as tokenizing only the size argument of `font(...)`. Prefer full
typography style tokens.

## Future Scaffold

Future design-system authoring should support:

- generated brand kits from websites/uploads
- semantic aliases
- mode-rich themes
- brand constraints and do/don't rules
- typography scale linting
- visual examples retrieved before authoring

