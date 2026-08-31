# Gallery Card Thumbnails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every gallery card (grid + list row) shows a real PNG preview of its design document — web documents via a headless-Chromium screenshot of the render HTML, ad/scene documents via the engine's own Skia PNG export — generated lazily, cached by document version, and served through the authenticated BFF.

**Architecture:** One new design-API route, `GET /documents/{document_id}/thumbnail`, dispatches by `doc_kind`: `web` → compose the existing `/web/render` HTML in-process, inline the Tailwind browser runtime, screenshot in Playwright Chromium at a 4:3 viewport; `scene` → the engine's `export_preview` PNG of the first page, Pillow-downscaled. Bytes land in `DesignBlobStore`; a new `design_document_thumbnail` table indexes `(workspace_id, document_id, version) → sha256` so generation happens once per version and never in the write path. The frontend's `toProjectArtifact` mapper composes the versioned BFF URL into the card's existing optional `imagePath` slot — the ruling-2 empty frame remains the fallback.

**Tech Stack:** FastAPI (sync routes → threadpool), Playwright sync API (already a design-API dependency: `playwright>=1.45,<2`), Pillow (already a dependency: `pillow>=10,<12`), Alembic (repo-root `alembic/`, hash revision ids), Next.js App Router BFF proxy, Zod/vitest on the frontend.

**Spec:** §Ratified decisions below — founder rulings from the 2026-08-31 session (no separate spec doc; this section is the contract the plan argues from).

## Ratified decisions (the spec)

