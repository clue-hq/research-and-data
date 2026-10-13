"""The evidence-indexing replay benchmark's statistics (no database, no storage)."""

import asyncio

from scripts.bench_evidence_indexing import TimedStorage, percentile, summarise


def test_percentiles_are_nearest_rank():
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 50) == 50.0
    assert percentile(values, 95) == 95.0
    assert percentile([7.0], 95) == 7.0


def test_each_step_is_summarised_and_missing_steps_are_left_out():
    calls = [
        {"lock_wait_ms": 10.0, "index_ms": 100.0, "total_ms": 150.0},
        {"lock_wait_ms": 30.0, "index_ms": 300.0, "total_ms": 350.0},
    ]
    summary = summarise(calls)
    assert set(summary) == {"lock_wait_ms", "index_ms", "total_ms"}
    assert summary["index_ms"] == {"p50": 100.0, "p95": 300.0, "mean": 200.0, "total": 400.0}


def test_storage_calls_are_counted_and_timed():
    class Fake:
        async def get(self, key):
            return b"x"

        name = "fake"

    storage = TimedStorage(Fake())
    assert asyncio.run(storage.get("k")) == b"x"
    assert asyncio.run(storage.get("k")) == b"x"
    assert storage.ops["get"] == 2 and storage.ms["get"] >= 0
    assert storage.name == "fake"  # non-coroutine attributes pass through
