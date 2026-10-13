"""What one site turn reads, by value, plus the four capabilities it may call (Lane B).

The design API builds this from the database (lumen_api/site_workspace_view.py); the runtime
only reads it — the rule `AgentRuntimeConfig` follows for brand kits and asset libraries. The
four ports are capabilities rather than values for the reason the cloned-section registry is: a
byte read, a governed write, a document-history read and a hardened render each happen at the
moment the agent asks, through the API's own seams.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "AccountLogo",
    "SiteAssetPort",
    "SiteRenderPort",
    "SiteSection",
    "SiteSectionPort",
    "SiteTurnInputs",
    "SiteVersionPort",
]


@dataclass(frozen=True)
class SiteSection:
    """One compiled agent-written section (Contract 4), as the turn may place and render it."""

    name: str
    digest: str
    props_schema: dict
    module_js: str
    css: str


@dataclass(frozen=True)
class AccountLogo:
    """One of the target account's logos, fetched at the start of the request and stored."""

    cell: str
    file: str
    content_type: str
    label: str | None = None
    alternative: bool = False


class SiteAssetPort(Protocol):
    def read(self, digest: str) -> tuple[str, bytes]:
        """``(media_type, bytes)`` of one of this workspace's blobs; raises when absent."""

    def exists(self, digest: str) -> bool:
        """Whether this workspace durably holds readable bytes for ``digest``."""

    def register_generated(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        model: str | None,
        license: dict | None,
        provenance: dict,
    ) -> dict:
        """Store a generated image as an AI-generated library asset: ``{asset_id, digest, file}``."""


class SiteSectionPort(Protocol):
    def compile(self, *, name: str, source: str) -> dict:
        """Check, compile, read the props schema, store and record one section.

        ``{"ok": True, "section": SiteSection}`` or ``{"ok": False, "errors": [str]}``.
        """


class SiteVersionPort(Protocol):
    def list_versions(self, limit: int) -> list[dict]:
        """The newest ``limit`` saved versions: ``[{version, actor, intent, created_at}]``."""

    def site_at(self, version: int) -> dict | None:
        """The whole site as it was at ``version``, or ``None``."""


class SiteRenderPort(Protocol):
    def render(
        self, site: dict, brand: dict, sections: list[SiteSection], *, route: str
    ) -> tuple[str, str, list[str]]:
        """``(sanitized html of route, css, warnings)``; raises with a ``code`` attribute."""

    def screenshot(self, html: str, css: str, *, width: int, section_only: bool = False) -> bytes:
        """A full-page PNG of rendered HTML at ``width``, network blocked; with ``section_only``, a
        PNG of the page's one section alone (a shell-less scratch site), not padded to the viewport."""


@dataclass(frozen=True)
class SiteTurnInputs:
    """Everything one site turn reads. Built by the design API; read-only to the runtime."""

    document_id: str
    workspace_id: str
    #: brief.md: the delegation brief plus "THIS ARTIFACT: <json>" (the spike's format).
    brief: str
    account_name: str
    #: The seller's name, the title of brand/brand.md.
    seller: str
    #: site-kit BrandData (lumen_api/site_brand.py); every file is /asset-store/<sha256>.
    brand: dict
    #: {relative path: markdown} from site-kit's catalog CLI: catalog/* and brand/brand.md.
    catalog: dict[str, str]
    overview: list[dict] = field(default_factory=list)
    insights: list[dict] = field(default_factory=list)
    #: Served AccountClaimView dicts about the account (read_cited_claims@1).
    claims: list[dict] = field(default_factory=list)
    #: Cited ids held back by a real rule: statements citing them leave the research files.
    held_claim_ids: frozenset[str] = frozenset()
    #: [{path, body_text}] — the opening turn's pinned instructions.md and decisions.md.
    project_files: list[dict] = field(default_factory=list)
    account_logos: list[AccountLogo] = field(default_factory=list)
    #: Sections the turn may place: the document's own pins plus the newest of each name.
    agent_sections: dict[str, SiteSection] = field(default_factory=dict)
    #: {asset_id: {"record": AssetRecord, "description"?, "title"?, "tags"?, "origin": str}}.
    asset_candidates: dict = field(default_factory=dict)
    #: {asset_id: [512 floats]} CLIP vectors, or None when visual search is off.
    asset_embeddings: dict | None = None
    #: The platform reads (web_search, seller_knowledge), or None outside a leg.
    platform_reads: Any = None
    assets: SiteAssetPort | None = None
    sections: SiteSectionPort | None = None
    site_versions: SiteVersionPort | None = None
    renderer: SiteRenderPort | None = None
    #: Test seam for image generation; None means lumen_api.image_provider.generate.
    image_generate: Any = None
