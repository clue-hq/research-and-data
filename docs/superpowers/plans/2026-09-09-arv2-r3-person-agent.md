# ARV2 R3 — committee step and person agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One person agent per confirmed committee member (up to `committee_cap`, or launched on demand for any contact), writing governed `contact.*` / `contact.facet.*` claims that the live contact and insights pages already read, with the committee step (web-confirm → AI Ark lookup → email export → contact entity) in between, a coded compliance pass after structuring, and the answer-key recall extended to the ten people.

**Architecture:** The **same** ARV2 runtime as the account agent, pointed at a person subject. No new tables: `arv2_research_job` gains `subject_type` / `subject_entity_id` / `profile_sha256` and one job row per person rides under the account's run (or a run of its own when launched on demand). The driver composes an account job or a person job from the row's `subject_type`, under the one fleet kind `arv2_account_research`. The person agent has its own sha-pinned catalog folder `entity-research/arv2-person/v1` written verbatim from the approved substance, a person toolbelt (a subset of the account tools plus `lookup_person` and `unique_insight`), and a compliance pass in code at the one write choke point. The committee read surfaces are re-pointed at ARV2's own rows (founder ruling 2026-09-09). Nothing in the frontend changes.

**Tech Stack:** Python 3.12, pydantic v2, SQLAlchemy async + Alembic, LangChain `create_agent` + `StructuredTool`, pytest (offline + DB-gated suites), the ARV2 lane under `platform/api/clue_api/arv2/`, the read surface under `platform/api/clue_api/frontend_read/`, catalog files under `platform/agents/catalog/entity-research/`.

**Spec:** `docs/superpowers/plans/2026-09-09-arv2-r3-person-agent-substance.md` (rev 2, **approved 2026-09-09**; §7 carries every ruling). Master plan row R3 in `docs/specs/ARV2-MASTER-PLAN.md` §9 Track R. Standing rulings in `_memory/2026-09-08-arv2-r2-account-agent.md` and the memory notes `arv2-schema-is-the-only-truth`, `agent-no-preemptive-caps-full-mode`, `skills-prompts-clear-not-condensed`.

## Global Constraints

- **ARV2 schema is the only truth** (founder, 2026-09-09): every read this plan touches stands on ARV2 rows or the claim store; never write to or read from `entity_research_*` / `account_run.references_index` from the new lane; no bridge rows. Legacy tests that pin a legacy committee source are updated or retired with a dated one-line reason in the test file, never deleted silently.
- **Skill text names only what the agent can see.** The five person catalog files are written verbatim from the substance document's skill sections; the "Provenance, for the founder" notes are never copied into a catalog file. Plain language, one idea per sentence (`skills-prompts-clear-not-condensed`).
- **Stop policy = the account agent's** (founder 2026-09-08): `CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS` / `_MAX_TOOL_CALLS_PER_ROUND` / `_MAX_RUNTIME_S`, full mode only, no total-call or zero-yield caps. Person jobs read the same three settings.
- **Failure law** (Appendix A): tools never raise into the graph; every failure path is a `RefusalError` with a code the person `manual.md` names, or a returned result.
- **Nothing decides meaning the field does not declare:** mappers read the registry's `value_schema` and `validation.use_class_hint`; no name→code tables; no guessed values. A vacant seat creates no contact and no job.
- **Env parity:** every new setting appears in `libs/clue-config/clue_config/settings.py` **and** `.env.example` in the same commit, with its default: `CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS=3`, `CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=false`, `ARV2_PERSON_AGENT_MODEL=x-ai/grok-4.6`, `ARV2_PERSON_AGENT_MODEL_EFFORT=` (in the consolidated agent-model block). The local `.env` is kept at parity (the controller does this, not an implementer).
- **Migrations:** hash ids via `uv run alembic revision -m "<slug>"`, `down_revision` = current head `0622104be021`; reversible; `alembic heads` single; smoke up→down→up on a **separate** throwaway DB (`clue_san-salvador_smoke`), never the lane DB.
- **Offline suites only, never with real keys sourced:** `uv run pytest tests/arv2 --ignore-glob='*_live.py' -p no:cacheprovider -q`. DB suites on the lane's throwaway DB only (`set -a; source .env; set +a` first; they skip without it). Never `make check` with keys. The only live spend is Task 10 (founder-triggered).
- **No `git stash`** (shared stack); never push; no AI attribution; commit per task with the message the task gives.
- **Reuse existing helpers; never duplicate:** `_draft`, `_without_nones`, `coerce_scalar`, `write_each`, `RefusalError`, `refusal_json`, `FieldCatalog`/`FieldSpec`/`schema_hint`, `MediaBudget`, test doubles in `tests/arv2/test_account_research_tools.py` (`_runtime`, `_call`, `FakeClients`, `FakeWriter`, `CATALOG`, `SCOPE`) and `tests/arv2/test_account_research_driver.py`.
- The sha-pinned account `profile.md` is never edited. The person `profile.md` becomes the second pin.

## File structure (decided)

