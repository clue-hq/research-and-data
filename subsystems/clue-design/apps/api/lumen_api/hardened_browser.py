"""Hardened headless Chromium for anything that loads agent-written or site HTML (D2, founder
ruling 2026-10-11).

One fresh browser per use, launched with a stripped environment, and the network refused in
layers, any one of which is enough on its own:

1. the page's own CSP (the caller's markup);
2. ``--host-resolver-rules=MAP * ~NOTFOUND``: no hostname resolves;
3. a dead-end proxy (``127.0.0.1:9``, the discard port) with loopback NOT bypassed
   (``<-loopback>``), so an IP literal or localhost goes nowhere either;
4. WebRTC forced through that proxy (``disable_non_proxied_udp``);
5. Playwright: the context is offline, service workers are blocked, every routed request is
   refused, and every WebSocket is mocked (its route never calls ``connect_to_server``; closing it
   from the handler hangs the page under the render CSP — Playwright 1.61, probe 2026-10-11). A
   navigation request is refused by answering it LOCALLY with an empty 204, so the page stays where
   it is: an aborted navigation makes Chromium commit its error page in place of the document
   (``abort("aborted")`` too — probe 2026-10-13). Anything else is aborted.

Plus a V8 heap cap, Chromium's own sandbox (``LUMEN_SITE_RENDER_CHROMIUM_SANDBOX``, default on)
and the process-wide capture slots shared with the web thumbnail captures. The browser is
closed — which also kills a page stuck in a loop — however the caller's block ends.

Sync Playwright: call from a thread with no running event loop (``asyncio.to_thread``).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .document_thumbnails import _CAPTURE_SLOTS

CHROMIUM_SANDBOX_ENV = "LUMEN_SITE_RENDER_CHROMIUM_SANDBOX"
HARDENED_CHROMIUM_ARGS: tuple[str, ...] = (
    "--host-resolver-rules=MAP * ~NOTFOUND",
    "--proxy-server=http://127.0.0.1:9",
    "--proxy-bypass-list=<-loopback>",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-sync",
    "--no-pings",
    "--js-flags=--max-old-space-size=256",
)
DEFAULT_VIEWPORT = {"width": 1440, "height": 900}


class HardenedBrowserUnavailable(Exception):
    """Playwright is not installed in this process."""


def chromium_sandbox_enabled() -> bool:
    return os.environ.get(CHROMIUM_SANDBOX_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def stripped_env(home: str) -> dict[str, str]:
    """The browser process's whole environment: no API keys, database URLs or tokens."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "TMPDIR": home}


@contextmanager
def hardened_context(
    *, javascript: bool, viewport: dict[str, int] | None = None, device_scale_factor: float = 1.0
) -> Iterator[tuple[Any, list[str]]]:
    """A fresh hardened browser context. Yields ``(context, blocked)``; ``blocked`` collects the URL
    of every request and WebSocket the context refused."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise HardenedBrowserUnavailable("playwright is not installed") from error
    home = tempfile.mkdtemp(prefix="clue-hardened-")
    blocked: list[str] = []

    def refuse(route: Any) -> None:
        blocked.append(route.request.url)
        if route.request.is_navigation_request():
            route.fulfill(status=204)
        else:
            route.abort("blockedbyclient")

    try:
        with _CAPTURE_SLOTS, sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=list(HARDENED_CHROMIUM_ARGS),
                env=stripped_env(home),
                chromium_sandbox=chromium_sandbox_enabled(),
                timeout=30_000,
            )
            try:
                context = browser.new_context(
                    java_script_enabled=javascript,
                    offline=True,
                    service_workers="block",
                    accept_downloads=False,
                    viewport=viewport or dict(DEFAULT_VIEWPORT),
                    device_scale_factor=device_scale_factor,
                )
                context.route("**/*", refuse)
                context.route_web_socket("**/*", lambda socket: blocked.append(socket.url))
                yield context, blocked
            finally:
                browser.close()
    finally:
        shutil.rmtree(home, ignore_errors=True)


@contextmanager
def hardened_page(
    *, javascript: bool, viewport: dict[str, int] | None = None, device_scale_factor: float = 1.0
) -> Iterator[tuple[Any, list[str]]]:
    """One page in a fresh hardened context. The page is closed, then the browser."""
    from playwright.sync_api import Error as PlaywrightError

    with hardened_context(javascript=javascript, viewport=viewport, device_scale_factor=device_scale_factor) as (context, blocked):
        page = context.new_page()
        try:
            yield page, blocked
        finally:
            try:
                page.close()
            except PlaywrightError:
                pass  # a page stuck in a loop: closing the browser (above) still ends it
