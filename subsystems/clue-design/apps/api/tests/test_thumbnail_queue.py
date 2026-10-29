"""The gallery-thumbnail render queue: renders run in the background, one per document, capped.

Production 2026-10-28 (7:45-11 PM IST): 705 thumbnail renders for 180 distinct document
versions (525 duplicates), 73 thumbnail requests in flight at once, and site renders of a
median 52 s each, all inside the Design API's request pool — loading a site's brand took
220 s. These pin the three properties the fix rests on, with fake renders and no database.
"""

from __future__ import annotations

import threading
import time

from lumen_api.thumbnail_queue import ThumbnailRenderQueue, render_lane


def _queue(**limits: int) -> tuple[ThumbnailRenderQueue, list[tuple[str, dict]]]:
    events: list[tuple[str, dict]] = []
    queue = ThumbnailRenderQueue(
        {"site": limits.get("site", 2), "scene": limits.get("scene", 4)},
        log=lambda event, **fields: events.append((event, fields)),
    )
    return queue, events


def test_web_and_site_share_the_browser_lane_and_ads_have_their_own() -> None:
    assert render_lane("site") == "site"
    assert render_lane("web") == "site"
    assert render_lane("scene") == "scene"


def test_many_requests_for_one_version_render_it_once() -> None:
    queue, _ = _queue()
    release = threading.Event()
    calls: list[int] = []

    def render() -> int:
        calls.append(1)
        release.wait(5)
        return 3

    for _ in range(10):
        queue.request(workspace_id="ws", document_id="doc", version=3, kind="site", render=render)
    release.set()
    assert queue.wait_idle(5)
    assert len(calls) == 1


def test_renders_never_exceed_each_lane_limit() -> None:
    queue, _ = _queue(site=2, scene=4)
    lock = threading.Lock()
    running = {"site": 0, "scene": 0}
    peak = {"site": 0, "scene": 0}
    release = threading.Event()

    def render_for(lane: str):
        def render() -> int:
            with lock:
                running[lane] += 1
                peak[lane] = max(peak[lane], running[lane])
            release.wait(5)
            with lock:
                running[lane] -= 1
            return 1

        return render

    for index in range(8):
        queue.request(workspace_id="ws", document_id=f"site{index}", version=1, kind="site",
                      render=render_for("site"))
        queue.request(workspace_id="ws", document_id=f"ad{index}", version=1, kind="scene",
                      render=render_for("scene"))
    time.sleep(0.2)
    assert peak == {"site": 2, "scene": 4}
    release.set()
    assert queue.wait_idle(5)


def test_a_newer_version_asked_for_mid_render_renders_once_more_and_only_the_newest() -> None:
    queue, _ = _queue()
    started = threading.Event()
    release = threading.Event()
    current = {"version": 3}
    rendered: list[int] = []

    def render() -> int:
        # A real render reads the document's current version when it starts.
        version = current["version"]
        started.set()
        release.wait(5)
        rendered.append(version)
        return version

    queue.request(workspace_id="ws", document_id="doc", version=3, kind="scene", render=render)
    assert started.wait(5)
    # The document moves on while version 3 renders; 4, 5 and 6 are all asked for.
    for version in (4, 5, 6):
        current["version"] = version
        queue.request(workspace_id="ws", document_id="doc", version=version, kind="scene",
                      render=render)
    release.set()
    assert queue.wait_idle(5)
    assert rendered == [3, 6]


def test_a_failed_render_is_logged_and_does_not_wedge_the_document() -> None:
    queue, events = _queue()

    def broken() -> int:
        raise RuntimeError("chromium exploded")

    queue.request(workspace_id="ws", document_id="doc", version=2, kind="site", render=broken)
    assert queue.wait_idle(5)
    failures = [fields for event, fields in events if event == "document_thumbnail_failed"]
    assert failures and "chromium exploded" in failures[0]["error"]
    calls: list[int] = []
    queue.request(workspace_id="ws", document_id="doc", version=2, kind="site",
                  render=lambda: calls.append(1) or 2)
    assert queue.wait_idle(5)
    assert calls == [1]


def test_the_log_says_how_long_a_render_waited_and_took() -> None:
    queue, events = _queue()
    queue.request(workspace_id="ws", document_id="doc", version=1, kind="scene", render=lambda: 1)
    assert queue.wait_idle(5)
    names = [event for event, _ in events]
    assert "document_thumbnail_queued" in names
    finished = [fields for event, fields in events if event == "document_thumbnail_render_finished"]
    assert finished and {"queue_wait_ms", "render_ms", "version", "lane"} <= set(finished[0])


def test_the_same_document_id_in_two_workspaces_is_two_documents() -> None:
    queue, _ = _queue()
    calls: list[str] = []
    for workspace in ("ws_a", "ws_b"):
        queue.request(workspace_id=workspace, document_id="doc", version=1, kind="scene",
                      render=lambda workspace=workspace: calls.append(workspace) or 1)
    assert queue.wait_idle(5)
    assert sorted(calls) == ["ws_a", "ws_b"]
