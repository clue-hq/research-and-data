# ARV2 D1 — the display substrate migration, the lenient claim writer, and the answer-key loader

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After D1 the database can hold ARV2 research (priority, outreach-safety, display blocks, section recipes, the provider ledger, owner columns, activity events), the claim store has a lenient write path that stores instead of refusing, and the Zafran and ten-person answer keys are real rows in Postgres with entities, lineage, committee coverage and media artifacts behind them.

**Architecture:** One hash-id Alembic revision adds every D1 object. A small contract-delta on frozen `clue_core.Claim` carries `signal_priority`, `outreach_safe` and `write_markers` through `insert_claim`. A new `clue_api.arv2.claim_writer.LenientClaimWriter` wraps `Claim` construction and `insert_claim` so an unknown key registers a proposed field, a schema miss is stored with a marker, and a missing URL is stored with a marker. A pure mapping module turns the two proof-of-concept JSON files into `ClaimDraft`s; a loader module writes them plus the spine rows the accounts screens need; a thin `scripts/` wrapper runs it against an explicit database.

**Tech Stack:** Python 3.12, pydantic v2 frozen models, SQLAlchemy async + asyncpg, Alembic (hand-written raw SQL), pytest (sync bodies + `run_async`), uv workspace, ruff (line length 100), mypy strict on `platform/api/clue_api`.

**Spec:** `docs/specs/ARV2-MASTER-PLAN.md` v1.6 (§2 principles, §4 data model, §5 seams, §9 Track D step D1, §12 D4/D8/D13), `docs/specs/ARV2-DATA-SOURCE-MAP.md` v1.1 (§2.2 the D1 tables, §3.9 evidence, §5 rulings), `docs/specs/ARV2-WORK-SPLIT.md` §4 rows A2/A3. Founder rulings 2026-09-07 recorded in those documents. Decisions this plan takes that the spec left open are listed in "Decisions taken by this plan" below; they are recorded in the memory note in Task 7 and surfaced to the founder in the close-out report.

## Decisions taken by this plan (each is a ruling the founder can overturn; none blocks execution)

