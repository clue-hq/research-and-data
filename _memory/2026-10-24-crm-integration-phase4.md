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
All passed on both test CRMs; the two fixes re-checked live after restarting on `e885c7cf1`.

## Gotchas
- Composio `check_existing` doesn't detect existing Salesforce fields; outer `successful` hides an
  inner `success:false` — read the inner result.
- After a workspace switch in the same tab, cards read "belongs to a different conversation" until a
  full reload (L12 / L4-4).
- A stack restart cuts off a running wake turn (no reply; the write is already done).

## Open
- L4-3: skill/tool-note line naming the duplicate-link action per CRM (founder wording, re-mint).
- L4-4 (= L12) frontend fix; minors L4-5 (HubSpot create can't carry clue_id), L4-6 (duplicate card
  title has no name). R-13.7 lookup by Clue id deferred. L-14 (Phase 3) still undecided.
- Not pushed; the founder decides when.
