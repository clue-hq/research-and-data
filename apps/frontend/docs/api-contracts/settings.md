# Settings integration contract

Implemented on Irvine `settings-page`, 2026-09-15. Product decisions and the design pin are in
[`2026-09-15-settings-integration-design.md`](../../../../docs/superpowers/specs/2026-09-15-settings-integration-design.md).
This document records the implemented transport and state behavior. The founder confirmed real
Clerk email receipt and acceptance on 2026-09-16; the invitee's own selected-workspace redirect
remains a separate observation.

## Ownership and routes

`/settings` defaults to Profile. `/settings/{profile,workspace,members}` uses authenticated server
repositories and Zod wire schemas. There is no fixture fallback for these sections. Expected read
failures render the existing typed recovery screen with Settings copy. Transport remains in
`features/settings/data`; client state and actions live in `hooks`; components render those models.

Connections, MCP server and Integrations are presentation previews beneath inert, `aria-hidden`
frosted overlays. Billing and Pages retain their dummy frontends. Pages remains part of V1 and
awaits its own contract; Billing has no live plan/credit integration.

Research fields replaces the dummy Data model after the founder approved the interactive preview
on 2026-09-16. `/settings/data-model` retains the Accounts/Contacts overview. Both entity-only
routes and `/settings/data-model/{accounts,contacts}/fields` load the live registry. Legacy
`/display` routes redirect to that entity's `/fields` route. Unknown entities, views and nesting
on other sections return 404. Read failures preserve the exact nested retry URL and use the
shared typed recovery screen; they never render fixture rows.

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

`/invite/accept?token=...&__clerk_ticket=...` collects first name, last name and password through
the existing onboarding auth driver. Clerk requires a password for this application's sign-up.
The adapter uses Clerk v7's `create({strategy: "ticket", ticket, firstName, lastName, password})`:
the `ticket()` convenience method does not accept a password. Passwords go directly to Clerk,
never through Clue's API or persistence. The form preserves inputs on error, displays Clerk's
password-policy errors, and finalizes only a completed signup. It sends the browser to
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
and existing presentation seams. The Research fields table/Create preview was approved and its management UI is now connected.
The Pages contract remains a separate pending choice.

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
pass. Generated account/person research remains separate live acceptance work.


### Research fields UI — approved preview, 2026-09-16

The screen renders Name, Description, origin and creator/date; platform rows have no actions.
Members without `workspace.manage_settings` have neither Create nor row menus. The server reads
and validates the selected entity; the client controller is keyed by workspace, entity and
permission. Unmount invalidates late mutation results and notifications.

Create expands a form above the table. Name and Description are required (200/2,000 characters),
trimmed on submission. The backend's `KEY_TAKEN`/`LABEL_INVALID` messages appear under Name.
Duplicate submissions are blocked; only a successful response appends the new workspace row.
Create and edit do not launch research: instructions apply to future job compositions.

Edit name/description use the shared autosave behavior. Descriptions save on blur or Cmd/Ctrl+Enter;
Enter inserts a newline. Escape restores the saved value; failed writes revert and show the server
message. Keyboard completion restores focus to the row action. Pending cells are read-only;
disjoint response merges update only the submitted attribute, preserving independent edits.

Retire changes to Confirm retire inside the row menu with the final/key-reservation explanation.
The row remains until the server accepts retirement; failure retains it. Successful create/edit/
retire operations reuse the shared confirmation card. Narrow screens stack each field's cells
without horizontal overflow and use the collapsible Settings sidebar.

---

## Pages (custom-domain publishing S2)

Status: as-built contract for Settings → Pages, landed 2026-09-18 on `website/custom-domain` (S2 of
custom-domain publishing). Covers the **Pages section only**; the other settings sections are the
settings-integration slice's to record here.
Spec: `docs/superpowers/specs/2026-09-17-custom-domain-publishing-design.md` §7 (repo root), with
`docs/superpowers/specs/2026-09-15-settings-integration-design.md` §2.2–2.3 for the seam and authority.

