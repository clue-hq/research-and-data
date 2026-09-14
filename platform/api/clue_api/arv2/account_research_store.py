"""Row transitions of the R2 account-research substrate (``a3602967bb73``; master plan §5).

One function per transition, each honouring the CHECKs the migration installed: a job's status and
its ``finished_at`` move together, ``needs_review`` is the only status that carries a failure code,
and a run's status is *derived* from its jobs rather than set by whoever finished one — a run is
"in progress" while any account still has work, "needs review" when one of them ended flagged, and
"completed" only when every job did.

One job per *subject* (the migrations' ruling): an account, and since R3 (``60e51eba0123``) each
committee member of it, so a subject that fails takes only itself down. The run row is a launch
record — what the request was pinned to — and the jobs are the moving parts. Nothing here calls a
provider or an agent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.onboarding_store import DocumentRow
from clue_api.arv2.structuring_client import FieldCatalog, FieldSpec
from clue_core import decode_jsonb

__all__ = [
    "PERSON_EXTRA_FIELDS",
    "UNRECORDED_REASON",
    "UNSPECIFIED_FAILURE",
    "AnnotationRow",
    "JobRow",
    "JobSpend",
    "JobStage",
    "JobStatus",
    "JobSubject",
    "RunRow",
    "TerminalJob",
    "begin_job",
    "contacts_named",
    "create_job",
    "create_run",
    "find_contact_by_linkedin",
    "find_contact_by_name",
    "finish_job",
    "fold_linkedin_url",
    "job_link_audit",
    "job_spend",
    "list_jobs",
    "read_account_catalog",
    "read_job",
    "read_person_catalog",
    "read_persona_documents",
    "read_run",
    "record_annotations",
    "refresh_run_status",
    "set_job_stage",
    "suspend_job",
]

#: The seam-1 states, shared by runs and jobs so a reader learns one vocabulary.
JobStatus = Literal["not_started", "in_progress", "needs_review", "completed", "suspended"]

#: What a job researches: the account (R2) or one of its committee members (R3).
JobSubject = Literal["account", "person"]

#: Where a job is (spec 2026-09-12 §1, the research progress card). An account job walks
#: ``deep_research`` → ``synthesis`` → ``committee`` → ``member_research``; a person job stamps
#: only the first two. The database CHECK carries the same four values.
JobStage = Literal["deep_research", "synthesis", "committee", "member_research"]

#: The two statuses a job can *finish* on. ``suspended`` is a pause, not a terminal.
TerminalJob = Literal["completed", "needs_review"]

#: What a ``needs_review`` job records when its caller named no reason. The CHECK is biconditional,
#: so "flagged with no code" is not a row the database will take; an honest placeholder beats an
#: IntegrityError on the one path that exists to surface a problem to a human.
UNSPECIFIED_FAILURE = "unspecified"

#: The document statuses a reader may serve, mirroring ``onboarding_store``'s own list: a
#: ``running``/``failed``/``superseded`` document is not something a job may research against.
SERVED_DOCUMENT_STATUSES: tuple[str, ...] = ("ready", "proposed", "confirmed")

_RUN_COLUMNS = (
    "run_id, workspace_id, project_id, brand_id, project_run_id, icp_artifact_key, "
    "icp_artifact_sha256, icp_key, icp_version, product_selection_version, effort, "
    "committee_cap, directive_text, profile_ref, profile_sha256, requested_by_user_id, "
    "request_sha256, status, created_at, finished_at"
)

#: The run's status, derived from its jobs in one statement so two drivers finishing two accounts
#: at the same time cannot compute it from stale reads. ``array_agg`` over a run with no jobs is
#: NULL, which would make every ``= ANY`` comparison NULL and land the run on ``completed`` with a
#: NULL ``finished_at`` (an illegal row) — the COALESCE makes the empty run legally completed.
_REFRESH_RUN = text(
    """
    WITH s AS (
        SELECT COALESCE(array_agg(status), ARRAY[]::text[]) AS statuses
        FROM arv2_research_job WHERE run_id = :run_id
    )
    UPDATE arv2_research_run r SET status = CASE
        WHEN 'in_progress' = ANY(s.statuses) THEN 'in_progress'
        WHEN 'not_started' = ANY(s.statuses) THEN CASE
            WHEN 'completed' = ANY(s.statuses) OR 'needs_review' = ANY(s.statuses)
            THEN 'in_progress' ELSE 'not_started' END
        WHEN 'suspended' = ANY(s.statuses) THEN 'suspended'
        WHEN 'needs_review' = ANY(s.statuses) THEN 'needs_review'
        ELSE 'completed' END,
      finished_at = CASE
        WHEN NOT ('in_progress' = ANY(s.statuses) OR 'not_started' = ANY(s.statuses)
                  OR 'suspended' = ANY(s.statuses))
        THEN now() ELSE NULL END
    FROM s WHERE r.run_id = :run_id RETURNING r.status
    """
)


@dataclass(frozen=True)
class RunRow:
    """One launched research request, with everything the launch was pinned to.

    The pins (the ICP artifact and its sha, the ICP key/version, the product selection version, the
    profile ref and its sha, the request sha) are what make a run replayable against exactly the
    inputs a human signed off on, rather than whatever recon has since advanced to.
    """

    run_id: UUID
    workspace_id: str
    project_id: str
    brand_id: str
    project_run_id: UUID
    icp_artifact_key: str
    icp_artifact_sha256: str
    icp_key: str
    icp_version: int
    product_selection_version: int
    effort: str
    committee_cap: int
    directive_text: str
    profile_ref: str
    profile_sha256: str
    requested_by_user_id: str
    request_sha256: str
    status: JobStatus = "not_started"
    created_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class JobRow:
    """One research subject inside a run. ``finalization`` decodes ``finalization_json``.

    ``subject_type`` says *what* the job researches: the account itself (R2), or one committee
    member of it (R3, with ``subject_entity_id`` naming the contact). ``account_entity_id`` is the
    account either way, so a person job stays scoped and joined like its account sibling.
    ``profile_sha256`` is the profile *this* job was pinned to — a person job is queued later than
    the launch, so replay reads the job's own copy rather than the run's.
    """

    job_id: UUID
    run_id: UUID
    workspace_id: str
    account_entity_id: UUID
    subject_type: JobSubject
    subject_entity_id: UUID | None
    profile_sha256: str | None
    status: JobStatus
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None
    finalization: dict[str, Any] | None
    failure_code: str | None
    failure_message: str | None
    model_rounds: int
    tool_calls: int
    cost_usd: Decimal
    credits: Decimal
    media_seconds: int
    #: Where the job is (spec 2026-09-12 §1); ``None`` before its first claim or on rows that
    #: predate the column. Stamped by the driver, read by the research progress card.
    stage: JobStage | None = None


@dataclass(frozen=True)
class JobSpend:
    """One job's settled spend, summed from ``provider_call_ledger``."""

    cost_usd: Decimal
    credits: Decimal
    media_seconds: int


