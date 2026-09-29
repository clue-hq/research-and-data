# ARV2 DATA SOURCE MAP — where every number and sentence on the accounts screens comes from

**Status: v1.1, 2026-09-07 — rulings S1–S12 decided by Aryan (S10 = read-time relaxation); Shashank's confirmation pending. Child of `ARV2-MASTER-PLAN.md` §6 (contract v1) and §9 (D1–D4).**
This document answers one question for every element the accounts screens render: **which API
endpoint serves it, which SQL produces it, and which table and column (or which claim
`field_key`) the value is read from.** Where the dummy frontend derives a value today, this
document names the served field that replaces the derivation. The dummy frontend defines *what*
data is needed. It never defines *where* the data comes from.

**Three rules this document enforces:**

1. **Production data comes from Postgres rows, never from files.** No markdown, JSON, or fixture
   file is read at request time. The dummy's markdown parser (`data/zafran/spec-content.ts`) is a
   fixture builder for offline demos; it does not exist in `apps/frontend` and is never called by
   a route. (Master plan ruling R11.)
2. **The frontend displays served values unchanged.** Every "[DERIVED]" entry in §3 names a
   derivation the dummy performs today and the served field that removes it. After D4 (the
   re-lift into `apps/frontend`), none of those derivations remain.
3. **One value, one source.** A field is read from exactly one place. If two candidate sources
   exist (for example a `contact_entity` column and a `contact.*` claim), this document names the
   winner and the other is not consulted.

**Notation.** `table.column` = a column read directly. `claim[field_key]` = the current
(un-superseded, workspace-scoped) claim for that field on the subject entity, read through the
existing `current_values(...)` merge (`clue_research.claimstore.merge`). `claim[...].value_json.x`
= a sub-field of that claim's JSON value. `served` = the backend computes it and the frontend
displays it as-is. "Existing" = code that is on the branch today; "D3" = the read-surface work in
master plan §9 Track D, step D3; "D1" = the migration + loader step.

---

## 1. The endpoints

All five reads live on the **existing** `/frontend/v1` router
(`platform/api/clue_api/frontend_read/`, prefix constant `FRONTEND_READ_PREFIX`, `app.py:67`). They
are flag-gated by `CLUE_FRONTEND_READ_ENABLED` and workspace-scoped by the router-level dependency
(`X-Workspace-Id` in isolated development; the authenticated principal resolver with
`X-Clue-Workspace-Id` in the application — `app.py:121-132`, `projections_app.py:841-848`). The
frontend never sends a workspace id from browser state; the same-origin BFF adds it.

| # | Endpoint | Exists today | Serves (master plan §6 payload) | D3 change |
|---|---|---|---|---|
| E1 | `GET /frontend/v1/accounts?projectId&limit&cursor\|page` | yes (`accounts_list.py:750`) | **Account list** rows + `meta` | rows re-shaped to the §6 list row (see §3.1); the FI-2 fields that the new screens do not read (`domain`, `employeeCount`, per-project `scores[]`, per-project `researchStatus[]`) stay on the wire for the existing `apps/frontend` accounts table until D4 replaces it, then are removed |
| E2 | `GET /frontend/v1/accounts/{accountId}` | yes (`account_detail.py:685`) | **Account detail** (rail + overview display block + committee + evidence) | adds the §6 fields (§3.2–§3.3); the FI-2 `neutralFacts` / `projectSections` / `coverage` shapes stay until D4, then are removed |
| E3 | `GET /frontend/v1/accounts/{accountId}/workspace` | **no** | **Account workspace** (insights display block, evidence, artifacts, activity, `insightSummary`) | new route in a new module `frontend_read/account_workspace.py` |
| E4 | `GET /frontend/v1/accounts/{accountId}/contacts` | yes (`contacts.py:541`) | **Contacts list** rows | rows re-shaped to the §6 contact row (§3.5) |
| E5 | `GET /frontend/v1/accounts/{accountId}/contacts/{contactId}` | yes (`contacts.py:555`) | **Contact detail** (rail + contact display block + evidence) | adds the §6 fields (§3.6) |
| ~~E6~~ | ~~`GET /frontend/v1/accounts/{accountId}/activity`~~ | **DELETED 2026-09-09 (D4-b Task 5)** | — | nothing read it; `activity[]` rides E2 and E3. `frontend_read/account_activity.py` (314 LOC) and `tests/api/test_frontend_read_account_activity.py` (535 LOC) are gone |
| E7 | `GET /frontend/v1/accounts/{accountId}/evidence/{claimId}` and the contact variant | yes (`account_detail.py:705`, `contacts.py:578`) | streams the snapshot behind a claim | unchanged; the new evidence hover links to `sourceUrl`, the artifact stream is the fallback for a claim with `sourceUrl: null` |

**Envelopes.** E1 returns `{ data: [...], meta: {...} }`. E2, E3, E5 return `{ data: {...} }` (the
dummy's repositories parse `AccountDetailResponseSchema` → `.data`; the FI-2 detail route returns
the bare object today — D3 adds the wrapper, and `apps/frontend`'s adapter is updated in the same
commit). E4 returns `{ data: [...], meta: { total } }`.

**Mount point.** The dummy's HTTP adapters build URLs as `new URL("/api/v1/accounts", base)`,
which discards any path on `CLUE_API_BASE_URL`. The re-lift (D4) points the adapters at
`/frontend/v1/...` through the existing same-origin BFF (`/api/clue/frontend/v1/...`), exactly as
the current `apps/frontend` accounts feature does. No backend path changes for this.

**Pagination, search, filter, sort.** The dummy calls E1 with **no query parameters** and does
search/filter/sort in the browser over the full list. E1 keeps its server-side `projectId`,
`limit` (max 200), `cursor` and `page` parameters as they exist today. For v1 the frontend
requests `limit=200` and paginates client-side only if `meta.total > 200`. Server-side search and
sort are not built in v1 (master plan §6; the dummy's `AccountsQuery` keys `search`, `sort`,
`overallFit`, `researchStatus` are not sent).

**As built (D3, 2026-09-08).** Contract v1 is **selected per request with `?contract=v1`**,
not by reshaping the FI-2 payloads in place. Without the parameter E1/E2/E4/E5 serve their FI-2
bodies byte-for-byte — the `apps/frontend` adapters, models and the FI-2 route tests are untouched
by D3 — and `?contract=v2` (any unrecognised value) is an enveloped 422 on every route of the
surface. E3 is new, so no FI-2 shape exists beside it and it answers v1 in **both** modes. The "D3
change" column above therefore describes what the *v1 branch* serves, not a mutation of the old
one; the FI-2 fields listed there as "stay on the wire until D4" are simply still on their own
payload. D4 re-points the adapters to `?contract=v1` and then deletes the FI-2 branches and the
parameter together. Cost if this was the wrong call: one query parameter to remove at D4.

There are **no FI-2 field renames** in D3. An earlier plan draft had E1/E2 rename
`researchStatus[]` → `projectResearchStatus` and `projects[]` → `projectMemberships` across the
backend and 33 frontend usages; the per-request ruling above voided that work, so those names do
not change anywhere and no `apps/frontend` file was edited for them.

**As built (D4-b, 2026-09-09) — one contract.** The `?contract=v1` selector described above is
**removed**. `/frontend/v1` now serves exactly one contract (ARV2 v1) on every route: the FI-2
readers, their wire models, their SQL and the modules that existed only for them are deleted
(`f96f99530`), the `apps/frontend` adapters no longer send the parameter (`c424b7827`), and an
unrecognised `?contract=` value is **ignored** rather than 422'd (a request that names a contract
that no longer exists is not an error; there is only one). `ContractMode` / `contract_mode` /
`ContractDep` no longer exist on `frontend_read.app` — asserted by
`tests/api/test_frontend_read_arv2_only_guard.py`. The v1 readers took the plain names
(`list_accounts`, `read_account_detail`, `read_account_contacts`, `read_contact_profile`). The
"cost if this was the wrong call: one query parameter to remove at D4" above was paid, as
predicted, in one commit. **E6 is deleted** (row above); **E7 survives** and now authorises against
the display page's `cited_claim_ids` plus, on the contact variant, the email/location claim ids the
v1 profile serves.

