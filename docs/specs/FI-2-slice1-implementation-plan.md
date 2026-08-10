# FI-2 Slice 1 Implementation Plan — the global-lens read layer (MVP read surface)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development — one fresh Opus agent per task, sequential, orchestrator reviews + commits between tasks. Same process that shipped slice 0.

**Goal:** The FI-2 §7 global-lens read layer — the flag-gated, workspace-scoped, Band-2-semantic backend API the frontend `/accounts` flow binds to: list (+`projectId` membership filter, `projects[]` per row, per-project attributed scores, honest research status), account detail (neutral facts + relative sections grouped by project), and the contacts union — plus the app plumbing FI-1 §8 lists as prerequisites (error envelope, CORS, the L2 index).

**Architecture:** One new router package at the api composition root (`platform/api/clue_api/frontend_read/`), composed from untouched mechanism surfaces: `account_entity` scans, `current_values` (canonical merge) for neutral fields, `run_lineage` + `resolve_research_scope` for relative-field grouping, `membership` readers, `ContactEligibilityResolver` for governed committees, M8D `entity_research_run`/`entity_research_job` aggregation for status. Read-only; no writes; no launch; no chat (Lane D); no prose synthesis (Lane E).

**Prerequisites & gating:** Slice 0 substrate (landed, commits cecb2c09..a8d30e55). FI-1 D-4…D-7 are **still open** — they gate ONLY Task 6 (frontend schemas/adapters). Tasks 1–5 are fully ratified ground (FI-2 §7 + FI-1 D-1). **MANDATORY pre-read for every agent:** `_memory/2026-08-08-fi2-slice0-complete.md` §"Slice-1 handoff" — the claim-scoping trap (`claim.workspace_id` is NOT a tenancy filter), species-conditional lineage filtering, the mixed run-id space, membership-less accounts, and the primaryProjectId policy live there and in spec §7.

## Global constraints (every task)

- Read `docs/specs/FI-2-workspace-account-layer.md` §7 (incl. the MVP ruling and the read-scope warning) before coding.
- **Band-2 wire discipline:** semantic values only — enums (backend-honest vocabularies), numbers, ISO-8601 timestamps, opaque ids. NO display strings (`timeLabel`, `sizeLabel`, …), no presentation mapping. Every enrichment field nullable/optional — absence is a legitimate value (FI-1 Band-1 rule). Evidence URLs stay off the wire (FI-1 G4 v1: non-link provenance chips only).
- **Scoping:** every endpoint requires the workspace (existing `X-Workspace-Id` header mode); every SQL read workspace-scoped; claim reads via entity-subselect or `WorkspaceScope.predicate()`, never `claim.workspace_id`.
- **Flag-gated:** one new settings flag (default False) gates the whole router, following the C7 flag pattern in `clue_config/settings.py`.
- Migrations: hash id off current head `9c8cbd79a0e7`; reversible; named indexes; `make db-smoke`; single head after.
- TDD; tests workspace-scoped (shared-DB pollution hazard); reuse `tests/_workspace.py`, `tests/_run_lineage.py`, and the canonical fixture patterns from `tests/integration/test_fi2_slice0_two_projects.py`.
- Do not touch: quarantined M8A/M8C paths, C7 research-view contracts, launch/chat surfaces, `subsystems/clue-design/`, `apps/frontend/` (until Task 6).
- Commit locally when green (plain messages, no AI attribution); NEVER push.

---

### Task 1: router foundation + envelope + CORS + L2 index

**Files:** Create `platform/api/clue_api/frontend_read/__init__.py` + `app.py` (router, mounted in `projections_main` behind the new flag); modify `clue_config/settings.py` (flag + CORS origins setting); create migration (index `entity_research_job_subject_entity` on `entity_research_job (subject_entity_id)` — FI-1 L2); tests `tests/api/test_frontend_read_app.py`.
**Behavior:** FI-1's error envelope `{error: {code, message, requestId}}` for every error path (404/422/500) via an exception handler scoped to this router; CORS middleware driven by a config list (default empty = same-origin only), applied app-level but inert when unset; flag off → routes absent (404), flag on → mounted. Health/readiness untouched.
**AC:** envelope shape asserted for 404 + validation error; CORS headers present iff origins configured; flag gating tested both ways; `make db-smoke` green, single head.

### Task 2: accounts list — read model + `GET /frontend/v1/accounts`

**Files:** Create `platform/api/clue_api/frontend_read/accounts_list.py` (+ wire in `app.py`); tests `tests/api/test_frontend_read_accounts_list.py`.
**Wire shape (list row):** `{id, name, domain, employeeCount, revenueBand, logoUrl: null-for-now, projects: [{projectId, addedVia, addedAt}], primaryProjectId, scores: [{projectId, fit, intent, icpKey, icpVersion, scoredAt}], researchStatus: [{projectId, status}], updatedAt}` — names/casing per the frontend's JSON convention, values Band-2.
**Composition rules:** workspace `account_entity` scan (exclude `merged` status); neutral list fields via ONE `current_values` batch call; `projects[]`/`primaryProjectId` from `membership.projects_for_accounts` (element 0 = primary — recorded policy); `scores[]` = live `account.scoring.fit`/`.intent` claims grouped by project via the `run_lineage` subselect (relative fields — lineage-filtered; serve ALL projects' scores attributed, no representative-run guessing); `researchStatus` per (account, project) from `entity_research_run`/`entity_research_job` aggregation using the honest backend vocabulary `not_started | in_progress | needs_review | completed | suspended` (FI-1 §5.2 mapping; `failed` deliberately absent — document why at the site); `?projectId=` filters by membership (unknown project → empty list, not 404 — it's a filter). Pagination: `?limit=`/`?cursor=` (opaque cursor over `(created_at, id)`), default limit 50 — the workspace scan must not be unbounded.
**AC:** two-project canonical-fixture-style test asserting: both accounts' rows; membership-less seed account renders with null-heavy row; `projectId` filter returns exactly the membership set; scores attributed per project (P2's ICP score never shown as P1's); an account with zero research → `not_started` for its projects; no display strings anywhere (shape-level assertion).

