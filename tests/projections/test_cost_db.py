"""Lane 3 slice 1, Task 4: the cost read over the two ledgers.

Seeds one workspace with a conversation turn (three model-call receipts: metered, unpriced, and a
legacy NULL row) and six provider ledger rows (a metered Exa search, its estimate-phase twin, a
free ATS fetch, an AI Ark credits call, a research-agent model round, and a row for a second job),
plus a second workspace with one row of each kind that must never leak in. Then asserts every
accounting rule in ``clue_projections.cost``'s docstring.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_projections.cost import CostFilters, CostReport, cost_report
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

T0 = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
SHA = "e" * 64


async def _turn(
    conn: AsyncConnection,
    *,
    ws: str,
    project_id: str,
    thread_id: str,
    role: str = "head_of_abm",
) -> UUID:
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :p) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": thread_id, "ws": ws, "p": project_id},
    )
    execution_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            " parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :p, 'human', :hash, :hash)"
        ),
        {"id": execution_id, "ws": ws, "p": project_id, "hash": "0" * 64},
    )
    key = f"{ws}/{SHA}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 11) "
            "ON CONFLICT (storage_key) DO NOTHING"
        ),
        {"key": key, "ws": ws, "sha": SHA},
    )
    turn_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_turn (id, execution_id, workspace_id, project_id, thread_id, "
            " actor_id, role, workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at) "
            "VALUES (:id, :execution, :ws, :p, :thread, 'actor-1', :role, 'root-1', "
            " 'head-of-abm', 'v1', :hash, :key, :sha, :hash, 'standard', :at)"
        ),
        {
            "id": turn_id,
            "role": role,
            "execution": execution_id,
            "ws": ws,
            "p": project_id,
            "thread": thread_id,
            "hash": "0" * 64,
            "key": key,
            "sha": SHA,
            "at": T0,
        },
    )
    return turn_id


async def _model_call(
    conn: AsyncConnection,
    *,
    ws: str,
    turn_id: UUID,
    sequence: int,
    cost_usd: Decimal | None,
    cost_source: str | None,
    started_at: datetime = T0,
    role: str = "head_of_abm",
) -> None:
    execution_id = (
        await conn.execute(
            text("SELECT execution_id FROM agent_turn WHERE id = :t"), {"t": turn_id}
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO agent_model_call (id, turn_id, execution_id, workspace_id, sequence, "
            " requested_model, answering_model, status, input_tokens, cache_read_input_tokens, "
            " output_tokens, cost_millicredits, cost_usd, cost_source, latency_ms, role, "
            " started_at, completed_at) "
            "VALUES (:id, :turn, :execution, :ws, :seq, 'x-ai/grok-4.6', 'x-ai/grok-4.6', "
            " 'completed', 100, 40, 10, 0, :cost, :source, 5, :role, :at, :at)"
        ),
        {
            "id": uuid4(),
            "role": role,
            "turn": turn_id,
            "execution": execution_id,
            "ws": ws,
            "seq": sequence,
            "cost": cost_usd,
            "source": cost_source,
            "at": started_at,
        },
    )


async def _ledger(
    conn: AsyncConnection,
    *,
    ws: str,
    project_id: str,
    project_run_id: str,
    job_id: UUID | None,
    provider: str,
    operation: str,
    phase: str = "result",
    outcome: str = "ok",
    cost_usd: Decimal | None,
    credits: Decimal | None = None,
    media_seconds: int | None = None,
    extras: dict[str, Any] | None = None,
    recorded_at: datetime = T0,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO provider_call_ledger (call_id, workspace_id, project_id, project_run_id, "
            " entity_research_job_id, provider, operation, label, phase, http_status, latency_ms, "
            " attempts, estimate_usd, cost_usd, credits, media_seconds, outcome, extras_json, "
            " recorded_at) "
            "VALUES (:call, :ws, :p, :run, :job, :provider, :op, :label, :phase, 200, 100, 1, "
            " 0.01, :cost, :credits, :media, :outcome, CAST(:extras AS jsonb), :at)"
        ),
        {
            "call": uuid4(),
            "ws": ws,
            "p": project_id,
            "run": project_run_id,
            "job": job_id,
            "provider": provider,
            "op": operation,
            "label": f"{provider}-{operation}",
            "phase": phase,
            "cost": cost_usd,
            "credits": credits,
            "media": media_seconds,
            "outcome": outcome,
            "extras": json.dumps(extras) if extras is not None else None,
            "at": recorded_at,
        },
    )


async def _seed(conn: AsyncConnection) -> dict[str, Any]:
    ws = f"ws_cost_{uuid4().hex[:10]}"
    project = await seed_project(conn, ws, name="cost read")
    run_a = str(uuid4())
    job_1, job_2 = uuid4(), uuid4()
    turn = await _turn(conn, ws=ws, project_id=project.project_id, thread_id=f"thread-{ws}")
    await _model_call(
        conn, ws=ws, turn_id=turn, sequence=1, cost_usd=Decimal("0.02"), cost_source="metered"
    )
    await _model_call(conn, ws=ws, turn_id=turn, sequence=2, cost_usd=None, cost_source="unpriced")
    await _model_call(
        conn,
        ws=ws,
        turn_id=turn,
        sequence=3,
        cost_usd=None,
        cost_source=None,
        started_at=T0 - timedelta(days=2),
    )
    p = project.project_id
    await _ledger(
        conn,
        ws=ws,
        project_id=p,
        project_run_id=run_a,
        job_id=job_1,
        provider="exa",
        operation="search",
        cost_usd=Decimal("0.007"),
        extras={"cost_source": "metered"},
    )
    await _ledger(
        conn,
        ws=ws,
        project_id=p,
        project_run_id=run_a,
        job_id=job_1,
        provider="exa",
        operation="search",
        phase="estimate",
        outcome="estimate",
        cost_usd=None,
    )
    await _ledger(
        conn,
        ws=ws,
        project_id=p,
        project_run_id=run_a,
        job_id=job_1,
        provider="ats",
        operation="board",
        cost_usd=Decimal("0"),
        extras={"cost_source": "free"},
    )
    await _ledger(
        conn,
        ws=ws,
        project_id=p,
        project_run_id=run_a,
        job_id=job_1,
        provider="aiark",
        operation="company",
        cost_usd=Decimal("0"),
        credits=Decimal("1.5"),
        extras={"cost_source": "metered"},
    )
    await _ledger(
        conn,
        ws=ws,
        project_id=p,
        project_run_id=run_a,
        job_id=job_1,
        provider="openrouter",
        operation="agent_completion",
        cost_usd=Decimal("0.5"),
        extras={
            "cost_source": "metered",
            "model": "x-ai/grok-4.6",
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "cached_prompt_tokens": 300,
        },
    )
    await _ledger(
        conn,
        ws=ws,
        project_id=p,
        project_run_id=run_a,
        job_id=job_2,
        provider="exa",
        operation="contents",
        cost_usd=Decimal("0.003"),
        extras={"cost_source": "metered"},
        recorded_at=T0 + timedelta(hours=1),
    )
    # the other tenant: one of each, never visible
    other = f"ws_other_{uuid4().hex[:10]}"
    other_project = await seed_project(conn, other, name="other")
    other_turn = await _turn(
        conn, ws=other, project_id=other_project.project_id, thread_id=f"thread-{other}"
    )
    await _model_call(
        conn, ws=other, turn_id=other_turn, sequence=1, cost_usd=Decimal("9"), cost_source="metered"
    )
    await _ledger(
        conn,
        ws=other,
        project_id=other_project.project_id,
        project_run_id=str(uuid4()),
        job_id=uuid4(),
        provider="exa",
        operation="search",
        cost_usd=Decimal("9"),
        extras={"cost_source": "metered"},
    )
    return {
        "ws": ws,
        "project_id": p,
        "run_a": run_a,
        "job_1": job_1,
        "job_2": job_2,
        "thread_id": f"thread-{ws}",
    }


def _report(
    filters: CostFilters | Callable[[dict[str, Any]], CostFilters] | None = None,
) -> tuple[dict[str, Any], CostReport]:
    """Seed a fresh workspace and report on it.

    Every call seeds its own workspace inside its own rolled-back transaction, so a filter that
    names a seeded id (a job, a thread) has to be built from *this* call's seeds — pass a callable
    and it is handed them. A ``CostFilters`` built from an earlier call's seeds would name rows
    this workspace never had, and the filter tests would pass on an empty report.
    """

    async def scenario() -> tuple[dict[str, Any], CostReport]:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            resolved = filters(seeds) if callable(filters) else filters
            report = await cost_report(
                workspace_id=seeds["ws"], filters=resolved, conn_factory=conn_session_factory(conn)
            )
            return seeds, report

    return run_async(scenario())


def test_totals_sum_result_rows_and_turn_receipts_without_double_counting() -> None:
    _, report = _report()
    assert report.provider_usd == Decimal("0.510000")  # 0.007 + 0 + 0 + 0.5 + 0.003
    assert report.turn_model_usd == Decimal("0.020000")  # NULL rows count 0
    assert report.total_usd == Decimal("0.530000")
    assert report.credits == Decimal("1.500")
    assert report.media_seconds == 0


def test_provider_lines_carry_labels_and_skip_the_estimate_phase() -> None:
    _, report = _report()
    lines = {(line.provider, line.operation): line for line in report.providers}
    exa = lines[("exa", "search")]
    assert (exa.calls, exa.ok_calls, exa.cost_usd, exa.metered_calls) == (
        1,
        1,
        Decimal("0.007000"),
        1,
    )
    assert lines[("ats", "board")].free_calls == 1
    assert lines[("aiark", "company")].credits == Decimal("1.500")
    assert report.providers[0].cost_usd >= report.providers[-1].cost_usd  # ordered by spend


def test_model_lines_split_turn_receipts_from_the_research_ledger() -> None:
    _, report = _report()
    turn = [m for m in report.models if m.source == "turn_receipts"]
    ledger = [m for m in report.models if m.source == "research_ledger"]
    assert len(turn) == 1 and turn[0].model == "x-ai/grok-4.6" and turn[0].role == "head_of_abm"
    assert (turn[0].calls, turn[0].cost_usd, turn[0].unpriced_calls) == (3, Decimal("0.020000"), 2)
    assert (turn[0].input_tokens, turn[0].cached_input_tokens, turn[0].output_tokens) == (
        300,
        120,
        30,
    )
    assert len(ledger) == 1 and ledger[0].model == "x-ai/grok-4.6"
    assert (ledger[0].calls, ledger[0].cost_usd, ledger[0].input_tokens) == (
        1,
        Decimal("0.500000"),
        1000,
    )


def test_jobs_and_projects_break_the_spend_down() -> None:
    seeds, report = _report()
    jobs = {line.job_id: line for line in report.jobs}
    assert jobs[seeds["job_1"]].cost_usd == Decimal("0.507000")
    assert jobs[seeds["job_2"]].cost_usd == Decimal("0.003000")
    assert report.jobs[0].job_id == seeds["job_1"]  # largest first
    assert len(report.projects) == 1
    project = report.projects[0]
    assert (project.provider_usd, project.turn_model_usd, project.total_usd) == (
        Decimal("0.510000"),
        Decimal("0.020000"),
        Decimal("0.530000"),
    )


def test_job_filter_narrows_the_ledger_and_says_turn_receipts_cannot_follow() -> None:
    _, report = _report(lambda seeds: CostFilters(job_id=seeds["job_2"]))
    assert report.provider_usd == Decimal("0.003000")
    assert report.turn_model_usd == Decimal("0")
    assert not [m for m in report.models if m.source == "turn_receipts"]
    assert any("turn" in note for note in report.notes)


def test_thread_filter_narrows_the_receipts_and_says_the_ledger_cannot_follow() -> None:
    _, report = _report(lambda seeds: CostFilters(thread_id=seeds["thread_id"]))
    assert report.turn_model_usd == Decimal("0.020000")
    assert report.provider_usd == Decimal("0") and report.providers == ()
    assert any("ledger" in note for note in report.notes)


def test_time_window_applies_to_both_ledgers() -> None:
    _, report = _report(
        CostFilters(since=T0 - timedelta(minutes=1), until=T0 + timedelta(minutes=1))
    )
    assert report.provider_usd == Decimal("0.507000")  # job_2's row at T0+1h excluded
    turn = [m for m in report.models if m.source == "turn_receipts"][0]
    assert turn.calls == 2  # the legacy row two days earlier excluded


def test_not_covered_names_only_the_ledgers_this_read_still_cannot_see() -> None:
    """Slice 1b routed the onboarding, display and evidence ledgers onto Postgres and slice 5 the
    design subsystem's; what is left is the turn rows written before the cost columns."""
    _, report = _report()
    text_ = " ".join(report.not_covered)
    assert "before" in text_
    for word in ("onboarding", "display", "evidence", "design"):
        assert word not in text_
    assert len(report.not_covered) == 1


