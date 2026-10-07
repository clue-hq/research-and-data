"""The separate page writer against real rows: durable inputs in, published pages out."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.arv2.page_writer import SECTIONS
from clue_api.arv2.page_writer_runtime import (
    publish_written,
    write_pages,
    writes_pages_separately,
)
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_json_dossier import (
    DossierInput,
    FinishDossierTool,
    SaveDossierSectionTool,
    SaveSectionInput,
)
from clue_api.arv2.quality_pages import read_page
from clue_api.arv2.research_operations import OperationScope
from clue_core import ExecutionId, OperationId
from tests.arv2.test_dossier_json import finding
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


class Model:
    """Answers the seller-brief call with prose and the page call with ``pages``."""

    def __init__(self, pages: Mapping[str, object]) -> None:
        self.pages = pages
        self.calls: list[tuple[list[Mapping[str, str]], bool]] = []

    async def __call__(self, messages: Sequence[Mapping[str, str]], json_mode: bool) -> str:
        self.calls.append((list(messages), json_mode))
        return json.dumps(self.pages) if json_mode else "The seller sells care navigation."


def result(pages: Sequence[str], fill: Mapping[str, object]) -> dict[str, object]:
    return {
        "pages": [
            {
                "page": page,
                "sections": [
                    fill.get(key) or {"key": key, "intro": [], "items": [], "gaps": []}
                    for key in SECTIONS[page]
                ],
            }
            for page in pages
        ]
    }


def section(key: str, text_: str, refs: Sequence[str]) -> dict[str, object]:
    return {
        "key": key,
        "intro": [{"text": text_, "kind": "fact", "refs": list(refs)}],
        "items": [],
        "gaps": [],
    }


def connections(conn):
    lock = asyncio.Lock()

    @asynccontextmanager
    async def factory():
        async with lock, conn.begin_nested():
            yield conn

    return factory


def test_account_pages_are_written_from_the_dossier_and_published(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            parent, _child, cid, storage, ctx, _gen, _path = await initial(conn, tmp_path)
            parent = replace(parent, input_refs={"quality_recipe_version": 25})
            assert writes_pages_separately(parent)
            await load_display_recipes(conn)
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            model = Model(
                result(
                    ["overview", "insights"],
                    {"why-they-fit": section("why-they-fit", "The short story.", ["F001"])},
                )
            )
            factory = connections(conn)
            written = await write_pages(model, factory, storage, scope=parent, context_id=cid)
            assert [json_mode for _, json_mode in model.calls] == [False, True]
            assert "The seller sells care navigation." in model.calls[1][0][1]["content"]
            ids = await publish_written(
                conn, storage, parent, context_id=cid, written=written, model_id="test/model"
            )
            assert len(ids) == len(SECTIONS["overview"]) + len(SECTIONS["insights"])
            page = await read_page(conn, parent, context_id=cid, page="overview")
            fit = next(s for s in page["display_block"]["sections"] if s["key"] == "why-they-fit")
            assert fit["intro"][0]["text"] == "The short story."
            assert fit["intro"][0]["claimIds"]
            # The brief is cached for the context: a second write does not ask for it again.
            again = Model(model.pages)
            await write_pages(again, factory, storage, scope=parent, context_id=cid)
            assert [json_mode for _, json_mode in again.calls] == [True]
            # Same reply, same execution: publishing it again replays the same blocks.
            assert (
                await publish_written(
                    conn, storage, parent, context_id=cid, written=written, model_id="test/model"
                )
                == ids
            )
            executions = (
                await conn.execute(
                    text("SELECT count(*) FROM display_block WHERE display_block_id=ANY(:ids)"),
                    {"ids": list(ids)},
                )
            ).scalar_one()
            assert executions == len(ids)

    run_async(case())


def test_contact_page_reads_its_parent_dossier_and_account_story(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, _gen, path = await initial(conn, tmp_path)
            parent = replace(parent, input_refs={"quality_recipe_version": 25})
            child = replace(child, input_refs={**child.input_refs, "quality_recipe_version": 25})
            await load_display_recipes(conn)
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            factory = connections(conn)
            account = await write_pages(
                Model(
                    result(
                        ["overview", "insights"],
                        {"why-they-fit": section("why-they-fit", "Why this account.", ["F001"])},
                    )
                ),
                factory,
                storage,
                scope=parent,
                context_id=cid,
            )
            await publish_written(
                conn, storage, parent, context_id=cid, written=account, model_id="test/model"
            )
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
            childctx = replace(
                ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4())
            )
            await invoke(
                SaveDossierSectionTool,
                child,
                storage,
                childctx,
                SaveSectionInput(section="Voice", findings=[finding(source_paths=[path])]),
            )
            await invoke(FinishDossierTool, child, storage, childctx, DossierInput())
            model = Model(
                result(
                    ["contact"],
                    {
                        "why-this-person": section(
                            "why-this-person", "Why this person.", ["F001", "A:F001"]
                        )
                    },
                )
            )
            written = await write_pages(model, factory, storage, scope=child, context_id=cid)
            prompt = model.calls[-1][0][1]["content"]
            assert "Why this account." in prompt and "A:F001" in prompt
            await publish_written(
                conn, storage, child, context_id=cid, written=written, model_id="test/model"
            )
            page = await read_page(conn, child, context_id=cid, page="contact")
            why = next(
                s for s in page["display_block"]["sections"] if s["key"] == "why-this-person"
            )
            assert why["intro"][0]["text"] == "Why this person."
            assert len(why["intro"][0]["claimIds"]) == 2

    run_async(case())


def test_account_rewrite_after_people_sees_their_findings_and_settles_the_generation(tmp_path):
    from clue_api.arv2.page_writer_runtime import PageWriterModels, rewrite_account_pages
    from clue_api.arv2.quality_generation import read_generation, record_child_result

    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            parent = replace(parent, input_refs={"quality_recipe_version": 25})
            child = replace(child, input_refs={**child.input_refs, "quality_recipe_version": 25})
            await load_display_recipes(conn)
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
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
            childctx = replace(
                ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4())
            )
            await invoke(
                SaveDossierSectionTool,
                child,
                storage,
                childctx,
                SaveSectionInput(section="Voice", findings=[finding(source_paths=[path])]),
            )
            await invoke(FinishDossierTool, child, storage, childctx, DossierInput())
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET status='completed',finished_at=now() "
                    "WHERE job_id=:id"
                ),
                {"id": child.job_id},
            )
            await record_child_result(conn, workspace_id=child.workspace_id, job_id=child.job_id)
            revision = (
                await read_generation(
                    conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
                )
            ).input_revision
            assert revision > 0
            model = Model(
                result(
                    ["overview", "insights"],
                    {
                        "why-they-fit": section(
                            "why-they-fit", "Rewritten with the committee.", ["F001", "P1:F001"]
                        )
                    },
                )
            )
            out = await rewrite_account_pages(
                conn_factory=connections(conn),
                storage=storage,
                scope=parent,
                context_id=cid,
                generation_id=gen.generation_id,
                revision=revision,
                models=PageWriterModels(call_for=lambda scope: model, model_id="test/model"),
            )
            assert out["applied"] is True
            assert "P1:F001" in model.calls[-1][0][1]["content"]
            page = await read_page(conn, parent, context_id=cid, page="overview")
            fit = next(s for s in page["display_block"]["sections"] if s["key"] == "why-they-fit")
            assert fit["intro"][0]["text"] == "Rewritten with the committee."
            settled = await read_generation(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            assert settled.reconciled_revision == revision

    run_async(case())


class Pages:
    """Answers the seller brief with prose and each page call with that subject's pages."""

    def __init__(self, account: Mapping[str, object], contact: Mapping[str, object]) -> None:
        self.account, self.contact = account, contact
        self.calls: list[str] = []
        self.contact_requests: list[str] = []

    async def __call__(self, messages: Sequence[Mapping[str, str]], json_mode: bool) -> str:
        from clue_api.arv2.page_writer import contact_system

        if not json_mode:
            self.calls.append("brief")
            return "The seller sells care navigation."
        subject = "contact" if messages[0]["content"] == contact_system() else "account"
        self.calls.append(subject)
        if subject == "contact":
            self.contact_requests.append(messages[1]["content"])
        return json.dumps(self.contact if subject == "contact" else self.account)


