"""Tests for lumen_api.run_view — the derived per-run observability view.

Founder-ratified 2026-08-23 (docs/superpowers/plans/2026-08-23-design-run-view.md):
a read-only, on-demand, disposable VIEW over the real homes; never a fourth substrate.

Step-1 evidence lock, run 2026-08-23 against the dev DB
(``postgresql://clue:clue@localhost:55040/clue``) and this checkout's roots.

1. Engine materialization cache —
   ``subsystems/clue-design/.engine-cache/{ws}/sha256/{aa}/{digest}``::

     $ ls subsystems/clue-design/.engine-cache/ws_8040294627e146ae93f753ec0d3e1726/sha256/81/
     81820a82421c379aac25ae5f426dadb453d120d0ef44675b54126f4943a9cc94

2. Durable platform blobs under ``.artifacts/`` carry TWO key shapes, not one::

     $ ls .artifacts/ws_8040294627e146ae93f753ec0d3e1726/ | wc -l        # 96 (95 blobs + design/)
     $ ls .artifacts/ws_8040294627e146ae93f753ec0d3e1726/design/ | wc -l # 4
     $ find .artifacts/ws_8040294627e146ae93f753ec0d3e1726 -maxdepth 1 -type d
     .artifacts/ws_8040294627e146ae93f753ec0d3e1726
     .artifacts/ws_8040294627e146ae93f753ec0d3e1726/design

   ``{ws}/design/{digest}`` is the DESIGN-ASSET custody key (``clue_design.storage
   .design_storage_key``); ``{ws}/{digest}`` is everything else, and a leg's
   ``bundle_artifact_ref`` is a FULL key of that second shape — live row::

     design_leg.bundle_artifact_ref =
       'ws_8040294627e146ae93f753ec0d3e1726/8c100d0f051e1aacae181f24482e2363bf06f2c9303bdc8f3a6cab9149e270d6'

   …so the bundle is read at ``storage_fs_root / bundle_artifact_ref`` verbatim (966 bytes of
   JSON, keys: binding_set_ref, brand_kit, brief, bundle_kind, claim_refs, leg_id,
   opened_by_turn_id, project_id, schema_version, target_document, template_revision_ref,
   thread_id, turn_contract, workspace_id) while an ASSET's durable path is
   ``storage_fs_root / ws / 'design' / digest``.

3. ``artifact`` columns (``information_schema``): artifact_id, storage_key, workspace_id,
   content_sha256, media_type, size_bytes, source_key, source_url, created_at, erased_at,
   purged_at. The ``/asset-store`` predicate mirrored read-only here is
   ``clue_design.storage.read_public_design_blob``: ``content_sha256 = $1 AND
   split_part(storage_key,'/',2) = 'design' AND erased_at IS NULL AND purged_at IS NULL``
   (LIVE rows, design namespace, deliberately workspace-unscoped per ruling R-D4-7). Verified
   live row: storage_key ``ws_8040…/design/3b18f383…``, content_sha256 ``3b18f383…``,
   media_type ``image/png``, erased_at/purged_at NULL.

4. **The brief's run_event predicate was wrong and is corrected here.** ``run_event.run_id`` is
   a ``uuid`` column and is NULL for every design row (``SELECT count(*) FROM run_event WHERE
   subject_kind='design_run' AND run_id IS NOT NULL`` → 0; all 504 non-null run_ids are
   ``project_run`` rows). A design run's id lives in ``subject_id`` under
   ``subject_kind='design_run'`` (1615 rows, 67 distinct run ids). The assembler therefore joins
   events on ``subject_kind='design_run' AND subject_id = ref``.

5. **The context's probe run ``run_6fa7db98bf384dfd8ef231ee790798ff`` exists in NEITHER home** —
   0 rows in ``design_agent_run``, 0 rows in ``run_event`` (as uuid or as subject_id). It is the
   INNER deepagent run id, carried in the payload of the OUTER run
   ``run_6b30ec198f6c5d60bbb9d1ce05e51bc1`` (``design.run.completed`` →
   ``payload.result.run_id``), whose ``design_agent_run`` row does exist. The
   no-``design_agent_run``-row lane is still real (7 of the 67 distinct ``design_run`` subject
   ids have no row, e.g. ``run_3042d3336149421c9ba38f06a5d51d13``), so the fallback is kept;
   an inner run id resolves to nothing and honestly raises ``RunViewNotFound``.

6. Seeding shapes the brief could not know: ``design_edit_envelope.id`` is
   ``GENERATED ALWAYS AS IDENTITY`` (bigint — it cannot be supplied) and ``batch_id`` is a
   NOT NULL text column carrying the unique batch key; both ``design_document`` and
   ``design_edit_envelope`` have ``FOREIGN KEY (workspace_id) REFERENCES workspace``, so these
   tests seed (and drop) their own ``workspace`` row.
"""

import asyncio
import json
import os
import re
import uuid
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from lumen_api import run_view as run_view_module
from lumen_api.run_view import RunViewNotFound, assemble

DB = (
    os.environ.get("CLUE_DATABASE_URL", "")
    .replace("postgresql+asyncpg:", "postgresql:", 1)
    .replace("postgresql+psycopg:", "postgresql:", 1)
)
# Was a module-level `pytestmark` (Task 1: every test needed the DB). Task 2 adds a pure-unit
# materializer test that must NOT be skipped just because this file's neighbours need Postgres,
# so the skip is now per-test.
needs_db = pytest.mark.skipif(not DB, reason="needs CLUE_DATABASE_URL")

