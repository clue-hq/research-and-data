# CRM integration — Phase 4 (Clue's own fields), 2026-10-24 → 2026-10-25

Continues `_memory/2026-10-23-crm-integration-phase3.md`. Branch `feat/crm-integration-phase-4`
(nashville lane), cut from `feat/crm-integration-phase-3` (pushed, no PR). **Unpushed.** Plan
`docs/superpowers/plans/2026-10-24-crm-integration-phase-4-clue-fields.md` (Tasks 1–7), executed
subagent-driven (Opus 5.5 implementers + per-task reviews, Opus whole-branch review); ledger
`.superpowers/sdd/2026-10-24-crm-integration-phase-4-clue-fields/progress.md` (git-ignored). Rulings
R-13.1–R-13.7 in `docs/superpowers/specs/crm-integration/rulings.md`; live check record
`docs/superpowers/specs/crm-integration/2026-10-25-phase-4-live-check-findings.md`.

## Built
- Registry `crm_clue_fields` (migration `53f06d57df36`, down `31b850b308e6`), names object-qualified.
- `propose_clue_fields_setup@1` (owner/admin only) → `clue_fields_setup` run: HubSpot group/props/
  label; Salesforce fields + own permission set `Clue_Fields` + assignment (R-13.1) + SOQL read-back.
- Clue field writes gated on `ready` + field present; gone field → refused + marked gone.
- `link_duplicate` (HubSpot association label; Salesforce `Clue_Possible_Duplicate__c` lookup);
  `crm_possible_duplicate` refusal on a create that finds >1 contact.
- crm-writing v5, Head of ABM v82 (recipe 42, manual v28, stage0-interview v55).
- Final fix pass: HubSpot contact updates via `HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID`
  (`HUBSPOT_UPDATE_CONTACTS` drops custom props + `hs_buying_role` — also hit Phase 3); one entry
  per record in Salesforce composite / HubSpot company batch (`DUPLICATE_VALUE`); precise gone match;
  setup "already set up" done line.

## Live check (stack DB `clue_nashville_pm` at `53f06d57df36`)
All passed on both test CRMs; the two fixes re-checked live after restarting on `e885c7cf1`; the
follow-up fixes re-checked on v83.

## Gotchas
- Composio `check_existing` doesn't detect existing Salesforce fields; outer `successful` hides an
  inner `success:false` — read the inner result.
- After a workspace switch in the same tab, cards read "belongs to a different conversation" until a
  full reload (L12 / L4-4).
- A stack restart cuts off a running wake turn (no reply; the write is already done).

## Follow-up fixes (2026-10-25, all re-checked live)
- L4-3: crm-writing v6 names the duplicate-link action per CRM → Head of ABM v83, manual v29,
  stage0-interview v56, recipe 43 (`5acc1f44c`; v82 untouched — live turns pin it).
- L4-4 (= L12): chat requests send `X-Clue-Page-Workspace`; the BFF answers `WORKSPACE_CHANGED`
  (409) when the selected workspace moved, and the page reloads (`72bec6309`, founder's choice).
- L4-5: HubSpot creates carry `custom_properties.clue_id`; L4-6: one-link card names the person
  (`e9261082c`).

## Open
- R-13.7 lookup by Clue id deferred. L-14 (Phase 3) still undecided. L4-8 harness retry error.
- Pushed to origin 2026-10-25 (no PR yet, by founder instruction).

## 2026-10-25 (later) — own OAuth apps, live check, D-1/D-2
- Own apps (R-14.1–R-14.5): HubSpot app `clue-hubspot` in dev account `clue-hq-dev` (13 scopes);
  Salesforce packaged external client app in a 2GP managed package, namespace `clue`, beta
  `04tg7000000aSozAAE` installed in the Garner test org; Composio custom configs HubSpot
  `ac_jD3YXBrp_2ed`, Salesforce `ac_k9cNBS3hGCgM` (scopes + v3 redirect set via PATCH, which merges
  credentials). Nashville `.env` points at both. Package project at `~/clue-salesforce`, HubSpot
  project at `~/clue-hubspot-app/clue-hubspot` (outside the repo).
- The nashville branch was fast-forwarded (by the founder) to `integration/f3-onto-crm-phase-4`;
  stack DB migrated in place to `b1d0eb59cd73`; F3's `CLUE_AGENT_WORKSPACE_*` keys added to `.env`.
- Live check `docs/superpowers/specs/crm-integration/2026-10-25-own-oauth-apps-live-check-findings.md`:
  both CRMs pass through Clue's own apps. D-1 (F3: two chats of one project deadlocked on
  `lock_project`) fixed `2e367467b` with `FOR NO KEY UPDATE`; D-2 (reconnect lost undo) fixed
  `dc2627ae2` — a reconnect to the same org/portal reuses the connection (`external_account_id`
  from who-am-I). Both re-checked live. D-5: `test_status_facts_are_workspace_scoped_…` fails on
  the merged branch regardless (ARV2 seeding FK), not ours.
- Test CRMs: old connections are `expired` rows; the agent can't open the connect pop-up (founder
  clicks Connect). A Phase 3 card re-proposed in Conduit chat `thr_9a8eef…` is still waiting.
- Before production: Salesforce Partner Business Org link for the `clue` namespace, release a package
  version, HubSpot Marketplace listing before install 25, privacy/terms links, Composio ZDR and a
  production Composio project.
