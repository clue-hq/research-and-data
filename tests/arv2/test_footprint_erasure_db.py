"""A person's saved social history is reachable by the DSAR subject erasure.

``AgentPrivacyService.erase_subject`` erases every artifact bound to the person in
``agent_artifact_subject``. The evidence wrapper binds each saved job result there, so a
person job's saved posts go with an erasure. The speaker check stores no personal text.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import text

from clue_api.arv2.quality_provider_tools import AcquireResearchInputV3, AcquireResearchToolV3
from clue_api.arv2.transport import ScriptedTransport
from clue_research.identity import insert_contact_entity
from tests.arv2.test_acquire_v3_db import bound, li_page
from tests.arv2.test_media_speaker_db import ANSWER
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_person_posts_are_bound_to_the_person_for_erasure(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            wire = ScriptedTransport([li_page()])
            rt, ctx, *_ = await bound(conn, tmp_path, wire=wire)
            contact = await insert_contact_entity(
                conn, account_entity_id=rt.scope.account_id, full_name="Ada Example"
            )
            rt.scope = replace(rt.scope, subject_kind="person", contact_id=contact)
            result = await AcquireResearchToolV3(rt).invoke(
                AcquireResearchInputV3(
                    operation="linkedin_activity",
                    arguments={"profile": "https://www.linkedin.com/in/ada", "kind": "posts"},
                ),
                ctx,
            )
            assert result.references["status"] == "completed"
            key = (
                await conn.execute(
                    text("SELECT artifact_key FROM arv2_research_operation WHERE operation_id=:id"),
                    {"id": result.references["operation_id"]},
                )
            ).scalar_one()
            bound_to = (
                (
                    await conn.execute(
                        text(
                            "SELECT subject_entity_id FROM agent_artifact_subject "
                            "WHERE workspace_id=:ws AND artifact_key=:key"
                        ),
                        {"ws": rt.scope.workspace_id, "key": key},
                    )
                )
                .scalars()
                .all()
            )
            assert contact in bound_to

    run_async(case())


def test_speaker_check_holds_no_personal_text():
    stored = ANSWER.model_dump(mode="json")
    assert set(stored) == {
        "state",
        "presence",
        "presence_probabilities",
        "is_speaking",
        "label",
        "label_probabilities",
        "windows",
        "model",
        "cost_usd",
        "reason",
    }
