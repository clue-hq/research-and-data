# FI Lane B — authenticated principal, session, and workspace-authorization contract

**Status: FOUNDER-RATIFIED CONTRACT — 2026-08-08.** The production human actor is a real
authenticated Clue user. Clerk is the initial authentication/session adapter only; Clue Postgres
owns every canonical user, workspace, membership, role/permission decision, and durable audit
identity. No Clerk identifier may be a primary key, foreign key, tenancy key, domain-object id, or
authorization decision key in the Clue database. Implementation proceeds as independently
landable B0–B5 slices with the Lane-D join gates in §9.

Date: 2026-08-08. Branch: `platform/frontend-integration`.
Parents: FI-1 §5.3/§9 (D-9 Option B); `FI-lane-D-production-chat-and-launch.md` P2/D1;
`FI-lane-demarcation.md` §2.2. Platform authority: harness REQ-20 (same tools/gates/journal for
humans and agents), Doc A (toolbelt is the only mutation path), Doc M (one user in many workspaces
changes auth, never tenant-local data boundaries).

---

## 0. Contract in one paragraph

An external provider may prove that a browser session belongs to an external subject. It does not
create a Clue actor and it never grants workspace access. The API maps that external subject through
one replaceable `auth_identity` row to a Clue-owned `platform_user`, checks an active Clue-owned
`workspace_membership` and the requested permission in Postgres, then constructs a closed
`RequestPrincipal`. Only internal ids from that principal may enter domain rows, turns, gates,
tool contexts, jobs, or audit receipts. Lane D consumes this principal and derives the exact human
action receipt (`turn-action:<turn_id>`); Clerk never supplies either `actor_id` or `action_ref`.

## 1. Binding rulings

1. **Authentication and authorization are separate.** Clerk answers only “did this external
   subject authenticate in a currently valid session?” Clue answers “which internal user is this,
   which workspace membership is active, and may it perform this operation?”
2. **Clue ids are canonical.** `actor_id = platform_user.user_id`. A human acts in a workspace
   through `workspace_membership.membership_id`. Neither value is an email address, browser string,
   Clerk user id, Clerk organization id, nor token claim authored by the client.
3. **No external foreign keys.** No database foreign key may reference any provider value. No
   domain table may reference `auth_identity.provider_subject`; all relationships reference
   `platform_user.user_id`, `workspace_membership.membership_id`, or another Clue-owned key.
4. **Clerk is replaceable.** Clerk-specific SDKs, token claims, JWKS URLs, cookies, and error shapes
   stop inside the authentication adapters. Replacing Clerk changes adapters and identity mappings,
   not Clue users, workspaces, memberships, threads, gates, claims, runs, or audit history.
5. **Postgres is authorization truth.** An authenticated provider subject with no active internal
   user and active membership has no workspace access. Provider organization membership, metadata,
   roles, or permissions are never sufficient authority.
6. **Workspace selection is not workspace authority.** A route, server session, or request may name
   a target `workspace_id`; the authorizer must still prove an active membership on every request.
   `X-Workspace-Id` may survive temporarily as a selector, never as a credential.
7. **Authority is ambient.** `actor_id`, `membership_id`, permissions, and `action_ref` never appear
   in model-visible tool inputs or caller-authored domain payloads. The server derives and injects
   them after authentication and authorization.
8. **Human and machine principals never impersonate one another.** A worker authenticates as a
   service principal. It may execute an agent turn that carries a persisted human approval receipt,
   but it may not synthesize a human `actor_id` from its own service credential.
9. **Session tokens are transient.** Provider cookies/tokens are validated at request time, are
   never written into domain tables/artifacts/logs, and never become queued-work authority. Durable
   jobs carry internal principal references plus approved action receipts.
10. **Deny by default.** Missing/invalid authentication, unmapped identity, inactive user,
    inactive membership, workspace mismatch, or absent permission refuses the operation before any
    tool call, enqueue, provider spend, or domain write.

## 2. Vocabulary and identity axes

| Term | Meaning | Authority |
|---|---|---|
| external authenticated subject | provider name + opaque provider subject from a validated session | authentication adapter only |
| platform user | durable Clue human identity (`usr_…`) | `platform_user` |
| workspace membership | one user’s active relationship to one workspace (`wsm_…`) | `workspace_membership` |
| request principal | request-scoped, already-authenticated and authorized internal identity | Lane-B principal service |
| actor class | existing effect class: `human` or `agent` (delegated-agent remains journal detail) | tool invocation |
| actor id | durable internal identity responsible for the effect; human value is `platform_user.user_id` | Clue Postgres |
| service principal | internal machine/process identity (`svc_…`), never a human | service-auth adapter |
| action ref | exact durable user action that authorized a gated effect | Lane D (`turn-action:<turn_id>`) |

