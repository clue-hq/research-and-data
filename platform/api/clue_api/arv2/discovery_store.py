"""Row transitions of the R4 discovery substrate (``2cd622be2da0``; spec §5–§6).

One function per transition, each honouring the CHECKs the migration installed. Two tables, and
each one exists for a reason the spec names:

``arv2_discovery_run`` is a launch record pinned to the ICP document the human asked against, so a
redelivered fleet task replays the same request rather than paying for a second long list —
:func:`find_discovery_run` is that replay lookup, keyed on the request sha the launch computed.
Its counters (``asked`` / ``found_strict`` / ``found_relaxed`` / ``analyzed`` /
``recall_estimate``) are the §4 "a short list is information, never padded" record: a run that
exhausts the pool says so with numbers instead of quietly returning fewer companies.

``arv2_discovery_search`` is one webset the run bought — up to three, in order (founder rulings
2026-09-28): the strict search for exactly the target, a strict top-up for what our checks
removed, a relaxed search for what is still missing. Each row is written **before** its webset is
created, under the ``externalId`` it sends, so a crashed attempt finds its webset again instead of
buying another (:func:`create_search`).

``arv2_discovery_candidate`` is one company, keyed by its verified domain inside its run, with the
per-gate verdicts and the fit derived from them.

**Unapproved is not rejected** (ruling 1′, rev 5). Nothing here can mark a candidate rejected;
:func:`mark_candidates_approved` is the only decision write, and it only ever writes ``approved``.
A later run of the same project skips every company an earlier one found
(:func:`project_found_domains`, stamped ``found_before``) — whatever the human did with it.

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
from clue_research.identity.normalize import registrable_domain

__all__ = [
    "PENDING_DISPOSITION",
    "SHOWN_DISPOSITIONS",
    "VERIFIED_PREDICATE",
    "CandidateRow",
    "Disposition",
    "DiscoveryRunRow",
    "DiscoveryStatus",
    "Pass",
    "SearchKind",
    "SearchRow",
    "active_discoveries_for_threads",
    "active_discovery_for_project",
    "begin_discovery_run",
    "create_discovery_run",
    "create_search",
    "end_discovery_run",
    "find_discovery_run",
    "finish_discovery_run",
    "finish_search",
    "list_candidates",
    "list_searches",
    "mark_candidates_approved",
    "project_found_domains",
    "project_webset_ids",
    "read_discovery_run",
    "record_discovery_progress",
    "record_search_webset",
    "record_verdicts",
    "record_wake_turn",
    "release_discovery_for_turn",
    "request_discovery_stop",
    "stop_requested",
    "suspend_discovery_run",
    "upsert_candidate",
]

#: The seam-1 states, verbatim — the same vocabulary the R2 runs and jobs carry — plus
#: ``stopped``: a human pressed Stop and the run ended early with what it had already verified.
DiscoveryStatus = Literal[
    "not_started", "in_progress", "needs_review", "completed", "suspended", "stopped"
]

#: Which §4 pass a candidate came from: the full criteria (the strict search and its top-up), or
#: the relaxed search.
Pass = Literal["strict", "relaxed"]

#: The searches a run may make. ``strict``/``strict_topup``/``relaxed`` are the three searches of a
#: run launched from a compiled brief (``launch_arv2_discovery@1``); ``round`` is one round of a run
#: launched from the brief the agent wrote (``@2``): round 1, then top-ups with the same brief.
SearchKind = Literal["strict", "strict_topup", "relaxed", "round"]

#: What a verified candidate *is*, never what it was refused for. ``duplicate_of_existing`` is a
#: company already among this project's accounts; ``found_before`` is one an earlier discovery run
#: of this project already found. Both are stamped before any gate is asked. ``excluded`` is a
#: company a ``must`` gate failed or a ``must_not`` gate passed: kept on the run with the gate that
#: excluded it (``excluded_by_gate``), never added to the project's accounts and never shown.
#: ``excluded_by_brief`` is a company the brief's ``exclude`` list (or the seller's own domain)
#: named, stamped before any spend with the entry that matched it (``excluded_by_entry``; spec
#: 2026-10-16-discovery-excludes-seller-customers §4.6).
Disposition = Literal[
    "pending",
    "pass",
    "partial",
    "unclear",
    "duplicate_of_existing",
    "found_before",
    "excluded",
    "excluded_by_brief",
]

#: The dispositions that mean the human was shown this company — §4's *shown*, and equally the
#: candidates a later run still remembers as "seen but not chosen". A duplicate is already an
#: account, and a pending one was never verified, so neither is re-surfacing news.
#:
#: Public because it is the lane's vocabulary, not this module's: anything that counts or reports
#: candidates (``status.md``'s discovery section, the driver's own tally) reads it from here
#: instead of re-typing the three words into its own SQL.
SHOWN_DISPOSITIONS: tuple[str, ...] = ("pass", "partial", "unclear")

#: A candidate nothing has verified yet.
PENDING_DISPOSITION = "pending"

#: What "verified" MEANS, in one place: the verifier actually judged this company.
#:
#: It used to be the complement of ``pending``, and that was wrong in a way nobody could see from
#: the number. ``_pre_spend_disposition`` stamps ``duplicate_of_existing`` and ``found_before``
#: **before any gate is asked** — those candidates cost the one website answer that identified them
#: and were never checked against the ICP — so "not pending" counted them as verified and the agent
#: told the founder the platform had checked companies it had skipped. A verdict row is the only
#: thing that proves a judgement happened, so the verdict array is the test.
#:
#: A SQL fragment rather than a helper because its three readers (the chat read, ``status.md`` and
#: the Target-accounts tab's poll) each embed it in a different statement; they alias the candidate
#: table ``c`` so one definition serves all three and the three numbers cannot drift apart.
VERIFIED_PREDICATE = "jsonb_array_length(c.verdicts_json) > 0"

_RUN_COLUMNS = (
    "run_id, workspace_id, project_id, brand_id, project_run_id, icp_artifact_key, "
    "icp_artifact_sha256, icp_key, icp_version, requested_by_user_id, request_sha256, "
    "target_count, relaxed_enabled, criteria_gate_keys, status, asked, found_strict, "
    "found_relaxed, analyzed, recall_estimate, receipt_json, created_at, started_at, finished_at, "
    "source, brief_json, launched_thread_id, launching_turn_id, end_reason, summary_json, "
    "stop_requested_at, wake_turn_id, released_at"
)

_SEARCH_COLUMNS = (
    "run_id, ordinal, kind, external_id, webset_id, asked, criteria, exclude_webset_ids, found, "
    "analyzed, recall_estimate, finished_at, source"
)

_CANDIDATE_COLUMNS = (
    "candidate_id, run_id, workspace_id, project_id, pass, domain, websets_url, name, "
    "provider_snapshot_json, verdicts_json, fit, disposition, decision, decided_by_user_id, "
    "decided_at, account_entity_id, excluded_by_gate, excluded_by_entry"
)


@dataclass(frozen=True)
class DiscoveryRunRow:
    """One launched discovery request, with what it was pinned to and what it found.

    The pins (the ICP artifact key and its sha, the ICP key/version, the request sha) are what make
    a run replayable against exactly the document a human asked against. ``criteria_gate_keys`` is
    the gate set the verifier must answer for every candidate, recorded at launch so a run that
    resumes after a restart grades on the same gates it started on.

    ``brief`` is the whole brief the Head of ABM wrote (query, criteria, gates) and ``source`` the
    search it chose. The lock and wake fields: a run is *active* — holding its project and its
    launching thread — until ``released_at`` is set. It ends (``finished_at``, ``end_reason``,
    ``summary``) and is then released either at once or, when a wake turn was queued in the
    launching thread (``wake_turn_id``), when that turn finishes.
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
    relaxed_enabled: bool
    criteria_gate_keys: tuple[str, ...]
    status: DiscoveryStatus = "not_started"
    #: How many companies the run's searches asked Exa for, all searches together.
    asked: int | None = None
    found_strict: int | None = None
    found_relaxed: int | None = None
    analyzed: int | None = None
    recall_estimate: int | None = None
    receipt: Mapping[str, Any] | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    source: str = "websets"
    brief: Mapping[str, Any] | None = None
    launched_thread_id: str | None = None
    launching_turn_id: UUID | None = None
    end_reason: str | None = None
    summary: Mapping[str, Any] | None = None
    stop_requested_at: datetime | None = None
    wake_turn_id: UUID | None = None
    released_at: datetime | None = None


