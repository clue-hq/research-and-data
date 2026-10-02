"""genad2 — ``open_design_leg@4`` births a ZERO-PAGE design document (genad2 ruling 1).

``open_design_leg@3`` (genad, 2026-08-23) made a document-less ``doc_kind="scene"`` open
birth an ad document with ONE page, at a format the *platform* resolved from ``ad_format`` /
``ad_width`` / ``ad_height`` tool parameters. The founder reversed that half of genad ruling 2
the same week: the platform must not own page geometry at all. **Superseded 2026-08-23 by
genad2 ruling 1** — plan ``docs/superpowers/plans/2026-08-23-agent-authored-pages.md``. The @3
tests this file used to carry (the format-required / custom-dimensions / preset-with-dimensions
/ ad-format-on-web refusals, the preset pixel lookup, the single-artboard assertions) are
deleted rather than amended: their whole subject — a platform-side format aperture — no longer
exists, and the design deepagent authors the page itself in a later turn, at the size and unit
the user's own words imply.

The properties this file pins at @4:

* **the birth is pageless** — ``pages == {}``, ``nodes == {}``: a durable document, a brand
  binding, a leg pin, and nothing whatsoever about geometry;
* **the format fields are gone, loudly** — ``ToolInput`` forbids extras, so an agent still
  sending ``ad_format`` gets a validation refusal instead of a silently ignored parameter
  (the correct behaviour while the Head-of-ABM profile catches up);
* **the birth is governed, twin-proof, and brand-decided-at-birth** — the same three
  guarantees the web birth carries, because it runs through the same seams
  (``create_document`` inside the leg's own transaction, a document id derived from the leg
  id, and a D5 brand pin READ BACK off the stored row);
* **the gallery states nothing it does not know** — a pageless ad card carries no dimensions.

**@5 (2026-09-19).** The single top-level ``title`` is retired into an ``artifacts`` list — one
item per artifact the user asked for — so every open in this file now sends a list of ONE, which
is the single-document case by construction (position 0's derived id is byte-identical to @4's).
The batch contract itself lives in ``test_multi_artifact_leg_birth_db``.

All writes run in rolled-back transactions against the session-migrated DB. Only the ENGINE
round-trip is faked (:class:`_RecordingSceneMinter`), so these tests need no Rust binary; the
scene it returns reproduces ``lumen_core::Scene::new``'s serialized shape (``scene.rs:25-42``)
field for field, including the ``null`` optionals serde emits.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import insert_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat.router import _design_artifact_list_item
from clue_api.conversation_capture import persist_user_turn
from clue_api.design_leg_tools import (
    OpenDesignLegTool,
    derive_design_leg_id,
    derive_leg_document_id,
)
from clue_api.design_leg_wiring import document_page_pixels, project_design_documents
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_design import legs as design_legs
from clue_design.documents import get_document
from clue_storage import FsStorage
from clue_toolbelt import (
    ToolContext,
    ToolRegistry,
    invoke_tool,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.test_genweb_leg_document_birth_db import engine_web_doc
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

USER_ID = "usr_genad_birth"
NOW_UTC = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def engine_ad_scene(
    *,
    document_id: str,
    title: str,
    brand_kit_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The engine's empty scene, reproduced (``lumen_core::Scene::new`` + serde).

    The real minter is a blocking ``lumen-api-helper`` round-trip; this is the shape it
    returns for ``new_scene(document_id, title, None, "ad")``. ``Scene::new`` builds empty
    ``pages``/``nodes``/``slots``/``assets`` maps, and the ``Option`` fields carry no
    ``skip_serializing_if``, so ``artifact_type`` and ``brand_kit`` ride the wire as JSON
    ``null`` — which is exactly the hole the DAL's creation contract fills with the
    workspace's latest approved kit.
    """

    scene: dict[str, Any] = {
        "schema_version": 1,
        "meta": {
            "id": document_id,
            "title": title,
            "artifact_type": None,
            "medium": "ad",
            "brand_kit": None,
            "status": {"kind": "draft"},
        },
        "pages": {},
        "nodes": {},
        "slots": {},
        "assets": {},
        "export_profiles": [],
    }
    if brand_kit_ref is not None:
        scene["meta"]["brand_kit"] = dict(brand_kit_ref)
    return scene


