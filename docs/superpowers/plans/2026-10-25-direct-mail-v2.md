# Project workspace V2 — corrective implementation plan

The founder's 2026-10-25 correction supersedes the initial broad V2 plan. Email
is owned by another agent; this branch is limited to the project view and its
connection to Direct Mail. No new approval is needed to execute this correction.

## Constraints

- Preserve V1 worktree and server on port 5000. Continue V2 on port 5001.
- Use Clue's existing shell, Satoshi typography, tokens and shared controls.
- Remove custom Email, Analytics, Home and chat screens. Keep project-local
  artifact previews without replacing global Artifacts.
- Frontend only, fictional fixtures, no backend mutations or external publishing.
- Local commits only; do not push or create a pull request.

## Tasks

- [x] Remove V2 email domain/actions/routes and restore original global surfaces.
- [x] Build compact searchable/filterable/sortable project table with bounded pages.
- [x] Add visible-page selection and atomic revision-checked owner assignment.
- [x] Use a 1,000-account fixture with honest research-pending states.
- [x] Connect one account drawer to gift, note, page and ad previews.
- [x] Keep existing Direct Mail review, cost approval and tracking.
- [x] Verify page boundaries, stale writes and preservation of sender identity.
- [x] Inspect browser layout, preview content and off-page selection behavior.
- [x] Complete final gates, update session ledger and commit the correction locally.

## Handoff

See apps/frontend/docs/architecture/direct-mail-v2.md. Local list queries are
explicitly fixture-backed; server pagination and provider integration require a
separate contract review. Continue the existing manual session ledger rather
than the previously runaway workspace helper.