@dataclass(frozen=True)
class SearchRow:
    """One webset a run bought, in the order it bought them (``ordinal`` 1–3).

    ``webset_id`` is ``None`` between writing the row and Exa answering the create: a resumed
    attempt then looks the webset up by ``external_id`` before creating anything. ``finished_at``
    set means the webset went idle and every company it found was verified — a resumed attempt
    skips it. ``criteria`` and ``exclude_webset_ids`` are exactly what the search sent.
    """

    run_id: UUID
    ordinal: int
    kind: SearchKind
    external_id: str
    asked: int
    criteria: tuple[str, ...]
    exclude_webset_ids: tuple[str, ...] = ()
    webset_id: str | None = None
    found: int | None = None
    analyzed: int | None = None
    recall_estimate: int | None = None
    finished_at: datetime | None = None
    source: str = "websets"


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
    excluded_by_gate: str | None = None
    excluded_by_entry: str | None = None


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
            " :request_sha256, :target_count, :relaxed_enabled, "
            " CAST(:criteria_gate_keys AS jsonb), :status, "
            " :asked, :found_strict, :found_relaxed, :analyzed, :recall_estimate, "
            " CAST(:receipt AS jsonb), COALESCE(:created_at, now()), :started_at, :finished_at, "
            " :source, CAST(:brief AS jsonb), :launched_thread_id, :launching_turn_id, "
            " :end_reason, CAST(:summary AS jsonb), :stop_requested_at, :wake_turn_id, "
            " :released_at) "
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
            "relaxed_enabled": row.relaxed_enabled,
            "criteria_gate_keys": json.dumps(list(row.criteria_gate_keys)),
            "status": row.status,
            "asked": row.asked,
            "found_strict": row.found_strict,
            "found_relaxed": row.found_relaxed,
            "analyzed": row.analyzed,
            "recall_estimate": row.recall_estimate,
            "receipt": _dump_json(row.receipt) if row.receipt is not None else None,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "source": row.source,
            "brief": _dump_json(row.brief) if row.brief is not None else None,
            "launched_thread_id": row.launched_thread_id,
            "launching_turn_id": row.launching_turn_id,
            "end_reason": row.end_reason,
            "summary": _dump_json(row.summary) if row.summary is not None else None,
            "stop_requested_at": row.stop_requested_at,
            "wake_turn_id": row.wake_turn_id,
            "released_at": row.released_at,
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