1. **PNG for both editors.** No live-iframe web previews (per-card Tailwind JIT cost, useless at the 44px list row); no SVG for ads (font embedding weight, base64 raster images, `dangerouslyAllowSVG`, and PNG is pixel-identical to the CanvasKit/Skia editor view).
2. **Lazy generation on first GET, never in the write path.** The edit loop's ~0.5s round-trip must not pay a screenshot/export tax.
3. **Cache key is the document version.** An edit bumps `current_version` → the mapper's URL changes → regenerate on next view. `?v=` matching the current version gets immutable caching; a stale `?v=` gets `no-store` (served current bytes, never cached under a wrong key).
4. **The empty preview frame (ruling 2) survives as the fallback** — a failed or not-yet-generated thumbnail renders the card frame without artwork, never placeholder art.
5. **Both document kinds ship together** (web + ad; the ad editor is fully integrated now — the earlier "web-only v1" scoping is superseded by this ruling).
6. **Web crop:** above-the-fold viewport capture at 1448×1086 (exactly 4:3 — the card's `aspect-ratio: 4 / 3`, and the web stage's historical letterbox ratio), `device_scale_factor 0.5` → 724×543 output. ~~Scene thumbnails keep their page aspect (`object-fit: contain` letterboxes them in the frame); downscale to max edge 724.~~ **[SUPERSEDED 2026-08-31 (founder ruling, post-walk): the artwork COVERS the card frame — `object-fit: cover; object-position: top` on `.artifactPreview img` — filling it completely and cropping overflow, never letterboxed. Generation is unchanged (scene PNGs still ship at their page aspect, max edge 724); the fill-vs-fit decision lives entirely in the card CSS, matching the list row's pre-existing `cover`/`top` posture.]**

## Global Constraints

- **Local commits only; never push; no PRs** (repo CLAUDE.md). No AI attribution in any commit message.
- **Alembic:** default hash revision ids via `alembic revision -m "<slug>"`; `down_revision` = current head; reversible `downgrade()`; exactly one head; `make db-smoke` on a clean throwaway DB is the gate.
- **Never run the full clue-design suite inline** (>1h). Run focused pytest files; kick one full run in the background at the end.
- **The design subsystem's seam discipline holds:** nothing outside `subsystems/clue-design/` imports design internals. All frontend traffic goes through the BFF (`/api/clue/design/...`); zero direct-to-FastAPI browser calls (W1.1 guard).
- **Frontend gates:** `npm run design-system:build && npm run lint && npm run build` + `npm test` in `apps/frontend/`.
- **Dev stack only via `DEV_STACK.md` / `dev_stack.sh`** — frontend 3020; the release `LUMEN_CORE_HELPER` binary is mandatory.
- FastAPI sync (`def`) routes run in the threadpool, NOT on the event loop — the Playwright sync API in the thumbnail route is therefore *not* the `[slice3×stage0]` blocking-the-loop bug class. State this in the route comment.
- `python -m playwright install chromium` becomes a design-API runtime prerequisite (Task 6 records it).

## File map

| File | Action | Responsibility |
|---|---|---|
| `alembic/versions/<hash>_design_document_thumbnail.py` | Create | The cache-index table |
| `subsystems/design/clue_design/thumbnails.py` | Create | Async DAL: get/record thumbnail rows |
| `tests/design/test_document_thumbnails_dal.py` | Create | DB-gated DAL tests |
| `subsystems/clue-design/apps/api/lumen_api/design_store.py` | Modify | `HybridRepository.get_document_thumbnail` / `.record_document_thumbnail` facade |
| `subsystems/clue-design/apps/api/lumen_api/document_thumbnails.py` | Create | Runtime resolver, HTML inliner, Playwright capture, PNG downscale, export-result extractor |
| `subsystems/clue-design/apps/api/tests/test_document_thumbnails.py` | Create | Unit tests (pure parts) + route tests (fakes) |
| `subsystems/clue-design/apps/api/lumen_api/main.py` | Modify | The `GET /documents/{document_id}/thumbnail` route |
| `apps/frontend/src/app/api/clue/design/route.test.ts` | Modify | Binary + cache-header passthrough proof |
| `apps/frontend/src/features/design-editor/adapter/gallery.ts` | Modify | `imagePath` composition in `toProjectArtifact` |
| `apps/frontend/src/features/design-editor/adapter/gallery.test.ts` | Modify | Mapper tests |
| `apps/frontend/src/features/gallery/components/gallery-artifact-card.tsx` | Modify | `unoptimized` on both `next/image` usages |
| `DEV_STACK.md`, `apps/frontend/docs/api-contracts/projects.md`, `_memory/` | Modify | Ops prerequisite, contract record, session notes |

---

### Task 1: Cache-index table — migration, DAL, repository facade

**Files:**
- Create: `alembic/versions/<hash>_design_document_thumbnail.py` (hash assigned by alembic)
- Create: `subsystems/design/clue_design/thumbnails.py`
- Create: `tests/design/test_document_thumbnails_dal.py` (sibling of `tests/design/test_storage_seam.py` — mirror its DB fixture usage)
- Modify: `subsystems/clue-design/apps/api/lumen_api/design_store.py` (add two methods to `HybridRepository`, class at ~line 520)

**Interfaces:**
- Consumes: `clue_design.storage`'s query style (read `subsystems/design/clue_design/storage.py` first and mirror its `AsyncConnection` + SQL idiom exactly); `DesignStoreBridge`/`self._bridge._run(...)` facade pattern (mirror `DesignBlobStore.register` in `design_store.py:341-410`).
- Produces: `HybridRepository.get_document_thumbnail(document_id: str, version: int) -> Optional[JsonObject]` (`{"sha256": str, "media_type": str}` or `None`) and `HybridRepository.record_document_thumbnail(document_id: str, version: int, *, sha256: str, media_type: str) -> JsonObject` (idempotent upsert, returns the row). Task 3 calls both.

- [ ] **Step 1: Read the DAL idiom.** Read `subsystems/design/clue_design/storage.py` (whole file) — note the connection type, SQL execution style, row→dict mapping, and how `workspace_id` scoping is threaded. The new module must be indistinguishable in style.

- [ ] **Step 2: Write the migration.** Run `alembic revision -m "design document thumbnail cache index"` (from the repo root; alembic.ini's `script_location = alembic`). Fill in:

```python
def upgrade() -> None:
    op.create_table(
        "design_document_thumbnail",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "document_id", "version",
            name="pk_design_document_thumbnail",
        ),
    )

def downgrade() -> None:
    op.drop_table("design_document_thumbnail")
```

No FK to the `artifact` blob row — blobs are content-addressed per workspace and a dangling ref is handled by regeneration at read (Task 3). No FK to `design_document` either: the thumbnail row is a pure cache and must not block document deletion flows.

- [ ] **Step 3: Verify the migration.** Run `alembic heads` (exactly one head) and `make db-smoke` (clean throwaway DB — up→down→up green).

- [ ] **Step 4: Write the failing DAL test** in `tests/design/test_document_thumbnails_dal.py`, using the same DB fixture as `tests/design/test_storage_seam.py`:

```python
async def test_record_then_get_roundtrip(conn, workspace_id):
    from clue_design import thumbnails

    missing = await thumbnails.get_document_thumbnail(
        conn, workspace_id=workspace_id, document_id="doc_1", version=3
    )
    assert missing is None

    row = await thumbnails.record_document_thumbnail(
        conn, workspace_id=workspace_id, document_id="doc_1", version=3,
        sha256="a" * 64, media_type="image/png",
    )
    assert row["sha256"] == "a" * 64

    found = await thumbnails.get_document_thumbnail(
        conn, workspace_id=workspace_id, document_id="doc_1", version=3
    )
    assert found == {"sha256": "a" * 64, "media_type": "image/png"}


async def test_record_is_an_idempotent_upsert(conn, workspace_id):
    from clue_design import thumbnails

    await thumbnails.record_document_thumbnail(
        conn, workspace_id=workspace_id, document_id="doc_1", version=3,
        sha256="a" * 64, media_type="image/png",
    )
    await thumbnails.record_document_thumbnail(
        conn, workspace_id=workspace_id, document_id="doc_1", version=3,
        sha256="b" * 64, media_type="image/png",
    )
    found = await thumbnails.get_document_thumbnail(
        conn, workspace_id=workspace_id, document_id="doc_1", version=3
    )
    assert found["sha256"] == "b" * 64


async def test_workspace_scoped(conn, workspace_id, other_workspace_id):
    from clue_design import thumbnails

    await thumbnails.record_document_thumbnail(
        conn, workspace_id=workspace_id, document_id="doc_1", version=1,
        sha256="a" * 64, media_type="image/png",
    )
    assert await thumbnails.get_document_thumbnail(
        conn, workspace_id=other_workspace_id, document_id="doc_1", version=1
    ) is None
```

Adapt fixture names to what `test_storage_seam.py` actually provides (if there is no `other_workspace_id` fixture, create the second workspace the way that file's cross-tenant tests do).

- [ ] **Step 5: Run it to make sure it fails.** `uv run pytest tests/design/test_document_thumbnails_dal.py -v` → FAIL (`clue_design.thumbnails` does not exist).

- [ ] **Step 6: Implement `subsystems/design/clue_design/thumbnails.py`** — two async functions in the storage.py idiom:

```python
"""Document-thumbnail cache index (design gallery cards).

One row per (workspace, document, version): which blob-store digest holds the
rendered PNG. A pure cache — no FK anywhere; a dangling digest is repaired by
regeneration at read time, and rows for superseded versions are kept (blobs
are content-addressed, so duplicates cost nothing; pruning is future work).
"""

async def get_document_thumbnail(
    conn, *, workspace_id: str, document_id: str, version: int
) -> dict | None:
    # SELECT sha256, media_type FROM design_document_thumbnail
    #  WHERE workspace_id = ... AND document_id = ... AND version = ...
    ...

async def record_document_thumbnail(
    conn, *, workspace_id: str, document_id: str, version: int,
    sha256: str, media_type: str,
) -> dict:
    # INSERT ... ON CONFLICT (workspace_id, document_id, version)
    #   DO UPDATE SET sha256 = EXCLUDED.sha256, media_type = EXCLUDED.media_type
    # RETURNING sha256, media_type
    ...
```

(The bodies use whatever execution idiom Step 1 found — the comments above are the SQL contract, not literal strings to paste.)

- [ ] **Step 7: Run the DAL tests to green.** `uv run pytest tests/design/test_document_thumbnails_dal.py -v` → PASS.

- [ ] **Step 8: Add the facade methods** to `HybridRepository` in `design_store.py`, mirroring the `DesignBlobStore.register` bridge pattern exactly (one bridged coroutine per method):

```python
    def get_document_thumbnail(self, document_id: str, version: int) -> Optional[JsonObject]:
        """The cached thumbnail digest for this document version, or None."""
        return self._bridge._run(
            lambda conn: design_thumbnails.get_document_thumbnail(
                conn, workspace_id=self.workspace_id,
                document_id=document_id, version=version,
            )
        )

    def record_document_thumbnail(
        self, document_id: str, version: int, *, sha256: str, media_type: str
    ) -> JsonObject:
        """Claim the (document, version) thumbnail slot — idempotent upsert."""
        return self._bridge._run(
            lambda conn: design_thumbnails.record_document_thumbnail(
                conn, workspace_id=self.workspace_id,
                document_id=document_id, version=version,
                sha256=sha256, media_type=media_type,
            )
        )
```

Match the import style at the top of the file (`from clue_design import thumbnails as design_thumbnails`, next to the existing `storage as design_storage` import). Confirm `HybridRepository` really exposes `self._bridge` / `self.workspace_id` the way `DesignBlobStore` does — if its attribute names differ, mirror *its* other methods instead.

- [ ] **Step 9: Commit.**

```bash
git add alembic/versions subsystems/design/clue_design/thumbnails.py tests/design/test_document_thumbnails_dal.py subsystems/clue-design/apps/api/lumen_api/design_store.py
git commit -m "feat(design): document-thumbnail cache index — table, DAL, repository facade"
```

---

### Task 2: The generator module — `lumen_api/document_thumbnails.py`

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/document_thumbnails.py`
- Create: `subsystems/clue-design/apps/api/tests/test_document_thumbnails.py` (unit half; the route half is Task 3)

**Interfaces:**
- Consumes: nothing from Task 1 (deliberately main.py-import-free — main.py imports *it*, never the reverse, so no cycle).
- Produces (Task 3 calls all of these):
  - `resolve_tailwind_runtime() -> Optional[bytes]`
  - `inline_tailwind(html: str, runtime: bytes) -> str`
  - `web_thumbnail_png(html: str, *, width: int = 1448, height: int = 1086, scale: float = 0.5) -> bytes`
  - `png_from_export_result(result: dict) -> bytes` (raises `ThumbnailUnavailable`)
  - `downscale_png(data: bytes, *, max_edge: int = 724) -> bytes`
  - `first_page_ids(scene: dict) -> Optional[list[str]]`
  - `class ThumbnailUnavailable(Exception)` with a `.code: str` attribute

- [ ] **Step 1: Read the two upstream patterns.** (a) `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py` — the Tailwind-runtime search path (lines ~236-272), the runtime-inline splice, and the Playwright `set_content` + settle-wait sequence its `_render_page_html`/capture path uses (~lines 7930-8560). The generator mirrors these; where this plan's code below disagrees with what web_substrate actually does for the inline splice or settle wait, **web_substrate wins** — it is the browser-verified production pattern. (b) `compact_export_artifact` in `lumen_api/main.py` (~line 8005) — how engine export bytes come back (`artifact["bytes"]` as a list of ints).

- [ ] **Step 2: Write the failing unit tests** in `tests/test_document_thumbnails.py`:

```python
import io
from PIL import Image

from lumen_api import document_thumbnails as thumbs


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_inline_tailwind_lands_before_head_close():
    html = "<html><head><title>t</title></head><body><p>hi</p></body></html>"
    out = thumbs.inline_tailwind(html, b"RUNTIME_JS")
    assert "<script>RUNTIME_JS</script></head>" in out


def test_inline_tailwind_without_head_falls_back_to_body():
    html = "<html><body><p>hi</p></body></html>"
    out = thumbs.inline_tailwind(html, b"RUNTIME_JS")
    assert "RUNTIME_JS" in out  # still injected, never dropped


def test_downscale_caps_the_long_edge_and_keeps_aspect():
    data = thumbs.downscale_png(_png(2000, 1000), max_edge=724)
    image = Image.open(io.BytesIO(data))
    assert image.size == (724, 362)


def test_downscale_never_upscales():
    data = thumbs.downscale_png(_png(400, 300), max_edge=724)
    image = Image.open(io.BytesIO(data))
    assert image.size == (400, 300)


def test_png_from_export_result_decodes_engine_bytes():
    png = _png(10, 10)
    result = {
        "ok": True,
        "export": {"artifacts": [{"bytes": list(png), "mime_type": "image/png"}]},
    }
    assert thumbs.png_from_export_result(result) == png


def test_png_from_export_result_refuses_a_failed_export():
    import pytest
    with pytest.raises(thumbs.ThumbnailUnavailable):
        thumbs.png_from_export_result({"ok": False, "export": {}})


def test_first_page_ids_takes_the_first_page_only():
    scene = {"pages": [{"id": "p1"}, {"id": "p2"}]}
    assert thumbs.first_page_ids(scene) == ["p1"]


def test_first_page_ids_none_when_shape_unknown():
    assert thumbs.first_page_ids({}) is None
```

Before writing `first_page_ids`, confirm the scene page shape: open a stored scene document's JSON (any `design_document` row in the dev DB, or a scene fixture under `subsystems/clue-design/apps/api/tests/`) and check the pages key/id field names. If pages live under a different key, fix the test AND the implementation to the real shape — `None` (= export all pages, engine picks) is the fallback, never a guessed key.

- [ ] **Step 3: Run them to make sure they fail.** `cd subsystems/clue-design/apps/api && uv run pytest tests/test_document_thumbnails.py -v` → FAIL (module missing). (Use this subsystem's own toolchain invocation — check how its existing tests are run, e.g. a `Makefile`/`pyproject` script — it is excluded from the root uv workspace.)

- [ ] **Step 4: Implement the module.**

```python
"""Document-thumbnail generation for the platform gallery (2026-08-31 ruling).

PNG for both document kinds:
- web: Playwright-Chromium screenshot of the composed render HTML (only a
  browser rasterizes Tailwind HTML faithfully). The Tailwind browser runtime
  is INLINED into the HTML the same way the agent runtime's preview capture
  does (web_substrate.py): set_content has no origin, so a src= reference to
  a dev-server URL is not an option.
- scene: the engine's Skia PNG (extracted from an export_preview result by
  the route), downscaled here.

main.py imports this module; this module never imports main.py.
"""

import io
import os
from pathlib import Path
from typing import Optional

from PIL import Image

_REPO_ROOT = Path(__file__).resolve().parents[4]

_TAILWIND_RUNTIME_ENV = "LUMEN_TAILWIND_RUNTIME"
_TAILWIND_RUNTIME_CANDIDATES = (
    ("subsystems", "clue-design", "apps", "editor", "public", "vendor", "tailwind-browser.js"),
    ("subsystems", "clue-design", "apps", "editor", "node_modules", "@tailwindcss", "browser", "dist", "index.global.js"),
    ("apps", "frontend", "public", "vendor", "tailwind-browser.js"),
    ("apps", "frontend", "node_modules", "@tailwindcss", "browser", "dist", "index.global.js"),
)


class ThumbnailUnavailable(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_tailwind_runtime() -> Optional[bytes]:
    # Mirrors web_substrate.tailwind_runtime_path: a set-but-missing env
    # override resolves to None (tell the operator, don't substitute).
    override = os.environ.get(_TAILWIND_RUNTIME_ENV)
    if override:
        candidate = Path(override).expanduser()
        return candidate.read_bytes() if candidate.is_file() else None
    for parts in _TAILWIND_RUNTIME_CANDIDATES:
        candidate = _REPO_ROOT.joinpath(*parts)
        if candidate.is_file():
            return candidate.read_bytes()
    return None


def inline_tailwind(html: str, runtime: bytes) -> str:
    script = f"<script>{runtime.decode('utf-8')}</script>"
    lowered = html.lower()
    head_close = lowered.find("</head>")
    if head_close != -1:
        return html[:head_close] + script + html[head_close:]
    body_close = lowered.rfind("</body>")
    if body_close != -1:
        return html[:body_close] + script + html[body_close:]
    return html + script


def web_thumbnail_png(
    html: str, *, width: int = 1448, height: int = 1086, scale: float = 0.5
) -> bytes:
    # 1448x1086 is exactly 4:3 — the gallery card's own aspect-ratio — so the
    # above-the-fold crop fills the frame. scale=0.5 -> 724x543 output pixels.
    runtime = resolve_tailwind_runtime()
    if runtime is None:
        # Render-bare-and-warn is the agent runtime's posture; for a
        # THUMBNAIL a layoutless page is worse than useless — refuse loudly.
        raise ThumbnailUnavailable(
            "thumbnail.tailwind_runtime_missing",
            "no Tailwind browser runtime found (set LUMEN_TAILWIND_RUNTIME "
            "or npm install in an editor/frontend app)",
        )
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=scale,
                )
                page = context.new_page()
                page.set_content(inline_tailwind(html, runtime), wait_until="networkidle")
                page.wait_for_timeout(250)  # Tailwind JIT settle (web_substrate's move)
                return page.screenshot(type="png")
            finally:
                browser.close()
    except PlaywrightError as error:
        raise ThumbnailUnavailable("thumbnail.capture_failed", str(error)) from error


def png_from_export_result(result: dict) -> bytes:
    export = result.get("export") or {}
    artifacts = [a for a in export.get("artifacts", []) if isinstance(a, dict)]
    if not result.get("ok", False) or not artifacts:
        raise ThumbnailUnavailable(
            "thumbnail.export_failed", "engine PNG export produced no artifact"
        )
    raw = artifacts[0].get("bytes", [])
    if not isinstance(raw, list) or not raw:
        raise ThumbnailUnavailable(
            "thumbnail.export_failed", "engine PNG artifact carried no bytes"
        )
    return bytes(int(value) & 0xFF for value in raw)


def downscale_png(data: bytes, *, max_edge: int = 724) -> bytes:
    image = Image.open(io.BytesIO(data))
    if max(image.size) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def first_page_ids(scene: dict) -> Optional[list[str]]:
    pages = scene.get("pages")
    if isinstance(pages, list) and pages and isinstance(pages[0], dict):
        page_id = pages[0].get("id")
        if isinstance(page_id, str):
            return [page_id]
    return None
```

Adjust `first_page_ids` (and the two settle constants) to whatever Step 1's reading found — the plan's values are defaults, the source's observed behavior is authoritative.

- [ ] **Step 5: Run the unit tests to green.** Same pytest command → all PASS.

- [ ] **Step 6: One real-browser smoke test, skipped when Chromium is absent** (append to the same test file):

```python
import pytest


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _chromium_available(), reason="playwright chromium not installed")
def test_web_thumbnail_png_captures_styled_html(monkeypatch):
    # A page that is red only if arbitrary-value Tailwind classes compiled.
    monkeypatch.setenv("LUMEN_TAILWIND_RUNTIME", "")  # force the search path OR
    # point at a real runtime copy if the search path is empty in CI:
    monkeypatch.delenv("LUMEN_TAILWIND_RUNTIME", raising=False)
    html = (
        "<html><head></head><body>"
        '<div class="min-h-screen bg-[rgb(255,0,0)]"></div>'
        "</body></html>"
    )
    data = thumbs.web_thumbnail_png(html)
    image = Image.open(io.BytesIO(data))
    assert image.size == (724, 543)
    assert image.convert("RGB").getpixel((362, 271)) == (255, 0, 0)
```

If no runtime file exists on the machine, this test will raise `ThumbnailUnavailable` — extend the skipif to also require `thumbs.resolve_tailwind_runtime() is not None`.

- [ ] **Step 7: Run it** (locally, where Chromium is installed): `uv run pytest tests/test_document_thumbnails.py -v` → PASS (or SKIP with the stated reason — then run `python -m playwright install chromium` once and re-run to see it green at least once before commit).

- [ ] **Step 8: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/document_thumbnails.py subsystems/clue-design/apps/api/tests/test_document_thumbnails.py
git commit -m "feat(design): thumbnail generator module — tailwind inline, chromium capture, png downscale"
```

---

### Task 3: The route — `GET /documents/{document_id}/thumbnail`

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (add the route inside `create_app`, next to `render_web_document` at ~line 3504)
- Modify: `subsystems/clue-design/apps/api/tests/test_document_thumbnails.py` (route tests)

**Interfaces:**
- Consumes: Task 1's `repo.get_document_thumbnail`/`repo.record_document_thumbnail`; Task 2's module (imported as `from lumen_api import document_thumbnails`); existing closure helpers `require_document`, `blob_store(repo)`, `request_cache_dir(repo)`, `render_web_document` (the sibling route function — callable in-process from the same closure), `scene_brand_fonts`, `materialize_scene_assets`, `default_export_profile`, `app.state.core.export_preview`, `log_event`.
- Produces: the HTTP contract Task 5's frontend URL targets — `GET /documents/{id}/thumbnail?v=<version>` → `200 image/png` with `Cache-Control: private, max-age=31536000, immutable` when `v` equals the current version, `Cache-Control: no-store` otherwise; `404` unknown document; `502 {"code": "thumbnail.*"}` on generation failure.

- [ ] **Step 1: Confirm three closure facts before writing** (read, don't assume): (a) the exact key `render_web_document`'s return dict uses for the HTML (follow its final `return` — expected `"html"`); (b) the document row's version field (`design_store.py:1953` reads `row["current_version"]` — confirm `repo.require_document(...)` surfaces it under that name); (c) `DesignBlobStore.register`'s return value vs the sha256 that `read_blob` takes (if register returns the full `{ws}/design/{sha}` storage key, compute the digest locally with `hashlib.sha256(data).hexdigest()` — registration is content-addressed and idempotent, so the local digest is authoritative).

- [ ] **Step 2: Write the failing route tests.** Mirror the existing route-test setup in `tests/test_api.py` (TestClient + seeded repo + fake core — reuse its fixtures/fakes; several test files fake `core.web_render`/`core.export_preview` already). Monkeypatch the *generator seams*, not HTTP:

```python
def test_web_thumbnail_generates_once_then_serves_from_cache(client, seeded_web_document, monkeypatch):
    calls = []

    def fake_capture(html, **kwargs):
        calls.append(html)
        return _png(724, 543)

    monkeypatch.setattr(
        "lumen_api.document_thumbnails.web_thumbnail_png", fake_capture
    )
    first = client.get(f"/documents/{seeded_web_document}/thumbnail")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    second = client.get(f"/documents/{seeded_web_document}/thumbnail")
    assert second.status_code == 200
    assert len(calls) == 1  # second hit came from the blob cache
    assert second.content == first.content


def test_matching_version_gets_immutable_caching(client, seeded_web_document, monkeypatch):
    monkeypatch.setattr(
        "lumen_api.document_thumbnails.web_thumbnail_png", lambda html, **kw: _png(7, 5)
    )
    version = client.get(f"/documents/{seeded_web_document}").json()["current_version"]
    fresh = client.get(f"/documents/{seeded_web_document}/thumbnail?v={version}")
    assert fresh.headers["cache-control"] == "private, max-age=31536000, immutable"
    stale = client.get(f"/documents/{seeded_web_document}/thumbnail?v=999999")
    assert stale.status_code == 200          # still serves the CURRENT bytes
    assert stale.headers["cache-control"] == "no-store"  # but never caches them under a stale key


def test_scene_thumbnail_goes_through_the_engine_export(client, seeded_scene_document):
    # The suite's fake core provides export_preview; assert the route serves
    # its PNG downscaled and does NOT call the web capture path.
    response = client.get(f"/documents/{seeded_scene_document}/thumbnail")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_generation_failure_is_a_typed_502(client, seeded_web_document, monkeypatch):
    from lumen_api.document_thumbnails import ThumbnailUnavailable

    def refuse(html, **kwargs):
        raise ThumbnailUnavailable("thumbnail.capture_failed", "boom")

    monkeypatch.setattr("lumen_api.document_thumbnails.web_thumbnail_png", refuse)
    response = client.get(f"/documents/{seeded_web_document}/thumbnail")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "thumbnail.capture_failed"


def test_unknown_document_is_404(client):
    assert client.get("/documents/doc_nope/thumbnail").status_code == 404
```

Adapt fixture names (`client`, `seeded_web_document`, `seeded_scene_document`) to what the suite actually provides — `test_api.py` is the reference. The single-document GET's version-field name in the second test comes from Step 1(b). If the fake core has no `export_preview`, add one to the fake returning `{"ok": True, "export": {"artifacts": [{"bytes": list(_png(100, 80)), "mime_type": "image/png", "format": "png"}]}}`.

- [ ] **Step 3: Run them to make sure they fail.** `uv run pytest tests/test_document_thumbnails.py -v` → route tests FAIL with 404 (route not defined).

- [ ] **Step 4: Implement the route** in `create_app`, directly after `render_web_document`:

```python
    @app.get("/documents/{document_id}/thumbnail")
    def get_document_thumbnail(
        document_id: str,
        request: Request,
        v: Optional[str] = None,
        repo: HybridRepository = Depends(repository),
    ) -> Response:
        # Gallery-card preview (2026-08-31 ruling): PNG for both kinds, built
        # LAZILY here on first read — never in the write path — and cached by
        # (document, version) in the blob store. Sync route => threadpool, so
        # the Playwright capture blocks a worker thread, not the event loop
        # (NOT the [slice3xstage0] class of bug).
        document = require_document(repo, document_id)
        version = int(document["current_version"])
        blobs = blob_store(repo)

        cached = repo.get_document_thumbnail(document_id, version)
        data: Optional[bytes] = None
        if cached is not None:
            try:
                _media, data = blobs.read_blob(cached["sha256"])
            except NotFoundError:
                data = None  # dangling index row — regenerate below

        if data is None:
            kind = document.get("doc_kind", "scene")
            try:
                if kind == "web":
                    rendered = render_web_document(
                        document_id, request, mode="editor",
                        runtime_src=None, bridge=0, nonce=None, repo=repo,
                    )
                    data = document_thumbnails.web_thumbnail_png(str(rendered["html"]))
                else:
                    scene = document["scene"]
                    cache_dir = request_cache_dir(repo)
                    materialize_scene_assets(blobs, cache_dir, [scene])
                    result = app.state.core.export_preview(
                        scene,
                        "png",
                        document_thumbnails.first_page_ids(scene),
                        default_export_profile("png"),
                        raise_on_error=False,
                        asset_store_root=cache_dir,
                        brand_fonts=scene_brand_fonts(repo, scene, blobs, cache_dir),
                    )
                    data = document_thumbnails.downscale_png(
                        document_thumbnails.png_from_export_result(result)
                    )
            except document_thumbnails.ThumbnailUnavailable as error:
                raise HTTPException(
                    status_code=502,
                    detail={"code": error.code, "message": str(error)},
                ) from error
            sha256 = hashlib.sha256(data).hexdigest()
            blobs.register(data, media_type="image/png", source_key="document_thumbnail")
            repo.record_document_thumbnail(
                document_id, version, sha256=sha256, media_type="image/png"
            )
            log_event(
                api_logger, logging.INFO, "document_thumbnail_generated",
                document_id=document_id, version=version, kind=kind,
                byte_count=len(data),
            )

        fresh = v == str(version)
        return Response(
            content=data,
            media_type="image/png",
            headers={
                "Cache-Control": (
                    "private, max-age=31536000, immutable" if fresh else "no-store"
                )
            },
        )
```

Reconcile against Step 1's findings: the render's HTML key, the version field name, `render_web_document`'s exact parameter list (match its current signature verbatim — it is a sibling closure function, called in-process so the composed HTML carries this request's own origin for asset URLs, which the Chromium page can fetch), the `CoreError` handling idiom if `export_preview` raises, and whether `import hashlib` already exists at the top of main.py (add if not). If the scene fake-core signature in tests disagrees with the real `export_preview` signature, follow the real one (visible at the `/export-preview` route).

- [ ] **Step 5: Run the route tests to green.** `uv run pytest tests/test_document_thumbnails.py -v` → PASS.

- [ ] **Step 6: Focused regression check.** Run the API test files that exercise neighboring surfaces: `uv run pytest tests/test_api.py -x -q` (this is a focused file, not the full design suite).

- [ ] **Step 7: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_document_thumbnails.py
git commit -m "feat(design): GET /documents/{id}/thumbnail — lazy version-cached PNG for web and scene documents"
```

---

### Task 4: BFF binary passthrough proof

**Files:**
- Modify: `apps/frontend/src/app/api/clue/design/route.test.ts`

**Interfaces:**
- Consumes: `handleDesignProxyRequest` from `src/app/api/clue/design/[...path]/design-proxy-handler.ts` (already forwards `content-type` and `cache-control` — `FORWARDED_RESPONSE_HEADERS` in `src/auth/bff.ts:9`; this task *proves* binary bodies and the query string survive, it should not need handler changes).
- Produces: confidence that Task 5's `imagePath` URL works end-to-end through the proxy.

- [ ] **Step 1: Write the failing (or immediately-green) test**, mirroring the dependency-stub shape the existing tests in that file use:

```ts
it("passes thumbnail PNG bytes, content-type, cache-control, and the version query through", async () => {
  const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);
  let upstreamUrl = "";
  const fetchImpl: typeof fetch = async (input) => {
    upstreamUrl = String(input);
    return new Response(png, {
      status: 200,
      headers: {
        "content-type": "image/png",
        "cache-control": "private, max-age=31536000, immutable",
      },
    });
  };
  const response = await handleDesignProxyRequest(
    new Request("https://app.local/api/clue/design/documents/doc_1/thumbnail?v=7"),
    ["documents", "doc_1", "thumbnail"],
    { ...workingDependencies, fetchImpl },
  );
  expect(response.status).toBe(200);
  expect(upstreamUrl).toContain("/documents/doc_1/thumbnail?v=7");
  expect(response.headers.get("content-type")).toBe("image/png");
  expect(response.headers.get("cache-control")).toBe("private, max-age=31536000, immutable");
  expect(new Uint8Array(await response.arrayBuffer())).toEqual(png);
});
```

`workingDependencies` = whatever authenticated-happy-path dependency object the file's existing tests construct (reuse it verbatim). If the query-string assertion fails because the handler drops `?v=`, fix `handleDesignProxyRequest` to append `new URL(request.url).search` to the upstream URL — and note it in the commit message as the one behavior change.

- [ ] **Step 2: Run it.** `cd apps/frontend && npx vitest run src/app/api/clue/design/route.test.ts` (or the repo's test runner invocation — match how `npm test` scopes files) → PASS.

- [ ] **Step 3: Commit.**

```bash
git add apps/frontend/src/app/api/clue/design/route.test.ts
git commit -m "test(frontend): BFF design proxy passes binary thumbnail bytes and caching headers through"
```

---

### Task 5: Frontend — versioned thumbnail URL on the card

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/gallery.ts` (`toProjectArtifact`)
- Modify: `apps/frontend/src/features/design-editor/adapter/gallery.test.ts`
- Modify: `apps/frontend/src/features/gallery/components/gallery-artifact-card.tsx`

**Interfaces:**
- Consumes: `DesignArtifactListItem` (already carries `documentId` and `currentVersionId` — no wire/schema change anywhere); Task 3's URL contract.
- Produces: `ProjectArtifact.imagePath` = `/api/clue/design/documents/{documentId}/thumbnail?v={currentVersionId}` for every listed design artifact, both kinds.

- [ ] **Step 1: Write the failing mapper tests** (append to `gallery.test.ts`, following its existing fixture style):

```ts
it("composes the versioned BFF thumbnail URL for a web document", () => {
  const artifact = toProjectArtifact(webListItem({ documentId: "doc_w1", currentVersionId: "7" }));
  expect(artifact.imagePath).toBe("/api/clue/design/documents/doc_w1/thumbnail?v=7");
});

it("composes the versioned BFF thumbnail URL for an ad document", () => {
  const artifact = toProjectArtifact(adListItem({ documentId: "doc_a1", currentVersionId: "3" }));
  expect(artifact.imagePath).toBe("/api/clue/design/documents/doc_a1/thumbnail?v=3");
});
```

(`webListItem`/`adListItem` = whatever list-item builders the test file already uses — reuse them; if it builds items inline, do the same.)

- [ ] **Step 2: Run to verify they fail.** Focused vitest on `gallery.test.ts` → FAIL (`imagePath` is `undefined`).

- [ ] **Step 3: Implement in `toProjectArtifact`.** Add to the `ProjectArtifactSchema.parse({...})` object:

```ts
    imagePath: designThumbnailPath(item),
```

with, above the function:

```ts
/**
 * The card's preview artwork (2026-08-31 ruling): the design API's lazy,
 * version-cached PNG, addressed through the BFF. The version in the URL is
 * the cache key — an edit bumps `currentVersionId`, the URL changes, and the
 * card picks up the fresh thumbnail on its next mount. The empty-frame
 * fallback (ruling 2) remains for a thumbnail that fails to load.
 */
function designThumbnailPath(item: DesignArtifactListItem): string {
  return `/api/clue/design/documents/${encodeURIComponent(item.documentId)}/thumbnail?v=${encodeURIComponent(item.currentVersionId)}`;
}
```

Also update the mapper's header comment: ruling 2's "real documents have no thumbnails" sentence is superseded — real documents now have real thumbnails; the empty frame is the *fallback*, not the norm. Keep the rest of the honesty rules (account, collateralType, size) untouched.

- [ ] **Step 4: Run the mapper tests to green**, plus the schema guard: `imagePath` is validated by `z.string().startsWith("/")` (`project-workspace.ts:93`) — the BFF path satisfies it; the existing `toProjectArtifact` tests must stay green (they assert absence of *other* fields, not `imagePath` — if any test asserts `imagePath` is absent, update it to the new contract).

- [ ] **Step 5: Mark the card images `unoptimized`.** In `gallery-artifact-card.tsx`, add the `unoptimized` prop to both `next/image` usages (grid card ~line 46, list row ~line 87):

```tsx
          <Image
            alt=""
            fill
            loading={preload ? "eager" : "lazy"}
            sizes="(max-width: 780px) 50vw, 200px"
            src={artifact.imagePath}
            unoptimized
          />
```

With one comment at the first site only:

```tsx
        {/* unoptimized: the thumbnail route is session-authenticated behind
            the BFF — the Next image optimizer's server-side refetch carries
            no session cookie and would 401. The API already serves a
            card-sized PNG, so there is nothing left to optimize. */}
```

Also update the ruling-2 comment above the conditional (line 43-44): the empty frame is now the fallback for a missing/failed thumbnail, not the universal state.

- [ ] **Step 6: Full frontend gates.** `cd apps/frontend && npm run design-system:build && npm run lint && npm run build && npm test` → all green.

- [ ] **Step 7: Commit.**

```bash
git add apps/frontend/src/features/design-editor/adapter/gallery.ts apps/frontend/src/features/design-editor/adapter/gallery.test.ts apps/frontend/src/features/gallery/components/gallery-artifact-card.tsx
git commit -m "feat(frontend): gallery cards show real design thumbnails — versioned BFF URL from the list read"
```

---

### Task 6: Ops recording, live browser verification, contract + memory

**Files:**
- Modify: `DEV_STACK.md` (design-API prerequisites)
- Modify: `apps/frontend/docs/api-contracts/projects.md` (the design-artifact section that already records the list read)
- Create: `_memory/2026-08-31-gallery-card-thumbnails.md`

**Interfaces:**
- Consumes: everything above, plus the DEV_STACK.md launch recipe (frontend 3020; `LUMEN_CORE_HELPER` mandatory).
- Produces: the verified feature plus its durable records.

- [ ] **Step 1: Record the Playwright prerequisite in DEV_STACK.md**, in the design-API section, same tone as the `LUMEN_CORE_HELPER` entry:

```markdown
- **Chromium for thumbnails (once per machine):** `python -m playwright install chromium`
  (from the design API's venv). Without it, `GET /documents/{id}/thumbnail` for web
  documents returns a typed 502 (`thumbnail.capture_failed`) and gallery cards fall
  back to the empty preview frame. Scene/ad thumbnails do not need it (engine PNG).
  Optional: `LUMEN_TAILWIND_RUNTIME=/abs/path/to/tailwind-browser.js` overrides the
  runtime search path (same env the agent runtime's preview capture uses).
```

- [ ] **Step 2: Start the dev stack per DEV_STACK.md** (never from memory — follow the runbook, including the clean-`.next` rule and the helper binary), run `python -m playwright install chromium` if this machine hasn't.

- [ ] **Step 3: Browser-verify the full walk** (screenshots at each point):
  1. Open a project's gallery (chats-route rail or artifact-route Gallery tab, signed in per the runbook's dev login).
  2. Web-document card shows the page's above-the-fold artwork; ad card shows the ad artwork letterboxed in the 4:3 frame; the list-view rows show the same at 44px.
  3. Devtools network: first load of a thumbnail is a `200 image/png` with `cache-control: private, max-age=31536000, immutable`; a reload serves it from the browser cache (no re-request) — and the design-API log shows exactly one `document_thumbnail_generated` per document.
  4. Edit the web document (any inspector write), return to the gallery, reload: the card's URL carries the new `?v=` and the artwork reflects the edit.
  5. Negative: stop nothing, pick a document id with no thumbnail yet and a deliberately broken generator condition is NOT needed — instead verify the fallback by temporarily renaming the tailwind runtime file, requesting a *new* web document's thumbnail (typed 502 in the API log), and confirming the card renders the empty frame without crashing the gallery. Restore the file.
  6. Confirm the editor's edit round-trip latency is unchanged (thumbnails generate on gallery reads, not on writes).

