"""What an account job's committee finding becomes: people, their claims, and their own jobs.

The account agent resolves a buying committee and finalizes; each confirmed candidate is written as
one ``account.committee_candidate`` claim on the account. That is a finding *about the account*. It
is not yet a person the platform can research, address or govern — that needs a contact entity, the
three committee claims keyed to it, and a job of its own. This module is that turn, and it runs
inside the settling transaction of the account job that made the finding.

Four rules shape it, and each is a test in ``tests/arv2/test_committee_step_db.py``:

* **A vacant seat is not a person.** "Nobody holds this role" is a fact about the account; it
  creates no contact, no claims and no job. Neither does a named candidate with no confirming URL —
  the account job never wrote it as a claim either (``committee_candidate_claims``).
* **One member is one savepoint.** The contact, its three claims and its person job land together
  or not at all, and a member that cannot be written is a recorded skip. The step runs *inside* the
  account job's terminal transaction, so a raised error here would cost that job the ``finish_job``
  row it just wrote — the one failure the driver's containment cannot repair.
* **The person job row is the member's latch.** It is derived (``run + contact``), so a re-settled
  job finds it already there, writes nothing a second time, and still reports the member as work to
  offer — a lost fleet offer is repaired by re-settling, and a duplicate dedup key is a no-op at
  the queue.
* **It queues nothing.** Like the launch it mirrors, it reports what to offer; the driver offers it
  once the settling transaction has committed. Rows first, offer second.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_catalog import has_capability
from clue_api.arv2.account_research_claims import JobScope, committee_member_claims
from clue_api.arv2.account_research_launch import QueuedJob, arv2_job_id
from clue_api.arv2.account_research_store import (
    JobRow,
    RunRow,
    contacts_named,
    create_job,
    find_contact_by_linkedin,
    fold_linkedin_url,
)
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.structuring_client import FieldCatalog
from clue_core import EntityId
from clue_obs import get_logger
from clue_obs.langfuse import tag_entities
from clue_research.identity import get_contact, insert_contact_entity
from clue_research.identity.provider import (
    ProviderIdentityConflict,
    link_selection_claim,
    resolve_provider_contact,
)

log = get_logger("clue_api.arv2.committee_step")

__all__ = ["CommitteeSkip", "CommitteeStepResult", "run_committee_step"]


@dataclass(frozen=True)
class CommitteeSkip:
    """One candidate the step did not fan out, and the named reason it did not.

    Reasons: ``vacant_seat`` (no person to research), ``unconfirmed`` (a name with no confirming
    URL behind it), ``committee_cap`` (past the run's cap), ``ambiguous_name`` (two people of that
    name already sit under this account — the same-name trap, refused rather than guessed) and
    ``member_not_written`` (the member's own savepoint rolled back; the log carries the error).
    """

    name: str
    reason: str


@dataclass(frozen=True)
class CommitteeStepResult:
    """What the step did: who it created, what to offer the fleet, and what it skipped."""

    contacts_created: tuple[EntityId, ...]
    jobs: tuple[QueuedJob, ...]
    skipped: tuple[CommitteeSkip, ...]
    #: Members admitted without a LinkedIn URL. They are researched (a confirmed person with a
    #: confirming URL is a person), but they were resolved on their name alone, so their identity
    #: rests on a weaker key than the strong one — worth saying out loud in the receipt and the log.
    linkedin_missing: tuple[str, ...] = ()


async def run_committee_step(
    conn: AsyncConnection,
    *,
    job: JobRow,
    run: RunRow,
    scope: JobScope,
    candidates: Sequence[Mapping[str, Any]],
    writer: LenientClaimWriter,
    person_profile_sha256: str,
    catalog: FieldCatalog,
    person_profile_ref: str | None = None,
) -> CommitteeStepResult:
    """Turn one account job's confirmed committee candidates into people and person jobs.

    Called by the driver for ``subject_type == "account"`` jobs only, inside the settling
    transaction and after ``finish_job``: the account job's terminal row is already written, so
    nothing this step does can un-write it, and everything it does is committed with it.
    """
    created: list[EntityId] = []
    queued: list[QueuedJob] = []
    skipped: list[CommitteeSkip] = []
    no_linkedin: list[str] = []
    admitted = 0
    seen: set[str] = set()

    for candidate in candidates:
        name = str(candidate.get("name") or "").strip()
        if candidate.get("vacant_seat") or not name:
            skipped.append(
                CommitteeSkip(
                    name,
                    "unfilled_role"
                    if candidate.get("evidence_kind") == "unfilled_role"
                    and not candidate.get("vacant_seat")
                    else "vacant_seat",
                )
            )
            continue
        if not candidate.get("confirmed_by") and not candidate.get("candidate_ref"):
            skipped.append(CommitteeSkip(name, "unconfirmed"))
            continue
        identity = str(
            candidate.get("provider_subject_id") or candidate.get("linkedin_url") or name.casefold()
        )
        if identity in seen:
            skipped.append(CommitteeSkip(name, "duplicate_selection"))
            continue
        if admitted >= run.committee_cap:
            skipped.append(CommitteeSkip(name, "committee_cap"))
            continue

        try:
            # One savepoint per member: the contact, its claims and its job row are one unit, and a
            # failure inside it rolls back to here instead of poisoning the settling transaction.
            async with conn.begin_nested():
                member = await _fan_out(
                    conn,
                    job=job,
                    run=run,
                    scope=scope,
                    candidate=candidate,
                    name=name,
                    writer=writer,
                    person_profile_sha256=person_profile_sha256,
                    catalog=catalog,
                    person_profile_ref=person_profile_ref,
                )
        except ProviderIdentityConflict as conflict:
            skipped.append(CommitteeSkip(name, str(conflict)))
            continue
        except _AmbiguousName:
            # Deliberately not an error in the log: two people of one name under one account is a
            # finding about the data, not a fault, and the refusal to guess is the correct answer.
            log.info("arv2.committee_member_ambiguous", job_id=str(job.job_id), name=name)
            skipped.append(CommitteeSkip(name, "ambiguous_name"))
            continue
        except Exception as error:  # noqa: BLE001 — a member's failure is a skip, never a stop
            log.exception(
                "arv2.committee_member_failed",
                job_id=str(job.job_id),
                run_id=str(run.run_id),
                error=str(error)[:300],
            )
            skipped.append(CommitteeSkip(name, "member_not_written"))
            continue

        seen.add(identity)
        admitted += 1
        if member.created:
            created.append(member.contact_id)
        if member.linkedin_missing:
            no_linkedin.append(name)
        queued.append(
            QueuedJob(job_id=member.job_id, run_id=run.run_id, workspace_id=run.workspace_id)
        )

    log.info(
        "arv2.committee_step_complete",
        job_id=str(job.job_id),
        run_id=str(run.run_id),
        admitted=admitted,
        contacts_created=len(created),
        skipped=[(skip.name, skip.reason) for skip in skipped],
        linkedin_missing=len(no_linkedin),
    )
    return CommitteeStepResult(
        contacts_created=tuple(created),
        jobs=tuple(queued),
        skipped=tuple(skipped),
        linkedin_missing=tuple(no_linkedin),
    )


class _AmbiguousName(Exception):
    """Two people of this name already sit under the account, so the candidate resolves to none."""


@dataclass(frozen=True)
class _Member:
    contact_id: EntityId
    job_id: UUID
    created: bool
    linkedin_missing: bool


async def _fan_out(
    conn: AsyncConnection,
    *,
    job: JobRow,
    run: RunRow,
    scope: JobScope,
    candidate: Mapping[str, Any],
    name: str,
    writer: LenientClaimWriter,
    person_profile_sha256: str,
    catalog: FieldCatalog,
    person_profile_ref: str | None = None,
) -> _Member:
    """One confirmed member: their contact row, their three claims, and their person job.

    The claims are written **only when this call inserts the job row**. The three of them and the
    row land in the same savepoint, so a job row that exists is a member whose claims are already
    written — which makes the row the member's idempotency latch and a re-settle a pure no-op.
    """
    linkedin = fold_linkedin_url(candidate.get("linkedin_url"))
    refs = (
        {"version": 1, "parent_job_id": str(job.job_id)}
        if has_capability(scope.catalog_version, "committee_discovery")
        else None
    )
    if candidate.get("candidate_ref"):
        contact_id, created = await resolve_provider_contact(
            conn,
            workspace_id=run.workspace_id,
            account_id=scope.account_id,
            provider="ai_ark",
            subject_id=str(candidate["provider_subject_id"]),
            name=name,
            linkedin_url=linkedin,
            artifact_key=str(candidate["artifact_key"]),
        )
        account_id = job.account_entity_id
        refs = {key: candidate[key] for key in ("candidate_ref", "parent_job_id")}
        refs["version"] = 1
    else:
        contact_id, account_id, created = await _resolve_contact(
            conn, run=run, account_id=job.account_entity_id, name=name, linkedin_url=linkedin
        )
        if (
            has_capability(scope.catalog_version, "committee_discovery")
            and account_id != job.account_entity_id
        ):
            raise ProviderIdentityConflict("employment_conflict")
    if candidate.get("selection_claim_id"):
        await link_selection_claim(
            conn,
            workspace_id=run.workspace_id,
            contact_id=contact_id,
            claim_id=UUID(str(candidate["selection_claim_id"])),
        )
    person_job_id = arv2_job_id(run.run_id, UUID(str(contact_id)))
    inserted = await create_job(
        conn,
        job_id=person_job_id,
        run_id=run.run_id,
        workspace_id=run.workspace_id,
        # The **person's own** account, which is this job's except in the one case where the strong
        # key resolved them to a contact the workspace already holds under a different employer.
        # Then the identity layer's answer wins, exactly as it does for an on-demand person launch:
        # the job composes the employer the entity names, not the page that mentioned them.
        account_entity_id=account_id,
        subject_type="person",
        subject_entity_id=UUID(str(contact_id)),
        # The person profile's own digest: a person job is queued long after the launch, so replay
        # reads the bytes *it* was pinned to rather than the account run's.
        profile_sha256=person_profile_sha256,
        profile_ref=person_profile_ref,
        input_refs=refs,
    )
    if inserted:
        # The member is born here: the account job's trace names every person it created.
        tag_entities([contact_id])
        for draft in committee_member_claims(
            candidate, scope=scope, contact_id=contact_id, catalog=catalog
        ):
            await writer.write(conn, draft)
    return _Member(
        contact_id=contact_id,
        job_id=person_job_id,
        created=created,
        linkedin_missing=linkedin is None,
    )


async def _resolve_contact(
    conn: AsyncConnection,
    *,
    run: RunRow,
    account_id: UUID,
    name: str,
    linkedin_url: str | None,
) -> tuple[EntityId, UUID, bool]:
    """The person this candidate is (and whose account they are), created if nobody holds them yet.

    The LinkedIn URL is the strong key, so it is asked first and across the whole workspace (that
    is the scope of its unique index): the same person met under two accounts is one row, never
    two — and the row's own employer is returned with it, because the entity layer is what decides
    where a person works. Without a URL — a candidate confirmed on a team page that links nothing —
    the fallback is the exact name *under this account*, which is the same resolution
    ``contact.reports_to`` uses and refuses the same way when two people share it.
    """
    if linkedin_url is not None:
        existing = await find_contact_by_linkedin(
            conn, workspace_id=run.workspace_id, linkedin_url=linkedin_url
        )
        if existing is not None:
            held = await get_contact(conn, EntityId(existing))
            if held is None:  # pragma: no cover - the id came from that same table
                raise RuntimeError(f"contact {existing} vanished between two reads")
            return held.id, UUID(str(held.account_entity_id)), False
    by_name = await contacts_named(
        conn, workspace_id=run.workspace_id, account_id=account_id, name=name
    )
    if len(by_name) > 1:
        raise _AmbiguousName(f"{len(by_name)} contacts under this account are called {name!r}")
    if by_name:
        return EntityId(by_name[0]), account_id, False
    contact_id = await insert_contact_entity(
        conn,
        account_entity_id=EntityId(account_id),
        full_name=name,
        linkedin_url=linkedin_url,
    )
    return contact_id, account_id, True