_CLI_PATH = Path(__file__).resolve().parents[3] / "scripts" / "run_view.py"


def _cli():
    """Load `scripts/run_view.py` as a module — it is a script, not an installed package."""
    spec = spec_from_file_location("run_view_cli", _CLI_PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
                    "location": {
                        "provider": "local-store",
                        "url": None,
                        "opaque_ref": f"sha256/{digest[:2]}/{digest}",
                    },
                },
            }
        },
    }


async def _seed(conn, ws: str, doc: str, digest: str) -> None:
    # Both design tables FK the workspace spine (evidence note 6).
    await conn.execute(
        "INSERT INTO workspace (workspace_id, name) VALUES ($1, 'run view test')", ws
    )
    await conn.execute(
        "INSERT INTO design_document (id, workspace_id, title, status, doc_kind,"
        " current_scene_json, current_version) VALUES ($1,$2,'View test','draft','scene',$3,2)",
        doc,
        ws,
        json.dumps(_scene(doc, digest)),
    )
    # `id` is GENERATED ALWAYS AS IDENTITY; `batch_id` is the supplied unique key.
    await conn.execute(
        "INSERT INTO design_edit_envelope (batch_id, workspace_id, document_id, seq,"
        " envelope_version, base_revision, actor_kind, actor_id, source, intent,"
        " operations_json) VALUES ($1,$2,$3,1,1,1,'agent','run_x','agent','first edit','[]')",
        f"env_{uuid.uuid4().hex[:12]}",
        ws,
        doc,
    )


async def _seed_leg(conn, ws: str, *, bundle_ref: str):
    """A leg that bound NO document — ``design_leg.document_id`` is nullable (migration
    549de68ae3b9), which is what a leg closed ``out_of_scope`` before a document was born looks
    like. ``design_leg`` FKs ``agent_thread(id, workspace_id)`` and
    ``execution(id, workspace_id)``, so the workspace→brand→project→thread spine is seeded
    too.
    """
    suffix = uuid.uuid4().hex[:10]
    brand, project, thread = f"brand_v_{suffix}", f"proj_v_{suffix}", f"thr_v_{suffix}"
    execution, leg = uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        "INSERT INTO workspace (workspace_id, name) VALUES ($1, 'run view test')", ws
    )
    await conn.execute(
        "INSERT INTO brand (brand_id, workspace_id, name) VALUES ($1,$2,'View brand')", brand, ws
    )
    await conn.execute(
        "INSERT INTO project (project_id, workspace_id, brand_id, name)"
        " VALUES ($1,$2,$3,'View project')",
        project,
        ws,
        brand,
    )
    await conn.execute(
        "INSERT INTO agent_thread (id, workspace_id, project_id) VALUES ($1,$2,$3)",
        thread,
        ws,
        project,
    )
    await conn.execute(
        "INSERT INTO execution (id, workspace_id, started_by, parameter_manifest_hash,"
        " pin_manifest_hash) VALUES ($1,$2,'agent',$3,$3)",
        execution,
        ws,
        "0" * 64,
    )
    await conn.execute(
        "INSERT INTO design_leg (id, workspace_id, thread_id, parent_execution_id, state,"
        " close_reason, bundle_artifact_ref) VALUES ($1,$2,$3,$4,'closed','out_of_scope',$5)",
        leg,
        ws,
        thread,
        execution,
        bundle_ref,
    )
    return leg


async def _cleanup(conn, ws: str) -> None:
    """FK order; every statement is a no-op for a test that seeded no such rows."""
    for table in (
        "design_edit_envelope",
        "design_document",
        "design_leg",
        "agent_thread",
        "project",
        "brand",
    ):
        await conn.execute(f"DELETE FROM {table} WHERE workspace_id=$1", ws)  # noqa: S608
    # `execution` is append-only (a DB trigger raises on DELETE) and it FKs the workspace, so the
    # leg test deliberately leaves one execution + one workspace row behind rather than fighting
    # the substrate. That matches the suite's stated convention (see conftest: rows accumulate;
    # run against a disposable CLUE_DATABASE_URL), and every seeded id is unique per run.
    leftover = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM execution WHERE workspace_id=$1)", ws
    )
    if not leftover:
        await conn.execute("DELETE FROM workspace WHERE workspace_id=$1", ws)


@needs_db
def test_assemble_by_document_id_carries_scene_envelopes_and_asset_states(tmp_path):
    ws = f"ws_view_{uuid.uuid4().hex[:10]}"
    doc = f"doc_view_{uuid.uuid4().hex[:10]}"
    digest = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars, guaranteed-absent bytes

    async def run():
        import asyncpg

        conn = await asyncpg.connect(DB)
        try:  # nested so a raising _cleanup can never leak the connection
            try:
                await _seed(conn, ws, doc, digest)
                return await assemble(
                    doc,
                    database_url=DB,
                    asset_store_root=tmp_path / "cache",
                    storage_fs_root=tmp_path / "blobs",
                )
            finally:
                await _cleanup(conn, ws)
        finally:
            await conn.close()

    view = asyncio.run(run())
    assert view.manifest["document"]["id"] == doc
    assert view.manifest["document"]["current_version"] == 2
    assert view.manifest["workspace_id"] == ws
    assert view.scene["meta"]["id"] == doc
    assert [e["intent"] for e in view.envelopes] == ["first edit"]
    (asset,) = view.assets
    assert asset.digest == digest
    assert asset.cache_path is None and asset.durable_path is None
    assert asset.durable_row is False
    assert any("bundle" in g or "leg" in g for g in view.manifest["gaps"])  # no leg seeded


