# Head-of-ABM Read Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Head of ABM can answer questions about a project's accounts, one account's research, and the latest discovery run from ARV2 rows — through three effect-free tools — instead of relying on what its own thread happened to launch.

**Architecture:** Three READ tools in `platform/api/clue_api/arv2/read_tools.py`, each a thin `Tool` over a service protocol whose DB implementation opens one transaction per call. `read_project_accounts` joins `project_account`, `account_entity` and `arv2_research_job`; `read_account_research` serves the account's live overview `display_block` sections or its live claims grouped by field; `read_discovery_run` serves the latest or a named `arv2_discovery_run` with its candidates. Skill v25 / profile v48 / recipe v26 grant them (two commits, as R4).

**Tech Stack:** Python 3.12, SQLAlchemy async, the `clue_toolbelt` `Tool` envelope, `clue_research.claimstore.claims_for_entities`, the ARV2 display blocks reader, pytest on the lane DB.

**Spec:** `docs/superpowers/specs/archive/2026-09-12-project-context-and-icp-authoring-design.md` §4.4 (ruling R8). Independent of plans 1–3 for code, but the skill version chain requires plan 3's v24 to exist first (this plan mints v25).

## Global Constraints

- `platform/api/clue_api/arv2/` import allowlist (see plan 2). `clue_research.claimstore` is allowed; `clue_api.frontend_read` is not — the accounts SQL is written here, not imported from `accounts_list.py`.
- Claim reads are scoped with `WorkspaceScope.for_workspace(workspace_id)`, never `claim.workspace_id = …` (documented at `frontend_read/accounts_list.py:24-31`).
- Every tool: `effect_class = READ`, `replay = ReplaySafety(policy=EFFECT_FREE, durable_identity=…)`, `pin_requirements = ("project",)`, typed `output_model`, `_not_composed` refusal when the service is `None`, absence is a typed `PreconditionFailed`, never an empty success that could be read as "nothing exists".
- Output is bounded: ≤ 200 accounts, ≤ 120 claims, ≤ 50 candidates; evidence spans clipped to 240 chars; ids are strings.
- Immutable catalog; two-commit grant; the R4 gate command; no `git push`; offline/DB suite rules as in the sibling plans.

---

## File structure

| File | Responsibility |
|---|---|
| `platform/api/clue_api/arv2/read_tools.py` | The three input/output models, the `Arv2ReadService` Protocol, `DbArv2ReadService`, the three `Tool` classes, `build_arv2_read_tools`. |
| `platform/api/clue_api/arv2/__init__.py` | Re-exports. |
| `toolbelt_wiring.py`, `agent_registry_wiring.py`, `fleet_main.py`, `projections_main.py` | Registration (`arv2_reads: Arv2ReadService | None = None`), authority rows, composition when `storage`/settings allow (the read service needs only a `conn_factory`; compose it always). |
| `platform/agents/catalog/skills/stage0-interview/v25/SKILL.md`, `profiles/head-of-abm/v48/profile.yaml`, `platform/execution/recipes/recipe0-stage0-v26.json` | The grant. |
| `tests/arv2/test_read_tools_db.py`, `tests/api/test_arv2_read_tools.py` | DB proofs and offline tool tests. |
| `apps/frontend/src/features/projects/model/chat-tool-presentation.ts` | Labels. |

---

### Task 1: `read_project_accounts@1`

**Interfaces:**

```python
class ReadProjectAccountsInput(ToolInput):
    project_id: str
    limit: int = Field(default=100, ge=1, le=200)

class ProjectAccountView(BaseModel, frozen=True):
    account_entity_id: str; name: str; domain: str | None
    research_status: str          # not_started | in_progress | needs_review | completed | suspended
    refreshing: bool; added_via: str; added_at: str   # ISO

class ReadProjectAccountsOutput(ToolOutput):
    project_id: str; total: int; accounts: tuple[dict[str, Any], ...]
```

SQL (one statement):

```sql
SELECT a.id, a.canonical_name, a.primary_domain, pa.added_via, pa.added_at,
       j.status AS research_status,
       EXISTS (SELECT 1 FROM arv2_research_job j2
               WHERE j2.workspace_id = :ws AND j2.account_entity_id = a.id AND j2.subject_type = 'account'
                 AND j2.status IN ('not_started', 'in_progress')
                 AND EXISTS (SELECT 1 FROM arv2_research_job j3
                             WHERE j3.workspace_id = :ws AND j3.account_entity_id = a.id
                               AND j3.subject_type = 'account' AND j3.status = 'completed'
                               AND j3.created_at < j2.created_at)) AS refreshing
FROM project_account pa
JOIN account_entity a ON a.id = pa.account_entity_id AND a.merged_into IS NULL
LEFT JOIN LATERAL (
  SELECT status FROM arv2_research_job j
  WHERE j.workspace_id = :ws AND j.account_entity_id = a.id AND j.subject_type = 'account'
  ORDER BY j.created_at DESC, j.job_id DESC LIMIT 1
) j ON TRUE
WHERE pa.workspace_id = :ws AND pa.project_id = :project
ORDER BY a.canonical_name, a.id
LIMIT :limit
```

