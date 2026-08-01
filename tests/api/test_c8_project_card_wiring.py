"""PC-C8 task 1.3: the project card is what actually reaches the model, and it is reproducible.

Three guarantees the §10 contract delta has to keep, none of which the card compiler can prove on
its own (they are properties of the *wiring*):

* **AC-5 — the model sees the card, not rows.** Walk the messages the real assembler emits and
  assert the L3 body validates as a :class:`Stage0ProjectCard`, with none of the ``to_jsonb(row)``
  column vocabulary the retired stage/readiness snapshots shipped.
* **AC-8 — determinism across a process restart.** The same durable state compiles to the same
  ``content_sha256`` in two *separate interpreters* with different ``PYTHONHASHSEED``. In-process
  repetition cannot catch a set/dict iteration order leaking into the bytes; content-addressed
  artifact reuse (AC-9) is exactly what breaks when it does.
* **The journal role label.** ``agent_artifact_ref.ref_role`` carried ``stage_snapshot`` and
  ``readiness_snapshot``; one turn now writes one ``project_card`` row, and the DB CHECK
  (migration ``933c7b604f1c``) refuses the retired vocabulary.

DB-backed tests follow the ``tests/api`` conventions: a per-branch ``CLUE_DATABASE_URL``, one
rollback-only transaction per scenario, and ``pytest.skip`` when no database is reachable.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
import textwrap
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentRole
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_platform_wiring import build_agent_context_assembler
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_wiring import DbAgentTurnJournal, DurableAgentArtifactStore
from clue_api.stage0_trial import Stage0Trial, Stage0TrialPaths, stage0_trial_context_policy
from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import AccountStatus, MemoryType
from clue_db import db_lifespan
from clue_projections import STAGE0_PROJECT_CARD_MEDIA_TYPE, Stage0ProjectCard
from clue_research.identity import insert_account_entity
from clue_spine import create_brand, create_product, create_project, create_workspace
from clue_storage import FsStorage
from tests.api.test_c8_slice0_evidence import (
    _ANSWER,
    _NoMemory,
    _seed_material_turns,
    _state,
    _turn_request,
)
from tests.db.conftest import _db_available, run_async

# Column names only a ``to_jsonb(row)`` dump carries. The retired stage/readiness snapshots shipped
# whole `volunteered_statement` / `readiness_decision` / `icp_spec` rows, so every one of these was
# in front of the model; a typed card must carry none of them.
_ROW_SHAPE_KEYS = (
    "created_by_actor",
    "onboarding_input_id",
    "quote_sha256",
    "superseded_by",
    "correction_of_id",
    "policy_hash",
    "agent_sufficiency_status",
    "gap_refs",
)


@pytest.fixture
def stage0_db_available() -> bool:
    return _db_available()


@asynccontextmanager
async def _seeded_trial(tmp_path: Path, *, slug: str) -> AsyncIterator[tuple[Any, ...]]:
    """One rollback-only transaction holding a seeded Stage-0 project and a shell trial."""

    state = _state(slug)
    async with db_lifespan() as engine:
        conn = await engine.connect()
        outer = await conn.begin()

        @asynccontextmanager
        async def connection_factory() -> AsyncIterator[AsyncConnection]:
            yield conn

        try:
            await create_workspace(conn, workspace_id=state.workspace_id, name="C8 card wiring")
            brand = await create_brand(
                conn, workspace_id=state.workspace_id, name="Aura", brand_id=state.brand_id
            )
            product = await create_product(
                conn,
                workspace_id=state.workspace_id,
                brand_id=brand.brand_id,
                name="Aura ABM",
                product_id=state.product_id,
            )
            await create_project(
                conn,
                workspace_id=state.workspace_id,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                name="Aura Stage 0 trial",
                project_id=state.project_id,
            )
            client = await insert_account_entity(
                conn,
                canonical_name="Aura AI",
                primary_domain="aura.invalid",
                workspace_id=state.workspace_id,
                status=AccountStatus.ACTIVE,
            )
            seeded = state.model_copy(update={"client_entity_id": client})
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"),
                conn_factory=connection_factory,
            )
            trial = object.__new__(Stage0Trial)
            trial.state = seeded
            trial.paths = Stage0TrialPaths.for_session(tmp_path, seeded.session_slug)
            trial._components = SimpleNamespace(artifacts=artifacts)  # type: ignore[assignment]
            trial._conn_factory = connection_factory  # type: ignore[assignment]
            # A turn's context receipt and artifact refs are journaled against its execution, so
            # the execution row is the one non-Stage-0 durable prerequisite these tests need.
            await conn.execute(
                text(
                    "INSERT INTO execution (id, workspace_id, project_id, started_by, "
                    "parameter_manifest_hash, pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
                ),
                {
                    "id": uuid5(seeded.session_id, "c8-slice0-execution"),
                    "workspace": seeded.workspace_id,
                    "project": seeded.project_id,
                    "hash": "0" * 64,
                },
            )
            await _seed_material_turns(conn, artifacts, state=seeded, statements=6, decisions=5)
            yield trial, conn, artifacts, connection_factory
        finally:
            await outer.rollback()
            await conn.close()


def test_the_assembled_l3_messages_carry_the_card_schema_and_no_row_dumps(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """AC-5: walk what the model is actually handed, not what the compiler returned."""

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"ac5-{uuid4().hex[:8]}") as (
            trial,
            _conn,
            artifacts,
            connection_factory,
        ):
            card_ref = await trial._project_card_ref()
            budget_ref = await trial._artifact(
                "application/vnd.clue.agent-budget-envelope+json",
                {"schema_version": "1", "limit_millicents": 1_000_000},
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
            manifest_ref = await trial._artifact(
                "application/vnd.clue.agent-resource-manifest+json",
                resolved.resource_manifest.model_dump(mode="json"),
            )
            user_ref = await artifacts.persist_body(
                workspace_id=trial.state.workspace_id,
                data=_ANSWER.encode(),
                media_type="text/plain",
            )
            assembler = build_agent_context_assembler(
                resolved_profile=resolved,
                artifacts=artifacts,
                cards=DbCompiledContextCardReader(conn_factory=connection_factory),
                memory=cast(Any, _NoMemory()),
                memory_recipe="recipe0-stage0@3",
                requested_memory_types=(MemoryType.PREFERENCE, MemoryType.BEHAVIORAL_LEARNING),
                policy=stage0_trial_context_policy(),
                conn_factory=connection_factory,
            )
            request = _turn_request(
                state=trial.state,
                resolved=resolved,
                card_ref=card_ref,
                budget_ref=budget_ref,
                manifest_ref=manifest_ref,
                user_ref=user_ref,
            )
            await DbAgentTurnJournal(conn_factory=connection_factory).create(
                request=request, profile=resolved.profile
            )
            context = await assembler.assemble(
                request=request, profile=resolved.profile, history=()
            )

            # The card reaches the model as one materialized L3 file, and it round-trips through
            # the frozen schema — so it is the typed projection, not a dump that happens to fit.
            l3 = [
                item
                for item in context.materializations
                if item.path.startswith("context/project/")
            ]
            assert sorted(item.path for item in l3) == [
                "context/project/budget.json",
                "context/project/project_card.json",
            ]
            card_file = next(
                item for item in l3 if item.path == "context/project/project_card.json"
            )
            card = Stage0ProjectCard.model_validate_json(card_file.data)
            assert card.canonical_bytes() == card_file.data
            assert card.project.project_id == trial.state.project_id
            assert card_ref.media_type == STAGE0_PROJECT_CARD_MEDIA_TYPE

            # No row vocabulary anywhere in what the model reads, L3 messages included.
            bodies = "".join(str(getattr(item, "content", "")) for item in context.messages)
            for key in _ROW_SHAPE_KEYS:
                assert key not in card_file.data.decode()
                assert f'"{key}"' not in bodies

    run_async(scenario())


def test_one_turn_journals_one_project_card_ref_and_no_retired_snapshot_roles(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """The journal vocabulary flipped with the constitution, and the DB enforces the new one."""

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"role-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            card_ref = await trial._project_card_ref()
            budget_ref = await trial._artifact(
                "application/vnd.clue.agent-budget-envelope+json",
                {"schema_version": "1", "limit_millicents": 1_000_000},
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
            manifest_ref = await trial._artifact(
                "application/vnd.clue.agent-resource-manifest+json",
                resolved.resource_manifest.model_dump(mode="json"),
            )
            user_ref = await artifacts.persist_body(
                workspace_id=trial.state.workspace_id,
                data=_ANSWER.encode(),
                media_type="text/plain",
            )
            request = _turn_request(
                state=trial.state,
                resolved=resolved,
                card_ref=card_ref,
                budget_ref=budget_ref,
                manifest_ref=manifest_ref,
                user_ref=user_ref,
            )
            journal = DbAgentTurnJournal(conn_factory=connection_factory)
            await journal.create(request=request, profile=resolved.profile)

            roles = [
                row[0]
                for row in (
                    await conn.execute(
                        text(
                            "SELECT ref_role, artifact_key FROM agent_artifact_ref "
                            "WHERE turn_id = :turn ORDER BY ref_role"
                        ),
                        {"turn": request.turn_id},
                    )
                ).all()
            ]
            assert roles == [
                "budget_envelope",
                "project_card",
                "resource_manifest",
                "user_message",
            ]
            card_row = (
                await conn.execute(
                    text(
                        "SELECT artifact_key FROM agent_artifact_ref "
                        "WHERE turn_id = :turn AND ref_role = 'project_card'"
                    ),
                    {"turn": request.turn_id},
                )
            ).scalar_one()
            assert card_row == card_ref.artifact_key

            # And the retired vocabulary is refused by the schema, not merely unused.
            with pytest.raises(Exception, match="agent_artifact_ref_role"):
                await conn.execute(
                    text(
                        "INSERT INTO agent_artifact_ref (id, turn_id, workspace_id, owner_kind, "
                        "owner_id, ref_role, ordinal, artifact_key, artifact_sha256, "
                        "retention_class) VALUES (:id, :turn, :ws, 'turn', :turn, "
                        "'stage_snapshot', 0, :key, :sha, 'agent-turn-standard')"
                    ),
                    {
                        "id": uuid5(request.turn_id, "retired-role"),
                        "turn": request.turn_id,
                        "ws": trial.state.workspace_id,
                        "key": card_ref.artifact_key,
                        "sha": card_ref.sha256,
                    },
                )

    run_async(scenario())


# --- AC-8: byte-identical across a process restart -------------------------------------------

# Deliberately self-contained: it runs in a *fresh interpreter*, so it may not import the test
# module. It seeds a fully deterministic Stage-0 project (fixed scope ids, uuid5 input ids, no
# client entity — the account row's id is DB-generated and would be the one non-reproducible
# input), compiles the card, prints its sha, and rolls everything back.
_DETERMINISM_SCRIPT = textwrap.dedent(
    """
    import asyncio, hashlib, sys
    from contextlib import asynccontextmanager
    from uuid import NAMESPACE_URL, uuid5

    from clue_api.agent_turn_wiring import DurableAgentArtifactStore
    from clue_api.statement_evidence import ArtifactStatementEvidenceReader
    from clue_config import DEFAULT_STAGE0_POLICY
    from clue_core import (
        EntityId, OnboardingInputId, OnboardingInputKind, ReadinessDecisionId, ReadinessGate,
    )
    from clue_db import db_lifespan
    from clue_projections import compile_stage0_project_card
    from clue_research.stage0 import (
        StatementRoute, ensure_readiness_spec, evaluate_readiness, record_statement,
        submit_onboarding_input,
    )
    from clue_spine import create_brand, create_product, create_project, create_workspace
    from clue_storage import FsStorage

    ROOT = sys.argv[1]
    WS = "c8-determinism-ws"
    BRAND, PRODUCT, PROJECT = "brand_det", "product_det", "project_det"
    CLIENT = EntityId(uuid5(NAMESPACE_URL, "c8-determinism-client"))
    ANSWER = (
        "We sell an AI-native ABM platform to neurosurgery practices in the US that run "
        "their own imaging."
    )


    async def main() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            outer = await conn.begin()

            @asynccontextmanager
            async def factory():
                yield conn

            try:
                await create_workspace(conn, workspace_id=WS, name="C8 determinism")
                brand = await create_brand(conn, workspace_id=WS, name="Aura", brand_id=BRAND)
                product = await create_product(
                    conn, workspace_id=WS, brand_id=brand.brand_id, name="Aura ABM",
                    product_id=PRODUCT,
                )
                await create_project(
                    conn, workspace_id=WS, brand_id=brand.brand_id,
                    product_id=product.product_id, name="Aura", project_id=PROJECT,
                )
                artifacts = DurableAgentArtifactStore(
                    storage=FsStorage(ROOT), conn_factory=factory
                )
                for index in range(6):
                    ref = await artifacts.persist_body(
                        workspace_id=WS,
                        data=f"{ANSWER} (turn {index})".encode(),
                        media_type="text/plain",
                    )
                    captured = await submit_onboarding_input(
                        conn, workspace_id=WS, brand_id=BRAND, product_id=PRODUCT,
                        project_id=PROJECT, kind=OnboardingInputKind.USER_TURN,
                        artifact_key=ref.artifact_key, content_sha256=ref.sha256, actor="human",
                        onboarding_input_id=OnboardingInputId(
                            uuid5(NAMESPACE_URL, f"c8-determinism:input:{index}")
                        ),
                    )
                    await record_statement(
                        conn, onboarding_input_id=captured.onboarding_input_id, workspace_id=WS,
                        brand_id=BRAND, product_id=PRODUCT, project_id=PROJECT,
                        route_kind=StatementRoute.PROJECT_STATE,
                        route_key=f"target_segment_{index}", quote=ANSWER[37:59],
                        quote_start=37, quote_end=59, created_by_actor="agent",
                    )
                    await evaluate_readiness(
                        conn, workspace_id=WS, brand_id=BRAND, product_id=PRODUCT,
                        project_id=PROJECT, client_kb_version=1,
                        gate=ReadinessGate.ICP_SYNTHESIS, spec=DEFAULT_STAGE0_POLICY.readiness,
                        metrics={"coverage_ratio": 0.0, "verified_claims": 0},
                        created_by_actor="system",
                        readiness_decision_id=ReadinessDecisionId(
                            uuid5(NAMESPACE_URL, f"c8-determinism:readiness:{index}")
                        ),
                    )
                spec_version = await ensure_readiness_spec(
                    conn, workspace_id=WS, spec=DEFAULT_STAGE0_POLICY.readiness
                )
                card = await compile_stage0_project_card(
                    project_id=PROJECT, workspace_id=WS, client_entity_id=CLIENT,
                    client_kb_version=1,
                    evidence=ArtifactStatementEvidenceReader(
                        artifacts=artifacts, conn_factory=factory
                    ),
                    product_id=PRODUCT, readiness_spec_version=spec_version, conn_factory=factory,
                )
                print(card.content_sha256())
            finally:
                await outer.rollback()
                await conn.close()


    asyncio.run(main())
    """
)


def test_the_same_durable_state_compiles_the_same_card_in_a_second_process(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """AC-8's restart half: two interpreters, two hash seeds, one ``content_sha256``.

    A card whose bytes depend on ``PYTHONHASHSEED`` — one set iteration, one unordered dict —
    still looks perfectly deterministic inside a single process, and would silently defeat the
    content-addressed reuse AC-9 depends on: every turn would persist a "new" card.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    shas: list[str] = []
    for index, seed in enumerate(("0", "424242")):
        root = tmp_path / f"run-{index}"
        root.mkdir()
        result = subprocess.run(  # noqa: S603 - fixed argv, this interpreter
            [sys.executable, "-c", _DETERMINISM_SCRIPT, str(root)],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        assert result.returncode == 0, result.stderr
        shas.append(result.stdout.strip().splitlines()[-1])

    assert len(shas[0]) == 64
    assert shas[0] == shas[1], (
        f"the same durable state compiled two different cards across processes: {shas}"
    )


def test_the_card_is_content_addressed_so_an_unchanged_project_persists_no_second_artifact(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """AC-9's mechanism: identical state re-persists the identical key, not a duplicate."""

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"addr-{uuid4().hex[:8]}") as (
            trial,
            conn,
            _artifacts,
            _factory,
        ):
            first = await trial._project_card_ref()
            second = await trial._project_card_ref()
            assert first == second
            rows = (
                await conn.execute(
                    text("SELECT count(*) FROM artifact WHERE storage_key = :key"),
                    {"key": first.artifact_key},
                )
            ).scalar_one()
            assert rows == 1
            assert first.artifact_key.endswith(f"/{first.sha256}")

    run_async(scenario())


def test_the_report_snapshot_stopped_naming_the_current_turn() -> None:
    """Turn identity has one owner (L7): the human inspection surface no longer names it too.

    A no-DB shape check on the production signature. ``snapshot()`` used to take a
    ``current_turn`` block and echo it as ``current_turn_input``, which is how the model came to
    read an id out of L3 and hand it back as if it had chosen it.
    """

    signature = inspect.signature(Stage0Trial.snapshot)
    assert list(signature.parameters) == ["self"]
    source = inspect.getsource(Stage0Trial.snapshot)
    assert "current_turn_input" not in source
