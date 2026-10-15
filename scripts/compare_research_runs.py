"""Compare two sets of account-research jobs: cost, rounds, tools, page writes, findings, claims.

Read-only (the transaction is ``READ ONLY``). Each id is a research job id or a research run id
(a run id expands to all of its jobs). Typical use — production's 2026-10-06 jobs, copied into
this lane's database, against a recipe-26 run on the same accounts:

    set -a; source .env; set +a
    uv run python scripts/compare_research_runs.py --workspace ws_... \
        --before <run or job ids> --after <run or job ids> [--langfuse] [--json out.json]

Per job: status, cost, model rounds, tool calls, wall time, how long a person waited between
nomination and starting, page-writer calls (from the provider ledger), findings per dossier
section (from the stored dossier), and claims by conclusion. ``--langfuse`` adds failed tool
calls by tool name, counted from the jobs' Langfuse traces (``CLUE_LANGFUSE_*``); without it
those columns are left out, never guessed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DOSSIER_KIND = "research_json_dossier"


def _add(into: dict[str, int], counts: Mapping[str, int]) -> None:
    for key, value in counts.items():
        into[key] = into.get(key, 0) + int(value)


def summarise(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per-account and overall totals of per-job rows (see ``load_rows`` for the row shape)."""
    accounts: dict[str, dict[str, Any]] = {}
    for row in rows:
        account = accounts.setdefault(
            str(row["account"]),
            {
                "jobs": 0,
                "statuses": {},
                "cost_usd": 0.0,
                "model_rounds": 0,
                "tool_calls": 0,
                "wall_s": 0.0,
                "max_start_delay_s": None,
                "page_writer_calls": {},
                "tool_errors": {},
                "findings": 0,
                "claims": {},
            },
        )
        account["jobs"] += 1
        _add(account["statuses"], {str(row["status"]): 1})
        account["cost_usd"] = round(account["cost_usd"] + float(row["cost_usd"] or 0), 6)
        account["model_rounds"] += int(row["model_rounds"] or 0)
        account["tool_calls"] += int(row["tool_calls"] or 0)
        account["wall_s"] = max(account["wall_s"], float(row["wall_s"] or 0))
        delay = row.get("start_delay_s")
        if delay is not None:
            current = account["max_start_delay_s"]
            account["max_start_delay_s"] = delay if current is None else max(current, delay)
        _add(account["page_writer_calls"], row.get("page_writer_calls") or {})
        _add(account["tool_errors"], row.get("tool_errors") or {})
        account["findings"] += sum((row.get("sections") or {}).values())
        _add(account["claims"], row.get("claims") or {})
    cost = round(sum(a["cost_usd"] for a in accounts.values()), 6)
    return {
        "jobs": [dict(r) for r in rows],
        "accounts": accounts,
        "total": {
            "jobs": len(rows),
            "accounts": len(accounts),
            "cost_usd": cost,
            "cost_per_account": round(cost / len(accounts), 6) if accounts else 0.0,
        },
    }