1. **Where the write markers live.** Master plan §4 lists the markers (`schema_valid`, `source_missing`, `evidence_verbatim`, `unevidenced`, `entailment`) but gives them no column. They live in a new nullable `claim.write_markers jsonb` column, written once at insert, mutable in place (they are write-time annotations, not provenance).
2. **A claim may exist without a source URL.** `clue_core.Claim` today refuses an `api`, `scrape` or `llm_synthesis` claim with no `source_url`. Lenient mode needs such rows to exist with a `source_missing` marker (§2 principle 2). The rule moves from construction to promotion: `Claim` accepts a missing URL; `can_be_promoted` additionally returns `False` when a URL-requiring method has no URL. Nothing verified today has no URL, so no existing row changes meaning.
3. **`Persona` gains `user` (D8) with no DDL**, because `persona` is not a Postgres enum; it is an `enum` list inside three registered value schemas. The migration rewrites those three `field_definition.value_schema` rows so an already-migrated database does not raise `FieldRedefinitionError` when packs reload.
4. **Persona mapping for the Zafran committee.** The run used two values outside the vocabulary. `executive_sponsor` → `economic_buyer` (Sanaz Yashar, CEO); `adjacent_buyer` → `user` (Tom Anthony, SVP Global Sales — the plan's own definition of `user`: "sales lead / the person who operates the tool daily"). The malformed duplicate persona row for Nick Fisher (`zaf-164`) is skipped as a duplicate of `zaf-039`.
5. **Priority for the Zafran account run.** All 174 rows carry `priority: null`. The loader stamps priority from a field-key table (below), not from a model; the ten-person rows keep their own `P1/P2/P3`.
6. **`NOT FOUND` rows are not claims.** Four Zafran rows (`zaf-130`…`zaf-133`) carry the string `NOT FOUND…` as a value. They are recorded in the load report as `not_found`, never written (empty is the correct output).
7. **Deep-dossier sources have no URL.** Synthesized rows cite `BUNDLE: SOURCE A` etc. A = the Exa deep-reasoning dossier (no URL → `source_missing`), B = `https://www.zafran.io/`, C–F = the podcast, two videos and Nick's article. Multi-source labels resolve to the first label with a URL.
8. **Media rows carry their media fields inside `value_json`.** Rows with `media_url` are written as `{"text": <value>, "media_url": …, "media_timestamp": …}` so the source map's `value_json.media_timestamp` read works; where the registered schema is a plain string this sets `schema_valid=false`, which is the lenient contract.
9. **Every ARV2 claim is `tenant_private` with a workspace id.** Accounts are workspace-local (founder ruling 2026-07-22); a claim more private than its field is always allowed, so the writer never hits `ReuseScopeError`.
10. **Identity binding for the Zafran rows** (which carry none): `STRONG` when `source_kind` ∈ {`provider_database`, `transcript_self`, `company_primary`} (name-scoped AI Ark, the person's own media, the company's own pages), else `WEAK`. The ten-person rows keep their own `STRONG`.
11. **The three non-Zafran companies** in the ten-person set (Cogent Security `cogent.com`, Harmonic Security `harmonic.security`, UPTIQ `uptiq.ai`) get account entities, project membership and their contacts, but no research run, job, or committee coverage — their status is honestly `not_started` and their people are stored for R3's acceptance.
12. **The loader is one-shot per database**, keyed on a deterministic run id; a second run refuses with a typed message rather than duplicating rows.

## Global Constraints (bind every task)

1. **Every new configuration knob is a `Settings` field and a `.env.example` line with its default in the same commit** (CLAUDE.md parity rule). Never change an existing `.env.example` value.
2. **Migration conventions** (CLAUDE.md): hash revision id from `uv run alembic revision -m "<slug>"`; `down_revision = "44039cb83844"` (the current single head); raw SQL via `op.execute`; constraint names `<table>_<predicate>`, index names `<table>_<purpose>`, no `ck_`/`ix_` prefixes; `COMMENT ON` every new table and column; `downgrade()` drops everything `upgrade()` created (the `test_no_domain_tables_at_m0_head` guard downgrades to `0001`).
3. **`platform/api/clue_api/arv2/` imports nothing quarantined.** Allowed internal prefixes: `clue_api.arv2`, `clue_core`, `clue_config`, `clue_obs`, `clue_storage`, `clue_db`, `clue_gateway`, `clue_locks`, `clue_spine`, `clue_toolbelt`, `clue_fleet`, `clue_agents`, `clue_execution`, `clue_auth`, `clue_projections`, `clue_research.claimstore`. `tests/arv2/test_import_guard.py` enforces this over every `.py` under `arv2/`. **This plan adds two more allowed prefixes** in Task 4 (`clue_research.identity`, `clue_research.membership`, `clue_research.durable.project_run`) — see that task; they are entity/membership writers the master plan keeps, not quarantined machinery.
4. **No old-lane gate on any new path** (standing rule, `_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`): the loader never sets `project_run.product_id`, `client_entity_id`, `client_kb_version` or `readiness_decision_id`; it never binds the demo account as the workspace client.
5. **Code style:** `from __future__ import annotations`; ruff line length 100; mypy `strict` (`clue_api` is in the mypy file set); frozen pydantic models or frozen dataclasses for value types; docstrings state the rule a function implements. `print` is banned outside `scripts/` and `tests/` (ruff `T20`).
6. **Database tests** use `CLUE_DATABASE_URL`; they skip when unset. This worktree's database is the `clue-pg-managua` container on `localhost:55060` (user/password/db `clue`). Migration smoke and the loader's DB test run only against that throwaway database, never the shared dev database. Before Task 1, create the worktree `.env` from `.env.example` and set `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55060/clue`; leave every flag at its example value.
7. **Commits:** on the task branch only; message says what and why; **no Co-Authored-By and no AI attribution**; never push.
8. **Reports:** the implementer writes its full report to the report path in its dispatch and returns only the short status contract. Every report cites the exact command output for its exit gate.
9. **Known pre-existing failures** (`_memory/2026-09-01-r0-step2-merge-complete.md`): 11 test reds, one mypy error (`ad_assets.py:149`), 10 unformatted files, 9 ruff findings. Anything else red after your change is yours.
10. **Answer-key inputs (read-only):** `.context/arv2-one-account-aiark/claims_zafran.json` (174 rows), `.context/arv2-one-account-aiark/transcripts/{sanaz_boardroom.md,nick_supporting_cc.md,nick_moscow_mule.md}`, `.context/arv2-person-depth/claims_people.json` (10 people, 119 rows), `.context/arv2-person-depth/roster.json` (domains). Never edit them.

## File structure

| File | Responsibility |
|---|---|
| `alembic/versions/<hash>_arv2_d1_display_substrate.py` | The D1 migration (Task 1) |
| `libs/clue-config/clue_config/settings.py` | Five leniency/check flags (Task 1) |
| `.env.example` | The five lines (Task 1) |
| `tests/db/test_arv2_d1_migration.py` | Column/table presence + single head (Task 1) |
| `tests/arv2/test_settings.py` | Extended with the five flags (Task 1) |
| `libs/clue-core/clue_core/enums.py` | `Persona.USER` (Task 2) |
| `libs/clue-core/clue_core/claim.py` | Three new `Claim` fields; URL rule moves to promotion (Task 2) |
| `subsystems/research/clue_research/claimstore/claims.py` | Insert/select the three columns (Task 2) |
| `tests/arv2/test_claim_contract_delta.py` | Pure model tests (Task 2) |
| `tests/claimstore/test_arv2_claim_columns.py` | DB round-trip (Task 2) |
| `platform/api/clue_api/arv2/catalog_seed.py` | `ARV2_PACK` seed rows + `load_arv2_pack` (Task 3) |
| `platform/api/clue_api/arv2_wiring.py` | Appends the loader to `RESEARCH_PACK_LOADERS` (Task 3) |
| `tests/arv2/test_catalog_seed.py` | Shape + registration tests (Task 3) |
| `platform/api/clue_api/arv2/claim_writer.py` | `ClaimDraft`, `WriteReceipt`, `LenientClaimWriter` (Task 4) |
| `tests/arv2/test_claim_writer.py` | Lenient/strict behaviour against the DB (Task 4) |
| `platform/api/clue_api/arv2/answer_key.py` | Pure mapping: PoC rows → drafts, manifest, report (Task 5) |
| `tests/arv2/test_answer_key.py` | Mapping rules (Task 5) |
| `platform/api/clue_api/arv2/answer_key_loader.py` | The DB loader (Task 6) |
| `scripts/load_arv2_answer_key.py` | argparse wrapper (Task 6) |
| `tests/arv2/test_answer_key_loader_db.py` | End-to-end load against the DB (Task 6) |
| `platform/api/clue_api/arv2/README.md`, `_memory/2026-09-07-arv2-d1-*.md`, `docs/specs/ARV2-MASTER-PLAN.md` §4, `docs/specs/ARV2-DATA-SOURCE-MAP.md` §2.2 | Close-out records (Task 7) |

---

## Task 1 — The D1 migration and the five flags

**Files:**
- Create: `alembic/versions/<hash>_arv2_d1_display_substrate.py` (id assigned by `alembic revision`)
- Modify: `libs/clue-config/clue_config/settings.py` (after line 328, the end of the ARV2 R1 block)
- Modify: `.env.example` (after line 145, `CLUE_ARV2_RAW_ROOT=.artifacts/arv2`)
- Modify: `tests/arv2/test_settings.py` (extend `ARV2_SETTING_DEFAULTS`)
- Create: `tests/db/test_arv2_d1_migration.py`

**Interfaces:**
- Produces: tables `display_block`, `display_section_recipe`, `provider_call_ledger`, `account_activity_event`; columns `claim.signal_priority`, `claim.outreach_safe`, `claim.write_markers`, `account_entity.owner_user_id`, `account_entity.created_by_user_id`, `workspace_field_definition.presentation`; `Settings.claim_write_lenient: bool`, `Settings.evidence_verbatim_check: Literal["on","off"]`, `Settings.unevidenced_row_purge_enabled: bool`, `Settings.interview_entailment_check: Literal["on","off"]`, `Settings.sensitivity_floor_enabled: bool`.

- [ ] **Step 1: Write the failing migration test**

`tests/db/test_arv2_d1_migration.py`:

```python
"""D1 (master plan §4, source map §2.2): the display substrate lands as one reversible revision."""

from __future__ import annotations

from alembic.script import ScriptDirectory
from sqlalchemy import text

from clue_db import db_lifespan
from tests.claimstore.conftest import _alembic_config
from tests.db.conftest import run_async

import pytest

_EXPECTED_TABLES = {
    "display_block",
    "display_section_recipe",
    "provider_call_ledger",
    "account_activity_event",
}
_EXPECTED_COLUMNS = {
    ("claim", "signal_priority"),
    ("claim", "outreach_safe"),
    ("claim", "write_markers"),
    ("account_entity", "owner_user_id"),
    ("account_entity", "created_by_user_id"),
    ("workspace_field_definition", "presentation"),
}


def test_single_alembic_head() -> None:
    heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
    assert len(heads) == 1, heads


@pytest.mark.usefixtures("require_claimstore_db")
def test_d1_objects_exist_at_head() -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            tables = {
                row[0]
                for row in await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            }
            assert _EXPECTED_TABLES <= tables, _EXPECTED_TABLES - tables
            cols = {
                (row[0], row[1])
                for row in await conn.execute(
                    text(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public'"
                    )
                )
            }
            assert _EXPECTED_COLUMNS <= cols, _EXPECTED_COLUMNS - cols
            defaults = {
                row[0]: (row[1], row[2])
                for row in await conn.execute(
                    text(
                        "SELECT column_name, column_default, is_nullable "
                        "FROM information_schema.columns WHERE table_name = 'claim' "
                        "AND column_name IN ('signal_priority','outreach_safe','write_markers')"
                    )
                )
            }
            assert defaults["signal_priority"] == ("3", "NO")
            assert defaults["outreach_safe"] == ("true", "NO")
            assert defaults["write_markers"][1] == "YES"

    run_async(_check())


@pytest.mark.usefixtures("require_claimstore_db")
def test_persona_schemas_admit_user_after_migration() -> None:
    """D8: the three persona-bearing registry rows carry ``user`` once packs have loaded."""

    async def _check() -> None:
        from clue_research.claimstore.packs import load_core_pack
        from clue_research.profiling.committee.fields import load_committee_pack

        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                await load_core_pack(conn)
                await load_committee_pack(conn)  # raises FieldRedefinitionError if drifted
                row = (
                    await conn.execute(
                        text(
                            "SELECT value_schema->'enum' FROM field_definition "
                            "WHERE field_key = 'contact.persona'"
                        )
                    )
                ).scalar_one()
                assert "user" in row
            finally:
                await trans.rollback()
                await conn.close()

    run_async(_check())
```

Note: `test_persona_schemas_admit_user_after_migration` passes only after Task 2 adds `Persona.USER`; leave it red until then and say so in the report.

- [ ] **Step 2: Run the test to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/db/test_arv2_d1_migration.py -q`
Expected: `test_d1_objects_exist_at_head` FAILS with missing tables; `test_single_alembic_head` PASSES.

- [ ] **Step 3: Generate the revision and write it**

Run: `uv run alembic revision -m "arv2_d1_display_substrate"` and open the generated file under `alembic/versions/`. Replace its body with the following (keep the generated `revision` id; set `down_revision = "44039cb83844"`):

```python
"""ARV2 D1 — the display substrate: priority/outreach-safety/write-markers on claim, owner columns
on account_entity, display_block, display_section_recipe, provider_call_ledger,
account_activity_event, workspace_field_definition.presentation, and the persona vocabulary
data-fix (Persona gains ``user``).

Master plan v1.6 §4 and ARV2-DATA-SOURCE-MAP v1.1 §2.2. Conventions: append-only claim history,
UTC timestamptz, jsonb payloads with indexed hot keys, everything keyed on entity ids, forward +
reverse.

The persona vocabulary is not a Postgres enum: it is the ``enum`` list inside three registered
value schemas (``contact.persona``, ``contact.role_on_committee``, ``account.value_narrative``),
built at pack-load time from ``clue_core.Persona``. Adding ``user`` to the Python enum changes
those schemas, and ``register_field`` refuses a redefinition, so this revision rewrites the stored
rows to match. On a fresh database the UPDATEs touch zero rows; that is fine.

The three new claim columns are deliberately NOT added to the append-only immutable-column guard:
``signal_priority`` and ``outreach_safe`` are governance annotations whose change is a display
invalidation event (master plan §7), and ``write_markers`` records write-time checks. Supersession
remains the way a value changes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "<generated>"
down_revision: str | None = "44039cb83844"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


_COMMENTS: tuple[tuple[str, str], ...] = (
    ("claim.signal_priority", "ARV2 signal priority: 1 active buying intent, 2 qualifying fact, 3 context. Stamped at write time; orders display items, never gates."),
    ("claim.outreach_safe", "ARV2 appropriateness flag, distinct from accuracy: false confines the claim to restricted display sections and bars it from outreach copy."),
    ("claim.write_markers", "ARV2 lenient-write annotations recorded at insert (schema_valid, source_missing, proposed_field, identity_binding_defaulted, use_class_defaulted, pipe_joined_key, evidence_verbatim, unevidenced, entailment). NULL = nothing to note."),
    ("account_entity.owner_user_id", "Assigned account owner (a workspace user). NULL = unassigned; the frontend then shows createdBy, else 'Unassigned' — never the viewer (ruling R6)."),
    ("account_entity.created_by_user_id", "The user who created the account; NULL when an agent or loader created it."),
    ("display_block", "One persisted display section for one subject and page: the Luna-written body with the claim ids every sentence cites. Generated once on first request, superseded on recipe-scoped invalidation (master plan §7)."),
    ("display_section_recipe", "One page section's allow-list of field keys plus its served heading and layout flags. NULL workspace_id = the system row; a workspace row overrides it."),
    ("provider_call_ledger", "One row per provider-call phase (estimate before the wire, result after) written by the ARV2 ProviderCaller; raw bodies are artifact rows the row references (Appendix A laws 1-2)."),
    ("account_activity_event", "The account activity feed: actor-based events written by the backend (account created, researched, committee confirmed, page written, artifact bound)."),
    ("workspace_field_definition.presentation", "How a custom variable renders on the accounts screens: text, badge or score (contract v1 customFields.presentation)."),
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE claim ADD COLUMN signal_priority smallint NOT NULL DEFAULT 3, "
        "ADD COLUMN outreach_safe boolean NOT NULL DEFAULT true, "
        "ADD COLUMN write_markers jsonb"
    )
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_signal_priority_range "
        "CHECK (signal_priority BETWEEN 1 AND 3)"
    )
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_write_markers_object "
        "CHECK (write_markers IS NULL OR jsonb_typeof(write_markers) = 'object')"
    )
    op.execute(
        "CREATE INDEX claim_live_unsafe ON claim (entity_id) "
        "WHERE superseded_by IS NULL AND outreach_safe = false"
    )

    op.execute(
        "ALTER TABLE account_entity ADD COLUMN owner_user_id text, "
        "ADD COLUMN created_by_user_id text"
    )
    op.execute(
        "ALTER TABLE account_entity ADD CONSTRAINT account_entity_owner_user_fk "
        "FOREIGN KEY (owner_user_id) REFERENCES platform_user (user_id)"
    )
    op.execute(
        "ALTER TABLE account_entity ADD CONSTRAINT account_entity_created_by_user_fk "
        "FOREIGN KEY (created_by_user_id) REFERENCES platform_user (user_id)"
    )

    op.execute(
        "ALTER TABLE workspace_field_definition ADD COLUMN presentation text "
        "NOT NULL DEFAULT 'text'"
    )
    op.execute(
        "ALTER TABLE workspace_field_definition ADD CONSTRAINT "
        "workspace_field_definition_presentation "
        "CHECK (presentation IN ('text', 'badge', 'score'))"
    )

    op.execute(
        """
        CREATE TABLE display_section_recipe (
            page                 text    NOT NULL,
            section_key          text    NOT NULL,
            workspace_id         text    NOT NULL DEFAULT '',
            h1                   text    NOT NULL,
            position             integer NOT NULL,
            allowed_field_keys   text[]  NOT NULL,
            restricted           boolean NOT NULL DEFAULT false,
            default_open         boolean NOT NULL DEFAULT false,
            instruction_version  text    NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT display_section_recipe_pkey
                PRIMARY KEY (page, section_key, workspace_id),
            CONSTRAINT display_section_recipe_page
                CHECK (page IN ('overview', 'insights', 'contact')),
            CONSTRAINT display_section_recipe_h1_nonempty CHECK (length(h1) > 0),
            CONSTRAINT display_section_recipe_position_nonneg CHECK (position >= 0)
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN display_section_recipe.workspace_id IS "
        "'Empty string = the system recipe (a NULL cannot sit in a primary key); a workspace id "
        "= that workspace''s override row.'"
    )

    op.execute(
        """
        CREATE TABLE display_block (
            display_block_id  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id      text        NOT NULL REFERENCES workspace (workspace_id),
            subject_kind      text        NOT NULL,
            subject_id        uuid        NOT NULL,
            page              text        NOT NULL,
            section_key       text        NOT NULL,
            body_json         jsonb       NOT NULL,
            cited_claim_ids   uuid[]      NOT NULL,
            model             text        NOT NULL,
            prompt_version    text        NOT NULL,
            recipe_version    integer     NOT NULL,
            generated_at      timestamptz NOT NULL DEFAULT now(),
            superseded_at     timestamptz,
            CONSTRAINT display_block_subject_kind
                CHECK (subject_kind IN ('account', 'contact')),
            CONSTRAINT display_block_page
                CHECK (page IN ('overview', 'insights', 'contact')),
            CONSTRAINT display_block_body_object CHECK (jsonb_typeof(body_json) = 'object')
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX display_block_live ON display_block "
        "(workspace_id, subject_kind, subject_id, page, section_key) "
        "WHERE superseded_at IS NULL"
    )
    op.execute(
        "CREATE INDEX display_block_subject ON display_block "
        "(workspace_id, subject_kind, subject_id, page)"
    )

    op.execute(
        """
        CREATE TABLE provider_call_ledger (
            ledger_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            call_id                 uuid NOT NULL,
            workspace_id            text,
            project_id              text,
            project_run_id          text,
            entity_research_job_id  uuid,
            provider                text NOT NULL,
            operation               text NOT NULL,
            label                   text NOT NULL,
            phase                   text NOT NULL,
            http_status             integer,
            latency_ms              integer,
            attempts                integer NOT NULL DEFAULT 0,
            estimate_usd            numeric(12, 6) NOT NULL DEFAULT 0,
            estimate_credits        numeric(12, 3) NOT NULL DEFAULT 0,
            estimate_media_seconds  integer NOT NULL DEFAULT 0,
            cost_usd                numeric(12, 6),
            credits                 numeric(12, 3),
            media_seconds           integer,
            over_ceiling            boolean NOT NULL DEFAULT false,
            outcome                 text NOT NULL,
            error_code              text,
            provider_request_id     text,
            request_artifact_key    text,
            response_artifact_key   text,
            recorded_at             timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT provider_call_ledger_phase CHECK (phase IN ('estimate', 'result')),
            CONSTRAINT provider_call_ledger_outcome CHECK (outcome IN (
                'estimate', 'ok', 'client_error', 'retry_exhausted', 'halted',
                'transport_error'))
        )
        """
    )
    op.execute(
        "CREATE INDEX provider_call_ledger_workspace_time ON provider_call_ledger "
        "(workspace_id, recorded_at)"
    )
    op.execute("CREATE INDEX provider_call_ledger_call ON provider_call_ledger (call_id)")

    op.execute(
        """
        CREATE TABLE account_activity_event (
            event_id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id       text        NOT NULL REFERENCES workspace (workspace_id),
            account_entity_id  uuid        NOT NULL,
            kind               text        NOT NULL,
            actor_kind         text        NOT NULL,
            actor_user_id      text        REFERENCES platform_user (user_id),
            text               text        NOT NULL,
            action             text,
            occurred_at        timestamptz NOT NULL,
            project_id         text,
            ref_json           jsonb,
            CONSTRAINT account_activity_event_account_fk
                FOREIGN KEY (account_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT account_activity_event_kind
                CHECK (kind IN ('created', 'contacts', 'summary', 'artifact', 'updated')),
            CONSTRAINT account_activity_event_actor_kind
                CHECK (actor_kind IN ('clue', 'person')),
            CONSTRAINT account_activity_event_actor_shape CHECK (
                (actor_kind = 'clue' AND actor_user_id IS NULL) OR
                (actor_kind = 'person' AND actor_user_id IS NOT NULL)),
            CONSTRAINT account_activity_event_text_nonempty CHECK (length(text) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX account_activity_event_feed ON account_activity_event "
        "(workspace_id, account_entity_id, occurred_at DESC, event_id DESC)"
    )

    # D8 data-fix: append 'user' to the three stored persona vocabularies where present.
    op.execute(
        """
        UPDATE field_definition
        SET value_schema = jsonb_set(value_schema, '{enum}', (value_schema->'enum') || '"user"')
        WHERE field_key = 'contact.persona'
          AND value_schema ? 'enum'
          AND NOT (value_schema->'enum') ? 'user'
        """
    )
    op.execute(
        """
        UPDATE field_definition
        SET value_schema = jsonb_set(value_schema, '{properties,role,enum}',
                                     (value_schema#>'{properties,role,enum}') || '"user"')
        WHERE field_key = 'contact.role_on_committee'
          AND value_schema#>'{properties,role,enum}' IS NOT NULL
          AND NOT (value_schema#>'{properties,role,enum}') ? 'user'
        """
    )
    op.execute(
        """
        UPDATE field_definition
        SET value_schema = jsonb_set(value_schema, '{properties,persona,enum}',
                                     (value_schema#>'{properties,persona,enum}') || '"user"')
        WHERE field_key = 'account.value_narrative'
          AND value_schema#>'{properties,persona,enum}' IS NOT NULL
          AND NOT (value_schema#>'{properties,persona,enum}') ? 'user'
        """
    )

    for target, comment in _COMMENTS:
        keyword = "COLUMN" if "." in target else "TABLE"
        op.execute(f"COMMENT ON {keyword} {target} IS {_literal(comment)}")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_activity_event")
    op.execute("DROP TABLE IF EXISTS provider_call_ledger")
    op.execute("DROP TABLE IF EXISTS display_block")
    op.execute("DROP TABLE IF EXISTS display_section_recipe")
    op.execute(
        "ALTER TABLE workspace_field_definition DROP CONSTRAINT IF EXISTS "
        "workspace_field_definition_presentation"
    )
    op.execute("ALTER TABLE workspace_field_definition DROP COLUMN IF EXISTS presentation")
    op.execute(
        "ALTER TABLE account_entity DROP CONSTRAINT IF EXISTS account_entity_owner_user_fk"
    )
    op.execute(
        "ALTER TABLE account_entity DROP CONSTRAINT IF EXISTS account_entity_created_by_user_fk"
    )
    op.execute(
        "ALTER TABLE account_entity DROP COLUMN IF EXISTS owner_user_id, "
        "DROP COLUMN IF EXISTS created_by_user_id"
    )
    op.execute("DROP INDEX IF EXISTS claim_live_unsafe")
    op.execute("ALTER TABLE claim DROP CONSTRAINT IF EXISTS claim_write_markers_object")
    op.execute("ALTER TABLE claim DROP CONSTRAINT IF EXISTS claim_signal_priority_range")
    op.execute(
        "ALTER TABLE claim DROP COLUMN IF EXISTS write_markers, "
        "DROP COLUMN IF EXISTS outreach_safe, DROP COLUMN IF EXISTS signal_priority"
    )
    # The persona 'user' label stays in the three value schemas: the Python enum keeps it, and a
    # pack reload against the downgraded row would refuse a redefinition otherwise.
```

Verify first that `account.value_narrative`'s stored schema nests the persona enum at `properties.persona.enum` (read `subsystems/research/clue_research/narrative/fields.py:91-126`); if the path differs, correct the third UPDATE's path and say so in the report.

Also read `alembic/versions/d091e3962833_b2_artifact_table_and_claim_artifact_key.py:127` (`_guard_function_sql`) to confirm the immutable-column guard enumerates columns explicitly, so the three new columns are outside it as this migration's docstring states. If the guard is instead a "whole row except allow-list" design, STOP and write a QUESTION.

- [ ] **Step 4: Add the five settings**

In `libs/clue-config/clue_config/settings.py`, insert after line 328 (`arv2_raw_root`):

```python
    # --- ARV2 lenient write gate and annotation checks (D1; master plan §2 items 2 and 6, §4) ---
    # The claim write gate stores instead of refusing: an unregistered key becomes a proposed field,
    # a schema miss is stored with ``schema_valid=false``, a missing source URL is stored with
    # ``source_missing``. False restores strict refusals. Env: ``CLUE_CLAIM_WRITE_LENIENT``.
    claim_write_lenient: bool = True
    # When "on", quoted spans are checked against cited claims and the verdict is recorded as a
    # marker; never a blocker. Env: ``CLUE_EVIDENCE_VERBATIM_CHECK``.
    evidence_verbatim_check: Literal["on", "off"] = "off"
    # When true, rows with no quote and no URL are purged by the compliance pass; when false they
    # are only marked ``unevidenced``. Env: ``CLUE_UNEVIDENCED_ROW_PURGE_ENABLED``.
    unevidenced_row_purge_enabled: bool = False
    # When "on", the interview records whether a typed value is entailed by the user's statement
    # as a marker; the value is never required to be a substring. Env:
    # ``CLUE_INTERVIEW_ENTAILMENT_CHECK``.
    interview_entailment_check: Literal["on", "off"] = "off"
    # The one default-on check: redact references to minors from a value and mark special-category
    # facts outreach_safe=false. It never drops a claim. Env: ``CLUE_SENSITIVITY_FLOOR_ENABLED``.
    sensitivity_floor_enabled: bool = True
```

In `.env.example`, insert after line 145:

```
# --- ARV2 lenient write gate + annotation checks (D1; master plan §2 items 2/6, §4) ---
# The claim write gate stores instead of refusing (unregistered key -> proposed field; schema miss
# -> schema_valid=false marker; missing URL -> source_missing marker). false = strict refusals.
CLUE_CLAIM_WRITE_LENIENT=true
# on = record a verbatim-quote verdict as a marker on the claim; never a blocker.
CLUE_EVIDENCE_VERBATIM_CHECK=off
# true = the compliance pass purges rows with no quote and no URL; false = it only marks them.
CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=false
# on = record whether a typed interview value is entailed by the user's statement; never required.
CLUE_INTERVIEW_ENTAILMENT_CHECK=off
# The one default-on check: redact minors references, mark special-category facts unsafe. Never drops.
CLUE_SENSITIVITY_FLOOR_ENABLED=true
```

In `tests/arv2/test_settings.py`, add these five entries to `ARV2_SETTING_DEFAULTS` (keep the existing ones):

```python
    "claim_write_lenient": True,
    "evidence_verbatim_check": "off",
    "unevidenced_row_purge_enabled": False,
    "interview_entailment_check": "off",
    "sensitivity_floor_enabled": True,
```

and add one test:

```python
def test_the_on_off_checks_load_from_their_env_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE.md: a Literal that rejects its own documented env form is a bug."""
    monkeypatch.setenv("CLUE_EVIDENCE_VERBATIM_CHECK", "on")
    monkeypatch.setenv("CLUE_INTERVIEW_ENTAILMENT_CHECK", "on")
    settings = Settings(_env_file=None)
    assert settings.evidence_verbatim_check == "on"
    assert settings.interview_entailment_check == "on"
```

- [ ] **Step 5: Run the migration smoke and the tests**

Run:
```bash
set -a; source .env; set +a
uv run alembic heads            # exactly one head, the new id
make db-smoke                   # up -> base -> up, green
uv run pytest tests/db/test_arv2_d1_migration.py tests/arv2/test_settings.py tests/db/test_db_migrations.py -q
```
Expected: one head; db-smoke green; every test green except `test_persona_schemas_admit_user_after_migration` (red until Task 2, because `Persona` has no `user` yet — report it as expected-red).

- [ ] **Step 6: Lint, type-check, commit**

Run: `uv run ruff format alembic/versions/<file> libs/clue-config tests/db/test_arv2_d1_migration.py tests/arv2/test_settings.py && uv run ruff check <same paths> && uv run mypy`
Expected: clean; mypy shows only the pre-existing `ad_assets.py:149` error.

```bash
git add alembic/versions/<file> libs/clue-config/clue_config/settings.py .env.example tests/db/test_arv2_d1_migration.py tests/arv2/test_settings.py
git commit -m "arv2(d1): display substrate migration + the five leniency/check flags

One reversible revision: claim.signal_priority/outreach_safe/write_markers, account_entity owner
columns, display_block, display_section_recipe, provider_call_ledger, account_activity_event,
workspace_field_definition.presentation, and the persona value-schema data-fix for D8. The five
flags land in Settings and .env.example in the same commit (parity rule)."
```

---

## Task 2 — Core contract-delta: `Persona.USER`, the three `Claim` fields, the URL rule

**Files:**
- Modify: `libs/clue-core/clue_core/enums.py:358-364`
- Modify: `libs/clue-core/clue_core/claim.py:91-210` (fields), `:203-208` (URL rule), `:265-287` (`can_be_promoted`)
- Modify: `subsystems/research/clue_research/claimstore/claims.py:49-88` (`_INSERT_SQL`, `_SELECT_COLUMNS`), `:110-152` (`_insert_params`), `:155-196` (`_row_to_claim`)
- Create: `tests/arv2/test_claim_contract_delta.py`
- Create: `tests/claimstore/test_arv2_claim_columns.py`

**Interfaces:**
- Produces: `Claim.signal_priority: int = 3` (1..3), `Claim.outreach_safe: bool = True`, `Claim.write_markers: dict[str, JsonValue] | None = None`; `Persona.USER = "user"`; `can_be_promoted` returns `False` for an `api`/`scrape`/`llm_synthesis` claim with no `source_url`.

- [ ] **Step 1: Write the failing pure tests**

`tests/arv2/test_claim_contract_delta.py`:

```python
"""D1 contract-delta on clue_core.Claim (master plan §4) and Persona.USER (D8)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    Persona,
    ResearchMode,
    can_be_promoted,
    new_entity_id,
    new_run_id,
)


def _claim(**overrides: object) -> Claim:
    base: dict[str, object] = {
        "entity_id": new_entity_id(),
        "entity_type": EntityType.ACCOUNT,
        "field_key": "core.account_name",
        "value_json": "Zafran Security",
        "source_tier": 1,
        "extraction_method": ExtractionMethod.API,
        "confidence": 0.9,
        "run_id": new_run_id(),
        "research_mode": ResearchMode.ACCOUNT_PROFILING,
        "workspace_id": "ws_test",
    }
    base.update(overrides)
    return Claim(**base)  # type: ignore[arg-type]


def test_persona_has_user() -> None:
    assert Persona("user") is Persona.USER
    assert [p.value for p in Persona] == [
        "champion", "economic_buyer", "technical_evaluator", "blocker", "user"
    ]


def test_new_fields_default_and_validate() -> None:
    claim = _claim()
    assert claim.signal_priority == 3
    assert claim.outreach_safe is True
    assert claim.write_markers is None
    stamped = _claim(signal_priority=1, outreach_safe=False, write_markers={"source_missing": True})
    assert stamped.signal_priority == 1
    assert stamped.write_markers == {"source_missing": True}
    with pytest.raises(ValidationError):
        _claim(signal_priority=0)
    with pytest.raises(ValidationError):
        _claim(signal_priority=4)


def test_an_api_claim_may_exist_without_a_url_but_cannot_be_promoted() -> None:
    claim = _claim(source_url=None, write_markers={"source_missing": True})
    assert claim.source_url is None
    assert can_be_promoted(claim) is False
    assert can_be_promoted(_claim(source_url="https://api.example.com/v1/companies")) is True


def test_a_human_claim_needs_no_url_and_is_promotable() -> None:
    claim = _claim(extraction_method=ExtractionMethod.HUMAN, source_url=None)
    assert can_be_promoted(claim) is True
```

`tests/claimstore/test_arv2_claim_columns.py`:

```python
"""The three D1 claim columns round-trip through insert_claim / claims_by_ids."""

from __future__ import annotations

import pytest

from clue_core import Claim, EntityType, ExtractionMethod, ResearchMode, new_run_id
from clue_research.claimstore import claims_by_ids, insert_claim
from clue_research.claimstore.tenancy import WorkspaceScope
from clue_research.identity import insert_account_entity
from tests.claimstore.conftest import rollback_conn
from tests.db.conftest import run_async
from tests._workspace import seed_workspace


@pytest.mark.usefixtures("require_claimstore_db")
def test_priority_outreach_and_markers_round_trip() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "ws_d1")
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=ws
            )
            claim = Claim(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="core.account_name",
                value_json="Zafran Security",
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                workspace_id=ws,
                signal_priority=2,
                outreach_safe=False,
                write_markers={"source_missing": True},
            )
            claim_id = await insert_claim(conn, claim)
            stored = (await claims_by_ids(conn, [claim_id], scope=WorkspaceScope.for_workspace(ws)))[
                claim_id
            ]
            assert stored.signal_priority == 2
            assert stored.outreach_safe is False
            assert stored.write_markers == {"source_missing": True}
            assert stored.source_url is None

    run_async(_run())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_claim_contract_delta.py tests/claimstore/test_arv2_claim_columns.py -q`
Expected: FAIL — `Persona("user")` raises `ValueError`; `Claim` rejects `signal_priority` (`extra="forbid"`); the DB test fails on the URL rule.

- [ ] **Step 3: Implement**

`libs/clue-core/clue_core/enums.py` — append to `Persona` after `BLOCKER`:

```python
    # Appended 2026-09-07 (ARV2 master plan D8): the person who operates the tool daily. Not a DB
    # enum — the value lives in registered value schemas; migration arv2_d1 rewrites stored rows.
    USER = "user"
```

`libs/clue-core/clue_core/claim.py` — after `verification_status` (line ~146) add:

```python
    # --- ARV2 D1 (master plan §4) ---
    # 1 = active buying intent, 2 = qualifying fact, 3 = context. Orders display items; never gates.
    signal_priority: Annotated[int, Ge(1), Le(3)] = 3
    # Appropriateness, distinct from accuracy: False confines the claim to restricted display
    # sections and bars it from outreach copy.
    outreach_safe: bool = True
    # Lenient-write annotations stamped at insert (schema_valid, source_missing, proposed_field,
    # identity_binding_defaulted, use_class_defaulted, pipe_joined_key, evidence_verbatim,
    # unevidenced, entailment). None = nothing to note.
    write_markers: dict[str, JsonValue] | None = None
```

(add `from annotated_types import Ge, Le` and `Annotated` to the imports if not already present — `primitives.py` uses the same). Then **delete** the URL block in `_check_provenance`:

```python
        # Web/synthesis claims must cite a source.
        if (
            self.claim_flavor is not ClaimFlavor.DERIVED
            and self.extraction_method in _URL_REQUIRED_METHODS
            and not self.source_url
        ):
            raise ValueError(f"extraction_method {self.extraction_method} requires a source_url")
```

and extend `can_be_promoted`:

```python
    url_required_but_missing = (
        claim.claim_flavor is not ClaimFlavor.DERIVED
        and claim.extraction_method in _URL_REQUIRED_METHODS
        and not claim.source_url
    )
    return not (tier4_without_span or weakly_bound_contact or url_required_but_missing)
```

Update the two docstrings: the `Claim` class docstring gains "it does **not** require a `source_url` for api/scrape/synthesis claims either — such a claim exists `UNVERIFIED` with a `source_missing` write marker and cannot be promoted (ARV2 D1, master plan §2)"; `can_be_promoted`'s bullet list gains the URL rule.

`subsystems/research/clue_research/claimstore/claims.py` — add `signal_priority, outreach_safe, write_markers` to `_INSERT_SQL`'s column list and `:signal_priority, :outreach_safe, CAST(:write_markers AS jsonb)` to its VALUES; add the three names to `_SELECT_COLUMNS`; in `_insert_params` add:

```python
        "signal_priority": claim.signal_priority,
        "outreach_safe": claim.outreach_safe,
        "write_markers": (
            None if claim.write_markers is None else serialize_value_json(claim.write_markers)
        ),
```

and in `_row_to_claim` add (using the same `row.get` idiom the late-added columns use):

```python
        signal_priority=int(row.get("signal_priority", 3)),
        outreach_safe=bool(row.get("outreach_safe", True)),
        write_markers=(
            None if row.get("write_markers") is None else decode_jsonb(row["write_markers"])
        ),
```

Then grep for tests that pinned the old construction-time URL rule and update them to assert on `can_be_promoted` instead:

Run: `grep -rn "requires a source_url" tests libs subsystems platform`
For each hit in a test, change the `pytest.raises(ValidationError)` expectation into an assertion that the claim constructs and `can_be_promoted(claim) is False`. List every file you touched in the report.

- [ ] **Step 4: Run the tests**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_claim_contract_delta.py tests/claimstore/test_arv2_claim_columns.py tests/db/test_arv2_d1_migration.py tests/claimstore tests/test_claim*.py -q`
Expected: all green, including the Task 1 persona test now that `Persona.USER` exists.

Then run the wider suites that construct claims: `uv run pytest tests/core tests/verification tests/identity tests/api/test_frontend_read_contacts.py tests/agents/test_o3_account_deep_behavior.py -q` — expected: only the known pre-existing reds.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff format libs/clue-core subsystems/research/clue_research/claimstore/claims.py tests/arv2 tests/claimstore/test_arv2_claim_columns.py && uv run ruff check <same> && uv run mypy && uv run lint-imports`

```bash
git add libs/clue-core/clue_core/enums.py libs/clue-core/clue_core/claim.py subsystems/research/clue_research/claimstore/claims.py tests/arv2/test_claim_contract_delta.py tests/claimstore/test_arv2_claim_columns.py <any updated tests>
git commit -m "core(arv2 d1): Claim carries signal_priority/outreach_safe/write_markers; URL rule moves to promotion; Persona gains user

The lenient write gate (master plan §2) needs a claim to exist without a source URL, stored with
a source_missing marker; promotion still requires one (can_be_promoted). Persona.USER per D8.
claims.py inserts and reads the three D1 columns."
```

---

## Task 3 — The ARV2 field pack (S3 seed rows) and its wiring

**Files:**
- Create: `platform/api/clue_api/arv2/catalog_seed.py`
- Create: `platform/api/clue_api/arv2_wiring.py`
- Create: `tests/arv2/test_catalog_seed.py`

**Interfaces:**
- Consumes: `clue_research.claimstore.packs.SeedField`, `load_pack`; `clue_core.FieldDef`, `PassKind`.
- Produces: `ARV2_PACK: tuple[SeedField, ...]`, `ARV2_FIELD_KEYS: frozenset[str]`, `async def load_arv2_pack(conn) -> None`, `def register_arv2_wiring() -> None` (appends `load_arv2_pack` to `RESEARCH_PACK_LOADERS`).

The registry validator accepts a small schema subset: a single scalar `type`, `enum`, `required`, `properties`, `items`, `maxItems`, `minimum`, `maximum`, `maxLength`. Never a list-valued `type`. Every sub-field optional except the one that identifies an item (master plan §4). `contact.facet.*` rows must carry `validation={"use_class_hint": ...}` and a `freshness_ttl` under 90 days.

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_catalog_seed.py`:

```python
"""S3: every field the answer keys and the display recipes use is a registered row."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from clue_api.arv2.catalog_seed import ARV2_FIELD_KEYS, ARV2_PACK, load_arv2_pack
from clue_core import FieldClass, classify_field_key
from clue_research.claimstore.packs import CORE_PACK
from clue_research.claimstore.registry import validate_value_against_schema
from clue_research.profiling.committee.fields import COMMITTEE_PACK
from clue_research.profiling.fields import DEEP_PROFILING_PACK

REPO = Path(__file__).resolve().parents[2]
ZAFRAN = REPO / ".context/arv2-one-account-aiark/claims_zafran.json"
PEOPLE = REPO / ".context/arv2-person-depth/claims_people.json"

_REGISTERED_ELSEWHERE = {
    str(seed.field_def.field_key) for seed in (*CORE_PACK, *DEEP_PROFILING_PACK, *COMMITTEE_PACK)
}


def _answer_key_field_keys() -> set[str]:
    keys: set[str] = set()
    for row in json.loads(ZAFRAN.read_text())["claims"]:
        key = row["field_key"].removeprefix("PROPOSED::")
        keys.update(key.split("|"))
    for person in json.loads(PEOPLE.read_text())["people"].values():
        for row in person["claims"]:
            keys.update(row["field_key"].split("|"))
    return keys


def test_pack_covers_every_answer_key_field_not_registered_elsewhere() -> None:
    missing = _answer_key_field_keys() - _REGISTERED_ELSEWHERE - ARV2_FIELD_KEYS
    assert not missing, sorted(missing)


def test_pack_does_not_redefine_an_existing_key() -> None:
    assert not (ARV2_FIELD_KEYS & _REGISTERED_ELSEWHERE)


def test_every_row_is_canonical_optional_and_facets_are_governed() -> None:
    for seed in ARV2_PACK:
        key = str(seed.field_def.field_key)
        assert classify_field_key(key) is not FieldClass.PACK, key
        assert seed.pack is None, key
        assert seed.description, key
        schema = seed.value_schema
        assert schema is not None, key
        assert isinstance(schema["type"], str), key  # never a list-valued type
        if classify_field_key(key) is FieldClass.CONTACT_FACET:
            assert seed.field_def.validation is not None, key
            assert "use_class_hint" in seed.field_def.validation, key
            assert seed.field_def.freshness_ttl is not None, key
            assert seed.field_def.freshness_ttl < timedelta(days=90), key


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("account.open_requisitions", [{"title": "Senior Manager, ABM", "days_open": 105}]),
        ("account.gtm_tooling_stack", {"present": ["HubSpot"], "absent": ["6sense"]}),
        ("account.named_customers", ["OpenAI"]),
        ("account.reputation_risk", {"what": "Cisco acquisition rumor", "status": "REFUTED"}),
        ("core.founded_year", 2022),
        ("core.legal_name", "Zafran Security Ltd."),
        ("contact.facet.voice_quote", {"text": "…", "media_url": "https://x", "media_timestamp": "05:14"}),
        ("contact.facet.hooks", ["Congrats on the raise"]),
        ("contact.facet.openers", ["Saw your post"]),
        ("contact.facet.certifications", ["6sense certified"]),
        ("contact.facet.education_highschool", "Oregon Episcopal School"),
        ("contact.facet.self_summary", "Marketer by title, builder at heart"),
        ("contact.facet.excluded_lookalike", {"discarded_media": "https://y", "title": "Not him"}),
        ("contact.facet.best_channel", "email"),
        ("contact.reports_to", {"contact_id": "0b8a3e2c-0000-0000-0000-000000000000"}),
    ],
)
def test_sample_values_pass_their_schemas(key: str, value: object) -> None:
    seed = next(s for s in ARV2_PACK if str(s.field_def.field_key) == key)
    validate_value_against_schema(value, seed.value_schema)


@pytest.mark.usefixtures("require_claimstore_db")
def test_pack_loads_idempotently() -> None:
    from tests.claimstore.conftest import rollback_conn
    from tests.db.conftest import run_async

    async def _run() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            await load_arv2_pack(conn)
            await load_arv2_pack(conn)  # second load is a no-op, never a redefinition

    run_async(_run())
```

Note `validate_value_against_schema` is the public name used by `tests/narrative/test_prose_fields.py:101-124`; confirm it in `registry.py` (it wraps `_validate_payload`) and use the name that exists.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/arv2/test_catalog_seed.py -q`
Expected: FAIL with `ModuleNotFoundError: clue_api.arv2.catalog_seed`.

- [ ] **Step 3: Write the pack**

`platform/api/clue_api/arv2/catalog_seed.py`:

```python
"""The ARV2 field pack (master plan §4 "new registered fields" + every key the answer keys wrote).

Rules (master plan §4): every field is optional — inside a value schema every sub-field is
optional except the one that identifies an item; a single scalar ``type`` only (the registry
validator rejects unions); ``contact.facet.*`` rows carry a ``use_class_hint`` and a TTL under
90 days. Canonical namespaces never pass ``pack=``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import FieldDef, PassKind
from clue_research.claimstore.packs import SeedField, load_pack

_STR: dict[str, Any] = {"type": "string"}
_STR_LIST: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
_OBJ: dict[str, Any] = {"type": "object"}
_OBJ_LIST: dict[str, Any] = {"type": "array", "items": {"type": "object"}}


def _row(
    key: str,
    value_type: str,
    schema: dict[str, Any],
    description: str,
    *,
    pass_kind: PassKind = PassKind.DEEP,
    ttl_days: int = 90,
    use_class_hint: str | None = None,
) -> SeedField:
    validation = {"use_class_hint": use_class_hint} if use_class_hint else None
    return SeedField(
        field_def=FieldDef(
            field_key=key,
            value_type=value_type,
            validation=validation,
            tier_plan=(),
            freshness_ttl=timedelta(days=ttl_days),
            pass_kind=pass_kind,
            gate=None,
        ),
        value_schema=schema,
        description=description,
    )


def _facet(key: str, value_type: str, schema: dict[str, Any], description: str, hint: str) -> SeedField:
    return _row(key, value_type, schema, description, ttl_days=75, use_class_hint=hint)


_PROF = "professional-public"
_PERS = "personal-public-non-sensitive"

ARV2_PACK: tuple[SeedField, ...] = (
    # --- account: the master plan's new fields ---
    _row(
        "account.open_requisitions",
        "list[object]",
        {"type": "array", "items": {"type": "object", "required": ["title"], "properties": {
            "title": _STR, "dept": _STR, "published": _STR, "days_open": {"type": "integer"},
            "salary_band": _STR, "still_listed": {"type": "boolean"}, "url": _STR}}},
        "Open job requisitions read from the company's own ATS board: title, department, publish date, days open, salary band, whether still listed, URL.",
    ),
    _row(
        "account.gtm_tooling_stack",
        "object",
        {"type": "object", "properties": {"present": _STR_LIST, "absent": _STR_LIST, "notes": _STR}},
        "CRM, outbound and ABM tools the company demonstrably uses (present) and tools explicitly named as not used (absent).",
    ),
    _row("account.named_customers", "list[str]", _STR_LIST, "Customers the company itself names publicly (logos, case studies, press)."),
    _row(
        "account.reputation_risk",
        "object",
        {"type": "object", "required": ["what"], "properties": {"what": _STR, "status": _STR, "source_note": _STR}},
        "A negative or contested public claim about the company with its status (confirmed, refuted, unresolved). Born outreach_safe=false.",
    ),
    _row("account.abm_program_maturity", "object", _OBJ, "Evidence of the company's own ABM program: open ABM roles, named ABM tooling, stated ABM motion."),
    _row("core.legal_name", "str", _STR, "The registered legal entity name.", pass_kind=PassKind.SCORING, ttl_days=365),
    _row("core.founded_year", "int", {"type": "integer"}, "Year the company was founded.", pass_kind=PassKind.SCORING, ttl_days=365),
    # --- account: keys the Zafran run wrote ---
    _row("core.company_crunchbase_url", "str", _STR, "Crunchbase profile URL.", pass_kind=PassKind.SCORING, ttl_days=365),
    _row("core.company_languages", "list[str]", _STR_LIST, "Languages the company publishes in.", pass_kind=PassKind.SCORING, ttl_days=365),
    _row("core.company_twitter_url", "str", _STR, "Company X/Twitter profile URL.", pass_kind=PassKind.SCORING, ttl_days=365),
    _row("core.company_type", "str", _STR, "Provider company type label (private, public, non-profit…).", pass_kind=PassKind.SCORING, ttl_days=365),
    _row("core.industries_all", "list[str]", _STR_LIST, "Every industry label the provider records, primary first.", pass_kind=PassKind.SCORING, ttl_days=180),
    _row("core.tech_stack_categorised", "list[object]", _OBJ_LIST, "Technology stack grouped by category as the provider reports it.", pass_kind=PassKind.SCORING),
    _row("account.employee_roster_sample", "list[object]", _OBJ_LIST, "A provider sample of employees (name, title) used to sketch org shape; never a committee source."),
    _row("account.hiring_velocity", "object", _OBJ, "Open roles by department and their ages, from the company's own job board."),
    _row("account.media_layer_index", "list[object]", _OBJ_LIST, "Podcasts and videos found for the account's people: media URL, duration, whether transcribed."),
    _row("account.media_transcript_quality_warning", "object", _OBJ, "A recorded defect in a media transcript (model, media, symptom). Born outreach_safe=false; context only."),
    _row("account.claimed_customer_logos", "list[str]", _STR_LIST, "Customer logos the company shows on its own site (proposed by the structuring pass)."),
    _row("account.claimed_outcomes_metrics", "object", _OBJ, "Outcome metrics the company claims for customers (proposed by the structuring pass)."),
    _row("account.product_packaging", "object", _OBJ, "How the company packages and names its products (proposed by the structuring pass)."),
    # --- contact: plain professional facts ---
    _row("contact.headline", "str", _STR, "The person's LinkedIn headline as published.", ttl_days=60),
    _row("contact.member_badges", "object", _OBJ, "Provider-recorded profile badges (creator, premium, open-to-work).", ttl_days=60),
    _row("contact.network_statistics", "object", {"type": "object", "properties": {"followers": {"type": "integer"}, "connections": {"type": "integer"}}}, "Follower and connection counts.", ttl_days=60),
    _row("contact.reports_to", "object", {"type": "object", "required": ["contact_id"], "properties": {"contact_id": _STR, "name": _STR}}, "The committee member this person reports to (a contact entity id)."),
    _row("contact.x_url", "str", _STR, "The person's X/Twitter profile URL.", ttl_days=180),
    # --- contact facets: the master plan's new fields ---
    _facet("contact.facet.hooks", "list[str]", _STR_LIST, "Specific, recent, self-published facts usable as outreach hooks, each grounded in a quote.", _PROF),
    _facet("contact.facet.openers", "list[str]", _STR_LIST, "Three grounded opening lines the marketer can send, each tied to a hook.", _PROF),
    _facet(
        "contact.facet.voice_quote",
        "object",
        {"type": "object", "required": ["text"], "properties": {"text": _STR, "media_url": _STR, "media_timestamp": _STR, "source_title": _STR}},
        "A verbatim spoken quote with the media URL and timestamp it came from.",
        _PROF,
    ),
    _facet("contact.facet.certifications", "list[str]", _STR_LIST, "Professional certifications the person lists.", _PROF),
    _facet("contact.facet.education_highschool", "str", _STR, "High school, when self-published.", _PERS),
    _facet("contact.facet.self_summary", "str", _STR, "The person's own summary of themselves, verbatim or lightly trimmed.", _PROF),
    _facet(
        "contact.facet.excluded_lookalike",
        "object",
        {"type": "object", "properties": {"discarded_media": _STR, "title": _STR, "reason": _STR}},
        "A same-name candidate the research rejected and why. Born outreach_safe=false; context only.",
        _PROF,
    ),
    _facet("contact.facet.best_channel", "str", _STR, "The channel the research judges most likely to reach this person first.", _PROF),
    # --- contact facets: keys the runs wrote ---
    _facet("contact.facet.conference_talk", "list[str]", _STR_LIST, "Conference talks the person gave, title and venue.", _PROF),
    _facet("contact.facet.hobby", "list[str]", _STR_LIST, "Hobbies the person states publicly themselves.", _PERS),
    _facet("contact.facet.other_roles", "list[str]", _STR_LIST, "Board seats, advisory and side roles the person lists.", _PROF),
    _facet("contact.facet.recent_award", "list[str]", _STR_LIST, "Awards or recognitions the person announced.", _PROF),
    _facet("contact.facet.stated_skills", "list[str]", _STR_LIST, "Skills the person lists on their own profile.", _PROF),
)

ARV2_FIELD_KEYS: frozenset[str] = frozenset(str(seed.field_def.field_key) for seed in ARV2_PACK)


async def load_arv2_pack(conn: AsyncConnection) -> None:
    """Register the ARV2 pack (idempotent — register_field is a no-op on an identical row)."""
    await load_pack(conn, ARV2_PACK)
```

Confirm each existing key you did NOT include (`contact.facet.hobby` is unregistered today — include it; `contact.facet.nickname`, `contact.facet.recent_post`, `contact.facet.alma_mater`, `contact.facet.career_history`, `contact.facet.communication_style`, `contact.facet.public_appearances`, `contact.facet.publications`, `contact.facet.stated_interests` are registered — exclude them). The first test enforces this; adjust the list until it and `test_pack_does_not_redefine_an_existing_key` both pass.

`platform/api/clue_api/arv2_wiring.py`:

```python
"""ARV2 composition hooks (PF-7 pattern: each lane appends its own pack loader)."""

from __future__ import annotations

from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.composition import RESEARCH_PACK_LOADERS


def register_arv2_wiring() -> None:
    """Append the ARV2 field pack to the production pack loaders (safe to call twice)."""
    if load_arv2_pack not in RESEARCH_PACK_LOADERS:
        RESEARCH_PACK_LOADERS.append(load_arv2_pack)
```

Then call `register_arv2_wiring()` from the same places `narrative_wiring.register_narrative_wiring` (or its equivalent) is called — find them with `grep -rn "register_narrative_wiring\|narrative_wiring" platform/api/clue_api/*.py` and add the ARV2 call next to each, so `fleet_main`, `projections_main` and the HTTP root all load the pack.

- [ ] **Step 4: Run the tests**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_catalog_seed.py tests/arv2/test_import_guard.py -q`
Expected: green.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format platform/api/clue_api/arv2/catalog_seed.py platform/api/clue_api/arv2_wiring.py tests/arv2/test_catalog_seed.py && uv run ruff check <same> && uv run mypy && uv run lint-imports
git add platform/api/clue_api/arv2/catalog_seed.py platform/api/clue_api/arv2_wiring.py tests/arv2/test_catalog_seed.py <the composition-root files you edited>
git commit -m "arv2(d1): the ARV2 field pack — every answer-key and master-plan field as data rows

Loose schemas (every sub-field optional), facets governed with use_class_hint + <90d TTL, canonical
namespaces only. Wired into RESEARCH_PACK_LOADERS from arv2_wiring."
```

---

## Task 4 — The lenient claim writer

**Files:**
- Create: `platform/api/clue_api/arv2/claim_writer.py`
- Modify: `tests/arv2/test_import_guard.py:20-38` (add three allowed prefixes)
- Create: `tests/arv2/test_claim_writer.py`

**Interfaces:**
- Consumes: `clue_research.claimstore.registry.check_claim_writable, get_effective_field, register_field, FieldRegistryScope, UnknownFieldError, ValueSchemaError`; `clue_research.claimstore.claims.insert_claim`; `clue_core.Claim, FieldDef, PassKind, classify_field_key, FieldClass, ReuseScope, ResearchScope, IdentityBinding, UseClass, ExtractionMethod, EntityType`.
- Produces:

```python
@dataclass(frozen=True)
class ClaimDraft:
    entity_id: EntityId
    entity_type: EntityType
    field_key: str
    value_json: JsonValue
    extraction_method: ExtractionMethod
    run_id: RunId
    research_mode: ResearchMode
    workspace_id: str
    source_url: str | None = None
    source_key: str | None = None
    evidence_span: str | None = None
    observed_at: datetime | None = None
    confidence: float = 0.5
    identity_binding: IdentityBinding | None = None
    use_class: UseClass | None = None
    signal_priority: int = 3
    outreach_safe: bool = True
    artifact_key: str | None = None
    product_id: str | None = None
    field_description: str | None = None
    markers: Mapping[str, JsonValue] = field(default_factory=dict)

@dataclass(frozen=True)
class WriteReceipt:
    claim_id: ClaimId
    field_key: str
    markers: dict[str, JsonValue]
    registered_field: bool

class LenientClaimWriter:
    def __init__(self, *, lenient: bool) -> None: ...
    async def write(self, conn: AsyncConnection, draft: ClaimDraft) -> WriteReceipt: ...

TIER_FOR_METHOD: dict[ExtractionMethod, int]  # api 1, crm_import 1, human 1, scrape 2, llm_synthesis 4
```

Behaviour (each line is a test):
1. Tier is stamped from the method (`TIER_FOR_METHOD`).
2. Every claim is written `reuse_scope=TENANT_PRIVATE` with `workspace_id` (decision 9).
3. A `contact.facet.*` draft with no binding gets `WEAK` + marker `identity_binding_defaulted`; with no use class gets `PROFESSIONAL_PUBLIC` + marker `use_class_defaulted`.
4. An `api`/`scrape`/`llm_synthesis` draft with no URL gets marker `source_missing` (lenient) or raises `ValueError` (strict).
5. A `human` draft needs no URL and gets no marker.
6. An unregistered canonical key is registered as a proposed field (no schema, `pass_kind=DEEP`, description = `draft.field_description` or `"Proposed field (unregistered key written in lenient mode)"`) and the claim gets marker `proposed_field` (lenient) or `UnknownFieldError` propagates (strict). A non-canonical key (`vertical_saas.x`) registers with `pack=<namespace>` and `research_scope=PROJECT_NEUTRAL`.
7. A value that misses the registered schema is stored with marker `schema_valid: false` (lenient) or `ValueSchemaError` propagates (strict).
8. Caller markers pass through; the receipt carries the merged markers and whether a field was registered.

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_claim_writer.py`:

```python
"""The lenient claim writer (master plan §2 principle 2, §4): store, stamp, mark — never refuse."""

from __future__ import annotations

import pytest

from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter, TIER_FOR_METHOD
from clue_core import (
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ReuseScope,
    ResearchMode,
    UseClass,
    new_run_id,
)
from clue_research.claimstore import claims_by_ids
from clue_research.claimstore.registry import UnknownFieldError, ValueSchemaError, get_effective_field, FieldRegistryScope
from clue_research.claimstore.tenancy import WorkspaceScope
from clue_research.identity import insert_account_entity, insert_contact_entity
from tests._workspace import seed_workspace
from tests.claimstore.conftest import rollback_conn
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def _setup(conn):  # type: ignore[no-untyped-def]
    ws = await seed_workspace(conn, "ws_writer")
    account = await insert_account_entity(
        conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=ws
    )
    contact = await insert_contact_entity(
        conn, account_entity_id=account, full_name="Nick Fisher",
        linkedin_url="https://www.linkedin.com/in/nicholastfisher",
    )
    return ws, account, contact


def _draft(ws: str, entity, entity_type: EntityType, **overrides: object) -> ClaimDraft:  # type: ignore[no-untyped-def]
    base: dict[str, object] = {
        "entity_id": entity, "entity_type": entity_type, "field_key": "core.account_name",
        "value_json": "Zafran Security", "extraction_method": ExtractionMethod.API,
        "run_id": new_run_id(), "research_mode": ResearchMode.ACCOUNT_PROFILING,
        "workspace_id": ws, "source_url": "https://api.ai-ark.com/v1/companies",
    }
    base.update(overrides)
    return ClaimDraft(**base)  # type: ignore[arg-type]


def test_tier_and_scope_are_stamped() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, account, _ = await _setup(conn)
            receipt = await LenientClaimWriter(lenient=True).write(conn, _draft(ws, account, EntityType.ACCOUNT))
            stored = (await claims_by_ids(conn, [receipt.claim_id], scope=WorkspaceScope.for_workspace(ws)))[receipt.claim_id]
            assert stored.source_tier == TIER_FOR_METHOD[ExtractionMethod.API] == 1
            assert stored.reuse_scope is ReuseScope.TENANT_PRIVATE and stored.workspace_id == ws
            assert receipt.markers == {} and receipt.registered_field is False
    run_async(_run())


def test_facet_governance_defaults_are_stamped_and_marked() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, _, contact = await _setup(conn)
            receipt = await LenientClaimWriter(lenient=True).write(
                conn, _draft(ws, contact, EntityType.CONTACT, field_key="contact.facet.recent_post",
                             value_json="Hiring an ABM manager", extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                             evidence_span="Hiring an ABM manager", source_url="https://www.linkedin.com/posts/x"))
            stored = (await claims_by_ids(conn, [receipt.claim_id], scope=WorkspaceScope.for_workspace(ws)))[receipt.claim_id]
            assert stored.identity_binding is IdentityBinding.WEAK
            assert stored.use_class is UseClass.PROFESSIONAL_PUBLIC
            assert receipt.markers == {"identity_binding_defaulted": True, "use_class_defaulted": True}
    run_async(_run())


def test_missing_url_is_marked_in_lenient_mode_and_refused_in_strict_mode() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, account, _ = await _setup(conn)
            receipt = await LenientClaimWriter(lenient=True).write(conn, _draft(ws, account, EntityType.ACCOUNT, source_url=None))
            assert receipt.markers == {"source_missing": True}
            with pytest.raises(ValueError, match="source_url"):
                await LenientClaimWriter(lenient=False).write(conn, _draft(ws, account, EntityType.ACCOUNT, source_url=None))
            human = await LenientClaimWriter(lenient=False).write(
                conn, _draft(ws, account, EntityType.ACCOUNT, extraction_method=ExtractionMethod.HUMAN, source_url=None))
            assert human.markers == {}
    run_async(_run())


def test_unknown_key_registers_a_proposed_field_in_lenient_mode() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, account, _ = await _setup(conn)
            draft = _draft(ws, account, EntityType.ACCOUNT, field_key="account.claimed_customer_logos_v2",
                           value_json=["OpenAI"], field_description="Logos on the site")
            with pytest.raises(UnknownFieldError):
                await LenientClaimWriter(lenient=False).write(conn, draft)
            receipt = await LenientClaimWriter(lenient=True).write(conn, draft)
            assert receipt.registered_field is True and receipt.markers == {"proposed_field": True}
            resolved = await get_effective_field(conn, scope=FieldRegistryScope.for_workspace(ws), field_key=draft.field_key)
            assert resolved is not None and resolved.description == "Logos on the site"
            pack_draft = _draft(ws, account, EntityType.ACCOUNT, field_key="vertical_saas.core_banking_vendor", value_json="Temenos")
            assert (await LenientClaimWriter(lenient=True).write(conn, pack_draft)).registered_field is True
    run_async(_run())


def test_schema_miss_is_stored_with_a_marker_in_lenient_mode() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, account, _ = await _setup(conn)
            draft = _draft(ws, account, EntityType.ACCOUNT, field_key="core.employee_count", value_json="about 170")
            with pytest.raises(ValueSchemaError):
                await LenientClaimWriter(lenient=False).write(conn, draft)
            receipt = await LenientClaimWriter(lenient=True).write(conn, draft)
            assert receipt.markers == {"schema_valid": False}
            stored = (await claims_by_ids(conn, [receipt.claim_id], scope=WorkspaceScope.for_workspace(ws)))[receipt.claim_id]
            assert stored.value_json == "about 170" and stored.write_markers == {"schema_valid": False}
    run_async(_run())


def test_caller_markers_and_priority_pass_through() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, account, _ = await _setup(conn)
            receipt = await LenientClaimWriter(lenient=True).write(
                conn, _draft(ws, account, EntityType.ACCOUNT, signal_priority=1, outreach_safe=False,
                             markers={"pipe_joined_key": "a|b"}))
            stored = (await claims_by_ids(conn, [receipt.claim_id], scope=WorkspaceScope.for_workspace(ws)))[receipt.claim_id]
            assert stored.signal_priority == 1 and stored.outreach_safe is False
            assert stored.write_markers == {"pipe_joined_key": "a|b"}
    run_async(_run())
```

Also extend `ALLOWED_INTERNAL_PREFIXES` in `tests/arv2/test_import_guard.py` with:

```python
    "clue_research.identity",
    "clue_research.membership",
    "clue_research.durable.project_run",
```

with a comment: `# D1: the entity, membership and project-run writers the master plan keeps (not quarantined).`

- [ ] **Step 2: Run to verify failure**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_claim_writer.py -q`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write the writer**

`platform/api/clue_api/arv2/claim_writer.py`:

```python
"""The lenient claim write gate (master plan §2 principle 2, §4).

Rule: storing information is never blocked. The gate stamps what the writer did not say (tier from
the method, tenant-private scope, facet governance defaults), stores a schema miss with
``schema_valid=false``, registers an unknown key as a proposed field, and stores a research claim
with no source URL under a ``source_missing`` marker. With ``lenient=False`` every one of those is
the strict refusal the claim store already implements.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldClass,
    FieldDef,
    IdentityBinding,
    JsonValue,
    PassKind,
    ResearchMode,
    ResearchScope,
    ReuseScope,
    RunId,
    UseClass,
    classify_field_key,
    field_namespace,
)
from clue_research.claimstore.claims import insert_claim
from clue_research.claimstore.registry import (
    FieldRegistryScope,
    UnknownFieldError,
    ValueSchemaError,
    check_claim_writable,
    register_field,
)