### Task 3: account detail — `GET /frontend/v1/accounts/{id}`

**Files:** Create `platform/api/clue_api/frontend_read/account_detail.py`; tests.
**Wire shape:** `{id, name, domain, aliases, registryIds, hqGeo, neutralFacts: [{fieldKey, value, freshness: fresh|stale, observedAt, provider}], projectSections: [{projectId, addedVia, addedAt, score: {...}|null, insights: [{fieldKey, value, observedAt, provider}], narrative: {...}|null}], committee: [{contactId, name, persona, roleOnCommittee, projectIds}], coverage: {researchedFieldCount, unresolvedFieldKeys?}}`.
**Composition rules:** identity block from the entity row; neutral facts = `current_values` over the account-axis neutral fields present for this entity (species via `resolve_research_scope`; include freshness state — it's semantic, not cosmetic); relative claims partitioned into `projectSections` via lineage (claims whose run maps to no project → an `unattributed` section, honest not hidden); committee = union across projects via the governed reader (never `identity.contact_ids_for_account`), each member carrying the projects that target them; provider = source display-name map (registry data, not hardcoded). 404 (enveloped) for unknown/foreign-workspace/merged-loser id — merged losers REDIRECT (serve the survivor with a `redirectedFrom` field) rather than 404, matching `surviving_id` semantics.
**AC:** two-project fixture: neutral facts appear once (not per project); P1's narrative/insights never in P2's section; unattributed-claims section exercised (an ingestion-style manual run); merged-loser redirect asserted; a `RESTRICTED`/display-denied contact field is absent-not-null-crash (governance intact).

### Task 4: contacts — `GET /frontend/v1/accounts/{id}/contacts` + `GET .../contacts/{contactId}`

**Files:** Create `platform/api/clue_api/frontend_read/contacts.py`; tests.
**Wire shape (row):** `{id, name, title, persona, roleOnCommittee: {value, confidence}, linkedinUrl, projectIds, signals: {count}}`; profile adds `{accountId, accountName, professionalFacts: [...], evidence: [{provider, observedAt}] }` — no email addresses (G3), no avatar (G1), no non-LinkedIn socials (G2), evidence chips without URLs (G4).
**Composition rules:** committee union via `ContactEligibilityResolver.resolve_account` per targeting project (project_run/product derived per project by the recorded latest-run rule — implement it as a small documented helper, it is THE per-project context rule); governed display gates respected (a weak-binding `title` serves absent + a `restricted: true` marker, mirroring C7 availability semantics at Band-2); signal counts count display-eligible statements only (G7).
**AC:** persona/role served with backend 4-value vocabulary; a governance-blanked field renders absent+restricted, never fabricated; contact in two projects' committees appears once with both `projectIds`.

### Task 5: endpoint integration tests + contract recording

**Files:** Create `tests/integration/test_fi2_slice1_read_layer.py` (drives Tasks 2–4's endpoints over the slice-0 canonical fixture through the real app, flag on); modify `apps/frontend/docs/api-contracts/accounts.md` (append an "As-built backend read API (slice 1)" section: the actual wire shapes, the D-4/D-5 semantics applied, and an explicit "pending founder ratification: D-4 absence vocabulary in Zod, D-6 enum adoption, D-7 drops" list per the branch charter's record-back rule).
**AC:** one test module proving the three endpoints compose over one seeded workspace exactly as specced, incl. the no-display-strings and never-`claim.workspace_id` disciplines (grep-level assertion on the new package); the contract doc addition is factual (shapes copied from the passing tests, not aspirational).

### Task 6 (GATED — dispatch only after founder ratifies FI-1 D-4–D-7): frontend seam flip

**Files:** `apps/frontend/src/features/accounts/model/*` (Zod: absence/redaction vocabulary, ISO timestamps, ratified enums), `.../data/*` (HTTP adapter against the slice-1 endpoints), fixtures updated to the new schemas.
**Gate:** `npm run design-system:build && npm run lint && npm run build` (the frontend's own check gate); fixture mode must keep working (no `CLUE_API_BASE_URL` → fixtures).
**AC:** flipping `CLUE_API_BASE_URL` binds the accounts list/detail/contacts screens to the live API with no component changes (the repository-seam promise).

---

## Sequencing & non-goals

Tasks 1→2→3→4→5 sequential (each builds on the previous's package). Task 6 waits on founder sign-off and may be preceded by slices of other lanes landing. Non-goals: launch/kickoff (Lane D per D-9), chat (Lane D), prose synthesis (Lane E per D-10), project-lens detail endpoints (post-MVP per §7 ruling), C7 `allowed_run_ids` lineage convergence (slice 2), economics (slice 3), any `apps/frontend` change before Task 6.
