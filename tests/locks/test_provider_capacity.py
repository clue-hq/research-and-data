from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep
from uuid import uuid4

import pytest
from redis import Redis
from redis.exceptions import ConnectionError

from clue_locks.capacity import provider_capacity
from clue_locks.client import redis_url


@pytest.fixture(autouse=True)
def require_redis():
    with Redis.from_url(redis_url(), socket_connect_timeout=1) as client:
        try:
            client.ping()
        except ConnectionError:
            pytest.skip("Redis is unavailable")


def test_independent_clients_share_capacity_and_release_on_failure():
    key = f"asset-test-{uuid4().hex}"
    active = peak = 0
    lock = Lock()

    def work(index):
        nonlocal active, peak
        with provider_capacity(key, limit=3, wait_seconds=5):
            with lock:
                active += 1
                peak = max(peak, active)
            sleep(0.02)
            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=15) as pool:
        list(pool.map(work, range(30)))
    assert peak == 3 and active == 0
    with pytest.raises(ValueError), provider_capacity(key, limit=1):
        raise ValueError("provider failed")
    with (
        provider_capacity(key, limit=1, wait_seconds=0),
        pytest.raises(TimeoutError),
        provider_capacity(key, limit=1, wait_seconds=0),
    ):
        pytest.fail("a held slot cannot be bypassed")


def test_expired_crashed_slot_is_reclaimed():
    key = f"asset-test-{uuid4().hex}"
    with Redis.from_url(redis_url()) as client:
        client.zadd(f"provider-capacity:{key}", {"crashed-worker": 1})
        with provider_capacity(key, limit=1, wait_seconds=0, client=client):
            assert client.zcard(f"provider-capacity:{key}") == 1
        assert client.zcard(f"provider-capacity:{key}") == 0
