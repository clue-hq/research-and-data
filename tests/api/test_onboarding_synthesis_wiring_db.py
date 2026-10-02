"""The split synthesis run end to end on a scripted model: one ICP turn, then one persona turn.

The documents each turn needs ride the **opening context** (L5 focus) as their own markdown, and
the same bytes are seeded under ``inputs/brand/knowledge/`` so the model can cite them by path.
Both claims are asserted from durable state — the context receipt rows and the turn's own trusted
artifacts — never by reading the messages we handed the model.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentRole, ScriptedAgentChatModel
from clue_api.agent_registry_wiring import ONBOARDING_ICP_SURFACE
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.onboarding_synthesis_wiring import (
    EXECUTION_NAMESPACE_KEY,
    SYNTHESIS_CARD_MEDIA_TYPE,
    TURN_NAMESPACE,
    OnboardingSynthesisLauncher,
    RegisteredIcp,
    ensure_onboarding_project,
)
from clue_core import operation_id_from_key
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

WS = "ws-o4-synth"
TURN_INPUT_MEDIA_TYPE = "application/vnd.clue.agent-turn-input+json"

OVERVIEW = "---\nkind: company-overview\n---\n\n# Company overview\n"
CATALOG = (
    "---\nkind: product-catalog\nproducts:\n"
    "  - {name: Aura, product_id: prd_aura}\n"
    "  - {name: Other, product_id: prd_other}\n---\n\n# Catalog\n"
)
AURA_RESEARCH = "---\nkind: product-research\nproduct_id: prd_aura\n---\n\n# Aura\n"
OTHER_RESEARCH = "---\nkind: product-research\nproduct_id: prd_other\n---\n\n# Other\n"

#: The seeded knowledge documents, in the shape O3 writes them: (path, kind, folder, body).
_SEED_DOCUMENTS = (
    ("company/overview.md", "company-overview", "company", OVERVIEW),
    ("product/catalog.md", "product-catalog", "product", CATALOG),
    ("product/aura.md", "product-research", "product", AURA_RESEARCH),
    ("product/other.md", "product-research", "product", OTHER_RESEARCH),
)


def _icp(version: int) -> str:
    return f"""---
kind: icp-definition
icp_key: gi-groups
version: {version}
status: proposed
product_ids: [prd_aura]
hard_gates:
  - {{key: specialty, rule: gastroenterology practices, test: NPI taxonomy}}
exclusions: []
persona_map:
  economic_buyer: {{titles: [Practice Administrator]}}
  user: {{titles: [Gastroenterologist]}}
qualifier_fields: []
---

# GI groups

Body (inputs/brand/knowledge/company/overview.md).
"""


def _persona(icp_version: int) -> str:
    return f"""---
kind: audience-persona
icp_key: gi-groups
icp_version: {icp_version}
personas:
  - {{role: economic_buyer, titles: [Practice Administrator],
     buying_triggers: [new referral coordinator posting], evidence_urls: []}}
---

# Personas for GI groups

