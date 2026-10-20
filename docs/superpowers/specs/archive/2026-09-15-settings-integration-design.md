# Settings section — frontend ⇄ backend integration design

**Status (updated 2026-09-16):** implementation in progress. Profile/Workspace authority fixes,
workspace Research fields registry/API, all research catalog callers, custom-value/evidence
projections, and the Research fields management UI are implemented. The founder approved the
interactive preview and reuse of Settings primitives; the visual gate is satisfied. Pages/Billing
remain dummy frontends. Pages V1 contracts and generated-research acceptance remain open. Real
invitation email receipt and acceptance are confirmed; the invitee's selected workspace/redirect
and remaining membership lifecycle walk still need direct observation. The
[completion plan](../../plans/2026-09-16-settings-integration-completion.md) tracks these separately.
**Original design branch:** `research-streaming` (worktree `san-salvador`).
**Implementation branch:** `settings-page` (worktree `irvine`). **Founder:** Aryan.
**Discussion record:** `_memory/2026-09-14-settings-integration-exploration.md` (committed as `9c1e791f9`).
**Presentation truth:** the co-founder's dummy frontend, originally served at `http://localhost:3000/settings`,
historical source path `/Users/aryankeshri/conductor/workspaces/clue-frontend/live-backend-v1` (branch
`integration/live-backend-v1`, commit `64232a0`, 2026-09-13). Its frontend-authored contract
proposal is `docs/api-contracts/settings.md` in that checkout; Figma page `Settings-dev-ready`,
node `1735:38951`.

## 1. What this integrates, and what it does not

The dummy's Settings section has nine screens in two groups. Personal: Profile, Connections, MCP
server. Admin: Workspace, Members, Integrations, Pages, Data model, Billing. At the original
exploration, `apps/frontend` had no Settings feature, route or profile menu; those now exist.
The integration lifts screens from the dummy and binds the approved live sections to real data
at the repository seam, per `apps/frontend/docs/architecture/frontend.md` and
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
| Research fields | Approved preview replaces Data model; retain entity overview and old field links | Live management UI and backend implemented; generated-research acceptance pending |

Two cross-cutting rulings apply to every editable field: **autosave on blur** with an ephemeral
confirmation card, and **the sidebar shows the signed-in person's display name**, never a
placeholder.

Original assumptions and subsequent founder rulings:

- **A1 — superseded by latest founder follow-up, 2026-09-15.** Billing and Pages show their existing
  dummy frontends without the "Coming soon" overlay. Pages is part of V1 and still awaits development;
  the earlier permission to retain its overlay is withdrawn. Data model also remains clickable with
  its original dummy until visual approval. That approval arrived on 2026-09-16; the live Research
  fields screen replaces Fields, and old Display links redirect to Fields.
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
| Rename workspace; create, edit or retire a research field | `workspace.manage_settings` — a new permission added to the internal policy (revision 3), granted to admin and owner alongside `workspace.manage_members`. One word for "may change what the workspace is", so field management does not borrow the members permission. |
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
  "website": "https://insighthealth.ai", "logo_url": "/api/clue/design/assets/<asset_id>/bytes" }
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
  provisioning brand (`self_serve_provisioning.brand_id`), served through the existing authenticated
  asset proxy used by the app; null when no kit or no logo exists, and
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

- Members come from `workspace_membership` joined to `platform_user`; `active` renders as active.
  **Founder ruling 2026-09-16:** `suspended` stays visibly Suspended and read-only, with no Re-admit
  action. This supersedes the original active-state mapping. `revoked` renders as `removed` (kept
  in the list so Re-admit has something to act on), `invited` memberships (legacy state) render as
  `invited`. `joined_on` is
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
`already_invited`, `invalid`. Partial success is normal and the frontend shows one aggregate confirmation card
listing outcome counts ("3 invitations sent · 1 already a member").

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
surfaced as outcome `rate_limited` and the Clue row is still created. **Founder ruling 2026-09-16:**
to retry a rate-limited or failed delivery, revoke the pending invitation and invite again. Keep
that behavior; no automatic retry or resend action is required.

