"""Site birth behind CLUE_DESIGN_SITE_ENGINE_WORKSPACES (plan 2026-10-09, Task 3)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import DomainObjectRef
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.design_leg_tools import OpenDesignLegTool
from clue_api.design_leg_wiring import _exit_judge_artifact_lines, design_leg_run_id
from clue_api.toolbelt_wiring import build_toolbelt
from clue_design import legs as design_legs
from clue_design.documents import create_document, get_document
from clue_research.membership import ensure_project_account
from clue_toolbelt import ToolRegistry
from tests.api.conftest import hermetic_flag_env
from tests.api.test_genad_leg_document_birth_db import (
    _open,
    _RecordingSceneMinter,
    _seed_conversation,
)
from tests.api.test_genweb_leg_document_birth_db import engine_web_doc
from tests.api.test_genweb_web_turn_dispatch_db import (
    _FakeLane,
    _run_turn,
    _seed_leg_conversation,
    _submit_message,
)
from tests.api.test_multi_artifact_leg_birth_db import _seed_account_entity
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


# --- K6-3 / founder ruling 2026-10-16: every website the leg births is noindex at birth ----------


async def _tagged_account(conn: AsyncConnection, seeds: dict[str, Any]) -> str:
    """A live research account of this workspace, on this project: what the composer's tag names."""

    entity_id = await _seed_account_entity(
        conn, workspace_id=seeds["workspace_id"], name="Apollo Clinics", domain="apollo.example"
    )
    await ensure_project_account(
        conn,
        workspace_id=seeds["workspace_id"],
        project_id=seeds["project_id"],
        account_entity_id=entity_id,
        added_via="manual",
    )
    return str(entity_id)


