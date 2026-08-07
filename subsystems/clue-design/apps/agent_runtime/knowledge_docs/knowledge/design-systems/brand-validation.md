# Brand Validation And Governance

Brand validation answers whether a scene or Brand Kit follows the selected
brand system. It should produce repairable diagnostics, not vague style advice.

## Brand Kit Validation

Use Brand Kit validation for:

- missing required semantic tokens
- missing typography roles
- invalid token references
- missing mode axes
- missing logo/font assets
- weak typography metrics
- generated token confidence gaps

Approved kits should be stricter than draft or generated-unreviewed kits.

## Scene Governance

Use scene brand governance when a design is attached to a Brand Kit.

Strict mode should flag:

- raw fills and strokes when a token should be used
- raw typography styles when a `type.*` token should be used
- raw spacing, radius, opacity, and layout rhythm
- logo on disallowed backgrounds
- print or direct-mail transparency problems

Important diagnostics:

- `LUMB0804`: raw/off-brand color
- `LUMB0805`: raw typography
- `LUMB0806`: raw spacing, radius, stroke, opacity, or layout value
- `LUMB0807`: logo background rule violation
- `LUMB0811`: print/direct-mail transparency violation
- `LUMB0813` to `LUMB0815`: Brand Kit compatibility breakage

## Repair Policy

Repair with semantic tokens:

```text
fill($surface.card)
style($type.body)
rd($radius.card)
g($space.stack.default)
```

Do not repair off-brand output by picking a new raw hex value unless the user
explicitly asks for an override.