- [ ] **Step 4: Record the contract** in `apps/frontend/docs/api-contracts/projects.md`, appended to the design-artifacts section:

```markdown
### Design-document thumbnails (2026-08-31)

`GET /api/clue/design/documents/{documentId}/thumbnail?v={currentVersionId}` →
`200 image/png`. Lazily generated server-side on first read (web: Chromium
screenshot of the render HTML at 1448×1086 → 724×543; ad/scene: engine Skia
PNG of page 1, max edge 724) and cached by `(document, version)` in the design
blob store. `v` equal to the document's current version ⇒
`Cache-Control: private, max-age=31536000, immutable`; any other `v` serves the
current bytes with `no-store`. Generation failure is a typed 502
(`thumbnail.*`); the gallery card's empty preview frame is the fallback.
The frontend composes this URL in `toProjectArtifact` from the list read's
`documentId` + `currentVersionId` — no wire-shape change.
```

- [ ] **Step 5: Kick the full design-API suite in the background** (never inline): the subsystem's full-suite command from its own docs, `run_in_background`, and note the run in the memory file for the next session to check.

- [ ] **Step 6: Write the `_memory` close-out** (`_memory/2026-08-31-gallery-card-thumbnails.md`): what shipped (route, table, generator, mapper, card), the rulings (PNG-both, lazy, version-keyed, empty-frame fallback), the Playwright/`LUMEN_TAILWIND_RUNTIME` ops facts, verification evidence (which document ids, observed byte sizes/latencies), and open follow-ups (below).

