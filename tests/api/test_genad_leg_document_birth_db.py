"""genad — ``open_design_leg@3`` births the ad (scene) document (genad rulings 1+2).

``open_design_leg@2`` refused scene creation outright: the ad flow was editor-first, so a
scene leg could only ever pin a document a human had already made in the editor. That ruling
was reversed 2026-08-23 — "make me a LinkedIn ad" must land the same way "make me a landing
page" does. A document-less open with ``doc_kind="scene"`` now names a ratified **format**
and births one empty ad document at that size.

The properties this file pins, mirroring the genweb birth file seam for seam:

* **the format is a loud precondition, never a guess** — a scene open with no ``ad_format``
  is refused (``design_leg_ad_format_required``), ``custom`` without dimensions and a preset
  *with* dimensions are both refused (``design_leg_ad_format_invalid``), and an ``ad_format``
  on a ``web`` open is refused too (no cross-kind leakage);
* **the preset resolves its own pixels** — the tool, not the minter, looks the format up in
  :data:`clue_api.design_tools.AD_FORMAT_PRESETS`;
* **the birth is governed, twin-proof, and brand-decided-at-birth** — the same three
  guarantees the web birth carries, because it runs through the same seams
  (``create_document`` inside the leg's own transaction, a document id derived from the leg
  id, and a D5 brand pin READ BACK off the stored row).

All writes run in rolled-back transactions against the session-migrated DB. Only the ENGINE
round-trip is faked (:class:`_RecordingSceneMinter`), so these tests need no Rust binary; the
scene it returns reproduces the real ``mint_empty_ad_document`` shape (``new_scene`` + one
``add_page`` carrying :func:`clue_api.design_tools.ad_birth_page`) field for field.
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
from clue_api.design_leg_wiring import document_page_pixels, project_design_documents
from clue_api.design_tools import AD_FORMAT_PRESETS, ad_birth_page
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_design import legs as design_legs
from clue_design.documents import get_document
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

USER_ID = "usr_genad_birth"
NOW_UTC = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def engine_ad_scene(
    *,
    document_id: str,
    title: str,
    format_key: str,
    width: int,
    height: int,
    brand_kit_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The engine's empty ad scene, reproduced (``new_scene`` + one ``add_page``).

    The real ``mint_empty_ad_document`` is a blocking ``lumen-api-helper`` round-trip; this is
    the shape it returns, built from the SAME :func:`ad_birth_page` payload so the artboard
    (and therefore the gallery card's pixels) is the production one, not a test invention.
    NO ``meta.brand_kit`` unless the caller pinned a kit — which is exactly the hole the DAL's
    creation contract fills with the workspace's latest approved kit.
    """

    page = ad_birth_page(document_id=document_id, format_key=format_key, width=width, height=height)
    scene: dict[str, Any] = {
        "schema_version": 1,
        "meta": {
            "id": document_id,
            "title": title,
            "artifact_type": f"{format_key}_ad",
            "medium": "ad",
            "status": {"kind": "draft"},
        },
        "pages": {page["id"]: page},
        "nodes": {},
        "slots": {},
        "assets": {},
        "export_profiles": [],
    }
    if brand_kit_ref is not None:
        scene["meta"]["brand_kit"] = dict(brand_kit_ref)
    return scene


class _RecordingSceneMinter:
    """The injected engine seam, recording every kwarg the tool threaded into it."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        document_id: str,
        title: str,
        format_key: str,
        width: int,
        height: int,
        brand_kit_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "document_id": document_id,
                "title": title,
                "format_key": format_key,
                "width": width,
                "height": height,
                "brand_kit_ref": brand_kit_ref,
            }
        )
        return engine_ad_scene(
            document_id=document_id,
            title=title,
            format_key=format_key,
            width=width,
            height=height,
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
        "ad_format": "square",
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


def test_a_document_less_scene_open_births_the_ad_and_pins_the_leg(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """genad ruling 1: the leg creates its own empty ad document at the ratified format."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="birth")
            minter = _RecordingSceneMinter()
            result = await _open(seeds, _registry(seeds, minter), title="Insight Health launch ad")
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
            # EMPTY: one artboard at the format's size and nothing authored on it.
            page = next(iter(document["scene"]["pages"].values()))
            assert page["children"] == []
            assert page["size"]["output"]["raster"] == {"width_px": 1200, "height_px": 1200}

            # The leg is pinned to it at birth, and the pin is the durable row's.
            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(refs["leg_id"])
            )
            assert leg["state"] == "open_awaiting_user"
            assert leg["document_id"] == document["id"]
            assert leg["document_version_guard"] == 0

            # The PRESET resolved the pixels — the tool looked them up, not the minter.
            assert len(minter.calls) == 1
            call = minter.calls[0]
            assert call["format_key"] == "square"
            assert (call["width"], call["height"]) == AD_FORMAT_PRESETS["square"]
            assert (call["width"], call["height"]) == (1200, 1200)
            assert call["document_id"] == document["id"]
            assert call["title"] == "Insight Health launch ad"

            # The frozen bundle names the document this delegation created.
            bundle = json.loads(await seeds["storage"].get(leg["bundle_artifact_ref"]))
            assert bundle["target_document"] == {
                "document_id": document["id"],
                "version_guard": 0,
            }

    run_async(scenario())


