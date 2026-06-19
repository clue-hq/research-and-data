"""Distributed rate-limit coordination over Redis (M2.4).

The same Redis substrate that holds in-flight locks also coordinates **provider rate limits**
(conventions §6): resolvers (M4) across many workers must collectively respect a source's call
budget, not each worker independently. :class:`RateLimiter` is a shared **token bucket** keyed on a
``source_key`` — refill + consume happen atomically in one Lua call, so N concurrent workers can
never collectively exceed the configured budget (within one token of tolerance).

The bucket starts full (``capacity`` tokens) and refills at ``rate_per_sec``; an empty bucket denies
until it refills. The source layer (M4) consumes this helper; M2.4 only provides the primitive.
"""

from __future__ import annotations

import time

from redis.asyncio import Redis

# Atomic token-bucket refill+consume. now is passed from the caller (single-coordinator clock); the
# stored state is (tokens, last_refill_ms). Returns 1 if allowed (tokens consumed), else 0.
_TOKEN_BUCKET = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
local state = redis.call('hmget', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then tokens = capacity; ts = now end
local delta = math.max(0, now - ts) / 1000.0
tokens = math.min(capacity, tokens + delta * rate)
local allowed = 0
if tokens >= requested then tokens = tokens - requested; allowed = 1 end
redis.call('hmset', key, 'tokens', tokens, 'ts', now)
redis.call('pexpire', key, ttl)
return allowed
"""


class RateLimiter:
    """A shared token-bucket rate limiter over Redis (per ``source_key``)."""

    def __init__(self, redis: Redis, *, rate_per_sec: float, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._redis = redis
        self._rate = float(rate_per_sec)
        self._capacity = capacity
        # Idle buckets expire so the keyspace stays bounded; long enough to span a full refill.
        self._ttl_ms = max(
            1000, int((capacity / self._rate * 1000) * 2) if self._rate > 0 else 60_000
        )

    async def acquire(self, source_key: str, *, tokens: int = 1) -> bool:
        """Try to consume ``tokens`` from ``source_key``'s bucket — ``True`` if allowed."""
        now_ms = time.time() * 1000.0
        result = await self._redis.eval(
            _TOKEN_BUCKET,
            1,
            f"ratelimit:{source_key}",
            now_ms,
            self._rate,
            self._capacity,
            tokens,
            self._ttl_ms,
        )
        return bool(result)
