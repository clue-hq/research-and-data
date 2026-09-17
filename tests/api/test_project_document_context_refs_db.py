"""``project_document`` context refs: the CHECK, the validation, the focus card.

One seed: a project with a plan written through the real writer, plus the smallest honest
submission scaffolding (artifact, onboarding input, thread, user, membership), so a submission
carrying a ``project_document`` ref can be inserted and re-read exactly as the fleet re-reads it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import DomainObjectRef
from clue_api.agent_turn_submission import insert_submission, submission_context_refs
from clue_api.arv2.project_documents import ProjectPlanWrite, write_project_plan
from clue_db import db_lifespan
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

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
