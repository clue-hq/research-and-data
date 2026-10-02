"""Apply a project's ICP and products automatically, with explicit turn provenance.

Founder ruling 2026-09-21: product/ICP approval is automatic. This free governed write
replaces the two human gate tools on the current profile. It never fabricates gate answers
and never launches research. Historical gate tools and their receipts remain replayable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, ClassVar, Literal

from pydantic import Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.arv2.icp_confirmation import (
    IcpDocumentSubject,
    confirm_icp_document,
    current_icp_document,
    current_project_icp_pin,
    pin_project_icp,
)
from clue_api.turn_action import TurnActionUnresolvable, load_turn_identity, parse_turn_action_ref
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_db import ConnFactory, transaction
from clue_spine import (
    confirm_project_product_set,
    current_project_product_set,
    get_project,
    list_products,
)
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


class ConfigureProjectTargetingInput(ToolInput):
    icp_key: str = Field(min_length=1, max_length=200)
    product_ids: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=200)
    source_turn_ref: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class ConfigureProjectTargetingOutput(ToolOutput):
    project_id: str
    icp_key: str
    document_id: str
    icp_artifact_key: str
    icp_artifact_sha256: str
    product_ids: tuple[str, ...]
    product_selection_version: int
    approval_mode: Literal["automatic"] = "automatic"


class TargetingRefused(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Targeting:
    project_id: str
    brand_id: str
    user_id: str
    subject: IcpDocumentSubject
    product_ids: tuple[str, ...]


class ConfigureProjectTargetingTool(Tool):
    name = "configure_project_targeting"
    version = "1"
    model_description = (
        "Apply this project's ICP and product set automatically, without asking for approval. "
        "Read the ICP first and supply its icp_key. Optional product_ids override its product set; "
        "otherwise use its products, the existing project set, or the brand's active products. "
        "Returns the confirmed artifact and product-selection version for use in the same turn. "
        "No gate opens and no research launches. Continue the user's task after this succeeds. "
        + tool_manual_link("configure_project_targeting")
    )
    input_model: ClassVar[type[ToolInput]] = ConfigureProjectTargetingInput
    output_model: ClassVar[type[ToolOutput]] = ConfigureProjectTargetingOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project plus current ICP document and selected product set",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("icp_key", "product_ids"))
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
        assert isinstance(inputs, ConfigureProjectTargetingInput)
        try:
            async with self._conn_factory() as conn:
                await self._resolve(conn, inputs, ctx)
        except TargetingRefused as exc:
            return (PreconditionFailure(reason_code=exc.code, message=str(exc)),)
        return ()

    async def _resolve(
        self, conn: AsyncConnection, inputs: ConfigureProjectTargetingInput, ctx: ToolContext
    ) -> _Targeting:
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise TargetingRefused("targeting_turn_unavailable", str(exc)) from exc
        turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None or not turn.submitted_by_user_id:
            raise TargetingRefused(
                "targeting_turn_unavailable", "the initiating turn is unavailable"
            )
        # Serialize product versions and ICP pins; resolve again under this lock at invoke.
        await conn.execute(
            text(
                "SELECT project_id FROM project WHERE project_id = :project "
                "AND workspace_id = :workspace FOR UPDATE"
            ),
            {"project": turn.project_id, "workspace": ctx.workspace_id},
        )
        project = await get_project(conn, turn.project_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            raise TargetingRefused("targeting_project_unavailable", "the project is unavailable")
        subject = (
            None
            if self._storage is None
            else await current_icp_document(
                conn,
                self._storage,
                workspace_id=ctx.workspace_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
                icp_key=inputs.icp_key,
            )
        )
        if subject is None:
            raise TargetingRefused("icp_document_not_found", "no readable current ICP has this key")
        products = {
            p.product_id
            for p in await list_products(conn, project.brand_id)
            if p.workspace_id == ctx.workspace_id and p.status == "active"
        }
        current = await current_project_product_set(
            conn,
            workspace_id=ctx.workspace_id,
            project_id=project.project_id,
        )
        selected = inputs.product_ids
        if selected is None:
            pin = await current_project_icp_pin(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=project.project_id,
            )
            selected = (
                (current.product_ids if current and pin and pin.icp_key == inputs.icp_key else ())
                or subject.product_ids
                or (current.product_ids if current else ())
                or tuple(sorted(products))
            )
        selected = tuple(dict.fromkeys(selected))
        if not selected or not set(selected).issubset(products):
            raise TargetingRefused(
                "targeting_products_unavailable",
                "choose active product ids from this brand's catalog",
            )
        return _Targeting(
            project.project_id, project.brand_id, turn.submitted_by_user_id, subject, selected
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ConfigureProjectTargetingInput)
        async with self._conn_factory() as conn:
            target = await self._resolve(conn, inputs, ctx)
            assert self._storage is not None
            selection = await current_project_product_set(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=target.project_id,
            )
            if selection is None or set(selection.product_ids) != set(target.product_ids):
                selection = await confirm_project_product_set(
                    conn,
                    workspace_id=ctx.workspace_id,
                    project_id=target.project_id,
                    product_ids=target.product_ids,
                    gate_id=None,
                    confirmed_by_user_id=target.user_id,
                    confirmation_turn_id=parse_turn_action_ref(inputs.source_turn_ref),
                )
                if selection is None:
                    raise TargetingRefused(
                        "targeting_products_unavailable", "the product set changed"
                    )
            pin = await current_project_icp_pin(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=target.project_id,
            )
            if (
                pin is None
                or pin.document_id != target.subject.document_id
                or pin.product_selection_version != selection.selection_version
            ):
                confirmed = await confirm_icp_document(
                    conn,
                    self._storage,
                    workspace_id=ctx.workspace_id,
                    brand_id=target.brand_id,
                    project_id=target.project_id,
                    proposed=target.subject,
                    expected_sha256=target.subject.artifact_sha256,
                    confirmed_by_user_id=target.user_id,
                    product_selection_version=selection.selection_version,
                    automatic_turn_ref=inputs.source_turn_ref,
                )
                pin = await pin_project_icp(
                    conn,
                    workspace_id=ctx.workspace_id,
                    project_id=target.project_id,
                    brand_id=target.brand_id,
                    document=confirmed,
                    product_selection_version=selection.selection_version,
                    pinned_by_user_id=target.user_id,
                )
            output = ConfigureProjectTargetingOutput(
                project_id=target.project_id,
                icp_key=pin.icp_key,
                document_id=str(pin.document_id),
                icp_artifact_key=pin.artifact_key,
                icp_artifact_sha256=pin.artifact_sha256,
                product_ids=selection.product_ids,
                product_selection_version=selection.selection_version,
            )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())
