# Settings section — frontend ⇄ backend integration design

**Status:** design for founder review, 2026-09-15. Nothing in this document is implemented.
**Branch:** `research-streaming` (worktree `san-salvador`). **Founder:** Aryan.
**Discussion record:** `_memory/2026-09-14-settings-integration-exploration.md` (committed as `9c1e791f9`).
**Presentation truth:** the co-founder's dummy frontend, served at `http://localhost:3000/settings`,
source at `/Users/aryankeshri/conductor/workspaces/clue-frontend/live-backend-v1` (branch
`integration/live-backend-v1`, commit `64232a0`, 2026-09-13). Its frontend-authored contract
proposal is `docs/api-contracts/settings.md` in that checkout; Figma page `Settings-dev-ready`,
node `1735:38951`.

## 1. What this integrates, and what it does not

The dummy's Settings section has nine screens in two groups. Personal: Profile, Connections, MCP
server. Admin: Workspace, Members, Integrations, Pages, Data model, Billing. This repo's
`apps/frontend` has no settings feature, no `/settings` route, and no profile menu in the sidebar
(`/settings` on the lane frontend is a 404). Every screen is lifted from the dummy verbatim and
bound to real data at the repository seam, per `apps/frontend/docs/architecture/frontend.md` and
the presentation-truth rule: no invented screens, no raw backend strings in the UI.

Founder rulings from the 2026-09-14 discussion fix the scope:

| Screen | Ruling | In this build |
| --- | --- | --- |
| Profile | Full name and display name editable; initials avatar, no upload | Yes |
| Workspace | Organization name editable; logo from the brand kit; website read-only | Yes |
| Members | Clerk sends the invitation email; Clue owns the row, the role and the membership; owner shows as Admin; Member is the operator role; row menu with Remove, Revoke invitation, Re-admit | Yes |
| Connections, MCP server, Integrations | Lifted exactly as the dummy's inert "Coming soon" previews | Yes (static) |
| Billing | Stays a dummy | Yes (static, see §8) |
| Pages | Stays a dummy | Yes (static, see §8) |
| Data model | Re-scoped with the co-founder to "Research fields" before anything is wired | No — §9 records the agreed re-scope and the research-side change it needs |

Two cross-cutting rulings apply to every editable field: **autosave on blur** with an ephemeral
confirmation card, and **the sidebar shows the signed-in person's display name**, never a
placeholder.

Two assumptions are carried until the founder says otherwise (they were asked, not yet answered):

- **A1.** The Billing and Pages dummies get the same "Coming soon" overlay the dummy already uses
  for Connections, so fixture numbers ("300 / 500 credits") are never read as real.
- **A2.** The static "Clue workspace" caption under the person's name in the profile menu becomes
  the real workspace name (a data binding into an existing slot).

## 2. Architecture

### 2.1 Where the code lives

**Backend (FastAPI, `platform/api/clue_api`).** One new module `frontend_read/settings.py`
mounted on the existing frontend-read router under `/frontend/v1/settings/*`, so it rides the same
`CLUE_FRONTEND_READ_ENABLED` flag, the same error envelope, request-id and CORS middleware, and the
same workspace resolver the accounts and brand-context reads use. Member-management writes and
invitation acceptance need the auth package; they live in `platform/auth/clue_auth` (store and
provisioning functions already exist) plus one small Clerk backend-API client in
`clue_auth/providers/clerk_api.py`. Invitation acceptance is an auth route
(`/auth/v1/invitations/accept`) next to session, principal and provision in `auth_wiring.py`,
because it runs before the caller has a membership.

**Frontend (Next.js, `apps/frontend`).** A new feature `src/features/settings/` lifted from the
dummy: `components/`, `settings.module.css`, `config/settings-navigation.ts`, and `model/settings.ts`
are copied verbatim, then the model is split per section and `data/` is rewritten as per-section
repositories on this repo's seam (`fetchRead` on the server for reads, `fetchMutation` through the
same-origin BFF for writes; both exist in `features/accounts/data` and are reused, not copied).
The route is `src/app/(protected)/settings/[[...section]]/page.tsx`. The profile menu
(`sidebar-profile-menu.tsx`, `use-sidebar-profile-menu.ts`) is lifted into `components/shell/`.
One new shared component, the confirmation card, goes in `components/ui/`.

