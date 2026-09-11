"""Row transitions of the R4 discovery substrate (``2cd622be2da0``; spec §5–§6).

One function per transition, each honouring the CHECKs the migration installed. Two tables, and
each one exists for a reason the spec names:

``arv2_discovery_run`` is a launch record pinned to the ICP document the human asked against, so a
redelivered fleet task replays the same request rather than paying for a second long list —
:func:`find_discovery_run` is that replay lookup, keyed on the request sha the launch computed.
Its counters (``asked`` / ``found_strict`` / ``found_relaxed`` / ``analyzed`` /
``recall_estimate``) are the §4 "a short list is information, never padded" record: a run that
exhausts the pool says so with numbers instead of quietly returning fewer companies.

``arv2_discovery_candidate`` is one company, keyed by its verified domain inside its run, with the
per-gate verdicts and the fit derived from them.

**Unapproved is not rejected** (ruling 1′, rev 5). Nothing here can mark a candidate rejected;
:func:`mark_candidates_approved` is the only decision write, and it only ever writes ``approved``.
A candidate the human left alone keeps no label — :func:`unapproved_domains` is how a *later* run
in the same project remembers not to re-surface it, and the ``not_chosen_before`` disposition is
what that later run stamps. The absence of a rejection vocabulary is the product's, not an
oversight.

Nothing here calls a provider or an agent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import decode_jsonb

__all__ = [
    "CandidateRow",
    "Disposition",
    "DiscoveryRunRow",
    "DiscoveryStatus",
    "Pass",
    "begin_discovery_run",
    "create_discovery_run",
    "find_discovery_run",
    "finish_discovery_run",
    "list_candidates",
    "mark_candidates_approved",
    "read_discovery_run",
    "record_discovery_progress",
    "record_relaxed_search",
    "record_verdicts",
    "record_webset",
    "request_relaxed",
    "suspend_discovery_run",
    "unapproved_domains",
    "upsert_candidate",
]

#: The seam-1 states, verbatim — the same vocabulary the R2 runs and jobs carry.
DiscoveryStatus = Literal["not_started", "in_progress", "needs_review", "completed", "suspended"]

#: Which §4 pass a candidate came from: the full criteria, or the relaxed re-search.
Pass = Literal["strict", "relaxed"]

#: What a verified candidate *is*, never what it was refused for. ``not_chosen_before`` is how a
#: later run records a candidate an earlier run surfaced and the human did not tick.
Disposition = Literal[
    "pending", "pass", "partial", "unclear", "duplicate_of_existing", "not_chosen_before"
]

#: The dispositions a candidate is still worth remembering as "seen but not chosen". A duplicate
#: is already an account, and a pending one was never verified, so neither is re-surfacing news.
_LIVE_DISPOSITIONS = "('pass', 'partial', 'unclear')"

_RUN_COLUMNS = (
    "run_id, workspace_id, project_id, brand_id, project_run_id, icp_artifact_key, "
    "icp_artifact_sha256, icp_key, icp_version, requested_by_user_id, request_sha256, "
    "target_count, strict_count, relaxed_enabled, relaxed_requested, criteria_gate_keys, "
    "status, webset_id, strict_search_id, relaxed_search_id, asked, found_strict, "
    "found_relaxed, analyzed, recall_estimate, "
    "receipt_json, created_at, started_at, finished_at"
)

_CANDIDATE_COLUMNS = (
    "candidate_id, run_id, workspace_id, project_id, pass, domain, websets_url, name, "
    "provider_snapshot_json, verdicts_json, fit, disposition, decision, decided_by_user_id, "
    "decided_at, account_entity_id"
)


@dataclass(frozen=True)
class DiscoveryRunRow:
    """One launched discovery request, with what it was pinned to and what it found.

    The pins (the ICP artifact key and its sha, the ICP key/version, the request sha) are what make
    a run replayable against exactly the document a human asked against. ``criteria_gate_keys`` is
    the gate set the verifier must answer for every candidate, recorded at launch so a run that
    resumes after a restart grades on the same gates it started on.
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
    requested_by_user_id: str
    request_sha256: str
    target_count: int
    strict_count: int
    relaxed_enabled: bool
    criteria_gate_keys: tuple[str, ...]
    status: DiscoveryStatus = "not_started"
    relaxed_requested: bool = False
    webset_id: str | None = None
    #: The two searches inside that webset, recorded so a resumed attempt never guesses which one
    #: is the strict pass (an array position is not a provider contract) and never buys the
    #: widening search a second time. ``relaxed_search_id`` set means "the relaxed pass has been
    #: bought" — the driver polls and reads it rather than calling ``add_search`` again.
    strict_search_id: str | None = None
    relaxed_search_id: str | None = None
    asked: int | None = None
    found_strict: int | None = None
    found_relaxed: int | None = None
    analyzed: int | None = None
    recall_estimate: int | None = None
    receipt: Mapping[str, Any] | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class CandidateRow:
    """One company the long list returned, verified on every gate.

    ``provider_snapshot`` is the raw record the long list gave, kept whole so nothing the verifier
    or the account writer later needs has to be re-fetched. ``verdicts`` are the per-gate results
    with their quotes and urls; ``fit`` is derived from them, and ``disposition`` says what the
    candidate is. ``decision`` is the human's approval — ``None`` or ``"approved"``, never a
    rejection (see the module docstring).
    """

    candidate_id: UUID
    run_id: UUID
    workspace_id: str
    project_id: str
    pass_: Pass
    domain: str
    websets_url: str | None
    name: str
    provider_snapshot: Mapping[str, Any]
    verdicts: tuple[Mapping[str, Any], ...] = ()
    fit: float | None = None
    disposition: Disposition = "pending"
    decision: str | None = None
    decided_by_user_id: str | None = None
    decided_at: datetime | None = None
    account_entity_id: UUID | None = None


