"""The research card's arithmetic (spec 2026-09-12 §2-§3, §6): pure, over job rows.

Nothing here reads a table. The read (``frontend_read/research_progress.py``) loads every job of
the project's runs that are not all terminal — plus runs whose last job finished inside the
linger window — and hands the rows here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

__all__ = [
    "LINGER_S",
    "ProgressAgent",
    "ProgressAttention",
    "ProgressCard",
    "ProgressJob",
    "account_score",
    "fold_progress",
]

TERMINAL = frozenset({"completed", "needs_review", "suspended"})
ATTENTION = frozenset({"needs_review", "suspended"})

#: A finished card stays on screen this long after its last job finished, then disappears.
LINGER_S = 60

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


@dataclass(frozen=True)
class ProgressAgent:
    account_name: str
    stage: str
    subject: Literal["account", "person"]


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
    * ``member_research`` reached → 0.75 + 0.25 × (person jobs terminal ÷ person jobs)
    * a terminal account job that never reached ``member_research`` (no committee) → 1.0
    """
    if account_job.stage is None:
        return 0.0
    index = _STAGE_INDEX.get(account_job.stage, 0)
    if index < 3:
        if account_job.status in TERMINAL:
            return 1.0
        return 0.25 * index
    if not person_jobs:
        return 1.0 if account_job.status in TERMINAL else 0.75
    done = sum(1 for p in person_jobs if p.status in TERMINAL)
    return 0.75 + 0.25 * (done / len(person_jobs))


def _reason(job: ProgressJob) -> str:
    if job.status == "suspended":
        return "paused, waiting for a worker"
    return job.failure_message or "needs review"


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
    accounts = [j for j in jobs if j.subject_type == "account"]
    people_by_account: dict[UUID, list[ProgressJob]] = {}
    for j in jobs:
        if j.subject_type == "person":
            people_by_account.setdefault(j.account_entity_id, []).append(j)

    all_terminal = all(j.status in TERMINAL for j in jobs)
    last_finished = max((j.finished_at for j in jobs if j.finished_at), default=None)
    attention = tuple(
        ProgressAttention(account_name=j.account_name, reason=_reason(j))
        for j in jobs
        if j.status in ATTENTION
    ) + tuple(
        ProgressAttention(account_name=j.account_name, reason="run suspended")
        for j in accounts
        if run_statuses.get(j.run_id) == "suspended" and j.status not in ATTENTION
    )
    lingered_out = last_finished is None or now - last_finished > timedelta(seconds=linger_s)
    if all_terminal and not attention and lingered_out:
        return None

    scores = [account_score(a, people_by_account.get(a.account_entity_id, ())) for a in accounts]
    pct = math.floor(100 * sum(scores) / len(scores) + 0.5) if scores else 0
    running_jobs = sorted(
        (j for j in jobs if j.status == "in_progress"),
        key=lambda j: (j.started_at or now, str(j.job_id)),
    )
    pill: Literal["running", "completed", "needs_attention"]
    if attention:
        pill = "needs_attention"
    elif all_terminal:
        pill = "completed"
    else:
        pill = "running"
    return ProgressCard(
        requested_accounts=len(accounts),
        queued=sum(1 for a in accounts if a.status == "not_started"),
        running=len(running_jobs),
        finished=sum(1 for a in accounts if a.status in TERMINAL),
        progress_pct=100 if all_terminal and not attention else min(pct, 99),
        pill=pill,
        last_finished_at=last_finished,
        agents=tuple(
            ProgressAgent(
                account_name=j.account_name,
                stage=j.stage or "deep_research",
                subject=j.subject_type,
            )
            for j in running_jobs
        ),
        attention=attention,
    )
