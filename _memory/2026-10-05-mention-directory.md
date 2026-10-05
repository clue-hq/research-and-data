# 2026-10-05 — @ tagger: hot-loaded mention directory (rides PR #104)

Branch `fix/deploy-self-update-design-failure-reason` (same PR as the design-workspace fix).

## Problem
The composer's @ tagger only offered the workspace's 50 newest accounts (each with its committee),
filtered in the browser — `list_composer_context_entities` is bounded and ran one committee query per
account. Any older account (e.g. Atrium, 66th newest of 75) could not be tagged whatever was typed.

## What shipped
- Backend `platform/api/clue_api/chat/mention_directory.py`:
  - `GET /api/v1/mention-directory?project_id=` returns every lens account plus its ARV2 committee
    contacts, names and ids only. The reads are fixed: accounts, one batched committee call and one
    batched logo call.
  - Project accounts come first, then newest. Strong `ETag` with `Cache-Control: private, no-cache`;
    `If-None-Match` gets a bodiless 304. A foreign or system project gets 404 `PROJECT_NOT_FOUND`.
  - Above `CLUE_MENTION_DIRECTORY_MAX_ENTRIES` (default 5000; in `.env.example`) the list is cut,
    keeping project accounts, and marked `complete=false`.
  - `GET /api/v1/mention-directory/search?q=` (2–60 chars) does ILIKE on name/domain plus committee
    contacts by name, workspace-scoped, limit 20.
- `gather.committee_members_for_accounts` batches the committee rule for N accounts (or the whole
  workspace with `None`). `committee_members` and `list_composer_context_entities` now use it, so the
  composer listing is no longer N+1. `ACCOUNT_LENS_FILTER` is now public in
  `frontend_read/accounts_list.py`.
- BFF:
  - forwards `if-none-match`;
  - the `/api/clue/[...path]` proxy returns a null body for 101/204/205/304 (a Response with a body
    on 304 throws).
- Frontend:
  - `data/mention-directory.repository.ts` (304-aware);
  - `model/mention-directory-store.ts` (session cache, shared in-flight request, last good directory
    kept on failure);
  - `model/mention-remote-search.ts` (120 ms debounce, aborts the stale request, local matches first);
  - `hooks/use-mention-directory.ts` (revalidates on mount and on focus, at most every 30 s; server
    hits accumulate for the session so a picked hit keeps resolving by id).
  - Wired into all three composers:
    - chat surface: catalog built from directory entities; the controller now orders the catalog first;
    - Home: `controller.mentionEntities`;
    - project overview: `c.mentionEntities`.
  - The editor calls `onMentionQueryChange` only when the directory is incomplete.

## Verification
- Backend:
  - `tests/api/test_mention_directory_db.py` (7) and `test_mention_directory_routes_db.py` (3);
  - 335 related tests green on `clue_dushanbe_test`: gather, page, composer, home bootstrap,
    context refs, D2 submission, attachment presentation, design-leg failure reason, env-parity suites.
- ruff and mypy are clean on touched files.
- Frontend:
  - 9 new node:test cases; 581 projects/chat-shell/auth tests green;
  - the gate `design-system:build && lint && build` is green.
  - `tsc --noEmit` shows 58 pre-existing errors, all in untouched test files.

## Owed
- A live check in the deployed app: type `@Atr` in a project chat and confirm Atrium is offered.
- The incomplete-directory path has not run against a real >5000-entry workspace.
- `shouldAutoCloseMention` can close the picker on a spaced query before server hits arrive. This
  matters only for incomplete directories.