async def suspend_discovery_run(conn: AsyncConnection, *, run_id: UUID) -> None:
    """Park a run for requeue (a lost lease, a stop request).

    Guarded off the terminal statuses so the requeue path can never walk a finished run back into
    the queue.
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET status = 'suspended' "
            "WHERE run_id = :run_id AND status NOT IN ('completed', 'needs_review', 'stopped')"
        ),
        {"run_id": run_id},
    )


async def create_search(conn: AsyncConnection, row: SearchRow) -> SearchRow:
    """Record a search the run is about to buy, BEFORE its webset is created; return the row held.

    ``(run_id, ordinal)`` is the key, so an attempt that died after writing the row gets the row it
    already wrote back — with its ``external_id``, its criteria and its exclusions — rather than a
    second search. The run's ``asked`` is kept as the sum of its searches' asks in the same
    statement pair, so it never counts one search twice.
    """
    await conn.execute(
        text(
            "INSERT INTO arv2_discovery_search (run_id, ordinal, kind, external_id, asked, "
            " criteria, exclude_webset_ids, source) VALUES (:run_id, :ordinal, :kind, "
            " :external_id, :asked, CAST(:criteria AS jsonb), CAST(:exclude AS jsonb), :source) "
            "ON CONFLICT (run_id, ordinal) DO NOTHING"
        ),
        {
            "run_id": row.run_id,
            "ordinal": row.ordinal,
            "kind": row.kind,
            "external_id": row.external_id,
            "asked": int(row.asked),
            "criteria": json.dumps(list(row.criteria)),
            "exclude": json.dumps(list(row.exclude_webset_ids)),
            "source": row.source,
        },
    )
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET asked = (SELECT sum(asked) FROM arv2_discovery_search "
            " WHERE run_id = :run_id) WHERE run_id = :run_id"
        ),
        {"run_id": row.run_id},
    )
    held = (
        (
            await conn.execute(
                text(
                    f"SELECT {_SEARCH_COLUMNS} FROM arv2_discovery_search "
                    "WHERE run_id = :run_id AND ordinal = :ordinal"
                ),
                {"run_id": row.run_id, "ordinal": row.ordinal},
            )
        )
        .mappings()
        .one()
    )
    return _search(held)


async def record_search_webset(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    ordinal: int,
    webset_id: str,
    recall_estimate: int | None,
) -> None:
    """Record the webset Exa created for a search, before any of it is read.

    The first search's recall estimate is also the run's: it is the one search that asks for it,
    and it is what tells "Exa ran out" apart from "our checks removed some".
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_search SET webset_id = :webset_id, "
            " recall_estimate = COALESCE(:recall_estimate, recall_estimate) "
            "WHERE run_id = :run_id AND ordinal = :ordinal"
        ),
        {
            "webset_id": webset_id,
            "recall_estimate": None if recall_estimate is None else int(recall_estimate),
            "run_id": run_id,
            "ordinal": ordinal,
        },
    )
    if ordinal == 1 and recall_estimate is not None:
        await conn.execute(
            text("UPDATE arv2_discovery_run SET recall_estimate = :recall WHERE run_id = :run_id"),
            {"recall": int(recall_estimate), "run_id": run_id},
        )


