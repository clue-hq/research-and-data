# CRM integration — Phase 3 (first writes), 2026-10-23 → 2026-10-24

Continues `_memory/2026-10-22-crm-integration-phase2.md`. Branch `feat/crm-integration-phase-3`
(nashville lane), cut from `feat/crm-integration` (pushed after Phase 2). **Unpushed.** Plan
`docs/superpowers/plans/2026-10-23-crm-integration-phase-3-first-writes.md` (Tasks 1–12), executed
subagent-driven (Opus implementers, per-task Opus reviews, Fable whole-branch review); ledger in
`.superpowers/sdd/2026-10-23-crm-integration-phase-3-first-writes/progress.md` (git-ignored — every
controller/implementer ruling and deferred minor is there). Rulings R-12.1–R-12.18 in
`docs/superpowers/specs/crm-integration/rulings.md`; live-check record
`docs/superpowers/specs/crm-integration/2026-10-23-phase-3-live-check-findings.md` (L-1–L-17).

## Built
- Tasks 1–9 (plan): list registry `crm_list`/`crm_list_project` (migration `31b850b308e6`), list
  create + `new:<list name>` on one card, `read_crm_targets`, R-8.7 gate in prepare, record links,
  `find_crm_list`/`link_crm_list`, crm-writing v2 / Head of ABM v78.
- R-12.10 (founder): catch-all emails count as checked.
- Task 10 (R-12.11): `new:company:<domain>` / `new:contact:<email>` — one card creates records and
  uses them; executor stages creates first and fills ids. crm-writing v3, v79.
- Task 11 (R-12.12–R-12.14): name cleaning, card labels by name, stage0 prompt line against recording
  Clue-written messages; no duplicate company for an account Clue knows; stale company links
  forgotten when the CRM record is gone. v80.
- Task 12 (R-12.15–R-12.18): HubSpot deleted-list answer → gone; a turn's still-open cards are always
  shown (every kind, superseded drafts skipped, replay-stable); `crm_write_log` ids internal +
  crm-writing v4 sentence; card polls 15 s while hidden and re-reads on the wake. Head of ABM **v81**,
  recipe 41, manual v27, stage0-interview v54.
- Final fix pass (after the Fable review): Salesforce deleted campaign → gone; kept list verified by
  id before a create is refused (L-17); read-back by id (L-3); same-named list adoption; project link
  on a shared list.

## Live checks (nashville stack, DB `clue_nashville_pm` migrated in place; test DB `clue_nashville_crm_test`)
- HubSpot (Conduit AI) and Salesforce (Garner Health) flows passed; step 4 (deleted-list recovery)
  passed on v81 — HubSpot list 18 deleted by the founder, 19 created in its place.
- Left in the test CRMs: HubSpot lists 17 "Clue: spike" (empty) and 19 "Clue: Conduit AI hotel
  operators" (ATMA, Baywood); companies created by the runs (10 hotels, Atrium, ATMA, Baywood);
  contacts Rob Mangiarelli + test contact. Salesforce: campaign "Clue: US employer benefits"
  (701jV00000HsI7qQAF) with 6 members; accounts Syracuse City School District, Carmel Clay Schools;
  spike campaigns "Clue: spike", "Clue: spike active".
- A hidden card `59ace5ee` from the 2026-10-24 Conduit wake (pre-Task 12) is still
  `awaiting_permission`; harmless (replaced by the next proposal in that thread).

## Gotchas found this phase
- The Claude in-app browser reports the page as `hidden` even when shown → anything gated on
  visibility (card polling before R-12.18) stalls there.
- Restart the stack only by double fork; `restart-api` leaves the APIs DOWN for ~1 min before UP.
- When the founder's laptop sleeps, turns lose the network and are abandoned (L-10, not CRM).
- Frontend `crm-write.test.ts` and the hook tests use `node:test` → `npx tsx --test <file>`.
- Version clash with the F3 workspace lane (its head-of-abm v78 / manual v24 / stage0 v51):
  founder ruled F3 renumbers once at merge, above wherever this branch ends.

## Open
- L-14: code check against recording Clue-written messages — founder left undecided (prompt only).
- Deferred minors: ledger "minor (deferred)" lines (list adoption of a person's same-named list,
  two-transaction gone marking, SF sharing-rule "gone", etc.).
- Open frontend bugs L12/L14 (Phase 2) and L-11/L-16 display notes.
- Not pushed; the founder decides when.
