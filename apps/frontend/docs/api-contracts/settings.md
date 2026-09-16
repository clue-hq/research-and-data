# Settings integration contract

Implemented on Irvine `settings-page`, 2026-09-15. Product decisions and the design pin are in
[`2026-09-15-settings-integration-design.md`](../../../../docs/superpowers/specs/2026-09-15-settings-integration-design.md).
This document records the implemented transport and state behavior. Real Clerk email acceptance
on the founder's running stack remains a separate manual acceptance step.

## Ownership and routes

`/settings` defaults to Profile. `/settings/{profile,workspace,members}` uses authenticated server
repositories and Zod wire schemas. There is no fixture fallback for these sections. Expected read
failures render the existing typed recovery screen with Settings copy. Transport remains in
`features/settings/data`; client state and actions live in `hooks`; components render those models.

Connections, MCP server and Integrations are presentation previews beneath inert, `aria-hidden`
frosted overlays. Per the founder's latest 2026-09-15 follow-up, Billing, Pages and Data model show
their dummy frontends directly. Pages remains part of V1; its form edits are local placeholders.
Data model opens the Accounts/Contacts overview and `/settings/data-model/{accounts,contacts}/{fields,display}`;
entity-only routes default to Fields. Unknown entities, views and nesting on other sections return 404.
Data model retains the pinned dummy fields/display data; creating fields, row actions and reordering
are not connected. The Research fields management API and repository now exist (see below); replacing this dummy
with its live management screen is still gated on approved frames or primitive reuse. Billing's
plan/credit values and buttons have no live billing integration.

All Settings endpoints use `/frontend/v1/settings`, behind `CLUE_FRONTEND_READ_ENABLED`, the existing
authenticated principal, workspace dependency and error envelope. Browser writes use the existing
same-origin `/api/clue/frontend/v1/settings` BFF; clients cannot select their own workspace header.
Successful payloads below are **bare objects**, not `{data: ...}` wrappers.

| Method and suffix | Request | Response / authority |
| --- | --- | --- |
| GET `/profile` | — | Profile for the signed-in internal user |
| PATCH `/profile` | `{full_name?, display_name?}` | Updated Profile; own user only |
| GET `/workspace` | — | Workspace |
| PATCH `/workspace` | `{name}` | Updated Workspace; `workspace.manage_settings` |
| GET `/members` | — | `{rows, invitations_configured}`; active members may read |
| POST `/members/invitations` | `{emails: string[], role: "admin" \| "operator"}` | `{outcomes: [{email, outcome}]}`; manage permission |
| DELETE `/members/invitations/{id}` | — | `{ok: true}`; manage permission |
| PATCH `/members/{id}` | `{role: "admin" \| "operator"}` | `{ok: true}`; manage permission |
| DELETE `/members/{id}` | — | `{ok: true}`; manage permission |
| POST `/members/{id}/readmit` | `{role: "admin" \| "operator"}` | `{ok: true}`; UI re-admits as Member |

Profile: `{user_id, first_name: string|null, last_name: string|null, full_name: string,
display_name: string|null, email: string|null}`.

Workspace: `{workspace_id, name, website: string|null, logo_url: string|null}`.

Member row: `{kind: "member"|"invitation", id, name: string|null, email: string|null,
role_key: "owner"|"admin"|"operator"|"viewer", state: "active"|"invited"|"removed"|"suspended",
joined_on: YYYY-MM-DD|null, is_self: boolean}`. `suspended` is an additive read-only state so
pre-existing suspended access is not mislabeled Active or offered Re-admit.
The founder explicitly accepted this suspended-state behavior on 2026-09-16.

## Profile, workspace and shell

Profile fields trim input and save independently on blur or Enter. Escape restores the last saved
value. Failed writes revert that field and show the envelope message. Inputs are read-only while
their request is pending. Responses update only the corresponding local profile field, so two
overlapping saves cannot overwrite each other's display state. Refreshing the route updates the
shared shell provider. Inputs remount when their user/workspace scope changes.

`full_name` splits at the first space; the remainder is `last_name`. Empty name parts clear their
columns. Missing fields are preserved. Null or blank `display_name` clears it. Both inputs have a
200-character limit. Job role, email and avatar are not writable here. The store's explicit-clear
option preserves the previous onboarding update semantics for existing callers.

