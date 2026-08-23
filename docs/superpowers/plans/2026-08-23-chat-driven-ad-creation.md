# Chat-Driven Ad Creation (genad) Implementation Plan

> **[SUPERSEDED IN PART — 2026-08-23 (evening), by genad2.** This plan SHIPPED in full
> (close-out: `_memory/2026-08-23-genad-close-out.md`), and then the founder reversed its
> **format-parameter aperture**. The birth-owns-the-page mechanism described below —
> `ad_format`/`ad_width`/`ad_height` on the tool, `AD_FORMAT_PRESETS`, `ad_birth_page`,
> `mint_empty_ad_document`, and `open_design_leg@3` itself — no longer exists in the
> codebase. `open_design_leg@4` births a **ZERO-page** scene document with **no format or
> dimension parameters**, and the design deepagent authors every page from the user's own
> words (`size(w,h,pt|px|mm|in)` / `preset(...)`); Head-of-ABM routes and delegates and
> never resolves presets, units, or dimensions. The superseding plan is
> `docs/superpowers/plans/2026-08-23-agent-authored-pages.md` (rulings recorded in
> `_memory/2026-08-23-genad-rulings.md` §ADDENDUM). Everything else this plan shipped —
> scene-birth brand stamping, the one-transaction/CAS/pin disciplines, the leg-only scene
> persist, the gallery/auto-open/editor loop — **survives unchanged**. The text below is
> kept verbatim as the historical record; do NOT read Tasks 2 and 3 as live contract.]**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A marketer asks for an ad in a project chat; Head-of-ABM opens a design leg that *births* a brand-stamped scene document at the requested format; the design trio generates and iterates on it through chat turns whose applied results persist to the document; the ad appears in the rail's gallery and opens in the (already-shipped) scene editor.

**Architecture:** This is "genweb slice 2 + G-series, for scenes." Three seams change: (1) the design DAL's creation contract learns to stamp the workspace's approved brand kit onto newborn *scene* documents exactly as it already does for web documents; (2) `open_design_leg` goes to `@3` — the v1 scene-creation refusal is replaced by a scene birth path (engine-minted empty scene + one `add_page` engine operation at the ratified format), sharing every discipline the web birth already has (leg-derived document id, one transaction, `document_version_guard=0`, pin read-back off the stored row); (3) the scene turn executor gains a **leg-only** persist step so a chat turn's accepted proposal lands in the document under CAS — the exact posture `execute_web_turn_job` already ships — while non-leg (MVP editor) turns stay byte-identical. Nothing in the trio, its tools, or the engine changes.

**Tech Stack:** Python (platform `clue_api`, design DAL `clue_design`, design API `lumen_api`), Postgres, the Rust `lumen-api-helper` engine seam (existing actions only: `new_scene`, `apply_operations`), pytest.

**Spec:** The two founder rulings ratified 2026-08-23 (recorded in `_memory/2026-08-23-genad-rulings.md`):
1. **Reverse the v1 editor-first refusal.** A document-less `open_design_leg` with `doc_kind="scene"` births an ad document — same disciplines as web birth: id derived from the leg id (retry-convergent), one transaction with the leg insert, pinned at `document_version_guard=0`, brand kit stamped at birth (fail-closed in a multi-brand workspace, honestly un-branded when no approved kit exists — identical semantics to web).
2. **Format is a structured tool parameter** — presets + a custom width×height escape, inferred by Head-of-ABM from the conversation and *stated*, correctable in chat. Infer-and-state, **no** hard confirmation gate.