async def create_discovery_run(conn: AsyncConnection, row: DiscoveryRunRow) -> bool:
    """Insert the launch record. Returns whether it was inserted.

    A re-launch of the same id is a quiet no-op, never a second run against the same signed-off
    request — the same posture ``account_research_store.create_run`` takes.
    """
    result = await conn.execute(
        text(
            f"INSERT INTO arv2_discovery_run ({_RUN_COLUMNS}) VALUES ("
            " :run_id, :workspace_id, :project_id, :brand_id, :project_run_id, :icp_artifact_key, "
            " :icp_artifact_sha256, :icp_key, :icp_version, :requested_by_user_id, "
            " :request_sha256, :target_count, :strict_count, :relaxed_enabled, "
            " :relaxed_requested, CAST(:criteria_gate_keys AS jsonb), :status, :webset_id, "
            " :strict_search_id, :relaxed_search_id, "
            " :asked, :found_strict, :found_relaxed, :analyzed, :recall_estimate, "
            " CAST(:receipt AS jsonb), COALESCE(:created_at, now()), :started_at, :finished_at) "
            "ON CONFLICT (run_id) DO NOTHING"
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
            "requested_by_user_id": row.requested_by_user_id,
            "request_sha256": row.request_sha256,
            "target_count": row.target_count,
            "strict_count": row.strict_count,
            "relaxed_enabled": row.relaxed_enabled,
            "relaxed_requested": row.relaxed_requested,
            "criteria_gate_keys": json.dumps(list(row.criteria_gate_keys)),
            "status": row.status,
            "webset_id": row.webset_id,
            "strict_search_id": row.strict_search_id,
            "relaxed_search_id": row.relaxed_search_id,
            "asked": row.asked,
            "found_strict": row.found_strict,
            "found_relaxed": row.found_relaxed,
            "analyzed": row.analyzed,
            "recall_estimate": row.recall_estimate,
            "receipt": _dump_json(row.receipt) if row.receipt is not None else None,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
        },
    )
    return result.rowcount == 1


async def find_discovery_run(
    conn: AsyncConnection, *, workspace_id: str, request_sha256: str
) -> DiscoveryRunRow | None:
    """The run a request already made, if any — the replay lookup a re-launch does first."""
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_RUN_COLUMNS} FROM arv2_discovery_run "
                    "WHERE workspace_id = :workspace_id AND request_sha256 = :request_sha256"
                ),
                {"workspace_id": workspace_id, "request_sha256": request_sha256},
            )
        )
        .mappings()
        .first()
    )
    return _run(row) if row is not None else None


