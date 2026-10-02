# ARV2 R4 — Verified Account Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A discovery run on the fleet builds a long list of companies from the project's pinned ICP with Exa Websets, verifies every company on every ICP hard gate with Exa Answer (quote, URL, date, three code guards), writes the verified companies as candidate accounts with an honest project-relative fit the existing accounts table already shows, runs a relaxed pass when the strict pass falls short, and can be started from the project chat by the Head of ABM.

**Architecture:** One new fleet kind `arv2_discovery` with two ARV2 tables (`arv2_discovery_run`, `arv2_discovery_candidate`); a thin Websets client and an `answer()` method on the existing Exa client, both through the lane's `ProviderCaller` (raw saved, ledgered, halted); a pure brief compiler (ICP document → query + criteria + gates) and a pure verifier (Answer JSON + citations → guarded verdict, fit, disposition); a discovery launch with replay and a launch tool granted to the Head of ABM by a v45 profile bump; approval stays the existing "Add to project" bulk action, which now stamps the candidate row. No frontend change.

**Tech Stack:** Python 3.12, `clue_api.arv2` (ProviderCaller, LenientClaimWriter, store patterns), `clue_fleet` (LeasedWorkWorker, DbWorkQueue), SQLAlchemy async `text()` SQL, Alembic (hash ids), pytest with `rollback_conn` / `pytest_db` / `run_async`, `ScriptedTransport` for offline provider tests, YAML/JSON catalog files.

**Spec:** `docs/superpowers/plans/2026-09-10-arv2-r4-discovery-substance.md` (rev 5, rulings ledger §9). Evidence the design rests on: `.context/arv2-websets-experiment/answer/answer_evaluation.md`, `.context/arv2-websets-experiment/hybrid/hybrid_evaluation.md`.

## Global Constraints

