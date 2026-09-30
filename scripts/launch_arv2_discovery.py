#!/usr/bin/env python3
"""Launch ARV2 verified account discovery for one project, or read what a run found.

    set -a; source .env; set +a
    uv run python scripts/launch_arv2_discovery.py \
        --workspace ws_arv2_answer_key --project prj_arv2_answer_key --target 20 \
        --brief brief.json

    # replay (or re-offer) the run a key already made, instead of starting a new one
    uv run python scripts/launch_arv2_discovery.py \
        --workspace ws_arv2_answer_key --project prj_arv2_answer_key --target 20 \
        --brief brief.json --request-key k1

    # what did it find?
    uv run python scripts/launch_arv2_discovery.py --workspace ws_arv2_answer_key \
        --report 3f1c…-uuid

The search the run makes is the brief in ``--brief``: a JSON file holding exactly what the Head of
ABM writes when it launches discovery from a project chat (spec 2026-09-30 §3) — ``source``
(``websets`` or ``search``), the ``query``, one to five ``criteria``, and two to eight ``gates``,
each a ``key``, ``rule``, ``test`` and ``role`` (``must``, ``must_not`` or ``prefer``). It is
validated as ``DiscoveryBrief2``; a launch without one, or with one that does not validate, is a
refusal. The project must still have pinned a confirmed ICP document: the run records that pin, and
a project that has pinned no ICP is a refusal, not a fallback to somebody else's audience.

Every launch is a new run (founder ruling 2026-09-28: asking for more is a new discovery, which
skips every company this project's earlier discoveries found). ``--request-key`` names the ask:
repeating a key replays that run and re-offers its task if the offer went missing; leaving it out
makes a fresh key, so the command starts a new run. A run that is short tops up with the same
brief, up to ``CLUE_ARV2_DISCOVERY_MAX_TOPUPS`` more searches.

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
from uuid import UUID, uuid4

from pydantic import ValidationError

from clue_api.arv2.answer_key_loader import ANSWER_KEY_USER_ID
from clue_api.arv2.discovery_launch import (
    Arv2DiscoveryRefused,
    Arv2DiscoveryRequest,
    enqueue_discovery_run,
    launch_arv2_discovery,
)
from clue_api.arv2.discovery_request import DiscoveryBrief2
from clue_api.arv2.discovery_store import (
    CandidateRow,
    list_candidates,
    list_searches,
    read_discovery_run,
)
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
        "--request-key",
        default=None,
        help=(
            "Names this ask. Repeat a key to replay its run; leave it out to start a new run "
            "(a fresh key is made)."
        ),
    )
    parser.add_argument(
        "--brief",
        default=None,
        type=Path,
        metavar="PATH",
        help=(
            "JSON file holding the discovery brief (source, query, criteria, gates with roles), "
            "validated as DiscoveryBrief2. Required to launch."
        ),
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


def _read_brief(path: Path | None) -> DiscoveryBrief2:
    """The brief file, validated — or a one-line refusal naming what is wrong with it."""
    if path is None:
        raise Refused(
            "--brief names the JSON file holding the discovery brief (source, query, criteria, "
            "gates); a launch has no search without one"
        )
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise Refused(f"cannot read the brief file {str(path)!r}: {error}") from error
    try:
        return DiscoveryBrief2.model_validate_json(raw)
    except ValidationError as bad:
        raise Refused(f"brief_invalid: {path} is not a valid discovery brief: {bad}") from bad


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
        searches = await list_searches(conn, run_id=run_id)
    _print_candidates(candidates)
    return {
        "run_id": str(run.run_id),
        "project_id": run.project_id,
        "status": run.status,
        "source": run.source,
        "end_reason": run.end_reason,
        "icp": f"{run.icp_key}@{run.icp_version}",
        "criteria_gate_keys": list(run.criteria_gate_keys),
        "target_count": run.target_count,
        "relaxed_enabled": run.relaxed_enabled,
        "searches": [
            {
                "ordinal": search.ordinal,
                "kind": search.kind,
                "asked": search.asked,
                "found": search.found,
                "webset_id": search.webset_id,
                "excluded_websets": len(search.exclude_webset_ids),
                "finished": search.finished_at is not None,
            }
            for search in searches
        ],
        "asked": run.asked,
        "found_strict": run.found_strict,
        "found_relaxed": run.found_relaxed,
        "analyzed": run.analyzed,
        "recall_estimate": run.recall_estimate,
        "candidates": len(candidates),
        "receipt": run.receipt,
    }


async def _launch(args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    if args.project is None:
        raise Refused("--project names the project whose pinned ICP the search runs against")
    brief = _read_brief(args.brief)
    storage: StorageBackend = (
        FsStorage(Path(args.storage_root))
        if args.storage_root is not None
        else build_storage_backend(settings)
    )
    request_key = args.request_key or f"cli:{uuid4()}"

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
                    request_key=request_key,
                    target_count=args.target,
                    brief=brief,
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
        # with the same --request-key replays the same run and re-offers the task if it went
        # missing.
        enqueued = await enqueue_discovery_run(DbWorkQueue(), receipt)

    return {
        "run_id": str(receipt.run_id),
        "project_run_id": str(receipt.project_run_id),
        "replayed": receipt.replayed,
        "request_key": request_key,
        "enqueued": enqueued,
        "target_count": args.target,
        "source": brief.source,
        "gates": {gate.key: gate.role for gate in brief.gates},
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
    return await _launch(args, settings)


def main() -> None:
    # The launch's own refusals are prerequisites the operator has to fix — a project with no
    # pinned ICP, a digest that moved under the pin — so
    # they print as the same one-line refusal this script's own checks do, not as a traceback.
    try:
        receipt = asyncio.run(_run(_args()))
    except Arv2DiscoveryRefused as refused:
        raise Refused(f"{refused.code}: {refused}") from refused
    print(json.dumps(receipt, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