#: Appendix A / master plan §4: the tier is stamped from the tool of origin, never chosen.
TIER_FOR_METHOD: dict[ExtractionMethod, int] = {
    ExtractionMethod.API: 1,
    ExtractionMethod.CRM_IMPORT: 1,
    ExtractionMethod.HUMAN: 1,
    ExtractionMethod.SCRAPE: 2,
    ExtractionMethod.LLM_SYNTHESIS: 4,
}

_URL_REQUIRED = frozenset(
    {ExtractionMethod.API, ExtractionMethod.SCRAPE, ExtractionMethod.LLM_SYNTHESIS}
)
_PROPOSED_DESCRIPTION = "Proposed field (unregistered key written in lenient mode)"


@dataclass(frozen=True)
class ClaimDraft:
    """What a writer knows about one fact; the gate fills in everything it did not say."""

    entity_id: EntityId
    entity_type: EntityType
    field_key: str
    value_json: JsonValue
    extraction_method: ExtractionMethod
    run_id: RunId
    research_mode: ResearchMode
    workspace_id: str
    source_url: str | None = None
    source_key: str | None = None
    evidence_span: str | None = None
    observed_at: datetime | None = None
    confidence: float = 0.5
    identity_binding: IdentityBinding | None = None
    use_class: UseClass | None = None
    signal_priority: int = 3
    outreach_safe: bool = True
    artifact_key: str | None = None
    product_id: str | None = None
    field_description: str | None = None
    markers: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class WriteReceipt:
    claim_id: ClaimId
    field_key: str
    markers: dict[str, JsonValue]
    registered_field: bool


