# CRM integration — Phase 2 (write foundation), 2026-10-22

Continues `_memory/2026-10-20-crm-integration-phase1.md`. Branch `feat/crm-integration` (nashville
lane). Plan `docs/superpowers/plans/2026-10-22-crm-integration-phase-2-write-foundation.md`,
executed subagent-driven (Opus implementers, per-task reviews; ledger in
`.superpowers/sdd/2026-10-22-crm-integration-phase-2-write-foundation/progress.md`, git-ignored).
Rulings R-11.x in `docs/superpowers/specs/crm-integration/rulings.md`; status in `status.md`.

## Built (Tasks 1–10)
- `platform/api/clue_api/crm/`: `write_actions.py` (allowlist + parsed changes), `writes.py` (DAL),
  `write_prepare.py` (reads, picklist check, overwrite marker, `card_snapshot`), `write_tools.py`
  (`propose_crm_changes`, `crm_write_log`, `manage_crm_grants`), `write_executor.py` (fleet kind
  `crm_write`), `write_answer.py` (card answer, progress), `wake.py` (finished/paused wake turns).
- Migrations `ebf28e41a6a4`, `a3b587b8fdfd`, `0e92986934d3`, then `f09f9e286be6`
  (`agent_turn_submission.agent_reply`, R-11.6).
- Frontend: `integrations/model/crm-write.ts`, `projects/components/crm-write-permission-card.tsx`,
  `hooks/use-crm-proposal-progress.ts`; gate state `withdrawn`; turn list `answered_gate_id`.
- Catalog: `crm-writing/v1`, `crm-sales-analysis/v2`, head-of-abm `v77`, recipe 37, manual v23
  (re-minted in place twice: gate line + `#crm_write_log`/`#manage_crm_grants`; refusal row).
- Skills-block budget raised to 5632 (founder).

## Live check (Task 11) — see `docs/superpowers/specs/crm-integration/2026-10-22-phase-2-live-check-findings.md`
Passed on HubSpot (Conduit AI) and Salesforce (Garner Health): propose → card → allow (+ always
allow) → read-back → log → undo without a card → revoke; create (one CRM refusal, one success);
Salesforce refusal, overwrite row, undo. Four card answers started no agent turn (R-11.6 live).
Cost ≈ $6.50 (Langfuse by chat). Fixed mid-run: L1 card link type (`e672ab95c`), L2 record names
(`e93ad4a27`), L3 option labels (`17c3e5ff3`), double turn (`0e68df0a1`, `6935eb0d2`), bubble
(`fac5e0f75`). Open: L5/L6/L10 founder questions, L8/L9 fixes, minors L4/L7/L11.

## Operational notes (not product findings)
- Stopping a background Bash task that had started the stack's APIs/workers inside it (TaskStop)
  killed them; the replacement workers never served the queue (logs stopped). Restart the stack
  with a plain double fork `(nohup ./scripts/dev_stack_nashville.sh restart-… > /tmp/x.out 2>&1 &)`
  from a foreground Bash, never inside a task you may stop. `setsid` does not exist on macOS.
- The chat composer's Send button becomes Stop while a turn runs: a second click cancels the turn
  (`stop_requested`). Check for a submission in the DB before clicking again.
- The test account that owns both test workspaces is `aryan+clerk_test_arv2@example.com` (the
  runbook's password is for a different test account); the founder signs in.
- `.test` email domains are refused by HubSpot (`INVALID_EMAIL`); `@example.com` is accepted.

## Next
- Founder calls on L5 (list lookup/create action), L6 (per-change not-found), L10 (composite patch
  for fields the named action lacks); fixes L8, L9.
- Whole-branch Fable review (Phase 1 + Phase 2), one fix wave, finishing-a-development-branch.
- Not exercised live: "Don't allow" + decline context line, replace of an unanswered card, paused
  batch, 422/409 refusals, list membership, SF picklist pre-check.
