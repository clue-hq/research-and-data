# FI-1 — Accounts & contacts flow: frontend ⇄ backend contract-gap review

**Status: study complete — awaiting founder discussion and sign-off. No decisions in this doc are ratified.**
Date: 2026-08-07. Branch: `platform/frontend-integration` @ `f89ad09e` (study verified against `421a9f53` ancestry).
Method: four parallel read-only code studies (HTTP surface inventory; account-flow field mapping; contact/committee field mapping; runs/launch/chat surfaces), consolidated here. Frontend truth = the Zod schemas under `apps/frontend/src/features/*/model/` (not the prose contracts). Backend truth = code on this branch.

This is the "contract-gap review with the founder" step required by the branch charter (root `CLAUDE.md`) before any accounts-flow implementation. The companion decision register is §8; nothing in §8 may be implemented before it is ratified.

---

## 0. Verdict in one paragraph

The **data substance** matches better than expected — most of what the account/contact screens want either exists as governed claims/entities or is derivable with an explicit mapping. The **transport and shape** match is poor: the frontend expects workspace-global, account-centric REST lists; the backend serves project-run-scoped, single-entity, reference-only reads behind default-off flags, with exactly one generic write endpoint and no way to start research over HTTP at all. The gap is therefore mostly *architectural* (a missing screen-shaped read layer + a launch-authority decision), not *data* (only ~8 frontend fields are true no-data). Nothing on the frontend breaks today because it is 100% fixture-backed — the contract can be renegotiated freely before any adapter is switched on.

---

## 1. Structural mismatches (these frame every field-level row below)

- **S1 — Scope model.** Frontend screens are workspace-global and account-centric (`/accounts`, `/accounts/:id/contacts` — no project in the URL). Every backend account/contact read resolves `(workspace_id, project_id, project_run_id, product_id)` first and 404s otherwise (`research_view_api.py:187-260`). There is **no product-neutral, run-free account read anywhere**.
- **S2 — No list surfaces.** No endpoint, repository function, or tool lists accounts or contacts. `GET /v1/projects/{id}/research-view-status` is the nearest thing: it lists only subjects that already have a composed snapshot and carries no name/domain/score/status business fields. There is also no lookup-by-domain; every read needs a pre-resolved entity uuid. A frontend at `/accounts` has no discoverable path to a set of entity ids.
- **S3 — Reference-only reads.** The C7 research view deliberately serves references, not values, for identity/score/committee/activity/coverage (`ResearchOwnedReference` with opaque `owner_ref`); values need a second `POST …/research-view-owner-references:resolve` call. `OpaqueReferenceToken` **rejects any string containing `://`** — evidence URLs are architecturally excluded from payloads, and the evidence-action redemption route does not exist (process-local broker, no HTTP redemption).
- **S4 — Everything is dark by default.** All C7 flags default `False` (`settings.py:225-243`) plus a canary workspace allowlist that 404s non-admitted workspaces. **No CORS middleware exists anywhere.** Tenancy is a trusted `X-Workspace-Id` header (`local_header` mode; `service` mode crashes at startup). No auth, no user identity, no error envelope matching the frontend's `{error:{code,message,requestId}}`.
- **S5 — Research launch is not a REST verb.** `launch_account_research@1` is batch (1–500 accounts), project-run + confirmed-directive + budget-approved, requires a per-account **human tier-checkpoint claim**, and needs an ambient non-forgeable `ToolContext.action_ref` that **no production code path sets**. It is composed only into the fleet worker (no HTTP server); on the HTTP process the tool 422s. So today *nothing* can start research over HTTP — and the frontend's proposed `POST /accounts/:id/research` conflicts with backend authority doctrine, not just shape.
- **S6 — Chat has no production surface.** The only conversational HTTP endpoint (`POST /v1/trials/{id}/turns`) is a loopback-only, flag-gated local canary. Production `/agent/*` endpoints serve turn metadata/telemetry only — no message text. No streaming exists (single blocking `graph.ainvoke`); the append-only, content-addressed turn substrate has no stable *part-level* identity, which the frontend's streamed-in-place message parts assume.