class _RecordingSceneMinter:
    """The injected engine seam, recording every kwarg the tool threaded into it.

    Its signature IS an assertion: a tool that still tried to thread a format key or
    dimensions through would raise ``TypeError`` here rather than quietly pass them on.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        document_id: str,
        title: str,
        brand_kit_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "document_id": document_id,
                "title": title,
                "brand_kit_ref": brand_kit_ref,
            }
        )
        return engine_ad_scene(
            document_id=document_id,
            title=title,
            brand_kit_ref=brand_kit_ref,
        )


async def _seed_conversation(
    conn: AsyncConnection,
    *,
    storage_root: Path,
    label: str,
) -> dict[str, Any]:
    """One workspace, project, thread, and a durable presenting head-of-abm turn."""

    workspace_id = f"ws_genad_{label}_{uuid4().hex[:8]}"
    project = await seed_project(conn, workspace_id, name=f"genad {label}")
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"wsm_genad_{workspace_id}",
    )
    thread_id = f"thr_genad_{label}_{uuid4().hex[:8]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": workspace_id, "project": project.project_id},
    )
    conn_factory = conn_session_factory(conn)
    artifacts = DurableAgentArtifactStore(
        storage=FsStorage(storage_root / "artifacts"),
        conn_factory=conn_factory,
    )
    turn_id = uuid5(NAMESPACE_URL, f"genad:{workspace_id}:{label}:presenting-turn")
    captured = await persist_user_turn(
        conn,
        artifacts=artifacts,
        workspace_id=workspace_id,
        brand_id=project.brand_id,
        product_id=project.product_id,
        project_id=project.project_id,
        turn_id=turn_id,
        message="Make me a LinkedIn ad for the Insight Health launch.",
    )
    await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=workspace_id,
        project_id=project.project_id,
        thread_id=thread_id,
        submitted_by_user_id=USER_ID,
        submitted_via_membership_id=f"wsm_genad_{workspace_id}",
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=captured.artifact_ref.artifact_key,
        message_sha256=captured.artifact_ref.sha256,
        idempotency_key=f"genad-{label}-presenting",
    )
    manifest = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    execution_id = uuid5(NAMESPACE_URL, f"genad:{workspace_id}:{label}:execution")
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
            " 'head_of_abm', 'root-genad', 'head-of-abm', 'v37', :sha, :key, :sha256, "
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
            "membership": f"wsm_genad_{workspace_id}",
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


def _registry(seeds: dict[str, Any], minter: _RecordingSceneMinter) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        OpenDesignLegTool(
            conn_factory=seeds["conn_factory"],
            storage=seeds["storage"],
            scene_document_minter=minter,
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


async def _open(seeds: dict[str, Any], registry: ToolRegistry, **overrides: Any) -> Any:
    args: dict[str, Any] = {
        "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
        "brief": "A launch ad for Insight Health, aimed at clinical operations leads.",
        "doc_kind": "scene",
        # @5 retired the single top-level `title` into the artifacts list; one artifact is a
        # list of one, which is exactly what every @4 test in this file asks for.
        "artifacts": [{"title": "A launch ad for Insight Health, aimed at"}],
    }
    args.update(overrides)
    return await invoke_tool(
        registry,
        "open_design_leg",
        args,
        _context(seeds),
        idempotency_ttl_s=60,
    )


async def _no_leg_and_no_document(conn: AsyncConnection, seeds: dict[str, Any]) -> bool:
    """A refused delegation leaves neither a leg nor a document behind (any kind)."""

    open_leg = await design_legs.get_open_leg_for_thread(
        conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
    )
    born = (
        await conn.execute(
            text("SELECT count(*) FROM design_document WHERE workspace_id = :ws"),
            {"ws": seeds["workspace_id"]},
        )
    ).scalar_one()
    return open_leg is None and int(born) == 0


def test_a_document_less_scene_open_births_a_zero_page_document(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """genad2 ruling 1: the leg creates the document and the brand binding — and NO page.

    Geometry is the design deepagent's to author, so the birth names none: no format key
    reaches the engine, ``artifact_type`` stays null, and the scene is pageless."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="birth")
            minter = _RecordingSceneMinter()
            result = await _open(
                seeds,
                _registry(seeds, minter),
                artifacts=[{"title": "Insight Health launch ad"}],
            )
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
            assert document["doc_kind"] == "scene"
            assert document["status"] == "draft"
            assert document["current_version"] == 0
            assert document["title"] == "Insight Health launch ad"
            assert document["account_id"] is None
            # ZERO PAGES: the document exists, and nothing about its geometry does.
            assert document["scene"]["pages"] == {}
            assert document["scene"]["nodes"] == {}
            assert document["scene"]["meta"]["medium"] == "ad"
            assert document["scene"]["meta"]["artifact_type"] is None

            # The leg is pinned to it at birth, and the pin is the durable row's.
            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(refs["leg_id"])
            )
            assert leg["state"] == "open_awaiting_user"
            assert leg["document_id"] == document["id"]
            assert leg["document_version_guard"] == 0

            # The engine was asked for an identity and nothing else — no format, no size.
            assert minter.calls == [
                {
                    "document_id": document["id"],
                    "title": "Insight Health launch ad",
                    "brand_kit_ref": None,
                }
            ]

            # The frozen bundle names the document this delegation created.
            bundle = json.loads(await seeds["storage"].get(leg["bundle_artifact_ref"]))
            assert bundle["target_document"] == {
                "document_id": document["id"],
                "version_guard": 0,
            }

    run_async(scenario())


