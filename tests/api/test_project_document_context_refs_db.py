"""``project_document`` context refs: the CHECK, the validation, the focus card.

One seed: a project with a plan written through the real writer, plus the smallest honest
submission scaffolding (artifact, onboarding input, thread, user, membership), so a submission
carrying a ``project_document`` ref can be inserted and re-read exactly as the fleet re-reads it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import DomainObjectRef
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_turn_submission import insert_submission, submission_context_refs
from clue_api.arv2.project_documents import (
    DEFAULT_DOCUMENT_KIND,
    ProjectPlanWrite,
    write_project_plan,
)
from clue_api.chat.composer_context import ContextReferenceError, validated_context_refs
from clue_db import db_lifespan
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

PLAN_BODY = """# Q4 expansion plan

## Outcome
Twenty qualified conversations with GI-focused ASCs by the end of the quarter.
"""


async def _seed(conn: AsyncConnection, storage: FsStorage) -> dict[str, Any]:
    ws = f"ws_test_pdref_{uuid4().hex[:12]}"
    project = await seed_project(conn, ws, name="Project document refs")
    plan = await write_project_plan(
        conn,
        storage,
        ProjectPlanWrite(
            workspace_id=ws,
            brand_id=str(project.brand_id),
            project_id=project.project_id,
            turn_id=uuid4(),
            user_id="usr_pdref",
            body=PLAN_BODY,
            expected_version=None,
        ),
    )
    sha = "b" * 64
    artifact_key = f"{ws}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 5)"
        ),
        {"key": artifact_key, "ws": ws, "sha": sha},
    )
    onboarding_input_id = uuid5(NAMESPACE_URL, f"pdref-onb:{ws}")
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
    thread_id = f"thr_pdref_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": ws, "project": project.project_id},
    )
    user_id = f"user_pdref_{uuid4().hex[:8]}"
    membership_id = f"member_pdref_{uuid4().hex[:8]}"
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
        "ws": ws,
        "project_id": project.project_id,
        "brand_id": str(project.brand_id),
        "thread_id": thread_id,
        "user_id": user_id,
        "membership_id": membership_id,
        "onboarding_input_id": onboarding_input_id,
        "artifact_key": artifact_key,
        "sha": sha,
        "plan": plan,
    }


def _submission_kwargs(seeds: dict[str, Any], tag: str) -> dict[str, Any]:
    return {
        "turn_id": uuid5(NAMESPACE_URL, f"pdref:{tag}:{seeds['ws']}"),
        "workspace_id": seeds["ws"],
        "project_id": seeds["project_id"],
        "thread_id": seeds["thread_id"],
        "submitted_by_user_id": seeds["user_id"],
        "submitted_via_membership_id": seeds["membership_id"],
        "onboarding_input_id": seeds["onboarding_input_id"],
        "message_artifact_key": seeds["artifact_key"],
        "message_sha256": seeds["sha"],
        "idempotency_key": None,
    }


def test_project_document_ref_persists_on_submission(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, FsStorage(tmp_path))
            plan = seeds["plan"]
            kwargs = _submission_kwargs(seeds, "persist")
            ref = DomainObjectRef(
                workspace_id=seeds["ws"],
                object_type="project_document",
                object_id=str(plan.document_id),
                version=plan.version,
            )
            _row, created = await insert_submission(conn, context_refs=(ref,), **kwargs)
            assert created
            refs = await submission_context_refs(
                conn, workspace_id=seeds["ws"], turn_id=kwargs["turn_id"]
            )
            assert refs == (ref,)
            await txn.rollback()

    run_async(scenario())


def test_context_ref_type_is_check_bounded(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin():
            seeds = await _seed(conn, FsStorage(tmp_path))
            kwargs = _submission_kwargs(seeds, "bad-type")
            with pytest.raises(IntegrityError):
                await insert_submission(
                    conn,
                    context_refs=(
                        DomainObjectRef(
                            workspace_id=seeds["ws"],
                            object_type="gallery_card",
                            object_id="x",
                            version=1,
                        ),
                    ),
                    **kwargs,
                )

    run_async(scenario())


def test_validated_context_refs_project_document_semantics(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            storage = FsStorage(tmp_path)
            seeds = await _seed(conn, storage)
            plan = seeds["plan"]

            def ref(object_id: str, version: int | None) -> DomainObjectRef:
                return DomainObjectRef(
                    workspace_id=seeds["ws"],
                    object_type="project_document",
                    object_id=object_id,
                    version=version,
                )

            accepted = await validated_context_refs(
                conn,
                workspace_id=seeds["ws"],
                refs=(ref(str(plan.document_id), plan.version),),
                project_id=seeds["project_id"],
            )
            assert accepted[0].version == plan.version

            other = await seed_project(conn, seeds["ws"], name="Another project")
            with pytest.raises(ContextReferenceError) as foreign:
                await validated_context_refs(
                    conn,
                    workspace_id=seeds["ws"],
                    refs=(ref(str(plan.document_id), plan.version),),
                    project_id=other.project_id,
                )
            assert foreign.value.code == "CONTEXT_REF_NOT_FOUND"

            newer = await write_project_plan(
                conn,
                storage,
                ProjectPlanWrite(
                    workspace_id=seeds["ws"],
                    brand_id=seeds["brand_id"],
                    project_id=seeds["project_id"],
                    turn_id=uuid4(),
                    user_id="usr_pdref",
                    body=PLAN_BODY + "\nMore.\n",
                    expected_version=plan.version,
                ),
            )
            assert newer.version == plan.version + 1
            # A retired version is still a row of this project, so it is stale, not absent.
            with pytest.raises(ContextReferenceError) as stale:
                await validated_context_refs(
                    conn,
                    workspace_id=seeds["ws"],
                    refs=(ref(str(plan.document_id), plan.version),),
                    project_id=seeds["project_id"],
                )
            assert stale.value.code == "CONTEXT_REF_STALE"
            await txn.rollback()

    run_async(scenario())


def test_project_document_focus_card_names_the_mounted_path(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            storage = FsStorage(tmp_path)
            seeds = await _seed(conn, storage)
            plan = seeds["plan"]
            factory = conn_session_factory(conn)

            with_storage = DbCompiledContextCardReader(conn_factory=factory, storage=storage)
            card = await with_storage.read(
                workspace_id=seeds["ws"],
                object_type="project_document",
                object_id=str(plan.document_id),
            )
            assert card is not None
            assert card.ref.version == plan.version
            body = json.loads(card.body)
            assert body["path"] == "project/plan.md"
            assert body["title"] == "Q4 expansion plan"
            # The plan body declares no front-matter ``kind``, so the row carries the default one
            # and the card echoes it rather than a name invented for the plan.
            assert body["kind"] == DEFAULT_DOCUMENT_KIND
            assert body["version"] == plan.version
            assert body["document_id"] == str(plan.document_id)
            assert "artifact_key" not in body

            without_storage = DbCompiledContextCardReader(conn_factory=factory)
            bare = await without_storage.read(
                workspace_id=seeds["ws"],
                object_type="project_document",
                object_id=str(plan.document_id),
            )
            assert bare is not None
            assert json.loads(bare.body)["title"] == "plan"

            assert (
                await with_storage.read(
                    workspace_id="ws_someone_else",
                    object_type="project_document",
                    object_id=str(plan.document_id),
                )
                is None
            )
            assert (
                await with_storage.read(
                    workspace_id=seeds["ws"], object_type="project_document", object_id="nope"
                )
                is None
            )

            # A newer version retires the tagged one. Replaying that turn still names the
            # document the user tagged, rather than falling back to the file name.
            newer = await write_project_plan(
                conn,
                storage,
                ProjectPlanWrite(
                    workspace_id=seeds["ws"],
                    brand_id=seeds["brand_id"],
                    project_id=seeds["project_id"],
                    turn_id=uuid4(),
                    user_id="usr_pdref",
                    body=PLAN_BODY + "\nMore.\n",
                    expected_version=plan.version,
                ),
            )
            assert newer.version == plan.version + 1
            retired = await with_storage.read(
                workspace_id=seeds["ws"],
                object_type="project_document",
                object_id=str(plan.document_id),
            )
            assert retired is not None
            retired_body = json.loads(retired.body)
            assert retired_body["title"] == "Q4 expansion plan"
            assert retired_body["version"] == plan.version
            assert retired_body["status"] == "superseded"
            await txn.rollback()

    run_async(scenario())