| Path | Responsibility |
| --- | --- |
| `alembic/versions/<hash>_arv2_r3_person_jobs.py` | `subject_type`, `subject_entity_id`, `profile_sha256` on `arv2_research_job`; the per-subject uniqueness. |
| `platform/api/clue_api/arv2/account_research_store.py` | `JobRow` + `create_job` carry the three new columns; `list_jobs` unchanged in shape. |
| `platform/api/clue_api/arv2/account_research_catalog.py` | Generic catalog root (`arv2_catalog_root(agent, version)`), `load_person_resources`, `arv2_person_profile_sha256`, `PersonContext`, `build_person_system_prompt`. |
| `platform/agents/catalog/entity-research/arv2-person/v1/{profile,prompt,dossier,audit,manual}.md` | The person agent's files, verbatim from the substance. |
| `platform/api/clue_api/arv2/account_research_claims.py` | `JobScope` grows the person subject; `_draft` stamps the subject's entity, mode, binding and use class; `ai_ark_person_claims`, `email_export_claim`, `committee_member_claims`; catalog carries `use_class_hint`. |
| `platform/api/clue_api/arv2/person_compliance.py` (new) | The coded compliance pass: `apply_person_floor(drafts, *, purge_unevidenced) -> (drafts, log)`. |
| `platform/api/clue_api/arv2/account_research_tools.py` | `lookup_person`, `unique_insight`, person branch of `structure_material`, the media item cap, person `finalize_research`, `build_person_tools`. |
| `platform/api/clue_api/arv2/structuring_client.py` | `UNIQUE_INSIGHT_MODE` prompt + row cap; `use_class_hint` on `FieldSpec`. |
| `platform/api/clue_api/arv2/account_research_driver.py` | `_compose` dispatches on `subject_type`; `_compose_person`; the committee step in `_settle` for account jobs (`committee_step.py`, new); person receipt. |
| `platform/api/clue_api/arv2/committee_step.py` (new) | Confirmed candidates → contact entities + persona/role/title claims → person jobs, enqueued after commit. |
| `platform/api/clue_api/arv2/account_research_launch.py` | `Arv2PersonLaunchRequest`, `launch_arv2_person_research`, toolbelt tool `launch_arv2_person_research@1` (ungranted). |
| `scripts/launch_arv2_person_research.py` (new) | CLI: `--contacts <linkedin urls or contact ids>` under a project. |
| `platform/api/clue_api/arv2/display/gather.py`, `platform/api/clue_api/contact_eligibility.py` | Committee membership from ARV2 rows (`Arv2CommitteeSource`), first in the chain; the coverage SQL removed from `committee_members`. |
| `platform/api/clue_api/arv2/answer_key_recall.py`, `scripts/arv2_answer_key_recall.py` | `people_keys`, per-person grading, `--people`. |
| `libs/clue-config/clue_config/settings.py`, `.env.example` | The three new settings. |
| `tests/arv2/…`, `tests/api/…` | Per task below. |

---

### Task 1: Job rows carry a subject; settings and env for R3

**Files:**
- Create: `alembic/versions/<hash>_arv2_r3_person_jobs.py` (mint with `uv run alembic revision -m "arv2 r3 person jobs"`; `down_revision = "0622104be021"`).
- Modify: `platform/api/clue_api/arv2/account_research_store.py` — `JobRow` (line 137), `create_job` (line 220), `read_job`/`list_jobs`/`begin_job` row mapping.
- Modify: `platform/api/clue_api/arv2/account_research_launch.py` — `create_job(...)` call at ~line 300 passes `subject_type="account"`, `profile_sha256=profile_sha256`.
- Modify: `libs/clue-config/clue_config/settings.py` (after `arv2_account_media_max_enclosure_mb`, line 351) and `.env.example` (after line 159 and in the agent-model block at 259–260).
- Test: `tests/arv2/test_account_research_store_db.py`, `tests/arv2/test_account_research_launch_db.py`, `tests/db/test_env_parity*.py` (existing parity test must stay green).

**Interfaces:**
- Produces: columns `arv2_research_job.subject_type text NOT NULL DEFAULT 'account' CHECK IN ('account','person')`, `subject_entity_id uuid NULL` (the contact for a person job), `profile_sha256 text NULL` (the pinned profile of *this* job); CHECK `arv2_research_job_subject` = `(subject_type = 'person') = (subject_entity_id IS NOT NULL)`; the old `arv2_research_job_once UNIQUE (run_id, account_entity_id)` is **dropped** and replaced by a unique expression index `arv2_research_job_subject_once ON (run_id, subject_type, COALESCE(subject_entity_id, account_entity_id))`.
- Produces: `JobRow.subject_type: Literal["account","person"]`, `JobRow.subject_entity_id: UUID | None`, `JobRow.profile_sha256: str | None`; `create_job(conn, *, job_id, run_id, workspace_id, account_entity_id, subject_type="account", subject_entity_id=None, profile_sha256=None) -> bool`.
- Produces settings: `arv2_person_media_max_items: int = Field(default=3, ge=0)`, `unevidenced_row_purge_enabled: bool = False`; env `ARV2_PERSON_AGENT_MODEL` / `_EFFORT` read by the driver (Task 8) exactly as `ARV2_ACCOUNT_AGENT_MODEL` is.

