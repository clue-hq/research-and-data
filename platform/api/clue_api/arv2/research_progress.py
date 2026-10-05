"""The research card's arithmetic (spec 2026-09-12 §2-§3, §6): pure, over job rows.

Nothing here reads a table. The read (``frontend_read/research_progress.py``) loads every job of
the project's runs that are not all terminal — plus runs whose last job finished inside the
linger window — and hands the rows here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from clue_api.provider_incidents import incident_sentence
from clue_core.provider_failures import parse_failure_code

__all__ = [
    "ATTENTION_LINGER_S",
    "FINISHED",
    "LINGER_S",
    "SETTLED",
    "ProgressAgent",
    "ProgressAttention",
    "ProgressCard",
    "ProgressJob",
    "account_score",
    "fold_progress",
    "person_group_score",
]

#: The two statuses a job can *finish* on (``account_research_store``'s own words). ``suspended``
#: is a PAUSE, not an ending — the driver suspends every in-flight job on a stop request or a lost
#: lease, i.e. on every worker restart — so a paused job must never score as done. Scoring, the
#: "finished" count and the member quarter all read THIS set.
FINISHED = frozenset({"completed", "needs_review"})

#: Everything with nothing left to do right now. Only the "is the whole thing settled" test (the
#: linger rule and the ``completed`` pill) reads this one: a run whose jobs are all paused is not
#: progressing, but it is also not running, and the card should not claim an agent is at work.
SETTLED = frozenset({"completed", "needs_review", "suspended"})

ATTENTION = frozenset({"needs_review", "suspended"})

#: A finished card stays on screen this long after its last job finished, then disappears.
LINGER_S = 60

#: Ruling R11 (provisional, 2026-09-12): a run keeps the card alive through a job that wants a
#: human only this long. Nothing in the system moves a job out of ``needs_review`` and the card
#: has no dismiss control, so an unbounded attention clause pins "Needs attention" above a
#: project's composer forever. The bound lives in the READ's query (the fold sees only the rows
#: the read loaded, so the fold's own "attention never lingers away" rule is unchanged).
ATTENTION_LINGER_S = 24 * 3600

#: The longest failure text the card will show. The driver puts ``outcome.error[:1000]`` on the
#: row — raw model/provider prose — and the card's line is one clipped row.
_REASON_MAX = 140

#: Four equal quarters, in the driver's real order. A stage's quarter is earned when the job has
#: MOVED PAST it (the next stamp landed), except ``member_research``, which fills fractionally.
_STAGE_INDEX = {"deep_research": 0, "synthesis": 1, "committee": 2, "member_research": 3}


@dataclass(frozen=True)
class ProgressJob:
    run_id: UUID
    job_id: UUID
    account_entity_id: UUID
    account_name: str
    subject_type: Literal["account", "person"]
    status: str
    stage: str | None
    started_at: datetime | None
    finished_at: datetime | None
    failure_message: str | None
    #: ``provider_refused:<provider>:<reason>`` / ``provider_failed:…`` when the job died on a
    #: provider that stopped serving us; anything else (or ``None``) leaves the prose alone.
    failure_code: str | None = None
    delivery_stage: str | None = None
    deliverables_ready: bool = False
    delivered_at: datetime | None = None
    subject_name: str | None = None


@dataclass(frozen=True)
class ProgressAgent:
    account_name: str
    stage: str
    subject: Literal["account", "person"]
    subject_name: str | None = None


@dataclass(frozen=True)
class ProgressAttention:
    account_name: str
    reason: str


@dataclass(frozen=True)
class ProgressCard:
    requested_accounts: int
    queued: int
    running: int
    finished: int
    progress_pct: int
    pill: Literal["running", "completed", "needs_attention"]
    last_finished_at: datetime | None
    agents: tuple[ProgressAgent, ...]
    attention: tuple[ProgressAttention, ...]


def account_score(account_job: ProgressJob, person_jobs: Sequence[ProgressJob]) -> float:
    """One account's share of done, 0..1 (spec §3).

    * not yet claimed, or still in ``deep_research`` → 0
    * ``synthesis`` reached → 0.25; ``committee`` reached → 0.5
    * ``member_research`` reached → 0.75 + 0.25 × (person jobs finished ÷ person jobs)
    * a FINISHED account job that never reached ``member_research`` (no committee) → 1.0

    "Finished" is :data:`FINISHED`, never :data:`SETTLED`: a suspended job is paused mid-stage and
    earns the quarters it actually walked, nothing more.
    """
    if account_job.delivery_stage is not None:
        group = [account_job, *person_jobs]
        return sum(delivery_score(j) for j in group) / len(group)
    if account_job.stage is None:
        return 0.0
    index = _STAGE_INDEX.get(account_job.stage, 0)
    if index < 3:
        if account_job.status in FINISHED:
            return 1.0
        return 0.25 * index
    if not person_jobs:
        return 1.0 if account_job.status in FINISHED else 0.75
    done = sum(1 for p in person_jobs if p.status in FINISHED)
    return 0.75 + 0.25 * (done / len(person_jobs))


def person_group_score(person_jobs: Sequence[ProgressJob]) -> float:
    """A person-only group's share of done, 0..1: finished people ÷ people.

    ``launch_arv2_person_research`` creates a run of its own with no account job at all, so there
    are no account quarters to walk — the people ARE the work.
    """
    if not person_jobs:
        return 0.0
    return sum(
        delivery_score(p) if p.delivery_stage is not None else float(p.status in FINISHED)
        for p in person_jobs
    ) / len(person_jobs)


def delivery_score(job: ProgressJob) -> float:
    """Completed milestone fractions, not time estimates or claims about coverage."""
    if job.deliverables_ready:
        return 1.0
    return {
        "researching": 0.0,
        "compiling_findings": 0.25,
        "storing_claims": 0.5,
        "writing_narrative": 0.75,
    }.get(job.delivery_stage or "", 0.0)


def presentation_job(job: ProgressJob) -> ProgressJob:
    if job.delivery_stage is None:
        return job
    if job.deliverables_ready:
        return replace(job, status="completed", finished_at=job.delivered_at or job.finished_at)
    # A terminal execution alone does not establish a usable publication.
    if job.status == "completed":
        return replace(
            job, status="needs_review", failure_message="Research pages are not yet available"
        )
    return job


def _clip(text: str, limit: int = _REASON_MAX) -> str:
    """``text`` at most ``limit`` characters, the tail replaced by a single ellipsis."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