@needs_db
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
        try:  # nested so a raising _cleanup can never leak the connection
            try:
                await _seed(conn, ws, doc, digest)
                return await assemble(
                    doc,
                    database_url=DB,
                    asset_store_root=tmp_path / "cache",
                    storage_fs_root=tmp_path / "blobs",
                )
            finally:
                await _cleanup(conn, ws)
        finally:
            await conn.close()

    view = asyncio.run(run())
    (asset,) = view.assets
    assert asset.cache_path == blob
    assert asset.durable_row is False


@needs_db
def test_leg_that_bound_no_document_degrades_with_a_gap(tmp_path):
    """A leg that RESOLVED but bound no document is a view, not a raise.

    Only a ref matching no row at all raises. This is the state of a leg closed
    ``out_of_scope`` before a document was born — its frozen context bundle is exactly what a
    debugger needs to see, so the view degrades with a gap instead of vanishing.
    """
    ws = f"ws_view_{uuid.uuid4().hex[:10]}"
    digest = uuid.uuid4().hex + uuid.uuid4().hex
    bundle_ref = f"{ws}/{digest}"  # the live shape: a FULL key, no `design/` segment
    bundle = tmp_path / "blobs" / ws / digest
    bundle.parent.mkdir(parents=True)
    bundle.write_text(json.dumps({"bundle_kind": "design_leg", "brief": "make a banner"}))

    async def run():
        import asyncpg

        conn = await asyncpg.connect(DB)
        try:  # nested so a raising _cleanup can never leak the connection
            try:
                leg = await _seed_leg(conn, ws, bundle_ref=bundle_ref)
                return await assemble(
                    str(leg),
                    database_url=DB,
                    asset_store_root=tmp_path / "cache",
                    storage_fs_root=tmp_path / "blobs",
                )
            finally:
                await _cleanup(conn, ws)
        finally:
            await conn.close()

    view = asyncio.run(run())
    assert view.manifest["workspace_id"] == ws
    assert view.manifest["leg"]["state"] == "closed"
    assert view.manifest["leg"]["close_reason"] == "out_of_scope"
    assert view.manifest["leg"]["document_id"] is None
    assert view.manifest["document"] is None
    assert view.scene is None
    assert view.envelopes == [] and view.assets == []
    assert view.brief["brief"] == "make a banner"  # the bundle still reads
    assert any("bound no document" in g for g in view.manifest["gaps"])


@needs_db
def test_unknown_ref_raises_not_found(tmp_path):
    with pytest.raises(RunViewNotFound):
        asyncio.run(
            assemble(
                "doc_view_definitely_absent",
                database_url=DB,
                asset_store_root=tmp_path,
                storage_fs_root=tmp_path,
            )
        )


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


def test_materialize_copies_bytes_and_says_so_when_an_asset_has_none(tmp_path):
    """`--copy` writes real bytes; a byte-less asset is NAMED in the README, never silently
    dropped — the whole point of the view is that absence is visible."""
    from lumen_api.run_view import AssetView, RunView

    cli = _cli()
    blob = tmp_path / "cachefile"
    blob.write_bytes(b"png")
    view = RunView(
        manifest={"ref": "doc_x", "gaps": ["one honest gap"]},
        brief=None,
        scene=None,
        envelopes=[],
        events=[],
        assets=[
            AssetView("a1", "hero", "ab" * 32, "image/png", None, blob, True),
            AssetView("a2", None, None, None, None, None, False),
        ],
    )
    out = tmp_path / "out"
    cli.materialize(view, out, copy=True)

    (copied,) = (out / "assets").iterdir()
    assert not copied.is_symlink() and copied.read_bytes() == b"png"
    assert copied.name == "hero--abababababab"
    readme = (out / "README.md").read_text()
    assert "a2" in readme and "one honest gap" in readme
    # Absent sections are skipped silently — the manifest's `gaps` already names them.
    assert not (out / "brief.json").exists()
    assert not (out / "scene.current.json").exists()
    assert not (out / "events.jsonl").exists()


def test_materialize_replaces_a_previous_view_of_the_same_ref(tmp_path):
    """Re-running the CLI on one ref must not leave the PREVIOUS run's envelopes and asset
    links lying around — a stale file in a derived view is a lie, and a leftover symlink would
    otherwise crash the second run outright."""
    from lumen_api.run_view import AssetView, RunView

    cli = _cli()
    blob = tmp_path / "cachefile"
    blob.write_bytes(b"x")
    out = tmp_path / "out"
    cli.materialize(
        RunView(
            manifest={"ref": "doc_x", "gaps": []},
            brief={"brief": "old"},
            scene=None,
            envelopes=[{"seq": 1, "base_revision": 1}, {"seq": 2, "base_revision": 2}],
            events=[],
            assets=[AssetView("a1", "hero", "ab" * 32, None, blob, None, False)],
        ),
        out,
    )
    stray = out / "not-ours.txt"
    stray.write_text("kept — materialize only clears what it wrote")

    cli.materialize(
        RunView(
            manifest={"ref": "doc_x", "gaps": []},
            brief=None,
            scene=None,
            envelopes=[{"seq": 9, "base_revision": 9}],
            events=[],
            assets=[AssetView("a1", "hero", "ab" * 32, None, blob, None, False)],
        ),
        out,
    )
    assert [p.name for p in sorted((out / "envelopes").iterdir())] == ["000-v9.json"]
    assert not (out / "brief.json").exists()
    assert len(list((out / "assets").iterdir())) == 1
    assert stray.exists()