@dataclass(frozen=True)
class AnnotationRow:
    """One claim's link-audit result: the verdict, and the ``detail`` that says how it was reached.

    The verdict alone is not actionable — two claims can both be ``fetch_failed`` because one page
    returned no text and the other would not load at all, and those want different repairs. The
    ``detail`` carries the ``reason`` (plus the ``url``, the claim's ``origin`` source and the
    structuring block the quote came from) so a reader of the annotations never has to guess.
    """

    claim_id: UUID
    verdict: str
    detail: Mapping[str, Any]


async def create_run(conn: AsyncConnection, row: RunRow) -> bool:
    """Insert the launch record. Returns whether it was inserted (a re-launch of the same id is a
    no-op, never a second run against the same signed-off request)."""
    result = await conn.execute(
        text(
            f"INSERT INTO arv2_research_run ({_RUN_COLUMNS}) VALUES ("
            " :run_id, :workspace_id, :project_id, :brand_id, :project_run_id, :icp_artifact_key, "
            " :icp_artifact_sha256, :icp_key, :icp_version, :product_selection_version, :effort, "
            " :committee_cap, :directive_text, :profile_ref, :profile_sha256, "
            " :requested_by_user_id, :request_sha256, :status, COALESCE(:created_at, now()), "
            " :finished_at) ON CONFLICT (run_id) DO NOTHING"
        ),
        {
            "run_id": row.run_id,
            "workspace_id": row.workspace_id,
            "project_id": row.project_id,
            "brand_id": row.brand_id,
            "project_run_id": row.project_run_id,
            "icp_artifact_key": row.icp_artifact_key,
            "icp_artifact_sha256": row.icp_artifact_sha256,
            "icp_key": row.icp_key,
            "icp_version": row.icp_version,
            "product_selection_version": row.product_selection_version,
            "effort": row.effort,
            "committee_cap": row.committee_cap,
            "directive_text": row.directive_text,
            "profile_ref": row.profile_ref,
            "profile_sha256": row.profile_sha256,
            "requested_by_user_id": row.requested_by_user_id,
            "request_sha256": row.request_sha256,
            "status": row.status,
            "created_at": row.created_at,
            "finished_at": row.finished_at,
        },
    )
    return result.rowcount == 1