async def finish_search(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    ordinal: int,
    found: int,
    analyzed: int | None,
    recall_estimate: int | None,
) -> None:
    """Close a search: its webset is idle and every company it found has been verified."""
    await conn.execute(
        text(
            "UPDATE arv2_discovery_search SET found = :found, analyzed = :analyzed, "
            " recall_estimate = COALESCE(:recall_estimate, recall_estimate), finished_at = now() "
            "WHERE run_id = :run_id AND ordinal = :ordinal"
        ),
        {
            "found": int(found),
            "analyzed": None if analyzed is None else int(analyzed),
            "recall_estimate": None if recall_estimate is None else int(recall_estimate),
            "run_id": run_id,
            "ordinal": ordinal,
        },
    )
    if ordinal == 1 and recall_estimate is not None:
        await conn.execute(
            text("UPDATE arv2_discovery_run SET recall_estimate = :recall WHERE run_id = :run_id"),
            {"recall": int(recall_estimate), "run_id": run_id},
        )


async def list_searches(conn: AsyncConnection, *, run_id: UUID) -> tuple[SearchRow, ...]:
    """Every search of a run, in the order it made them."""
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_SEARCH_COLUMNS} FROM arv2_discovery_search "
                    "WHERE run_id = :run_id ORDER BY ordinal"
                ),
                {"run_id": run_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(_search(row) for row in rows)


async def project_webset_ids(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, before_run_id: UUID
) -> tuple[str, ...]:
    """Every webset an earlier discovery run of this project bought — what a new run tells Exa to
    skip, so "find more" never finds (or pays for) the same companies again (ruling 2026-09-28)."""
    rows = await conn.execute(
        text(
            "SELECT s.webset_id "
            "FROM arv2_discovery_search s JOIN arv2_discovery_run r ON r.run_id = s.run_id "
            "WHERE r.workspace_id = :workspace_id AND r.project_id = :project_id "
            " AND r.run_id <> :before_run_id AND s.webset_id IS NOT NULL "
            "GROUP BY s.webset_id ORDER BY min(s.created_at), s.webset_id"
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "before_run_id": before_run_id,
        },
    )
    return tuple(str(row[0]) for row in rows)


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


#: A run holds its project and its launching thread until it is released (spec 2026-09-30 §5).
#: The partial unique index ``arv2_discovery_run_project_active`` is keyed on this same predicate,
#: so two simultaneous launches in one project cannot both insert.
_ACTIVE = "released_at IS NULL"


async def active_discovery_for_project(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> DiscoveryRunRow | None:
    """The project's unreleased discovery run, if any — the one a new launch is refused over."""
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_RUN_COLUMNS} FROM arv2_discovery_run "
                    f"WHERE workspace_id = :w AND project_id = :p AND {_ACTIVE}"
                ),
                {"w": workspace_id, "p": project_id},
            )
        )
        .mappings()
        .first()
    )
    return None if row is None else _run(row)