`actor` and `actor_id` are deliberately different axes. `actor="human"` without a non-null internal
`actor_id` is invalid for a human-gated production effect. A service-authenticated worker executing
the platform deepagent uses the agent actor class and its service/execution identity; a linked human
`action_ref` proves approval without turning the worker into that human.

## 3. Canonical Postgres model

Ids follow the platform spine’s opaque prefixed-text convention. Exact timestamps use the shared UTC
type; names below are the frozen semantic shape, while each slice plan may add operational indexes.

### 3.1 `platform_user`

```text
platform_user
  user_id text primary key                 -- usr_<random>; Clue-owned
  display_name text null
  status text not null                     -- active | suspended | disabled
  created_at timestamptz not null
  suspended_at timestamptz null
  disabled_at timestamptz null
```

No email is a primary/canonical identity key. A verified email may be profile/provisioning data, but
changing or reassigning it does not change `user_id`.

### 3.2 `auth_identity`

```text
auth_identity
  auth_identity_id text primary key        -- aid_<random>; Clue-owned
  user_id text not null references platform_user(user_id)
  provider_key text not null               -- initial value: clerk
  provider_subject text not null            -- opaque lookup attribute
  status text not null                     -- active | unlinked | revoked
  linked_at timestamptz not null
  revoked_at timestamptz null
  unique(provider_key, provider_subject)
```

This is the **only** place an external user identifier is stored for authentication lookup. The
provider value is not a foreign key and no other table may reference it. One `platform_user` may
have multiple identities, permitting provider migration/account linking without changing domain ids.

### 3.3 `workspace_membership`

```text
workspace_membership
  membership_id text primary key           -- wsm_<random>; Clue-owned
  workspace_id text not null references workspace(workspace_id)
  user_id text not null references platform_user(user_id)
  role_key text not null
  status text not null                     -- invited | active | suspended | revoked
  created_at timestamptz not null
  activated_at timestamptz null
  revoked_at timestamptz null
  unique(workspace_id, user_id)
  unique(membership_id, workspace_id)
```

All workspace-owned user artifacts use internal composite foreign keys where locality matters. A
user may hold memberships in many workspaces; no membership grants reads or memory access to any
other workspace.

### 3.4 Provisioning

Clerk does not own workspace invitations or membership creation. A minimal internal
`workspace_invitation` record owns `workspace_id`, invited address/delivery target, `role_key`,
expiry, token digest, and eventual `accepted_by_user_id`. After successful provider authentication,
an invite-acceptance transaction links/creates the internal user, writes `auth_identity`, and
activates `workspace_membership`. The verified address assists that one-time claim; it does not
become the user id or a permanent authorization key.

Self-serve workspace creation, if enabled, creates the Clue `workspace`, internal user mapping, and
owner membership in one transaction. Provider organizations are not required for MVP and never
replace these rows. A future SSO connection may carry an external tenant/config reference inside an
auth-adapter-owned mapping, but no Clue table may foreign-key to it or accept its role claims as
authorization truth.

### 3.5 Role/permission floor

MVP role keys are internal policy inputs, not provider roles:

```text
owner | admin | operator | viewer
```

The authorizer resolves them to versioned internal permissions. Lane D requires at least:

```text
project.read
thread.read
thread.write
gate.respond
research.estimate
research.launch
research.approve_spend
workspace.manage_members
```

UI checks are advisory. Every backend request and every human-only tool boundary re-checks the
required permission. A role/permission policy may become data-backed without changing the principal
contract.

## 4. Provider-neutral seams

```text
Authenticator.authenticate(http_request) -> ExternalSession

ExternalSession
  provider_key
  provider_subject
  provider_session_subject?     -- diagnostic/request-local only
  authenticated_at?
  expires_at

IdentityResolver.resolve(external_session) -> InternalIdentity

InternalIdentity
  user_id
  user_status

Authorizer.require(
  internal_identity,
  requested_workspace_id,
  required_permission,
) -> RequestPrincipal

RequestPrincipal
  principal_kind                -- human
  user_id
  membership_id
  workspace_id
  role_key
  permissions                   -- immutable set for this request
  authenticated_at?
```

Only `Authenticator` is provider-specific. `IdentityResolver`, `Authorizer`, routes, repositories,
toolbelt wiring, and Lane D consume internal ids only. The production Clerk adapter validates the
session/token and returns `ExternalSession`; test and local-development adapters implement the same
contract. A dev adapter is permitted only under an explicit local/test environment guard and must
still resolve a real internal user/membership fixture from Postgres.

## 5. HTTP, frontend session, and token boundary

1. The browser holds only the provider-managed secure, HTTP-only session cookie. Provider access or
   refresh tokens never enter browser storage or application state.
