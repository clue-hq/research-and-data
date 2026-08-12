# FI-2 Slice 9B — selected Accounts/Contacts to project chat

Date: 2026-08-13
Branch: `platform/fi2-accounts-cutover-2`
Owner: FI-2 / Bangui

## Ratified product contract

- Account and Contact tables offer `Add to chat`; they do not add direct Research Account or
  Research Contact buttons.
- The user chooses a project and an active existing chat or creates an idempotent new chat. There
  is no extra confirmation for the transfer.
- The table action only prepares an unsent draft. It performs no research, project-membership
  mutation, provider call or spend.
- Names/chips are presentation. Ordered workspace-scoped entity ids, object types and canonical
  versions remain the authority through the existing composer reference and turn-submission path.
- References belong to the next accepted message only. A failed submission preserves the draft;
  successful acceptance clears the draft/handoff while history retains the submitted refs.
- The originating selection clears only after the browser can read back the safely stored handoff.
- Maximum Account or Contact chat handoff: 100. Contact email lookup remains independently capped
  at 20.

## Implementation

- Frontend-read capability payloads now advertise `addToChat` only when live chat is composed and
  the principal has `thread.write`.
- `POST /api/v1/projects/{projectId}/composer-context/prepare` validates project/thread tenancy,
  active-thread state, exact refs and current revisions, then hydrates display-safe Account/Contact
  labels without depending on the bounded mention catalog. It writes nothing.
- The destination chooser reads the complete cursor-paginated sidebar catalog, prepares refs before
  navigation, and creates a new thread under one retry-stable idempotency key only when requested.
- A 30-minute `sessionStorage` handoff is addressed by an opaque UUID. The URL contains only project,
  thread and handoff ids. Transfer errors leave table selection intact.
- The project controller restores the handoff after hydration. Slate synchronizes external refs into
  visible chips. Turn submission returns a typed accepted/failed result, and draft cleanup runs only
  after the durable `202` acceptance.
- `head-of-abm@v24` pins `account-deep-steering@v4` and the new governed
  `launch_selected_account_research@1` tool. With budget controls disabled, an explicit current
  message can confirm and launch its exact ordered Account refs without another confirmation turn.
  The server derives the human/member receipt, verifies `research.launch`, project run and latest
  directive, computes the estimate, and refuses widening, duplicates, Contacts and cross-turn use.
  When budget controls are enabled, the normal durable gate and `launch_account_research@1` remain
  mandatory.

## Verification so far

- Frontend: `npx tsc --noEmit`, `npm run lint`, 183 unit tests, design-token build and optimized Next
  build pass. The sandboxed Turbopack build stalled; the same build completed successfully outside
  the sandbox in 3.1 seconds.
- Backend static/focused: Ruff passes; 49 profile/tool/catalog/steering tests pass (five unrelated
  DB cases skipped in that provider-free run).
- Fresh database `clue_fi2_slice9b_20260813`: seven composer-context/bulk-action cases pass, followed
  by an expanded 12-case matrix covering current v24 Home/project surfaces, ordered durable turn
  refs, preparation and existing bulk actions.
- The pre-existing database on port 55040 carried another worktree's Alembic revision
  `da5f3fe5a90f`; it was not changed. Database tests use the separately named disposable database.

## Browser acceptance

- Pending final authenticated rerun after restarting the local API with chat enabled. The first
  reload correctly failed closed against the stale pre-9B API payload by hiding selection rather
  than assuming capability. API restart then expired the server session; sign-in is required before
  the Account and Contact handoff journeys can finish.

## Follow-ups outside Slice 9B

- Contact deep research remains separately governed; attached Contact refs never authorize Account
  research.
- The deferred React-only New Account control is unchanged.
- Project-scoped actions may still refuse a discussion-only Account that is not eligible for the
  destination project; `Add to chat` never silently adds membership.
