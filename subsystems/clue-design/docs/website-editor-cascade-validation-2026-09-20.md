# Website editor cascade validation — 2026-09-20

## Result

The captured AWS hero now has the same measured geometry in the source, delivery render, and editor render at desktop and mobile sizes. This is a targeted editor fix, not whole-page fidelity acceptance. No production services, live workspaces, environment files, source artifacts or approval states were changed.

## Cause and change

The browser Tailwind compiler scans every DOM class, including a source website's `container` class inside a cloned section. On the frozen AWS page this generated an unintended `max-width:80rem`, reducing the desktop outer container from 1440 to 1280 pixels and the headline from 504 to 424 pixels wide. Static delivery already excludes cloned interiors from its utility scan.

`CoreClient.web_render` now adds a supported `@source not inline(...)` declaration to the editor compiler block for classes used exclusively inside cloned sections. Native node and fragment-wrapper classes remain eligible. Neither stored fragment markup/CSS nor delivery HTML is rewritten. Classes shared with native nodes are retained and diagnosed because suppressing them would break authored utilities.

Candidate serialization rejects quote, backslash, brace-expansion, control and markup syntax. Input, body, node, token and directive bounds are explicit. Partial or skipped isolation is diagnosed rather than reported as complete. The scan parses only the canonical body and the small compiler prefix; the real AWS render contains roughly 33 MB of stylesheet text but only 480 KB of body markup. Parent review rejected the first whole-document 16 MiB bound because it would have skipped this real case despite passing smaller tests.

## Verification

| Viewport | Source headline | Delivery headline | Patched editor headline |
|---|---:|---:|---:|
| 1440 px | 504 × 88 | 504 × 88 | 504 × 88 |
| 375 px | 279 × 108 | 279 × 108 | 279 × 108 |

The parent independently reran the actual frozen capture through the real helper/API path, measured all three modes in Chromium with external requests blocked, and inspected both editor screenshots. The desktop card and outer widths returned to 584 and 1440 pixels. Existing source/delivery probes were retained separately.

- 21 new tests passed independently under parent execution: desktop/mobile geometry, native utilities, shared candidates, hostile strings, unchanged delivery, deterministic output, inert templates and bounded/oversized inputs.
- 19 existing fragment-render tests passed on the disposable test database, including API and agent preview seams.
- The implementer also passed 22 related root-unit/CoreClient checks (43 in its focused run, overlapping the 21 above).
- New files are Ruff-clean and whitespace checks pass. Pytest emitted existing temporary-directory cleanup warnings; assertions passed.
- Evidence: `.local-setup/website-capture/editor-candidate-20260920/`, `editor-candidate-parent-tests.xml`, and `editor-candidate-render-seam-tests.xml`. These are local ignored evidence, not published assets.

## Remaining failures and limits

Source body-class typography inheritance is still absent. The AWS regional heading is 16.38 px Arial in the source, 11.7 px Inter in delivery and 10 px Inter in the editor; Tailwind preflight contributes to the editor difference. The source chat widget remains captured and needs deliberate treatment. These problems are visible and were not hidden by this fix.

Shared native/source utilities can still collide, and unsupported or over-budget class tokens remain eligible for the browser compiler with a diagnostic. Large repeated fragment stylesheet output remains a performance concern. Interaction, WebGL playback and whole-page visual fidelity are not proven. The four running brand workspaces have not received this isolated branch yet.
