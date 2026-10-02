"""What a design leg may read from the platform mid-turn, against the real rows it answers from.

Three properties are load-bearing here and none of them can be asserted from an in-memory double:

* **The reads are the governed reads.** ``read_project_accounts`` / ``read_account_research@2`` /
  ``read_claims`` go through the shared journaled ``ToolInvoker``, so a design turn's reads leave
  the same receipts head-of-abm's do — and each call is its own logical operation, so A9 never
  replays page one as the answer to page two.
* **The scope is the leg's project.** A design turn never names a workspace or a project of its
  own; both come from the envelope the platform minted.
* **The seller is the OPENING turn's pinned set.** Not "whatever the brand knows now": the leg is
  a delegation of one head-of-abm turn, and it must argue from the documents that turn argued
  from, at the versions that turn pinned.

A direct editor turn — no ``leg`` block — gets no reads at all.
"""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally function arguments

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.icp_confirmation import ConfirmedIcp, pin_project_icp
from clue_api.arv2.read_tools import (
    DbArv2ReadService,
    build_arv2_paged_read_tools,
    build_arv2_read_tools,
)
from clue_api.brand_knowledge_context import load_or_create_knowledge_pin
from clue_api.execution_wiring import build_tool_invoker
from clue_config import load_settings
from clue_design.envelopes import DesignTurnEnvelope
from clue_design.runs import work_id_for_run
from clue_research.identity import insert_account_entity
from clue_research.membership import ensure_project_account
from clue_spine import confirm_project_product_set, create_product
from clue_storage import FsStorage
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.test_brand_knowledge_context_db import _seed_document, _submitted_turn
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

ACCOUNT_NAME = "Premier Gastroenterology"
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

OVERVIEW = "---\nkind: company-overview\n---\n\n# Acme\n\nScheduling software for GI clinics.\n"
CATALOG = "---\nkind: product-catalog\n---\n\n# Catalog\n\nTwo products: Aura and Beta.\n"
ICP = (
    "---\nkind: icp-definition\nicp_key: x\nstatus: confirmed\n"
    "product_ids: [prd_aura]\nproduct_selection_version: 1\n---\n\n"
    "# ICP x\n\nIndependent GI groups with three to twelve physicians.\n"
)


def _leg_envelope(
    workspace_id: str,
    project_id: str | None,
    opening_turn: UUID | None,
    *,
    leg: bool = True,
) -> DesignTurnEnvelope:
    run_id = f"run_{uuid4().hex}"
    config: dict[str, Any] = {"request": {"prompt": "p", "scene": {}}}
    if leg:
        config["leg"] = {"leg_id": "leg-1"}
        config["delegation_bundle"] = {
            "brief": "b",
            **({} if opening_turn is None else {"opened_by_turn_id": str(opening_turn)}),
        }
    return DesignTurnEnvelope(
        kind="agent_turn",
        work_id=work_id_for_run(run_id),
        workspace_id=workspace_id,
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=None,
        project_id=project_id,
        config=config,
    )


async def _seed_overview_block(
    conn: AsyncConnection, *, workspace_id: str, account_id: Any
) -> None:
    """One live ``display_block`` for the account's overview page."""

    await conn.execute(
        text(
            "INSERT INTO display_block (workspace_id, subject_kind, subject_id, page, "
            "section_key, body_json, cited_claim_ids, model, prompt_version, recipe_version, "
            "generated_at) VALUES (:ws, 'account', :subject, 'overview', 'why-now', "
            "CAST(:body AS jsonb), CAST(:cited AS uuid[]), 'luna', 'v1+v1', 1, "
            "CAST(:now AS timestamptz))"
        ),
        {
            "ws": workspace_id,
            "subject": account_id,
            "body": json.dumps({"text": "They opened a second endoscopy suite."}),
            "cited": [],
            "now": NOW,
        },
    )