def test_the_scene_birth_is_twin_proof_under_replay(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """§6 trap 3, for ads: a retried delegation must not mint a second ad document."""

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


def test_a_custom_format_threads_its_dimensions(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The custom escape: the agent's own width×height reach the engine unaltered."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="custom")
            minter = _RecordingSceneMinter()
            result = await _open(
                seeds,
                _registry(seeds, minter),
                ad_format="custom",
                ad_width=900,
                ad_height=450,
            )
            assert result.references["document_created"] is True
            assert len(minter.calls) == 1
            call = minter.calls[0]
            assert call["format_key"] == "custom"
            assert call["width"] == 900
            assert call["height"] == 450

            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(result.references["document_id"]),
            )
            page = next(iter(document["scene"]["pages"].values()))
            assert page["size"]["output"]["raster"] == {"width_px": 900, "height_px": 450}

    run_async(scenario())


def test_a_scene_open_without_a_format_is_refused(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The format is a loud precondition: an ad has a size, and guessing one is a lie."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="noformat")
            minter = _RecordingSceneMinter()
            with pytest.raises(PreconditionFailed) as failure:
                await _open(seeds, _registry(seeds, minter), ad_format=None)
            assert "design_leg_ad_format_required" in str(failure.value)
            assert minter.calls == []
            assert await _no_leg_and_no_document(conn, seeds)

    run_async(scenario())


def test_a_custom_format_without_dimensions_is_refused(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """``custom`` names no size by itself — a silent 1200×1200 would be a fabricated ad."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="nodims")
            minter = _RecordingSceneMinter()
            with pytest.raises(PreconditionFailed) as failure:
                await _open(seeds, _registry(seeds, minter), ad_format="custom")
            assert "design_leg_ad_format_invalid" in str(failure.value)
            assert minter.calls == []
            assert await _no_leg_and_no_document(conn, seeds)

    run_async(scenario())


def test_a_preset_with_explicit_dimensions_is_refused(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """A preset OWNS its pixels: dimensions alongside one are a malformed agent belief, and
    silently ignoring them would hide it."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="presetdims")
            minter = _RecordingSceneMinter()
            with pytest.raises(PreconditionFailed) as failure:
                await _open(seeds, _registry(seeds, minter), ad_format="story", ad_width=1000)
            assert "design_leg_ad_format_invalid" in str(failure.value)
            assert minter.calls == []
            assert await _no_leg_and_no_document(conn, seeds)

    run_async(scenario())


def test_a_web_open_with_an_ad_format_is_refused(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """No cross-kind leakage: a website has no ad format, so naming one is refused rather
    than dropped on the floor."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="webformat")
            minter = _RecordingSceneMinter()
            with pytest.raises(PreconditionFailed) as failure:
                await _open(seeds, _registry(seeds, minter), doc_kind="web", ad_format="square")
            assert "design_leg_ad_format_invalid" in str(failure.value)
            assert minter.calls == []
            assert await _no_leg_and_no_document(conn, seeds)

    run_async(scenario())


def test_an_approved_kit_is_stamped_on_the_born_ad_and_the_leg_pins_it_read_back(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The Task-1 scene stamp, THROUGH the tool: the minter returns a kit-less scene, the
    creation contract stamps the workspace's latest APPROVED kit, and the leg's D5 pin is
    that stored stamp read back — never a second, independent derivation. (The approved v1
    wins over the newer *draft* v2: approval is version-specific.)"""

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


def test_without_an_approved_kit_the_born_ad_is_unbranded_and_the_leg_carries_no_pin(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The honest fallback: no approved kit ⇒ no ``meta.brand_kit`` at all and a leg with no
    pin. Generation still works — un-branded, honestly."""

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
            assert "brand_kit" not in document["scene"]["meta"]
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


def test_the_born_ad_appears_in_the_projects_gallery_feed_as_kind_ad(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Rail derivation, for free (AD2.1): the kind-aware feed serves the newborn ad, and the
    card's size is the FORMAT's — read off the document's own page, never guessed."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="rail")
            minter = _RecordingSceneMinter()
            result = await _open(
                seeds,
                _registry(seeds, minter),
                ad_format="portrait",
                title="Insight Health launch ad",
            )

            feed = await project_design_documents(
                conn,
                workspace_id=seeds["workspace_id"],
                project_id=seeds["project_id"],
            )
            assert [item["id"] for item in feed] == [result.references["document_id"]]
            card = feed[0]
            # The wire's ``kind`` is "web" iff doc_kind is "web" — an ad card otherwise.
            assert card["doc_kind"] == "scene"
            assert card["title"] == "Insight Health launch ad"
            assert card["status"] == "draft"
            assert card["current_version"] == 0
            assert card["origin_thread_id"] == seeds["thread_id"]
            assert card["artifact_type"] == "portrait_ad"
            assert document_page_pixels(card["pages_json"]) == AD_FORMAT_PRESETS["portrait"]
            assert document_page_pixels(card["pages_json"]) == (1080, 1350)

    run_async(scenario())
