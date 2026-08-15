"""Stage-0 Slice-1 tools: trusted readiness and durable draft ICP synthesis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.project_execution_router import ProjectExecutionRouter
from clue_api.stage0_project_contracts import (
    PRODUCT_CONTEXT_RECEIPT_SCHEMA_V1,
    DraftIcpSpecRef,
    EvaluateStage0ReadinessV2Input,
    ProductContextReceiptContract,
    ProductContextReceiptInputRef,
    Stage0ReadinessV2Output,
    StartConfirmedProjectRunV2Input,
    StartConfirmedProjectRunV2Output,
    SynthesizeIcpsV2Input,
    SynthesizeIcpsV2Output,
    canonical_subject_sha256,
    product_context_receipt_manifest_sha256,
)
from clue_api.stage0_project_scope import Stage0ProjectScope, resolve_stage0_project_scope
from clue_api.stage0_tools import start_confirmed_project_run
from clue_api.statement_evidence import ArtifactStatementEvidenceReader
from clue_config import DEFAULT_STAGE0_POLICY, Stage0Policy
from clue_core import (
    ICPStatus,
    LLMGateway,
    ProductContextVersionId,
    ProjectRunId,
    ReadinessDecisionId,
    ReadinessGate,
    ReadinessVerdict,
    VolunteeredStatementId,
    decode_jsonb,
    operation_id_from_key,
    serialize_value_json,
)
from clue_db import ConnFactory, transaction
from clue_projections import (
    CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE,
    PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE,
    PRODUCT_PROFILE_CARD_MEDIA_TYPE,
    STAGE0_PROJECT_STATE_CARD_MEDIA_TYPE,
)
from clue_projections.stage0 import ExcludedEvidence
from clue_research.icp import get_icp_version
from clue_research.stage0 import (
    CLIENT_ICP_SYNTHESIS_FIELDS,
    ClientKnowledgeBaseRef,
    ICPSynthesisStatus,
    ProjectStatement,
    ReadinessDecisionRow,
    client_kb_readiness_metrics,
    compile_product_context,
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
    "StartConfirmedProjectRunV2Tool",
    "SynthesizeIcpsV2Tool",
    "stage0_project_tools",
]

_METRICS_AUTHORITY = "backend_product_scoped_client_kb"
_CONFIRMED_RUN_METRICS_AUTHORITY = "backend_confirmed_discovery_run_v2"
_PRODUCT_CONTEXT_COMPILER_VERSION = "product-context@2-existing-stage0-receipt"


@dataclass(frozen=True, slots=True)
class _ContextArtifact:
    artifact_key: str
    sha256: str


@dataclass(frozen=True, slots=True)
class _ApprovedIcp:
    icp_key: str
    version: int
    subject_ref: str
    expected_subject_sha256: str


def _failure(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


async def _scope(conn: AsyncConnection, ctx: ToolContext) -> Stage0ProjectScope | None:
    """Resolve every tool path through the same execution-derived project scope."""

    return await resolve_stage0_project_scope(
        conn,
        workspace_id=ctx.workspace_id,
        execution_id=ctx.execution_id,
    )


async def _turn_context_artifacts(
    conn: AsyncConnection,
    *,
    scope: Stage0ProjectScope,
) -> dict[str, _ContextArtifact]:
    """Read the exact context cards already materialized for this immutable turn."""

    if scope.turn_id is None:
        return {}
    rows = (
        (
            await conn.execute(
                text(
                    """
                    SELECT a.media_type, r.artifact_key, r.artifact_sha256
                    FROM agent_artifact_ref r
                    JOIN artifact a
                      ON a.storage_key = r.artifact_key
                     AND a.workspace_id = r.workspace_id
                    WHERE r.turn_id = :turn_id
                      AND r.workspace_id = :workspace_id
                      AND r.owner_kind = 'context'
                      AND r.owner_id = :turn_id
                      AND r.ref_role = 'context_materialization'
                      AND a.erased_at IS NULL
                      AND a.purged_at IS NULL
                    ORDER BY r.ordinal
                    FOR SHARE OF a
                    """
                ),
                {"turn_id": scope.turn_id, "workspace_id": scope.workspace_id},
            )
        )
        .mappings()
        .all()
    )
    artifacts: dict[str, _ContextArtifact] = {}
    for row in rows:
        media_type = str(row["media_type"])
        if media_type in artifacts:
            raise ValueError(f"turn carries duplicate {media_type} context materializations")
        artifacts[media_type] = _ContextArtifact(
            artifact_key=str(row["artifact_key"]),
            sha256=str(row["artifact_sha256"]),
        )
    return artifacts


async def _approved_icp(
    conn: AsyncConnection,
    *,
    scope: Stage0ProjectScope,
) -> _ApprovedIcp | None:
    """Resolve the newest human-approved active ICP in this exact pinned lineage."""

    if (
        scope.client_entity_id is None
        or scope.client_kb_version is None
        or scope.product_id is None
    ):
        return None
    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT i.icp_key, i.version, g.subject_ref, g.expected_subject_sha256
                    FROM agent_gate_answer a
                    JOIN agent_gate g
                      ON g.gate_id = a.gate_id
                     AND g.workspace_id = a.workspace_id
                    JOIN icp_spec i
                      ON i.workspace_id = g.workspace_id
                     AND i.icp_key = g.subject_snapshot ->> 'icp_key'
                     AND i.version = (g.subject_snapshot ->> 'version')::integer
                    WHERE a.workspace_id = :workspace_id
                      AND a.decision = 'approved'
                      AND a.expected_subject_sha256 = g.expected_subject_sha256
                      AND g.kind = 'icp_confirmation'
                      AND g.project_id = :project_id
                      AND g.snapshot_erased_at IS NULL
                      AND i.status = 'active'
                      AND i.client_entity_id = :client_entity_id
                      AND i.client_kb_version = :client_kb_version
                      AND i.product_id = :product_id
                    ORDER BY CASE WHEN a.turn_id = :turn_id THEN 0 ELSE 1 END,
                             a.answered_at DESC, g.gate_id DESC
                    LIMIT 1
                    FOR SHARE OF a, g, i
                    """
                ),
                {
                    "workspace_id": scope.workspace_id,
                    "project_id": scope.project_id,
                    "client_entity_id": scope.client_entity_id,
                    "client_kb_version": scope.client_kb_version,
                    "product_id": scope.product_id,
                    "turn_id": scope.turn_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    spec = await get_icp_version(
        conn,
        scope.workspace_id,
        str(row["icp_key"]),
        int(row["version"]),
    )
    if spec is None or spec.status is not ICPStatus.ACTIVE:
        return None
    return _ApprovedIcp(
        icp_key=spec.icp_key,
        version=spec.version,
        subject_ref=str(row["subject_ref"]),
        expected_subject_sha256=str(row["expected_subject_sha256"]),
    )


def _receipt_from_existing_inputs(
    *,
    scope: Stage0ProjectScope,
    approved_icp: _ApprovedIcp,
    artifacts: dict[str, _ContextArtifact],
) -> ProductContextReceiptContract:
    """Describe the existing Stage-0 inputs; this function creates no knowledge or artifact."""

    assert scope.client_entity_id is not None
    assert scope.client_kb_version is not None
    assert scope.product_id is not None
    assert scope.product_kb_version is not None
    required_media = {
        CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE,
        STAGE0_PROJECT_STATE_CARD_MEDIA_TYPE,
        PRODUCT_PROFILE_CARD_MEDIA_TYPE,
        PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE,
    }
    missing_media = sorted(required_media - set(artifacts))
    if missing_media:
        raise ValueError(f"turn is missing exact Stage-0 context cards: {missing_media}")
    client_card = artifacts[CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE]
    product_profile = artifacts[PRODUCT_PROFILE_CARD_MEDIA_TYPE]
    product_card = artifacts[PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE]
    selected_product_snapshot: dict[str, JsonValue] = {
        "project_id": scope.project_id,
        "product_id": scope.product_id,
    }
    inputs = (
        ProductContextReceiptInputRef(
            kind="client_kb",
            subject_ref=f"client_kb:{scope.client_entity_id}|-",
            revision=str(scope.client_kb_version),
            subject_sha256=client_card.sha256,
        ),
        ProductContextReceiptInputRef(
            kind="selected_product",
            subject_ref=f"project-product:{scope.project_id}",
            revision=scope.product_id,
            subject_sha256=canonical_subject_sha256(selected_product_snapshot),
        ),
        ProductContextReceiptInputRef(
            kind="product_profile",
            subject_ref=f"product-profile:{scope.product_id}",
            revision=product_profile.artifact_key,
            subject_sha256=product_profile.sha256,
        ),
        ProductContextReceiptInputRef(
            kind="product_kb",
            subject_ref=f"product_kb:{scope.client_entity_id}|{scope.product_id}",
            revision=str(scope.product_kb_version),
            subject_sha256=product_card.sha256,
        ),
        ProductContextReceiptInputRef(
            kind="approved_icp",
            subject_ref=approved_icp.subject_ref,
            revision=f"{approved_icp.icp_key}@{approved_icp.version}",
            subject_sha256=approved_icp.expected_subject_sha256,
        ),
    )
    manifest_sha256 = product_context_receipt_manifest_sha256(
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
        client_entity_id=str(scope.client_entity_id),
        product_id=scope.product_id,
        inputs=inputs,
    )
    return ProductContextReceiptContract(
        receipt_schema_version=PRODUCT_CONTEXT_RECEIPT_SCHEMA_V1,
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
        client_entity_id=str(scope.client_entity_id),
        product_id=scope.product_id,
        inputs=inputs,
        manifest_sha256=manifest_sha256,
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
        project_execution_router: ProjectExecutionRouter | None = None,
        budget_controls_enabled: bool = True,
    ) -> None:
        self._conn_factory = conn_factory
        self._policy = policy
        self._gateway = gateway
        self._synthesis_model = synthesis_model
        self._statement_evidence = statement_evidence
        self._project_execution_router = project_execution_router
        self._budget_controls_enabled = budget_controls_enabled


class EvaluateStage0ReadinessV2Tool(_Stage0ProjectTool):
    """Compute readiness from the current company Client KB in trusted product context."""

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
                    product_id=None,
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
                    "client_kb_missing", "the workspace client has no current company Client KB"
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
                    # ICP synthesis reads the company KB; the separately trusted selected product
                    # is persisted on the resulting ICP lineage below.
                    product_id=None,
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


class StartConfirmedProjectRunV2Tool(_Stage0ProjectTool):
    """Start discovery from the exact already-materialized, human-approved Stage-0 lineage."""

    name = "start_confirmed_project_run"
    version = "2"
    model_description = (
        "Start discovery after the human approves the ICP. Takes no arguments; the platform "
        "uses the turn's existing Client-KB, selected product, product profile, Product-KB and "
        "approved ICP and returns only the durable project-run reference."
    )
    input_model = StartConfirmedProjectRunV2Input
    output_model = StartConfirmedProjectRunV2Output
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="ProjectRunId(approved ICP + existing product-context receipt)",
        operation_id_required=True,
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy()
    pin_requirements = ("brand", "project", "product", "client_kb", "product_kb")

    @staticmethod
    def _scope_failure(scope: Stage0ProjectScope | None) -> tuple[PreconditionFailure, ...]:
        if scope is None or scope.turn_id is None:
            return _failure(
                "stage0_turn_scope_not_found",
                "the governed execution has no immutable Stage-0 turn scope",
            )
        if scope.product_id is None:
            return _failure("product_not_confirmed", "the project has no confirmed product")
        if scope.client_entity_id is None or scope.client_kb_version is None:
            return _failure("client_kb_missing", "the turn has no exact company Client-KB lineage")
        if scope.product_kb_version is None:
            return _failure(
                "product_kb_missing", "the turn has no exact selected-product knowledge lineage"
            )
        return ()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, StartConfirmedProjectRunV2Input)
        async with self._conn_factory() as conn:
            scope = await _scope(conn, ctx)
            if failure := self._scope_failure(scope):
                return failure
            assert scope is not None
            artifacts = await _turn_context_artifacts(conn, scope=scope)
            required_media = {
                CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE,
                STAGE0_PROJECT_STATE_CARD_MEDIA_TYPE,
                PRODUCT_PROFILE_CARD_MEDIA_TYPE,
                PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE,
            }
            if not required_media.issubset(artifacts):
                return _failure(
                    "stage0_context_materialization_missing",
                    "the turn does not carry every exact existing Stage-0 context card",
                )
            approved_icp = await _approved_icp(conn, scope=scope)
            if approved_icp is None:
                return _failure(
                    "approved_icp_missing",
                    "the project has no human-approved active ICP in this exact Stage-0 lineage",
                )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, StartConfirmedProjectRunV2Input)
        async with self._conn_factory() as conn:
            scope = await _scope(conn, ctx)
            if self._scope_failure(scope):
                raise ValueError("trusted Stage-0 confirmed-run scope became incomplete")
            assert scope is not None
            assert scope.product_id is not None
            assert scope.client_entity_id is not None
            assert scope.client_kb_version is not None

            artifacts = await _turn_context_artifacts(conn, scope=scope)
            approved_icp = await _approved_icp(conn, scope=scope)
            if approved_icp is None:
                raise ValueError("no human-approved active ICP exists in this exact turn lineage")
            receipt = _receipt_from_existing_inputs(
                scope=scope,
                approved_icp=approved_icp,
                artifacts=artifacts,
            )
            ordered_artifact_refs = tuple(
                artifacts[media_type].artifact_key
                for media_type in (
                    CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE,
                    STAGE0_PROJECT_STATE_CARD_MEDIA_TYPE,
                    PRODUCT_PROFILE_CARD_MEDIA_TYPE,
                    PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE,
                )
            )
            # This is the existing content-addressed insert-or-return compiler. The receipt is a
            # freshness/lineage manifest over cards that already exist; no agent, research call,
            # claim synthesis or second KB is involved.
            context_ref = await compile_product_context(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                product_id=scope.product_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                claim_refs=(),
                memory_refs=(),
                artifact_refs=ordered_artifact_refs,
                freshness_snapshot=cast(dict[str, JsonValue], receipt.model_dump(mode="json")),
                compiler_version=_PRODUCT_CONTEXT_COMPILER_VERSION,
            )

            claims = await read_client_kb_claims(
                conn,
                scope.client_entity_id,
                workspace_id=scope.workspace_id,
                version=scope.client_kb_version,
                product_id=None,
            )
            workspace_policy = await get_workspace_client_kb_readiness_policy(
                conn,
                workspace_id=scope.workspace_id,
            )
            workspace_required = (
                workspace_policy.required_field_keys if workspace_policy is not None else ()
            )
            metrics = client_kb_readiness_metrics(
                claims,
                baseline_field_keys=CLIENT_ICP_SYNTHESIS_FIELDS,
                required_field_keys=workspace_required,
            )
            metrics.update(
                {
                    "open_policy_blocks": 0,
                    "metrics_authority": _CONFIRMED_RUN_METRICS_AUTHORITY,
                    "budget_controls_enabled": self._budget_controls_enabled,
                    "budget_enforcement_mode": (
                        "enforced" if self._budget_controls_enabled else "record_only"
                    ),
                    "receipt_manifest_sha256": receipt.manifest_sha256,
                }
            )
            readiness_operation = operation_id_from_key(
                scope.workspace_id,
                "confirmed-discovery-readiness:"
                f"{scope.project_id}:{approved_icp.icp_key}:{approved_icp.version}:"
                f"{context_ref.version_id}",
            )
            readiness_id = ReadinessDecisionId(UUID(str(readiness_operation)))
            readiness_snapshot = await evaluate_readiness(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                product_id=scope.product_id,
                project_id=scope.project_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                icp_key=approved_icp.icp_key,
                icp_version=approved_icp.version,
                product_context_version_id=ProductContextVersionId(context_ref.version_id),
                gate=ReadinessGate.DISCOVERY_SPEND,
                spec=self._policy.readiness,
                metrics=metrics,
                created_by_actor="system",
                readiness_decision_id=readiness_id,
            )
            readiness = await get_readiness_decision(
                conn,
                readiness_snapshot.readiness_decision_id,
                workspace_id=scope.workspace_id,
            )
            if readiness is None or readiness.verdict is not ReadinessVerdict.READY:
                raise ValueError("the internally evaluated discovery boundary is not ready")

            run_operation = operation_id_from_key(
                scope.workspace_id,
                "confirmed-project-run:"
                f"{scope.project_id}:{approved_icp.icp_key}:{approved_icp.version}:"
                f"{context_ref.version_id}",
            )
            run_id = ProjectRunId(UUID(str(run_operation)))
            await start_confirmed_project_run(
                conn,
                project_run_id=run_id,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                client_entity_id=scope.client_entity_id,
                client_kb_version=scope.client_kb_version,
                product_id=scope.product_id,
                product_context_version_id=ProductContextVersionId(context_ref.version_id),
                readiness_decision_id=readiness.id,
                icp_key=approved_icp.icp_key,
                icp_version=approved_icp.version,
                budget_cap_cents=None,
            )
        if self._project_execution_router is not None:
            await self._project_execution_router.attach_if_eligible(
                run_id,
                actor=ctx.actor,
                parent_execution_id=ctx.execution_id,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=StartConfirmedProjectRunV2Output(
                project_run_id=str(run_id),
                phase="discovery",
            ).model_dump(),
        )


def stage0_project_tools(
    *,
    conn_factory: ConnFactory,
    policy: Stage0Policy,
    gateway: LLMGateway | None,
    synthesis_model: str | None,
    statement_evidence: ArtifactStatementEvidenceReader | None,
    project_execution_router: ProjectExecutionRouter | None = None,
    budget_controls_enabled: bool = True,
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
        StartConfirmedProjectRunV2Tool(
            conn_factory=conn_factory,
            policy=policy,
            project_execution_router=project_execution_router,
            budget_controls_enabled=budget_controls_enabled,
        ),
    )