`total` = `SELECT count(*) FROM project_account WHERE workspace_id = :ws AND project_id = :project`. `research_status` defaults to `"not_started"` when `j.status` is NULL. Refusal `project_not_found` when `get_project` (clue_spine) returns no row in this workspace.

`model_description`: "List the accounts in one project with each account's research status (not_started, in_progress, needs_review, completed, suspended) and how it joined the project. Read this before saying how many accounts there are, which are researched, or before proposing more discovery. Effect-free."

- [ ] **Step 1: Failing DB test** (`tests/arv2/test_read_tools_db.py`): two accounts in the project, one with a completed account job followed by a running one (`refreshing == True`), one with no job (`not_started`); a merged account excluded; another project's accounts excluded; `limit=1` returns one row with `total == 2`; a foreign project → `project_not_found`.
- [ ] **Step 2–4: implement the model, service method `list_project_accounts`, tool, tests green.**

### Task 2: `read_account_research@1`

**Interfaces:**

```python
class ReadAccountResearchInput(ToolInput):
    account_entity_id: str
    section: Literal["overview", "claims"] = "overview"
    field_prefix: str | None = Field(default=None, max_length=80)   # claims only: e.g. "account.resonance"

class ReadAccountResearchOutput(ToolOutput):
    account_entity_id: str; account_name: str; section: str
    overview: tuple[dict[str, Any], ...]      # [{section_key, body, cited_claim_ids, generated_at}]
    claims: tuple[dict[str, Any], ...]        # [{claim_id, field_key, value, source_url, evidence, tier, collected_at}]
    truncated: bool
```

`overview`: `live_blocks(conn, workspace_id=…, subject_kind="account", subject_id=…, page="overview")` (from `clue_api.arv2.display.blocks`); ordered by the overview recipes' section order (`display_section_recipe` rows for page `overview`, or the `section_key` sort if the recipe reader is not importable); `body = block.body_json` verbatim. Empty → `PreconditionFailed("overview_not_written", "this account's overview has not been written yet; read section='claims' or open the account in the app")`.

`claims`: `claims_for_entities(conn, [EntityId(account_id)], scope=WorkspaceScope.for_workspace(workspace_id))`, filtered by `field_key.startswith(field_prefix)` when given, sorted by `(field_key, collected_at desc)`, first 120 → `truncated = len > 120`; `value = claim.value_json`, `evidence = (claim.evidence_span or "")[:240]`, `tier = int(claim.source_tier)`. Empty → `PreconditionFailed("account_not_researched", …)`.

The account must exist in this workspace (`SELECT id, canonical_name FROM account_entity WHERE id = :id AND workspace_id = :ws`) → else `account_not_found`.

`model_description`: "Read what research found about one account: section='overview' returns the written overview sections (prose with the claim ids they cite); section='claims' returns the account's verified claims grouped by field (value, source, evidence, tier), optionally under a field prefix. Read this before saying anything specific about an account. Effect-free."

- [ ] **Step 1: Failing DB test**: an account with two live `display_block` rows and three claims (one superseded); `overview` returns the two sections; `claims` returns the two live claims with clipped evidence; `field_prefix` filters; another workspace's account → `account_not_found`; no blocks → `overview_not_written`.
- [ ] **Step 2–4: implement, green.**

### Task 3: `read_discovery_run@1`

**Interfaces:**

```python
class ReadDiscoveryRunInput(ToolInput):
    project_id: str
    run_id: str | None = None
    candidate_limit: int = Field(default=25, ge=0, le=50)

class ReadDiscoveryRunOutput(ToolOutput):
    run_id: str; status: str; icp_key: str; icp_version: int; target_count: int
    asked: int | None; found: int; verified: int; shown: int; approved: int
    relaxed_requested: bool; started_at: str | None; finished_at: str | None
    candidates: tuple[dict[str, Any], ...]   # [{name, domain, pass, disposition, decision, fit}]
    candidate_total: int
```

Latest run: the `_LATEST_DISCOVERY` idea from plan 1 (`ORDER BY created_at DESC, run_id DESC LIMIT 1`, counts via the candidate subqueries); by id: `read_discovery_run(conn, run_id=…)` (discovery_store) and refuse `discovery_run_not_found` when absent or another project's. Candidates: `list_candidates(conn, run_id=…)` sorted `disposition in (pass, partial, unclear) first, then fit desc, then name`, first `candidate_limit`. No run at all → `PreconditionFailed("no_discovery_run", "this project has not run discovery yet")`.

`model_description`: "Read the project's latest discovery run (or one by id): status, what was asked for and found, how many candidates were verified, shown and approved, and the top candidates with their verdict. Read this before proposing another discovery, and to answer what discovery found. It approves nothing. Effect-free."