**Landing.** Clerk sends the invitee to our redirect URL with its sign-up ticket appended. A new
page `src/app/(auth)/invite/accept/page.tsx` runs Clerk's ticket sign-up through the existing
onboarding auth driver (extended with the ticket strategy), which auto-verifies the address, then
redirects to `/session/establish?invite=<token>`.

**Live acceptance correction, 2026-09-16.** The configured Clerk instance requires a password.
The invitation form therefore collects first name, last name and password; the adapter calls
`signUp.create({strategy: "ticket", ticket, firstName, lastName, password})`, because Clerk v7's
`ticket()` helper does not accept the password. Errors preserve entered values, and incomplete
sign-ups never activate a session. Credentials remain inside the browser-to-Clerk flow.

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

A second, separate revision carries the research-fields registry change (§9.4) so the two can land
independently:

- `workspace_field_definition`: the namespace CHECK widens from `client.%` to `client.%`,
  `account.%` or `contact.%`; the pack CHECK becomes "pack rows are `client`, research rows have
  `pack IS NULL` and a `field_class` of `account` or `contact`"; `promoted_from_proposal_id`
  becomes nullable (its FK and UNIQUE tolerate nulls); drop `pack NOT NULL`; `client_kb_role`
  admits `research`; add nullable `label TEXT`. The UPDATE trigger permits only research
  label/description changes with an exact version increment. Preserve all legacy Client-KB checks.
- No change to `workspace_field_retirement`; retirement already keys on `(workspace_id, field_key)`.

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

Responsive navigation ruling (2026-09-16): at widths up to 860px, collapse Settings navigation
behind a sidebar icon beside the page heading. It opens the same vertical navigation in a left
drawer; do not convert it into a horizontal top bar. Close on navigation, outside click or Escape,
restore focus to the trigger, and dismiss the drawer when returning to the permanent desktop
sidebar. Use the existing sidebar icon, dialog primitive and design tokens.

The catch-all route parses the section, entity and view with the dummy's `SettingsRouteSchema`,
loads only the section's data on the server (profile, workspace, members or the selected entity's
research fields), and renders `SettingsScreen`. Connections, MCP server, Integrations, Billing and
Pages render from the placeholder module. Only Connections, MCP server and Integrations retain the
overlay. Research fields uses the live registry with the approved management UI (§9).

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

Connections, MCP server and Integrations are the dummy's previews and stay inert. Billing and Pages
expose their dummy frontends directly using the placeholder module. Pages remains
in V1 scope; its backend integration is still pending. Re-scope notes recorded for when they become
real:

- **Billing.** Usage-only v1 over lane 3's cost read (`GET /cost/report`) once it merges: a plan
  record per workspace (name, included credits, expiry) set by the founders, credits derived from
  measured USD spend through `millicredit_rate`, and the Manage plan / Top up buttons removed until
  a payments provider and pricing exist. `cost_millicredits` stays 0 by the existing decision.
- **Pages.** Published pages serve at `/w/{workspace_id}/p/{slug}` on the design API; no subdomain
  or custom domain exists; each document carries its own noindex and ABM pages are noindex by
  rule. When publishing is real: favicon, social preview, title and description sourced from the
  brand kit rather than uploads; a fallback URL; head/body snippets with a security review; no
  custom domain, no indexing toggles, no llms.txt.

## 9. Data model → Research fields: specification (design approved 2026-09-16)

The founder approved the interactive preview on 2026-09-16. The live Research fields screen now
replaces the dummy Data model and connects creation, editing and retirement to the existing scoped
API. Accounts/Contacts overview and `/fields` links remain; old `/display` links redirect. Live
create/edit/reload checks pass; retirement confirmation and generated-research acceptance are
tracked separately in the completion plan.