Workspace name trims to 1–200 characters. Rename changes only `workspace.name`, never brand names
or the provisioning receipt. Website is that receipt's readonly website. Logo comes from the
latest approved kit for its provisioning brand; opaque asset IDs resolve through
`/api/clue/design/assets/{asset_id}/bytes`. There is no logo upload.

The protected layout shares the profile across the application. Display name falls back to full
name, with initials and the existing fixed avatar colour. Under assumption A2 the profile menu
caption uses the workspace name. Its Settings link, keyboard navigation, Escape and focus return
work independently of the account screens.

## Members and invitation delivery

Owner/admin render as Admin; operator/viewer as Member. Viewer is never an offered write value.
The backend protects **every** owner and rejects self-removal. Removed memberships remain visible;
Re-admit changes the same membership to active as Member. All target IDs are workspace scoped.
Management writes serialize on the workspace and recheck current actor authority in the transaction.

The invite input accepts comma-separated addresses, at most 50 per request. The backend normalizes
and deduplicates addresses and reports invalid ones. Existing member addresses return
`already_member`; pending invitations return `already_invited`. A newly created row stores a
SHA-256 digest, never the bearer token, and expires in 30 days. Clerk application invitations carry
the redirect and Clue invitation ID as metadata; Clerk Organizations are not involved.

Outcomes: `sent`, `created_no_email`, `already_member`, `already_invited`, `invalid`, `rate_limited`,
and additive `delivery_failed`. The last state covers provider/network failures without presenting
them as successful email delivery. Provider refusals leave the pending Clue row intact. To retry a
rate-limited/failed delivery, revoke that pending row and invite again; the UI message says this
explicitly. Pending tokens are never silently rotated during concurrent requests.
The founder explicitly accepted this revoke-and-invite-again retry behavior on 2026-09-16.

Existing Clerk accounts receive no email under the agreed rule (`created_no_email`) and join on
their next sign-in. A mixed batch produces one aggregated confirmation message so the single-card
replacement rule does not hide earlier outcomes. Batches containing invalid/failed outcomes use
the error icon. Revocation commits in Clue first, then mirrors to Clerk. A provider revocation
failure reports `INVITATION_DELIVERY_REVOKE_FAILED`; Clue access remains revoked.

When `CLUE_AUTH_CLERK_SECRET_KEY` is absent, `invitations_configured` is false, the UI is read-only,
and invitation creation returns `503 INVITATIONS_UNCONFIGURED` without creating rows. Operator and
viewer callers always see a read-only members table.

## Invitation acceptance and session establishment

`POST /auth/v1/invitations/accept` accepts `{token?: string|null}`. It requires a provider session
but deliberately requires no existing Clue identity or membership. The backend fetches the verified
primary email from Clerk. Token acceptance checks its digest, address, expiry and lifecycle state.
Without a token, it accepts unexpired pending invitations for that verified address, skipping rows
that would restore revoked/suspended access. It returns `{accepted: number, workspace_id?,
membership_id?}`. The first accepted workspace becomes the selected workspace.

Errors include `409 ADDRESS_MISMATCH`, `410 INVITATION_UNAVAILABLE`,
`409 VERIFIED_EMAIL_REQUIRED`, and `503 INVITATIONS_UNCONFIGURED/INVITATIONS_UNAVAILABLE`.
Both acceptance paths share the same locked transaction; an identity lock precedes invitation
row locks. Tokens are idempotent only for the same active identity/membership.

`/invite/accept?token=...&__clerk_ticket=...` uses the existing onboarding auth driver and Clerk v7's
ticket method, then finalizes only a completed signup. It sends the browser to
`/session/establish?invite=...`. That route accepts invitations **before** resolving the protected
session, including on normal sign-ins without a token. A joined workspace cookie is set before
membership resolution. Unconfigured acceptance preserves ordinary sign-in when no token was given.
Other acceptance failures render a retry/sign-in message rather than sending an invitee through
owner provisioning.

The verified email is saved on invitation acceptance, provisioning and the first session read
where it is absent. A new invitee's first/last name is seeded from the same Clerk profile fetch;
existing Clue names and explicit clears are never overwritten. DSAR erasure clears the email.

## Configuration and verification

- Migration `27aa2ae947bc` adds nullable `platform_user.email`, a partial lowercase email index,
  and nullable `workspace_invitation.provider_invitation_id`; it has a complete downgrade.