async def _seeded(
    conn: AsyncConnection, tmp_path: Path, *, label: str, overview: bool = True
) -> dict[str, Any]:
    """Workspace + project + one account + the seller's brand knowledge, pinned to a real turn."""

    workspace_id = f"ws_dpr_{label}_{uuid4().hex[:8]}"
    project = await seed_project(conn, workspace_id, name=f"design reads {label}")
    principal = await seed_principal(
        conn, workspace_id=workspace_id, user_id=f"usr-dpr-{label}-{uuid4().hex[:6]}"
    )
    conn_factory = conn_session_factory(conn)
    storage = FsStorage(tmp_path / "artifacts")
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)

    account_id = await insert_account_entity(
        conn,
        canonical_name=ACCOUNT_NAME,
        primary_domain="premier-gi.example",
        workspace_id=workspace_id,
    )
    await ensure_project_account(
        conn,
        workspace_id=workspace_id,
        project_id=project.project_id,
        account_entity_id=account_id,
        added_via="manual",
    )
    if overview:
        await _seed_overview_block(conn, workspace_id=workspace_id, account_id=account_id)

    documents: dict[str, UUID] = {}
    for path, kind, body in (
        ("company/overview.md", "company-overview", OVERVIEW),
        ("product/catalog.md", "product-catalog", CATALOG),
        ("audience/icp-x.md", "icp-definition", ICP),
    ):
        documents[path] = await _seed_document(
            conn,
            artifacts=artifacts,
            workspace_id=workspace_id,
            brand_id=project.brand_id,
            path=path,
            kind=kind,
            version=1,
            status="ready",
            body=body,
        )

    products = [
        await create_product(conn, brand_id=project.brand_id, workspace_id=workspace_id, name=name)
        for name in ("Aura", "Beta")
    ]
    product_set = await confirm_project_product_set(
        conn,
        workspace_id=workspace_id,
        project_id=project.project_id,
        product_ids=[product.product_id for product in products],
        gate_id=uuid4(),
        confirmed_by_user_id=principal.user_id,
    )
    assert product_set is not None

    icp_row = (
        (
            await conn.execute(
                text(
                    "SELECT version, artifact_key, artifact_sha256 "
                    "FROM brand_knowledge_document WHERE document_id = :id"
                ),
                {"id": documents["audience/icp-x.md"]},
            )
        )
        .mappings()
        .one()
    )
    await pin_project_icp(
        conn,
        workspace_id=workspace_id,
        project_id=project.project_id,
        brand_id=project.brand_id,
        document=ConfirmedIcp(
            document_id=documents["audience/icp-x.md"],
            icp_key="x",
            version=int(icp_row["version"]),
            artifact_key=str(icp_row["artifact_key"]),
            artifact_sha256=str(icp_row["artifact_sha256"]),
            supersedes_document_id=documents["audience/icp-x.md"],
            product_selection_version=product_set.selection_version,
        ),
        product_selection_version=product_set.selection_version,
        pinned_by_user_id=principal.user_id,
    )

    opening_turn = await _submitted_turn(
        conn,
        artifacts=artifacts,
        workspace_id=workspace_id,
        project_id=project.project_id,
        brand_id=project.brand_id,
        label=f"{label}-{uuid4().hex[:6]}",
    )
    pin, _ = await load_or_create_knowledge_pin(
        conn,
        workspace_id=workspace_id,
        turn_id=opening_turn,
        brand_id=project.brand_id,
        project_id=project.project_id,
    )

    settings = load_settings(_env_file=None)
    registry = ToolRegistry()
    service = DbArv2ReadService(settings=settings, conn_factory=conn_factory)
    unaliased = {"read_account_research", "read_discovery_run"}
    for tool in build_arv2_read_tools(service):
        registry.register(tool, make_default=tool.descriptor.name not in unaliased)
    for tool in build_arv2_paged_read_tools(service):
        registry.register(tool, make_default=True)
    from clue_api.web_search_tool import WebSearchTool  # noqa: PLC0415
    from tests.api.test_web_search_tool import HIT, FakeExa, _result  # noqa: PLC0415

    fake_exa = FakeExa(_result(output_text="Acme's summit is in May.", hits=(HIT,)))
    # The offline double, injected through the constructor the production builder uses.
    search_tool = WebSearchTool(client_factory=lambda label, raw, ledger: fake_exa)
    registry.register(search_tool, make_default=True)
    invoker = build_tool_invoker(
        registry=registry,
        idempotency_store=DbIdempotencyStore(conn_factory=conn_factory),
        storage=FsStorage(tmp_path / "snapshots"),
        settings=settings,
        conn_factory=conn_factory,
    )
    return {
        "workspace_id": workspace_id,
        "project": project,
        "account_id": account_id,
        "conn_factory": conn_factory,
        "storage": storage,
        "invoker": invoker,
        "opening_turn": opening_turn,
        "pin": pin,
        "product_set": product_set,
        "fake_exa": fake_exa,
    }