**Envelopes, as built.** E1 `{data, meta{total, nextCursor}}`; E2/E3/E5 `{data}`; E4
`{data, meta{total}}` — `meta.total` is a D3 addition to the dummy's `AccountContactsResponse`
(additive; the dummy's envelope Zod is not strict). The **FI-2** detail and contact profile remain
unenveloped, which is why the two contracts cannot be told apart by envelope alone.

---

## 2. The tables

### 2.1 Existing tables the reads touch (no change)

| Table | Used for | Key columns read |
|---|---|---|
| `account_entity` | the account spine | `id, canonical_name, primary_domain, aliases, hq_geo, merged_into, workspace_id, created_at, updated_at` |
| `contact_entity` | the contact spine | `id, account_entity_id, full_name, linkedin_url, merged_into, workspace_id, created_at` |
| `claim` | every fact | `id, entity_id, entity_type, field_key, value_json, source_url, source_key, evidence_span, extraction_method, observed_at, collected_at, run_id, superseded_by, verification_status, identity_binding, use_class, artifact_key, workspace_id, reuse_scope` + the D1 columns below |
| `run_lineage` | claim → project attribution | `run_id, workspace_id, project_id, project_run_id, kind` |
| `project_account` | which projects target the account | `workspace_id, project_id, account_entity_id, added_via, added_at` |
| `project` | project names | `project_id, workspace_id, name, status` |
| `field_definition`, `workspace_field_definition` | the field registry (labels, descriptions, custom variables) | `field_key, description, value_schema, active, pack` |
| ~~`entity_research_run`, `entity_research_job`~~ | ~~research status per account~~ | **STRUCK 2026-09-09 (D4-b Task 1).** Research status is now one statement over **`arv2_research_job`** (`v1_shared.arv2_research_status_for`): the account's latest job by `(created_at, job_id)`, `status` served verbatim, `refreshing` = a non-terminal job newer than a `completed` one. No read of the old lane's job tables survives on this surface. |
| ~~`entity_research_account_coverage`~~ | ~~the confirmed buying committee~~ | **STRUCK 2026-09-09 (D4-b Task 2).** The committee is **the account's contacts that hold at least one live claim** (`arv2/display/gather.committee_members`), scope-predicated, merged losers excluded, ordered by persona rank then name then id. The coverage-row branch and `_COVERAGE_SQL` are deleted. |
| `artifact` | the snapshot behind a claim (E7) | `storage_key, workspace_id, content_sha256, media_type, size_bytes, erased_at, purged_at` |
| `platform_user`, `workspace_membership` | account owner / creator display | `user_id, display_name`; membership confirms the user belongs to the workspace |
| `agent_artifact_subject`, `agent_artifact_project`, `artifact` | generated artifacts bound to an account (E3 `artifacts[]`) | `subject_entity_id, artifact_key, binding_kind, created_at`; see §3.7 for the open ruling |
| ~~`research_subject_activity`~~ | ~~the old lane's activity ledger~~ | **STRUCK 2026-09-09 (D4-b Task 5).** Its only reader was E6, which is deleted with the FI-2 surface (`frontend_read/account_activity.py`, 314 LOC). `activity[]` on E2/E3 is composed by `v1_shared.activity_for` over the ARV2 `account_activity_event` table. |

**SUPERSEDED 2026-09-09 (founder ruling; D4-b Tasks 1, 2, 6).** ~~The ARV2 lane (Track R) and the
D1 loader write to the same substrate tables the old lane used for **run state**: one
`entity_research_run` per launch, one `entity_research_job` per account, one
`entity_research_account_coverage` row per finished account (master plan §5.1 reverse edge).~~

ARV2's own rows are the only truth. The lane writes **`arv2_research_run` + `arv2_research_job`**
through `arv2/account_research_store.py`, and the D1 answer-key loader now does the same
(`ceb82f841`): its four legacy INSERTs are gone, and it drives `create_run` → `create_job` →
`begin_job` → `finish_job` exactly as R2's driver does. No module under `clue_api/arv2` or
`clue_api/frontend_read` names an `entity_research_*` table any more — pinned by
`tests/api/test_frontend_read_arv2_only_guard.py`, whose file allowlist is now **empty**. The one
remaining name is the column `provider_call_ledger.entity_research_job_id`, an ARV2 column that
holds an `arv2_research_job.job_id` under an inherited name. The old lane's own tables are
inventoried for deletion in `docs/specs/ARV2-PHASE6-LEGACY-DELETION-INVENTORY.md`.

### 2.2 Tables and columns added by the D1 migration (master plan §4)

| Object | Definition | Why |
|---|---|---|
| `claim.signal_priority` | `smallint NOT NULL DEFAULT 3 CHECK (signal_priority BETWEEN 1 AND 3)` | `ResearchItem.priority` = min over cited claims |
| `claim.outreach_safe` | `boolean NOT NULL DEFAULT true` | `ResearchEvidence.outreachSafe`; restricted-section routing |
| `claim.write_markers` | `jsonb NULL CHECK (write_markers IS NULL OR jsonb_typeof(write_markers) = 'object')` | the write-time annotations' home (master plan §4): `schema_valid`, `source_missing`, `proposed_field`, `identity_binding_defaulted`, `use_class_defaulted`, `pipe_joined_key`, `evidence_verbatim`, `unevidenced`, `entailment`. NULL = nothing to note; outside the append-only immutable-column guard |
| `account_entity.owner_user_id` | `text NULL REFERENCES platform_user(user_id)` | `owner` (ruling S1 below) |
| `account_entity.created_by_user_id` | `text NULL REFERENCES platform_user(user_id)` | `createdBy`; NULL when an agent created the account |
| `display_block` | `(display_block_id uuid PK, workspace_id text NOT NULL, subject_kind text CHECK IN ('account','contact'), subject_id uuid NOT NULL, page text CHECK IN ('overview','insights','contact'), section_key text NOT NULL, body_json jsonb NOT NULL, cited_claim_ids uuid[] NOT NULL, model text NOT NULL, prompt_version text NOT NULL, recipe_version int NOT NULL, generated_at timestamptz NOT NULL, superseded_at timestamptz NULL)`; partial unique index on `(workspace_id, subject_kind, subject_id, page, section_key) WHERE superseded_at IS NULL` | the persisted section copy (§4) |
| `display_section_recipe` | `(page text, section_key text, h1 text NOT NULL, position int NOT NULL, allowed_field_keys text[] NOT NULL, restricted boolean NOT NULL DEFAULT false, default_open boolean NOT NULL DEFAULT false, instruction_version text NOT NULL, workspace_id text NOT NULL DEFAULT '', PRIMARY KEY (page, section_key, workspace_id))` — the **empty-string** `workspace_id` row is the system recipe (a NULL cannot sit in a primary key); a workspace-id row overrides it | the recipes (§4). **Named `display_section_recipe`, not `recipe`:** a `recipe` table already exists for Stage-0 execution recipes (`128c83d5e151_c5_1_execution_journal.py:80`) |
| `provider_call_ledger` | `(ledger_id uuid PK, call_id uuid NOT NULL, workspace_id text NULL, project_id text NULL, project_run_id text NULL, entity_research_job_id uuid NULL, provider text NOT NULL, operation text NOT NULL, label text NOT NULL, phase text NOT NULL CHECK (phase IN ('estimate','result')), http_status int NULL, latency_ms int NULL, attempts int NOT NULL DEFAULT 0, estimate_usd numeric(12,6) NOT NULL DEFAULT 0, estimate_credits numeric(12,3) NOT NULL DEFAULT 0, estimate_media_seconds int NOT NULL DEFAULT 0, cost_usd numeric(12,6) NULL, credits numeric(12,3) NULL, media_seconds int NULL, over_ceiling boolean NOT NULL DEFAULT false, outcome text NOT NULL CHECK (outcome IN ('estimate','ok','client_error','retry_exhausted','halted','transport_error')), error_code text NULL, provider_request_id text NULL, request_artifact_key text NULL, response_artifact_key text NULL, recorded_at timestamptz NOT NULL DEFAULT now())`; indexes on `(workspace_id, recorded_at)` and `(call_id)` | Appendix A laws 1–2 — every paid call's estimate, cost, credits, media seconds and raw refs; the cost dashboards read it. Raw bodies are `artifact` rows (`source_key = 'arv2:<provider>:<operation>'`) the row references. R1 ships the wrapper + file/memory sinks; the table lands with D1/A7 |
| `workspace_field_definition.presentation` | `text NOT NULL DEFAULT 'text' CHECK IN ('text','badge','score')` | `customFields[].presentation` (§3.2) |
| `account_activity_event` | `(event_id uuid PK, workspace_id text NOT NULL, account_entity_id uuid NOT NULL, kind text CHECK IN ('created','contacts','summary','artifact','updated'), actor_kind text CHECK IN ('clue','person'), actor_user_id text NULL REFERENCES platform_user(user_id), text text NOT NULL, action text NULL, occurred_at timestamptz NOT NULL, project_id text NULL, ref_json jsonb NULL)` | the new `activity[]` (§3.8) |

No visit table (master plan D5). No `logo` table (ruling S2 below).

---

## 3. Element → field → endpoint → source

Each table below is one screen. Columns: the rendered element; the wire field (master plan §6
names); the endpoint; the source and the exact rule; and, where the dummy derives the value today,
the derivation that the served field replaces (file:line in `clue-frontend` @ `84f8ee7`).

### 3.1 Accounts list — `/accounts` (E1)

| Element | Wire field | Source and rule | Replaces (dummy derivation) |
|---|---|---|---|
| row identity | `id` | `account_entity.id` (survivor; `merged_into IS NULL` rows only — existing `_ACCOUNT_FILTER`, `accounts_list.py:270-288`) | — |
| company name | `name` | `account_entity.canonical_name` | — |
| logo | `logoPath` | **ruling S2.** No logo pipeline exists (`accounts_list.py:204-206`). Recommendation: contract change to `logoPath: string \| null`; frontend renders its building glyph on `null`. Until ruled, the backend serves `null` | dummy requires a `/`-prefixed path |
| website | `websiteUrl` | `'https://' + account_entity.primary_domain`; `null` when no domain (contract change: nullable) | table computes hostname from URL (`accounts-table.tsx:104-106`) → served `websiteLabel` on detail; the list column shows `websiteUrl` as-is |
| research status | `researchStatus` | **As built (D4-b, 2026-09-09)** — `v1_shared.arv2_research_status_for`: ONE statement over **`arv2_research_job`**, `DISTINCT ON (account_entity_id) ORDER BY account_entity_id, created_at DESC, job_id DESC`, scoped by `workspace_id`. The job's `status` is served **verbatim** (R2's `JobStatus` and the wire's `ResearchStatus` are the same five strings, pinned by a vocabulary-equality test), `not_started` when the account has no job. **The status is per account, not per project** — the primary-project attribution is gone; whichever project launched the job, the account is researched. ~~existing rule `research_status_for(...)` over `entity_research_job` + fleet control~~ | — |
| research status label | `researchStatusLabel` | served text from one backend map: `not_started→"Not started"`, `in_progress→"In progress"`, `needs_review→"Needs review"`, `completed→"Researched"`, `suspended→"Paused"` | three independent relabel maps in the dummy (`accounts-table.tsx:82-87`, `accounts-filter-panel.tsx:57-62`, `account-detail-primitives.tsx:35-40`) |
| spinner | `researchIsRefreshing` | **As built (D4-b, 2026-09-09)** — `true` when a **later** `arv2_research_job` for the same `(workspace_id, account_entity_id)` is non-terminal (`not_started` / `in_progress`; a `suspended` job is halted, not running) than a `completed` one, on the same `(created_at, job_id)` total order the status read uses; else `false` | — |
| overall fit | `overallFit` | `claim[account.scoring.fit]` attributed to the primary project via `run_lineage`; band from `value_json.value` (0–1): `≥ 0.70 → High`, `≥ 0.40 → Medium`, else `Low`; `null` when no claim. **Thresholds are ruling S3** | `createLocalAccount` invents `"Medium"` (`create-account.ts:15`) |
| fit score | `fitScore` | `round(100 × claim[account.scoring.fit].value_json.value)`; `null` when no claim | `createLocalAccount` invents `0` (`create-account.ts:7`) |
| revenue | `revenueBand` | `claim[core.revenue_band].value_json` served through `v1_shared.revenue_band_label` — `10m_50m` → `"$10M–50M"`, `1b_plus` → `"$1B+"`, `under_1m` → `"under $1M"`; an unparseable token passes through as written; `"Unknown"` when absent. **As built (D4-b, 2026-09-09)** — the raw token used to reach the screen. `revenue_band_label` covers all seven `REVENUE_BAND_OPTIONS` members and a test refuses any member that would be served as its own token | — |
| headcount | `employeeBand` | `claim[core.employee_range].value_json` (string, e.g. `"51-200"`); when absent but `claim[core.employee_count]` exists, the band computed by one backend function `band_for_headcount(n)`; `"Unknown"` when neither | — |
| locations | `locationCount`, `locationsLabel` | `locationsLabel = claim[core.hq_location].value_json` (string); `locationCount = 1` when that claim exists else `0`. Additional office locations are not modelled in v1 | table falls back to the count when the label is absent (`accounts-table.tsx:342`) — kept, but the backend always serves the label when it serves a count ≥ 1 |
| owner | `owner` | `account_entity.owner_user_id → platform_user.display_name`; `{id: user_id, name: display_name}`; `null` when unassigned. **No `avatarUrl`** (no avatar store) | viewer substituted for the owner (`account-owner.ts:16`) — **removed** (ruling R6) |
| creator | `createdBy` | `account_entity.created_by_user_id → platform_user`; `null` when agent-created | — |
| industry | `industryLabels[]` | `claim[core.industry].value_json` first, then each entry of `claim[core.industries_all].value_json` (list) not equal to it; deduped, source order; `[]` when neither | — |
| socials | `socials[]` | `claim[core.company_linkedin_url]` → `{id:"linkedin", label:"LinkedIn", url}`; `claim[core.company_twitter_url]` → `{id:"twitter", label:"Twitter", url}`. Only claims whose value passes `safe_public_url` | — |
| created / modified | `createdAt`, `lastModifiedAt` | `createdAt = account_entity.created_at`; `lastModifiedAt = GREATEST(account_entity.updated_at, MAX(claim.collected_at) over the account's live claims, MAX(display_block.generated_at) for the account)` | the dummy formats dates in the browser — kept (formatting is presentation, the value is served as ISO-8601) |
| projects | `projects[]`, `primaryProjectId` | `project_account JOIN project` (`membership.py:96-102`); `primaryProjectId` = earliest `added_at` (existing rule, `accounts_list.py:722-724`) | — |
| custom variables | `customFields[]` | for each `workspace_field_definition` row with `pack='client'` and `active` whose `field_key` has a live claim on the account: `{id: field_key, label: description, value: value_json rendered as text by the backend, presentation: presentation, primary: false}` | `Number(value) \|\| 0` for scores (`accounts-table.tsx:395`) — **removed**: a `score` presentation is served with a numeric string, never absent |
| `meta` | `total`, `nextCursor` | existing (`accounts_list.py:290`, `:239-242`) | — |

**SQL sketch for E1 (one round trip per concern, as today):** spine page (`_PAGE_ACCOUNTS`) →
`current_values(ids, LIST_FIELD_KEYS)` where `LIST_FIELD_KEYS` grows from the existing two to
`core.employee_count, core.employee_range, core.revenue_band, core.hq_location, core.industry,
core.industries_all, core.company_linkedin_url, core.company_twitter_url` plus active client-pack
keys → scores (`_SCORE_CLAIMS_TEMPLATE`, filtered to the primary project) → memberships → project
names → research jobs (`_RESEARCH_JOBS`) → owners (`SELECT user_id, display_name FROM platform_user
WHERE user_id IN :ids`) → `MAX(collected_at)` per entity.

**As built (D3, 2026-09-08).**

- **`fitScore` / `overallFit` = the primary project's latest `account.scoring.fit`.** An account
  can hold several fit claims (one per project, several per project when scored under more than one
  ICP). The row has one fit column and the primary project is the row's lens, so only that
  project's scores are candidates and the most recently scored wins. No primary project, or none
  scored under it → both fields are `null` **together**, never `0` and never a band borrowed from
  another project (`accounts_list._primary_project_fit`).
- **`researchIsRefreshing`** is true only for "researched, *and* being re-researched right now": a
  non-terminal `entity_research_job` for this `(account, project)` exists **and** a terminal
  `completed` job precedes it in the same `(created_at, job_id)` order the status `DISTINCT ON`
  uses. A first-ever run in flight is `in_progress`, not refreshing.
- **`lastModifiedAt` = `GREATEST` of three sources** in one statement: `account_entity.updated_at`,
  `MAX(claim.collected_at)` over the account's live claims, and `MAX(display_block.generated_at)`
  over its live blocks. A regenerated page therefore moves the account's "Updated" stamp, which is
  what the screen means by it (`v1_shared.last_modified_for`).
- **`employeeBand` and `locationsLabel` read the registry objects' own keys, never the object.**
  `core.employee_range` is `{label, min, max}` → `label`; `core.hq_location` is `{raw, city,
  region, country}` → `raw` (the source's own words), falling back to the joined normalized parts.
  Rendering the whole object would put `"city: Tel Aviv; country: Israel; raw: Tel Aviv, Israel"`
  on a table cell. `employeeBand` falls back to our own bucketing of `core.employee_count`, then to
  `"Unknown"`. **Not yet done the same way:** `revenueLabel` and `fundingLabel` on E2 still render
  whole objects — the Zafran walk serves `"amount_max: 25000000; amount_min: 10000000; as_of:
  2026-08-22; currency: USD; estimate_kind: provider_estimate"` — recorded as a D4 follow-up.
- **`customFields` order is `field_key`**, ascending, per account: the client pack's variables have
  no declared display order, and `field_key` is the one stable order that does not move under the
  user between two reads.

### 3.2 Account detail, right rail "Core" — `/accounts/{id}` and the preview drawer (E2)

Everything in §3.1 is repeated on the detail object, plus:

| Element | Wire field | Source and rule | Replaces |
|---|---|---|---|
| preview title | `previewTitle` | `account_entity.canonical_name` (**ruling S4** if a richer title is wanted) | — |
| website label | `websiteLabel` | `account_entity.primary_domain` (bare host, no `www.`) | hostname parsing (`accounts-table.tsx:104`) |
| headcount | `headcountLabel` | `"{employee_count} ({employee_range})"` when both claims exist; the one that exists otherwise; `"Unknown"` when neither | — |
| revenue | `revenueLabel` | `claim[core.annual_revenue].value_json` rendered by the backend (e.g. `"$10–25M"`); else `revenueBand`; else `"Unknown"` | — |
| locations | `locationsLabel` | as §3.1 | rail label flips "HQ"/"Locations" on `overviewDisplay` presence (`account-detail-primitives.tsx:270`) — presentation, unchanged |
| founded | `foundedLabel` | `str(claim[core.founded_year].value_json)`; absent when no claim | — |
| funding | `fundingLabel` | `"{stage} · {total}"` from `claim[account.recent_funding].value_json.round` and `claim[account.total_funding].value_json` rendered; whichever exists; absent when neither | — |
| fit score label | `fitScoreLabel` | absent in v1 (the numeric `fitScore` renders) | — |
| dates | `createdAt`, `lastModifiedAt` | as §3.1; **required** on detail | — |
| legacy prose | `summaryParagraphs[]`, `businessParagraphs[]` | **contract change (ruling S5):** default `[]`. The dummy's Zod requires ≥1 string but never renders them when `overviewDisplay` exists; the backend does not fabricate prose to satisfy a legacy slot | — |
| legacy fit criteria / insights | `fitCriteria[]`, `insights[]` | served `[]` (legacy slots; rendered only when `overviewDisplay` is absent) | — |
| contacts (rail, first three) | `contacts[]` | committee members (§3.3 `buyingCommittee` source) projected to `{id: contact_entity.id, name: contact_entity.full_name, title: claim[contact.current_title], persona: claim[contact.persona], emailVerified: claim[core.work_email].value_json.status == 'verified_smtp', hasDetail: true}`. `avatarUrl` absent (no avatar store) | `slice(0, 3)` in the component (`account-detail-primitives.tsx:140`) — presentation, unchanged |
| custom variables | `customFields[]` | as §3.1; `primary` = `true` for the first four in registry order (**ruling S6**) | — |
| activity (rail) | `activity[]` | §3.8 | — |

### 3.3 Account overview body (E2)

| Element | Wire field | Source and rule | Replaces |
|---|---|---|---|
| the overview page | `overviewDisplay` | `display_block` rows for `(subject_kind='account', subject_id, page='overview')` with `superseded_at IS NULL`, ordered by `display_section_recipe.position`; one `ResearchSection` per recipe row **whether or not a block exists** (a missing block → `empty: true, items: []`). Generation on miss: §4 | — |
| section heading | `sections[].h1` | `display_section_recipe.h1` — served bare, no counts, no parentheticals | count/fit parsed out of `h1` (`research-content.tsx:551-554, 787-790`) — **removed** (ruling R9) |
| section flags | `key, restricted, defaultOpen, empty, emptyMessage` | `key = recipe.section_key`; `restricted`, `defaultOpen` from the recipe row; `empty = (no block) OR (block.body_json.items = [] AND intro = [])`; `emptyMessage` absent (client default text) | emptiness recomputed client-side (`research-content.tsx:639`) — harmless; the served flag is authoritative |
| intro paragraphs | `sections[].intro[]` | `display_block.body_json.intro[]` — `{text, claimIds[], segments[]}` as the model emitted them | — |
| items | `sections[].items[]` | `display_block.body_json.items[]`; `priority = MIN(claim.signal_priority) over the item's cited claim ids` (computed at generation time and stored in `body_json`); `newSinceLastVisit = false` (D5) | client localStorage computation (`research-content.tsx:642`) — allowed to stay (D5 resolved frontend-side) |
| overall fit badge | `overallFit` (detail field) | §3.1 | regex on the "Why they fit" heading (`research-content.tsx:787`) — **removed** |
| buying committee table | `buyingCommittee[]` | **As built (D4-b, 2026-09-09)** — members = **every contact under the account holding ≥1 live claim**: `contact.account_entity_id = :account_id AND contact.workspace_id = :workspace_id AND contact.merged_into IS NULL AND EXISTS (live claim on the contact under `WorkspaceScope.for_workspace(...).predicate()`)`. There is **no coverage-row branch** — `arv2/display/gather.committee_members` is the one rule, ordered `(persona_rank(persona), name, id)` so D2 and D3 share one order and two namesakes come back the same way every read. Per member: `contactId = contact_entity.id`; `name = contact_entity.full_name`; `title = claim[contact.current_title]`; `persona =` `claim[contact.persona]` as **display text**; `email = claim[core.work_email].value_json.address`, `emailClaimId = that claim's id` (both `null` when absent); `linkedinUrl = contact_entity.linkedin_url`; `whyTheyMatter` per the rule below | avatar without `src` (`research-content.tsx:963`) — presentation, unchanged |
| "why they matter" | `buyingCommittee[].whyTheyMatter` | **As built (D4-b, 2026-09-09)** — a **researched** rationale is served verbatim (`claim[contact.role_on_committee].value_json.rationale`). A role claim written by the derived-role path counts as having **no** rationale — recognised by either the `derived_role_from_persona` write marker (durable, machine-readable) or the phrase `"role derived from the committee persona"` in the rationale (survives a row that lost its markers). With no rationale the served text is `"{title} · {persona label}"` when both are known, else the `"Committee member"` placeholder. A member with a title and no role claim at all therefore reads `"Head of RevOps · Champion"`, not `"Committee member"` | — |
| evidence for every chip | `researchEvidence[]` | §3.9, for the union of claim ids cited by `overviewDisplay` + `buyingCommittee[].emailClaimId` | — |

**As built (D4-b, 2026-09-09).** `revenueLabel` and `fundingLabel` read their registry **objects**
rather than rendering them generically: `core.annual_revenue`'s `{amount_min, amount_max,
currency}` becomes `"$10M–25M"` (one bound → `"$10M+"` / `"up to $25M"`; an `amount` → one figure),
and `fundingLabel` joins the latest funding round to the running total — `"Series C · $60M ·
$130.5M"` — reading the provider's list shape (`[{type, raised_amount, announced_at}, …]`, latest
announcement wins) as well as the registry sketch's single object. A round that states no currency
**borrows the sibling `account.total_funding` object's** (controller ruling 1): same account, same
provider record, so the denomination is read off that record rather than guessed. When neither half
names one the amounts stay bare (`"60M"`) — defaulting to `$` with nothing to read it off would
turn an undenominated figure into a dollar figure. The band fall-through goes through
`revenue_band_label` too, so `revenueLabel` can never print `"10m_50m"` either. `buyingCommittee[].persona` (and every other `persona` on the wire) is
served as **display text** — `"Economic buyer"`, never `economic_buyer`; the vocabulary value still
drives `personaTone`, `influence` and the committee ordering behind it.

