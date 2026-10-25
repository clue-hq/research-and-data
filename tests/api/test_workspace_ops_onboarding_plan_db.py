"""The onboarding half of a workspace repair plan, operators and the audit row (spec 2026-10-25).

Real ``onboarding_run`` / ``onboarding_step`` rows in a rolled-back transaction; the planner only
reads.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.workspace_ops.audit import record_operation
from clue_api.workspace_ops.onboarding_plan import plan_onboarding_repair
from clue_api.workspace_ops.operators import OpsRefused, resolve_operator
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.auth.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


async def _seed(conn: AsyncConnection, tag: str) -> tuple[str, str, str]:
    ws = f"ws-ops-plan-{tag}-{uuid4().hex[:6]}"
    project = await seed_project(conn, ws, name=f"Ops plan {tag}")
    user = f"usr_ops_plan_{uuid4().hex[:8]}"
    await seed_principal(conn, workspace_id=ws, user_id=user)
    return ws, project.brand_id, user


async def _run(
    conn: AsyncConnection,
    ws: str,
    brand: str,
    user: str,
    *,
    kind: str = "full",
    status: str = "completed_with_gaps",
    at: datetime = _T0,
    steps: list[tuple[str, str | None, str, str | None]] = (),
) -> UUID:
    run_id = uuid4()
    terminal = status not in ("queued", "running")
    await conn.execute(
        text(
            "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, company_domain,"
            " requested_by_user_id, requested_at, status, kind, planned_steps, finished_at)"
            " VALUES (:r, :w, :b, 'illumio.com', :u, :at, :s, :k, CAST(:p AS jsonb), :f)"
        ),
        {
            "r": run_id,
            "w": ws,
            "b": brand,
            "u": user,
            "at": at,
            "s": status,
            "k": kind,
            "p": "[]" if kind == "repair" else None,
            "f": at + timedelta(minutes=5) if terminal else None,
        },
    )
    for offset, (step_kind, subject, step_status, code) in enumerate(steps):
        finished = step_status not in ("queued", "running")
        await conn.execute(
            text(
                "INSERT INTO onboarding_step (step_id, run_id, workspace_id, kind, subject_ref,"
                " phase, status, started_at, finished_at, failure_code, failure_message)"
                " VALUES (:id, :r, :w, :k, :sub, 'fast', :s, :st, :fin, :code, :msg)"
            ),
            {
                "id": uuid4(),
                "r": run_id,
                "w": ws,
                "k": step_kind,
                "sub": subject,
                "s": step_status,
                "st": at + timedelta(seconds=offset),
                "fin": at + timedelta(seconds=offset + 1) if finished else None,
                "code": code,
                "msg": f"{step_kind} failed" if code else None,
            },
        )
    return run_id


_ICP_FAILED = [
    ("overview", None, "completed", None),
    ("lineup", None, "completed", None),
    ("catalog_sync", None, "completed", None),
    ("reviews", None, "empty", None),
    ("synthesis", None, "failed", "provider_refused:openrouter:auth_invalid"),
]


def test_failed_icp_plans_synthesis_with_a_reason_and_an_estimate() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand, user = await _seed(conn, "icp")
            await _run(conn, ws, brand, user, steps=_ICP_FAILED)
            plan = await plan_onboarding_repair(conn, workspace_id=ws)
            assert [(s.kind, s.subject_ref) for s in plan.steps] == [("synthesis", None)]
            assert "provider_refused:openrouter:auth_invalid" in plan.steps[0].reason
            assert plan.steps[0].estimate_usd > Decimal(0)
            assert plan.in_flight == ()
            assert (plan.brand_id, plan.company_domain) == (brand, "illumio.com")

    run_async(scenario())


def test_empty_steps_are_never_planned_and_catalog_sync_redoes_lineup() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand, user = await _seed(conn, "catalog")
            await _run(
                conn,
                ws,
                brand,
                user,
                steps=[
                    ("overview", None, "completed", None),
                    ("lineup", None, "completed", None),
                    ("catalog_sync", None, "failed", "AuthenticationError"),
                    ("reviews", None, "empty", None),
                    ("synthesis", None, "completed", None),
                    ("persona", "enterprise-security", "failed", "turn_hung"),
                    ("product_research", "prod_1", "failed", "ProviderHalted"),
                ],
            )
            plan = await plan_onboarding_repair(conn, workspace_id=ws)
            assert sorted((s.kind, s.subject_ref) for s in plan.steps) == [
                ("lineup", None),
                ("persona", "enterprise-security"),
                ("product_research", "prod_1"),
            ]

    run_async(scenario())


def test_a_later_repair_attempt_supersedes_the_full_runs_failure() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand, user = await _seed(conn, "superseded")
            await _run(conn, ws, brand, user, steps=_ICP_FAILED)
            await _run(
                conn,
                ws,
                brand,
                user,
                kind="repair",
                status="completed",
                at=_T0 + timedelta(hours=1),
                steps=[("synthesis", None, "completed", None)],
            )
            plan = await plan_onboarding_repair(conn, workspace_id=ws)
            assert plan.steps == ()

    run_async(scenario())


def test_an_open_repair_or_full_run_puts_everything_in_flight() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand, user = await _seed(conn, "open")
            await _run(conn, ws, brand, user, steps=_ICP_FAILED)
            await _run(
                conn, ws, brand, user, kind="repair", status="queued", at=_T0 + timedelta(hours=1)
            )
            plan = await plan_onboarding_repair(conn, workspace_id=ws)
            assert plan.steps == ()
            assert plan.in_flight and "queued" in plan.in_flight[0]

    run_async(scenario())


def test_a_workspace_never_onboarded_plans_nothing() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, _brand, _user = await _seed(conn, "never")
            plan = await plan_onboarding_repair(conn, workspace_id=ws)
            assert plan.steps == () and plan.brand_id is None
            assert plan.in_flight == ("no onboarding has run for this workspace; start one",)

    run_async(scenario())


def test_resolve_operator_normalizes_case_and_spaces() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, _brand, user = await _seed(conn, "operator")
            email = f"Ops.Plan.{uuid4().hex[:6]}@CLUEHQ.ai"
            await conn.execute(
                text("UPDATE platform_user SET email = :e WHERE user_id = :u"),
                {"e": email, "u": user},
            )
            operator = await resolve_operator(conn, f"  {email.upper()} ")
            assert operator.user_id == user
            assert operator.actor == f"operator:{email.casefold()}"

    run_async(scenario())


def test_unknown_operator_is_refused_422() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(OpsRefused) as refused:
                await resolve_operator(conn, "nobody@example.invalid")
            assert (refused.value.status, refused.value.code) == (422, "operator_unknown")

    run_async(scenario())


def test_record_operation_writes_one_audit_row() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            run_id = uuid4()
            operation_id = await record_operation(
                conn,
                operation="repair",
                workspace_id="ws-audit",
                actor="operator:a@b.c",
                reason="outage",
                plan={"steps": ["synthesis"]},
                estimated_cost_usd=Decimal("1.5"),
                onboarding_run_id=run_id,
                design_job_ids=["ingest_1"],
            )
            row = (
                await conn.execute(
                    text("SELECT * FROM workspace_operation WHERE operation_id = :id"),
                    {"id": operation_id},
                )
            ).one()
            assert (row.operation, row.actor, row.reason) == ("repair", "operator:a@b.c", "outage")
            assert row.plan_json == {"steps": ["synthesis"]}
            assert row.estimated_cost_usd == Decimal("1.5")
            assert (row.onboarding_run_id, row.design_job_ids) == (run_id, ["ingest_1"])

    run_async(scenario())


def test_brand_kit_gaps_clear_once_a_later_kit_repair_finishes() -> None:
    """Final review #2: a repaired gap disappears from the onboarding view (spec §3.4 A)."""
    import json as _json

    from clue_api.workspace_ops.onboarding_plan import brand_kit_gaps
    from clue_design import ingestion as design_ingestion

    async def job(conn: AsyncConnection, ws: str, kind: str, status: str, evidence: dict) -> None:
        created = await design_ingestion.create_job(conn, workspace_id=ws, kind=kind, request={})
        await conn.execute(
            text(
                "UPDATE design_ingestion_job SET status = CAST(:s AS design_ingestion_status),"
                " evidence_json = CAST(:e AS jsonb), created_at = clock_timestamp()"
                " WHERE job_id = :j"
            ),
            {"s": status, "e": _json.dumps(evidence), "j": created["job_id"]},
        )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, _brand, _user = await _seed(conn, "kitgaps")
            gap = {"area": "descriptions", "failed": 252, "reason": "auth_invalid"}
            await job(conn, ws, "website", "succeeded_with_gaps", {"gaps": [gap]})
            assert [g["item"] for g in await brand_kit_gaps(conn, workspace_id=ws)] == [
                "descriptions"
            ]
            # A repair still running changes nothing yet.
            await job(conn, ws, "kit_repair", "running", {})
            assert len(await brand_kit_gaps(conn, workspace_id=ws)) == 1
            # A finished repair speaks for the kit: here it healed everything.
            await job(conn, ws, "kit_repair", "succeeded", {"gaps": []})
            assert await brand_kit_gaps(conn, workspace_id=ws) == []

    run_async(scenario())