### 2.2 Contract shape

The dummy proposes one blob, `GET /api/v1/settings`, with all nine sections inside. This repo
serves per-section reads under `/frontend/v1` and the settings page needs different authority per
section, so the contract is reconciled to per-section endpoints (§3). The resolution is recorded
back into `apps/frontend/docs/api-contracts/settings.md` (a new file in this repo, superseding the
dummy's proposal for these sections).

### 2.3 Authority

Every settings route resolves the request principal the way the other authenticated routes do:
the BFF forwards the Clerk session token and the selected workspace header, the backend verifies
the token and loads the membership, and the route reads the closed `RequestPrincipal`
(`user_id`, `membership_id`, `workspace_id`, `role_key`, `permissions`). Reads require an active
membership. Writes:

| Write | Required |
| --- | --- |
| Edit own profile | any active membership (the row edited is the caller's own user) |
| Rename workspace | `workspace.manage_members` (admin or owner) |
| Invite, change role, remove, re-admit, revoke invitation | `workspace.manage_members`, plus the existing ladder rule: nobody grants above their own rank, the owner cannot be demoted or removed |

A caller without the permission gets `403` with code `PERMISSION_REQUIRED`. The frontend hides
the invite row, the role dropdowns and the row menus for such callers and shows the table read-only.

## 3. Backend surface

All paths below are relative to the API origin. Reads are `GET`; the BFF proxies every method.
Error envelopes follow the frontend-read convention (`error.code`, `error.message`, request id).

### 3.1 Profile

```
GET   /frontend/v1/settings/profile
PATCH /frontend/v1/settings/profile      body: { full_name?: string, display_name?: string | null }
```

Response (both):

```json
{ "user_id": "usr_…", "first_name": "Aakash", "last_name": "Shrivastava",
  "full_name": "Aakash Shrivastava", "display_name": null, "email": "aakash@…" }
```

Source: `platform_user`. `full_name` is first and last joined with one space, either side may be
empty. PATCH semantics are the store's existing uniform PATCH: a field absent from the body is
preserved. `full_name` is split on the **first** space: "Mary Anne Smith" stores first `Mary`,
last `Anne Smith`; a single token stores first only and clears last. `display_name` accepts null
or whitespace to clear. Writes go through the existing `update_platform_user_profile`, which gains
a `last_name` clear path if it lacks one. Job role is untouched: the design has no slot for it.

### 3.2 Workspace

```
GET   /frontend/v1/settings/workspace
PATCH /frontend/v1/settings/workspace    body: { name: string }
```

Response:

```json
{ "workspace_id": "ws_…", "name": "Insight Health AI",
  "website": "https://insighthealth.ai", "logo_url": "/api/clue/design-public/asset-store/<digest>" }
```

- `name` is `workspace.name`. Rename is a new spine function `rename_workspace(conn, workspace_id,
  name)` in `libs/clue-spine`, mirroring `create_workspace` (non-empty, trimmed, max 200). Brand
  rows are untouched: brands are their own concept under the multi-brand model.
- `website` is **read-only** by ruling. It is read from `self_serve_provisioning.company_website`
  by workspace id (the table has a unique workspace constraint). No column is added now; when a
  rebuild-from-new-site flow exists the website gets a proper home on the workspace row. The
  response carries it as a plain string or null; a PATCH that includes `website` is refused with
  `400 FIELD_READ_ONLY`.
- `logo_url` is the primary logo of the latest approved `design_brand_kit` for the workspace's
  provisioning brand (`self_serve_provisioning.brand_id`), served through the existing public
  asset-store proxy the brand-context page already uses; null when no kit or no logo exists, and
  the component then shows the designed briefcase icon. No upload.

### 3.3 Members

```
GET    /frontend/v1/settings/members
POST   /frontend/v1/settings/members/invitations           body: { emails: string[], role: "admin" | "operator" }
DELETE /frontend/v1/settings/members/invitations/{invitation_id}
PATCH  /frontend/v1/settings/members/{membership_id}        body: { role: "admin" | "operator" }
DELETE /frontend/v1/settings/members/{membership_id}
POST   /frontend/v1/settings/members/{membership_id}/readmit  body: { role: "admin" | "operator" }
```

`GET` returns one list, members and pending invitations together, which is what the designed
table shows:

```json
{ "rows": [
  { "kind": "member", "id": "mem_…", "name": "Leila Walker", "email": "leila@…",
    "role_key": "owner", "state": "active", "joined_on": "2025-08-24", "is_self": true },
  { "kind": "invitation", "id": "inv_…", "name": null, "email": "eric@…",
    "role_key": "operator", "state": "invited", "joined_on": null, "is_self": false },
  { "kind": "member", "id": "mem_…", "name": "Omari Norris", "email": "omari@…",
    "role_key": "operator", "state": "removed", "joined_on": "2025-11-03", "is_self": false }
] }
```

- Members come from `workspace_membership` joined to `platform_user`; statuses `active` and
  `suspended` render as `active`, `revoked` renders as `removed` (kept in the list so Re-admit has
  something to act on), `invited` memberships (legacy state) render as `invited`. `joined_on` is
  `activated_at`'s date.
- Pending invitations come from `workspace_invitation` with status `pending` and a future
  `expires_at`; `name` is null and the table shows the address. Accepted, revoked and expired
  invitations are not listed.
- `email` for members is `platform_user.email` (new column, §5). Null renders as an em dash.
- Role keys are served raw. The frontend maps `owner` and `admin` to "Admin", `operator` and
  `viewer` to "Member" (viewer is dormant: never offered, never written). The owner's row is
  `locked` in the frontend by `role_key == "owner"`.

Invite (`POST …/invitations`): for each address, after validation and de-duplication, the backend
(1) creates the Clue invitation row with a fresh random token (only its SHA-256 digest is stored,
as today), role, `invited_by_membership_id`, and `expires_at` 30 days out to match Clerk's
one-month expiry; (2) asks Clerk to send the email (§4). The response lists one outcome per
address: `sent`, `created_no_email` (§4, existing Clerk account), `already_member`,
`already_invited`, `invalid`. Partial success is normal and the frontend shows one card per
outcome class ("3 invitations sent", "1 already a member").

Revoke invitation: `revoke_workspace_invitation` plus Clerk's revoke of the matching Clerk
invitation id (stored on our row, §5). Change role: `change_workspace_member_role`. Remove:
`revoke_workspace_member`. Re-admit: `readmit_workspace_member`. All four exist in
`clue_auth.store` with the actor and ladder checks already inside; the routes only translate
their typed errors to envelopes (`403 PERMISSION_REQUIRED`, `409 OWNER_PROTECTED`,
`409 INVALID_TRANSITION`, `404 MEMBER_NOT_FOUND`).

### 3.4 Invitation acceptance (auth surface)

```
POST /auth/v1/invitations/accept      body: { token?: string }
```

Requires a live Clerk session but **not** a membership, like `/auth/v1/provision`. The backend
resolves the external session (provider subject), fetches the user's verified primary email from
Clerk's backend API (§4), then:

- with a `token`: runs the existing `accept_workspace_invitation(raw_token, verified_address,
  provider_key, provider_subject)` transaction, which links or creates the platform user,
  activates the membership and marks the invitation accepted; persists the email on the user;
  returns `{ workspace_id, membership_id }`.
- without a token: finds pending invitations whose `invited_address` equals the verified email
  (case-insensitive), accepts them the same way, and returns the first workspace joined or
  `{ accepted: 0 }`. This is the path for people who already had a Clerk account and therefore got
  no Clerk email (§4).

Errors: `410 INVITATION_UNAVAILABLE` (missing, expired, revoked), `409 ADDRESS_MISMATCH` (token's
address is not the signed-in email).

## 4. Clerk as the invitation mail carrier

Verified against Clerk's docs on 2026-09-14 (`clerk.com/docs/guides/users/inviting`, updated
2026-09-11). Clerk's **application** invitations are used, not Clerk Organizations; the session
contract's boundary stands: Clerk owns sign-in and the email, Clue owns workspace, membership,
role and permissions.

**Sending.** The backend calls `POST https://api.clerk.com/v1/invitations` with
`email_address`, `redirect_url = {CLUE_APP_ORIGIN}/invite/accept?token=<raw token>`, and
`public_metadata = { clue_invitation_id }`. Clerk sends the email from the Invitation template
(branded in the Clerk dashboard under Customization, Emails). The Clerk invitation id is stored on
our row so revocation can be mirrored. Limit: 100 creations per hour per instance; a `429` is
surfaced as outcome `rate_limited` and the Clue row is still created (the admin can retry later;
no automatic retry).

**Landing.** Clerk sends the invitee to our redirect URL with its sign-up ticket appended. A new
page `src/app/(auth)/invite/accept/page.tsx` runs Clerk's ticket sign-up through the existing
onboarding auth driver (extended with the ticket strategy), which auto-verifies the address, then
redirects to `/session/establish?invite=<token>`.

**Establishing.** `session/establish` gains one step: it calls `POST /auth/v1/invitations/accept`
(with the token when present, without it otherwise) **before** resolving the protected session,
then sets the workspace cookie to the workspace just joined. Existing behaviour is unchanged when
nothing is accepted. A person signing in normally who has a pending invitation addressed to their
email therefore joins automatically on their next sign-in.

**Known limitation, accepted by ruling.** Clerk refuses to create an invitation for an address
that already has an account in the instance. The backend still creates the Clue row, reports
`created_no_email`, the table shows the person as Invited, and acceptance happens on their next
sign-in through the no-token path. No email is sent in that case.

**Clerk backend-API client.** `clue_auth/providers/clerk_api.py`: `create_invitation`,
`revoke_invitation`, `primary_email(user_id)` over `httpx`, bearer `CLUE_AUTH_CLERK_SECRET_KEY`.
Nothing outside that module imports a Clerk SDK (none is used) or knows Clerk's URL shapes.

## 5. Schema change

One Alembic revision (hash id, chained off the current head), reversible:

- `platform_user.email TEXT NULL` plus a partial index on `lower(email)`. Written when the backend
  first learns the address: at self-serve provisioning (the provision route fetches it from Clerk
  after resolving the session), at invitation acceptance, and lazily at `/auth/v1/session`
  resolution when the stored value is null (a one-call backfill for the existing users). The
  address is the user's Clerk primary email at that moment; it is a display and matching value,
  never an authentication credential.
- `workspace_invitation.provider_invitation_id TEXT NULL` for the Clerk invitation id.
- `erase_platform_user` (DSAR) clears `email` along with the other profile fields; the existing
  invitation-address erasure already covers `invited_address`.

`alembic heads` stays single; `make db-smoke` on a throwaway database is the gate.

## 6. Frontend design

### 6.1 Feature layout

```
src/features/settings/
  components/            lifted verbatim, then bound (profile, workspace, members editable;
                         coming-soon, billing, pages static)
  config/settings-navigation.ts
  model/profile.ts  workspace.ts  members.ts  settings-route.ts     (Zod, contract v1 above)
  data/profile.repository.ts  workspace.repository.ts  members.repository.ts
  data/settings.actions.ts   (browser mutations through fetchMutation)
  data/static-sections.ts    (the dummy's billing and pages placeholders, plus the coming-soon
                              connection cards; explicitly labelled placeholder data)
src/app/(protected)/settings/[[...section]]/page.tsx
src/app/(auth)/invite/accept/page.tsx
src/components/shell/sidebar-profile-menu.tsx, use-sidebar-profile-menu.ts   (lifted)
src/components/ui/confirmation-card.tsx                                        (new)
```

No fixture mode for the live sections: reads either succeed or surface the typed error screen the
accounts feature already uses. The placeholder module is presentation data for screens that are
dummies by ruling, not a fallback for a failed read.

### 6.2 Page composition

The catch-all route parses the section, entity and view with the dummy's `SettingsRouteSchema`,
loads only the section's data on the server (profile, workspace or members), and renders the
lifted `SettingsScreen`. Connections, MCP server, Integrations, Billing and Pages render from the
placeholder module, the first three under the dummy's existing overlay and the last two under the
same overlay per assumption A1.

### 6.3 Autosave

A small client wrapper around the lifted `SettingsInput`: it keeps the last saved value, and on
blur or Enter, if the trimmed value differs, calls the section's action. While saving the input is
read-only. On success the saved value updates and a confirmation card shows ("Profile updated",
"Workspace updated"). On failure the input reverts to the last saved value and the card shows the
error message from the envelope. No Save button, no dirty state across fields; each field is its
own transaction. Escape restores the last saved value without saving.

### 6.4 Confirmation card

One shared, single-instance card anchored bottom-right, mounted once in the protected layout.
Content: a status icon, one line of text, a close button. Auto-dismisses after four seconds;
a new message replaces the current one. Built entirely from the platform design-system tokens
(`packages/design-system/generated/tokens.css`), which are byte-identical to the dummy's, so it
matches the shell. The reference the founder supplied (a dark "Profile updated" card with a green
check and an X) is the interaction; the visual is ours. This is new UI authorised by the founder
on 2026-09-14; it should be added to the design file afterwards, not blocked on it.

### 6.5 Members interactions

- Invite row: the email input accepts comma-separated addresses; the role button toggles between
  Member and Admin (design shows Member by default); Invite posts, then the list re-reads and a
  card reports the outcomes. Invalid addresses are reported, not silently dropped.
- Role dropdown per row: Admin or Member; owner row locked (rendered as "Admin" with the dropdown
  disabled). Changing writes immediately and shows "Role updated".
- Row ellipsis opens a dropdown built from the design-system tokens with the three ruled items,
  each shown only when applicable: **Remove from workspace** (active member, not self, not owner),
  **Revoke invitation** (invitation row), **Re-admit** (removed member; re-admits as Member).
- A removed member keeps its row with "Removed" in the Joined-on column, mirroring "Invited".

### 6.6 Sidebar person and workspace caption

The protected layout resolves `GET /frontend/v1/settings/profile` once per request and provides
it through the existing `WorkspaceProfileProvider` for the whole shell (today only the accounts
layout provides a profile). Name shown is `display_name`, falling back to `full_name` only when
display name is unset; initials from the shown name; the design's single avatar colour. The
anonymous "Workspace" person and the user-id-derived name in
`features/accounts/data/workspace-profile.repository.ts` are removed for the live path. Under
assumption A2 the caption reads the workspace name from `GET /frontend/v1/settings/workspace`.

## 7. Configuration and environment

Per the parity rule, every new setting lands in `.env.example` in the same commit:

| Key | Where | Default in example | Notes |
| --- | --- | --- | --- |
| `CLUE_AUTH_CLERK_SECRET_KEY` | backend `Secrets.clerk_secret_key` | empty placeholder | secret; the same value the frontend holds as `CLERK_SECRET_KEY` |
| `CLUE_APP_ORIGIN` | backend settings | `http://localhost:3020` | builds the invitation redirect URL; already exists on the frontend side |

The invitation flow refuses loudly (`503 INVITATIONS_UNCONFIGURED`) when the secret is absent, and
the Members screen shows the table read-only with the invite row disabled in that case, rather
than creating rows that no email will ever follow.

## 8. Static sections

Connections, MCP server and Integrations are the dummy's previews and stay inert. Billing and
Pages are dummies by ruling; their data comes from the placeholder module and, under A1, they sit
under the coming-soon overlay. Re-scope notes recorded for when they become real:

- **Billing.** Usage-only v1 over lane 3's cost read (`GET /cost/report`) once it merges: a plan
  record per workspace (name, included credits, expiry) set by the founders, credits derived from
  measured USD spend through `millicredit_rate`, and the Manage plan / Top up buttons removed until
  a payments provider and pricing exist. `cost_millicredits` stays 0 by the existing decision.
- **Pages.** Published pages serve at `/w/{workspace_id}/p/{slug}` on the design API; no subdomain
  or custom domain exists; each document carries its own noindex and ABM pages are noindex by
  rule. When publishing is real: favicon, social preview, title and description sourced from the
  brand kit rather than uploads; a fallback URL; head/body snippets with a security review; no
  custom domain, no indexing toggles, no llms.txt.

## 9. Data model: the agreed re-scope (not built here)

The dummy's Data model page is the CRM object-settings pattern. Our data model is a registered
field catalog that research writes against; nobody types a value into an account. Ruling: the page
is redrawn by the co-founder as **Research fields** before anything is wired.

- Entities: Accounts = the active `core.*` and `account.*` keys (the account job's menu, 70
  today); Contacts = `contact.*` plus `core.work_email` (the person job's menu, 70 today).
- Columns: Name (derived from the key, with the accounts table's existing labels) and
  Description (the registry description, which is the research instruction).
- **Create field, workspace level only:** a standing research question with a name and a
  description. Row menu for workspace-created rows: Edit description, Retire.
- Dropped: Editable by (no human write path exists), AI fill (every menu field is AI-filled),
  Relationships (fixed by the domain), the Display tab (a view preference; the accounts table's
  own column toggles are the place, persisted later if wanted).

Research-side change this needs (Track R, recorded, not part of this build): the global
`field_definition` is cross-tenant, and the per-workspace `workspace_field_definition` refuses
keys outside `client.*` and requires a proposal id. Create field needs the per-workspace table to
accept `account.*` and `contact.*` rows created from Settings without a proposal, and
`read_account_catalog` / `read_person_catalog` to take a workspace id and union that workspace's
rows into the menu. The accounts-list custom-column query then reads the same rows.

## 10. Testing and acceptance

**Backend.** Offline tests for the profile split rule, the role mapping and ladder errors, the
invitation outcome classification, and the Clerk client against a stubbed transport. Database
tests on the lane's throwaway database only (`pytest --ignore-glob='*_live.py'`): each route
through the ASGI app with a seeded owner, admin and operator; acceptance with and without a token;
the email backfill; DSAR erasure clearing the email. Migration up, down, up via `make db-smoke`.

**Frontend.** `npm run design-system:build && npm run lint && npm run build` and `npm test`
(`node:test` over the repositories: schema parsing, error envelopes, the autosave wrapper's
revert-on-failure, the role display mapping).

**Parity.** A side-by-side screenshot of every lifted screen against `localhost:3000` at the same
viewport, recorded under `.context/settings-acceptance/`. Any visual difference is a defect in the
lift, not a design change.

**Live walk on the san-salvador stack** (founder-driven, unseeded): sign in; open Settings from
the profile menu; set a display name and see the sidebar change; rename the workspace; invite a
second address you control, receive the Clerk email, accept it, and see the row move from Invited
to a join date; change its role; remove it; re-admit it; revoke a pending invitation. Every step
must show its confirmation card, and every failure must show the envelope message.

## 11. Out of scope and follow-ups

- Human editing of account or contact field values (no design, no write path).
- A workspace-level home for the website and the rebuild-from-new-site flow.
- Avatar upload (the design has no control; Clerk holds an image nobody shows).
- Viewer role in the UI (a three-way dropdown is a later design request).
- Data model build, Billing and Pages: §8 and §9.
- Migrating the two Clerk secrets into one shared secret store; today both processes read their
  own env.

## 12. Build order

1. Migration and the email backfill path; profile read and PATCH; workspace read and rename.
2. Frontend lift: feature, route, profile menu, confirmation card, autosave; Profile and Workspace
   bound; static sections under the overlay; sidebar person from the profile read.
3. Members read and the five management writes; Members screen bound, read-only for callers
   without the permission.
4. Clerk invitation sending, the invite landing page, acceptance route, and the establish hook.
5. Contract doc, `.env.example` parity, parity screenshots, live walk.
