"""Canonical C5.6 outcome fingerprint used only by tests/evals.

Generated ids, timestamps, prose, raw token counts, and unordered reference ordering are excluded.
The remaining fields are the replay-relevant input roles and governed outcome categories.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectPhase, ProjectRunId
from clue_research.durable import get_checkpoint, get_project_run


class OutcomeFingerprint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pin_roles: tuple[tuple[str, str | None, str], ...]
    phases: tuple[tuple[str, str, str | None], ...]
    fields: tuple[tuple[str, str, str], ...]
    attempts: tuple[tuple[str, str, str, str], ...]
    decisions: tuple[tuple[str, str | None, str], ...]
    controls: tuple[tuple[str, str, str, str], ...]
    budget_bands: tuple[tuple[str, str], ...]
    yield_bands: tuple[tuple[str, str, str], ...]


def _band(value: object) -> str:
    amount = Decimal(str(value))
    if amount == 0:
        return "zero"
    if amount <= 100:
        return "low"
    if amount <= 1_000:
        return "medium"
    return "high"


async def build_outcome_fingerprint(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
) -> OutcomeFingerprint:
    run = await get_project_run(conn, project_run_id)
    if run is None or run.workspace_id != workspace_id:
        raise ValueError("project run is missing or outside the workspace")
    owner = (
        await conn.execute(
            text(
                "SELECT execution_id FROM project_run_execution_owner "
                "WHERE project_run_id = :run_id AND workspace_id = :workspace_id"
            ),
            {"run_id": project_run_id, "workspace_id": workspace_id},
        )
    ).scalar_one_or_none()
    pin_roles: tuple[tuple[str, str | None, str], ...]
    if owner is None:
        pin_roles = (
            ("field_registry", "snapshot-v1", "active"),
            ("icp", str(run.icp_version), "active"),
            ("project", "1", "active"),
            ("project_run", "1", "active"),
            ("source_registry", "snapshot-v1", "active"),
            ("supervisor_policy", "supervisor-v1", "active"),
        )
    else:
        pins = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT DISTINCT kind, version, resolved_status
                        FROM execution_pin
                        WHERE execution_id = :execution_id AND node_id IS NULL
                          AND resolved_status = 'active'
                          AND kind IN (
                              'field_registry', 'icp', 'project', 'project_run',
                              'source_registry', 'supervisor_policy'
                          )
                        ORDER BY kind, version, resolved_status
                        """
                    ),
                    {"execution_id": owner},
                )
            )
            .mappings()
            .all()
        )
        pin_roles = tuple(
            (
                str(row["kind"]),
                str(row["version"]) if row["version"] is not None else None,
                str(row["resolved_status"]),
            )
            for row in pins
        )

    phase_rows: list[tuple[str, str, str | None]] = []
    for phase in ProjectPhase:
        checkpoint = await get_checkpoint(conn, project_run_id, phase)
        if checkpoint is not None:
            decision = checkpoint.payload.get("decision")
            action = (
                str(decision.get("action"))
                if isinstance(decision, dict) and decision.get("action") is not None
                else None
            )
            phase_rows.append((phase.value, checkpoint.status.value, action))

    fields = (
        (
            await conn.execute(
                text(
                    """
                    SELECT field_key, source_key, verification_status
                    FROM claim
                    WHERE workspace_id = :workspace_id
                    ORDER BY field_key, source_key, verification_status
                    """
                ),
                {"workspace_id": workspace_id},
            )
        )
        .tuples()
        .all()
    )
    attempts = (
        (
            await conn.execute(
                text(
                    """
                    SELECT field_key, strategy_key, outcome, stop_reason
                    FROM coverage_attempt
                    WHERE workspace_id = :workspace_id AND project_run_id = :run_id
                    ORDER BY field_key, round, strategy_key
                    """
                ),
                {"workspace_id": workspace_id, "run_id": project_run_id},
            )
        )
        .tuples()
        .all()
    )
    decisions = (
        (
            await conn.execute(
                text(
                    """
                    SELECT field_key, terminal_status, reason_code
                    FROM coverage_decision
                    WHERE workspace_id = :workspace_id AND project_run_id = :run_id
                    ORDER BY field_key, round
                    """
                ),
                {"workspace_id": workspace_id, "run_id": project_run_id},
            )
        )
        .tuples()
        .all()
    )
    control_rows: Sequence[tuple[Any, Any, Any, Any]] = ()
    if owner is not None:
        control_rows = cast(
            Sequence[tuple[Any, Any, Any, Any]],
            (
                await conn.execute(
                    text(
                        """
                        SELECT control_kind, subject_ref, action, reason_code
                        FROM run_control_event
                        WHERE execution_id = :execution_id
                        ORDER BY seq
                        """
                    ),
                    {"execution_id": owner},
                )
            )
            .tuples()
            .all(),
        )
    budgets = (
        (
            await conn.execute(
                text(
                    """
                    SELECT kind, projected_cents
                    FROM budget_event
                    WHERE project_run_id = :run_id
                    ORDER BY seq
                    """
                ),
                {"run_id": project_run_id},
            )
        )
        .tuples()
        .all()
    )
    yields = (
        (
            await conn.execute(
                text(
                    """
                    SELECT source_key, fields_filled, cost_cents
                    FROM source_yield
                    WHERE workspace_id = :workspace_id
                      AND run_id = :run_id
                      AND icp_key = :icp_key
                      AND (icp_version IS NULL OR icp_version = :icp_version)
                    ORDER BY source_key, id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "run_id": project_run_id,
                    "icp_key": run.icp_key,
                    "icp_version": run.icp_version,
                },
            )
        )
        .tuples()
        .all()
    )
    return OutcomeFingerprint(
        pin_roles=pin_roles,
        phases=tuple(phase_rows),
        fields=tuple((str(a), str(b), str(c)) for a, b, c in fields),
        attempts=tuple((str(a), str(b), str(c), str(d)) for a, b, c, d in attempts),
        decisions=tuple(
            (str(a), str(b) if b is not None else None, str(c)) for a, b, c in decisions
        ),
        controls=tuple((str(a), str(b), str(c), str(d)) for a, b, c, d in control_rows),
        budget_bands=tuple((str(kind), _band(value)) for kind, value in budgets),
        yield_bands=tuple(
            (str(source), _band(filled), _band(cost)) for source, filled, cost in yields
        ),
    )


__all__ = ["OutcomeFingerprint", "build_outcome_fingerprint"]