def test_design_spend_lands_on_both_halves_of_the_report() -> None:
    """Slice 5: a design provider call is a provider line and a design model call is a turn
    receipt line — the two surfaces the ``NOT COVERED`` design entry used to stand in for."""

    async def scenario() -> CostReport:
        async with rollback_conn(seed_pack=False) as conn:
            ws = f"ws_design_cost_{uuid4().hex[:10]}"
            project = await seed_project(conn, ws, name="design cost")
            turn = await _turn(
                conn,
                ws=ws,
                project_id=project.project_id,
                thread_id=f"thread-{ws}",
                role="design",
            )
            await _model_call(
                conn,
                ws=ws,
                turn_id=turn,
                sequence=1,
                cost_usd=Decimal("0.0087"),
                cost_source="metered",
                role="design",
            )
            await _ledger(
                conn,
                ws=ws,
                project_id=project.project_id,
                project_run_id=str(uuid4()),
                job_id=uuid4(),
                provider="openrouter",
                operation="design.ingestion.describe",
                cost_usd=Decimal("0.0123"),
                extras={"cost_source": "metered"},
            )
            return await cost_report(workspace_id=ws, conn_factory=conn_session_factory(conn))

    report = run_async(scenario())
    (provider_line,) = report.providers
    assert provider_line.provider == "openrouter"
    assert provider_line.operation == "design.ingestion.describe"
    assert provider_line.cost_usd == Decimal("0.012300")
    turn_lines = [m for m in report.models if m.source == "turn_receipts"]
    assert [(m.role, m.cost_usd) for m in turn_lines] == [("design", Decimal("0.008700"))]
    assert report.total_usd == Decimal("0.021000")
