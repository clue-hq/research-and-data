"""Shared fixtures for the Puck site suites (Wave 2 Lane A).

The brand and the site come from site-kit's own test fixtures (`apps/frontend/packages/site-kit/
test/fixtures`), so the design API is tested against the exact data the kit's tests use. Site
documents are stored the way the platform births them (`clue_design.documents.create_document`
with `doc_kind="site"`).
"""

from __future__ import annotations

import functools
import hashlib
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from clue_design.storage import SOURCE_KEY_ASSET

REPO_ROOT = Path(__file__).resolve().parents[5]
SITE_KIT = REPO_ROOT / "apps" / "frontend" / "packages" / "site-kit"
FIXTURES = SITE_KIT / "test" / "fixtures"
_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")
_CLONE_IMG = re.compile(r'<img[^>]*?src="(/asset-store/[0-9a-f]{64})"[^>]*?(?:alt="([^"]*)")?')


def _read(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _clone_images(clones: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The images captured with the seller's own sections, exactly as site-kit's `cloneImages`
    (`src/brand.ts`) finds them."""
    found: dict[str, dict[str, Any]] = {}
    for clone in clones:
        for match in _CLONE_IMG.finditer(clone["html"]):
            file = match.group(1)
            if file in found:
                continue
            found[file] = {
                "kind": "captured_image",
                "label": clone["label"],
                "description": match.group(2) or f'From the seller\'s section "{clone["label"]}"',
                "mime": None,
                "file": file,
                "logo": None,
            }
    return found


def garner_brand() -> dict[str, Any]:
    """Garner's BrandData exactly as site-kit's brandData() builds it from the same fixtures: the
    kit's assets plus the images captured with the seller's own sections."""
    clones = _read("clones.json")
    return {
        "slug": "garner",
        "kit": _read("kit.json"),
        "fonts": _read("fonts.json"),
        "assets": {**_read("assets.json"), **_clone_images(clones)},
        "clones": {clone["id"]: clone for clone in clones},
    }


def garner_site(document_id: str, title: str = "Garner for Syracuse") -> dict[str, Any]:
    """The `garner-syracuse` site as a stored site document (Contract 1)."""
    stored = _read("garner-syracuse.json")
    return {
        "id": document_id,
        "title": title,
        "theme": {},
        "pages": stored["pages"],
        "shell": stored["shell"],
        "agent_sections": {},
    }


def garner_site_without_clones(document_id: str) -> dict[str, Any]:
    """Garner's site with only our own sections (no registry needed), and a nav link to /analysis."""
    site = garner_site(document_id)
    for page in site["pages"].values():
        page["content"] = [item for item in page["content"] if item["type"] != "ClonedSection"]
    site["shell"] = {**site["shell"], "header": {**site["shell"]["header"], "nav": [{"label": "The analysis", "href": "/analysis"}]}}
    return site


def conduit_brand() -> dict[str, Any]:
    """Conduit's BrandData exactly as site-kit's `kitBrand("conduit")` builds it
    (`test/fixtures/kits.ts`): the real kit alone — no fonts, no kit assets, no clones."""
    return {"slug": "conduit", "kit": _read("kits/conduit.json"), "fonts": [], "assets": {}, "clones": {}}


def conduit_site(document_id: str, title: str = "Conduit for Atrium Hospitality") -> dict[str, Any]:
    """The `conduit-atrium` site as a stored site document (Contract 1)."""
    stored = _read("conduit-atrium.json")
    return {
        "id": document_id,
        "title": title,
        "theme": {},
        "pages": stored["pages"],
        "shell": stored["shell"],
        "agent_sections": {},
    }


def born_site(document_id: str, title: str = "Garner for Syracuse") -> dict[str, Any]:
    """The empty site a website leg births (platform/api/clue_api/site_documents.py)."""
    return {
        "id": document_id,
        "title": title,
        "theme": {},
        "pages": {"/": {"root": {"props": {"title": title}}, "content": []}},
        "shell": None,
        "agent_sections": {},
    }


def store_site(site: dict[str, Any], *, account_id: str | None = None) -> dict[str, Any]:
    from lumen_api.design_store import HybridRepository

    return HybridRepository().create_document(site, doc_kind="site", account_id=account_id)


def png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


def hold_site_images(site: dict[str, Any], brand: dict[str, Any], blobs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Swap every /asset-store digest the site's pages and shell name for a tiny PNG this
    workspace holds — in the site and in the brand alike — so custody passes as in production."""
    named = json.dumps({"pages": site["pages"], "shell": site["shell"]})
    mapping: dict[str, str] = {}
    for index, old in enumerate(dict.fromkeys(_ASSET_REF.findall(named))):
        data = png(((index * 40) % 256, 120, 200))
        blobs.register(data, media_type="image/png", source_key=SOURCE_KEY_ASSET)
        mapping[old] = hashlib.sha256(data).hexdigest()

    def swap(value: Any) -> Any:
        text = _ASSET_REF.sub(lambda m: "/asset-store/" + mapping.get(m.group(1), m.group(1)), json.dumps(value))
        return json.loads(text)

    return swap(site), swap(brand)


def install_site_inputs(app: Any, brand: dict[str, Any], sections: Sequence[Any] = ()) -> None:
    """Stand in for Lane B's two loaders (site_doc_inputs): this brand, and these section modules."""
    app.state.site_brand_loader = lambda repo, blobs, document: brand
    app.state.site_section_loader = lambda repo, blobs, agent_sections: [
        module for module in sections if agent_sections.get(module.name) == module.digest
    ]


@functools.lru_cache(maxsize=1)
def ensure_site_kit_dist() -> Path:
    """Build site-kit's dist/ once per test process (needs node and apps/frontend/node_modules)."""
    if not (REPO_ROOT / "apps" / "frontend" / "node_modules" / "esbuild").is_dir():
        raise RuntimeError("apps/frontend/node_modules is missing: run `npm ci` in apps/frontend")
    subprocess.run(["node", "bin/build-bundles.mjs"], cwd=SITE_KIT, check=True, capture_output=True, text=True, timeout=300)
    return SITE_KIT / "dist"


QUOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "surface": {"type": "string", "enum": ["page", "card", "muted", "brandSubtle", "brand", "inverse"]},
        "quote": {"type": "string", "minLength": 1},
    },
    "required": ["id", "surface", "quote"],
    "additionalProperties": False,
}

#: A compiled agent section exactly as esbuild emits one (ESM, automatic JSX, three host imports).
QUOTE_JS = """import { jsx } from "react/jsx-runtime";
import { z } from "zod";
export const schema = z.object({ id: z.string(), surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]), quote: z.string().min(1) }).strict();
export function render(props, kit) {
  return jsx(kit.Shell, { surface: props.surface, children: jsx("blockquote", { className: "brand-heading font-headline text-headline", children: props.quote }) });
}
"""


def section_module(name: str, module_js: str, props_schema: dict[str, Any] | None = None, css: str = "") -> Any:
    from lumen_api.site_render import SectionModule

    return SectionModule(
        name=name,
        digest=hashlib.sha256(module_js.encode("utf-8")).hexdigest(),
        module_js=module_js,
        css=css,
        props_schema=props_schema if props_schema is not None else QUOTE_SCHEMA,
    )


def site_with_section(document_id: str, name: str, digest: str, props: dict[str, Any]) -> dict[str, Any]:
    """A one-page site holding one agent section, with Garner's shell."""
    site = garner_site(document_id)
    site["pages"] = {"/": {"root": {"props": {"title": "Section test"}}, "content": [{"type": name, "props": props}]}}
    site["agent_sections"] = {name: digest}
    return site


def site_with_agent_section(name: str, module_js: str) -> tuple[dict[str, Any], list[Any]]:
    """garner-syracuse with one agent section ``name`` appended to its home page, and its module."""
    from lumen_api.site_render import SectionModule

    site = garner_site(f"doc_{name.lower()}")
    digest = hashlib.sha256(module_js.encode("utf-8")).hexdigest()
    site["pages"]["/"]["content"].append({"type": name, "props": {"id": name.lower(), "surface": "page"}})
    site["agent_sections"] = {name: digest}
    return site, [SectionModule(name=name, digest=digest, module_js=module_js, css="", props_schema={})]


@functools.lru_cache(maxsize=1)
def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False
