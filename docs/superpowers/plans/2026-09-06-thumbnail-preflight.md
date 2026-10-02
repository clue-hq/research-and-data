# Thumbnail route: preflight before render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A scene document's gallery thumbnail renders the document as the editor and the export do: brand tokens resolved against the document's effective kit and geometry solved, instead of the raw stored scene (which fails with LUME0209 "unresolved brand token" and LUME0205 "no export geometry" and comes back as a blank white PNG for every agent-authored ad).

**Architecture:** In `GET /documents/{id}/thumbnail`'s scene branch (`lumen_api/main.py`), do what `POST /documents/{id}/export` does before rendering: choose the effective brand (`choose_effective_brand` with a default `PreflightRequest`), its mode, its fonts, run `core.preflight_scene`, and export the PREFLIGHTED scene. Best-effort by contract: preflight diagnostics are logged, never a refusal (a thumbnail is a preview, not a deliverable); the route stays read-only (no `_persist_preflight`); cache, kind routing and the typed 502s are untouched.

**Tech Stack:** Python 3.12 / FastAPI; pytest (`apps/api/tests`, TestClient over the real core helper, throwaway DB); PIL for the pixel assertion (already a dependency of `document_thumbnails`).

**Spec:** founder Q&A 2026-09-06 (this chat): the route predates token-based documents; fix at the route, keep read-only, keep best-effort, bounded cost (one preflight per document version, then cached).

## Global Constraints

- One Opus implementer; controller reviews the diff and re-runs the tests first-hand. Commit locally, never push, no AI attribution, never `git stash`; stage by explicit path.
- Python tests run from `subsystems/clue-design`: `set -a; source ../../.env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_plan1_test"; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_document_thumbnails.py -q` — the throwaway DB `clue_plan1_test` on 55040, NEVER the shared `clue_colombo`. `LUMEN_CORE_HELPER` in `.env` points at the release helper; do not rebuild Rust.
- Touch only `apps/api/lumen_api/main.py` (the thumbnail route) and `apps/api/tests/test_document_thumbnails.py` (+ its conftest if a scene seed fixture is needed). No other route changes.
- The existing three thumbnail route tests and the module tests must pass unchanged.

---

### Task 1: Preflight in the thumbnail's scene branch

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`get_document_thumbnail`, the `else:` scene branch — currently `scene = document["scene"] … export_preview(scene, …, brand_fonts=scene_brand_fonts(...))`)
- Test: `subsystems/clue-design/apps/api/tests/test_document_thumbnails.py` (+ `tests/conftest.py` only if no seeded-scene-document fixture exists)

**Interfaces:**
- Consumes (all existing in `main.py`/`core.py`): `choose_effective_brand(core, repo, document, PreflightRequest)`, `choose_effective_brand_mode(document, brand_kit, requested_mode)`, `brand_kit_font_spec(repo, brand_kit, blobs, cache_dir)`, `scene_brand_fonts(repo, scene, blobs, cache_dir)`, `core.preflight_scene(scene, brand_kit, mode, brand_fonts=)`, `diagnostic_summary`, `log_event`.
- Produces: no new names.

- [ ] **Step 1: Write the failing test.** Find how the suite seeds documents (`seeded_web_document` in conftest; look for a scene equivalent). Seed a SCENE document whose scene has: one page; a frame filled with a brand TOKEN (`{"kind": "token", "token": "surface.inverse"}` or whatever token shape the minimal fixture/kit uses — read `crates/lumen-core/fixtures/minimal_scene.json` and a kit fixture the API tests already create, e.g. via `POST /brand-kits`); one text node sized `hug`×`hug`; every node with `"computed": null`. Attach a kit that defines that token (`POST /documents/{id}/brand-kit` or the seed path the export tests use). Then:

```python
def test_scene_thumbnail_resolves_tokens_and_geometry(client: TestClient, seeded_token_scene_document: str):
    """A token-filled, unsolved scene (every agent-authored ad) used to export raw and come back
    as a blank white PNG (LUME0209 / LUME0205, raise_on_error=False). The route now preflights
    like the export route, so the card shows the design."""
    response = client.get(f"/documents/{seeded_token_scene_document}/thumbnail")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    colours = image.getcolors(maxcolors=1 << 20) or []
    non_white = [count for count, rgb in colours if rgb != (255, 255, 255)]
    assert non_white, "the thumbnail is blank: nothing but white pixels"
    assert sum(non_white) > image.width * image.height * 0.05, "barely any ink — tokens or geometry still unresolved"
```

