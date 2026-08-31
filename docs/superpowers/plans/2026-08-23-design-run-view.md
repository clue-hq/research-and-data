# Design Run View (unified per-run observability surface) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command materializes a browsable `.design-runs/<id>/` directory — manifest, frozen brief, current scene, per-iteration edit envelopes, event stream, and asset links with custody status — for any design run or document, derived entirely from the real storage homes.

**Architecture:** A read-only assembler module in the design API package (`lumen_api/run_view.py`) queries the design tables (`design_agent_run` / `run_event` / `design_leg` / `design_document` / `design_edit_envelope`), resolves the leg's frozen context bundle out of platform blob storage, and resolves each scene asset against BOTH homes (engine materialization cache; durable artifact custody). A thin CLI (`scripts/run_view.py`) materializes the result as files + symlinks under a gitignored `.design-runs/` tree. **Nothing writes to any substrate; the view is disposable and re-derivable.** No UI in v1 (an inspector page is designed UI → presentation-truth rule → future founder-design item).

**Tech Stack:** Python 3.12 (design-subsystem venv), asyncpg (read-only queries), pytest. No new dependencies.

**Spec (ratified in-chat by the founder, 2026-08-23):** the founder's ask — "one single dedicated design deep agent workspace" — resolved as: keep the substrate split (frozen bundle = governance; engine cache = wipeable materialization; Postgres = the only source of truth for scenes/traces), and build a **derived, unified per-run VIEW** for humans instead. Decisions: (1) v1 is a filesystem surface, not a UI page; (2) materialized **on demand** by a CLI (re-run to refresh), never by a production hook; (3) output under `subsystems/clue-design/.design-runs/<id>/`, gitignored, safe to delete.

## Global Constraints

- Local commits only; never push; no AI attribution in commits (repo rule).
- **Read-only over every substrate**: the tool must never INSERT/UPDATE/DELETE, never write inside `.engine-cache/`, `.artifacts/`, or the DB. Its only writes are inside its own `.design-runs/<id>/` output dir.
- Design-subsystem scope only (`subsystems/clue-design/`). Nothing outside imports it; it imports design/platform-shared libs only through already-sanctioned seams (it reads the DB directly and the filesystem directly — no `clue_api` imports).
- DB for tests and live use: `CLUE_DATABASE_URL` (dev: `postgresql+asyncpg://clue:clue@localhost:55040/clue`; asyncpg wants the `postgresql://` form — strip `+asyncpg`).
- Test gate (bounded — the full design api suite takes >1h and is FORBIDDEN): the new test file only, plus `ruff`-equivalent hygiene by eye (the design tree is ruff-excluded at root).
- Key filesystem shapes (verify in Task 1 Step 1 before relying on them): engine cache blob = `<asset_store_root>/<workspace_id>/sha256/<digest[:2]>/<digest>`; durable blob = `<CLUE_STORAGE_FS_ROOT>/<workspace_id>/design/<digest>`; bundle blob = `<CLUE_STORAGE_FS_ROOT>/<bundle_artifact_ref>` where the ref is already `"{ws}/{sha}"`.

## File Structure (whole-plan map)

```
subsystems/clue-design/apps/api/lumen_api/run_view.py   CREATE  Task 1 (assembler: queries + resolution, pure data out)
subsystems/clue-design/apps/api/tests/test_run_view.py  CREATE  Task 1+2 (tests)
subsystems/clue-design/scripts/run_view.py              CREATE  Task 2 (CLI + materializer)
subsystems/clue-design/.gitignore                       MODIFY  Task 2 (+ .design-runs/)
docs + ledger close-out note                            Task 3
```

---

