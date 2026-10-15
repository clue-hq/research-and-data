"""The background product-page writer (spec 2026-10-15 product management §6).

When a person adds or merges products in Brand context, the action opens a pending (``running``)
page row and offers one ``product_page_write`` fleet task after its transaction commits. The task
gathers what is known — the pages being merged, the survivor's own page, or the description the
person typed — makes one model call through the spend ledger (the ``conversation_naming`` shape)
and publishes the page. In chat the Head of ABM writes the page itself, so no task is offered.

The handler never raises: a failure marks the page ``failed`` (not served; the product stays on the
list and in the catalog) and ends the task ``failed`` without a requeue.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue, SecretStr

from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_api.product_management import (
    ProductChangeResult,
    change_details,
    main_page_of,
    mark_product_page_failed,
    publish_product_page,
    read_brand_document,
)
from clue_config import Secrets, Settings
from clue_config.gateway import GatewayConfig
from clue_db import ConnFactory, transaction
from clue_fleet import FleetTaskKind, WorkContext, WorkId, WorkQueue, WorkResult
from clue_obs import get_logger
from clue_spend.calls import CallSpec, ProviderCaller, SpendEstimate
from clue_spend.ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_spend.transport import HttpxTransport, Transport
from clue_spine import get_product
from clue_storage import StorageBackend

__all__ = [
    "PRODUCT_PAGE_SYSTEM_PROMPT",
    "OpenRouterProductPageModel",
    "ProductPageModel",
    "ProductPageWorkHandler",
    "build_product_page_handler",
    "offer_product_page",
    "product_page_messages",
    "product_page_payload",
    "product_page_work_id",
]

log = get_logger("clue_api.product_page_writer")

PRODUCT_PAGE_DEDUP_PREFIX = "product-page:"
#: Below research and discovery (they produce facts), level with display pages: a person is
#: waiting on the page they just asked for.
PRODUCT_PAGE_TASK_PRIORITY = -80
PRODUCT_PAGE_LABEL = "product-page-writer"
PRODUCT_PAGE_ESTIMATE_USD = Decimal("0.05")
PRODUCT_PAGE_MAX_TOKENS = 6_000
#: The most source text one call is shown, in characters, split evenly across the source pages.
PRODUCT_PAGE_SOURCE_CHARS = 120_000

PRODUCT_PAGE_SYSTEM_PROMPT = """\
You write one product's page for a company's Brand context. Sales and marketing people read it, and
an AI agent uses it to plan campaigns.

You are given the product's name, any other names it has been called, and the source material:
pages written earlier about this product or about the parts that were combined into it, or a short
description a person typed.

Write the page in Markdown with these sections, in this order:

## Overview
## Capabilities
## Use cases
## Who it is for
## Integrations
## Pricing
## Differentiators
## Competitors
## Customer evidence
## Not established

Rules:
- Use only facts found in the source material. Do not add facts from your own knowledge.
- When the sources describe parts of one product (for example features that were listed as
  separate products), describe them as parts of this product, not as separate products.
- Keep links to sources where the source material has them.
- Where nothing is known for a section, write "_Not established._" under it, and list what is
  missing in the "Not established" section.
- Write plainly. No marketing language, no headline above the first section (the title is added
  for you), no closing summary.
