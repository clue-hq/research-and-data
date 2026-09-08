# ARV2 R2 — Account Research Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `launch_arv2_account_research(...)` creates one ARV2 research run (pinned to a confirmed ICP artifact, a product-set version and the agent profile digest) plus one job per account, enqueues one `arv2_account_research` fleet task per job; the fleet driver runs one `create_agent` loop per job with twelve tools over the R1 clients; every provider call lands on `provider_call_ledger` with its raw body in the artifact store; every fact lands through `LenientClaimWriter`; caps and errors push to a driver-side finalization, never a raise; Probook and Zafran are researched end to end.

**Architecture:** New files only, all under `platform/api/clue_api/arv2/` except the toolbelt registration, the authority dict entry and the fleet composition (which live at their existing roots). Own rows (`arv2_research_run`, `arv2_research_job`, `arv2_claim_annotation`) and own fleet kind, copying the O3 onboarding driver's shape: `async def handle` contains every exception, one blocking provider call per `asyncio.to_thread` hop, one `ProviderCaller` per tool invocation with buffered sinks drained to the DB after the hop. The agent is `langchain.agents.create_agent` with `StructuredTool`s and two small middlewares (round cap → graceful end; per-round parallel cap → refusals). The M8D entity-research runtime, its job table, its launcher and its tool-surface validator are **not** reused (facts-agent.md, facts-jobs.md: hard bounds that contradict the founder's stop-policy ruling, a hard-coded tool allowlist, raise-at-cap, and the old lane's `product_id NOT NULL` + `icp_spec` coupling).

**Tech Stack:** Python 3.12, LangChain `create_agent` + `StructuredTool` + `AgentMiddleware`, `clue_gateway.OpenRouterAgentModelProvider`, `clue_fleet` leased work worker, SQLAlchemy async `text()` SQL, Alembic, `clue_storage` artifacts, the R1 `clue_api.arv2` clients, pytest with `rollback_conn`.

**Spec:** `docs/specs/ARV2-MASTER-PLAN.md` §2 (principles), §5.1–5.2 (the two seams), §9 Track R row "R2 account agent", §11, Appendix A; `docs/specs/ARV2-R0-seam-freeze.md` (Seam 1 RATIFIED, boxes 1a/1b); `docs/superpowers/plans/2026-09-07-arv2-s7-agent-content-substance.md` (APPROVED 2026-09-08 — the agent content, the tool surface, the stop policy, the refusal table); `docs/specs/ARV2-WORK-SPLIT.md` rows S7, S10, A7; `platform/api/clue_api/arv2/README.md` "R2 composition constraints". **Facts files (exact signatures; read before any task):** `docs/superpowers/plans/2026-09-08-arv2-r2-account-agent-facts/facts-{fleet,jobs,agent,tools}.md`.

## Global Constraints