### Task 1: The assembler — `lumen_api/run_view.py`

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/run_view.py`
- Test: `subsystems/clue-design/apps/api/tests/test_run_view.py`

**Interfaces:**
- Consumes: the design tables (names verified against the dev DB 2026-08-23): `design_agent_run(run_id, workspace_id, status, document_id, result_json, leg_id, execution_id, checkpoint_thread_id, kind, created_at, updated_at)`, `run_event(seq, workspace_id, run_id, topic, payload, created_at, subject_kind, subject_id)`, `design_leg(id, workspace_id, thread_id, state, bundle_artifact_ref, document_id, document_version_guard, brand_kit_id, brand_kit_version, created_at)`, `design_document(id, workspace_id, title, doc_kind, current_scene_json, current_version, effective_brand_kit_id, effective_brand_kit_version)`, `design_edit_envelope(id, workspace_id, document_id, seq, base_revision, actor_kind, actor_id, source, intent, checkpoint_label, operations_json)`.
- Produces (Task 2 consumes): `async def assemble(ref: str, *, database_url: str, asset_store_root: Path, storage_fs_root: Path) -> RunView` where `RunView` is a dataclass: `manifest: dict`, `brief: dict | None`, `scene: dict | None`, `envelopes: list[dict]`, `events: list[dict]`, `assets: list[AssetView]`; `AssetView` is a dataclass: `asset_id: str`, `label: str | None`, `digest: str | None`, `media_type_hint: str | None`, `cache_path: Path | None` (None when absent), `durable_path: Path | None` (None when absent), `durable_row: bool`.

**Semantics (binding):**
- `ref` may be a run id (`run_…`), a document id (`doc_…`), or a leg id (UUID). Resolution: run id → try `design_agent_run` first (design-lane runs), else fall back to `run_event` rows (`run_id = ref`, take `workspace_id` and — when `subject_kind = 'design_document'` — `subject_id` as the document id; the platform inline lane writes no `design_agent_run` row, proven live on run `run_6fa7db98…`). Document id → straight to `design_document`, leg via `design_leg.document_id`. Leg id → `design_leg.id` → its document. A ref that resolves to nothing raises `RunViewNotFound` with the ref echoed.
- Everything is best-effort-and-honest: a missing bundle blob, missing scene, or zero envelopes yields `None`/empty WITH a `manifest["gaps"]` entry naming what was absent and why that can happen (e.g. `"bundle blob not on this machine's storage root"`). The view never fabricates.
- `durable_row` is answered by the artifact-table query below (LIVE rows only), `durable_path` by direct file existence under the documented key shape — the same two facts `has_readable_bytes` checks (deliberately re-derived read-only here rather than importing the app's store, so the tool composes no app).
- No secrets in the manifest: it carries ids, versions, timestamps, statuses, gap notes — never env values or keys.

- [ ] **Step 1 (evidence lock, no code): verify the three filesystem shapes and the live-lane facts against the real dev data** — run and paste into the test file's docstring:

```bash
cd /Users/aryankeshri/conductor/workspaces/research-and-data/colombo
ls subsystems/clue-design/.engine-cache/ws_8040294627e146ae93f753ec0d3e1726/sha256/81/ | head -2
ls .artifacts/ws_8040294627e146ae93f753ec0d3e1726/ | head -3
.venv/bin/python - <<'EOF'
import asyncio, asyncpg
async def main():
    c = await asyncpg.connect('postgresql://clue:clue@localhost:55040/clue')
    print(await c.fetchrow("SELECT run_id, subject_kind, subject_id FROM run_event WHERE run_id='run_6fa7db98bf384dfd8ef231ee790798ff' LIMIT 1"))
    print(await c.fetch("SELECT table_name FROM information_schema.tables WHERE table_name='artifact'"))
    cols = await c.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='artifact' ORDER BY ordinal_position")
    print([r[0] for r in cols])
    await c.close()
asyncio.run(main())
EOF
```
Adjust the artifact-row query in Step 3 to the real column names (expect content-hash + status/namespace columns; the `/asset-store` route resolves "any LIVE row in the design namespace holding this content hash" — mirror exactly that predicate, read-only).

- [ ] **Step 2: Write the failing tests** in `subsystems/clue-design/apps/api/tests/test_run_view.py`. These are DB-seeding integration tests against the dev DB (the suite's existing DB-backed tests are the precedent; use unique ids per test so reruns never collide):

```python
"""Tests for lumen_api.run_view — the derived per-run observability view.

Founder-ratified 2026-08-23 (docs/superpowers/plans/2026-08-23-design-run-view.md):
a read-only, on-demand, disposable VIEW over the real homes; never a fourth substrate.
[Paste Step-1 evidence output here.]
"""
import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest

from lumen_api.run_view import RunViewNotFound, assemble

DB = os.environ.get("CLUE_DATABASE_URL", "").replace("+asyncpg", "")
pytestmark = pytest.mark.skipif(not DB, reason="needs CLUE_DATABASE_URL")


def _scene(document_id: str, digest: str) -> dict:
    return {
        "schema_version": 1,
        "meta": {"id": document_id, "title": "View test", "status": {"kind": "draft"}},
        "pages": {"p1": {"id": "p1"}},
        "nodes": {},
        "assets": {
            "asset_v_1": {
                "id": "asset_v_1",
                "kind": "raster_image",
                "label": "hero",
                "media": {
                    "digest": {"algorithm": "sha256", "value": digest},
                    "location": {"provider": "local-store", "url": None,
                                 "opaque_ref": f"sha256/{digest[:2]}/{digest}"},
                },
            }
        },
    }


