"""A model's context window: the platform's own registry first, OpenRouter's catalogue after.

Compaction sizes itself from this number (founder ruling 2026-09-29). The models the platform runs
on are registered with their windows in ``CLUE_AGENT_MODEL_CONTEXT_WINDOWS``, so they never cost a
network call. Only a model nobody registered is looked up in OpenRouter's public catalogue (no key
needed), read once per process and cached; a model found in neither answers ``None`` so the caller
falls back to fixed thresholds — never an unlimited agent, never a start-up failure.

The catalogue read is blocking network I/O, so callers on an event loop run this in a thread (the
agent runtime does). On 2026-10-05 it ran on a fleet worker's loop while OpenRouter trickled the
body: every read beat the socket timeout, the fetch took 105 s, and the worker lost every lease it
held. So the whole fetch has a deadline, one thread fetches while the others wait, and a failure
is retried after a cooldown instead of pinning the process to the fallback for good.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping

from clue_obs import get_logger

log = get_logger("clue_gateway.model_windows")

_CATALOGUE_URL = "https://openrouter.ai/api/v1/models"
#: The whole fetch, not one socket read: ``urlopen``'s timeout restarts on every chunk received.
_FETCH_DEADLINE_S = 15.0
#: How long a failed fetch answers "unknown" before the catalogue is tried again.
_RETRY_AFTER_S = 600.0
_lock = threading.Lock()
_cache: Mapping[str, int] | None = None
_failed_at: float | None = None


def _reset_cache() -> None:
    global _cache, _failed_at
    _cache = None
    _failed_at = None


def _fetch_catalogue(*, deadline_s: float = _FETCH_DEADLINE_S) -> Mapping[str, int]:
    deadline = time.monotonic() + deadline_s
    chunks: list[bytes] = []
    with urllib.request.urlopen(_CATALOGUE_URL, timeout=min(10.0, deadline_s)) as response:  # noqa: S310
        # ``read1``, not ``read``: on a chunked body ``read(n)`` keeps reading chunks until it has
        # ``n`` bytes, so one call would span the whole trickle and the deadline would never run.
        while chunk := response.read1(64 * 1024):
            chunks.append(chunk)
            if time.monotonic() > deadline:
                raise TimeoutError(f"model catalogue still arriving after {deadline_s:g}s")
    body = json.loads(b"".join(chunks))
    return {
        str(item["id"]): int(item["context_length"])
        for item in body.get("data", [])
        if isinstance(item, dict) and item.get("id") and item.get("context_length")
    }


def resolve_context_window(
    model_id: str,
    *,
    override: int | None,
    registry: Mapping[str, int] | None = None,
    fetch: Callable[[], Mapping[str, int]] | None = None,
) -> int | None:
    """The model's context window in tokens: ``override``, then ``registry``, then the catalogue;
    ``None`` when unknown.

    Blocking when the catalogue is needed: call it from a thread when on an event loop.
    """
    if override is not None:
        return override
    registered = (registry or {}).get(model_id)
    if registered is not None:
        return registered
    log.warning(
        "model_windows.not_registered",
        model_id=model_id,
        detail="add it to CLUE_AGENT_MODEL_CONTEXT_WINDOWS; reading OpenRouter's catalogue instead",
    )
    global _cache, _failed_at
    with _lock:
        cooling = _failed_at is not None and time.monotonic() - _failed_at < _RETRY_AFTER_S
        if _cache is None and not cooling:
            try:
                _cache = dict((fetch or _fetch_catalogue)())
                _failed_at = None
            except Exception:  # noqa: BLE001 — an unreachable catalogue is a fallback, not a failure
                log.warning("model_windows.catalogue_unavailable", exc_info=True)
                _failed_at = time.monotonic()
        window = (_cache or {}).get(model_id)
    if window is None:
        log.warning("model_windows.window_unknown", model_id=model_id)
    return window
