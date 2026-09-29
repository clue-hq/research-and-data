# Miscellaneous section integration — 2026-09-27

User approved Miscellaneous on account Insights and contact pages after accepting the narrative
skills. Added owned recipes (positions 6/5), unrestricted and collapsed by default. Existing
generic frontend ResearchDocument/ResearchStack already render these sections with source controls;
added honest empty sections to account and all contact fixtures. No new API payload shape or
component-specific rendering. Overview remains unchanged.

read_narrative_inputs now offers the new recipes; owner narrative writes persist them through the
existing scoped finding-to-claim resolution and page storage. Legacy section prompt table also
covers both keys. Additive optional-key handling permits older/in-flight drafts without Miscellaneous;
missing optional blocks display an honest empty message and do not trigger perpetual refresh.
Saved Miscellaneous blocks still participate in invalidation. Recipe version remains 1 so this
addition does not globally invalidate old narratives. Startup seeds new recipes; no application
DB writes or service restarts were performed.

Verified full display suite plus quality-owned narrative and quality page DB suites against
clue_miscellaneous_verify_20260927, with one paid/live test skipped. Additional compatibility tests
passed for account/person missing sections; scripted native researchers publish both new sections.
Frontend 8 focused tests passed; design-system build, lint (2 pre-existing unused-variable warnings
in design-editor canvasOperations), and Next production build passed. Ruff/diff checks passed.

Browser check used real production React components with exported synthetic test-DB blocks and
evidence in a temporary localhost harness. Initial harness-only failures: missing Next env defines,
and root React 18 vs frontend React 19 resolution; corrected harness bundling. User requested
OpenAI browser-use; final checks used cua_repl. Verified collapsed defaults, mouse/keyboard expansion,
source access, and empty message. No final browser errors/warnings. This is not a full authenticated
app test or a live narrative-quality run. Temporary browser tab/server closed.
Evidence: .artifacts/miscellaneous-integration-20260927/ (test logs, wire payload, harness).
No paid research/model calls, fleet workers, publication, or changes to the accepted skill prose.