- [ ] **Step 1: Failing DB test**: latest-run resolution with counts; by-id; candidate ordering and limit; foreign project → `discovery_run_not_found`; none → `no_discovery_run`.
- [ ] **Step 2–4: implement, green.**

### Task 4: Register ungranted; offline tool tests

- `build_arv2_read_tools(service: Arv2ReadService | None) -> tuple[Tool, ...]`; `toolbelt_wiring.build_toolbelt(..., arv2_reads=None)`; register all three `make_default=True`; three `C6_AGENT_TOOL_AUTHORITY` rows `()`; compose `DbArv2ReadService(conn_factory=transaction)` in `fleet_main.py` and `projections_main.py` unconditionally (no flag: a read over rows that exist).
- `tests/api/test_arv2_read_tools.py`: uncomposed refusals (`arv2_reads_not_composed`), descriptor classes (`READ`, `EFFECT_FREE`, `recipe_safe`, `pin_requirements == ("project",)`), a scripted service receiving `ctx.workspace_id`.
- Count bumps: `tests/api/test_toolbelt_wiring.py` (`_MATRIX` ×3, `_bodies()`, `len(registry.names())` +3), `tests/agents/test_tool_authority_audit.py` (+3), `tests/api/test_agent_registry_wiring.py` inventory comment (+3).
- Run `tests/arv2 tests/api/test_arv2_read_tools.py tests/api/test_toolbelt_wiring.py tests/agents tests/api/test_agent_registry_wiring.py --ignore-glob='*_live.py' -p no:cacheprovider -q`, ruff, mypy, `lint-imports`, `tests/arv2/test_import_guard.py`.
- [ ] **Commit** — `git commit -m "feat(arv2): read_project_accounts@1, read_account_research@1, read_discovery_run@1 — effect-free reads over ARV2 rows, registered ungranted"`.

### Task 5: The grant — skill v25, profile v48, recipe v26

As plan 2 Task 6 one version further (`v25` / `v48` / `recipe0-stage0-v26.json` / `CONVERSATION_RECIPE_VERSION = 26` / `"head-of-abm@v48"`); the three names go in the `_execution_project_pin` branch of `stage0_recipe.py` (they carry `project_id` as an untrusted input, like the launches). The trial surface withholds none of them (reads are harmless), unless `tests/api/test_c8_trial_surface.py`'s intersection assertion requires listing; follow its failure message.

**Skill v25 — text (v24 verbatim plus):**

`summary` appends ", and read the project's accounts, an account's research and the discovery run before speaking about them".

§7b append:

```
Before proposing another discovery run, call `read_discovery_run` for this project and say what the last run asked for, found and how many the human approved. Do not launch again to answer a question the read answers.
```

New §7c after §7b:

```
## 7c. Read before you speak about accounts

- **How many accounts, which are researched, what joined when:** `read_project_accounts`. `status.md` carries the summary; this read is the list.
- **What research found about one account:** `read_account_research` with `section: "overview"` first; when the overview is not written yet, `section: "claims"`. Quote a fact only with a claim behind it, and say when a field is empty. Never state a fact about an account from memory of an earlier thread.
- **What discovery found:** `read_discovery_run`.

A read costs nothing and is never a launch. When the human names an account you have not read this turn, read it before you answer.
```

- [ ] **Steps: mint, flip, digest, gate command twice + `tests/execution/test_recipes.py`; commit** — `git commit -m "feat(head-of-abm): v48 grants the three ARV2 read tools — skill v25 §7c says read before you speak; recipe v26 admits them"`.

### Task 6: Labels, live proof, close-out

- `chat-tool-presentation.ts`: `read_project_accounts: "Review the project's accounts"`, `read_account_research: "Review an account's research"`, `read_discovery_run: "Review the discovery run"` (+ test).
- Restart the lane's API twins and workers; in a **new thread** of the founder's project ask "what did we find about Goodman Campbell?" → `read_account_research` in the transcript, the answer cites the overview; ask "how many accounts do we have and how many are researched?" → `read_project_accounts`; ask "should we discover more?" → `read_discovery_run` before any launch. Record the transcript summary and any refusal in `_memory/2026-09-12-head-of-abm-read-tools.md`; README row; `platform/api/clue_api/arv2/README.md` section.
- [ ] **Commit** — `git commit -m "docs(arv2): read tools close-out — labels, README, memory"`.

---

## Self-review

- Spec §4.4: three tools with the listed shapes and bounds (T1–T3), registration (T4), grant + skill text (T5), labels + walk (T6). ✔
- Placeholder scan: none. ✔
- Type consistency: `Arv2ReadService` methods `list_project_accounts`, `read_account_research`, `read_discovery_run` named once each in T1–T3 and built in T4; `candidate_limit` `ge=0, le=50` matches the 50 cap in the constraints. ✔