@needs_db
def test_cli_bridges_an_inner_deepagent_run_id_to_its_outer_run(tmp_path):
    """The inner-id bridge (controller ruling 2026-08-23).

    The trio's INNER deepagent run id — the one worker logs print — exists in NO durable table;
    it survives only inside the OUTER design run's ``run_event`` payloads (evidence note 5). A
    human pasting that id must still get the view, so on ``RunViewNotFound`` the CLI runs ONE
    bounded payload search and re-assembles against the outer run, recording the indirection in
    ``manifest['bridged_from']`` and a gap. The bridge lives in the CLI, not the assembler:
    a substring match over JSON text is a paste-a-log-id affordance, not a substrate truth.
    """
    import asyncpg

    cli = _cli()
    ws = f"ws_view_{uuid.uuid4().hex[:10]}"
    outer = f"run_{uuid.uuid4().hex}"
    inner = f"run_{uuid.uuid4().hex}"

    async def run():
        conn = await asyncpg.connect(DB)
        try:
            try:
                await conn.execute(
                    "INSERT INTO workspace (workspace_id, name) VALUES ($1,'run view test')", ws
                )
                await conn.execute(
                    "INSERT INTO run_event (workspace_id, topic, subject_kind, subject_id,"
                    " payload) VALUES ($1,'design.run.completed','design_run',$2,$3)",
                    ws,
                    outer,
                    json.dumps({"result": {"run_id": inner, "status": "ok"}}),
                )
                return await cli.load_view(
                    inner,
                    database_url=DB,
                    asset_store_root=tmp_path / "cache",
                    storage_fs_root=tmp_path / "blobs",
                )
            finally:
                await conn.execute("DELETE FROM run_event WHERE workspace_id=$1", ws)
                await _cleanup(conn, ws)
        finally:
            await conn.close()

    view = asyncio.run(run())
    assert view.manifest["ref"] == outer
    assert view.manifest["bridged_from"] == inner
    assert view.manifest["workspace_id"] == ws
    assert [e["topic"] for e in view.events] == ["design.run.completed"]
    assert any(inner in gap and outer in gap for gap in view.manifest["gaps"])


@needs_db
def test_cli_bridge_miss_stays_an_honest_not_found(tmp_path):
    """A run id in no table and in no payload is simply unknown — never an invented one."""
    cli = _cli()
    with pytest.raises(RunViewNotFound):
        asyncio.run(
            cli.load_view(
                f"run_{uuid.uuid4().hex}",
                database_url=DB,
                asset_store_root=tmp_path,
                storage_fs_root=tmp_path,
            )
        )


def test_cli_refuses_an_unset_or_relative_storage_root(tmp_path, monkeypatch, capsys):
    """A RELATIVE durable root is refused as loudly as a missing one.

    `Path('.artifacts')` resolves against wherever the operator happens to stand, so the view
    would report the frozen context bundle and every durable asset as missing — the identical
    confident lie the unset-refusal exists to close, and the same cwd-relative-root class the
    design custody fix killed. Both refusals must fire BEFORE any database work.
    """
    cli = _cli()
    monkeypatch.setenv("CLUE_DATABASE_URL", "postgresql://clue:clue@127.0.0.1:1/nope")
    monkeypatch.delenv("CLUE_STORAGE_FS_ROOT", raising=False)

    with pytest.raises(SystemExit) as unset:
        cli.main(["doc_x"])
    assert "CLUE_STORAGE_FS_ROOT is not set" in str(unset.value)

    monkeypatch.setenv("CLUE_STORAGE_FS_ROOT", ".artifacts")
    with pytest.raises(SystemExit) as relative:
        cli.main(["doc_x"])
    message = str(relative.value)
    assert "relative path" in message
    # The actionable part: the path it WOULD have read.
    assert str((Path.cwd() / ".artifacts").resolve()) in message


def test_cli_warns_but_continues_on_a_relative_cache_root(tmp_path, monkeypatch, capsys):
    """The engine cache is a per-machine materialization — a wrong one costs a fallback to the
    durable blob, not a false "missing" — so a relative value warns (naming the absolute path
    used) instead of refusing. The run then fails on the DATABASE, proving it got that far."""
    cli = _cli()
    monkeypatch.setenv("CLUE_DATABASE_URL", "postgresql://clue:clue@127.0.0.1:1/nope")
    monkeypatch.setenv("CLUE_STORAGE_FS_ROOT", str(tmp_path))
    monkeypatch.setenv("LUMEN_ASSET_STORE_ROOT", "engine-cache")

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["doc_x"])
    warning = capsys.readouterr().err
    assert "LUMEN_ASSET_STORE_ROOT" in warning
    assert str((Path.cwd() / "engine-cache").resolve()) in warning
    # A connection-class failure is one friendly line naming the redacted target, not a
    # traceback — and never the credentials, which outlive a shell error line.
    message = str(exit_info.value)
    assert "cannot reach the database at 127.0.0.1:1/nope" in message
    assert "clue:clue" not in message


