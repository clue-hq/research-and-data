"""Measured job totals join existing model/provider ledgers and preserve unknown prices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class QualityUsage:
    known_usd: Decimal
    credits: Decimal
    media_seconds: int
    unpriced_provider_calls: int
    unpriced_model_calls: int
    model_calls: int
    tool_calls: int
    runtime_used_ms: int

    def receipt(self) -> dict[str, object]:
        return {
            "known_usd": str(self.known_usd),
            "credits": str(self.credits),
            "media_seconds": self.media_seconds,
            "unpriced_provider_calls": self.unpriced_provider_calls,
            "unpriced_model_calls": self.unpriced_model_calls,
            "cost_complete": not (self.unpriced_provider_calls or self.unpriced_model_calls),
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "runtime_used_ms": self.runtime_used_ms,
        }


async def usage(conn: AsyncConnection, *, workspace_id: str, job_id: UUID) -> QualityUsage:
    provider = (
        await conn.execute(
            text("""SELECT COALESCE(sum(cost_usd),0) AS usd,
        COALESCE(sum(credits),0) AS credits, COALESCE(sum(media_seconds),0) AS media,
        count(*) FILTER (WHERE cost_usd IS NULL) AS unpriced
        FROM provider_call_ledger WHERE workspace_id=:ws
          AND entity_research_job_id=:job AND phase='result'"""),
            {"ws": workspace_id, "job": job_id},
        )
    ).one()
    model = (
        await conn.execute(
            text("""SELECT COALESCE(sum(m.cost_usd),0) AS usd,
        count(*) FILTER (WHERE m.cost_usd IS NULL) AS unpriced FROM agent_model_call m
        JOIN arv2_quality_execution e ON e.execution_id=m.execution_id
          AND e.workspace_id=m.workspace_id
        WHERE e.job_id=:job AND e.workspace_id=:ws"""),
            {"ws": workspace_id, "job": job_id},
        )
    ).one()
    bounds = (
        await conn.execute(
            text("""SELECT model_calls,tool_calls,runtime_used_ms FROM arv2_quality_allowance
        WHERE job_id=:job AND workspace_id=:ws"""),
            {"ws": workspace_id, "job": job_id},
        )
    ).one_or_none()
    return QualityUsage(
        Decimal(provider.usd) + Decimal(model.usd),
        Decimal(provider.credits),
        int(provider.media),
        int(provider.unpriced),
        int(model.unpriced),
        bounds.model_calls if bounds else 0,
        bounds.tool_calls if bounds else 0,
        bounds.runtime_used_ms if bounds else 0,
    )
