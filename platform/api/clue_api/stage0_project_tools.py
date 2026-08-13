"""Stage-0 Slice-1 tools: trusted readiness and durable draft ICP synthesis."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.stage0_project_contracts import (
    DraftIcpSpecRef,
    EvaluateStage0ReadinessV2Input,
    Stage0ReadinessV2Output,
    SynthesizeIcpsV2Input,
    SynthesizeIcpsV2Output,
)
from clue_api.stage0_project_scope import Stage0ProjectScope, resolve_stage0_project_scope
from clue_api.statement_evidence import ArtifactStatementEvidenceReader
from clue_config import DEFAULT_STAGE0_POLICY, Stage0Policy
from clue_core import (
    LLMGateway,
    ReadinessDecisionId,
    ReadinessGate,
    ReadinessVerdict,
    VolunteeredStatementId,
    decode_jsonb,
    serialize_value_json,
)
from clue_db import ConnFactory, transaction
from clue_projections.stage0 import ExcludedEvidence
from clue_research.stage0 import (
    CLIENT_ICP_SYNTHESIS_FIELDS,
    ClientKnowledgeBaseRef,
    ICPSynthesisStatus,
    ProjectStatement,
    ReadinessDecisionRow,
    client_kb_readiness_metrics,
    ensure_readiness_spec,
    evaluate_readiness,
    get_readiness_decision,
    get_workspace_client_kb_readiness_policy,
    persist_icp_proposal_draft,
    read_client_kb_claims,
    read_statements,
    synthesize_icps,
)
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolResult,
)

__all__ = [
    "EvaluateStage0ReadinessV2Tool",
    "SynthesizeIcpsV2Tool",
    "stage0_project_tools",
]

_METRICS_AUTHORITY = "backend_product_scoped_client_kb"


def _failure(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


async def _scope(conn: AsyncConnection, ctx: ToolContext) -> Stage0ProjectScope | None:
    """Resolve every tool path through the same execution-derived project scope."""

    return await resolve_stage0_project_scope(
        conn,
        workspace_id=ctx.workspace_id,
        execution_id=ctx.execution_id,
    )


async def _current_backend_readiness(
    conn: AsyncConnection,
    *,
    scope: Stage0ProjectScope,
    policy: Stage0Policy,
) -> ReadinessDecisionRow | None:
    """Return the newest current-lineage v2 readiness decision, never a v1 metric submission."""

    if (
        scope.product_id is None
        or scope.client_entity_id is None
        or scope.client_kb_version is None
    ):
        return None
    readiness_policy_version = await ensure_readiness_spec(
        conn,
        workspace_id=scope.workspace_id,
        spec=policy.readiness,
    )
    workspace_policy = await get_workspace_client_kb_readiness_policy(
        conn,
        workspace_id=scope.workspace_id,
    )
    workspace_policy_version = workspace_policy.version if workspace_policy is not None else 0
    decision_id = (
        await conn.execute(
            text(
                """
                SELECT id
                FROM readiness_decision
                WHERE workspace_id = :workspace_id
                  AND project_id = :project_id
                  AND brand_id = :brand_id
                  AND product_id = :product_id
                  AND client_entity_id = :client_entity_id
                  AND client_kb_version = :client_kb_version
                  AND gate = 'icp_synthesis'
                  AND spec_version = :readiness_policy_version
                  AND metrics ->> 'metrics_authority' = :metrics_authority
                  AND COALESCE((metrics ->> 'workspace_readiness_policy_version')::int, 0)
                      = :workspace_policy_version
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ),
            {
                "workspace_id": scope.workspace_id,
                "project_id": scope.project_id,
                "brand_id": scope.brand_id,
                "product_id": scope.product_id,
                "client_entity_id": scope.client_entity_id,
                "client_kb_version": scope.client_kb_version,
                "readiness_policy_version": readiness_policy_version,
                "metrics_authority": _METRICS_AUTHORITY,
                "workspace_policy_version": workspace_policy_version,
            },
        )
    ).scalar_one_or_none()
    if decision_id is None:
        return None
    return await get_readiness_decision(
        conn,
        ReadinessDecisionId(UUID(str(decision_id))),
        workspace_id=scope.workspace_id,
    )


