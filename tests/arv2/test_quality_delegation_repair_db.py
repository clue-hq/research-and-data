"""Explicit, scoped repair recovers a retained delegation without rerunning research."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.person_research_brief import read_person_brief
from clue_api.arv2.quality_catalog import bundle_pin, load_quality_resources
from clue_api.arv2.quality_delegation_repair import restore_person_delegation
from clue_api.arv2.quality_json_dossier import DossierInput, FinishDossierTool
from clue_api.arv2.quality_person_release import read_parent_dossier
from tests.arv2.test_quality_json_dossier_db import invoke
from tests.arv2.test_quality_person_release_db import initial
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_recover_known_self_parent_corruption_and_replay(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET input_refs=CAST(:refs AS jsonb), "
                    "profile_sha256=:pin WHERE job_id=:id"
                ),
                {
                    "id": child.job_id,
                    "pin": bundle_pin(load_quality_resources("arv2-person", version=24)),
                    "refs": json.dumps(
                        {"parent_job_id": str(child.job_id), "unrelated": "preserve"}
                    ),
                },
            )
            with pytest.raises(ValueError, match="no available completed dossier"):
                await read_parent_dossier(conn, storage, child, cid)
            result = await restore_person_delegation(conn, storage, child, cid)
            assert result["changed"]
            refs = result["input_refs"]
            assert refs["parent_job_id"] == str(parent.job_id)
            assert refs["generation_id"] == str(gen.generation_id)
            assert refs["quality_recipe_version"] == 24 and refs["unrelated"] == "preserve"
            fixed = replace(child, input_refs=refs)
            assert (await read_parent_dossier(conn, storage, fixed, cid))["parent_job_id"] == str(
                parent.job_id
            )
            assert (await read_person_brief(conn, storage, fixed, context_id=cid))["brief"]
            assert not (await restore_person_delegation(conn, storage, fixed, cid))["changed"]
            for bad in (replace(child, contact_id=uuid4()), replace(child, workspace_id="foreign")):
                with pytest.raises(ValueError, match="No scoped child"):
                    await restore_person_delegation(conn, storage, bad, cid)
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET input_refs=input_refs || "
                    "jsonb_build_object('parent_job_id',CAST(:parent AS text)) WHERE job_id=:id"
                ),
                {"id": child.job_id, "parent": str(uuid4())},
            )
            with pytest.raises(ValueError, match="disagrees with retained brief"):
                await restore_person_delegation(conn, storage, child, cid)

    run_async(case())
