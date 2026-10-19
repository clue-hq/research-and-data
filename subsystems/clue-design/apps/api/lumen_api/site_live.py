"""Live Puck sites (publishing live sites, phase 1): which workspaces publish them, and how a live
page is put together around the server's HTML.

A live page is the hardened render's HTML plus, in this order: the site's CSS and our head (as a
static page has), the inline import map (head) that points react, react/jsx-runtime and zod at
the host shims, the page data as inert JSON, and the site runtime as a module script. The runtime
and the shims are site-kit's build output (``dist/site-runtime.js``,
``dist/site-runtime-shims/``); every file is published by its sha256 under ``/p-assets/``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from . import web_export
from .site_render import (
    RENDER_FAILED,
    RenderedPage,
    SectionModule,
    SiteRenderError,
    site_kit_dist,
    site_page_html,
)

LIVE_WORKSPACES_ENV = "LUMEN_SITE_LIVE_WORKSPACES"
SHIM_FILES = {"react": "react.js", "react/jsx-runtime": "react-jsx-runtime.js", "zod": "zod.js"}


def live_sites_enabled(workspace_id: str) -> bool:
    """Whether this workspace publishes live sites: it is listed, or the list holds `*` (every
    workspace; founder 2026-10-15, what production sets)."""
    listed = {
        part.strip() for part in os.environ.get(LIVE_WORKSPACES_ENV, "").split(",") if part.strip()
    }
    return "*" in listed or workspace_id in listed


@dataclass(frozen=True)
class LiveRuntime:
    runtime_js: bytes
    #: Keyed by the host specifier the import map names ("react", "react/jsx-runtime", "zod").
    shims: dict[str, bytes]


def live_runtime() -> LiveRuntime:
    dist = site_kit_dist()
    runtime = dist / "site-runtime.js"
    shims = {
        specifier: dist / "site-runtime-shims" / name for specifier, name in SHIM_FILES.items()
    }
    missing = [path for path in (runtime, *shims.values()) if not path.is_file()]
    if missing:
        raise SiteRenderError(
            RENDER_FAILED,
            f"the site runtime is not built ({missing[0]} is missing): "
            "run `npm run build -w @clue/site-kit` in apps/frontend",
        )
    return LiveRuntime(
        runtime_js=runtime.read_bytes(), shims={s: p.read_bytes() for s, p in shims.items()}
    )


def import_map_json(urls: Mapping[str, str]) -> str:
    return json.dumps(
        {"imports": dict(sorted(urls.items()))}, separators=(",", ":"), sort_keys=True
    )


def script_hash(text: str) -> str:
    """The CSP source for an inline script whose text is ``text``."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def import_map_element(import_map: str) -> str:
    """The inline import map exactly as ``live_page_html`` writes it: the last thing in the head."""
    return f'<script type="importmap">{import_map}</script>\n'


def _inert_json(value: object) -> str:
    # "<" escaped everywhere, so no string in the data can end or confuse the inert element.
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.replace("<", "\\u003c")


def live_page_html(
    html: str,
    data: Mapping[str, object],
    *,
    section_urls: Mapping[str, str],
    import_map: str,
    runtime_url: str,
) -> str:
    """``html`` (one whole page, exactly one ``</body>``) with the import map in its head and the
    page data and the runtime at the end of its body."""
    page_data = {**data, "sections": dict(sorted(section_urls.items()))}
    head = import_map_element(import_map)
    tail = (
        f'<script type="application/json" id="clue-page-data">{_inert_json(page_data)}</script>'
        f'<script type="module" src="{runtime_url}"></script>'
    )
    return web_export._inject_before_head_close(html, head).replace("</body>", tail + "</body>", 1)


_PREVIEW_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' data:; style-src 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; media-src 'self'; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
)


def _data_module(source: str | bytes) -> str:
    text = source.decode("utf-8") if isinstance(source, bytes) else source
    return "data:text/javascript;charset=utf-8," + urllib.parse.quote(text)


def live_preview_document(
    page: RenderedPage, css: str, modules: Sequence[SectionModule], runtime: LiveRuntime
) -> str:
    """The live page as one self-contained document for the agent's screenshot inside the hardened
    page (no network): CSS inline; the shims, the sections and the runtime as ``data:`` modules (the
    runtime is never inlined: its text holds "<!--" and "<script", which can make the HTML parser
    end an inline script early). Its own CSP meta sits immediately before the import map, so it
    covers every script on the page (as on a published live page)."""
    import_map = import_map_json(
        {specifier: _data_module(data) for specifier, data in runtime.shims.items()}
    )
    html = live_page_html(
        site_page_html(page, css),
        page.data or {},
        section_urls={module.name: _data_module(module.module_js) for module in modules},
        import_map=import_map,
        runtime_url=_data_module(runtime.runtime_js),
    )
    meta = f'<meta http-equiv="Content-Security-Policy" content="{_PREVIEW_CSP}">\n'
    element = import_map_element(import_map)
    return html.replace(element, meta + element, 1)