**As built (D3, 2026-09-08; the first sentence SUPERSEDED by D4-b above).** `buyingCommittee[]` is
not a second implementation of the committee query: it is D2's `committee_members` behind
`display_pages.committee()` — ~~the latest coverage row's `committee_member_ids` when one exists,
**else** every contact under the account with ≥1 live claim (D2 decision 5)~~ **now: only the
contacts-with-live-claims rule, always** (D4-b Task 2, founder ruling 2026-09-09). Two contract points follow from real data: `linkedinUrl` is **nullable** on
`BuyingCommitteeMember` (D3 ruling — a member resolved from a coverage row may have no LinkedIn
URL, and the dummy renders the link only when present), and a member with no title/rationale claim
is served the placeholders `"—"` and `"Committee member"` rather than being dropped, because the
committee is the research's answer about who matters and an unnamed role does not unmake it.

### 3.4 Insights tab — `/accounts/{id}/insights` (E3)

| Element | Wire field | Source and rule | Replaces |
|---|---|---|---|
| scope | `accountId` | the path id (survivor) | three defensive re-scopings in the dummy (`account-library-screens.tsx:41`, `account-workspace-presentation.ts:35`) — harmless |
| header strip | `insightSummary[]` | served exactly two strings: `"{n} insights"` where `n = SUM(items.length)` over non-restricted sections of `insightsDisplay`, and `"{m} people"` where `m = len(buyingCommittee)` | regex rewrite of the fixture's "42 reported in research" (`account-workspace-presentation.ts:26-30`) — **removed** |
| the insights page | `insightsDisplay` | as §3.3 with `page='insights'` | — |
| Sources panel | (client-side over `researchEvidence[]`) | all evidence for claim ids cited by `insightsDisplay` | the dummy also admits any `claimId` starting with the literal `"register-"` (`research-presentation.ts:8`) — fixture artefact, **removed** in the re-lift |
| Internal notes | `sections[].restricted` | recipe rows `context-only` (insights), `watch-outs` (overview payload, rendered only here), `do-not-mention` (contact) carry `restricted = true`; only these sections are ever generated from `outreach_safe = false` claims | — |
| legacy insight links | `insights[]` | served `[]` | — |
| artifacts | `artifacts[]` | §3.7 | — |
| activity | `activity[]` | §3.8 | — |
| evidence | `researchEvidence[]` | §3.9 for the claim ids cited by `insightsDisplay` | — |

