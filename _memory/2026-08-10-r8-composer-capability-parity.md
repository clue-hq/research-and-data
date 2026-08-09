# 2026-08-10 — R8 composer capability parity

## Scope

- Implemented repair Slice R8 only on `platform/lane-d-chat-launch`.
- Preserved the unrelated untracked `.artifacts/` directory and did not begin
  any later repair slice.
- Used the founder's R8 model ruling: keep one visible selector whose sole real
  option is GPT-5.6 Terra.

## Decisions and changes

- Added migration `39513bbba38a` with nullable immutable
  `agent_turn_submission.agent_profile_id` and ordered append-only
  `agent_turn_submission_context_ref` rows. The new table is workspace-anchored
  to the submission and accepts only account/contact object kinds.
- Home and project reads now advertise a real Lane-C-backed account/contact
  catalog, context-ref capability, and one promoted profile:
  `head-of-abm@v23` / `openai/gpt-5.6-terra` / `GPT-5.6 Terra`.
- Home bootstrap and ordinary message submission validate tenant ownership,
  current revisions, duplicate refs, and contact/account relationships before
  writing. Exact idempotent replay compares message, profile, and ordered refs.
- The detached project-conversation worker rehydrates submission refs into
  `AgentTurnRequest.focus_refs` and verifies the persisted profile id against
  the promoted profile before execution. Retry copies both values.
- L5 focus assembly now prefixes stable keys with the durable ordinal, so the
  assembler's canonical sort preserves the user's submitted ref order.
- Transcript projection batch-reads submission refs and exposes them as the new
  user-message `context` flavor. The frontend schema and transcript render the
  ordered `@entity` details after canonical message materialization/reload.
- Home and project composers submit ordered refs separately from prompt text.
  Duplicate-request fingerprints and Home retry identity include refs and the
  profile, and the Home controller retains the complete current draft while a
  request is in flight.
- The model picker renders the selected profile too, so the one-option picker is
  not empty. It shows exactly one checked GPT-5.6 Terra entry.
- Attachments remain unsupported: backend reads advertise false, attempted
  receipts return `409 CAPABILITY_UNAVAILABLE`, project HTTP mode has no
  control, and Home structurally withholds the timer/object-URL fixture handlers
  in HTTP mode. The simulation remains fixture-only.
- Updated the executable projects contract and Lane-D charter amendment with
  the implemented R8 behavior.

## Verification

- `alembic heads` — one head: `39513bbba38a`.
- Applied `18541ff11335 -> 39513bbba38a` to isolated local database
  `clue_r2_damascus_20260810`.
- R8 backend/API/projection target set — 13 passed, including Home/project
  reads, Home and ordinary submissions, ordered durable receipts, transcript
  rehydration, profile/catalog alignment, and L5 order.
- R8 pure validation target set — 4 passed, including stale/duplicate refs and
  contact/account relationship mismatch.
- Frontend `npm test` — 134 passed, 0 failed/skipped.
- `npm run lint` — pass.
- `npx tsc --noEmit` — pass.
- `npm run design-system:build` — pass.
- `npm run build -- --webpack` — pass: compilation, TypeScript, 8/8 static
  pages, optimization, and trace collection. The existing parent-lockfile
  workspace-root warning remains informational.
- Python `ruff check` and `git diff --check` — pass.
- A broader existing registry test still hard-codes retired
  `stage0-interview/v9`; that unrelated assertion fails independently. R8's
  focused promoted-profile/model assertion passes and no unrelated registry
  path was changed.
- React best-practices review: components remain transport-free; no fetch
  waterfall or global listener was added; timers/object URLs are cleaned up and
  cannot be reached in HTTP mode; draft identity is updated at event boundaries
  rather than synchronized through a derived-state effect.

## In-app browser evidence

- Authenticated Home loaded one visible `GPT-5.6 Terra` selector. Opening it
  produced exactly one checked menu option with the governed profile
  description.
- Home showed one real seeded account from the isolated database,
  `R8 Browser Northstar Labs`; selecting it created an atomic Home submission
  and navigated to real project `prj_944866573d5d59f6bdb9adea88fb294c`
  with thread `thr_c6ce81429bf45e2ba19a7fde62f8747a`.
- Direct database evidence for browser turn
  `76486da5-d9da-5a81-9b45-334d8f12abf1` recorded
  `agent_profile_id=head-of-abm@v23` and ordinal 0 account ref
  `8a8a8a8a-0000-4000-8000-000000000801`.
- After a cold reload, the project composer still exposed one checked Terra
  option and one context control, exposed zero attachment controls, retained
  the real project/thread URL, and reconstructed the durable queued state.
- Browser diagnostics contained no application error. Only the expected Clerk
  development-key warning and dev/HMR information were present.
- The deliverable browser tab was finalized on the real R8 project and empty
  Gallery.

## Closing state

- Backend is running on port 8000 against the isolated verification database;
  frontend development server is running on port 3000.
- R8 implementation, contract updates, tests, browser evidence, and this note
  are ready for one focused local commit. No remote push was performed.
