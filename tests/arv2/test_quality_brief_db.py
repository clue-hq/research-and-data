"""Opening briefs and original-history reads against the real substrate; no paid calls."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.quality_brief import compile_brief, render_brief
from clue_api.arv2.quality_claims import ClaimProposal, submit_proposal
from clue_api.arv2.quality_context import build_context, read_context
from clue_api.arv2.quality_evidence import JsonSupport, grant_manifest
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_history import history_page
from clue_api.arv2.quality_views import ResearchViewMount
from clue_spine import confirm_project_product_set, create_product
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import USER_ID, seed_icp_document
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


@pytest.mark.parametrize(
    "seller,target,products,question",
    [
        ("Clue", "Zafran", ["Clue"], "Investigate campaign production bottlenecks."),
        (
            "Insight Health",
            "Premier",
            ["MagicDocs", "Intake AI Agent", "DAC intake"],
            "Investigate fax referral intake and GI screening workflows.",
        ),
    ],
)
def test_opening_and_provider_briefs_preserve_selected_context(
    tmp_path, seller, target, products, question
):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            context = await read_context(
                conn,
                storage,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                context_id=cid,
            )
            # These are renderer fixtures, not customer research findings. The context builder
            # is still exercised to ensure non-selected product documents never enter the brief.
            selected = []
            for i, name in enumerate(products):
                if name in context.products.values():
                    product = next(k for k, v in context.products.items() if v == name)
                else:
                    product = (
                        await create_product(
                            conn,
                            brand_id=context.brand_id,
                            workspace_id=scope.workspace_id,
                            name=name,
                        )
                    ).product_id
                selected.append(product)
                await seed_icp_document(
                    conn,
                    storage,
                    workspace_id=scope.workspace_id,
                    brand_id=context.brand_id,
                    kind="product-research",
                    status="ready",
                    path=f"products/{i}.md",
                    body=f"---\nkind: product-research\nproduct_id: {product}\n"
                    f"product_name: {name}\ncapabilities:\n- {question}\n"
                    "pricing: Quote-based\nproof_points:\n- A documented proof point\n"
                    "integrations:\n- Example CRM\n---\nOriginal product prose.",
                )
            selection = await confirm_project_product_set(
                conn,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                product_ids=selected,
                gate_id=uuid4(),
                confirmed_by_user_id=USER_ID,
            )
            assert selection is not None
            await seed_icp_document(
                conn,
                storage,
                workspace_id=scope.workspace_id,
                brand_id=context.brand_id,
                kind="product-research",
                status="ready",
                path="products/unselected.md",
                body="---\nkind: product-research\nproduct_id: unselected\n---\n"
                "UNSELECTED PRODUCT CAPABILITIES MUST NOT APPEAR",
            )
            await conn.execute(
                text("UPDATE brand SET name=:seller WHERE brand_id=:b"),
                {"seller": seller, "b": context.brand_id},
            )
            await conn.execute(
                text("UPDATE arv2_research_run SET directive_text=:q WHERE run_id=:run"),
                {"q": question, "run": op.run_id},
            )
            context = await build_context(
                conn,
                storage,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                product_selection_version=selection.selection_version,
            )
            brief = await compile_brief(
                conn,
                storage,
                scope=replace(scope, account_name=target),
                context=context,
                context_id=cid,
                as_of=datetime.now(UTC),
                limits=Allowance(200, 60, 10),
                media_ceiling_s=3600,
            )
            opening, provider = render_brief(brief), render_brief(brief, provider=True)
            for output in (opening, provider):
                assert seller in output and target in output and question in output
                assert all(name in output for name in products)
                assert "Quote-based" in output and "Example CRM" in output
                assert "A documented proof point" in output
                assert "US-headquartered" in output  # exact pinned fixture ICP front matter
                assert "UNSELECTED PRODUCT" not in output
                assert "persona:missing" in output
                assert "not reasons to halt research" in output
            assert "/research/documents/" in opening and "/research/documents/" not in provider
            assert brief["run_scope"]["limits"]["model_calls"] == 200
            assert brief["run_scope"]["media_ceiling_s"] == 3600
            assert brief["known_claims_total"] == 0
            assert set(brief["products"].values()) == set(products)

    run_async(case())


def test_history_originals_are_project_account_scoped_and_revocable(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            report = "Original provider finding.\n" * 900
            source = await save(conn, storage, op, report, kind="research_report")
            page = await history_page(conn, scope, kind="sources")
            assert page["total"] == 1 and page["items"][0]["id"] == source.source_id
            for foreign in (
                replace(scope, project_id="other-project"),
                replace(scope, workspace_id="other-workspace"),
                replace(scope, account_id=uuid4()),
            ):
                assert not (await history_page(conn, foreign, kind="sources"))["items"]
            eid = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=eid,
                context_id=cid,
                role="account_research",
                limits=Allowance(20, 30, 4),
            )

            @asynccontextmanager
            async def connections():
                yield conn

            mount = ResearchViewMount(connections, storage, scope, eid)
            path = page["items"][0]["path"].removeprefix("/research")
            rebuilt = ""
            while path:
                result = await mount.aread(path)
                assert not result.error
                value = json.loads(result.file_data["content"])
                rebuilt += "".join(s["text"] for s in value["text_segments"])
                path = (value["next_path"] or "").removeprefix("/research")
            assert rebuilt == report
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET input_refs="
                    "COALESCE(input_refs,'{}'::jsonb) || "
                    "jsonb_build_object('privacy_stopped',true) "
                    "WHERE job_id=:id"
                ),
                {"id": scope.job_id},
            )
            assert not (await history_page(conn, scope, kind="sources"))["items"]
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET input_refs="
                    "input_refs - 'privacy_stopped' WHERE job_id=:id"
                ),
                {"id": scope.job_id},
            )
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM artifact_reference "
                        "WHERE reference_kind='research_prior_source' AND reference_id=:id"
                    ),
                    {"id": str(scope.job_id)},
                )
            ).scalar_one() == 1
            await conn.execute(
                text("UPDATE artifact SET privacy_erased=true WHERE storage_key=:k"),
                {"k": source.artifact_key},
            )
            assert (await mount.aread(f"/history/sources/{source.source_id}/0.json")).error

    run_async(case())


def test_prior_findings_keep_their_values_dates_and_evidence_without_cross_project_reuse(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            source = await save(conn, storage, op, {"employees": 64}, kind="provider_record")
            grant = await grant_manifest(conn, op, consumer_id=uuid4())
            await submit_proposal(
                conn,
                storage,
                scope,
                grant,
                ClaimProposal(
                    operation_key="prior-staff",
                    field_key="core.employee_count",
                    value=64,
                    assessment=assessment(),
                    support=(
                        JsonSupport(
                            source_id=source.source_id, pointer="/employees", expected_value=64
                        ),
                    ),
                ),
                context_id=cid,
                actor_ref="fixture",
            )
            context = await read_context(
                conn,
                storage,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                context_id=cid,
            )
            brief = await compile_brief(
                conn,
                storage,
                scope=scope,
                context=context,
                context_id=cid,
                as_of=datetime.now(UTC),
                limits=Allowance(20, 30, 4),
                media_ceiling_s=None,
            )
            assert brief["known_claims_total"] == 1
            prior = brief["known_claims"][0]
            assert prior["value_preview"] == "64" and prior["assessment"] == "supported"
            assert prior["collected_at"] and prior["context_id"] == str(cid)
            assert prior["source_url"] == "https://example.test/source"
            assert "fresh verification" in render_brief(brief, provider=True)
            assert not (
                await history_page(conn, replace(scope, project_id="other-project"), kind="claims")
            )["items"]

    run_async(case())
