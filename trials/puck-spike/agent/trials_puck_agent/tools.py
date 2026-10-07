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
IMAGE_MAX_PX = 2000
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
    ) -> None:
        self.workspace = Path(workspace)
        self.spike_root = Path(spike_root)
        self.base_url = base_url.rstrip("/")
        self.reads = reads
        self.retry_delay_s = retry_delay_s
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
        """Roll page.json and shell.json back to a version saved by validate_page."""
        path = self._versions() / f"{int(version)}.json"
        if not path.exists():
            saved = sorted(int(p.stem) for p in self._versions().glob("*.json"))
            return f"No version {version}. Saved versions: {saved or 'none yet'}."
        snapshot = json.loads(path.read_text())
        (self.workspace / "page.json").write_text(json.dumps(snapshot["page"], indent=2))
        (self.workspace / "shell.json").write_text(json.dumps(snapshot["shell"], indent=2))
        self._record("restore", version=int(version))
        return f"restored version {version} into page.json and shell.json."

    # --- render --------------------------------------------------------------------------------

    def _publish_for_preview(self) -> str:
        run = self._run()
        site_file = self.spike_root / "data" / "sites" / f"{run['site']}.json"
        site = json.loads(site_file.read_text()) if site_file.exists() else {"brand": run["brand"], "pages": {}}
        site["brand"] = run["brand"]
        site["shell"] = json.loads((self.workspace / "shell.json").read_text())
        site["pages"][run.get("route", "/")] = json.loads((self.workspace / "page.json").read_text())
        site_file.write_text(json.dumps(site, indent=2))
        route = run.get("route", "/")
        return f"{self.base_url}/s/{run['site']}{'' if route == '/' else route}"

    @staticmethod
    def _image_block(png: bytes) -> dict:
        from PIL import Image

        with Image.open(io.BytesIO(png)) as image:
            image = image.convert("RGB")
            scale = min(1.0, IMAGE_MAX_PX / max(image.size))
            if scale < 1.0:
                image = image.resize((int(image.width * scale), int(image.height * scale)))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
        return {
            "type": "image",
            "source_type": "base64",
            "mime_type": "image/png",
            "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }

    def render_page(self) -> list[dict] | str:
        """Screenshot the page at 1440 and 375 wide. Refuses while the page is invalid."""
        check = self.validate_page()
        if not check.startswith("VALID"):
            return "NOT RENDERED: the page is invalid.\n" + check
        url = self._publish_for_preview()
        from playwright.sync_api import sync_playwright

        blocks: list[dict] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (1440, 375):
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                self._retry(lambda: page.goto(url, wait_until="load", timeout=60_000), "render")
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
                blocks.append({
                    "type": "text",
                    "text": (
                        f"{width} wide: page height {height}px, broken images: {facts['broken']}, "
                        f"horizontal overflow: {'yes' if facts['overflow'] else 'no'}, "
                        f"console errors: {len(errors)}{(' (' + '; '.join(errors[:3]) + ')') if errors else ''}"
                    ),
                })
                blocks.append(self._image_block(png))
                page.close()
            browser.close()
        self._record("render", url=url)
        return blocks

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