A third, derived requirement surfaced during plan research and is treated as in-scope (without it the ratified flow is inert): **scene leg turns must persist their applied proposal.** Today the scene path is preview-only — the run row holds the proposal and the *editor* is the accept seam (`PUT /documents/{id}/scene`, `AgentChatPanel` → `useAgentTurn`), so a chat-born ad would generate into a run row and never reach the document, the gallery, or the editor. The genweb precedent (`execute_web_turn_job` owns its persist under the envelope's frozen `base_version`) is the ratified shape to extend.

## Global Constraints

- **Local commits only; never push; no AI attribution in commits** (repo rule).
- **No Rust/engine changes.** `new_scene` and `AddPage` are existing engine surface (`crates/lumen-api-helper/src/main.rs:916-930`, `crates/lumen-core/src/operations.rs:144`). No wasm rebuild, no handshake step, no stamp movement.
- **No new DB tables/migrations.** Birth reuses `design_document` + `design_leg` exactly as web birth does.
- **The MVP editor's non-leg turn path stays byte-identical** (the P3.7 layering rule): every new behavior in the scene executor is gated on the leg envelope block (`envelope.config["leg"]`), which non-leg turns do not carry.
- **The seam discipline holds**: nothing outside `subsystems/clue-design/` imports design internals except via the existing `clue_api.design_tools` / `clue_design` seams already in use.
- **Design-subsystem test gate** (for the `lumen_api` change): `PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/pytest apps/api/tests` from `subsystems/clue-design/`, zero new failures (five documented pre-existing checkout reds may exist — A/B against a pre-change run).
- **Platform test gate**: targeted pytest files below, then root `make check` at the end — exactly the documented pre-existing reds, zero new.
- Known trip-wire: `tests/api/test_genweb_leg_document_birth_db.py::test_scene_document_creation_is_refused` pins the v1 refusal. It **must** be consciously rewritten (Task 3), not deleted or skipped — it becomes the pin on the new birth contract.

## File Structure (whole-plan map)

```
subsystems/design/clue_design/documents.py            MODIFY  Task 1 (scene-birth brand stamp)
tests/design/test_documents_dal_db.py                 MODIFY  Task 1 (tests)
platform/api/clue_api/design_tools.py                 MODIFY  Task 2 (ad minter + page builder + presets)
tests/api/test_design_tools_ad_mint.py                CREATE  Task 2 (tests)
platform/api/clue_api/design_leg_tools.py             MODIFY  Task 3 (@3: input fields, birth path)
tests/api/test_genad_leg_document_birth_db.py         CREATE  Task 3 (tests)
tests/api/test_genweb_leg_document_birth_db.py        MODIFY  Task 3 (rewrite the refusal trip-wire)
platform/agents/catalog/profiles/head-of-abm/v38/     CREATE  Task 4 (profile bump)
platform/agents/catalog/prompts/head-of-abm/v6/       CREATE  Task 4 (prompt bump)
platform/api/clue_api/agent_registry_wiring.py        MODIFY  Task 4 (v37 → v38)
platform/api/clue_api/design_leg_wiring.py            MODIFY  Task 5 (document_base_version on the leg block)
subsystems/clue-design/apps/api/lumen_api/main.py     MODIFY  Task 5 (leg-only scene persist in execute_agent_turn_job)
subsystems/clue-design/apps/api/tests/…               MODIFY  Task 5 (executor persist tests)
scripts/seed_ad_document.py                           MODIFY  Task 7 (stale-comment sweep)
_memory/…                                             CREATE  Task 7 (close-out)
```

---

### Task 1: Scene-birth brand stamping in the design DAL

**Files:**
- Modify: `subsystems/design/clue_design/documents.py` (the `create_document` scene branch, currently lines 158-222; the web-only stamper `_stamp_approved_brand_kit_at_birth` at 64-86 is the model)
- Test: `tests/design/test_documents_dal_db.py`

**Interfaces:**
- Consumes: `clue_design.brand.latest_approved_brand_kit_ref(conn, workspace_id=…)` (already imported as `_brand`; already carries the fail-closed multi-brand semantics — reuse, do not reimplement).
- Produces: `create_document(conn, workspace_id=…, scene=…, doc_kind="scene")` stamps `scene["meta"]["brand_kit"] = {"id", "version"}` when the caller's scene carries none and the workspace has one approved kit; the stored row's `effective_brand_kit_id`/`effective_brand_kit_version` then reflect it (the existing `brand_ref = scene["meta"].get("brand_kit")` read at line 183 needs no change). Task 3's pin read-back depends on exactly this.

**Semantics (mirror the web stamper exactly):**
- Caller's explicit `meta.brand_kit` is authoritative — never overwritten.
- No approved kit (or the fail-closed multi-brand case, which `latest_approved_brand_kit_ref` already handles) → scene returned untouched: un-branded, honestly.
- A malformed `meta` (not a dict) → returned untouched (never repair caller data while choosing its brand identity — the web stamper's comment applies verbatim).
- This is create-time only; existing documents are never restamped.
- **Disclosed behavior change:** every scene creation through this DAL (editor `POST /documents`, seed scripts) in a workspace with an approved kit now births brand-stamped unless the caller pinned a kit explicitly. The seed script pins explicitly (`scripts/seed_ad_document.py` meta carries `brand_kit`), so it is unaffected. State this in the commit message.

- [ ] **Step 1: Write the failing tests** in `tests/design/test_documents_dal_db.py` (follow the file's existing fixtures for a workspace + approved kit; `test_genweb_leg_document_birth_db.py:579` shows the approved-kit arrangement to copy if this file lacks one):

```python
async def test_scene_birth_stamps_the_latest_approved_kit(db_conn, workspace_with_approved_kit):
    ws, kit_id, kit_version = workspace_with_approved_kit
    scene = _minimal_scene("doc_stamp_scene_1", title="Ad")  # meta WITHOUT brand_kit
    doc = await create_document(db_conn, workspace_id=ws, scene=scene, doc_kind="scene")
    assert doc["scene"]["meta"]["brand_kit"] == {"id": kit_id, "version": kit_version}
    assert doc["effective_brand_kit_id"] == kit_id
    assert doc["effective_brand_kit_version"] == kit_version


async def test_scene_birth_respects_an_explicit_caller_kit(db_conn, workspace_with_approved_kit):
    ws, kit_id, kit_version = workspace_with_approved_kit
    scene = _minimal_scene("doc_stamp_scene_2", title="Ad")
    scene["meta"]["brand_kit"] = {"id": "brand_kit_other", "version": 3}
    doc = await create_document(db_conn, workspace_id=ws, scene=scene, doc_kind="scene")
    assert doc["scene"]["meta"]["brand_kit"] == {"id": "brand_kit_other", "version": 3}


async def test_scene_birth_without_an_approved_kit_stays_unbranded(db_conn, bare_workspace):
    scene = _minimal_scene("doc_stamp_scene_3", title="Ad")
    doc = await create_document(db_conn, workspace_id=bare_workspace, scene=scene, doc_kind="scene")
    assert doc["scene"]["meta"].get("brand_kit") is None
    assert doc["effective_brand_kit_id"] is None
```

`_minimal_scene(document_id, title)` is a local helper returning the smallest valid scene dict: `{"schema_version": 1, "meta": {"id": document_id, "title": title, "status": {"kind": "draft"}}, "pages": {}, "nodes": {}, "slots": {}, "assets": {}, "export_profiles": []}`. Reuse an existing helper in the test file if one exists.

- [ ] **Step 2: Run to verify failure.** `CLUE_DATABASE_URL=<per-branch dev db> .venv/bin/pytest tests/design/test_documents_dal_db.py -k stamp -x -q` → the first test FAILS (meta has no `brand_kit`).

- [ ] **Step 3: Implement.** In `documents.py`, add the scene sibling directly under the web stamper:

```python
async def _stamp_approved_brand_kit_at_scene_birth(
    conn: AsyncConnection, *, workspace_id: str, scene: JsonObject
) -> JsonObject:
    """Default a NEW scene (ad) document to the workspace brand's latest approved kit.

    The scene mirror of ``_stamp_approved_brand_kit_at_birth``: create-time only, the
    caller's explicit ``meta.brand_kit`` is authoritative, and no approved kit (or the
    fail-closed multi-brand case inside ``latest_approved_brand_kit_ref``) leaves the
    scene untouched — un-branded, honestly. Ratified 2026-08-23 (genad ruling 1).
    """
    meta = scene.get("meta")
    if not isinstance(meta, dict):
        return scene
    if meta.get("brand_kit") is not None:
        return scene
    brand_kit_ref = await _brand.latest_approved_brand_kit_ref(conn, workspace_id=workspace_id)
    if brand_kit_ref is None:
        return scene
    stamped = copy.deepcopy(scene)
    stamped["meta"]["brand_kit"] = brand_kit_ref
    return stamped
```

and in `create_document`'s `else:` branch (line 179), before reading `document_id`:

```python
    else:
        scene = await _stamp_approved_brand_kit_at_scene_birth(
            conn, workspace_id=workspace_id, scene=scene
        )
        document_id = str(scene["meta"]["id"])
```

- [ ] **Step 4: Run the new tests + the whole file.** `…pytest tests/design/test_documents_dal_db.py -x -q` → PASS, zero regressions in the file.
- [ ] **Step 5: Commit.** `git add subsystems/design/clue_design/documents.py tests/design/test_documents_dal_db.py && git commit` — message: `feat(design): scene births stamp the workspace's approved brand kit (genad ruling 1) — explicit caller kit stays authoritative; no-kit births stay honestly un-branded`.

---

### Task 2: The ad document minter + format presets (platform seam)

> **[SUPERSEDED 2026-08-23 (evening) by genad2 ruling 1 — this whole task is RETIRED, not
> amended.** `AD_FORMAT_PRESETS`, `ad_birth_page`, and `mint_empty_ad_document` were
> DELETED from `platform/api/clue_api/design_tools.py` (with
> `tests/api/test_design_tools_ad_mint.py`); there is no preset registry anywhere in the
> platform, by ruling ("the agent's knowledge is the catalog"). Scene birth is now one
> engine call minting a zero-page scene. See
> `docs/superpowers/plans/2026-08-23-agent-authored-pages.md` Task 1.]**

**Files:**
- Modify: `platform/api/clue_api/design_tools.py`
- Test: `tests/api/test_design_tools_ad_mint.py` (create)

**Interfaces:**
- Consumes: `_core_client()` (`lumen_api.core.CoreClient`) — `new_scene(document_id, title, artifact_type, medium)` and `apply_operations(scene, operations)` (both existing).
- Produces (Task 3 consumes all three):
  - `AD_FORMAT_PRESETS: dict[str, tuple[int, int]]` — `{"square": (1200, 1200), "portrait": (1080, 1350), "story": (1080, 1920), "landscape": (1200, 628)}` (px; `square` matches the proven seeded LinkedIn ad).
  - `ad_birth_page(*, document_id: str, format_key: str, width: int, height: int) -> dict[str, Any]` — pure, engine-free page literal builder.
  - `mint_empty_ad_document(*, document_id: str, title: str, format_key: str, width: int, height: int, brand_kit_ref: dict[str, Any] | None = None) -> dict[str, Any]` — SYNC, blocking (helper subprocess ×2); callers on an event loop must `asyncio.to_thread` (same contract as `mint_empty_web_document`, whose docstring pattern this follows).

**Design:** the engine stays the only author of the scene shape. Mint via `new_scene` (zero pages), then add the artboard with one `add_page` engine operation — the page literal is the only platform-authored JSON, and it mirrors the engine-validated seed page shape (`scripts/seed_ad_document.py:355-372`) byte-for-shape. An explicit `brand_kit_ref` is written into `meta.brand_kit` before the DAL create (the creation contract treats it as authoritative — same rule as web); `None` leaves it absent so Task 1's stamper decides.

- [ ] **Step 1: Write the failing tests** (`tests/api/test_design_tools_ad_mint.py`). The page builder is pure — test it without the engine; the minter's engine round-trip gets one integration test that skips without a helper binary:

```python
import os
import pytest

from clue_api.design_tools import AD_FORMAT_PRESETS, ad_birth_page, mint_empty_ad_document


def test_presets_are_the_ratified_set():
    assert AD_FORMAT_PRESETS == {
        "square": (1200, 1200),
        "portrait": (1080, 1350),
        "story": (1080, 1920),
        "landscape": (1200, 628),
    }


def test_ad_birth_page_mirrors_the_seed_shape():
    page = ad_birth_page(document_id="doc_x", format_key="story", width=1080, height=1920)
    assert page["id"] == "page_" + __import__("uuid").uuid5(
        __import__("uuid").NAMESPACE_URL, "clue:genad:birth-page:doc_x"
    ).hex[:16]
    assert page["size"]["width"] == 1080.0 and page["size"]["height"] == 1920.0
    assert page["size"]["unit"] == "pt" and page["size"]["preset"] == "custom"
    assert page["size"]["orientation"] == "portrait"
    assert page["size"]["source"] == {"width": 1080.0, "height": 1920.0, "unit": "px"}
    assert page["size"]["output"] == {"raster": {"width_px": 1080, "height_px": 1920}}
    assert page["children"] == [] and page["bleed"] is None and page["safe_area"] is None
    assert page["background"] == []
    assert page["name"] == "Story"


def test_ad_birth_page_landscape_orientation():
    page = ad_birth_page(document_id="doc_y", format_key="landscape", width=1200, height=628)
    assert page["size"]["orientation"] == "landscape"


@pytest.mark.skipif(
    not os.environ.get("LUMEN_CORE_HELPER"), reason="needs the design engine helper binary"
)
def test_mint_empty_ad_document_round_trips_the_engine():
    scene = mint_empty_ad_document(
        document_id="doc_mint_ad_1", title="Test ad", format_key="square",
        width=1200, height=1200, brand_kit_ref=None,
    )
    assert scene["meta"]["id"] == "doc_mint_ad_1"
    assert scene["meta"]["title"] == "Test ad"
    assert scene["meta"]["artifact_type"] == "square_ad"
    assert scene["meta"]["medium"] == "ad"
    assert scene["meta"].get("brand_kit") is None
    assert len(scene["pages"]) == 1
    (page,) = scene["pages"].values()
    assert page["size"]["width"] == 1200.0
    assert scene["nodes"] == {}
```

- [ ] **Step 2: Run to verify failure.** `.venv/bin/pytest tests/api/test_design_tools_ad_mint.py -x -q` → FAIL (`ImportError: cannot import name 'AD_FORMAT_PRESETS'`).

- [ ] **Step 3: Implement** in `design_tools.py` (append after `mint_empty_web_document`; extend `__all__`):

```python
#: The ratified ad format presets (genad ruling 2, 2026-08-23) — px. ``square`` matches the
#: engine-validated seeded LinkedIn ad (scripts/seed_ad_document.py). Copy tweaks are cheap;
#: the custom escape (explicit width×height) covers everything else.
AD_FORMAT_PRESETS: dict[str, tuple[int, int]] = {
    "square": (1200, 1200),
    "portrait": (1080, 1350),
    "story": (1080, 1920),
    "landscape": (1200, 628),
}


def ad_birth_page(
    *, document_id: str, format_key: str, width: int, height: int
) -> dict[str, Any]:
    """The newborn ad's single artboard, as an ``add_page`` operation payload.

    The one platform-authored scene fragment in the birth path, mirroring the
    engine-validated seed page shape (scripts/seed_ad_document.py) field for field;
    everything around it is engine-minted. Deterministic page id, so a replayed birth
    converges byte-identically.
    """
    from uuid import NAMESPACE_URL, uuid5

    return {
        "id": "page_" + uuid5(NAMESPACE_URL, f"clue:genad:birth-page:{document_id}").hex[:16],
        "name": format_key.replace("_", " ").title(),
        "size": {
            "width": float(width),
            "height": float(height),
            "unit": "pt",
            "preset": "custom",
            "orientation": "landscape" if width > height else "portrait",
            "source": {"width": float(width), "height": float(height), "unit": "px"},
            "output": {"raster": {"width_px": width, "height_px": height}},
        },
        "children": [],
        "bleed": None,
        "safe_area": None,
        "background": [],
    }


def mint_empty_ad_document(
    *,
    document_id: str,
    title: str,
    format_key: str,
    width: int,
    height: int,
    brand_kit_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mint the engine's empty scene for a new ad document, with one artboard at the format.

    The scene sibling of :func:`mint_empty_web_document`, same contract: the engine is the
    only author of the scene shape (``new_scene`` then one ``add_page`` engine operation),
    it is a SYNC blocking subprocess round-trip (callers on an event loop must hop a
    thread), and ``brand_kit_ref=None`` leaves ``meta.brand_kit`` absent so the DAL's
    creation contract stamps the workspace's latest approved kit at birth (Task-1 seam).
    An explicit ref is authoritative, exactly as the web path treats ``theme.brand_kit``.
    """
    core = _core_client()
    scene = core.new_scene(document_id, title, f"{format_key}_ad", "ad")
    result = core.apply_operations(
        scene,
        [{"kind": "add_page", "page": ad_birth_page(
            document_id=document_id, format_key=format_key, width=width, height=height
        )}],
    )
    minted = cast(dict[str, Any], result["scene"])
    if brand_kit_ref is not None:
        minted["meta"]["brand_kit"] = dict(brand_kit_ref)
    return minted
```

- [ ] **Step 4: Run tests.** Pure tests PASS everywhere; the engine test PASSES when `LUMEN_CORE_HELPER` is exported (build once if needed: `cargo build -p lumen-api-helper --release` in `subsystems/clue-design/`, then `LUMEN_CORE_HELPER=<path> .venv/bin/pytest tests/api/test_design_tools_ad_mint.py -x -q`). Run it at least once with the engine before committing.
- [ ] **Step 5: Commit.** `feat(platform): mint_empty_ad_document + ratified ad format presets — engine-minted scene, one add_page op, brand ref authoritative-or-absent`.

---

### Task 3: `open_design_leg@3` — scene birth replaces the v1 refusal

> **[SUPERSEDED IN PART — 2026-08-23 (evening) by genad2 ruling 1.** The scene BIRTH this
> task introduced survives (leg-derived document id, one transaction with the leg insert,
> `document_version_guard=0`, brand stamp + pin read-back). Its **format aperture does
> not**: `ad_format`/`ad_width`/`ad_height` are gone from the input model, and with them
> the refusal codes `design_leg_ad_format_required` / `design_leg_ad_format_invalid`; the
> tool is now `open_design_leg@4` and it births a **zero-page** document (`pages == {}`)
> that the design agent then authors. An agent still sending a format field gets a loud
> unknown-field validation refusal. See
> `docs/superpowers/plans/2026-08-23-agent-authored-pages.md` Tasks 1–2.]**

**Files:**
- Modify: `platform/api/clue_api/design_leg_tools.py`
- Test: `tests/api/test_genad_leg_document_birth_db.py` (create); `tests/api/test_genweb_leg_document_birth_db.py` (rewrite `test_scene_document_creation_is_refused` at line 461)

**Interfaces:**
- Consumes: `mint_empty_ad_document`, `AD_FORMAT_PRESETS` (Task 2, imported lazily like `_default_web_document_minter` does); `create_document` (Task 1 semantics); existing `derive_leg_document_id`, `_document_title`, `_birth_web_document` (the pattern), `design_legs.open_leg`.
- Produces: the `@3` tool — new input fields `ad_format` / `ad_width` / `ad_height`; new refusal codes `design_leg_ad_format_required`, `design_leg_ad_format_invalid`; the birth path for scenes; constructor seam `scene_document_minter: SceneDocumentMinter | None = None` (tests inject a fake, mirroring `web_document_minter`). Task 4 references `open_design_leg@3`.

**Input contract (loud preconditions, toolbelt style):**
- With `document_id` present: `ad_format`/`ad_width`/`ad_height` are ignored (same rule as `doc_kind`/`title`).
- Document-less + `doc_kind="scene"`: `ad_format` REQUIRED (`design_leg_ad_format_required` refusal naming the presets). `ad_format="custom"` requires both `ad_width` and `ad_height`; a preset must NOT carry them (`design_leg_ad_format_invalid` either way — a silent ignore would hide a malformed agent belief).
- Document-less + `doc_kind="web"`: `ad_format`/dims must be absent (`design_leg_ad_format_invalid`) — no cross-kind leakage.

- [ ] **Step 1: Write the failing tests** in `tests/api/test_genad_leg_document_birth_db.py`. Copy the arrangement machinery wholesale from `tests/api/test_genweb_leg_document_birth_db.py` (workspace/project/thread/turn fixtures, the tool construction with an injected minter, the invoke harness — the file's tests at lines 277/344/579/639 are the four templates). The new coverage, one test each:

```python
# 1. test_a_document_less_scene_open_births_the_ad_and_pins_the_leg
#    doc_kind="scene", ad_format="square", fake scene minter returns a minimal scene whose
#    meta.id is the requested document_id. Assert: output.document_created is True;
#    output.document_version_guard == 0; the design_document row exists with
#    doc_kind="scene"; the leg row pins document_id + guard 0; the minter was called with
#    format_key="square", width=1200, height=1200 (the preset resolved the dims).
# 2. test_the_scene_birth_is_twin_proof_under_replay
#    Same invoke twice: same leg_id, same document_id, second call document_created=False,
#    exactly one design_document row. (Mirror of test_the_birth_is_twin_proof_under_replay:344.)
# 3. test_a_custom_format_threads_its_dimensions
#    ad_format="custom", ad_width=900, ad_height=450 → minter called with width=900,
#    height=450, format_key="custom".
# 4. test_a_scene_open_without_a_format_is_refused
#    doc_kind="scene", no ad_format → refusal reason_code="design_leg_ad_format_required";
#    no leg row, no document row (the transaction discipline).
# 5. test_a_custom_format_without_dimensions_is_refused
#    ad_format="custom", no dims → "design_leg_ad_format_invalid".
# 6. test_a_preset_with_explicit_dimensions_is_refused
#    ad_format="story", ad_width=10 → "design_leg_ad_format_invalid".
# 7. test_a_web_open_with_an_ad_format_is_refused
#    doc_kind="web", ad_format="square" → "design_leg_ad_format_invalid".
# 8. test_an_approved_kit_is_stamped_on_the_born_ad_and_the_leg_pins_it_read_back
#    Real create path (fake minter returning a kit-less scene, workspace with one approved
#    kit): leg brand_kit_id/version == the approved kit's; document row
#    effective_brand_kit_id matches. (Mirror of :579. This proves the Task-1 seam through
#    the tool.)
# 9. test_without_an_approved_kit_the_born_ad_is_unbranded_and_the_leg_carries_no_pin
#    (Mirror of :639.)
# 10. test_the_born_ad_appears_in_the_projects_gallery_feed_as_kind_ad
#    (Mirror of :388 — the AD2.1 list must serve the newborn with kind == "ad" and the
#    format's dimensions via document_page_pixels.)
```

Write all ten as real tests (the genweb file gives every arrangement; the fake minter is `lambda **kw: _minimal_scene(kw["document_id"], …)` recording its kwargs). Also rewrite the trip-wire in the genweb file:

```python
def test_scene_document_creation_births_since_genad(…):
    """Replaces test_scene_document_creation_is_refused — the v1 editor-first ruling was
    reversed 2026-08-23 (genad ruling 1). A document-less scene open now requires a format
    and births; the format-less refusal is pinned in test_genad_leg_document_birth_db."""
```
(asserting the `design_leg_ad_format_required` refusal for a format-less scene open — the closest surviving assertion to the old pin).

- [ ] **Step 2: Run to verify failure.** `CLUE_DATABASE_URL=… .venv/bin/pytest tests/api/test_genad_leg_document_birth_db.py -x -q` → FAIL (no `ad_format` field).

- [ ] **Step 3: Implement**, mirroring the web birth at every seam:

1. `OpenDesignLegInput` gains (after `title`):
```python
    #: genad ruling 2 (2026-08-23): the ad's format, REQUIRED on a document-less
    #: doc_kind="scene" open. A preset resolves its own dimensions; "custom" requires
    #: ad_width/ad_height (px). Ignored when document_id pins an existing artifact.
    ad_format: Literal["square", "portrait", "story", "landscape", "custom"] | None = Field(
        default=None
    )
    ad_width: int | None = Field(default=None, ge=16, le=8192)
    ad_height: int | None = Field(default=None, ge=16, le=8192)
```
2. `_ResolvedDelegation` gains `birth_doc_kind: str | None = None` and `birth_format: tuple[str, int, int] | None = None` (`(format_key, width, height)`); the existing `birth_title` keeps meaning "this open births".
3. In `_resolve` (the document-less branch at lines 721-741): delete the scene refusal; validate the format contract per the input rules above (raising `_LegRefused` with the two new reason codes); resolve preset dims from `AD_FORMAT_PRESETS`; set `birth_doc_kind=inputs.doc_kind`, `birth_format=(key, w, h)` for scenes / `None` for web. The web sub-branch refuses any `ad_format`/dims.
4. New `SceneDocumentMinter = Callable[..., dict[str, Any]]` + `_default_scene_document_minter` (lazy import of `mint_empty_ad_document`, mirroring `_default_web_document_minter` at 321-330); constructor takes `scene_document_minter=None` and stores it like `web_document_minter`.
5. New `_birth_scene_document` (sibling of `_birth_web_document` at 537-584, same docstring discipline):
```python
    async def _birth_scene_document(
        self, conn, *, workspace_id, document_id, title,
        format_key, width, height,
        requested_brand_kit_id, requested_brand_kit_version,
    ) -> tuple[str | None, int | None]:
        requested_ref = (
            None
            if requested_brand_kit_id is None or requested_brand_kit_version is None
            else {"id": requested_brand_kit_id, "version": requested_brand_kit_version}
        )
        scene = await asyncio.to_thread(
            self._mint_scene_document,
            document_id=document_id, title=title, format_key=format_key,
            width=width, height=height, brand_kit_ref=requested_ref,
        )
        document = await create_document(
            conn, workspace_id=workspace_id, scene=scene, doc_kind="scene"
        )
        stamped_id = document.get("effective_brand_kit_id")
        stamped_version = document.get("effective_brand_kit_version")
        if stamped_id is None or stamped_version is None:
            return None, None
        return str(stamped_id), int(stamped_version)
```
6. In `invoke`'s birth branch (line 465): branch on `resolved.birth_doc_kind` — `"scene"` calls `_birth_scene_document` with `resolved.birth_format`, `"web"` keeps the existing call byte-identical. The bundle re-freeze with the born pin (lines 477-484) is shared and unchanged.
7. `version = "3"`; `parameter_policy.safe_display_fields` gains `"ad_format"`, `"ad_width"`, `"ad_height"`; `model_description` rewritten — replace the sentence `"doc_kind='scene' cannot create a document."` with:
```
"For a NEW ad pass doc_kind='scene', no document_id, and ad_format — one of square
(1200×1200), portrait (1080×1350), story (1080×1920), landscape (1200×628), or custom
with ad_width/ad_height in px. Infer the format from what the user asked for and STATE
your choice in your reply (they can correct it); do not block on a confirmation."
```
Also update the module docstring's v1 paragraph (lines 57-58) with a dated supersession note, and the `doc_kind` field comment at 216-218.

- [ ] **Step 4: Run** the new file, the full genweb birth file, and the older leg-tool suites: `…pytest tests/api/test_genad_leg_document_birth_db.py tests/api/test_genweb_leg_document_birth_db.py tests/api/test_p34_design_leg_tool_db.py -q` → all PASS.
- [ ] **Step 5: Commit.** `feat(platform): open_design_leg@3 — chat births scene (ad) documents at a ratified format; the v1 editor-first refusal is superseded (genad rulings 1+2)`.

---

### Task 4: Head-of-ABM profile v38 + prompt v6

**Files:**
- Create: `platform/agents/catalog/profiles/head-of-abm/v38/` (copy of `v37/`), `platform/agents/catalog/prompts/head-of-abm/v6/` (copy of `v5/`)
- Modify: `platform/api/clue_api/agent_registry_wiring.py:48` (`AgentRole.HEAD_OF_ABM: "v37"` → `"v38"`, plus a dated comment line above it following the v37 comment's format: `# v38 (genad): v37 with the delegation entry at open_design_leg@3 and prompt v6 — chat ad creation.`)
- Test: whatever profile-integrity test the catalog already has (find it: `grep -rln "v37" tests/` — run it red/green around the wiring flip)

**Interfaces:**
- Consumes: Task 3's `@3` descriptor.
- Produces: the running Head-of-ABM resolves `open_design_leg@3` with prompt guidance to infer-and-state ad formats.

- [ ] **Step 1:** Diff the v36→v37 delta first (`diff -r profiles/head-of-abm/v36 profiles/head-of-abm/v37`) — that was exactly this change-class (genweb slice 2: tool `@1`→`@2` + prompt bump) and is the authoritative template for which files inside the folder carry the tool version string and the prompt pointer. Replicate that delta shape for v37→v38: every `open_design_leg@2` reference becomes `@3`; the prompt pointer moves v5→v6.
- [ ] **Step 2:** In prompt v6, extend the design-delegation guidance where v5 describes websites, with the ad counterpart (keep v5's voice):
```
When the user asks for an ad, open the design leg with doc_kind='scene' and an ad_format.
Infer the format from the ask (a LinkedIn feed ad → square; an Instagram story → story; a
display banner → landscape; otherwise ask yourself what channel they named). State the
chosen format in your reply so the user can correct it — do not ask for confirmation
before opening the leg. The generation itself starts with the user's next message, and
the ad appears in the project gallery immediately.
```
- [ ] **Step 3:** Flip `agent_registry_wiring.py` to `"v38"`. Run the catalog/profile integrity tests plus the C6 authority audit test (find via `grep -rln "build_agent_profile_registry" tests/`) → PASS.
- [ ] **Step 4: Commit.** `feat(platform): head-of-abm v38 — open_design_leg@3 grant + prompt v6 ad-format infer-and-state guidance`.

---

### Task 5: Scene leg turns persist their applied proposal (the genweb persist posture, scene-side)

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py` (`_envelope`, scene branch, lines 1315-1345)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`execute_agent_turn_job`, lines 7898-8003)
- Test: platform — extend the leg-engine test file that exercises `_envelope`/`run_leg_turn` with a stub lane driver (`tests/api/test_p34_design_leg_engine_db.py`; add assertions there or a sibling `test_genad_scene_turn_persist_db.py`); design — `subsystems/clue-design/apps/api/tests/` (the file already covering `execute_agent_turn_job` / `host.agent_turn_runner` overrides — locate with `grep -rln "agent_turn_runner" apps/api/tests/`)

**Interfaces:**
- Consumes: the existing envelope leg block (`design_leg_wiring.py:1327-1341`), `_turn_design_tools`, `_turn_core`, `_turn_blob_store`, `register_scene_asset_backstop`, the governed `design_apply_operations` tool (arg shape pinned at `main.py:984-1022`: `{document_id, scene, diagnostics, operations, source, actor_kind, actor_id, envelope, expected_base_version}`), `DesignRunSubject`, `WebDocumentVersionConflict` (raised by the CAS layer for both kinds — verify at the DAL and use whichever typed conflict `design_apply_operations` actually raises; the web executor's `except WebDocumentVersionConflict` at `main.py:8172` is the template).
- Produces: a leg-scene turn whose trio result is `status="proposed"` with a non-empty `operations` list lands those operations in the pinned document under CAS; the run result gains `"current_version"`; a CAS loss returns an honest conflicted result (never a clobber, never a fake success). Non-leg turns byte-identical. Task 6/7's visible loop depends on this.

**Persist rules (each is a test):**
1. **Leg-only.** Gate on `leg_block` being a non-empty dict AND `payload.document_id`. A direct editor turn (no leg block) must produce a byte-identical result envelope to today's.
2. **CAS base.** `_envelope`'s scene branch adds to the leg dict: `"document_base_version": int(document.get("current_version") or 0)` when the pinned document is scene-kind (`document.get("doc_kind")` not `"web"` and `leg.get("document_id")` present). The executor pre-checks `store.require_document(document_id)["current_version"] != base_version` → conflicted result *before* running the trio (the web executor's exact early-out, `main.py:8061-8062`), and passes `expected_base_version=base_version` on the governed write for the race window after.
3. **Replay-verify before trusting.** Apply the proposal's `operations` server-side via `_turn_core(host).apply_operations(doc["scene"], operations)`; error diagnostics in the result → honest failure (`agent_turn.operations_replay_failed`), no write.
4. **Asset custody before the write.** `register_scene_asset_backstop(_turn_blob_store(host, workspace_id), <the engine cache dir for this workspace — the same value `_host_engine_cache_root(host, workspace_id)` the runner was handed>, applied_scene)` — the accept-seam rule from `PUT /scene` (`main.py:2213-2218`); a generated image must gain durable custody before the registry write points at it.
5. **The governed write**, mirroring `_apply_scene_operations`'s arg shape with the web executor's actor stance:
```python
_turn_design_tools(host, run_subject).invoke(
    "design_apply_operations",
    {
        "document_id": document_id,
        "scene": applied["scene"],
        "diagnostics": applied.get("diagnostics", []),
        "operations": operations,
        "source": "agent",
        "actor_kind": "agent",
        "actor_id": envelope.run_id,
        "envelope": {
            "intent": user_message[:120],   # the USER's words, captured BEFORE the leg
                                            # prompt render — the G9 rule
            "checkpoint_label": "Design turn",
            "inverse_operations": (applied.get("edit") or {}).get("inverse_operations"),
        },
        "expected_base_version": base_version,
    },
    workspace_id=envelope.workspace_id,
    actor="agent",
    actor_id=envelope.run_id,
)
```
with `run_subject = DesignRunSubject(run_id=envelope.run_id, lease_generation=lease_generation)` now built in this executor too (the docstring sentence claiming the scene path has nothing to fence dies with this change — rewrite it).
6. **Result surface.** On success set `response["current_version"] = store.require_document(document_id)["current_version"]` and leave `status="proposed"` mapping to `"succeeded"` as today; on CAS loss return a conflicted failure result whose summary names both versions (mint `conflicted_agent_turn_response(expected, current)` beside `failed_agent_turn_response`, mirroring `conflicted_web_turn_response`). A proposal with empty/absent `operations` (pure clarification / failed run) persists nothing and flows through unchanged.

- [ ] **Step 1 (platform, TDD):** failing test — build the scene-leg envelope through the existing `run_leg_turn` stub-driver harness with a pinned scene document at version 3; assert `captured_envelope.config["leg"]["document_base_version"] == 3`, and that a **web**-pinned leg's block does NOT carry the key. Run → FAIL.
- [ ] **Step 2:** implement the `_envelope` change. Run → PASS.
- [ ] **Step 3 (design, TDD):** failing tests in the design API suite, via `host.agent_turn_runner` override (no real trio):
```
a. a leg envelope (leg block with document_base_version + document_id) whose stub runner
   returns {"status": "proposed", "operations": [<one update_node op>], …} advances the
   document: current_version bumps by 1, the op's effect is in the stored scene, the
   result carries current_version.
b. the same envelope against a document whose version moved (human edit) returns a
   conflicted failure and the document is untouched.
c. a NON-leg envelope with the same stub result does NOT touch the document (preview-only,
   byte-identical result envelope).
d. a proposed result with operations=[] persists nothing and still succeeds.
e. a stub result whose operations fail replay (an op naming a missing node) returns an
   honest failure, no write.
```
Run → FAIL.
- [ ] **Step 4:** implement the executor persist per rules 1-6. Run the new tests + the whole design API suite (`PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/pytest apps/api/tests -q`) → zero new reds.
- [ ] **Step 5: Commit** (one commit per repo-side is fine): `feat(design): leg scene turns persist their applied proposal under CAS — the genweb executor-owns-persist ruling extended to ads; editor preview turns byte-identical` and `feat(platform): scene leg envelopes carry document_base_version for the executor's CAS`.

---

### Task 6: The visible loop — gallery card, auto-open, editor entry for a chat-born ad

**Files:**
- Verification-first; expected-zero-to-small frontend/router diffs. Known surfaces: `platform/api/clue_api/chat/router.py` (the AD2.1 kind mapping at 1040-1054), `apps/frontend/src/features/design-editor/adapter/gallery.ts`, the genweb auto-open path (trace from `_memory/2026-08-19-genweb-f2b-auto-open.md`), `artifact-stage.tsx`'s ad branch.

**Interfaces:** consumes Tasks 3+5; produces the browser-proven claim Task 7's walk depends on.

- [ ] **Step 1:** Read `_memory/2026-08-19-genweb-f2b-auto-open.md` and trace the auto-open flow for a leg-born document; verify (in code, then browser) that a `kind:"ad"` birth either auto-opens the ad artifact or degrades to the card appearing without auto-open. **Ruling boundary:** if auto-open is web-hardcoded, extending it to ads is in scope ONLY if it is a branch on already-designed behavior; any new UI is a founder item (dummy frontend is presentation truth).
- [ ] **Step 2:** Browser-verify the newborn empty ad end-to-end on the live stack (frontend `:3033`, platform `:8032`, design `:8010`, fleet worker running): seed a birth through the tool (or the Task 7 walk's first half), confirm — the gallery card appears with `type:"canvas"` and the format's dimensions (`document_page_pixels` reads the birth page), no broken thumbnail; the card opens the scene editor; the editor renders the empty artboard at the format size with the Layers panel showing the artboard row; no console errors. The empty-artboard render has never been exercised before this step — if it fails, fix forward in the artifact-canvas seam and pin with a fixture test.
- [ ] **Step 3:** Commit anything changed: `feat(ad-editor): chat-born ads verified through gallery card → editor entry (empty-artboard state pinned)`.

---

### Task 7: Acceptance walk, doc supersessions, close-out

**Files:**
- Modify: `scripts/seed_ad_document.py` (docstring: the "open_design_leg refuses doc_kind='scene'" paragraph gains a dated supersession note), `docs/specs/design-integration-master-plan.md` + `CLAUDE.md` only if they state the refusal as current (grep `design_leg_scene_creation_unsupported` / "editor-first" and annotate, never rewrite history)
- Create: `_memory/2026-08-23-genad-close-out.md`

- [ ] **Step 1: The full acceptance walk** on the live stack, driven by hand (not headless-only), recorded step-for-step in the close-out note:
```
1. In a project chat: "make me a LinkedIn ad for <product>" → Head-of-ABM opens the leg,
   STATES the inferred format (square), does not ask for confirmation. Leg row + document
   row exist; document is scene-kind, version 0, brand kit stamped (the workspace has an
   approved kit); gallery card visible.
2. Next chat message ("go ahead") → the trio runs (fleet worker log); on completion the
   document version advanced, the generated ad renders in the gallery card's editor entry,
   and the chat shows the design turn's summary.
3. Manual inspector edit in the editor (one commit, one version) → then another chat turn
   ("make the headline shorter") → CAS holds: the turn ran against the fresh version or
   came back conflicted honestly (both are correct; a clobber is the failure).
4. The G-H lockout engages while the turn runs and releases after.
5. A format correction ("actually make it a story ad") on a NEW ask births a story-format
   document (1080×1920 artboard).
6. No approved kit (fresh workspace): the birth is honestly un-branded and generation
   still works.
```
- [ ] **Step 2:** Root `make check` + the design-subsystem pytest gates — exactly the documented pre-existing reds, zero new.
- [ ] **Step 3:** Write `_memory/2026-08-23-genad-close-out.md` (state, commits, walk evidence, residuals — expected carriers: reference-attachments-in-chat still dormant; leg CLOSE exit-judge timeout unchanged; any Task 6 founder items). Update the stale-comment sites. Commit: `docs(genad): close-out — chat-driven ad creation live; v1 editor-first ruling superseded (dated)`.

## Self-review (performed at authoring)

- **Spec coverage:** ruling 1 → Tasks 1+3 (birth, one transaction, guard 0, stamp, read-back); ruling 2 → Tasks 2+3+4 (presets, custom escape, required-on-scene, infer-and-state prompt); derived persist requirement → Task 5; visible loop → Task 6; evidence + supersessions → Task 7. No uncovered spec line.
- **Type consistency:** `mint_empty_ad_document(document_id, title, format_key, width, height, brand_kit_ref)` is spelled identically in Tasks 2 and 3; `AD_FORMAT_PRESETS` keys match `ad_format`'s Literal minus `"custom"`; `document_base_version` is the same key in Task 5's platform and design halves; refusal codes appear once each.
- **Placeholder scan:** Task 3 Step 1 lists tests as numbered specs with the genweb template line-refs rather than ten full bodies — deliberate: the arrangement code they share lives in the named file and copying it here 10× would drift; each entry states the exact inputs and the exact assertions. Task 5/6 name two verify-then-use facts (the typed CAS exception; the auto-open flow) where the implementer must read the named line/file first — flagged as such, not silently assumed.