Also assert the document's version and stored scene are UNCHANGED after the call (read-only): compare `client.get(f"/documents/{id}")` before/after (`current_version` equal, `scene` equal).

- [ ] **Step 2: Run it to verify it fails** — the assertion on ink fails (all white) on the current route.

- [ ] **Step 3: Implement** — replace the scene branch body with:

```python
                else:
                    scene = document["scene"]
                    cache_dir = request_cache_dir(repo)
                    materialize_scene_assets(blobs, cache_dir, [scene])
                    # 2026-09-06: render what the editor and the export show, not the
                    # raw stored scene. Agent-authored ads carry brand TOKENS and
                    # hug/fill sizes with no stored geometry; exported raw they fail
                    # LUME0209 / LUME0205 on every node and the PNG came back white
                    # — a 200 with nothing in it. So: the document's effective brand
                    # (the export route's own chooser, default request = the pinned
                    # kit, platform default as the last resort), its mode and fonts,
                    # one preflight, and the PREFLIGHTED scene goes to the renderer.
                    # Best-effort by contract — preflight diagnostics are logged,
                    # never a refusal (a card is a preview, not a deliverable) — and
                    # READ-ONLY: nothing here persists (no `_persist_preflight`),
                    # keeping the route's never-in-the-write-path rule.
                    source, brand_kit = choose_effective_brand(
                        app.state.core, repo, document, PreflightRequest(persist_effective_brand=False)
                    )
                    mode = choose_effective_brand_mode(document, brand_kit, None)
                    brand_fonts = (
                        brand_kit_font_spec(repo, brand_kit, blobs, cache_dir)
                        if brand_kit is not None
                        else scene_brand_fonts(repo, scene, blobs, cache_dir)
                    )
                    preflight_result = app.state.core.preflight_scene(
                        scene, brand_kit, mode, brand_fonts=brand_fonts
                    )
                    preflight_diagnostics = preflight_result.get("diagnostics", [])
                    log_event(
                        api_logger,
                        logging.INFO,
                        "document_thumbnail_preflight",
                        document_id=document_id,
                        version=version,
                        effective_brand_source=source,
                        **diagnostic_summary(preflight_diagnostics),
                    )
                    export_scene = preflight_result.get("scene") or scene
                    result = app.state.core.export_preview(
                        export_scene,
                        "png",
                        document_thumbnails.first_page_ids(export_scene),
                        default_export_profile("png"),
                        raise_on_error=False,
                        asset_store_root=cache_dir,
                        brand_fonts=brand_fonts,
                    )
                    data = document_thumbnails.downscale_png(
                        document_thumbnails.png_from_export_result(result)
                    )
```

`choose_effective_brand` and `preflight_scene` raise `CoreError`/`NotFoundError` on their own failure paths; both must land in the existing `except CoreError` → 502 `thumbnail.export_failed` (widen that clause to `except (CoreError, NotFoundError)` if `NotFoundError` is not a `CoreError`; check). Verify `PreflightRequest`, `choose_effective_brand`, `choose_effective_brand_mode`, `brand_kit_font_spec`, `diagnostic_summary`, `log_event`, `api_logger`, `logging` are all in scope in `main.py` (they are used by `export_document` in the same file).

- [ ] **Step 4: Run the file's tests** — the new test passes; the existing thumbnail tests pass unchanged. Then run `apps/api/tests/test_api.py -k thumbnail -q` if any there, and `apps/api/tests/test_document_thumbnails.py -q` again.

- [ ] **Step 5: Commit** (explicit paths):

```bash
git add subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_document_thumbnails.py   # + conftest.py if touched
git commit -m "fix(design-api): thumbnails preflight the document before rendering

The gallery thumbnail exported the raw stored scene — no brand kit, no layout —
so every agent-authored ad (token fills, hug sizes, no stored geometry) failed
LUME0209/LUME0205 on every node and came back as a blank white PNG with a 200.
The scene branch now resolves the document's effective brand, mode and fonts and
preflights exactly as the export route does, then renders the preflighted scene.
Best-effort (diagnostics logged, never refused) and read-only (nothing persisted)."
```

### Task 2 (controller): deploy and clear the cached blanks

- [ ] Restart colombo's design API (8060) per the runbook; find the thumbnail index table (`repo.get_document_thumbnail` → DAL) and delete the cached rows for the Apollo workspace's scene documents so the next gallery view regenerates; open the gallery in the browser and confirm the Deel, Brex and Ramp cards render; memo.