## Economic buyer
Text.
"""


class _Models:
    """Hand out one scripted response list per turn.

    ``build`` is called once per turn, and this lane now runs several turns against one launcher,
    so a single shared script would have every turn replay the first turn's moves.
    """

    def __init__(self, *scripts: list[AIMessage]) -> None:
        self._scripts: deque[list[AIMessage]] = deque(scripts)

    def build(self, **kwargs: Any) -> ScriptedAgentChatModel:
        del kwargs
        if not self._scripts:
            raise AssertionError("a turn was run that the test did not script")
        return ScriptedAgentChatModel(responses=self._scripts.popleft())


def _call(name: str, args: dict[str, Any], index: int) -> dict[str, Any]:
    return {"name": name, "args": args, "id": f"c{index}", "type": "tool_call"}


def _icp_script(version: int, *, content: str | None = None) -> list[AIMessage]:
    """The ICP turn writes the profile and finalizes. It reads nothing.

    Reading nothing is the point of the assertion that follows it: if the turn still knows the
    company overview and the product catalog, they reached the model through the opening context,
    which is the whole change this lane makes. ``content`` replaces the profile's text.
    """

    return [
        AIMessage(
            content="",
            tool_calls=[
                _call(
                    "write_file",
                    {
                        "file_path": "outputs/audience/icp-gi-groups.md",
                        "content": _icp(version) if content is None else content,
                    },
                    1,
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                _call(
                    "finalize_turn",
                    {"status": "completed", "user_message": "Wrote icp-gi-groups."},
                    2,
                )
            ],
        ),
    ]


def _persona_script(icp_version: int) -> list[AIMessage]:
    """The persona turn writes its document and finalizes.

    **It deliberately does not call ``exa_search_evidence``, and that is a loss.** The predecessor
    of this test scripted that call on purpose: it is the only governed tool this role may spend,
    and it is the call that materializes a dynamic child beneath the recipe's interaction gate —
    the regression guard for the pin provider that re-requested the gate's *statically* pinned
    skill and made every evidence call fail ``IncompatibleRecipe``.

    Scripting it here hangs the process, and the hang is **not** this lane's: it reproduces
    unchanged on this branch's base commit (``50afb9c67``) with the pre-split launcher and the
    pre-split test, which also never terminates. With no ``CLUE_EXA_API_KEY`` the tool refuses
    ``exa_not_configured``; the refusal is handed back to the model as a tool result (not a node
    failure), so the dynamic child beneath the gate stays incomplete, and the launcher's
    post-turn ``RecipeExecutor.execute`` drive then spins its ``while True`` forever — status
    stays ``running``, no node is ``failed``, nothing is ``ready``, and it appends ``GATE_OPENED``
    on every pass. Measured: with the evidence call the whole scenario never finishes (>30 min,
    no output); without it, the same four turns and every assertion below finish in ~2 s.

    So the evidence path is uncovered here until that engine defect is owned. The surface claim
    the split actually makes — the ICP turn cannot spend the tool, the persona turn can — is
    asserted structurally below instead, from the two resolved profiles and the ICP execution's
    (empty) plan operations.
    """

    return [
        AIMessage(
            content="",
            tool_calls=[
                _call(
                    "write_file",
                    {
                        "file_path": "outputs/audience/persona-gi-groups.md",
                        "content": _persona(icp_version),
                    },
                    2,
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                _call(
                    "finalize_turn",
                    {"status": "completed", "user_message": "Wrote persona-gi-groups."},
                    3,
                )
            ],
        ),
    ]


async def _seed_inputs(
    conn: AsyncConnection,
    *,
    storage: _MemoryStorage,
    brand_id: str,
) -> None:
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
    for path, kind, folder, body in _SEED_DOCUMENTS:
        ref = await artifacts.persist_body(
            workspace_id=WS,
            data=body.encode(),
            media_type="text/markdown",
        )
        await conn.execute(
            text(
                "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, "
                "folder, path, kind, version, status, artifact_key, artifact_sha256) "
                "VALUES (gen_random_uuid(), :ws, :brand, :folder, :path, :kind, 1, 'ready', "
                ":key, :sha)"
            ),
            {
                "ws": WS,
                "brand": brand_id,
                "folder": folder,
                "path": path,
                "kind": kind,
                "key": ref.artifact_key,
                "sha": ref.sha256,
            },
        )


def _turn_id(run_id: UUID, task: str) -> UUID:
    return uuid5(TURN_NAMESPACE, f"{run_id}:{task}")


def _execution_id(run_id: UUID, task: str) -> UUID:
    return operation_id_from_key(f"{run_id}:{task}", EXECUTION_NAMESPACE_KEY)


async def _focus_receipts(conn: AsyncConnection, turn_id: UUID) -> list[dict[str, Any]]:
    """The durable L5 receipt rows for one turn — what the assembler actually put in context."""

    rows = (
        (
            await conn.execute(
                text(
                    "SELECT r.disposition, r.object_type, r.object_id, r.object_version, "
                    "  r.materialized_path "
                    "FROM agent_context_ref r "
                    "JOIN agent_context_layer l ON l.context_bundle_id = r.context_bundle_id "
                    "  AND l.ordinal = r.layer_ordinal "
                    "JOIN agent_context_bundle b ON b.id = r.context_bundle_id "
                    "WHERE b.turn_id = :turn AND l.layer = 'l5_focus' "
                    "ORDER BY r.ordinal"
                ),
                {"turn": turn_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def _payloads(
    conn: AsyncConnection,
    *,
    storage: _MemoryStorage,
    media_type: str,
) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            text("SELECT storage_key FROM artifact WHERE workspace_id = :ws AND media_type = :mt"),
            {"ws": WS, "mt": media_type},
        )
    ).all()
    return [json.loads(storage.blobs[row[0]]) for row in rows]


async def _spent_addresses(conn: AsyncConnection, execution_id: UUID) -> set[str]:
    """Every governed tool address this execution actually compiled a plan node for."""

    rows = (
        await conn.execute(
            text(
                "SELECT o.address FROM agent_plan_operation o "
                "JOIN agent_plan p ON p.id = o.plan_id "
                "WHERE p.execution_id = :execution"
            ),
            {"execution": execution_id},
        )
    ).all()
    return {str(row[0]) for row in rows}


async def _document_rows(conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT path, kind, version, status, document_id, supersedes_document_id, "
                    "  produced_by_turn_id, source_icp_document_id, source_icp_sha256 "
                    "FROM brand_knowledge_document "
                    "WHERE workspace_id = :ws AND folder = 'audience' "
                    "ORDER BY path, version"
                ),
                {"ws": WS},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def test_the_split_run_writes_an_icp_then_its_persona_and_a_re_run_refines_it(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WS, name="seed")
            await seed_principal(conn, workspace_id=WS, user_id="usr_o4")
            brand_id = project.brand_id
            storage = _MemoryStorage()
            await _seed_inputs(conn, storage=storage, brand_id=brand_id)

            launcher = await OnboardingSynthesisLauncher.for_tests(
                conn=conn,
                storage=storage,
                models=_Models(
                    _icp_script(1),
                    _persona_script(1),
                    _icp_script(2),
                    _persona_script(2),
                ),
                workspace_root=tmp_path / "ws",
            )

            # The ICP turn is structurally unable to search: its surface withholds the one tool
            # this role may spend, so the rule is enforced by absence, not by prose. The persona
            # turns resolve the role unnarrowed and keep it.
            profiles = launcher._components.profiles
            assert [
                pin.address
                for pin in profiles.resolve(
                    AgentRole.ONBOARDING_SYNTHESIS, surface=ONBOARDING_ICP_SURFACE
                ).profile.tools
            ] == []
            assert [
                pin.address
                for pin in profiles.resolve(AgentRole.ONBOARDING_SYNTHESIS).profile.tools
            ] == ["exa_search_evidence@1"]

            # --- the ICP turn ------------------------------------------------------------------
            first_run = uuid4()
            icps = await launcher.launch_icps(
                workspace_id=WS,
                brand_id=brand_id,
                run_id=first_run,
                step_id=uuid4(),
            )
            assert icps.status == "completed", (icps.failure_code, icps.failure_message)
            registered = icps.icps
            assert len(registered) == 1
            assert (registered[0].icp_key, registered[0].version, registered[0].path) == (
                "gi-groups",
                1,
                "audience/icp-gi-groups.md",
            )

            # The ICP row exists, proposed, BEFORE any persona turn has run.
            rows = await _document_rows(conn)
            assert [(row["path"], row["kind"], row["status"]) for row in rows] == [
                ("audience/icp-gi-groups.md", "icp-definition", "proposed")
            ]
            assert rows[0]["document_id"] == registered[0].document_id
            assert rows[0]["produced_by_turn_id"] == _turn_id(first_run, "icp")

            # The overview and the catalog reached the model as CONTEXT, not as a path it had to
            # go and read: the turn's script never called read_file.
            receipts = await _focus_receipts(conn, _turn_id(first_run, "icp"))
            assert len(receipts) == 2
            assert {row["disposition"] for row in receipts} == {"included"}
            assert {row["object_type"] for row in receipts} == {"brand_knowledge_document"}
            assert all(
                str(row["materialized_path"]).startswith("context/focus/") for row in receipts
            )
            # Product research is deliberately NOT in context — it is seeded on disk instead.
            icp_card = next(
                card
                for card in await _payloads(
                    conn, storage=storage, media_type=SYNTHESIS_CARD_MEDIA_TYPE
                )
                if card["task"] == "icp" and card["icp"] is None
            )
            assert icp_card["context_paths"] == [
                "inputs/brand/knowledge/company/overview.md",
                "inputs/brand/knowledge/product/catalog.md",
            ]
            assert icp_card["seeded_paths"] == [
                "inputs/brand/knowledge/company/overview.md",
                "inputs/brand/knowledge/product/catalog.md",
                "inputs/brand/knowledge/product/aura.md",
                "inputs/brand/knowledge/product/other.md",
            ]
            assert icp_card["schema_version"] == "2"
            # No profiles on file yet, so the instruction names none.
            objectives = {
                payload["objective"]
                for payload in await _payloads(
                    conn, storage=storage, media_type=TURN_INPUT_MEDIA_TYPE
                )
            }
            assert "Task: icp. Write the ICP documents, then finalize_turn." in objectives
            # The withheld tool was never even a plan node on the ICP execution.
            assert await _spent_addresses(conn, _execution_id(first_run, "icp")) == set()

            # --- the persona turn --------------------------------------------------------------
            persona = await launcher.launch_persona(
                workspace_id=WS,
                brand_id=brand_id,
                run_id=first_run,
                step_id=uuid4(),
                icp=registered[0],
            )
            assert persona.status == "completed", (persona.failure_code, persona.failure_message)
            assert len(persona.documents) == 1
            rows = await _document_rows(conn)
            assert [(row["path"], row["kind"], row["status"]) for row in rows] == [
                ("audience/icp-gi-groups.md", "icp-definition", "proposed"),
                ("audience/persona-gi-groups.md", "audience-persona", "ready"),
            ]
            assert rows[1]["source_icp_document_id"] == registered[0].document_id
            assert len(rows[1]["source_icp_sha256"]) == 64

            persona_card = next(
                card
                for card in await _payloads(
                    conn, storage=storage, media_type=SYNTHESIS_CARD_MEDIA_TYPE
                )
                if card["task"] == "persona"
            )
            assert persona_card["icp"] == {
                "key": "gi-groups",
                "document_id": str(registered[0].document_id),
                "version": 1,
            }
            # The ICP names prd_aura only, so only Aura's research is on this turn's disk.
            assert "inputs/brand/knowledge/product/aura.md" in persona_card["seeded_paths"]
            assert "inputs/brand/knowledge/product/other.md" not in persona_card["seeded_paths"]
            # The one ICP it writes about is in its context; the other documents are the core.
            assert persona_card["context_paths"] == [
                "inputs/brand/knowledge/company/overview.md",
                "inputs/brand/knowledge/product/catalog.md",
                "inputs/brand/knowledge/audience/icp-gi-groups.md",
            ]
            objectives = {
                payload["objective"]
                for payload in await _payloads(
                    conn, storage=storage, media_type=TURN_INPUT_MEDIA_TYPE
                )
            }
            assert (
                "Task: persona:gi-groups. The ICP is "
                "inputs/brand/knowledge/audience/icp-gi-groups.md, version 1. "
                "Write outputs/audience/persona-gi-groups.md, then finalize_turn."
            ) in objectives
            # Neither turn compiled a governed plan operation here, because neither script calls
            # the evidence tool (see `_persona_script`). For the ICP turn that is the durable
            # half of the surface claim: the tool it may not spend never became a plan node.
            assert await _spent_addresses(conn, _execution_id(first_run, "persona:gi-groups")) == (
                set()
            )

            # --- a re-run refines the profile it finds on file ---------------------------------
            second_run = uuid4()
            again = await launcher.launch_icps(
                workspace_id=WS,
                brand_id=brand_id,
                run_id=second_run,
                step_id=uuid4(),
            )
            assert again.status == "completed", (again.failure_code, again.failure_message)
            assert again.icps[0].version == 2
            # The ICP already on file is in the second run's context, and named in its instruction.
            receipts = await _focus_receipts(conn, _turn_id(second_run, "icp"))
            assert len(receipts) == 3
            assert str(registered[0].document_id) in {str(row["object_id"]) for row in receipts}
            objectives = {
                payload["objective"]
                for payload in await _payloads(
                    conn, storage=storage, media_type=TURN_INPUT_MEDIA_TYPE
                )
            }
            assert (
                "Task: icp. Write the ICP documents, then finalize_turn. ICPs already on file: "
                "gi-groups (inputs/brand/knowledge/audience/icp-gi-groups.md, version 1)."
            ) in objectives

            versions = {
                (row["path"], row["version"]): row
                for row in await _document_rows(conn)
                if row["path"] == "audience/icp-gi-groups.md"
            }
            assert versions[("audience/icp-gi-groups.md", 1)]["status"] == "superseded"
            assert versions[("audience/icp-gi-groups.md", 2)]["supersedes_document_id"] == (
                registered[0].document_id
            )

            second_persona = await launcher.launch_persona(
                workspace_id=WS,
                brand_id=brand_id,
                run_id=second_run,
                step_id=uuid4(),
                icp=again.icps[0],
            )
            assert second_persona.status == "completed", (
                second_persona.failure_code,
                second_persona.failure_message,
            )
            objectives = {
                payload["objective"]
                for payload in await _payloads(
                    conn, storage=storage, media_type=TURN_INPUT_MEDIA_TYPE
                )
            }
            assert (
                "Task: persona:gi-groups. The ICP is "
                "inputs/brand/knowledge/audience/icp-gi-groups.md, version 2. "
                "Write outputs/audience/persona-gi-groups.md, then finalize_turn."
            ) in objectives
            personas = [
                row for row in await _document_rows(conn) if row["kind"] == "audience-persona"
            ]
            assert [row["version"] for row in personas] == [1, 2]

            # The per-brand system project both turns are scoped to is still a scope anchor.
            project_row = (
                (
                    await conn.execute(
                        text("SELECT name, status FROM project WHERE project_id = :p"),
                        {
                            "p": await ensure_onboarding_project(
                                conn,
                                workspace_id=WS,
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

    run_async(scenario())


def test_a_persona_turn_whose_icp_document_is_gone_fails_without_raising(tmp_path: Path) -> None:
    """The failure law: a missing input is a typed step outcome, never an exception."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WS, name="seed")
            await seed_principal(conn, workspace_id=WS, user_id="usr_o4")
            storage = _MemoryStorage()
            await _seed_inputs(conn, storage=storage, brand_id=project.brand_id)

            launcher = await OnboardingSynthesisLauncher.for_tests(
                conn=conn,
                storage=storage,
                models=_Models(),
                workspace_root=tmp_path / "ws",
            )
            result = await launcher.launch_persona(
                workspace_id=WS,
                brand_id=project.brand_id,
                run_id=uuid4(),
                step_id=uuid4(),
                icp=RegisteredIcp(
                    document_id=uuid4(),
                    icp_key="never-registered",
                    version=1,
                    path="audience/icp-never-registered.md",
                ),
            )

            assert result.status == "failed"
            assert result.failure_code == "icp_document_missing"
            assert result.documents == ()

    run_async(scenario())


