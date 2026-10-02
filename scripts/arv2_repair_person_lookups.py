#!/usr/bin/env python3
"""Re-run the deterministic person lookup for ARV2 person jobs that already finished.

    set -a; source .env; set +a
    uv run python scripts/arv2_repair_person_lookups.py \
        --job-ids 2d3f74ca-6b0e-5bf1-a550-53927af26fab,7c1e… --dry-run

The first live person jobs refused ``lookup_person`` with ``subject_lock_failed`` whenever the
provider record spelled the employer's name two ways ("Cogent" on the position, "Cogent Security"
on the company block): the domain came back unstated and an unstated employer was read as a
contradiction. Those people finished with no provider claims and no email, even though their
LinkedIn URL matched the one the committee confirmed exactly.

This is the repair. For each named job it rebuilds the job's own scope exactly as the driver does
(``person_scope_for``), calls the same two AI Ark endpoints ``lookup_person`` calls, and writes the
same deterministic claims under the same scope — through the same lenient writer and the same
compliance floor, with the ledger rows stamped to the job that paid for them. Every claim it writes
carries ``repaired: "lookup_person"``, and ``employer_unverified`` when the record still cannot
state the employer.

**It never calls a model.** The clients object it composes offers AI Ark and nothing else, so the
structuring, media and search paths are not merely unused — they are absent.

It is **idempotent by default**: a job that already carries the lookup's own ``ai_ark:person``
claims is reported ``skipped_already_looked_up`` and costs nothing, because re-running a lookup
that worked buys the same record a second time and leaves duplicate rows behind. ``--force``
overrides that. ``--persona`` additionally seats each job's person on their account's committee
when they hold no seat yet — the write a person launched on demand never got — which is how the
people who have already been researched become visible on their account's contact list.

``--dry-run`` reads the rows and prints what each job would be asked for — including whether each
person already holds a seat — without a provider call and without a write. ``CLUE_AI_ARK_API_KEY``
is demanded only where a lookup will actually run, so a ``--persona`` pass over people whose lookup
already succeeded (every job ``skipped_already_looked_up``, the seat the only write) needs no
provider key at all. The database is the one ``CLUE_DATABASE_URL`` names unless ``--database-url``
overrides it, and the blob store is this deployment's configured storage unless ``--storage-root``
overrides it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2 import account_research_store as store
from clue_api.arv2.account_research_claims import (
    PERSONA_FIELD,
    ai_ark_person_claims,
    email_export_claim,
)
from clue_api.arv2.account_research_driver import ContactMissing, person_scope_for
from clue_api.arv2.account_research_launch import seat_person_on_committee
from clue_api.arv2.account_research_tools import (
    ProviderClients,
    ToolRuntime,
    WriteFailure,
    fold_identity,
    marked,
)
from clue_api.arv2.ai_ark_client import AiArkClient
from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.gemini_media_client import MediaBudget
from clue_api.arv2.provider_ledger import ArtifactSink
from clue_api.arv2_wiring import register_arv2_wiring
from clue_api.storage_wiring import build_storage_backend
from clue_config import Secrets, Settings
from clue_core import Persona
from clue_db import db_lifespan, transaction
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_storage import StorageBackend
from clue_storage.fs import FsStorage

#: How many candidates the name-scoped search asks for — the same size ``lookup_person`` uses, so
#: the repair sees exactly the candidate set the live call saw.
_CANDIDATES = 3

#: The source key every claim of a successful person lookup carries. A job that already holds one
#: of these — written by the lookup itself, not by a previous repair — was never broken.
_LOOKUP_SOURCE_KEY = "ai_ark:person"


class Refused(SystemExit):
    """A prerequisite the operator has to fix: one line on stderr, exit 2, never a traceback."""

    def __init__(self, message: str) -> None:
        print(f"refused: {message}", file=sys.stderr)
        super().__init__(2)


class _AiArkOnly:
    """The provider surface this repair is allowed to reach: AI Ark, and nothing else.

    The three other clients raise rather than being composed. "It never calls a model" is then a
    property of the object the runtime holds, not a promise in a docstring.
    """

    def __init__(self, *, settings: Settings, api_key: SecretStr) -> None:
        self._settings = settings
        self._api_key = api_key

    def ai_ark(self, caller: ProviderCaller) -> AiArkClient:
        return AiArkClient(caller, self._api_key, min_gap_s=self._settings.arv2_ai_ark_min_gap_s)

    def exa(self, caller: ProviderCaller) -> Any:
        raise NotImplementedError("the lookup repair searches nothing")

    def media(self, caller: ProviderCaller, ledger: Any) -> Any:
        raise NotImplementedError("the lookup repair reads no media")

    def structuring(self, caller: ProviderCaller) -> Any:
        raise NotImplementedError("the lookup repair calls no model")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--job-ids",
        required=True,
        help="Comma-separated person job ids to repair, in the order they should run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read the rows and print the plan; spend nothing and write nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Look the person up again even when the job already holds the lookup's own claims. "
            "Without it such a job is skipped, because re-running it buys the same record twice."
        ),
    )
    parser.add_argument(
        "--persona",
        default=None,
        choices=[persona.value for persona in Persona],
        help=(
            "Seat every named job's person on their account's committee at this persona when "
            "they hold no seat yet. Without a seat a finished person is invisible on their own "
            "account's contact list, which is read from exactly those claims."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy async Postgres URL. Defaults to CLUE_DATABASE_URL.",
    )
    parser.add_argument(
        "--storage-root",
        default=None,
        help="Filesystem root for the raw-body artifacts. Defaults to the configured storage.",
    )
    return parser.parse_args()


def _job_ids(raw: str) -> list[UUID]:
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if not tokens:
        raise Refused("--job-ids named nothing")
    ids: list[UUID] = []
    for token in tokens:
        try:
            ids.append(UUID(token))
        except ValueError as error:
            raise Refused(f"{token!r} is not a job id") from error
    return list(dict.fromkeys(ids))


async def _read_rows(job_ids: list[UUID]) -> list[tuple[store.JobRow, store.RunRow]]:
    """Every named job with its run, refusing the whole command on the first row it cannot repair.

    The refusals are all-or-nothing on purpose: a job this repair should not touch (an account job,
    a job that never ran) is an operator mistake about *which* ids to pass, and finding out after
    three people have already been paid for is the wrong order.
    """
    rows: list[tuple[store.JobRow, store.RunRow]] = []
    async with transaction() as conn:
        for job_id in job_ids:
            job = await store.read_job(conn, job_id=job_id)
            if job is None:
                raise Refused(f"job {job_id} has no row")
            if job.subject_type != "person":
                raise Refused(
                    f"job {job_id} researches an {job.subject_type}; this repair re-runs the "
                    "person lookup only"
                )
            if job.status == "not_started":
                raise Refused(
                    f"job {job_id} has not run yet — let the fleet drive it rather than repairing "
                    "a lookup it has not made"
                )
            run = await store.read_run(conn, run_id=job.run_id)
            if run is None:
                raise Refused(f"run row {job.run_id} is missing for job {job_id}")
            rows.append((job, run))
    return rows


async def _repair_one(
    *,
    job: store.JobRow,
    run: store.RunRow,
    settings: Settings,
    artifacts: ArtifactSink,
    api_key: SecretStr | None,
    dry_run: bool,
    force: bool,
    persona: Persona | None,
) -> dict[str, Any]:
    """One job: rebuild its scope, seat the person if asked, re-run the two calls, write.

    Two things are decided before a single provider call is made, because both cost money to get
    wrong. **The seat** (``--persona``) is written whether or not the lookup runs: a person whose
    lookup already succeeded still needs a committee claim to appear on their account's contact
    list, and that is a write this repair can make without buying anything. **The skip** is the
    idempotency this script did not have on its first live run, where the two people whose lookup
    had actually succeeded were looked up (and billed) a second time and ended up with duplicate
    rows. A job that already carries the lookup's own claims — ``ai_ark:person`` written by
    ``lookup_person`` rather than by a previous repair — was never broken, so it is skipped unless
    ``--force`` says otherwise.
    """
    writer = LenientClaimWriter(lenient=settings.claim_write_lenient)
    async with transaction() as conn:
        # The job's own pins (workspace, project, run, account, contact) come off the rows. The
        # prompt half of the composition is left at its defaults on purpose: this repair runs no
        # model, so an ICP body and a persona map would be context nobody reads.
        try:
            scope = await person_scope_for(conn, job=job, run=run, today=datetime.now(UTC).date())
        except ContactMissing as error:
            # Every other prerequisite this script cannot satisfy is one line and exit 2; a job
            # naming a contact row that is not there is the same kind of operator fact.
            raise Refused(str(error)) from error
        catalog = await store.read_person_catalog(conn)
        contact_id = scope.contact_id
        assert contact_id is not None  # a person scope carries its contact (JobScope.__post_init__)
        live = await claims_for(
            conn, contact_id, scope=WorkspaceScope.for_workspace(scope.workspace_id)
        )

    report: dict[str, Any] = {
        "job_id": str(job.job_id),
        "person": scope.person_name,
        "linkedin_url": scope.person_linkedin_url,
        "account_domain": scope.account_domain,
    }

    if persona is not None:
        # The same read ``seat_person_on_committee`` makes, on the claims already in hand: the dry
        # run exists so the operator does not have to guess, so it answers rather than restating
        # the condition.
        seated = any(str(claim.field_key) == PERSONA_FIELD for claim in live)
        if dry_run:
            report["seat"] = "already seated" if seated else f"would seat as {persona.value}"
        else:
            async with transaction() as conn:
                wrote = await seat_person_on_committee(
                    conn,
                    scope=scope,
                    persona=persona,
                    requested_by_user_id=run.requested_by_user_id,
                    writer=writer,
                    catalog=catalog,
                )
            report["seat"] = f"seated as {persona.value}" if wrote else "already seated"

    looked_up = [
        claim
        for claim in live
        if claim.source_key == _LOOKUP_SOURCE_KEY
        and not (claim.write_markers or {}).get("repaired")
    ]
    if looked_up and not force:
        report["existing_lookup_claims"] = len(looked_up)
        report["outcome"] = "skipped_already_looked_up"
        return report

    if not scope.person_linkedin_url:
        report["outcome"] = "no confirmed LinkedIn URL on the contact — nothing to match on"
        return report
    if dry_run:
        report["outcome"] = "would look the person up and write the record's claims"
        return report
    if api_key is None:
        # Checked here rather than up front because a ``--persona`` run over people whose lookup
        # already worked buys nothing: every job reports ``skipped_already_looked_up`` and the only
        # write is the seat. Demanding the provider key for that run refused a repair that needed
        # no provider. It is still refused before the first paid call, and still all-or-nothing —
        # this is the first job that would spend.
        raise Refused(
            f"CLUE_AI_ARK_API_KEY is unset and job {job.job_id} needs the lookup; set the key, or "
            "run with --dry-run, or name only jobs whose lookup already succeeded"
        )

    clients: ProviderClients = _AiArkOnly(settings=settings, api_key=api_key)
    runtime = ToolRuntime(
        scope=scope,
        settings=settings,
        clients=clients,
        conn_factory=transaction,
        artifacts=artifacts,
        writer=writer,
        catalog=catalog,
        media_budget=MediaBudget(settings.arv2_media_seconds_ceiling),
    )

    wanted = fold_identity(scope.person_linkedin_url)
    people = await runtime.call_provider(
        "ai_ark",
        lambda caller: runtime.clients.ai_ark(caller).people_by_name(
            [scope.person_name], scope.account_domain, size=_CANDIDATES
        ),
    )
    record = next(
        (
            person
            for person in people.people
            if person.linkedin_url and fold_identity(person.linkedin_url) == wanted
        ),
        None,
    )
    if record is None:
        report["record_found"] = False
        report["candidates"] = [person.current_company for person in people.people]
        report["outcome"] = "no candidate carries the confirmed LinkedIn URL — nothing written"
        return report

    employer = fold_identity(record.current_company_domain or "")
    account_domain = fold_identity(scope.account_domain)
    report["record_found"] = True
    if employer and employer != account_domain:
        report["employer"] = f"mismatch: {employer} is not {account_domain}"
        report["outcome"] = "the record puts this person at another employer — nothing written"
        return report
    report["employer"] = "verified" if employer else "unverified"

    stamps: dict[str, Any] = {"repaired": "lookup_person"}
    if not employer:
        stamps["employer_unverified"] = True

    written = await runtime.write_each(
        [marked(draft, stamps) for draft in ai_ark_person_claims(record, scope)]
    )
    exported = await runtime.call_provider(
        "ai_ark",
        lambda caller: runtime.clients.ai_ark(caller).export_email(scope.person_linkedin_url),
    )
    email_draft = email_export_claim(exported, scope)
    if email_draft is not None:
        written.extend(await runtime.write_each([marked(email_draft, stamps)]))

    report["claims_written"] = [
        draft.field_key for draft, result in written if not isinstance(result, WriteFailure)
    ]
    report["write_failures"] = [
        {"field_key": result.field_key, "error": result.error}
        for _, result in written
        if isinstance(result, WriteFailure)
    ]
    report["email"] = exported.address if exported.found and exported.address else None
    report["compliance"] = runtime.compliance_log
    report["outcome"] = "repaired"
    return report


async def _run(args: argparse.Namespace) -> list[dict[str, Any]]:
    settings = Settings()
    if not settings.arv2_account_research_enabled:
        raise Refused("CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED is false in this environment")
    secrets = Secrets()
    key = secrets.ai_ark_api_key
    if key is not None and not key.get_secret_value().strip():
        key = None
    register_arv2_wiring()
    storage: StorageBackend = (
        FsStorage(Path(args.storage_root))
        if args.storage_root is not None
        else build_storage_backend(settings)
    )
    job_ids = _job_ids(args.job_ids)

    reports: list[dict[str, Any]] = []
    async with db_lifespan(args.database_url):
        rows = await _read_rows(job_ids)
        artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=transaction)
        for job, run in rows:
            reports.append(
                await _repair_one(
                    job=job,
                    run=run,
                    settings=settings,
                    artifacts=artifacts,
                    api_key=key,
                    dry_run=args.dry_run,
                    force=args.force,
                    persona=Persona(args.persona) if args.persona else None,
                )
            )
    return reports


def main() -> None:
    args = _args()
    reports = asyncio.run(_run(args))
    for report in reports:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
