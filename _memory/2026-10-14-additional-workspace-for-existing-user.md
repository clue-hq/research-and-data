# 2026-10-14 — Operator-added workspace for an existing user

**Ask (founder):** let shank@cluehq.ai add one more workspace in production on their existing
account (no new email), then do onboarding/ingestion in production through the product.

**Branch:** `platform/admin-additional-workspace` in the nashville worktree, cut from
`origin/main` `baafd4e3a` (upstream unset; not pushed). Plan:
`docs/superpowers/plans/2026-10-14-additional-workspace-for-existing-user.md`.
Note: nashville's running lane stack (3060/8061-8063) was started on
`design/linkedin-ad-skill-testing`; its Python servers do not reload, but `next dev` now serves
this branch's frontend until nashville is switched back.

## Decisions
- Self-serve signup stays first-time-only (refuses an active membership; `self_serve_provisioning`
  UNIQUE(user_id)). Untouched.
- **No migration.** The earlier proposal (relax `self_serve_provisioning` to one row per
  workspace) was made against an older branch. On main, onboarding starts via `POST /onboarding`,
  which needs only the selected workspace, exactly one brand, and a domain — it never reads the
  signup record.
- Onboarding starts from the browser, not the script: `POST /onboarding` also fires brand-kit
  ingestion against the design API, which is Railway-private and unreachable from the OVH
  worker VM.
- The link carries the workspace id and the screen selects it first (membership re-checked
  server-side), so a link can never onboard whichever workspace was selected before.

## Commits
1. `4a7f8398e` `clue_auth.provision_additional_workspace` (+ 11 DB tests).
2. `4f9e3dbbb` Settings workspace read: website from latest full onboarding run, logo from the
   workspace's approved kit, when there is no signup record (+1 test).
3. `4be9d331d` `scripts/provision_additional_workspace.py` (dry run default, `--apply`; prints
   the operator link) (+1 test).
4. `e62d67c9f` Frontend: `/onboarding/setting-up?workspace=<id>&website=<url>` selects that
   workspace via `selectWorkspace`, then mounts `LiveSetupScreen` (+4 parser tests).

## Verification
- Throwaway DB `clue_nashville_addws` (lane Postgres :55040, migrated to `ecc5f641c0d9`).
- `pytest tests/auth tests/scripts/test_provision_additional_workspace.py
  tests/api/test_frontend_read_settings_pages_db.py` → 106 passed, 0 skipped.
- Script on the throwaway DB: dry run rolled back; `--apply` committed; re-run refused
  (`already owns a workspace named 'Acme'`).
- Frontend: onboarding model tests 11/11; `npm run lint` 0 errors (2 pre-existing warnings in
  canvasOperations.ts); `tsc --noEmit` has 58 pre-existing errors, all in untouched test files.
  `npm run build` NOT run locally (dev server owns `.next`) — CI "Editor" job is the build gate.
- Final review: self-review (no reviewer subagents by founder rule).

## Owed (founder-triggered)
- Push + PR (→ main, and a copy → research-streaming) on instruction.
- Production walk after deploy (spends money: one onboarding run):
  `ssh ubuntu@40.160.37.148 'sudo docker exec -i vm-batch1-1 python - --email shank@cluehq.ai --website https://<site> --company-name "<Company>" --app-origin https://app.cluehq.ai' < scripts/provision_additional_workspace.py`
  → read the dry run → repeat with `--apply` → sign in as shank, open the printed link → watch
  setting-up release into the app → check switcher, Brand context, Settings website.

## Proxon Brand context replaced with the client's own product brief and ICP (2026-10-14)
- Onboarding split Proxon's one platform into 9 "products". Operator writes in production (dry run first, then
  applied; scripts mirror `save_knowledge_document`: new version, previous superseded, `operator_edit` stamp):
  - `product/proxon.md` v3 = the client's Agent Context Brief; `product/catalog.md` v3 lists Proxon only
    (offering_kind platform). 8 feature product rows archived; their pages superseded.
  - New brand-level `audience/icp-proxon-ai-workforce.md` v1 (proposed; passes `icp_authoring._validate_front`):
    gates size_50_plus, ai_in_two_functions, desk_based_workforce, accountable_ai_leader, buyable; 7 exclusions;
    persona_map economic_buyer/champion/user(finance)/blocker(security). Body = client ICP verbatim.
  - New `audience/persona-proxon-ai-workforce.md` v1. The 3 onboarding ICPs and 3 personas superseded.
- Gates are judged by the research agent (LLM) from rule/test text; code reads only the gate KEYS to file
  per-gate verdicts. The current Head of ABM (v70) writes ICPs project-scoped only, so a brand-level ICP
  needed an operator write.
- PR #118 (branch `fix/product-picker-skip-archived`): the product-set gate offered archived products;
  now active only. 17/17 gate tests on a throwaway DB.
