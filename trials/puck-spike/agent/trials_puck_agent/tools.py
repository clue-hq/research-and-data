"""The agent's tools on Puck pages (T2 of the phase-2 spike).

Plain methods on one object bound to a run workspace; the runner (T3) wraps them as LangChain
tools. Each returns text the agent can act on, never a raised exception.

- validate_page   the component schemas + brand/evidence checks (scripts/validate-page.ts);
                  a valid page is saved as a new version; a repeated error trips the loop guard
- render_page     refuses an invalid page; otherwise one desktop (1440) and one mobile (375)
                  full-page screenshot plus runtime facts
- fetch_page      opens a page, saves its text under fetched/ (evidence), returns the text
- web_search      the platform's web search, retried on transient failure
- restore_version rolls page.json and shell.json back to a saved version
- view_asset      shows up to four images (the brand's, or this site's generated ones) with their
                  descriptions (the platform's provider-safe image block from lumen_agent/tools/view.py)
- generate_image  makes a new image for this site with the platform's image provider, in the
                  brand's style (up to three brand images as references), saves it under
                  public/generated/<site>/ with its prompt as its description, and shows it
- view_clone, compare_section   the component library spike: see a seller's section on its own,
                  and compare a rebuilt component with it side by side (difference score, missing words)
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

FETCH_LIMIT = 12_000
#: Screenshots keep their width: desktop at half size (720 px wide), mobile at full size (375 px),
#: cut into pieces of at most TILE_PX tall so a model never shrinks a tall page into a sliver.
SCALE_BY_WIDTH = {1440: 0.5, 375: 1.0}
TILE_PX = 1600
VIEW_ASSET_MAX = 4
BUILT_IN_SECTIONS = {"ClonedSection", "StatsBand", "FeatureSplit", "ProofCard", "CtaBand", "TokenProbe"}
VIEW_ASSET_PX = 1024
STYLE_REFERENCES_MAX = 3
REFERENCE_PX = 1024
IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
RETRIES = 2
LOOP_GUARD_AT = 3


class PageTools:
    def __init__(
        self,
        *,
        workspace: Path,
        spike_root: Path,
        base_url: str,
        reads: Any = None,
        retry_delay_s: float = 1.0,
        image_generate: Callable[..., Any] | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.spike_root = Path(spike_root)
        self.base_url = base_url.rstrip("/")
        self.reads = reads
        self.retry_delay_s = retry_delay_s
        self._image_generate = image_generate
        self._seen: Counter[str] = Counter()
        self.events: list[dict] = []  # for the run record: what failed and how it ended

    # --- helpers -------------------------------------------------------------------------------

    def _run(self) -> dict:
        return json.loads((self.workspace / ".run.json").read_text())

    def _record(self, kind: str, **data: Any) -> None:
        self.events.append({"kind": kind, "at": time.time(), **data})

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

    def _versions(self) -> Path:
        path = self.workspace / "versions"
        path.mkdir(exist_ok=True)
        return path

    # --- validate ------------------------------------------------------------------------------

    def _validate_raw(self) -> dict:
        completed = subprocess.run(
            ["npx", "tsx", "scripts/validate-page.ts", str(self.workspace)],
            cwd=self.spike_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return {"valid": False, "errors": [f"validator crashed: {completed.stderr.strip()[-500:]}"]}
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def validate_page(self) -> str:
        """Check page.json and shell.json. Returns VALID (and saves a version) or INVALID with errors."""
        result = self._validate_raw()
        if result["valid"]:
            versions = self._versions()
            number = len(list(versions.glob("*.json"))) + 1
            snapshot = {
                "page": json.loads((self.workspace / "page.json").read_text()),
                "shell": json.loads((self.workspace / "shell.json").read_text()),
                "pages": {route: page for route, page in self._pages().items() if route != "/"},
            }
            (versions / f"{number}.json").write_text(json.dumps(snapshot, indent=2))
            self._seen.clear()
            self._record("valid", version=number)
            return f"VALID. Saved as version {number} (restore_version can bring it back)."

        errors = result["errors"]
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

    def restore_version(self, version: int) -> str:
        """Roll page.json, shell.json and pages/ back to a version saved by validate_page."""
        path = self._versions() / f"{int(version)}.json"
        if not path.exists():
            saved = sorted(int(p.stem) for p in self._versions().glob("*.json"))
            return f"No version {version}. Saved versions: {saved or 'none yet'}."
        snapshot = json.loads(path.read_text())
        (self.workspace / "page.json").write_text(json.dumps(snapshot["page"], indent=2))
        (self.workspace / "shell.json").write_text(json.dumps(snapshot["shell"], indent=2))
        pages_dir = self.workspace / "pages"
        if pages_dir.exists():
            for stale in pages_dir.glob("*.json"):
                stale.unlink()
        for route, page in (snapshot.get("pages") or {}).items():
            pages_dir.mkdir(exist_ok=True)
            (pages_dir / f"{route.strip('/')}.json").write_text(json.dumps(page, indent=2))
        self._record("restore", version=int(version))
        return f"restored version {version} into page.json, shell.json and pages/."

    # --- render --------------------------------------------------------------------------------

    def _pages(self) -> dict[str, dict]:
        """Every page of the site by route: page.json is "/", pages/<name>.json is "/<name>"."""
        pages = {"/": json.loads((self.workspace / "page.json").read_text())}
        for file in sorted((self.workspace / "pages").glob("*.json")) if (self.workspace / "pages").exists() else []:
            pages[f"/{file.stem}"] = json.loads(file.read_text())
        return pages

    def _publish_for_preview(self, route: str = "/") -> str:
        run = self._run()
        site_file = self.spike_root / "data" / "sites" / f"{run['site']}.json"
        site = {"brand": run["brand"], "shell": json.loads((self.workspace / "shell.json").read_text()),
                "pages": self._pages()}
        site_file.write_text(json.dumps(site, indent=2))
        return f"{self.base_url}/s/{run['site']}{'' if route == '/' else route}"

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

    def render_page(self, route: str = "/") -> list[dict] | str:
        """Screenshot one page at 1440 and 375 wide ("/" is page.json, "/analysis" is
        pages/analysis.json). Refuses while the site is invalid."""
        check = self.validate_page()
        if not check.startswith("VALID"):
            return "NOT RENDERED: the site is invalid.\n" + check
        route = "/" + route.strip("/") if route.strip("/") else "/"
        if route not in self._pages():
            return f"NOT RENDERED: no page {route}. Pages: {', '.join(self._pages())}."
        url = self._publish_for_preview(route)
        from playwright.sync_api import sync_playwright

        renders = self.workspace / "renders"
        renders.mkdir(exist_ok=True)
        round_number = len({p.name.split("-")[0] for p in renders.glob("*.png")}) + 1

        blocks: list[dict] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (1440, 375):
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                self._retry(lambda: page.goto(url, wait_until="load", timeout=60_000), "render")
                page.add_style_tag(content="nextjs-portal{display:none!important}")  # the dev server's badge
                page.wait_for_timeout(1500)
                height = page.evaluate("document.body.scrollHeight")
                for y in range(0, height, 600):
                    page.evaluate(f"window.scrollTo(0,{y})")
                    page.wait_for_timeout(60)
                page.evaluate("window.scrollTo(0,0)")
                page.wait_for_timeout(400)
                facts = page.evaluate(
                    """() => ({
                      broken: [...document.images].filter(i => i.complete && i.naturalWidth === 0).length,
                      overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
                      sections: document.querySelectorAll('main > *, .brand-root > section, [data-lumen-fragment]').length,
                    })"""
                )
                png = page.screenshot(full_page=True)
                name = "home" if route == "/" else route.strip("/").replace("/", "-")
                (renders / f"{round_number}-{name}-{width}.png").write_bytes(png)
                tiles = self._tiles(png, SCALE_BY_WIDTH.get(width, 1.0))
                size = "half size" if SCALE_BY_WIDTH.get(width, 1.0) < 1 else "full size"
                blocks.append({
                    "type": "text",
                    "text": (
                        f"{width} wide: page height {height}px, broken images: {facts['broken']}, "
                        f"horizontal overflow: {'yes' if facts['overflow'] else 'no'}, "
                        f"console errors: {len(errors)}{(' (' + '; '.join(errors[:3]) + ')') if errors else ''}. "
                        f"Shown at {size} in {len(tiles)} part{'s' if len(tiles) != 1 else ''}, top to bottom."
                    ),
                })
                blocks.extend(tiles)
                page.close()
            browser.close()
        self._record("render", url=url, route=route)
        return blocks

    # --- images --------------------------------------------------------------------------------

    def _generated_dir(self) -> Path:
        return self.spike_root / "public" / "generated" / self._run()["site"]

    def _generated_index(self) -> dict[str, dict]:
        index = self._generated_dir() / "index.json"
        return json.loads(index.read_text()) if index.exists() else {}

    def _asset_descriptions(self) -> dict[str, str]:
        assets_file = self.spike_root / "data" / "brands" / self._run()["brand"] / "assets.json"
        assets = json.loads(assets_file.read_text()) if assets_file.exists() else {}
        described = {a["file"]: (a.get("description") or a.get("label") or "") for a in assets.values()}
        described.update({file: f"generated: {entry['prompt']}" for file, entry in self._generated_index().items()})
        return described

    def view_asset(self, files: list[str]) -> list[dict] | str:
        """Look at up to four images (the brand's from brand/brand.md, or this site's generated ones),
        with their descriptions."""
        from lumen_agent.tools.view import _image_bytes_block  # the platform's provider-safe image block

        if not files:
            return "Give one to four image files from brand/brand.md or ones you generated."
        descriptions = self._asset_descriptions()
        run = self._run()
        own = (f"/brands/{run['brand']}/", f"/generated/{run['site']}/", f"/accounts/{run['site']}/")
        blocks: list[dict] = []
        for file in files[:VIEW_ASSET_MAX]:
            path = self.spike_root / "public" / file.lstrip("/")
            if not file.startswith(own) or not path.is_file():
                blocks.append({"type": "text", "text": f"{file}: not one of this site's images; use a file from "
                               "brand/brand.md or one you generated"})
                continue
            if path.suffix.lower() in (".mp4", ".webm", ".mov"):
                blocks.append({"type": "text", "text": f"{file}: a video; it cannot be shown as a picture"})
                continue
            try:
                image = _image_bytes_block(path.read_bytes(), max_px=VIEW_ASSET_PX)
            except Exception as error:  # an unreadable file is an answer, not a crash
                blocks.append({"type": "text", "text": f"{file}: could not be opened ({error})"})
                continue
            description = descriptions.get(file, "")
            blocks.append({"type": "text", "text": f"{file}" + (f": {description[:300]}" if description else "")})
            blocks.append(image)
        self._record("view_asset", files=list(files[:VIEW_ASSET_MAX]))
        if files[VIEW_ASSET_MAX:]:
            blocks.append({"type": "text", "text": f"Showed the first {VIEW_ASSET_MAX}; ask again for the rest."})
        return blocks

    def _reference(self, file: str) -> tuple[bytes, str] | str:
        """One brand image as a PNG reference for the image model, or the reason it cannot be one."""
        from PIL import Image

        path = self.spike_root / "public" / file.lstrip("/")
        if not file.startswith(f"/brands/{self._run()['brand']}/") or not path.is_file():
            return f"{file}: not one of this brand's images; use a file from brand/brand.md"
        if path.suffix.lower() in (".svg", ".mp4", ".webm", ".mov"):
            return f"{file}: a style reference must be a photo or picture, not a logo file or a video"
        try:
            image = Image.open(path)
            image.thumbnail((REFERENCE_PX, REFERENCE_PX))
            buffer = io.BytesIO()
            image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB").save(buffer, format="PNG")
        except Exception as error:  # an unreadable file is an answer, not a crash
            return f"{file}: could not be opened ({error})"
        return buffer.getvalue(), "image/png"

    def generate_image(
        self, prompt: str, aspect_ratio: str = "16:9", style_references: list[str] | None = None
    ) -> list[dict] | str:
        """Make a new image for this site, in the brand's style (see the images-and-logos skill)."""
        from lumen_agent.tools.view import _image_bytes_block

        references = list(style_references or [])
        if len(references) > STYLE_REFERENCES_MAX:
            return f"Give at most three style references (you gave {len(references)})."
        prepared: list[tuple[bytes, str]] = []
        for file in references:
            reference = self._reference(file)
            if isinstance(reference, str):
                return reference
            prepared.append(reference)
        generate = self._image_generate
        if generate is None:
            from lumen_api.image_provider import generate  # the platform's image provider
        try:
            result = generate(prompt=prompt, aspect_ratio=aspect_ratio, reference_images=prepared or None)
        except Exception as error:  # the provider failing is an answer, not a crash
            self._record("generate_image", ok=False, error=str(error)[:200])
            return f"The image model could not make the image ({str(error)[:200]}). Try once more with a shorter " \
                   "prompt, or choose a section without an image."
        extension = IMAGE_EXTENSIONS.get(result.mime_type, ".png")
        name = hashlib.sha256(result.image_bytes).hexdigest()[:16] + extension
        folder = self._generated_dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(result.image_bytes)
        file = f"/generated/{self._run()['site']}/{name}"
        index = self._generated_index()
        index[file] = {"prompt": prompt, "aspect_ratio": aspect_ratio, "style_references": references,
                       "width": result.width, "height": result.height, "model": getattr(result, "model", None),
                       "at": datetime.now(timezone.utc).isoformat()}
        (folder / "index.json").write_text(json.dumps(index, indent=2))
        self._record("generate_image", ok=True, file=file, model=getattr(result, "model", None))
        size = f"{result.width}x{result.height}" if result.width and result.height else "size unknown"
        return [
            {"type": "text", "text": f"{file} ({size}). Look at it before you use it: put this path in an image "
             "slot or image prop, or leave it out if it breaks the images-and-logos rules."},
            _image_bytes_block(result.image_bytes, max_px=VIEW_ASSET_PX),
        ]

    # --- new sections (E5) -----------------------------------------------------------------------

    def write_section(self, name: str, code: str) -> str:
        """Write a new section as one React file. It must pass the brand-token check and type-check;
        only then does it join this site, under its name."""
        if not re.fullmatch(r"[A-Z][A-Za-z0-9]{2,40}", name or ""):
            return "NOT WRITTEN: a section name is PascalCase letters and digits, for example StepsBand."
        if name in BUILT_IN_SECTIONS:
            return f"NOT WRITTEN: {name} is one of the built-in sections; choose another name."
        site = self._run()["site"]
        # Checked outside the app first: a broken file inside it would break every page on the dev server.
        pending_dir = self.spike_root / "agent-runs" / ".section-check" / site
        pending_dir.mkdir(parents=True, exist_ok=True)
        pending = pending_dir / f"{name}.tsx"
        pending.write_text(code)
        completed = subprocess.run(
            ["npx", "tsx", "scripts/check-section.ts", str(pending)],
            cwd=self.spike_root, capture_output=True, text=True, timeout=180,
        )
        try:
            result = json.loads(completed.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            return f"NOT WRITTEN: the check crashed: {completed.stderr.strip()[-500:]}"
        if not result["ok"]:
            self._record("section_refused", name=name, errors=result["errors"])
            return "NOT WRITTEN (fix these, then call write_section again):\n" + "\n".join(f"- {e}" for e in result["errors"])
        target = self.spike_root / "puck" / "agent-sections" / site / f"{name}.tsx"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code)
        self._write_section_index()
        self._record_component(name, result["props"] or {})
        self._record("section_written", name=name)
        return (f"WRITTEN: {name} is ready for this site. Place it in a page with \"type\": \"{name}\" and "
                f"these props:\n{json.dumps(result['props'], indent=1)[:4000]}")

    def _write_section_index(self) -> None:
        """puck/agent-sections/index.ts: every site's sections, imported for the config and validator."""
        root = self.spike_root / "puck" / "agent-sections"
        files = sorted(root.glob("*/*.tsx"))
        lines = ["// Written by write_section (tools.py). Every site's agent-written sections.",
                 'import type { AgentSectionModule } from "../agent-kit";']
        entries: dict[str, list[str]] = {}
        for n, file in enumerate(files):
            lines.append(f'import * as s{n} from "./{file.parent.name}/{file.stem}";')
            entries.setdefault(file.parent.name, []).append(f'"{file.stem}": s{n} as unknown as AgentSectionModule')
        lines.append("export const AGENT_SECTIONS: Record<string, Record<string, AgentSectionModule>> = {")
        lines += [f'  "{site}": {{ {", ".join(items)} }},' for site, items in entries.items()]
        lines.append("};")
        (root / "index.ts").write_text("\n".join(lines) + "\n")

    # --- rebuilding the seller's sections (component library spike) -----------------------------

    def _scratch_url(self, content: list[dict]) -> str:
        """A one-page preview site holding just these sections, able to use this run's agent sections."""
        run = self._run()
        name = f"{run['site']}-scratch"
        site = {"brand": run["brand"], "sectionsSite": run["site"],
                "pages": {"/": {"root": {"props": {"title": "scratch"}}, "content": content}}}
        (self.spike_root / "data" / "sites" / f"{name}.json").write_text(json.dumps(site))
        return f"{self.base_url}/s/{name}"

    def _shoot_sections(self, url: str, width: int, expected: int) -> list[tuple[bytes, str]]:
        """A screenshot and the visible text of each section on the page, in order."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": 900})
            shots: list[tuple[bytes, str]] = []
            for attempt in range(4):  # a just-written section can take a moment to reach the dev server
                self._retry(lambda: page.goto(url, wait_until="load", timeout=60_000), "preview")
                page.add_style_tag(content="nextjs-portal{display:none!important}")  # the dev server's badge
                page.wait_for_timeout(1500)
                height = page.evaluate("document.body.scrollHeight")
                for y in range(0, height, 600):
                    page.evaluate(f"window.scrollTo(0,{y})")
                    page.wait_for_timeout(60)
                page.evaluate("window.scrollTo(0,0)")
                page.wait_for_timeout(300)
                handles = page.query_selector_all(".brand-root > div.lumen-fragment, .brand-root > [data-agent-section]")
                if len(handles) >= expected:
                    shots = [(h.screenshot(), h.inner_text()) for h in handles[:expected]]
                    break
                page.wait_for_timeout(2000 * (attempt + 1))
            browser.close()
        return shots

    def view_clone(self, fragment_id: str) -> list[dict] | str:
        """Look at one of the seller's sections on its own: desktop and mobile pictures, plus its card."""
        brand = self._run()["brand"]
        clones = {c["id"] for c in json.loads((self.spike_root / "data" / "brands" / brand / "clones.json").read_text())}
        if fragment_id not in clones:
            return f"No clone {fragment_id}; see catalog/index.md."
        url = self._scratch_url([{"type": "ClonedSection", "props": {
            "id": "original", "fragmentId": fragment_id, "slots": {}, "replacements": [], "links": []}}])
        card_path = self.workspace / "catalog" / "clones" / f"{fragment_id}.md"
        blocks: list[dict] = [{"type": "text", "text": card_path.read_text()[:4000] if card_path.exists() else fragment_id}]
        for width in (1440, 375):
            shots = self._shoot_sections(url, width, expected=1)
            if not shots:
                return f"Could not show {fragment_id} (the preview did not render)."
            tiles = self._tiles(shots[0][0], SCALE_BY_WIDTH.get(width, 1.0))
            blocks.append({"type": "text", "text": f"The original at {width} wide, in {len(tiles)} part(s), top to bottom."})
            blocks.extend(tiles)
        self._record("view_clone", fragment_id=fragment_id)
        return blocks

    def compare_section(self, name: str, fragment_id: str, props: dict) -> list[dict] | str:
        """Show the original section and your component side by side, with a difference score and
        the original's words your version is missing."""
        site = self._run()["site"]
        if not (self.spike_root / "puck" / "agent-sections" / site / f"{name}.tsx").exists():
            return f"No component {name} on this site yet; write it with write_section first."
        props = {"id": "rebuilt", "surface": "page", **(props or {})}
        url = self._scratch_url([
            {"type": "ClonedSection", "props": {"id": "original", "fragmentId": fragment_id, "slots": {}, "replacements": [], "links": []}},
            {"type": name, "props": props},
        ])
        blocks: list[dict] = []
        summary: list[str] = []
        scores: dict[int, float] = {}
        for width in (1440, 375):
            shots = self._shoot_sections(url, width, expected=2)
            if len(shots) < 2:
                return (f"Could not compare: the preview did not show both sections. Check that the props fit "
                        f"{name}'s schema (catalog/seller-components.md).")
            (original, original_text), (rebuilt, rebuilt_text) = shots
            score, pair, heights = _difference(original, rebuilt)
            scores[width] = score
            summary.append(f"{width} wide: {score:.0%} of the area differs; heights {heights[0]}px (original) "
                           f"and {heights[1]}px (yours).")
            if width == 1440:
                missing = _missing_words(original_text, rebuilt_text)
                summary.append("Words of the original missing from yours: "
                               + (", ".join(missing[:40]) if missing else "none") + ".")
            tiles = self._tiles(pair, 0.5 if width == 1440 else 1.0)
            blocks.append({"type": "text", "text": f"Side by side at {width} wide (original left, yours right), "
                                                   f"in {len(tiles)} part(s)."})
            blocks.extend(tiles)
        self._record("compare", name=name, fragment_id=fragment_id, scores=scores)
        return [{"type": "text", "text": "\n".join(summary)}] + blocks

    def _record_component(self, name: str, props_schema: dict) -> None:
        """catalog/seller-components.md: every component rebuilt or written for this site, with its props."""
        path = self.workspace / "catalog" / "seller-components.md"
        entries: dict[str, str] = {}
        if path.exists():
            for chunk in path.read_text().split("\n## ")[1:]:
                entries[chunk.split("\n", 1)[0].strip()] = chunk.split("\n", 1)[1] if "\n" in chunk else ""
        entries[name] = f"Use it with `\"type\": \"{name}\"` and these props:\n\n```json\n{json.dumps(props_schema, indent=1)}\n```\n"
        text = "# The seller's components on this site\n\nWritten for you as each one is written. Use them like any section.\n"
        text += "".join(f"\n## {n}\n{body}" for n, body in entries.items())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    # --- research ------------------------------------------------------------------------------

    def fetch_page(self, url: str) -> str:
        """Open a page, save its text under fetched/ as evidence, and return the text."""
        import httpx
        from bs4 import BeautifulSoup

        def get() -> httpx.Response:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/140.0"},
            )
            if response.status_code >= 500:
                raise RuntimeError(f"status {response.status_code}")
            return response

        try:
            response = self._retry(get, f"fetch {url}")
        except RuntimeError as error:
            return f"FETCH FAILED: {error}"
        soup = BeautifulSoup(response.text, "html.parser")
        for node in soup(["script", "style", "noscript", "svg"]):
            node.decompose()
        text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        name = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")[:80]
        digest = hashlib.sha1(url.encode()).hexdigest()[:8]
        saved = self.workspace / "fetched" / f"{name}-{digest}.md"
        saved.parent.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        saved.write_text(f"Source: {url}\nFetched: {stamp}\nStatus: {response.status_code}\n\n{text}\n")
        self._record("fetch", url=url, status=response.status_code)
        return f"Saved to fetched/{saved.name} (status {response.status_code}).\n\n{text[:FETCH_LIMIT]}"

    def web_search(self, query: str, include_domains: list[str] | None = None, num_results: int = 8) -> str:
        """The platform's web search. Set include_domains to the seller's domain for its case studies."""
        if self.reads is None:
            return "SEARCH UNAVAILABLE in this run."
        try:
            result = self._retry(
                lambda: self.reads.web_search(
                    query=query, num_results=num_results, include_domains=include_domains
                ),
                f"search {query!r}",
            )
        except RuntimeError as error:
            return f"SEARCH FAILED: {error}"
        self._record("search", query=query)
        return json.dumps(result, ensure_ascii=False)[:FETCH_LIMIT]