async def _seed(conn, ws: str, doc: str, digest: str) -> None:
    await conn.execute(
        "INSERT INTO design_document (id, workspace_id, title, status, doc_kind,"
        " current_scene_json, current_version) VALUES ($1,$2,'View test','draft','scene',$3,2)",
        doc, ws, json.dumps(_scene(doc, digest)),
    )
    await conn.execute(
        "INSERT INTO design_edit_envelope (id, workspace_id, document_id, seq,"
        " envelope_version, base_revision, actor_kind, actor_id, source, intent,"
        " operations_json) VALUES ($1,$2,$3,1,1,1,'agent','run_x','agent','first edit','[]')",
        f"env_{uuid.uuid4().hex[:12]}", ws, doc,
    )


def test_assemble_by_document_id_carries_scene_envelopes_and_asset_states(tmp_path):
    ws = f"ws_view_{uuid.uuid4().hex[:10]}"
    doc = f"doc_view_{uuid.uuid4().hex[:10]}"
    digest = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars, guaranteed-absent bytes

    async def run():
        import asyncpg
        conn = await asyncpg.connect(DB)
        try:
            await _seed(conn, ws, doc, digest)
            return await assemble(
                doc, database_url=DB,
                asset_store_root=tmp_path / "cache", storage_fs_root=tmp_path / "blobs",
            )
        finally:
            await conn.execute("DELETE FROM design_edit_envelope WHERE workspace_id=$1", ws)
            await conn.execute("DELETE FROM design_document WHERE workspace_id=$1", ws)
            await conn.close()

    view = asyncio.run(run())
    assert view.manifest["document"]["id"] == doc
    assert view.manifest["document"]["current_version"] == 2
    assert view.scene["meta"]["id"] == doc
    assert [e["intent"] for e in view.envelopes] == ["first edit"]
    (asset,) = view.assets
    assert asset.digest == digest
    assert asset.cache_path is None and asset.durable_path is None
    assert asset.durable_row is False
    assert any("bundle" in g or "leg" in g for g in view.manifest["gaps"])  # no leg seeded


def test_assemble_finds_cache_resident_bytes(tmp_path):
    ws = f"ws_view_{uuid.uuid4().hex[:10]}"
    doc = f"doc_view_{uuid.uuid4().hex[:10]}"
    digest = uuid.uuid4().hex + uuid.uuid4().hex
    blob = tmp_path / "cache" / ws / "sha256" / digest[:2] / digest
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"png-bytes")

    async def run():
        import asyncpg
        conn = await asyncpg.connect(DB)
        try:
            await _seed(conn, ws, doc, digest)
            return await assemble(
                doc, database_url=DB,
                asset_store_root=tmp_path / "cache", storage_fs_root=tmp_path / "blobs",
            )
        finally:
            await conn.execute("DELETE FROM design_edit_envelope WHERE workspace_id=$1", ws)
            await conn.execute("DELETE FROM design_document WHERE workspace_id=$1", ws)
            await conn.close()

    view = asyncio.run(run())
    (asset,) = view.assets
    assert asset.cache_path == blob
    assert asset.durable_row is False


def test_unknown_ref_raises_not_found(tmp_path):
    with pytest.raises(RunViewNotFound):
        asyncio.run(assemble(
            "doc_view_definitely_absent", database_url=DB,
            asset_store_root=tmp_path, storage_fs_root=tmp_path,
        ))