---

## 2. What the backend actually serves over HTTP today

One production FastAPI app (`clue_api.projections_main:app`, default `127.0.0.1:8000`). ~51 registered routes, **~29 served with default settings**. Summary (full inventory in the study transcripts; key routes):

| Surface | Routes | Served by default? |
|---|---|---|
| Agent turn metadata | `GET /agent/projects/{project_id}/turns`, `/agent/turns/{turn_id}` (+`/progress`, `/telemetry`), `/agent/routes/{surface}/{subject}` | yes (metadata only, no prose) |
| Project-run projections | `GET /project_runs/{run_id}/overview`, `…/accounts/{account_id}/progress`, `…/manifest`, `…/readiness` | yes — **but `…/progress` reads `account_run`, which the M8D path leaves at `pending` forever** |
| Coverage/attempts | `GET /research_coverage/{run_id}`, `GET /research_attempt_history/{run_id}/{entity_id}/{field_key}` | yes |
| Stage-0 | `GET /stage0/recon/{id}/brief`, `…/progress`, `GET /stage0/readiness/{id}` | yes |
| Proposals | `GET /field_proposals`, `GET /source_proposals` (the only true workspace-scoped lists) | yes |
| Writes | `POST /tools/{name}` (48 default-addressable tools; pydantic-validated; idempotency headers) + `PATCH /project_runs/{id}/manifest` (pause/resume/adjust) | yes, but: M8D-quarantined tools raise; entity-research launch tools 422 on this process; LLM-gateway tools 422 (no gateway wired); ingestion tools fail (`ingestion_engine` never wired) |
| SSE | `POST /project_runs/{id}/stream_token` → `GET /project_runs/{id}/events?stream_token=…` (single-use 5-min token; `Last-Event-ID` replay; 24h horizon; project-run-scoped topics only — **entity-research fleet jobs and agent turns emit nothing**) | yes |
| C7 research views | `GET /v1/projects/{pid}/accounts/{aid}/research-view` (+contact twin, +snapshot read, +status list, +owner-ref resolve, +compose/recheck/evidence-action mutations, +deprecated `/dossier` aliases) | **no — all flags default off** |
| Ingestion upload | `POST /ingestion/uploads` | route yes; fails at tool (engine unwired) |
| Exa webhook | `POST /v1/webhooks/exa-websets` (HMAC) | only if secret set |
| Trial (local canary) | `POST /v1/trials`, `…/turns`, `…/accounts`, `…:research`, etc. | separate loopback process, flag-gated |
| Handoff app | `GET /project_runs/{id}/handoffs`, `GET /accounts/{id}/handoff` (+provenance) | **never mounted — dead code** (do not resurrect; path collides with the natural `/accounts/:id`) |

Id vocabulary: `workspace_id` = header string; `project_id` = **slug string**; `project_run_id` = uuid; account/contact ids = **entity uuids** (never domain/slug/name); `field_key` = dotted registry key in path.

---

## 3. Field-by-field: accounts screens

Statuses: **SERVED** (exists, reachable), **DERIVABLE** (data exists; mapping/aggregation decision needed), **NO-DATA** (backend never produces it), **CONFLICT** (semantic clash needing a decision).

### 3.1 Account list row (`model/account.ts`)