- [ ] **Step 7: Final commit.**

```bash
git add DEV_STACK.md apps/frontend/docs/api-contracts/projects.md _memory/2026-08-31-gallery-card-thumbnails.md
git commit -m "docs(design): thumbnail route contract, chromium prerequisite, session close-out"
```

---

## Recorded follow-ups (not in scope — do not build)

1. **Thumbnail pruning:** superseded-version rows/blobs are kept; prune with the design-subject `run_event` pruner discipline if volume ever matters.
2. **Warm-path generation:** a post-write background warm (generate the next thumbnail right after an edit commits) would hide the one-time cold-read latency; only worth it if founders notice the first gallery paint.
3. **Chat-message artifact previews / share-OG images:** both can consume the same route unchanged — record, don't build.
4. **Persistent browser process:** web_substrate keeps a long-lived Chromium because it captures on every agent turn; the thumbnail route launches per generation (rare — once per version). If thumbnail volume grows, lift web_substrate's pooled-browser pattern.

## Execution ledger — deferred findings and rulings (Tasks 1–3, executed 2026-08-31)

**PLAN COMPLETE (2026-08-31).** All six tasks plus two deferral-closure batches and the final whole-branch review are done on `integration/frontend-design-part-iv-v2`: `f3b6d457` (T1) → `596aa690` (T2) → `ed330788`+`704b2c7a` (T3+fix) → `8fcc8c7b` (T4) → `1753a430` (T5) → `42726b72` (batch A, ledger rows 1,2,4–11 closed) → `cb74f33a` (batch B, rows 14,15a,16 closed) → `1c9f01a1`+`fff8a702` (T6+fix: 6/6 browser walk, evidence independently audited) → `4c08aca7` (final-review wave: Chromium capture semaphore(3), `"use client"` on the card, self-origin-fetch deployment prerequisite in DEV_STACK, record corrections). Final whole-branch review verdict: **ready to merge with fixes — and the fixes landed**; scoped re-review clean. Standing residuals, all recorded: rows 3 (template ticket), 12, 13, 15b, 17 waived; the pre-existing head-pin test and the dev password in DEV_STACK.md are founder-decision items; the background full suite's 19 failures are out-of-branch (17 = missing `typescript` in the compile worker's node toolchain; 2 pre-existing singletons wanting their own triage — details in `_memory/2026-08-31-gallery-card-thumbnails.md`).

