"""The cost read (lane 3 slice 1): what a workspace's work cost, from the rows that recorded it.

Two ledgers, summed once each, never recomputed:

* ``provider_call_ledger`` — every paid call ARV2 makes through ``ProviderCaller`` (Exa, AI Ark,
  Gemini media, structuring, the ATS fetches) **and** the ARV2 research agent's own model rounds
  (``provider='openrouter'``) **and**, since slice 5, every paid call the design subsystem makes
  through the same caller (text-to-image, the ingestion models, ad-DNA, the logo and ad-library
  vendors). Only ``phase='result'`` rows are money; an ``estimate`` row is a
  reservation written before the wire. ``extras_json->>'cost_source'`` labels each row
  ``metered`` / ``estimate`` / ``free`` / ``unpriced``.
* ``agent_model_call`` — every conversation-turn model call (Head of ABM and its delegates, and
  since slice 5 the design trio's calls, re-keyed onto the design leg's turn with
  ``role='design'``), with the gateway-measured ``cost_usd`` beside the still-zero
  ``cost_millicredits``. A NULL ``cost_usd`` is an unpriced model or a row older than the cost
  columns; it counts as 0 and as ``unpriced``, never as a measured zero.

The two tables never hold the same call, so ``total_usd = provider_usd + turn_model_usd``. The
``models`` section shows the research ledger's model rounds beside the turn receipts for a
per-model view; those research lines are a subset of ``providers`` and are not added to any total.
A ``research_ledger`` line reuses ``role`` to carry the ledger ``operation``.

What this read cannot see is named in ``not_covered`` on every report: turn rows written before
the cost columns existed are blank. Every other paid call — ARV2 research, discovery, onboarding,
the display prewrite, the persona-evidence tool (slice 1b) and the design subsystem (slice 5) —
is on one of these two ledgers.

Every query is workspace-scoped and read-only (the projections package writes nothing).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import ConnFactory, transaction

__all__ = [
    "CostFilters",
    "CostReport",
    "JobSpendLine",
    "ModelSpendLine",
    "NOT_COVERED",
    "ProjectSpendLine",
    "ProviderSpendLine",
    "cost_report",
]

_ZERO = Decimal("0")
_USD = Decimal("0.000001")
_CREDITS = Decimal("0.001")

#: The spend this read cannot see. Constant and printed on every report so a partial total is
#: never mistaken for a whole one. Each entry names the ledger and the reason. (Slice 1b routed
#: the onboarding lane, the display prewrite and the persona-evidence tool onto
#: provider_call_ledger, so they are no longer listed. Slice 5 put the design subsystem's
#: providers and the design trio's receipts on the ledgers.)
NOT_COVERED: tuple[str, ...] = (
    "conversation-turn model calls recorded before agent_model_call.cost_usd existed: blank, "
    "counted as unpriced",
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CostFilters(_Frozen):
    """Narrow the report. A filter a ledger cannot honour empties that ledger's half and adds a
    note; it never silently returns the unfiltered figure."""

    project_id: str | None = None
    project_run_id: str | None = None
    job_id: UUID | None = None
    thread_id: str | None = None
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None


class ProviderSpendLine(_Frozen):
    provider: str
    operation: str
    calls: int = Field(ge=0)
    ok_calls: int = Field(ge=0)
    cost_usd: Decimal
    credits: Decimal
    media_seconds: int = Field(ge=0)
    metered_calls: int = Field(ge=0)
    estimated_calls: int = Field(ge=0)
    free_calls: int = Field(ge=0)
    unpriced_calls: int = Field(ge=0)


class ModelSpendLine(_Frozen):
    source: Literal["turn_receipts", "research_ledger"]
    model: str
    #: turn_receipts: the agent role; research_ledger: the ledger operation (agent_completion /
    #: chat/completions).
    role: str | None
    calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal
    unpriced_calls: int = Field(ge=0)


class JobSpendLine(_Frozen):
    job_id: UUID
    calls: int = Field(ge=0)
    cost_usd: Decimal
    credits: Decimal
    media_seconds: int = Field(ge=0)


class ProjectSpendLine(_Frozen):
    project_id: str
    provider_usd: Decimal
    turn_model_usd: Decimal
    total_usd: Decimal


class CostReport(_Frozen):
    workspace_id: str
    filters: CostFilters
    provider_usd: Decimal
    turn_model_usd: Decimal
    total_usd: Decimal
    credits: Decimal
    media_seconds: int = Field(ge=0)
    providers: tuple[ProviderSpendLine, ...]
    models: tuple[ModelSpendLine, ...]
    jobs: tuple[JobSpendLine, ...]
    projects: tuple[ProjectSpendLine, ...]
    not_covered: tuple[str, ...]
    notes: tuple[str, ...]


def _usd(value: Any) -> Decimal:
    return (Decimal(value) if value is not None else _ZERO).quantize(_USD)


def _credits(value: Any) -> Decimal:
    return (Decimal(value) if value is not None else _ZERO).quantize(_CREDITS)


def _ledger_where(filters: CostFilters, workspace_id: str) -> tuple[str, dict[str, Any]]:
    clauses = ["workspace_id = :workspace", "phase = 'result'"]
    params: dict[str, Any] = {"workspace": workspace_id}
    if filters.project_id is not None:
        clauses.append("project_id = :project")
        params["project"] = filters.project_id
    if filters.project_run_id is not None:
        clauses.append("project_run_id = :project_run")
        params["project_run"] = filters.project_run_id
    if filters.job_id is not None:
        clauses.append("entity_research_job_id = :job")
        params["job"] = filters.job_id
    if filters.since is not None:
        clauses.append("recorded_at >= :since")
        params["since"] = filters.since
    if filters.until is not None:
        clauses.append("recorded_at < :until")
        params["until"] = filters.until
    return " AND ".join(clauses), params


def _receipt_where(filters: CostFilters, workspace_id: str) -> tuple[str, dict[str, Any]]:
    clauses = ["m.workspace_id = :workspace"]
    params: dict[str, Any] = {"workspace": workspace_id}
    if filters.project_id is not None:
        clauses.append("t.project_id = :project")
        params["project"] = filters.project_id
    if filters.thread_id is not None:
        clauses.append("t.thread_id = :thread")
        params["thread"] = filters.thread_id
    if filters.since is not None:
        clauses.append("m.started_at >= :since")
        params["since"] = filters.since
    if filters.until is not None:
        clauses.append("m.started_at < :until")
        params["until"] = filters.until
    return " AND ".join(clauses), params


_PROVIDER_LINES = (
    "SELECT provider, operation, count(*) AS calls, "
    " count(*) FILTER (WHERE outcome = 'ok') AS ok_calls, "
    " COALESCE(sum(cost_usd), 0) AS cost_usd, COALESCE(sum(credits), 0) AS credits, "
    " COALESCE(sum(media_seconds), 0) AS media_seconds, "
    " count(*) FILTER (WHERE extras_json->>'cost_source' = 'metered') AS metered_calls, "
    " count(*) FILTER (WHERE extras_json->>'cost_source' = 'estimate') AS estimated_calls, "
    " count(*) FILTER (WHERE extras_json->>'cost_source' = 'free') AS free_calls, "
    " count(*) FILTER (WHERE cost_usd IS NULL OR extras_json->>'cost_source' = 'unpriced') "
    "   AS unpriced_calls "
    "FROM provider_call_ledger WHERE {where} "
    "GROUP BY provider, operation ORDER BY cost_usd DESC, provider, operation"
)

_RESEARCH_MODEL_LINES = (
    "SELECT operation, COALESCE(NULLIF(extras_json->>'model', ''), 'unknown') AS model, "
    " count(*) AS calls, "
    " COALESCE(sum((extras_json->>'prompt_tokens')::bigint), 0) AS input_tokens, "
    " COALESCE(sum((extras_json->>'cached_prompt_tokens')::bigint), 0) AS cached_input_tokens, "
    " COALESCE(sum((extras_json->>'completion_tokens')::bigint), 0) AS output_tokens, "
    " COALESCE(sum(cost_usd), 0) AS cost_usd, "
    " count(*) FILTER (WHERE cost_usd IS NULL OR extras_json->>'cost_source' = 'unpriced') "
    "   AS unpriced_calls "
    "FROM provider_call_ledger WHERE {where} AND provider = 'openrouter' "
    "GROUP BY operation, model ORDER BY cost_usd DESC, model"
)

_JOB_LINES = (
    "SELECT entity_research_job_id AS job_id, count(*) AS calls, "
    " COALESCE(sum(cost_usd), 0) AS cost_usd, COALESCE(sum(credits), 0) AS credits, "
    " COALESCE(sum(media_seconds), 0) AS media_seconds "
    "FROM provider_call_ledger WHERE {where} AND entity_research_job_id IS NOT NULL "
    "GROUP BY entity_research_job_id ORDER BY cost_usd DESC, job_id LIMIT :job_limit"
)

_PROVIDER_BY_PROJECT = (
    "SELECT project_id, COALESCE(sum(cost_usd), 0) AS cost_usd "
    "FROM provider_call_ledger WHERE {where} AND project_id IS NOT NULL GROUP BY project_id"
)

_TURN_MODEL_LINES = (
    "SELECT COALESCE(m.answering_model, m.requested_model) AS model, m.role, count(*) AS calls, "
    " COALESCE(sum(m.input_tokens), 0) AS input_tokens, "
    " COALESCE(sum(m.cache_read_input_tokens), 0) AS cached_input_tokens, "
    " COALESCE(sum(m.output_tokens), 0) AS output_tokens, "
    " COALESCE(sum(m.cost_usd), 0) AS cost_usd, "
    " count(*) FILTER (WHERE m.cost_usd IS NULL) AS unpriced_calls "
    "FROM agent_model_call m JOIN agent_turn t "
    " ON t.id = m.turn_id AND t.workspace_id = m.workspace_id "
    "WHERE {where} GROUP BY model, m.role ORDER BY cost_usd DESC, model, m.role"
)

_TURN_MODEL_BY_PROJECT = (
    "SELECT t.project_id, COALESCE(sum(m.cost_usd), 0) AS cost_usd "
    "FROM agent_model_call m JOIN agent_turn t "
    " ON t.id = m.turn_id AND t.workspace_id = m.workspace_id "
    "WHERE {where} GROUP BY t.project_id"
)


async def _rows(conn: AsyncConnection, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    result = await conn.execute(text(sql), params)
    return [dict(row) for row in result.mappings().all()]


async def cost_report(
    *,
    workspace_id: str,
    filters: CostFilters | None = None,
    conn_factory: ConnFactory = transaction,
    job_limit: int = 50,
) -> CostReport:
    """Build one workspace's cost report under ``filters`` (see the module docstring for the
    accounting rules). Always returns a report; an empty workspace is all zeros, not an error."""
    resolved = filters or CostFilters()
    notes: list[str] = []
    ledger_applies = resolved.thread_id is None
    receipts_apply = resolved.project_run_id is None and resolved.job_id is None
    if not ledger_applies:
        notes.append(
            "thread_id filter: the provider ledger carries no thread, so provider lines, jobs "
            "and provider_usd are empty under this filter"
        )
    if not receipts_apply:
        notes.append(
            "project_run_id / job_id filter: conversation-turn receipts carry neither, so "
            "turn_receipts model lines and turn_model_usd are empty under this filter"
        )

    providers: list[ProviderSpendLine] = []
    research_models: list[ModelSpendLine] = []
    jobs: list[JobSpendLine] = []
    provider_by_project: dict[str, Decimal] = {}
    turn_models: list[ModelSpendLine] = []
    turn_by_project: dict[str, Decimal] = {}

    async with conn_factory() as conn:
        if ledger_applies:
            where, params = _ledger_where(resolved, workspace_id)
            for row in await _rows(conn, _PROVIDER_LINES.format(where=where), params):
                providers.append(
                    ProviderSpendLine(
                        provider=row["provider"],
                        operation=row["operation"],
                        calls=int(row["calls"]),
                        ok_calls=int(row["ok_calls"]),
                        cost_usd=_usd(row["cost_usd"]),
                        credits=_credits(row["credits"]),
                        media_seconds=int(row["media_seconds"]),
                        metered_calls=int(row["metered_calls"]),
                        estimated_calls=int(row["estimated_calls"]),
                        free_calls=int(row["free_calls"]),
                        unpriced_calls=int(row["unpriced_calls"]),
                    )
                )
            for row in await _rows(conn, _RESEARCH_MODEL_LINES.format(where=where), params):
                research_models.append(
                    ModelSpendLine(
                        source="research_ledger",
                        model=str(row["model"]),
                        role=str(row["operation"]),
                        calls=int(row["calls"]),
                        input_tokens=int(row["input_tokens"]),
                        cached_input_tokens=int(row["cached_input_tokens"]),
                        output_tokens=int(row["output_tokens"]),
                        cost_usd=_usd(row["cost_usd"]),
                        unpriced_calls=int(row["unpriced_calls"]),
                    )
                )
            for row in await _rows(
                conn, _JOB_LINES.format(where=where), {**params, "job_limit": job_limit}
            ):
                jobs.append(
                    JobSpendLine(
                        job_id=row["job_id"],
                        calls=int(row["calls"]),
                        cost_usd=_usd(row["cost_usd"]),
                        credits=_credits(row["credits"]),
                        media_seconds=int(row["media_seconds"]),
                    )
                )
            for row in await _rows(conn, _PROVIDER_BY_PROJECT.format(where=where), params):
                provider_by_project[str(row["project_id"])] = _usd(row["cost_usd"])
        if receipts_apply:
            where, params = _receipt_where(resolved, workspace_id)
            for row in await _rows(conn, _TURN_MODEL_LINES.format(where=where), params):
                turn_models.append(
                    ModelSpendLine(
                        source="turn_receipts",
                        model=str(row["model"]),
                        role=None if row["role"] is None else str(row["role"]),
                        calls=int(row["calls"]),
                        input_tokens=int(row["input_tokens"]),
                        cached_input_tokens=int(row["cached_input_tokens"]),
                        output_tokens=int(row["output_tokens"]),
                        cost_usd=_usd(row["cost_usd"]),
                        unpriced_calls=int(row["unpriced_calls"]),
                    )
                )
            for row in await _rows(conn, _TURN_MODEL_BY_PROJECT.format(where=where), params):
                turn_by_project[str(row["project_id"])] = _usd(row["cost_usd"])

    provider_usd = sum((line.cost_usd for line in providers), _ZERO).quantize(_USD)
    turn_model_usd = sum((line.cost_usd for line in turn_models), _ZERO).quantize(_USD)
    projects = tuple(
        ProjectSpendLine(
            project_id=project_id,
            provider_usd=provider_by_project.get(project_id, _ZERO).quantize(_USD),
            turn_model_usd=turn_by_project.get(project_id, _ZERO).quantize(_USD),
            total_usd=(
                provider_by_project.get(project_id, _ZERO) + turn_by_project.get(project_id, _ZERO)
            ).quantize(_USD),
        )
        for project_id in sorted(
            set(provider_by_project) | set(turn_by_project),
            key=lambda p: -(provider_by_project.get(p, _ZERO) + turn_by_project.get(p, _ZERO)),
        )
    )
    return CostReport(
        workspace_id=workspace_id,
        filters=resolved,
        provider_usd=provider_usd,
        turn_model_usd=turn_model_usd,
        total_usd=(provider_usd + turn_model_usd).quantize(_USD),
        credits=sum((line.credits for line in providers), _ZERO).quantize(_CREDITS),
        media_seconds=sum(line.media_seconds for line in providers),
        providers=tuple(providers),
        models=tuple(turn_models) + tuple(research_models),
        jobs=tuple(jobs),
        projects=projects,
        not_covered=NOT_COVERED,
        notes=tuple(notes),
    )
