# 2026-08-08 — FI-2 slice 1 backend COMPLETE (global-lens read layer, Tasks 1–5) — closing entry

Same SDD process as slice 0 (Opus implementers + reviewers, fix rounds, scoped re-reviews, Fable whole-slice
final review — verdict: coherent, seam-clean, ZERO Criticals). Commits `94490772..feb4c5ec` (12), local only.
Task 6 (frontend Zod/adapter flip) NOT started — gated (below).

## What exists now — `platform/api/clue_api/frontend_read/` (flag `CLUE_FRONTEND_READ_ENABLED`, default off)

- `app.py`: scoped router (structural workspace dependency; `/frontend/v1/health` outside it), FI-1 error
  envelope `{error:{code,message,requestId}}` + `X-Request-Id` echoed, 500-envelope produced INSIDE the CORS
  layer, CORS config that REFUSES `"*"` (Starlette echoes origin on *+credentials — real exposure with
  trusted-header tenancy) and narrows to GET/OPTIONS process-wide. Migration `870fe4f2af87` = the FI-1 L2 index
  (`entity_research_job_subject_entity`), single head.
- `accounts_list.py`: `GET /frontend/v1/accounts` — 6 constant queries/page; keyset cursor (default 50, max
  200); `?projectId=` membership filter; `projects[] = {projectId, addedVia, addedAt}` (NO name — see gate);
  per-`(project, icpKey, icpVersion)` attributed `scores[]` (lineage inner join — unattributable dropped);
  `researchStatus[]` per project, vocabulary `not_started|in_progress|needs_review|completed|suspended`
  (terminal outcome beats run-level fleet suspension — the precedence bug was caught+fixed in review).
- `account_detail.py`: neutral facts once via canonical merge (species registry-driven incl. retired
  declarations); relative claims per-project via lineage LEFT join + honest `projectId: null` unattributed
  section; plural `scores[]`/`narratives[]` (ratified); committee display-gated (fix from Task 4's review —
  detail and contacts share `committee.py::committee_member_displayable`); merged-loser redirect
  (`redirectedFrom`); coverage `{researchedFieldCount, unresolvedFieldKeys}` (subject-filtered — contact-row
  leak fixed in review).
- `contacts.py`: committee union + profile; governance airtight (no emails/avatars/URLs; absent+`restricted`;
  eligible-only `signals.count`); `request_bound_conn_factory` lends the route's connection (pool peak 1 —
  starvation hazard fixed).
- `committee.py`: the shared display predicate + conn lender (own module — real import cycle otherwise).
- Integration proof: `tests/integration/test_fi2_slice1_read_layer.py` (list↔detail↔contacts coherence over one
  composed fixture; package-wide `claim.workspace_id` grep; cross-surface policy-flip).
- **Contract recorded**: `apps/frontend/docs/api-contracts/accounts.md` "As-built backend read API" section —
  appended only, 14+ ratified deviations with reasons, faithful FI-1 D-4..D-7 pending list, the three
  schema-breakers (projects[].name gone; employeeBand→employeeCount int; revenueBand same-key vocabulary swap),
  redirect matrix per surface, open error-code set, researchedFieldCount/updatedAt honest definitions.

## Task 6 GATE — founder decisions needed

1. **`projects[].name`** (THE blocker): frontend searches/sorts on `project.name` (`account-query.ts:80-91`);
   slice 1 serves ids only. Options recorded in the doc: add `name` to the membership row read vs a projects
   lookup endpoint vs client-side catalog join.
2. **FI-1 D-4..D-7 ratification** — faithful list in the contract doc (incl. ratifying `not_launchable` into
   the status vocabulary now, tied to Lane D/D-9, to avoid widening the schema twice).
3. `signals.count` unit for list-valued facets (1 per field today vs per item).
4. CORS origins at deployment = exposure decision (process-wide credentialed GET for every surface in the
   projections process; wildcard refused at startup).