### Deferred minors (fix at final review or explicitly waive)

| # | From | Finding | Site |
|---|---|---|---|
| 1 | T1 review | Upsert test never exercises `media_type = excluded.media_type` — second record should use `image/webp` and assert it | `tests/design/test_document_thumbnails_dal.py:349-365` |
| 2 | T1 review | Migration uses `op.create_table` — the only 1 of 191 migrations not using raw `op.execute("CREATE TABLE …")`; plan-mandated. Mechanical rewrite would also allow the house `COMMENT ON TABLE` | `alembic/versions/be0659753362_*.py` |
| 3 | T1 review | Migration docstring carries stale template boilerplate (claim-store vocabulary + a rotted `src/clue_research/db/README.md` path) — present in 88 migrations; owner is `alembic/script.py.mako`, not this plan | template |
| 4 | T2 review | `_chromium_available()` evaluates at pytest collection time — every collection of the file launches/closes a real Chromium, including full-suite runs that deselect it | `apps/api/tests/test_document_thumbnails.py` skipif |
| 5 | T2 review | First-page test dict (`page_a4`, `page_b`) cannot distinguish key-sort order from insertion order — seed a non-sorted order (`page_z`, `page_a`) to pin the BTreeMap contract | `apps/api/tests/test_document_thumbnails.py` |
| 6 | T2 review | `inline_tailwind`'s no-`</head>` prepend can land the script ahead of a `<!DOCTYPE>` → quirks mode; web_substrate-verbatim, recorded because our input set differs | `lumen_api/document_thumbnails.py:inline_tailwind` |
| 7 | T2 review | No test pins `thumbnail.capture_failed` (a monkeypatched `sync_playwright` raising `PlaywrightError` closes the set) | `lumen_api/document_thumbnails.py:web_thumbnail_png` |
| 8 | T3 review | Deferred playwright import sits outside the `try` — an `ImportError` would escape the typed channel; unreachable in a valid install (hard dependency `playwright>=1.45,<2`) | `lumen_api/document_thumbnails.py:web_thumbnail_png` |
| 9 | T3 review | Scene path has no cache-hit test (web has one; scene is the expensive miss — a second GET should provably skip the engine export) | `apps/api/tests/test_document_thumbnails.py` |
| 10 | T3 review | No `response_class=Response` on the route → OpenAPI documents a JSON 200; cosmetic | `main.py:get_document_thumbnail` |
| 11 | T3 re-review | A `CoreError` escaping `render_web_document`'s *unwrapped* calls (brand-kit / custom-component frames) is labeled `thumbnail.export_failed` on a WEB document — contract-valid 502, code off-kind only | `main.py` thumbnail route `except CoreError` |
| 12 | T2+T3 | Suite-wide Starlette/httpx `testclient` deprecation warning in test output — pre-existing conftest-chain noise, not this plan's | `apps/api` conftest chain |
| 13 | T4 review | BFF proxy test hardcodes the harness's default base URL `http://design.internal:8000` (sibling-test pattern; both would move together) | `apps/frontend/src/app/api/clue/design/route.test.ts` |
| 14 | T5 review | Three comments (plan-inherited wording) promise a "fails to load" fallback, but the empty frame guards ABSENCE only — no `onError` anywhere, and `imagePath` is now set unconditionally, so a 502 renders a broken image element and the empty-frame branch is unreachable for the design feed. Task 6's negative check must expect that; soften the wording or rule in a real onError fallback | `gallery.ts` header + helper docblock, `gallery-artifact-card.tsx:41-43` |
| 15 | T5 review | Two DEAD legacy renderers of `ProjectArtifact.imagePath` would mishandle the new URL if remounted: `projects/components/artifact-gallery.tsx:22` (next/image WITHOUT `unoptimized` → the 401 case) and `artifact-viewer.tsx:86,158` (the Export link would download a card-sized thumbnail). Verified unimported today; latent only | `apps/frontend/src/features/projects/components/` |
| 16 | T5 | `project-workspace.ts:93-96` schema comment still says design documents "have no thumbnail" — comment drift; the field stays `.optional()` regardless | `apps/frontend/src/features/projects/model/project-workspace.ts` |
| 17 | T4 note | `etag` is NOT in `FORWARDED_RESPONSE_HEADERS` — revalidation doesn't survive the BFF; harmless under the immutable `?v=` scheme, recorded so nobody designs against it | `apps/frontend/src/auth/bff.ts:9-17` |