### 3.5 Contacts tab — `/accounts/{id}/contacts` (E4)

Rows = the committee members of §3.3 (**one rule, no coverage query** — D4-b), ordered by persona
rank (`economic_buyer, champion, technical_evaluator, user, blocker`, unranked personas last) then
`full_name` then `contact_entity.id`. The ordering lives in `committee_members` itself, so E2's
card and E4's table cannot disagree about who is first.

| Element | Wire field | Source and rule | Replaces |
|---|---|---|---|
| identity | `id`, `name` | `contact_entity.id`, `contact_entity.full_name` | — |
| avatar | `avatarUrl` | absent (no avatar store); the client renders initials | — |
| title | `title` | `claim[contact.current_title].value_json`; `"—"` when absent (the dummy requires a non-empty string; **ruling S7**: make `title` nullable) | — |
| persona | `persona`, `personaTone` | `persona = claim[contact.persona].value_json` (the ICP `persona_map` vocabulary, master plan §5.2); `personaTone` from one backend map `economic_buyer→olive, champion→orange, technical_evaluator→blue, user→cyan, blocker→red` | — |
| influence | `influence` | `claim[contact.role_on_committee].value_json.influence ∈ High\|Medium\|Low`; when the claim lacks it, from persona: `economic_buyer→High, champion→High, technical_evaluator→Medium, user→Medium, blocker→Medium` (**ruling S8**) | — |
| email | `emailStatus`, `emailLabel` | **As built (D4-b, 2026-09-09)** — `core.work_email` is registered an **object** (`{"address", "status", "checked_at"?}`; `status` in `verified_smtp \| catch_all_valid \| invalid \| unknown \| unverified`; migration `7332ac974920`). `status ∈ (verified_smtp, catch_all_valid)` → `emailStatus: "available"`, `emailLabel: value_json.address`; every other verdict, and a legacy **bare-string** value, → `emailStatus: "lookup"` with the claim id kept and no label. An unrecognised provider verdict is graded `unknown`, never stored raw, so the enum stays closed; `checked_at` is **omitted**, not null, when the provider sent none | row branches on `emailLabel` presence (`contact-row.tsx:118`) — the two are served consistently, so either works; the re-lift branches on `emailStatus` |
| socials | `socials[]` | `["linkedin"]` when `contact_entity.linkedin_url` is set; `"x"` appended when `claim[contact.x_url]` exists (not produced by the lane in v1) | — |
| open action | `profileAction` | `"page"` when the contact has ≥1 live claim or ≥1 display block; else `"none"`. `"preview"` is not served in v1 (the dummy's featured-contact drawer is a fixture behaviour, `contacts/page.tsx:26-28`) | — |
| lookup button | — | the dummy's `LookupEmailButton` is a `setTimeout` stub (`use-email-lookup-controller.ts:20-25`). Production wires it to the existing `POST .../contacts/{id}/email-lookup` + poll (`contacts.py:711, 740`) in D4 | — |

**As built (D4-b, 2026-09-09).** `persona` on the wire is **display text** — `"Economic buyer"`,
`"Technical evaluator"`, and an unrecognised value spelled as words (`weird_value` → `"Weird
value"`) rather than served raw. The `persona_map` vocabulary value is what `personaTone`, the
`influence` default and the persona-rank ordering still read; only the string the browser prints
changed. The same conversion applies to E5, to E2's committee card and contact chips, to
`reports[]`, and to the contact chips *inside* generated display blocks — those are written into
`display_block.body_json` at generation time, so the blocks already at rest were corrected once by
`scripts/rewrite_display_persona_labels.py`.

**As built (D3, 2026-09-08).** The E4 row set **is** the coverage committee of §3.3, resolved
through the same `display_pages.committee()` seam and one claims read — not a second query. Two
details are worth pinning: `influence` falls back to the persona default table above whenever the
`contact.role_on_committee` claim does not carry one (served, never derived in the browser), and
`profileAction` is `"page"` for a contact with ≥1 live claim **or** a stored display section, else
`"none"` — `"preview"` is never served in v1. The E4 row's `title` is served `null` when no title
claim exists (ruling S7); the `"—"` placeholder belongs to E2's committee card only.

**Finding (the Zafran walk, 2026-09-08) — CLOSED 2026-09-09 by D4-b task 4.** The email rule above
reads `value_json.status` / `value_json.address`, the provider pair `AiArkEmailExport` insists on
("an address flattened away from its status/domainType pair is a claim nobody can grade"). At the
walk **no writer produced that shape** — D1's answer-key loader and FI-2's own email-lookup writer
both stored the bare address string, and `core.work_email` was registered `value_type = str` — so
every real contact served `emailStatus: "lookup"` even when an address was stored. The fix was the
writer's, as recorded: `core.work_email` is now registered an **object**
(`{"address", "status", "checked_at"?}`, `status` in
`verified_smtp | catch_all_valid | invalid | unknown | unverified`; migration `7332ac974920`), the
answer-key mapper carries AI Ark's `verification.verdict` and `checked_at` into it, the FI-2 and C5
acquisition writers write `unverified` (neither probes a mailbox), and
`scripts/load_arv2_answer_key.py --repair-emails` superseded the four loaded Zafran rows with their
verdict. The four committee members with addresses now serve `emailStatus: "available"` and
`buyingCommittee[].email`; Ben Seri, for whom the run found none, still serves `null`. A bare
string left anywhere still reads `lookup` — the reader never invents a verdict.

### 3.6 Contact profile — `/accounts/{id}/contacts/{contactId}` (E5)

The row of §3.5, plus:

**As built (D4-b, 2026-09-09).** E5 inherits §3.5's two corrections unchanged: `persona` is the
display label (`"Economic buyer"`), and the email verdict object drives `emailStatus` / `emailLabel` /
`emailVerifiedAt`. `reports[]` carries the same display-text persona.

| Element | Wire field | Source and rule | Replaces |
|---|---|---|---|
| account link | `accountId`, `accountName`, `accountLogoPath` | `contact_entity.account_entity_id`, `account_entity.canonical_name`, logo as §3.1 ruling S2 | — |
| "Research" row | `recentSignalsLabel` | `"{k} signals"` where `k = COUNT(claim) for the contact with signal_priority ≤ 2 and outreach_safe`; `"No signals yet"` when 0 | — |
| LinkedIn | `linkedinUrl`, `linkedinLabel` | `contact_entity.linkedin_url`; label = the URL path's last segment (`/in/nicholastfisher` → `nicholastfisher`) computed by the backend | — |
| X | `xUrl`, `xLabel` | absent in v1 (no field produced) | — |
| email verified date | `emailVerifiedAt` | **As built (D4-b, 2026-09-09)** — `date(claim[core.work_email].value_json.checked_at)` when it parses, else `date(observed_at or collected_at)`. It is the **provider's own check date**, not the day the claim was written: Nick Fisher reads `2026-08-31` (AI Ark's SMTP check), not `2026-09-02` (D1's load). The provider's timestamp is carried verbatim and no timezone is invented | — |
| location | `locationLabel`, `locationClaimId` | `claim[contact.current_location].value_json` and that claim's id | evidence array scanned twice by id (`contact-profile-content.tsx:178-179`) — fine; the id is served |
| email evidence chip | (client) | the chip resolves `emailClaimId` → `researchEvidence`; **`emailClaimId` is added to the contact detail** (contract change, ruling R5) | substring search over evidence text (`contact-profile-content.tsx:91-95`) — **removed** |
| best channel | `bestFirstChannelLabel` | `claim[contact.facet.best_channel].value_json` when the lane writes it (registered as a new field in D1); absent otherwise | — |
| education | `educationLabel` | `claim[contact.facet.alma_mater].value_json` rendered (`"{institution}, {degree}"`) | — |
| tenure | `tenureLabel`, `employmentStartedAt` | `employmentStartedAt = claim[contact.facet.career_history].value_json.current.start_date` (ISO date); `tenureLabel = "{years} years {months} months"` computed **by the backend at request time** from that date | tenure computed from `Date.now()` in the browser (`contact-profile-content.tsx:217`) — **removed** (ruling R8) |
| LinkedIn stats | `linkedinFollowers`, `linkedinCreator` | `claim[contact.network_statistics].value_json.followers` (int); `claim[contact.member_badges].value_json` contains `"creator"` | — |
| reports | `reports[]` | committee members whose `claim[contact.reports_to].value_json.contact_id` equals this contact (new field, D1); `[]` otherwise | — |
| header "Updated" | (detail-level `lastModifiedAt` on the account is what the dummy shows) | **ruling R8:** the contact detail gains `lastModifiedAt = MAX(claim.collected_at) over the contact's live claims`; the shell shows it instead of the account's | account date shown on a contact page (`account-workspace-shell.tsx:179-185`) — **removed** |
| the contact page | `contactDisplay` | as §3.3 with `subject_kind='contact'`, `page='contact'`; generated lazily on first request (§4) | `ResearchStack` strips self-references by **name equality** (`research-content.tsx:745-751`) — replaced by `contactId` equality in the re-lift |
| legacy prose / evidence | `overviewParagraphs[]`, `evidence[]` | `[]` (contract change, ruling S5: relax the ≥1 minimum) | — |
| evidence | `researchEvidence[]` | §3.9 for the claim ids cited by `contactDisplay` + `locationClaimId` + `emailClaimId` | — |

**As built (D3, 2026-09-08).**

- **Addressability (D3 ruling).** E5 serves any contact that is **under this account** and has
  **≥1 live claim or a stored display section** — not only the coverage committee. A contact the
  research found and wrote facts about is a page the marketer may open; a contact row with nothing
  behind it is still a 404. Page *generation* is attempted only when claims exist, so an off-
  committee contact can never cause a spend on an empty page.
- **`linkedinUrl` has no null branch.** The dummy declares it a required `HttpUrl`, so a contact
  with no safe LinkedIn URL is served the **site root** `https://www.linkedin.com/` with
  `linkedinLabel: "LinkedIn"` — never a guessed profile path. Making the field nullable (as
  `BuyingCommitteeMember.linkedinUrl` now is) is a D4 follow-up.
- **`lastModifiedAt` is the contact's own** `MAX(claim.collected_at)` over its live claims (ruling
  R8), never the account's stamp.

