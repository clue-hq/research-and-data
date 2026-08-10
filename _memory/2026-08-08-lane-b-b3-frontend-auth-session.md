# Lane B B3 — frontend authentication and session boundary

Date: 2026-08-08
Branch: `platform/platformlane-b-auth`

## Shipped

- Added Clerk's Next.js provider and proxy behind the same default-off `CLUE_AUTH_ENABLED` switch;
  enabled mode refuses missing provider/API configuration instead of entering keyless mode.
- Moved every existing product page under a protected route-group layout while preserving its URL.
  Disabled auth still renders the fixture-backed frontend; enabled auth resolves the current Clue
  session and selected workspace before rendering product pages.
- Added custom sign-in, recovery-through-Clerk, sign-out, and internal access-denied surfaces.
- Added strict Zod session/principal wire schemas, an HttpOnly workspace-selection cookie, and a
  Server Action that re-authorizes membership before changing the selected workspace.
- Added `/api/clue/[...path]` as the same-origin browser BFF. It obtains the short-lived session JWT
  server-side, replaces browser-controlled authority headers, forwards only narrow request/response
  header allowlists, rejects non-same-origin mutations and dot-segment paths, and streams the
  backend response.
- Preserved the legacy accounts HTTP-adapter variables because their removal belongs to B5.
  No account/project presentation component or backend `frontend_read/**` code was changed.

## Verification

- Frontend ESLint: green.
- `next typegen` plus TypeScript `--noEmit`: green.
- All frontend tests discovered recursively: 32 passed.
- Design-system build plus Next.js production build: green; all application routes are dynamic and
  the Next.js 16 proxy is compiled.
- Build/test ran without Clerk credentials and made no live provider call.

## Limits / follow-up

- No Clerk application keys are present, so live sign-in/recovery/session acceptance remains an
  environment-specific gate rather than a claimed result.
- Auth remains default-off and the older trusted-header adapters remain available until B5.
- B4 must add the provider-neutral principal-to-`ToolContext` audit seam; it must not thread Clerk
  identifiers or SDK types into toolbelt/domain code.
