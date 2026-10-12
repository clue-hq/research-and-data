"""The Puck site renderer (Wave 2 Lane A, Contract 3).

Every site render — publish, thumbnail, export, the agent's own preview — runs agent-written
section code inside ONE hardened headless Chromium page (D2, founder ruling 2026-10-11). Python and
Node never import or run it. This module starts with the shared types and paths (Task 11); the
render itself lands in Task 17.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]

RENDER_TIMEOUT = "render.timeout"
OUTPUT_TOO_LARGE = "render.output_too_large"
SECTION_MODULE_MISSING = "render.section_module_missing"
RENDER_FAILED = "render.failed"

#: The monorepo root — `subsystems/clue-design/apps/api/lumen_api/<this file>`.
_REPO_ROOT = Path(__file__).resolve().parents[5]
SITE_KIT_DIST_ENV = "LUMEN_SITE_KIT_DIST"
DEFAULT_SITE_KIT_DIST = _REPO_ROOT / "apps" / "frontend" / "packages" / "site-kit" / "dist"


class SiteRenderError(Exception):
    """A site render, a screenshot or a section-schema read that could not finish.

    ``code`` is one of the four contract codes above; ``message`` says why, in words a caller can
    show (a route's 409/502 body, or the agent's tool answer)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass(frozen=True)
class SectionModule:
    """One compiled agent section as Lane B6's store returns it (Contract 4)."""

    name: str
    digest: str
    module_js: str
    css: str
    props_schema: JsonObject


@dataclass(frozen=True)
class RenderedPage:
    """One route of a rendered site: a whole HTML document, without the site's compiled CSS."""

    route: str
    html: str


@dataclass(frozen=True)
class SiteRender:
    pages: list[RenderedPage]
    css: str
    warnings: list[str] = field(default_factory=list)


def site_kit_dist() -> Path:
    """Where site-kit's built files are: ``LUMEN_SITE_KIT_DIST``, else the checkout's
    ``apps/frontend/packages/site-kit/dist`` (which ``npm run build -w @clue/site-kit`` writes and
    the backend image builds)."""
    override = os.environ.get(SITE_KIT_DIST_ENV, "").strip()
    return Path(override).expanduser() if override else DEFAULT_SITE_KIT_DIST


def site_routes(site: JsonObject) -> list[str]:
    """A site's routes in render order: "/" first, then the others alphabetically."""
    pages = site.get("pages") or {}
    return (["/"] if "/" in pages else []) + sorted(route for route in pages if route != "/")


def pinned_modules(site: JsonObject, sections: Sequence[SectionModule]) -> list[SectionModule]:
    """The modules the site's ``agent_sections`` pin, in pin order. Every pinned name must come
    with exactly its digest, and the module's bytes must hash to it: a module whose bytes changed is
    stale and is refused like a missing one, never rendered as a blank section (the master plan's Review focus 5)."""
    by_name = {module.name: module for module in sections}
    modules: list[SectionModule] = []
    for name, digest in (site.get("agent_sections") or {}).items():
        module = by_name.get(str(name))
        if module is None or module.digest != digest:
            raise SiteRenderError(SECTION_MODULE_MISSING, f"agent section {name} has no stored module {str(digest)[:12]}")
        if hashlib.sha256(module.module_js.encode("utf-8")).hexdigest() != digest:
            raise SiteRenderError(
                SECTION_MODULE_MISSING,
                f"agent section {name}'s stored module is stale (its bytes do not match {str(digest)[:12]})",
            )
        modules.append(module)
    return modules