def test_materialize_refuses_an_out_dir_it_does_not_own(tmp_path):
    """`--out` at a real directory must not delete the caller's data.

    `_reset` removes `envelopes/` and `assets/` by name, and those are ordinary names — a
    caller-supplied out dir that happens to hold a real `assets/` directory would lose it. So
    materialize asserts OWNERSHIP first (empty, or holding the `manifest.json` every run view
    has) and refuses otherwise, deleting nothing.
    """
    from lumen_api.run_view import RunView

    cli = _cli()
    out = tmp_path / "someones-work"
    (out / "assets").mkdir(parents=True)
    (out / "assets" / "precious.png").write_bytes(b"not ours")
    (out / "envelopes").mkdir()
    (out / "notes.txt").write_text("keep me")

    view = RunView(manifest={"ref": "doc_x", "gaps": []}, brief=None, scene=None)
    with pytest.raises(SystemExit) as exit_info:
        cli.materialize(view, out)
    assert "not a run view this tool wrote" in str(exit_info.value)
    assert (out / "assets" / "precious.png").read_bytes() == b"not ours"
    assert (out / "envelopes").is_dir() and (out / "notes.txt").exists()
    assert not (out / "manifest.json").exists()  # nothing was written either


# --- the agent runtime's per-run summary (fast-loop v1 §7) --------------------------------------


def _metrics_body(**overrides) -> dict:
    body = {
        "run_id": "run_inner",
        "outcome": "accepted",
        "status": "accepted",
        "stop_reason": "review_passed",
        "wall_time_ms": 2_598_000,
        "llm_calls_total": 178,
        "llm_calls_failed": 0,
        "llm_calls_over_30s": 6,
        "input_tokens_total": 13_500_000,
        "output_tokens_total": 92_000,
        "time_to_first_preview_ms": 924_000,
        "rounds_total": 3,
        "compile_iterations_total": 34,
        "by_role": {
            "author": {
                "calls": 90,
                "failed": 0,
                "duration_ms_total": 1_200_000,
                "duration_ms_max": 104_000,
                "input_tokens": 9_000_000,
                "output_tokens": 60_000,
            }
        },
    }
    body.update(overrides)
    return body


def _progress(event_type: str, data: dict) -> dict:
    """One `design.run.event` row as the assembler hands it over."""
    return {
        "seq": 1,
        "topic": "design.run.event",
        "payload": {"event_type": event_type, "data": data},
    }


def test_extract_run_metrics_lifts_the_summary_out_of_the_event_stream():
    from lumen_api.run_view import _extract_run_metrics

    body = _metrics_body()
    gaps: list[str] = []
    events = [
        _progress("run_started", {"actor": "coordinator"}),
        _progress("run_metrics", {"actor": "coordinator", "metrics": body}),
    ]
    assert _extract_run_metrics(events, "run_outer", gaps) == body
    assert gaps == []


def test_extract_run_metrics_takes_the_newest_of_several():
    """A resumed or taken-over run can emit more than one summary; the attempt that actually
    finished is the last one on the stream."""
    from lumen_api.run_view import _extract_run_metrics

    first, second = _metrics_body(llm_calls_total=1), _metrics_body(llm_calls_total=2)
    events = [
        _progress("run_metrics", {"metrics": first}),
        _progress("run_metrics", {"metrics": second}),
    ]
    assert _extract_run_metrics(events, "run_outer", [])["llm_calls_total"] == 2


def test_extract_run_metrics_reports_its_absence_as_a_gap():
    from lumen_api.run_view import _extract_run_metrics

    gaps: list[str] = []
    assert _extract_run_metrics([_progress("run_started", {})], "run_outer", gaps) is None
    assert len(gaps) == 1 and "no run_metrics event" in gaps[0]

    # A ref that names no run has nothing to join on — that emptiness is already
    # explained by the events loader's own gap, so this must not add a second one.
    other: list[str] = []
    assert _extract_run_metrics([], None, other) is None
    assert other == []


def test_readme_renders_the_run_metrics_summary(tmp_path):
    """The whole point of the counters: the README answers "where did 43 minutes go?" without
    anyone opening a log."""
    from lumen_api.run_view import RunView

    cli = _cli()
    body = _metrics_body()
    view = RunView(
        manifest={"ref": "run_outer", "gaps": [], "metrics": body},
        brief=None,
        scene=None,
        metrics=body,
    )
    out = tmp_path / "out"
    cli.materialize(view, out)
    readme = (out / "README.md").read_text()

    assert "## Run metrics" in readme
    assert "Outcome: **accepted** (review_passed)" in readme
    assert "| wall time | 43m18s | <= 10 min |" in readme
    assert "| llm calls | 178 | <= 45 |" in readme
    assert "| time to first preview | 15m24s | <= 4 min |" in readme
    assert "| input tokens | 13,500,000 | <= 3M |" in readme
    assert "| compile iterations | 34 |" in readme
    # The per-role split names where the calls actually went.
    assert "| author | 90 | 0 | 20m00s | 1m44s | 9,000,000 | 60,000 |" in readme


def test_readme_is_honest_when_a_run_emitted_no_metrics(tmp_path):
    from lumen_api.run_view import RunView

    cli = _cli()
    view = RunView(manifest={"ref": "run_outer", "gaps": []}, brief=None, scene=None)
    out = tmp_path / "out"
    cli.materialize(view, out)
    readme = (out / "README.md").read_text()
    assert "## Run metrics" in readme
    assert "None on this run's stream" in readme