- [ ] **Step 1: Write the failing DB tests** in `tests/arv2/test_account_research_store_db.py` (reuse `_seed`): a person job inserts with `subject_type="person"`, `subject_entity_id=<uuid>`, `profile_sha256="a"*64` and reads back with the three fields; two person jobs under one run for the same account both insert; a second **account** job for the same run+account is refused (`create_job` returns `False`, as today); a person row with `subject_entity_id=None` raises `IntegrityError`.
- [ ] **Step 2: Run them to verify they fail** (`uv run pytest tests/arv2/test_account_research_store_db.py -k subject -q -p no:cacheprovider`, with `.env` sourced): FAIL — unknown column / TypeError.
- [ ] **Step 3: Write the migration.** `upgrade()`: `op.add_column` ×3 with server defaults; `op.execute("ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_research_job_subject_type CHECK (subject_type IN ('account','person'))")`; the subject CHECK; `op.drop_constraint("arv2_research_job_once", "arv2_research_job", type_="unique")`; `op.execute("CREATE UNIQUE INDEX arv2_research_job_subject_once ON arv2_research_job (run_id, subject_type, COALESCE(subject_entity_id, account_entity_id))")`. `downgrade()`: refuse while any `subject_type='person'` row exists (`RAISE EXCEPTION`, the R2 precedent in `a3602967bb73`), then drop index, re-create the old UNIQUE, drop the CHECKs and columns. Docstring carries the conventions block every migration carries.
- [ ] **Step 4: Store + launch.** Extend `JobRow`, `_row_to_job` mapping, `create_job` (INSERT the three columns), and pass `subject_type="account", profile_sha256=profile_sha256` from `launch_arv2_account_research` (the run already pins it; the job now carries its own copy).
- [ ] **Step 5: Settings + env.** Add the two settings with docstrings naming their env keys; add to `.env.example`:
  ```
  # R3: media items one person job may read (podcast episodes / YouTube appearances); 0 disables media.
  CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS=3
  # R3 compliance pass: purge a person claim that has neither a quote nor a URL (default: keep it, marked unevidenced).
  CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=false
  ```
  and in the agent-model block: `ARV2_PERSON_AGENT_MODEL=x-ai/grok-4.6` / `ARV2_PERSON_AGENT_MODEL_EFFORT=`.
- [ ] **Step 6: Run** `uv run alembic upgrade head` on the lane DB; the store and launch DB suites; the env-parity tests (`uv run pytest tests/db -k parity -q -p no:cacheprovider`); smoke up→down→up on `clue_san-salvador_smoke`. Expected: all green, `alembic heads` = one.
- [ ] **Step 7: Commit** — `feat(arv2 r3): job rows carry a subject (account|person), the subject's contact, and the job's own profile pin; person media cap and unevidenced-purge settings`.

---

### Task 2: The person catalog — five files written verbatim from the substance; generic catalog loading

**Files:**
- Create: `platform/agents/catalog/entity-research/arv2-person/v1/profile.md`, `prompt.md`, `dossier.md`, `audit.md`, `manual.md`.
- Modify: `platform/api/clue_api/arv2/account_research_catalog.py` — generalise the root (line 27), add `ARV2_PERSON_CATALOG_VERSION = "v1"`, `ARV2_PERSON_PROFILE_REF = "agent-profile:arv2-person:v1"`, `arv2_person_catalog_root()`, `arv2_person_profile_sha256()`, `load_person_resources()` (same `AccountResourceBundle` shape — rename the dataclass to `ResourceBundle` with a back-compatible alias), `PersonContext`, `build_person_system_prompt`.
- Test: `tests/arv2/test_account_research_catalog.py` (person variants of the five existing tests).

**Interfaces:**
- Produces: `PersonContext(person_name, person_title, person_linkedin_url, employment_history: tuple[str,...], account_name, account_domain, contact_id, account_id, workspace_id, today, icp_markdown, persona_markdown, catalog_menu, already_established, directive_text, media_max_items, stop_policy)` with `.block()` rendering a JSON head (`person`, `account`, `lock.employment_history`, `media_max_items`, `stop_policy`) followed by `## context/icp.md`, `## context/persona.md`, `## context/catalog.md`, `## context/already-established.md`.
- Produces: `build_person_system_prompt(bundle, context) -> str` stacking `<profile>`, prompt body, `<skill>` ×3, `<person_research_context>`.

