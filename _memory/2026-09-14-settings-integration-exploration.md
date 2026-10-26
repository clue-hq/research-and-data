# 2026-09-14 — Settings section: exploration before integration planning (no code changed)

**Lane:** `research-streaming`, worktree `san-salvador`. Exploration only; nothing committed.

## What exists

- **Presentation truth:** the co-founder's dummy frontend at `http://localhost:3000/settings`, served
  from `/Users/aryankeshri/conductor/workspaces/clue-frontend/live-backend-v1` — the founder-named reference path (a symlink to the `port-of-spain` checkout that serves :3000; branch
  `integration/live-backend-v1`, HEAD `64232a0` 2026-09-13 "coming soon previews"). Route
  `src/app/settings/[[...section]]/page.tsx`; feature `src/features/settings/{components,config,data,model}`;
  frontend-authored contract proposal `docs/api-contracts/settings.md` (Figma `NcLl2r0dzVDN28xAQCwvM1`
  page `Settings-dev-ready` `1735:38951`). Entry point: `components/shell/sidebar-profile-menu.tsx`
  → `/settings/profile`.
- **This repo's `apps/frontend` has NO settings feature or route** (`/settings` → 404 on :3020) and no
  `sidebar-profile-menu.tsx`; its `app-sidebar.tsx` has the profile trigger but no menu/settings link.
  `packages/design-system/generated/tokens.css` is byte-identical to the dummy's, so the settings CSS
  lifts cleanly.
- Nine sections: Profile, Connections, MCP server (personal) / Workspace, Members, Integrations,
  Pages, Data model, Billing (admin). Connections, MCP server, Integrations are rendered as inert
  "Coming soon" previews by the dummy itself. Data model has nested routes
  `/settings/data-model/{accounts|contacts}/{fields|display}` (Relationships tab present, no route).
- Dummy reads one blob `GET /api/v1/settings` (fixture unless `CLUE_API_BASE_URL`), no mutations
  wired anywhere (zero onSubmit/onClick handlers in the settings components); the contract doc lists
  14 proposed mutation endpoints "documented but deliberately not called".

## Backend readiness per section (lane DB `clue_san-salvador`, read-only)

| Section | Substrate today | Gap |
| --- | --- | --- |
| Profile | `platform_user(first_name,last_name,display_name,job_role)`; `clue_auth.store.update_platform_user_profile/_display_name` | no HTTP route; avatar lives in Clerk only (no column); design shows Full name + Display name + picture |
| Workspace | `workspace(name)`; website only in `self_serve_provisioning.company_website`; brand kit `design_brand_kit` | no workspace website/logo column; no read/write route |
| Members | `workspace_membership`, `workspace_invitation` (token digest, expiry, status), store fns invite/role/revoke/readmit; `ROLE_PERMISSIONS` | zero HTTP routes; role vocab mismatch (design Admin/Member vs backend owner/admin/operator/viewer); no invitation email sender found; "Joined on" needs `activated_at` |
| Billing | `millicredit_rate` groundwork (0 rows), per-call cost columns (`agent_model_call.cost_millicredits`, `provider_call_ledger.credits`, …) | no plan/credit ledger, no payments provider; "Manage plan"/"Top up" undefined |
| Pages | design `design_web_publish` (workspace-local slugs, per-document `noindex`) | no workspace-level custom domain / fallback / favicon / social preview / head+body snippets / llms.txt |
| Data model | `field_definition` 161 active (139 unpacked + 22 `client`), `workspace_field_definition` (+`presentation`, proposal promotion), `display_section_recipe` | design vocab (Type / Editable by / AI fill / System / Create field / Relationships / Display order) unmapped; accounts column visibility is static in `account-table-view.ts` |
| Connections / MCP / Integrations | nothing | dummy shows them as coming soon; leave as lifted previews |

Existing read surface `/frontend/v1` has accounts, brand-context, project documents only. Seam
pattern to follow: `fetchRead` (server, `/frontend/v1`) + `fetchMutation` (browser → `/api/clue/frontend/v1`),
Zod models, fixtures only behind an explicit fixture flag.

## Open questions for the founder (planning not started)

1. Slice order — recommended by readiness: Profile+Workspace+Members → Data model → Billing/Pages.
2. Contract shape: dummy's single `GET /api/v1/settings` blob vs this repo's per-section `/frontend/v1/settings/*`.
3. Members role vocabulary + whether invitations must send email in v1.
4. Billing: what "plan" and "credits" mean before any ledger exists.
5. Pages: custom-domain hosting is a product/infra decision (Part IV ruling: tenant-subdomain v1).

## Founder rulings from the component-by-component discussion (2026-09-14, later)

Cross-cutting
- **Autosave on blur** for every editable field; an ephemeral bottom-right confirmation card
  ("Profile updated", check icon, close) styled with the platform design-system tokens. No toast
  primitive exists in either frontend today; this card is new UI the founder authorised.
- **Sidebar person = the signed-in user's display name**, initials from it; no placeholder /
  shell name anywhere. The dummy's `sidebar-profile-menu.tsx` (→ `/settings/profile`) is lifted.
- Contract shape follows this repo's convention: per-section reads under `/frontend/v1/settings/*`
  via `fetchRead`, mutations through the BFF via `fetchMutation`; not the dummy's single blob.