def test_a_non_leg_envelope_gets_no_reads(tmp_path: Path, migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="nonleg")
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"],
                storage=seeds["storage"],
                conn_factory=seeds["conn_factory"],
            )
            envelope = _leg_envelope(
                seeds["workspace_id"],
                seeds["project"].project_id,
                seeds["opening_turn"],
                leg=False,
            )
            assert factory(envelope) is None

    run_async(scenario())


def test_the_three_reads_answer_for_the_legs_project_on_the_platform_loop(
    tmp_path: Path, migrated_db: bool
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="reads")
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"],
                storage=seeds["storage"],
                conn_factory=seeds["conn_factory"],
            )
            envelope = _leg_envelope(
                seeds["workspace_id"], seeds["project"].project_id, seeds["opening_turn"]
            )
            reads = await asyncio.to_thread(factory, envelope)
            assert reads is not None

            accounts = await asyncio.to_thread(reads.read_project_accounts, query="premier")
            assert accounts["total"] == 1
            assert accounts["accounts"][0]["name"] == ACCOUNT_NAME
            account_entity_id = accounts["accounts"][0]["account_entity_id"]

            research = await asyncio.to_thread(
                reads.read_account_research,
                account_entity_id=account_entity_id,
                section="overview",
            )
            assert research["account_name"] == ACCOUNT_NAME
            assert [section["section_key"] for section in research["overview"]] == ["why-now"]

            claims = await asyncio.to_thread(reads.read_claims, entity_id=account_entity_id)
            assert "claims" in claims and "prefixes" in claims

            # Every call was journaled as a governed invocation under this design turn, at the
            # version the design role is granted — and each is its own logical operation, so the
            # A9 store holds three rows rather than one replayed three times.
            rows = (
                await conn.execute(
                    text(
                        "SELECT tool_name FROM tool_invocation WHERE workspace_id = :ws "
                        "ORDER BY created_at"
                    ),
                    {"ws": seeds["workspace_id"]},
                )
            ).all()
            assert [str(row[0]) for row in rows] == [
                "read_project_accounts@1",
                "read_account_research@2",
                "read_claims@1",
            ]

    run_async(scenario())


