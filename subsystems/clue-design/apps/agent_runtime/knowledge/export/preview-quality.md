# Preview And Export Quality

Status: supported now, recognized but not lowered, and future scaffold.

## Supported Now

SVG export is the canonical Phase A preview. PNG export is available as a
preview format when configured. Before visual critique, the runtime must verify:

- at least one artifact exists
- bytes are non-empty
- SVG artifacts begin with an SVG root
- PNG artifacts have a valid PNG header
- page ID and dimensions are recorded when known
- requested aspect ratio is compared against actual page dimensions when known

The visual reviewer should reject designs that are clipped, mis-scaled,
off-canvas, unreadable, or visibly incomplete even when export succeeds.

## Recognized But Not Lowered

Raster screenshot parity and browser-level preview may not always be available
in CI/dev. In that case, use SVG as the critic artifact and record the missing
raster path as a preview gap.

## Future Scaffold

Future preview/export work should add:

- browser screenshot capture
- visual regression metrics
- print-safe PDF validation
- font embedding checks
- asset byte resolution
- bleed/safe-area proofing