5. (Standing from slice 0) C6 v10/v22 re-pin ack; hq_geo-at-mint owner; workspace research_scope NOT NULL ack.

## Follow-ups (final-review triage — FOLLOW-UP unless noted)

Keyset index `(workspace_id, created_at DESC, id DESC)` on account_entity when scale warrants; score
last-collected-wins revisit WITH slice-3 §6.4; unscoped per-hop surviving_id hardening; list_effective_fields
whole-registry per request; retired-workspace-shadow 500 class (substrate owner); R11 bridge AC must re-run the
contacts suite shapes against real M8D output; committee/contacts empty on live data until R11 (fixture-proven
seam, no adapter change needed); phase-2 cross-origin POST needs deliberate CORS widening/path split.

## Loose facts worth keeping

- Live-data reality: committee/contacts serve [] until R11 (resolver reads account_run.references_index; only
  writer quarantined). researchStatus/scores/neutral facts are live-real already.
- `localhost:5432` on this machine resolves to a docker postgres; the host server is `127.0.0.1:5432`; the
  shared `clue` DB is stamped at an off-branch revision — always use per-branch throwaway DBs.
- Slices 2 (C7 lineage convergence) and 3 (economics incl. §6.4 project-scoped supersedes) not started.

## Task-6 gate RESOLVED (founder, 2026-08-08 — recorded in FI-1 §9)

D-4/D-5/D-6/D-7 ratified (D-6 incl. not_launchable now; no overallFit; D-7: fixture-only fields were
industry-pack placeholders — packs' custom fields render DYNAMICALLY when the account's industry pack yields
claims; the hardcoded fixture fields are dropped, not preserved). signals = count of SIGNAL TYPES (unit kept).
CORS: same-origin proxy in prod, exact localhost origin in dev, no wildcard. projects[].name: plan-owner
addendum — membership rows gain name via read-layer join. Task 6 unblocked.

## Task 6a DONE (2026-08-08) — the three gate-implied backend changes, before the frontend flip

Small pre-step landing the ratified decisions on the wire. No migration (head stays `870fe4f2af87`).

1. **`projects[].name`** — `AccountProjectMembership.name` (list) and `AccountProjectSection.name` (detail),
   both `str | None`. Resolved by ONE batched `accounts_list.project_names(conn, workspace_id, project_ids)`
   per response (`SELECT project_id, name FROM project WHERE workspace_id = … AND project_id IN …`), shared by
   both surfaces so they cannot name a project differently. `clue_research.membership` untouched — the name is
   a read-layer presentation join, not membership state, and the substrate stays free of spine knowledge.
   Null cases: the detail's unattributed section (`projectId: null`) and any lineage-derived section id with no
   `project` row in this workspace (`run_lineage.project_id` has NO FK to `project`). The workspace filter is
   load-bearing — without it another tenant's project label would render on this response (mutation-proven).
2. **`signals.count` → `signals.typeCount`** (+ `_signal_count` → `_signal_type_count`), matching the ratified
   "count of signal TYPES" unit. Wire rename only; no consumer existed.
3. **Contract doc** `apps/frontend/docs/api-contracts/accounts.md` as-built section: both shapes updated, the
   `projects[]` deviation rewritten (was the Task-6 blocker → now the ratified widening), the `signals`
   deviation rewritten, and "Pending founder ratification (FI-1 D-4–D-7)" converted to "Ratified 2026-08-08"
   incl. the D-7 industry-pack clarification, the signals unit, CORS posture, and the `projects[].name` addendum.

Tests: 88 across the four suites (+22 app), all green on a per-branch throwaway DB `clue_fi2_task6a`
(`127.0.0.1:5432`). New: an N+1 guard that *counts statements* over the list endpoint before/after three extra
memberships (mutation-proven — a per-membership lookup fails it), a cross-workspace name-leak guard, and a
list-valued-facet fixture proving `typeCount` is per-field not per-item (the `solo` contact now carries a
three-item `public_appearances`; the "no facets at all" zero case moved to `masked`).