### Resolved along the way (no action left)

- T1's "facade methods have no committed test" → closed by Task 3's DB-gated route tests (real repo + blob store + engine).
- T2's "PIL `UnidentifiedImageError`/`ValueError` can leak past `ThumbnailUnavailable`" → closed by founder order in Task 3 (`ed330788`): both module bodies wrap non-`ThumbnailUnavailable` failures as `thumbnail.export_failed`, with pinning tests.

### Controller rulings on the record (what each costs if wrong)

1. Implementers stage only their own task files (the tree carries unrelated founder WIP) — cost: WIP committed by mistake; caught at diff review.
2. Kept plan-mandated `op.create_table` over raw-SQL house style — cost: one-file idiom inconsistency (deferred #2).
3. Smoke-test env setup: `delenv` only + skipif extended to require a resolvable runtime — cost: a skipped smoke on runtime-less machines, already accepted by the plan.
4. web_substrate authority over the plan's draft code — outcome: three deviations, all verified correct (splice `\n`, prepend fallback, `load`+400ms settle); plus two draft bugs fixed (`_REPO_ROOT` parents[4]→[5]; scene `pages` is a BTreeMap-serialized dict, first key = the editor's own page 1).
5. Task 3 dispatch keyed on `doc_kind` (default `"scene"`), never payload shape — cost if wrong: none observed; shape-sniffing would mis-route silently.
6. 502-boundary fix shape: `CoreError` → `thumbnail.export_failed`; in-try `HTTPException` → `thumbnail.render_failed` (safe: the 404 runs before the try) — **accepted consequence:** a 404 raised inside the try by a concurrent-delete race now answers 502 `render_failed`; documented at the catch site.
7. Pulled the `str(rendered["html"])`→cached-"None" guard into fix round 1 (same site, poisoned-cache class) — cost: one guard line.

