"""Lane 3 slice 1, Task 6: the cost CLI renders a report without touching a database."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from clue_projections.cost import (
    NOT_COVERED,
    CostFilters,
    CostReport,
    JobSpendLine,
    ModelSpendLine,
    ProjectSpendLine,
    ProviderSpendLine,
)
from clue_projections.cost_cli import build_parser, render_report

JOB = UUID("00000000-0000-0000-0000-000000000001")


def _report() -> CostReport:
    return CostReport(
        workspace_id="acme",
        filters=CostFilters(project_id="p1"),
        provider_usd=Decimal("0.510000"),
        turn_model_usd=Decimal("0.020000"),
        total_usd=Decimal("0.530000"),
        credits=Decimal("1.500"),
        media_seconds=0,
        providers=(
            ProviderSpendLine(
                provider="openrouter",
                operation="agent_completion",
                calls=1,
                ok_calls=1,
                cost_usd=Decimal("0.500000"),
                credits=Decimal("0"),
                media_seconds=0,
                metered_calls=1,
                estimated_calls=0,
                free_calls=0,
                unpriced_calls=0,
            ),
            ProviderSpendLine(
                provider="exa",
                operation="search",
                calls=2,
                ok_calls=2,
                cost_usd=Decimal("0.010000"),
                credits=Decimal("0"),
                media_seconds=0,
                metered_calls=2,
                estimated_calls=0,
                free_calls=0,
                unpriced_calls=0,
            ),
        ),
        models=(
            ModelSpendLine(
                source="turn_receipts",
                model="x-ai/grok-4.6",
                role="head_of_abm",
                calls=3,
                input_tokens=300,
                cached_input_tokens=120,
                output_tokens=30,
                cost_usd=Decimal("0.020000"),
                unpriced_calls=2,
            ),
        ),
        jobs=(
            JobSpendLine(
                job_id=JOB,
                calls=3,
                cost_usd=Decimal("0.507000"),
                credits=Decimal("1.500"),
                media_seconds=0,
            ),
        ),
        projects=(
            ProjectSpendLine(
                project_id="p1",
                provider_usd=Decimal("0.510000"),
                turn_model_usd=Decimal("0.020000"),
                total_usd=Decimal("0.530000"),
            ),
        ),
        not_covered=NOT_COVERED,
        notes=("a note",),
    )


def test_render_report_prints_every_section_and_the_honesty_list() -> None:
    out = render_report(_report())
    assert "workspace acme" in out and "project_id=p1" in out
    assert "total_usd 0.530000" in out
    assert "openrouter  agent_completion" in out and "exa  search" in out
    assert "x-ai/grok-4.6" in out and "unpriced 2" in out
    assert str(JOB) in out
    assert "p1" in out
    # Slice 5 removed the design entry; the pre-cost-columns turn rows are the one left.
    assert "NOT COVERED" in out and "counted as unpriced" in out
    assert "design subsystem" not in out
    assert "a note" in out


def test_parser_maps_every_flag_to_a_filter() -> None:
    args = build_parser().parse_args(
        [
            "--workspace",
            "acme",
            "--project",
            "p1",
            "--job",
            str(JOB),
            "--since",
            "2026-09-14T00:00:00Z",
            "--until",
            "2026-09-15T00:00:00Z",
            "--json",
        ]
    )
    assert args.workspace == "acme" and args.project == "p1" and args.job == JOB
    assert args.since == datetime(2026, 9, 14, tzinfo=UTC)
    assert args.until == datetime(2026, 9, 15, tzinfo=UTC)
    assert args.json is True
