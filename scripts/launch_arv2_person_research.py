#!/usr/bin/env python3
"""Launch ARV2 person research for named contacts of one project.

    set -a; source .env; set +a
    uv run python scripts/launch_arv2_person_research.py \
        --workspace ws_arv2_answer_key --project prj_arv2_answer_key \
        --contacts https://www.linkedin.com/in/dana-reyes,3f1c…-uuid \
        --directive "open with the podcast"

The on-demand half of the person lane: the committee step launches a member the moment an account
job confirms them, and this is how a human launches anybody else — a contact they picked out of the
account, or a member whose job needs re-running. It researches contacts that already exist and
**creates nobody**: resolving a person is an identity act with its own evidence, so a name this
workspace does not hold is a refusal rather than a new row.

``--contacts`` takes either form, mixed freely: a contact id, or the person's LinkedIn URL (folded
the way the entity layer folds it, so the trailing slash and the capitals a real page carries do
not matter). Every unresolvable one is named in a single refusal.

``--persona`` is the committee seat each named person is given when they hold none yet (default
``user``). Without a seat a person is researched and then invisible on their own account's contact
list, which reads the committee off exactly those claims.

The database is the one ``CLUE_DATABASE_URL`` names unless ``--database-url`` overrides it, and the
blob store is this deployment's configured storage unless ``--storage-root`` overrides it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_catalog import arv2_person_profile_sha256
from clue_api.arv2.account_research_launch import (
    Arv2LaunchRefused,
    Arv2PersonLaunchRequest,
    enqueue_launched_jobs,
    launch_arv2_person_research,
)
from clue_api.arv2.account_research_store import find_contact_by_linkedin
from clue_api.arv2.answer_key_loader import ANSWER_KEY_USER_ID
from clue_api.arv2_wiring import register_arv2_wiring
from clue_api.storage_wiring import build_storage_backend
from clue_config import Settings
from clue_core import Persona
from clue_db import db_lifespan
from clue_fleet import DbWorkQueue
from clue_spine import get_project
from clue_storage import StorageBackend
from clue_storage.fs import FsStorage

_CONTACT_BY_ID = text(
    "SELECT id FROM contact_entity "
    "WHERE workspace_id = :workspace_id AND id = :contact_id AND merged_into IS NULL"
)

_CONTACT_NAME = text("SELECT full_name FROM contact_entity WHERE id = :contact_id")


class Refused(SystemExit):
    """A prerequisite the operator has to fix, printed as one line rather than a traceback."""

    def __init__(self, message: str) -> None:
        super().__init__(f"refused: {message}")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="Workspace id that owns the contacts.")
    parser.add_argument("--project", required=True, help="Project id the research runs under.")
    parser.add_argument(
        "--contacts",
        required=True,
        help="Comma-separated contact ids or LinkedIn profile URLs, mixed freely.",
    )
    parser.add_argument(
        "--directive",
        default="",
        help="Free-text steer recorded on the run and shown to the agent.",
    )
    parser.add_argument(
        "--persona",
        default=Persona.USER.value,
        choices=[persona.value for persona in Persona],
        help=(
            "The committee seat every named person is given if they do not already hold one. "
            "It is what puts them on their account's contact list."
        ),
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


async def _resolve_contacts(
    conn: AsyncConnection, *, workspace_id: str, tokens: list[str]
) -> list[UUID]:
    """Turn the operator's shorthand into contact ids, naming every token that resolved to none."""
    resolved: list[UUID] = []
    missing: list[str] = []
    for token in tokens:
        contact_id: UUID | None = None
        try:
            candidate = UUID(token)
        except ValueError:
            candidate = None
        if candidate is not None:
            row = (
                await conn.execute(
                    _CONTACT_BY_ID, {"workspace_id": workspace_id, "contact_id": candidate}
                )
            ).first()
            contact_id = candidate if row is not None else None
        else:
            contact_id = await find_contact_by_linkedin(
                conn, workspace_id=workspace_id, linkedin_url=token
            )
        if contact_id is None:
            missing.append(token)
            continue
        resolved.append(contact_id)
    if missing:
        raise Refused(
            f"workspace {workspace_id!r} holds no contact for {', '.join(missing)} — research the "
            "account first, or name a contact it already resolved"
        )
    # The operator's order is the run's order, so the receipt reads like the command. A token named
    # twice is one person, and one job: the job id is derived from the contact.
    return list(dict.fromkeys(resolved))


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
    tokens = [value.strip() for value in str(args.contacts).split(",") if value.strip()]
    if not tokens:
        raise Refused("--contacts named nobody")

    async with db_lifespan(args.database_url) as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            project = await get_project(conn, args.project)
            if project is None or project.workspace_id != args.workspace:
                raise Refused(
                    f"project {args.project!r} does not exist in workspace {args.workspace!r}"
                )
            contact_ids = await _resolve_contacts(conn, workspace_id=args.workspace, tokens=tokens)
            names: dict[str, str | None] = {}
            for contact_id in contact_ids:
                found = await conn.execute(_CONTACT_NAME, {"contact_id": contact_id})
                names[str(contact_id)] = found.scalar_one_or_none()
            receipt = await launch_arv2_person_research(
                conn,
                Arv2PersonLaunchRequest(
                    workspace_id=args.workspace,
                    project_id=args.project,
                    contact_entity_ids=tuple(contact_ids),
                    requested_by_user_id=args.requested_by,
                    directive_text=args.directive,
                    persona=Persona(args.persona),
                    project_run_id=(
                        UUID(args.project_run_id) if args.project_run_id is not None else None
                    ),
                ),
                settings=settings,
                storage=storage,
                profile_sha256=arv2_person_profile_sha256(),
            )
            await trans.commit()
        except BaseException:
            await trans.rollback()
            raise
        finally:
            await conn.close()

        # The rows are committed, so every task now offered finds its job row. Offering inside the
        # transaction is the race that silently drops a person: the queue commits its own row
        # first, a worker claims it, finds no job, and finishes the task as done. Re-running this
        # command replays the same run and re-offers exactly the jobs whose task is missing.
        enqueued = await enqueue_launched_jobs(DbWorkQueue(), receipt)

    return {
        "run_id": str(receipt.run_id),
        "project_run_id": str(receipt.project_run_id),
        "job_ids": [str(job_id) for job_id in receipt.job_ids],
        "replayed": receipt.replayed,
        "enqueued": enqueued,
        "people": names,
        "persona": args.persona,
        "directive": args.directive,
    }


def main() -> None:
    # The launch's own refusals are prerequisites the operator has to fix — an unknown contact, a
    # brand with no confirmed ICP, a project with no confirmed product set — so they print as the
    # same one-line refusal this script's own checks do, rather than as a traceback.
    try:
        receipt = asyncio.run(_run(_args()))
    except Arv2LaunchRefused as refused:
        raise Refused(f"{refused.code}: {refused}") from refused
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