| Frontend field | Backend source | Status |
|---|---|---|
| `id` | `account_entity.id` (uuid) | SERVED |
| `name` | `account_entity.canonical_name` / claim `core.account_name` | SERVED |
| `logoPath` | none — Exa returns `logoUrl` and drops it (`adapters/exa_websets.py:555`); no field, no writer | NO-DATA |
| `websiteUrl` (`z.url()`) | `primary_domain` (bare domain, **nullable**) | DERIVABLE — scheme-prepend + nullability decision |
| `researchStatus` (4-value enum) | M8D `entity_research_job.state` × `finalization_outcome` (+legacy `account_run`) | DERIVABLE/CONFLICT — see §5 |
| `researchIsRefreshing` | nothing — no refresh concept persisted | NO-DATA (schema addition or derived count) |
| `overallFit` (High/Med/Low) | claim `account.scoring.tier` — free string; live rubric emits only `"high"`/`"low"` → **`Medium` unreachable**; also conflates tier (governed checkpoint) with fit (score) | CONFLICT |
| `fitScore` (0–100 int) | claim `account.scoring.fit` — float ∈ [0,1], pinned to `(product, icp_key, icp_version, project_run)`; `AmbiguousFitProjection` if two live | DERIVABLE — ×100 + a representative-run rule |
| `revenueBand` | claim `core.revenue_band` (7-value enum; written only by Exa enrichment) | DERIVABLE, thin coverage; label map needed |
| `employeeBand` | `core.employee_count` (well-populated int); `core.employee_range` registered but **never written** | DERIVABLE — bucketer needed |
| `locationCount` | nothing — only singular `core.hq_location` | NO-DATA |
| `primaryProjectId` | no "primary" concept; only `ORDER BY pr.created_at DESC` | DERIVABLE (policy) |
| `projects[]` | **no account↔project junction table**; only (a) execution path `project→project_run→account_run` or (b) directive path `account_research_directive_account` — neither covers merely-discovered accounts | DERIVABLE (structural decision) |

`POST /accounts/query` as spec'd is not implementable: 4 of its 8 filter fields (`fitScore`, `revenueBand`, `employeeBand`, `locationCount`) are merged-JSONB claim values or nonexistent, not SQL columns — needs a materialized read model if wanted.

### 3.2 Account detail (`model/account-detail.ts`) vs the C7 account view

Composed account sections: `IDENTITY`, `RESEARCH_STATUS`, `SUMMARY` (**always empty — no account field routes to it**), `ABOUT`, `FIT` (single score reference), `INSIGHTS`, `COMMITTEE`, `ACTIVITY`, `COVERAGE_GAPS`. `PERSONALIZATION`/`VALUE_NARRATIVE`/`FEASIBILITY` never composed for accounts.