def _reason(job: ProgressJob) -> str:
    """The one line the card shows for a job that wants a human.

    A job killed by a provider that stopped serving us reads as the shared incident sentence
    rather than the provider's raw prose. ``notified`` is always ``False`` here: the fold is pure
    and cannot know whether Sentry was told — the read appends that clause when it finds the open
    incident's event id.
    """
    if job.status == "suspended":
        return "paused, resuming automatically"
    parsed = parse_failure_code(job.failure_code)
    if parsed is not None and job.finished_at is not None:
        provider, kind, reason = parsed
        return incident_sentence(
            provider=provider,
            kind=kind,
            reason=reason,
            since=job.finished_at,
            affected=None,
            unit="jobs",
            notified=False,
        )
    return _clip(job.failure_message or "needs review")


def _dedupe(rows: tuple[ProgressAttention, ...]) -> tuple[ProgressAttention, ...]:
    """One row per ``(account, reason)``, first-seen order: eight failed committee members of one
    account are one thing to look at, not eight identical lines the card rotates through."""
    seen: dict[tuple[str, str], ProgressAttention] = {}
    for row in rows:
        seen.setdefault((row.account_name, row.reason), row)
    return tuple(seen.values())


def fold_progress(
    jobs: Sequence[ProgressJob],
    *,
    run_statuses: Mapping[UUID, str],
    now: datetime,
    linger_s: int = LINGER_S,
) -> ProgressCard | None:
    """Every job of the project's qualifying runs → one card, or ``None`` (spec §2, §6).

    ``progress_pct`` rounds HALF-UP (``floor(x + 0.5)``), never Python's banker's ``round``: a
    mean of 12.5 % shows as 13 %, so the bar never reads lower than the work actually done.
    """
    if not jobs:
        return None
    jobs = [presentation_job(j) for j in jobs]
    accounts = [j for j in jobs if j.subject_type == "account"]
    # Keyed by the RUN as well as the account: the same account researched twice is two separate
    # pieces of work, and one run's people must never be counted against another run's job.
    people_by_account: dict[tuple[UUID, UUID], list[ProgressJob]] = {}
    for j in jobs:
        if j.subject_type == "person":
            people_by_account.setdefault((j.run_id, j.account_entity_id), []).append(j)
    account_keys = {(a.run_id, a.account_entity_id) for a in accounts}
    # ``launch_arv2_person_research`` makes a run with no account job at all. Each such group is a
    # requested "account" of its own, scored on its people (spec §3 covers only the account shape).
    person_only = [people for key, people in people_by_account.items() if key not in account_keys]

    all_settled = all(j.status in SETTLED for j in jobs)
    last_finished = max((j.finished_at for j in jobs if j.finished_at), default=None)
    attention = _dedupe(
        tuple(
            ProgressAttention(account_name=j.account_name, reason=_reason(j))
            for j in jobs
            if j.status in ATTENTION
        )
        + tuple(
            ProgressAttention(account_name=j.account_name, reason="run suspended")
            for j in accounts
            if run_statuses.get(j.run_id) == "suspended"
            and j.status not in ATTENTION
            and not j.deliverables_ready
        )
    )
    lingered_out = last_finished is None or now - last_finished > timedelta(seconds=linger_s)
    if all_settled and not attention and lingered_out:
        return None

    scores = [
        account_score(a, people_by_account.get((a.run_id, a.account_entity_id), ()))
        for a in accounts
    ] + [person_group_score(people) for people in person_only]
    pct = math.floor(100 * sum(scores) / len(scores) + 0.5) if scores else 0
    running_jobs = sorted(
        (j for j in jobs if j.status == "in_progress"),
        key=lambda j: (j.started_at or now, str(j.job_id)),
    )
    pill: Literal["running", "completed", "needs_attention"]
    if attention:
        pill = "needs_attention"
    elif all_settled:
        pill = "completed"
    else:
        pill = "running"
    return ProgressCard(
        requested_accounts=len(accounts) + len(person_only),
        queued=sum(1 for a in accounts if a.status == "not_started")
        + sum(1 for people in person_only if all(p.status == "not_started" for p in people)),
        running=len(running_jobs),
        finished=sum(
            1
            for a in accounts
            if (
                a.deliverables_ready
                and all(
                    p.deliverables_ready
                    for p in people_by_account.get((a.run_id, a.account_entity_id), ())
                )
                if a.delivery_stage is not None
                else a.status in FINISHED
            )
        )
        + sum(
            1
            for people in person_only
            if all(
                p.deliverables_ready if p.delivery_stage is not None else p.status in FINISHED
                for p in people
            )
        ),
        progress_pct=100 if all_settled and not attention else min(pct, 99),
        pill=pill,
        last_finished_at=last_finished,
        agents=tuple(
            ProgressAgent(
                account_name=j.account_name,
                stage=j.delivery_stage or j.stage or "deep_research",
                subject_name=j.subject_name,
                subject=j.subject_type,
            )
            for j in running_jobs
        ),
        attention=attention,
    )
