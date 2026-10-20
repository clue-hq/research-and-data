"""``open_design_leg@5`` — a list of artifacts, N births, the account stamp.

Spec ``docs/superpowers/specs/archive/2026-09-19-multi-artifact-design-legs-design.md`` §3.1/§3.2/§3.6:
one chat message may ask for MANY design artifacts, so one delegation opens ONE leg holding a
SET of documents. The properties pinned here:

* **N artifacts ⇒ N born documents on one leg, in ONE transaction** — each item's title and its
  own words (``note``) land on the leg's child rows in position order;
* **the ids are derived from (leg, position)**, and position 0 keeps the @4 derivation byte for
  byte, so a single-item leg mints exactly the id it always did and a retried delegation
  converges on the same N rows;
* **a document born for a tagged research account carries the design-plane account** (§3.6) —
  validated as an ``account_entity`` of this workspace that is on this project, resolved to a
  ``design_account`` and stamped on the document;
* **the bundle records the item list**, and its byte cap grows with the item count so a large
  batch is not refused for being large.

All writes run in rolled-back transactions against the session-migrated DB; only the ENGINE
round-trip is faked (the genad file's ``_RecordingSceneMinter``), so these tests need no Rust
binary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.design_leg_tools import (
    DesignArtifactSpec,
    OpenDesignLegTool,
    delegation_bundle_cap,
    derive_leg_document_id,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_design import legs as design_legs
from clue_design.documents import create_document, get_document
from clue_research.membership import ensure_project_account
from clue_toolbelt import PreconditionFailed, ToolContext, ToolRegistry, invoke_tool
from tests.api.test_genad_leg_document_birth_db import (
    _RecordingSceneMinter,
    _seed_conversation,
)
from tests.api.test_genweb_leg_document_birth_db import engine_web_doc
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
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
        "brief": "1:1 LinkedIn ads for the tagged accounts.",
        "doc_kind": "scene",
    }
    args.update(overrides)
    return await invoke_tool(
        registry,
        "open_design_leg",
        args,
        _context(seeds),
        idempotency_ttl_s=60,
    )


async def _seed_account_entity(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    name: str,
    domain: str | None,
) -> UUID:
    """One live research account in this workspace (the tag's subject)."""

    entity_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO account_entity (id, canonical_name, primary_domain, status, "
            " workspace_id) "
            "VALUES (CAST(:id AS uuid), :name, :domain, 'active', :ws)"
        ),
        {"id": str(entity_id), "name": name, "domain": domain, "ws": workspace_id},
    )
    return entity_id


async def _bundle(seeds: dict[str, Any], artifact_key: str) -> dict[str, Any]:
    return json.loads(await seeds["storage"].get(artifact_key))