| Frontend field | Status | Note |
|---|---|---|
| `previewTitle`, `websiteLabel` | DERIVABLE | formatting |
| `sizeLabel`, `revenueLabel` | DERIVABLE | needs vocab + null branch (backend's correct-empty) |
| `locationsLabel` ("Global") | CONFLICT | backend has one HQ; multi-site judgement never made |
| `referralFit` / `directAccessFit` / `recallFit` | NO-DATA | `ScoreDimension` = {FIT, INTENT} only; the three dials don't exist as a concept. Backend has `intent`, which the frontend never asks for |
| `summaryParagraphs` (`.min(1)`) | NO-DATA today | account `SUMMARY` structurally empty; intended filler `account.value_narrative` routes to a section **not in `ACCOUNT_SECTION_ORDER`** → see defect L1 |
| `businessParagraphs` (`.min(1)`) | DERIVABLE | `core.company_about` = one provider blurb + a facts list, not paragraphs |
| `fitCriteria[{matched:bool,title,evidence}]` | CONFLICT | scoring `Contribution{factor,flag}` computed then **discarded at persistence**; `RubricEntry.label` declared, never read; persisted shape is `{name:field_key,weight,value,evidence_claim_ids}`. Alternative candidate: `DiscoveryCriterionReview` (criterion text + tri-state decision + reasoning + reference URLs), only in `ScoringMode.DISABLED` |
| `contacts[{id,name,avatarUrl}]` | DERIVABLE minus avatar | committee refs resolve to `{contact_entity_id, persona, role_on_committee,…}`; name via identity resolve; **avatar NO-DATA** |
| `insights[{source,title,dateLabel,url}]` | CONFLICT | values exist (`account.recent_funding`, `operational_pain`, `strategic_moves`, `resonance.*` route to INSIGHTS) but **`url` cannot cross the C7 boundary** (S3), and no `title`/`source` classifier exists; timestamps exist |
| `activity[{kind,text,timeLabel}]` | CONFLICT | `research_subject_activity` is reference-only, **no `text`**; only writer emits `research_view.{section_stale,updated,recheck_completed}` — nothing maps to `contacts\|summary\|created` |
| workspace tab `artifacts[]` | NO-DATA in practice | `agent_artifact_subject` binding exists but rows are agent-turn artifacts; real design artifacts arrive only when the design-integration branch merges |

Zod hard floors (`.min(1)` strings/arrays, required `.url()`) will **throw in the repository adapter** on the backend's correct-empty outputs — the schemas currently have no absence/redaction vocabulary at all.

---

## 4. Field-by-field: contact screens

### 4.1 Contact table row (`model/account-contact.ts`)

| Frontend field | Backend source | Status |
|---|---|---|
| `id` | `contact_entity.id` | SERVED |
| `name` | `contact_entity.full_name` (nullable; via owner-ref resolve — 2 calls) | DERIVABLE |
| `title` | claim `contact.current_title` (Sumble; governed — `value_json` nulled on display-deny) | SERVED (governed) |
| `persona` | claim `contact.persona` — not a routed statement; only inside committee owner-ref | DERIVABLE (2 calls) + enum clash (§4.3) |
| `personaTone` | none | NO-DATA — keep as frontend deterministic map |
| `influence` (High/Med/Low) | none — nearest: free-text `contact.job_level`, `role_confidence`/`role_plausible`; `RoleSeniority` exists but never persisted | NO-DATA / weakly DERIVABLE |
| `avatarUrl` | nothing, repo-wide zero hits | NO-DATA + policy question (§7) |
| `emailStatus` (`available\|lookup`) | 4 stacked state machines; authoritative predicate `ContactChannelValidation.delivery_eligible` | CONFLICT — 2 values can't express refused/in-flight (§4.4) |
| `socials[]` (5 networks) | only `contact_entity.linkedin_url`; approved host list is literally `("linkedin.com",)` | NO-DATA beyond LinkedIn |

### 4.2 Contact profile (`AccountContactDetailSchema`)

`accountId`/`accountName` SERVED (join at API root). `accountLogoPath` NO-DATA (same logo gap). `recentSignalsLabel` DERIVABLE (count `contact.facet.recent_post` + `public_appearances` statements — **count display-eligible only**, else it leaks suppressed data). `linkedinLabel/Url` DERIVABLE. `xLabel/xUrl` NO-DATA yet **required non-nullable** in Zod. `overviewParagraphs` NO-DATA/architectural — contact `summary` section has zero routes in any shipped pack; a contact narrative is an M12-class synthesis deliverable, not a mapping. `evidence[].url` CONFLICT (S3 doctrine); `.title` NO-DATA; `.dateLabel` DERIVABLE; `.source` DERIVABLE via provider-label map.

### 4.3 Persona taxonomy clash

Backend `Persona` is **closed, 4 values**: `champion`, `economic_buyer`, `technical_evaluator`, `blocker` (also the domain of `role_on_committee`, which carries `{confidence, plausible, rationale}`). Orthogonal open grouping: `contact.class` (workspace-defined; explicitly not guessable from title/persona). Frontend fixtures use **11 open labels** (`Executive Sponsor`, `Decision Maker`, `Financial Buyer`, `Operational Leader`, `Strategic Influencer`, `External Stakeholder`, …) — only `Economic Buyer` maps cleanly; `blocker` has no frontend counterpart. Two different taxonomies at different granularities, not a rename.

### 4.4 emailStatus mapping (honest version)

`delivery_eligible` → `available`; `not_requested`/no row → `lookup`; **no frontend state exists** for `excluded`/`failed_validation`/`rejected`/`denied`/suppressed (rendering these as `lookup` invites re-triggering a spend compliance already refused — the real defect of the 2-value enum) nor for in-flight (`waiting_external`, `validating`, …). No HTTP surface serves channels at all today; the value itself (the address) is deliberately kept out of generic surfaces at every layer (handoff carries `ContactDeliveryChannelRef` — capability, no value).

### 4.5 The right substrate for the contact list

`ContactEligibilityResolver.resolve_account(account_entity_id, workspace_id)` (`platform/api/clue_api/contact_eligibility.py:166-256`) already returns the governed committee: workspace-scoped, product-exact, merge-redirect-following, use-decision-joined, sorted — built "so C7 contact detail cannot drift from the account committee list, M12 handoff, or positioning eligibility." It needs `project_run + product` context the frontend URL doesn't carry. Do **not** build on `identity.contact_ids_for_account` (ungoverned membership read).

---

## 5. Research status & kickoff

### 5.1 Job lifecycle (M8D)

`queued → leased → running → {waiting_external → queued (wake) | terminal}`; **one terminal state**, requiring an engine receipt (DB CHECK). `ResearchFinalizationOutcome` has 6 values but only **`completed` / `needs_review` / `cancelled` are ever produced**; `failed` is unreachable — a worker crash *re-queues* the job, pauses admission, and drives the fleet to `SUSPENDED` (no attempt counter, no retry ceiling, no persisted error text — only an error sha + reason code). Legacy `account_run` rows are written at `PENDING` and **never advanced** on the M8D path (only quarantined code advances them) — so the existing `GET /project_runs/{id}/accounts/{id}/progress` endpoint reports a fiction for M8D-researched accounts.

### 5.2 Mapping to `researchStatus`

| Frontend value | Honest backend condition |
|---|---|
| `not_started` | no `entity_research_job` for the entity (needs the missing `subject_entity_id` index; cheaper proxy: zero `entity_research_result` rows) |
| `in_progress` | job non-terminal AND `admission_state ≠ paused` |
| `fully_enriched` | terminal + `completed` — but true "fully enriched" = empty `unresolved_field_keys` + `committee_status='complete'`, and the fleet projection SQL **doesn't select those columns** |
| `failed` | **nothing maps** — backend's failure mode is "suspended, awaiting a human" |
| *(no frontend slot)* | `needs_review` — the backend's honest third outcome |
| *(no frontend slot)* | "not launchable" — account lacks the human tier-checkpoint disposition |

`researchIsRefreshing`: no backend concept; derivable only by counting prior terminal jobs, or a schema addition. Multiple concurrent runs per account are legal and undetected — a per-account status needs a latest-run-wins rule.

### 5.3 The launch-authority decision (the big one)

Frontend proposes: per-account, session-authed `POST /accounts/:id/research` → `202 {jobId, status:"queued"}` + a `GET` poll. Backend doctrine: launch is a SPEND effect requiring confirmed directive + project run lineage + per-account human tier disposition + reviewed estimate/cap + ambient non-forgeable `action_ref` ("caller-authored tool arguments never get to choose who approved an operation"). **Today neither works** — no production `ToolContext` ever sets `action_ref`, so every human-receipt-gated tool (incl. directive confirmation) is uninvocable in production; the launch services aren't composed into the HTTP process; `entity_research_runtime_enabled` defaults off.

Options (founder decision — see D-9):
- **A — HTTP confirmation ritual.** `POST …/research:estimate` (returns eligible set + per-account cost + a set-bound single-use `confirmation_token`) then `POST …/research:launch` (token *is* the `action_ref`). Requires an actor/action_ref seam at the HTTP edge (a real auth-layer decision), composing launch services into the HTTP process, flipping the flag, a per-account status read (+ index), and a which-run/which-directive rule. Approval becomes structurally real but no longer conversation-mediated.
- **B — Kickoff through Head-of-ABM.** The button opens/posts into the project thread; the agent drafts the directive, presents the estimate, launches on the user's confirming turn. Doctrine fully intact — but requires the entire production chat surface to exist first (S6), a new post-Stage-0 conversation surface (the tool is withheld on the trial surface), extending turn-binding to ambient `action_ref`, and an approval-card UX. Still needs the same status read path.
- **Shared prerequisite work under either:** action_ref plumbing; launch-service composition + flag; per-account reverse status lookup + `subject_entity_id` index; enum reconciliation (D-6); surfacing "not launchable".

Frontend reality check: no component calls `/research` today (the only kickoff-shaped control is a 700 ms timer stub), so nothing blocks read-only integration while this is decided.

### 5.4 Phase constraint (existing ruling)

Until the M8D R11 DEEP-phase bridge lands, composed project runs cannot pass `TIER_CHECKPOINT`→`DEEP`; `run_overview.current_phase` never reaches `verification`/`handoff`, and `run_verification` silently returns `accounts_processed=0` on M8D-researched accounts. Any phase-stepper UI must treat post-TIER_CHECKPOINT phases as not-yet-composed (already in the charter; reaffirmed by this study).

---

## 6. Chat components

What exists: read-only turn *metadata* endpoints; a loopback-only trial chat; no streaming; no part-level records. Mapping vs the frontend's 7 message-part kinds: `text` — substrate yes (one blob per turn, artifact-backed), HTTP no; `reasoning` — MISSING (raw LLMResult blobs only, never typed/extracted); `tool` — DERIVABLE from `agent_plan_operation` + `agent_tool_result` (artifact keys, not inline JSON; the frontend's 7 tool states have no counterpart); `plan` — DERIVABLE (richer backend); `task` — PARTIAL (delegations durable; `write_todos` lives only in the checkpointer; no numeric progress); `sources` — MISSING at turn layer; `action` — frontend-only. **Stable mutable per-part ids are fundamentally absent** — the substrate is append-only and content-addressed by design. Conversation status: `idle←completed`, `running←running`, `needs-input←awaiting_input` map; `review`/`approval` have no counterpart (nearest: `open_gate_refs` on the finalize envelope, un-flavored). HITL is *not* an interrupt: `finalize_turn` is `return_direct=True`, the turn ends, the human answers in a new turn; today's real confirmations are out-of-band `_HUMAN_ONLY_TOOLS` commands. Serving the chat contract needs: a production turn-creation route, a streaming story, typed part records (a doctrine question against append-only), reasoning extraction, and turn pagination (`agent_turns_for_project` currently has no LIMIT). **Recommendation: chat integration is phase-2 scope; do not let the accounts flow depend on it.**

