"""The research progress card's math and pill, as pure functions over job rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from clue_api.arv2.research_progress import (
    LINGER_S,
    ProgressAttention,
    ProgressJob,
    account_score,
    fold_progress,
    person_group_score,
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
    failure_code: str | None = None,
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
        failure_code=failure_code,
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


def test_a_suspended_job_is_paused_not_finished() -> None:
    """A worker restart suspends every in-flight job. That is a PAUSE: nothing has been researched,
    so the bar reads 0 %, nothing is counted finished, and the pill asks for a human."""
    jobs = [
        job(f"Account {n}", status="suspended", stage="deep_research", account_id=uuid4())
        for n in range(10)
    ]
    card = fold_progress(jobs, run_statuses={RUN: "in_progress"}, now=NOW)
    assert card is not None
    assert card.progress_pct == 0
    assert (card.requested_accounts, card.queued, card.running, card.finished) == (10, 0, 0, 0)
    assert card.pill == "needs_attention"
    # ... and a job paused further along still keeps the quarters it walked, and only those.
    paused_late = job("Late", status="suspended", stage="committee", account_id=uuid4())
    assert account_score(paused_late, []) == 0.5


def test_a_person_only_run_scores_on_its_people() -> None:
    """``launch_arv2_person_research`` makes a run with no account job at all (I3)."""
    acc = uuid4()
    people = [
        job(
            "Acme",
            subject="person",
            status="completed",
            stage="synthesis",
            account_id=acc,
            finished_at=NOW,
        ),
        *(job("Acme", subject="person", account_id=acc) for _ in range(3)),
    ]
    assert person_group_score(people) == 0.25
    card = fold_progress(people, run_statuses={RUN: "in_progress"}, now=NOW)
    assert card is not None
    assert card.progress_pct == 25
    assert (card.requested_accounts, card.queued, card.running, card.finished) == (1, 0, 3, 0)
    assert card.pill == "running"


def test_a_person_only_group_is_queued_until_one_of_its_people_starts() -> None:
    acc = uuid4()
    waiting = [
        job("Acme", subject="person", status="not_started", stage=None, account_id=acc)
        for _ in range(2)
    ]
    card = fold_progress(waiting, run_statuses={RUN: "not_started"}, now=NOW)
    assert card is not None
    assert (card.requested_accounts, card.queued, card.finished) == (1, 1, 0)
    assert card.progress_pct == 0


def test_the_same_account_in_two_runs_is_two_groups_each_with_its_own_people() -> None:
    """People are keyed by ``(run, account)``: one run's members never fill another's bar (M5)."""
    acc = uuid4()
    other_run = uuid4()
    first = job("Acme", stage="member_research", status="in_progress", account_id=acc)
    second = ProgressJob(
        **{
            **job("Acme", stage="deep_research", status="in_progress", account_id=acc).__dict__,
            "run_id": other_run,
        }
    )
    # The first run's one member is done; the second run has no people at all.
    member = job(
        "Acme",
        subject="person",
        status="completed",
        stage="synthesis",
        account_id=acc,
        finished_at=NOW,
    )
    jobs = [first, second, member]
    card = fold_progress(jobs, run_statuses={RUN: "in_progress", other_run: "in_progress"}, now=NOW)
    assert card is not None
    assert card.requested_accounts == 2
    # first: member_research with 1/1 people done → 1.0; second: deep_research → 0. Mean 50 %.
    assert card.progress_pct == 50
    assert account_score(second, []) == 0.0


def test_one_account_failing_eight_members_is_one_attention_row() -> None:
    """Deduped by ``(account, reason)`` so the line does not rotate through the same sentence."""
    acc = uuid4()
    failed = [
        job(
            "Acme",
            subject="person",
            status="needs_review",
            stage="synthesis",
            account_id=acc,
            finished_at=NOW,
            failure="the model errored",
        )
        for _ in range(2)
    ]
    card = fold_progress(failed, run_statuses={RUN: "needs_review"}, now=NOW)
    assert card is not None
    assert card.attention == (ProgressAttention(account_name="Acme", reason="the model errored"),)


def test_a_long_failure_message_is_clipped_to_one_line() -> None:
    """The driver stores ``outcome.error[:1000]``; the card shows at most 140 characters (M3)."""
    acc = uuid4()
    bad = job(
        "Acme",
        stage="synthesis",
        status="needs_review",
        account_id=acc,
        finished_at=NOW,
        failure="x" * 500,
    )
    card = fold_progress([bad], run_statuses={RUN: "needs_review"}, now=NOW)
    assert card is not None
    reason = card.attention[0].reason
    assert len(reason) == 140
    assert reason.endswith("\u2026") and reason.startswith("x" * 139)


def test_a_provider_refusal_reads_as_the_incident_sentence_on_the_card() -> None:
    """A parsed ``failure_code`` replaces the provider's raw prose with the shared sentence.

    ``notified`` is unknown to the pure fold — only the read knows whether the open incident
    carries a Sentry id — so the fold's sentence never claims Clue has been told.
    """
    finished = datetime(2026, 9, 16, 10, 31, 29, tzinfo=UTC)
    refused = job(
        "Acme",
        subject="person",
        status="needs_review",
        stage="synthesis",
        finished_at=finished,
        failure="PermissionDeniedError: Error code: 403 - key limit exceeded",
        failure_code="provider_refused:openrouter:key_limit",
    )
    card = fold_progress(
        [refused], run_statuses={RUN: "needs_review"}, now=finished + timedelta(minutes=1)
    )
    assert card is not None
    assert card.attention[0].reason == "Model provider refused: key limit exceeded. Since 10:31."


def test_an_unparsable_failure_code_still_shows_the_provider_prose() -> None:
    finished = datetime(2026, 9, 16, 10, 31, 29, tzinfo=UTC)
    bad = job(
        "Acme",
        status="needs_review",
        stage="synthesis",
        finished_at=finished,
        failure="the model errored",
        failure_code="permission_denied_error",
    )
    card = fold_progress([bad], run_statuses={RUN: "needs_review"}, now=finished)
    assert card is not None
    assert card.attention[0].reason == "the model errored"


def test_viewable_outputs_complete_despite_execution_review_without_mutating_job():
    from dataclasses import replace

    original = replace(
        job("A", status="needs_review", failure="completion reference rejected"),
        delivery_stage="completed",
        deliverables_ready=True,
        delivered_at=NOW,
    )
    card = fold_progress([original], run_statuses={RUN: "in_progress"}, now=NOW)
    assert card.pill == "completed" and card.progress_pct == 100
    assert not card.attention and card.running == 0 and card.finished == 1
    assert original.status == "needs_review"


def test_account_publication_does_not_complete_pending_person_work():
    from dataclasses import replace

    acc = uuid4()
    parent = replace(
        job("A", status="needs_review", account_id=acc),
        delivery_stage="completed",
        deliverables_ready=True,
        delivered_at=NOW,
    )
    person = replace(
        job("A", subject="person", account_id=acc),
        delivery_stage="compiling_findings",
        subject_name="Jane Doe",
    )
    card = fold_progress([parent, person], run_statuses={}, now=NOW)
    assert card.pill == "running" and card.finished == 0 and card.running == 1
    assert card.progress_pct == 63  # average of 100% and 25% milestones, not elapsed time
    assert card.agents[0].stage == "compiling_findings"
    assert card.agents[0].subject_name == "Jane Doe"


def test_missing_pages_do_not_become_completed_by_ignoring_review():
    from dataclasses import replace

    for status in ("completed", "needs_review"):
        missing = replace(job("A", status=status), delivery_stage="writing_narrative")
        card = fold_progress([missing], run_statuses={}, now=NOW)
        assert card.pill == "needs_attention" and card.progress_pct < 100


def test_delivered_review_job_uses_normal_completed_linger():
    from dataclasses import replace

    done = replace(
        job("A", status="needs_review"),
        delivery_stage="completed",
        deliverables_ready=True,
        delivered_at=NOW - timedelta(minutes=2),
    )
    assert fold_progress([done], run_statuses={}, now=NOW) is None
