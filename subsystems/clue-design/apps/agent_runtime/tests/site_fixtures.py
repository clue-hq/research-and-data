"""Shared helpers for the site agent's tests: site-kit's tracked fixtures, fakes for the ports,
and the spike's scripted model (Lane B). Not a conftest, so each test file imports what it uses."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from lumen_agent.site.inputs import SiteSection, SiteTurnInputs

FIXTURES = Path(__file__).resolve().parents[5] / "apps" / "frontend" / "packages" / "site-kit" / "test" / "fixtures"
_CLONE_IMAGE = re.compile(r'<img[^>]*?src="(/asset-store/[0-9a-f]{64})"[^>]*?(?:alt="([^"]*)")?')


def read_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def garner_brand() -> dict:
    """BrandData for Garner, exactly as site-kit's `brandData()` builds the test fixture."""

    clones = read_fixture("clones.json")
    captured: dict[str, dict] = {}
    for clone in clones:
        for match in _CLONE_IMAGE.finditer(clone["html"]):
            file = match.group(1)
            if file in captured:
                continue
            captured[file] = {
                "kind": "captured_image", "label": clone["label"],
                "description": match.group(2) or f'From the seller\'s section "{clone["label"]}"',
                "mime": None, "file": file, "logo": None,
            }
    return {
        "slug": "garner", "kit": read_fixture("kit.json"),
        "fonts": read_fixture("fonts.json"), "assets": {**read_fixture("assets.json"), **captured},
        "clones": {clone["id"]: clone for clone in clones},
    }


def garner_site(document_id: str = "doc_garner") -> dict:
    """The phase-1 Garner page as a stored site document (Contract 1)."""

    stored = read_fixture("garner-syracuse.json")
    return {"id": document_id, "title": "Syracuse City School District", "theme": {},
            "pages": stored["pages"], "shell": stored["shell"], "agent_sections": {}}


def png(colour: str = "white", size: tuple[int, int] = (32, 18)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass
class FakeAssets:
    """SiteAssetPort over a dict of digest -> (media type, bytes)."""

    blobs: dict[str, tuple[str, bytes]] = field(default_factory=dict)
    generated: list[dict] = field(default_factory=list)
    fail_register: bool = False

    def read(self, digest: str) -> tuple[str, bytes]:
        if digest not in self.blobs:
            raise KeyError(digest)
        return self.blobs[digest]

    def exists(self, digest: str) -> bool:
        return digest in self.blobs

    def register_generated(self, *, image_bytes, mime_type, prompt, model, license, provenance) -> dict:
        import hashlib

        if self.fail_register:
            raise RuntimeError("storage down")
        digest = hashlib.sha256(image_bytes).hexdigest()
        self.blobs[digest] = (mime_type, image_bytes)
        self.generated.append({"prompt": prompt, "model": model, "digest": digest})
        return {"asset_id": f"asset_gen_{digest[:12]}", "digest": digest, "file": f"/asset-store/{digest}"}


@dataclass
class FakeVersions:
    """SiteVersionPort over a dict of version -> site."""

    sites: dict[int, dict] = field(default_factory=dict)

    def list_versions(self, limit: int) -> list[dict]:
        return [{"version": v, "actor": "agent", "intent": f"request {v}", "created_at": "2026-10-11T14:02:00+00:00"}
                for v in sorted(self.sites, reverse=True)[:limit]]

    def site_at(self, version: int) -> dict | None:
        return self.sites.get(version)


@dataclass
class FakeRenderer:
    """SiteRenderPort: records what it was asked to draw; answers with fixed HTML and PNGs."""

    html: str = '<main><img src="/asset-store/' + "a" * 64 + '"></main>'
    warnings: list[str] = field(default_factory=list)
    shot: bytes = b""
    fail_code: str | None = None
    calls: list[tuple] = field(default_factory=list)

    def render(self, site, brand, sections, *, route):
        self.calls.append(("render", route, [s.name for s in sections]))
        if self.fail_code:
            error = RuntimeError(self.fail_code)
            error.code = self.fail_code  # type: ignore[attr-defined]
            raise error
        return self.html, ".x{}", list(self.warnings)

    def screenshot(self, html, css, *, width, section_only=False):
        self.calls.append(("screenshot", width, section_only))
        return self.shot or png("white", (width, 2000))


@dataclass
class FakeSections:
    """SiteSectionPort: compiles nothing; answers with a canned section or errors."""

    errors: list[str] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def compile(self, *, name: str, source: str) -> dict:
        self.calls.append((name, source))
        if self.errors:
            return {"ok": False, "errors": list(self.errors)}
        schema = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}, "quote": {"type": "string"}}}
        return {"ok": True, "section": SiteSection(name=name, digest="e" * 64, props_schema=schema, module_js="export {}", css="")}


def inputs_for(brand: dict | None = None, **overrides: Any) -> SiteTurnInputs:
    values: dict[str, Any] = {
        "document_id": "doc_garner", "workspace_id": "ws_test", "brief": "For the page\n",
        "account_name": "Syracuse City School District", "seller": "Garner Health",
        "brand": brand if brand is not None else garner_brand(),
        "catalog": {"catalog/index.md": "# Sections you can use\n", "brand/brand.md": "# Brand: Garner Health\n"},
    }
    values.update(overrides)
    return SiteTurnInputs(**values)


class ScriptedModel(GenericFakeChatModel):
    """Answers with the next scripted message; tools are accepted and ignored (the spike's)."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name: str, args: dict, n: int) -> dict:
    return {"name": name, "args": args, "id": f"call_{n}", "type": "tool_call"}
