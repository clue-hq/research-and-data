"""Builders that turn a stored Puck site into something people see: the gallery thumbnail (Task
18), the publish package (Task 20), and the ZIP and PDF exports (Task 22). Every one renders
through ``site_render.render_site`` (agent code only inside the hardened page) and cleans the
result with ``site_sanitize.sanitize_site_html`` before anything sees it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .site_render import RenderedPage, SectionModule, capture_site_screenshot, render_site, site_page_html
from .web_pdf import inline_asset_store_refs

JsonObject = dict[str, Any]

#: The gallery card's own 4:3, captured at half scale (724×543 output) — web_thumbnail_png's frame.
THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT, THUMBNAIL_SCALE = 1448, 1086, 0.5


def site_thumbnail_png(
    document: JsonObject,
    *,
    blobs: Any,
    brand: JsonObject,
    sections: Sequence[SectionModule],
    node_bin: str = "node",
) -> bytes:
    """The top of the site's home page as the gallery card shows it."""
    render = render_site(document["scene"], brand, sections, base_path="", routes=["/"], node_bin=node_bin)
    home = render.pages[0]
    inlined, _missing = inline_asset_store_refs(site_page_html(home, render.css), blobs.read_blob)
    return capture_site_screenshot(
        RenderedPage(route=home.route, html=inlined),
        "",
        width=THUMBNAIL_WIDTH,
        height=THUMBNAIL_HEIGHT,
        full_page=False,
        scale=THUMBNAIL_SCALE,
    )