def test_an_icp_whose_gate_a_comma_split_is_not_registered(tmp_path: Path) -> None:
    """An inline gate whose rule carried a comma loses the rest of the rule to value-less keys.

    Registering it would store the first fragment as the whole rule, so the output is skipped the
    way an unreadable one is — and with it the only ICP, so the turn honestly wrote none.
    """

    comma_split = _icp(1).replace(
        "  - {key: specialty, rule: gastroenterology practices, test: NPI taxonomy}\n",
        "  - {key: specialty, rule: gastroenterology practices, with endoscopy suites, "
        "test: NPI taxonomy}\n",
    )
    assert "with endoscopy suites" in comma_split

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WS, name="seed")
            await seed_principal(conn, workspace_id=WS, user_id="usr_o4")
            storage = _MemoryStorage()
            await _seed_inputs(conn, storage=storage, brand_id=project.brand_id)

            launcher = await OnboardingSynthesisLauncher.for_tests(
                conn=conn,
                storage=storage,
                models=_Models(_icp_script(1, content=comma_split)),
                workspace_root=tmp_path / "ws",
            )
            icps = await launcher.launch_icps(
                workspace_id=WS,
                brand_id=project.brand_id,
                run_id=uuid4(),
                step_id=uuid4(),
            )

            assert icps.status == "empty"
            assert icps.icps == ()
            assert await _document_rows(conn) == []

    run_async(scenario())


