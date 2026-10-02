"""Renewed, expiring Redis capacity leases for synchronous provider clients.

Redis coordinates in-flight work only; durable outcomes remain in Postgres.
All processes sharing a provider credential must use the same capacity policy.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from redis import Redis

from .client import redis_url

_ACQUIRE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""
_RENEW = """
if not redis.call('ZSCORE', KEYS[1], ARGV[1]) then return 0 end
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""


@contextmanager
def provider_capacity(
    key: str,
    *,
    limit: int,
    wait_seconds: float = 300,
    lease_seconds: int = 120,
    client: Redis | None = None,
) -> Iterator[None]:
    """Wait boundedly for a shared slot. A crashed process's slot expires.

    Redis unavailability refuses the call rather than bypassing the shared cap.
    Renewal keeps slow calls counted; token-specific release cannot evict a successor.
    """
    if limit < 1 or lease_seconds < 3:
        raise ValueError("capacity and lease duration must be positive")
    owned = client is None
    redis = client or Redis.from_url(redis_url(), socket_timeout=5, socket_connect_timeout=5)
    redis_key, token = f"provider-capacity:{key}", uuid4().hex
    stopped, lost = threading.Event(), threading.Event()
    acquired = False
    heartbeat: threading.Thread | None = None

    def renew() -> None:
        while not stopped.wait(lease_seconds / 3):
            try:
                if not redis.eval(_RENEW, 1, redis_key, token, lease_seconds):
                    lost.set()
                    return
            except Exception:
                lost.set()
                return

    try:
        deadline = time.monotonic() + wait_seconds
        while not redis.eval(_ACQUIRE, 1, redis_key, limit, token, lease_seconds):
            if time.monotonic() >= deadline:
                raise TimeoutError("Shared provider capacity is busy; retry this analysis later")
            time.sleep(0.1)
        acquired = True
        heartbeat = threading.Thread(target=renew, daemon=True, name="provider-capacity")
        heartbeat.start()
        yield
        if lost.is_set():
            raise RuntimeError("Shared provider capacity lease was lost during the call")
    finally:
        stopped.set()
        if heartbeat is not None:
            heartbeat.join(timeout=6)
        try:
            if acquired:
                redis.zrem(redis_key, token)
        finally:
            if owned:
                redis.close()