- [ ] **Step 1: Write the five files.** Content comes **only** from the substance document (rev 2), skill sections, in this mapping — copy the sentences, do not summarise:
  - `profile.md`: the account profile's shape (`role: arv2-person-research`, `framework`, `contract: arv2-r3-person-research-v1`, identity `agent-profile:arv2-person:v1`, model env `ARV2_PERSON_AGENT_MODEL`, the same stop-policy table naming the `CLUE_ARV2_ACCOUNT_*` keys, effort full only, spend recorded never enforced, media cap `CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS`), plus one paragraph stating the subject is one person confirmed by the committee step, locked by employment history.
  - `prompt.md`: the account constitution's ten rules re-read for a person, with the seven deltas of substance §2 inserted as their own numbered rules (target lock by employment history; never attribute a colleague's or company's words; the person's own words first; the sensitivity floor; allowed background with the origin tag; family milestones only self-announced, new-job/relocation may be hooks, wedding/baby never; no "likely/probably").
  - `dossier.md`: §3.1 (the ladder, seven rungs, **without** the provenance paragraph), §3.2 (the ten-section charter, **without** the provenance paragraph), §3.3 (structuring and the narrow follow-up, stated as the tool behaves: `unique_insight` writes into the existing facet at priority 1; openers name their hook and the hook its quote).
  - `audit.md`: the account audit skill's text plus §4's three deltas (speaker attribution, `second_hand_from_company`, the lock audit).
  - `manual.md`: the account manual's refusal table with the rows of §6 added (`subject_lock_failed`, `email_export_empty`, `insight_not_found`, `media_cap_reached`, `person_not_admitted`), the tool table for the person toolbelt (`read_person_state`, `fetch_page`, `search_web`, `lookup_person`, `read_media_feeds`, `research_deep`, `structure_material`, `unique_insight`, `write_claims`, `verify_links`, `finalize_research`), and the reactions table used by `REACTIONS` (Task 4 adds the codes there; the manual↔`REACTIONS` guard test from the R2 follow-ups must stay green — extend it to the person manual).
