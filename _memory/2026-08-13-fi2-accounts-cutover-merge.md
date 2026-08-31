# 2026-08-13 — FI-2 accounts/contacts cutover merged into pilot controls

Branch: `platform/pilot-budget-controls`.

## Merge

- Merged the exact live tip of `platform/fi2-accounts-cutover` with an explicit merge commit
  `8bd70ca9` (`merge: integrate FI-2 accounts and contacts cutover`).
- The source branch advanced during the pre-merge inspection: it was first observed at `2fb7d63f`,
  then was fast-forwarded and pushed to `543fd52e` by merging the former
  `platform/fi2-accounts-cutover-2` tail. `git ls-remote` confirmed `543fd52e` as the live tip before
  the merge, so the merge follows the exact branch the founder named.
- The current branch was the source branch's direct ancestor. The merge had no conflicts, and the
  merge commit's tree is byte-identical to its FI-2 second parent.
- Preserved the pre-existing unstaged `.env.example` addition for
  `CLUE_VALUE_NARRATIVE_SYNTHESIS_ENABLED=true` through a path-scoped stash and restored it after
  the merge. It remains unstaged and is not part of either integration commit.
- Nothing was pushed.

## Integration correction

- This checkout's pinned Ruff formatter found two incoming test files unformatted:
  `tests/agents/test_tool_authority_audit.py` and
  `tests/api/test_selected_account_research_tool.py`.
- Applied only Ruff's mechanical line wrapping; no test behavior changed.

## Verification

- Alembic: exactly one head, `fdb5f0eb3b0e`.
- Frontend: 185/185 tests pass; ESLint passes; design-system token build passes; optimized
  `next build --webpack` passes compilation, TypeScript, nine static pages, optimization, and trace
  collection. The build retains the known multiple-lockfile workspace-root warning.
- Python: Ruff format/check pass across the repository; mypy passes across 636 source files; all 25
  import contracts pass.
- Focused FI-2/tool/catalog/composer/email/provider suite passes; database-gated cases skip when no
  isolated test database is selected. The two reformatted test files pass together (6 cases).
- An initial sandboxed frontend test attempt failed before test execution because `tsx` could not
  create its local IPC socket (`EPERM`). The exact command passed outside the restricted sandbox;
  this is an execution-environment limitation, not a product/test failure.
