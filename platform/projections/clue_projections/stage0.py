"""C4 Stage-0 read models. Every query is workspace-scoped and side-effect free."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text

from clue_core import ReadinessDecisionId, ReconRunId
from clue_db import ConnFactory, transaction
from clue_research.stage0 import get_readiness_decision, get_recon, read_client_kb


class ReconBriefView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    recon_run_id: str
    client_entity_id: str | None
    client_kb_version: int | None
    product_id: str | None
    facts: dict[str, JsonValue]
    fast_cost_cents: str
    background_pending: bool


class Stage0ProgressView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    recon_run_id: str
    fast_status: str
    background_status: str
    fast_client_kb_version: int | None
    client_kb_version: int | None
    fast_run_id: str
    background_run_id: str
    failure_code: str | None
    gap_refs: tuple[dict[str, JsonValue], ...] = ()
    field_proposal_refs: tuple[str, ...] = ()
    source_proposal_refs: tuple[str, ...] = ()
    ingestion_refs: tuple[str, ...] = ()


class Stage0ReadinessView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    readiness_decision_id: str
    gate: str
    verdict: str
    effective_verdict: str
    spec_version: int
    reason_codes: tuple[str, ...]
    metrics: dict[str, JsonValue]
    gap_refs: tuple[dict[str, JsonValue], ...]
    field_proposal_refs: tuple[str, ...]
    source_proposal_refs: tuple[str, ...]
    ingestion_refs: tuple[str, ...]
    agent_sufficiency_status: str


async def recon_brief(
    *,
    recon_run_id: ReconRunId,
    workspace_id: str,
    conn_factory: ConnFactory = transaction,
) -> ReconBriefView | None:
    async with conn_factory() as conn:
        recon = await get_recon(conn, recon_run_id, workspace_id=workspace_id)
        if recon is None:
            return None
        facts: dict[str, JsonValue] = {}
        if recon.client_entity_id is not None and recon.fast_client_kb_version is not None:
            facts = await read_client_kb(
                conn,
                recon.client_entity_id,
                workspace_id=workspace_id,
                version=recon.fast_client_kb_version,
                product_id=recon.product_id,
            )
    return ReconBriefView(
        recon_run_id=str(recon.id),
        client_entity_id=(
            str(recon.client_entity_id) if recon.client_entity_id is not None else None
        ),
        client_kb_version=recon.fast_client_kb_version,
        product_id=recon.product_id,
        facts=facts,
        fast_cost_cents=str(recon.fast_cost_cents),
        background_pending=recon.background_status.value in {"queued", "running", "paused"},
    )


async def stage0_progress(
    *,
    recon_run_id: ReconRunId,
    workspace_id: str,
    conn_factory: ConnFactory = transaction,
) -> Stage0ProgressView | None:
    async with conn_factory() as conn:
        recon = await get_recon(conn, recon_run_id, workspace_id=workspace_id)
        decision = None
        if recon is not None and recon.project_id is not None:
            decision_id = (
                await conn.execute(
                    text(
                        "SELECT id FROM readiness_decision "
                        "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "project_id": recon.project_id,
                    },
                )
            ).scalar_one_or_none()
            if decision_id is not None:
                decision = await get_readiness_decision(
                    conn, ReadinessDecisionId(decision_id), workspace_id=workspace_id
                )
    if recon is None:
        return None
    return Stage0ProgressView(
        recon_run_id=str(recon.id),
        fast_status=recon.fast_status.value,
        background_status=recon.background_status.value,
        fast_client_kb_version=recon.fast_client_kb_version,
        client_kb_version=recon.client_kb_version,
        fast_run_id=str(recon.fast_run_id),
        background_run_id=str(recon.background_run_id),
        failure_code=recon.failure_code,
        gap_refs=decision.gap_refs if decision is not None else (),
        field_proposal_refs=decision.field_proposal_refs if decision is not None else (),
        source_proposal_refs=decision.source_proposal_refs if decision is not None else (),
        ingestion_refs=decision.ingestion_refs if decision is not None else (),
    )


async def stage0_readiness(
    *,
    readiness_decision_id: ReadinessDecisionId,
    workspace_id: str,
    conn_factory: ConnFactory = transaction,
) -> Stage0ReadinessView | None:
    async with conn_factory() as conn:
        decision = await get_readiness_decision(
            conn, readiness_decision_id, workspace_id=workspace_id
        )
        if decision is None:
            return None
        overridden = (
            await conn.execute(
                text(
                    "SELECT 1 FROM readiness_override "
                    "WHERE readiness_decision_id = :id AND workspace_id = :workspace_id"
                ),
                {"id": readiness_decision_id, "workspace_id": workspace_id},
            )
        ).scalar_one_or_none()
    return Stage0ReadinessView(
        readiness_decision_id=str(decision.id),
        gate=decision.gate.value,
        verdict=decision.verdict.value,
        effective_verdict="overridden" if overridden else decision.verdict.value,
        spec_version=decision.spec_version,
        reason_codes=decision.reason_codes,
        metrics=decision.metrics,
        gap_refs=decision.gap_refs,
        field_proposal_refs=decision.field_proposal_refs,
        source_proposal_refs=decision.source_proposal_refs,
        ingestion_refs=decision.ingestion_refs,
        agent_sufficiency_status=decision.agent_sufficiency_status,
    )


__all__ = [
    "ReconBriefView",
    "Stage0ProgressView",
    "Stage0ReadinessView",
    "recon_brief",
    "stage0_progress",
    "stage0_readiness",
]
