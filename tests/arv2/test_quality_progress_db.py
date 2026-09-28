"""Milestones follow real dossier imports and owner page publication, not model claims."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_json_dossier import (
    DossierInput,
    FinishDossierTool,
    SaveDossierSectionTool,
    SaveSectionInput,
)
from clue_api.arv2.quality_owned_narrative import (
    ReadNarrativeInput,
    ReadNarrativeInputsTool,
    WriteResearchNarrativeTool,
)
from clue_api.arv2.quality_progress import delivery_progress
from clue_api.arv2.research_operations import OperationScope
from clue_api.frontend_read.v1_shared import arv2_research_status_for
from clue_core import ExecutionId, OperationId
from tests.arv2.test_dossier_json import finding
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_json_dossier_db import invoke
from tests.arv2.test_quality_owned_narrative_db import call, draft
from tests.arv2.test_quality_person_release_db import initial
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_committed_draft_import_and_publication_determine_product_completion(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            job, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            job = replace(job, input_refs={"quality_recipe_version": 20})

            async def read():
                return (
                    await delivery_progress(
                        conn, workspace_id=job.workspace_id, job_ids=[job.job_id]
                    )
                )[job.job_id]

            assert (await read()).stage == "compiling_findings"
            await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert (await read()).stage == "writing_narrative"
            assert not (await read()).ready
            await load_display_recipes(conn)
            meta = await call(ReadNarrativeInputsTool, job, storage, ctx, ReadNarrativeInput())
            await call(WriteResearchNarrativeTool, job, storage, ctx, draft(meta))
            assert (await read()).ready
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET status='needs_review', "
                    "failure_code='finalize_rejected', finished_at=now() WHERE job_id=:j"
                ),
                {"j": job.job_id},
            )
            assert (await read()).ready
            statuses = await arv2_research_status_for(
                conn, workspace_id=job.workspace_id, account_ids=[job.account_id]
            )
            assert statuses[job.account_id] == ("completed", False)
            assert (
                await conn.execute(
                    text("SELECT status FROM arv2_research_job WHERE job_id=:j"),
                    {"j": job.job_id},
                )
            ).scalar_one() == "needs_review"
            assert (
                await delivery_progress(conn, workspace_id="wrong-workspace", job_ids=[job.job_id])
                == {}
            )
            await conn.execute(
                text(
                    "UPDATE artifact SET expires_at=now()-interval '1 second' "
                    "WHERE workspace_id=:ws AND storage_key IN ("
                    "SELECT output_artifact_key FROM display_block WHERE subject_id=:id)"
                ),
                {"ws": job.workspace_id, "id": job.account_id},
            )
            assert not (await read()).ready
            await conn.execute(
                text("UPDATE artifact SET expires_at=NULL WHERE workspace_id=:ws"),
                {"ws": job.workspace_id},
            )
            assert (await read()).ready
            await conn.execute(
                text(
                    "DELETE FROM arv2_research_page_current "
                    "WHERE subject_id=:id AND page='insights'"
                ),
                {"id": job.account_id},
            )
            assert not (await read()).ready

    run_async(case())


def test_contact_completion_requires_its_own_page_and_available_dossier(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            parent = replace(parent, input_refs={"quality_recipe_version": 20})
            child = replace(child, input_refs={**child.input_refs, "quality_recipe_version": 20})
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            await load_display_recipes(conn)
            meta = await call(ReadNarrativeInputsTool, parent, storage, ctx, ReadNarrativeInput())
            await call(WriteResearchNarrativeTool, parent, storage, ctx, draft(meta))
            op = OperationScope(child.workspace_id, child.run_id, child.job_id, child.account_id)
            eid = await execution(conn, op, child.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=eid,
                context_id=cid,
                role="account_research",
                limits=Allowance(100, 100, 10),
            )
            personctx = replace(
                ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4())
            )
            await invoke(
                SaveDossierSectionTool,
                child,
                storage,
                personctx,
                SaveSectionInput(section="Voice", findings=[finding(source_paths=[path])]),
            )

            async def read():
                return (
                    await delivery_progress(
                        conn, workspace_id=child.workspace_id, job_ids=[child.job_id]
                    )
                )[child.job_id]

            assert not (await read()).ready  # Account pages cannot complete a person job.
            assert (await read()).subject_name == "Fixture researcher"
            await invoke(FinishDossierTool, child, storage, personctx, DossierInput())
            assert not (await read()).ready
            meta = await call(
                ReadNarrativeInputsTool, child, storage, personctx, ReadNarrativeInput()
            )
            await call(WriteResearchNarrativeTool, child, storage, personctx, draft(meta, True))
            assert (await read()).ready
            await conn.execute(
                text(
                    "UPDATE artifact SET expires_at=now()-interval '1 second' "
                    "WHERE workspace_id=:ws AND storage_key=(SELECT storage_key "
                    "FROM artifact_reference WHERE workspace_id=:ws "
                    "AND reference_kind='research_dossier_progress' "
                    "AND reference_id LIKE :prefix ORDER BY reference_id DESC LIMIT 1)"
                ),
                {"ws": child.workspace_id, "prefix": str(child.job_id) + ":%"},
            )
            assert not (await read()).ready  # Never fall back to an older, available snapshot.

    run_async(case())