### Environment facts execution depends on (recorded for Tasks 4–6 and the next session)

- The shared dev Postgres (55040) carries **foreign-branch alembic stamps** on both the workspace `clue` DB (`518a3784f3a4`) and the default db-smoke DB (`612428f3731f`) — neither resolves on this branch. All DB-gated runs use an explicit clean DSN; `clue_thumb_t1` (migrated to `be0659753362`) is the reusable throwaway: `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55040/clue_thumb_t1`. A DSN-less run of the Task-3 tests yields 8 errors — environment, not code. **Drop `clue_thumb_t1` at plan close (Task 6).**
- Pre-existing, not this plan's: `tests/db/test_unified_agent_gate_migration.py` pins a stale literal head (`064ad0f43519`) and was failing before Task 1 — separate ticket (assert `len(get_heads()) == 1` + lineage instead of a constant).
- Standing runtime prerequisites (already recorded in `subsystems/clue-design/AGENTS.md` §5, reaffirmed here): Playwright Chromium on the API process and the untracked vendored Tailwind runtime — without them, web thumbnails answer a typed 502 per card and cards fall back to the empty frame.
- Standing design notes for Tasks 5/6: cold scene thumbnails run a full engine PNG export on first gallery read; concurrent first reads duplicate generation (idempotent, wasted work only — no lock by YAGNI).

