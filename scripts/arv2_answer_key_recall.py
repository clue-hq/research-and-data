#!/usr/bin/env python3
"""Grade one ARV2 account-research run against the two fixed answer keys.

    set -a; source .env; set +a
    uv run python scripts/arv2_answer_key_recall.py \
        --database-url "$CLUE_DATABASE_URL" \
        --run-id a0021ecf-8396-5f41-b4aa-eb8de755839a \
        --out .context/arv2-r2-acceptance/recall-before

Reads only: it opens one connection, resolves the run's accounts from its job rows, reads the
answer keys (Probook's from the sample file, Zafran's from the rows the loader wrote), grades the
run's claims against them, writes ``recall-<account>.md`` plus one ``recall.json`` into ``--out``,
and prints the two recall lines. It spends nothing — no provider is touched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from clue_api.arv2.answer_key_recall import RecallReport, match_claims, probook_keys, zafran_keys
from clue_core import RunId
from clue_db import db_lifespan
from clue_research.claimstore import WorkspaceScope, claims_for_runs

REPO = Path(__file__).resolve().parents[1]
#: The workspace the answer-key loader seeds. Overridable, never guessed from the database.
DEFAULT_WORKSPACE = "ws_arv2_answer_key"
DEFAULT_PROBOOK_KEY = REPO / ".context/arv2-clue-sample-v3/claims.json"
DEFAULT_OUT = REPO / ".context/arv2-r2-acceptance/recall"
#: The account each answer key grades, by the domain the run researched.
ACCOUNT_LABELS = {"probook.ai": "probook", "zafran.io": "zafran"}

_ACCOUNTS = text(
    """
    SELECT job.account_entity_id AS account_entity_id, account.primary_domain AS primary_domain
    FROM arv2_research_job AS job
    JOIN account_entity AS account ON account.id = job.account_entity_id
    WHERE job.run_id = :run_id AND job.workspace_id = :workspace_id
    ORDER BY account.primary_domain
    """
)


class Refused(SystemExit):
    """A prerequisite the operator has to fix, printed as one line rather than a traceback."""

    def __init__(self, message: str) -> None:
        super().__init__(f"refused: {message}")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="The ARV2 research run to grade.")
    parser.add_argument(
        "--workspace",
        default=DEFAULT_WORKSPACE,
        help=f"Workspace that owns the run and the answer key (default: {DEFAULT_WORKSPACE}).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy async Postgres URL. Defaults to CLUE_DATABASE_URL.",
    )
    parser.add_argument(
        "--probook-key",
        default=str(DEFAULT_PROBOOK_KEY),
        help="The Probook answer-key claims file.",
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT), help="Directory the reports are written to."
    )
    return parser.parse_args()


async def _reports(args: argparse.Namespace) -> list[RecallReport]:
    run_id = RunId(UUID(str(args.run_id)))
    probook_key_path = Path(args.probook_key)
    if not probook_key_path.exists():
        raise Refused(f"no Probook answer key at {probook_key_path}")

    async with db_lifespan(args.database_url) as engine, engine.connect() as conn:
        accounts = (
            (await conn.execute(_ACCOUNTS, {"run_id": str(run_id), "workspace_id": args.workspace}))
            .mappings()
            .all()
        )
        if not accounts:
            raise Refused(
                f"run {run_id} has no research jobs in workspace {args.workspace!r} — "
                "check the run id and the workspace"
            )
        unknown = sorted({str(row["primary_domain"]) for row in accounts} - set(ACCOUNT_LABELS))
        if unknown:
            raise Refused(
                f"no answer key exists for {', '.join(unknown)} — this measurement grades "
                f"only {', '.join(sorted(ACCOUNT_LABELS))}"
            )

        claims = await claims_for_runs(
            conn, [run_id], scope=WorkspaceScope.for_workspace(args.workspace)
        )
        reports: list[RecallReport] = []
        for row in accounts:
            domain = str(row["primary_domain"])
            label = ACCOUNT_LABELS[domain]
            keys = (
                probook_keys(probook_key_path)
                if label == "probook"
                else await zafran_keys(conn, workspace_id=args.workspace)
            )
            if not keys:
                raise Refused(f"the {label} answer key is empty — load it into this database first")
            account_id = UUID(str(row["account_entity_id"]))
            run_claims = [claim for claim in claims if UUID(str(claim.entity_id)) == account_id]
            reports.append(match_claims(keys, run_claims, account=label))
    return reports


def main() -> None:
    args = _args()
    reports = asyncio.run(_reports(args))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for report in reports:
        (out / f"recall-{report.account}.md").write_text(report.markdown(), encoding="utf-8")
    (out / "recall.json").write_text(
        json.dumps(
            {
                "run_id": str(args.run_id),
                "workspace_id": args.workspace,
                "accounts": [report.as_dict() for report in reports],
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    for report in reports:
        print(
            f"{report.account} recall {report.recall():.2f} "
            f"(exact {report.exact} / partial {report.partial} / "
            f"field_only {report.field_only} / missing {report.missing} of {report.keys})"
        )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