- **The ICP document is the program** (spec §1): no gate logic in code. Gate questions are the ICP's own `rule` + `test` text; pattern code only reads structured JSON (Websets items, Answer output). The one regex over ICP text is the window parser (`(\d+)\s*months`), which parses policy, not web prose.
- **Three guards and nothing else** (spec §3): quote on the cited page (normalised), cited domain is the company's or the page names the company, `evidence_date` inside the gate's window. Absence of a source is `unclear`, never `fail`. Aggregator job sites count (ruling 5′).
- **No spend caps, no money stops** (ruling 3): every call on the provider ledger with its cost; the pre-spend estimate is raised before the wire as a recorded fact.
- **No frontend change of any kind** (rev 3/4 rulings). Discovery shows itself through `account.scoring.fit` (Overall fit High/Medium/Low + Fit score) and the ordinary firmographic claims only. Parity with `clue-frontend/live-backend-v1`.
- **Unapproved ≠ rejected** (ruling 1′): no "rejected" label anywhere; an earlier unapproved candidate of the same project is not re-surfaced (`disposition = 'not_chosen_before'`, no spend).
- **No per-run concurrency cap** (ruling 3′). **Websets exclusion import deferred** (ruling 1′); local domain dedupe always.
- **ARV2 rows only.** Never touch the old `discovery_*` tables or `clue_research.adapters.exa_websets`. `clue_api.arv2` imports only the prefixes `tests/arv2/test_import_guard.py` allows (`clue_api.arv2`, `clue_core`, `clue_config`, `clue_obs`, `clue_storage`, `clue_db`, `clue_gateway`, `clue_locks`, `clue_fleet`, `clue_spine`, `clue_research.claimstore`, `clue_research.identity`, `clue_research.membership`, `clue_research.durable.project_run` — read the test's tuple before adding an import).
- **Env parity:** every new `Settings` field appears in `.env.example` with its default the moment it is introduced, and is mirrored into the lane's local `.env`. New keys: `CLUE_ARV2_DISCOVERY_ENABLED=false`, `CLUE_ARV2_DISCOVERY_STRICT_COUNT=35`, `CLUE_ARV2_DISCOVERY_RELAXED_AUTO=true`, `CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS=geography,stage`, `CLUE_ARV2_DISCOVERY_ANSWER_MODEL=exa`, `CLUE_ARV2_DISCOVERY_POLL_INTERVAL_S=15`, `CLUE_ARV2_DISCOVERY_WALL_S=1800`, `CLUE_ARV2_DISCOVERY_WEBSETS_USD_PER_CREDIT=0.00449`. The lane's `.env` sets `CLUE_ARV2_DISCOVERY_ENABLED=true`.
- **Alembic:** one migration, hash id off head `71e80c777cf6`, reversible, `alembic heads` = 1; smoke up→down→up on a throwaway DB on `localhost:55040` only (never `clue_semarang`).
- **Tests:** offline suites only, `--ignore-glob='*_live.py'`, `-p no:cacheprovider`; DB suites only on the lane's throwaway DB `clue_san-salvador` (`CLUE_DATABASE_URL` from the lane `.env`); never `make check`, never a broad `pytest` with provider keys sourced, never run `*_live.py`.
- **Skill and prompt wording is founder-reviewed.** Task 8's skill passage is shown to the founder in chat by the controller (Fable) before the implementer writes the file.
- **Implementers are Opus subagents; Fable reviews every diff personally.** Never bare `git stash`. One commit per task with the message given. Never push. No AI attribution in commits.
- **Every provider response saved raw before parsing; every call ledgered** (master plan Appendix A laws 1–2) — automatic when calls go through `ProviderCaller`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `alembic/versions/<hash>_arv2_r4_discovery.py` | **Create.** `fleet_task_kind` gains `arv2_discovery`; tables `arv2_discovery_run`, `arv2_discovery_candidate`. Reversible. |
| `platform/fleet/clue_fleet/enums.py` | **Modify.** `FleetTaskKind.ARV2_DISCOVERY = "arv2_discovery"`. |
| `platform/api/clue_api/arv2/discovery_store.py` | **Create.** Row dataclasses + all SQL for the two tables (create/read/begin/finish run; upsert/verdict/list candidates; unapproved memory; approval stamp). |
| `platform/api/clue_api/arv2/exa_client.py` | **Modify.** `answer_body`, `ExaCitation`, `ExaAnswerResult`, `ExaClient.answer()`, `ANSWER_ESTIMATE_USD`. |
| `platform/api/clue_api/arv2/exa_websets_client.py` | **Create.** `ExaWebsetsClient` (create, get, items, add_search), item/search views, credit cost reader, halt rule. |
| `platform/api/clue_api/arv2/discovery_brief.py` | **Create.** `Gate`, `DiscoveryBrief`, `compile_brief(front, body, criteria_gate_keys)`, `parse_window_months`. Pure. |
| `platform/api/clue_api/arv2/discovery_verifier.py` | **Create.** `SYSTEM_PROMPT`, `OUTPUT_SCHEMA`, `gate_question`, `website_question`, `apply_guards`, `fit_score`, `disposition`, `normalise`. Pure. |
| `platform/api/clue_api/arv2/discovery_launch.py` | **Create.** `Arv2DiscoveryRequest`, `Arv2DiscoveryReceipt`, `launch_arv2_discovery`, `request_relaxed_pass`, `enqueue_discovery_run`, `read_pinned_icp`, `DbArv2DiscoveryService`, `LaunchArv2DiscoveryTool`, `build_arv2_discovery_tools`. |
| `platform/api/clue_api/arv2/discovery_driver.py` | **Create.** `Arv2DiscoveryWorkHandler` (kind `ARV2_DISCOVERY`), `DiscoveryClients`, `build_arv2_discovery_handler`. |
| `platform/api/clue_api/arv2/fleet_task.py` | **Modify.** `ARV2_DISCOVERY_DEDUP_PREFIX`, `ARV2_DISCOVERY_TASK_PRIORITY`, `arv2_discovery_work_id`. |
| `platform/api/clue_api/arv2/__init__.py` | **Modify.** Export the new public names. |
| `platform/api/clue_api/fleet_main.py`, `platform/api/clue_api/fleet_wiring.py` | **Modify.** Compose and register the discovery handler behind `arv2_discovery_enabled`. |
| `platform/api/clue_api/toolbelt_wiring.py`, `projections_main.py` | **Modify.** Register `launch_arv2_discovery@1`; compose `DbArv2DiscoveryService` where the lane is. |
| `platform/api/clue_api/frontend_read/bulk_actions.py` | **Modify.** After `ensure_project_accounts`, stamp candidate rows approved. |
| `libs/clue-config/clue_config/settings.py`, `.env.example`, lane `.env` | **Modify.** The eight settings above. |
| `scripts/launch_arv2_discovery.py` | **Create.** CLI: launch, `--relaxed-pass <run_id>`, `--report <run_id>`. |
| `platform/agents/catalog/profiles/head-of-abm/v45/profile.yaml`, `skills/stage0-interview/v22/SKILL.md` | **Create.** The profile bump and the skill with the discovery passage. |
| `platform/api/clue_api/agent_registry_wiring.py`, `recipe_contracts.py`, `recipe_wiring.py`, `stage0_recipe.py`, `platform/execution/recipes/recipe0-stage0-v23.json`, `chat/composer_context.py` | **Modify/Create.** Active version v45, authority map, withheld set, standing address, recipe v23 promoted, project pin for the tool. |
| `platform/api/clue_api/arv2/README.md`, `docs/specs/ARV2-MASTER-PLAN.md`, `_memory/2026-09-10-arv2-r4-discovery.md`, `_memory/README.md` | **Modify/Create.** R4 section, R4 row, close-out. |
| Tests | `tests/db/test_arv2_r4_migration.py`, `tests/arv2/test_discovery_store_db.py`, `tests/arv2/test_exa_client.py` (extend), `tests/arv2/test_exa_websets_client.py`, `tests/arv2/test_discovery_brief.py`, `tests/arv2/test_discovery_verifier.py`, `tests/arv2/test_discovery_launch_db.py`, `tests/arv2/test_discovery_driver.py`, `tests/arv2/test_discovery_driver_db.py`, `tests/api/test_frontend_bulk_actions_discovery_db.py`, plus the registry/recipe/catalog/authority/toolbelt tests re-pinned. |

---

### Task 1: Baseline, settings and env parity

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (the ARV2 block, after `arv2_person_media_max_items` ~line 365)
- Modify: `.env.example` (the ARV2 block, after `CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS=3` ~line 163)
- Modify: the lane's local `.env` (same keys; `CLUE_ARV2_DISCOVERY_ENABLED=true`)
- Test: `tests/arv2/test_settings.py` (extend)

**Interfaces:**
- Produces on `Settings`: `arv2_discovery_enabled: bool = False`, `arv2_discovery_strict_count: int = 35` (ge=1), `arv2_discovery_relaxed_auto: bool = True`, `arv2_discovery_criteria_gate_keys: str = "geography,stage"`, `arv2_discovery_answer_model: str = "exa"`, `arv2_discovery_poll_interval_s: float = 15.0` (gt=0), `arv2_discovery_wall_s: int = 1800` (ge=60), `arv2_discovery_websets_usd_per_credit: Decimal = Decimal("0.00449")`.

- [ ] **Step 1: Baseline.** From the worktree: `uv run pytest tests/arv2 tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py tests/agents/test_catalog.py --ignore-glob='*_live.py' -p no:cacheprovider -q`. Record the pass/fail counts in the SDD ledger. Known pre-existing reds (leave them): `test_design_profile_resolves_with_the_full_granted_write_surface` (design model id), the toolbelt `_MATRIX` drift pair if still red, the two `tests/execution/test_recipes.py` seeding contracts.

- [ ] **Step 2: Write the failing settings test** in `tests/arv2/test_settings.py`:

```python
def test_discovery_settings_defaults_and_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)
    assert settings.arv2_discovery_enabled is False
    assert settings.arv2_discovery_strict_count == 35
    assert settings.arv2_discovery_relaxed_auto is True
    assert settings.arv2_discovery_criteria_gate_keys == "geography,stage"
    assert settings.arv2_discovery_answer_model == "exa"
    assert settings.arv2_discovery_poll_interval_s == 15.0
    assert settings.arv2_discovery_wall_s == 1800
    assert settings.arv2_discovery_websets_usd_per_credit == Decimal("0.00449")
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_STRICT_COUNT", "12")
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS", "geography")
    loaded = Settings(_env_file=None)
    assert loaded.arv2_discovery_enabled is True
    assert loaded.arv2_discovery_strict_count == 12
    assert loaded.arv2_discovery_criteria_gate_keys == "geography"


def test_every_discovery_setting_is_in_env_example() -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    for key in (
        "CLUE_ARV2_DISCOVERY_ENABLED=false",
        "CLUE_ARV2_DISCOVERY_STRICT_COUNT=35",
        "CLUE_ARV2_DISCOVERY_RELAXED_AUTO=true",
        "CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS=geography,stage",
        "CLUE_ARV2_DISCOVERY_ANSWER_MODEL=exa",
        "CLUE_ARV2_DISCOVERY_POLL_INTERVAL_S=15",
        "CLUE_ARV2_DISCOVERY_WALL_S=1800",
        "CLUE_ARV2_DISCOVERY_WEBSETS_USD_PER_CREDIT=0.00449",
    ):
        assert key in example, key
```

- [ ] **Step 3: Run it to see it fail.** `uv run pytest tests/arv2/test_settings.py -q -p no:cacheprovider` → FAIL (attribute missing).

- [ ] **Step 4: Add the fields** in `settings.py` after `arv2_person_media_max_items`, each with a one-line comment naming the spec section:

```python
    # ARV2 Track R, R4 — verified account discovery (spec §2–§4). Off by default: a worker composes
    # the discovery handler only when this is on AND CLUE_EXA_API_KEY is configured.
    arv2_discovery_enabled: bool = False
    #: The strict pass's Websets ask (ruling 4: 35 for a target of 20 while precision is measured).
    arv2_discovery_strict_count: int = Field(default=35, ge=1)
    #: Run the relaxed pass automatically when the strict pass falls short (ruling, rev 5).
    arv2_discovery_relaxed_auto: bool = True
    #: Comma-separated ICP hard-gate keys used as Websets criteria (≤ 3, page-answerable). The
    #: ICP body's buyer sentence fills the third slot when fewer are named.
    arv2_discovery_criteria_gate_keys: str = "geography,stage"
    #: Exa Answer model for gate verification (`exa`, `exa-pro`, `exa-fast`).
    arv2_discovery_answer_model: str = "exa"
    arv2_discovery_poll_interval_s: float = Field(default=15.0, gt=0)
    arv2_discovery_wall_s: int = Field(default=1800, ge=60)
    #: Websets bill 10 credits per all-green result; this is the plan's dollar rate per credit.
    arv2_discovery_websets_usd_per_credit: Decimal = Field(default=Decimal("0.00449"), ge=0)
```

(`from decimal import Decimal` if not already imported.) Add the eight lines to `.env.example` under a `# --- ARV2 R4 discovery ---` comment after `CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS=3`, defaults as in Global Constraints. Add the same eight to the lane's `.env` with `CLUE_ARV2_DISCOVERY_ENABLED=true`.

- [ ] **Step 5: Run to pass.** `uv run pytest tests/arv2/test_settings.py -q -p no:cacheprovider` → PASS.

- [ ] **Step 6: Commit.** `git add libs/clue-config/clue_config/settings.py .env.example tests/arv2/test_settings.py && git commit -m "feat(arv2 r4): discovery settings with .env.example parity"`

---

### Task 2: Migration, fleet kind, and the discovery store

**Files:**
- Create: `alembic/versions/<hash>_arv2_r4_discovery.py` (mint with `uv run alembic revision -m "arv2 r4 discovery"`; `down_revision = "71e80c777cf6"`)
- Modify: `platform/fleet/clue_fleet/enums.py` (add the member after `ARV2_ACCOUNT_RESEARCH`, docstring bullet too)
- Create: `platform/api/clue_api/arv2/discovery_store.py`
- Test: `tests/db/test_arv2_r4_migration.py`, `tests/arv2/test_discovery_store_db.py`

**Interfaces (produces):**

```python
# discovery_store.py
DiscoveryStatus = Literal["not_started", "in_progress", "needs_review", "completed", "suspended"]
Pass = Literal["strict", "relaxed"]
Disposition = Literal["pending", "pass", "partial", "unclear", "duplicate_of_existing", "not_chosen_before"]

@dataclass(frozen=True)
class DiscoveryRunRow:
    run_id: UUID; workspace_id: str; project_id: str; brand_id: str; project_run_id: UUID
    icp_artifact_key: str; icp_artifact_sha256: str; icp_key: str; icp_version: int
    requested_by_user_id: str; request_sha256: str
    target_count: int; strict_count: int; relaxed_enabled: bool; criteria_gate_keys: tuple[str, ...]
    status: DiscoveryStatus = "not_started"; relaxed_requested: bool = False
    webset_id: str | None = None; asked: int | None = None; found_strict: int | None = None
    found_relaxed: int | None = None; analyzed: int | None = None; recall_estimate: int | None = None
    receipt: Mapping[str, Any] | None = None
    created_at: datetime | None = None; started_at: datetime | None = None; finished_at: datetime | None = None

@dataclass(frozen=True)
class CandidateRow:
    candidate_id: UUID; run_id: UUID; workspace_id: str; project_id: str; pass_: Pass
    domain: str; websets_url: str | None; name: str; provider_snapshot: Mapping[str, Any]
    verdicts: tuple[Mapping[str, Any], ...] = (); fit: float | None = None
    disposition: Disposition = "pending"; decision: str | None = None
    decided_by_user_id: str | None = None; decided_at: datetime | None = None
    account_entity_id: UUID | None = None

async def create_discovery_run(conn, row: DiscoveryRunRow) -> bool            # ON CONFLICT (run_id) DO NOTHING
async def find_discovery_run(conn, *, workspace_id: str, request_sha256: str) -> DiscoveryRunRow | None
async def read_discovery_run(conn, *, run_id: UUID) -> DiscoveryRunRow | None
async def begin_discovery_run(conn, *, run_id: UUID) -> DiscoveryRunRow | None   # not_started|suspended → in_progress, started_at=now()
async def request_relaxed(conn, *, run_id: UUID) -> bool                         # completed|needs_review → not_started, relaxed_requested=true
async def suspend_discovery_run(conn, *, run_id: UUID) -> None
async def record_webset(conn, *, run_id: UUID, webset_id: str, asked: int, recall_estimate: int | None) -> None
async def finish_discovery_run(conn, *, run_id: UUID, status: DiscoveryStatus, found_strict: int, found_relaxed: int, analyzed: int, receipt: Mapping[str, Any]) -> None
async def upsert_candidate(conn, row: CandidateRow) -> UUID                     # ON CONFLICT (run_id, domain) DO UPDATE snapshot/name/websets_url; returns candidate_id
async def record_verdicts(conn, *, candidate_id: UUID, verdicts: Sequence[Mapping[str, Any]], fit: float | None, disposition: Disposition, account_entity_id: UUID | None) -> None
async def list_candidates(conn, *, run_id: UUID) -> tuple[CandidateRow, ...]
async def unapproved_domains(conn, *, workspace_id: str, project_id: str, before_run_id: UUID) -> frozenset[str]
async def mark_candidates_approved(conn, *, workspace_id: str, project_id: str, account_entity_ids: Sequence[UUID], decided_by_user_id: str) -> int
```

- [ ] **Step 1: Write the failing migration test** `tests/db/test_arv2_r4_migration.py` (copy the imports and `run_async` use from `tests/db/test_arv2_r2_migration.py`):

```python
def test_fleet_kind_and_r4_tables_exist() -> None:
    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                labels = [
                    row[0]
                    for row in await conn.execute(
                        text("SELECT unnest(enum_range(NULL::fleet_task_kind))::text")
                    )
                ]
                assert "arv2_discovery" in labels
                assert FleetTaskKind.ARV2_DISCOVERY.value == "arv2_discovery"
                for table in ("arv2_discovery_run", "arv2_discovery_candidate"):
                    exists = await conn.scalar(text("SELECT to_regclass(:t)"), {"t": table})
                    assert exists is not None, table
    run_async(scenario())


def test_candidate_domain_is_unique_per_run_and_dispositions_are_closed() -> None:
    async def scenario() -> None:
        async with db_lifespan():
            async with rollback_conn() as conn:
                checks = {
                    row[0]
                    for row in await conn.execute(
                        text("SELECT conname FROM pg_constraint WHERE conrelid = 'arv2_discovery_candidate'::regclass")
                    )
                }
                assert "arv2_discovery_candidate_run_domain" in checks
                assert "arv2_discovery_candidate_disposition" in checks
    run_async(scenario())
```

- [ ] **Step 2: Run it.** `uv run pytest tests/db/test_arv2_r4_migration.py -q -p no:cacheprovider` → FAIL.

- [ ] **Step 3: Add the enum member** in `enums.py`: `ARV2_DISCOVERY = "arv2_discovery"` right after `ARV2_ACCOUNT_RESEARCH`, with a docstring bullet: "one ARV2 discovery run (Track R, R4): Websets long list, Answer verification, candidate accounts". `tests/fleet/test_fleet_db.py::…labels == [k.value for k in FleetTaskKind]` will now require the migration.

- [ ] **Step 4: Write the migration** (copy the R2 precedent's enum handling exactly):

```python
"""arv2 r4: verified account discovery — fleet kind, discovery runs and candidates

Revision ID: <hash>
Revises: 71e80c777cf6
"""
from __future__ import annotations
from collections.abc import Sequence
from alembic import op

revision: str = "<hash>"
down_revision: str | None = "71e80c777cf6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "('not_started', 'in_progress', 'needs_review', 'completed', 'suspended')"
_DISPOSITIONS = "('pending', 'pass', 'partial', 'unclear', 'duplicate_of_existing', 'not_chosen_before')"


def upgrade() -> None:
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'arv2_discovery'")
    op.execute(f"""
        CREATE TABLE arv2_discovery_run (
            run_id               uuid PRIMARY KEY,
            workspace_id         text NOT NULL,
            project_id           text NOT NULL,
            brand_id             text NOT NULL,
            project_run_id       uuid NOT NULL REFERENCES project_run (id),
            icp_artifact_key     text NOT NULL,
            icp_artifact_sha256  text NOT NULL,
            icp_key              text NOT NULL,
            icp_version          integer NOT NULL,
            requested_by_user_id text NOT NULL,
            request_sha256       text NOT NULL,
            target_count         integer NOT NULL CHECK (target_count > 0),
            strict_count         integer NOT NULL CHECK (strict_count > 0),
            relaxed_enabled      boolean NOT NULL,
            relaxed_requested    boolean NOT NULL DEFAULT false,
            criteria_gate_keys   jsonb NOT NULL,
            status               text NOT NULL DEFAULT 'not_started',
            webset_id            text,
            asked                integer,
            found_strict         integer,
            found_relaxed        integer,
            analyzed             integer,
            recall_estimate      integer,
            receipt_json         jsonb,
            created_at           timestamptz NOT NULL DEFAULT now(),
            started_at           timestamptz,
            finished_at          timestamptz,
            CONSTRAINT arv2_discovery_run_status CHECK (status IN {_STATUSES}),
            CONSTRAINT arv2_discovery_run_request UNIQUE (workspace_id, request_sha256)
        )
    """)
    op.execute("CREATE INDEX arv2_discovery_run_project ON arv2_discovery_run (workspace_id, project_id, created_at DESC)")
    op.execute(f"""
        CREATE TABLE arv2_discovery_candidate (
            candidate_id           uuid PRIMARY KEY,
            run_id                 uuid NOT NULL REFERENCES arv2_discovery_run (run_id),
            workspace_id           text NOT NULL,
            project_id             text NOT NULL,
            pass                   text NOT NULL CHECK (pass IN ('strict', 'relaxed')),
            domain                 text NOT NULL,
            websets_url            text,
            name                   text NOT NULL,
            provider_snapshot_json jsonb NOT NULL,
            verdicts_json          jsonb NOT NULL DEFAULT '[]'::jsonb,
            fit                    numeric(4,3),
            disposition            text NOT NULL DEFAULT 'pending',
            decision               text,
            decided_by_user_id     text,
            decided_at             timestamptz,
            account_entity_id      uuid REFERENCES account_entity (id),
            created_at             timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT arv2_discovery_candidate_run_domain UNIQUE (run_id, domain),
            CONSTRAINT arv2_discovery_candidate_disposition CHECK (disposition IN {_DISPOSITIONS}),
            CONSTRAINT arv2_discovery_candidate_decision CHECK (decision IS NULL OR decision = 'approved')
        )
    """)
    op.execute("CREATE INDEX arv2_discovery_candidate_project_domain ON arv2_discovery_candidate (workspace_id, project_id, domain)")
    op.execute("CREATE INDEX arv2_discovery_candidate_account ON arv2_discovery_candidate (account_entity_id)")


def downgrade() -> None:
    op.execute("DROP TABLE arv2_discovery_candidate")
    op.execute("DROP TABLE arv2_discovery_run")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'arv2_discovery') THEN
                RAISE EXCEPTION 'cannot downgrade R4 while arv2_discovery fleet tasks exist';
            END IF;
        END $$
    """)
    # Recreate the enum without the label, exactly as a3602967bb73 does: read that migration's
    # downgrade for the RENAME / CREATE TYPE / ALTER COLUMN ... USING / DROP TYPE sequence and the
    # `_KINDS_BEFORE` tuple, and reproduce it with the current label list minus 'arv2_discovery'.
```

Read `a3602967bb73`'s `downgrade()` and `_KINDS_BEFORE` and reproduce the enum recreation with today's full label list (every value of `FleetTaskKind` except `arv2_discovery`).

- [ ] **Step 5: Apply on the lane DB and smoke.** `set -a; source .env; set +a; uv run alembic upgrade head`; `uv run alembic heads` prints one head. Smoke: `createdb -h localhost -p 55040 clue_r4_smoke_$$` → with `CLUE_DATABASE_URL` pointed at it run `upgrade head`, `downgrade 71e80c777cf6`, `upgrade head`; drop the DB.

- [ ] **Step 6: Run the migration test** → PASS. Also `uv run pytest tests/fleet/test_fleet_db.py -q -p no:cacheprovider` → PASS.

- [ ] **Step 7: Write the failing store tests** `tests/arv2/test_discovery_store_db.py` (`rollback_conn` from `tests.profiling.conftest`, `run_async` from `tests.db.conftest`, `seed_project` from `tests._workspace`, `ensure_project_run` for the FK; mark with `pytest_db` the way `tests/arv2/test_account_research_store_db.py` does):

```python
def _run(project, *, request_sha256: str = "a" * 64, target: int = 20) -> DiscoveryRunRow:
    return DiscoveryRunRow(
        run_id=uuid4(), workspace_id=project.workspace_id, project_id=project.project_id,
        brand_id=str(project.brand_id), project_run_id=PROJECT_RUN_ID,
        icp_artifact_key="ws/abc", icp_artifact_sha256="b" * 64, icp_key="clue-abm-buyers",
        icp_version=1, requested_by_user_id="user-1", request_sha256=request_sha256,
        target_count=target, strict_count=35, relaxed_enabled=True, criteria_gate_keys=("geography", "stage"),
    )


def test_run_create_is_idempotent_and_replay_finds_it_by_request_sha() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project)
            assert await create_discovery_run(conn, row) is True
            assert await create_discovery_run(conn, row) is False
            found = await find_discovery_run(conn, workspace_id=row.workspace_id, request_sha256=row.request_sha256)
            assert found is not None and found.run_id == row.run_id and found.status == "not_started"
    run_async(scenario())


def test_begin_claims_only_not_started_or_suspended_and_finish_records_counts() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project); await create_discovery_run(conn, row)
            begun = await begin_discovery_run(conn, run_id=row.run_id)
            assert begun is not None and begun.status == "in_progress" and begun.started_at is not None
            assert await begin_discovery_run(conn, run_id=row.run_id) is None
            await finish_discovery_run(conn, run_id=row.run_id, status="completed", found_strict=15, found_relaxed=0, analyzed=333, receipt={"asked": 35})
            done = await read_discovery_run(conn, run_id=row.run_id)
            assert done is not None and done.status == "completed" and done.found_strict == 15 and done.receipt == {"asked": 35}
            assert await request_relaxed(conn, run_id=row.run_id) is True
            reopened = await read_discovery_run(conn, run_id=row.run_id)
            assert reopened is not None and reopened.status == "not_started" and reopened.relaxed_requested is True
    run_async(scenario())


def test_candidates_upsert_by_domain_record_verdicts_and_remember_the_unapproved() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            first = _run(project, request_sha256="1" * 64); await create_discovery_run(conn, first)
            cand = CandidateRow(candidate_id=uuid4(), run_id=first.run_id, workspace_id=first.workspace_id,
                                project_id=first.project_id, pass_="strict", domain="probook.ai",
                                websets_url="https://probook.com", name="Probook", provider_snapshot={"employees": 52})
            cid = await upsert_candidate(conn, cand)
            assert await upsert_candidate(conn, dataclasses.replace(cand, candidate_id=uuid4(), name="Probook AI")) == cid
            await record_verdicts(conn, candidate_id=cid, verdicts=[{"gate_key": "stage", "verdict": "pass"}], fit=1.0, disposition="pass", account_entity_id=None)
            (row,) = await list_candidates(conn, run_id=first.run_id)
            assert row.name == "Probook AI" and row.fit == 1.0 and row.disposition == "pass" and row.verdicts[0]["gate_key"] == "stage"
            second = _run(project, request_sha256="2" * 64); await create_discovery_run(conn, second)
            assert await unapproved_domains(conn, workspace_id=first.workspace_id, project_id=first.project_id, before_run_id=second.run_id) == frozenset({"probook.ai"})
            account = await insert_account_entity(conn, canonical_name="Probook", primary_domain="probook.ai", workspace_id=first.workspace_id)
            await record_verdicts(conn, candidate_id=cid, verdicts=row.verdicts, fit=1.0, disposition="pass", account_entity_id=UUID(str(account)))
            assert await mark_candidates_approved(conn, workspace_id=first.workspace_id, project_id=first.project_id, account_entity_ids=[UUID(str(account))], decided_by_user_id="user-1") == 1
            assert await unapproved_domains(conn, workspace_id=first.workspace_id, project_id=first.project_id, before_run_id=second.run_id) == frozenset()
            (approved,) = await list_candidates(conn, run_id=first.run_id)
            assert approved.decision == "approved" and approved.decided_by_user_id == "user-1" and approved.decided_at is not None
    run_async(scenario())
```

`_seed(conn)` = `seed_project(conn, WORKSPACE)` + `ensure_project_run(conn, project_run_id=ProjectRunId(PROJECT_RUN_ID), project_id=project.project_id, workspace_id=project.workspace_id, icp_key="clue-abm-buyers", icp_version=1, phase=ProjectPhase.DEEP)` (imports as in `account_research_launch.py`).

- [ ] **Step 8: Run → FAIL** (module missing).

- [ ] **Step 9: Implement `discovery_store.py`** following `account_research_store.py`'s style (module docstring stating the ruling each table serves; `text()` SQL constants; `_run(row)`/`_candidate(row)` mappers; `decode_jsonb` for jsonb). Rules the SQL must encode: `begin_discovery_run` = `UPDATE … SET status='in_progress', started_at=now() WHERE run_id=:id AND status IN ('not_started','suspended') RETURNING *`; `request_relaxed` = `UPDATE … SET status='not_started', relaxed_requested=true WHERE run_id=:id AND status IN ('completed','needs_review')`; `unapproved_domains` = `SELECT DISTINCT domain FROM arv2_discovery_candidate WHERE workspace_id=:w AND project_id=:p AND run_id <> :before AND decision IS NULL AND disposition IN ('pass','partial','unclear')`; `mark_candidates_approved` = `UPDATE … SET decision='approved', decided_by_user_id=:u, decided_at=now() WHERE workspace_id=:w AND project_id=:p AND account_entity_id = ANY(:ids) AND decision IS NULL` returning rowcount.

- [ ] **Step 10: Run → PASS.** Ruff + `uv run ruff format` on the new files.

- [ ] **Step 11: Commit.** `git add alembic/versions/*arv2_r4_discovery.py platform/fleet/clue_fleet/enums.py platform/api/clue_api/arv2/discovery_store.py tests/db/test_arv2_r4_migration.py tests/arv2/test_discovery_store_db.py && git commit -m "feat(arv2 r4): fleet kind arv2_discovery, discovery run and candidate tables, the discovery store"`

---

### Task 3: Exa Answer on the Exa client, and the Websets client

**Files:**
- Modify: `platform/api/clue_api/arv2/exa_client.py`
- Create: `platform/api/clue_api/arv2/exa_websets_client.py`
- Test: `tests/arv2/test_exa_client.py` (extend), `tests/arv2/test_exa_websets_client.py`

**Interfaces (produces):**

```python
# exa_client.py additions
ANSWER_ESTIMATE_USD = Decimal("0.01")

def answer_body(query: str, *, system_prompt: str, output_schema: Mapping[str, object], model: str = "exa", text: bool = True) -> dict[str, Any]

@dataclass(frozen=True)
class ExaCitation:
    url: str; title: str | None; published_date: str | None; text: str | None

@dataclass(frozen=True)
class ExaAnswerResult:
    answer: object                      # dict when outputSchema was given, else str; None when absent
    citations: tuple[ExaCitation, ...]
    status: int; cost_usd: Decimal | None; request_id: str | None
    raw_ref: str | None; ledger_row_id: str; cost: CallCost

class ExaClient:
    def answer(self, query: str, *, system_prompt: str, output_schema: Mapping[str, object], model: str = "exa", label: str = "exa-answer", timeout_s: float = 120.0) -> ExaAnswerResult
```

```python
# exa_websets_client.py
PROVIDER = "exa_websets"; WEBSETS_BASE_PATH = "/websets/v0/websets"; CREDITS_PER_MATCH = 10

@dataclass(frozen=True)
class WebsetSearchView:
    search_id: str; status: str; count: int; found: int | None; analyzed: int | None
    recall_estimate: int | None; criteria_success_rates: tuple[tuple[str, float | None], ...]

@dataclass(frozen=True)
class WebsetView:
    webset_id: str; status: str; searches: tuple[WebsetSearchView, ...]; raw_ref: str | None; ledger_row_id: str

@dataclass(frozen=True)
class WebsetItem:
    item_id: str; search_id: str | None; url: str; name: str; description: str | None
    hq_city: str | None; hq_state: str | None; hq_country_code: str | None
    employees: int | None; revenue_annual: int | None; funding_total: int | None
    evaluations: tuple[Mapping[str, Any], ...]; raw: Mapping[str, Any]

@dataclass(frozen=True)
class WebsetItemsResult:
    items: tuple[WebsetItem, ...]; all_green: int; credits_est: int; cost_usd: Decimal; raw_refs: tuple[str, ...]; ledger_row_ids: tuple[str, ...]

class ExaWebsetsClient:
    def __init__(self, caller: ProviderCaller, api_key: SecretStr, *, usd_per_credit: Decimal, base_url: str = EXA_BASE_URL) -> None
    def create(self, *, query: str, count: int, criteria: Sequence[str], external_id: str, title: str, recall: bool = True) -> WebsetView
    def get(self, webset_id: str) -> WebsetView
    def items(self, webset_id: str) -> WebsetItemsResult            # follows hasMore/nextCursor
    def add_search(self, webset_id: str, *, query: str, count: int, criteria: Sequence[str], exclude_search_ids: Sequence[str]) -> WebsetView

def websets_halt_rule(response: HttpResponse) -> str | None          # 401/402 → "exa websets: <error message>"
def websets_items_cost(all_green: int, usd_per_credit: Decimal) -> Decimal
```

The `create` estimate is `count × CREDITS_PER_MATCH × usd_per_credit`; `items` records `all_green × 10 × usd_per_credit` as the cost reading of the items call (a custom `cost_reader` closing over the rate, counting items whose every evaluation is `satisfied == "yes"`); `get` and `create` cost `0` (the credits are charged for results, read on `items`). The `add_search` body is `{"query", "count", "entity": {"type": "company"}, "criteria": [...], "exclude": [{"source": "search", "id": <search_id>} …]}` (per Exa's create-search docs) at `POST {base}/websets/v0/websets/{id}/searches`.

- [ ] **Step 1: Write the failing Answer tests** in `tests/arv2/test_exa_client.py` (use the file's existing `ScriptedTransport`/caller helpers; if it builds callers with a local helper, reuse it):

```python
def test_answer_body_carries_prompt_schema_and_text() -> None:
    body = answer_body("Q?", system_prompt="S", output_schema={"type": "object"}, model="exa")
    assert body == {"query": "Q?", "model": "exa", "text": True, "systemPrompt": "S", "outputSchema": {"type": "object"}}


def test_answer_returns_the_structured_object_and_citations_with_text() -> None:
    payload = {
        "requestId": "r1",
        "answer": {"verdict": "fail", "reasoning": "Series B", "evidence_quote": "our Series B", "evidence_url": "https://avoca.ai/blog", "evidence_date": "2026-04-27"},
        "citations": [{"url": "https://avoca.ai/blog", "title": "Why", "publishedDate": "2026-04-27T00:00:00.000Z", "text": "Today, we announced our Series B"}],
        "costDollars": {"total": 0.005},
    }
    caller, transport = _caller([HttpResponse(status=200, body=json.dumps(payload).encode())])
    result = ExaClient(caller, SecretStr("k")).answer("Q?", system_prompt="S", output_schema={"type": "object"})
    assert result.answer == payload["answer"]
    assert result.citations[0].url == "https://avoca.ai/blog" and result.citations[0].text.startswith("Today")
    assert result.cost_usd == Decimal("0.005") and result.request_id == "r1"
    sent = json.loads(transport.requests[0].body)
    assert sent["outputSchema"] == {"type": "object"} and transport.requests[0].url.endswith("/answer")
```

(`_caller` = whatever helper the file already uses to build a `ProviderCaller` over a `ScriptedTransport` with in-memory sinks; if none exists, write one at the top of the test module using `ProviderCaller(transport=ScriptedTransport([...]), raw_sink=BufferedRawSink(), ledger=BufferedLedger(), now=lambda: datetime(2026, 9, 10, tzinfo=UTC))`.)

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement** `answer_body`, `ExaCitation`, `ExaAnswerResult`, `ExaClient.answer` via `self._call(operation="answer", path="/answer", estimate=SpendEstimate(usd=ANSWER_ESTIMATE_USD), …)`; parse `answer` (dict or str or None) and `citations[]` (`url`, `title`, `publishedDate`, `text`). **Step 4: Run → PASS.**

- [ ] **Step 5: Write the failing Websets tests** `tests/arv2/test_exa_websets_client.py`:

```python
def test_create_posts_company_entity_criteria_and_recall() -> None:
    body = {"id": "webset_1", "status": "running", "searches": [{"id": "ws_1", "status": "running", "count": 35, "criteria": [{"description": "US", "successRate": None}], "progress": {"found": 0, "analyzed": 0}}]}
    caller, transport = _caller([HttpResponse(status=201, body=json.dumps(body).encode())])
    client = ExaWebsetsClient(caller, SecretStr("k"), usd_per_credit=Decimal("0.00449"))
    view = client.create(query="ICP", count=35, criteria=["US", "Series A"], external_id="run-1", title="R4 run-1")
    sent = json.loads(transport.requests[0].body)
    assert sent["search"] == {"query": "ICP", "count": 35, "entity": {"type": "company"}, "criteria": [{"description": "US"}, {"description": "Series A"}], "recall": True}
    assert sent["externalId"] == "run-1" and view.webset_id == "webset_1" and view.searches[0].count == 35


def test_items_follow_the_cursor_map_the_company_record_and_price_the_all_green_rows() -> None:
    page1 = {"data": [_item("witem_1", "https://probook.com", "Probook", yes=True)], "hasMore": True, "nextCursor": "c2"}
    page2 = {"data": [_item("witem_2", "https://lassie.ai", "Lassie", yes=False)], "hasMore": False}
    caller, transport = _caller([HttpResponse(status=200, body=json.dumps(page1).encode()), HttpResponse(status=200, body=json.dumps(page2).encode())])
    client = ExaWebsetsClient(caller, SecretStr("k"), usd_per_credit=Decimal("0.00449"))
    result = client.items("webset_1")
    assert [i.name for i in result.items] == ["Probook", "Lassie"]
    assert result.items[0].hq_country_code == "US" and result.items[0].employees == 52
    assert result.all_green == 1 and result.credits_est == 10 and result.cost_usd == Decimal("0.0449")
    assert "cursor=c2" in transport.requests[1].url


def test_a_402_halts_the_provider() -> None:
    caller, _ = _caller([HttpResponse(status=402, body=b'{"error": "You have exceeded your credits limit"}')])
    client = ExaWebsetsClient(caller, SecretStr("k"), usd_per_credit=Decimal("0.00449"))
    with pytest.raises(ProviderHalted):
        client.get("webset_1")
    assert caller.halted("exa_websets")
```

with `_item(id, url, name, *, yes)` returning the item JSON shape from `.context/arv2-websets-experiment/raw/hybrid_webset_items.json` (properties.type/url/description/company{name, employees:52, headquarters{city,state,countryCode:"US"}, financials{fundingTotal, revenueAnnual}}, evaluations[{criterion, satisfied: "yes"|"no", reasoning, references}]).

- [ ] **Step 6: Run → FAIL. Step 7: Implement the client** (mirror `ExaClient._call`: `json_request` with `x-api-key`, `CallSpec(provider="exa_websets", …, halt_rule=websets_halt_rule, cost_reader=…)`; GET requests via `json_request("GET", …)` with no body). **Step 8: Run → PASS.** Ruff/format.

- [ ] **Step 9: Commit.** `git add platform/api/clue_api/arv2/exa_client.py platform/api/clue_api/arv2/exa_websets_client.py tests/arv2/test_exa_client.py tests/arv2/test_exa_websets_client.py && git commit -m "feat(arv2 r4): Exa Answer on the Exa client and a thin Websets client, both through the provider caller"`

---

### Task 4: The brief compiler and the verifier (pure)

**Files:**
- Create: `platform/api/clue_api/arv2/discovery_brief.py`, `platform/api/clue_api/arv2/discovery_verifier.py`
- Test: `tests/arv2/test_discovery_brief.py`, `tests/arv2/test_discovery_verifier.py`

**Interfaces (produces):**

```python
# discovery_brief.py
@dataclass(frozen=True)
class Gate:
    key: str; rule: str; test: str; window_months: int | None

@dataclass(frozen=True)
class DiscoveryBrief:
    query: str                       # the ICP body's buyer sentence (first non-heading paragraph)
    criteria: tuple[str, ...]        # ≤ 3: the chosen gates' rules, then the buyer sentence if a slot is free
    criteria_gate_keys: tuple[str, ...]
    gates: tuple[Gate, ...]          # every hard gate, document order
    exclusions: tuple[str, ...]

def parse_window_months(*texts: str) -> int | None        # first r"(\d+)\s*months" match across rule/test
def compile_brief(front: Mapping[str, Any], body: str, *, criteria_gate_keys: Sequence[str]) -> DiscoveryBrief
# raises BriefError("icp has no hard_gates") / BriefError("unknown criteria gate key 'x'")
```

```python
# discovery_verifier.py
VERDICTS = ("pass", "fail", "unclear")
OUTPUT_SCHEMA: dict[str, Any]           # verdict enum, reasoning, evidence_quote, evidence_url, evidence_date (all required, additionalProperties false)
WEBSITE_SCHEMA: dict[str, Any]          # {website_domain, evidence_url}
def system_prompt(today: date) -> str   # the spec §3 paragraph, verbatim, with the date
def gate_question(company_name: str, url: str, gate: Gate) -> str
def website_question(company_name: str, websets_url: str) -> str
def normalise(text: str) -> str         # NFKC, lowercase, typographic quotes/dashes → ASCII, whitespace collapsed, [^a-z0-9' -] → space

@dataclass(frozen=True)
class GateVerdict:
    gate_key: str; verdict: str; reasoning: str; evidence_quote: str; evidence_url: str; evidence_date: str
    guard: str                           # "ok" | "quote_not_on_page" | "wrong_company" | "outside_window" | "no_source" | "malformed"
    model_verdict: str                   # what Answer said before guards
    def as_json(self) -> dict[str, Any]

def apply_guards(*, gate: Gate, answer: object, citations: Sequence[ExaCitation], company_domain: str, company_name: str, today: date) -> GateVerdict
def fit_score(verdicts: Sequence[GateVerdict]) -> float          # passes/gates, unclear = 0.5
def disposition(verdicts: Sequence[GateVerdict]) -> str          # pass | partial | unclear (spec §3 rules)
```

Guard rules (`apply_guards`), in order: (1) `answer` not a dict or `verdict` not in `VERDICTS` → `unclear`, guard `malformed`; (2) verdict `unclear` → keep, guard `ok`; (3) empty quote or empty URL on a pass/fail → `unclear`, guard `no_source`; (4) `normalise(quote)[:60]` not in `normalise(citation.text)` for any citation → `unclear`, guard `quote_not_on_page`; (5) the cited URL's `registrable_domain` ≠ `company_domain` AND `normalise(company_name)` not in the normalised text of that citation → `unclear`, guard `wrong_company`; (6) gate has a window and `evidence_date` parses (`YYYY-MM-DD` or `YYYY-MM`) and `months_between(date, today) > window_months` → `fail` if the model said pass, guard `outside_window`; unparseable date with a window → leave the verdict, guard `ok`. `disposition`: all pass → `pass`; any fail and at least as many passes as fails → `partial`; more fails than passes → `partial` too (the row stays visible; there is no `fail` disposition on a shown row); no fail and ≥1 unclear → `unclear`.

- [ ] **Step 1: Write the failing brief tests** `tests/arv2/test_discovery_brief.py` using the Clue ICP text: copy the `hard_gates`/`exclusions` YAML block from `.context/arv2-answer-key-knowledge/icp-clue-abm-buyers.md` into a module constant `ICP_TEXT` (front matter + a body: `# Who we sell to\n\nUS B2B vertical SaaS…\n\n## More\n\n…`), parse with `parse_front_matter`:

```python
def test_compile_brief_reads_gates_query_and_windows_from_the_document() -> None:
    front, body = parse_front_matter(ICP_TEXT)
    brief = compile_brief(front, body, criteria_gate_keys=["geography", "stage"])
    assert [g.key for g in brief.gates] == ["geography", "stage", "hiring", "intent"]
    assert brief.gates[1].window_months == 36 and brief.gates[0].window_months is None
    assert brief.query.startswith("US B2B vertical SaaS")
    assert brief.criteria == (brief.gates[0].rule, brief.gates[1].rule, brief.query)
    assert brief.criteria_gate_keys == ("geography", "stage")
    assert "Sells to consumers (B2C)" in brief.exclusions


def test_three_named_gates_leave_no_slot_for_the_buyer_sentence() -> None:
    front, body = parse_front_matter(ICP_TEXT)
    brief = compile_brief(front, body, criteria_gate_keys=["geography", "stage", "hiring"])
    assert len(brief.criteria) == 3 and brief.query not in brief.criteria


def test_unknown_gate_key_and_missing_gates_refuse_by_name() -> None:
    front, body = parse_front_matter(ICP_TEXT)
    with pytest.raises(BriefError, match="unknown criteria gate key 'vertical'"):
        compile_brief(front, body, criteria_gate_keys=["vertical"])
    with pytest.raises(BriefError, match="no hard_gates"):
        compile_brief({"kind": "icp-definition"}, body, criteria_gate_keys=[])
```

- [ ] **Step 2: Run → FAIL. Step 3: Implement `discovery_brief.py`.** Buyer sentence = first paragraph of the body that is not a heading (`#`), not empty, joined on single spaces, truncated at 600 chars. **Step 4: Run → PASS.**

- [ ] **Step 5: Write the failing verifier tests** `tests/arv2/test_discovery_verifier.py` (`_cit(url, text, date)` helper builds `ExaCitation`):

```python
STAGE = Gate(key="stage", rule="most recent round is a Series A within 24 months", test="A dated announcement…", window_months=24)
TODAY = date(2026, 9, 10)

def test_a_grounded_pass_keeps_its_verdict_and_quote() -> None:
    answer = {"verdict": "pass", "reasoning": "r", "evidence_quote": "Probook Raises $40M in Seed and Series A Financing", "evidence_url": "https://finsmes.com/x", "evidence_date": "2026-06-23"}
    v = apply_guards(gate=STAGE, answer=answer, citations=[_cit("https://finsmes.com/x", "FinSMEs: Probook Raises $40M in Seed and Series A Financing today", "2026-06-23")], company_domain="probook.ai", company_name="Probook", today=TODAY)
    assert (v.verdict, v.guard, v.model_verdict) == ("pass", "ok", "pass")


def test_a_quote_not_on_the_cited_page_becomes_unclear() -> None:
    answer = {"verdict": "fail", "reasoning": "r", "evidence_quote": "closed a $2.8M seed round", "evidence_url": "https://signalbase.com/p", "evidence_date": "2026-04-28"}
    v = apply_guards(gate=STAGE, answer=answer, citations=[_cit("https://signalbase.com/p", "unrelated text about dentists", "2026-04-28")], company_domain="patientdesk.ai", company_name="Patientdesk", today=TODAY)
    assert (v.verdict, v.guard) == ("unclear", "quote_not_on_page")


def test_a_page_about_another_company_on_another_domain_becomes_unclear() -> None:
    answer = {"verdict": "pass", "reasoning": "r", "evidence_quote": "As an Account Executive at infinIT, you will prospect", "evidence_url": "https://jobera.com/infinit", "evidence_date": "2026-04-03"}
    v = apply_guards(gate=Gate("intent", "…", "…", None), answer=answer, citations=[_cit("https://jobera.com/infinit", "As an Account Executive at infinIT, you will prospect daily", None)], company_domain="infi.us", company_name="INFI", today=TODAY)
    assert (v.verdict, v.guard) == ("unclear", "wrong_company")


def test_a_news_page_that_names_the_company_is_accepted_off_domain() -> None:
    answer = {"verdict": "pass", "reasoning": "r", "evidence_quote": "Lassie raised $35 million in Series A financing", "evidence_url": "https://businesswire.com/l", "evidence_date": "2026-06-03"}
    v = apply_guards(gate=STAGE, answer=answer, citations=[_cit("https://businesswire.com/l", "SAN FRANCISCO — Lassie raised $35 million in Series A financing led by a16z", "2026-06-03")], company_domain="lassie.ai", company_name="Lassie", today=TODAY)
    assert (v.verdict, v.guard) == ("pass", "ok")


def test_arithmetic_is_codes_a_pass_outside_the_window_fails() -> None:
    answer = {"verdict": "pass", "reasoning": "within 24 months", "evidence_quote": "Superorder today announced that it raised $10 million", "evidence_url": "https://techcrunch.com/s", "evidence_date": "2023-09-15"}
    v = apply_guards(gate=STAGE, answer=answer, citations=[_cit("https://techcrunch.com/s", "Superorder today announced that it raised $10 million in a Series A", "2023-09-15")], company_domain="superorder.com", company_name="Superorder", today=TODAY)
    assert (v.verdict, v.guard) == ("fail", "outside_window")


def test_no_source_is_unclear_never_fail_and_malformed_is_unclear() -> None:
    absent = apply_guards(gate=STAGE, answer={"verdict": "fail", "reasoning": "no roles found", "evidence_quote": "", "evidence_url": "", "evidence_date": ""}, citations=[], company_domain="x.com", company_name="X", today=TODAY)
    assert (absent.verdict, absent.guard) == ("unclear", "no_source")
    assert apply_guards(gate=STAGE, answer="not json", citations=[], company_domain="x.com", company_name="X", today=TODAY).guard == "malformed"


def test_fit_and_disposition_follow_the_spec_table() -> None:
    def v(verdict: str) -> GateVerdict:
        return GateVerdict("g", verdict, "", "", "", "", "ok", verdict)
    assert fit_score([v("pass")] * 4) == 1.0 and disposition([v("pass")] * 4) == "pass"
    assert fit_score([v("pass")] * 3 + [v("unclear")]) == 0.875 and disposition([v("pass")] * 3 + [v("unclear")]) == "unclear"
    assert fit_score([v("pass"), v("pass"), v("fail"), v("fail")]) == 0.5 and disposition([v("pass"), v("pass"), v("fail"), v("fail")]) == "partial"
    assert fit_score([v("pass"), v("fail"), v("fail"), v("fail")]) == 0.25 and disposition([v("pass"), v("fail"), v("fail"), v("fail")]) == "partial"


def test_the_question_is_the_gates_own_words() -> None:
    q = gate_question("Avoca", "https://avoca.ai", STAGE)
    assert "Company: Avoca (website https://avoca.ai)" in q and STAGE.rule in q and STAGE.test in q
    assert "freshest" in system_prompt(TODAY) and "2026-09-10" in system_prompt(TODAY)
```

- [ ] **Step 6: Run → FAIL. Step 7: Implement `discovery_verifier.py`.** `system_prompt` returns the spec §3 paragraph exactly (today's date; sources only; most recent dated announcement is the authority; profile pages secondary; same-name warning; pass only when stated, fail only when contradicted, otherwise unclear; quote verbatim). **Step 8: Run → PASS.** Ruff/format.

- [ ] **Step 9: Commit.** `git add platform/api/clue_api/arv2/discovery_brief.py platform/api/clue_api/arv2/discovery_verifier.py tests/arv2/test_discovery_brief.py tests/arv2/test_discovery_verifier.py && git commit -m "feat(arv2 r4): the discovery brief compiled from the ICP document, and the verifier with its three guards"`

---

### Task 5: The discovery launch, replay, enqueue, tool, and CLI

**Files:**
- Create: `platform/api/clue_api/arv2/discovery_launch.py`, `scripts/launch_arv2_discovery.py`
- Modify: `platform/api/clue_api/arv2/fleet_task.py`, `platform/api/clue_api/arv2/__init__.py`, `platform/api/clue_api/toolbelt_wiring.py` (register beside `build_arv2_launch_tools`), `platform/api/clue_api/projections_main.py` and `fleet_main.py` (compose `DbArv2DiscoveryService` where `DbArv2LaunchService` is)
- Test: `tests/arv2/test_discovery_launch_db.py`, `tests/api/test_arv2_launch_tools.py` (extend), `tests/api/test_toolbelt_wiring.py` (`_MATRIX` entry + counts)

**Interfaces (produces):**

```python
# fleet_task.py
ARV2_DISCOVERY_DEDUP_PREFIX = "arv2-discovery:"; ARV2_DISCOVERY_TASK_PRIORITY = -90
def arv2_discovery_work_id(run_id: UUID) -> WorkId

# discovery_launch.py
@dataclass(frozen=True)
class Arv2DiscoveryRequest:
    workspace_id: str; project_id: str; requested_by_user_id: str
    target_count: int = 20; strict_count: int | None = None      # None → settings.arv2_discovery_strict_count
    relaxed_enabled: bool | None = None                            # None → settings.arv2_discovery_relaxed_auto
    criteria_gate_keys: tuple[str, ...] = ()                       # () → settings.arv2_discovery_criteria_gate_keys split on ","
    project_run_id: UUID | None = None

class Arv2DiscoveryRefused(Arv2Error): code: str    # lane_disabled, project_not_found, project_icp_not_pinned, icp_artifact_not_found, icp_artifact_not_confirmed, icp_digest_mismatch, unknown_criteria_gate_key, target_count_invalid

@dataclass(frozen=True)
class Arv2DiscoveryReceipt:
    run_id: UUID; replayed: bool; project_run_id: UUID; workspace_id: str; to_enqueue: bool

@dataclass(frozen=True)
class PinnedIcpDocument:
    front: Mapping[str, Any]; body: str; artifact_key: str; artifact_sha256: str; icp_key: str; icp_version: int; brand_id: str

async def read_pinned_icp(conn, storage: StorageBackend, *, workspace_id: str, project_id: str) -> PinnedIcpDocument
async def launch_arv2_discovery(conn, request: Arv2DiscoveryRequest, *, settings: Settings, storage: StorageBackend) -> Arv2DiscoveryReceipt
async def request_relaxed_pass(conn, *, workspace_id: str, run_id: UUID) -> Arv2DiscoveryReceipt     # refuses run_not_found / run_not_finished
async def enqueue_discovery_run(queue: WorkQueue, receipt: Arv2DiscoveryReceipt) -> bool

class Arv2DiscoveryService(Protocol):
    async def launch(self, request: Arv2DiscoveryRequest) -> Arv2DiscoveryReceipt: ...
class DbArv2DiscoveryService:   # __init__(settings, storage, *, queue: WorkQueue | None = None, conn_factory=transaction); launch() = transaction + launch + enqueue after commit
class LaunchArv2DiscoveryInput(ToolInput): project_id: str; target_count: int = Field(default=20, ge=1, le=500); relaxed_enabled: bool = True
class LaunchArv2DiscoveryOutput(ToolOutput): run_id: str; replayed: bool
class LaunchArv2DiscoveryTool(Tool): name = "launch_arv2_discovery"; version = "1"; effect_class = SPEND; pin_requirements = ("project",)
def build_arv2_discovery_tools(service: Arv2DiscoveryService | None) -> tuple[Tool, ...]
```

`launch_arv2_discovery` mirrors `launch_arv2_account_research` lines 240–380: refuse `lane_disabled` unless `settings.arv2_discovery_enabled`; `get_project` (refuse `project_not_found`); `read_pinned_icp` (the `current_project_icp_pin` → row → artifact → `parse_front_matter` chain, refusals named as in the account launch); compile the brief once to validate `criteria_gate_keys` (refuse `unknown_criteria_gate_key`); `project_run_id = request.project_run_id or uuid5(NAMESPACE_URL, f"arv2-project-run:{project_id}:{icp_key}:{icp_version}")` + `ensure_project_run(... phase=ProjectPhase.DEEP)`; `request_sha256` = sha256 of the canonical JSON of (workspace, project, icp artifact sha, target, strict, relaxed, criteria keys); `run_id = uuid5(_DISCOVERY_RUN_NS, request_sha)`; `create_discovery_run` (replayed when it returns False); `record_run_lineage(conn, run_id=run_id, workspace_id=…, kind="discovery", project_id=…, project_run_id=…)`; receipt `to_enqueue=True` when the run's status is `not_started`. `enqueue_discovery_run` offers `kind=FleetTaskKind.ARV2_DISCOVERY, work_id=arv2_discovery_work_id(run_id), dedup_key=f"{ARV2_DISCOVERY_DEDUP_PREFIX}{run_id}", priority=ARV2_DISCOVERY_TASK_PRIORITY, payload={"run_id", "workspace_id"}, reopen_terminal=True` (a relaxed request re-offers a finished run's task).

- [ ] **Step 1: Write the failing launch tests** `tests/arv2/test_discovery_launch_db.py`. Copy `_seed_icp_document`, `_pin_icp`, `_FakeQueue` and `_seed` from `tests/arv2/test_account_research_launch_db.py` into a new shared module `tests/arv2/icp_fixture.py` (move, and import them back in the launch test file so nothing duplicates), using the Clue ICP text with `hard_gates` as `ICP_BODY` (Task 4's `ICP_TEXT`). Tests:

```python
def test_a_launch_creates_one_run_pinned_to_the_projects_icp_and_records_lineage(tmp_path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path); fixture = await seed_icp_fixture(conn, storage)
            receipt = await launch_arv2_discovery(conn, Arv2DiscoveryRequest(workspace_id=fixture.workspace_id, project_id=fixture.project_id, requested_by_user_id=USER_ID, target_count=20), settings=_settings(), storage=storage)
            run = await read_discovery_run(conn, run_id=receipt.run_id)
            assert run is not None and run.icp_artifact_sha256 == fixture.icp_artifact_sha256 and run.icp_key == ICP_KEY
            assert run.target_count == 20 and run.strict_count == 35 and run.relaxed_enabled is True
            assert run.criteria_gate_keys == ("geography", "stage") and run.status == "not_started"
            lineage = (await conn.execute(text("SELECT kind, project_id FROM run_lineage WHERE run_id = :r"), {"r": receipt.run_id})).one()
            assert tuple(lineage) == ("discovery", fixture.project_id)
            queue = _FakeQueue(); assert await enqueue_discovery_run(queue, receipt) is True
            assert queue.calls[0]["kind"] is FleetTaskKind.ARV2_DISCOVERY and queue.calls[0]["payload"]["run_id"] == str(receipt.run_id)
    run_async(scenario())


def test_the_same_request_replays_to_the_same_run() -> None: ...   # second launch → replayed True, same run_id, create returned False
def test_refusals_are_named(tmp_path) -> None: ...                    # lane off → lane_disabled; unknown project → project_not_found; no pin → project_icp_not_pinned; criteria key "vertical" → unknown_criteria_gate_key
def test_a_relaxed_pass_can_be_requested_only_on_a_finished_run(tmp_path) -> None: ...  # not finished → run_not_finished; after finish_discovery_run(completed) → status not_started, relaxed_requested, receipt.to_enqueue True
```

- [ ] **Step 2: Run → FAIL. Step 3: Implement** `fleet_task.py` additions, `discovery_launch.py` (tool class modelled on `LaunchArv2PersonResearchTool`: preconditions `_not_composed()` when the service is None else `_trusted_action(ctx)`; `invoke` builds the request with ambient `ctx.workspace_id` and `ctx.actor_id or ctx.actor`; refusals → `PreconditionFailed`), exports in `__init__.py`. **Step 4: Run → PASS.**

- [ ] **Step 5: Register the tool.** In `toolbelt_wiring.py` next to the `build_arv2_launch_tools` loop: `for tool in build_arv2_discovery_tools(arv2_discovery_launch): registry.register(tool, make_default=True)`, threading a new `arv2_discovery_launch: Arv2DiscoveryService | None = None` parameter through `build_toolbelt` the same way `arv2_account_launch` is threaded (grep its every occurrence and add the sibling). Compose `DbArv2DiscoveryService(settings, storage, queue=work_queue)` in `fleet_main.py` beside `DbArv2LaunchService` and `DbArv2DiscoveryService(resolved, storage)` in `projections_main.py` behind `arv2_discovery_enabled`. Extend `tests/api/test_arv2_launch_tools.py` with the not-composed refusal (`arv2_discovery_not_composed`) and the missing-action-ref precondition; add the `_MATRIX` entry in `tests/api/test_toolbelt_wiring.py` beside `launch_arv2_person_research` (`("arv2_discovery_not_composed",)`) and bump the two `len(registry.names()) == 124` → `125` and `len(registry) == 142` → `143` assertions (with a comment naming R4).

- [ ] **Step 6: Write the CLI** `scripts/launch_arv2_discovery.py` modelled on `scripts/launch_arv2_person_research.py` (same `db_lifespan`, `build_storage_backend`, `DbWorkQueue`, `register_arv2_wiring`, `--requested-by` default, `--database-url`, `--storage-root`): arguments `--workspace`, `--project`, `--target` (default 20), `--strict-count`, `--no-relaxed`, `--criteria-gates`, `--relaxed-pass <run_id>` (calls `request_relaxed_pass` then enqueues), `--report <run_id>` (prints the run row and a table of candidates: domain, name, pass, disposition, fit, decision, per-gate verdict letters). Print the receipt as JSON.

- [ ] **Step 7: Run** `uv run pytest tests/arv2/test_discovery_launch_db.py tests/api/test_arv2_launch_tools.py tests/api/test_toolbelt_wiring.py -q -p no:cacheprovider` → PASS (except the pre-existing reds recorded in Task 1). Ruff/format.

- [ ] **Step 8: Commit.** `git add -A platform/api/clue_api/arv2/discovery_launch.py platform/api/clue_api/arv2/fleet_task.py platform/api/clue_api/arv2/__init__.py platform/api/clue_api/toolbelt_wiring.py platform/api/clue_api/fleet_main.py platform/api/clue_api/projections_main.py scripts/launch_arv2_discovery.py tests/arv2/icp_fixture.py tests/arv2/test_account_research_launch_db.py tests/arv2/test_discovery_launch_db.py tests/api/test_arv2_launch_tools.py tests/api/test_toolbelt_wiring.py && git commit -m "feat(arv2 r4): the discovery launch with replay and lineage, the relaxed-pass request, the launch tool registered ungranted, and the CLI"`

---

### Task 6: The discovery driver on the fleet

**Files:**
- Create: `platform/api/clue_api/arv2/discovery_driver.py`
- Modify: `platform/api/clue_api/fleet_main.py` (`_build_arv2_discovery_handler`, passed to `build_multi_work_worker`), `platform/api/clue_api/fleet_wiring.py` (`arv2_discovery_handler: WorkHandler | None = None` parameter, kind check, append)
- Test: `tests/arv2/test_discovery_driver.py` (offline, scripted clients), `tests/arv2/test_discovery_driver_db.py` (one end-to-end on the DB with scripted clients), `tests/api/test_fleet_wiring.py` (extend: the handler is registered under its kind)

**Interfaces (produces):**

```python
class DiscoveryClients(Protocol):
    def exa(self, caller: ProviderCaller) -> ExaClient: ...
    def websets(self, caller: ProviderCaller) -> ExaWebsetsClient: ...

class Arv2DiscoveryWorkHandler:
    kind = FleetTaskKind.ARV2_DISCOVERY
    def __init__(self, *, settings: Settings, conn_factory: ConnFactory, storage: StorageBackend, artifacts: ArtifactSink,
                 clients: DiscoveryClients, writer: LenientClaimWriter, store: Any = discovery_store,
                 transport_factory: Callable[[], Transport] = HttpxTransport, clock: Callable[[], datetime] = _utcnow,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None
    async def handle(self, context: WorkContext) -> WorkResult          # payload {"run_id", "workspace_id"}; never raises

def build_arv2_discovery_handler(settings: Settings, secrets: Secrets, *, storage: StorageBackend, artifacts: ArtifactSink, conn_factory: ConnFactory = transaction) -> Arv2DiscoveryWorkHandler | None   # None + named warning when CLUE_EXA_API_KEY is missing
```

The run, in order (each provider hop through a fresh `ProviderCaller` over `BufferedRawSink`/`BufferedLedger`, run in `asyncio.to_thread`, then drained with `drain_provider_calls(conn, raw=…, ledger=…, artifacts=…, stamp=LedgerStamp(workspace_id, project_id, str(project_run_id), job_id=run_id))` — copy `ToolRuntime._hop`'s shape without the semaphores):

1. `begin_discovery_run`; if `None` → `WorkResult(outcome="completed", requeue=False)` (already running or done). Stop/lease-lost before work → `suspend_discovery_run` + `outcome="stopped", requeue=True`.
2. `read_pinned_icp` → `compile_brief(front, body, criteria_gate_keys=run.criteria_gate_keys)`.
3. **Strict pass** (skipped when `run.relaxed_requested` and a webset already exists): `websets.create(query=brief.query, count=run.strict_count, criteria=brief.criteria, external_id=f"arv2-discovery:{run_id}", title=f"ARV2 discovery {project_id} {icp_key}@{icp_version}")`; `record_webset(asked=strict_count, recall_estimate=…)`; poll `websets.get` every `poll_interval_s` until `status == "idle"` or `wall_s` elapsed (then `needs_review` with reason `webset_wall_exceeded`); `websets.items`.
4. For every item: `domain0 = registrable_domain(item.url)`; **website verification** = one `exa.answer(website_question(item.name, item.url), system_prompt=…, output_schema=WEBSITE_SCHEMA, model=…)` → `verified = registrable_domain(answer["website_domain"]) or domain0`; record `{"websets_domain": domain0, "verified_domain": verified, "evidence_url": …}` in the snapshot; **dedupe**: `verified` in the workspace's `account_entity.primary_domain` set (one SQL per run) → `disposition = duplicate_of_existing`, no further spend; `verified` in `unapproved_domains(before_run_id=run_id)` → `not_chosen_before`, no spend; else `upsert_candidate` (`pass_="strict"`), then **verify every gate**: `exa.answer(gate_question(name, f"https://{verified}", gate), system_prompt=system_prompt(today), output_schema=OUTPUT_SCHEMA, model=settings.arv2_discovery_answer_model, label=f"discovery-{gate.key}-{verified}")` → `apply_guards(...)`; `fit_score`, `disposition`; **write the account**: `insert_account_entity(conn, canonical_name=item.name, primary_domain=verified, workspace_id=…, status=AccountStatus.CANDIDATE)`; claims through `writer.write(conn, ClaimDraft(...))`: `account.scoring.fit` `{"value": fit}` (`extraction_method=ExtractionMethod.API`, `run_id=RunId(run_id)`, `research_mode=ResearchMode.ACCOUNT_DISCOVERY`, `source_key="exa_answer"`, `source_url=<first pass verdict's evidence_url or the verified site>`, `evidence_span=<that quote or None>`, `confidence=fit`, `markers={"discovery_run_id": str(run_id), "pass": "strict", "gates": {key: verdict}}`), `core.employee_count` when `item.employees` is an int (`source_key="exa_websets"`, `source_url=item.url`), `core.revenue_band` from `item.revenue_annual` when present (under_1m | 1m_10m | 10m_50m | 50m_100m | 100m_500m | 500m_1b | 1b_plus, arithmetic); `record_verdicts(...)` with `account_entity_id`.
5. `shown = count(disposition in pass/partial/unclear)`; **relaxed pass** when `shown < target_count` and (`run.relaxed_enabled` or `run.relaxed_requested`): `criteria_relaxed` = `brief.criteria` minus the criterion with the lowest `criteria_success_rates` value on the strict search (ties: the last), `websets.add_search(webset_id, query=brief.query, count=target_count - shown, criteria=criteria_relaxed, exclude_search_ids=[strict_search_id])`; poll; `items`; the same per-item flow with `pass_="relaxed"`, skipping items whose domain is already a candidate of this run.
6. `finish_discovery_run(status="completed" (or "needs_review" on the wall), found_strict, found_relaxed, analyzed=sum of searches' analyzed, receipt={"asked", "recall_estimate", "shown", "target_count", "criteria", "criteria_relaxed", "guards": {guard: count}, "cost_usd": ledger total, "duplicates", "not_chosen_before"})`; `WorkResult(outcome=status, references={"run_id"})`.
7. Any exception → `log.exception`, `finish_discovery_run(status="needs_review", …, receipt={"failure": code, "message"})`; drains shielded like the account driver.

- [ ] **Step 1: Write the failing offline driver tests** `tests/arv2/test_discovery_driver.py` with: an in-memory `_Store` recording every store call (the account driver's tests do this — read `tests/arv2/test_account_research_driver.py` `_handler()` and the store stub pattern and mirror it), `_ScriptedClients` whose `websets(caller)` returns a `_FakeWebsets` scripted with `create → running`, `get → idle with found/analyzed/successRates`, `items → [Probook@probook.com, Patientdesk]`, `add_search → …`, and `exa(caller)` returns a `_FakeExa` scripted with `answer` responses keyed by the question's gate/company (website question → `probook.ai`), a `_FakeWriter` collecting drafts, `_fake_conn_factory` (an `AsyncMock` connection is enough for the offline tests since the store is stubbed and `insert_account_entity` is monkeypatched to return a fixed id), `transport_factory=lambda: ScriptedTransport([])`, `sleep` as a no-op. Tests:

```python
def test_strict_pass_verifies_every_candidate_writes_fit_and_records_the_receipt() -> None
    # Probook: websets url probook.com, website verification → probook.ai, 4 gates pass → fit 1.0, disposition pass, one account entity, fit claim value 1.0, employee_count claim; Patientdesk: stage fail (grounded) → partial fit 0.5; receipt asked=35, shown=2, guards counted; run finished completed
def test_a_candidate_matching_an_existing_account_is_a_duplicate_with_no_spend() -> None
def test_an_earlier_unapproved_candidate_of_the_project_is_not_chosen_before_and_not_re_verified() -> None
def test_the_relaxed_pass_runs_when_short_and_drops_the_lowest_success_criterion() -> None
    # target 3, strict finds 1 → add_search called with count 2 and criteria minus the min-successRate one, exclude = [strict search id]; relaxed items get pass_="relaxed"
def test_no_relaxed_pass_when_disabled_and_not_requested() -> None
def test_a_requested_relaxed_pass_on_a_finished_run_skips_the_strict_pass() -> None
def test_the_wall_clock_ends_the_run_needs_review_with_the_reason() -> None
def test_a_provider_failure_is_contained_as_needs_review_and_the_ledger_is_still_drained() -> None
```

- [ ] **Step 2: Run → FAIL. Step 3: Implement `discovery_driver.py`** (docstring: the spec §2–§4 steps; the money law; the guard counts on the receipt). **Step 4: Run → PASS.**

- [ ] **Step 5: DB test** `tests/arv2/test_discovery_driver_db.py`: one scenario on `rollback_conn` with the real store and real writer (`LenientClaimWriter(lenient=True)`, `load_core_pack` + `load_arv2_pack` first), scripted clients as above, asserting: the candidate rows, the `account_entity` with `status='candidate'` and `primary_domain='probook.ai'`, the `account.scoring.fit` claim readable through `frontend_read.accounts_list`'s fit read for the project (call `_read_scores` or the public helper it wraps; assert `fit_score_100(...) == 100` for Probook), the `run_lineage` join, and `provider_call_ledger` rows for `exa_answer`/`exa_websets` with the stamp's `project_id`.

- [ ] **Step 6: Compose.** `fleet_main._build_arv2_discovery_handler(settings, secrets, *, storage)` → `None` unless `settings.arv2_discovery_enabled`, warning when `secrets.exa_api_key` is None; `build_arv2_discovery_handler(settings, secrets, storage=storage, artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=transaction))`; pass it to `build_multi_work_worker(arv2_discovery_handler=…)`; in `fleet_wiring.build_multi_work_worker` add the parameter, the `kind is not FleetTaskKind.ARV2_DISCOVERY → ValueError` check, and `handlers.append`. Extend `tests/api/test_fleet_wiring.py` with a stub handler of the new kind being registered and a wrong-kind refusal.

- [ ] **Step 7: Run** `uv run pytest tests/arv2/test_discovery_driver.py tests/arv2/test_discovery_driver_db.py tests/api/test_fleet_wiring.py -q -p no:cacheprovider` → PASS. Ruff/format. `uv run lint-imports` → 0 broken.

- [ ] **Step 8: Commit.** `git add platform/api/clue_api/arv2/discovery_driver.py platform/api/clue_api/fleet_main.py platform/api/clue_api/fleet_wiring.py tests/arv2/test_discovery_driver.py tests/arv2/test_discovery_driver_db.py tests/api/test_fleet_wiring.py && git commit -m "feat(arv2 r4): the discovery driver — websets long list, answer verification with guards, candidate accounts with fit, strict then relaxed pass"`

---

### Task 7: Approval stamps the candidate row

**Files:**
- Modify: `platform/api/clue_api/frontend_read/bulk_actions.py` (after `ensure_project_accounts` in `add_accounts_to_project`)
- Test: `tests/api/test_frontend_bulk_actions_discovery_db.py`

**Interfaces:** consumes `discovery_store.mark_candidates_approved(conn, workspace_id=, project_id=, account_entity_ids=, decided_by_user_id=)`.

- [ ] **Step 1: Write the failing test** (drive the existing bulk-action route the way `tests/api/test_frontend_bulk_actions_db.py` — or whatever file already tests `add_to_project` — does; seed a discovery run + candidate with `account_entity_id` set):

```python
def test_add_to_project_marks_the_discovered_candidate_approved() -> None:
    # seed project, account, discovery run, candidate(account_entity_id=account, decision None)
    # POST the bulk action with that account id
    # assert project_account row exists AND the candidate row has decision='approved', decided_by_user_id = the actor, decided_at not None
    # a second POST (new idempotency key) leaves decided_at unchanged (mark_candidates_approved touches decision IS NULL only)
```

- [ ] **Step 2: Run → FAIL. Step 3: Implement**: after `inserted = await ensure_project_accounts(...)`, add

```python
            # ARV2 R4 (ruling 2, rev 2): adding a discovered account to the project IS its
            # approval. The candidate row learns who approved it and when; rows never added stay
            # unapproved — not rejected (ruling 1′) — and a later run does not re-surface them.
            await mark_candidates_approved(
                conn,
                workspace_id=workspace_id,
                project_id=body.project_id,
                account_entity_ids=tuple(inserted),
                decided_by_user_id=actor_user_id,
            )
```

with `from clue_api.arv2.discovery_store import mark_candidates_approved`. **Step 4: Run → PASS.** Also run `tests/api/test_frontend_*bulk*` to confirm nothing else moved.

- [ ] **Step 5: Commit.** `git commit -am "feat(arv2 r4): add-to-project stamps the discovered candidate approved" -- platform/api/clue_api/frontend_read/bulk_actions.py tests/api/test_frontend_bulk_actions_discovery_db.py`

---

### Task 8: The Head-of-ABM profile bump (v45), skill v22, recipe v23

**Files:**
- Create: `platform/agents/catalog/profiles/head-of-abm/v45/profile.yaml` (copy v44; add the tool; pin `stage0-interview` `v22`; header comment names R4), `platform/agents/catalog/skills/stage0-interview/v22/SKILL.md` (copy v21; frontmatter `version: v22`; tools list gains `launch_arv2_discovery@1` with its live digests; a new section **"7b. Discover accounts for this project"** between §7 and §8 — text below, founder-reviewed), `platform/execution/recipes/recipe0-stage0-v23.json` (v22 with `launch_arv2_discovery@1` at the four insertion points where `launch_arv2_person_research@1` sits, `"version": 23`)
- Modify: `agent_registry_wiring.py` (`AgentRole.HEAD_OF_ABM: "v45"`; `C6_AGENT_TOOL_AUTHORITY["launch_arv2_discovery"] = (AgentRole.HEAD_OF_ABM,)` with a comment; the trial-surface withheld set gains `"launch_arv2_discovery"`), `recipe_contracts.py` (`RECIPE_0_TOOL_ADDRESSES` gains `"launch_arv2_discovery@1"`; `CONVERSATION_RECIPE_VERSION = 23` wherever it is defined), `recipe_wiring.py` (`SYSTEM_RECIPE_FILENAMES` gains `"recipe0-stage0-v23.json"` after v22, promoted the way O6's `7039c6da8` promoted v22 — read that commit), `stage0_recipe.py` (the `_execution_project_pin` tool-name set gains `"launch_arv2_discovery"`), `chat/composer_context.py` (`PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v45"`)
- Test: `tests/api/test_agent_registry_wiring.py` (v45 comment + measured digest; counts 142→143 at both sites), `tests/agents/test_catalog.py` (`profile:head-of-abm@v45`, `skill:stage0-interview@v22`), `tests/agents/test_tool_authority_audit.py` (124→125; the grant assertion), `tests/api/test_recipe_contracts.py` (v23 minted without rewriting v22; version 23), `tests/api/test_c8_trial_surface.py` (`_WITHHELD` gains the tool), `tests/api/test_stage0_tool_guidance.py` / `test_lane_d4_model_planned_kickoff_db.py` / `test_o6_conversation_composition_db.py` (v44→v45 where they pin the promoted profile)

**Skill passage (§7b), the substance the founder reviews before the file is written:**

> ## 7b. Discover accounts for this project
>
> When the human asks you to find accounts, and this project has a confirmed ICP and a confirmed product set, call `launch_arv2_discovery` with `project_id` and the number of accounts the human wants (`target_count`). Leave `relaxed_enabled` on unless the human says they want strict matches only.
>
> What happens next is not yours to do: the platform finds candidate companies from the ICP, checks each one against every gate of the ICP with a quote and a source, and lists them on the accounts table with a fit. The human approves accounts there by adding them to the project. A successful result means the discovery is running. Say that, and say where the accounts will appear. It is never a finished list, and you never name accounts you have not been shown.
>
> If the human asks for more accounts after a discovery finished short, say that a relaxed pass can be run for that discovery and that it shows partial matches with a weaker fit, honestly. Do not start a second discovery for the same target; the platform re-runs the existing one.

- [ ] **Step 1: Controller step (Fable, not the implementer):** present the §7b passage to the founder in chat; apply edits to this plan before dispatching the task.

- [ ] **Step 2: Write the failing tests first** (registry: `AgentRole.HEAD_OF_ABM` active version `"v45"` and the digest placeholder measured off the tree per the file's convention; catalog lists; authority `len == 125` and `C6_AGENT_TOOL_AUTHORITY["launch_arv2_discovery"] == (AgentRole.HEAD_OF_ABM,)`; recipe test `test_r4_mints_recipe_v23_without_rewriting_v22` modelled on the O6 one; trial surface withheld set). Run → FAIL.

- [ ] **Step 3: Create the files and edits** listed above. Digests: read the tool's input/output schema digests off the live `build_toolbelt` descriptor the way O6 did (`tests/api/test_agent_registry_wiring.py` documents the measurement); the profile's resource-manifest digest is measured from the tree and pinned in the test with a comment "v45 (ARV2 R4) is v44 plus `launch_arv2_discovery@1` and stage0-interview v22; digest measured off this tree".

- [ ] **Step 4: Run** `uv run pytest tests/api/test_agent_registry_wiring.py tests/agents/test_catalog.py tests/agents/test_tool_authority_audit.py tests/api/test_recipe_contracts.py tests/api/test_c8_trial_surface.py tests/api/test_stage0_tool_guidance.py tests/api/test_toolbelt_wiring.py -q -p no:cacheprovider` → PASS except the recorded pre-existing reds. Standing-rule item 1 (`grep` the v45 profile for any readiness/Stage-0/Client-KB tool → none).

- [ ] **Step 5: Commit.** `git add platform/agents/catalog/profiles/head-of-abm/v45 platform/agents/catalog/skills/stage0-interview/v22 platform/execution/recipes/recipe0-stage0-v23.json platform/api/clue_api/agent_registry_wiring.py platform/api/clue_api/recipe_contracts.py platform/api/clue_api/recipe_wiring.py platform/api/clue_api/stage0_recipe.py platform/api/clue_api/chat/composer_context.py tests/ && git commit -m "feat(arv2 r4): head-of-abm@v45 grants launch_arv2_discovery@1 — stage0-interview v22 teaches it, recipe v23 admits it"`

---

### Task 9: Docs, memory, standing-rule checklist, close-out

**Files:**
- Modify: `platform/api/clue_api/arv2/README.md` (new section `## R4 — verified account discovery` after the O6 section: the module map, the run's steps, the three guards, the settings, the CLI, the approval stamp, what is deliberately not built: exclusion import, concurrency cap, frontend), `docs/specs/ARV2-MASTER-PLAN.md` (R4 row: "built 2026-09-1x; live exit gate owed" + the evidence path), `_memory/README.md` (index line), create `_memory/2026-09-10-arv2-r4-discovery.md` (what landed per task, rulings honoured with dates, verification commands and counts, pre-existing reds left alone, follow-ups: Websets exclusion import once Exa confirms the cap; worker scheduling discussion; the chat gate after the target-accounts tab; the recall angles if pools prove short; `exa-pro` comparison)
- Run the 7-item checklist in `_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md` and record each item's evidence in the memory note.

- [ ] **Step 1: Write the docs.** **Step 2: Run the full offline gate** `uv run pytest tests/arv2 tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py tests/api/test_toolbelt_wiring.py tests/agents tests/api/test_frontend_read_accounts_list.py tests/api/test_frontend_bulk_actions_discovery_db.py tests/db/test_arv2_r4_migration.py tests/fleet --ignore-glob='*_live.py' -p no:cacheprovider -q`, `uv run ruff check` + `ruff format --check` on every file the slice touched, `uv run lint-imports`, `uv run alembic heads` = 1. Record all counts in the memory note.

- [ ] **Step 3: Commit.** `git add platform/api/clue_api/arv2/README.md docs/specs/ARV2-MASTER-PLAN.md _memory/2026-09-10-arv2-r4-discovery.md _memory/README.md && git commit -m "docs(arv2 r4): README section, master plan row, memory close-out, standing-rule checklist"`

---

### Task 10: Live acceptance — the R4 exit gate (Fable-run, founder present; spends Exa credits and, at launch, R2 provider calls)

Not an implementer task. On the lane stack (`clue_san-salvador`, this worktree's fleet worker restarted by reproducing `.env` with `CLUE_ARV2_DISCOVERY_ENABLED=true`):

- [ ] Workspace with the Clue ICP pinned to a project (the answer-key workspace, or seed the confirmed document and pin it with the CLI/gate as O6's acceptance does).
- [ ] `uv run python scripts/launch_arv2_discovery.py --workspace … --project … --target 20` → receipt; watch the worker; `--report <run_id>` when finished.
- [ ] Record under `.context/arv2-r4-acceptance/`: the run row (asked / found_strict / found_relaxed / analyzed / recall_estimate), the candidates table, guard hit counts, hand-graded precision on a 10-company sample, whether Probook and Zafran surfaced, cost per shown company from the ledger (recorded, not capped), time to idle, the relaxed pass's contribution.
- [ ] Open `localhost:3000/accounts` (dummy frontend against the lane API): every discovered account listed with Overall fit and Fit score, Research status "Not started"; tick rows → "Add to project"; `--report` shows `decision = approved`.
- [ ] Launch research on the approved cohort through the existing account launch (chat via v45, or `scripts/launch_arv2_account_research.py`); confirm jobs run; the accounts table shows research status moving.
- [ ] Standing-rule checklist 7/7 on the merged tree; memory addendum; master plan R4 row marked done with the date.

---

## Self-review

- **Spec coverage:** §1 principle → Tasks 4 (brief from the document; guards only) and 6 (no gate code). §2 Websets (≤3 criteria, recall, exclusion-by-dedupe, async, no money stop, search kept) → Tasks 3, 6; the Websets exclusion *import* is deferred by ruling and named as a follow-up in Task 9. §3 verifier (URL verification, dedupe, Answer per gate, prompt, schema, three guards, unclear-never-fail, aggregators, verdict storage, fit) → Tasks 4, 6. §4 strict/relaxed/exhausted with both triggers → Tasks 5 (request), 6 (auto + requested), receipt fields. §5 no frontend change, fit claim, firmographics, "Not started", approval via add-to-project, unapproved memory → Tasks 6, 7, 2. §6 launch via existing tool, no cap, discovery as a fleet job, the two tables, raw + ledger → Tasks 2, 5, 6. §7 profile bump in R4 → Task 8. §8 acceptance → Task 10. §9 rulings: each is named at the step that honours it.
- **Placeholder scan:** the four `...` test bodies in Task 5 Step 1 are named scenarios with their assertions stated in the comment line; the implementer writes them from those statements. The migration downgrade instructs copying a precedent's enum recreation rather than pasting it, because the label list must be read from the tree at implementation time. Everything else is spelled out.
- **Type consistency:** `DiscoveryRunRow` / `CandidateRow` names and fields are used identically in Tasks 2, 5, 6; `GateVerdict.as_json()` feeds `record_verdicts(verdicts=…)`; `Arv2DiscoveryReceipt.to_enqueue: bool` is consumed by `enqueue_discovery_run`; `ExaWebsetsClient.items()` returns `WebsetItemsResult` whose `items` the driver iterates; `WebsetSearchView.criteria_success_rates` drives the relaxed criterion choice.
