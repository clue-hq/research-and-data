"""Exact context identities on the real substrate; no provider/model calls."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from clue_api.arv2.quality_context import (
    ContextUnavailable,
    build_context,
    persist_context,
    read_context,
    read_document,
)
from clue_storage import ArtifactIntegrityError, erase_if_unreferenced, release_artifacts
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import ICP_BODY, pin_icp, seed_icp_document, seed_icp_fixture
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def persona(
    conn, storage, f, *, project=None, source=None, sha=None, path="audience/persona.md"
):
    did, _, _ = await seed_icp_document(
        conn,
        storage,
        workspace_id=f.workspace_id,
        brand_id=f.brand_id,
        kind="audience-persona",
        status="ready",
        path=path,
        project_id=project,
        body="---\nkind: audience-persona\nicp_key: clue-abm-buyers\n"
        "icp_version: 1\n---\nOperations buyer",
    )
    if source:
        await conn.execute(
            text(
                "UPDATE brand_knowledge_document SET source_icp_document_id=:s, "
                "source_icp_sha256=:sha WHERE document_id=:d"
            ),
            {"s": source, "sha": sha, "d": did},
        )
    return did


def test_context_pins_exact_seller_products_and_originals(tmp_path: Path):

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            f = await seed_icp_fixture(conn, storage)
            await conn.execute(
                text("UPDATE brand SET name='Clinical Seller' WHERE brand_id=:b"), {"b": f.brand_id}
            )
            product = (
                await conn.execute(
                    text("SELECT product_id FROM product WHERE brand_id=:b"), {"b": f.brand_id}
                )
            ).scalar_one()
            await seed_icp_document(
                conn,
                storage,
                workspace_id=f.workspace_id,
                brand_id=f.brand_id,
                kind="product-research",
                path="products/intake.md",
                status="ready",
                body=f"---\nkind: product-research\nproduct_id: {product}\n"
                "---\nAutomated GI intake",
            )
            pd = await persona(
                conn, storage, f, source=f.icp_document_id, sha=f.icp_artifact_sha256
            )
            c = await build_context(
                conn,
                storage,
                workspace_id=f.workspace_id,
                project_id=f.project_id,
                product_selection_version=f.selection_version,
            )
            assert c.seller_name == "Clinical Seller"
            assert c.persona_state == "pinned" and c.personas[0].document_id == pd
            assert len(c.seller_documents) == 1 and not c.gaps
            cid = await persist_context(conn, storage, c)
            assert await persist_context(conn, storage, c) == cid
            assert not await erase_if_unreferenced(conn, c.icp.artifact_key)
            await release_artifacts(
                conn, workspace_id=f.workspace_id, reference_kind="unrelated", reference_id=str(cid)
            )
            assert not await erase_if_unreferenced(conn, c.icp.artifact_key)
            await conn.execute(
                text("UPDATE brand SET name='Changed later' WHERE brand_id=:b"), {"b": f.brand_id}
            )
            stored = await read_context(
                conn, storage, workspace_id=f.workspace_id, project_id=f.project_id, context_id=cid
            )
            assert stored == c
            assert "Automated GI intake" in await read_document(
                conn, storage, workspace_id=f.workspace_id, pin=stored.seller_documents[0]
            )
            with pytest.raises(ContextUnavailable):
                await read_context(
                    conn,
                    storage,
                    workspace_id=f.workspace_id,
                    project_id="other-project",
                    context_id=cid,
                )
            await storage.delete(c.icp.artifact_key)
            with pytest.raises(ArtifactIntegrityError):
                await read_document(conn, storage, workspace_id=f.workspace_id, pin=c.icp)

    run_async(case())


def test_unrelated_version_integer_is_not_persona_lineage(tmp_path):

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            f = await seed_icp_fixture(conn, storage)
            await persona(conn, storage, f)
            c = await build_context(
                conn,
                storage,
                workspace_id=f.workspace_id,
                project_id=f.project_id,
                product_selection_version=f.selection_version,
            )
            assert c.persona_state == "lineage_unresolved" and not c.personas
            assert "persona:lineage_unresolved" in c.gaps

    run_async(case())


def test_project_persona_specializes_brand_pin_and_ambiguity_is_explicit(tmp_path):

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            f = await seed_icp_fixture(conn, storage)
            await persona(conn, storage, f, source=f.icp_document_id, sha=f.icp_artifact_sha256)
            local = await persona(
                conn,
                storage,
                f,
                project=f.project_id,
                source=f.icp_document_id,
                sha=f.icp_artifact_sha256,
            )

            async def build(ids=None):
                return await build_context(
                    conn,
                    storage,
                    workspace_id=f.workspace_id,
                    project_id=f.project_id,
                    product_selection_version=f.selection_version,
                    persona_document_ids=ids,
                )

            assert (await build()).personas[0].document_id == local
            second = await persona(
                conn,
                storage,
                f,
                project=f.project_id,
                source=f.icp_document_id,
                sha=f.icp_artifact_sha256,
                path="audience/second.md",
            )
            assert (await build()).persona_state == "ambiguous"
            assert (await build([second])).personas[0].document_id == second
            with pytest.raises(ContextUnavailable):
                await build([f.icp_document_id])

    run_async(case())


@pytest.mark.parametrize("changed", [False, True])
def test_confirmation_revision_preserves_only_demonstrable_lineage(tmp_path, changed):

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            f = await seed_icp_fixture(conn, storage)
            await persona(conn, storage, f, source=f.icp_document_id, sha=f.icp_artifact_sha256)
            raw = ICP_BODY.replace("version: 1", "version: 4")
            if changed:
                raw += "\nA substantively different market.\n"
            did, key, sha = await seed_icp_document(
                conn,
                storage,
                workspace_id=f.workspace_id,
                brand_id=f.brand_id,
                path="audience/icp-clue-abm-buyers.md",
                version=5,
                body=raw,
            )
            await conn.execute(
                text(
                    "UPDATE brand_knowledge_document SET supersedes_document_id=:p "
                    "WHERE document_id=:d"
                ),
                {"p": f.icp_document_id, "d": did},
            )
            await pin_icp(
                conn,
                workspace_id=f.workspace_id,
                project_id=f.project_id,
                brand_id=f.brand_id,
                document_id=did,
                artifact_key_=key,
                artifact_sha256=sha,
            )
            c = await build_context(
                conn,
                storage,
                workspace_id=f.workspace_id,
                project_id=f.project_id,
                product_selection_version=f.selection_version,
            )
            assert c.icp.document_version == 5
            assert c.persona_state == ("lineage_unresolved" if changed else "pinned")

    run_async(case())


def test_project_variant_never_inherits_brand_persona_implicitly(tmp_path):

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            f = await seed_icp_fixture(conn, storage)
            await persona(conn, storage, f, source=f.icp_document_id, sha=f.icp_artifact_sha256)
            did, key, sha = await seed_icp_document(
                conn,
                storage,
                workspace_id=f.workspace_id,
                brand_id=f.brand_id,
                project_id=f.project_id,
                path="audience/local.md",
                body=ICP_BODY + "\nLocal clinic variant.",
            )
            await conn.execute(
                text(
                    "UPDATE brand_knowledge_document SET derived_from_document_id=:p "
                    "WHERE document_id=:d"
                ),
                {"p": f.icp_document_id, "d": did},
            )
            await pin_icp(
                conn,
                workspace_id=f.workspace_id,
                project_id=f.project_id,
                brand_id=f.brand_id,
                document_id=did,
                artifact_key_=key,
                artifact_sha256=sha,
            )
            c = await build_context(
                conn,
                storage,
                workspace_id=f.workspace_id,
                project_id=f.project_id,
                product_selection_version=f.selection_version,
            )
            assert c.icp.document_id == did and c.persona_state == "lineage_unresolved"

    run_async(case())
