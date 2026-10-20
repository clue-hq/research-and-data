# Preview And Export Quality

Status: supported now, recognized but not lowered, and future scaffold.

## Supported Now

SVG export is the canonical vector preview. PNG export rasterizes the canonical
SVG page output and is the preferred critic artifact when multimodal review is
available, because it includes rendered text instead of asking the model to
reason over raw SVG markup. Before visual critique, the runtime must verify:

- at least one artifact exists
- bytes are non-empty
- SVG artifacts begin with an SVG root
- PNG artifacts have a valid PNG header and should visibly include SVG text
  nodes unless the source SVG itself has no visible text
- page ID and dimensions are recorded when known
- requested aspect ratio is compared against actual page dimensions when known

Reject designs that are clipped, mis-scaled,
off-canvas, unreadable, or visibly incomplete even when export succeeds.

## Recognized But Not Lowered

Browser screenshot parity may not always be available in CI/dev. In that case,
use the SVG-to-PNG raster artifact for critic review, keep the canonical SVG
beside it for traceability, and record the missing browser screenshot path as a
preview gap only when browser-specific behavior is required.

## Future Scaffold

Future preview/export work should add:

- browser screenshot capture
- visual regression metrics
- print-safe PDF validation
- font embedding checks
- asset byte resolution
- bleed/safe-area proofing
