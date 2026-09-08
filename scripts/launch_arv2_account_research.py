#!/usr/bin/env python3
"""Launch ARV2 account research for one project (the answer-key runs' entry point).

    set -a; source .env; set +a
    uv run python scripts/launch_arv2_account_research.py \
        --workspace ws_arv2_answer_key --project prj_arv2_answer_key \
        --accounts probook.ai,zafran.io --effort full --committee-cap 5

This is the CLI face of seam 1: it resolves the operator's shorthand (account *domains*, "the
project's confirmed ICP", "the current product set") into the exact pins
:func:`launch_arv2_account_research` demands, then calls it once inside one transaction and prints
the receipt. Every resolution failure is a loud refusal naming what is missing — the launch itself
refuses the same way, and neither invents a default.

The database is the one ``CLUE_DATABASE_URL`` names unless ``--database-url`` overrides it, and the
blob store is this deployment's configured storage unless ``--storage-root`` overrides it (pass the
same root the answer-key loader wrote its documents to).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
from clue_api.arv2.account_research_launch import (
    Arv2LaunchRefused,
    Arv2LaunchRequest,
    enqueue_launched_jobs,
    launch_arv2_account_research,
)
from clue_api.arv2.answer_key_loader import ANSWER_KEY_USER_ID
from clue_api.arv2_wiring import register_arv2_wiring
from clue_api.storage_wiring import build_storage_backend
from clue_config import Settings
from clue_db import db_lifespan
from clue_fleet import DbWorkQueue
from clue_spine import current_project_product_set, get_project
from clue_storage import StorageBackend
from clue_storage.fs import FsStorage

_ACCOUNTS = text(
    "SELECT id, primary_domain FROM account_entity "
    "WHERE workspace_id = :workspace_id AND primary_domain IN :domains"
).bindparams(bindparam("domains", expanding=True))

_CONFIRMED_ICP = text(
    """
    SELECT path, artifact_key, artifact_sha256, version
    FROM brand_knowledge_document
    WHERE workspace_id = :workspace_id AND brand_id = :brand_id
      AND kind = 'icp-definition' AND status = 'confirmed' AND artifact_key IS NOT NULL
    ORDER BY version DESC, path
    LIMIT 1
    """
)


class Refused(SystemExit):
    """A prerequisite the operator has to fix, printed as one line rather than a traceback."""

    def __init__(self, message: str) -> None:
        super().__init__(f"refused: {message}")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="Workspace id that owns the accounts.")
    parser.add_argument("--project", required=True, help="Project id the research runs under.")
    parser.add_argument(
        "--accounts",
        required=True,
        help="Comma-separated account primary domains (e.g. probook.ai,zafran.io).",
    )
    parser.add_argument(
        "--effort",
        default="full",
        choices=("full", "reduced", "cheap-pass"),
        help="Research posture recorded on the run (default: full).",
    )
    parser.add_argument(
        "--committee-cap",
        type=int,
        default=5,
        help="How many committee members one account may resolve (default: 5).",
    )
    parser.add_argument(
        "--directive",
        default="",
        help="Free-text steer recorded on the run and shown to the agent.",
    )
    parser.add_argument(
        "--project-run-id",
        default=None,
        help="Join an existing project run instead of the deterministic per-ICP one.",
    )
    parser.add_argument(
        "--requested-by",
        default=ANSWER_KEY_USER_ID,
        help="The user id recorded as having requested the launch.",
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


async def _resolve_accounts(
    conn: AsyncConnection, *, workspace_id: str, domains: list[str]
) -> list[UUID]:
    rows = (
        (await conn.execute(_ACCOUNTS, {"workspace_id": workspace_id, "domains": domains}))
        .mappings()
        .all()
    )
    by_domain = {str(row["primary_domain"]): UUID(str(row["id"])) for row in rows}
    missing = [domain for domain in domains if domain not in by_domain]
    if missing:
        raise Refused(
            f"workspace {workspace_id!r} has no account with primary domain(s) "
            f"{', '.join(missing)} — import or discover them first"
        )
    # The operator's order is the run's order, so the receipt reads like the command.
    return [by_domain[domain] for domain in domains]


async def _run(args: argparse.Namespace) -> dict[str, object]:
    settings = Settings()
    if not settings.arv2_account_research_enabled:
        raise Refused("CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED is false in this environment")
    register_arv2_wiring()
    storage: StorageBackend = (
        FsStorage(Path(args.storage_root))
        if args.storage_root is not None
        else build_storage_backend(settings)
    )
    domains = [value.strip() for value in str(args.accounts).split(",") if value.strip()]
    if not domains:
        raise Refused("--accounts named no domains")

    async with db_lifespan(args.database_url) as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            project = await get_project(conn, args.project)
            if project is None or project.workspace_id != args.workspace:
                raise Refused(
                    f"project {args.project!r} does not exist in workspace {args.workspace!r}"
                )
            account_ids = await _resolve_accounts(
                conn, workspace_id=args.workspace, domains=domains
            )
            icp = (
                (
                    await conn.execute(
                        _CONFIRMED_ICP,
                        {"workspace_id": args.workspace, "brand_id": str(project.brand_id)},
                    )
                )
                .mappings()
                .first()
            )
            if icp is None:
                raise Refused(
                    f"brand {project.brand_id} has no confirmed icp-definition document to "
                    "launch against"
                )
            product_set = await current_project_product_set(
                conn, workspace_id=args.workspace, project_id=args.project
            )
            if product_set is None:
                raise Refused(
                    f"project {args.project!r} has no confirmed product set; confirm one before "
                    "launching research"
                )
            receipt = await launch_arv2_account_research(
                conn,
                Arv2LaunchRequest(
                    workspace_id=args.workspace,
                    project_id=args.project,
                    account_entity_ids=tuple(account_ids),
                    icp_artifact_key=str(icp["artifact_key"]),
                    icp_artifact_sha256=str(icp["artifact_sha256"]),
                    product_selection_version=product_set.selection_version,
                    requested_by_user_id=args.requested_by,
                    effort=args.effort,
                    committee_cap=args.committee_cap,
                    directive_text=args.directive,
                    project_run_id=(
                        UUID(args.project_run_id) if args.project_run_id is not None else None
                    ),
                ),
                settings=settings,
                storage=storage,
                profile_sha256=arv2_account_profile_sha256(),
            )
            await trans.commit()
        except BaseException:
            await trans.rollback()
            raise
        finally:
            await conn.close()

        # The rows are committed, so every task now offered finds its job row. Offering inside the
        # transaction is the race that silently drops an account: the queue commits its own row
        # first, a worker claims it, finds no job, and finishes the task as done. A failed offer
        # here raises with the job ids in the log — the rows exist, so re-running this command
        # replays the same run and re-offers exactly the jobs whose task is missing.
        enqueued = await enqueue_launched_jobs(DbWorkQueue(), receipt)

    return {
        "run_id": str(receipt.run_id),
        "project_run_id": str(receipt.project_run_id),
        "job_ids": [str(job_id) for job_id in receipt.job_ids],
        "replayed": receipt.replayed,
        "enqueued": enqueued,
        "accounts": {
            domain: str(account_id) for domain, account_id in zip(domains, account_ids, strict=True)
        },
        "icp_document": str(icp["path"]),
        "icp_artifact_sha256": str(icp["artifact_sha256"]),
        "product_selection_version": product_set.selection_version,
        "effort": args.effort,
        "committee_cap": args.committee_cap,
    }


def main() -> None:
    # The launch's own refusals are prerequisites the operator has to fix — a malformed ICP front
    # matter, an unconfirmed document, a digest that moved — so they print as the same one-line
    # refusal this script's own checks do, rather than as a traceback.
    try:
        receipt = asyncio.run(_run(_args()))
    except Arv2LaunchRefused as refused:
        raise Refused(f"{refused.code}: {refused}") from refused
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
