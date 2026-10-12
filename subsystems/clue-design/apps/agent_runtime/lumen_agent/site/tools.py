"""The site agent's tools (Lane B): the Puck spike's PageTools on the platform's seams.

Plain methods on one object bound to the request's workspace; the harness wraps them as LangChain
tools. Each returns text (or text and image blocks) the agent can act on, never a raised exception.

- validate_page    site-kit's validator (contracts only), agent sections by stored schema
- render_page      Lane A's hardened renderer + screenshots at 1440 and 375 (Task 9)
- restore_version  the site as it was at a saved document version
- view_asset       up to four of this turn's images, with their descriptions
- search_assets    the workspace's images by words and by look (Task 11)
- generate_image   a new image, stored as an AI-generated library asset (Task 10)
- web_search       the platform's open-web search, retried on a transient failure
- fetch_page       a public page through the platform's guard, saved under fetched/
- write_section, view_clone, compare_section   agent sections and rebuilding a clone (Tasks 15, 18)
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from lumen_api.site_kit_cli import SiteKitCliError, validate_site_files

from .inputs import SiteSection, SiteTurnInputs
from .workspace import turn_brand, write_site_files

FETCH_LIMIT = 12_000
VIEW_ASSET_MAX = 4
VIEW_ASSET_PX = 1024
RETRIES = 2
LOOP_GUARD_AT = 3
#: Screenshots keep their width: desktop at half size (720 px wide), mobile at full size (375 px),
#: cut into pieces of at most TILE_PX tall so a model never shrinks a tall page into a sliver.
SCALE_BY_WIDTH = {1440: 0.5, 375: 1.0}
TILE_PX = 1600
_SOURCES = re.compile(r'\bsrc="([^"]*)"|url\(\s*[\'"]?([^\'")\s]+)[\'"]?\s*\)')
_ASSET_FILE = re.compile(r"^/asset-store/([0-9a-f]{64})$")

#: Tool name -> the description the model reads, in the order the model sees them (the spike's
#: order, `search_assets` after `view_asset`). A name joins the tool set when its method exists.
TOOL_DESCRIPTIONS: dict[str, str] = {
    "write_section": (
        "Write a new section as one React file (see the writing-a-section skill). It is checked for "
        "brand tokens and types; if it passes, place it in a page by its name."
    ),
    "view_clone": (
        "Look at one of the seller's captured sections on its own: a desktop (1440 wide) and a "
        "mobile (375 wide) picture, plus its catalog card (words, images, links)."
    ),
    "compare_section": (
        "Show a seller's section (fragment_id) and your component (name, filled with props) side by "
        "side at 1440 and 375 wide, with the share of the area that differs, both heights, and the "
        "original's words that yours is missing."
    ),
    "validate_page": (
        "Check page.json and shell.json against the components, the catalog, the brand and the "
        "evidence. Returns VALID or INVALID with each error and its fix."
    ),
    "render_page": (
        "Render the site and return a desktop (1440 wide) and a mobile (375 wide) full-page "
        "screenshot of one page, with facts about broken images and overflow. route "
        "is \"/\" for page.json or \"/<name>\" for pages/<name>.json. Refuses while the site is invalid."
    ),
    "restore_version": (
        "Bring back the site as it was at an earlier saved version (site.md lists them) into "
        "page.json, shell.json and pages/."
    ),
    "view_asset": (
        "Look at up to four images (files from brand/brand.md, images you generated, or images "
        "search_assets found), each with its description, before you choose one for a section."
    ),
    "search_assets": (
        "Search the seller's images by what they show and how they look. Write what you need in "
        "plain words, for example \"calm classroom, morning light\" or \"product dashboard "
        "screenshot\". Returns the best matches first (up to limit, 1 to 20), each with its file, "
        "type, title and a one-line description. Look at one with view_asset before you use it. "
        "kind narrows to image or logo."
    ),
    "generate_image": (
        "Make a new image for this site in the brand's style (see the images-and-logos skill). "
        "prompt says what it shows; aspect_ratio is the section's shape, such as \"16:9\", \"4:3\" or "
        "\"1:1\"; style_references are one to three of the brand's own photos from brand/brand.md. "
        "Returns the image's path and shows it to you."
    ),
    "web_search": (
        "Search the web. Set include_domains to the seller's domain to find its own published case "
        "studies and customer stories."
    ),
    "fetch_page": (
        "Open a page and save its text under fetched/ as evidence. Use it before you put a number or "
        "a quote from that page on the page."
    ),
}


def digest_of_file(file: str) -> str | None:
    """The sha256 an /asset-store/<sha256> file names, or None."""

    match = _ASSET_FILE.match(file or "")
    return match.group(1) if match else None


class SiteTools:
    def __init__(
        self,
        *,
        workspace: Path,
        inputs: SiteTurnInputs,
        base_site: dict,
        event_sink: Callable[[str, dict], Any] | None = None,
        retry_delay_s: float = 1.0,
    ) -> None:
        self.workspace = Path(workspace)
        self.inputs = inputs
        self.base_site = copy.deepcopy(base_site)
        self.event_sink = event_sink
        self.retry_delay_s = retry_delay_s
        #: The brand this turn validates with: the stored brand, the account's logos, and every
        #: image the turn generates or finds (Contract 1: a blob of this workspace).
        self.brand = turn_brand(inputs.brand, inputs.account_logos)
        #: Sections the pages may place: the workspace's, plus any written this turn.
        self.sections: dict[str, SiteSection] = dict(inputs.agent_sections)
        self._seen: Counter[str] = Counter()
        self._initial_files = self._site_files()
        self.events: list[dict] = []

    # --- helpers ---------------------------------------------------------------------------

    def _record(self, kind: str, **data: Any) -> None:
        self.events.append({"kind": kind, "at": time.time(), **data})
        if self.event_sink is not None:
            try:
                self.event_sink(f"site_{kind}", {key: value for key, value in data.items() if key != "operations"})
            except Exception:  # noqa: BLE001 - progress events are best-effort
                pass

    def _retry(self, operation: Callable[[], Any], what: str) -> Any:
        last: Exception | None = None
        for attempt in range(RETRIES + 1):
            try:
                return operation()
            except Exception as error:  # transient failures are retried, then reported
                last = error
                self._record("retry", what=what, attempt=attempt + 1, error=str(error)[:200])
                if attempt < RETRIES:
                    time.sleep(self.retry_delay_s * (attempt + 1))
        raise RuntimeError(f"{what} failed after {RETRIES + 1} attempts: {last}")

    def _site_files(self) -> dict:
        """The site's files as the validator reads them: page text by route, and shell.json."""

        pages: dict[str, str] = {}
        if (self.workspace / "page.json").exists():
            pages["/"] = (self.workspace / "page.json").read_text()
        folder = self.workspace / "pages"
        for file in sorted(folder.glob("*.json")) if folder.exists() else []:
            pages[f"/{file.stem}"] = file.read_text()
        shell = self.workspace / "shell.json"
        return {"pages": pages, "shell": shell.read_text() if shell.exists() else None}

    def site_unchanged(self) -> bool:
        """True while the agent has not touched the site's files this request."""

        return self._site_files() == self._initial_files

    def _asset_by_file(self) -> dict[str, dict]:
        return {
            asset["file"]: asset
            for asset in (self.brand.get("assets") or {}).values()
            if isinstance(asset, dict) and asset.get("file")
        }

    # --- validate ------------------------------------------------------------------------------

    def _validate_raw(self) -> dict:
        try:
            return validate_site_files(
                self._site_files(), self.brand, {name: s.props_schema for name, s in self.sections.items()}
            )
        except SiteKitCliError as error:
            return {"valid": False, "errors": [f"validator crashed: {error.detail[-500:]}"]}

    def validate_page(self) -> str:
        """Check page.json and shell.json. Returns VALID or INVALID with each error and its fix."""

        result = self._validate_raw()
        if result["valid"]:
            self._seen.clear()
            self._record("valid")
            return "VALID."
        errors = list(result["errors"])
        lines = [f"INVALID ({len(errors)} error{'s' if len(errors) != 1 else ''}):"]
        repeated = []
        for error in errors:
            self._seen[error] += 1
            lines.append(f"- {error}")
            if self._seen[error] == LOOP_GUARD_AT:
                repeated.append(error)
        if repeated:
            self._record("loop_guard", errors=repeated)
            lines.append(
                "\nNOTE: this has failed for the third time: "
                + "; ".join(repeated)
                + ". Try a different approach (another section or slot), or leave that part out and"
                " record why in plan.md."
            )
        self._record("invalid", errors=errors)
        lines.append("\nFix these in page.json / shell.json, then call validate_page again.")
        return "\n".join(lines)

    # --- render --------------------------------------------------------------------------------

    @staticmethod
    def _tiles(png: bytes, scale: float) -> list[dict]:
        from PIL import Image

        blocks = []
        with Image.open(io.BytesIO(png)) as image:
            image = image.convert("RGB")
            if scale != 1.0:
                image = image.resize((round(image.width * scale), round(image.height * scale)))
            for top in range(0, image.height, TILE_PX):
                tile = image.crop((0, top, image.width, min(image.height, top + TILE_PX)))
                buffer = io.BytesIO()
                tile.save(buffer, format="PNG", optimize=True)
                blocks.append({
                    "type": "image",
                    "source_type": "base64",
                    "mime_type": "image/png",
                    "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
                })
        return blocks

    @staticmethod
    def _png_size(png: bytes) -> tuple[int, int]:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(png)) as image:
            return image.width, image.height

    def _broken_images(self, html: str) -> int:
        """Images the rendered page names that this workspace cannot serve (the sanitizer strips any
        source that is not /asset-store/<sha256> or data:, so those count as broken too)."""

        broken = 0
        for match in _SOURCES.finditer(html):
            source = match.group(1) or match.group(2) or ""
            if not source or source.startswith("data:"):
                continue
            digest = digest_of_file(source)
            if digest is None or self.inputs.assets is None or not self.inputs.assets.exists(digest):
                broken += 1
        return broken

    def render_page(self, route: str = "/") -> list[dict] | str:
        """Screenshot one page at 1440 and 375 wide ("/" is page.json, "/analysis" is
        pages/analysis.json). Refuses while the site is invalid."""

        from .workspace import read_site_files, site_pages

        check = self.validate_page()
        if not check.startswith("VALID"):
            return "NOT RENDERED: the site is invalid.\n" + check
        route = "/" + route.strip("/") if route.strip("/") else "/"
        pages = site_pages(self.workspace)
        if route not in pages:
            return f"NOT RENDERED: no page {route}. Pages: {', '.join(pages)}."
        renderer = self.inputs.renderer
        site = read_site_files(self.workspace, self.base_site, self.sections)
        sections = [self.sections[name] for name in site["agent_sections"]]

        def refused(error: Exception) -> str:
            code = getattr(error, "code", None) or type(error).__name__
            return (f"NOT RENDERED: the page could not be drawn ({code}). Validate it and try again; "
                    "if this repeats, say so in your report.")

        if renderer is None:
            return refused(RuntimeError("render.unavailable"))
        try:
            html, css, warnings = renderer.render(site, self.brand, sections, route=route)
        except Exception as error:  # noqa: BLE001 - a refused render is an answer, not a crash
            return refused(error)
        broken = self._broken_images(html)
        blocks: list[dict] = []
        for width in (1440, 375):
            try:
                png = renderer.screenshot(html, css, width=width)
            except Exception as error:  # noqa: BLE001
                return refused(error)
            shot_width, height = self._png_size(png)
            scale = SCALE_BY_WIDTH.get(width, 1.0)
            tiles = self._tiles(png, scale)
            size = "half size" if scale < 1 else "full size"
            notes = f" Render notes: {'; '.join(warnings[:3])}." if warnings and width == 1440 else ""
            blocks.append({
                "type": "text",
                "text": (
                    f"{width} wide: page height {height}px, broken images: {broken}, "
                    f"horizontal overflow: {'yes' if shot_width > width + 1 else 'no'}. "
                    f"Shown at {size} in {len(tiles)} part{'s' if len(tiles) != 1 else ''}, top to bottom.{notes}"
                ),
            })
            blocks.extend(tiles)
        self._record("render", route=route)
        return blocks

    def restore_version(self, version: int) -> str:
        """Bring back the site as it was at a saved version into page.json, shell.json and pages/."""

        port = self.inputs.site_versions
        snapshot = port.site_at(int(version)) if port is not None else None
        if snapshot is None:
            saved = sorted(item["version"] for item in (port.list_versions(50) if port is not None else []))
            return f"No version {version}. Saved versions: {saved or 'none yet'}."
        write_site_files(self.workspace, snapshot)
        self._record("restore", version=int(version))
        return f"restored version {version} into page.json, shell.json and pages/."

    # --- images --------------------------------------------------------------------------------

    def view_asset(self, files: list[str]) -> list[dict] | str:
        """Look at up to four of this site's images, with their descriptions."""

        from lumen_agent.tools.view import _image_bytes_block  # the platform's provider-safe image block

        if not files:
            return "Give one to four image files from brand/brand.md or ones you generated."
        known = self._asset_by_file()
        blocks: list[dict] = []
        for file in files[:VIEW_ASSET_MAX]:
            asset = known.get(file)
            digest = digest_of_file(file)
            if asset is None or digest is None or self.inputs.assets is None:
                blocks.append({"type": "text", "text": f"{file}: not one of this site's images; use a file from "
                               "brand/brand.md or one you generated"})
                continue
            try:
                mime, data = self.inputs.assets.read(digest)
            except Exception as error:  # an unreadable file is an answer, not a crash
                blocks.append({"type": "text", "text": f"{file}: could not be opened ({error})"})
                continue
            if (mime or "").startswith("video/"):
                blocks.append({"type": "text", "text": f"{file}: a video; it cannot be shown as a picture"})
                continue
            try:
                image = _image_bytes_block(data, max_px=VIEW_ASSET_PX)
            except Exception as error:  # an unreadable file is an answer, not a crash
                blocks.append({"type": "text", "text": f"{file}: could not be opened ({error})"})
                continue
            description = asset.get("description") or asset.get("label") or ""
            blocks.append({"type": "text", "text": f"{file}" + (f": {description[:300]}" if description else "")})
            blocks.append(image)
        self._record("view_asset", files=list(files[:VIEW_ASSET_MAX]))
        if files[VIEW_ASSET_MAX:]:
            blocks.append({"type": "text", "text": f"Showed the first {VIEW_ASSET_MAX}; ask again for the rest."})
        return blocks

    def search_assets(self, q: str, kind: str | None = None, limit: int = 8) -> str:
        """Search the seller's images by what they show and how they look."""

        import json

        from lumen_agent.tools.asset_catalog import hybrid_search

        candidates = {
            asset_id: (entry, str(entry.get("origin") or "library"))
            for asset_id, entry in (self.inputs.asset_candidates or {}).items()
        }
        answer = hybrid_search(candidates, q, kind, limit, self.inputs.asset_embeddings)
        for row in answer.get("results") or []:
            row.pop("view", None)
            entry, _ = candidates[row["asset_id"]]
            record = entry.get("record") or {}
            digest = ((record.get("media") or {}).get("digest") or {}).get("value")
            if not isinstance(digest, str) or not _ASSET_FILE.match(f"/asset-store/{digest}"):
                continue
            row["file"] = f"/asset-store/{digest}"
            # Found by search, so placeable: the validator checks images against the turn's brand.
            self.brand.setdefault("assets", {}).setdefault(row["asset_id"], {
                "kind": record.get("kind") or "other", "label": entry.get("title") or record.get("label"),
                "description": entry.get("description"), "mime": (record.get("media") or {}).get("mime_type"),
                "file": row["file"], "logo": record.get("logo"),
            })
        self._record("search_assets", query=q, count=len(answer.get("results") or []))
        return json.dumps(answer)

    # --- research ------------------------------------------------------------------------------

    def fetch_page(self, url: str) -> str:
        """Open a page, save its text under fetched/ as evidence, and return the text."""

        from lumen_agent.tools import web_substrate
        from lumen_ingestion.capture.net import CaptureError

        def get() -> dict:
            return web_substrate._fetch_grounded_page(url)

        try:
            page = get()
        except CaptureError as error:  # a refused or failed URL is deterministic: no retry
            return f"FETCH FAILED: {error}"
        except Exception:  # noqa: BLE001 - a network blip is retried, then reported
            try:
                page = self._retry(get, f"fetch {url}")
            except RuntimeError as error:
                return f"FETCH FAILED: {error}"
        text = str(page.get("text") or "")
        status = page.get("http_status")
        name = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")[:80]
        digest = hashlib.sha1(url.encode()).hexdigest()[:8]
        saved = self.workspace / "fetched" / f"{name}-{digest}.md"
        saved.parent.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        saved.write_text(f"Source: {url}\nFetched: {stamp}\nStatus: {status}\n\n{text}\n")
        self._record("fetch", url=url, status=status)
        return f"Saved to fetched/{saved.name} (status {status}).\n\n{text[:FETCH_LIMIT]}"

    def web_search(self, query: str, include_domains: list[str] | None = None, num_results: int = 8) -> str:
        """The platform's web search. Set include_domains to the seller's domain for its case studies."""

        import json

        reads = self.inputs.platform_reads
        if reads is None:
            return "SEARCH UNAVAILABLE in this run."
        try:
            result = self._retry(
                lambda: reads.web_search(query=query, num_results=num_results, include_domains=include_domains),
                f"search {query!r}",
            )
        except RuntimeError as error:
            return f"SEARCH FAILED: {error}"
        self._record("search", query=query)
        return json.dumps(result, ensure_ascii=False)[:FETCH_LIMIT]


def site_tool_set(tools: SiteTools) -> list:
    """The tools the model sees: every described tool whose method exists, in the described order."""

    from langchain_core.tools import StructuredTool

    return [
        StructuredTool.from_function(getattr(tools, name), name=name, description=description)
        for name, description in TOOL_DESCRIPTIONS.items()
        if callable(getattr(tools, name, None))
    ]