### 9.1 What the page is

The dummy's Data model page is the CRM object-settings pattern. Our data model is a registered
field catalog that research writes against, and the description of a field is the instruction the
research agent follows. So the page is renamed **Research fields** and answers two questions for
an ABM lead: *what does Clue find out about every account and every contact*, and *what else do we
always want to know*. Ruling 2026-09-14: workspace level only. There is deliberately no
project-level custom field; the ICP document a project pins keeps its own qualifier fields, which
are a different thing (fit criteria for one motion).

Kept from the dummy: the two-entity list (Accounts, Contacts), the per-entity fields table, the
Create field button, the per-row ellipsis. Dropped: the Type, Editable by and AI fill columns, the
Relationships tab, the Display tab, and Restore defaults. Added: a Description column, a Create
field form, and a row menu for editing the name/instruction and retiring the field. The founder-approved preview
in §9.7 supplies the two required frames.

### 9.2 Rows

| Entity | Platform rows | Workspace rows |
| --- | --- | --- |
| Accounts | every active global `core.*` and `account.*` key. This is the account research job's menu (`read_account_catalog`), so the page shows precisely what the agent may write. 70 keys today. | every active, unretired `account.*` row of this workspace in the per-workspace registry |
| Contacts | every active global `contact.*` key plus `core.work_email`, the person job's menu (`read_person_catalog`). 70 keys today. | every active, unretired `contact.*` row of this workspace |

All platform rows are shown, including bookkeeping keys such as `account.media_layer_index`. No
"hidden from settings" flag is added: the page shows the agent's real menu, and a flag would be a
second source of truth about what the agent sees. **Open for the founder (R-1):** if the
bookkeeping keys read as noise in the walk, the cheapest honest filter is by the registry's own
`pass_kind` and `signal_class` columns, not a new flag.

Each row carries:

| Column | Platform row | Workspace row |
| --- | --- | --- |
| Name | derived from the key's last segment in sentence case (`annual_revenue` → "Annual revenue"), with the accounts table's own labels overriding for the keys it displays (`core.account_name` → "Company name", `core.industry` → "Industry", `core.employee_count` and `core.employee_range` → "Headcount", `core.annual_revenue` and `core.revenue_band` → "Revenue", `core.hq_location` → "Locations", `core.primary_domain` → "Website", `account.scoring.fit` → "Fit score") | the `label` as typed at creation |
| Description | the registry `description` verbatim | the description as typed; this is the research instruction |
| Origin | "Clue" | "Workspace", with who created it and when |
| Menu | none (platform vocabulary a workspace cannot change) | Edit description, Retire |

### 9.3 Backend surface

```
GET    /frontend/v1/settings/research-fields?entity=accounts|contacts
POST   /frontend/v1/settings/research-fields          body: { entity, label, description }
PATCH  /frontend/v1/settings/research-fields/{key}     body: { label?: string, description?: string }
DELETE /frontend/v1/settings/research-fields/{key}
```

`GET` response:

```json
{ "entity": "accounts",
  "rows": [
    { "key": "core.industry", "label": "Industry", "description": "Primary industry classification…",
      "origin": "platform", "created_by": null, "created_at": null },
    { "key": "account.uses_salesforce", "label": "Uses Salesforce", "description": "Whether the account runs Salesforce as its CRM; cite the job post, case study or integration page that shows it.",
      "origin": "workspace", "created_by": "Aakash", "created_at": "2026-09-16" }
  ] }
```

Platform rows first, in key order, then workspace rows in creation order. Reads require an active
membership; the three writes require `workspace.manage_settings` (§2.3).