def _counts(value: Mapping[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(value.items())) or "-"


def render(sides: Mapping[str, Mapping[str, Any]]) -> str:
    """A plain-text table per side: one line per account, then its jobs."""
    lines: list[str] = []
    for side, summary in sides.items():
        total = summary["total"]
        lines.append(
            f"== {side}: {total['jobs']} jobs, {total['accounts']} accounts, "
            f"${total['cost_usd']:.2f} (${total['cost_per_account']:.2f} per account)"
        )
        for name, account in sorted(summary["accounts"].items()):
            delay = account["max_start_delay_s"]
            lines.append(
                f"  {name}: ${account['cost_usd']:.2f} | jobs {account['jobs']} "
                f"({_counts(account['statuses'])}) | rounds {account['model_rounds']} | "
                f"tools {account['tool_calls']} | wall {account['wall_s'] / 60:.1f} min | "
                f"slowest contact start {'-' if delay is None else f'{delay:.0f} s'}"
            )
            lines.append(
                f"    page writer: {_counts(account['page_writer_calls'])} | "
                f"tool errors: {_counts(account['tool_errors'])} | "
                f"findings {account['findings']} | claims: {_counts(account['claims'])}"
            )
        for job in summary["jobs"]:
            lines.append(
                f"    - {job['account']} {job['subject_type']} {job['job_id']}: {job['status']} "
                f"${float(job['cost_usd'] or 0):.2f}, rounds {job['model_rounds']}, "
                f"tools {job['tool_calls']}, sections: {_counts(job.get('sections') or {})}"
            )
    return "\n".join(lines)


async def _job_ids(conn: Any, workspace: str, ids: Iterable[str]) -> list[UUID]:
    from sqlalchemy import text

    found: list[UUID] = []
    for raw in ids:
        rows = (
            await conn.execute(
                text("""SELECT job_id FROM arv2_research_job WHERE workspace_id=:ws
                AND (job_id=CAST(:id AS uuid) OR run_id=CAST(:id AS uuid))
                ORDER BY created_at, job_id"""),
                {"ws": workspace, "id": raw},
            )
        ).scalars()
        found.extend(r for r in rows if r not in found)
    return found


async def _sections(conn: Any, storage: Any, workspace: str, job_id: UUID) -> dict[str, int]:
    from sqlalchemy import text

    key = (
        await conn.execute(
            text("""SELECT storage_key FROM artifact_reference WHERE workspace_id=:ws
            AND reference_kind=:kind AND reference_id LIKE :prefix
            ORDER BY reference_id DESC LIMIT 1"""),
            {"ws": workspace, "kind": _DOSSIER_KIND, "prefix": f"{job_id}:%"},
        )
    ).scalar_one_or_none()
    if key is None or storage is None:
        return {}
    try:
        saved = json.loads(await storage.get(key))
    except Exception:  # noqa: BLE001 - a missing blob reads as "no sections", not a crash
        return {}
    return {
        str(s.get("section")): len(s.get("findings") or [])
        for s in (saved.get("document") or {}).get("sections") or []
    }


async def load_rows(
    conn: Any, storage: Any, workspace: str, ids: Iterable[str]
) -> list[dict[str, Any]]:
    """One row per job, from the database (and the dossier blob for its sections)."""
    from sqlalchemy import text

    rows: list[dict[str, Any]] = []
    for job_id in await _job_ids(conn, workspace, ids):
        job = (
            (
                await conn.execute(
                    text("""SELECT j.job_id,j.subject_type,j.status,j.failure_code,j.cost_usd,
                j.model_rounds,j.tool_calls,j.created_at,j.started_at,j.finished_at,
                j.subject_entity_id,j.account_entity_id,r.context_id,
                COALESCE(a.canonical_name,a.primary_domain,CAST(a.id AS text)) AS account,
                j.input_refs->>'quality_recipe_version' AS recipe
                FROM arv2_research_job j
                JOIN arv2_research_run r ON r.run_id=j.run_id AND r.workspace_id=j.workspace_id
                LEFT JOIN account_entity a ON a.id=j.account_entity_id
                WHERE j.job_id=:job AND j.workspace_id=:ws"""),
                    {"job": job_id, "ws": workspace},
                )
            )
            .mappings()
            .one()
        )
        writer = (
            await conn.execute(
                text("""SELECT label,count(*) FROM provider_call_ledger
                WHERE workspace_id=:ws AND entity_research_job_id=:job
                  AND label LIKE 'page-writer-%' AND phase='result' GROUP BY label"""),
                {"ws": workspace, "job": job_id},
            )
        ).all()
        subject = job["subject_entity_id"] or job["account_entity_id"]
        claims = (
            await conn.execute(
                text("""SELECT q.conclusion,count(*) FROM claim c
                JOIN claim_quality_current q ON q.claim_id=c.id
                WHERE c.workspace_id=:ws AND c.entity_id=:subject AND q.context_id=:context
                  AND c.superseded_by IS NULL GROUP BY q.conclusion"""),
                {"ws": workspace, "subject": subject, "context": job["context_id"]},
            )
        ).all()
        started, finished = job["started_at"], job["finished_at"]
        rows.append(
            {
                "job_id": str(job_id),
                "account": job["account"],
                "subject_type": job["subject_type"],
                "recipe": job["recipe"],
                "status": job["status"],
                "failure_code": job["failure_code"],
                "cost_usd": float(job["cost_usd"] or 0),
                "model_rounds": job["model_rounds"] or 0,
                "tool_calls": job["tool_calls"] or 0,
                "wall_s": (finished - started).total_seconds() if started and finished else 0.0,
                # A person's job row is created at nomination; it starts when released.
                "start_delay_s": (started - job["created_at"]).total_seconds()
                if job["subject_type"] == "person" and started
                else None,
                "page_writer_calls": {
                    ("contact" if "contact" in label else "account"): n for label, n in writer
                },
                "tool_errors": {},
                "sections": await _sections(conn, storage, workspace, job_id),
                "claims": {str(conclusion): n for conclusion, n in claims},
            }
        )
    return rows


async def _trace_ids(conn: Any, workspace: str, job_id: str) -> list[str]:
    from sqlalchemy import text

    return list(
        (
            await conn.execute(
                text("""SELECT DISTINCT m.langfuse_trace_id FROM agent_model_call m
                JOIN arv2_quality_execution e ON e.execution_id=m.execution_id
                WHERE e.workspace_id=:ws AND e.job_id=CAST(:job AS uuid)
                  AND m.langfuse_trace_id IS NOT NULL"""),
                {"ws": workspace, "job": job_id},
            )
        ).scalars()
    )


def tool_errors(observations: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Failed tool calls by tool name: tool observations at level ERROR."""
    counts: Counter[str] = Counter()
    for item in observations:
        if item.get("type") == "TOOL" and item.get("level") == "ERROR":
            counts[str(item.get("name"))] += 1
    return dict(counts)


def _observations(trace_id: str) -> list[dict[str, Any]]:
    import httpx

    from clue_config import Secrets, load_settings

    settings, secrets = load_settings(), Secrets()
    if secrets.langfuse_public_key is None or secrets.langfuse_secret_key is None:
        raise SystemExit("--langfuse needs CLUE_LANGFUSE_PUBLIC_KEY and CLUE_LANGFUSE_SECRET_KEY")
    auth = (
        secrets.langfuse_public_key.get_secret_value(),
        secrets.langfuse_secret_key.get_secret_value(),
    )
    found: list[dict[str, Any]] = []
    page = 1
    with httpx.Client(base_url=settings.langfuse_host, auth=auth, timeout=60) as client:
        while True:
            for wait in (0, 2, 5, 10, 20, 40):
                time.sleep(wait)
                response = client.get(
                    "/api/public/observations",
                    params={"traceId": trace_id, "page": page, "limit": 100},
                )
                if response.status_code != 429:
                    break
            response.raise_for_status()
            body = response.json()
            found.extend(body.get("data") or [])
            if page >= int((body.get("meta") or {}).get("totalPages") or 1):
                return found
            page += 1


async def _main(args: argparse.Namespace) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from clue_config import load_settings
    from clue_db.engine import database_url
    from clue_storage import storage_from_settings

    engine = create_async_engine(database_url())
    storage = storage_from_settings(load_settings())
    sides: dict[str, dict[str, Any]] = {}
    try:
        async with engine.connect() as conn, conn.begin():
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            for side, ids in (("before", args.before), ("after", args.after)):
                rows = await load_rows(conn, storage, args.workspace, ids)
                if args.langfuse:
                    for row in rows:
                        counts: dict[str, int] = {}
                        for trace in await _trace_ids(conn, args.workspace, row["job_id"]):
                            _add(counts, tool_errors(await asyncio.to_thread(_observations, trace)))
                        row["tool_errors"] = counts
                sides[side] = summarise(rows)
    finally:
        await engine.dispose()
    print(render(sides))
    if args.json:
        Path(args.json).write_text(json.dumps(sides, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--before", nargs="+", required=True, help="job or run ids")
    parser.add_argument("--after", nargs="+", required=True, help="job or run ids")
    parser.add_argument("--langfuse", action="store_true", help="count failed tool calls")
    parser.add_argument("--json", help="also write the full comparison to this file")
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
