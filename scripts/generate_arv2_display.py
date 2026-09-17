#!/usr/bin/env python3
"""Write the ARV2 display pages of one account (or one of its contacts) with the real model.

    uv run python scripts/generate_arv2_display.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue \
        --account zafran.io

    uv run python scripts/generate_arv2_display.py \
        --database-url ... --account zafran.io --contact "Nick Fisher"

--database-url is required so this command can never fall through to whatever CLUE_DATABASE_URL
points at (same rule as scripts/load_arv2_answer_key.py). This command SPENDS MONEY: every
section it decides is missing is one OpenRouter call. It writes nothing when every section is
already stored — pass --force to rewrite a page, or --regenerate-stale to rewrite only the
sections a newer claim has moved underneath. --dry-run runs the whole thing in one transaction,
prints the report, and rolls the page back; the calls still happen, are still paid for, and their
rows on provider_call_ledger are kept (they commit on their own).

Only JSON goes to stdout; progress goes to stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.display.gather import SubjectKind
from clue_api.arv2.display.page import PageResult, default_runner_factory, ensure_page
from clue_api.arv2.display.recipes import Page
from clue_api.arv2.errors import Arv2Error
from clue_api.storage_wiring import build_storage_backend
from clue_config import Secrets, Settings
from clue_db import db_lifespan, transaction

#: The workspace the answer-key loader seeds. Overridable, never guessed from the database.
DEFAULT_WORKSPACE = "ws_arv2_answer_key"

_ACCOUNT_SQL = text(
    """
    SELECT id FROM account_entity
    WHERE workspace_id = :workspace_id AND primary_domain = :domain
    """
)

_CONTACT_SQL = text(
    """
    SELECT id FROM contact_entity
    WHERE workspace_id = :workspace_id
      AND account_entity_id = :account_id
      AND full_name = :full_name
    """
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        required=True,
        help="SQLAlchemy async Postgres URL. Required — this command writes, so it must never "
        "fall through to CLUE_DATABASE_URL.",
    )
    parser.add_argument(
        "--workspace-id",
        default=DEFAULT_WORKSPACE,
        help=f"The workspace the account belongs to (default: {DEFAULT_WORKSPACE}).",
    )
    parser.add_argument(
        "--account",
        required=True,
        help="The account's primary domain, e.g. zafran.io.",
    )
    parser.add_argument(
        "--contact",
        default=None,
        help='A contact of that account, by full name, e.g. "Nick Fisher". Selects the contact '
        "page.",
    )
    parser.add_argument(
        "--page",
        choices=["overview", "insights", "contact", "all"],
        default="all",
        help="Which page to write. 'all' means overview + insights for an account, and the "
        "contact page when --contact is given (default: all).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Retire every live block of the page and rewrite all of it.",
    )
    parser.add_argument(
        "--regenerate-stale",
        action="store_true",
        help="Also rewrite the sections a newer claim (or a new prompt/recipe version) has made "
        "stale. Without it, a stale section is served as it was written.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run everything in one transaction, print the report, and roll it back. The model "
        "calls still happen and are still paid for.",
    )
    return parser.parse_args()


def _pages(args: argparse.Namespace) -> list[Page]:
    """Which pages this invocation writes, and about whom."""
    if args.page == "all":
        return ["contact"] if args.contact else ["overview", "insights"]
    page = cast(Page, args.page)
    if page == "contact" and not args.contact:
        raise SystemExit('--page contact needs --contact "<full name>"')
    if page != "contact" and args.contact:
        raise SystemExit(f"--page {page} is an account page; drop --contact")
    return [page]


async def _resolve(conn: AsyncConnection, args: argparse.Namespace) -> tuple[str, str | None]:
    """``(account id, contact id)`` for the names given, or a loud exit."""
    account = (
        await conn.execute(
            _ACCOUNT_SQL, {"workspace_id": args.workspace_id, "domain": args.account}
        )
    ).scalar_one_or_none()
    if account is None:
        raise SystemExit(f"no account with primary_domain {args.account!r} in {args.workspace_id}")
    if args.contact is None:
        return str(account), None
    contact = (
        await conn.execute(
            _CONTACT_SQL,
            {
                "workspace_id": args.workspace_id,
                "account_id": uuid.UUID(str(account)),
                "full_name": args.contact,
            },
        )
    ).scalar_one_or_none()
    if contact is None:
        raise SystemExit(f"no contact named {args.contact!r} under {args.account}")
    return str(account), str(contact)


def _report(result: PageResult) -> dict[str, Any]:
    """One page's line of the JSON report — the block, what changed, and what it cost."""
    return {
        "display_block": result.display_block,
        "generated": list(result.generated),
        "regenerated": list(result.regenerated),
        "skipped_empty": list(result.skipped_empty),
        "stale_served": list(result.stale_served),
        "failed": list(result.failed),
        "cost_usd": str(result.cost_usd),
        "checks": result.checks,
        "evidence_count": len(result.evidence),
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings()
    # Built before the database is touched: a missing key must fail before anything is written.
    runner_factory = default_runner_factory(settings, Secrets())
    pages = _pages(args)

    report: dict[str, Any] = {}
    total = Decimal(0)
    async with db_lifespan(args.database_url) as engine:
        # Slice 1b: the pages' provider spend lands on provider_call_ledger in its own
        # transactions (D2) — a --dry-run page rolls back, its spend rows do not.
        artifacts = DurableAgentArtifactStore(
            storage=build_storage_backend(settings), conn_factory=transaction
        )
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            account_id, contact_id = await _resolve(conn, args)
            for page in pages:
                print(f"writing {page}…", file=sys.stderr)
                is_contact_page = page == "contact"
                subject_kind: SubjectKind = "contact" if is_contact_page else "account"
                subject_id = contact_id if is_contact_page else account_id
                if subject_id is None:  # unreachable: _pages() demands --contact first
                    raise SystemExit("the contact page needs --contact")
                result = await ensure_page(
                    conn,
                    workspace_id=args.workspace_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    page=page,
                    settings=settings,
                    runner_factory=runner_factory,
                    artifacts=artifacts,
                    spend_conn_factory=transaction,
                    force=args.force,
                    regenerate_stale=args.regenerate_stale,
                )
                report[page] = _report(result)
                total += result.cost_usd
            if args.dry_run:
                await trans.rollback()
            else:
                await trans.commit()
        except BaseException:
            await trans.rollback()
            raise
        finally:
            await conn.close()
    return {**report, "total_cost_usd": str(total)}


def main() -> None:
    try:
        report = asyncio.run(_run(_args()))
    except Arv2Error as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