def test_paging_a_read_is_never_answered_by_the_previous_pages_receipt(
    tmp_path: Path, migrated_db: bool
) -> None:
    """A9 idempotency must not make page two a replay of page one."""

    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="paging")
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"],
                storage=seeds["storage"],
                conn_factory=seeds["conn_factory"],
            )
            reads = await asyncio.to_thread(
                factory,
                _leg_envelope(
                    seeds["workspace_id"], seeds["project"].project_id, seeds["opening_turn"]
                ),
            )
            assert reads is not None
            first = await asyncio.to_thread(reads.read_project_accounts, limit=1, offset=0)
            second = await asyncio.to_thread(reads.read_project_accounts, limit=1, offset=0)
            assert first["accounts"] == second["accounts"]
            rows = (
                await conn.execute(
                    text("SELECT count(*) FROM tool_invocation WHERE workspace_id = :ws"),
                    {"ws": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert rows == 2

    run_async(scenario())


def test_a_leg_may_search_the_web_through_the_governed_tool(
    tmp_path: Path, migrated_db: bool
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="search")
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"],
                storage=seeds["storage"],
                conn_factory=seeds["conn_factory"],
            )
            reads = await asyncio.to_thread(
                factory,
                _leg_envelope(
                    seeds["workspace_id"], seeds["project"].project_id, seeds["opening_turn"]
                ),
            )
            assert reads is not None

            found = await asyncio.to_thread(
                reads.web_search, query="acme summit 2026", num_results=3
            )
            assert found["answer"] == "Acme's summit is in May."
            assert found["rendered"].startswith("Acme's summit is in May.")
            assert seeds["fake_exa"].calls[0]["type"] == "deep-lite"
            assert seeds["fake_exa"].calls[0]["num_results"] == 3

            second = await asyncio.to_thread(
                reads.web_search, query="acme summit 2026", num_results=3
            )
            assert second == found
            # Two calls, two operations, two journal rows — a search is never replayed from the
            # previous search's receipt (the same rule the paged reads follow).
            rows = (
                await conn.execute(
                    text(
                        "SELECT tool_name FROM tool_invocation WHERE workspace_id = :ws "
                        "ORDER BY created_at"
                    ),
                    {"ws": seeds["workspace_id"]},
                )
            ).all()
            assert [str(row[0]) for row in rows] == ["web_search@1", "web_search@1"]
            assert len(seeds["fake_exa"].calls) == 2

    run_async(scenario())


def test_a_governed_reads_refusal_reaches_the_design_side_with_its_reason_code(
    tmp_path: Path, migrated_db: bool
) -> None:
    """Ruling T2-1: an unwritten overview is an ANSWER the agent can act on, not a failure.

    ``read_account_research`` refuses this case by name (``overview_not_written``) through the
    toolbelt's typed precondition failure, and that name is what tells the design agent to read
    the claims instead. Collapsed into ``read_failed`` it would read as a broken platform.
    """

    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import (
        DesignPlatformReadError,
        build_design_platform_reads_factory,
    )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="refused", overview=False)
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"],
                storage=seeds["storage"],
                conn_factory=seeds["conn_factory"],
            )
            reads = await asyncio.to_thread(
                factory,
                _leg_envelope(
                    seeds["workspace_id"], seeds["project"].project_id, seeds["opening_turn"]
                ),
            )
            assert reads is not None
            with pytest.raises(DesignPlatformReadError, match="^refused:overview_not_written$"):
                await asyncio.to_thread(
                    reads.read_account_research,
                    account_entity_id=str(seeds["account_id"]),
                    section="overview",
                )
            # An account this workspace cannot see is refused by its own name too, and so is the
            # claims section of an account nothing has researched yet — three different sentences
            # the design agent can act on differently, all of which would have read "read_failed".
            with pytest.raises(DesignPlatformReadError, match="^refused:account_not_found$"):
                await asyncio.to_thread(
                    reads.read_account_research,
                    account_entity_id=str(uuid4()),
                    section="overview",
                )
            with pytest.raises(DesignPlatformReadError, match="^refused:account_not_researched$"):
                await asyncio.to_thread(
                    reads.read_account_research,
                    account_entity_id=str(seeds["account_id"]),
                    section="claims",
                )
            # ``read_claims`` over the same account is the read that answers honestly EMPTY rather
            # than refusing: a claims query that matches nothing is a true, useful sentence.
            empty = await asyncio.to_thread(reads.read_claims, entity_id=str(seeds["account_id"]))
            assert empty["claims"] == [] and empty["prefixes"] == {}

    run_async(scenario())