**Create.** The key is derived from the label: lower-case, every run of non-alphanumerics becomes
one underscore, leading and trailing underscores trimmed, prefixed by the entity's namespace
(`account.` or `contact.`); a label that reduces to nothing is `400 LABEL_INVALID`. The label is trimmed to 1–200 characters. The description
is required, 1 to 2000 characters, because an instruction-less field cannot be researched. The
key must not collide with a global key (`409 KEY_TAKEN`, message names the platform field) or
with any workspace row including a retired one (`409 KEY_TAKEN`, message suggests appending a
qualifier). On success `201` with the row. Registered through a new registry function
`register_workspace_research_field` (§9.4).

**Edit.** `PATCH` updates `label` and/or `description` in place and bumps `definition_version`.
Claims already written keep their provenance; only future research reads the new instruction.
Platform keys are `409 PLATFORM_FIELD`.

**Retire.** `DELETE` calls the existing `retire_workspace_field` with `retired_by =
"human:<user_id>"` and reason `settings`. The row leaves the page, the research menu and the
accounts table; claims already written stay in the store with their provenance. Retirement is
final: the key cannot be re-registered (the registry refuses redefinition), so the frontend
confirms before calling. Platform keys are `409 PLATFORM_FIELD`.

### 9.4 The registry change (research side, `subsystems/research/clue_research/claimstore/registry.py`)

Why the per-workspace table and not a new one: `insert_claim` guards every field claim with
`check_claim_writable`, which validates the key through `validate_effective_value` under a
workspace `FieldRegistryScope`. That scope reads the global `field_definition` plus the
`workspace_field_definition` overlay for the workspace, with retirement and the erasure marker
already joined. A separate table would be invisible to that gate; the lenient writer would then
treat every custom-field claim as unregistered and file it as a *proposed* field in the global
table, which is exactly the cross-tenant leak §9 exists to avoid. The overlay is the correct home;
its `client.*`-only shape was the old dynamic Client-KB lane's policy, not a property of the
substrate (the table is on the Phase-6 keep list as claim-store substrate).

Changes to the shared registry:

1. **Schema** (§5, second revision): namespace CHECK widened to `client.%`, `account.%`,
   `contact.%`; pack CHECK split so research rows carry `pack IS NULL` and `field_class` of
   `account` or `contact`; `promoted_from_proposal_id` nullable; `client_kb_role` admits
   `research`; `label TEXT NULL` added. Drop the old `pack NOT NULL` constraint.
   Replace the UPDATE trigger with the narrow research-label/description/version guard; keep
   Client-KB rows and research identity, scopes, shape and creator metadata immutable. A populated
   downgrade refuses rather than deleting research definitions or claims.
2. **`register_workspace_research_field(conn, *, workspace_id, entity, label, description,
   created_by)`**, a sibling of `register_workspace_field` that forces the research shape:
   `field_key` derived as in §9.3, `field_class` from `classify_field_key`, `value_type = "json"`,
   `value_schema = None` (no shape constraint; the structuring model's coercion already handles
   free values), `pass_kind = deep`, `reuse_scope = tenant_private`, `research_scope =
   project_neutral`, `product_scope = forbidden`, `client_kb_role = "research"`,
   `promotion_policy_version = "settings-v1"`, `promoted_by = "human:<user_id>"`,
   `promoted_from_proposal_id = NULL`, `presentation = "text"`. The global-collision check and the
   workspace erasure guard are reused. Global and workspace registration share a transaction
   lock for each key and check collisions in both directions. Existing Client-KB shape stays intact.
3. **`update_workspace_research_field(conn, *, workspace_id, field_key, label, description)`**:
   partial label/description updates under a row lock, with exactly `definition_version + 1`
   when text changes. No-op patches do not advance the version; disjoint patches preserve each
   other. Refuse non-research and missing/retired rows. Immutable keys never change with labels.
