"""``manage_products@1`` — the Head of ABM changes the brand's product list (spec 2026-10-15).

Founder ruling D3 (2026-10-15): when the person asks in chat for a product change — add, rename,
merge or remove — the agent applies it directly. When it only suspects the list is wrong it asks
first (prompt guidance in the description, not code). The work is the same service the Brand-context
routes use (:mod:`clue_api.product_management`); in chat the agent writes the product page itself,
so an add or a merge requires ``page_markdown`` and nothing is left for the background writer.

Authority comes from the trusted ``source_turn_ref``: the project, its brand and the person the
change is credited to are read off the presenting turn, never from model-authored fields. A replay
of the same call in the same turn returns the first change (idempotency key over the turn and the
inputs).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.product_management import (
    ProductActor,
    ProductChangeRefused,
    ProductChangeResult,
    add_product,
    merge_products_action,
    remove_product_action,
    rename_product_action,
)
from clue_api.turn_action import TurnActionUnresolvable, load_turn_identity, parse_turn_action_ref
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_db import ConnFactory, transaction
from clue_spine import get_product, get_project
from clue_storage import StorageBackend
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = ["ManageProductsInput", "ManageProductsOutput", "ManageProductsTool"]


class ManageProductsInput(ToolInput):
    #: What to do to the brand's product list.
    action: Literal["add", "rename", "merge", "remove"]
    #: rename / remove: the product to change.
    product_id: str | None = Field(default=None, max_length=200)
    #: merge: the products folded in.
    product_ids: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=200)
    #: merge: fold into this existing product ...
    into_product_id: str | None = Field(default=None, max_length=200)
    #: ... or (merge) into a product with this name; add / rename: the product's name.
    name: str | None = Field(default=None, max_length=240)
    #: add / merge: the product's page, written by you.
    page_markdown: str | None = Field(default=None, max_length=200_000)
    source_turn_ref: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class ManageProductsOutput(ToolOutput):
    #: The change, as recorded in the brand's product change log.
    change_id: str
    action: str
    #: One sentence saying what changed, ready to tell the person.
    summary: str
    #: The product the change is about (for a merge, the product the others were folded into).
    product_id: str
    product_name: str
    #: Its other names, including the names of products merged into it.
    aliases: tuple[str, ...]
    #: The product page this call wrote, for add and merge.
    page_document_id: str | None
    #: The regenerated product catalog.
    catalog_document_id: str
    #: Projects whose product set moved to the new list.
    projects_updated: int
    #: Projects left with no product, which keep their old set until the person chooses.
    projects_needing_choice: int


class ProductsRefused(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Scope:
    workspace_id: str
    brand_id: str
    actor: ProductActor


def _input_problem(inputs: ManageProductsInput) -> tuple[str, str] | None:
    """What the action is missing, as ``(code, message)``; ``None`` when it is complete."""
    action = inputs.action
    if action in ("rename", "remove") and not inputs.product_id:
        return ("products_input_invalid", f"{action} needs product_id")
    if action in ("add", "rename") and not (inputs.name or "").strip():
        return ("products_input_invalid", f"{action} needs name")
    if action == "merge":
        if not inputs.product_ids:
            return ("products_input_invalid", "merge needs product_ids")
        if (inputs.into_product_id is None) == (inputs.name is None):
            return ("products_input_invalid", "merge needs into_product_id or name, not both")
    if action in ("add", "merge") and not (inputs.page_markdown or "").strip():
        return ("products_page_required", f"{action} needs page_markdown: the product's page")
    return None


def _idempotency_key(turn_id: UUID, inputs: ManageProductsInput) -> str:
    body = inputs.model_dump(mode="json", exclude={"source_turn_ref"})
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return f"turn:{turn_id}:{digest[:32]}"


class ManageProductsTool(Tool):
    name = "manage_products"
    version = "1"
    model_description = (
        "Change this brand's product list when the person asks you to: add a product, rename one, "
        "merge several into one (for example features that onboarding listed as separate "
        "products), or remove one. The change applies at once to the product list, the product "
        "pages, the catalog and every project that uses those products. For add and merge, write "
        "page_markdown: the product's page, from what you know and the pages being merged. If you "
        "only suspect the list is wrong, ask the person first instead of calling this. "
        + tool_manual_link("manage_products")
    )
    input_model: ClassVar[type[ToolInput]] = ManageProductsInput
    output_model: ClassVar[type[ToolOutput]] = ManageProductsOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="product_change keyed by the presenting turn and the call's inputs",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("action", "product_id", "product_ids", "into_product_id", "name")
    )
    pin_requirements = ("project",)

    def __init__(
        self, *, conn_factory: ConnFactory = transaction, storage: StorageBackend | None = None
    ) -> None:
        self._conn_factory = conn_factory
        self._storage = storage

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        return ToolEstimate.free()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ManageProductsInput)
        problem = _input_problem(inputs)
        if problem is not None:
            return (PreconditionFailure(reason_code=problem[0], message=problem[1]),)
        if self._storage is None:
            return (
                PreconditionFailure(
                    reason_code="products_storage_unavailable",
                    message="document storage is not composed on this deployment",
                ),
            )
        try:
            async with self._conn_factory() as conn:
                scope = await self._scope(conn, inputs, ctx)
                await self._check_products(conn, inputs, scope)
        except ProductsRefused as exc:
            return (PreconditionFailure(reason_code=exc.code, message=str(exc)),)
        return ()

    async def _scope(
        self, conn: AsyncConnection, inputs: ManageProductsInput, ctx: ToolContext
    ) -> _Scope:
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise ProductsRefused("products_turn_unavailable", str(exc)) from exc
        turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None or not turn.submitted_by_user_id:
            raise ProductsRefused("products_turn_unavailable", "the initiating turn is unavailable")
        project = await get_project(conn, turn.project_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            raise ProductsRefused("products_turn_unavailable", "the turn's project is unavailable")
        return _Scope(
            workspace_id=ctx.workspace_id,
            brand_id=project.brand_id,
            actor=ProductActor(turn.submitted_by_user_id, turn_id),
        )

    async def _check_products(
        self, conn: AsyncConnection, inputs: ManageProductsInput, scope: _Scope
    ) -> None:
        named = [
            *([inputs.product_id] if inputs.product_id else []),
            *(inputs.product_ids or ()),
            *([inputs.into_product_id] if inputs.into_product_id else []),
        ]
        for product_id in named:
            product = await get_product(conn, product_id)
            if product is None or product.brand_id != scope.brand_id:
                raise ProductsRefused(
                    "product_not_found", f"{product_id} is not a product of this brand"
                )
            if product.status != "active":
                raise ProductsRefused(
                    "product_not_active",
                    f"{product.name} is no longer on the product list; read the catalog again",
                )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ManageProductsInput)
        assert self._storage is not None
        storage = self._storage
        async with self._conn_factory() as conn:
            scope = await self._scope(conn, inputs, ctx)
            assert scope.actor.turn_id is not None
            key = _idempotency_key(scope.actor.turn_id, inputs)
            try:
                result: ProductChangeResult
                if inputs.action == "add":
                    result = await add_product(
                        conn,
                        storage,
                        workspace_id=scope.workspace_id,
                        brand_id=scope.brand_id,
                        actor=scope.actor,
                        idempotency_key=key,
                        name=inputs.name or "",
                        page_markdown=inputs.page_markdown,
                    )
                elif inputs.action == "rename":
                    result = await rename_product_action(
                        conn,
                        storage,
                        workspace_id=scope.workspace_id,
                        brand_id=scope.brand_id,
                        actor=scope.actor,
                        idempotency_key=key,
                        product_id=inputs.product_id or "",
                        name=inputs.name or "",
                    )
                elif inputs.action == "merge":
                    result = await merge_products_action(
                        conn,
                        storage,
                        workspace_id=scope.workspace_id,
                        brand_id=scope.brand_id,
                        actor=scope.actor,
                        idempotency_key=key,
                        product_ids=list(inputs.product_ids or ()),
                        into_product_id=inputs.into_product_id,
                        new_name=inputs.name if inputs.into_product_id is None else None,
                        page_markdown=inputs.page_markdown,
                    )
                else:
                    result = await remove_product_action(
                        conn,
                        storage,
                        workspace_id=scope.workspace_id,
                        brand_id=scope.brand_id,
                        actor=scope.actor,
                        idempotency_key=key,
                        product_id=inputs.product_id or "",
                    )
            except ProductChangeRefused as exc:
                raise ProductsRefused(exc.code, str(exc)) from exc
        output = ManageProductsOutput(
            change_id=str(result.change_id),
            action=inputs.action,
            summary=result.text,
            product_id=result.product.product_id,
            product_name=result.product.name,
            aliases=result.product.aliases,
            page_document_id=str(result.page_document_id) if result.page_document_id else None,
            catalog_document_id=str(result.catalog_document_id),
            projects_updated=sum(p.outcome == "updated" for p in result.projects),
            projects_needing_choice=sum(p.outcome == "needs_choice" for p in result.projects),
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())