async def read_discovery_run(conn: AsyncConnection, *, run_id: UUID) -> DiscoveryRunRow | None:
    row = (
        (
            await conn.execute(
                text(f"SELECT {_RUN_COLUMNS} FROM arv2_discovery_run WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
        )
        .mappings()
        .first()
    )
    return _run(row) if row is not None else None


async def begin_discovery_run(conn: AsyncConnection, *, run_id: UUID) -> DiscoveryRunRow | None:
    """Claim a run for this attempt: ``not_started``/``suspended`` → ``in_progress``.

    Guarded on those two statuses so a re-delivered fleet task can neither restart a run another
    worker is driving nor revive a finished one; ``None`` says "not mine to run", which is a normal
    outcome of a redelivery, not an error.
    """
    row = (
        (
            await conn.execute(
                text(
                    f"UPDATE arv2_discovery_run SET status = 'in_progress', started_at = now() "
                    f"WHERE run_id = :run_id AND status IN ('not_started', 'suspended') "
                    f"RETURNING {_RUN_COLUMNS}"
                ),
                {"run_id": run_id},
            )
        )
        .mappings()
        .first()
    )
    return _run(row) if row is not None else None


async def request_relaxed(conn: AsyncConnection, *, run_id: UUID) -> bool:
    """Reopen a finished run for the §4 relaxed pass on the human's request. Returns whether it was.

    Guarded on the two finished statuses so this cannot disturb a run that is still driving; the
    run goes back to ``not_started`` so the ordinary claim path picks it up, and
    ``relaxed_requested`` tells the driver it is resuming for the relaxed pass rather than
    re-running the strict one.
    """
    result = await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET status = 'not_started', relaxed_requested = true "
            "WHERE run_id = :run_id AND status IN ('completed', 'needs_review')"
        ),
        {"run_id": run_id},
    )
    return result.rowcount == 1


async def suspend_discovery_run(conn: AsyncConnection, *, run_id: UUID) -> None:
    """Park a run for requeue (a lost lease, a stop request).

    Guarded off the terminal statuses so the requeue path can never walk a finished run back into
    the queue.
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET status = 'suspended' "
            "WHERE run_id = :run_id AND status NOT IN ('completed', 'needs_review')"
        ),
        {"run_id": run_id},
    )


async def record_webset(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    webset_id: str,
    asked: int,
    recall_estimate: int | None,
    strict_search_id: str | None,
) -> None:
    """Record the long list this run is reading from, before any of it is verified.

    Written as its own transition rather than folded into the finish, so a run that dies mid-verify
    resumes against the webset it already paid to create instead of making a second one. The strict
    search's id rides along for the same reason one level down: a webset holds searches, and a
    resumed attempt that cannot name the strict one has to guess it by array position — which the
    provider never promised — and then excludes the wrong search when it widens.
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET webset_id = :webset_id, asked = :asked, "
            " recall_estimate = :recall_estimate, strict_search_id = :strict_search_id "
            "WHERE run_id = :run_id"
        ),
        {
            "webset_id": webset_id,
            "asked": int(asked),
            "recall_estimate": None if recall_estimate is None else int(recall_estimate),
            "strict_search_id": strict_search_id,
            "run_id": run_id,
        },
    )


async def record_relaxed_search(
    conn: AsyncConnection, *, run_id: UUID, relaxed_search_id: str
) -> None:
    """Record the widening search the §4 relaxed pass bought — the "never buy it twice" fact.

    Written the moment ``add_search`` returns, before any of its results are read, so an attempt
    that dies between the two resumes by *reading* the search it already paid for. Without it a
    redelivered relaxed request calls ``add_search`` again, excluding only the strict search, and
    Exa re-finds and re-charges for everything the first widening already returned.
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET relaxed_search_id = :relaxed_search_id "
            "WHERE run_id = :run_id"
        ),
        {"relaxed_search_id": relaxed_search_id, "run_id": run_id},
    )


async def record_discovery_progress(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    found_strict: int,
    found_relaxed: int,
    analyzed: int,
) -> None:
    """The §4 counters as they stand mid-run, written on every poll tick (spec 2026-09-12 §2).

    Only the numbers move, and only forward. ``GREATEST`` makes the durable counters monotonic in
    SQL, so a zombie attempt's late tick cannot walk them backwards for a tick — a guarantee that
    holds whoever writes and whatever the status happens to be. (The columns are nullable, hence
    the ``COALESCE``: a run that has never ticked starts from 0, not from NULL.) Status, the
    receipt and ``finished_at`` belong to :func:`finish_discovery_run`, so a reader that sees
    counters climbing on an ``in_progress`` row is watching a run, not a run that landed twice.
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run "
            "SET found_strict = GREATEST(COALESCE(found_strict, 0), :found_strict), "
            " found_relaxed = GREATEST(COALESCE(found_relaxed, 0), :found_relaxed), "
            " analyzed = GREATEST(COALESCE(analyzed, 0), :analyzed) WHERE run_id = :run_id"
        ),
        {
            "found_strict": int(found_strict),
            "found_relaxed": int(found_relaxed),
            "analyzed": int(analyzed),
            "run_id": run_id,
        },
    )