def test_seller_knowledge_is_the_opening_turns_pinned_set_plus_the_product_set(
    tmp_path: Path, migrated_db: bool
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="seller")
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"],
                storage=seeds["storage"],
                conn_factory=seeds["conn_factory"],
            )
            reads = await asyncio.to_thread(
                factory,
                _leg_envelope(
                    seeds["workspace_id"], seeds["project"].project_id, seeds["opening_turn"]
                ),
            )
            assert reads is not None
            seller = await asyncio.to_thread(reads.seller_knowledge)

            assert seller.documents_sha256 == seeds["pin"].documents_sha256
            assert {document.path for document in seller.documents} == {
                "company/overview.md",
                "product/catalog.md",
                "audience/icp-x.md",
            }
            # Front matter split off, markdown kept.
            assert all(document.body_text.startswith("#") for document in seller.documents)
            assert {document.kind for document in seller.documents} == {
                "company-overview",
                "product-catalog",
                "icp-definition",
            }
            assert all(document.version == 1 for document in seller.documents)
            assert all(document.status == "ready" for document in seller.documents)
            assert seller.confirmed_icp_path == "audience/icp-x.md"
            assert seller.product_set == {
                "selection_version": seeds["product_set"].selection_version,
                "product_ids": list(seeds["product_set"].product_ids),
            }

    run_async(scenario())


def test_a_leg_without_a_pin_gets_empty_seller_knowledge_not_an_error(
    tmp_path: Path, migrated_db: bool
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="nopin")
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"],
                storage=seeds["storage"],
                conn_factory=seeds["conn_factory"],
            )
            # A turn id that never pinned anything, and a bundle that names no opening turn at
            # all: both are honestly empty rather than a failure the design turn cannot recover
            # from.
            unpinned = await asyncio.to_thread(
                factory,
                _leg_envelope(seeds["workspace_id"], seeds["project"].project_id, uuid4()),
            )
            assert unpinned is not None
            seller = await asyncio.to_thread(unpinned.seller_knowledge)
            assert seller.documents == () and seller.documents_sha256 is None
            assert seller.confirmed_icp_path is None and seller.product_set is None

            unbundled = await asyncio.to_thread(
                factory,
                _leg_envelope(seeds["workspace_id"], seeds["project"].project_id, None),
            )
            assert unbundled is not None
            assert (await asyncio.to_thread(unbundled.seller_knowledge)).documents == ()

    run_async(scenario())


def test_a_leg_without_a_project_cannot_search(tmp_path: Path, migrated_db: bool) -> None:
    """The execution layer asserts the tool's ``project`` pin on head-of-abm's path; this seam runs
    outside an execution, so the seam itself refuses a search the leg cannot bind to a project."""
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import (
        DesignPlatformReadError,
        build_design_platform_reads_factory,
    )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="noproject")
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"],
                storage=seeds["storage"],
                conn_factory=seeds["conn_factory"],
            )
            reads = await asyncio.to_thread(
                factory, _leg_envelope(seeds["workspace_id"], None, seeds["opening_turn"])
            )
            assert reads is not None
            with pytest.raises(DesignPlatformReadError, match="project_unbound"):
                await asyncio.to_thread(reads.web_search, query="acme summit 2026")
            assert seeds["fake_exa"].calls == []

    run_async(scenario())


def test_calling_from_the_platform_loop_is_refused(tmp_path: Path, migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import (
        DesignPlatformReadError,
        build_design_platform_reads_factory,
    )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="onloop")
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"],
                storage=seeds["storage"],
                conn_factory=seeds["conn_factory"],
            )
            reads = factory(
                _leg_envelope(
                    seeds["workspace_id"], seeds["project"].project_id, seeds["opening_turn"]
                )
            )
            assert reads is not None
            with pytest.raises(DesignPlatformReadError, match="platform_loop"):
                reads.read_project_accounts()
            with pytest.raises(DesignPlatformReadError, match="platform_loop"):
                reads.seller_knowledge()

    run_async(scenario())