- **Stop policy (founder ruling 2026-09-08, substance §1):** full mode only; model rounds `CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS=100`; tool calls per round `CLUE_ARV2_ACCOUNT_MAX_TOOL_CALLS_PER_ROUND=50`; wall clock `CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S=1800`; **no** total tool-call cap; **no** consecutive-zero-yield cap. Reaching a ceiling ends the loop and the driver finalizes with what was written — never a raise, never a job death. The seam-1 `effort` field is recorded on the run and does not change behaviour in v1.
- **Failure law (master plan Appendix A 12; O3 precedent):** every tool error is a recoverable refusal envelope returned to the model; every provider failure, halt or empty answer is a tool result; nothing raises out of `handle`. An exception escaping the graph marks the job `needs_review` with its code and leaves every written claim in place.
- **Exactly two gates plus one floor (master plan §2.2).** The claim write gate is `LenientClaimWriter(lenient=settings.claim_write_lenient)`; human authority is the launch. No coverage floor, no judge veto, no budget veto; money is recorded (`provider_call_ledger`, `over_ceiling`) and never enforced except the media-seconds ceiling already inside the R1 media client. **The ICP hard gates never stop research** (substance §2 item 5, ruled): every launched account gets the full ladder; gates yield lenient fit verdicts (`pass | likely | unclear | fail`, `fail` only on positive contrary evidence).
- **Never on the event loop:** every `ProviderCaller.call` and every R1 client method runs inside `asyncio.to_thread`. **One `ProviderCaller` per tool invocation** (its totals and halt latch are unlocked mutable state; parallel tool calls run in parallel threads); the job-level halt registry and per-provider semaphores live in `ToolRuntime` (Task 4). AI Ark calls are serialised (its 10.5 s pacing is per client instance).
- **Import guard:** `clue_api.arv2` may import only the prefixes in `tests/arv2/test_import_guard.py` (facts-tools.md §"Import guard"); anything else is injected through a Protocol implemented outside `arv2/`. The twelve agent tools, the driver, the launcher and the store all live inside `arv2/` and need nothing outside the allowlist.
- **Standing rule (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`, items 5–7):** the launch needs account rows + ICP artifact ref + `product_selection_version` only; no `client_kb_version`, `readiness_decision_id`, `project.product_id`, `icp_spec` or `research_directive` on any R2 path; `.env.example` posture unchanged.
- **Settings/env parity:** every new `CLUE_ARV2_ACCOUNT_*` field goes into `Settings` (ARV2 block), `.env.example` (same commit) and the defaults dict in `tests/arv2/test_settings.py`. `ARV2_ACCOUNT_AGENT_MODEL` / `ARV2_ACCOUNT_AGENT_MODEL_EFFORT` go into the consolidated "Agent model configuration" block of `.env.example`.
- **Alembic:** `uv run alembic revision -m "arv2 r2 account research jobs"` (hash id), `down_revision = "9f81e5692fea"` (the single current head — verify with `uv run alembic heads` first); reversible; `make db-smoke` only on the throwaway DB `clue_san-salvador` (port 55040) after `make db-fresh`.
- **Tests:** offline suites via `uv run pytest tests/arv2 --ignore-glob='*_live.py' -p no:cacheprovider`; DB tests use `rollback_conn` and run with `set -a; source .env; set +a` against the throwaway DB. **Provider behaviour is never faked** (founder ruling): the tools' sequencing is tested with in-memory doubles of the R1 *clients* (the O3 precedent — client logic, not provider behaviour) and the loop is tested with a scripted fake chat model; real provider behaviour is proven only by the founder-triggered acceptance run (Task 7). Never run `make check` or a broad pytest with real keys in the env.
- **Commits:** local only, never push; no AI attribution; one commit per task with the message given; ruff (line length 100), mypy strict and import-linter clean before each commit (`uv run ruff check . && uv run ruff format --check . && uv run mypy platform/api/clue_api/arv2 && uv run lint-imports`).
- **Catalog files are written verbatim from the approved substance document.** The implementer of Task 2 copies §1–§5 of the substance into the five files, adapting only headings and the refusal table to the codes in `account_research_refusals.py`; any wording change is a review finding, not a judgement call.

---

## File Structure

| Path | Responsibility |
|---|---|
| `libs/clue-config/clue_config/settings.py` | **Modify.** Six `arv2_account_*` fields in the ARV2 block. |
| `.env.example` | **Modify.** The six `CLUE_ARV2_ACCOUNT_*` lines + `ARV2_ACCOUNT_AGENT_MODEL`, `ARV2_ACCOUNT_AGENT_MODEL_EFFORT`. |
| `platform/fleet/clue_fleet/enums.py` | **Modify.** Append `ARV2_ACCOUNT_RESEARCH = "arv2_account_research"`. |
| `alembic/versions/<hash>_arv2_r2_account_research_jobs.py` | **Create.** Fleet kind value; `arv2_research_run`, `arv2_research_job`, `arv2_claim_annotation`; `provider_call_ledger.extras_json`. |
| `platform/api/clue_api/arv2/catalog_seed.py` | **Modify.** Two account keys: `account.committee_candidate`, `account.icp_fit_verdict`. |
| `platform/api/clue_api/fleet_wiring.py` | **Modify.** `arv2_account_research_handler` kwarg + guard. |
| `platform/agents/catalog/entity-research/arv2-account/v1/{profile,prompt,dossier,audit,manual}.md` | **Create.** The S7 content. |
| `platform/api/clue_api/arv2/account_research_refusals.py` | **Create.** `REFUSAL_CODES`, `Refusal`, `refusal_json`. |
| `platform/api/clue_api/arv2/account_research_catalog.py` | **Create.** Profile ref/sha, resource bundle, system-prompt assembly, context block. |
| `platform/api/clue_api/arv2/provider_ledger.py` | **Create.** `BufferedRawSink`, `BufferedLedger`, `drain_provider_calls`. |
| `platform/api/clue_api/arv2/account_research_store.py` | **Create.** Run/job/annotation rows; one function per transition; job claims read. |
| `platform/api/clue_api/arv2/account_research_claims.py` | **Create.** Deterministic `ClaimDraft` mappers (ATS, AI Ark, media index, negatives, fit verdicts, committee candidates, agent claims). |
| `platform/api/clue_api/arv2/structuring_client.py` | **Modify.** `mode: Literal["broad","intent_sweep"]` on `structure_account`/`structure_person` + the sweep prompt. |
| `platform/api/clue_api/arv2/account_research_tools.py` | **Create.** `ToolRuntime`, `JobScope`, the twelve `StructuredTool`s, `build_account_tools`. |
| `platform/api/clue_api/arv2/account_research_agent.py` | **Create.** `run_account_agent` (create_agent loop, middlewares, finalization). |
| `platform/api/clue_api/arv2/account_research_driver.py` | **Create.** `Arv2AccountResearchWorkHandler`, provider client factories, `build_arv2_account_research_handler`. |
| `platform/api/clue_api/arv2/account_research_launch.py` | **Create.** `Arv2LaunchRequest`, `launch_arv2_account_research`, `Arv2LaunchRefused`, the two toolbelt tools. |
| `platform/api/clue_api/toolbelt_wiring.py`, `platform/api/clue_api/agent_registry_wiring.py`, `tests/agents/test_tool_authority_audit.py` | **Modify.** Register `launch_arv2_account_research@1`, `read_arv2_account_research_run@1`; grant HEAD_OF_ABM; count 120 → 122. |
| `platform/api/clue_api/fleet_main.py` | **Modify.** `_build_arv2_account_research_handler` behind the flag; pass to `build_multi_work_worker`. |
| `scripts/launch_arv2_account_research.py` | **Create.** CLI launcher for the answer-key runs. |
| `platform/api/clue_api/arv2/README.md`, `docs/specs/ARV2-MASTER-PLAN.md` | **Modify.** R2 module map; flag default flip at close. |
| `tests/arv2/test_account_research_*.py`, `tests/db/test_arv2_r2_migration.py`, `tests/api/test_fleet_wiring.py` | **Create/Modify.** |

---

### Task 1: Settings, fleet kind, migration, catalog keys, wiring kwarg

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (ARV2 block, after `arv2_raw_root` at ~:333)
- Modify: `.env.example` (ARV2 block ~:143-159; agent-model block ~:213-238)
- Modify: `platform/fleet/clue_fleet/enums.py` (append after `ONBOARDING_RUN`, :62)
- Create: `alembic/versions/<hash>_arv2_r2_account_research_jobs.py`
- Modify: `platform/api/clue_api/arv2/catalog_seed.py` (two `_row(...)` entries appended after `account.abm_program_maturity`)
- Modify: `platform/api/clue_api/fleet_wiring.py:324-398`
- Modify: `tests/db/test_arv2_onboarding_kind_migration.py:26` (relax `labels[-1] == "onboarding_run"` → `"onboarding_run" in labels`)
- Test: `tests/arv2/test_settings.py` (defaults dict), `tests/db/test_arv2_r2_migration.py`, `tests/api/test_fleet_wiring.py`, `tests/arv2/test_catalog_seed.py`

**Interfaces:**
- Produces: `Settings.arv2_account_max_model_rounds: int = 100`, `arv2_account_max_tool_calls_per_round: int = 50`, `arv2_account_max_runtime_s: int = 1800`, `arv2_account_max_parallel_jobs: int = 4`, `arv2_account_provider_concurrency: int = 4`, `arv2_account_media_max_enclosure_mb: int = 200`; `FleetTaskKind.ARV2_ACCOUNT_RESEARCH`; tables below; `build_multi_work_worker(..., arv2_account_research_handler: WorkHandler | None = None, ...)`; keys `account.committee_candidate`, `account.icp_fit_verdict` in `ARV2_FIELD_KEYS`.

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_settings.py` — add to the existing defaults dict (the test iterates it against `.env.example`):

```python
    "arv2_account_max_model_rounds": "100",
    "arv2_account_max_tool_calls_per_round": "50",
    "arv2_account_max_runtime_s": "1800",
    "arv2_account_max_parallel_jobs": "4",
    "arv2_account_provider_concurrency": "4",
    "arv2_account_media_max_enclosure_mb": "200",
```

`tests/db/test_arv2_r2_migration.py`:

```python
"""The R2 migration: fleet kind, run/job/annotation tables, the ledger extras column."""

from clue_fleet import FleetTaskKind
from sqlalchemy import text

from tests.db.helpers import rollback_conn, run_async


def test_fleet_kind_and_r2_tables_exist() -> None:
    async def scenario() -> tuple[list[str], set[str], bool]:
        async with rollback_conn() as conn:
            labels = [
                r[0]
                for r in await conn.execute(
                    text(
                        "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                        "WHERE t.typname = 'fleet_task_kind' ORDER BY e.enumsortorder"
                    )
                )
            ]
            tables = {
                r[0]
                for r in await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables WHERE table_name IN "
                        "('arv2_research_run','arv2_research_job','arv2_claim_annotation')"
                    )
                )
            }
            extras = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns WHERE table_name = "
                        "'provider_call_ledger' AND column_name = 'extras_json'"
                    )
                )
            ).first() is not None
        return labels, tables, extras

    labels, tables, extras = run_async(scenario())
    assert labels[-1] == "arv2_account_research"
    assert labels == [k.value for k in FleetTaskKind]
    assert tables == {"arv2_research_run", "arv2_research_job", "arv2_claim_annotation"}
    assert extras


def test_job_status_and_finished_at_move_together() -> None:
    async def scenario() -> str:
        async with rollback_conn() as conn:
            try:
                await conn.execute(
                    text(
                        "INSERT INTO arv2_research_job (job_id, run_id, workspace_id, "
                        "account_entity_id, status) VALUES (gen_random_uuid(), gen_random_uuid(), "
                        "'ws', gen_random_uuid(), 'completed')"
                    )
                )
            except Exception as error:  # noqa: BLE001 — the CHECK (or the FK) must refuse
                return type(error).__name__
        return "accepted"

    assert run_async(scenario()) != "accepted"
```

(Use whichever helper module the existing `tests/db/test_arv2_onboarding_kind_migration.py` imports for `rollback_conn`/`run_async`; mirror its imports exactly.)

`tests/api/test_fleet_wiring.py` — add beside the onboarding guard test (:268-290), same fixtures:

```python
def test_arv2_account_research_handler_must_own_its_kind(...) -> None:
    class Wrong:
        kind = FleetTaskKind.ONBOARDING_RUN

        async def handle(self, context):  # pragma: no cover - shape only
            raise AssertionError

    with pytest.raises(ValueError, match="arv2_account_research_handler must own"):
        build_multi_work_worker(settings, driver=driver, graph_handler=graph, arv2_account_research_handler=Wrong())
```

`tests/arv2/test_catalog_seed.py` — extend the existing key-count/shape test:

```python
def test_r2_account_keys_are_registered_in_the_pack() -> None:
    assert {"account.committee_candidate", "account.icp_fit_verdict"} <= ARV2_FIELD_KEYS
    assert len(ARV2_FIELD_KEYS) == 40
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/arv2/test_settings.py tests/arv2/test_catalog_seed.py tests/api/test_fleet_wiring.py -p no:cacheprovider -q` and (env sourced, throwaway DB) `uv run pytest tests/db/test_arv2_r2_migration.py -q`
Expected: FAIL — unknown settings keys, `AttributeError: ARV2_ACCOUNT_RESEARCH`, missing tables, unknown kwarg.

- [ ] **Step 3: Settings + `.env.example`**

`settings.py`, ARV2 block, after `arv2_raw_root`:

```python
    # --- ARV2 R2 account agent (master plan §9 R2; founder stop-policy ruling 2026-09-08) ------
    # Model rounds per account job. A ceiling ends the loop and the driver finalizes with what
    # was written; it is a safety net, never a budget. Env: ``CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS``.
    arv2_account_max_model_rounds: int = Field(default=100, ge=1)
    # Tool calls the model may issue in ONE round; the excess receive a recoverable refusal.
    # Env: ``CLUE_ARV2_ACCOUNT_MAX_TOOL_CALLS_PER_ROUND``.
    arv2_account_max_tool_calls_per_round: int = Field(default=50, ge=1)
    # Wall clock per account job, seconds. Env: ``CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S``.
    arv2_account_max_runtime_s: int = Field(default=1800, ge=60)
    # Account jobs one worker drives concurrently. Env: ``CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS``.
    arv2_account_max_parallel_jobs: int = Field(default=4, ge=1)
    # Concurrent calls per provider within one job (AI Ark is always 1 — its pacing is per
    # client). Env: ``CLUE_ARV2_ACCOUNT_PROVIDER_CONCURRENCY``.
    arv2_account_provider_concurrency: int = Field(default=4, ge=1)
    # Largest podcast enclosure the media tool downloads, MiB.
    # Env: ``CLUE_ARV2_ACCOUNT_MEDIA_MAX_ENCLOSURE_MB``.
    arv2_account_media_max_enclosure_mb: int = Field(default=200, ge=1)
```

`.env.example`, ARV2 block:

```
# --- ARV2 R2 account agent (founder stop-policy ruling 2026-09-08: full mode, no call caps) ---
CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS=100
CLUE_ARV2_ACCOUNT_MAX_TOOL_CALLS_PER_ROUND=50
CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S=1800
CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS=4
CLUE_ARV2_ACCOUNT_PROVIDER_CONCURRENCY=4
CLUE_ARV2_ACCOUNT_MEDIA_MAX_ENCLOSURE_MB=200
```

`.env.example`, agent-model block (beside `ACCOUNT_RESEARCH_AGENT_MODEL`):

```
ARV2_ACCOUNT_AGENT_MODEL=x-ai/grok-4.6
ARV2_ACCOUNT_AGENT_MODEL_EFFORT=
```

Mirror the six `CLUE_` lines into the local `.env` (parity rule; the two agent-model lines too).

- [ ] **Step 4: Fleet kind**

`platform/fleet/clue_fleet/enums.py`, after `ONBOARDING_RUN`:

```python
    # ARV2 R2: one job per account for the account research agent. Appended, never inserted.
    ARV2_ACCOUNT_RESEARCH = "arv2_account_research"
```

- [ ] **Step 5: Migration**

`uv run alembic revision -m "arv2 r2 account research jobs"`, then fill in (`down_revision = "9f81e5692fea"`):

```python
_KINDS_BEFORE = (
    "drive_run", "account_job", "execute_graph", "entity_research_job", "agent_turn",
    "stage0_recon", "official_site_crawl", "design_job", "onboarding_run",
)

_STATUSES = "('not_started', 'in_progress', 'needs_review', 'completed', 'suspended')"


def upgrade() -> None:
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'arv2_account_research'")
    op.execute(
        f"""
        CREATE TABLE arv2_research_run (
            run_id                    uuid PRIMARY KEY,
            workspace_id              text NOT NULL,
            project_id                text NOT NULL,
            brand_id                  text NOT NULL,
            project_run_id            uuid NOT NULL REFERENCES project_run (id),
            icp_artifact_key          text NOT NULL,
            icp_artifact_sha256       text NOT NULL,
            icp_key                   text NOT NULL,
            icp_version               integer NOT NULL,
            product_selection_version integer NOT NULL,
            effort                    text NOT NULL,
            committee_cap             integer NOT NULL,
            directive_text            text NOT NULL DEFAULT '',
            profile_ref               text NOT NULL,
            profile_sha256            text NOT NULL,
            requested_by_user_id      text NOT NULL,
            request_sha256            text NOT NULL,
            status                    text NOT NULL DEFAULT 'not_started',
            created_at                timestamptz NOT NULL DEFAULT now(),
            finished_at               timestamptz,
            CONSTRAINT arv2_research_run_icp_sha CHECK (icp_artifact_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT arv2_research_run_profile_sha CHECK (profile_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT arv2_research_run_request_sha CHECK (request_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT arv2_research_run_effort CHECK (effort IN ('full', 'reduced', 'cheap-pass')),
            CONSTRAINT arv2_research_run_cap CHECK (committee_cap >= 1),
            CONSTRAINT arv2_research_run_selection CHECK (product_selection_version >= 1),
            CONSTRAINT arv2_research_run_status CHECK (status IN {_STATUSES}),
            CONSTRAINT arv2_research_run_finished CHECK (
                (status IN ('completed', 'needs_review')) = (finished_at IS NOT NULL))
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE arv2_research_job (
            job_id             uuid PRIMARY KEY,
            run_id             uuid NOT NULL REFERENCES arv2_research_run (run_id),
            workspace_id       text NOT NULL,
            account_entity_id  uuid NOT NULL,
            status             text NOT NULL DEFAULT 'not_started',
            attempt            integer NOT NULL DEFAULT 0,
            started_at         timestamptz,
            finished_at        timestamptz,
            finalization_json  jsonb,
            failure_code       text,
            failure_message    text,
            model_rounds       integer NOT NULL DEFAULT 0,
            tool_calls         integer NOT NULL DEFAULT 0,
            cost_usd           numeric(12, 6) NOT NULL DEFAULT 0,
            credits            numeric(12, 3) NOT NULL DEFAULT 0,
            media_seconds      integer NOT NULL DEFAULT 0,
            created_at         timestamptz NOT NULL DEFAULT now(),
            updated_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT arv2_research_job_account_fk FOREIGN KEY (account_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT arv2_research_job_once UNIQUE (run_id, account_entity_id),
            CONSTRAINT arv2_research_job_status CHECK (status IN {_STATUSES}),
            CONSTRAINT arv2_research_job_finished CHECK (
                (status IN ('completed', 'needs_review')) = (finished_at IS NOT NULL)),
            CONSTRAINT arv2_research_job_failure CHECK (
                (status = 'needs_review') = (failure_code IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX arv2_research_job_run ON arv2_research_job (run_id)")
    op.execute(
        "CREATE INDEX arv2_research_job_account ON arv2_research_job (workspace_id, account_entity_id)"
    )
    op.execute(
        """
        CREATE TABLE arv2_claim_annotation (
            annotation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id      uuid NOT NULL REFERENCES claim (id),
            job_id        uuid NOT NULL REFERENCES arv2_research_job (job_id),
            kind          text NOT NULL,
            verdict       text NOT NULL,
            detail_json   jsonb,
            checked_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT arv2_claim_annotation_kind CHECK (kind IN ('link_audit')),
            CONSTRAINT arv2_claim_annotation_verdict CHECK (
                verdict IN ('EXACT', 'PARTIAL', 'NOT_FOUND', 'fetch_failed'))
        )
        """
    )
    op.execute("CREATE INDEX arv2_claim_annotation_claim ON arv2_claim_annotation (claim_id)")
    op.execute("ALTER TABLE provider_call_ledger ADD COLUMN extras_json jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE provider_call_ledger DROP COLUMN extras_json")
    op.execute("DROP TABLE arv2_claim_annotation")
    op.execute("DROP TABLE arv2_research_job")
    op.execute("DROP TABLE arv2_research_run")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'arv2_account_research') THEN
                RAISE EXCEPTION 'cannot downgrade R2 while arv2_account_research fleet tasks exist';
            END IF;
        END $$
        """
    )
    labels = ", ".join(f"'{k}'" for k in _KINDS_BEFORE)
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_r2")
    op.execute(f"CREATE TYPE fleet_task_kind AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE fleet_task ALTER COLUMN kind TYPE fleet_task_kind "
        "USING kind::text::fleet_task_kind"
    )
    op.execute("DROP TYPE fleet_task_kind_r2")
```

`arv2_research_job.status` values map to the seam-1 job states exactly (`not_started / in_progress / needs_review / completed / suspended`); `provider_call_ledger.entity_research_job_id` will carry the R2 `job_id` (the column name is the D1 migration's; its meaning here is "the job that spent", documented in `provider_ledger.py`).

- [ ] **Step 6: Catalog keys**

`catalog_seed.py`, after the `account.abm_program_maturity` row:

```python
    _row(
        "account.committee_candidate",
        "object",
        {
            "type": "object",
            "required": ["name", "persona"],
            "properties": {
                "name": _STR,
                "title": _STR,
                "persona": {
                    "type": "string",
                    "enum": ["economic_buyer", "champion", "user", "technical_evaluator", "blocker"],
                },
                "linkedin_url": _STR,
                "confirmed_by": _STR,
                "vacant_seat": {"type": "boolean"},
            },
        },
        "One buying-committee candidate the account agent confirmed on a non-provider URL: name, "
        "title, persona from the ICP persona map, LinkedIn URL, what confirmed the identity. A "
        "vacant seat is recorded with vacant_seat=true and no name (R3 creates the contact).",
    ),
    _row(
        "account.icp_fit_verdict",
        "object",
        {
            "type": "object",
            "required": ["gate", "verdict"],
            "properties": {
                "gate": _STR,
                "verdict": {"type": "string", "enum": ["pass", "likely", "unclear", "fail"]},
                "rationale": _STR,
                "claim_ids": _STR_LIST,
            },
        },
        "The agent's lenient fit verdict for one ICP hard gate, with the claim ids behind it. "
        "Information for the human; never a reason to stop research. Born outreach_safe=false.",
    ),
```

- [ ] **Step 7: Fleet wiring kwarg**

`fleet_wiring.build_multi_work_worker`: add `arv2_account_research_handler: WorkHandler | None = None` after `onboarding_handler`; docstring line "``arv2_account_research_handler`` (Track R, R2) is the same shape again: optional because a deployment without ``arv2_account_research_enabled`` composes no account driver."; guard:

```python
    if (
        arv2_account_research_handler is not None
        and arv2_account_research_handler.kind is not FleetTaskKind.ARV2_ACCOUNT_RESEARCH
    ):
        raise ValueError("arv2_account_research_handler must own arv2_account_research tasks")
```

and `handlers.append(arv2_account_research_handler)` when not None. Relax `tests/db/test_arv2_onboarding_kind_migration.py:26` to `assert "onboarding_run" in labels`.

- [ ] **Step 8: Migrate the throwaway DB and run the tests**

Run: `set -a; source .env; set +a; uv run alembic heads` (one head, the new id), `uv run alembic upgrade head`, then the four test files. Expected: PASS. Then `make db-fresh && make db-smoke` on the throwaway DB. Expected: up → down → up clean.

- [ ] **Step 9: Commit**

```bash
git add libs/clue-config/clue_config/settings.py .env.example platform/fleet/clue_fleet/enums.py alembic/versions/*_arv2_r2_account_research_jobs.py platform/api/clue_api/arv2/catalog_seed.py platform/api/clue_api/fleet_wiring.py tests/
git commit -m "feat(arv2 r2): stop-policy settings, arv2_account_research fleet kind, run/job/annotation tables, ledger extras, two account keys, wiring kwarg"
```

---

### Task 2: The S7 catalog files, the refusal codes, the resource bundle and the system prompt

**Files:**
- Create: `platform/agents/catalog/entity-research/arv2-account/v1/profile.md`, `prompt.md`, `dossier.md`, `audit.md`, `manual.md`
- Create: `platform/api/clue_api/arv2/account_research_refusals.py`
- Create: `platform/api/clue_api/arv2/account_research_catalog.py`
- Test: `tests/arv2/test_account_research_catalog.py`

**Interfaces:**
- Produces:
  - `REFUSAL_CODES: frozenset[str]`, `@dataclass(frozen=True) class Refusal(code: str, detail: str, reaction: str)`, `def refusal_json(code: str, detail: str) -> str` (the envelope), `class RefusalError(Arv2Error)` carrying a `Refusal` (raised inside a tool body, converted to the envelope by the tool wrapper in Task 4).
  - `ARV2_ACCOUNT_PROFILE_REF = "agent-profile:arv2-account:v1"`, `ARV2_ACCOUNT_CATALOG_VERSION = "v1"`, `def arv2_account_catalog_root(version: str = ARV2_ACCOUNT_CATALOG_VERSION) -> Path`, `def arv2_account_profile_sha256(root: Path | None = None) -> str`, `@dataclass(frozen=True) class CatalogResource(kind: Literal["profile","prompt","skill"], ref: str, version: str, sha256: str, body: str)`, `@dataclass(frozen=True) class AccountResourceBundle(profile, prompt, skills: tuple[CatalogResource, ...])` with `.manifest() -> dict[str, str]` (ref → sha) and `.manifest_sha256() -> str`, `def load_account_resources(root: Path | None = None) -> AccountResourceBundle`, `@dataclass(frozen=True) class AccountContext(account_name, account_domain, account_id: str, workspace_id, today: date, icp_markdown: str, persona_markdown: str, catalog_menu: str, already_established: str, directive_text: str, effort: str, committee_cap: int, stop_policy: dict[str, int])`, `def build_system_prompt(bundle: AccountResourceBundle, context: AccountContext) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
"""The arv2-account catalog: five files, sha-pinned; the manual covers every refusal code."""

import hashlib
import re

from clue_api.arv2.account_research_catalog import (
    ARV2_ACCOUNT_PROFILE_REF,
    AccountContext,
    arv2_account_catalog_root,
    arv2_account_profile_sha256,
    build_system_prompt,
    load_account_resources,
)
from clue_api.arv2.account_research_refusals import REFUSAL_CODES, refusal_json

FILES = ("profile.md", "prompt.md", "dossier.md", "audit.md", "manual.md")


def test_five_files_exist_and_the_profile_sha_is_the_file_digest() -> None:
    root = arv2_account_catalog_root()
    for name in FILES:
        assert (root / name).is_file(), name
    assert arv2_account_profile_sha256() == hashlib.sha256((root / "profile.md").read_bytes()).hexdigest()
    assert ARV2_ACCOUNT_PROFILE_REF == "agent-profile:arv2-account:v1"


def test_bundle_carries_one_prompt_and_three_skills_with_matching_digests() -> None:
    bundle = load_account_resources()
    assert bundle.prompt.ref == "agent-prompt:arv2-account:v1"
    assert [s.ref for s in bundle.skills] == [
        "agent-skill:arv2-account-dossier:v1",
        "agent-skill:arv2-account-audit:v1",
        "agent-skill:arv2-account-manual:v1",
    ]
    for resource in (bundle.profile, bundle.prompt, *bundle.skills):
        assert resource.sha256 == hashlib.sha256(resource.body.encode()).hexdigest()
    assert len(bundle.manifest_sha256()) == 64


def test_manual_names_every_refusal_code_the_driver_can_emit() -> None:
    manual = (arv2_account_catalog_root() / "manual.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`([a-z_]+(?::<[a-z_]+>)?)`", manual))
    missing = {code for code in REFUSAL_CODES if code not in named}
    assert not missing, f"manual.md lacks a row for: {sorted(missing)}"


def test_refusal_envelope_is_recoverable_json_with_the_manual_reaction() -> None:
    import json

    body = json.loads(refusal_json("board_not_found", "no ATS link on /careers"))
    assert body["error"] == "governed_research_rejection"
    assert body["code"] == "board_not_found" and body["recoverable"] is True
    assert "careers page" in body["reaction"]


def test_system_prompt_stacks_profile_prompt_skills_and_the_context_block() -> None:
    bundle = load_account_resources()
    context = AccountContext(
        account_name="Probook", account_domain="probook.ai", account_id="00000000-0000-0000-0000-000000000001",
        workspace_id="ws", today=__import__("datetime").date(2026, 9, 8), icp_markdown="# ICP\nhard_gates: []",
        persona_markdown="personas: []", catalog_menu="- account.named_customers", already_established="- HQ: New York",
        directive_text="", effort="full", committee_cap=5,
        stop_policy={"max_model_rounds": 100, "max_tool_calls_per_round": 50, "max_runtime_s": 1800},
    )
    prompt = build_system_prompt(bundle, context)
    for marker in ("<profile ref=\"agent-profile:arv2-account:v1\"", bundle.prompt.body[:40],
                   "<skill ref=\"agent-skill:arv2-account-dossier:v1\"", "<account_research_context>",
                   "probook.ai", "# ICP", "- account.named_customers", "2026-09-08"):
        assert marker in prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/arv2/test_account_research_catalog.py -p no:cacheprovider -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `account_research_refusals.py`**

```python
"""Refusal codes the R2 driver and tools can emit, and the envelope the model receives.

A refusal spends nothing, suspends nothing and ends nothing (master plan Appendix A 12; substance
§5). The ``reaction`` sentence is the manual's row for that code, so the model reads the correct
move inside the envelope and the manual test proves the two never drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from clue_api.arv2.errors import Arv2Error

REACTIONS: dict[str, str] = {
    "provider_halted": "Continue with the other providers and note the gap; never retry that provider in this job.",
    "board_not_found": "Fetch the careers page itself with fetch_page; hiring is a gap only after both were read; never guess a slug.",
    "board_fetch_failed": "Record hiring as an honest gap; do not re-fetch the board.",
    "page_unavailable": "Record the URL as unreadable; try a different known URL, never a search for the same page.",
    "company_not_found": "AI Ark has no record for this domain; continue from the web sources.",
    "feed_not_found": "No podcast or YouTube for this person; media stays empty; move on.",
    "episode_not_found": "The feed has no matching episode; media stays empty for this person.",
    "media_ceiling_reached": "Skip this item; the reservation was released; do not shorten and retry.",
    "enclosure_too_large": "Skip this item; do not retry with another URL for the same episode.",
    "native_video_rejected": "Use the YouTube words path (page text), never a video download.",
    "speaker_unverified": "Quote nothing from this transcript; record the item as unattributed media.",
    "deep_thin_response": "Both deep attempts came back thin; structure what the free sources yielded; do not call research_deep again.",
    "structuring_unparseable": "Resend the same material once; if it fails again record the subject as unstructured.",
    "already_established": "Drop that field from the call; it is already recorded.",
    "identical_call_repeated": "Change the arguments the way the earlier refusal named, make the call it named, or finalize honestly.",
    "too_many_parallel_calls": "Re-issue the refused calls in the next round; the first fifty of this round ran.",
    "finalization_already_proposed": "The decision is made; stop.",
    "tool_error": "The tool failed for a reason outside your control; record the gap and continue.",
    "invalid_arguments": "Correct the named argument and call again.",
}

REFUSAL_CODES: frozenset[str] = frozenset(REACTIONS)


@dataclass(frozen=True)
class Refusal:
    code: str
    detail: str

    @property
    def reaction(self) -> str:
        return REACTIONS[self.code.split(":", 1)[0]]


class RefusalError(Arv2Error):
    """Raised inside a tool body; the tool wrapper turns it into the envelope, never a raise."""

    def __init__(self, code: str, detail: str) -> None:
        base = code.split(":", 1)[0]
        if base not in REACTIONS:
            raise ValueError(f"unknown refusal code {code!r}")
        super().__init__(f"{code}: {detail}")
        self.refusal = Refusal(code=code, detail=detail)


def refusal_json(code: str, detail: str) -> str:
    refusal = Refusal(code=code, detail=detail)
    return json.dumps(
        {
            "error": "governed_research_rejection",
            "code": code,
            "detail": detail[:1_000],
            "recoverable": True,
            "reaction": refusal.reaction,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
```

Codes with a suffix (`provider_halted:<provider>`, `already_established:<field>`, `tool_error:<ExceptionName>`) resolve their reaction by the base code; the manual lists them with the `<…>` placeholder, which the test regex accepts.

- [ ] **Step 4: The five catalog files**

Write them **verbatim from the approved substance document** (`2026-09-07-arv2-s7-agent-content-substance.md`):

- `profile.md` — header lines `role: arv2-account-research`, `framework: langchain.agents.create_agent`, `contract: arv2-r2-account-research-v1`, then §1 of the substance as prose (identity, model env names, the stop policy table with the note that the numbers are carried by `CLUE_ARV2_ACCOUNT_*` env settings, full mode only, spend policy, what the context block carries). State explicitly: "This file is the sha-pinned authorization for a job; a change relaunches, never resumes."
- `prompt.md` — §2 items 1–10, one numbered section each, no frontmatter (the M8D v3 prompt shape).
- `dossier.md` — header `name: arv2-account-dossier` / `version: v1`, then §3.1 (the ladder), §3.2 (the twelve sections, numbered), §3.3 (committee), §3.4 (structuring and the second pass, rewritten for the tool contract of Task 4: `structure_material` **writes** the claims it extracts and returns them with ids and markers; the agent's field-meaning review happens on what came back, and a correction is a new `write_claims` claim carrying `markers.corrects_claim_id`).
- `audit.md` — header `name: arv2-account-audit` / `version: v1`, §4 items 1–5.
- `manual.md` — header `name: arv2-account-manual` / `version: v1`, the substance §5 table re-keyed to `REACTIONS` above (one row per key, the reaction text identical to the dict), plus the tool contract table from substance §0 with each tool's arguments as defined in Task 4.

Then `shasum -a 256 platform/agents/catalog/entity-research/arv2-account/v1/*.md` and record the digests in the memory note.

- [ ] **Step 5: `account_research_catalog.py`**

```python
"""The arv2-account catalog: sha-pinned resources and the system prompt they assemble into."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

ARV2_ACCOUNT_CATALOG_VERSION = "v1"
ARV2_ACCOUNT_PROFILE_REF = f"agent-profile:arv2-account:{ARV2_ACCOUNT_CATALOG_VERSION}"
_PROMPT_REF = f"agent-prompt:arv2-account:{ARV2_ACCOUNT_CATALOG_VERSION}"
_SKILL_FILES: tuple[tuple[str, str], ...] = (
    ("dossier.md", f"agent-skill:arv2-account-dossier:{ARV2_ACCOUNT_CATALOG_VERSION}"),
    ("audit.md", f"agent-skill:arv2-account-audit:{ARV2_ACCOUNT_CATALOG_VERSION}"),
    ("manual.md", f"agent-skill:arv2-account-manual:{ARV2_ACCOUNT_CATALOG_VERSION}"),
)


def arv2_account_catalog_root(version: str = ARV2_ACCOUNT_CATALOG_VERSION) -> Path:
    # platform/api/clue_api/arv2/<this file> -> parents[3] == platform/
    return Path(__file__).parents[3] / "agents" / "catalog" / "entity-research" / "arv2-account" / version


def arv2_account_profile_sha256(root: Path | None = None) -> str:
    base = root or arv2_account_catalog_root()
    return hashlib.sha256((base / "profile.md").read_bytes()).hexdigest()


@dataclass(frozen=True)
class CatalogResource:
    kind: Literal["profile", "prompt", "skill"]
    ref: str
    version: str
    sha256: str
    body: str


@dataclass(frozen=True)
class AccountResourceBundle:
    profile: CatalogResource
    prompt: CatalogResource
    skills: tuple[CatalogResource, ...]

    def manifest(self) -> dict[str, str]:
        return {r.ref: r.sha256 for r in (self.profile, self.prompt, *self.skills)}

    def manifest_sha256(self) -> str:
        canonical = json.dumps(self.manifest(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def _resource(kind: Literal["profile", "prompt", "skill"], ref: str, path: Path) -> CatalogResource:
    body = path.read_text(encoding="utf-8")
    return CatalogResource(kind=kind, ref=ref, version=ARV2_ACCOUNT_CATALOG_VERSION,
                           sha256=hashlib.sha256(body.encode()).hexdigest(), body=body)


def load_account_resources(root: Path | None = None) -> AccountResourceBundle:
    base = root or arv2_account_catalog_root()
    return AccountResourceBundle(
        profile=_resource("profile", ARV2_ACCOUNT_PROFILE_REF, base / "profile.md"),
        prompt=_resource("prompt", _PROMPT_REF, base / "prompt.md"),
        skills=tuple(_resource("skill", ref, base / name) for name, ref in _SKILL_FILES),
    )


@dataclass(frozen=True)
class AccountContext:
    account_name: str
    account_domain: str
    account_id: str
    workspace_id: str
    today: date
    icp_markdown: str
    persona_markdown: str
    catalog_menu: str
    already_established: str
    directive_text: str
    effort: str
    committee_cap: int
    stop_policy: dict[str, int]

    def block(self) -> str:
        head = {
            "account": {"name": self.account_name, "domain": self.account_domain, "id": self.account_id},
            "workspace_id": self.workspace_id,
            "today": self.today.isoformat(),
            "directive": {"text": self.directive_text, "effort": self.effort, "committee_cap": self.committee_cap},
            "stop_policy": self.stop_policy,
        }
        return "\n\n".join(
            [
                json.dumps(head, sort_keys=True),
                "## context/icp.md\n" + self.icp_markdown.rstrip(),
                "## context/persona.md\n" + self.persona_markdown.rstrip(),
                "## context/catalog.md\n" + self.catalog_menu.rstrip(),
                "## context/already-established.md\n" + (self.already_established.rstrip() or "(nothing yet)"),
            ]
        )


def _tag(resource: CatalogResource, tag: str) -> str:
    return (
        f'<{tag} ref="{resource.ref}" version="{resource.version}" sha256="{resource.sha256}">\n'
        f"{resource.body.rstrip()}\n</{tag}>"
    )


def build_system_prompt(bundle: AccountResourceBundle, context: AccountContext) -> str:
    sections = [
        _tag(bundle.profile, "profile"),
        bundle.prompt.body.rstrip(),
        "\n\n".join(_tag(skill, "skill") for skill in bundle.skills),
        "The following runtime context is engine authority: the account, the ICP, the persona map, "
        "the field catalog and what is already established. Research the account in full.\n"
        f"<account_research_context>\n{context.block()}\n</account_research_context>",
    ]
    return "\n\n".join(sections)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/arv2/test_account_research_catalog.py -p no:cacheprovider -q`
Expected: PASS (5 tests). Fix the manual until `test_manual_names_every_refusal_code_the_driver_can_emit` is green.

- [ ] **Step 7: Commit**

```bash
git add platform/agents/catalog/entity-research/arv2-account platform/api/clue_api/arv2/account_research_refusals.py platform/api/clue_api/arv2/account_research_catalog.py tests/arv2/test_account_research_catalog.py
git commit -m "feat(arv2 r2): the arv2-account/v1 catalog (profile, prompt, dossier, audit, manual), refusal codes, sha-pinned resource bundle and system prompt"
```

---

### Task 3: Production sinks and the run/job store

**Files:**
- Create: `platform/api/clue_api/arv2/provider_ledger.py`
- Create: `platform/api/clue_api/arv2/account_research_store.py`
- Test: `tests/arv2/test_provider_ledger.py` (pure), `tests/arv2/test_provider_ledger_db.py`, `tests/arv2/test_account_research_store_db.py`

**Interfaces:**
- Consumes: `clue_api.arv2.sinks.{RawRecord, LedgerRow, RawSink, LedgerSink}`; `ArtifactSink` protocol shape from `onboarding_driver.py:154-158` (`persist_body(*, workspace_id, data, media_type, subject_bindings=(), project_bindings=()) -> ArtifactRef`); `provider_call_ledger` columns (facts-tools.md).
- Produces:
  ```python
  class BufferedRawSink:               # RawSink; thread-safe (threading.Lock)
      def save(self, record: RawRecord, body: bytes) -> str   # returns f"raw:{sha256_hex(body)}"
      def drain(self) -> list[tuple[str, RawRecord, bytes]]   # (raw_ref, record, body), clears
  class BufferedLedger:                # LedgerSink; thread-safe
      def record(self, row: LedgerRow) -> str                  # returns row.row_id
      def drain(self) -> list[LedgerRow]
  @dataclass(frozen=True)
  class LedgerStamp: workspace_id: str; project_id: str; project_run_id: str; job_id: UUID
  async def drain_provider_calls(conn, *, raw: BufferedRawSink, ledger: BufferedLedger,
                                 artifacts: ArtifactSink, stamp: LedgerStamp) -> DrainReport
  @dataclass(frozen=True)
  class DrainReport: rows: int; artifacts: int; cost_usd: Decimal; credits: Decimal; media_seconds: int
  ```
  Store (all `async`, first arg `conn: AsyncConnection`, one function per transition):
  ```python
  @dataclass(frozen=True) class RunRow: run_id, workspace_id, project_id, brand_id, project_run_id, icp_artifact_key,
      icp_artifact_sha256, icp_key, icp_version, product_selection_version, effort, committee_cap, directive_text,
      profile_ref, profile_sha256, requested_by_user_id, request_sha256, status, created_at, finished_at
  @dataclass(frozen=True) class JobRow: job_id, run_id, workspace_id, account_entity_id, status, attempt, started_at,
      finished_at, finalization: dict | None, failure_code, failure_message, model_rounds, tool_calls, cost_usd, credits,
      media_seconds
  async def create_run(conn, row: RunRow) -> bool                      # INSERT ... ON CONFLICT (run_id) DO NOTHING; True if inserted
  async def create_job(conn, *, job_id, run_id, workspace_id, account_entity_id) -> bool
  async def begin_job(conn, *, job_id) -> JobRow | None               # status -> in_progress, attempt+1, started_at=now(); None if terminal
  async def finish_job(conn, *, job_id, status: Literal["completed","needs_review"], finalization: dict,
                       failure_code: str | None = None, failure_message: str | None = None,
                       model_rounds: int, tool_calls: int, cost_usd: Decimal, credits: Decimal, media_seconds: int) -> None
  async def suspend_job(conn, *, job_id) -> None                       # status -> suspended (requeue path)
  async def refresh_run_status(conn, *, run_id) -> str                 # derived from its jobs; sets finished_at when terminal
  async def read_run(conn, *, run_id) -> RunRow | None
  async def read_job(conn, *, job_id) -> JobRow | None
  async def list_jobs(conn, *, run_id) -> tuple[JobRow, ...]
  async def record_annotations(conn, *, job_id, claim_ids_by_verdict: Mapping[str, Sequence[UUID]]) -> int
  # added by Task 5 (listed here so names match): read_persona_document(conn, *, workspace_id, brand_id, icp_key) -> DocumentRow | None;
  # read_account_catalog(conn) -> FieldCatalog; job_spend(conn, *, job_id) -> tuple[Decimal, Decimal, int]
  ```

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_provider_ledger.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal

from clue_api.arv2.provider_ledger import BufferedLedger, BufferedRawSink
from clue_api.arv2.sinks import LedgerRow, RawRecord, RawRequest, RawResponse, sha256_hex


def _record(now: datetime) -> RawRecord:
    return RawRecord(
        call_id="7b1c2e4a-0f3d-4c7e-9a1b-2d3e4f5a6b7c", provider="exa", operation="search", label="t", attempt=1,
        recorded_at=now, latency_ms=5,
        request=RawRequest(method="POST", url="https://api.exa.ai/search", headers={}, body_text='{"q":1}',
                           body_sha256=sha256_hex(b'{"q":1}'), body_bytes=7),
        response=RawResponse(status=200, headers={}, body_text="{}", body_sha256=sha256_hex(b"{}"), body_bytes=2),
    )


def test_raw_sink_ref_is_content_addressed_and_drain_clears() -> None:
    sink = BufferedRawSink()
    ref = sink.save(_record(datetime.now(UTC)), b"{}")
    assert ref == f"raw:{sha256_hex(b'{}')}"
    drained = sink.drain()
    assert [d[0] for d in drained] == [ref] and sink.drain() == []


def test_ledger_buffers_rows_in_order() -> None:
    ledger = BufferedLedger()
    row = LedgerRow(row_id="r1", call_id="c1", phase="estimate", provider="exa", operation="search",
                    label="t", recorded_at=datetime.now(UTC), estimate_usd=Decimal("0.01"))
    assert ledger.record(row) == "r1"
    assert [r.row_id for r in ledger.drain()] == ["r1"] and ledger.drain() == []
```

`tests/arv2/test_provider_ledger_db.py` (rollback_conn; a fake `ArtifactSink` returning `ArtifactRef(workspace_id, artifact_key=f"art/{sha}", sha256, media_type, byte_count)`):

```python
def test_drain_writes_ledger_rows_with_artifact_keys_and_extras() -> None:
    async def scenario():
        raw, ledger = BufferedRawSink(), BufferedLedger()
        ref = raw.save(_record(now), b'{"ok":true}')
        ledger.record(LedgerRow(row_id="r1", call_id="c1", phase="result", provider="exa", operation="search",
                                label="t", recorded_at=now, http_status=200, attempts=1, cost_usd=Decimal("0.007"),
                                outcome="ok", raw_ref=ref, extras={"costDollars": {"total": 0.007}}))
        async with rollback_conn() as conn:
            report = await drain_provider_calls(conn, raw=raw, ledger=ledger, artifacts=FakeArtifacts(),
                                                stamp=LedgerStamp("ws", "prj", "run", job_id))
            row = (await conn.execute(text("SELECT response_artifact_key, extras_json, entity_research_job_id, "
                                           "cost_usd FROM provider_call_ledger WHERE call_id = :c"), {"c": ...})).one()
        return report, row
    report, row = run_async(scenario())
    assert report.rows == 1 and report.artifacts == 1 and report.cost_usd == Decimal("0.007")
    assert row.response_artifact_key.startswith("art/") and row.extras_json == {"costDollars": {"total": 0.007}}
```

`provider_call_ledger.call_id` is `uuid`; `LedgerRow.call_id` is a string. R1 mints it as `str(uuid.uuid4())` (`calls.py:270`), so `UUID(row.call_id)` parses; a non-UUID string (a foreign ledger row) falls back to `uuid5(NAMESPACE_URL, row.call_id)`. Test both branches.

`tests/arv2/test_account_research_store_db.py`: create a run (needs a `project_run` row and an `account_entity` — use `ensure_project_run` + `insert_account_entity` inside the rollback transaction the way `tests/arv2/test_answer_key_loader_db.py` does), create two jobs, `begin_job` one (→ `in_progress`, attempt 1), `finish_job` it `completed`, assert `refresh_run_status` returns `in_progress` while the other is `not_started`, finish the other `needs_review` with a failure code, assert run status `needs_review` and `finished_at` set; `record_annotations` inserts one row per claim id (insert one claim first via `LenientClaimWriter`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/arv2/test_provider_ledger.py -q` and (env sourced) the two DB files. Expected: FAIL — module not found.

- [ ] **Step 3: `provider_ledger.py`**

```python
"""Production sinks for the R1 caller: buffer in the worker thread, land in the DB after the hop.

``ProviderCaller`` is synchronous and runs inside ``asyncio.to_thread``; its sinks are called from
that thread. Writing to Postgres from there would need a loop hand-off inside a lock the driver
already holds, so the sinks only buffer, and the async side drains them right after the hop: raw
bodies to the artifact store (one artifact per attempt: the ``RawRecord`` as JSON plus the body,
base64 when not UTF-8), ledger rows to ``provider_call_ledger`` with the job stamp.

``provider_call_ledger.entity_research_job_id`` carries the R2 ``arv2_research_job.job_id`` — the
column was named by D1 before R2 existed; its meaning is "the job that spent".
A call in flight when the runtime cap fires drains at finalization (Task 5 waits, bounded, for
in-flight hops); a lost lease can lose that hop's rows — recorded as the known residual.
"""
```

Implementation notes the code must follow: `threading.Lock` around both buffers; `save` returns `f"raw:{sha256_hex(body)}"`; the artifact payload is `json.dumps({"record": dataclasses.asdict(record) (datetimes → isoformat), "body_utf8": body.decode() or None, "body_base64": ... or None}, sort_keys=True).encode()`, `media_type="application/json"`; `INSERT INTO provider_call_ledger (ledger_id, call_id, workspace_id, project_id, project_run_id, entity_research_job_id, provider, operation, label, phase, http_status, latency_ms, attempts, estimate_usd, estimate_credits, estimate_media_seconds, cost_usd, credits, media_seconds, over_ceiling, outcome, error_code, provider_request_id, response_artifact_key, extras_json, recorded_at) VALUES (...)` with `ledger_id = uuid5(NAMESPACE_URL, f"arv2-ledger:{row.row_id}")` and `ON CONFLICT (ledger_id) DO NOTHING` (drain is idempotent under a retry); `response_artifact_key` = the artifact key whose raw_ref matches `row.raw_ref` (None when the row has no raw ref, e.g. the estimate phase); `DrainReport` sums `cost_usd/credits/media_seconds` over `phase == "result"` rows only.

- [ ] **Step 4: `account_research_store.py`**

Plain `text()` SQL, mirroring `onboarding_store.py`'s style. `begin_job`:

```sql
UPDATE arv2_research_job SET status = 'in_progress', attempt = attempt + 1, started_at = now(),
       updated_at = now()
WHERE job_id = :job_id AND status IN ('not_started', 'suspended') RETURNING *
```

`finish_job` writes status, `finished_at = now()`, `finalization_json`, `failure_code`, `failure_message`, counters, `updated_at`. `refresh_run_status`:

```sql
WITH s AS (SELECT array_agg(status) AS statuses FROM arv2_research_job WHERE run_id = :run_id)
UPDATE arv2_research_run r SET status = CASE
    WHEN 'in_progress' = ANY(s.statuses) THEN 'in_progress'
    WHEN 'not_started' = ANY(s.statuses) THEN CASE WHEN 'completed' = ANY(s.statuses) OR 'needs_review' = ANY(s.statuses) THEN 'in_progress' ELSE 'not_started' END
    WHEN 'suspended' = ANY(s.statuses) THEN 'suspended'
    WHEN 'needs_review' = ANY(s.statuses) THEN 'needs_review'
    ELSE 'completed' END,
  finished_at = CASE WHEN NOT ('in_progress' = ANY(s.statuses) OR 'not_started' = ANY(s.statuses) OR 'suspended' = ANY(s.statuses)) THEN now() ELSE NULL END
FROM s WHERE r.run_id = :run_id RETURNING r.status
```

`record_annotations` inserts `(claim_id, job_id, kind='link_audit', verdict)` rows. `JobRow.finalization` decodes `finalization_json`.

- [ ] **Step 5: Run the tests**

Expected: PASS. Then `uv run ruff check platform/api/clue_api/arv2 tests/arv2 && uv run mypy platform/api/clue_api/arv2`.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/provider_ledger.py platform/api/clue_api/arv2/account_research_store.py tests/arv2/test_provider_ledger.py tests/arv2/test_provider_ledger_db.py tests/arv2/test_account_research_store_db.py
git commit -m "feat(arv2 r2): buffered raw/ledger sinks drained to provider_call_ledger + artifacts; the run/job/annotation store"
```

---

### Task 4: Deterministic claims, the structuring intent-sweep mode, and the twelve tools

**Files:**
- Create: `platform/api/clue_api/arv2/account_research_claims.py`
- Modify: `platform/api/clue_api/arv2/structuring_client.py` (`mode` parameter; `INTENT_SWEEP_SYSTEM_PROMPT`)
- Create: `platform/api/clue_api/arv2/account_research_tools.py`
- Test: `tests/arv2/test_account_research_claims.py`, `tests/arv2/test_structuring_client.py` (extend), `tests/arv2/test_account_research_tools.py`, `tests/arv2/test_structuring_client_live.py` (extend: one live intent-sweep call over the Probook material)

**Interfaces:**
- Consumes: Task 2 `RefusalError`, `refusal_json`; Task 3 `BufferedRawSink`, `BufferedLedger`, `drain_provider_calls`, `LedgerStamp`, store `record_annotations`; R1 clients (facts-tools.md); `LenientClaimWriter`, `ClaimDraft`; `clue_research.claimstore.claims_for_runs(conn, run_ids, *, scope=WorkspaceScope.for_workspace(workspace_id))` (`WorkspaceScope` is exported by `clue_research.claimstore`).
- Produces:
  ```python
  @dataclass(frozen=True)
  class JobScope:  # everything a tool needs to know about the job it serves
      workspace_id: str; project_id: str; project_run_id: UUID; run_id: UUID; job_id: UUID
      account_id: EntityId; account_name: str; account_domain: str
      icp_markdown: str; persona_markdown: str; already_established: str
      effort: str; committee_cap: int; today: date
  class ProviderClients(Protocol):  # built per tool invocation by the driver (Task 5)
      def exa(self, caller: ProviderCaller) -> ExaClient
      def ai_ark(self, caller: ProviderCaller) -> AiArkClient
      def media(self, caller: ProviderCaller, ledger: LedgerSink) -> GeminiMediaClient
      def structuring(self, caller: ProviderCaller) -> StructuringClient
  class ToolRuntime:
      def __init__(self, *, scope: JobScope, settings: Settings, clients: ProviderClients, conn_factory: ConnFactory,
                   artifacts: ArtifactSink, writer: LenientClaimWriter, catalog: FieldCatalog,
                   media_budget: MediaBudget, transport_factory: Callable[[], Transport] = HttpxTransport,
                   now: Callable[[], datetime] = ...) -> None
      halted: dict[str, str]                       # provider -> detail; job-level latch
      finalization: dict[str, Any] | None          # set by finalize_research
      tool_calls: int                              # counter
      pending_refusals: list[ToolMessage]          # envelopes for tool calls dropped by the per-round cap (Task 5)
      async def wait_for_inflight(self, *, timeout_s: float) -> None   # awaits in-flight call_provider hops so their drains run
      async def call_provider(self, provider: str, fn: Callable[[ProviderCaller], T]) -> T
          # semaphore(provider) -> new ProviderCaller(BufferedRawSink, BufferedLedger, now) -> asyncio.to_thread(fn, caller)
          # -> finally drain_provider_calls(...) under conn_factory -> ProviderHalted => halted[provider]=detail; raise RefusalError("provider_halted:<p>")
      async def write(self, drafts: Sequence[ClaimDraft]) -> list[WriteReceipt]
      async def job_claims(self) -> Sequence[Claim]  # claims_for_runs([run_id]) filtered to account_id
      def remember_refusal(self, tool: str, args: Mapping[str, Any], envelope: str) -> None
      def repeated_refusal(self, tool: str, args: Mapping[str, Any]) -> str | None
  def build_account_tools(runtime: ToolRuntime) -> list[StructuredTool]   # the twelve, in this order
  ACCOUNT_TOOL_NAMES: tuple[str, ...] = ("read_account_state", "read_ats_board", "fetch_page", "search_web",
      "lookup_company", "lookup_people", "read_media_feeds", "research_deep", "structure_material",
      "write_claims", "verify_links", "finalize_research")
  ```
  Deterministic mappers (pure; each returns `list[ClaimDraft]`): `ats_posting_claims(postings: BoardPostings, scope)`, `ai_ark_company_claims(company: AiArkCompany, scope)`, `media_index_claim(*, person, item_url, kind, duration_s, transcript_model, speaker_verified, scope)`, `negative_claims(negatives: Sequence[NegativeOrRisk], scope)`, `structured_claims(output: StructuredOutput, *, scope, subject_url_hint: str | None)`, `fit_verdict_claims(verdicts: Sequence[Mapping], scope)`, `committee_candidate_claims(candidates: Sequence[Mapping], scope)`, `agent_claims(items: Sequence[ClaimInput], scope)`.

- [ ] **Step 1: Write the failing tests for the mappers**

```python
def test_ats_postings_become_one_tier1_claim_each_with_the_json_path() -> None:
    postings = BoardPostings(board=AtsBoard(kind="ashby", slug="zafran-security", source_url="https://www.zafran.io/careers"),
                             url="https://api.ashbyhq.com/posting-api/job-board/zafran-security",
                             postings=(JobPosting(title="Senior Manager, ABM", department="Marketing", team=None, location="USA",
                                                  published_at=date(2026, 6, 17), days_open=83, is_listed=True, compensation=None,
                                                  description_plain="Own ABM…", url="https://jobs.ashbyhq.com/zafran-security/abc",
                                                  apply_url=None),),
                             raw_ref="raw:x", ledger_row_id="r", cost=_cost())
    [draft] = ats_posting_claims(postings, SCOPE)
    assert draft.field_key == "account.open_requisitions"
    assert draft.value_json == [{"title": "Senior Manager, ABM", "dept": "Marketing", "published": "2026-06-17",
                                "days_open": 83, "still_listed": True, "url": "https://jobs.ashbyhq.com/zafran-security/abc"}]
    assert draft.extraction_method is ExtractionMethod.API and draft.signal_priority == 1
    assert draft.source_url == "https://jobs.ashbyhq.com/zafran-security/abc"
    assert draft.evidence_span == "Senior Manager, ABM — Marketing — published 2026-06-17"
    assert draft.markers["json_path"] == "jobs[0]" and draft.source_key == "ats:ashby"


def test_ai_ark_company_maps_only_registered_keys() -> None:
    company = AiArkCompany(name="Zafran Security", domain="zafran.io", linkedin="https://www.linkedin.com/company/zafran",
                           industry="Computer & Network Security", employee_count=180, revenue="$10M-$25M",
                           technologies=("HubSpot",), location={"country": "US", "city": "New York"}, raw={}, cost=_cost())
    drafts = {d.field_key: d for d in ai_ark_company_claims(company, SCOPE)}
    assert set(drafts) == {"core.company_linkedin_url", "core.industry", "core.employee_count", "core.revenue_band", "core.hq_location"}
    assert drafts["core.employee_count"].value_json == 180 and drafts["core.employee_count"].markers["json_path"] == "summary.employee_count"
    assert all(d.extraction_method is ExtractionMethod.API and d.source_key == "ai_ark:company" for d in drafts.values())


def test_negatives_are_reputation_risk_claims_born_unsafe_priority_two() -> None:
    [draft] = negative_claims([NegativeOrRisk(what="Calcalist reported acquisition talks with Cisco", status="refuted",
                                              evidence_span="Zafran denied…", source_url="https://…", outreach_safe=True)], SCOPE)
    assert draft.field_key == "account.reputation_risk" and draft.outreach_safe is False and draft.signal_priority == 2
    assert draft.value_json == {"what": "Calcalist reported acquisition talks with Cisco", "status": "refuted", "source_note": None}


def test_fit_verdicts_are_claims_born_unsafe_and_never_fail_without_contrary_evidence() -> None:
    drafts = fit_verdict_claims([{"gate": "stage", "verdict": "fail", "rationale": "not found", "claim_ids": []}], SCOPE)
    assert drafts[0].value_json["verdict"] == "unclear"   # a fail with no claim ids behind it is downgraded to unclear
    assert drafts[0].outreach_safe is False
```

Mapping table for `ai_ark_company_claims` (the only AI Ark company fields written as claims; everything else stays in `raw` and is returned to the model): `linkedin → core.company_linkedin_url (json_path link.linkedin)`, `industry → core.industry (summary.industry)`, `employee_count → core.employee_count (summary.employee_count)`, `revenue → core.revenue_band (financial.revenue)`, `location → core.hq_location (location)`. Read the exact raw paths from `ai_ark_client.company_from_record` (:349) and use those strings. `source_url = f"https://api.ai-ark.com/v1/companies?domain={domain}"` is **not** a citable URL — use `source_url=None` with `markers={"json_path": ..., "provider_record": "ai_ark"}` and `source_key="ai_ark:company"` (the lenient writer marks `source_missing`; the display layer's provider label handles provider records). `confidence=0.9`.

- [ ] **Step 2: Write the failing tests for the intent-sweep mode**

```python
def test_structure_account_intent_sweep_uses_the_sweep_prompt(scripted_caller) -> None:
    client = StructuringClient(scripted_caller, api_key=SecretStr("k"), base_url="https://openrouter.ai/api/v1", model="m")
    client.structure_account(AccountSubject("Probook", "probook.ai"), "=== MATERIAL\n…", CATALOG, mode="intent_sweep")
    sent = scripted_caller.last_request_json()
    assert "VERBATIM public statements" in sent["messages"][0]["content"]
    assert "contact.facet.recent_post" not in sent["messages"][0]["content"]  # account sweep targets account keys
```

(`ScriptedTransport` is the permitted double for wrapper arithmetic; here it only proves which prompt was sent.)

- [ ] **Step 3: Write the failing tests for the tools**

`tests/arv2/test_account_research_tools.py` builds a `ToolRuntime` with in-memory client doubles (`FakeExa`, `FakeAiArk`, `FakeStructuring`, `FakeMedia`) implementing only the methods the tools call, a `MemoryConnFactory`/`FakeWriter` that records drafts, and a `FakeArtifacts`. Tests:

```python
async def test_read_ats_board_writes_one_claim_per_posting_and_returns_them() -> None
async def test_read_ats_board_refuses_board_not_found_without_raising() -> None   # result JSON has code board_not_found
async def test_provider_halt_latches_for_the_job_and_every_later_call_is_refused_identically() -> None
async def test_identical_call_after_a_refusal_is_refused_without_a_provider_hop() -> None
async def test_write_claims_caps_at_fifty_and_marks_the_rest_refused() -> None
async def test_structure_material_writes_claims_negatives_and_returns_ids() -> None
async def test_research_deep_marks_thin_reports() -> None
async def test_finalize_twice_is_refused_finalization_already_proposed() -> None
async def test_verify_links_records_annotations_per_verdict() -> None
async def test_every_tool_wraps_unexpected_exceptions_as_tool_error_refusals() -> None
```

Each asserts on the JSON the tool returns and on the fakes' call logs.

- [ ] **Step 4: Run the tests to verify they fail**

Expected: FAIL — modules missing / unknown `mode` kwarg.

- [ ] **Step 5: `account_research_claims.py`**

Common builder:

```python
def _draft(scope: JobScope, *, field_key: str, value: JsonValue, method: ExtractionMethod, source_url: str | None,
           evidence_span: str | None, priority: int, outreach_safe: bool, confidence: float, source_key: str,
           markers: Mapping[str, JsonValue] = {}) -> ClaimDraft:
    return ClaimDraft(entity_id=scope.account_id, entity_type=EntityType.ACCOUNT, field_key=field_key, value_json=value,
                      extraction_method=method, run_id=RunId(scope.run_id), research_mode=ResearchMode.ACCOUNT_PROFILING,
                      workspace_id=scope.workspace_id, source_url=source_url, source_key=source_key,
                      evidence_span=evidence_span, observed_at=None, confidence=confidence,
                      signal_priority=priority, outreach_safe=outreach_safe, markers=dict(markers))
```

`structured_claims(output, *, scope, subject_url_hint)`: one draft per `StructuredClaim` with `method=LLM_SYNTHESIS`, `source_key="structuring"`, `markers={"evidence_verbatim": claim.evidence_verbatim, "schema_valid": claim.schema_valid, "source_kind": claim.source_kind, "media_timestamp": claim.media_timestamp, "structuring_mode": mode}`, `confidence` parsed from the model's string (`high`→0.8, `medium`→0.6, else 0.5), plus one draft per `ProposedField` under its `suggested_key` (lenient writer auto-registers it; `field_description=proposed.why`). `agent_claims(items, scope)` for `write_claims`: `method=LLM_SYNTHESIS`, `source_key="agent"`, `markers={"corrects_claim_id": item.corrects_claim_id}` when given. `fit_verdict_claims` enforces the leniency rule in code: a `fail` with empty `claim_ids` becomes `unclear` and the rationale gets the suffix " (downgraded: no contrary evidence cited)". `committee_candidate_claims` requires `confirmed_by` (a URL) for a named candidate; a candidate without one is dropped with a marker on the tool result, never written.

- [ ] **Step 6: The intent-sweep mode on the structuring client**

Add `mode: Literal["broad", "intent_sweep"] = "broad"` to `structure_account` and `structure_person`; when `intent_sweep`, the system prompt is `INTENT_SWEEP_SYSTEM_PROMPT` (the step9c text generalised: "You extract VERBATIM public statements … TASK: find every statement the SUBJECT THEMSELVES made publicly … a named software tool praised/criticised; the state of or a gap in their GTM stack; target lists / account research / outbound / ABM; a named bottleneck; a team size or hiring mandate. One row per statement, priority 1, at most 4 rows, never a placeholder, skip NOT FOUND, skip special-category material") and the reply is read by the same `read_structured_reply` (rows land as `claims` with `priority=1`; for an account subject the field key menu is the account catalog, so the model picks `account.*` keys — the prompt names `account.abm_program_maturity`, `account.gtm_tooling_stack` and `account.hiring_velocity` as the usual homes and allows a proposed field otherwise). Record `mode` in `StructuredOutput` (new field `mode: str = "broad"`). Extend the live test file with one `intent_sweep` call over `.context/arv2-clue-sample-v3/account_report.md` asserting the reply parses (yield may be zero — assert shape, not count).

- [ ] **Step 7: `account_research_tools.py`**

The tool wrapper every tool goes through:

```python
def _governed(runtime: ToolRuntime, name: str, fn: Callable[..., Awaitable[Mapping[str, Any]]]) -> Callable[..., Awaitable[str]]:
    async def call(**args: Any) -> str:
        if runtime.finalization is not None and name != "finalize_research":
            return refusal_json("finalization_already_proposed", "the decision is made")
        if (previous := runtime.repeated_refusal(name, args)) is not None:
            return previous
        runtime.tool_calls += 1
        try:
            return json.dumps(await fn(**args), default=str)
        except RefusalError as refused:
            envelope = refusal_json(refused.refusal.code, refused.refusal.detail)
        except ValidationError as invalid:
            envelope = refusal_json("invalid_arguments", str(invalid)[:500])
        except Exception as error:  # noqa: BLE001 — the failure law: never a raise into the graph
            log.exception("arv2.account_tool_failed", tool=name)
            envelope = refusal_json(f"tool_error:{type(error).__name__}", str(error)[:500])
        runtime.remember_refusal(name, args, envelope)
        return envelope
    return call
```

Tool argument models (Pydantic, `extra="forbid"`) and what each body does:

1. `ReadAccountStateArgs(section: Literal["all","claims","open_fields","icp","persona","already_established"] = "all")` → `{"account": {...}, "claims": [ {claim_id, field_key, value, quote, url, priority, outreach_safe, source_key} for this job's run ], "open_fields": [keys in the catalog with no claim yet], "icp": ..., "persona": ..., "already_established": ...}` (sections filtered).
2. `ReadAtsBoardArgs(company_url: str)` → `find_board` (raises → `board_not_found` when None), `fetch_postings` (`BoardFetchFailed` → `board_fetch_failed`), write `ats_posting_claims`, return `{"board": {...}, "postings": [title, department, location, published_at, days_open, url, description_head (600 chars)], "claim_ids": [...], "cost": call_cost}`.
3. `FetchPageArgs(url: HttpUrl, max_chars: int = Field(8000, ge=500, le=20000))` → `exa.contents([url], text_max_chars=max_chars)`; empty text → `page_unavailable`; returns `{"url", "title", "text", "raw_ref", "cost"}`.
4. `SearchWebArgs(query: str, num_results: int = Field(8, ge=1, le=10), include_domains: list[str] | None = None, start_published_date: str | None = None)` → hits `{url, title, published, text_head}`.
5. `LookupCompanyArgs(domain: str)` → `ai_ark.company_by_domain`; None → `company_not_found`; writes `ai_ark_company_claims`; returns the mapped fields, `technologies`, funding rounds found in `raw` (read the raw path from `company_from_record`), `claim_ids`, `cost`.
6. `LookupPeopleArgs(name_variants: list[str] = Field(min_length=1, max_length=4), domain: str, size: int = Field(3, ge=1, le=3))` → `ai_ark.people_by_name`; returns `{"people": [full_name, title, headline, linkedin_url, current_company, current_company_domain], "cost"}` and writes **no** claims: identity confirmation only. Committee members become claims when the agent calls `write_claims` with `field_key="account.committee_candidate"` (or through `finalize_research.committee_candidates`).
7. `ReadMediaFeedsArgs(person_name: str, person_role: str = "", feed_url: HttpUrl | None = None, youtube_url: HttpUrl | None = None, episode_title_contains: str | None = None, episode_number: int | None = None)` — at least one of `feed_url`/`youtube_url` (validator). Podcast path: `fetch_feed` → `find_episode` (None → `episode_not_found`) → `download_enclosure(episode, dest=Path(settings.arv2_raw_root)/"media"/job_id/…, max_bytes=settings.arv2_account_media_max_enclosure_mb*1024*1024)` (`EnclosureTooLarge` → `enclosure_too_large`) → `transcription_input_from_enclosure(...)` → `transcribe_short` when `duration_s <= settings.arv2_media_short_max_seconds` else `transcribe_long` (`MediaCeilingExceeded` → `media_ceiling_reached`) → `verify_speaker(transcript, context)` (unverified → write the media index claim with `speaker_verified=False` and refuse `speaker_unverified`) → `mine_quotes(transcript.text, context=..., n=6, speaker_verified=True)`; write `media_index_claim`; return `{"item": {...}, "speaker_verified": True, "quotes": [{text, timestamp}], "transcript_excerpt": first 4000 chars, "cost": [...]}`. YouTube path: `reject_native_video(url)` (raises → `native_video_rejected`), `youtube_metadata`, `youtube_words(url, page_text=lambda u: exa.contents([u]).results[0].text)`; return words (no transcription). Media calls are serialised with the media semaphore (the `MediaBudget` is unlocked).
8. `ResearchDeepArgs(charter: str = Field(min_length=200), probes: list[str] = Field(default_factory=list, max_length=6), same_name_exclusions: list[str] = Field(default_factory=list), num_results: int = Field(20, ge=10, le=25))` → system prompt = `LOCK_TEMPLATE.format(name, domain, exclusions)` + `EVIDENCE_RULES` (constants in the module, text from prompt §2 items 2–3); query = charter + "\n\nSPECIAL PROBES\n" + probes + "\n\nALREADY ESTABLISHED (do not re-derive; find what is NOT here)\n" + scope.already_established; `exa.deep_reasoning(system_prompt=..., query=..., output_schema=report_output_schema(), num_results=...)`; `thin = is_thin_deep_response(n_results=r.n_results, cost_usd=r.cost_usd, report_chars=len(r.report_text or ""))`; returns `{"report": report_text, "thin": thin, "n_results": ..., "retried": r.retried, "raw_ref", "cost"}` — a thin report is still returned (the manual row says what to do with it); `deep_thin_response` is raised only when `report_text` is empty.
9. `StructureMaterialArgs(subject_kind: Literal["account","person"], subject_name: str, subject_domain_or_company: str, linkedin_url: str | None = None, material: str = Field(min_length=50, max_length=120_000), mode: Literal["broad","intent_sweep"] = "broad", already_known: str | None = None)` → `structuring.structure_account(AccountSubject(...), material, runtime.catalog, mode=mode)` (person → `structure_person`; person claims in R2 are **account-scoped**: the tool refuses `invalid_arguments` for `subject_kind="person"` until R3 — state this in the manual); unparseable (`RawParseError`) → `structuring_unparseable`; writes `structured_claims` + `negative_claims`; returns `{"written": [{claim_id, field_key, value, quote, url, priority, outreach_safe, markers}], "proposed": [...], "negatives_written": n, "cost"}`.
10. `WriteClaimsArgs(claims: list[ClaimInput] = Field(min_length=1, max_length=50))` with `ClaimInput(field_key: str, value: JsonValue, evidence_span: str = Field(min_length=1), source_url: HttpUrl | None, priority: int = Field(ge=1, le=3), outreach_safe: bool = True, confidence: float = Field(0.6, ge=0, le=1), corrects_claim_id: str | None = None)` → `agent_claims`; `account.committee_candidate` values are validated against the enum and need `confirmed_by`; `account.reputation_risk` and `account.icp_fit_verdict` are forced `outreach_safe=False`; returns receipts.
11. `VerifyLinksArgs(claim_ids: list[str] | None = None)` → this job's claims with a `source_url` (or the given ids); per distinct URL one `exa.contents([url], text_max_chars=20000)` (cached in the runtime for the job); `substring_verdict(claim.evidence_span, text)`; a failed fetch → `fetch_failed`; `record_annotations`; returns `{"EXACT": n, "PARTIAL": n, "NOT_FOUND": [claim_ids], "fetch_failed": [urls], "cost"}`.
12. `FinalizeResearchArgs(summary: str = Field(min_length=20), fit_verdicts: list[FitVerdict] (gate: str, verdict: Literal["pass","likely","unclear","fail"], rationale: str, claim_ids: list[str] = []), gaps: list[str] = [], committee_candidates: list[CommitteeCandidate] = [])` → second call → `finalization_already_proposed`; writes `fit_verdict_claims` and `committee_candidate_claims`; sets `runtime.finalization = {"summary", "fit_verdicts", "gaps", "proposed_at"}`; returns `{"accepted": True}`.

`ToolRuntime.call_provider` is the only path to a provider; it builds `ProviderCaller(transport=self._transport_factory(), raw_sink=BufferedRawSink(), ledger=BufferedLedger(), now=self._now)` per invocation, refuses immediately with `provider_halted:<p>` when `self.halted` has the provider, runs `fn` in `asyncio.to_thread` under `self._semaphores[provider]` (`asyncio.Semaphore(1)` for `ai_ark` and `media`, `Semaphore(settings.arv2_account_provider_concurrency)` otherwise), and in `finally` drains under `self._conn_factory()` with `LedgerStamp(workspace_id, project_id, str(project_run_id), job_id)` — a `ProviderHalted` sets `self.halted[provider] = str(error)` before re-raising as `RefusalError`.

- [ ] **Step 8: Run the tests**

Expected: PASS for the pure and tool tests; the live intent-sweep test only with keys (`uv run pytest tests/arv2/test_structuring_client_live.py -k intent_sweep`, ~$0.01).

- [ ] **Step 9: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_claims.py platform/api/clue_api/arv2/structuring_client.py platform/api/clue_api/arv2/account_research_tools.py tests/arv2/
git commit -m "feat(arv2 r2): deterministic claim mappers, the structuring intent-sweep mode, and the twelve governed account tools"
```

---

### Task 5: The agent loop and the fleet driver

**Files:**
- Create: `platform/api/clue_api/arv2/account_research_agent.py`
- Create: `platform/api/clue_api/arv2/account_research_driver.py`
- Test: `tests/arv2/test_account_research_agent.py`, `tests/arv2/test_account_research_driver.py`, `tests/arv2/test_account_research_driver_db.py`

**Interfaces:**
- Consumes: Task 2 bundle/prompt; Task 3 store; Task 4 `ToolRuntime`, `build_account_tools`, `JobScope`, `ProviderClients`; `clue_gateway.OpenRouterAgentModelProvider`; `clue_config.gateway.GatewayConfig`; `clue_storage.artifacts.read_verified_artifact`; `clue_research.identity.get_account`; `clue_fleet.work_worker.{WorkContext, WorkResult}`; `clue_fleet.FleetTaskKind`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class AgentOutcome: reason: Literal["finalized", "round_cap", "runtime_cap", "model_error"]; model_rounds: int;
      tool_calls: int; error: str | None
  async def run_account_agent(*, model: BaseChatModel, system_prompt: str, tools: Sequence[StructuredTool],
                              runtime: ToolRuntime, max_model_rounds: int, max_tool_calls_per_round: int,
                              max_runtime_s: float, task_instruction: str) -> AgentOutcome
  class Arv2AccountResearchWorkHandler:
      kind = FleetTaskKind.ARV2_ACCOUNT_RESEARCH
      def __init__(self, *, settings: Settings, conn_factory: ConnFactory, artifacts: ArtifactSink, storage: StorageBackend,
                   clients: ProviderClients, model_provider: AgentModelProvider, model_id: str, writer: LenientClaimWriter,
                   store: Any = default_store, catalog_root: Path | None = None, clock: Callable[[], datetime] = ...) -> None
      async def handle(self, context: WorkContext) -> WorkResult
  def build_arv2_account_research_handler(settings: Settings, secrets: Secrets, *, storage: StorageBackend,
                                          conn_factory: ConnFactory = transaction) -> Arv2AccountResearchWorkHandler | None
  ARV2_ACCOUNT_DEDUP_PREFIX = "arv2-account-research:"; ARV2_ACCOUNT_TASK_PRIORITY = -100
  def arv2_account_work_id(job_id: UUID) -> WorkId
  ```

- [ ] **Step 1: Write the failing tests for the loop**

Use LangChain's `GenericFakeChatModel` (or a minimal `BaseChatModel` subclass) scripted with `AIMessage`s carrying `tool_calls`:

```python
async def test_round_cap_ends_the_loop_and_reports_round_cap() -> None:
    # model always calls read_account_state; cap = 3 rounds
    outcome = await run_account_agent(model=_always_calls("read_account_state", rounds=99), ..., max_model_rounds=3, ...)
    assert outcome.reason == "round_cap" and outcome.model_rounds == 3


async def test_more_than_the_per_round_cap_refuses_the_excess_not_the_round() -> None:
    # one AIMessage with 7 tool calls; cap 5 -> 5 executed, 2 get too_many_parallel_calls envelopes
    ...
    assert runtime.tool_calls == 5 and envelopes.count("too_many_parallel_calls") == 2


async def test_finalize_ends_the_loop() -> None:
    outcome = await run_account_agent(model=_calls_then_finalizes(), ...)
    assert outcome.reason == "finalized" and runtime.finalization is not None


async def test_runtime_cap_ends_with_runtime_cap_after_inflight_tools_drain() -> None:
    # a tool that sleeps 2s; max_runtime_s=0.5
    assert outcome.reason == "runtime_cap"


async def test_model_error_is_reported_not_raised() -> None:
    # model raises RuntimeError on the 2nd call
    assert outcome.reason == "model_error" and "RuntimeError" in outcome.error
```

- [ ] **Step 2: Write the failing tests for the driver**

`tests/arv2/test_account_research_driver.py` (offline; fake store, fake clients, fake model provider whose model finalizes at once):

```python
async def test_handle_marks_job_completed_with_a_receipt_and_never_raises() -> None
async def test_handle_contains_a_composition_failure_as_needs_review() -> None   # e.g. ICP artifact digest mismatch
async def test_stop_requested_requeues_as_suspended() -> None
async def test_payload_work_id_mismatch_is_a_needs_review_not_a_crash() -> None
```

`tests/arv2/test_account_research_driver_db.py` (rollback_conn; real store; fake clients + fake model): a run + job created through the store, the ICP + persona documents registered the way `answer_key_loader._knowledge_documents` does, `handle` → job `completed`, `finalization_json.reason == "finalized"`, `refresh_run_status` → `completed`, at least one `account.icp_fit_verdict` claim written.

- [ ] **Step 3: Run the tests to verify they fail**

Expected: FAIL — modules missing.

- [ ] **Step 4: `account_research_agent.py`**

```python
class _RoundShapeMiddleware(AgentMiddleware):
    """Cap the parallel wave: the first ``limit`` tool calls run, the rest get a refusal envelope."""

    def __init__(self, *, limit: int, runtime: ToolRuntime) -> None: ...

    async def awrap_model_call(self, request, handler):
        response = await handler(request)
        message = response.result[0] if isinstance(response.result, list) else response.result  # ModelResponse shape: see langchain/agents/middleware/types.py
        calls = list(getattr(message, "tool_calls", ()) or ())
        if len(calls) <= self._limit:
            return response
        kept, dropped = calls[: self._limit], calls[self._limit :]
        message.tool_calls = kept
        self._runtime.pending_refusals.extend(
            ToolMessage(content=refusal_json("too_many_parallel_calls", f"{len(dropped)} calls beyond the {self._limit}-per-round ceiling"),
                        tool_call_id=call["id"], name=call["name"], status="error")
            for call in dropped
        )
        return response


class _FinalizeEndsMiddleware(AgentMiddleware):
    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime_):
        return {"jump_to": "end"} if self._runtime.finalization is not None else None

    async def aafter_model(self, state, runtime_):
        # deliver the refusals for dropped calls as tool messages so the wave is complete
        if self._runtime.pending_refusals:
            messages, self._runtime.pending_refusals = list(self._runtime.pending_refusals), []
            return {"messages": messages}
        return None
```

Read the installed `langchain` version's `AgentMiddleware` hook signatures (`.venv/lib/python3.12/site-packages/langchain/agents/middleware/types.py`) before writing these two; the M8D `_EntityResearchRuntimeMiddleware` in `platform/agents/clue_agents/entity_research_runtime.py:580-736` is the in-repo example of every hook used here (read it, do not import it). If dropped tool-call messages cannot be injected in `aafter_model` under the installed API, implement the per-round cap inside `awrap_tool_call` instead (count executed calls per model turn via the runtime; the 51st returns the envelope without executing).

```python
async def run_account_agent(*, model, system_prompt, tools, runtime, max_model_rounds, max_tool_calls_per_round,
                            max_runtime_s, task_instruction) -> AgentOutcome:
    rounds = _RoundCounter()   # a middleware that increments in awrap_model_call
    agent = create_agent(
        model=model, tools=list(tools), system_prompt=system_prompt,
        middleware=[rounds, _RoundShapeMiddleware(limit=max_tool_calls_per_round, runtime=runtime),
                    _FinalizeEndsMiddleware(runtime), ModelCallLimitMiddleware(run_limit=max_model_rounds, exit_behavior="end")],
        name="clue-arv2-account",
    )
    try:
        await asyncio.wait_for(
            agent.ainvoke({"messages": [HumanMessage(content=task_instruction)]},
                          config={"recursion_limit": max_model_rounds * (max_tool_calls_per_round + 2) + 4}),
            timeout=max_runtime_s,
        )
    except TimeoutError:
        await runtime.wait_for_inflight(timeout_s=60)
        return AgentOutcome("runtime_cap", rounds.count, runtime.tool_calls, None)
    except Exception as error:  # noqa: BLE001
        await runtime.wait_for_inflight(timeout_s=60)
        return AgentOutcome("model_error", rounds.count, runtime.tool_calls, f"{type(error).__name__}: {error}"[:500])
    if runtime.finalization is not None:
        return AgentOutcome("finalized", rounds.count, runtime.tool_calls, None)
    return AgentOutcome("round_cap", rounds.count, runtime.tool_calls, None)
```

`ToolRuntime.wait_for_inflight` (add in this task to Task 4's class): tracks the `asyncio.Task`s of in-flight `call_provider` hops in a set and awaits them with a bound so their drains run.

- [ ] **Step 5: `account_research_driver.py`**

`handle` mirrors O3 exactly (facts-fleet.md §2.1–2.2): stop/lease check → `_scope(payload)` (`job_id`, `run_id`, `workspace_id`) → work-id check → `try: outcome = await self._run(...) except Exception: contain → needs_review`. `_run`:

1. `async with self._connection() as conn:` `job = await store.begin_job(conn, job_id=...)` (None → already terminal → return `"completed"` idempotently); `run = await store.read_run(conn, run_id=...)`; `account = await get_account(conn, EntityId(job.account_entity_id))` (None → `RuntimeError("account row missing")` → contained → needs_review); ICP body: `read_verified_artifact(conn, self._storage, storage_key=run.icp_artifact_key, workspace_id=run.workspace_id)` and refuse on digest mismatch (`ArtifactIntegrityError` → contained); persona body: the latest `brand_knowledge_document` row with `kind='audience-persona'` and `icp_key=run.icp_key` (query in the store: `read_persona_document(conn, *, workspace_id, brand_id, icp_key) -> DocumentRow | None`, added here) → `read_verified_artifact`; `already_established`: this account's live claims (`claims_for_runs` is run-scoped — use `claims_for(conn, EntityId(job.account_entity_id), scope=WorkspaceScope.for_workspace(run.workspace_id))` from `clue_research.claimstore` for the account's current claims) rendered as "- field_key: value (source)" lines, capped at 60 lines; `catalog_menu = catalog_menu_text(catalog)` where `catalog = FieldCatalog(account=[FieldSpec(key, description, schema) for the account/core rows of ARV2_PACK + the core pack keys the writer can validate])` — build it from `field_definition` rows: `SELECT field_key, description, value_schema FROM field_definition WHERE field_key LIKE 'account.%' OR field_key LIKE 'core.%'` (store function `read_account_catalog(conn) -> FieldCatalog`).
2. Profile fence: `bundle = load_account_resources(self._catalog_root)`; `if bundle.profile.sha256 != run.profile_sha256: raise RuntimeError("profile digest differs from the launch pin — relaunch")` (contained → needs_review with `failure_code="profile_pin_mismatch"`).
3. `runtime = ToolRuntime(scope=JobScope(...), settings=..., clients=self._clients, conn_factory=self._conn_factory, artifacts=..., writer=self._writer, catalog=catalog, media_budget=MediaBudget(settings.arv2_media_seconds_ceiling))`; `tools = build_account_tools(runtime)`; `model = self._models.build(model_id=self._model_id, timeout_s=settings.gateway_timeout_s, max_retries=2, max_output_tokens=8192, temperature=0.2, role="arv2_account")`; `system_prompt = build_system_prompt(bundle, AccountContext(...))`; `task_instruction = "Research this account in full: run the ladder, write every evidenced claim, run the audit, then finalize once."`.
4. `outcome = await run_account_agent(...)` under the job semaphore (`asyncio.Semaphore(settings.arv2_account_max_parallel_jobs)` shared by the handler instance, like O3's fan-out).
5. Receipt: `finalization = {"reason": outcome.reason, "summary": ..., "fit_verdicts": ..., "gaps": ..., "claims_written": n (from job_claims), "by_field": {...}, "proposed_fields": [...], "link_audit": {...}, "halted_providers": runtime.halted, "profile_sha256": ..., "manifest_sha256": bundle.manifest_sha256(), "model_id": ...}`; spend from `SELECT COALESCE(SUM(cost_usd),0), COALESCE(SUM(credits),0), COALESCE(SUM(media_seconds),0) FROM provider_call_ledger WHERE entity_research_job_id = :job_id AND phase = 'result'` (store function `job_spend`); `finish_job(status="completed" if outcome.reason != "model_error" else "needs_review", failure_code=outcome.error and "model_error", ...)`; `refresh_run_status`; one `account_activity_event` row (`kind='updated'`, `actor_kind='clue'`, `text=f"Account research {outcome.reason}: {n} claims"`, `project_id=run.project_id`).
6. Return the job status string as `WorkResult.outcome`.

`build_arv2_account_research_handler(settings, secrets, *, storage, conn_factory=transaction)`: `None` when `not settings.arv2_account_research_enabled`; requires `exa_api_key`, `openrouter_api_key`, `ai_ark_api_key`, `gemini_api_key` and `ARV2_ACCOUNT_AGENT_MODEL` in the environment — a missing one logs `arv2.account_handler_not_composed` with the exact name and returns `None` (the O3 shape). `ProviderClients` production impl `_LiveClients(settings, secrets)` builds `ExaClient(caller, key)`, `AiArkClient(caller, key, min_gap_s=settings.arv2_ai_ark_min_gap_s)`, `GeminiMediaClient(caller, openrouter_api_key=..., openrouter_base_url=settings.openrouter_base_url, gemini_api_key=..., short_model=settings.arv2_media_short_model, transcribe_model=settings.arv2_media_transcribe_model, embedding_model=settings.arv2_embedding_model, media_budget=<the runtime's>, short_max_seconds=settings.arv2_media_short_max_seconds, ledger=<the caller's ledger>)`, `StructuringClient(caller, api_key=..., base_url=..., model=settings.arv2_structuring_model)` — read the exact settings names from `settings.py` (facts-fleet.md §5). Model provider: `OpenRouterAgentModelProvider(GatewayConfig(...same fields as clue_config.gateway.default_gateway_config()... timeout_s=settings.gateway_timeout_s, openrouter_chat_completions_fallback=True), secrets.openrouter_api_key)`.

- [ ] **Step 6: Run the tests**

Expected: PASS (loop tests, offline driver tests, DB driver test with env sourced).

- [ ] **Step 7: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_agent.py platform/api/clue_api/arv2/account_research_driver.py platform/api/clue_api/arv2/account_research_tools.py platform/api/clue_api/arv2/account_research_store.py tests/arv2/
git commit -m "feat(arv2 r2): the create_agent loop with cap-to-finalize middlewares, and the arv2_account_research fleet driver"
```

---

### Task 6: Launcher, toolbelt tools, authority, CLI, fleet composition, docs

**Files:**
- Create: `platform/api/clue_api/arv2/account_research_launch.py`
- Create: `scripts/launch_arv2_account_research.py`
- Modify: `platform/api/clue_api/toolbelt_wiring.py` (`build_toolbelt` kwarg `arv2_account_launch: Arv2LaunchService | None = None`; register the two tools beside :2773)
- Modify: `platform/api/clue_api/agent_registry_wiring.py:90` (two entries), `tests/agents/test_tool_authority_audit.py:80` (120 → 122 with a comment block), `:151` area (two grant assertions)
- Modify: `platform/api/clue_api/fleet_main.py` (`_build_arv2_account_research_handler`; pass `arv2_account_research_handler=`)
- Modify: `platform/api/clue_api/arv2/README.md` (R2 section), `platform/api/clue_api/arv2/__init__.py` (exports)
- Test: `tests/arv2/test_account_research_launch_db.py`, `tests/api/test_arv2_launch_tools.py`, `tests/agents/test_tool_authority_audit.py`, `tests/arv2/test_import_guard.py` (unchanged; must stay green)

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Arv2LaunchRequest:
      workspace_id: str; project_id: str; account_entity_ids: tuple[UUID, ...]
      icp_artifact_key: str; icp_artifact_sha256: str; product_selection_version: int
      requested_by_user_id: str; effort: Literal["full","reduced","cheap-pass"] = "full"
      committee_cap: int = 5; directive_text: str = ""; project_run_id: UUID | None = None
  class Arv2LaunchRefused(Arv2Error): code: str   # lane_disabled | account_not_found:<id> | account_not_in_workspace:<id> |
      # icp_artifact_not_found | icp_artifact_not_confirmed | icp_digest_mismatch | product_selection_version_unknown | project_not_found
  @dataclass(frozen=True)
  class Arv2LaunchReceipt: run_id: UUID; job_ids: tuple[UUID, ...]; replayed: bool; project_run_id: UUID
  async def launch_arv2_account_research(conn, request: Arv2LaunchRequest, *, settings: Settings, queue: WorkQueue,
                                         profile_sha256: str, now: Callable[[], datetime]) -> Arv2LaunchReceipt
  class Arv2LaunchService(Protocol):   # what the toolbelt tool calls; production impl wraps the function with `transaction` + DbWorkQueue
      async def launch(self, request: Arv2LaunchRequest) -> Arv2LaunchReceipt
      async def read_run(self, *, workspace_id: str, run_id: UUID) -> RunRow | None  (+ jobs)
  class LaunchArv2AccountResearchTool(Tool): name = "launch_arv2_account_research"; version = "1"; effect_class = SPEND
  class ReadArv2AccountResearchRunTool(Tool): name = "read_arv2_account_research_run"; version = "1"; effect_class = READ
  def build_arv2_launch_tools(service: Arv2LaunchService | None) -> tuple[Tool, Tool]
  ```

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_account_research_launch_db.py` (rollback_conn; seed via the answer-key loader pieces: `insert_account_entity`, `ensure_project_run`, a confirmed `icp-definition` document row + artifact via `_knowledge_documents`' path, `confirm_project_product_set`; a `FakeQueue` recording `enqueue` calls):

```python
async def test_launch_creates_run_jobs_lineage_and_enqueues_one_task_per_job() -> None
    # receipt.run_id deterministic (same request twice -> replayed=True, no second enqueue), run row pins icp key/sha,
    # selection version, profile sha, effort/committee_cap; run_lineage row kind entity_research; project_account rows exist;
    # queue.enqueue called with kind ARV2_ACCOUNT_RESEARCH, dedup_key f"arv2-account-research:{job_id}", priority -100,
    # payload {job_id, run_id, workspace_id}, reopen_terminal=False
async def test_launch_refuses_lane_disabled_unknown_account_unconfirmed_icp_and_digest_mismatch() -> None
async def test_launch_needs_only_accounts_icp_ref_and_selection_version() -> None
    # a project_run with every Stage-0 pin NULL and no icp_spec / research_directive rows launches fine (standing rule item 5)
```

`tests/api/test_arv2_launch_tools.py`: `LaunchArv2AccountResearchTool(None).preconditions` → `arv2_account_research_not_composed`; with a service but `ctx.action_ref is None` → `launch_action_ref_missing`; `invoke` maps the input to `Arv2LaunchRequest` and returns `{"run_id", "job_ids", "replayed"}`; `Arv2LaunchRefused` → `PreconditionFailed([PreconditionFailure(code, message)])` (a typed, actionable refusal, seam 1 §1.3).

`tests/agents/test_tool_authority_audit.py`: `== 122`; `C6_AGENT_TOOL_AUTHORITY["launch_arv2_account_research"] == (AgentRole.HEAD_OF_ABM,)`; `["read_arv2_account_research_run"] == (AgentRole.HEAD_OF_ABM,)`.

- [ ] **Step 2: Run the tests to verify they fail**

Expected: FAIL — module missing; authority count 120.

- [ ] **Step 3: `account_research_launch.py`**

`launch_arv2_account_research`:

1. `if not settings.arv2_account_research_enabled: raise Arv2LaunchRefused("lane_disabled", "CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED is false")`.
2. Accounts: for each id `get_account(conn, EntityId(id))`; None → `account_not_found:<id>`; the row's workspace (read `SELECT workspace_id FROM account_entity WHERE id = :id`) ≠ request → `account_not_in_workspace:<id>`.
3. ICP: `SELECT document_id, kind, status, artifact_key, artifact_sha256, path FROM brand_knowledge_document WHERE workspace_id = :w AND artifact_key = :key` → none → `icp_artifact_not_found`; `kind != 'icp-definition'` or `status != 'confirmed'` → `icp_artifact_not_confirmed`; `artifact_sha256 != request.icp_artifact_sha256` → `icp_digest_mismatch`; `brand_id` from the row; `icp_key`, `icp_version` from `parse_front_matter(read_verified_artifact(...)[1].decode())` (`front["icp_key"]`, `int(front["version"])`).
4. Product set: `list_project_product_sets(conn, workspace_id=..., project_id=...)`; the requested version must be one of them → else `product_selection_version_unknown`.
5. Project run: `request.project_run_id` or `uuid5(NAMESPACE_URL, f"arv2-project-run:{project_id}:{icp_key}:{icp_version}")`; `ensure_project_run(conn, project_run_id=..., project_id=..., workspace_id=..., icp_key=..., icp_version=..., phase=ProjectPhase.DEEP)` (its INSERT fails silently when the project row is missing → verify afterwards with `get_project_run`; missing → `project_not_found`).
6. `request_sha = sha256(canonical json of {workspace_id, project_id, sorted account ids, icp_artifact_sha256, product_selection_version, effort, committee_cap, directive_text, profile_sha256})`; `run_id = uuid5(_RUN_NS, request_sha)`; `create_run(...)` → `replayed = not inserted`; `record_run_lineage(conn, run_id=run_id, workspace_id=..., kind="entity_research", project_id=..., project_run_id=...)`; per account: `ensure_project_account(conn, workspace_id=..., project_id=..., account_entity_id=..., added_via="manual")`, `job_id = uuid5(_JOB_NS, f"{run_id}:{account_id}")`, `create_job(...)`, and `await queue.enqueue(kind=FleetTaskKind.ARV2_ACCOUNT_RESEARCH, work_id=arv2_account_work_id(job_id), dedup_key=f"{ARV2_ACCOUNT_DEDUP_PREFIX}{job_id}", priority=ARV2_ACCOUNT_TASK_PRIORITY, payload={"job_id": str(job_id), "run_id": str(run_id), "workspace_id": ...}, reopen_terminal=False)`.

The toolbelt tools follow `LaunchAccountResearchTool` (facts-tools.md §1.10) exactly: `ToolInput` with `project_id: str`, `account_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=200)`, `icp_artifact_key: str`, `icp_artifact_sha256: str`, `product_selection_version: int = Field(ge=1)`, `effort: Literal[...] = "full"`, `committee_cap: int = Field(5, ge=1, le=12)`, `directive_text: str = ""`; `ToolOutput(run_id: str, job_ids: tuple[str, ...], replayed: bool)`; `ReplaySafety(policy=DOMAIN_IDEMPOTENT, durable_identity="workspace + project + account set + ICP digest + product-set version + profile digest")`; `parameter_policy=JournalParameterPolicy(safe_display_fields=("project_id", "account_entity_ids", "icp_artifact_key", "product_selection_version", "effort", "committee_cap"))`; `pin_requirements = ()` (no Stage-0 pin — standing rule); `model_description` states that a success means enqueued, never that research completed, and that the human approved the launch in the current action. `requested_by_user_id = ctx.actor_id`. The read tool returns the run row + job states for project context (seam 1 reverse edge).

- [ ] **Step 4: Registration, authority, fleet composition**

`toolbelt_wiring.build_toolbelt(..., arv2_account_launch: Arv2LaunchService | None = None)`: `for tool in build_arv2_launch_tools(arv2_account_launch): registry.register(tool, make_default=True)`. `agent_registry_wiring.C6_AGENT_TOOL_AUTHORITY`: `"launch_arv2_account_research": (AgentRole.HEAD_OF_ABM,)`, `"read_arv2_account_research_run": (AgentRole.HEAD_OF_ABM,)` (O6 adds them to the Head-of-ABM profile; the grant is the authority decision). `fleet_main`: `_build_arv2_account_research_handler = build_arv2_account_research_handler(settings, secrets, storage=storage)` and `build_multi_work_worker(..., arv2_account_research_handler=...)`. The production `Arv2LaunchService` (`DbArv2LaunchService(settings, storage, queue=DbWorkQueue())`, in the same module) is composed wherever `build_toolbelt` is called with real secrets (the projections app root and `fleet_main`) behind `settings.arv2_account_research_enabled`.

- [ ] **Step 5: The CLI**

`scripts/launch_arv2_account_research.py`: `--workspace ws_arv2_answer_key --project prj_arv2_answer_key --accounts probook.ai,zafran.io --effort full --committee-cap 5 [--directive "..."] [--project-run-id <uuid>]`; resolves accounts by `primary_domain` in the workspace, the ICP as the latest `confirmed` `icp-definition` row for the project's brand, the selection version as `current_project_product_set(...).selection_version`, calls `launch_arv2_account_research` inside `transaction()` with `DbWorkQueue()`, prints the receipt as JSON. Reads env via `Settings()`/`Secrets()` (the workspace `.env` sourced by the caller).

- [ ] **Step 6: README + exports**

README: an "R2 — the account research agent" section: module map (the nine new modules), the failure law, the one-caller-per-invocation rule and buffered drain, the job states, the launch signature, the flag, the model env lines, and the known residual (a lease lost mid-hop can lose that hop's ledger rows). `__init__.py` exports the public names above.

- [ ] **Step 7: Run the tests and the static gates**

`uv run pytest tests/arv2 tests/agents/test_tool_authority_audit.py tests/api/test_arv2_launch_tools.py --ignore-glob='*_live.py' -p no:cacheprovider -q` (env sourced for the DB files); `uv run ruff check . && uv run ruff format --check . && uv run mypy platform/api && uv run lint-imports`. Expected: green (the two pre-existing base env-parity failures excepted, recorded).

- [ ] **Step 8: Commit**

```bash
git add platform/api/clue_api/arv2/account_research_launch.py scripts/launch_arv2_account_research.py platform/api/clue_api/toolbelt_wiring.py platform/api/clue_api/agent_registry_wiring.py platform/api/clue_api/fleet_main.py platform/api/clue_api/arv2/README.md platform/api/clue_api/arv2/__init__.py tests/
git commit -m "feat(arv2 r2): launch_arv2_account_research (seam-1 signature, typed refusals), the two Head-of-ABM toolbelt tools, CLI launcher, fleet composition"
```

---

### Task 7: The acceptance run (founder-triggered; spends ≈ $0.50 + AI Ark credits)

**Do not execute without the founder's explicit go.** It is the R2 exit gate (master plan §9): Probook and Zafran researched end to end, ≥15 claims each with quotes and URLs, the negatives section present, on the account screens.

- [ ] **Step 1: Preconditions**
  - AI Ark people credit active (re-run `uv run pytest tests/arv2/test_ai_ark_client_live.py -q` first; all green).
  - `.env`: `CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED=true`, `ARV2_ACCOUNT_AGENT_MODEL` set, all four provider keys set; throwaway DB `clue_san-salvador` at head.
  - Reload the answer key so the softened ICP is the confirmed version: `make db-fresh && uv run alembic upgrade head && uv run python scripts/load_arv2_answer_key.py` (the loader's own CLI; record the ids it prints).
- [ ] **Step 2: Start the fleet worker** in this worktree: `set -a; source .env; set +a; uv run python -m clue_api.fleet_main > /tmp/san-salvador_fleet.log 2>&1 &` and confirm the log shows the `arv2_account_research` handler composed.
- [ ] **Step 3: Launch** `uv run python scripts/launch_arv2_account_research.py --workspace ws_arv2_answer_key --project prj_arv2_answer_key --accounts probook.ai,zafran.io --effort full --committee-cap 5`.
- [ ] **Step 4: Watch** `SELECT job_id, status, attempt, model_rounds, tool_calls, cost_usd, credits FROM arv2_research_job` until both jobs are terminal (≤ 30 min each). If a job loops, read its ledger and the model transcript from the worker log before touching any setting — the ruling is observe, then fix the cause.
- [ ] **Step 5: Verify the exit gate**
  - `SELECT field_key, count(*) FROM claim WHERE run_id = :run_id GROUP BY 1` — ≥15 claims per account with `evidence_span IS NOT NULL AND source_url IS NOT NULL`; at least one `account.reputation_risk` per account; four `account.icp_fit_verdict` per account; `account.open_requisitions` present for Zafran (Ashby board).
  - `SELECT provider, count(*), sum(cost_usd), sum(credits) FROM provider_call_ledger WHERE entity_research_job_id IN (...) GROUP BY 1`.
  - Screens: if D3 (`track-d3`) is merged, open both account pages; else run `uv run python scripts/generate_arv2_display.py` for each account (D2's CLI; flags per `platform/api/clue_api/arv2/README.md` §D2) and record the screen check as owed.
- [ ] **Step 6: Evidence** into `.context/arv2-r2-acceptance/`: the two finalization receipts, the ledger totals, the claim counts, one dossier's raw deep report artifact, the worker log excerpt; append the numbers to `_memory/2026-09-08-arv2-r2-account-agent.md`; commit the note only.
- [ ] **Step 7: Close R2** — flip `arv2_account_research_enabled` default to `True` in `settings.py` and `.env.example` (the R1 ruling: true once R2 is over); update master plan §9 R2 row status; commit `chore(arv2 r2): lane flag default on — R2 exit gate met`.

---

## Decisions recorded by this plan (for the reviewer and the memory note)

1. **Own rows and own kind, not the M8D substrate** — facts-jobs.md §DECISION, facts-agent.md §DECISION.
2. **`structure_material` writes directly.** The substance §3.4.3 said the agent reviews field meaning before writing. Echoing every extracted claim through the model would re-type verbatim spans (the fabrication risk R1 was built to remove) and double the tokens, so the tool writes what the structuring pass produced (the PoC's proven lane) and the agent corrects by writing a new claim with `corrects_claim_id`. `dossier.md` states this.
3. **Stop-policy numbers live in env settings, not in `profile.md`.** The entity-research profile is bytes that are hashed, never parsed; the model rule "a change is an env change, never a profile version" applies to limits too. `profile.md` states the policy in words and names the env keys.
4. **No filesystem workspace.** ICP, persona, catalog and already-established text are system-prompt sections plus `read_account_state`; the substance's `context/*.md` names survive as section headings.
5. **Person subjects are refused in R2.** `structure_material(subject_kind="person")` returns `invalid_arguments` until R3 composes contact entities; committee members are account-level `account.committee_candidate` claims.
6. **Fit verdicts are claims** (`account.icp_fit_verdict`, born `outreach_safe=false`) and a `fail` without cited contrary evidence is downgraded to `unclear` in code, so leniency does not depend on the model.