async def active_discoveries_for_threads(
    conn: AsyncConnection, *, workspace_id: str, thread_ids: Sequence[str]
) -> dict[str, DiscoveryRunRow]:
    """The unreleased discovery run each of these threads launched, keyed by thread id.

    A thread in this map is busy: a turn submitted to it is held until the run's wake turn ends.
    """
    if not thread_ids:
        return {}
    rows = (
        await conn.execute(
            text(
                f"SELECT {_RUN_COLUMNS} FROM arv2_discovery_run WHERE workspace_id = :w "
                f"AND launched_thread_id = ANY(:t) AND {_ACTIVE}"
            ),
            {"w": workspace_id, "t": list(thread_ids)},
        )
    ).mappings()
    return {str(r["launched_thread_id"]): _run(r) for r in rows}


async def request_discovery_stop(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, run_id: UUID
) -> DiscoveryRunRow | None:
    """Record a human's Stop on an active run; the driver reads it and ends the run ``stopped``.

    The first request's time is kept (``COALESCE``), so a second press changes nothing. ``None``
    when the run is not this project's.
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET stop_requested_at = COALESCE(stop_requested_at, now()) "
            f"WHERE run_id = :r AND workspace_id = :w AND project_id = :p AND {_ACTIVE}"
        ),
        {"r": run_id, "w": workspace_id, "p": project_id},
    )
    run = await read_discovery_run(conn, run_id=run_id)
    if run is None or run.workspace_id != workspace_id or run.project_id != project_id:
        return None
    return run


async def stop_requested(conn: AsyncConnection, *, run_id: UUID) -> bool:
    """Whether a human asked this run to stop — the check the driver makes between steps."""
    value = await conn.scalar(
        text("SELECT stop_requested_at IS NOT NULL FROM arv2_discovery_run WHERE run_id = :r"),
        {"r": run_id},
    )
    return bool(value)


async def end_discovery_run(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    status: DiscoveryStatus,
    end_reason: str,
    summary: Mapping[str, Any],
    release: bool,
) -> None:
    """End a run with why it ended and its summary; release its locks now when ``release``.

    A run that queued a wake turn in its launching thread ends with ``release=False``: the project
    and the thread stay held until that turn finishes (:func:`release_discovery_for_turn`).
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_run SET status = :s, end_reason = :e, "
            "summary_json = CAST(:j AS jsonb), finished_at = COALESCE(finished_at, now()), "
            "released_at = CASE WHEN :rel THEN now() ELSE released_at END WHERE run_id = :r"
        ),
        {"s": status, "e": end_reason, "j": _dump_json(summary), "rel": release, "r": run_id},
    )


async def record_wake_turn(conn: AsyncConnection, *, run_id: UUID, wake_turn_id: UUID) -> None:
    """Record the derived turn that tells the launching thread the run ended."""
    await conn.execute(
        text("UPDATE arv2_discovery_run SET wake_turn_id = :t WHERE run_id = :r"),
        {"t": wake_turn_id, "r": run_id},
    )


