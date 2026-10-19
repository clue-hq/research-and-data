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

from .native import native_render_fields

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .refs import fragment_wrapper_class
from .render import rebase_artifact_assets, slot_kinds

#: The label an isolation render carries wherever it is described, and — since the F3.2 fix round
#: — the value written into ``design_web_fragment.preview_basis`` when one is attached.
#:
#: P-7 is explicit that this is an isolation render and NOT a source-site screenshot crop, and a
#: human deciding whether to activate a hidden section is deciding on the strength of one of those
#: two things. The label therefore has to be DURABLE and has to be a fact about the picture: the
#: mint's ``provenance.preview_basis`` is about the mint, and taking its word for a photograph
#: taken later says nothing for a repair and says "measured" for a section the capture measured
#: but could not crop — which would present our own render as a crop of the live site.
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
class IsolationFonts:
    """Resolved faces from the fragment's pinned kit, never a replacement theme."""

    css: str
    asset_digests: tuple[str, ...]


@dataclass(frozen=True)
class IsolationPage:
    """One fragment, rendered alone: the HTML, and the bytes that HTML asks for."""

    fragment_id: str
    html: str
    asset_digests: tuple[str, ...]
    #: The CSS selector the screenshot is taken of — the fragment's own wrapper, so the picture
    #: is the band and not the page chrome around it.
    element_selector: str
    #: What kind of picture this is (P-7). Carried on the page rather than assumed by the caller,
    #: so the value that reaches the row comes from the thing that made it.
    basis: str = ISOLATION_RENDER_BASIS


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


def build_isolation_page(
    core: Any, loaded: Any, *, brand_kit: Any = None, fonts: IsolationFonts | None = None
) -> IsolationPage:
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

    ``fonts`` supplies only the pinned kit's resolved @font-face rules and custodied digests.
    A generated section can use a kit font alias without carrying that font's declaration in
    its own CSS. Supplying those faces matches full-page rendering without changing the
    artifact's styles or choosing a newer theme. The artifact's own CSS still follows them.
    """
    fragment_id = loaded.fragment_id
    asset_base = ISOLATION_ORIGIN + _ASSET_PATH_PREFIX.rstrip("/")
    response = core.web_render(
        isolation_web_doc(fragment_id),
        _PAGE_ID,
        mode="delivery",
        asset_base_url=asset_base,
        brand_kit=brand_kit,
        **({"font_face_css": fonts.css} if fonts is not None else {}),
        fragments={
            fragment_id: {
                **native_render_fields(loaded.payload),
                "html": rebase_artifact_assets(loaded.html, asset_base),
                "slot_kinds": slot_kinds(loaded.slot_manifest),
            }
        },
        fragment_css=rebase_artifact_assets(loaded.css, asset_base),
    )
    return IsolationPage(
        fragment_id=fragment_id,
        html=str(response.get("html") or ""),
        asset_digests=tuple(
            dict.fromkeys(
                (*loaded.asset_digests, *(fonts.asset_digests if fonts is not None else ()))
            )
        ),
        element_selector=f".{fragment_wrapper_class(fragment_id)}",
    )


def held_isolation_asset(
    url: str, assets: Mapping[str, tuple[str, bytes]]
) -> tuple[str, bytes] | None:
    """The bytes this request is asking for, or ``None`` — which means abort.

    Split out of the route handler so the fail-closed rule is testable without a browser: it is
    the thing standing between "a picture of the artifact" and "a picture of the internet", and
    it was previously reachable only by launching Chromium.
    """
    path = urlsplit(url).path
    if not path.startswith(_ASSET_PATH_PREFIX):
        return None
    digest = path[len(_ASSET_PATH_PREFIX) :]
    return assets.get(digest)


#: The inline force: `!important` on the element's own style attribute outranks ANY stylesheet
#: rule regardless of selector specificity — which is the whole point, since the mint-side
#: countermand is a specificity fight it can lose (the CP2 walk's live case: `.section:has(…)`).
_FORCE_VISIBLE_JS = (
    "el => { el.style.setProperty('display', 'revert', 'important');"
    " el.style.setProperty('visibility', 'visible', 'important');"
    " el.style.setProperty('opacity', '1', 'important'); }"
)


async def _surface_element(element: Any) -> bool:
    """Force a hidden fragment visible for its photograph; ``True`` iff it surfaced.

    F4 wave, round 2 (the walk's F-2, then the re-walk's N-1 — this class was missed at TWO
    checkpoints and the first fix aimed too high): harvested CSS is SCOPED
    ``.lumen-frag-<id> <sel>``, so it can only ever hide DESCENDANTS of the engine's wrapper —
    never the wrapper itself. The force therefore lands on the wrapper AND on the artifact's
    own root (the wrapper's first element child), which is exactly the shape the re-walk
    proved yields a legible, honest picture of the walk's own fixture. Hiding any deeper
    stays a refusal — forcing arbitrary descendants would fabricate a layout the source
    never had. The STORED artifact is untouched throughout: this is a photograph, not an
    edit.
    """
    if await element.is_visible():
        return True
    await element.evaluate(_FORCE_VISIBLE_JS)
    artifact_root = await element.query_selector(":scope > *")
    if artifact_root is not None:
        await artifact_root.evaluate(_FORCE_VISIBLE_JS)
    return bool(await element.is_visible())


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
                #
                # Matched on the PATH, not on the whole url: a query string or a fragment after
                # the digest would otherwise land in the lookup key and abort a legitimate asset,
                # which fails in the quiet direction (a hole in the picture) rather than the loud
                # one.
                held = held_isolation_asset(route.request.url, assets)
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
            if not await _surface_element(element):
                raise IsolationRenderFailed(
                    "isolation.section_hidden_by_its_own_css",
                    "the fragment rendered but stays invisible even with its root forced "
                    "visible inline — the hiding lives deeper than the artifact's own root "
                    "(a collapsed descendant structure), where an automatic un-hide would "
                    "fabricate a layout the source never had. This section cannot be "
                    "previewed honestly; repair it through the ladder instead of activating "
                    "it blind.",
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
    from ..design_store import run_isolated

    try:
        return run_isolated(_shoot(page.html, page.element_selector, assets))
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
    fonts: IsolationFonts | None = None,
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
    page = build_isolation_page(core, loaded, brand_kit=brand_kit, fonts=fonts)
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
    "IsolationFonts",
    "IsolationPage",
    "IsolationRenderFailed",
    "build_isolation_page",
    "held_isolation_asset",
    "isolation_web_doc",
    "preview_digest",
    "render_isolation_preview",
    "screenshot_isolation_page",
]
