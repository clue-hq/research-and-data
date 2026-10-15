"""Lineup entries → product rows through the artifact-keyed lineage (catalog contract §5)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.onboarding_lineage import CatalogProduct, synchronize_catalog
from clue_api.arv2.onboarding_reconcile import ExistingProduct, ReconcileDecision
from clue_api.arv2.onboarding_store import create_run, mark_run_running, open_document, start_step
from clue_spine import (
    archive_product,
    create_product,
    get_product,
    list_products,
    merge_products,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")
USER = "usr_o3_lineage"


async def _catalog_document(conn: AsyncConnection, ws: str) -> tuple[str, UUID]:
    project = await seed_project(conn, ws, name="O3 lineage")
    await seed_principal(conn, workspace_id=ws, user_id=USER)
    run_id, step_id, doc_id = uuid4(), uuid4(), uuid4()
    await create_run(
        conn,
        run_id=run_id,
        workspace_id=ws,
        brand_id=project.brand_id,
        company_domain="insighthealth.ai",
        requested_by_user_id=USER,
    )
    await mark_run_running(conn, run_id=run_id)
    await start_step(
        conn, step_id=step_id, run_id=run_id, workspace_id=ws, kind="lineup", phase="fast"
    )
    await open_document(
        conn,
        document_id=doc_id,
        workspace_id=ws,
        brand_id=project.brand_id,
        folder="product",
        path="product/catalog.md",
        kind="product-catalog",
        step_id=step_id,
    )
    return project.brand_id, doc_id


async def _second_document(conn: AsyncConnection, ws: str, brand_id: str) -> UUID:
    """A second catalog document under the same run — a re-run publishing the catalog again."""
    step_id, doc_id = uuid4(), uuid4()
    run_id = (
        await conn.execute(
            text("SELECT run_id FROM onboarding_run WHERE workspace_id = :ws"), {"ws": ws}
        )
    ).scalar_one()
    await start_step(
        conn, step_id=step_id, run_id=run_id, workspace_id=ws, kind="reviews", phase="fast"
    )
    await open_document(
        conn,
        document_id=doc_id,
        workspace_id=ws,
        brand_id=brand_id,
        folder="product",
        path="product/catalog.md",
        kind="product-catalog",
        step_id=step_id,
    )
    return doc_id


class ScriptedReconciler:
    """A reconciler that answers from a script and records exactly what it was shown."""

    def __init__(self, decisions: Sequence[ReconcileDecision]) -> None:
        self.decisions = tuple(decisions)
        self.calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    async def reconcile(
        self, *, existing: Sequence[ExistingProduct], candidates: Sequence[CatalogProduct]
    ) -> tuple[ReconcileDecision, ...]:
        self.calls.append((tuple(p.name for p in existing), tuple(c.name for c in candidates)))
        return self.decisions


def test_new_entries_create_products_and_lineage_and_replay_reuses_them() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-new"
            brand_id, doc_id = await _catalog_document(conn, ws)
            entries = [
                CatalogProduct(
                    name="Aura AI Scribe", short_description="Ambient documentation.", aliases=()
                ),
                CatalogProduct(
                    name="MagicFlow", short_description="Workflow orchestration.", aliases=()
                ),
            ]
            links = await synchronize_catalog(
                conn, workspace_id=ws, brand_id=brand_id, document_id=doc_id, products=entries
            )
            assert [link.resolution_state for link in links] == ["created", "created"]
            assert all(link.product_id and link.product_id.startswith("prd_") for link in links)
            assert {p.name for p in await list_products(conn, brand_id)} == {
                "Aura AI Scribe",
                "MagicFlow",
            }

            again = await synchronize_catalog(
                conn, workspace_id=ws, brand_id=brand_id, document_id=doc_id, products=entries
            )
            assert [link.resolution_state for link in again] == [
                link.resolution_state for link in links
            ]
            assert [link.product_id for link in again] == [link.product_id for link in links]
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM onboarding_product_lineage WHERE document_id = :d"),
                    {"d": doc_id},
                )
            ).scalar_one()
            assert count == 2

    run_async(scenario())


def test_an_existing_alias_or_name_hit_is_reused_and_ambiguity_is_left_open() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-alias"
            brand_id, doc_id = await _catalog_document(conn, ws)
            existing = await create_product(
                conn,
                brand_id=brand_id,
                workspace_id=ws,
                name="Aura",
                aliases=("Aura AI Scribe",),
            )
            await create_product(
                conn,
                brand_id=brand_id,
                workspace_id=ws,
                name="Phone Triage",
                aliases=("Triage",),
            )
            await create_product(
                conn,
                brand_id=brand_id,
                workspace_id=ws,
                name="Triage Agent",
                aliases=("Triage",),
            )
            links = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=[
                    CatalogProduct(name="Aura AI Scribe", short_description="x", aliases=()),
                    CatalogProduct(name="Triage", short_description="y", aliases=()),
                ],
            )
            assert (links[0].resolution_state, links[0].product_id) == (
                "alias_reused",
                existing.product_id,
            )
            assert (
                links[1].resolution_state,
                links[1].product_id,
                links[1].candidate_count,
            ) == ("unresolved_ambiguous", None, 2)

    run_async(scenario())


def test_a_second_document_creates_its_own_lineage_but_reuses_products_by_name() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-v2"
            brand_id, doc1 = await _catalog_document(conn, ws)
            first = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc1,
                products=[CatalogProduct("MagicFlow", "Orchestration.", ())],
            )
            doc2 = uuid4()
            step2 = uuid4()
            run_id = (
                await conn.execute(
                    text("SELECT run_id FROM onboarding_run WHERE workspace_id = :ws"), {"ws": ws}
                )
            ).scalar_one()
            await start_step(
                conn, step_id=step2, run_id=run_id, workspace_id=ws, kind="reviews", phase="fast"
            )
            await open_document(
                conn,
                document_id=doc2,
                workspace_id=ws,
                brand_id=brand_id,
                folder="product",
                path="product/catalog.md",
                kind="product-catalog",
                step_id=step2,
            )
            second = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc2,
                products=[CatalogProduct("MagicFlow", "Orchestration, revised.", ())],
            )
            assert second[0].product_id == first[0].product_id
            assert second[0].resolution_state == "alias_reused"

    run_async(scenario())


def test_a_changed_entry_under_the_same_document_is_refused() -> None:
    """A document version is immutable, so an ordinal whose content changed means a *different*
    catalog was re-published under the same document id. The append-only row cannot be corrected,
    so the synchronizer fails loud rather than return a link for the wrong entry."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-changed"
            brand_id, doc_id = await _catalog_document(conn, ws)
            await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=[CatalogProduct("MagicFlow", "Orchestration.", ())],
            )
            with pytest.raises(ValueError, match="changed under its lineage"):
                await synchronize_catalog(
                    conn,
                    workspace_id=ws,
                    brand_id=brand_id,
                    document_id=doc_id,
                    products=[CatalogProduct("Aura AI Scribe", "Ambient documentation.", ())],
                )
            rows = (
                await conn.execute(
                    text("SELECT count(*) FROM onboarding_product_lineage WHERE document_id = :d"),
                    {"d": doc_id},
                )
            ).scalar_one()
            assert rows == 1

    run_async(scenario())