2. Next.js owns sign-in/out, session UX, protected route orchestration, and the same-origin backend-
   for-frontend boundary. A centralized server-only session/DAL helper validates every Server
   Component data request, Route Handler, and Server Action.
3. The BFF obtains a short-lived provider proof and forwards it to FastAPI. The FastAPI
   `Authenticator` independently validates expected algorithm, signature/JWKS, issuer, audience,
   expiry/not-before, authorized party/token type as applicable, then resolves internal identity.
4. The requested workspace comes from the current Clue workspace selection. It is passed as a
   selector and validated against `workspace_membership`; it is never inferred as authorized merely
   because a provider token or cookie contains an organization claim.
5. Native SSE does not place a bearer token in a URL. An authenticated request mints a short-lived,
   single-use, principal/workspace/turn-scoped stream token; the existing replay-token pattern and
   Lane-D turn stream consume it. Expiry/replay cannot extend domain authority.
6. `CLUE_WORKSPACE_ID`/`X-Workspace-Id` remains only for fixtures and explicitly guarded local/test
   operation until cutover. Production startup fails if the local-header resolver is selected.

Frontend placement:

```text
apps/frontend/src/auth/**                    -- server/provider/session adapter
apps/frontend/src/features/session/**        -- session + workspace UI/repositories
apps/frontend/src/app/(auth)/**              -- sign-in/up/callback screens
apps/frontend/src/app/(protected)/**         -- authenticated shell
apps/frontend/src/app/api/clue/**            -- same-origin BFF routes
apps/frontend/proxy.ts                       -- optimistic redirect only; never sole authz
```

Backend placement:

```text
platform/auth/clue_auth/**                   -- internal contracts/repository/authorizer
platform/api/clue_api/auth_wiring.py         -- provider + FastAPI composition
```

No Clerk import is allowed outside the provider/frontend-auth adapters. The toolbelt, agents,
fleet, projections, research, memory, content, and design packages may not import a Clerk SDK or
interpret a Clerk claim.

## 6. Error contract

All surfaces use the shared error envelope and request id. Minimum semantics:

| HTTP | Code | Meaning |
|---|---|---|
| 401 | `AUTHENTICATION_REQUIRED` | no usable session/token |
| 401 | `SESSION_INVALID` | signature/issuer/audience/time/token validation failed |
| 403 | `IDENTITY_NOT_PROVISIONED` | provider subject is valid but no active internal identity exists |
| 403 | `USER_DISABLED` | internal user is suspended/disabled |
| 403 | `WORKSPACE_FORBIDDEN` | no active membership for the requested workspace |
| 403 | `PERMISSION_DENIED` | active membership lacks the required permission |
| 409 | `MEMBERSHIP_STATE_CHANGED` | a submitted gate/action raced a membership/role revision |

Cross-workspace domain-object reads may still return the existing not-found response after the
principal passes workspace authorization, so object existence is never leaked. Client code may use
401 to enter session recovery and 403 to render an access state; it never converts either to an
empty business result.

## 7. Durable actor and async execution contract

At the authenticated HTTP boundary, Lane B creates `RequestPrincipal`. A human turn persists at
least `submitted_by_user_id`, `submitted_via_membership_id`, and `workspace_id` before enqueue. The
queue stores internal ids and immutable operation/turn references, never the provider token.

Lane D derives `action_ref = turn-action:<turn_id>` only after resolving the durable turn in the
same workspace and proving its internal submitter/membership. Gate answering re-checks the current
membership, gate addressee, permission, expected subject digest/revision, and estimate before
closing the gate. `ToolContext` then receives:

```text
workspace_id = RequestPrincipal.workspace_id
actor = "human"                         -- for the human-only confirmation effect
actor_id = RequestPrincipal.user_id
action_ref = "turn-action:<turn_id>"    -- Lane-D derived, never client supplied
```

Detached workers authenticate as service principals. They execute under their agent/service
identity and carry the already-persisted `action_ref`/approval references as evidence; an expired
browser session does not erase a committed approval, and a service credential does not become the
human approver.

## 8. Parallel ownership and file treaty

After this B0 contract, Lane B and Lane D run concurrently.

**Lane B owns:** `platform/auth/**`, auth migrations and internal user/membership CRUD,
`platform/api/clue_api/auth_*`, `apps/frontend/src/auth/**`,
`apps/frontend/src/features/session/**`, auth routes/proxy/provider wrapping, and the generic
principal-to-`ToolContext` seam. It also retains demarcation defects L3/L4.

**Lane D owns:** thread/turn/gate/event-stream domain implementation, `AGENT_TURN`,
turn-derived `action_ref`, the project-chat HTTP/stream repositories, and
`apps/frontend/src/features/projects/**` + `api-contracts/projects.md`.

