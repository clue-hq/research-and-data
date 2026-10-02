"""A model's context window, from OpenRouter's public model catalogue (no key needed).

Compaction sizes itself from this number (founder ruling 2026-09-29). It is read once per process
and cached; a missing model or an unreachable catalogue answers ``None`` so the caller falls back
to fixed thresholds — never an unlimited agent, never a start-up failure.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Mapping

from clue_obs import get_logger

log = get_logger("clue_gateway.model_windows")

_CATALOGUE_URL = "https://openrouter.ai/api/v1/models"
_cache: Mapping[str, int] | None = None


def _reset_cache() -> None:
    global _cache
    _cache = None


def _fetch_catalogue() -> Mapping[str, int]:
    with urllib.request.urlopen(_CATALOGUE_URL, timeout=10) as response:  # noqa: S310
        body = json.loads(response.read())
    return {
        str(item["id"]): int(item["context_length"])
        for item in body.get("data", [])
        if isinstance(item, dict) and item.get("id") and item.get("context_length")
    }


def resolve_context_window(
    model_id: str,
    *,
    override: int | None,
    fetch: Callable[[], Mapping[str, int]] | None = None,
) -> int | None:
    """The model's context window in tokens, ``override`` first; ``None`` when unknown."""
    if override is not None:
        return override
    global _cache
    if _cache is None:
        try:
            _cache = dict((fetch or _fetch_catalogue)())
        except Exception:  # noqa: BLE001 — an unreachable catalogue is a fallback, not a failure
            log.warning("model_windows.catalogue_unavailable", exc_info=True)
            _cache = {}
    window = _cache.get(model_id)
    if window is None:
        log.warning("model_windows.window_unknown", model_id=model_id)
    return window