def test_a_re_synthesis_retires_the_draft_it_replaces_but_never_a_confirmation(
    tmp_path: Path,
) -> None:
    """Founder rulings 2026-09-10: re-synthesis must never retire a ``confirmed`` row.

    A confirmed version is a human's yes and some project's pinned ICP. Onboarding keeps refining
    profiles in the background; if a refinement superseded the confirmation, the project's pinned
    document would stop being servable and its launches would refuse — a background process
    revoking an approval nobody withdrew. So the new version supersedes only ``ready``/``proposed``
    drafts, and the confirmation stays confirmed beside it until a human approves the new one.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WS, name="seed")
            await seed_principal(conn, workspace_id=WS, user_id="usr_o4")
            brand_id = project.brand_id
            storage = _MemoryStorage()
            await _seed_inputs(conn, storage=storage, brand_id=brand_id)

            launcher = await OnboardingSynthesisLauncher.for_tests(
                conn=conn,
                storage=storage,
                models=_Models(_icp_script(1), _icp_script(2), _icp_script(3)),
                workspace_root=tmp_path / "ws",
            )

            first = await launcher.launch_icps(
                workspace_id=WS, brand_id=brand_id, run_id=uuid4(), step_id=uuid4()
            )
            assert first.status == "completed", (first.failure_code, first.failure_message)
            confirmed_id = first.icps[0].document_id
            # A human approves v1 at the gate and their project pins it.
            await conn.execute(
                text(
                    "UPDATE brand_knowledge_document SET status = 'confirmed' "
                    "WHERE document_id = :id"
                ),
                {"id": confirmed_id},
            )

            second = await launcher.launch_icps(
                workspace_id=WS, brand_id=brand_id, run_id=uuid4(), step_id=uuid4()
            )
            assert second.status == "completed", (second.failure_code, second.failure_message)
            rows = {row["version"]: row for row in await _document_rows(conn)}
            assert rows[1]["status"] == "confirmed"
            assert rows[2]["status"] == "proposed"
            assert rows[2]["supersedes_document_id"] == confirmed_id

            # A third refinement retires the *draft* it replaces, and still leaves v1 alone.
            third = await launcher.launch_icps(
                workspace_id=WS, brand_id=brand_id, run_id=uuid4(), step_id=uuid4()
            )
            assert third.status == "completed", (third.failure_code, third.failure_message)
            rows = {row["version"]: row for row in await _document_rows(conn)}
            assert rows[1]["status"] == "confirmed"
            assert rows[2]["status"] == "superseded"
            assert rows[3]["status"] == "proposed"

    run_async(scenario())


PROJECT_ICP = """---
kind: icp-definition
icp_key: gi-groups-dac
version: 1
status: proposed
product_ids: [prd_aura]
persona_map:
  economic_buyer: {titles: [Practice Administrator]}
