"""One synthesis turn end to end on a scripted model.

The inputs materialize under ``inputs/brand/knowledge/`` and the outputs become documents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text

from clue_agents import ScriptedAgentChatModel
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.onboarding_synthesis_wiring import (
    OnboardingSynthesisLauncher,
    ensure_onboarding_project,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture
def require_profiling_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_profiling_db")

ICP = """---
kind: icp-definition
icp_key: gi-groups
version: 1
status: proposed
product_ids: [prd_aura]
hard_gates:
  - {key: specialty, rule: gastroenterology practices, test: NPI taxonomy}
exclusions: []
persona_map:
  economic_buyer: {titles: [Practice Administrator]}
  user: {titles: [Gastroenterologist]}
qualifier_fields: []
---

# GI groups

Body (inputs/brand/knowledge/company/overview.md).
"""
PERSONA = """---
kind: audience-persona
icp_key: gi-groups
icp_version: 1
personas:
  - {role: economic_buyer, titles: [Practice Administrator],
     buying_triggers: [new referral coordinator posting], evidence_urls: []}
---

# Personas for GI groups

## Economic buyer
Text.
"""


class _Models:
    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = tuple(responses)

    def build(self, **kwargs: Any) -> ScriptedAgentChatModel:
        del kwargs
        return ScriptedAgentChatModel(responses=self._responses)


def _scripted() -> list[AIMessage]:
    """The model reads two inputs, searches for evidence, writes an ICP and a persona, finalizes.

    The ``exa_search_evidence`` call is load-bearing, not decoration: it is the only governed tool
    this role may spend, and it is the call that materializes a dynamic child under the recipe's
    interaction gate — the path where a pin provider that re-requested the gate's *statically*
    pinned ``audience-persona`` skill made every evidence call fail ``IncompatibleRecipe``
    (``conflicting_requirement``) and ended the turn ``runtime_error``. The turn without it was
    green throughout that outage. The toolbelt here carries no Exa credential, so the call is
    refused ``exa_not_configured`` before any spend; a refused governed call is the model's
    problem, never the turn's, so the turn must still finish and register both documents.
    """

    def call(name: str, args: dict[str, Any], index: int) -> dict[str, Any]:
        return {"name": name, "args": args, "id": f"c{index}", "type": "tool_call"}

    return [
        AIMessage(
            content="",
            tool_calls=[
                call(
                    "read_file",
                    {"file_path": "inputs/brand/knowledge/company/overview.md"},
                    1,
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                call(
                    "read_file",
                    {"file_path": "inputs/brand/knowledge/product/catalog.md"},
                    2,
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                call(
                    "exa_search_evidence",
                    {
                        "query": "how practice administrators describe referral fax backlog pain",
                        "num_results": 4,
                    },
                    3,
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                call(
                    "write_file",
                    {"file_path": "outputs/audience/icp-gi-groups.md", "content": ICP},
                    4,
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                call(
                    "write_file",
                    {"file_path": "outputs/audience/persona-gi-groups.md", "content": PERSONA},
                    5,
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                call(
                    "finalize_turn",
                    {
                        "status": "completed",
                        "user_message": "Wrote icp-gi-groups and persona-gi-groups.",
                    },
                    6,
                )
            ],
        ),
    ]


def test_a_synthesis_turn_materializes_inputs_and_registers_its_outputs_as_documents(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = "ws-o4-synth"
            project = await seed_project(conn, ws, name="seed")
            await seed_principal(conn, workspace_id=ws, user_id="usr_o4")
            brand_id = project.brand_id
            # Two ready input documents, written the way O3 writes them (artifact + row).
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            )
            for path, kind, folder, body in (
                (
                    "company/overview.md",
                    "company-overview",
                    "company",
                    "---\nkind: company-overview\n---\n\n# Company overview\n",
                ),
                (
                    "product/catalog.md",
                    "product-catalog",
                    "product",
                    "---\nkind: product-catalog\nproducts:\n"
                    "  - {name: Aura, product_id: prd_aura}\n---\n\n# Catalog\n",
                ),
            ):
                ref = await artifacts.persist_body(
                    workspace_id=ws,
                    data=body.encode(),
                    media_type="text/markdown",
                )
                await conn.execute(
                    text(
                        "INSERT INTO brand_knowledge_document (document_id, workspace_id, "
                        "brand_id, folder, path, kind, version, status, artifact_key, "
                        "artifact_sha256) VALUES (gen_random_uuid(), :ws, :brand, :folder, "
                        ":path, :kind, 1, 'ready', :key, :sha)"
                    ),
                    {
                        "ws": ws,
                        "brand": brand_id,
                        "folder": folder,
                        "path": path,
                        "kind": kind,
                        "key": ref.artifact_key,
                        "sha": ref.sha256,
                    },
                )

            launcher = await OnboardingSynthesisLauncher.for_tests(
                conn=conn,
                storage=storage,
                models=_Models(_scripted()),
                workspace_root=tmp_path / "ws",
            )
            result = await launcher.launch(
                workspace_id=ws,
                brand_id=brand_id,
                run_id=uuid4(),
                step_id=uuid4(),
            )
            assert result.status == "completed", (result.failure_code, result.failure_message)
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT path, kind, status, produced_by_turn_id IS NOT NULL AS by_turn "
                            "FROM brand_knowledge_document "
                            "WHERE workspace_id = :ws AND folder = 'audience' ORDER BY path"
                        ),
                        {"ws": ws},
                    )
                )
                .mappings()
                .all()
            )
            assert [(r["path"], r["kind"], r["status"], r["by_turn"]) for r in rows] == [
                ("audience/icp-gi-groups.md", "icp-definition", "proposed", True),
                ("audience/persona-gi-groups.md", "audience-persona", "ready", True),
            ]
            assert len(result.documents) == 2
            project_row = (
                (
                    await conn.execute(
                        text("SELECT name, status FROM project WHERE project_id = :p"),
                        {
                            "p": await ensure_onboarding_project(
                                conn,
                                workspace_id=ws,
                                brand_id=brand_id,
                                brand_name="seed brand",
                            )
                        },
                    )
                )
                .mappings()
                .one()
            )
            assert project_row["name"].startswith("Onboarding ·")
            assert project_row["status"] == "archived"

            # A re-synthesis on the same brand writes version 2 of each path, names the version it
            # replaces, and retires that version. Walking `supersedes_document_id` backwards has to
            # land on a row that really is `superseded`.
            second = await launcher.launch(
                workspace_id=ws,
                brand_id=brand_id,
                run_id=uuid4(),
                step_id=uuid4(),
            )
            assert second.status == "completed", (second.failure_code, second.failure_message)
            chain = (
                (
                    await conn.execute(
                        text(
                            "SELECT path, version, status, document_id, supersedes_document_id "
                            "FROM brand_knowledge_document "
                            "WHERE workspace_id = :ws AND folder = 'audience' "
                            "ORDER BY path, version"
                        ),
                        {"ws": ws},
                    )
                )
                .mappings()
                .all()
            )
            by_path: dict[str, dict[int, Any]] = {}
            for row in chain:
                by_path.setdefault(row["path"], {})[row["version"]] = row
            assert set(by_path) == {
                "audience/icp-gi-groups.md",
                "audience/persona-gi-groups.md",
            }
            for path, versions in by_path.items():
                assert set(versions) == {1, 2}, path
                assert versions[1]["status"] == "superseded", path
                assert versions[1]["supersedes_document_id"] is None, path
                assert versions[2]["supersedes_document_id"] == versions[1]["document_id"], path

    run_async(scenario())