def test_a_document_belonging_to_another_brand_is_refused_before_anything_is_written() -> None:
    """The lineage's ``document_id`` FK is single-column, so nothing structurally ties a lineage
    row's ``(workspace_id, brand_id)`` to its document's. The synchronizer checks it itself, and
    refuses *before* a product is minted or a lineage row is written."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-scope"
            brand_id, _ = await _catalog_document(conn, ws)
            other = await seed_project(conn, ws, name="O3 lineage other brand")
            step_id, doc_id = uuid4(), uuid4()
            run_id = (
                await conn.execute(
                    text("SELECT run_id FROM onboarding_run WHERE workspace_id = :ws"), {"ws": ws}
                )
            ).scalar_one()
            await start_step(
                conn,
                step_id=step_id,
                run_id=run_id,
                workspace_id=ws,
                kind="catalog_sync",
                phase="fast",
            )
            await open_document(
                conn,
                document_id=doc_id,
                workspace_id=ws,
                brand_id=other.brand_id,
                folder="product",
                path="product/catalog.md",
                kind="product-catalog",
                step_id=step_id,
            )

            with pytest.raises(ValueError, match="not in this workspace/brand"):
                await synchronize_catalog(
                    conn,
                    workspace_id=ws,
                    brand_id=brand_id,
                    document_id=doc_id,
                    products=[CatalogProduct("MagicFlow", "Orchestration.", ())],
                )

            assert await list_products(conn, brand_id) == []
            assert await list_products(conn, other.brand_id) == []
            lineage = (
                await conn.execute(
                    text("SELECT count(*) FROM onboarding_product_lineage WHERE workspace_id = :w"),
                    {"w": ws},
                )
            ).scalar_one()
            assert lineage == 0

    run_async(scenario())


def test_an_unknown_document_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-missing"
            brand_id, _ = await _catalog_document(conn, ws)
            with pytest.raises(ValueError, match="not in this workspace/brand"):
                await synchronize_catalog(
                    conn,
                    workspace_id=ws,
                    brand_id=brand_id,
                    document_id=uuid4(),
                    products=[CatalogProduct("MagicFlow", "Orchestration.", ())],
                )

    run_async(scenario())


def test_a_trademark_marked_rerun_of_a_known_product_reuses_its_row() -> None:
    """The live drift that grew one workspace's product rows from 19 to 28: a later run spelled the
    same offering ``Aura™ AI Scribe``. The fingerprint differs (it is over the raw entry), so this
    resolves on the normalized name — one product, no second row."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-marks"
            brand_id, doc_id = await _catalog_document(conn, ws)
            existing = await create_product(
                conn, brand_id=brand_id, workspace_id=ws, name="Aura AI Scribe", aliases=()
            )
            links = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=[CatalogProduct("Aura™ AI Scribe", "Ambient documentation.", ())],
            )
            assert (links[0].resolution_state, links[0].product_id) == (
                "alias_reused",
                existing.product_id,
            )
            assert [p.product_id for p in await list_products(conn, brand_id)] == [
                existing.product_id
            ]

    run_async(scenario())