### 3.7 Artifacts tab — `/accounts/{id}/artifacts` (E3 `artifacts[]`)

**Today no table binds a generated artifact to an account.** The candidate join is
`agent_artifact_subject (subject_entity_id = account_entity.id, binding_kind = 'direct') JOIN
artifact ON storage_key = artifact_key`, with `projectName` via `agent_artifact_project JOIN
project`, and the design document's title/thumbnail via the design subsystem's own tables. Whether
those design rows are reachable from `artifact.storage_key` is **not established** on this branch.

**Ruling S9 (recommendation):** v1 serves `artifacts: []` from E3, and the frontend renders its
existing `empty` state ("no artifacts yet"). The account-scoped artifact projection is its own
slice after the design leg writes a `(account_entity_id, design_document_id)` binding. Nothing is
invented to fill the tab.

**Landed 2026-09-30 (founder: every project's artifacts, labelled by project; the gallery's
thumbnail).** The binding exists since the 2026-09-19 multi-artifact legs — an ad born for a tagged
account carries `design_document.account_id` → `design_account.account_entity_id`. E3 serves the
artifacts library's own rows (`workspace_design_documents(account_entity_id=…)`) narrowed to the
account, from every project, `projectName` = the project's name, archived ones omitted, newest
first, `thumbnailPath` = `/api/clue/design/documents/{id}/thumbnail?v={current_version}`. The
activity feed's "{title} created" event (§3.8) is still not written.