- Backend `Secrets.auth_clerk_secret_key` loads `CLUE_AUTH_CLERK_SECRET_KEY` (empty by default).
  `Settings.app_origin` loads `CLUE_APP_ORIGIN` (default `http://localhost:3020`). Both are documented
  in root `.env.example`; the backend secret is distinct from the frontend process's env name.
- ConfirmationProvider is mounted once in the protected layout. A new message replaces the last;
  messages dismiss after four seconds or via their close button.
- DB/ASGI tests cover profile clears and preservation, role permissions, owner/self protection,
  rename isolation, batch outcomes, digest custody, acceptance/replay, removal/readmission,
  email backfill and erasure, expiry, missing configuration and primary-logo routing.
- Browser component verification and pinned-design comparison captures are under local
  `.context/settings-acceptance/`; they use controlled test data and shared Irvine UI primitives.
  This is not a claim of live Clerk email acceptance or validation on the san-salvador runtime.


## Research fields — 2026-09-16 implementation

The founder authorized implementation of the completion plan. D1–D8 are applied to the backend
and existing presentation seams. The Research fields table/Create redesign and Pages contract
remain separate pending choices; this API's existence does not mean the dummy Data model is live.

| Method and suffix | Request | Response / authority |
| --- | --- | --- |
| GET `/research-fields` | `?entity=accounts|contacts` | `{entity, rows}`; active membership |
| POST `/research-fields` | `{entity, label, description}` | New row, 201; `workspace.manage_settings` |
| PATCH `/research-fields/{key}` | `{label?, description?}` | Updated row; same permission |
| DELETE `/research-fields/{key}` | — | `{ok:true}`; same permission |

A row contains `key`, `label`, `description`, `origin: platform|workspace`, nullable creator display
name `created_by`, and nullable ISO `created_at`. Platform rows are ordered by key; workspace rows
follow in creation order. Creator erasure produces null. No extra client lookup is needed.

Names trim to 1–200 characters; descriptions trim to 1–2000. The immutable key is derived once
from the name's ASCII letters/digits and the selected entity namespace. Changing the label does
not rename claims. Empty/non-ASCII-only derived keys return `400 LABEL_INVALID`. Collisions with
platform keys or an existing/retired same-workspace key return `409 KEY_TAKEN`; private keys can
be independently defined by different workspaces. Global registration also respects private-key
reservations, serialized by a shared advisory transaction lock.

Only label/description updates are permitted. Disjoint patches preserve each other under a row
lock; changed text advances the definition version exactly once, while no-op patches do not.
Platform changes return `409 PLATFORM_FIELD`; absent/retired fields return `404 FIELD_NOT_FOUND`.
Erased workspace vocabulary refuses writes with `409 WORKSPACE_FIELDS_ERASED`. No restore or
key reuse is exposed. Retirement is append-only and blocks later claim writes transactionally;
the lenient writer cannot turn retired/erased keys into globally proposed fields.

Both account and person research resolve the workspace catalog at job composition, including the
direct person launcher. Label/instruction edits apply on subsequent compositions, not by rewriting
an in-flight model context. Existing per-claim failure receipts isolate rejected batch entries.

Account list/detail custom values preserve legacy Client-KB columns and add populated active
account research fields. Contact fields are served only on contact payloads and pass the existing
contact-display policy. Custom values include a nullable `claimId`; custom evidence includes an
optional `researchFieldKey`. The account detail reuses the existing source chip. The existing
Sources control keeps retired-field evidence accessible, including private records without a URL.
The artifact routes authorize only scoped subject claims or stored page citations, and refuse
cross-workspace, cross-subject and erased-field access without generating prose.

`workspace.manage_settings` is policy revision 3, owner/admin only. Members continue to use
`workspace.manage_members`; non-managers see plain role text, suspended rows remain read-only,
and failed invitations retain revoke-then-invite retry. Invitation results use one aggregate
confirmation card. The project-accounts refresh route uses the same Settings profile as the shell.

Migration `3a75cb367c2b` follows the rebased join `6d25b68bff68`. It preserves Client-KB constraints,
permits only research text/version edits, and refuses downgrade when research definitions exist.
Only a clean research slice may restore the old schema; never erase definitions to make rollback
pass. Live email receive/accept and generated account/person research remain acceptance work.
