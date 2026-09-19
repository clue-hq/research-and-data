# Persistent project and chat names — 2026-09-12

Founder requested durable chat rename verification and a project Rename action in the sidebar.
This explicitly authorizes the missing project-label write; no other project lifecycle mutation.

- Chat rename already invokes rename_thread@1 and saves agent_thread.title. Its controller
  missed catalog invalidation, leaving the sidebar stale; now uses the saved response and
  invalidates the shared catalog after success.
- Project name was fixture-only local state. Added PATCH /api/v1/projects/:id {title} through
  project.write and the toolbelt's rename_project@1, with workspace-scoped spine update.
  Label only, trimmed 1–200 characters, no migration or agent-profile permission expansion.
- Repository and Zod seam, live Rename project menu/dialog, saving/error states, duplicate-save
  guard, preserved failed draft, server-confirmed labels and catalog refresh. Fixture mode
  explicitly refuses this write. No localStorage title or pretend successful write.
- Runtime remains Semarang :3040/:8070/:8071, clue_semarang, own Redis. Other workspaces untouched.
- In progress: isolated backend tests, frontend gate, live browser/DB persistence proof.

## Closing verification

- Live signed-in browser: changed project and chat labels, verified the sidebar, chat header and
  gallery, reloaded the page, then opened a fresh tab and read both names. Independent Postgres
  reads confirmed both writes. Restored both original names through the UI and verified SQL.
  No conversation messages, project associations or contents changed; no provider run started.
- A catalog refresh originally collapsed the tree. Preserve each project's local expansion while
  replacing server-owned labels/conversations. Verified the sidebar stays expanded after saves.
- Rename dialog now uses the installed Base UI Dialog for modal focus handling. Blank input
  disables Save; saving disables dismissal and repeated writes; failed writes keep the draft.
- 30 frontend tests pass; design-system build, ESLint and production build pass. Only the two
  pre-existing canvasOperations unused-function warnings remain.
- 57 backend/registry/authority tests pass on the empty clue_semarang_rename_test database.
  One existing design-profile model expectation fails independently (configured model differs
  from the expected model); reproduced with the unchanged HEAD test, then deselected for the
  final run. No model config was changed. Explicit inventory checks now include rename_project,
  with an empty agent-role grant. Test database removed after verifying no active connections.
- Test setup corrections: permission constant imports from chat.principal; sidebar fixture must
  be active; exact registry name/version inventory counts updated in all assertion sites.
- Automatic approval review rejected reading test credentials from dev_stack.sh for a separate
  browser login. Did not retry credential access: used the user's already authenticated browser
  and fresh server reads instead. A new authentication-session login was not tested.
- Restarted only the verified Semarang platform API. Its initial graceful shutdown waited on
  long-lived SSE connections; stopped that owned process group after timeout and relaunched.
  Final API PID 52408. Design/frontend/workers retained their PIDs. Three pre-existing sibling
  server PIDs were verified unchanged. User's original project chat remains open on :3040.