def test_the_model_stage_merges_only_high_confidence_and_flags_the_rest() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-ladder"
            brand_id, doc_id = await _catalog_document(conn, ws)
            referrals = await create_product(
                conn, brand_id=brand_id, workspace_id=ws, name="Referrals AI Agent"
            )
            entries = [
                CatalogProduct(
                    "Referral Management AI Agent",
                    "Automates referral processing.",
                    (),
                    "https://x.io/referral-management",
                ),
                CatalogProduct(
                    "HEDIS AI Workflows", "HEDIS coordination.", (), "https://x.io/hedis"
                ),
                CatalogProduct("Aura Anywhere", "Mobile scribe.", (), "https://x.io/aura-anywhere"),
            ]
            reconciler = ScriptedReconciler(
                [
                    ReconcileDecision(
                        "Referral Management AI Agent",
                        "same_as_existing",
                        referrals.product_id,
                        None,
                        "high",
                        "same page",
                    ),
                    ReconcileDecision(
                        "HEDIS AI Workflows", "new_product", None, None, "high", "own page"
                    ),
                    ReconcileDecision(
                        "Aura Anywhere",
                        "same_as_existing",
                        referrals.product_id,
                        None,
                        "medium",
                        "guess",
                    ),
                ]
            )
            links = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=entries,
                reconciler=reconciler,
            )
            assert reconciler.calls == [
                (
                    ("Referrals AI Agent",),
                    ("Referral Management AI Agent", "HEDIS AI Workflows", "Aura Anywhere"),
                )
            ]
            assert (
                links[0].resolution_state,
                links[0].product_id,
                links[0].reconcile_confidence,
            ) == ("model_reused", referrals.product_id, "high")
            assert (links[1].resolution_state, links[1].reconcile_confidence) == ("created", "high")
            assert links[2].resolution_state == "model_unsure" and links[2].product_id not in (
                None,
                referrals.product_id,
            )
            assert links[2].reconcile_reason is not None
            assert links[2].reconcile_reason.startswith("suggested: Referrals AI Agent")
            product = await get_product(conn, referrals.product_id)
            assert product is not None
            assert "Referral Management AI Agent" in product.aliases
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT resolution_state, reconcile_confidence, reconcile_reason "
                            "FROM onboarding_product_lineage WHERE document_id = :d "
                            "ORDER BY entry_ordinal"
                        ),
                        {"d": doc_id},
                    )
                )
                .mappings()
                .all()
            )
            assert [r["resolution_state"] for r in rows] == [
                "model_reused",
                "created",
                "model_unsure",
            ]
            assert [r["reconcile_confidence"] for r in rows] == ["high", "high", "medium"]
            # The next run replays both model-decided bindings at rung 2, without the model: a
            # lineage row IS the durable decision, whichever rung made it (controller ruling
            # 2026-09-09). The merge lands on the row it merged onto; the unsure mint lands on
            # the row it minted.
            reconciler2 = ScriptedReconciler([])
            doc2 = await _second_document(conn, ws, brand_id)
            again = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc2,
                products=[entries[0], entries[2]],
                reconciler=reconciler2,
            )
            assert reconciler2.calls == []
            assert again[0].resolution_state == "lineage_reused"
            assert again[0].product_id == referrals.product_id
            assert again[0].reconcile_confidence is None and again[0].reconcile_reason is None
            assert again[1].resolution_state == "lineage_reused"
            assert again[1].product_id == links[2].product_id

    run_async(scenario())


