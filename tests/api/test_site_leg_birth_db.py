"""Site birth behind CLUE_DESIGN_SITE_ENGINE_WORKSPACES (plan 2026-10-09, Task 3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentExecutionStatus
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.design_leg_tools import OpenDesignLegTool
from clue_api.toolbelt_wiring import build_toolbelt
from clue_design import legs as design_legs
from clue_design.documents import create_document, get_document
from clue_toolbelt import ToolRegistry
from tests.api.conftest import hermetic_flag_env
from tests.api.test_genad_leg_document_birth_db import (
    _open,
    _RecordingSceneMinter,
    _seed_conversation,
)
from tests.api.test_genweb_leg_document_birth_db import engine_web_doc
from tests.api.test_genweb_web_turn_dispatch_db import (
    APPLIED_WEB_RESULT,
    _FakeLane,
    _run_turn,
    _seed_leg_conversation,
    _submit_message,
    _turn_facts,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401


def _refusing_web_minter(**_: Any) -> dict[str, Any]:
    raise AssertionError("a listed workspace must never mint a WebDoc")


def _registry(seeds: dict[str, Any], *, listed: bool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        OpenDesignLegTool(
            conn_factory=seeds["conn_factory"],
            storage=seeds["storage"],
            scene_document_minter=_RecordingSceneMinter(),
            web_document_minter=_refusing_web_minter if listed else engine_web_doc,
            site_engine_workspaces=frozenset({seeds["workspace_id"]}) if listed else frozenset(),
        ),
        make_default=True,
    )
    return registry


def test_a_listed_workspace_births_a_site_document(tmp_path: Path, migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="site")
            result = await _open(seeds, _registry(seeds, listed=True), doc_kind="web")
            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(result.references["document_id"]),
            )
            assert document["doc_kind"] == "site"
            assert document["scene"]["pages"]["/"]["content"] == []
            assert document["current_version"] == 0

    run_async(scenario())


def test_an_unlisted_workspace_births_a_webdoc_unchanged(tmp_path: Path, migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="web-unlisted")
            result = await _open(seeds, _registry(seeds, listed=False), doc_kind="web")
            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(result.references["document_id"]),
            )
            assert document["doc_kind"] == "web"
            assert document["scene"]["pages"][0]["id"] == "home"

    run_async(scenario())


# --- Review focus 3: a site document's turn refuses until the site runtime lands (B5) ------------


async def _seed_site_leg(
    conn: AsyncConnection, *, storage_root: Path, label: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A leg pinned to a real ``doc_kind='site'`` document — `_seed_web_leg`'s site twin."""

    document_id = f"doc_site_{label}_{uuid4().hex[:8]}"
    seeds = await _seed_leg_conversation(conn, storage_root=storage_root, label=label)
    document = await create_document(
        conn,
        workspace_id=seeds["workspace_id"],
        scene={
            "id": document_id,
            "title": "Harbor & Sage",
            "theme": {},
            "pages": {"/": {"root": {"props": {"title": "Harbor & Sage"}}, "content": []}},
            "shell": None,
            "agent_sections": {},
        },
        doc_kind="site",
    )
    await conn.execute(
        text("UPDATE design_leg SET document_id = :doc WHERE id = CAST(:leg AS uuid)"),
        {"doc": document["id"], "leg": seeds["leg"]["id"]},
    )
    seeds["leg"] = await design_legs.get_leg(
        conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
    )
    return seeds, document


def test_a_site_document_turn_refuses_until_the_site_runtime_lands(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """A site document must never fall into the scene runtime (the ``else "agent_turn"`` arm):
    the turn refuses with the typed site-runtime code BEFORE any design run row is written,
    and the leg stays open for the user's next message."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, _document = await _seed_site_leg(conn, storage_root=tmp_path, label="siteturn")
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="siteturn", message="Build the landing page."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)

            assert result.outcome.status is AgentExecutionStatus.FAILED
            assert result.outcome.failure_code == "design_leg_site_runtime_not_composed"
            assert result.assistant_message is None
            assert lane.envelopes == []  # nothing was dispatched
            facts = await _turn_facts(conn, seeds, submission.turn_id)
            assert facts == {
                "runs": 0,
                "roles": ["user"],
                "commits": 0,
                "leg_state": "open_awaiting_user",
            }
            no_rows = (
                await conn.execute(
                    text("SELECT count(*) FROM design_agent_run WHERE workspace_id = :ws"),
                    {"ws": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert int(no_rows) == 0

    run_async(scenario())
