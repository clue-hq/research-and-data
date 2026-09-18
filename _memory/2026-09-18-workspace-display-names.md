# 2026-09-18 — Workspace display names (chooser + sidebar switcher on real memberships)

Spec `docs/superpowers/specs/2026-09-18-workspace-display-names-design.md`; plan
`docs/superpowers/plans/2026-09-18-workspace-display-names.md`. Branch `feature/workspace-display-names`
off research-streaming; SDD with Opus implementers, Fable reviewing.

## Rulings (founder, 2026-09-18)
- The display name is `workspace.name` (no new column). Typed company name first at provisioning,
  else `clue_core.normalize.canonical_workspace_name(website)` (host minus `www.`, registrable
  label, `-`/`_` split, capitalised; multi-label suffixes such as `co.uk` treated as suffixes;
  IP/dotless → None). Neither → 422 `COMPANY_NAME_REQUIRED` in the auth app's `{"error": …}` envelope.
- Both the post-sign-in chooser and the sidebar switcher land on `/`.
- The backfill renames only legacy workspaces (`name = workspace_id`) that have a
  `self_serve_provisioning.company_website` with a derivable name; dry-run by default.
- Users never see a workspace id: the session carries `workspace_name` per membership.

## Commits
- fbde3a652 backend: rule (reuses `normalize_host`), provisioning precedence + `ProvisioningValidationError`,
  `WorkspaceMembership.workspace_name` filled by the loader's JOIN, `SessionMembershipResponse.workspace_name`;
  design `_host_brand_name` delegates (now the registrable label: `shop.example.com` → Example).
- a20d21ebd `scripts/backfill_workspace_names.py` (+ rolled-back DB test). Lane dry-run: 0 renames —
  the lane's 943 id-named workspaces are dev rows without a provisioning row. Apply on real environments
  with `--apply` after reading the printed plan (the founder's step).
- 275c359c6 / d247be465 / e4c7ce6b8 frontend: strict session schema with `workspace_name`; chooser
  renders names; `WorkspaceSwitcherProvider` moves into the protected layout with the session's
  memberships (name, initials, role) and `onSelect=switchWorkspace` (server action: cookie + redirect
  `/`); demo store kept for fixture builds; `roleLabel` lives in `features/session/model/session.ts`
  (a server layout may not call a `"use client"` export — the walk caught it).
- Onboarding: `company_name` optional on the wire and in the profile screen (hint
  "Leave blank to use your website's name"); the website is required.

## Verification
- Backend: `tests/auth` 80 + `tests/core/test_canonical_workspace_name.py` 10 + backfill DB tests 3;
  lint-imports 28/0; mypy clean; design capture tests 62.
- Frontend: npm test 3171/3172 (1 pre-existing skip), lint 0 errors, tsc no new errors, `npm run build`
  green (re-run after the fix round).
- Browser (test account, temporary second membership added then deleted): chooser names+roles, no id in
  page text; choose → `/`; sidebar identity = chosen workspace; submenu lists both with the active check;
  switching lands on `/` with the sidebar renamed. Screenshots: /tmp/chooser-names.png, /tmp/switcher-open.png.

## Owed
- A real self-serve provisioning with a blank company name (acceptance 3) on a fresh Clerk user.
- Running the backfill with `--apply` on any environment that has legacy provisioned workspaces.