---

## 7. Governance red flags (decisions, never silent mappings)

- **G1 avatarUrl** — a LinkedIn headshot is a new personal-data category (no use_class, no identity-binding class, no DSAR path). Options: initials-only (component already falls back) or a governed avatar-acquisition path.
- **G2 socials beyond LinkedIn** — absent repo-wide; WhatsApp is a personal delivery channel needing its own authorization; phone can never become verified identity.
- **G3 email address display** — backend keeps the value out of generic surfaces everywhere; showing capability (`available`) is defensible, showing the address is a policy change.
- **G4 evidence URLs** — C7's no-URL doctrine + unshipped redemption route + the `[B2×presign/frontend]` cross-tenant serving backlog item. Doctrine decision.
- **G5 fail-closed display governance** — `display_requires_strong_contact_binding=True` by default; unclassified contact claims never display; a weakly-bound contact serves `title=null` + `availability=RESTRICTED`. The frontend needs a redaction vocabulary or its parsers crash (this is a *crash*, not cosmetics).
- **G6 sensitive facets** (`contact.facet.causes` is SENSITIVE) must never be laundered into any synthesized prose; **G7** signal counts must count display-eligible statements only.

## 7b. Latent defects found during the study (backend-side, independent of integration)

- **L1** — `account.value_narrative` is registered to route to `VALUE_NARRATIVE`, which is absent from `ACCOUNT_SECTION_ORDER`; the composer raises → HTTP 404s **the entire account research view** the moment the first such claim is written (M12.1). One-line fix + regression test; needs section-species owner sign-off. No test covers `section_not_allowed_for_subject`.
- **L2** — `entity_research_job` has **no index on `subject_entity_id`**; any per-account status read is a seq scan.
- **L3** — the account fleet projection SQL omits `unresolved_field_keys` + `committee_status` — the two columns that define "fully enriched".
- **L4** — `suspend_failure`'s out-of-band `running→queued` UPDATE writes **no `entity_research_job_event` row** (transition log has a hole).
- **L5** — `account_run` never advances past `PENDING` on the M8D path → `GET /project_runs/{id}/accounts/{id}/progress` misleads (known family: R11 bridge).
- **L6** — `agent_turns_for_project` has no LIMIT/cursor.
- **L7** — the frontend contract prose (`accounts.md:186-191`) claims `avatarUrl` "is supplied by the backend or enrichment provider" — nothing supplies it; amend when G1 lands.