@pytest.mark.parametrize("listed", [True, False], ids=["site", "web"])
def test_every_website_a_leg_births_is_noindex_tagged_account_or_not(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
    listed: bool,
) -> None:
    """Founder ruling 2026-10-16 (widening K6-3 / R25-4): every NEW web or site document is born
    with the durable noindex, through the one birth rule in the design DAL's insert. A chat-born
    page for a tagged account is noindex (the case K6-3 fixed), and so is a generic page in the
    same delegation; a person makes one indexable by ticking "Allow indexing" in Share."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label=f"noindex-{listed}")
            account = await _tagged_account(conn, seeds)
            result = await _open(
                seeds,
                _registry(seeds, listed=listed),
                doc_kind="web",
                artifacts=[
                    {"title": "Apollo page", "note": "for Apollo", "account_id": account},
                    {"title": "Generic page", "note": "no account"},
                ],
            )
            tagged, generic = [
                await get_document(
                    conn, workspace_id=seeds["workspace_id"], document_id=str(document_id)
                )
                for document_id in result.references["document_ids"]
            ]
            assert tagged["doc_kind"] == generic["doc_kind"] == ("site" if listed else "web")
            assert tagged["account_id"] is not None and tagged["web_noindex"] is True
            assert generic["account_id"] is None and generic["web_noindex"] is True

    run_async(scenario())


# --- Lane B (Contract 7): a site document runs a site_turn on a fresh thread ---------------------


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


#: What the site executor returns for a saved request (Contract 7), with one collected model call.
APPLIED_SITE_RESULT: dict[str, Any] = {
    "schema_version": 1,
    "status": "applied",
    "outcome": "saved",
    "summary": "Built the landing page.",
    "doc_kind": "site",
    "current_version": 1,
    "saved_version": 1,
    "stop_reason": None,
    "model_calls": [
        {
            "run_id": "8f0f1f51-0b5d-4a43-9d39-1d3c5d2f0a11",
            "sequence": 1,
            "requested_model": "openai:test/model",
            "answering_model": "test/model",
            "status": "completed",
            "role": "design_site",
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_input_tokens": 0,
            "cost_cents": "0.5",
            "cost_source": "metered",
            "langfuse_trace_id": None,
            "langfuse_observation_id": None,
            "latency_ms": 12.0,
            "error_code": None,
            "started_at": datetime(2026, 10, 11, 9, 0, tzinfo=UTC).isoformat(),
            "completed_at": datetime(2026, 10, 11, 9, 0, 1, tzinfo=UTC).isoformat(),
        }
    ],
}


def test_a_site_document_leg_dispatches_a_site_turn_on_a_fresh_thread(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Contract 7: doc_kind='site' -> kind='site_turn'; fresh session per request (thread = run);
    the summary names the website; the run's model calls reach agent_model_call."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_site_leg(conn, storage_root=tmp_path, label="siteturn")
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_SITE_RESULT)
            submission = await _submit_message(
                conn, seeds, label="siteturn", message="Build the landing page."
            )
            await _run_turn(conn, seeds, registry, lane, submission)

            envelope = lane.envelopes[0]
            run_id = design_leg_run_id(submission.turn_id)
            assert envelope.kind == "site_turn" and envelope.document_id == document["id"]
            assert envelope.checkpoint_thread_id == envelope.run_id == run_id
            assert envelope.config["request"] == {
                "prompt": "Build the landing page.",
                "base_version": document["current_version"],
            }
            assert "ad_lane" not in envelope.config and "design_memory" not in envelope.config
            assert "document_base_version" not in envelope.config["leg"]
            kind = (
                await conn.execute(
                    text(
                        "SELECT kind FROM design_agent_run "
                        "WHERE run_id = :run AND workspace_id = :ws"
                    ),
                    {"run": run_id, "ws": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert str(kind) == "site_turn"
            reply = (
                (
                    await conn.execute(
                        text(
                            "SELECT role FROM agent_thread_message "
                            "WHERE workspace_id = :ws AND thread_id = :t "
                            "ORDER BY sequence"
                        ),
                        {"ws": seeds["workspace_id"], "t": seeds["thread_id"]},
                    )
                )
                .scalars()
                .all()
            )
            assert list(reply)[-1] == "assistant"
            calls = (
                await conn.execute(
                    text("SELECT count(*) FROM agent_model_call WHERE turn_id = :turn"),
                    {"turn": submission.turn_id},
                )
            ).scalar_one()
            assert int(calls) == 1

    run_async(scenario())


def test_the_exit_judge_calls_a_site_a_web_page(tmp_path: Path, migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_site_leg(conn, storage_root=tmp_path, label="sitelabel")
            lines = await _exit_judge_artifact_lines(
                conn,
                workspace_id=seeds["workspace_id"],
                leg_documents=[
                    {
                        "document_id": document["id"],
                        "doc_kind": "site",
                        "title": "Harbor & Sage",
                        "position": 0,
                    }
                ],
            )
            assert lines[0].startswith('1. "Harbor & Sage" (web page)')

    run_async(scenario())


def test_site_annotations_ride_the_request_as_targets_in_order(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Ruling R9: the parts the person pointed at reach the site turn, in submission order, with
    their notes. (A targetless site request staying exactly {prompt, base_version} is pinned by
    Task 13's `test_a_site_document_leg_dispatches_a_site_turn_on_a_fresh_thread`.)"""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_site_leg(conn, storage_root=tmp_path, label="sitetargets")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_SITE_RESULT)

            def ref(object_type: str, object_id: str, note: str | None = None) -> DomainObjectRef:
                return DomainObjectRef(
                    workspace_id=seeds["workspace_id"],
                    object_type=object_type,
                    object_id=object_id,
                    note=note,
                )

            submission = await _submit_message(
                conn, seeds, label="sitetargets", message="Two fixes, please."
            )
            await _run_turn(
                conn,
                seeds,
                registry,
                lane,
                submission,
                focus_refs=(
                    ref("design_document", document["id"]),
                    ref("design_node", "site:/#hero.title", "1. Make it warmer."),
                    ref("design_node", "site:shell#header"),
                ),
            )
            request = lane.envelopes[0].config["request"]
            assert request["prompt"] == "Two fixes, please."
            assert request["targets"] == [
                {"object_id": "site:/#hero.title", "note": "1. Make it warmer."},
                {"object_id": "site:shell#header", "note": None},
            ]

    run_async(scenario())
