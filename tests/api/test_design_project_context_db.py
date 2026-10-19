"""Design must see exact project instruction/decision sources, not just a brief."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally function arguments

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.design_platform_reads import (
    DesignPlatformReadError,
    build_design_platform_reads_factory,
)
from clue_api.project_context_files import CompiledProjectFile, load_or_create_project_files_pin
from tests.api.test_design_platform_reads_db import _leg_envelope, _seeded
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401


def test_design_reads_exact_opening_instructions_and_decision_sources(tmp_path: Path, migrated_db):
    if not migrated_db:
        pytest.skip("requires a disposable migrated database")

    async def scenario():
        async with rollback_conn() as conn:
            seeded = await _seeded(conn, tmp_path, label="project-sources")
            artifacts = DurableAgentArtifactStore(
                storage=seeded["storage"], conn_factory=seeded["conn_factory"]
            )
            instructions = (
                "# Instructions\nKeep the target logo above the hero, outside navigation.\n"
            )
            decisions = (
                '# Decisions\n{"statement_id":"old","input_actor":"human",'
                '"quote":"Paired header"}\n'
            )

            async def compile_files():
                return tuple(
                    CompiledProjectFile(path, kind, body.encode(), 1, "ready", "")
                    for path, kind, body in (
                        ("instructions.md", "project-instructions", instructions),
                        ("decisions.md", "project-decisions", decisions),
                        ("audience/icp.md", "icp-definition", "Do not copy unrelated files."),
                    )
                )

            pin, _ = await load_or_create_project_files_pin(
                conn,
                artifacts,
                workspace_id=seeded["workspace_id"],
                project_id=seeded["project"].project_id,
                turn_id=seeded["opening_turn"],
                compile=compile_files,
            )
            factory = build_design_platform_reads_factory(
                invoker=seeded["invoker"],
                storage=seeded["storage"],
                conn_factory=seeded["conn_factory"],
            )
            envelope = _leg_envelope(
                seeded["workspace_id"], seeded["project"].project_id, seeded["opening_turn"]
            )
            reads = factory(envelope)
            method = getattr(reads, "project_design_context", None)
            assert callable(method), "Design cannot currently read the sources behind its brief"
            result = await asyncio.to_thread(method)
            assert result["status"] == "available"
            assert result["source_turn_id"] == str(seeded["opening_turn"])
            assert result["source_pin_sha256"] == pin.files_sha256
            assert result["is_live_project_view"] is False
            assert {f["path"]: f["body_text"] for f in result["files"]} == {
                "instructions.md": instructions,
                "decisions.md": decisions,
            }
            assert all(f["artifact_sha256"] and f["artifact_key"] for f in result["files"])

    run_async(scenario())


@pytest.mark.parametrize(
    "case", ["no_opening", "no_pin", "foreign_workspace", "foreign_project", "tampered", "erased"]
)
def test_project_sources_refuse_unavailable_or_wrong_scope_bytes(tmp_path: Path, migrated_db, case):
    if not migrated_db:
        pytest.skip("requires a disposable migrated database")

    async def scenario():
        async with rollback_conn() as conn:
            seeded = await _seeded(conn, tmp_path, label="source-boundaries")
            artifacts = DurableAgentArtifactStore(
                storage=seeded["storage"], conn_factory=seeded["conn_factory"]
            )

            async def compile_files():
                return (
                    CompiledProjectFile(
                        "instructions.md",
                        "project-instructions",
                        b"Private instruction.",
                        1,
                        "ready",
                        "",
                    ),
                )

            pin, _ = await load_or_create_project_files_pin(
                conn,
                artifacts,
                workspace_id=seeded["workspace_id"],
                project_id=seeded["project"].project_id,
                turn_id=seeded["opening_turn"],
                compile=compile_files,
            )
            opening = None if case == "no_opening" else seeded["opening_turn"]
            if case == "no_pin":
                opening = uuid4()
            envelope = _leg_envelope(
                "ws_foreign" if case == "foreign_workspace" else seeded["workspace_id"],
                "prj_foreign" if case == "foreign_project" else seeded["project"].project_id,
                opening,
            )
            if case == "tampered":
                await seeded["storage"].put(
                    pin.files[0].artifact_key, b"Different bytes", media_type="text/markdown"
                )
            if case == "erased":
                await seeded["storage"].delete(pin.files[0].artifact_key)
            reads = build_design_platform_reads_factory(
                invoker=seeded["invoker"],
                storage=seeded["storage"],
                conn_factory=seeded["conn_factory"],
            )(envelope)
            if case in {"foreign_project", "tampered", "erased"}:
                with pytest.raises(DesignPlatformReadError, match="^read_failed$"):
                    await asyncio.to_thread(reads.project_design_context)
            else:
                result = await asyncio.to_thread(reads.project_design_context)
                assert result["status"] == "not_pinned"
                assert result["files"] == []
                assert result["is_live_project_view"] is False

    run_async(scenario())