class LenientClaimWriter:
    def __init__(self, *, lenient: bool) -> None:
        self._lenient = lenient

    async def write(self, conn: AsyncConnection, draft: ClaimDraft) -> WriteReceipt:
        markers: dict[str, JsonValue] = dict(draft.markers)
        registered = False

        binding, use_class = draft.identity_binding, draft.use_class
        if (
            draft.entity_type is EntityType.CONTACT
            and classify_field_key(draft.field_key) is FieldClass.CONTACT_FACET
        ):
            if binding is None:
                binding, markers["identity_binding_defaulted"] = IdentityBinding.WEAK, True
            if use_class is None:
                use_class, markers["use_class_defaulted"] = UseClass.PROFESSIONAL_PUBLIC, True

        if draft.extraction_method in _URL_REQUIRED and not draft.source_url:
            if not self._lenient:
                raise ValueError(
                    f"extraction_method {draft.extraction_method} requires a source_url "
                    "(strict mode)"
                )
            markers["source_missing"] = True

        scope_kwargs = {
            "reuse_scope": ReuseScope.TENANT_PRIVATE,
            "workspace_id": draft.workspace_id,
            "product_id": draft.product_id,
        }
        try:
            await check_claim_writable(
                conn, field_key=draft.field_key, value_json=draft.value_json, **scope_kwargs
            )
        except UnknownFieldError:
            if not self._lenient:
                raise
            await _register_proposed_field(conn, draft)
            registered, markers["proposed_field"] = True, True
            await check_claim_writable(
                conn, field_key=draft.field_key, value_json=draft.value_json, **scope_kwargs
            )
        except ValueSchemaError:
            if not self._lenient:
                raise
            markers["schema_valid"] = False

        claim = Claim(
            entity_id=draft.entity_id,
            entity_type=draft.entity_type,
            field_key=draft.field_key,
            value_json=draft.value_json,
            source_url=draft.source_url,
            source_key=draft.source_key,
            artifact_key=draft.artifact_key,
            source_tier=TIER_FOR_METHOD[draft.extraction_method],
            extraction_method=draft.extraction_method,
            evidence_span=draft.evidence_span,
            confidence=draft.confidence,
            observed_at=draft.observed_at,
            run_id=draft.run_id,
            research_mode=draft.research_mode,
            identity_binding=binding,
            use_class=use_class,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            workspace_id=draft.workspace_id,
            product_id=draft.product_id,
            signal_priority=draft.signal_priority,
            outreach_safe=draft.outreach_safe,
            write_markers=markers or None,
        )
        claim_id = await insert_claim(conn, claim, validate_field=False)
        return WriteReceipt(
            claim_id=claim_id, field_key=draft.field_key, markers=markers, registered_field=registered
        )


