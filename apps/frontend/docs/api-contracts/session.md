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
memberships[]: membership_id, workspace_id, workspace_name, role_key, permissions[], workspace_logo_url?
```

`workspace_name` is the workspace's display name and is required on every membership: it is
the only workspace value a person is ever shown. The id stays a routing key and a cookie
value and never reaches a screen — not in the post-sign-in chooser, not in the sidebar
switcher.

`workspace_logo_url` (added 2026-09-30) is the company's logo for the sidebar workspace switcher:
Brandfetch's embed-only Logo API mark (`https://cdn.brandfetch.io/…`, square icon, lettermark
fallback) for the website given at onboarding — the sign-up website, else the latest brand
onboarding's domain. `null` (or absent) when there is no website or no Brandfetch client id; the
switcher then shows the workspace's initials. The browser loads it directly (`unoptimized`).

`GET /auth/v1/principal` additionally requires `X-Clue-Workspace-Id` as a selector. The backend
accepts it only when the resolved Clue user has a current active membership and returns the closed
internal principal. The selected workspace is stored in the HttpOnly, SameSite=Lax
`clue_workspace_id` cookie; changing it calls `/auth/v1/principal` before setting the cookie.
An absent or stale selection requires explicit workspace selection; it never falls back to a
different active membership. Every BFF request reloads the active membership set. Signing out
erases the workspace cookie before ending the provider session.

## Pinned local comparison instances

For simultaneous local brand reviews, `CLUE_LOCAL_WORKSPACE_ID` and
`CLUE_LOCAL_WORKSPACE_NAME` optionally bind one frontend process to one **existing** workspace.
Both settings default to empty. They require authenticated development mode and an explicit
loopback `CLUE_APP_ORIGIN` port; production or incomplete configuration fails closed.

The server pin precedes cookie selection in the shared session loader. The current identity
must still have an active membership, and `/auth/v1/principal` must return that workspace.
Missing/revoked access fails closed. Browser headers, another tab's cookie, workspace Server
Actions and the selector page cannot change the bound workspace. Both provisioning paths are
disabled because provisioning replay can modify the user's original self-serve workspace.

Each instance uses a port-specific HttpOnly workspace cookie and Next compiler directory.
The browser title and sidebar show the configured brand. The same-origin BFF and the backend's
Clerk authorized-party allowlist must include the exact new loopback origins. Clerk identity
and sign-out remain shared across localhost ports; this isolates workspace selection, not
authentication accounts. Backend/database/storage remain shared behind existing tenancy.

Run `node apps/frontend/scripts/local-workspace-instances.mjs run <manifest.json>` from the
repository root. The local, uncommitted manifest contains an `instances` array of `{name, port,
workspaceId}` objects. The manager refuses duplicate/occupied ports, records only its own PIDs,
keeps separate logs beside the manifest, and supports `status` and `stop` with the same path.

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

### Settings invitation acceptance (2026-09-15)

`/session/establish` now attempts authenticated invitation acceptance before calling the
protected-session DAL, then selects the first workspace just joined. A verified provider session
can accept an invitation before any Clue membership exists. Normal sign-ins also accept pending
invitations addressed to the verified primary email. With no token and invitation delivery
unconfigured, ordinary session establishment retains its previous behavior. See
[Settings contract](settings.md#invitation-acceptance-and-session-establishment) for token,
no-token, error, and profile-seeding behavior.
