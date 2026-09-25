"""The final narrative and page contract on real claims/storage: no paid models or providers."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.quality_claims import (
    ClaimProposal,
    ClaimSupport,
    NarrativeProposal,
    SellerDocumentSupport,
    submit_proposal,
)
from clue_api.arv2.quality_context import build_context, persist_context, read_document
from clue_api.arv2.quality_evidence import TextSupport, grant_manifest
from clue_api.arv2.quality_generation import ensure_generation
from clue_api.arv2.quality_page_inputs import page_inputs
from clue_api.arv2.quality_pages import (
    CitedSentence,
    PageDraft,
    PageSectionDraft,
    publish_page,
    read_page,
)
from clue_research.claimstore.quality import assess_claim
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import seed_icp_document
from tests.arv2.test_quality_claims_db import assessment, setup
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_execution_db import execution
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def clinical_context(conn, storage):
    from clue_api.arv2.display.recipes import load_display_recipes

    await load_display_recipes(conn)
    op, scope, _ = await setup(conn, storage)
    run = (
        await conn.execute(
            text(
                "SELECT brand_id,product_selection_version FROM arv2_research_run WHERE run_id=:run"
            ),
            {"run": op.run_id},
        )
    ).one()
    product = (
        await conn.execute(
            text("SELECT product_id FROM product WHERE brand_id=:brand"), {"brand": run.brand_id}
        )
    ).scalar_one()
    await seed_icp_document(
        conn,
        storage,
        workspace_id=scope.workspace_id,
        brand_id=run.brand_id,
        kind="product-research",
        status="ready",
        path="products/intake.md",
        body=(
            f"---\nkind: product-research\nproduct_id: {product}\n---\n"
            "MagicDocs automates GI referral intake."
        ),
    )
    context = await build_context(
        conn,
        storage,
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
        product_selection_version=run.product_selection_version,
    )
    cid = await persist_context(conn, storage, context)
    await conn.execute(
        text("UPDATE arv2_research_run SET context_id=:cid WHERE run_id=:run"),
        {"cid": cid, "run": scope.run_id},
    )
    generation = await ensure_generation(conn, op, context_id=cid)
    grant = await grant_manifest(conn, op, consumer_id=uuid4())
    return op, scope, context, cid, generation, grant


def test_two_sided_narrative_cas_and_immediate_invalid_suppression(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, context, cid, generation, _ = await clinical_context(conn, storage)
            source = await save(
                conn, storage, op, "Referral intake requires manual document entry."
            )
            grant = await grant_manifest(conn, op, consumer_id=uuid4())
            support = TextSupport(
                source_id=source.source_id,
                start=0,
                end=len("Referral intake requires manual document entry."),
                quote="Referral intake requires manual document entry.",
            )
            fact = await submit_proposal(
                conn,
                storage,
                scope,
                grant,
                ClaimProposal(
                    operation_key="intake",
                    field_key="account.operational_pain",
                    value="Manual document entry",
                    support=(support,),
                    assessment=assessment(),
                ),
                context_id=cid,
                actor_ref="claim-specialist",
            )
            assert fact.status == "supported", fact
            pin = context.seller_documents[0]
            body = await read_document(conn, storage, workspace_id=scope.workspace_id, pin=pin)
            quote = "MagicDocs automates GI referral intake."
            seller = SellerDocumentSupport(
                document_id=pin.document_id,
                sha256=pin.sha256,
                start=body.index(quote),
                end=len(body),
                quote=quote,
            )
            proposal = NarrativeProposal(
                operation_key="narrative",
                field_key="account.value_narrative",
                value={
                    "persona": "champion",
                    "argument": "MagicDocs could reduce manual GI intake.",
                    "icp_spec_version": 1,
                    "icp_key": (
                        await conn.execute(
                            text("SELECT icp_key FROM arv2_research_run WHERE run_id=:id"),
                            {"id": scope.run_id},
                        )
                    ).scalar_one(),
                    "project_id": scope.project_id,
                    "context_id": str(cid),
                    "product_ids": [str(p) for p in sorted(context.products)],
                },
                claim_kind="inference",
                support=(ClaimSupport(claim_ids=(fact.claim_id,)), seller),
                assessment=assessment(),
                outreach_safe=False,
            )
            refused = await submit_proposal(
                conn,
                storage,
                scope,
                grant,
                proposal.model_copy(
                    update={
                        "operation_key": "wrong-document",
                        "support": (
                            ClaimSupport(claim_ids=(fact.claim_id,)),
                            seller.model_copy(update={"document_id": uuid4()}),
                        ),
                    }
                ),
                context_id=cid,
                actor_ref="narrative-specialist",
            )
            assert refused.status == "refused"
            narrative = await submit_proposal(
                conn,
                storage,
                scope,
                grant,
                proposal,
                context_id=cid,
                actor_ref="narrative-specialist",
            )
            assert narrative.status == "supported", narrative
            stored_support = (
                await conn.execute(
                    text("SELECT * FROM claim_support WHERE claim_id=:id"),
                    {"id": narrative.claim_id},
                )
            ).one()
            assert stored_support.account_evidence_ids == [str(fact.claim_id)]
            assert str(pin.document_id) in stored_support.client_knowledge_ids[0]
            inputs = await page_inputs(conn, scope, context_id=cid, page="overview")
            sections = tuple(
                PageSectionDraft(
                    key=r["section_key"],
                    intro=(
                        CitedSentence(
                            text="MagicDocs could reduce manual GI intake.",
                            claimIds=(narrative.claim_id,),
                            kind="inference",
                        ),
                    )
                    if r["section_key"] == "why-they-fit"
                    else (),
                    gaps=("No supported finding for this section",)
                    if r["section_key"] != "why-they-fit"
                    else (),
                )
                for r in inputs.manifest["recipes"]
            )
            draft = PageDraft(
                page="overview", expected_dependency_sha256=inputs.sha256, sections=sections
            )
            eid = await execution(conn, op, scope.project_id)
            ids = await publish_page(
                conn, storage, scope, context_id=cid, execution_id=eid, model="offline", draft=draft
            )
            assert ids == await publish_page(
                conn, storage, scope, context_id=cid, execution_id=eid, model="offline", draft=draft
            )
            visible = await read_page(conn, scope, context_id=cid, page="overview")
            assert visible["cited_claim_ids"] == (str(narrative.claim_id),)
            assert not visible["research_quality"]["refreshPending"]
            from contextlib import asynccontextmanager

            from clue_api.arv2.quality_generation import signal_subject_change
            from clue_api.frontend_read.contract_v1 import ResearchDisplayBlock
            from clue_api.frontend_read.display_pages import DisplayPages
            from clue_api.frontend_read.v1_shared import research_evidence_for
            from clue_config.settings import Settings

            @asynccontextmanager
            async def connections():
                yield conn

            pages = DisplayPages(settings=Settings(), secrets=None, conn_factory=connections)
            wire = await pages.page(
                conn,
                workspace_id=scope.workspace_id,
                subject_kind="account",
                subject_id=str(scope.account_id),
                page="overview",
                generate=False,
            )
            parsed = ResearchDisplayBlock.model_validate(wire.display_block)
            assert parsed.research_quality.context_id == str(cid)
            assert parsed.research_quality.contexts[0].project_name
            assert (
                await pages.offer_contact_pages(
                    conn, workspace_id=scope.workspace_id, account_id=str(scope.account_id)
                )
                == 0
            )
            evidence = await research_evidence_for(
                conn, workspace_id=scope.workspace_id, claim_ids=wire.cited_claim_ids
            )
            assert evidence[0].source_kind == "inference"
            assert evidence[0].seller_passages[0].quote == quote
            assert evidence[0].supporting_claim_ids == (str(fact.claim_id),)
            # The narrative output cannot trigger another reconciliation round forever.
            await signal_subject_change(
                conn,
                {
                    "workspace_id": scope.workspace_id,
                    "entity_id": scope.account_id,
                    "claim_id": narrative.claim_id,
                    "event_id": narrative.operation_id,
                },
            )
            assert (
                await page_inputs(conn, scope, context_id=cid, page="overview")
            ).generation.input_revision == generation.input_revision
            await assess_claim(
                conn,
                workspace_id=scope.workspace_id,
                entity_id=scope.account_id,
                claim_id=fact.claim_id,
                operation_id=uuid4(),
                expected_revision=1,
                conclusion="invalid",
                actor_ref="claim-specialist",
                kind="withdrawal",
                context_id=cid,
                rationale_key=source.artifact_key,
                support_artifacts=(source.artifact_key,),
            )
            with pytest.raises(ValueError, match="stale_page_inputs"):
                await publish_page(
                    conn,
                    storage,
                    scope,
                    context_id=cid,
                    execution_id=eid,
                    model="offline",
                    draft=draft,
                )
            visible = await read_page(conn, scope, context_id=cid, page="overview")
            assert not visible["cited_claim_ids"]
            assert visible["research_quality"]["refreshPending"]
            # Safe empty sections remain available; only the invalid assertion is suppressed.
            assert "why-they-fit" in visible["stale"]
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM display_block WHERE context_id=:id"), {"id": cid}
                )
            ).scalar_one() == len(sections)
            with pytest.raises(ValueError):
                await page_inputs(
                    conn, replace(scope, workspace_id="foreign"), context_id=cid, page="overview"
                )

    run_async(case())


def test_same_account_has_two_explicit_project_pages(tmp_path):
    async def case():
        from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
        from clue_api.arv2.account_research_launch import launch_arv2_account_research
        from clue_api.arv2.quality_read import select_quality_context
        from clue_api.arv2.research_operations import OperationScope
        from clue_spine import confirm_project_product_set, create_product, create_project
        from tests.arv2.icp_fixture import USER_ID, IcpFixture, pin_icp, settings_for
        from tests.arv2.test_account_research_launch_db import _request

        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, first, context, cid, _, _ = await clinical_context(conn, storage)
            project = await create_project(
                conn,
                workspace_id=first.workspace_id,
                brand_id=context.brand_id,
                name="Different product motion",
            )
            product = await create_product(
                conn, workspace_id=first.workspace_id, brand_id=context.brand_id, name="Analytics"
            )
            selection = await confirm_project_product_set(
                conn,
                workspace_id=first.workspace_id,
                project_id=project.project_id,
                product_ids=[str(product.product_id)],
                gate_id=uuid4(),
                confirmed_by_user_id=USER_ID,
            )
            await pin_icp(
                conn,
                workspace_id=first.workspace_id,
                project_id=project.project_id,
                brand_id=context.brand_id,
                document_id=context.icp.document_id,
                artifact_key_=context.icp.artifact_key,
                artifact_sha256=context.icp.sha256,
            )
            f = IcpFixture(
                workspace_id=first.workspace_id,
                project_id=project.project_id,
                brand_id=context.brand_id,
                accounts=(first.account_id,),
                icp_document_id=context.icp.document_id,
                icp_artifact_key=context.icp.artifact_key,
                icp_artifact_sha256=context.icp.sha256,
                selection_version=selection.selection_version,
            )
            launch = await launch_arv2_account_research(
                conn,
                _request(f),
                storage=storage,
                settings=settings_for(
                    arv2_account_research_enabled=True, arv2_research_catalog_version="v2"
                ),
                profile_sha256=arv2_account_profile_sha256(version="v2"),
            )
            second_context = await build_context(
                conn,
                storage,
                workspace_id=first.workspace_id,
                project_id=project.project_id,
                product_selection_version=selection.selection_version,
            )
            second_id = await persist_context(conn, storage, second_context)
            await conn.execute(
                text("UPDATE arv2_research_run SET context_id=:context WHERE run_id=:run"),
                {"context": second_id, "run": launch.run_id},
            )
            second = replace(
                first, project_id=project.project_id, job_id=launch.job_ids[0], run_id=launch.run_id
            )
            op2 = OperationScope(
                second.workspace_id, second.run_id, second.job_id, second.account_id
            )
            await ensure_generation(conn, op2, context_id=second_id)
            for operation, scope, context_id, gap in [
                (op, first, cid, "Intake capability requires more evidence"),
                (op2, second, second_id, "Analytics capability requires more evidence"),
            ]:
                inputs = await page_inputs(conn, scope, context_id=context_id, page="overview")
                eid = await execution(conn, operation, scope.project_id)
                await publish_page(
                    conn,
                    storage,
                    scope,
                    context_id=context_id,
                    execution_id=eid,
                    model="offline",
                    draft=PageDraft(
                        page="overview",
                        expected_dependency_sha256=inputs.sha256,
                        sections=tuple(
                            PageSectionDraft(key=r["section_key"], gaps=(gap,))
                            for r in inputs.manifest["recipes"]
                        ),
                    ),
                )
            choice = await select_quality_context(
                conn, workspace_id=first.workspace_id, subject_id=first.account_id
            )
            assert choice.scope is None and len(choice.metadata["contexts"]) == 2
            assert choice.metadata["qualityState"] == "context_required"
            for scope, context_id, word in [
                (first, cid, "Intake"),
                (second, second_id, "Analytics"),
            ]:
                chosen = await select_quality_context(
                    conn,
                    workspace_id=scope.workspace_id,
                    subject_id=scope.account_id,
                    project_id=scope.project_id,
                )
                assert chosen.context_id == context_id
                page = await read_page(conn, chosen.scope, context_id=context_id, page="overview")
                assert all(word in g for g in page["research_quality"]["gaps"])
                assert not page["research_quality"]["refreshPending"]
            assert set(context.products).isdisjoint(second_context.products)
            assert (
                await conn.execute(
                    text(
                        "SELECT count(DISTINCT context_id) FROM display_block WHERE subject_id=:id"
                    ),
                    {"id": first.account_id},
                )
            ).scalar_one() == 2

    run_async(case())


def test_independent_person_research_has_its_own_refreshable_context(tmp_path):
    async def case():
        from clue_api.arv2.account_research_store import create_job
        from clue_api.arv2.display.recipes import load_display_recipes, read_recipes
        from clue_api.arv2.quality_read import select_quality_context
        from clue_api.arv2.research_operations import OperationScope
        from clue_research.identity import insert_contact_entity

        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, account, cid = await setup(conn, storage)
            await load_display_recipes(conn)
            contact = await insert_contact_entity(
                conn, account_entity_id=account.account_id, full_name="Independent Person"
            )
            jid = uuid4()
            await create_job(
                conn,
                job_id=jid,
                run_id=op.run_id,
                workspace_id=op.workspace_id,
                account_entity_id=op.account_id,
                subject_type="person",
                subject_entity_id=contact,
                profile_sha256="a" * 64,
            )
            scope = replace(
                account, job_id=jid, subject_kind="person", contact_id=contact, catalog_version="v4"
            )
            own = OperationScope(op.workspace_id, op.run_id, jid, op.account_id)
            await ensure_generation(conn, own, context_id=cid)
            deps = await page_inputs(conn, scope, context_id=cid, page="contact")
            assert deps.generation.initial_job_id == jid
            sections = await read_recipes(conn, "contact", workspace_id=op.workspace_id)
            draft = PageDraft(
                page="contact",
                expected_dependency_sha256=deps.sha256,
                sections=tuple(
                    PageSectionDraft(
                        key=r.section_key, gaps=("Public evidence remains to be acquired.",)
                    )
                    for r in sections
                ),
            )
            ex = await execution(conn, own, scope.project_id)
            await publish_page(
                conn,
                storage,
                scope,
                context_id=cid,
                execution_id=ex,
                draft=draft,
                model="fixture/no-model",
            )
            chosen = await select_quality_context(
                conn,
                workspace_id=op.workspace_id,
                subject_kind="contact",
                subject_id=contact,
                account_id=op.account_id,
                project_id=scope.project_id,
            )
            assert chosen and chosen.scope and chosen.scope.job_id == jid
            assert chosen.metadata["generationId"] == str(deps.generation.generation_id)
            page = await read_page(conn, scope, context_id=cid, page="contact")
            assert page["research_quality"]["refreshPending"] is False

    run_async(case())
