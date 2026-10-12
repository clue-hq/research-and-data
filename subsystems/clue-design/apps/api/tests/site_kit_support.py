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


def _read(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def garner_brand() -> dict[str, Any]:
    """Garner's BrandData as site-kit's `brandData()` builds it from the same fixtures, minus the
    clone-captured images (no suite here needs them)."""
    clones = _read("clones.json")
    return {
        "slug": "garner",
        "kit": _read("kit.json"),
        "fonts": _read("fonts.json"),
        "assets": _read("assets.json"),
        "clones": {clone["id"]: clone for clone in clones},
        "measured": _read("measured.json"),
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
