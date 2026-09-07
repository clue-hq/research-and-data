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
| E6 | `GET /frontend/v1/accounts/{accountId}/activity` | yes (`account_activity.py:282`) | not read by the new screens; `activity[]` rides E2 and E3 | unchanged; retired after D4 if nothing reads it |
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
| `entity_research_run`, `entity_research_job` | research status per account | `job.state, job.finalization_outcome, job.subject_entity_id, job.project_id, job.created_at, job.terminal_at` |
| `entity_research_account_coverage` | the confirmed buying committee | `research_run_id, account_entity_id, committee_member_ids, committee_status, created_at` |
| `artifact` | the snapshot behind a claim (E7) | `storage_key, workspace_id, content_sha256, media_type, size_bytes, erased_at, purged_at` |
| `platform_user`, `workspace_membership` | account owner / creator display | `user_id, display_name`; membership confirms the user belongs to the workspace |
| `agent_artifact_subject`, `agent_artifact_project`, `artifact` | generated artifacts bound to an account (E3 `artifacts[]`) | `subject_entity_id, artifact_key, binding_kind, created_at`; see §3.7 for the open ruling |
| `research_subject_activity` | the old lane's activity ledger | read by E6 only; **not** a source for the new `activity[]` (§3.8) |

The ARV2 lane (Track R) and the D1 loader write to the same substrate tables the old lane used
for **run state**: one `entity_research_run` per launch, one `entity_research_job` per account,
one `entity_research_account_coverage` row per finished account (master plan §5.1 reverse edge).
They do not import any quarantined module; they write rows.

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
| research status | `researchStatus` | existing rule `research_status_for(...)` over `entity_research_job` + fleet control (`accounts_list.py:383-402`), evaluated for **the account's primary project** (§3.1 `primaryProjectId`); `not_started` when no job. **The wire enum becomes the backend's five values** `not_started \| in_progress \| needs_review \| completed \| suspended` (contract change; the dummy's `fully_enriched`/`failed` are replaced) | — |
| research status label | `researchStatusLabel` | served text from one backend map: `not_started→"Not started"`, `in_progress→"In progress"`, `needs_review→"Needs review"`, `completed→"Researched"`, `suspended→"Paused"` | three independent relabel maps in the dummy (`accounts-table.tsx:82-87`, `accounts-filter-panel.tsx:57-62`, `account-detail-primitives.tsx:35-40`) |
| spinner | `researchIsRefreshing` | `true` when a **later** `entity_research_job` for this account is non-terminal while an earlier one is terminal `completed` (a re-run); else `false` | — |
| overall fit | `overallFit` | `claim[account.scoring.fit]` attributed to the primary project via `run_lineage`; band from `value_json.value` (0–1): `≥ 0.70 → High`, `≥ 0.40 → Medium`, else `Low`; `null` when no claim. **Thresholds are ruling S3** | `createLocalAccount` invents `"Medium"` (`create-account.ts:15`) |
| fit score | `fitScore` | `round(100 × claim[account.scoring.fit].value_json.value)`; `null` when no claim | `createLocalAccount` invents `0` (`create-account.ts:7`) |
| revenue | `revenueBand` | `claim[core.revenue_band].value_json` (string); `"Unknown"` when absent | — |
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
| buying committee table | `buyingCommittee[]` | members = `entity_research_account_coverage.committee_member_ids` of the **latest** coverage row for the account (`ORDER BY created_at DESC, coverage_id DESC LIMIT 1`), each resolved through `contact_entity` (survivor). Per member: `contactId = contact_entity.id`; `name = contact_entity.full_name`; `title = claim[contact.current_title]`; `persona = claim[contact.persona].value_json`; `email = claim[core.work_email].value_json.address`, `emailClaimId = that claim's id` (both `null` when absent); `linkedinUrl = contact_entity.linkedin_url`; `whyTheyMatter = claim[contact.role_on_committee].value_json.rationale` | avatar without `src` (`research-content.tsx:963`) — presentation, unchanged |
| evidence for every chip | `researchEvidence[]` | §3.9, for the union of claim ids cited by `overviewDisplay` + `buyingCommittee[].emailClaimId` | — |

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

Rows = the committee members of §3.3 (same coverage query), ordered by persona rank
(`economic_buyer, champion, technical_evaluator, user, blocker`) then `full_name`.

| Element | Wire field | Source and rule | Replaces |
|---|---|---|---|
| identity | `id`, `name` | `contact_entity.id`, `contact_entity.full_name` | — |
| avatar | `avatarUrl` | absent (no avatar store); the client renders initials | — |
| title | `title` | `claim[contact.current_title].value_json`; `"—"` when absent (the dummy requires a non-empty string; **ruling S7**: make `title` nullable) | — |
| persona | `persona`, `personaTone` | `persona = claim[contact.persona].value_json` (the ICP `persona_map` vocabulary, master plan §5.2); `personaTone` from one backend map `economic_buyer→olive, champion→orange, technical_evaluator→blue, user→cyan, blocker→red` | — |
| influence | `influence` | `claim[contact.role_on_committee].value_json.influence ∈ High\|Medium\|Low`; when the claim lacks it, from persona: `economic_buyer→High, champion→High, technical_evaluator→Medium, user→Medium, blocker→Medium` (**ruling S8**) | — |
| email | `emailStatus`, `emailLabel` | `claim[core.work_email]` exists with `value_json.status ∈ (verified_smtp, catch_all_valid)` → `emailStatus: "available"`, `emailLabel: value_json.address`; else `emailStatus: "lookup"`, no label | row branches on `emailLabel` presence (`contact-row.tsx:118`) — the two are served consistently, so either works; the re-lift branches on `emailStatus` |
| socials | `socials[]` | `["linkedin"]` when `contact_entity.linkedin_url` is set; `"x"` appended when `claim[contact.x_url]` exists (not produced by the lane in v1) | — |
| open action | `profileAction` | `"page"` when the contact has ≥1 live claim or ≥1 display block; else `"none"`. `"preview"` is not served in v1 (the dummy's featured-contact drawer is a fixture behaviour, `contacts/page.tsx:26-28`) | — |
| lookup button | — | the dummy's `LookupEmailButton` is a `setTimeout` stub (`use-email-lookup-controller.ts:20-25`). Production wires it to the existing `POST .../contacts/{id}/email-lookup` + poll (`contacts.py:711, 740`) in D4 | — |

### 3.6 Contact profile — `/accounts/{id}/contacts/{contactId}` (E5)

The row of §3.5, plus:

| Element | Wire field | Source and rule | Replaces |
|---|---|---|---|
| account link | `accountId`, `accountName`, `accountLogoPath` | `contact_entity.account_entity_id`, `account_entity.canonical_name`, logo as §3.1 ruling S2 | — |
| "Research" row | `recentSignalsLabel` | `"{k} signals"` where `k = COUNT(claim) for the contact with signal_priority ≤ 2 and outreach_safe`; `"No signals yet"` when 0 | — |
| LinkedIn | `linkedinUrl`, `linkedinLabel` | `contact_entity.linkedin_url`; label = the URL path's last segment (`/in/nicholastfisher` → `nicholastfisher`) computed by the backend | — |
| X | `xUrl`, `xLabel` | absent in v1 (no field produced) | — |
| email verified date | `emailVerifiedAt` | `date(claim[core.work_email].observed_at)` when `status = verified_smtp` | — |
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
3. **Miss (no block).** Gather `current_values(subject, recipe.allowed_field_keys)`; drop
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