**Named shared-file holders:** Lane B owns auth provider wrapping in `app/layout.tsx`, the auth SDK
dependency in `package.json`, and generic BFF/session helpers. Lane D calls those helpers and owns
project-specific route/repository code. Both add registration calls only at API composition roots.
`apps/frontend/src/features/accounts/**`, `api-contracts/accounts.md`, `frontend_read/**`, FI-2
membership (`project_account`), and FI-2 run-lineage/economics remain outside both lanes.

## 9. Slices and Lane-D join gates

- **B0 — this contract.** Freeze ids, tables, seams, provider boundary, errors, ownership, and
  acceptance matrix. No runtime implementation.
- **B1 — internal identity substrate.** Tables/models/CRUD for user, identity mapping, membership,
  invitation/provisioning; initial permission policy; DSAR/disable/revocation behavior. Must land
  before Lane-D D0’s `thread.created_by`/membership FKs.
- **B2 — backend authentication/authorization.** Provider-neutral service + initial Clerk adapter,
  FastAPI dependency, membership/permission enforcement, production refusal of local headers.
- **B3 — frontend session/BFF.** Login/logout/recovery, protected shell, workspace selection,
  server-only session DAL, authenticated BFF and session-expiry states.
- **B4 — actor/tool integration.** Thread internal actor ids through audited `ToolContext` sites,
  human-only tool enforcement, service-principal separation, durable audit fields.
- **B5 — cutover and adversarial acceptance.** Remove production `CLUE_WORKSPACE_ID` authority,
  cross-workspace/revocation/provider-swap tests, run operational docs and full gates.

Parallel execution:

```text
B0
 ├─ B1 → B2 → B4 ───────────────┐
 └─ Lane D contract/UI/streaming │
          D0 after B1            ├─ D1 join → D4 launch → D5 production flip
          D2 with test principal │
          D3 mostly independent ─┘
 B3 runs in parallel and joins D5
```

Lane D may use a deterministic injected test `RequestPrincipal` while B2/B3 are in flight. It may
not invent temporary user headers inside domain code or claim production acceptance before the
named join gates.

## 10. Acceptance matrix

1. **No-provider-FK static gate:** schema inspection finds no PK/FK/domain reference to
   `provider_subject`, Clerk ids, provider organizations, emails, or token/session claims.
2. **Provider-swap continuity:** linking a second provider identity to one `platform_user` changes
   no workspace membership, thread, gate, action, run, or audit foreign key.
3. **One user, two workspaces:** the same user can enter both through distinct memberships; a
   principal for W1 cannot read, stream, gate, or launch in W2.
4. **Two users, one workspace:** both authenticate separately; a gate addressed to U1 cannot be
   answered by U2 without an explicit reassignment record and permission.
5. **Revocation:** revoking membership immediately blocks new reads/writes/gate answers despite a
   still-cryptographically-valid provider token.
6. **Disabled user:** disabling `platform_user` blocks every provider identity linked to it.
7. **Token failures:** expired, wrong issuer/audience/authorized-party, unknown signing key, and
   malformed tokens fail before DB/domain/tool work; secrets/tokens never appear in logs.
8. **Ambient-authority negative:** client/model payloads have no `actor_id`, `membership_id`, or
   `action_ref`; attempts to add them are rejected/ignored at the schema boundary and cannot alter
   receipts.
9. **Async separation:** a service worker can resume an authorized turn after browser disconnect or
   session expiry, but cannot fabricate a new human approval or answer a gate.
10. **Workspace-selector negative:** changing `X-Workspace-Id`, route workspace, or client state to a
    non-member workspace returns `WORKSPACE_FORBIDDEN` and performs zero writes/spend.
11. **Frontend session:** cold load, expiry, logout, workspace switch, and revoked membership
    produce deterministic UI states; no token is readable through browser JavaScript storage.
12. **Lane-D receipt:** one approved two-account fixture persists internal `confirmed_by`,
    membership, `turn-action:<turn_id>`, directive/estimate digests, and launcher `approval_refs`;
    replay is byte-identical and another user/workspace cannot reuse the ref.

## 11. Explicit non-goals and later extensions

- Building passwords, MFA, recovery, or cryptographic session issuance inside Clue.
- Making Clerk Organizations the workspace store or Clerk roles the permission store.
- SCIM/directory sync, custom enterprise roles, step-up authentication, device posture, and
  customer-managed keys in B0–B5. The internal ids/seams must allow these later without migration of
  domain ownership.
- Rewriting FI-2’s accounts read contract while its owner is active. Lane B supplies the auth
  dependency; FI-2 (or a later integration slice after handoff) performs that surface’s cutover.

---

*Ratification log: 2026-08-08 — founder selected a real authenticated user principal for Lane-D
approvals and required strict provider independence: Clerk performs authentication/session proof
only; Clue Postgres owns users, workspaces, memberships, permissions, and every relationship; no
Clerk value is a foreign key.*
