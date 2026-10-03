# Bounded inspection of captured section source

- Native correction exposed a read limitation: `inspect_cloned_section` returned only the
  first 12,000 characters of each stream, with no continuation. Existing registry reads are
  workspace-scoped; no other agent-facing continuation was found.
- Added optional independent `html_offset` / `css_offset` character offsets, default zero.
  The original `html` / `css` first slices, total character counts, and default truncation
  behavior remain. Every response stays capped at 12,000 characters per stream and adds
  start/end offsets, returned slice lengths, next offsets, and the cap. A null next offset
  means finished; passing a stream's total skips it while continuing the other.
- Non-integer, boolean, negative and past-end offsets refuse. Equal-to-total offsets return
  an empty terminal slice. Registry authorization, immutable source, per-pin human overrides,
  provenance metadata and engine operations remain unchanged. Repair/source-readiness skills
  now describe continuation and distinguish source access from targeted edit capability.
- Separate limitation remains: unbound anchor attributes have no structured captured-source
  edit tool. Raw `repair_cloned_section` and registry `mint_repair` require complete HTML/CSS;
  `css=None` selects typed authoring, not CSS preservation. `patch_web_page` only patches a
  rejected authored submission. Pagination therefore does not make a two-link edit requiring
  195k CSS economical. Preserve supported native edits and report uneditable links honestly;
  no renderer, URL normalization, slot cardinality or mutation API changes in this pass.
- Verification: 16 new cases failed against the original tool; existing inspection passed.
  All 78 cloned-section and skill-family tests passed after the fix, including Unicode exact
  reassembly at 42,268 HTML / 195,384 CSS characters, the fixed cap, invalid/terminal offsets,
  unchanged documents/registry, unavailable-workspace source refusal, and human overrides.
  `git diff --check` passed. Ruff has no new diagnostics (source 283, tests 3, all pre-existing).
  No provider/network calls, live state edits, worker restarts, pushes, or live model behavior
  validation. Parent reviewed the production diff; local commit is scoped to this note, the
  tool, its tests, and the two relevant skills.
