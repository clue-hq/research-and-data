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


async def _cleanup(conn, ws: str) -> None:
    await conn.execute("DELETE FROM design_edit_envelope WHERE workspace_id=$1", ws)
    await conn.execute("DELETE FROM design_document WHERE workspace_id=$1", ws)
    await conn.execute("DELETE FROM workspace WHERE workspace_id=$1", ws)


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
                doc,
                database_url=DB,
                asset_store_root=tmp_path / "cache",
                storage_fs_root=tmp_path / "blobs",
            )
        finally:
            await _cleanup(conn, ws)
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
                doc,
                database_url=DB,
                asset_store_root=tmp_path / "cache",
                storage_fs_root=tmp_path / "blobs",
            )
        finally:
            await _cleanup(conn, ws)
            await conn.close()

    view = asyncio.run(run())
    (asset,) = view.assets
    assert asset.cache_path == blob
    assert asset.durable_row is False


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