async def finish_discovery_run(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    status: DiscoveryStatus,
    found_strict: int,
    found_relaxed: int,
    analyzed: int,
    receipt: Mapping[str, Any],
) -> None:
    """Land a run with its §4 counters and its receipt.

    The counters are the honest record of a short list: how many each pass found and how many
    companies were analyzed to get there, so "we found 15 of the 20 you asked for" is a number a
    human can act on rather than a silence.
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET status = :status, found_strict = :found_strict, "
            " found_relaxed = :found_relaxed, analyzed = :analyzed, "
            " receipt_json = CAST(:receipt AS jsonb), finished_at = now() WHERE run_id = :run_id"
        ),
        {
            "status": status,
            "found_strict": int(found_strict),
            "found_relaxed": int(found_relaxed),
            "analyzed": int(analyzed),
            "receipt": _dump_json(receipt),
            "run_id": run_id,
        },
    )


async def upsert_candidate(conn: AsyncConnection, row: CandidateRow) -> UUID:
    """Record one company of the long list; returns the candidate id that now holds that domain.

    The domain is unique per run, so a company the provider returns twice (a re-listed page, a
    resumed run re-reading the same webset) refreshes the snapshot it already has rather than
    landing twice. The returned id is the *existing* row's when there was one, which is what makes
    the caller's follow-up :func:`record_verdicts` address the right candidate.

    The verdicts and the decision are deliberately not touched here: a resumed run must not undo
    the verification it already paid for, or a human's approval.
    """
    result = await conn.execute(
        text(
            f"INSERT INTO arv2_discovery_candidate ({_CANDIDATE_COLUMNS}) VALUES ("
            " :candidate_id, :run_id, :workspace_id, :project_id, :pass, :domain, :websets_url, "
            " :name, CAST(:provider_snapshot AS jsonb), CAST(:verdicts AS jsonb), :fit, "
            " :disposition, :decision, :decided_by_user_id, :decided_at, :account_entity_id) "
            "ON CONFLICT (run_id, domain) DO UPDATE SET "
            " provider_snapshot_json = EXCLUDED.provider_snapshot_json, name = EXCLUDED.name, "
            " websets_url = EXCLUDED.websets_url "
            "RETURNING candidate_id"
        ),
        {
            "candidate_id": row.candidate_id,
            "run_id": row.run_id,
            "workspace_id": row.workspace_id,
            "project_id": row.project_id,
            "pass": row.pass_,
            "domain": row.domain,
            "websets_url": row.websets_url,
            "name": row.name,
            "provider_snapshot": _dump_json(row.provider_snapshot),
            "verdicts": json.dumps([dict(v) for v in row.verdicts], sort_keys=True, default=str),
            "fit": row.fit,
            "disposition": row.disposition,
            "decision": row.decision,
            "decided_by_user_id": row.decided_by_user_id,
            "decided_at": row.decided_at,
            "account_entity_id": row.account_entity_id,
        },
    )
    return UUID(str(result.scalar_one()))


async def record_verdicts(
    conn: AsyncConnection,
    *,
    candidate_id: UUID,
    verdicts: Sequence[Mapping[str, Any]],
    fit: float | None,
    disposition: Disposition,
    account_entity_id: UUID | None,
) -> None:
    """Store one candidate's per-gate verdicts, the fit derived from them, and what it turned out
    to be — plus the account it became, once the writer has made one."""
    await conn.execute(
        text(
            "UPDATE arv2_discovery_candidate SET verdicts_json = CAST(:verdicts AS jsonb), "
            " fit = :fit, disposition = :disposition, account_entity_id = :account_entity_id "
            "WHERE candidate_id = :candidate_id"
        ),
        {
            "verdicts": json.dumps([dict(v) for v in verdicts], sort_keys=True, default=str),
            "fit": fit,
            "disposition": disposition,
            "account_entity_id": account_entity_id,
            "candidate_id": candidate_id,
        },
    )


async def list_candidates(conn: AsyncConnection, *, run_id: UUID) -> tuple[CandidateRow, ...]:
    """Every candidate of a run, oldest first — the order the long list returned them in."""
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_CANDIDATE_COLUMNS} FROM arv2_discovery_candidate "
                    "WHERE run_id = :run_id ORDER BY created_at, candidate_id"
                ),
                {"run_id": run_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(_candidate(row) for row in rows)


async def unapproved_domains(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, before_run_id: UUID
) -> frozenset[str]:
    """Domains an earlier run of this project surfaced and the human did not approve.

    Not a rejection list (ruling 1′): these are companies already shown once, so a later run does
    not spend on them again and does not re-ask the same human the same question. The current run
    is excluded so a run never hides its own candidates from itself.
    """
    rows = await conn.execute(
        text(
            "SELECT DISTINCT domain FROM arv2_discovery_candidate "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            "AND run_id <> :before_run_id AND decision IS NULL "
            f"AND disposition IN {_LIVE_DISPOSITIONS}"
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "before_run_id": before_run_id,
        },
    )
    return frozenset(str(row[0]) for row in rows)


async def mark_candidates_approved(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    account_entity_ids: Sequence[UUID],
    decided_by_user_id: str,
) -> int:
    """Stamp the human's approval on the candidates behind an "Add to project" bulk action.

    Addressed by account id, because the accounts table is the approval surface (§5) and that is
    what it ticks. The only decision this substrate can write: ``decision IS NULL`` guards it so a
    second bulk action over an overlapping selection re-stamps nobody's earlier decision, and the
    returned count is how many rows this action actually decided.
    """
    result = await conn.execute(
        text(
            "UPDATE arv2_discovery_candidate SET decision = 'approved', "
            " decided_by_user_id = :decided_by_user_id, decided_at = now() "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            " AND account_entity_id = ANY(:account_entity_ids) AND decision IS NULL"
        ),
        {
            "decided_by_user_id": decided_by_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "account_entity_ids": list(account_entity_ids),
        },
    )
    return int(result.rowcount)


def _dump_json(payload: Mapping[str, Any]) -> str:
    """A payload as jsonb text. ``default=str`` so a Decimal or a datetime a provider snapshot
    carries is stored rather than raising at the last step of a run."""
    return json.dumps(dict(payload), sort_keys=True, default=str)


def _run(row: RowMapping) -> DiscoveryRunRow:
    gate_keys = decode_jsonb(row["criteria_gate_keys"]) or []
    return DiscoveryRunRow(
        run_id=row["run_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        brand_id=row["brand_id"],
        project_run_id=row["project_run_id"],
        icp_artifact_key=row["icp_artifact_key"],
        icp_artifact_sha256=row["icp_artifact_sha256"],
        icp_key=row["icp_key"],
        icp_version=row["icp_version"],
        requested_by_user_id=row["requested_by_user_id"],
        request_sha256=row["request_sha256"],
        target_count=row["target_count"],
        strict_count=row["strict_count"],
        relaxed_enabled=row["relaxed_enabled"],
        criteria_gate_keys=tuple(str(key) for key in gate_keys),
        status=row["status"],
        relaxed_requested=row["relaxed_requested"],
        webset_id=row["webset_id"],
        strict_search_id=row["strict_search_id"],
        relaxed_search_id=row["relaxed_search_id"],
        asked=row["asked"],
        found_strict=row["found_strict"],
        found_relaxed=row["found_relaxed"],
        analyzed=row["analyzed"],
        recall_estimate=row["recall_estimate"],
        receipt=decode_jsonb(row["receipt_json"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _candidate(row: RowMapping) -> CandidateRow:
    verdicts = decode_jsonb(row["verdicts_json"]) or []
    return CandidateRow(
        candidate_id=row["candidate_id"],
        run_id=row["run_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        pass_=row["pass"],
        domain=row["domain"],
        websets_url=row["websets_url"],
        name=row["name"],
        provider_snapshot=decode_jsonb(row["provider_snapshot_json"]) or {},
        verdicts=tuple(verdicts),
        # ``numeric(4,3)`` comes back as a Decimal; the fit is a ratio every reader compares and
        # bands as a float (the accounts list's own thresholds are floats).
        fit=None if row["fit"] is None else float(row["fit"]),
        disposition=row["disposition"],
        decision=row["decision"],
        decided_by_user_id=row["decided_by_user_id"],
        decided_at=row["decided_at"],
        account_entity_id=row["account_entity_id"],
    )
