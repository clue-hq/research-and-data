"""``python -m clue_projections.cost_cli`` — the operator's view of :func:`cost_report`.

Prints the report as aligned text (default) or JSON (``--json``). Reads the database named by
``CLUE_DATABASE_URL`` through the package's default connection factory; nothing here writes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from clue_db import db_lifespan
from clue_projections.cost import CostFilters, CostReport, cost_report

__all__ = ["build_parser", "main", "render_report"]


def _iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{value!r} needs a timezone (e.g. 2026-09-14T00:00:00Z)")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m clue_projections.cost_cli",
        description="What a workspace's work cost, from the provider ledger and the turn receipts.",
    )
    parser.add_argument("--workspace", required=True, help="workspace id (the tenant)")
    parser.add_argument("--project", default=None, help="project id")
    parser.add_argument("--project-run", dest="project_run", default=None, help="project run id")
    parser.add_argument("--job", type=UUID, default=None, help="account-research job id")
    parser.add_argument(
        "--thread", default=None, help="conversation thread id (turn receipts only)"
    )
    parser.add_argument("--since", type=_iso, default=None, help="inclusive ISO-8601 with timezone")
    parser.add_argument("--until", type=_iso, default=None, help="exclusive ISO-8601 with timezone")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser


def _section(title: str, header: str, rows: list[str]) -> list[str]:
    if not rows:
        return [f"{title}: none"]
    return [title, f"  {header}", *(f"  {row}" for row in rows)]


def render_report(report: CostReport) -> str:
    filters = ", ".join(
        f"{name}={value}"
        for name, value in report.filters.model_dump().items()
        if value is not None
    )
    lines = [
        f"cost report — workspace {report.workspace_id}" + (f" ({filters})" if filters else ""),
        f"  total_usd {report.total_usd}  provider_usd {report.provider_usd}  "
        f"turn_model_usd {report.turn_model_usd}  credits {report.credits}  "
        f"media_seconds {report.media_seconds}",
        "",
    ]
    lines += _section(
        "providers (result rows only)",
        "provider  operation  calls  ok  usd  credits  media_s  metered/estimate/free/unpriced",
        [
            f"{p.provider}  {p.operation}  {p.calls}  {p.ok_calls}  {p.cost_usd}  {p.credits}  "
            f"{p.media_seconds}  {p.metered_calls}/{p.estimated_calls}/"
            f"{p.free_calls}/{p.unpriced_calls}"
            for p in report.providers
        ],
    )
    lines.append("")
    lines += _section(
        "models",
        "source  model  role/operation  calls  in  cached  out  usd  unpriced",
        [
            f"{m.source}  {m.model}  {m.role or '-'}  {m.calls}  {m.input_tokens}  "
            f"{m.cached_input_tokens}  {m.output_tokens}  {m.cost_usd}  unpriced {m.unpriced_calls}"
            for m in report.models
        ],
    )
    lines.append("")
    lines += _section(
        "jobs (largest first)",
        "job_id  calls  usd  credits  media_s",
        [
            f"{j.job_id}  {j.calls}  {j.cost_usd}  {j.credits}  {j.media_seconds}"
            for j in report.jobs
        ],
    )
    lines.append("")
    lines += _section(
        "projects",
        "project_id  provider_usd  turn_model_usd  total_usd",
        [
            f"{p.project_id}  {p.provider_usd}  {p.turn_model_usd}  {p.total_usd}"
            for p in report.projects
        ],
    )
    lines.append("")
    lines += ["NOT COVERED by this read:", *(f"  - {item}" for item in report.not_covered)]
    if report.notes:
        lines += ["", "notes:", *(f"  - {note}" for note in report.notes)]
    return "\n".join(lines) + "\n"


async def _run(workspace_id: str, filters: CostFilters) -> CostReport:
    async with db_lifespan():
        return await cost_report(workspace_id=workspace_id, filters=filters)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    filters = CostFilters(
        project_id=args.project,
        project_run_id=args.project_run,
        job_id=args.job,
        thread_id=args.thread,
        since=args.since,
        until=args.until,
    )
    report = asyncio.run(_run(args.workspace, filters))
    if args.json:
        sys.stdout.write(json.dumps(report.model_dump(mode="json"), indent=2) + "\n")
    else:
        sys.stdout.write(render_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by hand and by the live proof
    raise SystemExit(main())
