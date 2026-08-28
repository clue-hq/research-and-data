"""The isolation render — a picture of a cloned section that was never on a page (F3.2, P-7).

Two fragments in this system can never have a preview at birth, and both of them need one before
a human is allowed to decide anything about them:

* a **dormant** clone (founder ruling D-F8). The source site HIDES the section, so the capture's
  screenshot contains no pixels of it, and ``crop_extent`` correctly refuses to borrow a
  neighbour's — F3.0 shipped the activation gate knowing this meant the activate path always
  honestly refused.
* a **repair** (ruling R17-2). It was composed this turn; nobody ever photographed it, so the
  human whose kit approval releases it is approving a section nobody can look at.

Orchestrator ruling **P-7** closes both with the same answer: render the artifact's OWN bytes —
its sanitized markup, its scoped CSS, its rehosted assets — through our engine, in isolation, and
photograph that. Nothing is fabricated and nothing is guessed at: these are the bytes the page
would show, shown by themselves. It is deliberately **not** a crop of the source site's
screenshot, which for a hidden section does not exist and for a repair never did.

**Two halves, and the seam between them is the point.** :func:`build_isolation_page` is the
engine half — it composes the one-section document, asks the engine to render it, and returns the
HTML plus the digests of every byte that HTML names. It needs no browser, so what a preview is a
picture OF is testable directly. :func:`screenshot_isolation_page` is the browser half; it is
injected, so nothing in the fragment package imports Playwright to be tested.

The rendered page is loaded with **no network at all**: every ``/asset-store/<digest>`` request is
served from the workspace's own blob custody through a route interception, and anything else is
aborted. A preview that could fetch from the open web would be a picture of the internet, not of
the artifact.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .refs import fragment_wrapper_class
from .render import rebase_artifact_assets, slot_kinds

#: The label an isolation render carries wherever it is described. P-7 is explicit that this is
#: an isolation render and NOT a source-site screenshot crop, and a human deciding whether to
#: activate a hidden section deserves to be told which kind of picture they are looking at.
ISOLATION_RENDER_BASIS = "isolation_render"

ISOLATION_PREVIEW_MEDIA_TYPE = "image/png"

#: The desktop width every other clone preview was cropped at (the capture renders at 1440).
#: Matching it means a dormant section's thumbnail sits beside its visible neighbours' at the same
#: scale rather than being obviously a different kind of picture.
ISOLATION_VIEWPORT_WIDTH = 1440

#: A tall band is the normal case here — the dead-height detector exists because clones reach
#: several thousand pixels — so the viewport is generous and the screenshot is of the ELEMENT,
#: not the viewport, which is what makes the height come out right whatever this is.
ISOLATION_VIEWPORT_HEIGHT = 1600

#: How long the browser gets. A local page with no network cannot legitimately take longer, and
#: an unbounded wait would hold a request open on a wedged browser.
ISOLATION_TIMEOUT_MS = 20_000

#: The origin the isolation page resolves its byte references against. Nothing is served from it
#: — every request to it is intercepted — but a page loaded through ``set_content`` has no
#: document origin, so a root-relative ``/asset-store/…`` would not resolve at all.
ISOLATION_ORIGIN = "https://isolation.lumen.invalid"

_ASSET_PATH_PREFIX = "/asset-store/"

_PAGE_ID = "home"
_SECTION_NODE_ID = "sec_isolation"
_FRAGMENT_NODE_ID = "frg_isolation"


@dataclass(frozen=True)
class IsolationPage:
    """One fragment, rendered alone: the HTML, and the bytes that HTML asks for."""

    fragment_id: str
    html: str
    asset_digests: tuple[str, ...]
    #: The CSS selector the screenshot is taken of — the fragment's own wrapper, so the picture
    #: is the band and not the page chrome around it.
    element_selector: str


def isolation_web_doc(fragment_id: str) -> dict[str, Any]:
    """The smallest renderable document that carries exactly this one cloned section.

    The wrapper section is not decoration: the page root holds sections and nothing else
    (LUMW0011) and a fragment node is a leaf, so this is the same ``(wrapper, fragment)`` pair
    every pinned clone occupies on a real page. Rendering the artifact in the shape it is
    actually used in is the whole reason to go through the engine rather than pasting the markup
    into a string.
    """
    return {
        "schema_version": 1,
        "id": "isolation",
        "title": "Isolation render",
        "pages": [
            {
                "id": _PAGE_ID,
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": {
                    "root": {
                        "id": "root",
                        "kind": "container",
                        "classes": "",
                        "children": [_SECTION_NODE_ID],
                    },
                    _SECTION_NODE_ID: {
                        "id": _SECTION_NODE_ID,
                        "kind": "section",
                        "tag": "section",
                        "classes": "",
                        "children": [_FRAGMENT_NODE_ID],
                    },
                    _FRAGMENT_NODE_ID: {
                        "id": _FRAGMENT_NODE_ID,
                        "kind": "fragment",
                        "classes": "",
                        "fragment_id": fragment_id,
                    },
                },
            }
        ],
        "assets": {},
        "custom_css": "",
    }


def build_isolation_page(core: Any, loaded: Any, *, brand_kit: Any = None) -> IsolationPage:
    """Render one fragment's own bytes, alone, through the engine.

    ``loaded`` is a :class:`~lumen_api.fragments.registry.LoadedFragment` — its ``html`` and
    ``css`` are the stored artifact's, read out of durable custody, and they are what is handed
    to the engine here. No markup is composed, rewritten or invented on the way: the engine gets
    the artifact's map exactly as the page render gives it (F1.3's ``fragments`` +
    ``fragment_css``), which is what makes this a picture of the artifact rather than a picture
    of something that resembles it.

    ``mode="delivery"`` because an isolation render is not being edited — the editor mode's
    instrumentation would put ``data-node-id`` attributes into a photograph.

    The brand kit is threaded through when the caller has one so a repair (whose stylesheet is
    written in the platform's own class vocabulary against theme tokens) photographs in the
    brand's real colours rather than the engine's defaults. A harvested clone carries all of its
    own styling and does not care either way.
    """
    fragment_id = loaded.fragment_id
    asset_base = ISOLATION_ORIGIN + _ASSET_PATH_PREFIX.rstrip("/")
    response = core.web_render(
        isolation_web_doc(fragment_id),
        _PAGE_ID,
        mode="delivery",
        asset_base_url=asset_base,
        brand_kit=brand_kit,
        fragments={
            fragment_id: {
                "html": rebase_artifact_assets(loaded.html, asset_base),
                "slot_kinds": slot_kinds(loaded.slot_manifest),
            }
        },
        fragment_css=rebase_artifact_assets(loaded.css, asset_base),
    )
    return IsolationPage(
        fragment_id=fragment_id,
        html=str(response.get("html") or ""),
        asset_digests=tuple(loaded.asset_digests),
        element_selector=f".{fragment_wrapper_class(fragment_id)}",
    )


async def _shoot(page_html: str, selector: str, assets: Mapping[str, tuple[str, bytes]]) -> bytes:
    from playwright.async_api import async_playwright  # lazy: never at import time

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page(
                viewport={
                    "width": ISOLATION_VIEWPORT_WIDTH,
                    "height": ISOLATION_VIEWPORT_HEIGHT,
                }
            )
            page.set_default_timeout(ISOLATION_TIMEOUT_MS)

            async def _route(route: Any) -> None:
                # Fail-CLOSED: the only requests this page may make are for bytes this workspace
                # already holds. Everything else — a font from a CDN the sanitizer left as a
                # reference, an analytics beacon in somebody's markup — is aborted, so the
                # picture can only ever be of what we have.
                url = route.request.url
                _, _, tail = url.partition(_ASSET_PATH_PREFIX)
                held = assets.get(tail) if _ASSET_PATH_PREFIX in url else None
                if held is None:
                    await route.abort()
                    return
                media_type, data = held
                await route.fulfill(status=200, body=data, content_type=media_type)

            await page.route("**/*", _route)
            await page.set_content(page_html, wait_until="load")
            element = await page.query_selector(selector)
            if element is None:
                # The wrapper is emitted by the engine around every fragment it renders, so its
                # absence means the artifact did not render at all (a placeholder took its
                # place). A full-page shot of a placeholder is worse than no picture: it is a
                # picture a human would activate a section on.
                raise IsolationRenderFailed(
                    "isolation.section_not_rendered",
                    f"the fragment did not render in isolation ({selector} is absent), so there "
                    "is nothing to photograph",
                )
            return await element.screenshot(type="png")
        finally:
            await browser.close()


class IsolationRenderFailed(RuntimeError):
    """The isolation render produced no usable picture. Carries a code the surface can map."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def screenshot_isolation_page(
    page: IsolationPage, assets: Mapping[str, tuple[str, bytes]]
) -> bytes:
    """Photograph one isolation page. The default browser half; injected everywhere it is used."""
    from ..design_store import _run_isolated

    try:
        return _run_isolated(_shoot(page.html, page.element_selector, assets))
    except IsolationRenderFailed:
        raise
    except Exception as error:  # noqa: BLE001 — every browser fault is one refusal to the human
        raise IsolationRenderFailed(
            "isolation.render_failed",
            f"the isolation render could not be photographed: {error}",
        ) from error


