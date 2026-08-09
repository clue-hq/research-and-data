"""Generation cache: (normalized prompt + constraints + model) → the generated
asset record, checked BEFORE the paid, non-deterministic text-to-image call.

The content-addressed asset store only dedups by *byte digest*, which happens
*after* the model has already run (and been paid for). The design quality loop
re-requests the same hero across iterations; without a request-keyed cache every
iteration re-pays the model and the design churns its imagery (Brilliant caches
the same way — one hero is generated once and re-placed). This closes that gap: it
maps a generation request to the asset produced the first time, so a repeat request
re-places the same asset for free.

Persisted as a small JSON sidecar at `{engine_cache_root}/{workspace_id}/.generation-cache.json`
(D4 / R-D4-8), so the cache lives and dies with the engine materialization cache it sits beside
and is shared by every caller pointed at that workspace's dir — the API route and the agent loop.

**LOUD WARNING (D4).** This file is *mutable JSON*, NOT asset bytes. It is the one thing under
the engine cache root that is deliberately EXEMPT from `StorageBackend` custody: platform storage
is content-addressed and immutable-by-construction, which is exactly wrong for a
last-writer-wins index that is rewritten on every generation. Losing it costs money (a repeat
prompt re-pays the model) but loses no data — every asset it points at has durable custody of its
own — so a wiped cache is a correct, self-healing state. **Its real home is Postgres, and that is
D5's to build.** Until then: do not "fix" this by registering it as a blob.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

CACHE_FILENAME = ".generation-cache.json"
_lock = threading.Lock()


def _normalize_text(text: Optional[str]) -> str:
    # Collapse whitespace + lowercase so trivial prompt variations share a cache
    # entry; an identical loop re-request matches exactly regardless.
    return " ".join((text or "").split()).lower()


def generation_key(
    *,
    prompt: str,
    model: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    brand_notes: Optional[List[str]] = None,
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    transparent_background: Optional[bool] = None,
    reference_asset_ids: Optional[List[str]] = None,
    reference_digests: Optional[List[str]] = None,
    source_digest: Optional[str] = None,
) -> str:
    """Stable hash of the generation request — the cache key. Anything that
    changes the produced image (prompt, brand conditioning, size, aspect, model,
    references, and for EDITS the source image digest) participates; ordering
    of notes/refs does not."""
    payload = {
        "prompt": _normalize_text(prompt),
        "model": (model or "").strip(),
        "width": width,
        "height": height,
        "brand_notes": sorted(_normalize_text(note) for note in (brand_notes or []) if (note or "").strip()),
        "aspect_ratio": aspect_ratio,
        "image_size": image_size,
        "transparent_background": bool(transparent_background) if transparent_background is not None else None,
        "reference_asset_ids": sorted(reference_asset_ids or []),
    }
    # Only present when reference-conditioned, so plain-generation keys (and the
    # existing cache) are unchanged. Reference PIXEL digests are the content key —
    # ids alone can't tell two different attachments apart, and they align the
    # runtime and route paths on the same truth.
    if reference_digests:
        payload["reference_digests"] = sorted(reference_digests)
    # Only present for EDITS, so plain-generation keys (and the existing cache)
    # are unchanged. Edits MUST key on the source pixels — editing asset A then
    # asset B with the same instruction would otherwise return A's result.
    if source_digest:
        payload["source_digest"] = source_digest
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_path(store_root: str) -> Path:
    return Path(store_root) / CACHE_FILENAME


def _read(store_root: str) -> Dict[str, Any]:
    path = _cache_path(store_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def lookup(store_root: str, key: str) -> Optional[Dict[str, Any]]:
    """Return the cached asset record for this generation key, or None on a miss."""
    entry = _read(store_root).get(key)
    return entry if isinstance(entry, dict) else None


def store(store_root: str, key: str, record: Dict[str, Any]) -> None:
    """Persist key → asset record (atomic write, last-writer-wins)."""
    if not isinstance(record, dict) or not record:
        return
    path = _cache_path(store_root)
    with _lock:
        data = _read(store_root)
        data[key] = record
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
