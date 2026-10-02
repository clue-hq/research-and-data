"""genweb slice 2 — ``open_design_leg@2`` births the web document (plan §4.1, B2/F5).

Before this slice a leg could only ever *pin* a document someone else had made, so "make me
a landing page" had nowhere to land. Now a document-less open with ``doc_kind="web"`` creates
one empty website-mode document and opens the leg on it, and three properties have to hold at
once:

* **the birth is governed** — it routes through ``clue_design.documents.create_document``,
  the frozen creation contract, in the SAME transaction as the leg insert;
* **the birth is twin-proof** — the document id derives from the leg id (which derives from
  the presenting turn), so a replayed delegation addresses the same row;
* **the brand identity is decided at birth and only READ BACK afterwards** — the leg's D5 pin
  is whatever the stored document was stamped with, never a second, independent derivation.

All writes run in rolled-back transactions against the session-migrated DB. The engine
round-trip (``lumen-api-helper``'s ``web_new_doc``) is injected, so these tests need no Rust
binary; :func:`engine_web_doc` reproduces the helper's real output byte for byte (recorded
2026-08-19 from ``target/release/lumen-api-helper``).

**Scene-side history (2026-08-23).** This file once carried the v1 pin
``test_scene_document_creation_is_refused`` (a scene leg could not create its document at all),
replaced during the genad lane by ``test_scene_document_creation_births_since_genad`` (a scene
open naming no ``ad_format`` still created nothing). ``open_design_leg@4`` deleted the format
aperture outright — genad2 ruling 1, plan
``docs/superpowers/plans/2026-08-23-agent-authored-pages.md`` — so a document-less scene open
now simply births a pageless document and there is no scene-shaped refusal left to pin here.
The whole scene birth contract, and a byte-unchanged regression pin over THIS file's web path,
live in ``test_genad_leg_document_birth_db``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import insert_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.conversation_capture import persist_user_turn
from clue_api.design_leg_tools import (
    OpenDesignLegTool,
    derive_design_leg_id,
    derive_leg_document_id,
)
from clue_api.design_leg_wiring import project_design_documents
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_design import legs as design_legs
from clue_design.documents import create_document, get_document
from clue_storage import FsStorage
from clue_toolbelt import (
    PreconditionFailed,
    ToolContext,
    ToolRegistry,
    invoke_tool,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

USER_ID = "usr_genweb_birth"
NOW_UTC = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def engine_web_doc(
    *, document_id: str, title: str, brand_kit_ref: dict[str, Any] | None
) -> dict[str, Any]:
    """The engine's empty ``WebDoc``, verbatim (``lumen_web::WebDoc::new``).

    Recorded from the real helper on 2026-08-19:
    ``echo '{"action":"web_new_doc",...}' | target/release/lumen-api-helper``. One page, one
    empty root container, NO theme unless the caller pinned a kit — which is exactly the hole
    the DAL's creation contract fills with the workspace's latest approved kit.
    """

    doc: dict[str, Any] = {
        "assets": {},
        "custom_css": "",
        "id": document_id,
        "pages": [
            {
                "id": "home",
                "name": "Home",
                "nodes": {
                    "root": {"classes": "", "id": "root", "kind": "container", "new_tab": False}
                },
                "root": "root",
                "route": "/",
            }
        ],
        "schema_version": 1,
        "theme": {},
        "title": title,
    }
    if brand_kit_ref is not None:
        doc["theme"] = {"brand_kit": brand_kit_ref}
    return doc


async def _seed_conversation(
    conn: AsyncConnection,
    *,
    storage_root: Path,
    label: str,
) -> dict[str, Any]:
    """One workspace, project, thread, and a durable presenting head-of-abm turn."""

    workspace_id = f"ws_genweb_{label}_{uuid4().hex[:8]}"
    project = await seed_project(conn, workspace_id, name=f"genweb {label}")
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"wsm_genweb_{workspace_id}",
    )
    thread_id = f"thr_genweb_{label}_{uuid4().hex[:8]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": workspace_id, "project": project.project_id},
    )
    conn_factory = conn_session_factory(conn)
    artifacts = DurableAgentArtifactStore(
        storage=FsStorage(storage_root / "artifacts"),
        conn_factory=conn_factory,
    )
    turn_id = uuid5(NAMESPACE_URL, f"genweb:{workspace_id}:{label}:presenting-turn")
    captured = await persist_user_turn(
        conn,
        artifacts=artifacts,
        workspace_id=workspace_id,
        brand_id=project.brand_id,
        product_id=project.product_id,
        project_id=project.project_id,
        turn_id=turn_id,
        message="Build me a landing page for the Insight Health launch.",
    )
    await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=workspace_id,
        project_id=project.project_id,
        thread_id=thread_id,
        submitted_by_user_id=USER_ID,
        submitted_via_membership_id=f"wsm_genweb_{workspace_id}",
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=captured.artifact_ref.artifact_key,
        message_sha256=captured.artifact_ref.sha256,
        idempotency_key=f"genweb-{label}-presenting",
    )
    manifest = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    execution_id = uuid5(NAMESPACE_URL, f"genweb:{workspace_id}:{label}:execution")
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
        ),
        {
            "id": execution_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "hash": "0" * 64,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at, "
            " submitted_by_user_id, submitted_via_membership_id) "
            "VALUES (:id, :execution, :workspace, :project, :thread, :actor_id, "
            " 'head_of_abm', 'root-genweb', 'head-of-abm', 'v37', :sha, :key, :sha256, "
            " :sha256, 'test', :requested_at, :user, :membership)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "thread": thread_id,
            "actor_id": USER_ID,
            "sha": "0" * 64,
            "key": manifest.artifact_key,
            "sha256": manifest.sha256,
            "requested_at": NOW_UTC,
            "user": USER_ID,
            "membership": f"wsm_genweb_{workspace_id}",
        },
    )
    return {
        "workspace_id": workspace_id,
        "project_id": project.project_id,
        "brand_id": project.brand_id,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "execution_id": execution_id,
        "conn_factory": conn_factory,
        "storage": FsStorage(storage_root / "artifacts"),
    }


async def _seed_brand_kit(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    kit_id: str,
    version: int,
    approval_status: str,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO design_brand_kit "
            "(brand_kit_id, version, workspace_id, brand_id, name, source, brand_kit_json, "
            " brand_summary_json, diagnostics_json, approval_status) "
            "VALUES (:kit, :version, :ws, :brand, 'Insight kit', 'manual', "
            " CAST('{}' AS jsonb), CAST('{}' AS jsonb), CAST('[]' AS jsonb), :status)"
        ),
        {
            "kit": kit_id,
            "version": version,
            "ws": workspace_id,
            "brand": brand_id,
            "status": approval_status,
        },
    )


def _registry(seeds: dict[str, Any]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        OpenDesignLegTool(
            conn_factory=seeds["conn_factory"],
            storage=seeds["storage"],
            web_document_minter=engine_web_doc,
        ),
        make_default=True,
    )
    return registry


def _context(seeds: dict[str, Any]) -> ToolContext:
    return ToolContext(
        workspace_id=seeds["workspace_id"],
        actor="agent",
        conn_factory=seeds["conn_factory"],
        operation_id=new_operation_id(),
    )


async def _open(
    seeds: dict[str, Any], registry: ToolRegistry | None = None, **overrides: Any
) -> Any:
    args: dict[str, Any] = {
        "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
        "brief": "A launch landing page for Insight Health, aimed at clinical operations leads.",
        "doc_kind": "web",
        # @5 retired the single top-level `title` into the artifacts list; one artifact is a
        # list of one, which is exactly what every @4 test in this file asks for.
        "artifacts": [{"title": "A launch landing page for Insight Health, aimed"}],
    }
    args.update(overrides)
    return await invoke_tool(
        registry or _registry(seeds),
        "open_design_leg",
        args,
        _context(seeds),
        idempotency_ttl_s=60,
    )


def test_a_document_less_web_open_births_the_document_and_pins_the_leg_to_it(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """B2's whole point: the leg creates its own empty, draft, workspace-scoped web document."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="birth")
            result = await _open(seeds, artifacts=[{"title": "Insight Health landing page"}])
            refs = result.references
            assert refs["created"] is True
            assert refs["document_created"] is True

            expected_leg_id = derive_design_leg_id(
                workspace_id=seeds["workspace_id"], turn_id=seeds["turn_id"]
            )
            assert refs["leg_id"] == expected_leg_id
            assert refs["document_id"] == derive_leg_document_id(leg_id=expected_leg_id)
            assert refs["document_version_guard"] == 0

            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(refs["document_id"]),
            )
            assert document["doc_kind"] == "web"
            assert document["status"] == "draft"
            assert document["current_version"] == 0
            assert document["title"] == "Insight Health landing page"
            assert document["account_id"] is None  # G2: a leg-born page has no account
            # EMPTY: the engine's one page with one empty root container and nothing authored.
            page = document["scene"]["pages"][0]
            assert page["id"] == "home"
            assert list(page["nodes"]) == ["root"]
            assert page["nodes"]["root"]["kind"] == "container"

            # The leg is pinned to it at birth, and the pin is the durable row's.
            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(refs["leg_id"])
            )
            assert leg["state"] == "open_awaiting_user"
            assert leg["document_id"] == document["id"]
            assert leg["document_version_guard"] == 0

            # Workspace-scoped: the row belongs to this workspace and no other.
            owner = (
                await conn.execute(
                    text("SELECT workspace_id FROM design_document WHERE id = :d"),
                    {"d": document["id"]},
                )
            ).scalar_one()
            assert owner == seeds["workspace_id"]

            # The frozen bundle names the document this delegation created.
            bundle = json.loads(await seeds["storage"].get(leg["bundle_artifact_ref"]))
            assert bundle["target_document"] == {
                "document_id": document["id"],
                "version_guard": 0,
            }

    run_async(scenario())