Profile — READ + PATCH. Full name = first + last joined; PATCH splits on the first space. Display
name → `platform_user.display_name`. Initials avatar with the design's single colour; no upload.

Workspace — Organization name = `workspace.name`, **editable** (needs a spine rename fn + route;
brand rows untouched). Logo slot binds the current brand kit's primary logo, falls back to the
designed icon; no upload. **Company website read-only (option C)** until a rebuild-from-new-site
flow exists; read from `self_serve_provisioning.company_website` by workspace id; no column added
now. (Note: that receipt is the wrong long-term home — per-owner, DSAR-erasable.)

Members — **Clerk application invitations** deliver the email (`createInvitation` with a redirect
URL carrying our token; Clerk auto-verifies the address; 100/h limit; template branded in the
Clerk dashboard); Clue owns the invitation row, the role and the membership; acceptance = the
existing `accept_workspace_invitation` transaction from the session-establish step. Known limit:
Clerk refuses invitations for an email that already has an account in the instance → row is
created, shows "Invited", accepted on that user's next sign-in, no email. Member email must be
persisted on `platform_user` (captured from Clerk at signup/acceptance; backfill on next sign-in) —
no email column exists today. Roles: dropdown Admin ↔ `admin`, Member ↔ `operator`; **owner row
displays "Admin", locked**; `viewer` dormant. Row ellipsis = design-system dropdown with Remove
from workspace / Revoke invitation / Re-admit; removed members stay listed with "Removed" in the
Joined-on column.

Data model — **re-scope with the co-founder before wiring**: page becomes "Research fields" per
entity (Accounts = active `core.*`+`account.*` = the account job's menu, 70 keys; Contacts =
`contact.*` + `core.work_email`, 70 keys) showing Name + Description; **Create field kept, at
workspace level only** (a standing research question whose description is the instruction);
Editable by, AI fill, Relationships and the Display tab **dropped**. Mechanics recorded: the global
`field_definition` is cross-tenant (a created row would enter every workspace's menu);
`workspace_field_definition` refuses non-`client.*` keys and needs a proposal id; neither catalog
reader (`read_account_catalog` / `read_person_catalog`) reads workspace rows → the Track R change
is: allow `account.*`/`contact.*` workspace rows created from Settings, and union them into the
menu per workspace. Human field edits: none exist, not planned.

Billing — **stays dummy** (fixture). Lane 3 slice 1 (`GET /cost/report`, USD) is the future base;
credits milestone uncomposed (`cost_millicredits` = 0 by decision; `millicredit_rate` empty); no
payments provider. Suggested: coming-soon overlay so fixture numbers aren't read as real (open).

Pages — **stays dummy**. Public pages serve at `/w/{workspace_id}/p/{slug}` on the design API;
subdomain ruling unbuilt; 0 publishes; per-document noindex is the rule (design's index-on
default is wrong for ABM pages). Re-scope note for later: brand-kit-sourced favicon/og/title,
fallback URL, head/body snippets (security review); no custom domain, no index toggles, no llms.txt.

Connections / MCP server / Integrations — lifted as the dummy's inert Coming-soon previews.

Slice order agreed: (1) Profile + Workspace + Members; (2) Research fields after the co-founder's
redraw; Billing and Pages dummy. **Design spec written 2026-09-15 for founder review:
`docs/superpowers/specs/archive/2026-09-15-settings-integration-design.md` (carries assumptions A1 overlay on
Billing/Pages dummies, A2 real workspace name in the profile-menu caption). No code yet; the plan
is drawn only after the founder approves the spec.**

## Addendum 2026-09-15 — Research fields fully specified (spec §9)

Founder asked for the complete Data-model spec. Written into the same spec as §9.1–9.7 (commit
after `a73f6d97c`). Key design facts found while writing it:
- `insert_claim` → `check_claim_writable` → `validate_effective_value` resolves keys through the
  per-workspace overlay `workspace_field_definition` (global + workspace rows, retirement and the
  erasure marker joined). A NEW table would be invisible to that gate → the lenient writer would
  file every custom-field claim as a global *proposed* field (cross-tenant). So the home is the
  existing overlay with its old-lane-only CHECKs relaxed (namespace `client.%` → +`account.%`/
  `contact.%`; pack CHECK split; `promoted_from_proposal_id` nullable; `client_kb_role` +`research`;
  new nullable `label`). Table is on the Phase-6 KEEP list (claim-store substrate), so this is not
  an old-lane bridge.
- New registry fns: `register_workspace_research_field`, `update_workspace_research_field`;
  `retire_workspace_field` reused (`human:` prefix). Catalog readers `read_account_catalog` /
  `read_person_catalog` take `workspace_id` and union the workspace rows (call sites hold it).
  Accounts custom-column SQL drops `pack='client'`. Contact custom fields: no designed slot → invisible.
- New permission `workspace.manage_settings` (policy revision 3; admin+owner) for rename + fields.
- Routes: `GET/POST /frontend/v1/settings/research-fields`, `PATCH/DELETE …/{key}`; key derived
  from label; description required (it is the instruction); retire is final (two-step confirm).
- Open for the founder: R-1 show all platform keys incl. bookkeeping ones (no hidden flag added).
- Frames owed by the co-founder: the Research fields table; the Create field form (invite-row pattern).
- Follow-up (Track R): `_register_proposed_field` still files agent-invented keys globally.