qualifier_fields: []
---

# GI groups, direct-to-employer

Body (inputs/brand/knowledge/company/overview.md).
"""

PROJECT_PERSONA = """---
kind: audience-persona
icp_key: gi-groups-dac
icp_version: 1
personas:
  - {role: economic_buyer, titles: [Benefits Director],
     buying_triggers: [self-funded plan renewal], evidence_urls: []}
---

# Personas for GI groups, direct-to-employer

## Economic buyer
Text.
"""


def _project_persona_script() -> list[AIMessage]:
    return [
        AIMessage(
            content="",
            tool_calls=[
                _call(
                    "write_file",
                    {
                        "file_path": "outputs/audience/persona-gi-groups-dac.md",
                        "content": PROJECT_PERSONA,
                    },
                    1,
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                _call(
                    "finalize_turn",
                    {"status": "completed", "user_message": "Wrote persona-gi-groups-dac."},
                    2,
                )
            ],
        ),
    ]


async def _seed_project_icp(
    conn: AsyncConnection,
    *,
    storage: _MemoryStorage,
    brand_id: str,
    project_id: str,
) -> UUID:
    """One project-local ICP variant, the shape ``author_icp_document`` writes for a project."""

    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
    ref = await artifacts.persist_body(
        workspace_id=WS, data=PROJECT_ICP.encode(), media_type="text/markdown"
    )
    document_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, "
            "project_id, folder, path, kind, version, status, artifact_key, artifact_sha256) "
            "VALUES (:id, :ws, :brand, :project, 'audience', :path, 'icp-definition', 1, "
            "'proposed', :key, :sha)"
        ),
        {
            "id": document_id,
            "ws": WS,
            "brand": brand_id,
            "project": project_id,
            "path": "audience/icp-gi-groups-dac.md",
            "key": ref.artifact_key,
            "sha": ref.sha256,
        },
    )
    return document_id


def test_a_persona_turn_for_a_project_local_icp_reads_and_writes_in_that_scope(
    tmp_path: Path,
) -> None:
    """A project's own ICP is not the brand's, on both sides of the turn.

    The brand-level reader cannot see it, so a persona turn that only read the brand's documents
    would fail ``icp_document_missing`` on the very document it was asked to write about. The
    turn's inputs are therefore the brand's knowledge **union** the ICP's own project's documents,
    and the persona it writes lands in that same project's scope rather than in the brand's.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WS, name="seed")
            await seed_principal(conn, workspace_id=WS, user_id="usr_o4")
            brand_id = project.brand_id
            storage = _MemoryStorage()
            await _seed_inputs(conn, storage=storage, brand_id=brand_id)
            variant = await _seed_project_icp(
                conn, storage=storage, brand_id=brand_id, project_id=project.project_id
            )

            launcher = await OnboardingSynthesisLauncher.for_tests(
                conn=conn,
                storage=storage,
                models=_Models(_project_persona_script()),
                workspace_root=tmp_path / "ws",
            )
            run_id = uuid4()
            result = await launcher.launch_persona(
                workspace_id=WS,
                brand_id=brand_id,
                run_id=run_id,
                step_id=uuid4(),
                icp=RegisteredIcp(
                    document_id=variant,
                    icp_key="gi-groups-dac",
                    version=1,
                    path="audience/icp-gi-groups-dac.md",
                    project_id=project.project_id,
                ),
            )

            assert result.status == "completed", (result.failure_code, result.failure_message)
            # The variant was selected as the turn's one ICP, by document id.
            card = next(
                card
                for card in await _payloads(
                    conn, storage=storage, media_type=SYNTHESIS_CARD_MEDIA_TYPE
                )
                if card["task"] == "persona"
            )
            assert card["icp"] == {
                "key": "gi-groups-dac",
                "document_id": str(variant),
                "version": 1,
            }
            assert "inputs/brand/knowledge/audience/icp-gi-groups-dac.md" in card["context_paths"]
            # And the persona it wrote is the project's, beside the brand's own knowledge.
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT path, kind, status, project_id FROM brand_knowledge_document "
                            "WHERE workspace_id = :ws AND folder = 'audience' ORDER BY path"
                        ),
                        {"ws": WS},
                    )
                )
                .mappings()
                .all()
            )
            assert [(row["path"], row["project_id"]) for row in rows] == [
                ("audience/icp-gi-groups-dac.md", project.project_id),
                ("audience/persona-gi-groups-dac.md", project.project_id),
            ]
            assert rows[1]["kind"] == "audience-persona" and rows[1]["status"] == "ready"

    run_async(scenario())