def test_readme_says_never_rendered_when_no_preview_landed(tmp_path):
    from lumen_api.run_view import RunView

    cli = _cli()
    body = _metrics_body(time_to_first_preview_ms=None, outcome="failed", stop_reason="quota")
    view = RunView(
        manifest={"ref": "run_outer", "gaps": []}, brief=None, scene=None, metrics=body
    )
    out = tmp_path / "out"
    cli.materialize(view, out)
    readme = (out / "README.md").read_text()
    assert "| time to first preview | never rendered | <= 4 min |" in readme
    assert "Outcome: **failed** (quota)" in readme


def test_the_run_view_never_writes_to_the_database(tmp_path):
    """The founder's "read-only over every substrate, never a write path" ratification, as a gate.

    Matcher rule, stated so a failure is actionable — over BOTH source files, parsed with `ast`
    so comments and the `sys.path.insert` call are out of scope by construction:

    * only STRING LITERALS are examined, and DOCSTRINGS are exempt (prose about the rule — the
      assembler's own "performs zero INSERT/UPDATE/DELETE" — is documentation, not SQL, and
      never reaches a cursor);
    * rule A: a SQL-SHAPED literal (one containing SELECT / FROM / WHERE) may not contain
      INSERT, UPDATE, DELETE, TRUNCATE, ALTER, DROP, or CREATE TABLE as whole words;
    * rule B: no literal at all may be STATEMENT-shaped (`INSERT INTO x`, `DELETE FROM x`,
      `UPDATE x SET`, `TRUNCATE/ALTER/DROP TABLE x`) — which catches a write with no FROM
      clause, and which English prose never accidentally forms.

    If prose ever trips rule A, move it into a comment or a docstring; do not weaken the gate.
    """
    import ast

    sql_shaped = re.compile(r"\b(SELECT|FROM|WHERE)\b", re.IGNORECASE)
    write_tokens = re.compile(
        r"\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP|CREATE\s+TABLE)\b", re.IGNORECASE
    )
    statements = re.compile(
        r"\b(INSERT\s+INTO|DELETE\s+FROM|UPDATE\s+\w+\s+SET|(TRUNCATE|ALTER|DROP)\s+TABLE)\b",
        re.IGNORECASE,
    )

    sources = {
        "lumen_api/run_view.py": Path(run_view_module.__file__),
        "scripts/run_view.py": _CLI_PATH,
    }
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for label, path in sources.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if not isinstance(node, holders):
                continue
            body = getattr(node, "body", None)
            first = body[0] if body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                if isinstance(first.value.value, str):
                    docstrings.add(id(first.value))
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
        assert literals, f"{label}: parsed no string literals — the matcher is broken, not clean"
        for literal in literals:
            if sql_shaped.search(literal):
                found = write_tokens.search(literal)
                assert not found, f"{label}: write token {found.group(0)!r} in SQL: {literal!r}"
            found = statements.search(literal)
            assert not found, f"{label}: write statement {found.group(0)!r} in: {literal!r}"


# Creative evaluation: removing any readiness observation, changing a delivery version,
# or resetting submission time on retry must prevent a false four-minute success.
def _evaluation_receipt(arm="candidate"):
    return {
        "schema_version": 1,
        "case_id": f"conduit-awareness-{arm}",
        "pair_id": "conduit-awareness",
        "arm": arm,
        "phase": "first_pass",
        "run_ref": f"run_{arm}",
        "request": "Create a square LinkedIn awareness ad for our product",
        "context": {
            "workspace_id": "ws_example", "product_id": "product_example",
            "brand_kit_id": "kit_example", "brand_kit_version": 1,
            "project_id": f"project_{arm}", "thread_id": f"thread_{arm}",
            "document_id": f"doc_{arm}",
        },
        "timestamps": {
            "submitted_at": "2026-09-13T12:00:00Z",
            "worker_started_at": "2026-09-13T12:00:20Z",
            "first_preview_at": "2026-09-13T12:01:00Z",
            "agent_completed_at": "2026-09-13T12:03:10Z",
            "saved_at": "2026-09-13T12:03:15Z",
            "visible_ready_at": "2026-09-13T12:03:20Z",
            "export_verified_at": "2026-09-13T12:03:30Z",
            "observed_until_at": "2026-09-13T12:03:30Z",
        },
        "attempts": [
            {"run_ref": f"run_{arm}", "kind": "initial"},
            {"run_ref": f"run_{arm}_retry", "kind": "internal_retry"},
        ],
        "operator_corrections": 0,
        "delivery": {
            "document_id": f"doc_{arm}", "version": 3,
            "scene_sha256": "a" * 64, "first_scene_ref": "evidence/scene.first.json",
            "first_png_ref": "evidence/first.png",
            **{name: {"document_id": f"doc_{arm}", "version": 3,
                      "ref": f"evidence/{name}.json"}
               for name in ("save_proof", "visible_ready_proof", "export_proof")},
        },
        "controls": {
            "runtime_sha256": "b" * 64,
            "model_config_sha256": "c" * 64,
            "knowledge_bundle_sha256": ("d" if arm == "candidate" else "e") * 64,
            "source_snapshot_sha256": "f" * 64,
            "source_snapshot_ref": "evidence/eligible-sources.json",
            "source_enforcement_ref": "evidence/retrieval-audit.json",
            "cache_isolation_ref": "evidence/cache-config.json",
            "generated_cache_namespace": f"cache_{arm}",
            "cache_hits": 0, "empty_history": True,
            "load_profile": "isolated", "worker_limit": 1, "provider_limit": 1,
        },
    }


