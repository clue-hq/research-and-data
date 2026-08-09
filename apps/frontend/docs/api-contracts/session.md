# Authenticated session and BFF contract

Status: Lane B B5 cutover-prepared, 2026-08-08; production flip waits for Lane D D5.

## Boundary

Clerk owns sign-in, recovery, sign-out, and the secure browser session cookie. It does not own a
Clue user, workspace, membership, role, permission, or audit identity. The browser never receives
or authors a backend bearer token. Next.js obtains the current short-lived session JWT on the
server and forwards it to FastAPI; FastAPI verifies it independently and resolves it through
`auth_identity` to a Clue `platform_user`.

Authentication remains deployment-default-off until D5 with `CLUE_AUTH_ENABLED=false`. Enabling it
requires `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, and server-only
`CLUE_API_BASE_URL`; missing configuration fails loudly and never enters Clerk keyless mode.

The forwarded token is Clerk's **default session token** — no JWT template. Ratified 2026-08-09
after live validation: Clerk template tokens structurally cannot carry the session-bound
`sid`/`azp` claims the backend requires (and templates cannot set them — they are reserved), while
the default session token always carries both for browser-originated sessions. The backend
therefore verifies signature (RS256 against instance JWKS), `iss`, `exp`/`nbf`/`iat`, requires
`sid`, and enforces `azp` against `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES`; no audience claim
participates in verification (`CLUE_AUTH_CLERK_AUDIENCE` and `CLUE_CLERK_JWT_TEMPLATE` are
retired). This supersedes the earlier template/audience design, which was never validated against
a live Clerk instance and could not have worked in either token shape.

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
The post-sign-in establishment route seeds the first active membership. Every BFF request reloads
the active membership set; an absent or revoked selection falls back to the first currently active
membership and replaces the cookie before proxying. Signing out erases the workspace cookie before
ending the provider session.

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

Production must declare `CLUE_AUTH_ENVIRONMENT=production` and use
`CLUE_PROJECTIONS_AUTH_MODE=authenticated_principal`. Application construction refuses a
production trusted-header resolver or an absent principal service. Local-header tenancy remains a
seeded local/test fixture only. Operational enablement and rollback are documented in
`docs/runbooks/authenticated-principal-cutover.md`.
