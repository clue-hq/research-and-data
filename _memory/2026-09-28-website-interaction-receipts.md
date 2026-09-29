# Website interaction observations — 2026-09-28

- Continued priority one from the cross-run audit with offline implementation.
  No app generation, paid provider request, ingestion, database mutation,
  service restart, live page edit or push. Wider quality goal remains active.
- New `lumen_agent/tools/web_interaction_capture.py` observes actual clicks on
  native tabs and eligible captured CSS-radio image groups at desktop/phone.
  Selected controls/panels, loaded visible media, finite transition settling,
  Tab entry and left/right keyboard selection/media changes are checked.
  Each successful state gets a component-region image. Source mapping,
  normal-motion timing and full accessibility remain unverified.
- Bounds: two eligible groups, four states per group, two widths; explicit
  failures and omissions. Form controls are skipped. Other custom control
  patterns are not automatically discovered. Existing dialog/accordion/nav
  captures still force state and do not prove trigger/controller behavior.
- `web_substrate.py` now plans only reachable nodes on the active page,
  checks rendered tab count against the document, preserves observations and
  failures through unchanged-render reuse, review evidence and final result,
  and clears state metadata on page changes. No new publication/readiness gate.
- Updated the existing motion/review skill references to describe actual
  capabilities and limits. No new skill family or brand-specific rule added.
- Regression sequence: the first sandboxed Chromium launch failed on macOS
  process permissions; escalated local fixtures blocked browser networking.
  Six old-behavior regressions failed then passed. Additional red cases exposed
  missing tab count, unsettled transitions and silently skipped forms. A
  supervised read-only review exposed keyboard media false positives, nonzero
  default selection, repeated image sources and skipped forms consuming budget;
  all four were reproduced before fixing. Final focused check: 126 tests passed
  in 218 seconds across `test_web_interaction_capture.py` and
  `test_web_substrate.py` (repository venv, design-root PYTHONPATH, `-o addopts=''`,
  isolated `/tmp` basetemp). Scoped Ruff error/import checks and diff whitespace
  checks passed. Second read-only review found no new blocking defect; its
  skill-reference comprehension check retained keyboard/source/motion gaps and
  rejected repeating an unchanged render as new evidence. That is not a live
  design-agent quality evaluation. Media fingerprints identify source URLs,
  not image bytes or pixel differences.
- Preserve unrelated research tests, older acceptance/import memory and the
  pre-existing edit to the earlier single-run audit. No engine source changed;
  no wasm rebuild needed. Commit only this checkpoint's explicit paths.
- Still owed: source typography/media composition fidelity, bounded source
  content edits, purposeful research-to-copy/CTA planning, retrieval/continuity
  improvements, and native visual acceptance after the user permits another run.
  These tests establish observation behavior, not improved page aesthetics.
- Closing state: coherent offline runtime/reference checkpoint ready for local
  commit on `codex/design-agent-v1`; no remote publication or fresh page run.
