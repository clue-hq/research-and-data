#!/usr/bin/env python3
"""Launch ARV2 verified account discovery for one project, or read what a run found.

    set -a; source .env; set +a
    uv run python scripts/launch_arv2_discovery.py \
        --workspace ws_arv2_answer_key --project prj_arv2_answer_key --target 20

    # the human read the counts, the strict pass came up short, and they want the relaxed one
    uv run python scripts/launch_arv2_discovery.py --workspace ws_arv2_answer_key \
        --relaxed-pass 3f1c…-uuid

    # what did it find?
    uv run python scripts/launch_arv2_discovery.py --workspace ws_arv2_answer_key \
        --report 3f1c…-uuid

Everything the run asks comes from the confirmed ICP document version the project pinned — the
long-list query, the criteria the provider filters on, the gates every candidate is verified
against. This command names none of them: it says *which project* and *how many companies*, and
the document is the program (spec §2). A project that has pinned no ICP is a refusal, not a
fallback to somebody else's audience.

``--criteria-gates`` overrides which of the document's hard gates become provider criteria (at most
three, and each must be a key the document defines); leaving it alone uses
``CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS``. Every gate is verified afterwards either way.

``--relaxed-pass`` reopens a **finished** run for the §4 relaxed pass. A short list is information,
never padded behind the human's back: the run lands with its counters, and asking for the wider
search is a decision somebody makes after reading them.

The database is the one ``CLUE_DATABASE_URL`` names unless ``--database-url`` overrides it, and the
blob store is this deployment's configured storage unless ``--storage-root`` overrides it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from clue_api.arv2.answer_key_loader import ANSWER_KEY_USER_ID
from clue_api.arv2.discovery_launch import (
    Arv2DiscoveryRefused,
    Arv2DiscoveryRequest,
    enqueue_discovery_run,
    launch_arv2_discovery,
    request_relaxed_pass,
)
from clue_api.arv2.discovery_store import CandidateRow, list_candidates, read_discovery_run
from clue_api.arv2_wiring import register_arv2_wiring
from clue_api.storage_wiring import build_storage_backend
from clue_config import Settings
from clue_db import db_lifespan
from clue_fleet import DbWorkQueue
from clue_spine import get_project
from clue_storage import StorageBackend
from clue_storage.fs import FsStorage


class Refused(SystemExit):
    """A prerequisite the operator has to fix, printed as one line rather than a traceback."""

    def __init__(self, message: str) -> None:
        super().__init__(f"refused: {message}")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="Workspace id that owns the project.")
    parser.add_argument(
        "--project", default=None, help="Project id to discover for (launch mode only)."
    )
    parser.add_argument(
        "--target", type=int, default=20, help="How many verified companies were asked for."
    )
    parser.add_argument(
        "--strict-count",
        type=int,
        default=None,
        help="How many the provider is asked for. Defaults to CLUE_ARV2_DISCOVERY_STRICT_COUNT.",
    )
    parser.add_argument(
        "--no-relaxed",
        action="store_true",
        help="Do not run the relaxed pass automatically when the strict pass falls short.",
    )
    parser.add_argument(
        "--criteria-gates",
        default=None,
        help=(
            "Comma-separated ICP hard-gate keys to use as provider criteria (at most three). "
            "Defaults to CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS. Every gate is verified either way."
        ),
    )
    parser.add_argument(
        "--relaxed-pass",
        default=None,
        metavar="RUN_ID",
        help="Reopen a finished run for the relaxed pass instead of launching a new one.",
    )
    parser.add_argument(
        "--report",
        default=None,
        metavar="RUN_ID",
        help="Print one run's row and its candidates instead of launching anything.",
    )
    parser.add_argument(
        "--requested-by",
        default=ANSWER_KEY_USER_ID,
        help="The user id recorded as having requested the run.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy async Postgres URL. Defaults to CLUE_DATABASE_URL.",
    )
    parser.add_argument(
        "--storage-root",
        default=None,
        help="Filesystem root holding the ICP artifact. Defaults to the configured storage.",
    )
    return parser.parse_args()


def _gate_letters(verdicts: Sequence[Mapping[str, Any]], legend: tuple[str, ...]) -> str:
    """One candidate's verdicts as letters, in the legend's gate order.

    A row whose gates are not the legend's prints ``key=L`` pairs instead, so a candidate graded on
    a different gate set can never be read as if it were graded on this one.
    """
    keys = tuple(str(verdict.get("gate_key", "")) for verdict in verdicts)
    letters = [str(verdict.get("verdict", "?"))[:1].upper() for verdict in verdicts]
    if keys == legend:
        return "".join(letters)
    return " ".join(f"{key}={letter}" for key, letter in zip(keys, letters, strict=False))


def _print_candidates(candidates: Sequence[CandidateRow]) -> None:
    """The candidate table: what each company is, and how it got there."""
    if not candidates:
        print("no candidates yet")
        return
    legend = tuple(str(verdict.get("gate_key", "")) for verdict in candidates[0].verdicts)
    print(f"gates: {' '.join(legend) if legend else '(none verified yet)'}")
    header = (
        f"{'domain':<34}{'name':<28}{'pass':<9}{'disposition':<22}{'fit':>5}  {'decision':<10}gates"
    )
    print(header)
    print("-" * len(header))
    for candidate in candidates:
        fit = "-" if candidate.fit is None else f"{candidate.fit:.2f}"
        print(
            f"{candidate.domain[:33]:<34}"
            f"{candidate.name[:27]:<28}"
            f"{candidate.pass_:<9}"
            f"{candidate.disposition:<22}"
            f"{fit:>5}  "
            f"{(candidate.decision or '-'):<10}"
            f"{_gate_letters(candidate.verdicts, legend)}"
        )


async def _report(args: argparse.Namespace) -> dict[str, Any]:
    """One run's row and its candidates. Reads only — it starts and changes nothing."""
    run_id = UUID(str(args.report))
    async with db_lifespan(args.database_url) as engine, engine.connect() as conn:
        run = await read_discovery_run(conn, run_id=run_id)
        if run is None or run.workspace_id != args.workspace:
            raise Refused(f"no ARV2 discovery run {run_id} in workspace {args.workspace!r}")
        candidates = await list_candidates(conn, run_id=run_id)
    _print_candidates(candidates)
    return {
        "run_id": str(run.run_id),
        "project_id": run.project_id,
        "status": run.status,
        "icp": f"{run.icp_key}@{run.icp_version}",
        "criteria_gate_keys": list(run.criteria_gate_keys),
        "target_count": run.target_count,
        "strict_count": run.strict_count,
        "relaxed_enabled": run.relaxed_enabled,
        "relaxed_requested": run.relaxed_requested,
        "webset_id": run.webset_id,
        "asked": run.asked,
        "found_strict": run.found_strict,
        "found_relaxed": run.found_relaxed,
        "analyzed": run.analyzed,
        "recall_estimate": run.recall_estimate,
        "candidates": len(candidates),
        "receipt": run.receipt,
    }


