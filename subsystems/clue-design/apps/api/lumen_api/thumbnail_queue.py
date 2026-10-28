"""Gallery-thumbnail renders, run in the background: one per document, capped per lane.

Production 2026-10-28 (7:45-11 PM IST): the thumbnail route rendered inside the request, so
705 renders ran for 180 distinct document versions (525 duplicates), 73 thumbnail requests were
in flight at once, and site renders — a hardened headless browser, median 52 s — starved the
Design API's request pool: loading a site's brand took 220 s.

The route now never renders. It answers with what is cached and asks this queue for the
document's current version. The queue:

* runs **one render per document** at a time. A request for a version while that document is
  already rendering only raises the version wanted; when the render ends, the document renders
  once more if a newer version was asked for meanwhile — and then only the newest.
* runs renders in **two lanes**, each with its own worker threads and limit: ``site`` (site and
  legacy web pages: a headless browser each) and ``scene`` (ads: the engine export, ~1 s).
* logs ``document_thumbnail_queued``, ``document_thumbnail_render_finished`` (with
  ``queue_wait_ms`` and ``render_ms``) and ``document_thumbnail_failed``, so the limits can be
  tuned from what production shows.

A render callable renders the document's CURRENT version and returns that version number. State
lives in this process only: a restart drops queued renders, and the next request queues them
again.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, Mapping, Optional, Tuple

#: The env settings for the two lane limits, and their defaults.
SITE_CONCURRENCY_ENV = "LUMEN_THUMBNAIL_SITE_CONCURRENCY"
SCENE_CONCURRENCY_ENV = "LUMEN_THUMBNAIL_SCENE_CONCURRENCY"
DEFAULT_LIMITS: Dict[str, int] = {"site": 2, "scene": 4}

Render = Callable[[], int]
Log = Callable[..., None]


def render_lane(kind: str) -> str:
    """The lane a document kind renders in: site and web pages need a browser, ads do not."""
    return "site" if kind in ("site", "web") else "scene"


def limits_from_env(env: Mapping[str, str] = os.environ) -> Dict[str, int]:
    """The two lane limits, from the env settings; a missing or unusable value keeps its default."""
    limits = dict(DEFAULT_LIMITS)
    for lane, name in (("site", SITE_CONCURRENCY_ENV), ("scene", SCENE_CONCURRENCY_ENV)):
        raw = (env.get(name) or "").strip()
        if raw.isdigit() and int(raw) > 0:
            limits[lane] = int(raw)
    return limits


@dataclass
class _Job:
    lane: str
    kind: str
    wanted: int
    render: Render
    queued_at: float = field(default_factory=time.monotonic)


class ThumbnailRenderQueue:
    """Background thumbnail renders: deduplicated per document, capped per lane."""

    def __init__(self, limits: Mapping[str, int], *, log: Optional[Log] = None) -> None:
        self._log: Log = log or (lambda event, **fields: None)
        self._executors = {
            lane: ThreadPoolExecutor(
                max_workers=max(1, int(count)), thread_name_prefix=f"thumbnail-{lane}"
            )
            for lane, count in limits.items()
        }
        self._jobs: Dict[Tuple[str, str], _Job] = {}
        self._idle = threading.Condition()

    def request(
        self, *, workspace_id: str, document_id: str, version: int, kind: str, render: Render
    ) -> None:
        """Ask for ``document_id`` to be rendered at ``version`` (or newer).

        Already rendering or queued: only the version wanted rises (and the newest render
        callable is kept), so no second render starts for the same document.
        """
        key = (workspace_id, document_id)
        lane = render_lane(kind)
        with self._idle:
            job = self._jobs.get(key)
            if job is not None:
                if version > job.wanted:
                    job.wanted = version
                    job.render = render
                return
            self._jobs[key] = _Job(lane=lane, kind=kind, wanted=version, render=render)
        self._log(
            "document_thumbnail_queued",
            document_id=document_id,
            version=version,
            kind=kind,
            lane=lane,
        )
        self._executors[lane].submit(self._run, key)

    def _run(self, key: Tuple[str, str]) -> None:
        workspace_id, document_id = key
        while True:
            with self._idle:
                job = self._jobs[key]
                wanted, render, queued_at = job.wanted, job.render, job.queued_at
            started = time.monotonic()
            try:
                rendered = render()
            except Exception as error:  # noqa: BLE001 - one card's failure must never stop the lane
                # The render's typed refusals carry `{code, message}` (the 502 bodies the route
                # used to answer); anything else is named by its type.
                detail = getattr(error, "detail", None)
                typed = isinstance(detail, dict)
                self._log(
                    "document_thumbnail_failed",
                    document_id=document_id,
                    version=wanted,
                    kind=job.kind,
                    lane=job.lane,
                    error_code=detail.get("code") if typed else type(error).__name__,
                    error=str(detail.get("message") if typed else error)[:500],
                )
                self._finish(key)
                return
            self._log(
                "document_thumbnail_render_finished",
                document_id=document_id,
                version=rendered,
                kind=job.kind,
                lane=job.lane,
                queue_wait_ms=round((started - queued_at) * 1000, 1),
                render_ms=round((time.monotonic() - started) * 1000, 1),
            )
            with self._idle:
                job = self._jobs[key]
                if job.wanted <= rendered:
                    del self._jobs[key]
                    self._idle.notify_all()
                    return
                # A newer version was asked for while this one rendered: render once more.
                job.queued_at = time.monotonic()

    def _finish(self, key: Tuple[str, str]) -> None:
        with self._idle:
            self._jobs.pop(key, None)
            self._idle.notify_all()

    def wait_idle(self, timeout: float) -> bool:
        """Block until no render is queued or running (tests; a graceful shutdown)."""
        deadline = time.monotonic() + timeout
        with self._idle:
            while self._jobs:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._idle.wait(remaining)
            return True