def test_the_zero_page_birth_is_twin_proof_under_replay(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """§6 trap 3, for ads: a retried delegation must not mint a second document."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="twin")
            minter = _RecordingSceneMinter()
            registry = _registry(seeds, minter)
            first = await _open(seeds, registry)
            replay = await _open(seeds, registry)

            assert replay.references["document_id"] == first.references["document_id"]
            assert replay.references["leg_id"] == first.references["leg_id"]
            assert first.references["document_created"] is True
            # The replay creates nothing — neither the leg nor the document.
            assert replay.references["created"] is False
            assert replay.references["document_created"] is False
            assert len(minter.calls) == 1

            documents = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM design_document "
                        "WHERE workspace_id = :ws AND doc_kind = 'scene'"
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


def test_an_approved_kit_is_stamped_on_the_pageless_birth_and_the_leg_pins_it_read_back(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The scene stamp survives the zero-page flip: the minter returns a kit-less scene, the
    creation contract stamps the workspace's latest APPROVED kit onto a document that has no
    pages at all, and the leg's D5 pin is that stored stamp read back — never a second,
    independent derivation. (The approved v1 wins over the newer *draft* v2: approval is
    version-specific.)"""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="kit")
            await _seed_brand_kit(
                conn,
                workspace_id=seeds["workspace_id"],
                brand_id=seeds["brand_id"],
                kit_id="kit_genad",
                version=1,
                approval_status="approved",
            )
            await _seed_brand_kit(
                conn,
                workspace_id=seeds["workspace_id"],
                brand_id=seeds["brand_id"],
                kit_id="kit_genad",
                version=2,
                approval_status="draft",
            )
            minter = _RecordingSceneMinter()
            result = await _open(seeds, _registry(seeds, minter))

            # The engine was handed NO kit — the stamp is the DAL's decision, not the tool's.
            assert minter.calls[0]["brand_kit_ref"] is None

            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(result.references["document_id"]),
            )
            assert document["scene"]["pages"] == {}
            stamped = document["scene"]["meta"]["brand_kit"]
            assert stamped == {"id": "kit_genad", "version": 1}
            assert document["effective_brand_kit_id"] == "kit_genad"
            assert document["effective_brand_kit_version"] == 1

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(result.references["leg_id"])
            )
            assert leg["brand_kit_id"] == document["effective_brand_kit_id"] == stamped["id"]
            assert (
                leg["brand_kit_version"]
                == document["effective_brand_kit_version"]
                == stamped["version"]
            )
            bundle = json.loads(await seeds["storage"].get(leg["bundle_artifact_ref"]))
            assert bundle["brand_kit"] == {"brand_kit_id": "kit_genad", "version": 1}

    run_async(scenario())