async def _recipe_26_generation(conn, tmp_path, *, imported=True):
    """An account (imported unless told otherwise) and one settled person whose contact page
    was deferred."""
    from clue_api.arv2.quality_generation import read_generation, record_child_result

    parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
    parent = replace(parent, input_refs={"quality_recipe_version": 26})
    child = replace(child, input_refs={**child.input_refs, "quality_recipe_version": 26})
    await load_display_recipes(conn)
    if imported:
        await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
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
    childctx = replace(ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4()))
    await invoke(
        SaveDossierSectionTool,
        child,
        storage,
        childctx,
        SaveSectionInput(section="Voice", findings=[finding(source_paths=[path])]),
    )
    await invoke(FinishDossierTool, child, storage, childctx, DossierInput())
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET status='completed',finished_at=now(),"
            "finalization_json=CAST(:fin AS jsonb) WHERE job_id=:id"
        ),
        {"id": child.job_id, "fin": json.dumps({"coverage": {"deferred_pages": ["contact"]}})},
    )
    await record_child_result(conn, workspace_id=child.workspace_id, job_id=child.job_id)
    revision = (
        await read_generation(
            conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
        )
    ).input_revision
    model = Pages(
        result(
            ["overview", "insights"],
            {"why-they-fit": section("why-they-fit", "Account with its people.", ["P1:F001"])},
        ),
        result(
            ["contact"],
            {
                "why-this-person": section(
                    "why-this-person",
                    "Why this person.",
                    ["F001", "A:F001"] if imported else ["F001"],
                )
            },
        ),
    )
    return parent, child, cid, storage, gen, revision, model