---

## 8. Decision register (for founder sign-off — none ratified)

**Architecture**
- **D-1. The screen-shaped read layer (BFF).** Proposal: a new, flag-gated "frontend read API" at the API composition root — one endpoint per screen need, workspace-scoped, single-call (collapsing C7's two-hop resolve server-side), speaking semantic values (enums/numbers/ISO timestamps/opaque ids, no display strings), built on: `account_entity` workspace scan + `current_values` (`claimstore/merge.py:418` — the right batch primitive) for the list; the C7 view + owner-ref resolver for detail; `ContactEligibilityResolver.resolve_account` for contacts; M8D job aggregation for status. Mechanism surfaces stay untouched.
- **D-2. The workspace-global scope rule.** The list is workspace-scoped, but scores/tier/committee are run-pinned. Need a representative-run rule (proposal: latest `project_run` per `(account, product)` by `created_at`; surface ambiguity rather than guessing) and a decision on whether the accounts URL gains project context (the contacts screen almost certainly needs it — committee is per-run).
- **D-3. Account↔project membership.** No junction table exists. Options: derive from execution+directive paths (leaves discovered-only accounts projectless) or add a real membership table. Affects `projects[]`, `primaryProjectId`, `projectId` filter.

**Frontend contract amendments (Band-3 → out of the wire; absence vocabulary in)**
- **D-4.** Nullable/optional everywhere the backend can be correctly empty + a per-field `availability`/`reasonCodes` redaction vocabulary (mirrors `ResearchItemState`; genuine capability gain — "not researched" vs "researched, not found"). Required before any HTTP adapter flips — current schemas crash.
- **D-5.** Display strings leave the wire: `timeLabel`/`dateLabel`/`editedLabel`/`sizeLabel`/`revenueLabel`/`locationsLabel` → ISO timestamps + semantic values, frontend formats. `personaTone` stays frontend-side.
- **D-6.** Enum reconciliation: `researchStatus` widens to the honest set (± `needs_review`, `suspended`, `not_launchable` — exact set to ratify); `emailStatus` widens (≥ `available|lookup|pending|unavailable`); persona adopts the 4 backend personas (+ optional `contact.class` chip); `overallFit` → decide two-value tier badge vs a versioned-policy 3-band score cut (never a hardcoded adapter constant); `activity.kind` widens to backend event kinds with a projection-layer label map.
- **D-7.** Drop-or-respec the pure no-datas: `referralFit`/`directAccessFit`/`recallFit` (or spec as new rubric dimensions — note backend has `intent` unused by the frontend), `locationCount`, `xUrl` requiredness, non-LinkedIn `socials`, `influence` (or define as a recorded derivation over `role_confidence`), `researchIsRefreshing` (or add real schema), `logoPath` (cheapest real fix: a small `core.company_logo_url` field + materializer; Exa already returns it).

**Policy (Band-1 — founder-only)**
- **D-8.** G1 avatar, G2 socials, G3 email-address display, G4 evidence-URL doctrine (recommended v1: non-link evidence chips `{provider_label, dateLabel}`; clickable sources wait for a redemption route + artifact-scope policy).
- **D-9.** Launch authority: Option A (HTTP confirmation ritual) vs Option B (through Head-of-ABM chat) — §5.3. Also which `fitCriteria` source is canonical (persist scoring `Contribution` vs adopt `DiscoveryCriterionReview`) — it decides whether explainability is a scoring-engine change or a new synthesis.
- **D-10.** Prose fields (`summaryParagraphs`, contact `overviewParagraphs`): defer, or scope as explicit new synthesis work (M12-class), never fabricated in an adapter.

**Backend fixes to schedule regardless of the above** (small, independent): L1 section-order fix (+ regression test), L2 index, L3 projection columns, L4 event-row, CORS middleware (or same-origin proxy via Next), error envelope, actor/action_ref seam design.

**Sequencing proposal:** slice 1 = read-only accounts list + account detail + contacts list + contact profile through the D-1 read layer (fixtures stay for everything undecided); slice 2 = research status live; slice 3 = kickoff per D-9; chat = phase-2. Each slice flips only its own repository adapter.

---

*Once decisions are ratified, each resolution is recorded into `apps/frontend/docs/api-contracts/accounts.md` (and `projects.md` where applicable) per the branch charter, and this doc gets a ratification log appended.*

---

## 9. Ratification log

- **2026-08-08 — D-9 RESOLVED (founder): Option B — kickoff through the platform deepagent.** Research launch on a project's target accounts is a deepagent tool call inside the project conversation, never a bare REST verb; the §5.3 Option-A confirmation-token ritual is rejected. Consequence, stated by the founder in the same ruling: the **production chat surface (S6) enters MVP scope** — it is no longer phase-2. The doctrine chain stays intact (confirmed directive + estimate + human confirming turn supplies the ambient `action_ref`). Charter to follow (FI-3 lane D).
- **2026-08-08 — D-10 RESOLVED (founder): empty-state until deep research completes, then real synthesis.** `summaryParagraphs` / contact `overviewParagraphs` render an honest empty state (per D-4 absence vocabulary) while the entity's deep research is incomplete; on completion, a genuine synthesis step composes prose **claims** from the completed research's claims (reusing M12 narrative machinery where it fits). Never fabricated in an adapter. Scoped concretely in `docs/specs/FI-lane-E-on-completion-synthesis.md` (Lane E charter).
- **2026-08-08 — MVP lifecycle ruling (founder): the M8D R11 DEEP-phase bridge is a fast-follow, not MVP-critical.** MVP research must *run and accumulate claims* (status: in-progress/enriched); reaching VERIFICATION/HANDOFF through the composed phase machine is not required for the accounts-flow MVP. §5.4's constraint stands: post-TIER_CHECKPOINT phases render as not-yet-composed.
- **2026-08-08 — D-4, D-5, D-6, D-7 RESOLVED (founder).** D-4: nullable/optional real-world fields + the honest availability/redaction vocabulary; no fabricated placeholders. D-5: backend sends semantic values; frontend owns all display formatting. D-6: the frontend adopts the backend vocabularies as-built, **including `not_launchable` now** (pre-ratified ahead of Lane D so the schema is not widened twice); `overallFit` is NOT invented. D-7: fixture-only fields are dropped for MVP — with the founder's clarification that they were **placeholders for industry-pack custom fields**: when an account's industry carries an associated pack, that pack's custom fields (already served dynamically by the slice-1 detail's registry-driven `neutralFacts`/sections) render dynamically on the frontend; the hardcoded fixture fields themselves are not preserved. Companion operational rulings: `signals` is presented as a count of **signal types** (per display-eligible field, MVP unit kept); CORS = same-origin proxy in production, exact localhost origin in development, wildcard never (already structurally refused). Plan-owner addendum (least-invasive resolution of the open Task-6 blocker, D-1-consistent): the accounts list's membership rows gain the project `name` via a read-layer join.
- **2026-08-08 — D-2 and D-3 RESOLVED by `docs/specs/FI-2-workspace-account-layer.md`** (founder-ratified design, verified by two follow-up code studies). The founder clarified that §1-S1's "structural mismatch" framing was wrong about intent: the frontend's workspace-global `/accounts` **is** the product model. FI-2 defines the two-lens scope rule (global lens = union of all projects' research, attributed; project lens = that project's research only), a real `project_account` membership table (D-3), a `run_lineage` claim→project join spine, a `research_scope` (project_neutral/project_relative) field attribute, TTL-gated no-respend on neutral fields, and project-scoped supersede predicates. D-2's "representative-run rule" dissolves — the global list serves per-project attributed scores instead of one guessed number. D-1's read layer is refined (not replaced) by FI-2 §7; D-4…D-10 remain open.