def test_old_preview_metrics_do_not_establish_finished_creative(tmp_path):
    from lumen_api.run_view import RunView

    body = _metrics_body(time_to_first_preview_ms=60_000, wall_time_ms=190_000)
    view = RunView(manifest={"ref": "run_candidate", "metrics": body, "gaps": []},
                   brief=None, scene=None, metrics=body)
    _cli().materialize(view, tmp_path / "out")
    manifest = json.loads((tmp_path / "out/manifest.json").read_text())
    assert manifest["metrics"] == body
    assert manifest["evaluation"]["finished_creative_ms"] is None
    assert manifest["evaluation"]["status"] == "unavailable"
    assert manifest["evaluation"]["within_target"] is None
    readme = (tmp_path / "out/README.md").read_text()
    assert "finished creative | unavailable" in readme
    assert "historical first-preview gate" in readme


def test_finished_creative_includes_queue_and_all_internal_retries():
    result = _cli().evaluate_creative(_evaluation_receipt())
    assert result["status"] == "observed"
    assert result["queue_ms"] == 20_000
    assert result["first_preview_ms"] == 60_000
    assert result["agent_completion_ms"] == 190_000
    assert result["save_ms"] == 195_000
    assert result["visible_ready_ms"] == 200_000
    assert result["finished_creative_ms"] == 210_000
    assert result["attempts_total"] == 2
    assert result["within_target"] is True
    assert result["within_stretch"] is False
    assert result["first_pass_eligible"] is True


@pytest.mark.parametrize("field", ["submitted_at", "agent_completed_at", "saved_at",
                                    "visible_ready_at", "export_verified_at"])
def test_finished_creative_is_unavailable_without_every_required_timestamp(field):
    receipt = _evaluation_receipt()
    receipt["timestamps"].pop(field)
    result = _cli().evaluate_creative(receipt)
    assert result["finished_creative_ms"] is None
    assert result["within_target"] is None
    assert any(field in gap for gap in result["gaps"])


@pytest.mark.parametrize("value", ["2026-09-13T12:03:30", "not a timestamp",
                                   "2026-09-13T11:59:59Z", True])
def test_bad_or_pre_submission_timestamp_cannot_count_as_finished(value):
    receipt = _evaluation_receipt()
    receipt["timestamps"]["export_verified_at"] = value
    result = _cli().evaluate_creative(receipt)
    assert result["finished_creative_ms"] is None
    assert result["status"] == "invalid"
    assert _cli().compare_evaluations(_evaluation_receipt("baseline"), receipt)["status"] == "ineligible"


def test_finished_evidence_cannot_mix_versions_or_precede_save():
    receipt = _evaluation_receipt()
    receipt["delivery"]["export_proof"]["version"] = 2
    result = _cli().evaluate_creative(receipt)
    assert result["finished_creative_ms"] is None
    assert any("export_proof" in gap for gap in result["gaps"])
    receipt = _evaluation_receipt()
    receipt["timestamps"]["visible_ready_at"] = "2026-09-13T12:03:00Z"
    assert _cli().evaluate_creative(receipt)["status"] == "invalid"


def test_missing_preview_does_not_erase_independently_observed_finish():
    receipt = _evaluation_receipt()
    receipt["timestamps"].pop("first_preview_at")
    result = _cli().evaluate_creative(receipt)
    assert result["first_preview_ms"] is None
    assert result["finished_creative_ms"] == 210_000
    assert any("first_preview_at" in gap for gap in result["gaps"])


def test_late_delivery_and_timeout_are_retained_without_imputed_finish():
    receipt = _evaluation_receipt()
    receipt["timestamps"]["export_verified_at"] = "2026-09-13T12:04:20Z"
    receipt["timestamps"]["observed_until_at"] = "2026-09-13T12:04:20Z"
    result = _cli().evaluate_creative(receipt)
    assert result["finished_creative_ms"] == 260_000
    assert result["within_target"] is False
    receipt["timestamps"].pop("export_verified_at")
    receipt["timestamps"]["observed_until_at"] = "2026-09-13T12:10:00Z"
    result = _cli().evaluate_creative(receipt)
    assert result["status"] == "timed_out"
    assert result["finished_creative_ms"] is None
    assert result["within_target"] is None
    assert result["include_in_denominator"] is True


def test_operator_repair_is_never_promoted_to_first_pass():
    receipt = _evaluation_receipt()
    receipt["operator_corrections"] = 1
    assert _cli().evaluate_creative(receipt)["status"] == "invalid"
    receipt["phase"] = "assisted_repair"
    receipt["parent_case_id"] = "conduit-awareness-first"
    result = _cli().evaluate_creative(receipt)
    assert result["finished_creative_ms"] == 210_000
    assert result["first_pass_eligible"] is False


@pytest.mark.parametrize("field,value", [
    ("source_snapshot_sha256", "0" * 64), ("runtime_sha256", "0" * 64),
    ("model_config_sha256", "0" * 64), ("load_profile", "queued"),
    ("worker_limit", 4), ("provider_limit", 4),
    ("generated_cache_namespace", "cache_baseline"),
    ("source_enforcement_ref", ""), ("empty_history", False),
])
def test_pair_rejects_changed_inputs_or_unproven_isolation(field, value):
    baseline, candidate = _evaluation_receipt("baseline"), _evaluation_receipt()
    candidate["controls"][field] = value
    result = _cli().compare_evaluations(baseline, candidate)
    assert result["status"] == "ineligible"
    assert any(field in gap for gap in result["gaps"])