4. **The two catalog readers** (`clue_api/arv2/account_research_store.py`) take `workspace_id`
   and union the workspace's active, unretired research rows into the menu: `account.%` into the
   account job's catalog, `contact.%` into the person job's. All three call sites supply the
   workspace id: account and queued-person composition in the driver, plus direct person launch. The
   structuring prompt renders each menu entry as key plus description, so a workspace field is
   researched on the next job with no further change. The docstring "every registered account.*
   and core.* field, exactly as the registry holds it" stays true: the registry now holds them.
5. **The lenient claim writer's registry gate** distinguishes retired/erased workspace keys from
   unknown fields. These refusals never trigger global proposed-field fallback. Shared definition
   locks remain held through claim insertion; retirement takes a conflicting lock. Jobs already
   composed keep their context, but subsequent writes after retirement refuse through the existing
   per-draft failure receipts without discarding successful sibling claims.
6. **Custom values and evidence** preserve the existing Client-KB columns and additionally select
   populated active `account.%` research fields for accounts, using the label with a key fallback.
   Contact research fields are served only in contact detail payloads through the existing use
   policy; no new contact UI slot is introduced. Values carry `claimId`; evidence carries optional
   `researchFieldKey`. The account detail reuses the existing source chip and Sources control.
   Stored page citations and scoped custom claims authorize evidence without generation, including
   retired fields. Erased fields and another workspace/subject remain refused.

Recorded follow-up, not in scope: `_register_proposed_field` in the lenient writer still
registers an agent-invented key in the **global** table. With the overlay accepting `account.*`
and `contact.*` rows, proposed fields should be filed per workspace instead. That is a Track R
change with its own review because it alters what every workspace's menu contains.

**2026-09-16: detailed follow-up plan requested.** Track R is now covered by
[Workspace-local agent-proposed research fields](../../plans/2026-09-16-workspace-agent-proposed-fields.md):
trusted registration, manager controls, namespaces/facets, historical global-definition containment,
concurrency/lifecycle tests and versioned agent documentation. This is planning only; automatic
global registration is still current. The [agent guidance](../../../agents/research-field-scope.md)
separates that behavior from prepared replacement instructions and their activation gates.

### 9.5 Frontend

- `components/data-model-settings.tsx` is lifted, then reduced to the redrawn shape: the entity
  list stays; `FieldsView` renders Name, Description and the ellipsis; `DataModelTabs`,
  `DisplayView` and `DisplayGroup` are deleted, not hidden. The header title and navigation label
  follow the redraw ("Research fields"); the route stays `/settings/data-model/{entity}` unless the
  redraw renames it, which is a one-line change.
- `model/research-fields.ts` (Zod) mirrors §9.3; `data/research-fields.repository.ts` reads on the
  server through `fetchRead`; `data/settings.actions.ts` gains create, update and retire through
  `fetchMutation`.
- **Create field** opens the redrawn form (§9.7): Name and Description, a Create button, and the
  `KEY_TAKEN` message shown inline under Name. On success the row appears at the bottom of the
  workspace rows and the confirmation card reads "Field created".
- **Edit description** turns that row's Description cell into an autosave textarea (blur or
  Cmd/Ctrl+Enter saves, Escape restores) with the card "Field updated". Editing the label uses the
  same mechanism on the Name cell.
- **Retire** is a two-step item in the row dropdown: "Retire" becomes "Confirm retire" in place;
  confirming calls `DELETE` and shows "Field retired". No modal dialog.
- Callers without `workspace.manage_settings` see the table without the Create button and the
  row menus.

### 9.6 Testing and acceptance for this section

Offline: key derivation and collision messages, label overrides, the row merge order. Database
(throwaway lane DB): the three writes with and without the permission; a claim written under a
workspace research key passes `check_claim_writable` and lands tenant-private; a retired key is
absent from both catalogs and from the accounts custom columns; the erasure marker refuses
registration. Migration up, down, up. Frontend: repository parsing, the create form's inline error,
the autosave cell's revert. **Live proof, unseeded, founder-driven:** create "Uses Salesforce" on
Accounts with a real instruction, launch account research on one already-researched account, and
see the claim appear as a column in the accounts table with its evidence; then retire the field
and see the column disappear while the account's evidence stays readable.

