"""What a site check, render or publish needs besides the stored site: its brand and its
agent-section modules (Wave 2 Lane A; Lane B fills both).

Two seams, each a callable on ``app.state`` and on the governed tools' host:

* ``site_brand_loader(repo, blobs, document) -> BrandData`` — Lane B2 builds site-kit's
  ``BrandData`` from the document's brand kit (fonts and assets as ``/asset-store/<sha256>``).
  Until then the default refuses with ``site_inputs.unavailable``: a site cannot be checked,
  rendered or published without its brand.
* ``site_section_loader(repo, blobs, {name: digest}) -> [SectionModule]`` — Lane B6 reads the
  workspace's stored modules (Contract 4) and raises ``render.section_module_missing`` for a digest
  the workspace does not hold. Until then the default serves a site with no agent sections and
  refuses one that has them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .site_render import SECTION_MODULE_MISSING, SectionModule, SiteRenderError, pinned_modules

JsonObject = dict[str, Any]

SiteBrandLoader = Callable[[Any, Any, JsonObject], JsonObject]
SiteSectionLoader = Callable[[Any, Any, Mapping[str, str]], list[SectionModule]]


class SiteInputsUnavailable(Exception):
    """The site's brand (or another input Lane B owns) cannot be built in this process."""

    code = "site_inputs.unavailable"


def brand_loader_not_composed(repo: Any, blobs: Any, document: JsonObject) -> JsonObject:
    raise SiteInputsUnavailable(
        "the site's brand cannot be built in this process yet: the BrandData builder "
        "(Lane B2, app.state.site_brand_loader) is not composed"
    )


def sections_not_stored(repo: Any, blobs: Any, agent_sections: Mapping[str, str]) -> list[SectionModule]:
    if not agent_sections:
        return []
    raise SiteRenderError(
        SECTION_MODULE_MISSING,
        "no stored module for agent section(s) " + ", ".join(sorted(agent_sections))
        + " (the section store, Lane B6, is not composed)",
    )


def load_section_modules(loader: SiteSectionLoader, repo: Any, blobs: Any, site: JsonObject) -> list[SectionModule]:
    """The site's agent-section modules through ``loader``, checked against the site's own pins
    (``site_render.pinned_modules``)."""
    pins = {str(name): str(digest) for name, digest in (site.get("agent_sections") or {}).items()}
    return pinned_modules(site, loader(repo, blobs, pins))