### 3.8 Activity — the detail rail and `/accounts/{id}/activity` (E2 and E3 `activity[]`)

The dummy's activity shape (`kind ∈ created\|contacts\|summary\|artifact\|updated`, `actor
clue\|person`, `text`, `action`, `occurredAt`) is **not** the old lane's `research_view.*` ledger.
The new `account_activity_event` table (§2.2) is the single source. Its writers, all backend:

| Event | Written by | `kind` | `actor` | `text` / `action` |
|---|---|---|---|---|
| account added to the workspace | the account writer (discovery, import, manual create) | `created` | `person` (the creating user) when `created_by_user_id` is set, else `clue` | `"Account created"` / `"added {name}"` |
| research run finished for the account | the ARV2 driver's finalization (or the D1 loader) | `updated` | `clue` | `"Account researched"` / `"researched {n} facts"` |
| committee confirmed | the committee step's finalization | `contacts` | `clue` | `"Buying committee confirmed"` / `"{m} people"` |
| a display page generated or regenerated | the display runner (§4) | `summary` | `clue` | `"Overview written"` / `"{page} regenerated"` |
| an artifact bound to the account | the design leg (when S9 lands) | `artifact` | `clue` | `"{title} created"` |

Read: `SELECT ... FROM account_activity_event WHERE workspace_id = :ws AND account_entity_id = :id
ORDER BY occurred_at DESC, event_id DESC LIMIT 100`; `actor` resolved through `platform_user` for
`person` rows. `timeLabel` is served as a relative string computed at request time ("2 days ago");
`occurredAt` is the ISO-8601 truth. `isSample` is never served.

Replaces: actor inferred from a `"Clue "` text prefix (`account-workspace-presentation.ts:60-61`)
— removed; every event carries `actor`.

### 3.9 Shared: `ResearchEvidence` (one row per cited claim; E2, E3, E5)

Query: `claims_by_ids(conn, cited_ids, scope=WorkspaceScope.for_workspace(ws))` — the existing
reader (`claimstore/claims.py`), which applies the workspace scope and the retention predicate.

| Wire field | Source |
|---|---|
| `claimId` | `claim.id` |
| `sourceUrl` | `claim.source_url` when `safe_public_url` (`research_view_governance.py:62-69`), else `null` |
| `sourceDomain` | hostname of `claim.source_url` without `www.`; `null` when no URL |
| `faviconUrl` | `null` always (the frontend resolves favicons by domain through its own `/api/source-favicon` proxy; **the re-lift removes the `faviconUrl` gate at `research-content.tsx:47`** so a record with a domain and no favicon URL still shows the favicon) |
| `title` | `claim.value_json.source_title` when the lane stored one (media items store the episode/video title); else `null` |
| `quote` | `claim.evidence_span`; `null` when absent |
| `researchExcerpt` | when `quote` is `null`: the claim's value rendered as one sentence by the backend's `render_value_text(field_key, value_json)`; absent when `quote` exists |
| `publishedAt` | `date(claim.value_json.source_last_updated)` when present, else `date(claim.observed_at)` when the source is a dated document, else `null`. Served, **not rendered** (ruling R1: no dates on chips or hover cards) |
| `verifiedAt` | `date(COALESCE(claim.observed_at, claim.collected_at))` (the existing `reference_time`). Served for the frontend's new-since-last-visit computation only; not rendered (R1) |
| `verificationKind` | `"record"` when `claim.source_url IS NULL AND claim.extraction_method = 'api'` (AI Ark rows, email checks); else `"verified"` |
| `mediaTimestamp` | `claim.value_json.media_timestamp` (e.g. `"12:41"`); `null` otherwise |
| `provider` | `claim.source_key` mapped through one backend label map (`ai_ark→"AI Ark"`, `exa_contents→"Exa"`, `ashby_posting_api→"Ashby"`, `gemini→"Gemini transcript"`, …); unknown keys served raw |
| `outreachSafe` | `claim.outreach_safe` |

**Display gate (ruled, S10).** The existing contacts routes filter every contact claim through
`display_allowed` (`research_view_governance.py:128-156`), which by default requires
`identity_binding = STRONG`. The lenient write gate stamps facet claims `WEAK` when the writer did
not say, so under that predicate no ARV2 contact fact would display. **Ruling:** the new accounts
reads (E2–E5, and the contact-insights section of E3) use their own predicate,
`arv2_display_allowed(claim, policy)`, defined in the new read module next to the routes:

- account claims always pass (unchanged);
- a contact claim with `use_class = sensitive` is refused unless `policy.display_sensitive` (unchanged, fail-closed);
- a contact claim with `outreach_safe = true` passes regardless of `identity_binding`;
- a contact claim with `outreach_safe = false` passes only into a restricted section (`context-only`, `watch-outs`, `do-not-mention`) — it never reaches an outreach section regardless of binding;
- the professional / personal use-class policy switches still apply as in `display_allowed`.

`display_allowed` itself and every C7 surface that calls it are left untouched. The lane still
stamps `identity_binding` with what it knows (the PoC rows carry it), but display never depends on
that stamp. Identity risk is handled upstream: name-scoped lookups only, same-name exclusions in
every deep-research system prompt, `contact.facet.excluded_lookalike` records rejected candidates,
speaker identity verified before a media quote.

**As built (D3, 2026-09-08).** `ResearchEvidence` is composed once, in
`v1_shared.research_evidence_for`, over D2's `evidence_for_ids` (live claims only — a DSAR
tombstone is a supersession, so serving superseded evidence would re-surface erased text). The read
surface adds exactly two things to D2's rows: `sourceUrl` passes through
`research_view_governance.safe_public_url` before it is served, and `provider` is the label map
above. Every timestamp on the v1 wire is `iso_utc` — UTC with a trailing `Z` — because Zod 4's
`datetime()` rejects `+00:00`; that applies to `verifiedAt`/`publishedAt` here and to
`createdAt`/`lastModifiedAt`/`activity[].occurredAt` everywhere else.

**As built (D4-b, 2026-09-09) — unchanged.** No rule in this section moved. Two mechanical notes:
`safe_public_url` now lives in the dependency-free `platform/api/clue_api/url_safety.py` (C7's
`research_view_governance` re-exports it under its old public name), because the read surface may
no longer import a `research_view` module — pinned by
`tests/api/test_frontend_read_arv2_only_guard.py`. And `frontend_read/evidence.py` was deleted with
the FI-2 surface; the three functions E7 still needs moved to `frontend_read/evidence_stream.py`.
`arv2_display_allowed` remains the read surface's one display predicate — the contact email-lookup
route was switched onto it too (it had been gating the very `core.work_email` addresses the screens
render behind C7's STRONG-binding `display_allowed`; two predicates over one claim is two answers to
"may this address be shown").

---

## 4. The display-block path (how `overviewDisplay`, `insightsDisplay`, `contactDisplay` are produced)

1. **Lookup.** `SELECT section_key, body_json, cited_claim_ids, generated_at FROM display_block
   WHERE workspace_id = :ws AND subject_kind = :kind AND subject_id = :id AND page = :page AND
   superseded_at IS NULL`.
2. **Staleness check (recipe-scoped).** For each recipe row of the page: `EXISTS (SELECT 1 FROM claim
   WHERE entity_id = :subject AND field_key = ANY(recipe.allowed_field_keys) AND workspace_id = :ws
   AND collected_at > block.generated_at)` or a superseded cited claim (`claim.superseded_by IS NOT
   NULL` for any id in `cited_claim_ids`) or `recipe.instruction_version <> block.prompt_version`.
   Stale → serve the existing block now, enqueue regeneration of that section only.
3. **Miss (no block).** Gather the subject's **live claims** on `recipe.allowed_field_keys` —
   every live row, not one winner per field: `claims_for_entities(...)` under the workspace scope,
   with the merge's *eligibility* posture applied (with `CLUE_VERIFICATION_ENABLED` on, unverified
   tier-4 rows are excluded) but **not** its `(entity, field)` collapse, because a page shows
   everything the research found. Drop
   `outreach_safe = false` claims unless `recipe.restricted`; if nothing remains → serve `empty:
   true` and write no block. Otherwise run one display-model call for the section (master plan §7),
   validate the `ResearchSection` shape, compute `priority` per item, run the sensitivity floor
   (an `outreach_safe = false` claim id cited outside a restricted section → regenerate once, then
   drop the item), and `INSERT INTO display_block`. All sections of a page run in parallel; the
   request waits for the page (~15 s first open).
4. **Contact pages** follow the same path with `subject_kind = 'contact'` and are never generated
   ahead of the first request.

The display model never receives a URL, a claim's `source_url`, or a claim id it may type into
prose; the frontend joins `claimIds → researchEvidence` at render time.

**Note (2026-09-08, D2).** Step 3 above previously read "Gather `current_values(subject,
recipe.allowed_field_keys)`". That wording is superseded: `current_values` is the *merge*, and the
merge answers "what is the current value of this field", which is the wrong question for a page.
The implemented rule is the one now written above, and it lives in
`platform/api/clue_api/arv2/display/gather.py` (`gather_section_inputs`) — one read for the whole
page, three counted exclusions (special-category never, unsafe outside the restricted sections,
unverified tier-4 under a verifying posture), then near-duplicate folding within each subject. The
rest of §4 is implemented as written: lookup in `blocks.live_blocks`, the recipe-scoped staleness
check in `blocks.stale_sections`, the per-section call and floor in `runner.py` / `floor.py`, and
the parallel page in `page.ensure_page`.

**As built (D3, 2026-09-08).** The read surface reaches §4 only through
`frontend_read/display_pages.py::DisplayPages`:

- **Generation on read happens only with the flag *and* a key.**
  `CLUE_ARV2_DISPLAY_GENERATE_ON_READ` (default `true`) off, **or** no OpenRouter secret, composes
  the seam with no runner, and `page()` is then a pure projection over stored blocks — which is why
  the flag alone is not a spend switch. `DisplayPages` never raises at construction.
- **Composition degrades, it never fails the request.** Any provider or transport error inside
  `ensure_page` is caught and the page is composed from whatever live blocks exist — an all-empty
  block is still a block, and the frontend renders the page grammar from it. A degraded read still
  schedules the background repair.
- **Stale is served, then repaired behind the request.** `page()` calls
  `ensure_page(regenerate_stale=False)`, composes the live rows, and — when `stale_sections`
  reports any — schedules regeneration as a background task **keyed per page** (deduped, its own
  connection, never awaited by the request), which is master plan §7's policy.
- **The evidence routes authorise with `generate=False`.** E7 and its contact variant check a
  requested `claimId` against what a *current* read exposes; that check must never write or spend,
  so `page(..., generate=False)` skips `ensure_page` **and** the stale scheduling.

---

## 5. Rulings (Aryan ruled 2026-09-07: S1–S9, S11, S12 as recommended; S10 = read-time relaxation. Shashank's confirmation pending)

| # | Question | Recommendation |
|---|---|---|
| S1 | Owner and creator: add `owner_user_id` / `created_by_user_id` columns on `account_entity` (D1 migration) referencing `platform_user` | Yes; the only alternative is a separate assignment table, which buys nothing in v1 |
| S2 | Logos: no pipeline exists | Contract change `logoPath: string \| null`; frontend glyph on `null`; no third-party logo fetch in v1 |
| S3 | Fit band thresholds from the 0–1 score | High ≥ 0.70, Medium ≥ 0.40, else Low; stored as config, not code |
| S4 | `previewTitle` | = `name` in v1 |
| S5 | Legacy prose slots (`summaryParagraphs`, `businessParagraphs`, `overviewParagraphs`) require ≥1 string in the dummy's Zod | Relax to `default([])`; the backend never fabricates prose for a legacy slot |
| S6 | Which custom variables are `primary` in the rail | the first four active client-pack fields in registry order; a `rail_position` column can follow if the client wants control |
| S7 | Contact `title` when no claim exists | make `title` nullable (`string \| null`); the row shows "—" |
| S8 | `influence` when the committee claim lacks it | persona-derived default table above, served by the backend |
| S9 | Artifacts tab source | `[]` in v1; account-scoped artifact binding is its own later slice |
| S10 | **Display gate vs lenient binding.** Keep `display_allowed` as the contact display predicate? With `display_requires_strong_contact_binding = true` (the default) and lenient `WEAK` stamping, every ARV2 contact fact is hidden | **Ruled: read-time relaxation.** E2–E5 use `arv2_display_allowed` (§3.9): use-class rules and the sensitive fail-close stay; a `WEAK` binding no longer hides an `outreach_safe = true` claim; `display_allowed` and the C7 surfaces are untouched. The lane keeps stamping the binding it knows, but nothing on screen depends on it |
| S11 | `researchStatus` enum on the wire | adopt the backend's five values in the dummy's Zod; drop `fully_enriched` / `failed` |
| S12 | The `recipe` name collision | display recipes live in `display_section_recipe`; the master plan's "recipe rows" wording is updated to that name |

---

## 6. What the dummy stops doing after the re-lift (checklist for D4)

Each line is a derivation found in `clue-frontend` @ `84f8ee7` that has a served replacement above.

- [ ] owner falls back to the viewer (`account-owner.ts:16`) → render `owner ?? createdBy ?? "Unassigned"`
- [ ] `fitScore: 0` / `overallFit: "Medium"` on create (`create-account.ts:7,15`) → POST and render the returned row
- [ ] overall fit parsed from `h1` (`research-content.tsx:787`) → `overallFit`
- [ ] section counts parsed from `h1` (`research-content.tsx:551-554`) → `items.length`
- [ ] `insightSummary` regex rewrite (`account-workspace-presentation.ts:26-30`) → served strings
- [ ] tenure from `Date.now()` (`contact-profile-content.tsx:217`) → `tenureLabel`
- [ ] contact "Updated" = account date (`account-workspace-shell.tsx:179-185`) → contact `lastModifiedAt`
- [ ] email chip by substring (`contact-profile-content.tsx:91-95`) → `emailClaimId`
- [ ] actor inferred from `"Clue "` prefix (`account-workspace-presentation.ts:60-61`) → `actor`
- [ ] `"register-"` claim-id prefix admitted to Sources (`research-presentation.ts:8`) → removed
- [ ] `faviconUrl` gate before the domain proxy (`research-content.tsx:47`) → proxy on `sourceDomain` alone
- [ ] self-reference stripping by name (`research-content.tsx:745-751`) → by `contactId`
- [ ] `Number(value) || 0` for score variables (`accounts-table.tsx:395`) → numeric string always served
- [ ] three research-status relabel maps → `researchStatusLabel`
- [ ] featured-contact drawer chosen by `profileAction === "preview"` scan (`contacts/page.tsx:26-28`) → not served in v1; the drawer opens on row click only
- [ ] `LookupEmailButton` stub (`use-email-lookup-controller.ts:20-25`) → the existing email-lookup POST + poll

Kept as presentation (not derivations): date formatting from ISO values, initials avatars, badge
tones, closed-by-default toggles, the localStorage "new since last visit" computation (D5).
