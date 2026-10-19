# Native glyph-font evidence — 2026-09-28

Branch: `codex/design-agent-v1`. Goal remains active and unqualified. Preserve the
user's no-new-generation restriction. No live workspace, DB, ingestion, service,
provider/model call or remote publication changed during this checkpoint.

- Added bounded actual font-usage receipts to the existing preview/layout path;
  computed CSS aliases alone were insufficient to diagnose saved typography drift.
- Chromium reports family/PostScript names and glyph counts for captured text.
  Max 48 distinct visible text owners, four fonts per owner, two-second budget
  checked between protocol calls. This is not a hard transport timeout.
- Nested owners share receipts; sampling gives later sections a turn before more
  text in the first. Capture-local owner IDs are not engine edit IDs. Unknown,
  hidden, stale and omitted evidence stays explicit. No automatic font repair.
- Existing source/product skill guidance uses those measurements and keeps
  source-file identity, variation/synthetic-weight fidelity and aesthetics open.
- Held local fragment/compose replay used 20 existing assets and zero external
  requests. It reproduced different actual regular versus medium font faces and
  source/authored size differences; 32 owners measured in 56–105ms. This is saved
  artifact evidence, not acceptance of a current native page or a latency promise.

Verification: initial sandbox Chromium launch failed on MachPortRendezvous
permissions; approved offline browser rerun reached intended red assertions.
Font tests passed after implementation. Read-only review found duplicate nested
owners wasting the probe budget; a regression failed before the dedup fix and
passed after. Full focused layout/font file: 20 passing cases. Skill loading:
12 passing. Extended native capture/view case passed separately after its added
glyph assertions. Scoped Ruff and whitespace checks passed. Pytest warned about
cleanup of old temporary directories; test exit status was zero and unrelated
temporary files were left alone.

Closing state: ready for scoped local commit, no push. Preserve unrelated account
display tests and prior working-tree notes/audit edits. Remaining work includes
asset-pixel classification/framing, source behavior preservation, retrieval and
continuity, and eventual native quality review when a new run is authorized.
