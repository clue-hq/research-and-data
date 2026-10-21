"""``write_brand_document@1`` (CRM integration Task 9): the Head of ABM publishes a Brand-context
document under company/ or proof/, as a new brand-level version of the conversation's brand."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from clue_api.brand_document_tool import WriteBrandDocumentInput, WriteBrandDocumentTool
from clue_api.brand_knowledge_writes import write_brand_document_version
from clue_api.product_management import read_brand_document
from clue_api.sandbox.workspaces import SandboxMounts, SandboxWorkspaces
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_execution_id, new_operation_id
from clue_storage import FsStorage
from clue_toolbelt import PreconditionFailed, ToolContext
from tests.agents.workspace_helpers import policy
from tests.api.test_lane_d4_agent_gate_db import USER_ID, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


def _ctx(conn: Any, workspace_id: str, execution_id: Any = None) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=new_operation_id(),
        execution_id=execution_id,
    )


def _input(seeded: Any, **values: Any) -> WriteBrandDocumentInput:
    return WriteBrandDocumentInput(source_turn_ref=derive_turn_action_ref(seeded.turn_id), **values)


async def _codes(tool: WriteBrandDocumentTool, inputs: Any, ctx: ToolContext) -> list[str]:
    return [failure.reason_code for failure in await tool.preconditions(inputs, ctx)]


async def _versions(conn: Any, workspace_id: str, path: str) -> list[tuple[int, str, str]]:
    rows = await conn.execute(
        text(
            "SELECT version, status, kind FROM brand_knowledge_document "
            "WHERE workspace_id = :ws AND path = :path AND project_id IS NULL ORDER BY version"
        ),
        {"ws": workspace_id, "path": path},
    )
    return [(int(r[0]), str(r[1]), str(r[2])) for r in rows]


async def _brand(conn: Any, seeded: Any) -> str:
    return str(
        await conn.scalar(
            text("SELECT brand_id FROM project WHERE project_id = :id"), {"id": seeded.project_id}
        )
    )


def _run(tmp_path: Path, label: str, body: Any, sandbox: SandboxWorkspaces | None = None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-bdoc-{label}", label=label)
            storage = FsStorage(tmp_path / f"bdoc-{label}")
            tool = WriteBrandDocumentTool(
                storage=storage,
                sandbox_workspaces=sandbox,
                conn_factory=conn_session_factory(conn),
            )
            await body(conn, seeded, tool, storage)

    run_async(scenario())


def test_writes_new_version_and_supersedes_previous(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, tool: WriteBrandDocumentTool, storage: Any) -> None:
        ws = seeded.workspace_id
        first = _input(
            seeded, path="company/sales-motion.md", kind="sales-motion", markdown="# Sales\n\nv1\n"
        )
        assert await _codes(tool, first, _ctx(conn, ws)) == []
        one = (await tool.invoke(first, _ctx(conn, ws))).references
        assert one["version"] == 1 and one["unchanged"] is False
        # an existing document keeps its kind, so kind may be left out
        second = _input(
            seeded, path="company/sales-motion.md", markdown="# Sales\n\nv2\n", based_on_version=1
        )
        two = (await tool.invoke(second, _ctx(conn, ws))).references
        assert two["version"] == 2
        assert await _versions(conn, ws, "company/sales-motion.md") == [
            (1, "superseded", "sales-motion"),
            (2, "ready", "sales-motion"),
        ]
        front, text_body = await read_brand_document(
            conn,
            storage,
            workspace_id=ws,
            brand_id=await _brand(conn, seeded),
            document_id=UUID(two["document_id"]),
        ) or ({}, "")
        assert text_body.strip() == "# Sales\n\nv2"
        assert front["kind"] == "sales-motion"
        assert front["written_by"] == {"user_id": USER_ID, "turn_id": str(seeded.turn_id)}
        # the same bytes again publish nothing (a replay is harmless)
        again = (await tool.invoke(second, _ctx(conn, ws))).references
        assert again == {**two, "unchanged": True}
        assert len(await _versions(conn, ws, "company/sales-motion.md")) == 2

    _run(tmp_path, "versions", body)


def test_an_existing_document_keeps_its_front_matter(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, tool: WriteBrandDocumentTool, storage: Any) -> None:
        ws = seeded.workspace_id
        brand = await _brand(conn, seeded)
        # onboarding's version, with its own front matter
        await write_brand_document_version(
            conn,
            storage,
            workspace_id=ws,
            brand_id=brand,
            path="proof/customers.md",
            kind="existing-customers",
            front={"kind": "existing-customers", "sources": [{"url": "https://a.test"}]},
            body="# Existing customers\n",
            source_key="test",
        )
        refs = (
            await tool.invoke(
                _input(
                    seeded,
                    path="proof/customers.md",
                    markdown="# Existing customers\n\nmore\n",
                    based_on_version=1,
                ),
                _ctx(conn, ws),
            )
        ).references
        front, _body = await read_brand_document(
            conn, storage, workspace_id=ws, brand_id=brand, document_id=UUID(refs["document_id"])
        ) or ({}, "")
        assert front["sources"] == [{"url": "https://a.test"}]
        assert front["kind"] == "existing-customers"
        assert front["written_by"]["user_id"] == USER_ID
        assert await _versions(conn, ws, "proof/customers.md") == [
            (1, "superseded", "existing-customers"),
            (2, "ready", "existing-customers"),
        ]
        with pytest.raises(PreconditionFailed) as exc:
            await tool.invoke(
                _input(
                    seeded,
                    path="proof/customers.md",
                    kind="other",
                    markdown="# B\n",
                    based_on_version=2,
                ),
                _ctx(conn, ws),
            )
        assert exc.value.reason_codes == ("kind_mismatch",)

    _run(tmp_path, "front", body)


@pytest.mark.parametrize(
    "path",
    [
        "design/brief.md",
        "project/plan.md",
        "company/../product/catalog.md",
        "company/Sales Motion.md",
        "company/sales-motion.txt",
        "proof/nested/customers.md",
    ],
)
def test_paths_outside_brand_context_are_refused(tmp_path: Path, path: str) -> None:
    async def body(conn: Any, seeded: Any, tool: WriteBrandDocumentTool, storage: Any) -> None:
        inputs = _input(seeded, path=path, kind="x", markdown="# X\n")
        assert await _codes(tool, inputs, _ctx(conn, seeded.workspace_id)) == ["path_not_allowed"]

    _run(tmp_path, f"path-{abs(hash(path)) % 10_000}", body)


@pytest.mark.parametrize(
    "path", ["audience/icp-gi.md", "audience/persona-gi.md", "product/aura-scribe.md"]
)
def test_audience_and_product_documents_can_be_written(tmp_path: Path, path: str) -> None:
    async def body(conn: Any, seeded: Any, tool: WriteBrandDocumentTool, storage: Any) -> None:
        inputs = _input(seeded, path=path, kind="x", markdown="# X\n")
        refs = (await tool.invoke(inputs, _ctx(conn, seeded.workspace_id))).references
        assert refs["version"] == 1 and refs["path"] == path

    _run(tmp_path, f"ok-{abs(hash(path)) % 10_000}", body)


def test_generated_documents_are_refused(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, tool: WriteBrandDocumentTool, storage: Any) -> None:
        ws = seeded.workspace_id
        catalog = _input(seeded, path="product/catalog.md", kind="product-catalog", markdown="# C\n")
        assert await _codes(tool, catalog, _ctx(conn, ws)) == ["document_generated"]
        await write_brand_document_version(
            conn,
            storage,
            workspace_id=ws,
            brand_id=await _brand(conn, seeded),
            path="company/generated-thing.md",
            kind="x",
            front={"kind": "x", "generated": True},
            body="# G\n",
            source_key="test",
        )
        with pytest.raises(PreconditionFailed) as exc:
            await tool.invoke(
                _input(seeded, path="company/generated-thing.md", markdown="# Y\n", based_on_version=1),
                _ctx(conn, ws),
            )
        assert exc.value.reason_codes == ("document_generated",)

    _run(tmp_path, "generated", body)


def test_a_document_saved_since_you_read_it_is_not_overwritten(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, tool: WriteBrandDocumentTool, storage: Any) -> None:
        ws = seeded.workspace_id
        path = "company/sales-motion.md"
        await tool.invoke(
            _input(seeded, path=path, kind="sales-motion", markdown="# v1\n"), _ctx(conn, ws)
        )
        # another chat (or a person) saves version 2
        await tool.invoke(
            _input(seeded, path=path, markdown="# v2 by someone else\n", based_on_version=1),
            _ctx(conn, ws),
        )
        for stale in (
            _input(seeded, path=path, markdown="# mine, built on v1\n", based_on_version=1),
            # leaving the version out on a document that exists is refused too
            _input(seeded, path=path, markdown="# mine\n"),
        ):
            with pytest.raises(PreconditionFailed) as exc:
                await tool.invoke(stale, _ctx(conn, ws))
            assert exc.value.reason_codes == ("document_changed",)
            assert "version 2" in exc.value.failures[0].message
        assert [v for v, _status, _kind in await _versions(conn, ws, path)] == [1, 2]

    _run(tmp_path, "stale", body)


def test_exactly_one_of_markdown_or_file(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, tool: WriteBrandDocumentTool, storage: Any) -> None:
        ctx = _ctx(conn, seeded.workspace_id)
        neither = _input(seeded, path="company/sales-motion.md", kind="sales-motion")
        both = _input(
            seeded,
            path="company/sales-motion.md",
            kind="sales-motion",
            markdown="# X\n",
            from_file="outputs/x.md",
        )
        assert await _codes(tool, neither, ctx) == ["markdown_or_file_required"]
        assert await _codes(tool, both, ctx) == ["markdown_or_file_required"]
        front_matter = _input(
            seeded, path="company/sales-motion.md", kind="sales-motion", markdown="---\na: 1\n---\nx"
        )
        assert await _codes(tool, front_matter, ctx) == ["front_matter_not_allowed"]
        new_without_kind = _input(seeded, path="company/sales-motion.md", markdown="# X\n")
        with pytest.raises(PreconditionFailed) as exc:
            await tool.invoke(new_without_kind, ctx)
        assert exc.value.reason_codes == ("kind_required",)

    _run(tmp_path, "one-of", body)


def test_from_file_reads_sandbox_output(tmp_path: Path) -> None:
    outputs = tmp_path / "thread" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "sales-motion.md").write_text("# Sales motion\n\nFrom the sandbox.\n")
    (tmp_path / "secret.md").write_text("# not yours\n")
    sandbox = SandboxWorkspaces(max_runs_per_turn=1)
    execution_id = new_execution_id()
    sandbox.register(
        execution_id,
        SandboxMounts(
            thread_root=tmp_path / "thread",
            read_only={},
            read_write={"outputs": outputs},
            policy=policy(),
        ),
    )

    async def body(conn: Any, seeded: Any, tool: WriteBrandDocumentTool, storage: Any) -> None:
        ws = seeded.workspace_id
        inputs = _input(
            seeded,
            path="company/sales-motion.md",
            kind="sales-motion",
            from_file="outputs/sales-motion.md",
        )
        refs = (await tool.invoke(inputs, _ctx(conn, ws, execution_id))).references
        _front, text_body = await read_brand_document(
            conn,
            storage,
            workspace_id=ws,
            brand_id=await _brand(conn, seeded),
            document_id=UUID(refs["document_id"]),
        ) or ({}, "")
        assert "From the sandbox." in text_body
        missing = _input(seeded, path="company/x.md", kind="x", from_file="outputs/nope.md")
        assert await _codes(tool, missing, _ctx(conn, ws, execution_id)) == ["file_not_found"]
        escape = _input(seeded, path="company/x.md", kind="x", from_file="outputs/../../secret.md")
        assert await _codes(tool, escape, _ctx(conn, ws, execution_id)) == ["file_not_allowed"]
        no_turn_sandbox = _input(
            seeded, path="company/x.md", kind="x", from_file="outputs/sales-motion.md"
        )
        assert await _codes(tool, no_turn_sandbox, _ctx(conn, ws)) == ["sandbox_unavailable"]

    _run(tmp_path, "from-file", body, sandbox=sandbox)


def test_no_storage_refuses(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, tool: WriteBrandDocumentTool, storage: Any) -> None:
        bare = WriteBrandDocumentTool(
            storage=None, sandbox_workspaces=None, conn_factory=conn_session_factory(conn)
        )
        inputs = _input(seeded, path="company/x.md", kind="x", markdown="# X\n")
        assert await _codes(bare, inputs, _ctx(conn, seeded.workspace_id)) == [
            "storage_unavailable"
        ]

    _run(tmp_path, "no-storage", body)