async def _register_proposed_field(conn: AsyncConnection, draft: ClaimDraft) -> None:
    """Master plan §4: an unregistered key is stored and auto-registered as a proposed field."""
    is_pack = classify_field_key(draft.field_key) is FieldClass.PACK
    field_def = FieldDef(
        field_key=draft.field_key,
        value_type="json",
        validation=None,
        tier_plan=(),
        freshness_ttl=None,
        pass_kind=PassKind.DEEP,
        gate=None,
        research_scope=ResearchScope.PROJECT_NEUTRAL if is_pack else None,
    )
    await register_field(
        conn,
        field_def,
        value_schema=None,
        description=draft.field_description or _PROPOSED_DESCRIPTION,
        pack=field_namespace(draft.field_key) if is_pack else None,
    )
```

Check `FieldDef`'s constructor accepts exactly these keyword names (`libs/clue-core/clue_core/field.py:151-200`) and that `field_namespace` and `FieldClass` are exported from `clue_core`; import from their modules if not. `insert_claim(..., validate_field=False)` is used because the gate already ran `check_claim_writable` itself (and deliberately skips it on a schema miss).

- [ ] **Step 4: Run the tests**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_claim_writer.py tests/arv2/test_import_guard.py -q`
Expected: green.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format platform/api/clue_api/arv2/claim_writer.py tests/arv2/test_claim_writer.py tests/arv2/test_import_guard.py && uv run ruff check <same> && uv run mypy && uv run lint-imports
git add platform/api/clue_api/arv2/claim_writer.py tests/arv2/test_claim_writer.py tests/arv2/test_import_guard.py
git commit -m "arv2(d1): the lenient claim writer — stamp, mark, register; never refuse

