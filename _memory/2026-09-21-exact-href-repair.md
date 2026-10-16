# Source-preserving exact anchor repair

- Native correction reached the authentic account logo but could not edit two inherited,
  unbound relative links without transcribing 42k HTML / 195k CSS. Pagination alone did not
  solve that editability gap. Parent approved a bounded exact-href lane only.
- `repair_cloned_section(..., href_replacements_json={...} as JSON text, note=...)` now accepts
  1–8 exact old/new targets (2048 characters each), without HTML/CSS. Existing raw/typed callers
  remain compatible. Replacements are simultaneous; every key must match an anchor. Invalid,
  duplicate, unsafe, oversized, mixed-source and ambiguous multi-pin requests refuse.
- The workspace registry reads the complete immutable sanitized payload. A typed derivative
  changes anchor hrefs and only matching href-slot fallbacks; slot keys/kinds, assets and other
  manifest data survive. Parsed CSS rebases only wrapper/keyframe namespaces, including nested
  non-global at-rules and @scope selectors. No second sanitizer/scoper or model transcription.
  A new preview is not claimed. Original payload, capture evidence and degraded state survive.
- Shared existing custody stores the derivative with ordinary repair lineage/release rules.
  Convergence reports the stored lineage, including disagreement with the requested reason.
  The single pin updates with `set_node_props`: node/wrapper/layout, explicit bindings and
  engine-owned human text overrides remain. Release uncertainty and released-but-failed-swap
  states identify the persisted artifact and leave the page unchanged.
- Verification: first builder test collection failed because the new module did not exist;
  subsequent iterations corrected the newly allowed fallback expectation and test fixtures
  (SlotSpec keyword ordering; human heading path initially selected the whole section).
  All 215 offline derivative/custody/artifact/cloned-section/skill checks passed, including
  LangChain StructuredTool schema/invocation and real editor/delivery HTML: two inherited
  destinations change, the explicit CTA binding stays authoritative, and human copy survives.
- Parent independently ran historical fragment-repair/web-fragment DB suites. The initial
  attempt had 57 sandbox PostgreSQL PermissionErrors before live writes; all 65 passed when
  explicitly routed to the preexisting disposable `clue_onboarding_dedup_20260921_072303` DB.
  Receipt: `.local-setup/conduit-fresh-native/href-db-regression.log`. No duplicate DB run here.
- `git diff --check` passed. New files/shared registry are Ruff-clean; no new historical-file
  diagnostics (capability 41 unchanged, runtime substrate 283 to 282, runtime tests 3 unchanged).
  Parent reviewed/approved the scoped local commit. No providers, live artifact/DB changes,
  worker restarts, pushes or live agent acceptance performed by this subtask. Parent owns the
  idle-worker reload and native follow-up; offline success is not fresh live acceptance.