def _difference(original: bytes, rebuilt: bytes) -> tuple[float, bytes, tuple[int, int]]:
    """Share of pixels that differ noticeably (after matching widths and padding heights), and a
    side-by-side picture: original left, rebuilt right."""
    from PIL import Image, ImageChops

    a = Image.open(io.BytesIO(original)).convert("RGB")
    b = Image.open(io.BytesIO(rebuilt)).convert("RGB")
    if b.width != a.width:
        b = b.resize((a.width, round(b.height * a.width / b.width)))
    height = max(a.height, b.height)
    pa, pb = Image.new("RGB", (a.width, height), "white"), Image.new("RGB", (a.width, height), "white")
    pa.paste(a, (0, 0))
    pb.paste(b, (0, 0))
    diff = ImageChops.difference(pa, pb).convert("L").point(lambda v: 255 if v > 40 else 0)
    score = sum(diff.histogram()[255:]) / (a.width * height)
    pair = Image.new("RGB", (a.width * 2 + 24, height), (200, 200, 200))
    pair.paste(pa, (0, 0))
    pair.paste(pb, (a.width + 24, 0))
    buffer = io.BytesIO()
    pair.save(buffer, format="PNG")
    return score, buffer.getvalue(), (a.height, b.height)


def _missing_words(original: str, rebuilt: str) -> list[str]:
    """Words (four letters or more) the original shows that the rebuilt section does not."""
    words = lambda text: re.findall(r"[A-Za-z][A-Za-z'’-]{3,}", text.lower())  # noqa: E731
    have = set(words(rebuilt))
    seen: list[str] = []
    for word in words(original):
        if word not in have and word not in seen:
            seen.append(word)
    return seen