def test_three_artifacts_birth_three_documents_on_one_leg(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """§3.1: one message, three ads — one leg, three documents, one transaction."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="three")
            minter = _RecordingSceneMinter()
            result = await _open(
                seeds,
                _registry(seeds, minter),
                brief="1:1 LinkedIn ads",
                artifacts=[
                    {"title": "Apollo ad", "note": "for Apollo Clinics (apollo.example)"},
                    {"title": "Mercy ad", "note": "for Mercy Health"},
                    {"title": "Premier ad", "note": "for Premier Gastro"},
                ],
            )
            refs = result.references
            leg_id = str(refs["leg_id"])
            expected = [derive_leg_document_id(leg_id=leg_id, position=i) for i in range(3)]
            assert list(refs["document_ids"]) == expected
            # Position 0 is the leg's pin — every single-document reader keeps working.
            assert refs["document_id"] == expected[0]
            assert refs["document_created"] is True
            assert refs["created"] is True

            rows = await design_legs.list_leg_documents(
                conn, workspace_id=seeds["workspace_id"], leg_id=leg_id
            )
            assert [(r["position"], r["title"], r["note"]) for r in rows] == [
                (0, "Apollo ad", "for Apollo Clinics (apollo.example)"),
                (1, "Mercy ad", "for Mercy Health"),
                (2, "Premier ad", "for Premier Gastro"),
            ]
            # Three real documents, each pageless and draft, all born under one kit.
            for row in rows:
                document = await get_document(
                    conn,
                    workspace_id=seeds["workspace_id"],
                    document_id=str(row["document_id"]),
                )
                assert document["doc_kind"] == "scene"
                assert document["current_version"] == 0
                assert document["scene"]["pages"] == {}
                assert document["account_id"] is None
            assert [call["title"] for call in minter.calls] == [
                "Apollo ad",
                "Mercy ad",
                "Premier ad",
            ]

            leg = await design_legs.get_leg(conn, workspace_id=seeds["workspace_id"], leg_id=leg_id)
            assert leg["document_id"] == expected[0]
            assert leg["document_version_guard"] == 0

            bundle = await _bundle(seeds, str(refs["bundle_artifact_key"]))
            assert [a["position"] for a in bundle["artifacts"]] == [0, 1, 2]
            assert bundle["artifacts"][1] == {
                "position": 1,
                "title": "Mercy ad",
                "note": "for Mercy Health",
                "account_id": None,
                "document_id": expected[1],
            }

    run_async(scenario())


def test_position_zero_keeps_the_at4_document_id() -> None:
    """A single-item leg mints the id it always has — the @4 derivation, byte for byte."""

    from uuid import NAMESPACE_URL, uuid5

    assert derive_leg_document_id(leg_id="leg-x") == derive_leg_document_id(
        leg_id="leg-x", position=0
    )
    namespace = uuid5(NAMESPACE_URL, "clue-design-leg-document")
    assert derive_leg_document_id(leg_id="leg-x") == f"doc_{uuid5(namespace, 'leg-x').hex}"
    at_one = derive_leg_document_id(leg_id="leg-x", position=1)
    assert at_one == f"doc_{uuid5(namespace, 'leg-x:1').hex}"


def test_a_replayed_multi_delegation_converges_on_the_same_rows(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Twin-proofing, widened: a retried batch mints no second document and no second child row."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="replay")
            minter = _RecordingSceneMinter()
            registry = _registry(seeds, minter)
            artifacts = [
                {"title": "Apollo ad", "note": "for Apollo Clinics"},
                {"title": "Mercy ad", "note": "for Mercy Health"},
                {"title": "Premier ad", "note": "for Premier Gastro"},
            ]
            first = await _open(seeds, registry, artifacts=artifacts)
            replay = await _open(seeds, registry, artifacts=artifacts)

            assert replay.references["created"] is False
            assert replay.references["document_created"] is False
            assert list(replay.references["document_ids"]) == list(first.references["document_ids"])
            assert replay.references["document_id"] == first.references["document_id"]
            assert len(minter.calls) == 3

            children = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM design_leg_document WHERE leg_id = CAST(:leg AS uuid)"
                    ),
                    {"leg": str(first.references["leg_id"])},
                )
            ).scalar_one()
            assert int(children) == 3
            documents = (
                await conn.execute(
                    text("SELECT count(*) FROM design_document WHERE workspace_id = :ws"),
                    {"ws": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert int(documents) == 3

    run_async(scenario())


def test_a_document_born_for_a_research_account_carries_the_design_account(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """§3.6: the tagged account rides the delegation for the durable link and the gallery."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="account")
            entity_id = await _seed_account_entity(
                conn,
                workspace_id=seeds["workspace_id"],
                name="Apollo Clinics",
                domain="apollo.example",
            )
            await ensure_project_account(
                conn,
                workspace_id=seeds["workspace_id"],
                project_id=seeds["project_id"],
                account_entity_id=entity_id,
                added_via="manual",
            )
            minter = _RecordingSceneMinter()
            result = await _open(
                seeds,
                _registry(seeds, minter),
                artifacts=[
                    {"title": "Apollo ad", "note": "for Apollo", "account_id": str(entity_id)},
                    {"title": "Generic ad", "note": "no account"},
                ],
            )
            refs = result.references
            stamped = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(refs["document_ids"][0]),
            )
            assert stamped["account_id"] is not None
            design_account = (
                (
                    await conn.execute(
                        text(
                            "SELECT account_entity_id, name, domain FROM design_account "
                            "WHERE account_id = :a AND workspace_id = :ws"
                        ),
                        {"a": stamped["account_id"], "ws": seeds["workspace_id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert UUID(str(design_account["account_entity_id"])) == entity_id
            assert design_account["name"] == "Apollo Clinics"
            assert design_account["domain"] == "apollo.example"

            # A generic variant has no account and no stamp.
            generic = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(refs["document_ids"][1]),
            )
            assert generic["account_id"] is None

            bundle = await _bundle(seeds, str(refs["bundle_artifact_key"]))
            assert bundle["artifacts"][0]["account_id"] == str(entity_id)
            assert bundle["artifacts"][1]["account_id"] is None

    run_async(scenario())


def test_an_account_off_the_project_is_refused(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The same containment the composer's tag validation applies — refused, never guessed."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="offproject")
            entity_id = await _seed_account_entity(
                conn,
                workspace_id=seeds["workspace_id"],
                name="Stranger Health",
                domain="stranger.example",
            )
            minter = _RecordingSceneMinter()
            with pytest.raises(PreconditionFailed) as failure:
                await _open(
                    seeds,
                    _registry(seeds, minter),
                    artifacts=[{"title": "Stranger ad", "account_id": str(entity_id)}],
                )
            assert "design_leg_account_not_on_project" in str(failure.value)
            assert minter.calls == []
            assert (
                await design_legs.get_open_leg_for_thread(
                    conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
                )
                is None
            )
            born = (
                await conn.execute(
                    text("SELECT count(*) FROM design_document WHERE workspace_id = :ws"),
                    {"ws": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert int(born) == 0

    run_async(scenario())


def test_an_unknown_account_is_refused(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """An id naming no live account of this workspace is a refusal, not a silent unstamped birth."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="unknown")
            minter = _RecordingSceneMinter()
            with pytest.raises(PreconditionFailed) as absent:
                await _open(
                    seeds,
                    _registry(seeds, minter),
                    artifacts=[{"title": "Ghost ad", "account_id": str(uuid4())}],
                )
            assert "design_leg_account_not_found" in str(absent.value)
            with pytest.raises(PreconditionFailed) as malformed:
                await _open(
                    seeds,
                    _registry(seeds, minter),
                    artifacts=[{"title": "Ghost ad", "account_id": "not-a-uuid"}],
                )
            assert "design_leg_account_not_found" in str(malformed.value)
            assert minter.calls == []

    run_async(scenario())


def test_artifacts_and_document_id_are_exclusive_and_a_single_item_is_the_old_shape(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """A leg either pins an existing artifact or births a list — never both. And one item
    births exactly what @4's ``title`` did: the same derived id, the same title."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="exclusive")
            existing = await create_document(
                conn,
                workspace_id=seeds["workspace_id"],
                scene={"meta": {"id": f"doc_ex_{uuid4().hex[:8]}", "title": "Existing"}},
            )
            minter = _RecordingSceneMinter()
            registry = _registry(seeds, minter)
            with pytest.raises(PreconditionFailed) as both:
                await _open(
                    seeds,
                    registry,
                    document_id=existing["id"],
                    artifacts=[{"title": "A new ad"}],
                )
            assert "design_leg_artifacts_with_document" in str(both.value)

            result = await _open(seeds, registry, artifacts=[{"title": "Insight Health launch ad"}])
            refs = result.references
            assert refs["document_id"] == derive_leg_document_id(leg_id=str(refs["leg_id"]))
            assert list(refs["document_ids"]) == [refs["document_id"]]
            document = await get_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=str(refs["document_id"]),
            )
            assert document["title"] == "Insight Health launch ad"
            rows = await design_legs.list_leg_documents(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(refs["leg_id"])
            )
            assert [(r["position"], r["note"]) for r in rows] == [(0, "")]

    run_async(scenario())


def test_a_document_less_open_without_artifacts_is_refused(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """@5 retired the top-level ``title``: a document-less open must name its items."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="noitems")
            minter = _RecordingSceneMinter()
            with pytest.raises(PreconditionFailed) as failure:
                await _open(seeds, _registry(seeds, minter))
            assert "design_leg_artifacts_required" in str(failure.value)
            assert minter.calls == []

    run_async(scenario())


def test_a_leg_pinning_an_existing_document_records_it_at_position_zero(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Every leg has its set: the pin path writes the one child row too (§3.2)."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="pin")
            existing = await create_document(
                conn,
                workspace_id=seeds["workspace_id"],
                scene={"meta": {"id": f"doc_pin_{uuid4().hex[:8]}", "title": "Launch artboard"}},
            )
            minter = _RecordingSceneMinter()
            result = await _open(
                seeds, _registry(seeds, minter), document_id=existing["id"], doc_kind=None
            )
            refs = result.references
            assert refs["document_created"] is False
            assert list(refs["document_ids"]) == [existing["id"]]
            rows = await design_legs.list_leg_documents(
                conn, workspace_id=seeds["workspace_id"], leg_id=str(refs["leg_id"])
            )
            assert [(r["position"], r["document_id"], r["note"]) for r in rows] == [
                (0, existing["id"], "")
            ]
            bundle = await _bundle(seeds, str(refs["bundle_artifact_key"]))
            assert bundle["artifacts"] == [
                {
                    "position": 0,
                    "title": "Launch artboard",
                    "note": "",
                    "account_id": None,
                    "document_id": existing["id"],
                }
            ]

    run_async(scenario())


def test_colliding_titles_are_suffixed_so_every_document_is_addressable(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """§3.1: distinct per item — the engine appends a suffix only when two items collide."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="collide")
            minter = _RecordingSceneMinter()
            result = await _open(
                seeds,
                _registry(seeds, minter),
                artifacts=[
                    {"title": "Launch ad", "note": "bold"},
                    {"title": "Launch ad", "note": "quiet"},
                    {"title": "Launch ad", "note": "proof-led"},
                    {"title": "Other ad", "note": "different"},
                ],
            )
            rows = await design_legs.list_leg_documents(
                conn,
                workspace_id=seeds["workspace_id"],
                leg_id=str(result.references["leg_id"]),
            )
            assert [row["title"] for row in rows] == [
                "Launch ad",
                "Launch ad (2)",
                "Launch ad (3)",
                "Other ad",
            ]

    run_async(scenario())


def test_the_bundle_cap_grows_with_the_item_count() -> None:
    """§3.1: the shared half of L3 is kept for one artifact; each further item adds room."""

    assert delegation_bundle_cap(0) == 24_000
    assert delegation_bundle_cap(1) == 24_000
    assert delegation_bundle_cap(20) == 24_000 + 1_500 * 19


def test_an_artifact_spec_forbids_unknown_keys() -> None:
    """The item model is closed: a misremembered key is a loud refusal, never a dropped belief."""

    spec = DesignArtifactSpec(title="  Apollo ad  ")
    assert spec.title == "Apollo ad"
    assert spec.note == ""
    assert spec.account_id is None
    with pytest.raises(ValueError):
        DesignArtifactSpec(title="Apollo ad", ad_format="square")  # type: ignore[call-arg]