- [ ] **Step 2: Failing tests** (mirror the five account tests at `tests/arv2/test_account_research_catalog.py:22–75` for the person folder): five files exist and the profile sha is the file digest; the launch pin and the bundle agree; bundle carries one prompt and three skills; the person manual names every refusal code the person driver can emit (the set from Task 4's `PERSON_REFUSAL_CODES`); the system prompt stacks profile, prompt, skills and the `<person_research_context>` block whose head names `lock.employment_history`.
- [ ] **Step 3: Implement** the catalog module changes (root generalised as `arv2_catalog_root(agent: Literal["arv2-account","arv2-person"], version)`; the account functions become thin wrappers; `PersonContext.block()` mirrors `AccountContext.block()`).
- [ ] **Step 4: Run** `uv run pytest tests/arv2/test_account_research_catalog.py -q -p no:cacheprovider`; ruff. Expected green; the account tests unchanged.
- [ ] **Step 5: Commit** — `feat(arv2 r3): the arv2-person catalog (profile, constitution, dossier, audit, manual) written from the approved substance; catalog loading generalised to two agents`.

---

### Task 3: A person subject in the claim path — scope, drafts, mappers, catalog hints

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_claims.py` — `JobScope` (line 102), `_draft` (line 167), new mappers; `platform/api/clue_api/arv2/structuring_client.py` — `FieldSpec` gains `use_class_hint: str | None = None` (line 135), `UNIQUE_INSIGHT_MODE`; `platform/api/clue_api/arv2/account_research_store.py` — `read_person_catalog(conn)` reading `field_key, description, value_schema, validation` for `contact.%` + `core.work_email` + the account fields the contact recipes read (`account.open_requisitions`, `account.abm_program_maturity`, `account.hiring_velocity`, `account.gtm_tooling_stack`, `account.operational_pain`, `account.claimed_outcomes_metrics`, `account.named_customers`).
- Test: `tests/arv2/test_account_research_claims.py`, `tests/arv2/test_structuring_client.py`, `tests/arv2/test_account_research_store_db.py`.

**Interfaces:**
- `JobScope` gains: `subject_kind: Literal["account","person"] = "account"`, `contact_id: EntityId | None = None`, `person_name: str = ""`, `person_title: str = ""`, `person_linkedin_url: str = ""`, `employment_history: tuple[str, ...] = ()`.
- `_draft(...)` stamps, when `scope.subject_kind == "person"`: `entity_id=scope.contact_id`, `entity_type=EntityType.CONTACT`, `research_mode=ResearchMode.CONTACT_PROFILING`, `identity_binding=IdentityBinding.STRONG` (the lock was confirmed on a non-provider URL before the job existed), `use_class` from the field's `use_class_hint` (`UseClass(hint)`), else `UseClass.PROFESSIONAL_PUBLIC` for `contact.*` non-facet fields. Account-subject behaviour is byte-for-byte unchanged (existing tests prove it).
- New pure mappers: `ai_ark_person_claims(person: AiArkPerson, scope) -> list[ClaimDraft]` (title → `contact.current_title`, headline → `contact.headline`, location → `contact.current_location {raw, country}` via `_without_nones`, linkedin → `contact.linkedin_url`, `network.followers_count` → `contact.network_statistics {followers}`, badges → `contact.member_badges`, `experience[]` → `contact.facet.career_history [{org, role, start, end}]`; each `json_path` marker; `source_key="ai_ark:person"`, method API); `email_export_claim(export: AiArkEmailExport, scope) -> ClaimDraft | None` (`core.work_email`, markers `verdict`, `provider_verified`, `source_key="ai_ark:email_export"`; `None` when not found); `committee_member_claims(candidate, *, scope, contact_id) -> list[ClaimDraft]` (`contact.persona` enum, `contact.role_on_committee {role, rationale, influence?}`, `contact.current_title`; `source_url=confirmed_by`, `evidence_span` the candidate's; binding STRONG).
- `UNIQUE_INSIGHT_MODE = "unique_insight"` in the structuring client: its own user prompt (the one question, at most **one** row, `priority: 1`, the row's `field_key` must be one of the person facets in the catalog, verbatim quote + URL required) and `system_prompt_for("unique_insight", "person")`; `StructuredOutput` rows in this mode carry marker `unique_insight: True` when written (Task 4).

- [ ] **Step 1: Failing tests.** Claims: a person-scoped `_draft` stamps CONTACT / CONTACT_PROFILING / STRONG / the hint's use class; an account-scoped draft is unchanged; `ai_ark_person_claims` over a fixture record (build it from the shape `AiArkPerson.raw` carries — read `tests/arv2/test_ai_ark_client.py` for the recorded people fixture) yields the listed fields with `json_path`; `email_export_claim` returns `None` on `found=False`; `committee_member_claims` writes persona/role/title with STRONG binding and the confirmed_by URL. Structuring: `system_prompt_for("unique_insight","person")` and the user prompt contain "one row" and "priority 1"; the mode caps rows at 1 (mirror `INTENT_SWEEP_MAX_ROWS` handling). Store DB: `read_person_catalog` returns `use_class_hint` for `contact.facet.hobby` = `personal-public-non-sensitive` and includes `core.work_email` and `contact.facet.alma_mater`.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.** **Step 4: Run** the three suites + ruff. **Step 5: Commit** — `feat(arv2 r3): a person subject in the claim path — contact-scoped drafts with strong binding and the field's use class; AI Ark person and email-export mappers; committee member claims; unique-insight structuring mode; person catalog with use-class hints`.

---

### Task 4: The person toolbelt — `lookup_person`, `unique_insight`, person structuring, the media cap, person finalize

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_tools.py`, `platform/api/clue_api/arv2/account_research_refusals.py` (REACTIONS + `PERSON_REFUSAL_CODES`).
- Test: `tests/arv2/test_account_research_tools.py` (a `PERSON_SCOPE` beside `SCOPE`; `FakeClients.ai_ark` gains `export_email`).

**Interfaces:**
- `build_person_tools(runtime) -> list[StructuredTool]` in the manual's order: `read_person_state`, `fetch_page`, `search_web`, `lookup_person`, `read_media_feeds`, `research_deep`, `structure_material`, `unique_insight`, `write_claims`, `verify_links`, `finalize_research`. Shared bodies are the account ones; only the five below differ.
- `lookup_person(linkedin_url)`: `people_by_name([scope.person_name], scope.account_domain, size=3)` → the record whose `linkedin_url` folds equal to the scope's (else refuse `subject_lock_failed` naming the candidates' companies); **employer exact-match**: `current_company_domain` must equal `scope.account_domain` (else `subject_lock_failed`); then `export_email(linkedin_url)`; writes `ai_ark_person_claims` + `email_export_claim` via `write_each`; returns the record summary, the email verdict, `write_failures`; refuses `email_export_empty` **only as a result field**, never as a refusal (the member is still researched) — the manual row says so.
- `structure_material(subject_kind="person")`: admitted when `scope.subject_kind == "person"` (refuse `person_not_admitted` when the job is an account job), calling `structure_person(PersonSubject(name, company, linkedin_url), bundle, catalog, mode, sources, notes)`; drafts through `structured_claims` with the person scope; the compliance pass (Task 5) runs inside `write_each` for person scopes.
- `unique_insight()`: one `structure_person(..., mode=UNIQUE_INSIGHT_MODE)` over the job's retrieved sources (the runtime keeps the source blocks the job has structured so far — add `ToolRuntime.person_sources: list[SourceBlock]` appended by `structure_material`); ≤1 draft, `signal_priority=1`, marker `unique_insight: True`; no row → refuse `insight_not_found` with the channels checked (the source kinds seen).
- `read_media_feeds` for a person scope: count this job's `account.media_layer_index`-equivalent for people — write the index claim on the **contact** (`contact.facet.public_appearances` for a YouTube/podcast appearance, one claim per item) and refuse `media_cap_reached` when the job already holds `settings.arv2_person_media_max_items` such claims; `0` refuses immediately.
- `finalize_research` (person): args `summary`, `openers: list[{text, hook, quote, url}]` (3), `hooks: list[str]`, `not_found: list[str]`, `same_name_log: list[{name_or_url, why_excluded}]`, `gaps`; writes `contact.facet.openers` (the three opener texts; an opener whose `quote` is empty is dropped and reported), `contact.facet.hooks`, one `contact.facet.excluded_lookalike` claim per log row; receipt = `{reason, summary, openers_written, hooks_written, not_found, same_name_log, insight_found: bool, compliance_log}`.
- `REACTIONS` gains the five person codes with the manual's exact cell text; `PERSON_REFUSAL_CODES` frozenset exported for the catalog test.

- [ ] **Step 1: Failing tests** for each tool above through `_call` on a person runtime: lookup writes title/headline/email claims and refuses on employer mismatch; structure_material person path writes contact-scoped drafts and refuses `person_not_admitted` on an account scope; unique_insight writes exactly one P1 claim with the marker, refuses `insight_not_found` on an empty reply; media cap: third call with cap 2 refuses `media_cap_reached`, cap 0 refuses at once; finalize writes openers/hooks/excluded_lookalike and drops the quoteless opener; the twelve→eleven tool order matches `PERSON_TOOL_NAMES`; manual↔REACTIONS guard covers the person manual.
- [ ] **Step 2: Run → FAIL. Step 3: Implement. Step 4: Run** tools + catalog suites, ruff. **Step 5: Commit** — `feat(arv2 r3): the person toolbelt — lookup_person with the employer lock and email export, person structuring, unique_insight at priority 1, the per-person media cap, person finalize`.

---

### Task 5: The coded compliance pass

**Files:**
- Create: `platform/api/clue_api/arv2/person_compliance.py`.
- Modify: `platform/api/clue_api/arv2/account_research_tools.py` — `ToolRuntime.write_each` / `write` call `apply_person_floor` when `scope.subject_kind == "person"`; the log accumulates on the runtime (`runtime.compliance_log`) and lands in the receipt (Task 4).
- Test: `tests/arv2/test_person_compliance.py` (new).

**Interfaces:**
- `apply_person_floor(drafts: Sequence[ClaimDraft], *, purge_unevidenced: bool) -> tuple[list[ClaimDraft], list[dict[str, str]]]` — pure. Per draft, in order: (1) **personal contact details** — a value or quote matching a phone / personal-email / street-address pattern on any field other than `core.work_email` → draft dropped, log `dropped: personal_contact_detail`; (2) **minors** — sentences mentioning children/kids/son/daughter/baby by keyword list → the sentence removed from string values and from `evidence_span`; if the value becomes empty the draft is dropped; marker `redacted: minors`; (3) **sensitivity floor** — keyword lists per category (health, faith, politics, sexuality, family_tragedy, union, criminal) → the matching sentence redacted, marker `redacted: <category>`; a draft whose whole value matched is dropped; (4) **origin / faith biography** — marker `origin_biography: True`, `outreach_safe=False`, never dropped; (5) **wedding / baby milestones** — `outreach_safe=False` (baby also hits rule 2's redaction), marker `self_announced_milestone`; (6) **unevidenced** — no `evidence_span` **or** no `source_url` → marker `unevidenced: True`; dropped only when `purge_unevidenced`; (7) `hooks`/`openers` values that reference a draft marked origin or milestone-unsafe are dropped with log `dropped: unsafe_hook`. Every action is one log row `{action, field_key, rule, detail}`; nothing is silently dropped.
- Keyword lists are module constants, plain lists a founder can read and edit, with a one-line comment each.

- [ ] **Step 1: Failing tests** with hand-built drafts for each rule (a health sentence inside a two-sentence hobby value is redacted, the other sentence kept; a phone number in `self_summary` drops the draft; a first-person origin story is kept, unsafe, marked; a wedding post is kept unsafe; a claim with a quote but no URL is marked unevidenced and kept, and dropped when purging; an opener resting on the origin claim is dropped; an account-scoped runtime never runs the pass).
- [ ] **Step 2: Run → FAIL. Step 3: Implement. Step 4: Run** + ruff. **Step 5: Commit** — `feat(arv2 r3): the coded compliance pass — minors redaction, the sensitivity floor, origin as biography only, self-announced milestones unsafe, unevidenced marking with the purge flag; every action logged`.

---

### Task 6: The committee step and the person launch paths

**Files:**
- Create: `platform/api/clue_api/arv2/committee_step.py`.
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` — `_settle` for account jobs calls the step after `finish_job`; enqueue after commit (the R2 launch pattern via `enqueue_launched_jobs`).
- Modify: `platform/api/clue_api/arv2/account_research_launch.py` — `Arv2PersonLaunchRequest(workspace_id, project_id, contact_entity_ids, requested_by_user_id, directive_text="", project_run_id=None)`, `launch_arv2_person_research(conn, request, *, settings, storage, profile_sha256) -> Arv2LaunchReceipt` (a run of its own, `effort="full"`, `committee_cap=len(contacts)`, ICP/product pins resolved the same way as the account launch; one person job per contact; refuses `contact_not_found`, `contact_without_account`); toolbelt tool `launch_arv2_person_research@1` registered **ungranted** beside the two account tools (`agent_registry_wiring.py:238` pattern).
- Create: `scripts/launch_arv2_person_research.py` (`--workspace --project --contacts <comma-separated linkedin urls or contact ids> --directive`).
- Test: `tests/arv2/test_committee_step_db.py` (new), `tests/arv2/test_account_research_launch_db.py`, `tests/api/test_arv2_launch_tools.py`.

**Interfaces:**
- `async def run_committee_step(conn, *, job: JobRow, run: RunRow, candidates: Sequence[Mapping], writer, settings, person_profile_sha256) -> CommitteeStepResult(contacts_created, jobs: tuple[QueuedJob,...], skipped: tuple[{name, reason},...])`: for each candidate with a `name` and `confirmed_by` (vacant seats skipped with reason `vacant_seat`), up to `run.committee_cap`: `insert_contact_entity(conn, account_entity_id=job.account_entity_id, full_name=name, linkedin_url=linkedin_url)` (a duplicate strong key → `get_contact` by linkedin, reused), write `committee_member_claims` through the writer, `create_job(subject_type="person", subject_entity_id=contact_id, profile_sha256=person_profile_sha256, job_id=uuid5(_JOB_NS, f"{run_id}:{contact_id}"))`. Idempotent: a re-settled job finds its contacts and jobs already there.
- The driver enqueues `result.jobs` **after** the settle transaction commits (same `enqueue_launched_jobs(queue, receipt)` seam; the handler receives the `WorkQueue` from `fleet_main` — add the constructor parameter the way `DbArv2LaunchService` receives `queue=`).

- [ ] **Step 1: Failing DB tests**: the step creates two contacts and two person jobs for two confirmed candidates and skips a vacant seat and a third candidate past cap 2; re-running creates nothing new; person launch by contact id creates a run with one job per contact and refuses an unknown id; the toolbelt tool is registered and ungranted (mirror the existing two).
- [ ] **Step 2: Run → FAIL. Step 3: Implement. Step 4: Run** DB suites + `tests/api/test_arv2_launch_tools.py` + ruff. **Step 5: Commit** — `feat(arv2 r3): the committee step — confirmed candidates become contact entities with persona/role/title claims and one person job each, enqueued after commit; on-demand person launch by contact (service, CLI, ungranted toolbelt tool)`.

---

### Task 7: Committee membership from ARV2 rows

**Files:**
- Modify: `platform/api/clue_api/arv2/display/gather.py` — `committee_members` (line 303): remove `_COVERAGE_SQL` and the coverage branch; members = `_MEMBERS_WITH_CLAIMS_SQL` **restricted to contacts holding a live `contact.persona` claim**, ordered by persona rank (economic_buyer, champion, technical_evaluator, user, blocker — the read surface's existing `persona_influence` order) then name.
- Modify: `platform/api/clue_api/contact_eligibility.py` — new `Arv2CommitteeReferenceSource` (reads the account's contacts with live `contact.persona` + `contact.role_on_committee` claims from the claim store, returning `AccountClaimReferences` keyed per member with those two claim ids; returns `None` when the account has no such contact) placed **first** in `default_claim_reference_source()`.
- Test: `tests/arv2/display/…` (the D2 seed tests for `committee_members`), `tests/api/test_frontend_read_account_detail.py`, `tests/api/test_frontend_read_account_workspace.py` — coverage-based expectations updated or retired with a dated one-line reason.

- [ ] **Step 1: Failing tests**: a contact with persona+role claims appears in `committee_members` and in the contacts list with no coverage row present; a contact with claims but no persona claim does not; the eligibility chain answers from ARV2 claims first.
- [ ] **Step 2: Run → FAIL. Step 3: Implement. Step 4: Run** the display and frontend_read suites + ruff + `uv run lint-imports`. **Step 5: Commit** — `feat(arv2 r3): committee membership read from ARV2 rows — contacts with live persona and role claims — first in the eligibility chain; the coverage read leaves committee_members (founder ruling 2026-09-09)`.

---

### Task 8: The driver composes person jobs

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` — `handle` reads the job row first and dispatches `_compose` / `_compose_person`; `_compose_person` builds `JobScope(subject_kind="person", contact_id, person_name, person_title, person_linkedin_url, employment_history)` from `get_contact` + the contact's live claims (`contact.current_title`, `contact.linkedin_url`, `contact.facet.career_history` rendered as `"role @ org (start–end)"` lines) + the account; `PersonContext`; `build_person_tools`; the person profile pin (`job.profile_sha256` vs `arv2_person_profile_sha256()`); `already_established` = the account's block **plus** the contact's own live claims (same `format_established`); `media_max_items` from settings; the model id from `ARV2_PERSON_AGENT_MODEL` (falls back to the account model env when empty, logged).
- `_settle`: person receipt (`finalization_json` from the person finalize + `compliance_log` + `insight_found`); account jobs run the committee step (Task 6).
- Test: `tests/arv2/test_account_research_driver.py`, `tests/arv2/test_account_research_driver_db.py` (a person job composes; a profile pin mismatch fails `profile_pin_mismatch`; the person system prompt carries the lock).

- [ ] **Step 1: Failing tests. Step 2: Run → FAIL. Step 3: Implement. Step 4: Run** driver suites + the whole offline ARV2 suite + ruff + `lint-imports`. **Step 5: Commit** — `feat(arv2 r3): the driver composes person jobs — person scope and lock, person catalog pin, person toolbelt, account plus contact established block, person receipt; account jobs fan out the committee`.

---

### Task 9: Recall extended to the ten people

**Files:**
- Modify: `platform/api/clue_api/arv2/answer_key_recall.py` — `people_keys(conn, *, workspace_id) -> dict[EntityId, list[KeyClaim]]` from `PEOPLE_RUN_ID` claims with marker `answer_key == _PEOPLE_ANSWER_KEY` (export the constant), grouped by contact; `match_claims` unchanged; `RecallReport.insight_found: bool` = any run claim on the contact with marker `unique_insight`.
- Modify: `scripts/arv2_answer_key_recall.py` — `--people` grades every contact in the manifest that has run claims in `--run-id` (or in the run ids listed by `--run-ids`), writing `recall-<slug>.md` per person and adding them to `recall.json`.
- Test: `tests/arv2/test_answer_key_recall.py`, `tests/arv2/test_answer_key_recall_db.py`.

- [ ] **Step 1: Failing tests** (people keys grouped per contact from the loaded answer key; a report's `insight_found` reads the marker). **Step 2: Run → FAIL. Step 3: Implement. Step 4: Run** + ruff. **Step 5: Commit** — `feat(arv2 r3): answer-key recall graded per person over the ten people, insight presence from the unique_insight marker`.

---

### Task 10: Live acceptance on the answer-key people (founder-triggered)

**Prerequisites:** the founder's go; this worktree's fleet worker running (`set -a; source .env; set +a; uv run python -m clue_api.fleet_main`), `.env` at parity, lane DB at head, the answer key loaded (it is).

- [ ] **Step 1: Zafran through the account path.** `scripts/launch_arv2_account_research.py --workspace ws_arv2_answer_key --project prj_arv2_answer_key --accounts zafran.io --effort full --committee-cap 5 --directive "R3 acceptance"`. Expected: the account job completes, the committee step creates contacts for the confirmed members (Vari Kaur, Nick Fisher, Sanaz Yashar, Tom Anthony expected; Ben Seri if confirmed) and one person job each, enqueued; the person jobs complete.
- [ ] **Step 2: The other answer-key people on demand.** `scripts/launch_arv2_person_research.py --workspace ws_arv2_answer_key --project prj_arv2_answer_key --contacts <the manifest's Cogent, Harmonic and UPTIQ LinkedIn URLs> --directive "R3 acceptance"` (their accounts and contact entities exist from the D1 loader; their account block is whatever the store holds).
- [ ] **Step 3: Measure.** `scripts/arv2_answer_key_recall.py --people --run-ids <both> --out .context/arv2-r3-acceptance/recall`; per-job cost incl. model spend from the ledger; link audit by reason; compliance log counts; media items per person; `insight_found` per person. Walk `/accounts/zafran-security/contacts/nick-fisher` and the Zafran contacts list on the live frontend (`/browse`), compare with the D5 drift list's D20/D21.
- [ ] **Step 4: Record** `.context/arv2-r3-acceptance/acceptance.md` (what ran, what it cost, recall per person, what the pages show, defects found); memory; master plan R3 row → DONE with the evidence path. Stop this worktree's worker.
- [ ] **Step 5: Commit** — `arv2 r3: live acceptance on the answer-key people — evidence and measurements`.

---

### Task 11: Docs and the record

- [ ] `platform/api/clue_api/arv2/README.md` — R3 section (job subjects, the committee step, the person toolbelt, the compliance pass, the two launch paths, the ARV2 committee source); `docs/specs/ARV2-MASTER-PLAN.md` R3 row status; `_memory/2026-09-09-arv2-r3-person-agent.md` (progress, rulings, evidence paths). Commit — `docs(arv2 r3): README, master plan, memory`.

---

## Self-review

- **Spec coverage:** substance §0 (runtime, subject, job rows, tools, catalog, compliance, field list) → T1/T2/T3/T4/T5/T8; §1 committee step + on-demand launch → T6; §2 constitution deltas → T2 prompt.md; §3 ladder/charter/structuring → T2 dossier.md + T3/T4 (`UNIQUE_INSIGHT_MODE`, marker, P1, media cap); §4 audit deltas → T2 audit.md (+ `second_hand_from_company` reason in `verify_links`, T4); §5 compliance → T5; §6 manual → T2 + T4 REACTIONS; §7 rulings: (1) T5 rules 5/7, (2) T3/T4 marker + no new field, (3) cap default already 5 in `Arv2LaunchRequest`, (4) T1 setting + T4 cap, (5) no cap change, (6) `reports_to` — **gap**: no task writes `contact.reports_to`; ruled source = ATS reporting lines / own statements → add to T4 `finalize_research` person args `reports_to: {name, contact_id?} | None` written only when the agent cites a posting or the person's own words (evidence_span required) — **added to T4 above by this note; the implementer treats it as part of T4**. (7) T9. Frontend walk field list → T3 catalog + T7 read surface. "ARV2 only truth" → T7.
- **Placeholders:** none of the forbidden forms; where a brief says "mirror the existing test", it names the file and line.
- **Type consistency:** `JobRow.subject_type` (T1) is read by T6/T8; `PersonContext`/`build_person_system_prompt` (T2) consumed by T8; `JobScope` person fields (T3) consumed by T4/T8; `apply_person_floor` (T5) called from T4's `write_each`; `Arv2CommitteeReferenceSource` (T7) independent; `people_keys` (T9) consumed by the script.