async def create_job(
    conn: AsyncConnection,
    *,
    job_id: UUID,
    run_id: UUID,
    workspace_id: str,
    account_entity_id: UUID,
    subject_type: JobSubject = "account",
    subject_entity_id: UUID | None = None,
    profile_sha256: str | None = None,
) -> bool:
    """Queue one subject — the account itself, or one of its committee members. Returns whether
    the row was inserted.

    ``arv2_research_job_subject_once`` is unique on ``(run_id, subject_type,
    COALESCE(subject_entity_id, account_entity_id))``, so re-queuing the same subject in the same
    run is refused there too — this conflict clause makes both spellings of "already queued" the
    same quiet ``False`` rather than one no-op and one IntegrityError. A *different* subject is
    never a conflict: the second committee member of an already-queued account inserts.

    A ``person`` subject must name its contact and an ``account`` subject must not; that pair is
    the migration's ``arv2_research_job_subject`` CHECK, so a caller that gets it wrong raises
    rather than storing a job nobody can interpret.
    """
    result = await conn.execute(
        text(
            "INSERT INTO arv2_research_job (job_id, run_id, workspace_id, account_entity_id, "
            " subject_type, subject_entity_id, profile_sha256) "
            "VALUES (:job_id, :run_id, :workspace_id, :account_entity_id, :subject_type, "
            " :subject_entity_id, :profile_sha256) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "job_id": job_id,
            "run_id": run_id,
            "workspace_id": workspace_id,
            "account_entity_id": account_entity_id,
            "subject_type": subject_type,
            "subject_entity_id": subject_entity_id,
            "profile_sha256": profile_sha256,
        },
    )
    return result.rowcount == 1


async def begin_job(conn: AsyncConnection, *, job_id: UUID) -> JobRow | None:
    """Claim a job for this attempt: ``not_started``/``suspended`` → ``in_progress``.

    Guarded on those two statuses so a re-delivered fleet task can neither restart a job another
    worker is driving nor revive a finished one; ``None`` says "not mine to run", which is a
    normal outcome of a redelivery, not an error.
    """
    row = (
        (
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET status = 'in_progress', attempt = attempt + 1, "
                    " started_at = now(), updated_at = now() "
                    "WHERE job_id = :job_id AND status IN ('not_started', 'suspended') RETURNING *"
                ),
                {"job_id": job_id},
            )
        )
        .mappings()
        .first()
    )
    return _job(row) if row is not None else None


async def finish_job(
    conn: AsyncConnection,
    *,
    job_id: UUID,
    status: TerminalJob,
    finalization: dict[str, Any],
    failure_code: str | None = None,
    failure_message: str | None = None,
    model_rounds: int,
    tool_calls: int,
    cost_usd: Decimal,
    credits: Decimal,
    media_seconds: int,
) -> None:
    """Land a job on a terminal status with its finalization and its spend.

    ``arv2_research_job_failure`` is biconditional, so the code is derived from the status rather
    than trusted from the caller: a ``completed`` job drops any failure pair it was handed, and a
    ``needs_review`` job that named no code records :data:`UNSPECIFIED_FAILURE`.
    """
    code = (failure_code or UNSPECIFIED_FAILURE) if status == "needs_review" else None
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET status = :status, finished_at = now(), "
            " finalization_json = CAST(:finalization AS jsonb), failure_code = :code, "
            " failure_message = :message, model_rounds = :model_rounds, tool_calls = :tool_calls, "
            " cost_usd = :cost_usd, credits = :credits, media_seconds = :media_seconds, "
            " updated_at = now() WHERE job_id = :job_id"
        ),
        {
            "status": status,
            "finalization": _dump_json(finalization),
            "code": code,
            "message": failure_message if code is not None else None,
            "model_rounds": int(model_rounds),
            "tool_calls": int(tool_calls),
            "cost_usd": cost_usd,
            "credits": credits,
            "media_seconds": int(media_seconds),
            "job_id": job_id,
        },
    )