def test_same_as_candidate_resolves_within_one_run_and_no_reconciler_is_todays_behaviour() -> None:
    """The brief's second scenario (its name shortened only to fit the 100-column line limit)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-ladder-batch"
            brand_id, doc_id = await _catalog_document(conn, ws)
            entries = [
                CatalogProduct("AI Front Desk", "Clinic phone operations.", (), "https://x.io/fd"),
                CatalogProduct("AI FrontDesk Agent", "Clinic phone operations.", (), None),
            ]
            reconciler = ScriptedReconciler(
                [
                    ReconcileDecision("AI Front Desk", "new_product", None, None, "high", "first"),
                    ReconcileDecision(
                        "AI FrontDesk Agent",
                        "same_as_candidate",
                        None,
                        "AI Front Desk",
                        "high",
                        "same job, no page",
                    ),
                ]
            )
            links = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=entries,
                reconciler=reconciler,
            )
            assert links[0].resolution_state == "created"
            assert links[1].resolution_state == "model_reused"
            assert links[1].product_id == links[0].product_id
            assert len(await list_products(conn, brand_id)) == 1
            merged = await get_product(conn, str(links[0].product_id))
            assert merged is not None and "AI FrontDesk Agent" in merged.aliases
            # no reconciler → both minted, exactly as before this plan
            doc2 = await _second_document(conn, ws, brand_id)
            plain = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc2,
                products=[CatalogProduct("Something Else", "x", (), None)],
            )
            assert plain[0].resolution_state == "created"
            assert plain[0].reconcile_confidence is None and plain[0].reconcile_reason is None

    run_async(scenario())


def test_a_repeated_spelling_of_a_leftover_never_reaches_the_model() -> None:
    """Controller ruling: leftovers handed to the model are unique by spelling key. A later entry
    whose key is an earlier leftover's key follows that leftover — so the model never sees two
    candidates with one key, and the name-keyed validator stays unambiguous."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-ladder-dupe"
            brand_id, doc_id = await _catalog_document(conn, ws)
            entries = [
                CatalogProduct("AI Front Desk", "Clinic phone operations.", (), None),
                CatalogProduct("AI FrontDesk", "Clinic phone operations, again.", (), None),
                CatalogProduct("Aura AI Scribe", "Ambient documentation.", (), None),
            ]
            reconciler = ScriptedReconciler(
                [
                    ReconcileDecision("AI Front Desk", "new_product", None, None, "high", "one"),
                    ReconcileDecision("Aura AI Scribe", "new_product", None, None, "high", "two"),
                ]
            )
            links = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=entries,
                reconciler=reconciler,
            )
            assert reconciler.calls == [((), ("AI Front Desk", "Aura AI Scribe"))]
            assert [link.resolution_state for link in links] == [
                "created",
                "alias_reused",
                "created",
            ]
            assert links[1].product_id == links[0].product_id
            assert links[1].reconcile_confidence is None
            assert len(await list_products(conn, brand_id)) == 2

    run_async(scenario())


def test_a_replay_mirrors_the_reconcile_columns_and_never_asks_the_model_again() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-ladder-replay"
            brand_id, doc_id = await _catalog_document(conn, ws)
            existing = await create_product(
                conn, brand_id=brand_id, workspace_id=ws, name="Referrals AI Agent"
            )
            entries = [
                CatalogProduct("Aura Anywhere", "Mobile scribe.", (), "https://x.io/aura"),
            ]
            reconciler = ScriptedReconciler(
                [
                    ReconcileDecision(
                        "Aura Anywhere",
                        "same_as_existing",
                        existing.product_id,
                        None,
                        "low",
                        "a guess",
                    )
                ]
            )
            first = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=entries,
                reconciler=reconciler,
            )
            assert first[0].resolution_state == "model_unsure"
            assert first[0].reconcile_confidence == "low"
            assert first[0].reconcile_reason == "suggested: Referrals AI Agent — a guess"

            replayed = ScriptedReconciler([])
            again = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=entries,
                reconciler=replayed,
            )
            assert again == first
            assert replayed.calls == []

    run_async(scenario())


