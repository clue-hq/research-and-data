# Workspace display names — design

**Status:** approved by the founder 2026-09-18 (rulings: typed company name first, canonical
domain form as fallback; both the post-sign-in chooser and the sidebar switcher land on the home
page; the backfill renames only legacy workspaces that have a provisioning website).

## 1. The problem

Users see workspace ids. The chooser after sign-in lists `ws_…` strings, and the sidebar switcher
lifted on 2026-09-18 (`f124050ad`) cannot switch a real tenant because the session carries no
names. 941 of the lane's 944 workspaces were born with their id as their name.

## 2. What exists (verified 2026-09-18)

- `workspace(workspace_id, name NOT NULL, status, created_at)`; no other human-facing column. The
  name is editable through `PATCH /frontend/v1/settings/workspace` (`rename_workspace`).
- The website the user typed lives on `self_serve_provisioning.company_website`, joined to the
  workspace by `workspace_id` (the Settings workspace read already does this join).
- Birth: `provision_self_serve_workspace` writes `workspace.name = company_name` (required);
  seeds, scripts and the design store write `name = workspace_id`.
- `GET /auth/v1/session` → `memberships[]: membership_id, workspace_id, role_key, permissions`;
  the frontend schema is `.strict()`. Nothing joins `workspace.name`.
- The frontend's current workspace name comes from a separate `GET /settings/workspace` read in
  the protected layout. The chooser renders `membership.workspace_id`. The switcher is a fixture
  preview with three hard-coded workspaces.
- The design subsystem has the exact domain→name rule wanted: `_host_brand_name` in
  `lumen_ingestion/capture/parse.py:1756`.

## 3. Design

### 3.1 The display name is `workspace.name`
No new column. Every surface that names a workspace reads `workspace.name`; no surface renders a
workspace id.

### 3.2 One canonical rule, shared
`clue_core.normalize.canonical_workspace_name(website: str | None) -> str | None`: parse the
host (a scheme is optional), lower-case it, drop a leading `www.`, take the registrable label
(the label before the public suffix, treating the design ladder's multi-label suffixes such as
`co.uk`/`com.au` as suffixes), split it on `-` and `_`, capitalise each part, join with spaces.
`https://www.acme-health.com/x` → `Acme Health`; `bright_side.co.uk` → `Bright Side`; an IP
literal, a dotless host or blank → `None`. The design subsystem's `_host_brand_name` delegates to
it (design may import `clue_core`).

### 3.3 Birth
`ProvisionRequest.company_name` becomes optional. The workspace and its first brand are named by
the typed company name when present, else by `canonical_workspace_name(company_website)`; a
request with neither yields 422 `COMPANY_NAME_REQUIRED`. The frontend profile screen keeps both
fields, requires the website, and treats the company name as optional ("Leave blank to use your
website's name").

### 3.4 The session carries names
`WorkspaceMembership` gains `workspace_name: str | None = None`; the database loader's SQL joins
`workspace` and fills it. `SessionMembershipResponse` gains `workspace_name: str` (the loader's
value, falling back to the id only for a non-database loader in tests). The frontend
`SessionMembershipSchema` gains `workspace_name` in lockstep. `ProtectedSession` keeps its shape.

### 3.5 Surfaces
- `/select-workspace` lists `workspace_name` with the role, never the id; selecting lands on `/`.
- The sidebar switcher shows the user's real memberships (name, initials from the name, role) and
  is enabled in live mode; selecting calls the existing cookie-setting server action and lands
  on `/`. The provider moves from the root layout into the protected layout, where the session
  is known; the demo preview stays for fixture builds.
- The sidebar identity block reads the active workspace's name from the session; the Settings
  workspace read stays for the logo and the Settings section.

### 3.6 Backfill
`scripts/backfill_workspace_names.py` (dry-run by default, `--apply`): for every workspace whose
`name = workspace_id` and whose provisioning row has a website with a derivable name, set the
name. Workspaces with a real name, and test rows without a website, are untouched. Idempotent.

### 3.7 Not changed
Renaming in Settings, the local pinned-instance name, `design_workspace_handle`, invitations,
the principal contract, the workspace cookie.

## 4. Environment
No new keys.

## 5. Acceptance
1. Sign in with the test account: the chooser shows workspace names with roles, no id anywhere
   in the DOM text; choosing one lands on the home page.
2. The sidebar switcher lists the same memberships by name, the active one checked; picking
   another switches the tenant (the sidebar and the accounts screen change) and lands on `/`.
3. Provisioning with a blank company name and `www.acme-health.com` creates "Acme Health".
4. The backfill dry-run on the lane lists the legacy rows it would rename and applies them.
5. Gates: named backend suites on the lane DB, `lint-imports`, `ruff`, `mypy`; frontend
   `npm test`, `npm run lint`, `npm run build`; contract docs `session.md` and `onboarding.md`.
