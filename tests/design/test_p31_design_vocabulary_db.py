"""P3.1 acceptance: the design vocabulary reaches the platform wire (PD-part3 §3, deltas 1/4/5).

Pins the three widenings end to end against the migrated DB:

* a ``design_document`` context ref survives submission persistence and reads back in
  order (the §2.4 canvas-context path — previously triple-narrowed to account|contact
  and silently dropped);
* ``validated_context_refs`` accepts a real design document (string id, NOT an entity
  UUID), refuses an unknown one, and refuses a stale ``current_version`` pin (the D5
  CAS-guard semantics);
* the L5 card reader compiles a ``design_document`` focus card whose version is the
  document's CAS counter;
* ``previous_turn_outcome`` persists on the submission row and is CHECK-bounded;
* the widened role CHECKs admit ``'design'`` (constraint-definition probe — cheaper and
  just as honest as inserting a full ``agent_turn`` row).
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import AgentRole, DomainObjectRef
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_turn_submission import insert_submission, submission_context_refs
from clue_api.chat.composer_context import ContextReferenceError, validated_context_refs
from clue_db import db_lifespan
from clue_design.documents import create_document
from tests._workspace import seed_project
from tests.design.conftest import run_async


async def _seed(conn: AsyncConnection) -> dict[str, Any]:
    ws = f"ws_test_p31_{uuid4().hex[:12]}"
    project = await seed_project(conn, ws, name="P31 vocab")
    document = await create_document(
        conn,
        workspace_id=ws,
        scene={"meta": {"id": f"doc_p31_{uuid4().hex[:8]}", "title": "P31 doc"}, "pages": {}},
    )
    # A submission FKs a captured message artifact and an onboarding_input row; seed the
    # smallest honest versions of both.
    sha = "a" * 64
    artifact_key = f"{ws}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 5)"
        ),
        {"key": artifact_key, "ws": ws, "sha": sha},
    )
    onboarding_input_id = uuid5(NAMESPACE_URL, f"p31-onb:{ws}")
    await conn.execute(
        text(
            "INSERT INTO onboarding_input (id, workspace_id, brand_id, kind, artifact_key, "
            " content_sha256, actor) "
            "VALUES (:id, :ws, :brand, 'user_turn', :key, :sha, 'human')"
        ),
        {
            "id": onboarding_input_id,
            "ws": ws,
            "brand": project.brand_id,
            "key": artifact_key,
            "sha": sha,
        },
    )
    thread_id = f"thr_p31_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": ws, "project": project.project_id},
    )
    user_id = f"user_p31_{uuid4().hex[:8]}"
    membership_id = f"member_p31_{uuid4().hex[:8]}"
    await conn.execute(
        text("INSERT INTO platform_user (user_id) VALUES (:user)"), {"user": user_id}
    )
    await conn.execute(
        text(
            "INSERT INTO workspace_membership (membership_id, workspace_id, user_id, "
            " role_key, status, activated_at) "
            "VALUES (:membership, :ws, :user, 'owner', 'active', now())"
        ),
        {"membership": membership_id, "ws": ws, "user": user_id},
    )
    return {
        "user_id": user_id,
        "membership_id": membership_id,
        "ws": ws,
        "project_id": project.project_id,
        "document": document,
        "onboarding_input_id": onboarding_input_id,
        "artifact_key": artifact_key,
        "sha": sha,
        "thread_id": thread_id,
    }


def test_design_document_ref_and_outcome_persist_on_submission(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn)
            doc_id = seeds["document"]["id"]
            turn_id = uuid5(NAMESPACE_URL, f"p31:{seeds['ws']}")
            row, created = await insert_submission(
                conn,
                turn_id=turn_id,
                workspace_id=seeds["ws"],
                project_id=seeds["project_id"],
                thread_id=seeds["thread_id"],
                submitted_by_user_id=seeds["user_id"],
                submitted_via_membership_id=seeds["membership_id"],
                onboarding_input_id=seeds["onboarding_input_id"],
                message_artifact_key=seeds["artifact_key"],
                message_sha256=seeds["sha"],
                idempotency_key=None,
                context_refs=(
                    DomainObjectRef(
                        workspace_id=seeds["ws"],
                        object_type="design_document",
                        object_id=doc_id,
                        version=1,
                    ),
                ),
                previous_turn_outcome="clarification_requested",
            )
            assert created and row.previous_turn_outcome == "clarification_requested"
            refs = await submission_context_refs(conn, workspace_id=seeds["ws"], turn_id=turn_id)
            assert [(r.object_type, r.object_id) for r in refs] == [("design_document", doc_id)]
            await txn.rollback()

    run_async(scenario())


def test_previous_turn_outcome_vocabulary_is_check_bounded(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin():
            seeds = await _seed(conn)
            with pytest.raises(IntegrityError):
                await insert_submission(
                    conn,
                    turn_id=uuid5(NAMESPACE_URL, f"p31-bad:{seeds['ws']}"),
                    workspace_id=seeds["ws"],
                    project_id=seeds["project_id"],
                    thread_id=seeds["thread_id"],
                    submitted_by_user_id=seeds["user_id"],
                    submitted_via_membership_id=seeds["membership_id"],
                    onboarding_input_id=seeds["onboarding_input_id"],
                    message_artifact_key=seeds["artifact_key"],
                    message_sha256=seeds["sha"],
                    idempotency_key=None,
                    previous_turn_outcome="not_a_vocabulary_value",
                )

    run_async(scenario())


def test_validated_context_refs_design_document_semantics(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn)
            doc = seeds["document"]

            def ref(object_id: str, version: int | None) -> DomainObjectRef:
                return DomainObjectRef(
                    workspace_id=seeds["ws"],
                    object_type="design_document",
                    object_id=object_id,
                    version=version,
                )

            # A fresh document is v0 and DomainObjectRef pins are >= 1, so: unpinned
            # accepts; then bump the CAS counter and accept an exact pin.
            accepted = await validated_context_refs(
                conn, workspace_id=seeds["ws"], refs=(ref(doc["id"], None),)
            )
            assert accepted[0].object_id == doc["id"]
            await conn.execute(
                text(
                    "UPDATE design_document SET current_version = 3 "
                    "WHERE id = :id AND workspace_id = :ws"
                ),
                {"id": doc["id"], "ws": seeds["ws"]},
            )
            pinned = await validated_context_refs(
                conn, workspace_id=seeds["ws"], refs=(ref(doc["id"], 3),)
            )
            assert pinned[0].version == 3

            with pytest.raises(ContextReferenceError) as missing:
                await validated_context_refs(
                    conn, workspace_id=seeds["ws"], refs=(ref("doc_ghost", None),)
                )
            assert missing.value.code == "CONTEXT_REF_NOT_FOUND"

            with pytest.raises(ContextReferenceError) as stale:
                await validated_context_refs(
                    conn,
                    workspace_id=seeds["ws"],
                    refs=(ref(doc["id"], doc["current_version"] + 41),),
                )
            assert stale.value.code == "CONTEXT_REF_STALE"
            await txn.rollback()

    run_async(scenario())


def test_card_reader_compiles_design_document_focus_card(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn)
            doc = seeds["document"]

            def conn_factory():  # the reader takes a CM factory; reuse this txn's conn
                class _Held:
                    async def __aenter__(self) -> AsyncConnection:
                        return conn

                    async def __aexit__(self, *exc: object) -> None:
                        return None

                return _Held()

            reader = DbCompiledContextCardReader(conn_factory=conn_factory)
            # v0 (never-written) documents compile as unversioned cards; a written
            # document's card pins the CAS counter.
            card = await reader.read(
                workspace_id=seeds["ws"],
                object_type="design_document",
                object_id=doc["id"],
            )
            assert card is not None and card.ref.version is None
            await conn.execute(
                text(
                    "UPDATE design_document SET current_version = 3 "
                    "WHERE id = :id AND workspace_id = :ws"
                ),
                {"id": doc["id"], "ws": seeds["ws"]},
            )
            card = await reader.read(
                workspace_id=seeds["ws"],
                object_type="design_document",
                object_id=doc["id"],
            )
            assert card is not None and card.ref.version == 3
            assert doc["id"] in card.body and "current_version" in card.body
            # Unknown ids stay a silent None (the L5 drop rule), never an exception.
            assert (
                await reader.read(
                    workspace_id=seeds["ws"],
                    object_type="design_document",
                    object_id="doc_ghost",
                )
                is None
            )
            await txn.rollback()

    run_async(scenario())


def test_role_checks_admit_design(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    assert AgentRole.DESIGN.value == "design"

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            for constraint in ("agent_turn_role", "agent_plan_role", "agent_delegation_roles"):
                definition = (
                    await conn.execute(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conname = :name"
                        ),
                        {"name": constraint},
                    )
                ).scalar_one()
                assert "'design'" in definition, f"{constraint} does not admit 'design'"
                assert "'onboarding_synthesis'" in definition, (
                    f"{constraint} does not admit 'onboarding_synthesis'"
                )

    run_async(scenario())