Reply with the Markdown only.
"""


def product_page_work_id(document_id: UUID) -> WorkId:
    """One task per pending page: offering the same page twice is one task."""
    return WorkId(uuid5(NAMESPACE_URL, f"clue:product-page:{document_id}"))


def product_page_payload(
    *,
    workspace_id: str,
    brand_id: str,
    document_id: UUID,
    product_id: str,
    change_id: UUID,
    actor_user_id: str,
) -> dict[str, JsonValue]:
    return {
        "workspace_id": workspace_id,
        "brand_id": brand_id,
        "document_id": str(document_id),
        "product_id": product_id,
        "change_id": str(change_id),
        "actor_user_id": actor_user_id,
    }


async def offer_product_page(
    queue: WorkQueue | None,
    *,
    result: ProductChangeResult,
    workspace_id: str,
    brand_id: str,
    actor_user_id: str,
) -> bool:
    """Offer the page task for a change whose page is pending — AFTER the change committed.

    ``False`` (logged, never raised) when there is nothing to offer or the queue failed: the
    product and catalog are already saved; only the page stays "being written".
    """
    if not result.page_pending or result.page_document_id is None:
        return False
    if queue is None:
        log.warning(
            "product_page.offer_skipped",
            reason="no work queue composed",
            document_id=str(result.page_document_id),
        )
        return False
    try:
        await queue.enqueue(
            kind=FleetTaskKind.PRODUCT_PAGE_WRITE,
            work_id=product_page_work_id(result.page_document_id),
            dedup_key=f"{PRODUCT_PAGE_DEDUP_PREFIX}{result.page_document_id}",
            priority=PRODUCT_PAGE_TASK_PRIORITY,
            payload=product_page_payload(
                workspace_id=workspace_id,
                brand_id=brand_id,
                document_id=result.page_document_id,
                product_id=result.product.product_id,
                change_id=result.change_id,
                actor_user_id=actor_user_id,
            ),
        )
    except Exception:  # noqa: BLE001 — a queue outage must not undo a saved change
        log.warning(
            "product_page.offer_failed",
            document_id=str(result.page_document_id),
            exc_info=True,
        )
        return False
    return True


def product_page_messages(
    *,
    product_name: str,
    aliases: Sequence[str],
    description: str | None,
    sources: Sequence[tuple[str, str]],
) -> list[dict[str, str]]:
    """The call's messages. ``sources`` are ``(title, markdown)`` pairs, trimmed to fit."""
    share = PRODUCT_PAGE_SOURCE_CHARS // max(len(sources), 1)
    parts = [f"Product name: {product_name}"]
    if aliases:
        parts.append("Also called: " + ", ".join(aliases))
    if description:
        parts.append(f"Description from a person: {description}")
    for index, (title, body) in enumerate(sources, start=1):
        parts.append(f"--- Source {index}: {title} ---\n{body[:share]}")
    if not sources and not description:
        parts.append("No source material is available yet.")
    return [
        {"role": "system", "content": PRODUCT_PAGE_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


class ProductPageModel(Protocol):
    async def write(
        self, *, messages: list[dict[str, str]], workspace_id: str, change_id: UUID
    ) -> str:
        """The page's Markdown. Raises on any failure."""


class ProductPageWriteFailed(RuntimeError):
    pass


class OpenRouterProductPageModel:
    """One OpenRouter call through the spend-ledger caller; the raw bodies and the ledger row are
    drained with the change id as the job."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_s: float,
        artifacts: ArtifactSink | None,
        conn_factory: ConnFactory = transaction,
        transport_factory: Callable[[], Transport] = HttpxTransport,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout_s = timeout_s
        self._artifacts = artifacts
        self._conn_factory = conn_factory
        self._transport_factory = transport_factory

    async def write(
        self, *, messages: list[dict[str, str]], workspace_id: str, change_id: UUID
    ) -> str:
        spec = CallSpec(
            provider="openrouter",
            operation="chat/completions",
            label=PRODUCT_PAGE_LABEL,
            request=openrouter_chat_request(
                base_url=self._base_url,
                api_key=self._api_key,
                model=self._model,
                messages=messages,
                max_tokens=PRODUCT_PAGE_MAX_TOKENS,
                temperature=0.2,
                timeout_s=self._timeout_s,
            ),
            estimate=SpendEstimate(usd=PRODUCT_PAGE_ESTIMATE_USD),
            max_attempts=1,
            cost_reader=openrouter_cost_reader,
            halt_rule=openrouter_halt_rule,
            extras={"change_id": str(change_id)},
        )
        raw, ledger = BufferedRawSink(), BufferedLedger()
        caller = ProviderCaller(
            transport=self._transport_factory(),
            raw_sink=raw,
            ledger=ledger,
            now=lambda: datetime.now(UTC),
        )
        try:
            # ``ProviderCaller.call`` is synchronous (httpx); keep the worker loop free.
            result = await asyncio.to_thread(caller.call, spec)
        finally:
            async with self._conn_factory() as conn:
                await drain_provider_calls(
                    conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=self._artifacts,
                    stamp=LedgerStamp(workspace_id=workspace_id, job_id=change_id),
                )
        if result.response.status >= 400:
            raise ProductPageWriteFailed(f"provider status {result.response.status}")
        markdown = (openrouter_message_text(result.json()) or "").strip()
        if not markdown:
            raise ProductPageWriteFailed("the model returned no page")
        return markdown


@dataclass(frozen=True)
class _Task:
    workspace_id: str
    brand_id: str
    document_id: UUID
    product_id: str
    change_id: UUID
    actor_user_id: str


def _task(payload: Mapping[str, JsonValue]) -> _Task | None:
    try:
        return _Task(
            workspace_id=str(payload["workspace_id"]),
            brand_id=str(payload["brand_id"]),
            document_id=UUID(str(payload["document_id"])),
            product_id=str(payload["product_id"]),
            change_id=UUID(str(payload["change_id"])),
            actor_user_id=str(payload["actor_user_id"]),
        )
    except (KeyError, ValueError, TypeError):
        return None


class ProductPageWorkHandler:
    """One pending product page, as one fleet work handler."""

    kind = FleetTaskKind.PRODUCT_PAGE_WRITE

    def __init__(
        self,
        *,
        storage: StorageBackend,
        model: ProductPageModel,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._storage = storage
        self._model = model
        self._conn_factory = conn_factory

    async def handle(self, context: WorkContext) -> WorkResult:
        """Write the page. Never raises: every ending is a :class:`WorkResult`."""
        task = _task(context.payload)
        if task is None:
            log.error("product_page.invalid_payload", payload=sorted(context.payload))
            return WorkResult(outcome="failed", references={}, requeue=False)
        try:
            messages = await self._messages(task)
            if messages is None:
                return WorkResult(
                    outcome="failed", references={"reason": "product_gone"}, requeue=False
                )
            markdown = await self._model.write(
                messages=messages, workspace_id=task.workspace_id, change_id=task.change_id
            )
            async with self._conn_factory() as conn:
                published = await publish_product_page(
                    conn,
                    self._storage,
                    workspace_id=task.workspace_id,
                    brand_id=task.brand_id,
                    document_id=task.document_id,
                    product_id=task.product_id,
                    change_id=task.change_id,
                    actor_user_id=task.actor_user_id,
                    markdown=markdown,
                )
        except Exception as exc:  # noqa: BLE001 — a failed page must never escape the handler
            log.warning(
                "product_page.write_failed",
                document_id=str(task.document_id),
                reason=type(exc).__name__,
                exc_info=True,
            )
            await self._fail(task)
            return WorkResult(
                outcome="failed", references={"reason": type(exc).__name__}, requeue=False
            )
        if not published:
            return WorkResult(
                outcome="failed", references={"reason": "page_superseded"}, requeue=False
            )
        log.info("product_page.written", document_id=str(task.document_id))
        return WorkResult(
            outcome="completed",
            references={"document_id": str(task.document_id)},
            requeue=False,
        )

    async def _messages(self, task: _Task) -> list[dict[str, str]] | None:
        async with self._conn_factory() as conn:
            product = await get_product(conn, task.product_id)
            if product is None or product.status != "active":
                await mark_product_page_failed(conn, document_id=task.document_id)
                return None
            details = (
                await change_details(conn, workspace_id=task.workspace_id, change_id=task.change_id)
                or {}
            )
            sources: list[tuple[str, str]] = []
            own = await main_page_of(
                conn,
                self._storage,
                workspace_id=task.workspace_id,
                brand_id=task.brand_id,
                product_id=task.product_id,
            )
            if own is not None:
                sources.append((f"The current page about {product.name}", own[1]))
            retired: dict[str, Any] = details.get("retired_pages") or {}
            for document_id in retired.values():
                read = await read_brand_document(
                    conn,
                    self._storage,
                    workspace_id=task.workspace_id,
                    brand_id=task.brand_id,
                    document_id=UUID(str(document_id)),
                )
                if read is not None:
                    front, body = read
                    title = str(front.get("product_name") or "A product merged into this one")
                    sources.append((f"The page about {title}", body))
        description = details.get("description")
        return product_page_messages(
            product_name=product.name,
            aliases=product.aliases,
            description=description if isinstance(description, str) else None,
            sources=sources,
        )

    async def _fail(self, task: _Task) -> None:
        try:
            async with self._conn_factory() as conn:
                await mark_product_page_failed(conn, document_id=task.document_id)
        except Exception:  # noqa: BLE001 — best effort; the page simply stays "being written"
            log.warning("product_page.mark_failed_failed", document_id=str(task.document_id))


def build_product_page_handler(
    settings: Settings,
    secrets: Secrets,
    *,
    storage: StorageBackend,
    artifacts: ArtifactSink | None,
    conn_factory: ConnFactory = transaction,
) -> ProductPageWorkHandler | None:
    """The fleet worker's page writer, or ``None`` (stated once at boot) when off or keyless."""
    if not settings.product_page_writer_enabled:
        log.info(
            "product_page.handler_not_composed", reason="CLUE_PRODUCT_PAGE_WRITER_ENABLED is off"
        )
        return None
    key = secrets.openrouter_api_key
    if key is None or not key.get_secret_value().strip():
        log.warning(
            "product_page.handler_not_composed",
            reason="CLUE_OPENROUTER_API_KEY is not configured",
            detail="product page tasks stay queued until a worker with the key drains them",
        )
        return None
    return ProductPageWorkHandler(
        storage=storage,
        model=OpenRouterProductPageModel(
            api_key=key,
            base_url=GatewayConfig().base_url,
            model=settings.product_page_writer_model,
            timeout_s=settings.product_page_writer_timeout_s,
            artifacts=artifacts,
            conn_factory=conn_factory,
        ),
        conn_factory=conn_factory,
    )
