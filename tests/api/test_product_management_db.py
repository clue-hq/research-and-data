"""Product management end to end on a real database (spec 2026-10-15 §5, §7, §12).

Each scenario seeds a brand the way onboarding leaves it — product rows, one page per product, a
catalog — plus projects holding product sets, then acts through the service and checks every
place the product list lives: the table, the pages, the catalog, the projects and the change log.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.product_management import (
    CATALOG_PATH,
    ProductActor,
    ProductChangeRefused,
    add_product,
    list_brand_products,
    merge_products_action,
    publish_product_page,
    recent_product_changes,
    remove_product_action,
    rename_product_action,
    undo_product_change,
)
from clue_spine import (
    confirm_project_product_set,
    create_product,
    create_project,
    current_project_product_set,
    get_product,
)
from clue_storage import read_verified_artifact
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.test_frontend_read_brand_knowledge import _document
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")

USER = "usr_product_management"
ACTOR = ProductActor(USER)
FEATURES = [
    "Proxon Observer",
    "Proxon Levels",
    "Proxon Own",
    "Proxon Spend",
    "Proxon Inventory",
    "Proxon Policies",
    "Proxon Lineage",
    "Proxon Alerts",
]


def _page(product_id: str, name: str) -> str:
    return (
        f"---\nkind: product-research\nproduct_id: {product_id}\nproduct_name: {name}\n---\n\n"
        f"# {name}\n\nResearch about {name}.\n"
    )


def _catalog(names: list[str]) -> str:
    entries = "".join(
        f"- name: {n}\n  short_description: About {n}.\n  offering_kind: feature\n" for n in names
    )
    head = "---\nkind: product-catalog\ncompany_domain: proxon.ai\nproducts:\n"
    return f"{head}{entries}---\n\n# Product catalog\n"


class _Brand:
    def __init__(self, conn: AsyncConnection, ws: str) -> None:
        self.conn = conn
        self.ws = ws
        self.storage = _MemoryStorage()
        self.artifacts = DurableAgentArtifactStore(
            storage=self.storage, conn_factory=conn_session_factory(conn)
        )
        self.brand = ""
        self.products: dict[str, str] = {}
        self.projects: list[str] = []

    async def seed(self, names: list[str]) -> _Brand:
        project = await seed_project(self.conn, self.ws, name="Proxon")
        await seed_principal(self.conn, workspace_id=self.ws, user_id=USER)
        self.brand = project.brand_id
        self.projects.append(project.project_id)
        for name in names:
            product = await create_product(
                self.conn, brand_id=self.brand, workspace_id=self.ws, name=name
            )
            self.products[name] = product.product_id
            await self.page(
                f"product/{name.lower().replace(' ', '-')}.md", product.product_id, name
            )
        await _document(
            self.conn,
            self.artifacts,
            ws=self.ws,
            brand_id=self.brand,
            folder="product",
            path=CATALOG_PATH,
            kind="product-catalog",
            version=1,
            status="ready",
            body=_catalog(names),
        )
        return self

    async def page(self, path: str, product_id: str, name: str) -> None:
        await _document(
            self.conn,
            self.artifacts,
            ws=self.ws,
            brand_id=self.brand,
            folder="product",
            path=path,
            kind="product-research",
            version=1,
            status="ready",
            body=_page(product_id, name),
        )

    async def project(self, names: list[str]) -> str:
        project = await create_project(
            self.conn, workspace_id=self.ws, brand_id=self.brand, name=f"P{len(self.projects)}"
        )
        self.projects.append(project.project_id)
        await self.set(project.project_id, names)
        return project.project_id

    async def set(self, project_id: str, names: list[str]) -> None:
        await confirm_project_product_set(
            self.conn,
            workspace_id=self.ws,
            project_id=project_id,
            product_ids=[self.products[n] for n in names],
            gate_id=uuid4(),
            confirmed_by_user_id=USER,
        )

    async def current_set(self, project_id: str) -> tuple[str, ...]:
        current = await current_project_product_set(
            self.conn, workspace_id=self.ws, project_id=project_id
        )
        assert current is not None
        return current.product_ids

    async def servable(self) -> dict[str, tuple[dict, str]]:
        rows = await self.conn.execute(
            text(
                "SELECT d.path, d.artifact_key FROM brand_knowledge_document d "
                "WHERE d.workspace_id = :ws AND d.brand_id = :brand AND d.folder = 'product' "
                "AND d.project_id IS NULL AND d.status IN ('ready','proposed','confirmed') "
                "AND d.version = (SELECT MAX(version) FROM brand_knowledge_document d2 "
                " WHERE d2.workspace_id = d.workspace_id AND d2.brand_id = d.brand_id "
                " AND d2.path = d.path AND d2.project_id IS NULL "
                " AND d2.status IN ('ready','proposed','confirmed'))"
            ),
            {"ws": self.ws, "brand": self.brand},
        )
        out = {}
        for row in rows.mappings().all():
            _, raw = await read_verified_artifact(
                self.conn, self.storage, storage_key=row["artifact_key"], workspace_id=self.ws
            )
            out[row["path"]] = parse_front_matter(raw.decode(), preserve_body=True)
        return out


def test_proxon_nine_features_merge_into_one_product_everywhere() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-pm-proxon").seed([*FEATURES, "Proxon"])
            everything = await brand.project([*FEATURES, "Proxon"])
            some = await brand.project(["Proxon Observer", "Proxon Levels"])
            result = await merge_products_action(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ACTOR,
                product_ids=[brand.products[n] for n in FEATURES],
                into_product_id=brand.products["Proxon"],
                page_markdown="## Overview\n\nOne platform for managing an AI workforce.",
            )
            survivor = brand.products["Proxon"]
            assert result.text == "8 products merged into Proxon"
            assert not result.page_pending
            pages = await brand.servable()
            # Only the survivor's page and the catalog are left in the product folder.
            assert set(pages) == {"product/proxon.md", CATALOG_PATH}
            front, body = pages["product/proxon.md"]
            assert front["product_id"] == survivor
            assert body.startswith("# Proxon") and "AI workforce" in body
            catalog, catalog_body = pages[CATALOG_PATH]
            assert catalog["generated"] is True
            assert [e["name"] for e in catalog["products"]] == ["Proxon"]
            assert catalog["products"][0]["aliases"] == FEATURES
            assert "Proxon Observer" in catalog_body
            for project_id in (everything, some):
                assert await brand.current_set(project_id) == (survivor,)
            # The original project held no merged product, so it was not touched.
            assert {p.project_id for p in result.projects} == {everything, some}
            assert {p.outcome for p in result.projects} == {"updated"}
            merged = await get_product(conn, brand.products["Proxon Levels"])
            assert merged is not None and (merged.status, merged.merged_into) == (
                "merged",
                survivor,
            )
            products = await list_brand_products(
                conn, brand.storage, workspace_id=brand.ws, brand_id=brand.brand
            )
            assert [p.name for p in products] == ["Proxon"]

    run_async(scenario())


def test_rename_moves_the_page_and_keeps_the_old_name_findable() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-pm-rename").seed(["Proxon Platform"])
            result = await rename_product_action(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ACTOR,
                product_id=brand.products["Proxon Platform"],
                name="Proxon",
            )
            assert result.text == "Proxon Platform renamed to Proxon"
            pages = await brand.servable()
            assert "product/proxon-platform.md" not in pages
            front, body = pages["product/proxon.md"]
            assert front["product_name"] == "Proxon" and body.startswith("# Proxon\n")
            assert pages[CATALOG_PATH][0]["products"][0]["name"] == "Proxon"
            # The catalog row kept what research found about the product.
            assert (
                pages[CATALOG_PATH][0]["products"][0]["short_description"]
                == "About Proxon Platform."
            )
            assert result.product.aliases == ("Proxon Platform",)
            with pytest.raises(ProductChangeRefused) as refused:
                await rename_product_action(
                    conn,
                    brand.storage,
                    workspace_id=brand.ws,
                    brand_id=brand.brand,
                    actor=ACTOR,
                    product_id=brand.products["Proxon Platform"],
                    name="   ",
                )
            assert refused.value.code == "name_invalid"

    run_async(scenario())


def test_removing_a_projects_only_product_asks_for_a_choice() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-pm-remove").seed(["A", "B"])
            only_a = await brand.project(["A"])
            both = await brand.project(["A", "B"])
            result = await remove_product_action(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ACTOR,
                product_id=brand.products["A"],
            )
            outcomes = {p.project_id: p.outcome for p in result.projects}
            assert outcomes == {only_a: "needs_choice", both: "updated"}
            assert await brand.current_set(only_a) == (brand.products["A"],)
            assert await brand.current_set(both) == (brand.products["B"],)
            assert "product/a.md" not in await brand.servable()
            with pytest.raises(ProductChangeRefused) as refused:
                await remove_product_action(
                    conn,
                    brand.storage,
                    workspace_id=brand.ws,
                    brand_id=brand.brand,
                    actor=ACTOR,
                    product_id=brand.products["A"],
                )
            assert refused.value.code == "product_not_active"

    run_async(scenario())


def test_undoing_a_merge_restores_products_pages_and_untouched_projects() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-pm-undo").seed(["A", "B", "Proxon"])
            untouched = await brand.project(["A", "Proxon"])
            changed = await brand.project(["B"])
            merge = await merge_products_action(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ACTOR,
                product_ids=[brand.products["A"], brand.products["B"]],
                into_product_id=brand.products["Proxon"],
                page_markdown="Proxon, one platform.",
            )
            # Someone sets the second project's products again after the merge.
            await brand.set(changed, ["Proxon"])
            undo = await undo_product_change(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ACTOR,
                change_id=merge.change_id,
            )
            assert undo.text == "Undone: 2 products merged into Proxon"
            assert {p.project_id: p.outcome for p in undo.projects} == {
                untouched: "restored",
                changed: "left_as_is",
            }
            assert await brand.current_set(untouched) == (
                brand.products["A"],
                brand.products["Proxon"],
            )
            for name in ("A", "B"):
                product = await get_product(conn, brand.products[name])
                assert product is not None and product.status == "active"
            survivor = await get_product(conn, brand.products["Proxon"])
            assert survivor is not None and survivor.aliases == ()
            pages = await brand.servable()
            assert {"product/a.md", "product/b.md", "product/proxon.md"} <= set(pages)
            assert [e["name"] for e in pages[CATALOG_PATH][0]["products"]] == [
                "A",
                "B",
                "Proxon",
            ]
            with pytest.raises(ProductChangeRefused) as again:
                await undo_product_change(
                    conn,
                    brand.storage,
                    workspace_id=brand.ws,
                    brand_id=brand.brand,
                    actor=ACTOR,
                    change_id=merge.change_id,
                )
            assert again.value.code == "change_not_undoable"
            lines = await recent_product_changes(
                conn,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                since=undo.product.created_at.replace(year=2000),
            )
            assert [(line.kind, line.undoable) for line in lines] == [
                ("restore", False),
                ("merge", False),
            ]

    run_async(scenario())


def test_an_app_add_opens_a_pending_page_the_writer_fills() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-pm-add").seed(["A"])
            result = await add_product(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ACTOR,
                name="Proxon Agents",
                description="Agents that run work.",
            )
            assert result.page_pending and result.page_document_id is not None
            listed = {
                p.name: p
                for p in await list_brand_products(
                    conn, brand.storage, workspace_id=brand.ws, brand_id=brand.brand
                )
            }
            assert listed["Proxon Agents"].page_pending
            assert "product/proxon-agents.md" not in await brand.servable()
            assert await publish_product_page(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                document_id=result.page_document_id,
                product_id=result.product.product_id,
                change_id=result.change_id,
                actor_user_id=USER,
                markdown="## Overview\n\nAgents that run work.",
            )
            front, body = (await brand.servable())["product/proxon-agents.md"]
            assert front["product_id"] == result.product.product_id
            assert body.startswith("# Proxon Agents")
            with pytest.raises(ProductChangeRefused) as taken:
                await add_product(
                    conn,
                    brand.storage,
                    workspace_id=brand.ws,
                    brand_id=brand.brand,
                    actor=ACTOR,
                    name="proxon agents",
                )
            assert taken.value.code == "product_name_taken"

    run_async(scenario())


def test_the_same_idempotency_key_replays_the_first_change() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-pm-replay").seed(["A", "B"])
            actor = ProductActor(USER, uuid4())

            async def merge():
                return await merge_products_action(
                    conn,
                    brand.storage,
                    workspace_id=brand.ws,
                    brand_id=brand.brand,
                    actor=actor,
                    product_ids=[brand.products["A"]],
                    into_product_id=brand.products["B"],
                    page_markdown="B.",
                    idempotency_key="turn:x:merge",
                )

            first = await merge()
            second = await merge()
            assert second.replayed and second.change_id == first.change_id
            count = await conn.scalar(
                text("SELECT count(*) FROM product_change WHERE workspace_id = :ws"),
                {"ws": brand.ws},
            )
            assert count == 1

    run_async(scenario())


def test_a_merge_into_a_new_name_that_a_member_already_has_keeps_that_member() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-pm-new-name").seed(["Proxon", "Proxon Levels"])
            result = await merge_products_action(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ACTOR,
                product_ids=[brand.products["Proxon"], brand.products["Proxon Levels"]],
                new_name="proxon",
                page_markdown="Proxon.",
            )
            assert result.product.product_id == brand.products["Proxon"]
            assert result.text == "Proxon Levels merged into Proxon"
            refused = None
            try:
                await merge_products_action(
                    conn,
                    brand.storage,
                    workspace_id=brand.ws,
                    brand_id=brand.brand,
                    actor=ACTOR,
                    product_ids=[brand.products["Proxon"]],
                    into_product_id=brand.products["Proxon"],
                )
            except ProductChangeRefused as error:
                refused = error.code
            assert refused == "merge_invalid"

    run_async(scenario())


def test_a_change_names_the_person_and_the_turn() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-pm-actor").seed(["A"])
            turn = uuid4()
            result = await remove_product_action(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ProductActor(USER, turn),
                product_id=brand.products["A"],
            )
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT actor_user_id, actor_turn_id FROM product_change "
                            "WHERE change_id = :id"
                        ),
                        {"id": result.change_id},
                    )
                )
                .mappings()
                .one()
            )
            assert (row["actor_user_id"], UUID(str(row["actor_turn_id"]))) == (USER, turn)

    run_async(scenario())