**Reconciled 2026-09-17:** the dummy proposes one blob, `GET /api/v1/settings`, with all nine
sections inside. This repo serves **per-section reads under `/frontend/v1`** and each section needs
its own authority, so the Pages section is a dedicated read plus seven further routes under
`/frontend/v1/settings/pages`, taken on this repo's existing seams (`fetchRead` server-side for the
read, `fetchMutation` through the same-origin BFF for writes). **The dummy's
`GET /api/v1/settings` blob is superseded for Pages.** The remaining sections are served by their
own reads (the settings slice's `data/settings-read.ts` / `data/static-sections.ts`); Pages is its
`"pages"` case. There is no settings fixture file.

### Read (`/frontend/v1`, server, `fetchRead`)

`GET /frontend/v1/settings/pages` → the spec §7.2 shape, camelCase, no envelope wrapper:

```json
{
  "settings": { "fallbackUrl": string|null, "pageTitle": string|null, "pageDescription": string|null,
                "faviconUrl": string|null, "socialPreviewUrl": string|null },
  "systemHostname": { "hostname": string, "label": string, "url": string },
  "customHostname": null | {
    "hostname": string,
    "status": "pending_dns"|"verifying_ownership"|"issuing_certificate"|"active"|"error"|"disconnecting",
    "records": [ { "type": "CNAME"|"TXT", "name": string, "required": string,
                   "observed": string|null, "ok": bool } ],
    "lastCheckedAt": string|null,
    "error": null | { "code": string, "detail": string|null },
    "url": string|null
  }
}
```

`customHostname` is `null` when none is connected; `url` is non-null only when `status == "active"`.
`records` always carries exactly the CNAME and the ownership TXT, in that order.
`faviconUrl` / `socialPreviewUrl` are absolute URLs on the workspace's system hostname
(`…/favicon.ico`, `…/asset-store/<sha256>`) and are `null` until an image is uploaded.

Auth: an active membership (the read surface's workspace dependency). Every **write** below
additionally requires `workspace.manage_settings` (clue_auth policy revision 3 — admin and owner);
without it the route answers `403` `PERMISSION_REQUIRED`.

The GET is not purely passive: when the custom row is non-active it re-derives status from DNS + the
provider, rate-limited to one derivation per 5 s per workspace (spec §7.1/§7.4). It never retries a
stuck removal — only "Check now" does.

### Writes (`/frontend/v1`, browser, `fetchMutation` through `/api/clue/frontend/v1`)

| Method + path | Body | Success | Notes |
| --- | --- | --- | --- |
| `PATCH /settings/pages` | `{ fallbackUrl?, pageTitle?, pageDescription? }` | `200` + the read shape | Partial: an absent key is untouched, an explicit `null` clears. Unknown keys are refused (`extra="forbid"`). |
| `POST /settings/pages/favicon` | multipart `file` | `200` + the read shape | ≤ 256 KB; `image/png`, `image/x-icon`, `image/vnd.microsoft.icon`, `image/svg+xml`. |
| `POST /settings/pages/social-preview` | multipart `file` | `200` + the read shape | ≤ 2 MB; `image/png`, `image/jpeg`. |
| `PATCH /settings/pages/system-hostname` | `{ "label": string }` | `200` + the read shape | The Clue address label (spec §4.1 A1, superseded 2026-09-28). **The label locks at the workspace's first publish**; after that the change is refused with `label_locked`. Until then a change frees the old hostname immediately; there is no redirect. |
| `POST /settings/pages/custom-hostname` | `{ "hostname": string }` | **`201`** + the read shape | Connect. One custom hostname per workspace. |
| `POST /settings/pages/custom-hostname/check` | — | `200` + the read shape | "Check now". **Membership only** — it reads the world rather than changing it — and it is the one path that retries a stuck `disconnecting` removal. |
| `DELETE /settings/pages/custom-hostname` | — | **`204`**, no body | Ordered removal (row → `disconnecting`, provider delete, row deleted). |

Both uploads go through the same storage path as design assets; there is no second upload route.

### Refusals

Every refusal is the frontend-read envelope: `{ "error": { "code", "message", "requestId" } }`.

| Code | HTTP | When |
| --- | --- | --- |
| `PERMISSION_REQUIRED` | 403 | Any write without `workspace.manage_settings`. |
| `UNAUTHORIZED` | 401 | No principal on a deployment that does not allow local mutations. |
| `VALIDATION_ERROR` | 422 | `fallbackUrl` does not start with `https://`. |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | Upload content type outside the allowed set. |
| `PAYLOAD_TOO_LARGE` | 413 | Upload over the section's byte cap. |
| `PAGES_STORAGE_UNAVAILABLE` | 503 | The deployment has no storage backend. |
| `label_invalid` / `label_reserved` | 422 | Label shape (3–40 of `[a-z0-9-]`, no edge hyphen) / reserved word. |
| `label_taken` | 409 | Another workspace holds that Clue address. |
| `label_locked` | 422 | The workspace has already published a site, so its label is fixed. Message: "This address has already published a site, so its label is fixed." |
| `hostname_invalid` | 422 | Not a valid hostname after normalisation. |
| `hostname_reserved` | 422 | Under our own registrable domain (`cluehq.ai`). |
| `hostname_is_apex` | 422 | The hostname equals its registrable domain — a dedicated subdomain is required. |
| `custom_hostname_exists` | 409 | This workspace already has a custom row; remove it first. |
| `hostname_taken` | 409 | The hostname is already connected to a workspace. |
| `PROVIDER_NOT_CONFIGURED` | 503 | Connect on a deployment with no Cloudflare token/zone. Everything else on the screen still works. |
| `provider_error` | 502 | Cloudflare refused. On removal the envelope also carries `"retryable": true` and the row stays `disconnecting`. |
| `CUSTOM_HOSTNAME_NOT_FOUND` | 404 | Removing when nothing is connected. |
| `SYSTEM_HOSTNAME_MISSING` | 500 | The workspace has no system hostname row — run `make pages-backfill-hostnames`. |

The hostname and label codes are the spec's own lowercase codes (from
`clue_spine.hostnames.validate_custom_hostname` / `validate_label`, `label_locked` from
`replace_system_label`, plus `provider_error`); every
other code is the read surface's uppercase envelope convention. Validation order is
invalid → reserved → apex, so our own zone apex reports `hostname_reserved`, not `hostname_is_apex`.

`customHostname.error.code` on the read is a different, closed set — the provisioning failure the
row last observed, not an HTTP refusal: `cname_incorrect`, `txt_missing`, `caa_blocked`,
`hostname_taken`, `verification_expired`, `provider_error` (spec §7.5).

### Frontend seam

- `src/features/settings/model/pages.ts` — the Zod schemas (`PagesSettingsReadSchema`), the
  `connectionView` / `stepIndex` derivations and `REFUSAL_MESSAGES` (copy per refusal code).
- `src/features/settings/data/pages.repository.ts` — `getPagesSettings()` over `fetchRead`
  (`src/features/accounts/data/frontend-api.ts`), reached through the settings slice's
  `readSettingsSection` (`src/features/settings/data/settings-read.ts`, the `"pages"` case).
  **No fixture mode:** a misconfigured or unauthorised surface throws `ClueApiError` rather than
  rendering an empty screen.
- `src/features/settings/data/pages.actions.ts` — the JSON mutations over `fetchMutation`, and the
  204 removal over `fetchMutationVoid` (both in `src/features/accounts/data/frontend-mutation.ts`),
  plus `uploadPagesImage`, which calls the BFF with a
  raw `fetch` because the browser must set the multipart boundary itself; the BFF catch-all
  (`src/app/api/clue/[...path]/route.ts`) forwards the raw body and headers, so the boundary
  survives the hop.
- `src/features/settings/hooks/use-pages-settings.ts` — holds the read as state, replaces it with
  each mutation's response, and polls `check` every 5 s while the connection view is `connecting`.

The screen is `src/app/(protected)/settings/[[...section]]/page.tsx`; it fetches the Pages read only
for the `pages` section and passes `canManage` from
`session.principal.permissions.includes("workspace.manage_settings")`. A caller without it sees the
section read-only (no input, no Connect, no Check now, no Remove) rather than a hidden section.