def test_without_an_approved_kit_the_pageless_birth_is_unbranded_no_pin(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The honest fallback: no approved kit ⇒ ``meta.brand_kit`` stays null and the leg
    carries no pin. Generation still works — un-branded, honestly."""

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
            minter = _RecordingSceneMinter()
            result = await _open(seeds, _registry(seeds, minter))

            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(result.references["document_id"]),
            )
            assert document["scene"]["pages"] == {}
            assert document["scene"]["meta"]["brand_kit"] is None
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


def test_format_fields_are_rejected_as_unknown(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The @3 aperture is DELETED, not deprecated: ``ToolInput`` forbids extras, so an agent
    still sending ``ad_format`` gets a loud validation refusal rather than a silently ignored
    parameter. That is the correct behaviour while the Head-of-ABM profile catches up — a
    dropped format would look like agreement."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="format")
            minter = _RecordingSceneMinter()
            with pytest.raises(ValidationError) as failure:
                await _open(seeds, _registry(seeds, minter), ad_format="square")
            assert "ad_format" in str(failure.value)
            assert "extra_forbidden" in str(failure.value)
            assert minter.calls == []
            assert await _no_leg_and_no_document(conn, seeds)

    run_async(scenario())


def test_the_zero_page_birth_appears_in_the_gallery_feed_with_no_dimensions(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Rail derivation, for free (AD2.1) — and the card states nothing it does not know.

    The feed serves the newborn ad the moment the leg opens, but a pageless document records
    no size and no artifact type, so ``document_page_pixels`` is honestly ``None`` and the
    wire's ``width_px``/``height_px`` are ``None`` too. The G-H rule holds under zero pages:
    a card says nothing rather than something false."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="rail")
            minter = _RecordingSceneMinter()
            result = await _open(
                seeds,
                _registry(seeds, minter),
                artifacts=[{"title": "Insight Health launch ad"}],
            )

            feed = await project_design_documents(
                conn,
                workspace_id=seeds["workspace_id"],
                project_id=seeds["project_id"],
            )
            assert [item["id"] for item in feed] == [result.references["document_id"]]
            card = feed[0]
            assert card["doc_kind"] == "scene"
            assert card["title"] == "Insight Health launch ad"
            assert card["status"] == "draft"
            assert card["current_version"] == 0
            assert card["origin_thread_id"] == seeds["thread_id"]
            assert card["artifact_type"] is None
            assert document_page_pixels(card["pages_json"]) is None

            wire = _design_artifact_list_item(seeds["project_id"], card)
            assert wire.kind == "ad"
            assert wire.artifact_type is None
            assert wire.width_px is None
            assert wire.height_px is None

    run_async(scenario())


def test_web_birth_is_byte_unchanged(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The regression pin: @4 touches the SCENE path only. A ``doc_kind="web"`` open still
    births the engine's one-page ``WebDoc`` exactly as it did at @3 — same page, same root
    container, same pin at version 0."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="web")
            minter = _RecordingSceneMinter()
            result = await _open(seeds, _registry(seeds, minter), doc_kind="web")
            assert result.references["document_created"] is True
            # The web birth never touches the scene minter.
            assert minter.calls == []

            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(result.references["document_id"]),
            )
            assert document["doc_kind"] == "web"
            assert document["status"] == "draft"
            assert document["current_version"] == 0
            page = document["scene"]["pages"][0]
            assert page["id"] == "home"
            assert list(page["nodes"]) == ["root"]
            assert page["nodes"]["root"]["kind"] == "container"

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(result.references["leg_id"])
            )
            assert leg["document_id"] == document["id"]
            assert leg["document_version_guard"] == 0

    run_async(scenario())