def test_the_birth_is_twin_proof_under_replay(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """§6 trap 3: a retried delegation must not mint a second document."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="twin")
            registry = _registry(seeds)
            first = await _open(seeds, registry)
            replay = await _open(seeds, registry)

            assert replay.references["document_id"] == first.references["document_id"]
            assert replay.references["leg_id"] == first.references["leg_id"]
            assert first.references["document_created"] is True
            # The replay creates nothing — neither the leg nor the document.
            assert replay.references["created"] is False
            assert replay.references["document_created"] is False

            documents = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM design_document "
                        "WHERE workspace_id = :ws AND doc_kind = 'web'"
                    ),
                    {"ws": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert int(documents) == 1
            legs = (
                await conn.execute(
                    text("SELECT count(*) FROM design_leg WHERE thread_id = :thread"),
                    {"thread": seeds["thread_id"]},
                )
            ).scalar_one()
            assert int(legs) == 1

    run_async(scenario())


def test_the_leg_born_document_appears_in_the_projects_gallery_feed(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Rail derivation, for free: the gallery feed reads legs joined to web documents, so the
    card exists the moment the leg opens — no state filter, no extra write."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="rail")
            result = await _open(seeds, artifacts=[{"title": "Insight Health landing page"}])

            feed = await project_design_documents(
                conn,
                workspace_id=seeds["workspace_id"],
                project_id=seeds["project_id"],
            )
            assert [item["id"] for item in feed] == [result.references["document_id"]]
            card = feed[0]
            assert card["title"] == "Insight Health landing page"
            assert card["status"] == "draft"
            assert card["current_version"] == 0
            assert card["origin_thread_id"] == seeds["thread_id"]

    run_async(scenario())


def test_the_items_title_is_the_born_documents_title(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """F5, at @5: the item's own title names the document, so the gallery card is never
    nameless. The @4 fallback (no title ⇒ the brief's first ~8 words) is GONE — an artifact
    always carries a title, and a document-less open with no artifacts is refused instead."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="title")
            result = await _open(seeds)
            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(result.references["document_id"]),
            )
            assert document["title"] == "A launch landing page for Insight Health, aimed"

    run_async(scenario())


def test_a_document_less_open_without_a_doc_kind_is_refused(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The delegation must say what to make; silence is not "guess a website"."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="nokind")
            with pytest.raises(PreconditionFailed) as failure:
                await _open(seeds, doc_kind=None)
            assert "design_leg_doc_kind_required" in str(failure.value)
            assert await _no_leg_and_no_document(conn, seeds)

    run_async(scenario())


def test_another_workspaces_document_cannot_be_pinned(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Workspace mismatch: a foreign document is indistinguishable from a missing one, and no
    ``doc_kind`` on the input can turn that refusal into a silent birth."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="foreign")
            foreign = await _seed_conversation(conn, storage_root=tmp_path, label="otherws")
            stranger = await create_document(
                conn,
                workspace_id=foreign["workspace_id"],
                scene={"meta": {"id": f"doc_stranger_{uuid4().hex[:8]}", "title": "Not yours"}},
            )
            with pytest.raises(PreconditionFailed) as failure:
                # @5: a pin carries no artifacts list (they are exclusive), so the refusal
                # under test is the workspace mismatch and nothing else.
                await _open(seeds, document_id=stranger["id"], artifacts=[])
            assert "design_document_not_found" in str(failure.value)
            assert await _no_leg_and_no_document(conn, seeds)

    run_async(scenario())


def test_a_reopen_ignores_doc_kind(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """§2.2: a reopen is a resumption, not a fresh delegation — it births nothing and keeps the
    original leg's pins byte for byte."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="reopen")
            existing = await create_document(
                conn,
                workspace_id=seeds["workspace_id"],
                scene={"meta": {"id": f"doc_reopen_{uuid4().hex[:8]}", "title": "Original"}},
            )
            closed = await design_legs.open_leg(
                conn,
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
                parent_execution_id=seeds["execution_id"],
                document_id=existing["id"],
                document_version_guard=0,
            )
            await design_legs.close_leg(
                conn,
                workspace_id=seeds["workspace_id"],
                leg_id=str(closed["id"]),
                reason="abandoned",
                summary_refs={"closing_turn_id": str(uuid4())},
            )
            before = (
                await conn.execute(
                    text("SELECT count(*) FROM design_document WHERE workspace_id = :ws"),
                    {"ws": seeds["workspace_id"]},
                )
            ).scalar_one()

            # @5: `artifacts` beside a reopen is refused outright (a reopen resumes the
            # leg's OWN artifacts), so the doc_kind that used to be silently ignored is the
            # only thing left to ignore here.
            result = await _open(
                seeds,
                reopen_leg_id=str(closed["id"]),
                doc_kind="web",
                artifacts=[],
            )
            assert result.references["reopened"] is True
            assert result.references["document_created"] is False
            assert result.references["document_id"] == existing["id"]

            after = (
                await conn.execute(
                    text("SELECT count(*) FROM design_document WHERE workspace_id = :ws"),
                    {"ws": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert int(after) == int(before)
            assert (
                await get_document(
                    conn, workspace_id=seeds["workspace_id"], document_id=existing["id"]
                )
            )["title"] == "Original"

    run_async(scenario())


# --------------------------------------------------------------------------------------------
# Brand theming — the founder-ordered amendment (plan §4.1)
# --------------------------------------------------------------------------------------------


def test_an_approved_kit_is_stamped_at_birth_and_the_leg_pins_it_read_back(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """(a) The document carries the approved kit's theme ref AND the leg pins the SAME
    ``{brand_kit_id, version}`` — asserted equal to the STORED document's stamp, never
    re-derived. Note the approved v1 wins over the newer *draft* v2: approval is
    version-specific, and the leg must pin what the document actually got."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="kit")
            await _seed_brand_kit(
                conn,
                workspace_id=seeds["workspace_id"],
                brand_id=seeds["brand_id"],
                kit_id="kit_genweb",
                version=1,
                approval_status="approved",
            )
            await _seed_brand_kit(
                conn,
                workspace_id=seeds["workspace_id"],
                brand_id=seeds["brand_id"],
                kit_id="kit_genweb",
                version=2,
                approval_status="draft",
            )
            result = await _open(seeds)

            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(result.references["document_id"]),
            )
            stamped = document["scene"]["theme"]["brand_kit"]
            assert stamped == {"id": "kit_genweb", "version": 1}
            assert document["effective_brand_kit_id"] == "kit_genweb"
            assert document["effective_brand_kit_version"] == 1

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(result.references["leg_id"])
            )
            # The pin IS the stored document's stamp — the same two values, read back.
            assert leg["brand_kit_id"] == document["effective_brand_kit_id"] == stamped["id"]
            assert (
                leg["brand_kit_version"]
                == document["effective_brand_kit_version"]
                == stamped["version"]
            )
            # ...and the frozen bundle records the same born identity.
            bundle = json.loads(await seeds["storage"].get(leg["bundle_artifact_ref"]))
            assert bundle["brand_kit"] == {"brand_kit_id": "kit_genweb", "version": 1}

    run_async(scenario())


def test_without_an_approved_kit_the_theme_is_all_null_and_the_leg_carries_no_pin(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """(b) The real fallback shape (slice-0 datapoint): an ALL-NULL theme, NOT a "platform
    default kit" object. Generation still works — un-branded, honestly."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="nokit")
            await _seed_brand_kit(
                conn,
                workspace_id=seeds["workspace_id"],
                brand_id=seeds["brand_id"],
                kit_id="kit_unapproved",
                version=1,
                approval_status="draft",
            )
            result = await _open(seeds)

            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(result.references["document_id"]),
            )
            assert document["scene"]["theme"] == {}
            assert document["effective_brand_kit_id"] is None
            assert document["effective_brand_kit_version"] is None

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(result.references["leg_id"])
            )
            assert leg["brand_kit_id"] is None
            assert leg["brand_kit_version"] is None
            bundle = json.loads(await seeds["storage"].get(leg["bundle_artifact_ref"]))
            assert bundle["brand_kit"] is None

    run_async(scenario())


def test_a_kit_approved_after_birth_neither_restamps_the_document_nor_moves_the_pin(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """(c) Version honesty across a whole conversation: the creation contract stamps only at
    birth, and the leg's pin is a durable column, so a mid-conversation approval changes
    neither. Every generation turn on this leg designs against the born kit version."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="later")
            await _seed_brand_kit(
                conn,
                workspace_id=seeds["workspace_id"],
                brand_id=seeds["brand_id"],
                kit_id="kit_genweb",
                version=1,
                approval_status="approved",
            )
            result = await _open(seeds)
            document_id = str(result.references["document_id"])
            leg_id = str(result.references["leg_id"])

            # A newer kit version is approved MID-CONVERSATION.
            await _seed_brand_kit(
                conn,
                workspace_id=seeds["workspace_id"],
                brand_id=seeds["brand_id"],
                kit_id="kit_genweb",
                version=2,
                approval_status="approved",
            )

            document = await get_document(
                conn, workspace_id=seeds["workspace_id"], document_id=document_id
            )
            assert document["scene"]["theme"]["brand_kit"] == {"id": "kit_genweb", "version": 1}
            assert document["effective_brand_kit_version"] == 1
            leg = await design_legs.get_leg(conn, workspace_id=seeds["workspace_id"], leg_id=leg_id)
            assert leg["brand_kit_version"] == 1

    run_async(scenario())


async def _no_leg_and_no_document(conn: AsyncConnection, seeds: dict[str, Any]) -> bool:
    """A refused delegation leaves neither a leg nor a document behind."""

    open_leg = await design_legs.get_open_leg_for_thread(
        conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
    )
    born = (
        await conn.execute(
            text(
                "SELECT count(*) FROM design_document WHERE workspace_id = :ws AND doc_kind = 'web'"
            ),
            {"ws": seeds["workspace_id"]},
        )
    ).scalar_one()
    return open_leg is None and int(born) == 0