def test_final_step_writes_the_account_then_its_deferred_contact_pages(tmp_path):
    from clue_api.arv2.page_writer_runtime import PageWriterModels, rewrite_account_pages
    from clue_api.arv2.quality_generation import deferred_contact_jobs, read_generation

    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, gen, revision, model = await _recipe_26_generation(
                conn, tmp_path
            )
            waiting = await deferred_contact_jobs(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            assert waiting == [child.job_id]
            out = await rewrite_account_pages(
                conn_factory=connections(conn),
                storage=storage,
                scope=parent,
                context_id=cid,
                generation_id=gen.generation_id,
                revision=revision,
                models=PageWriterModels(call_for=lambda scope: model, model_id="test/model"),
                deferred=(child,),
            )
            assert out["applied"] is True and out["contact_pages"] == 1
            # The account first, so each contact page is written against the account's new story.
            assert [c for c in model.calls if c != "brief"] == ["account", "contact"]
            assert "Account with its people." in model.contact_requests[0]
            # Written once: a later revision does not select the person again.
            assert not await deferred_contact_jobs(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            contact = await read_page(conn, child, context_id=cid, page="contact")
            assert any(s["key"] == "why-this-person" for s in contact["display_block"]["sections"])
            overview = await read_page(conn, parent, context_id=cid, page="overview")
            fit = next(
                s for s in overview["display_block"]["sections"] if s["key"] == "why-they-fit"
            )
            assert fit["intro"][0]["text"] == "Account with its people."
            settled = await read_generation(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            assert settled.reconciled_revision == revision

    run_async(case())


def test_a_deferred_contact_page_is_written_even_if_the_account_never_imported(tmp_path):
    """Review I1: the people's pages must not wait forever on an account that ended without
    an import; they are written from the person's own findings and the revision needs review."""
    from clue_api.arv2.page_writer_runtime import PageWriterModels, rewrite_account_pages
    from clue_api.arv2.quality_generation import read_generation

    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, gen, revision, model = await _recipe_26_generation(
                conn, tmp_path, imported=False
            )
            out = await rewrite_account_pages(
                conn_factory=connections(conn),
                storage=storage,
                scope=parent,
                context_id=cid,
                generation_id=gen.generation_id,
                revision=revision,
                models=PageWriterModels(call_for=lambda scope: model, model_id="test/model"),
                deferred=(child,),
            )
            assert out["skipped"] == "account_dossier_not_imported"
            assert out["contact_pages"] == 1
            assert [c for c in model.calls if c != "brief"] == ["contact"]
            contact = await read_page(conn, child, context_id=cid, page="contact")
            assert any(s["key"] == "why-this-person" for s in contact["display_block"]["sections"])
            settled = await read_generation(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            assert settled.reconciled_revision == revision

    run_async(case())


def test_rewrite_with_identical_inputs_settles_without_a_model_call(tmp_path):
    from clue_api.arv2.page_writer_runtime import PageWriterModels, rewrite_account_pages
    from clue_api.arv2.quality_generation import read_generation, signal

    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, gen, revision, model = await _recipe_26_generation(
                conn, tmp_path
            )
            models = PageWriterModels(call_for=lambda scope: model, model_id="test/model")

            async def rewrite(rev):
                return await rewrite_account_pages(
                    conn_factory=connections(conn),
                    storage=storage,
                    scope=parent,
                    context_id=cid,
                    generation_id=gen.generation_id,
                    revision=rev,
                    models=models,
                )

            assert (await rewrite(revision))["applied"] is True
            calls = len(model.calls)
            later = await signal(
                conn,
                workspace_id=parent.workspace_id,
                generation_id=gen.generation_id,
                event_id=uuid4(),
                reason="claim_changed",
            )
            assert later > revision
            out = await rewrite(later)
            assert out["applied"] is True and out["unchanged"] is True
            assert len(model.calls) == calls
            settled = await read_generation(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            assert settled.reconciled_revision == later

    run_async(case())


def test_rewrite_skips_an_account_whose_research_never_imported(tmp_path):
    from clue_api.arv2.page_writer_runtime import PageWriterModels, rewrite_account_pages
    from clue_api.arv2.quality_generation import read_generation

    async def case():
        async with rollback_conn() as conn:
            # The account research failed before finish_dossier: there is no imported dossier.
            parent, _child, cid, storage, _ctx, gen, _path = await initial(conn, tmp_path)
            parent = replace(parent, input_refs={"quality_recipe_version": 25})
            await load_display_recipes(conn)
            revision = (
                await read_generation(
                    conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
                )
            ).input_revision
            model = Model(result(["overview", "insights"], {}))
            out = await rewrite_account_pages(
                conn_factory=connections(conn),
                storage=storage,
                scope=parent,
                context_id=cid,
                generation_id=gen.generation_id,
                revision=revision,
                models=PageWriterModels(call_for=lambda scope: model, model_id="test/model"),
            )
            assert model.calls == []
            assert out["skipped"] == "account_dossier_not_imported"
            page = await read_page(conn, parent, context_id=cid, page="overview")
            sections = page["display_block"]["sections"]
            assert not any(s.get("intro") or s.get("items") for s in sections)
            settled = await read_generation(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            assert settled.reconciled_revision == revision
            assert settled.state == "needs_review"

    run_async(case())


def test_independent_person_page_uses_the_accounts_completed_dossier(tmp_path):
    """A person launched on its own (no parent account job) still sees the account's findings."""
    from clue_api.arv2.account_research_store import create_job
    from clue_api.arv2.quality_generation import ensure_generation
    from clue_research.identity import insert_contact_entity

    async def case():
        async with rollback_conn() as conn:
            parent, _child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            parent = replace(parent, input_refs={"quality_recipe_version": 25})
            await load_display_recipes(conn)
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            contact = await insert_contact_entity(
                conn, account_entity_id=parent.account_id, full_name="Independent person"
            )
            solo_id = uuid4()
            refs = {"quality_recipe_version": 25}
            await create_job(
                conn,
                job_id=solo_id,
                run_id=parent.run_id,
                workspace_id=parent.workspace_id,
                account_entity_id=parent.account_id,
                subject_type="person",
                subject_entity_id=contact,
                profile_sha256="a" * 64,
                input_refs=refs,
            )
            solo = replace(
                parent, job_id=solo_id, subject_kind="person", contact_id=contact, input_refs=refs
            )
            op = OperationScope(solo.workspace_id, solo.run_id, solo_id, solo.account_id)
            await ensure_generation(conn, op, context_id=cid)
            # As live: the account's research (and its generation) came well before the person's.
            await conn.execute(
                text(
                    "UPDATE arv2_account_research_generation "
                    "SET created_at=created_at - interval '1 hour' WHERE generation_id=:id"
                ),
                {"id": gen.generation_id},
            )
            eid = await execution(conn, op, solo.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=eid,
                context_id=cid,
                role="account_research",
                limits=Allowance(100, 100, 10),
            )
            soloctx = replace(ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4()))
            await invoke(
                SaveDossierSectionTool,
                solo,
                storage,
                soloctx,
                SaveSectionInput(section="Voice", findings=[finding(source_paths=[path])]),
            )
            await invoke(FinishDossierTool, solo, storage, soloctx, DossierInput())
            model = Model(
                result(
                    ["contact"],
                    {"why-this-person": section("why-this-person", "Why.", ["F001", "A:F001"])},
                )
            )
            written = await write_pages(
                model, connections(conn), storage, scope=solo, context_id=cid
            )
            assert "A:F001" in model.calls[-1][0][1]["content"]
            await publish_written(
                conn, storage, solo, context_id=cid, written=written, model_id="test/model"
            )
            page = await read_page(conn, solo, context_id=cid, page="contact")
            why = next(
                s for s in page["display_block"]["sections"] if s["key"] == "why-this-person"
            )
            assert len(why["intro"][0]["claimIds"]) == 2

    run_async(case())