## Self-review notes

- **Spec coverage:** ruling 1 → Tasks 2/3 (PNG generators only); ruling 2 → Task 3 (generation inside the GET, no write-path hook anywhere); ruling 3 → Task 3 Step 4 (`fresh = v == str(version)`) + Task 5 (URL carries `currentVersionId`); ruling 4 → Task 5 Step 5 (card comment + `unoptimized` keeps direct authed fetch; empty frame intact) + Task 6 Step 3.5 (verified live); ruling 5 → Task 3 (kind dispatch) + Task 5 (both kinds mapped) + fixture coverage in both test files; ruling 6 → Task 2 (constants 1448/1086/0.5/724) + Task 6 contract text.
- **Known verify-at-implementation points are named as read-steps, not assumptions:** render return key + version field + register return (Task 3 Step 1), scene page shape (Task 2 Step 2), web_substrate's splice/settle authority (Task 2 Step 1), fixture names in both suites.
- **Type consistency:** `web_thumbnail_png(html)` / `png_from_export_result(result)` / `downscale_png(data)` / `first_page_ids(scene)` / `ThumbnailUnavailable(code, message)` are used identically in Tasks 2 and 3; `get_document_thumbnail(document_id, version)` / `record_document_thumbnail(document_id, version, *, sha256, media_type)` identically in Tasks 1 and 3; the URL string is byte-identical in Tasks 3, 4, 5, and 6's contract text.
