"""The background product-page writer (spec 2026-10-15 §6), against a real database."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.product_management import ProductActor, add_product, merge_products_action
from clue_api.product_page_writer import (
    PRODUCT_PAGE_SYSTEM_PROMPT,
    ProductPageWorkHandler,
    offer_product_page,
    product_page_messages,
    product_page_work_id,
)
from clue_fleet import FleetTaskKind, LeaseGeneration, WorkContext
from tests.api.test_product_management_db import USER, _Brand
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

ACTOR = ProductActor(USER)


class _Model:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.messages: list[dict[str, str]] = []

    async def write(self, *, messages, workspace_id, change_id):  # noqa: ANN001
        del workspace_id, change_id
        self.messages = messages
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class _Queue:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        return True


def _context(payload: dict) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=product_page_work_id(UUID(payload.get("document_id", str(uuid4())))),
        worker_id="t",
        lease_generation=LeaseGeneration(1),
        payload=payload,
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


async def _status(conn, document_id: UUID) -> str:  # noqa: ANN001
    return await conn.scalar(
        text("SELECT status FROM brand_knowledge_document WHERE document_id = :id"),
        {"id": document_id},
    )


@pytest.mark.usefixtures("require_profiling_db")
def test_an_app_merge_is_written_from_the_merged_pages_and_published() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-ppw-merge").seed(["Proxon Observer", "Proxon"])
            result = await merge_products_action(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ACTOR,
                product_ids=[brand.products["Proxon Observer"]],
                into_product_id=brand.products["Proxon"],
            )
            assert result.page_pending
            queue = _Queue()
            assert await offer_product_page(
                queue,
                result=result,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor_user_id=USER,
            )
            (offer,) = queue.calls
            assert offer["kind"] == FleetTaskKind.PRODUCT_PAGE_WRITE
            model = _Model("## Overview\n\nOne platform; the Observer is a part of it.")
            handler = ProductPageWorkHandler(
                storage=brand.storage, model=model, conn_factory=conn_session_factory(conn)
            )
            outcome = await handler.handle(_context(offer["payload"]))
            assert outcome.outcome == "completed"
            prompt = model.messages[1]["content"]
            assert model.messages[0]["content"] == PRODUCT_PAGE_SYSTEM_PROMPT
            assert "Research about Proxon Observer." in prompt
            assert "Research about Proxon." in prompt
            assert "Also called: Proxon Observer" in prompt
            assert result.page_document_id is not None
            assert await _status(conn, result.page_document_id) == "ready"
            front, body = (await brand.servable())["product/proxon.md"]
            assert body.startswith("# Proxon\n") and "a part of it" in body
            assert front["written_by"]["change_id"] == str(result.change_id)

    run_async(scenario())


@pytest.mark.usefixtures("require_profiling_db")
def test_a_failed_call_marks_the_page_failed_and_never_raises() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-ppw-fail").seed(["A"])
            result = await add_product(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ACTOR,
                name="Proxon Agents",
                description="Agents that run work.",
            )
            queue = _Queue()
            await offer_product_page(
                queue,
                result=result,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor_user_id=USER,
            )
            model = _Model(RuntimeError("provider down"))
            handler = ProductPageWorkHandler(
                storage=brand.storage, model=model, conn_factory=conn_session_factory(conn)
            )
            outcome = await handler.handle(_context(queue.calls[0]["payload"]))
            assert (outcome.outcome, outcome.requeue) == ("failed", False)
            assert (
                "Description from a person: Agents that run work." in model.messages[1]["content"]
            )
            assert result.page_document_id is not None
            assert await _status(conn, result.page_document_id) == "failed"
            bad = await handler.handle(_context({"workspace_id": brand.ws}))
            assert bad.outcome == "failed"

    run_async(scenario())


def test_nothing_is_offered_for_a_change_whose_page_was_written_in_chat() -> None:
    class _Result:
        page_pending = False
        page_document_id = None

    queue = _Queue()
    assert not run_async(
        offer_product_page(
            queue,
            result=_Result(),  # type: ignore[arg-type]
            workspace_id="ws",
            brand_id="b",
            actor_user_id=USER,
        )
    )
    assert queue.calls == []


def test_the_messages_split_the_source_budget_and_say_when_there_is_nothing() -> None:
    empty = product_page_messages(product_name="X", aliases=(), description=None, sources=())
    assert "No source material is available yet." in empty[1]["content"]
    long = product_page_messages(
        product_name="X",
        aliases=("Y",),
        description=None,
        sources=[("a", "a" * 200_000), ("b", "b" * 200_000)],
    )
    assert long[1]["content"].count("a") < 70_000