async def suspend_job(conn: AsyncConnection, *, job_id: UUID) -> None:
    """Park a job for requeue (a lost lease, a stop request, a run-level pause).

    Guarded off the terminal statuses so the requeue path can never walk a finished job back into
    the queue — and so the biconditional ``finished_at`` CHECK stays satisfied without this
    function having to clear a column it does not own.
    """
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET status = 'suspended', updated_at = now() "
            "WHERE job_id = :job_id AND status NOT IN ('completed', 'needs_review')"
        ),
        {"job_id": job_id},
    )


async def set_job_stage(conn: AsyncConnection, *, job_id: UUID, stage: JobStage) -> None:
    """Stamp where the job is (spec 2026-09-12 §1). Never touches status or the receipt."""
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET stage = :stage, updated_at = now() WHERE job_id = :job_id"
        ),
        {"stage": stage, "job_id": job_id},
    )


async def refresh_run_status(conn: AsyncConnection, *, run_id: UUID) -> str:
    """Recompute the run's status from its jobs and return it; sets ``finished_at`` iff terminal.

    Called after every job transition, so the run row is never a second opinion about its jobs.
    """
    return str((await conn.execute(_REFRESH_RUN, {"run_id": run_id})).scalar_one())


async def read_run(conn: AsyncConnection, *, run_id: UUID) -> RunRow | None:
    row = (
        (
            await conn.execute(
                text(f"SELECT {_RUN_COLUMNS} FROM arv2_research_run WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
        )
        .mappings()
        .first()
    )
    return _run(row) if row is not None else None


async def read_job(conn: AsyncConnection, *, job_id: UUID) -> JobRow | None:
    row = (
        (
            await conn.execute(
                text("SELECT * FROM arv2_research_job WHERE job_id = :job_id"), {"job_id": job_id}
            )
        )
        .mappings()
        .first()
    )
    return _job(row) if row is not None else None


async def list_jobs(conn: AsyncConnection, *, run_id: UUID) -> tuple[JobRow, ...]:
    """Every job of a run, oldest first — the order the driver queued the accounts in."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT * FROM arv2_research_job WHERE run_id = :run_id "
                    "ORDER BY created_at, job_id"
                ),
                {"run_id": run_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(_job(row) for row in rows)


async def record_annotations(
    conn: AsyncConnection,
    *,
    job_id: UUID,
    rows: Sequence[AnnotationRow] | None = None,
    claim_ids_by_verdict: Mapping[str, Sequence[UUID]] | None = None,
) -> int:
    """Write the link-audit result for each claim; returns how many annotations were written.

    An annotation is a *check result*, never the claim's own value, which is why it is a row beside
    the claim rather than an edit to append-only history.

    ``rows`` is the real form: a verdict plus the ``detail`` that says how it was reached, which is
    what makes the audit actionable — ``fetch_failed`` alone cannot tell an empty page from a dead
    link. ``claim_ids_by_verdict`` is the older verdict-only form, kept working as a thin wrapper
    (it records a bare verdict with no detail) so a caller that has nothing to say about *why*
    still writes the annotation rather than skipping it.
    """
    if rows is None:
        rows = [
            AnnotationRow(claim_id=claim_id, verdict=verdict, detail={})
            for verdict, claim_ids in (claim_ids_by_verdict or {}).items()
            for claim_id in claim_ids
        ]
    params = [
        {
            "claim_id": row.claim_id,
            "job_id": job_id,
            "verdict": row.verdict,
            "detail": json.dumps(dict(row.detail), sort_keys=True) if row.detail else None,
        }
        for row in rows
    ]
    if not params:
        return 0
    await conn.execute(
        text(
            "INSERT INTO arv2_claim_annotation (claim_id, job_id, kind, verdict, detail_json) "
            "VALUES (:claim_id, :job_id, 'link_audit', :verdict, CAST(:detail AS jsonb))"
        ),
        params,
    )
    return len(params)


async def job_spend(conn: AsyncConnection, *, job_id: UUID) -> JobSpend:
    """What one job actually spent, summed from the ledger rather than from a running total.

    Only ``phase = 'result'`` rows count: an ``estimate`` row is what a call *might* cost, and
    adding the two together would bill every call twice. The ledger is the money truth, so a job's
    ``cost_usd``/``credits``/``media_seconds`` are derived from it at the end rather than
    accumulated by whoever remembered to.
    """
    row = (
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd, "
                    " COALESCE(SUM(credits), 0) AS credits, "
                    " COALESCE(SUM(media_seconds), 0) AS media_seconds "
                    "FROM provider_call_ledger "
                    "WHERE entity_research_job_id = :job_id AND phase = 'result'"
                ),
                {"job_id": job_id},
            )
        )
        .mappings()
        .one()
    )
    return JobSpend(
        cost_usd=Decimal(row["cost_usd"]),
        credits=Decimal(row["credits"]),
        media_seconds=int(row["media_seconds"]),
    )


#: What a pre-reason annotation (one written by the verdict-only wrapper) tallies under. It is a
#: label for "this row does not say why", never a reason in its own right.
UNRECORDED_REASON = "unrecorded"


async def job_link_audit(conn: AsyncConnection, *, job_id: UUID) -> dict[str, int]:
    """The link-audit tally for one job, keyed ``"<verdict>/<reason>"`` → how many claims got it.

    Read back rather than remembered, so a receipt reports what is actually recorded beside the
    claims — including a re-run audit's second pass — instead of what one tool call returned.

    The reason is part of the key because the verdict alone hides the difference that matters: a
    job whose audit is all ``fetch_failed/page_unreachable`` has a link problem, while one that is
    all ``NOT_FOUND/not_on_page`` has a quoting problem, and a receipt that reported only
    ``fetch_failed: 4`` would leave a reader to guess which.
    """
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT verdict, COALESCE(detail_json->>'reason', :unrecorded) AS reason, "
                    " COUNT(*) AS n FROM arv2_claim_annotation "
                    "WHERE job_id = :job_id AND kind = 'link_audit' "
                    "GROUP BY verdict, reason"
                ),
                {"job_id": job_id, "unrecorded": UNRECORDED_REASON},
            )
        )
        .mappings()
        .all()
    )
    return {f"{row['verdict']}/{row['reason']}": int(row["n"]) for row in rows}


async def read_account_catalog(conn: AsyncConnection) -> FieldCatalog:
    """The account-side field menu one job may write against: every registered ``account.*`` and
    ``core.*`` field, exactly as the registry holds it.

    The catalog is read from the registry rather than enumerated in code, because "open by
    registration, not enumeration" is the whole point of the field registry: a pack that adds a
    field is a row, and this menu grows with it without a code change.
    """
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT field_key, description, value_schema FROM field_definition "
                    "WHERE active AND (field_key LIKE 'account.%' OR field_key LIKE 'core.%') "
                    "ORDER BY field_key"
                )
            )
        )
        .mappings()
        .all()
    )
    return FieldCatalog(
        account=tuple(
            FieldSpec(
                key=str(row["field_key"]),
                description=str(row["description"] or ""),
                value_schema=_schema(row["value_schema"]),
            )
            for row in rows
        )
    )


#: The one non-``contact.*`` field a person job may write against: the person's own work email,
#: which the registry holds in the ``core.*`` namespace as a contact channel rather than as a
#: company fact.
#:
#: **No ``account.*`` key belongs on this menu.** A person job stamps every claim it writes to the
#: contact (``account_research_claims._draft``), so an account fact offered here would be written
#: *on the person* — a company's open requisitions recorded as a fact about one employee, where no
#: reader of the account looks. The person agent reads the account's facts from the
#: already-established block the driver supplies in its context, and writes none of them.
PERSON_EXTRA_FIELDS: tuple[str, ...] = ("core.work_email",)


async def read_person_catalog(conn: AsyncConnection) -> FieldCatalog:
    """The person-side field menu one person job may write against.

    Every registered ``contact.*`` field — plain facts in the contact section, personal hooks in
    the facet section — plus :data:`PERSON_EXTRA_FIELDS`. Read from the registry for the same
    reason :func:`read_account_catalog` is: a pack that adds a contact field is a row, and the menu
    grows with it without a code change.

    Each row also carries the field's declared ``use_class_hint``. The registry holds it in
    ``field_definition.validation`` (``{"use_class_hint": …}``), and it is what a contact claim
    written against that field is born with — so the difference between a professional fact and a
    personal one is read off the field that declares it, never inferred from the key's spelling.
    A field whose ``validation`` says nothing has no hint, and the claim path's default decides.
    """
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT field_key, description, value_schema, "
                    " validation->>'use_class_hint' AS use_class_hint "
                    "FROM field_definition "
                    "WHERE active AND (field_key LIKE 'contact.%' OR field_key = ANY(:extra)) "
                    "ORDER BY field_key"
                ),
                {"extra": list(PERSON_EXTRA_FIELDS)},
            )
        )
        .mappings()
        .all()
    )
    sections: dict[str, list[FieldSpec]] = {"account": [], "contact": [], "facet": []}
    for row in rows:
        key = str(row["field_key"])
        section = (
            "facet"
            if key.startswith("contact.facet.")
            else "contact"
            if key.startswith("contact.")
            else "account"
        )
        sections[section].append(
            FieldSpec(
                key=key,
                description=str(row["description"] or ""),
                value_schema=_schema(row["value_schema"]),
                use_class_hint=(
                    str(row["use_class_hint"]) if row["use_class_hint"] is not None else None
                ),
            )
        )
    return FieldCatalog(
        account=tuple(sections["account"]),
        contact=tuple(sections["contact"]),
        facet=tuple(sections["facet"]),
    )


async def contacts_named(
    conn: AsyncConnection, *, workspace_id: str, account_id: UUID, name: str
) -> tuple[UUID, ...]:
    """Every live contact under this account whose full name is ``name`` (at most two).

    Two is all any caller needs: one is a resolution, two or more is the same-name trap and the
    honest answer is "not resolvable", never "whichever row came back first". The match is exact on
    the trimmed, case-folded name.
    """
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT id FROM contact_entity "
                    "WHERE workspace_id = :workspace_id AND account_entity_id = :account_id "
                    "  AND merged_into IS NULL "
                    "  AND lower(btrim(full_name)) = lower(btrim(:name)) "
                    "LIMIT 2"
                ),
                {"workspace_id": workspace_id, "account_id": account_id, "name": name},
            )
        )
        .mappings()
        .all()
    )
    return tuple(UUID(str(row["id"])) for row in rows)


async def find_contact_by_name(
    conn: AsyncConnection, *, workspace_id: str, account_id: UUID, name: str
) -> UUID | None:
    """The one contact under this account whose name is ``name``, or ``None``.

    ``contact.reports_to`` declares ``contact_id`` as its **required** key, but the agent knows the
    manager by name — so the name is resolved here, against the entities this workspace actually
    holds, rather than the agent being asked for an id it cannot know or the claim being written
    with an invented one.

    The match is exact on the trimmed, case-folded full name, and **two matches resolve to
    nothing**: two people called "Dana Reyes" at one account is precisely the same-name trap this
    lane exists to refuse, and picking either would be a guess. The caller records the skip. A
    caller that must tell "nobody" from "two of them" — the committee step, which would otherwise
    create a third row — reads :func:`contacts_named` instead.
    """
    found = await contacts_named(conn, workspace_id=workspace_id, account_id=account_id, name=name)
    return found[0] if len(found) == 1 else None


def fold_linkedin_url(value: object) -> str | None:
    """The stored form of a LinkedIn profile URL, or ``None`` when there is none.

    It must fold exactly the way ``clue_research.identity`` folds a strong-key column on insert
    (lower-cased, trimmed, trailing slash dropped), because a lookup that folds differently from
    the write would miss a row that is there and then insert a duplicate — which the unique index
    refuses, turning a join into an error. The fold is repeated rather than imported: it is a
    private of that package, and three lines copied under this comment are safer than a private
    import that can move.
    """
    if not isinstance(value, str):
        return None
    folded = value.strip().rstrip("/").lower()
    return folded or None


async def find_contact_by_linkedin(
    conn: AsyncConnection, *, workspace_id: str, linkedin_url: str
) -> UUID | None:
    """The contact this workspace holds under that LinkedIn URL, or ``None``.

    Workspace-scoped, not account-scoped, because that is the scope of the strong key's unique
    index (``contact_entity_linkedin_url_ws_key``): the same person met under two accounts is one
    row, and looking only under one account would insert a duplicate the index then refuses.
    """
    folded = fold_linkedin_url(linkedin_url)
    if folded is None:
        return None
    row = (
        await conn.execute(
            text(
                "SELECT id FROM contact_entity "
                "WHERE workspace_id = :workspace_id AND linkedin_url = :linkedin_url "
                "  AND merged_into IS NULL "
                "LIMIT 1"
            ),
            {"workspace_id": workspace_id, "linkedin_url": folded},
        )
    ).scalar_one_or_none()
    return UUID(str(row)) if row is not None else None


async def read_persona_documents(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, project_id: str
) -> tuple[DocumentRow, ...]:
    """The served ``audience-persona`` documents this project may read, newest first.

    It returns *candidates* rather than the one document a run wants, because a persona document
    names its ICP in its front matter, not in a column — the caller reads the bodies and keeps the
    one whose ``icp_key`` matches the run's pin. Filtering here would mean guessing the ICP from
    the path, which is exactly the kind of guess this lane refuses to make.

    Scope is not a guess, though, and it is enforced: the brand's personas plus this project's own,
    project-local ones first. Another project's personas are never candidates — a persona written
    for one project's rewritten ICP would otherwise be matched by key into a run that never asked
    for it.
    """
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT document_id, folder, path, kind, version, status, artifact_key, "
                    " artifact_sha256 FROM brand_knowledge_document "
                    "WHERE workspace_id = :workspace_id AND brand_id = :brand_id "
                    " AND kind = 'audience-persona' AND status = ANY(:served) "
                    " AND artifact_key IS NOT NULL "
                    " AND (project_id IS NULL OR project_id = :project_id) "
                    "ORDER BY (project_id IS NULL), version DESC, created_at DESC"
                ),
                {
                    "workspace_id": workspace_id,
                    "brand_id": brand_id,
                    "project_id": project_id,
                    "served": list(SERVED_DOCUMENT_STATUSES),
                },
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        DocumentRow(
            document_id=row["document_id"],
            folder=row["folder"],
            path=row["path"],
            kind=row["kind"],
            version=row["version"],
            status=row["status"],
            artifact_key=row["artifact_key"],
            artifact_sha256=row["artifact_sha256"],
        )
        for row in rows
    )


def _schema(raw: Any) -> Mapping[str, Any] | None:
    """A ``value_schema`` column as a mapping, or ``None`` when the field declares none."""
    decoded = decode_jsonb(raw)
    return decoded if isinstance(decoded, Mapping) else None


def _dump_json(payload: Mapping[str, Any]) -> str:
    """The finalization payload as jsonb text. ``default=str`` so a Decimal or a datetime the
    driver put in its finalization is stored rather than raising at the last step of a job."""
    return json.dumps(dict(payload), sort_keys=True, default=str)


def _run(row: RowMapping) -> RunRow:
    return RunRow(
        run_id=row["run_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        brand_id=row["brand_id"],
        project_run_id=row["project_run_id"],
        icp_artifact_key=row["icp_artifact_key"],
        icp_artifact_sha256=row["icp_artifact_sha256"],
        icp_key=row["icp_key"],
        icp_version=row["icp_version"],
        product_selection_version=row["product_selection_version"],
        effort=row["effort"],
        committee_cap=row["committee_cap"],
        directive_text=row["directive_text"],
        profile_ref=row["profile_ref"],
        profile_sha256=row["profile_sha256"],
        requested_by_user_id=row["requested_by_user_id"],
        request_sha256=row["request_sha256"],
        status=row["status"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
    )


def _job(row: RowMapping) -> JobRow:
    finalization = decode_jsonb(row["finalization_json"])
    return JobRow(
        job_id=row["job_id"],
        run_id=row["run_id"],
        workspace_id=row["workspace_id"],
        account_entity_id=row["account_entity_id"],
        subject_type=row["subject_type"],
        subject_entity_id=row["subject_entity_id"],
        profile_sha256=row["profile_sha256"],
        status=row["status"],
        attempt=row["attempt"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        finalization=finalization,
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        model_rounds=row["model_rounds"],
        tool_calls=row["tool_calls"],
        cost_usd=row["cost_usd"],
        credits=row["credits"],
        media_seconds=row["media_seconds"],
        stage=row["stage"],
    )