class _Stage0ProjectTool(Tool):
    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        policy: Stage0Policy = DEFAULT_STAGE0_POLICY,
        gateway: LLMGateway | None = None,
        synthesis_model: str | None = None,
        statement_evidence: ArtifactStatementEvidenceReader | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._policy = policy
        self._gateway = gateway
        self._synthesis_model = synthesis_model
        self._statement_evidence = statement_evidence


class EvaluateStage0ReadinessV2Tool(_Stage0ProjectTool):
    """Compute readiness from the current product-scoped Client KB, never model measurements."""

    name = "evaluate_stage0_readiness"
    version = "2"
    model_description = (
        "Request a backend evaluation of the ICP-synthesis readiness gate. Supply only the gate; "
        "the platform resolves scope, claims, metrics, policy, and the durable decision."
    )
    input_model = EvaluateStage0ReadinessV2Input
    output_model = Stage0ReadinessV2Output
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="ReadinessDecisionId(operation_id)",
        operation_id_required=True,
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(safe_display_fields=("gate",))
    # ``brand_id`` is persisted on the readiness decision even though the model never supplies
    # it. Keep every trusted scope value the tool consumes in the descriptor so the generic
    # Stage-0 pin provider can freeze the complete authority boundary without knowing tool names.
    pin_requirements = ("readiness_policy", "brand", "project")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, EvaluateStage0ReadinessV2Input)
        async with self._conn_factory() as conn:
            scope = await _scope(conn, ctx)
        if scope is None:
            return _failure(
                "stage0_scope_not_found",
                "the governed execution is not bound to a project in this workspace",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, EvaluateStage0ReadinessV2Input)
        async with self._conn_factory() as conn:
            scope = await _scope(conn, ctx)
            if scope is None:  # defence in depth if state changed after preconditions
                raise ValueError("the governed execution has no trusted Stage-0 project scope")
            claims = (
                {}
                if (
                    scope.product_id is None
                    or scope.client_entity_id is None
                    or scope.client_kb_version is None
                )
                else await read_client_kb_claims(
                    conn,
                    scope.client_entity_id,
                    workspace_id=scope.workspace_id,
                    version=scope.client_kb_version,
                    product_id=scope.product_id,
                )
            )
            workspace_policy = await get_workspace_client_kb_readiness_policy(
                conn,
                workspace_id=scope.workspace_id,
            )
            workspace_required = (
                workspace_policy.required_field_keys if workspace_policy is not None else ()
            )
            effective_expected_fields = tuple(
                sorted(set(CLIENT_ICP_SYNTHESIS_FIELDS).union(workspace_required))
            )
            metrics = client_kb_readiness_metrics(
                claims,
                baseline_field_keys=CLIENT_ICP_SYNTHESIS_FIELDS,
                required_field_keys=workspace_required,
            )
            metrics.update(
                {
                    "open_policy_blocks": 0,
                    "metrics_authority": _METRICS_AUTHORITY,
                    "baseline_field_keys": cast(
                        list[JsonValue], sorted(CLIENT_ICP_SYNTHESIS_FIELDS)
                    ),
                    "effective_expected_field_keys": cast(
                        list[JsonValue], list(effective_expected_fields)
                    ),
                }
            )
            scope_reasons: list[str] = []
            if scope.product_id is None:
                scope_reasons.append("product_not_confirmed")
            if scope.client_entity_id is None:
                scope_reasons.append("client_not_bound")
            elif scope.client_kb_version is None:
                scope_reasons.append("client_kb_missing")
            if not effective_expected_fields:
                scope_reasons.append("required_field_policy_empty")
            snapshot = await evaluate_readiness(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                product_id=scope.product_id,
                project_id=scope.project_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                gate=ReadinessGate.ICP_SYNTHESIS,
                spec=self._policy.readiness,
                metrics=metrics,
                created_by_actor="system",
                additional_reason_codes=scope_reasons,
                readiness_decision_id=ReadinessDecisionId(ctx.operation_id),
            )
            decision = await get_readiness_decision(
                conn,
                snapshot.readiness_decision_id,
                workspace_id=scope.workspace_id,
            )
            assert decision is not None
        available = decision.metrics.get("available_field_keys", [])
        available_fields = (
            tuple(sorted(item for item in available if isinstance(item, str)))
            if isinstance(available, list)
            else ()
        )
        coverage = decision.metrics.get("coverage_ratio", 0.0)
        verified = decision.metrics.get("verified_claims", 0)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=Stage0ReadinessV2Output(
                readiness_decision_id=str(decision.id),
                gate="icp_synthesis",
                verdict=("ready" if decision.verdict is ReadinessVerdict.READY else "not_ready"),
                coverage_ratio=(float(coverage) if isinstance(coverage, (int, float)) else 0.0),
                verified_claims=(int(verified) if isinstance(verified, (int, float)) else 0),
                available_field_keys=available_fields,
                reason_codes=decision.reason_codes,
                readiness_policy_version=decision.spec_version,
            ).model_dump(),
        )


