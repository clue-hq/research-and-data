# Website capture cascade validation — 2026-09-20

## Result

The rendered and static capture paths now retain stylesheet occurrence order, owner media/disabled state, and bounded in-place imports. Previously inline sheets were concatenated before external sheets and imports were appended last. This could change typography, colors, and responsive behavior before a fragment was even extracted.

Effective CSS chunks keep their physical stylesheet URL for relative asset resolution. Snapshot storage retains raw source text separately, the source ordinal path, media, disabled state, and import parent. Existing snapshots remain readable; this does not repair or relabel old snapshots as source-faithful.

Imports use CSS tokens, including escaped/quoted URLs, nested imports, media, supports and named/anonymous layers. Requests deduplicate while repeated source occurrences remain distinct. Limits are four import levels, 64 extra requests, 4096 chunks and 32 MiB effective CSS per collection. Diagnostics are capped at 256 with an explicit truncation notice. Refused or unsupported imports stay diagnostic rather than becoming unconditional rules.

## Supervised verification

Four independent review findings were reproduced and fixed: missing rendered page base URL, malformed CSS/URL crashes, invalid block-form imports being applied, and nested imports lost when an active sheet imports a cached disabled root. Parent browser comparisons found a fifth issue: an inactive media import must not establish its cascade layer. The condition now encloses the layer, matching Chromium.

Fourteen focused tests passed, including source-versus-capture Chromium checks at 1440/375, conditional imports, anonymous layers, repeated occurrences, disabled owners, storage round-trip and bounded malformed-input diagnostics. A related capture/snapshot run had 88 passes, one pre-existing opt-in live skip, and one test-harness callback-signature failure introduced during lint cleanup. The callback was corrected and that exact test rerun passed. Earlier setup failures (test syntax and an asyncio call inside synchronous Playwright) were corrected before interpreting browser results. No product failures are hidden by these harness corrections.

Evidence is retained under the ignored `.local-setup/website-capture/` directory: `stylesheet-final-focused.xml`, `stylesheet-final-integration.xml`, and `stylesheet-browser-final.xml`. New files are Ruff-clean. Full-file lint still reports existing debt in rendered.py/site_snapshot.py; this is not a claim of a clean repository-wide lint run.

## Remaining scope

This is captured-evidence fidelity, not proof of complete website reproduction. General ancestor context, source runtime JavaScript/WebGL, full-page motion, all four live workspace imports and end-to-end generation acceptance remain separate checks. Source HTML/body inheritance is being implemented and reviewed independently. No live database, environment, running service or original checkout was changed.