Tier from the method, tenant-private scope, facet governance defaults, source_missing /
schema_valid / proposed_field markers; strict mode restores every refusal. Import guard admits
the identity, membership and project-run writers the plan keeps."
```

---

## Task 5 — Answer-key mapping (pure): proof-of-concept rows → drafts

**Files:**
- Create: `platform/api/clue_api/arv2/answer_key.py`
- Create: `tests/arv2/test_answer_key.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class PersonSpec: key: str; name: str; title: str; company_domain: str; linkedin_url: str
@dataclass(frozen=True)
class AccountSpec: key: str; name: str; domain: str
@dataclass(frozen=True)
class MediaSpec: media_url: str; transcript_file: str; title: str
@dataclass(frozen=True)
class AnswerKeyManifest:
    workspace_id: str; workspace_name: str; brand_name: str; product_name: str
    project_id: str; project_name: str; run_id: RunId; project_run_id: ProjectRunId
    accounts: tuple[AccountSpec, ...]; people: tuple[PersonSpec, ...]; media: tuple[MediaSpec, ...]
ZAFRAN_MANIFEST: AnswerKeyManifest
@dataclass(frozen=True)
class RowDraft:            # a draft before entity ids are known
    subject: str           # "account:<domain>" or "contact:<linkedin_url>"
    entity_type: EntityType
    field_key: str
    value_json: JsonValue
    extraction_method: ExtractionMethod
    research_mode: ResearchMode
    source_url: str | None; source_key: str | None; evidence_span: str | None
    observed_at: datetime | None; confidence: float
    identity_binding: IdentityBinding | None; use_class: UseClass | None
    signal_priority: int; outreach_safe: bool; media_url: str | None
    field_description: str | None; markers: dict[str, JsonValue]; source_row_id: str
