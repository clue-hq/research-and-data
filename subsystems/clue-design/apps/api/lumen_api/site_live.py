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
from collections.abc import Mapping
from dataclasses import dataclass

from . import web_export
from .site_render import RENDER_FAILED, SiteRenderError, site_kit_dist

LIVE_WORKSPACES_ENV = "LUMEN_SITE_LIVE_WORKSPACES"
SHIM_FILES = {"react": "react.js", "react/jsx-runtime": "react-jsx-runtime.js", "zod": "zod.js"}


def live_sites_enabled(workspace_id: str) -> bool:
    listed = {
        part.strip() for part in os.environ.get(LIVE_WORKSPACES_ENV, "").split(",") if part.strip()
    }
    return workspace_id in listed


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
    head = f'<script type="importmap">{import_map}</script>\n'
    tail = (
        f'<script type="application/json" id="clue-page-data">{_inert_json(page_data)}</script>'
        f'<script type="module" src="{runtime_url}"></script>'
    )
    return web_export._inject_before_head_close(html, head).replace("</body>", tail + "</body>", 1)