# --- spec 2026-10-15 §9: a re-run respects what a person decided -------------------------------


def test_an_entry_spelled_like_a_merged_product_reuses_the_survivor() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-merged"
            brand_id, doc_id = await _catalog_document(conn, ws)
            feature = await create_product(
                conn, brand_id=brand_id, workspace_id=ws, name="Proxon Observer"
            )
            platform = await create_product(conn, brand_id=brand_id, workspace_id=ws, name="Proxon")
            await merge_products(
                conn,
                product_ids=[feature.product_id],
                into_product_id=platform.product_id,
                workspace_id=ws,
            )
            links = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=[
                    CatalogProduct(
                        name="Proxon Observer", short_description="A feature.", aliases=()
                    ),
                    CatalogProduct(name="Proxon", short_description="The platform.", aliases=()),
                ],
            )
            assert [(link.product_id, link.resolution_state) for link in links] == [
                (platform.product_id, "alias_reused"),
                (platform.product_id, "alias_reused"),
            ]
            assert [link.redirected for link in links] == [True, False]
            assert {p.name for p in await list_products(conn, brand_id)} == {
                "Proxon Observer",
                "Proxon",
            }

    run_async(scenario())


def test_an_entry_spelled_like_a_removed_product_stays_removed_on_replay_too() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-removed"
            brand_id, doc_id = await _catalog_document(conn, ws)
            removed = await create_product(
                conn, brand_id=brand_id, workspace_id=ws, name="Proxon Levels"
            )
            await archive_product(conn, product_id=removed.product_id, workspace_id=ws)
            entries = [
                CatalogProduct(name="Proxon Levels", short_description="Levels.", aliases=())
            ]
            for _ in range(2):  # the second pass is the replay of the same document
                links = await synchronize_catalog(
                    conn,
                    workspace_id=ws,
                    brand_id=brand_id,
                    document_id=doc_id,
                    products=entries,
                )
                assert [(link.product_id, link.resolution_state) for link in links] == [
                    (None, "removed_by_person")
                ]
            row = (
                await conn.execute(
                    text("SELECT product_id FROM onboarding_product_lineage WHERE document_id=:d"),
                    {"d": doc_id},
                )
            ).scalar_one()
            assert row == removed.product_id
            assert len(await list_products(conn, brand_id)) == 1

    run_async(scenario())


def test_a_fingerprint_bound_to_a_merged_product_replays_onto_the_survivor() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-prior-merged"
            brand_id, first_doc = await _catalog_document(conn, ws)
            entry = CatalogProduct(name="Proxon Spend", short_description="Spend.", aliases=())
            (first,) = await synchronize_catalog(
                conn, workspace_id=ws, brand_id=brand_id, document_id=first_doc, products=[entry]
            )
            assert first.product_id is not None
            platform = await create_product(conn, brand_id=brand_id, workspace_id=ws, name="Proxon")
            await merge_products(
                conn,
                product_ids=[first.product_id],
                into_product_id=platform.product_id,
                workspace_id=ws,
            )
            second_doc = await _second_document(conn, ws, brand_id)
            (again,) = await synchronize_catalog(
                conn, workspace_id=ws, brand_id=brand_id, document_id=second_doc, products=[entry]
            )
            assert (again.product_id, again.resolution_state, again.redirected) == (
                platform.product_id,
                "lineage_reused",
                True,
            )

    run_async(scenario())


def test_the_model_stage_is_shown_active_products_only() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-model-active"
            brand_id, doc_id = await _catalog_document(conn, ws)
            kept = await create_product(conn, brand_id=brand_id, workspace_id=ws, name="Kept")
            gone = await create_product(conn, brand_id=brand_id, workspace_id=ws, name="Gone")
            await archive_product(conn, product_id=gone.product_id, workspace_id=ws)
            reconciler = ScriptedReconciler([])
            await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=[CatalogProduct(name="Brand new", short_description="New.", aliases=())],
                reconciler=reconciler,
            )
            assert reconciler.calls and reconciler.calls[0][0] == (kept.name,)

    run_async(scenario())