def render_isolation_preview(
    core: Any,
    loaded: Any,
    *,
    read_blob: Callable[[str], tuple[str, bytes]],
    brand_kit: Any = None,
    shoot: Callable[[IsolationPage, Mapping[str, tuple[str, bytes]]], bytes] = (
        screenshot_isolation_page
    ),
) -> tuple[bytes, IsolationPage]:
    """The whole of P-7: the artifact's own bytes in, one PNG out.

    A digest the workspace does not hold is left out of the served map rather than failing the
    render — the reference is already in the stored markup and the page simply shows it missing,
    which is honest, and refusing would mean a clone with one purged byte could never be looked
    at at all.
    """
    page = build_isolation_page(core, loaded, brand_kit=brand_kit)
    assets: dict[str, tuple[str, bytes]] = {}
    for digest in page.asset_digests:
        try:
            assets[digest] = read_blob(digest)
        except Exception:  # noqa: BLE001 — a missing byte is a gap in the picture, not a failure
            continue
    return shoot(page, assets), page


def preview_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "ISOLATION_PREVIEW_MEDIA_TYPE",
    "ISOLATION_RENDER_BASIS",
    "IsolationPage",
    "IsolationRenderFailed",
    "build_isolation_page",
    "isolation_web_doc",
    "preview_digest",
    "render_isolation_preview",
    "screenshot_isolation_page",
]
