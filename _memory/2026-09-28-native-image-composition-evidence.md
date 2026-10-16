# Native image composition evidence — 2026-09-28

Continued active goal on `codex/design-agent-v1` from `97daabe6`. Previous turn
was progress. No new Clue/provider generation, ingestion, DB or page mutation,
service restart, push or publication. The no-new-run restriction remains.

- Traced the saved image composition and viewed all five existing source blobs.
  One shared padded background wrapped both finished composites and independent
  transparent UI layers. Non-opaque edges were present even in finished composites;
  alpha presence alone cannot select the correct composition treatment.
- Found the scene/ad viewer's existing transparency helper was absent from the
  web viewer. Reused it in the native web asset view, adding optional opaque
  receipts. No new agent/tool/classifier or crop mutation was introduced.
- Receipts identify decoded preview bytes, alpha counts/bounds and frame zero;
  non-opaque previews get white/charcoal inspection surfaces. All-opaque previews
  add no second image. Asset pixels and document stay unchanged. Thumbnail-first
  selection remains; do not present preview evidence as proof of original alpha.
- Existing media skills now explicitly distinguish mixed composition classes,
  feathered edges and intentional transparent margins. Alpha bounds are not an
  auto-crop rectangle; comparison backgrounds are not placement assets.
- Read-only baseline comprehension already understood the broad principle.
  Review found no blocker and applied it to a separate industry case. This is
  not causal model-performance improvement or native visual acceptance.

Verification: two new regressions failed before implementation, then passed.
Full focused web/scene asset-view, format and skill-loading checks: 68 pass.
Two prior tests asserting absent words across all text were narrowed to their
metadata label and supplemented with independent decoded-dimension assertions.
Ruff: 21/298/14 existing findings in the touched legacy files, identical by
rule/message/source line to HEAD; no new finding. Whitespace checks pass. Pytest
still warns about cleanup of unrelated old temporary directories; exit zero.
Held-asset helper replay: digest identity and alpha facts confirmed for all five
blobs, 24–33ms locally each; no latency promise or current page proof.

Closing checkpoint is scoped for local commit only. Unrelated account display
tests and prior notes remain untouched. Goal incomplete: still need source
behavior preservation, retrieval/continuity, and native copy/layout/interaction
acceptance when a new run is authorized. The original-asset-versus-thumbnail
inspection limitation remains explicit.
