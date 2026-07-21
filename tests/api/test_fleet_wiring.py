"""PB-B1 api-composition-root fleet wiring (``clue_api.fleet_wiring`` / ``clue_api.fleet_main``).

Composition-only assertions — construction, settings threading, the fail-loud single-flight
contract, and rubric-derived tier priority. No live Redis or Postgres (construction of the ``Db*``
stores and the lock factory makes no I/O), so these run in the offline ``make check`` suite.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from clue_fleet import (
    FleetTaskKind,
    ProjectRunWorker,
    QueueBackedScheduler,
    default_tier_priority,
)

from clue_api.fleet_wiring import (
    build_account_lock_factory,
    build_fleet_deep_scheduler,
    build_fleet_run_driver,
    build_fleet_worker,
    enqueue_run_drive,
    tier_priority_from_rubric,
)
from clue_config import Settings
from clue_core import new_campaign_run_id
from clue_research.durable import CampaignRun
from clue_research.icp.rubric import TierBand, TierCutoffs
from tests.db.conftest import run_async


def _settings(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


# --- (a) the queue-backed scheduler is built WITH the lock factory; none → it will not build ---


def test_build_fleet_deep_scheduler_passes_the_lock_factory() -> None:
    settings = _settings()
    lock_factory = build_account_lock_factory(redis=object())  # no redis I/O at construction
    scheduler = build_fleet_deep_scheduler(settings, lock_factory=lock_factory)
    assert isinstance(scheduler, QueueBackedScheduler)
    assert scheduler._lock_factory is lock_factory
    # window + stale window come from CLUE_FLEET_* settings (policy as data)
    assert scheduler._window == settings.fleet_deep_window
    assert scheduler._stale_after == timedelta(seconds=settings.fleet_task_stale_after_s)


def test_queue_backed_scheduler_requires_a_lock_factory() -> None:
    """The fail-loud single-flight contract: the fleet scheduler makes ``lock_factory`` required, so
    a composition site cannot silently disable Doc C §4 single-flight (a forgotten factory is a
    construction-time ``TypeError``, not a double-spend)."""
    with pytest.raises(TypeError):
        QueueBackedScheduler(window=4)  # type: ignore[call-arg]


# --- (c) rubric-derived tier priority ranks real band labels, fallback after, else the ladder ---


def test_tier_priority_from_rubric_ranks_bands_most_selective_first() -> None:
    cutoffs = TierCutoffs(
        bands=(TierBand(tier="platinum"), TierBand(tier="gold"), TierBand(tier="silver")),
        fallback_tier="untiered",
    )
    priority = tier_priority_from_rubric(cutoffs)
    assert priority("platinum") == 0
    assert priority("gold") == 1
    assert priority("silver") == 2
    # the fallback tier (cleared no band) sorts AFTER the last band
    assert priority("untiered") == 3
    # an unknown label falls through to the default name/number ladder (last resort)
    assert priority("mystery") == default_tier_priority("mystery")


def test_default_tier_priority_alone_cannot_rank_rubric_names() -> None:
    """Why :func:`tier_priority_from_rubric` exists (spec §5): the stock policy ranks free-form
    band names at the unknown floor (100), collapsing their order — so it must not be bound."""
    assert default_tier_priority("platinum") == default_tier_priority("gold") == 100


# --- (d) the fleet-main composition builds a worker + driver from settings, no live redis ---


def test_build_fleet_run_driver_is_a_campaign_run() -> None:
    assert isinstance(build_fleet_run_driver(), CampaignRun)


def test_build_account_lock_factory_needs_no_live_redis_at_construction() -> None:
    assert callable(build_account_lock_factory(redis=object()))


def test_build_fleet_worker_threads_every_fleet_setting() -> None:
    settings = _settings(
        fleet_poll_interval_s=2.0,
        fleet_lease_ttl_s=40.0,
        fleet_heartbeat_interval_s=5.0,
        fleet_task_stale_after_s=80.0,
    )
    worker = build_fleet_worker(settings, driver=build_fleet_run_driver(), worker_id="w-1")
    assert isinstance(worker, ProjectRunWorker)
    assert worker.worker_id == "w-1"
    assert worker._poll_interval == 2.0
    assert worker._lease_ttl == timedelta(seconds=40.0)
    assert worker._heartbeat_interval == 5.0
    assert worker._task_stale_after == timedelta(seconds=80.0)


# --- the resume-surface helper (spec §2.4): re-driving is a fresh enqueue_drive -------------------


class _RecordingQueue:
    """Captures the one ``enqueue`` the drive helper issues (a minimal ``TaskQueue`` stand-in)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def enqueue(self, **kwargs: object) -> bool:
        self.calls.append(kwargs)
        return True


def test_enqueue_run_drive_offers_a_reopenable_drive_run() -> None:
    queue = _RecordingQueue()
    run_id = new_campaign_run_id()
    ok = run_async(enqueue_run_drive(run_id, queue=queue))  # type: ignore[arg-type]
    assert ok
    (call,) = queue.calls
    assert call["kind"] is FleetTaskKind.DRIVE_RUN
    assert call["dedup_key"] == str(run_id)
    assert call["reopen_terminal"] is True