async def _relaxed(args: argparse.Namespace) -> dict[str, Any]:
    """Reopen a finished run for the relaxed pass, then offer its task once the row is committed."""
    run_id = UUID(str(args.relaxed_pass))
    async with db_lifespan(args.database_url) as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            receipt = await request_relaxed_pass(conn, workspace_id=args.workspace, run_id=run_id)
            await trans.commit()
        except BaseException:
            await trans.rollback()
            raise
        finally:
            await conn.close()
        enqueued = await enqueue_discovery_run(DbWorkQueue(), receipt)
    return {
        "run_id": str(receipt.run_id),
        "project_run_id": str(receipt.project_run_id),
        "relaxed_pass": True,
        "enqueued": enqueued,
    }


async def _launch(args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    if args.project is None:
        raise Refused("--project names the project whose pinned ICP the search runs against")
    storage: StorageBackend = (
        FsStorage(Path(args.storage_root))
        if args.storage_root is not None
        else build_storage_backend(settings)
    )
    gates = tuple(key.strip() for key in str(args.criteria_gates or "").split(",") if key.strip())

    async with db_lifespan(args.database_url) as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            project = await get_project(conn, args.project)
            if project is None or project.workspace_id != args.workspace:
                raise Refused(
                    f"project {args.project!r} does not exist in workspace {args.workspace!r}"
                )
            receipt = await launch_arv2_discovery(
                conn,
                Arv2DiscoveryRequest(
                    workspace_id=args.workspace,
                    project_id=args.project,
                    requested_by_user_id=args.requested_by,
                    target_count=args.target,
                    strict_count=args.strict_count,
                    relaxed_enabled=False if args.no_relaxed else None,
                    criteria_gate_keys=gates,
                ),
                settings=settings,
                storage=storage,
            )
            await trans.commit()
        except BaseException:
            await trans.rollback()
            raise
        finally:
            await conn.close()

        # The row is committed, so the task now offered finds its run. Offering inside the
        # transaction is the race that silently drops a run: the queue commits its own row first, a
        # worker claims it, finds no run, and finishes the task as done. Re-running this command
        # replays the same run and re-offers the task if it went missing.
        enqueued = await enqueue_discovery_run(DbWorkQueue(), receipt)

    return {
        "run_id": str(receipt.run_id),
        "project_run_id": str(receipt.project_run_id),
        "replayed": receipt.replayed,
        "enqueued": enqueued,
        "target_count": args.target,
        "criteria_gate_keys": list(gates),
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings()
    register_arv2_wiring()
    if args.report is not None:
        # A read needs no lane flag: an operator must be able to see what a run found on a
        # deployment where the lane has since been switched off.
        return await _report(args)
    if not settings.arv2_discovery_enabled:
        raise Refused("CLUE_ARV2_DISCOVERY_ENABLED is false in this environment")
    if args.relaxed_pass is not None:
        return await _relaxed(args)
    return await _launch(args, settings)


def main() -> None:
    # The launch's own refusals are prerequisites the operator has to fix — a project with no
    # pinned ICP, a criteria gate the document does not define, a run that has not finished — so
    # they print as the same one-line refusal this script's own checks do, not as a traceback.
    try:
        receipt = asyncio.run(_run(_args()))
    except Arv2DiscoveryRefused as refused:
        raise Refused(f"{refused.code}: {refused}") from refused
    print(json.dumps(receipt, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