class SynthesizeIcpsV2Tool(_Stage0ProjectTool):
    """Synthesize current-lineage ICPs and persist each proposal as a draft spec."""

    name = "synthesize_icps"
    version = "2"
    model_description = (
        "Synthesize ICP proposals for the current trusted Stage-0 scope after backend readiness "
        "passes. Takes no arguments and returns only durable draft icp_spec references."
    )
    input_model = SynthesizeIcpsV2Input
    output_model = SynthesizeIcpsV2Output
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="stage0_icp_synthesis.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy()
    pin_requirements = (
        "brand",
        "project",
        "product",
        "client_kb",
        "field_registry",
        "model_prompt",
    )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SynthesizeIcpsV2Input)
        async with self._conn_factory() as conn:
            scope = await _scope(conn, ctx)
            if scope is None:
                return _failure(
                    "stage0_scope_not_found",
                    "the governed execution is not bound to a project in this workspace",
                )
            if scope.product_id is None:
                return _failure("product_not_confirmed", "the project has no confirmed product")
            if scope.client_entity_id is None:
                return _failure("client_not_bound", "the project has no bound client entity")
            if scope.client_kb_version is None:
                return _failure(
                    "client_kb_missing", "the confirmed product has no current Client KB"
                )
            decision = await _current_backend_readiness(
                conn,
                scope=scope,
                policy=self._policy,
            )
        if decision is None or decision.verdict is not ReadinessVerdict.READY:
            return _failure(
                "icp_synthesis_not_ready",
                "run evaluate_stage0_readiness@2 for the current Client-KB lineage first",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, SynthesizeIcpsV2Input)
        async with self._conn_factory() as conn:
            # Serialize this logical operation before reading the replay ledger. A concurrent retry
            # waits, then reads the committed refs instead of spending or appending another spec.
            await conn.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(CAST(:operation_id AS text), 0))"
                ),
                {"operation_id": str(ctx.operation_id)},
            )
            existing = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT workspace_id, readiness_decision_id, icp_spec_refs
                            FROM stage0_icp_synthesis
                            WHERE operation_id = :operation_id
                            """
                        ),
                        {"operation_id": ctx.operation_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if str(existing["workspace_id"]) != ctx.workspace_id:
                    raise ValueError("synthesis operation id belongs to another workspace")
                output = SynthesizeIcpsV2Output(
                    readiness_decision_id=str(existing["readiness_decision_id"]),
                    icp_specs=tuple(
                        DraftIcpSpecRef.model_validate(item)
                        for item in decode_jsonb(existing["icp_spec_refs"])
                    ),
                )
                return ToolResult(
                    tool=self.name,
                    version=self.version,
                    references=output.model_dump(),
                    replayed=True,
                )

            scope = await _scope(conn, ctx)
            if (
                scope is None
                or scope.product_id is None
                or scope.client_entity_id is None
                or scope.client_kb_version is None
            ):
                raise ValueError("trusted Stage-0 synthesis scope became incomplete")
            decision = await _current_backend_readiness(
                conn,
                scope=scope,
                policy=self._policy,
            )
            if decision is None or decision.verdict is not ReadinessVerdict.READY:
                raise ValueError("current Stage-0 lineage is not ready for ICP synthesis")

            rows = await read_statements(
                conn,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
            )
            project_statements: list[ProjectStatement] = []
            excluded_statement_ids: list[VolunteeredStatementId] = []
            if rows:
                if self._statement_evidence is None:
                    raise ValueError("statement evidence storage is not configured")
                resolutions = await self._statement_evidence.resolve_quotes(
                    workspace_id=scope.workspace_id,
                    statements=rows,
                )
                route_keys = {row.id: row.route_key for row in rows}
                for resolution in resolutions:
                    if isinstance(resolution, ExcludedEvidence):
                        excluded_statement_ids.append(resolution.statement_id)
                    else:
                        project_statements.append(
                            ProjectStatement(
                                statement_id=resolution.statement_id,
                                route_key=route_keys[resolution.statement_id],
                                quote=resolution.quote,
                            )
                        )

            synthesized = await synthesize_icps(
                conn,
                ClientKnowledgeBaseRef(
                    client_entity_id=scope.client_entity_id,
                    client_kb_version=scope.client_kb_version,
                    product_id=scope.product_id,
                ),
                workspace_id=scope.workspace_id,
                project_statements=tuple(project_statements),
                gateway=self._gateway,
                synthesis_model=self._synthesis_model,
            )
            if synthesized.status is not ICPSynthesisStatus.GROUNDED:
                raise ValueError("ICP synthesis returned no grounded proposal")
            keys = [proposal.icp_key for proposal in synthesized.proposals]
            if len(set(keys)) != len(keys):
                raise ValueError("ICP synthesis returned duplicate proposal keys")
            refs: list[DraftIcpSpecRef] = []
            for proposal in synthesized.proposals:
                spec = await persist_icp_proposal_draft(
                    conn,
                    proposal,
                    workspace_id=scope.workspace_id,
                    client_entity_id=scope.client_entity_id,
                    client_kb_version=scope.client_kb_version,
                    product_id=scope.product_id,
                    created_by="agent",
                )
                refs.append(
                    DraftIcpSpecRef(
                        workspace_id=scope.workspace_id,
                        icp_key=spec.icp_key,
                        icp_version=spec.version,
                        status="draft",
                    )
                )
            output = SynthesizeIcpsV2Output(
                readiness_decision_id=str(decision.id),
                icp_specs=tuple(refs),
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO stage0_icp_synthesis (
                        operation_id, workspace_id, brand_id, project_id, readiness_decision_id,
                        client_entity_id, client_kb_version, product_id, icp_spec_refs,
                        excluded_statement_ids
                    ) VALUES (
                        :operation_id, :workspace_id, :brand_id, :project_id,
                        :readiness_decision_id,
                        :client_entity_id, :client_kb_version, :product_id,
                        CAST(:icp_spec_refs AS jsonb), CAST(:excluded_statement_ids AS jsonb)
                    )
                    """
                ),
                {
                    "operation_id": ctx.operation_id,
                    "workspace_id": scope.workspace_id,
                    "brand_id": scope.brand_id,
                    "project_id": scope.project_id,
                    "readiness_decision_id": decision.id,
                    "client_entity_id": scope.client_entity_id,
                    "client_kb_version": scope.client_kb_version,
                    "product_id": scope.product_id,
                    "icp_spec_refs": serialize_value_json(
                        [ref.model_dump(mode="json") for ref in refs]
                    ),
                    "excluded_statement_ids": serialize_value_json(
                        [str(item) for item in excluded_statement_ids]
                    ),
                },
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=output.model_dump(),
        )


def stage0_project_tools(
    *,
    conn_factory: ConnFactory,
    policy: Stage0Policy,
    gateway: LLMGateway | None,
    synthesis_model: str | None,
    statement_evidence: ArtifactStatementEvidenceReader | None,
) -> tuple[Tool, ...]:
    return (
        EvaluateStage0ReadinessV2Tool(
            conn_factory=conn_factory,
            policy=policy,
            gateway=gateway,
            synthesis_model=synthesis_model,
            statement_evidence=statement_evidence,
        ),
        SynthesizeIcpsV2Tool(
            conn_factory=conn_factory,
            policy=policy,
            gateway=gateway,
            synthesis_model=synthesis_model,
            statement_evidence=statement_evidence,
        ),
    )
