# Authenticated session and BFF contract

Status: Lane B B3 as built, 2026-08-08.

## Boundary

Clerk owns sign-in, recovery, sign-out, and the secure browser session cookie. It does not own a
Clue user, workspace, membership, role, permission, or audit identity. The browser never receives
or authors a backend bearer token. Next.js obtains the current short-lived session JWT on the
server and forwards it to FastAPI; FastAPI verifies it independently and resolves it through
`auth_identity` to a Clue `platform_user`.

Authentication remains default-off until B5 with `CLUE_AUTH_ENABLED=false`. Enabling it requires
`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, and server-only `CLUE_API_BASE_URL`; missing
configuration fails loudly and never enters Clerk keyless mode.

## Server session reads

`GET /auth/v1/session` returns only internal values:

```text
user_id
memberships[]: membership_id, workspace_id, role_key, permissions[]
```

`GET /auth/v1/principal` additionally requires `X-Clue-Workspace-Id` as a selector. The backend
accepts it only when the resolved Clue user has a current active membership and returns the closed
internal principal. The selected workspace is stored in the HttpOnly, SameSite=Lax
`clue_workspace_id` cookie; changing it calls `/auth/v1/principal` before setting the cookie.

## Same-origin BFF

`/api/clue/[...path]` is the only browser-facing authenticated transport. It:

- obtains the session JWT with server-side Clerk `auth()`;
- replaces any browser authorization/workspace headers with server-resolved values;
- never forwards browser cookies, backend `Set-Cookie`, or authorization response headers;
- forwards only the method/body plus a small content/idempotency/cursor header allowlist;
- rejects cross-origin or origin-less mutations;
- streams the backend response body without buffering it;
- returns `AUTHENTICATION_REQUIRED` / `SESSION_INVALID` on missing or expired sessions.

The backend remains authoritative. Every protected endpoint must still resolve and authorize a
`RequestPrincipal`; BFF success is not authorization evidence.
