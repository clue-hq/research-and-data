# Google sign-in recovery

- User reported that Continue with Google did nothing on Fresh port 3020.
- Live diagnosis: Clerk retained an expired external-verification attempt. Future
  `signIn.sso()` returned no error within milliseconds, with no redirect URL, and
  our adapter incorrectly reported authentication complete. Email navigation worked.
- Google now reads the live public Clerk client at click time and calls
  `authenticateWithRedirect` with `continueSignIn: false`. Existing callback and
  session-establishment routes remain unchanged. The driver reports redirecting,
  handles unloaded clients, errors and timeout; the button disables while busy.
- Four new provider-boundary regressions failed before the fix and passed after.
  Final verification: 22 focused checks; full frontend suite 3,241 passed, one
  skipped; design-system build, lint and production build passed. Lint has two
  pre-existing unused-variable warnings in canvasOperations.ts. Diff check clean.
- Live normal OAuth completed into authenticated Conduit Fresh Home. No account
  selection, server-token workaround or authentication bypass was needed. Temporary
  sanitized diagnostic logging was removed. No credentials recorded.
- Resumed the one existing queued native website submission via the UI Resume
  button. Read-only audit confirms run_2f33ccf3c9e954e199f7489ea8a961e1 running,
  correct fresh kit v1, two seller logos, ten successful skill reads, project-account
  evidence lookup and captured-section search. Final render/quality acceptance is
  still pending; do not treat skill reads as proof of visual quality.
- Only Fresh 3020 is in scope; legacy workspaces stay suspended. No new chat,
  duplicate generation, discovery, seeding, publishing or remote push.
- Operational failures: first test command needed local IPC permission; rerun passed.
  One edit script used the wrong working directory and made no changes; corrected.

## Closing checkpoint

Sign-in fix verified end to end and ready for local commit. Existing native website
test is running through Clue and remains the next acceptance step. The previous
website artifact is preserved.
