"""People launched on their own join the account's research, so its rewrite hears from them."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_store import create_job, create_run, read_run
from clue_api.arv2.evidence_paths import source_path
from clue_api.arv2.page_writer_runtime import committee_people
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_generation import (
    attach_to_account_research,
    read_generation,
    record_child_result,
)
from clue_api.arv2.quality_json_dossier import (
    DossierInput,
    FinishDossierTool,
    SaveDossierSectionTool,
    SaveSectionInput,
)
from clue_api.arv2.research_operations import OperationScope
from clue_core import ExecutionId, OperationId
from clue_research.identity import insert_contact_entity
from tests.arv2.account_research_job_helpers import finish_seeded_job
from tests.arv2.test_dossier_json import finding
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_json_dossier_db import invoke
from tests.arv2.test_quality_person_release_db import initial
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def account_recipe(conn, job_id, version):
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET input_refs=COALESCE(input_refs,'{}'::jsonb) || "
            "jsonb_build_object('quality_recipe_version', CAST(:v AS int)) WHERE job_id=:id"
        ),
        {"id": job_id, "v": version},
    )


async def independent_person(conn, parent):
    """A person launched on their own: a run of their own on the same project and context."""
    run = await read_run(conn, run_id=parent.run_id)
    assert run is not None
    other = replace(run, run_id=uuid4(), request_sha256=uuid4().hex * 2)
    await create_run(conn, other)
    contact = await insert_contact_entity(
        conn, account_entity_id=parent.account_id, full_name="Independent person"
    )
    job_id = uuid4()
    refs = {"quality_recipe_version": 25}
    await create_job(
        conn,
        job_id=job_id,
        run_id=other.run_id,
        workspace_id=parent.workspace_id,
        account_entity_id=parent.account_id,
        subject_type="person",
        subject_entity_id=contact,
        profile_sha256="a" * 64,
        input_refs=refs,
    )
    return replace(
        parent,
        run_id=other.run_id,
        job_id=job_id,
        subject_kind="person",
        contact_id=contact,
        input_refs=refs,
    )


def test_an_independent_person_joins_the_accounts_recipe_25_research(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            parent, _child, cid, _storage, _ctx, gen, _path = await initial(conn, tmp_path)
            person = await independent_person(conn, parent)
            attach = {
                "workspace_id": parent.workspace_id,
                "project_id": parent.project_id,
                "account_id": parent.account_id,
                "context_id": cid,
                "job_id": person.job_id,
            }
            # Research from before the separate writer keeps its own reconciliation untouched.
            await account_recipe(conn, parent.job_id, 24)
            assert await attach_to_account_research(conn, **attach) is None
            await account_recipe(conn, parent.job_id, 25)
            joined = await attach_to_account_research(conn, **attach)
            assert joined is not None and joined.generation_id == gen.generation_id
            assert await attach_to_account_research(conn, **attach) is not None  # replay is safe
            children = (
                await conn.execute(
                    text("SELECT count(*) FROM arv2_generation_child WHERE job_id=:id"),
                    {"id": person.job_id},
                )
            ).scalar_one()
            assert children == 1
            # Another context's research is not this person's account research.
            assert (
                await attach_to_account_research(conn, **{**attach, "context_id": uuid4()}) is None
            )

    run_async(case())


def test_the_attached_persons_result_reaches_the_account_rewrite(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            parent, _child, cid, storage, ctx, gen, _path = await initial(conn, tmp_path)
            await account_recipe(conn, parent.job_id, 25)
            person = await independent_person(conn, parent)
            await attach_to_account_research(
                conn,
                workspace_id=parent.workspace_id,
                project_id=parent.project_id,
                account_id=parent.account_id,
                context_id=cid,
                job_id=person.job_id,
            )
            op = OperationScope(
                person.workspace_id, person.run_id, person.job_id, person.account_id
            )
            eid = await execution(conn, op, person.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=eid,
                context_id=cid,
                role="account_research",
                limits=Allowance(100, 100, 10),
            )
            source = await save(conn, storage, op, "We keep the original public wording.")
            own_path = source_path(source.model_dump())
            personctx = replace(
                ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4())
            )
            await invoke(
                SaveDossierSectionTool,
                person,
                storage,
                personctx,
                SaveSectionInput(section="Voice", findings=[finding(source_paths=[own_path])]),
            )
            finished = await invoke(FinishDossierTool, person, storage, personctx, DossierInput())
            assert finished["finished"], finished
            before = (
                await read_generation(
                    conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
                )
            ).input_revision
            await finish_seeded_job(
                conn,
                job_id=person.job_id,
                status="completed",
                finalization={"summary": "done"},
                failure_code=None,
                model_rounds=1,
                tool_calls=1,
                cost_usd=0,
                credits=0,
                media_seconds=0,
            )
            await record_child_result(conn, workspace_id=person.workspace_id, job_id=person.job_id)
            after = await read_generation(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            assert after.input_revision > before
            people = await committee_people(conn, storage, parent, cid)
            attached = next(p for p in people if p.contact_id == person.contact_id)
            assert attached.dossier is not None
            assert attached.dossier["job_id"] == str(person.job_id)

    run_async(case())


def test_a_person_launch_joins_the_accounts_research(tmp_path):
    from uuid import UUID

    from clue_api.arv2.account_research_catalog import (
        arv2_account_profile_sha256,
        arv2_person_profile_sha256,
    )
    from clue_api.arv2.account_research_launch import (
        Arv2PersonLaunchRequest,
        launch_arv2_account_research,
        launch_arv2_person_research,
    )
    from clue_api.arv2.quality_generation import ensure_generation
    from clue_storage.fs import FsStorage
    from tests.arv2.icp_fixture import USER_ID, seed_icp_fixture, settings_for
    from tests.arv2.test_account_research_launch_db import _request

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            settings = settings_for(arv2_account_research_enabled=True)
            account = UUID(str(fixture.accounts[0]))
            launch = await launch_arv2_account_research(
                conn,
                _request(fixture, account_entity_ids=(account,)),
                settings=settings,
                storage=storage,
                profile_sha256=arv2_account_profile_sha256(version="v4"),
            )
            run = await read_run(conn, run_id=launch.run_id)
            assert run is not None and run.context_id is not None
            account_job = launch.job_ids[0]
            await account_recipe(conn, account_job, 25)
            generation = await ensure_generation(
                conn,
                OperationScope(run.workspace_id, run.run_id, account_job, account),
                context_id=run.context_id,
            )
            dana = await insert_contact_entity(
                conn, account_entity_id=account, full_name="Dana Reyes"
            )
            receipt = await launch_arv2_person_research(
                conn,
                Arv2PersonLaunchRequest(
                    workspace_id=fixture.workspace_id,
                    project_id=fixture.project_id,
                    contact_entity_ids=(UUID(str(dana)),),
                    requested_by_user_id=USER_ID,
                    directive_text="",
                ),
                settings=settings,
                storage=storage,
                profile_sha256=arv2_person_profile_sha256(),
            )
            assert receipt.run_id != launch.run_id
            joined = (
                await conn.execute(
                    text("SELECT generation_id FROM arv2_generation_child WHERE job_id=:id"),
                    {"id": receipt.job_ids[0]},
                )
            ).scalar_one_or_none()
            assert joined == generation.generation_id

    run_async(case())
