#!/usr/bin/env python3
"""Grade one ARV2 run against the fixed answer keys — accounts, and (R3) the ten people.

    set -a; source .env; set +a
    uv run python scripts/arv2_answer_key_recall.py \
        --database-url "$CLUE_DATABASE_URL" \
        --run-id a0021ecf-8396-5f41-b4aa-eb8de755839a \
        --out .context/arv2-r2-acceptance/recall-before

    # R3: the account run and the on-demand person run, graded together
    uv run python scripts/arv2_answer_key_recall.py --people \
        --run-id <account-run> --run-ids <person-run>,<second-person-run> \
        --out .context/arv2-r3-acceptance/recall

Reads only: it opens one connection, resolves the run's accounts from its job rows, reads the
answer keys (Probook's from the sample file, Zafran's and the person-depth key from the rows the
loader wrote), grades the run's claims against them, writes ``recall-<subject>.md`` plus one
``recall.json`` into ``--out``, and prints one line per subject. It spends nothing — no provider
is touched.

``--run-ids`` is additive to ``--run-id`` because a person is not always researched by the run
that researched their account: the committee fan-out queues person jobs inside the account run,
while an on-demand person launch is its own run. Every read below is over the union.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.answer_key import ZAFRAN_MANIFEST, PersonSpec
from clue_api.arv2.answer_key_recall import (
    RecallReport,
    match_claims,
    people_keys,
    person_report,
    probook_keys,
    zafran_keys,
)
from clue_core import Claim, EntityId, RunId
from clue_db import db_lifespan
from clue_research.claimstore import WorkspaceScope, claims_for_runs

REPO = Path(__file__).resolve().parents[1]
#: The workspace the answer-key loader seeds. Overridable, never guessed from the database.
DEFAULT_WORKSPACE = "ws_arv2_answer_key"
DEFAULT_PROBOOK_KEY = REPO / ".context/arv2-clue-sample-v3/claims.json"
DEFAULT_OUT = REPO / ".context/arv2-r2-acceptance/recall"
#: The account each answer key grades, by the domain the run researched.
ACCOUNT_LABELS = {"probook.ai": "probook", "zafran.io": "zafran"}

#: Only ``account`` jobs name an account to grade: a person job carries its person's account too,
#: and reading it here would grade an account nobody researched (and refuse on the person's
#: account when no answer key exists for it).
_ACCOUNTS = text(
    """
    SELECT DISTINCT job.account_entity_id AS account_entity_id,
                    account.primary_domain AS primary_domain
    FROM arv2_research_job AS job
    JOIN account_entity AS account ON account.id = job.account_entity_id
    WHERE job.run_id IN :run_ids
      AND job.workspace_id = :workspace_id
      AND job.subject_type = 'account'
    ORDER BY account.primary_domain
    """
).bindparams(bindparam("run_ids", expanding=True))

#: The manifest's people, resolved to the contact entities the loader created for them. The join
#: is the folded LinkedIn URL — the contact's strong key, and the only identifier both the manifest
#: and the database agree on.
_CONTACTS = text(
    """
    SELECT id, linkedin_url
    FROM contact_entity
    WHERE workspace_id = :workspace_id AND linkedin_url IN :urls AND merged_into IS NULL
    """
).bindparams(bindparam("urls", expanding=True))


class Refused(SystemExit):
    """A prerequisite the operator has to fix, printed as one line rather than a traceback."""

    def __init__(self, message: str) -> None:
        super().__init__(f"refused: {message}")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="The ARV2 research run to grade.")
    parser.add_argument(
        "--run-ids",
        default=None,
        help="More run ids, comma-separated, graded together with --run-id (people and their "
        "accounts are often researched by different runs).",
    )
    parser.add_argument(
        "--people",
        action="store_true",
        help="Also grade every answer-key person who has claims in these runs, one report each.",
    )
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


def _run_ids(args: argparse.Namespace) -> list[RunId]:
    """``--run-id`` plus ``--run-ids``, in the order given, each id kept once."""
    raw = [str(args.run_id)]
    raw += [part.strip() for part in str(args.run_ids or "").split(",") if part.strip()]
    seen: dict[str, RunId] = {}
    for item in raw:
        try:
            seen.setdefault(item, RunId(UUID(item)))
        except ValueError as error:
            raise Refused(f"{item!r} is not a run id ({error})") from error
    return list(seen.values())


def _slug(person: PersonSpec) -> str:
    """The person's short label — ``nick_fisher`` → ``nick-fisher``, the report's file name."""
    return person.key.replace("_", "-")


def _folded(url: str) -> str:
    """The LinkedIn URL as ``contact_entity.linkedin_url`` stores it (lower-cased, no slash)."""
    return url.strip().rstrip("/").lower()


def _claims_of(claims: Sequence[Claim], entity_id: UUID) -> list[Claim]:
    return [claim for claim in claims if UUID(str(claim.entity_id)) == entity_id]


async def _account_reports(
    conn: AsyncConnection,
    args: argparse.Namespace,
    run_ids: Sequence[RunId],
    claims: Sequence[Claim],
) -> list[RecallReport]:
    """One report per account these runs researched as an account."""
    accounts = (
        (
            await conn.execute(
                _ACCOUNTS,
                {"run_ids": [str(run_id) for run_id in run_ids], "workspace_id": args.workspace},
            )
        )
        .mappings()
        .all()
    )
    if not accounts:
        if args.people:
            # A person-only run has no account job; the people below are the whole measurement.
            return []
        raise Refused(
            f"run {run_ids[0]} has no research jobs in workspace {args.workspace!r} — "
            "check the run id and the workspace"
        )
    unknown = sorted({str(row["primary_domain"]) for row in accounts} - set(ACCOUNT_LABELS))
    if unknown:
        raise Refused(
            f"no answer key exists for {', '.join(unknown)} — this measurement grades "
            f"only {', '.join(sorted(ACCOUNT_LABELS))}"
        )

    probook_key_path = Path(args.probook_key)
    reports: list[RecallReport] = []
    for row in accounts:
        label = ACCOUNT_LABELS[str(row["primary_domain"])]
        keys = (
            probook_keys(probook_key_path)
            if label == "probook"
            else await zafran_keys(conn, workspace_id=args.workspace)
        )
        if not keys:
            raise Refused(f"the {label} answer key is empty — load it into this database first")
        run_claims = _claims_of(claims, UUID(str(row["account_entity_id"])))
        reports.append(match_claims(keys, run_claims, account=label))
    return reports


async def _person_reports(
    conn: AsyncConnection, args: argparse.Namespace, claims: Sequence[Claim]
) -> list[RecallReport]:
    """One report per answer-key person these runs actually researched.

    A person with no claim in these runs was never researched and is not graded — a zero-recall
    report for a job that never ran would read as a failed job. A person the runs *did* research
    but the answer key never covered (the two Zafran committee members outside the ten-person
    roster) is named on stdout rather than graded against nothing.
    """
    by_url = {_folded(person.linkedin_url): person for person in ZAFRAN_MANIFEST.people}
    rows = (
        (await conn.execute(_CONTACTS, {"workspace_id": args.workspace, "urls": sorted(by_url)}))
        .mappings()
        .all()
    )
    if not rows:
        raise Refused(
            f"workspace {args.workspace!r} has none of the answer key's contacts — "
            "run scripts/load_arv2_answer_key.py against this database first"
        )
    keys_by_contact = await people_keys(conn, workspace_id=args.workspace)

    reports: list[RecallReport] = []
    for row in sorted(rows, key=lambda row: _slug(by_url[str(row["linkedin_url"])])):
        person = by_url[str(row["linkedin_url"])]
        contact_id = UUID(str(row["id"]))
        run_claims = _claims_of(claims, contact_id)
        if not run_claims:
            continue
        keys = keys_by_contact.get(EntityId(contact_id))
        if not keys:
            print(
                f"{_slug(person)}: {len(run_claims)} claims written, "
                "but the answer key does not cover this person — not graded"
            )
            continue
        reports.append(person_report(keys, run_claims, person=_slug(person)))
    return reports


async def _reports(args: argparse.Namespace) -> tuple[list[RecallReport], list[RecallReport]]:
    run_ids = _run_ids(args)
    probook_key_path = Path(args.probook_key)
    if not probook_key_path.exists():
        raise Refused(f"no Probook answer key at {probook_key_path}")

    async with db_lifespan(args.database_url) as engine, engine.connect() as conn:
        claims = await claims_for_runs(
            conn, run_ids, scope=WorkspaceScope.for_workspace(args.workspace)
        )
        accounts = await _account_reports(conn, args, run_ids, claims)
        people = await _person_reports(conn, args, claims) if args.people else []
    if not accounts and not people:
        raise Refused(
            f"nothing to grade: no account job and no answer-key person has claims in "
            f"{', '.join(str(run_id) for run_id in run_ids)}"
        )
    return accounts, people


def _line(report: RecallReport) -> str:
    counts = (
        f"(exact {report.exact} / partial {report.partial} / "
        f"field_only {report.field_only} / missing {report.missing} of {report.keys})"
    )
    insight = ""
    if report.subject_kind == "person":
        insight = " insight found" if report.insight_found else " insight not found"
    return f"{report.account} recall {report.recall():.2f} {counts}{insight}"


def main() -> None:
    args = _args()
    accounts, people = asyncio.run(_reports(args))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for report in (*accounts, *people):
        (out / f"recall-{report.account}.md").write_text(report.markdown(), encoding="utf-8")
    (out / "recall.json").write_text(
        json.dumps(
            {
                "run_id": str(args.run_id),
                "run_ids": [str(run_id) for run_id in _run_ids(args)],
                "workspace_id": args.workspace,
                "accounts": [report.as_dict() for report in accounts],
                "people": [report.as_dict() for report in people],
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    for report in (*accounts, *people):
        print(_line(report))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