@dataclass(frozen=True)
class Skip: source_row_id: str; reason: str   # reasons: not_found | duplicate_persona | unknown_persona
@dataclass(frozen=True)
class MappedRows: drafts: tuple[RowDraft, ...]; skips: tuple[Skip, ...]
def map_zafran_rows(payload: Mapping[str, Any]) -> MappedRows
def map_people_rows(payload: Mapping[str, Any], roster: Sequence[Mapping[str, Any]]) -> MappedRows
BUNDLE_SOURCES: dict[str, str | None]; ZAFRAN_PRIORITY: dict[str, int]; PERSONA_MAP: dict[str, str]
USE_CLASS_MAP: dict[str, UseClass | None]
def resolve_source_url(raw: str | None) -> str | None
def priority_for(field_key: str, entity_type: EntityType) -> int
```

Mapping rules (each a test):

- **Subjects.** Zafran account rows → `account:zafran.io`. Contact rows key on `entity_key`, which is either a LinkedIn URL or a bare name; build `{person_name: linkedin_url}` from the URL-keyed rows (`person` field) and resolve name-keyed rows through it. People rows → `contact:<person.linkedin>` (lower-cased, trailing slash stripped, which is what `insert_contact_entity` stores).
- **Extraction method.** Zafran `claim_kind`: `deterministic` → `API`; `deterministic_media`, `exclusion` → `SCRAPE`; `synthesised`, `proposed_field` → `LLM_SYNTHESIS`. People rows → `LLM_SYNTHESIS`.
- **Research mode.** account rows → `ACCOUNT_PROFILING`; contact rows → `CONTACT_PROFILING`.
- **Source key.** Zafran: the first `|`-separated token of `source_provider`, lower-cased, spaces → `_` (`ai_ark`, `ashby_posting_api`, `exa_contents`, `gemini`, `exa_deep_reasoning`, `structuring_pass`). People: `arv2_person_depth`.
- **Source URL.** `resolve_source_url`: split on `" / "`; for each token in order, an `http` token wins; a `BUNDLE: <labels>` token resolves each `SOURCE X` label through `BUNDLE_SOURCES` and the first non-None wins; else `None`. `BUNDLE_SOURCES = {"SOURCE A": None, "SOURCE B": "https://www.zafran.io/", "SOURCE C": "https://podcasters.spotify.com/pod/show/boardroomclub/episodes/AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai", "SOURCE D": "https://www.youtube.com/watch?v=8_YWBtq4eic", "SOURCE E": "https://www.youtube.com/watch?v=avcD5WVLCYs", "SOURCE F": "https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf"}`. A deterministic row with no URL keeps `None` (the writer marks it).
- **Evidence span.** Zafran: `evidence_span` (fallback `evidence_span_2`); people: `evidence_quote`.
- **Observed at.** Zafran `observed_at` (`YYYY-MM-DD` → aware UTC midnight); people `source_timestamp` when present, else `2026-09-03` (the run date in `PERSON-DEPTH-REPORT.md`).
- **Confidence.** `high` 0.9, `medium` 0.6, `low` 0.3, absent 0.7.
- **Use class.** `USE_CLASS_MAP = {"business_public": None, "professional_public": PROFESSIONAL_PUBLIC, "personal_public_self_stated": PERSONAL_PUBLIC_NON_SENSITIVE, "professional-public": PROFESSIONAL_PUBLIC, "personal-public-non-sensitive": PERSONAL_PUBLIC_NON_SENSITIVE}`; account rows always `None`.
- **Identity binding.** Zafran contact rows: `STRONG` when `source_kind` ∈ {`provider_database`, `transcript_self`, `company_primary`}, else `WEAK`; account rows `None`; people rows: `IdentityBinding(row["identity_binding"].lower())`.
- **Priority.** People: `{"P1": 1, "P2": 2, "P3": 3}[row["priority"]]`. Zafran: `priority_for(field_key, entity_type)` from `ZAFRAN_PRIORITY = {"account.open_requisitions": 1, "account.hiring_velocity": 1, "account.hiring_velocity_eng": 1, "account.abm_program_maturity": 1, "account.operational_pain": 1, "account.strategic_moves": 1, "account.recent_funding": 2, "account.total_funding": 2, "account.gtm_tooling_stack": 2, "account.named_customers": 2, "account.reputation_risk": 2, "account.claimed_customer_logos": 2, "account.claimed_outcomes_metrics": 2, "core.annual_revenue": 2, "core.revenue_band": 2, "core.employee_count": 2, "core.employee_range": 2, "account.resonance.attrition_signal": 2, "account.resonance.buying_culture": 2, "account.resonance.public_frustrations": 2, "account.resonance.culture": 2, "account.resonance.eng_blog_tone": 2, "contact.facet.hobby": 2, "contact.facet.voice_quote": 2, "contact.facet.recent_post": 2, "contact.facet.publications": 2, "contact.facet.public_appearances": 2, "contact.facet.certifications": 2, "contact.facet.recent_award": 2, "contact.facet.communication_style": 2, "contact.facet.stated_interests": 2, "contact.facet.career_history": 2}`; anything else 3.
- **Outreach safe.** `bool(row["outreach_safe"])`.
- **NOT FOUND.** A string value starting with `NOT FOUND` → `Skip(reason="not_found")`.
- **Persona.** `contact.persona` value through `PERSONA_MAP = {"executive_sponsor": "economic_buyer", "adjacent_buyer": "user"}` then must be a `Persona` value; otherwise, if the same contact already has a persona draft → `Skip("duplicate_persona")`, else `Skip("unknown_persona")`. `contact.role_on_committee` string values become `{"role": <that contact's mapped persona>, "rationale": <string>}`; dict values pass through.
- **Proposed keys.** `PROPOSED::x` → key `x`, marker `{"proposed_field_origin": "structuring_pass"}`, `field_description` from the row's `why`/`note` when present.
- **Pipe-joined keys.** `a|b` → one draft per key with the whole value and marker `{"pipe_joined_key": "a|b"}`.
- **Media rows** (`media_url` present): `value_json = {"text": value, "media_url": …, "media_timestamp": row.get("media_timestamp")}` and `RowDraft.media_url` set so the loader can attach the artifact.
- **Every draft's `markers` also carries `{"source_row_id": <claim_id>, "answer_key": "zafran-2026-09-02" | "person-depth-2026-09-03"}`** so a row can be traced back.

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_answer_key.py`:

```python
"""Answer-key mapping rules (plan decisions 4-8, 10)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from clue_api.arv2.answer_key import (
    PERSONA_MAP,
    ZAFRAN_MANIFEST,
    map_people_rows,
    map_zafran_rows,
    priority_for,
    resolve_source_url,
)
from clue_core import EntityType, ExtractionMethod, IdentityBinding, Persona, UseClass

REPO = Path(__file__).resolve().parents[2]
ZAFRAN = json.loads((REPO / ".context/arv2-one-account-aiark/claims_zafran.json").read_text())
PEOPLE = json.loads((REPO / ".context/arv2-person-depth/claims_people.json").read_text())
ROSTER = json.loads((REPO / ".context/arv2-person-depth/roster.json").read_text())


def test_resolve_source_url() -> None:
    assert resolve_source_url("https://www.zafran.io/about") == "https://www.zafran.io/about"
    assert resolve_source_url("BUNDLE: SOURCE A") is None
    assert resolve_source_url("BUNDLE: SOURCE A / SOURCE B") == "https://www.zafran.io/"
    assert resolve_source_url("BUNDLE: SOURCE B / SOURCE C") == "https://www.zafran.io/"
    assert resolve_source_url("https://www.zafran.io/x / BUNDLE: SOURCE A") == "https://www.zafran.io/x"
    assert resolve_source_url(None) is None


def test_priority_table() -> None:
    assert priority_for("account.open_requisitions", EntityType.ACCOUNT) == 1
    assert priority_for("account.recent_funding", EntityType.ACCOUNT) == 2
    assert priority_for("core.account_name", EntityType.ACCOUNT) == 3
    assert priority_for("contact.facet.hobby", EntityType.CONTACT) == 2
    assert priority_for("contact.current_title", EntityType.CONTACT) == 3


def test_zafran_rows_map_completely() -> None:
    mapped = map_zafran_rows(ZAFRAN)
    reasons = Counter(skip.reason for skip in mapped.skips)
    assert reasons == {"not_found": 4, "duplicate_persona": 1}
    assert {s.source_row_id for s in mapped.skips if s.reason == "not_found"} == {"zaf-130", "zaf-131", "zaf-132", "zaf-133"}
    assert len(mapped.drafts) == 174 - 5
    subjects = {d.subject for d in mapped.drafts}
    assert "account:zafran.io" in subjects
    assert {s for s in subjects if s.startswith("contact:")} == {
        "contact:https://www.linkedin.com/in/nicholastfisher",
        "contact:https://www.linkedin.com/in/sanaz-yashar",
        "contact:https://www.linkedin.com/in/varinderkaur",
        "contact:https://www.linkedin.com/in/tomanthonyjr",
        "contact:https://www.linkedin.com/in/ben-seri",
    }
    personas = {d.subject: d.value_json for d in mapped.drafts if d.field_key == "contact.persona"}
    assert personas["contact:https://www.linkedin.com/in/sanaz-yashar"] == "economic_buyer"
    assert personas["contact:https://www.linkedin.com/in/tomanthonyjr"] == "user"
    assert all(Persona(v) for v in personas.values())
    roles = [d for d in mapped.drafts if d.field_key == "contact.role_on_committee"]
    assert all(isinstance(d.value_json, dict) and d.value_json["role"] == personas[d.subject] for d in roles)
    by_id = {d.source_row_id: d for d in mapped.drafts}
    assert by_id["zaf-001"].extraction_method is ExtractionMethod.API and by_id["zaf-001"].source_url is None
    assert by_id["zaf-119"].extraction_method is ExtractionMethod.LLM_SYNTHESIS and by_id["zaf-119"].source_url == "https://www.zafran.io/"
    assert by_id["zaf-172"].field_key == "account.claimed_customer_logos"
    media = [d for d in mapped.drafts if d.media_url]
    assert media and all(isinstance(d.value_json, dict) and "text" in d.value_json and "media_timestamp" in d.value_json for d in media)
    contact_rows = [d for d in mapped.drafts if d.entity_type is EntityType.CONTACT]
    assert all(d.identity_binding in (IdentityBinding.STRONG, IdentityBinding.WEAK) for d in contact_rows)
    assert all(d.use_class is not None for d in contact_rows)
    assert all(d.use_class is None for d in mapped.drafts if d.entity_type is EntityType.ACCOUNT)
    assert sum(1 for d in mapped.drafts if not d.outreach_safe) == 11  # 12 unsafe rows minus zaf-132 (NOT FOUND)


def test_people_rows_map_completely() -> None:
    mapped = map_people_rows(PEOPLE, ROSTER)
    assert not mapped.skips
    assert len(mapped.drafts) == 119 + 3  # three pipe-joined rows each become two drafts
    assert {d.subject for d in mapped.drafts} == {f"contact:{p['linkedin'].lower().rstrip('/')}" for p in ROSTER}
    assert all(d.extraction_method is ExtractionMethod.LLM_SYNTHESIS and d.source_url and d.evidence_span for d in mapped.drafts)
    assert all(d.identity_binding is IdentityBinding.STRONG for d in mapped.drafts)
    assert {d.use_class for d in mapped.drafts} == {UseClass.PROFESSIONAL_PUBLIC, UseClass.PERSONAL_PUBLIC_NON_SENSITIVE}
    assert Counter(d.signal_priority for d in mapped.drafts)[1] >= 83
    joined = [d for d in mapped.drafts if "pipe_joined_key" in d.markers]
    assert len(joined) == 6 and all("|" not in d.field_key for d in joined)


def test_manifest_names_the_four_accounts_and_ten_people() -> None:
    assert {a.domain for a in ZAFRAN_MANIFEST.accounts} == {"zafran.io", "cogent.com", "harmonic.security", "uptiq.ai"}
    assert len(ZAFRAN_MANIFEST.people) == 10 and len(ZAFRAN_MANIFEST.media) == 3
    assert PERSONA_MAP == {"executive_sponsor": "economic_buyer", "adjacent_buyer": "user"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/arv2/test_answer_key.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

`platform/api/clue_api/arv2/answer_key.py` — implement exactly the rules above. Skeleton with the non-obvious parts written out:

```python
"""Answer-key mapping: the two proof-of-concept claim files → claim drafts (pure, no I/O).

Every rule here is a recorded plan decision (docs/superpowers/plans/2026-09-07-arv2-d1-…md,
"Decisions taken by this plan" 4-8, 10). Nothing is invented: a value the run did not find is a
skip, a source the run could not name is a ``source_missing`` marker.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from clue_core import (
    EntityType, ExtractionMethod, IdentityBinding, JsonValue, Persona, ProjectRunId,
    ResearchMode, RunId, UseClass,
)

_NAMESPACE = uuid.UUID("6f1c2a3e-7b4d-4e8f-9a0b-1c2d3e4f5a6b")
ZAFRAN_RUN_ID = RunId(uuid.uuid5(_NAMESPACE, "arv2-answer-key:zafran:2026-09-02"))
ZAFRAN_PROJECT_RUN_ID = ProjectRunId(uuid.uuid5(_NAMESPACE, "arv2-answer-key:project-run:v1"))
PEOPLE_RUN_ID = RunId(uuid.uuid5(_NAMESPACE, "arv2-answer-key:person-depth:2026-09-03"))

BUNDLE_SOURCES: dict[str, str | None] = { ... as specified ... }
PERSONA_MAP: dict[str, str] = {"executive_sponsor": "economic_buyer", "adjacent_buyer": "user"}
USE_CLASS_MAP: dict[str, UseClass | None] = { ... as specified ... }
ZAFRAN_PRIORITY: dict[str, int] = { ... as specified ... }
_STRONG_SOURCE_KINDS = frozenset({"provider_database", "transcript_self", "company_primary"})
_CONFIDENCE = {"high": 0.9, "medium": 0.6, "low": 0.3}
_METHOD_FOR_KIND = {
    "deterministic": ExtractionMethod.API,
    "deterministic_media": ExtractionMethod.SCRAPE,
    "exclusion": ExtractionMethod.SCRAPE,
    "synthesised": ExtractionMethod.LLM_SYNTHESIS,
    "proposed_field": ExtractionMethod.LLM_SYNTHESIS,
}


def _contact_subject(linkedin_url: str) -> str:
    return "contact:" + linkedin_url.strip().lower().rstrip("/")


def resolve_source_url(raw: str | None) -> str | None:
    if not raw:
        return None
    for token in (t.strip() for t in raw.split(" / ")):
        if token.startswith("http"):
            return token
        if token.startswith("BUNDLE:"):
            for label in (lbl.strip() for lbl in token.removeprefix("BUNDLE:").split("/")):
                url = BUNDLE_SOURCES.get(label)
                if url:
                    return url
    return None


def priority_for(field_key: str, entity_type: EntityType) -> int:
    return ZAFRAN_PRIORITY.get(field_key, 3)


def _observed(date_text: str | None, default: str) -> datetime:
    return datetime.strptime(date_text or default, "%Y-%m-%d").replace(tzinfo=UTC)
```

`map_zafran_rows` must: build the name→URL map first (`{r["person"]: r["entity_key"] for r in rows if r["entity"] == "contact" and str(r["entity_key"]).startswith("http")}`), then walk rows in file order, applying NOT FOUND → skip, persona mapping with the duplicate rule, role wrapping (which needs the contact's mapped persona: collect personas in a first pass over `contact.persona` rows), `PROPOSED::` stripping, pipe splitting, media wrapping, and the marker/source rules. `map_people_rows` walks `payload["people"].values()` → `person["claims"]`, using `person["linkedin"]` for the subject and `roster` for the company domain (kept in the draft's `markers["company_domain"]` for the loader).

Also define `ZAFRAN_MANIFEST` with: `workspace_id="ws_arv2_answer_key"`, `workspace_name="ARV2 answer key"`, `brand_name="Clue"`, `product_name="Clue"`, `project_id="prj_arv2_answer_key"`, `project_name="ARV2 answer key — Zafran"`, the two ids above, four `AccountSpec`s (`zafran`/Zafran Security/zafran.io, `cogent`/Cogent Security/cogent.com, `harmonic`/Harmonic Security/harmonic.security, `uptiq`/UPTIQ, Inc./uptiq.ai), ten `PersonSpec`s from `roster.json` plus Tom Anthony (`SVP, Global Sales`, `zafran.io`, `https://www.linkedin.com/in/tomanthonyjr`) and Ben Seri (`Co-Founder & CTO`, `zafran.io`, `https://www.linkedin.com/in/ben-seri`) — twelve people in total (adjust the manifest test to 12), and three `MediaSpec`s: the Boardroom podcast URL → `sanaz_boardroom.md` / "AI Summit: Sanaz Yashar (Boardroom Club)", `https://www.youtube.com/watch?v=8_YWBtq4eic` → `nick_supporting_cc.md` / "Supporting Cocktail Chemistry", `https://www.youtube.com/watch?v=avcD5WVLCYs` → `nick_moscow_mule.md` / "Perfect Moscow Mule".

- [ ] **Step 4: Run the tests until green**

Run: `uv run pytest tests/arv2/test_answer_key.py -q`. The row counts in the tests are derived from the files (174 rows, 4 NOT FOUND, 1 duplicate persona, 12 unsafe; 119 people rows, 3 pipe-joined keys). If a count differs, print the disagreeing rows in the report and fix the mapping, not the test, unless the file itself proves the test wrong.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format platform/api/clue_api/arv2/answer_key.py tests/arv2/test_answer_key.py && uv run ruff check <same> && uv run mypy && uv run pytest tests/arv2/test_import_guard.py -q
git add platform/api/clue_api/arv2/answer_key.py tests/arv2/test_answer_key.py
git commit -m "arv2(d1): answer-key mapping — Zafran and person-depth rows to claim drafts (pure)

Persona map, bundle-source map, priority table, NOT FOUND skips, pipe-joined split, media wrap,
governance defaults per source kind. Every rule is a recorded plan decision."
```

---

## Task 6 — The answer-key loader and its script

**Files:**
- Create: `platform/api/clue_api/arv2/answer_key_loader.py`
- Create: `scripts/load_arv2_answer_key.py`
- Create: `tests/arv2/test_answer_key_loader_db.py`

**Interfaces:**
- Consumes: Task 4 `LenientClaimWriter`, `ClaimDraft`; Task 5 `map_*`, `ZAFRAN_MANIFEST`; `clue_spine.create_workspace/create_brand/create_product/create_project/get_workspace`; `clue_research.identity.insert_account_entity/insert_contact_entity`; `clue_research.membership.ensure_project_account`; `clue_research.durable.project_run.ensure_project_run`; `clue_research.claimstore.run_lineage.record_run_lineage`; `clue_storage.artifacts.record_artifact`, `clue_storage.protocol.artifact_key, content_address`, `clue_storage.fs.FsStorage`; `clue_config.Settings`.
- Produces:

```python
@dataclass(frozen=True)
class LoadReport:
    workspace_id: str; project_id: str; run_id: str
    accounts: dict[str, str]          # domain -> account_entity_id
    contacts: dict[str, str]          # linkedin_url -> contact_entity_id
    claims_written: int; registered_fields: list[str]
    markers: dict[str, int]           # marker name -> count
    skips: list[dict[str, str]]       # {"source_row_id", "reason"}
    artifacts: list[str]              # artifact keys
class AlreadyLoaded(RuntimeError): ...
async def load_answer_key(conn: AsyncConnection, *, storage: FsStorage, context_root: Path,
                          settings: Settings) -> LoadReport
```

Order inside one transaction (dependency-derived):

1. Refuse if `SELECT 1 FROM claim WHERE run_id = :run_id LIMIT 1` finds a row for `ZAFRAN_RUN_ID` → raise `AlreadyLoaded("answer key already loaded into this database (run <id>); use a fresh database")`.
2. `create_workspace(conn, name=..., workspace_id=manifest.workspace_id)` unless `get_workspace` finds it; `create_brand`; `create_product`; `create_project(..., project_id=manifest.project_id, status="active")` (no `product_id`).
3. Load packs: `load_core_pack`, `load_deep_profiling_pack`, `load_committee_pack`, `load_arv2_pack` (import each from its module; `load_deep_profiling_pack` is in `clue_research.profiling.fields`, `load_committee_pack` in `clue_research.profiling.committee.fields` — **these two modules are outside the import allowlist**; import them inside the loader through `clue_api.composition.RESEARCH_PACK_LOADERS` instead: call `register_arv2_wiring()` then `for loader in RESEARCH_PACK_LOADERS: await loader(conn)`; `clue_api.composition` is also outside the allowlist, so add `"clue_api.composition"` to the allowlist with the comment `# D1: the pack-loader list (composition root data, not a lane)`).
4. `insert_account_entity` for the four accounts (`status=AccountStatus.CANDIDATE`), `ensure_project_account(added_via="manual")` for each; `insert_contact_entity` for the twelve people under their account.
5. `ensure_project_run(conn, project_run_id=ZAFRAN_PROJECT_RUN_ID, project_id=..., workspace_id=..., icp_key="answer-key", icp_version=1, phase=ProjectPhase.DEEP, status=ProjectRunStatus.ACTIVE)` with no product/client/readiness pins.
6. `record_run_lineage` twice: `ZAFRAN_RUN_ID` kind `entity_research` and `PEOPLE_RUN_ID` kind `contact_research`, both with `project_id` and `project_run_id`.
7. Media artifacts: for each `MediaSpec`, read `context_root / "arv2-one-account-aiark/transcripts" / spec.transcript_file` as bytes, `sha = content_address(data)`, `key = artifact_key(workspace_id, sha)`, `record_artifact(conn, storage_key=key, workspace_id=..., content_sha256=sha, media_type="text/markdown", size_bytes=len(data), source_key="arv2:answer_key:transcript", source_url=spec.media_url)`, then `await storage.put(key, data)` (check `FsStorage.put`'s exact signature in `libs/clue-storage/clue_storage/fs.py:24`). Keep `{media_url: key}`.
8. Write claims: map subjects to entity ids; for every draft build a `ClaimDraft` (Zafran → `run_id=ZAFRAN_RUN_ID`, people → `PEOPLE_RUN_ID`; `artifact_key` = the media map entry when `draft.media_url` is set; `source_key`, markers etc. straight through) and call `LenientClaimWriter(lenient=settings.claim_write_lenient).write`. Collect receipts.
9. Research-run rows for Zafran only, by direct INSERT (state `terminal`; the immutability trigger only fires on UPDATE):
   - `entity_research_run`: `research_run_id=uuid5(_NAMESPACE, "arv2-answer-key:research-run")`, `run_kind='account_research'`, `subject_type='account'`, `product_id=<the product id created in step 2>`, `project_run_id=ZAFRAN_PROJECT_RUN_ID`, `selection_id=uuid5(..., "selection")`, `budget_envelope_ref='answer-key'`, `budget_cap_cents=0`, `concurrency_limit=1`, `state='terminal'`, `terminal_at=now()`, and `lifecycle_json` = `{"run_id": <research_run_id>, "run_kind": "account_research", "selection": {"selection_id": …, "subject_type": "account", "workspace_id": …, "project_id": …, "product_id": …, "project_run_id": …, "budget_envelope_ref": "answer-key", "subjects": [{"subject_entity_id": <zafran id>}]}, "origin": "arv2-answer-key-loader"}` with `lifecycle_sha256 = sha256(json.dumps(lifecycle, sort_keys=True, separators=(",", ":")))`.
   - `entity_research_job`: `job_id=uuid5(..., "job:zafran")`, `subject_entity_id=<zafran id>`, `parent_account_id=NULL`, `checkpoint_thread_id="answer-key:zafran"`, `authorization_json` echoing every scoped column exactly as the CHECK requires (`job_id, research_run_id, subject_type, subject_entity_id, workspace_id, project_id, product_id, project_run_id, checkpoint_thread_id, selection{workspace_id, project_id, product_id, project_run_id}`, no `parent_account_id` key), `authorization_sha256`/`initial_state_sha256`/`current_state_sha256` = sha256 of that JSON, `budget_envelope_ref='answer-key'`, `budget_cap_cents=0`, `state='terminal'`, `finalization_outcome='completed'`, `finalization_receipt_ref='answer-key:zafran:completed'`, `terminal_at=now()`.
   - `entity_research_account_coverage`: `coverage_id=uuid5(..., "coverage:zafran")`, `result_refs=[]`, `completed_field_keys` = sorted distinct `account.*`/`core.*` keys written for Zafran, `unresolved_field_keys=[]`, `unresolved_reasons=[]`, `committee_result_refs=[]`, `committee_member_ids` = the five Zafran contact ids, `committee_status='complete'`, `review_flags=[]`, `claim_refs=[f"claim:{id}" for every Zafran claim (account and contact)]`, `evidence_refs=[]`, `coverage_json={"origin": "arv2-answer-key-loader", "account_entity_id": …}` and its sha.
10. Activity events for Zafran (`account_activity_event`, actor `clue`): `created` "Account created" / "added Zafran Security" at the run date; `updated` "Account researched" / f"researched {n} facts"; `contacts` "Buying committee confirmed" / "5 people". For the other three accounts: `created` only.
11. Return the `LoadReport`.

`scripts/load_arv2_answer_key.py` follows the house pattern (`scripts/backfill_fi2_slice0.py`): `--database-url` required, `--context-root` default `.context`, `--storage-root` default `.artifacts/answer-key`, `--dry-run` (runs everything in the transaction, prints the report, rolls back), prints `json.dumps(asdict(report), indent=2, sort_keys=True)`.

- [ ] **Step 1: Write the failing DB test**

`tests/arv2/test_answer_key_loader_db.py`:

```python
"""D1 exit gate: the answer keys load into a real database with entities, lineage and committee."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from clue_api.arv2.answer_key import PEOPLE_RUN_ID, ZAFRAN_MANIFEST, ZAFRAN_RUN_ID
from clue_api.arv2.answer_key_loader import AlreadyLoaded, load_answer_key
from clue_config import Settings
from clue_storage.fs import FsStorage
from tests.claimstore.conftest import rollback_conn
from tests.db.conftest import run_async

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_load_writes_every_row_and_the_screen_prerequisites(tmp_path: Path) -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            report = await load_answer_key(
                conn, storage=FsStorage(tmp_path), context_root=REPO / ".context",
                settings=Settings(_env_file=None, claim_write_lenient=True),
            )
            assert report.claims_written == (174 - 5) + (119 + 3)
            assert set(report.accounts) == {"zafran.io", "cogent.com", "harmonic.security", "uptiq.ai"}
            assert len(report.contacts) == 12
            assert {s["reason"] for s in report.skips} == {"not_found", "duplicate_persona"}
            assert len(report.artifacts) == 3
            ws = ZAFRAN_MANIFEST.workspace_id
            counts = dict(
                (await conn.execute(text(
                    "SELECT run_id::text, count(*) FROM claim WHERE workspace_id = :ws GROUP BY run_id"
                ), {"ws": ws})).all()
            )
            assert counts[str(ZAFRAN_RUN_ID)] == 174 - 5 and counts[str(PEOPLE_RUN_ID)] == 119 + 3
            lineage = (await conn.execute(text(
                "SELECT count(*) FROM run_lineage WHERE workspace_id = :ws AND project_id = :p"
            ), {"ws": ws, "p": ZAFRAN_MANIFEST.project_id})).scalar_one()
            assert lineage == 2
            job = (await conn.execute(text(
                "SELECT state, finalization_outcome FROM entity_research_job WHERE workspace_id = :ws"
            ), {"ws": ws})).one()
            assert tuple(job) == ("terminal", "completed")
            members = (await conn.execute(text(
                "SELECT cardinality(committee_member_ids), committee_status "
                "FROM entity_research_account_coverage WHERE workspace_id = :ws"
            ), {"ws": ws})).one()
            assert tuple(members) == (5, "complete")
            events = (await conn.execute(text(
                "SELECT kind FROM account_activity_event WHERE workspace_id = :ws ORDER BY occurred_at"
            ), {"ws": ws})).scalars().all()
            assert events.count("created") == 4 and "updated" in events and "contacts" in events
            unsafe = (await conn.execute(text(
                "SELECT count(*) FROM claim WHERE workspace_id = :ws AND outreach_safe = false"
            ), {"ws": ws})).scalar_one()
            assert unsafe == 11 + 1  # Zafran's 12 unsafe rows minus the NOT FOUND one, plus one person row
            media = (await conn.execute(text(
                "SELECT count(*) FROM claim WHERE workspace_id = :ws AND artifact_key IS NOT NULL"
            ), {"ws": ws})).scalar_one()
            assert media == 21
            with pytest.raises(AlreadyLoaded):
                await load_answer_key(conn, storage=FsStorage(tmp_path), context_root=REPO / ".context",
                                      settings=Settings(_env_file=None, claim_write_lenient=True))

    run_async(_run())


def test_committee_read_sees_the_five_members(tmp_path: Path) -> None:
    """The existing governed committee read resolves the loaded rows (source map §3.3)."""
    from clue_api.frontend_read.committee import read_governed_committee
    from clue_core import EntityId
    from clue_research.membership import memberships_for_accounts

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            report = await load_answer_key(conn, storage=FsStorage(tmp_path), context_root=REPO / ".context",
                                           settings=Settings(_env_file=None, claim_write_lenient=True))
            zafran = EntityId(__import__("uuid").UUID(report.accounts["zafran.io"]))
            memberships = await memberships_for_accounts(conn, workspace_id=report.workspace_id, account_entity_ids=[zafran])
            committee, _policy = await read_governed_committee(
                conn, account_id=zafran, workspace_id=report.workspace_id, memberships=list(memberships.values())[0]
            )
            names = {m.name for m in committee.members}  # adjust to the union's real attribute names
            assert names == {"Nick Fisher", "Sanaz Yashar", "Vari Kaur", "Tom Anthony", "Ben Seri"}

    run_async(_run())
```

Read `platform/api/clue_api/frontend_read/committee.py:140` and `clue_research.membership.memberships_for_accounts` for the exact return shapes and fix the two `# adjust` lines before running; the assertion (five named members) is the requirement.

The unsafe count is `11 + 1` because zaf-132 is both unsafe and NOT FOUND (skipped) and the people file carries one `outreach_safe: false` row; the media count is the 21 `deterministic_media` rows. If the loader's real numbers differ, print the offending rows and reconcile against the files.

- [ ] **Step 2: Run to verify failure**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_answer_key_loader_db.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Write the loader and the script**

Implement `platform/api/clue_api/arv2/answer_key_loader.py` per the ordered steps above (one `async def load_answer_key`, private helpers `_ensure_spine`, `_load_packs`, `_entities`, `_media_artifacts`, `_write_claims`, `_research_rows`, `_activity`), and `scripts/load_arv2_answer_key.py`:

```python
#!/usr/bin/env python3
"""Load the ARV2 answer keys (Zafran + the ten people) into one database.

    uv run python scripts/load_arv2_answer_key.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue

--database-url is required so this command can never fall through to whatever CLUE_DATABASE_URL
points at (same rule as scripts/backfill_fi2_slice0.py). --dry-run runs the whole load in one
transaction, prints the report and rolls back.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from clue_api.arv2.answer_key_loader import load_answer_key
from clue_config import Settings
from clue_db import db_lifespan
from clue_storage.fs import FsStorage


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--context-root", default=".context")
    parser.add_argument("--storage-root", default=".artifacts/answer-key")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with db_lifespan(args.database_url) as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            report = await load_answer_key(
                conn,
                storage=FsStorage(Path(args.storage_root)),
                context_root=Path(args.context_root),
                settings=Settings(),
            )
            if args.dry_run:
                await trans.rollback()
            else:
                await trans.commit()
        except BaseException:
            await trans.rollback()
            raise
        finally:
            await conn.close()
    return {"dry_run": args.dry_run, **asdict(report)}


def main() -> None:
    print(json.dumps(asyncio.run(_run(_args())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests, then the real load**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_answer_key_loader_db.py tests/arv2 -q` → green.

Then the real load into this worktree's database (the D1 exit gate):

```bash
uv run alembic upgrade head
uv run python scripts/load_arv2_answer_key.py --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue --dry-run
uv run python scripts/load_arv2_answer_key.py --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue
```

Paste the report JSON into your task report. Then prove the rows with:

```bash
uv run python - <<'EOF'
import asyncio, os
from sqlalchemy import text
from clue_db import db_lifespan
async def main():
    async with db_lifespan(os.environ["CLUE_DATABASE_URL"]) as engine, engine.connect() as conn:
        for sql in (
            "SELECT count(*) FROM claim WHERE workspace_id='ws_arv2_answer_key'",
            "SELECT count(*) FROM claim WHERE workspace_id='ws_arv2_answer_key' AND write_markers ? 'schema_valid'",
            "SELECT count(*) FROM claim WHERE workspace_id='ws_arv2_answer_key' AND write_markers ? 'source_missing'",
            "SELECT count(*) FROM claim WHERE workspace_id='ws_arv2_answer_key' AND write_markers ? 'proposed_field'",
            "SELECT field_key, count(*) FROM claim WHERE workspace_id='ws_arv2_answer_key' GROUP BY 1 ORDER BY 2 DESC LIMIT 15",
        ):
            print(sql, "->", (await conn.execute(text(sql))).all())
asyncio.run(main())
EOF
```

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format platform/api/clue_api/arv2/answer_key_loader.py scripts/load_arv2_answer_key.py tests/arv2/test_answer_key_loader_db.py tests/arv2/test_import_guard.py && uv run ruff check <same> && uv run mypy && uv run lint-imports && uv run pytest tests/arv2/test_import_guard.py -q
git add platform/api/clue_api/arv2/answer_key_loader.py scripts/load_arv2_answer_key.py tests/arv2/test_answer_key_loader_db.py tests/arv2/test_import_guard.py
git commit -m "arv2(d1): the answer-key loader — Zafran + ten people into the real store

Spine rows, entities, project membership, project run, run lineage, media transcript artifacts,
every claim through the lenient writer, the terminal research run/job/coverage that makes the
account show researched with a five-person committee, and the activity feed. One-shot per DB."
```

---

## Task 7 — Close-out: README, memory note, plan-document pointers, full gate

**Files:**
- Modify: `platform/api/clue_api/arv2/README.md` (a "D1" section: the writer, the pack, the loader, the flags)
- Create: `_memory/2026-09-07-arv2-d1-migration-writer-and-answer-key.md`
- Modify: `docs/specs/ARV2-MASTER-PLAN.md` §4 (add the `claim.write_markers` column line; note the URL rule moved to promotion; the persona map) and `docs/specs/ARV2-DATA-SOURCE-MAP.md` §2.2 (the `write_markers` row; `display_section_recipe.workspace_id` is `''` for the system row, not NULL)
- Modify: `_memory/README.md` (one topic-note line)

- [ ] **Step 1: Run the full gate and record the baseline delta**

```bash
set -a; source .env; set +a
make check 2>&1 | tail -40
make db-smoke
uv run alembic heads
```
Expected: `make check` shows only the documented pre-existing findings plus nothing new; a single head; db-smoke green. If any new red appears, fix it before this task's commit and list it.

- [ ] **Step 2: Write the records**

The memory note states: what landed (commit shas per task), the twelve plan decisions with a one-line rationale each, the real-load report numbers (claims written, markers by name, skips, artifacts), the exact database and script command used, the gate outputs, and the follow-ups for D2/D3 (`render_value_text` must read `text` on media-wrapped values; D3's `arv2_display_allowed`; the source-map rule that `record` evidence is `extraction_method='api' AND source_url IS NULL` now matches 91 AI Ark rows). Add the README section and the two spec edits (dated, two to four lines each, no history).

- [ ] **Step 3: Commit**

```bash
git add platform/api/clue_api/arv2/README.md _memory/2026-09-07-arv2-d1-migration-writer-and-answer-key.md _memory/README.md docs/specs/ARV2-MASTER-PLAN.md docs/specs/ARV2-DATA-SOURCE-MAP.md
git commit -m "docs(arv2 d1): close-out — README, memory note, master plan §4 + source map §2.2 pointers (write_markers, URL rule at promotion, persona map)"
```

---

## Self-review (run by the plan author before dispatch)

- **Spec coverage.** Master plan §4: priority ✔ (T1/T2), outreach_safe ✔, display_block ✔, display_section_recipe ✔, provider_call_ledger ✔, the minimum-claim rule ✔ (T4 stamps defaults, never refuses), leniency flags ✔ (T1), every field optional ✔ (T3 schemas), new registered fields ✔ (T3), Persona gains user ✔ (T2 + T1 data-fix). Source map §2.2: owner columns ✔, presentation ✔, account_activity_event ✔. Work split A2 ✔ (T1–T3), A3 ✔ (T4–T6): 174 + 119 rows, catalog-valid (lenient markers where not), lineage-pinned, media snapshots, one-fact-one-flag dedupe — **the dedupe of near-duplicate unsafe rows is NOT in this plan**; the control test's two duplicate cases are left as data for D2's recipe input filter, recorded as a follow-up in T7 rather than invented here.
- **Placeholders.** The only unwritten code is `answer_key.py`'s two mapping functions and `answer_key_loader.py`'s helpers, whose rules and order are fully specified line by line above with the exact tables, columns, ids and JSON echoes; `<generated>` is Alembic's revision id; `# adjust` in the committee test names two attribute lookups the implementer must read from `committee.py` and `membership.py`.
- **Type consistency.** `ClaimDraft`/`WriteReceipt`/`LenientClaimWriter(lenient=…)`/`TIER_FOR_METHOD` are named identically in T4, T5 and T6; `ZAFRAN_RUN_ID`, `PEOPLE_RUN_ID`, `ZAFRAN_PROJECT_RUN_ID`, `ZAFRAN_MANIFEST` in T5 and T6; `load_arv2_pack`/`register_arv2_wiring` in T3 and T6; `write_markers` in T1, T2, T4.
