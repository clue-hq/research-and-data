"""The research progress card's math and pill, as pure functions over job rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from clue_api.arv2.research_progress import (
    LINGER_S,
    ProgressJob,
    account_score,
    fold_progress,
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
RUN = uuid4()


def job(
    name: str,
    *,
    subject: str = "account",
    status: str = "in_progress",
    stage: str | None = "deep_research",
    finished_at: datetime | None = None,
    failure: str | None = None,
    account_id=None,  # noqa: ANN001
) -> ProgressJob:
    return ProgressJob(
        run_id=RUN,
        job_id=uuid4(),
        account_entity_id=account_id or uuid4(),
        account_name=name,
        subject_type=subject,  # type: ignore[arg-type]
        status=status,
        stage=stage,
        started_at=NOW - timedelta(minutes=5) if status != "not_started" else None,
        finished_at=finished_at,
        failure_message=failure,
    )


def test_account_score_walks_the_four_quarters() -> None:
    acc = uuid4()
    assert account_score(job("A", status="not_started", stage=None, account_id=acc), []) == 0
    assert account_score(job("A", stage="deep_research", account_id=acc), []) == 0
    assert account_score(job("A", stage="synthesis", account_id=acc), []) == 0.25
    assert account_score(job("A", stage="committee", account_id=acc), []) == 0.5
    members = [
        job(
            "A",
            subject="person",
            status="completed",
            stage="synthesis",
            account_id=acc,
            finished_at=NOW,
        )
    ]
    members += [job("A", subject="person", status="in_progress", account_id=acc) for _ in range(4)]
    # member_research: 1 of 5 people done → 0.75 + 0.25 * (1/5)
    assert (
        account_score(
            job("A", stage="member_research", status="completed", account_id=acc, finished_at=NOW),
            members,
        )
        == 0.8
    )


def test_no_committee_completes_at_the_committee_quarter() -> None:
    acc = uuid4()
    done = job("A", stage="committee", status="completed", account_id=acc, finished_at=NOW)
    assert account_score(done, []) == 1.0


def test_member_research_with_no_person_jobs_yet_holds_at_three_quarters() -> None:
    acc = uuid4()
    live = job("A", stage="member_research", status="in_progress", account_id=acc)
    assert account_score(live, []) == 0.75
    done = job("A", stage="member_research", status="completed", account_id=acc, finished_at=NOW)
    assert account_score(done, []) == 1.0


def test_fold_sums_every_live_run_and_lists_running_agents_in_start_order() -> None:
    a, b = uuid4(), uuid4()
    other_run = uuid4()
    # Alpha started first; Gamma, on the project's other live run, a minute later. The brief's
    # version gave both the same started_at, which left the order to the random job_id tiebreak.
    jobs = [
        ProgressJob(
            **{
                **job("Alpha", stage="synthesis", account_id=a).__dict__,
                "started_at": NOW - timedelta(minutes=6),
            }
        ),
        job("Beta", status="not_started", stage=None, account_id=b),
        ProgressJob(**{**job("Gamma", stage="committee").__dict__, "run_id": other_run}),
    ]
    card = fold_progress(jobs, run_statuses={RUN: "in_progress", other_run: "in_progress"}, now=NOW)
    assert card is not None
    assert (card.requested_accounts, card.queued, card.running, card.finished) == (3, 1, 2, 0)
    assert card.progress_pct == round(100 * (0.25 + 0 + 0.5) / 3)
    assert card.pill == "running"
    assert [(agent.account_name, agent.stage) for agent in card.agents] == [
        ("Alpha", "synthesis"),
        ("Gamma", "committee"),
    ]


def test_agents_with_the_same_start_time_break_the_tie_on_job_id() -> None:
    """Two workers claiming in the same instant still order deterministically."""
    a, b = uuid4(), uuid4()
    first, second = sorted((uuid4(), uuid4()), key=str)
    jobs = [
        ProgressJob(**{**job("Zulu", account_id=a).__dict__, "job_id": second}),
        ProgressJob(**{**job("Alpha", account_id=b).__dict__, "job_id": first}),
    ]
    card = fold_progress(jobs, run_statuses={RUN: "in_progress"}, now=NOW)
    assert card is not None
    assert [agent.account_name for agent in card.agents] == ["Alpha", "Zulu"]


def test_progress_pct_rounds_half_up_not_to_even() -> None:
    """12.5 % is 13 %, not Python's banker's 12 (controller ruling R6)."""
    a, b = uuid4(), uuid4()
    jobs = [
        job("Alpha", stage="synthesis", account_id=a),
        job("Beta", status="not_started", stage=None, account_id=b),
    ]
    card = fold_progress(jobs, run_statuses={RUN: "in_progress"}, now=NOW)
    assert card is not None
    assert card.progress_pct == 13


def test_progress_caps_at_99_until_every_job_is_terminal() -> None:
    acc = uuid4()
    jobs = [
        # the account's own quarters are all earned, but the account job is still live
        job("A", stage="member_research", status="in_progress", account_id=acc),
        job(
            "A",
            subject="person",
            status="completed",
            stage="synthesis",
            account_id=acc,
            finished_at=NOW,
        ),
    ]
    card = fold_progress(jobs, run_statuses={RUN: "in_progress"}, now=NOW)
    assert card is not None
    assert account_score(jobs[0], [jobs[1]]) == 1.0
    assert card.progress_pct == 99
    assert card.pill == "running"


def test_completed_lingers_then_disappears() -> None:
    acc = uuid4()
    done = job(
        "A",
        stage="committee",
        status="completed",
        account_id=acc,
        finished_at=NOW - timedelta(seconds=30),
    )
    card = fold_progress([done], run_statuses={RUN: "completed"}, now=NOW)
    assert card is not None and card.pill == "completed" and card.progress_pct == 100
    assert (
        fold_progress([done], run_statuses={RUN: "completed"}, now=NOW + timedelta(seconds=61))
        is None
    )


def test_linger_window_is_sixty_seconds() -> None:
    assert LINGER_S == 60
    acc = uuid4()
    done = job("A", stage="committee", status="completed", account_id=acc, finished_at=NOW)
    # default linger_s is LINGER_S: still there at 60 s, gone just after
    assert (
        fold_progress([done], run_statuses={RUN: "completed"}, now=NOW + timedelta(seconds=60))
        is not None
    )
    assert (
        fold_progress([done], run_statuses={RUN: "completed"}, now=NOW + timedelta(seconds=61))
        is None
    )


def test_needs_attention_names_the_account_and_never_lingers_away() -> None:
    acc = uuid4()
    bad = job(
        "A",
        stage="synthesis",
        status="needs_review",
        account_id=acc,
        finished_at=NOW - timedelta(hours=2),
        failure="model_error",
    )
    card = fold_progress([bad], run_statuses={RUN: "needs_review"}, now=NOW)
    assert card is not None
    assert card.pill == "needs_attention"
    assert card.attention[0].account_name == "A" and "model_error" in card.attention[0].reason


def test_a_suspended_run_flips_the_pill_even_with_a_healthy_job() -> None:
    acc = uuid4()
    live = job("A", stage="deep_research", status="in_progress", account_id=acc)
    card = fold_progress([live], run_statuses={RUN: "suspended"}, now=NOW)
    assert card is not None
    assert card.pill == "needs_attention"
    assert card.attention[0].reason == "run suspended"


def test_nothing_live_and_nothing_recent_is_no_card() -> None:
    assert fold_progress([], run_statuses={}, now=NOW) is None
