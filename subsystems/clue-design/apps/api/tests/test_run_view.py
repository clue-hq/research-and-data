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
import uuid
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from lumen_api.run_view import RunViewNotFound, assemble

DB = os.environ.get("CLUE_DATABASE_URL", "").replace("+asyncpg", "")
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