```

- [ ] **Step 3: Run to verify failure.** From `subsystems/clue-design/`: `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55040/clue PYTHONPATH=.:apps/api:apps/agent_runtime /Users/aryankeshri/conductor/workspaces/research-and-data/colombo/.venv/bin/pytest apps/api/tests/test_run_view.py -x -q` → FAIL (`ModuleNotFoundError: lumen_api.run_view`).

- [ ] **Step 4: Implement `run_view.py`** — dataclasses + `assemble` per the Semantics block. Shape (fill the artifact-row predicate from Step 1's evidence; keep every query read-only):

```python
"""Derived per-run observability view (founder-ratified 2026-08-23).

Read-only over every substrate. Resolution: run_… → design_agent_run, else the
run_event stream (the platform inline lane writes no design_agent_run row);
doc_… → design_document; UUID → design_leg. Missing pieces become
manifest["gaps"] entries — the view is honest, never fabricated.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg


class RunViewNotFound(LookupError):
    """The ref matched no run, document, or leg."""


@dataclass
class AssetView:
    asset_id: str
    label: str | None
    digest: str | None
    media_type_hint: str | None
    cache_path: Path | None
    durable_path: Path | None
    durable_row: bool


@dataclass
class RunView:
    manifest: dict
    brief: dict | None
    scene: dict | None
    envelopes: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    assets: list[AssetView] = field(default_factory=list)


def _decode(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value


async def assemble(ref, *, database_url, asset_store_root, storage_fs_root):
    conn = await asyncpg.connect(database_url.replace("+asyncpg", ""))
    try:
        return await _assemble(conn, ref, Path(asset_store_root), Path(storage_fs_root))
    finally:
        await conn.close()
```
…with `_assemble` doing, in order: resolve ref → `(workspace_id, document_id, run_id | None, leg_row | None)`; load the document row; load envelopes (`ORDER BY seq`); load `run_event` rows when a run id is known (`ORDER BY seq`, payload decoded); load the bundle (`storage_fs_root / bundle_artifact_ref`, `gaps` entry when the leg or the file is absent); build `AssetView`s from `scene["assets"]` (digest from `media.digest.value`; cache path = `asset_store_root / ws / "sha256" / digest[:2] / digest` if it exists; durable path = `storage_fs_root / ws / "design" / digest` if it exists — adjust to the Step-1-verified key shape; `durable_row` from the artifact-table query); assemble `manifest` = `{"ref": ref, "workspace_id": …, "run": …, "leg": …, "document": {"id", "title", "doc_kind", "current_version", "effective_brand_kit_id", "effective_brand_kit_version"}, "counts": {"envelopes": n, "events": n, "assets": n}, "gaps": [...]}` with datetimes isoformatted.

- [ ] **Step 5: Run the file → PASS.** Same command as Step 3, all green.
- [ ] **Step 6: Commit.** `git add subsystems/clue-design/apps/api/lumen_api/run_view.py subsystems/clue-design/apps/api/tests/test_run_view.py && git commit -m "feat(design): run_view assembler — the derived per-run observability view (read-only over every home)"`

---

### Task 2: The CLI + materializer — `scripts/run_view.py`

**Files:**
- Create: `subsystems/clue-design/scripts/run_view.py`
- Modify: `subsystems/clue-design/.gitignore` (add `.design-runs/` beside `.engine-cache/`)
- Test: extend `subsystems/clue-design/apps/api/tests/test_run_view.py`

**Interfaces:**
- Consumes: `assemble` (Task 1); env `CLUE_DATABASE_URL`, `LUMEN_ASSET_STORE_ROOT` (default: the repo-local `.engine-cache` — mirror `effective_asset_store_root`'s documented default), `CLUE_STORAGE_FS_ROOT` (required; refuse loudly if unset — a guessed root is exactly the cwd-relative bug class the custody fix closed).
- Produces: `materialize(view: RunView, out_dir: Path, *, copy: bool = False) -> None` (importable, tested), plus `python scripts/run_view.py <ref> [--out DIR] [--copy]` printing the output path last.

**Output layout (binding):**
```
.design-runs/<ref>/
  manifest.json      # RunView.manifest, pretty-printed
  brief.json         # when present
  scene.current.json # when present
  envelopes/000-v<base_revision>.json …   # one per envelope, seq-ordered
  events.jsonl       # one run_event per line
  assets/<label-or-asset_id>--<digest[:12]>  # symlink to cache_path or durable_path (cache preferred); --copy copies bytes instead
  README.md          # generated: what this is, that it is disposable, the source homes
```

- [ ] **Step 1: Write the failing test** (append to `test_run_view.py`):

```python
def test_materialize_writes_the_layout(tmp_path):
    from lumen_api.run_view import AssetView, RunView
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "run_view_cli",
        Path(__file__).resolve().parents[3] / "scripts" / "run_view.py",
    )
    cli = module_from_spec(spec); spec.loader.exec_module(cli)

    blob = tmp_path / "cachefile"; blob.write_bytes(b"x")
    view = RunView(
        manifest={"ref": "doc_x", "gaps": []},
        brief={"brief": "hello"},
        scene={"meta": {"id": "doc_x"}},
        envelopes=[{"seq": 1, "base_revision": 1, "intent": "i"}],
        events=[{"seq": 1, "topic": "t", "payload": {}}],
        assets=[AssetView("a1", "hero", "ab" * 32, None, blob, None, False)],
    )
    out = tmp_path / "out"
    cli.materialize(view, out)
    assert json.loads((out / "manifest.json").read_text())["ref"] == "doc_x"
    assert json.loads((out / "brief.json").read_text()) == {"brief": "hello"}
    assert (out / "envelopes" / "000-v1.json").exists()
    assert (out / "events.jsonl").read_text().count("\n") == 1
    (link,) = (out / "assets").iterdir()
    assert link.is_symlink() and link.resolve() == blob.resolve()
    assert "disposable" in (out / "README.md").read_text()
```

- [ ] **Step 2: Run → FAIL** (no `scripts/run_view.py`).
- [ ] **Step 3: Implement** `scripts/run_view.py`: `materialize` writing exactly the layout (create dirs; `json.dumps(..., indent=2, default=str)`; skip absent sections silently — the manifest's `gaps` already names them; asset link name `f"{(a.label or a.asset_id)}--{(a.digest or 'nodigest')[:12]}"`; symlink to `cache_path or durable_path`, skip with a README note when both are None; `--copy` uses `shutil.copyfile`), and a `main()` that reads the env (refusing without `CLUE_STORAGE_FS_ROOT`), calls `asyncio.run(assemble(...))`, materializes to `--out` or `subsystems/clue-design/.design-runs/<ref>/`, and prints the path.
- [ ] **Step 4: Run the whole file → PASS.** Also gitignore: add `.design-runs/` on the line after `.engine-cache/`.
- [ ] **Step 5: Live acceptance (the real point):** from the repo root with the colombo `.env` sourced, run `python subsystems/clue-design/scripts/run_view.py run_6fa7db98bf384dfd8ef231ee790798ff` — expect: manifest resolves via the run_event fallback to `doc_9e93c1e0…`, envelopes present, `events.jsonl` non-empty, the `hero_wave_ribbons--81820a8242…` link resolves to real bytes, and `gaps` honest about anything absent. Paste the output tree into the commit body.
- [ ] **Step 6: Commit.** `git add subsystems/clue-design/scripts/run_view.py subsystems/clue-design/.gitignore subsystems/clue-design/apps/api/tests/test_run_view.py && git commit -m "feat(design): run_view CLI — one browsable .design-runs/<ref>/ per design run, derived and disposable"`

---

### Task 3: Docs + ledger close-out

**Files:**
- Modify: `subsystems/clue-design/AGENTS.md` (a short "observability: the run view" paragraph — command, what it contains, disposable)
- The genad2 ledger + close-out memory pick up the pointer (the controller owns those files).

- [ ] **Step 1:** Add to `AGENTS.md`, after §2 (keep the file's voice):
```
## 2a. Watching a design run (the run view)

`python scripts/run_view.py <run_id|doc_id|leg_id>` (env: CLUE_DATABASE_URL,
CLUE_STORAGE_FS_ROOT; optional LUMEN_ASSET_STORE_ROOT) materializes
`.design-runs/<ref>/` — manifest, frozen brief, current scene, per-iteration
envelopes, run events, and asset links with custody state. It is a DERIVED,
read-only, disposable view over the real homes (bundle artifact / engine
cache / Postgres); delete it freely, re-run to refresh. It is not a fourth
substrate and must never become a write path.
```
- [ ] **Step 2: Commit.** `git commit -m "docs(design): run-view observability note in AGENTS.md"`

## Self-review (performed at authoring)

- **Spec coverage:** decision 1 (filesystem, no UI) → Tasks 1-2 produce no frontend; decision 2 (on-demand) → CLI only, no hooks; decision 3 (location/gitignore/disposable) → Task 2 Steps 3-4 + README wording; "derived from the real homes, honest about gaps" → Task 1 semantics + tests; the founder's original pain ("where do I watch it") → Task 2 Step 5 exercises the exact live run that caused it.
- **Type consistency:** `assemble(ref, *, database_url, asset_store_root, storage_fs_root) -> RunView` and the `RunView`/`AssetView` fields are spelled identically in Tasks 1 and 2; `materialize(view, out_dir, *, copy=False)` matches its test.
- **Placeholder scan:** two deliberate verify-then-fill points, both fenced as Step-1 evidence locks with exact probe commands (the `artifact` table's real columns; the durable key shape) — the implementer adjusts one query and one path expression from pasted evidence, never invents.