async def release_discovery_for_turn(
    conn: AsyncConnection, *, workspace_id: str, turn_id: UUID
) -> UUID | None:
    """Release the run whose wake turn this is, now that the turn has finished.

    Returns the released run's id, or ``None`` when this turn woke no active run.
    """
    released = await conn.scalar(
        text(
            "UPDATE arv2_discovery_run SET released_at = now() WHERE workspace_id = :w "
            f"AND wake_turn_id = :t AND {_ACTIVE} RETURNING run_id"
        ),
        {"w": workspace_id, "t": turn_id},
    )
    return None if released is None else UUID(str(released))


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
            " :disposition, :decision, :decided_by_user_id, :decided_at, :account_entity_id, "
            " :excluded_by_gate, :excluded_by_entry) "
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
            "excluded_by_gate": row.excluded_by_gate,
            "excluded_by_entry": row.excluded_by_entry,
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
    excluded_by_gate: str | None = None,
) -> None:
    """Store one candidate's per-gate verdicts, the fit derived from them, and what it turned out
    to be — plus the account it became, once the writer has made one.

    An ``excluded`` candidate is recorded here too, with the gate that excluded it and no account:
    the row already exists ``pending`` by the time its gates are answered, and
    :func:`upsert_candidate` deliberately leaves an existing row's disposition alone.
    """
    await conn.execute(
        text(
            "UPDATE arv2_discovery_candidate SET verdicts_json = CAST(:verdicts AS jsonb), "
            " fit = :fit, disposition = :disposition, account_entity_id = :account_entity_id, "
            " excluded_by_gate = :excluded_by_gate "
            "WHERE candidate_id = :candidate_id"
        ),
        {
            "verdicts": json.dumps([dict(v) for v in verdicts], sort_keys=True, default=str),
            "fit": fit,
            "disposition": disposition,
            "account_entity_id": account_entity_id,
            "excluded_by_gate": excluded_by_gate,
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


async def project_found_domains(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, before_run_id: UUID
) -> frozenset[str]:
    """Every company an earlier discovery run of this project found, whatever became of it.

    A later run skips these (``found_before``) without asking a gate: they were found once, and a
    company the human has since removed from the project must not come back through discovery.
    The current run is excluded so a run never hides its own candidates from itself. A company a
    brief excluded was never judged, so it is not "found": the next run decides from its own
    brief, and a person's correction to the customer page takes effect there.
    """
    rows = await conn.execute(
        text(
            "SELECT DISTINCT domain FROM arv2_discovery_candidate "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            "AND run_id <> :before_run_id "
            "AND disposition NOT IN ('pending', 'excluded_by_brief')"
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "before_run_id": before_run_id,
        },
    )
    return frozenset(str(row[0]) for row in rows)


async def seller_domain(conn: AsyncConnection, *, workspace_id: str, brand_id: str) -> str | None:
    """The seller's own domain as the platform knows it: the ``company_domain`` of the brand's most
    recent completed whole-brand onboarding (spec 2026-10-16 §4.6). ``None`` when the brand was
    never onboarded; discovery then excludes only what its brief names."""
    domain = await conn.scalar(
        text(
            "SELECT company_domain FROM onboarding_run "
            "WHERE workspace_id = :workspace_id AND brand_id = :brand_id AND kind = 'full' "
            "AND status IN ('completed', 'completed_with_gaps') "
            "ORDER BY requested_at DESC LIMIT 1"
        ),
        {"workspace_id": workspace_id, "brand_id": brand_id},
    )
    return (registrable_domain(str(domain)) or None) if domain else None


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
        relaxed_enabled=row["relaxed_enabled"],
        criteria_gate_keys=tuple(str(key) for key in gate_keys),
        status=row["status"],
        asked=row["asked"],
        found_strict=row["found_strict"],
        found_relaxed=row["found_relaxed"],
        analyzed=row["analyzed"],
        recall_estimate=row["recall_estimate"],
        receipt=decode_jsonb(row["receipt_json"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        source=row["source"],
        brief=decode_jsonb(row["brief_json"]),
        launched_thread_id=row["launched_thread_id"],
        launching_turn_id=row["launching_turn_id"],
        end_reason=row["end_reason"],
        summary=decode_jsonb(row["summary_json"]),
        stop_requested_at=row["stop_requested_at"],
        wake_turn_id=row["wake_turn_id"],
        released_at=row["released_at"],
    )


def _search(row: RowMapping) -> SearchRow:
    return SearchRow(
        run_id=row["run_id"],
        ordinal=int(row["ordinal"]),
        kind=row["kind"],
        external_id=row["external_id"],
        asked=int(row["asked"]),
        criteria=tuple(str(value) for value in decode_jsonb(row["criteria"]) or []),
        exclude_webset_ids=tuple(
            str(value) for value in decode_jsonb(row["exclude_webset_ids"]) or []
        ),
        webset_id=row["webset_id"],
        found=row["found"],
        analyzed=row["analyzed"],
        recall_estimate=row["recall_estimate"],
        finished_at=row["finished_at"],
        source=row["source"],
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
        excluded_by_gate=row["excluded_by_gate"],
        excluded_by_entry=row["excluded_by_entry"],
    )