def test_consistent_pair_is_not_an_execution_isolation_claim():
    result = _cli().compare_evaluations(_evaluation_receipt("baseline"), _evaluation_receipt())
    assert result["status"] == "receipt_consistent"
    assert result["execution_isolation_verified"] is False
    assert result["gaps"] == []


def test_pair_rejects_operator_repair_and_reused_chat():
    baseline, candidate = _evaluation_receipt("baseline"), _evaluation_receipt()
    candidate["context"]["thread_id"] = baseline["context"]["thread_id"]
    candidate["phase"] = "assisted_repair"
    result = _cli().compare_evaluations(baseline, candidate)
    assert result["status"] == "ineligible"
    assert any("thread_id" in gap for gap in result["gaps"])
    assert any("first_pass" in gap for gap in result["gaps"])


def test_materialized_evaluation_binds_the_receipt_to_actual_run_and_document(tmp_path):
    from lumen_api.run_view import RunView

    view = RunView(manifest={"ref": "run_other", "workspace_id": "ws_example",
                            "document": {"id": "doc_candidate", "current_version": 3},
                            "gaps": []}, brief=None, scene=None)
    cli = _cli()
    cli.materialize(view, tmp_path / "out", evaluation_receipt=_evaluation_receipt())
    result = json.loads((tmp_path / "out/manifest.json").read_text())["evaluation"]
    assert result["status"] == "invalid"
    assert result["finished_creative_ms"] is None
    assert any("run_ref" in gap for gap in result["gaps"])


@pytest.mark.parametrize("field", ["context", "timestamps", "delivery", "controls"])
def test_malformed_receipt_sections_are_invalid_not_tracebacks(field):
    receipt = _evaluation_receipt()
    receipt[field] = "malformed"
    result = _cli().evaluate_creative(receipt)
    assert result["status"] == "invalid"
    assert result["finished_creative_ms"] is None
    assert _cli().compare_evaluations(_evaluation_receipt("baseline"), receipt)["status"] == "ineligible"


@pytest.mark.parametrize("attempts", [
    None, [], "missing attempt records", {"run_ref": "run_candidate", "kind": "initial"},
    [None], [{}], [{"kind": "initial"}],
    [{"run_ref": "", "kind": "initial"}], [{"run_ref": "   ", "kind": "initial"}],
    [{"run_ref": 7, "kind": "initial"}], [{"run_ref": ["run_candidate"], "kind": "initial"}],
    [{"run_ref": "run_other", "kind": "initial"}],
    [{"run_ref": "run_candidate"}], [{"run_ref": "run_candidate", "kind": None}],
    [{"run_ref": "run_candidate", "kind": "unknown"}],
    [{"run_ref": "run_candidate", "kind": "internal_retry"}],
    [{"run_ref": "run_candidate", "kind": "initial"}, None],
    [{"run_ref": "run_candidate", "kind": "initial"},
     {"run_ref": "run_candidate_retry", "kind": "initial"}],
    [{"run_ref": "run_candidate", "kind": "initial"},
     {"run_ref": "run_candidate_retry", "kind": []}],
])
def test_pair_requires_attempt_receipts_so_retries_cannot_disappear(attempts):
    receipt = _evaluation_receipt()
    receipt["attempts"] = attempts
    evaluation = _cli().evaluate_creative(receipt)
    assert evaluation["status"] == "invalid"
    assert evaluation["finished_creative_ms"] is None
    assert evaluation["attempts_total"] is None
    assert evaluation["first_pass_eligible"] is False
    assert evaluation["include_in_denominator"] is True
    result = _cli().compare_evaluations(_evaluation_receipt("baseline"), receipt)
    assert result["status"] == "ineligible"
    assert any("candidate.attempts" in gap for gap in result["gaps"])


def test_missing_attempt_ledger_is_not_an_eligible_first_pass():
    receipt = _evaluation_receipt("baseline")
    receipt.pop("attempts")
    assert _cli().evaluate_creative(receipt)["first_pass_eligible"] is False
    result = _cli().compare_evaluations(receipt, _evaluation_receipt())
    assert result["status"] == "ineligible"
    assert any("baseline.attempts" in gap for gap in result["gaps"])


def test_internal_repairs_keep_the_original_submission_and_run_binding():
    receipt = _evaluation_receipt()
    receipt["attempts"].append({"run_ref": "run_candidate_retry", "kind": "internal_repair"})
    result = _cli().evaluate_creative(receipt)
    assert result["status"] == "observed"
    assert result["first_pass_eligible"] is True
    assert result["attempts_total"] == 3
    assert result["finished_creative_ms"] == 210_000
    assert _cli().compare_evaluations(_evaluation_receipt("baseline"), receipt)["status"] == "receipt_consistent"


def test_cli_rejects_bad_receipt_before_any_database_access(tmp_path, monkeypatch):
    monkeypatch.delenv("CLUE_DATABASE_URL", raising=False)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("[]")
    with pytest.raises(SystemExit) as error:
        _cli().main(["run_example", "--evaluation-receipt", str(receipt)])
    assert error.value.code == 2