### 9.7 Frames required before the visual build

The 2026-09-16 scheduling amendment permits backend/contract implementation ahead of these
frames. The founder approved the interactive preview on 2026-09-16, authorizing composition with the
existing Settings primitives. The approved design preserves the entity overview, renders origin/
creator/date beneath Name, places Create inline above the table, uses in-place edits and retirement
confirmation, and stacks field cells at narrow widths. The visual gate is satisfied.

1. The **Research fields table** per entity: Name, Description, ellipsis; the Create field
   button in the existing toolbar position; the header without the Fields/Relationships/Display
   tabs.
2. The **Create field form**: Name and Description inputs, Create, and the inline "name already
   used" error. The invite row on Members is the closest existing pattern; an inline row above
   the table would keep the section consistent.

The row dropdown reuses the design-system dropdown ruled for Members (Edit description, Retire /
Confirm retire) and needs no separate frame.

## 10. Testing and acceptance

**Backend.** Offline tests for the profile split rule, the role mapping and ladder errors, the
invitation outcome classification, and the Clerk client against a stubbed transport. Database
tests on the lane's throwaway database only (`pytest --ignore-glob='*_live.py'`): each route
through the ASGI app with a seeded owner, admin and operator; acceptance with and without a token;
the email backfill; DSAR erasure clearing the email. Migration up, down, up via `make db-smoke`.

**Research fields.** §9.6, run when that build lands.

**Frontend.** `npm run design-system:build && npm run lint && npm run build` and `npm test`
(`node:test` over the repositories: schema parsing, error envelopes, the autosave wrapper's
revert-on-failure, the role display mapping).

**Parity.** A side-by-side screenshot of every lifted screen against `localhost:3000` at the same
viewport, recorded under `.context/settings-acceptance/`. Any visual difference is a defect in the
lift, not a design change.

**Live walk on the isolated Irvine stack** (founder-driven, unseeded): sign in; open Settings from
the profile menu; set a display name and see the sidebar change; rename the workspace; invite a
second address you control, receive the Clerk email, accept it, and see the row move from Invited
to a join date; change its role; remove it; re-admit it; revoke a pending invitation. Every step
must show its confirmation card, and every failure must show the envelope message.

## 11. Out of scope and follow-ups

- Human editing of account or contact field values (no design, no write path).
- A workspace-level home for the website and the rebuild-from-new-site flow.
- Avatar upload (the design has no control; Clerk holds an image nobody shows).
- Viewer role in the UI (a three-way dropdown is a later design request).
- Billing integration stays outside this build. Pages is required for V1 but awaits its §8 contract
  and completion-plan phase 8. Per-workspace filing of agent-proposed fields: §9.4 follow-up.
- Migrating the two Clerk secrets into one shared secret store; today both processes read their
  own env.

## 12. Build order

This is the original build order. The [2026-09-16 completion plan](../../plans/2026-09-16-settings-integration-completion.md)
records what already exists and the proposed remaining sequence, including concrete registry,
retirement and evidence-access corrections discovered by tracing the current code.

1. Migration and the email backfill path; profile read and PATCH; workspace read and rename.
2. Frontend lift: feature, route, profile menu, confirmation card, autosave; Profile and Workspace
   bound; static sections presented per §8; sidebar person from the profile read.
3. Members read and the five management writes; Members screen bound, read-only for callers
   without the permission.
4. Clerk invitation sending, the invite landing page, acceptance route, and the establish hook.
5. Contract doc, `.env.example` parity, parity screenshots, live walk.
6. **Visual gate satisfied by the approved preview (§9.7):** the registry revision and `register_workspace_research_field`;
   the two catalog readers taking `workspace_id`; the custom-column query; the four routes; the
   Research fields screen; the §9.6 live proof.
