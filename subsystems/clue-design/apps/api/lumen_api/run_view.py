"""Derived per-run observability view (founder-ratified 2026-08-23).

Read-only over every substrate. Resolution: ``run_…`` → ``design_agent_run``, else the
``run_event`` stream (the platform inline lane writes no ``design_agent_run`` row);
``doc_…`` → ``design_document``; UUID → ``design_leg``. Missing pieces become
``manifest["gaps"]`` entries — the view is honest, never fabricated.

This module performs **zero** INSERT/UPDATE/DELETE and writes no files: it is a VIEW over the
design subsystem's three real homes (the frozen context bundle in platform blob storage, the
engine materialization cache, and Postgres as the sole source of truth for scenes/envelopes/
events), never a fourth substrate. It also composes no app — the ``/asset-store`` route's
durable-row predicate is re-derived here as read-only SQL rather than imported, so the tool
needs no FastAPI application, no storage backend, and no workspace context to run.
"""

from __future__ import annotations

import json
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import asyncpg

# Mirrors `clue_design.storage.DESIGN_KEY_SEGMENT` — the namespace segment of a design custody
# key `{workspace_id}/design/{sha256}`. Re-stated (not imported) so this module composes no app.
_DESIGN_KEY_SEGMENT = "design"


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


def _decode(value: Any) -> Any:
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def _stamp(value: Any) -> Any:
    """Datetimes isoformat and UUIDs stringify, so the manifest is plain JSON.

    UUIDs are not cosmetic here: ``design_leg.id``, ``design_agent_run.leg_id`` and
    ``execution_id`` are real ``uuid`` columns, and asyncpg hands back ``uuid.UUID`` objects
    that ``json.dumps`` refuses — which would break the writer that consumes this manifest.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, _uuid.UUID):
        return str(value)
    return value


def _row(record: asyncpg.Record | None, *json_columns: str) -> dict | None:
    if record is None:
        return None
    out: dict = {}
    for key, value in record.items():
        out[key] = _decode(value) if key in json_columns else _stamp(value)
    return out


async def assemble(
    ref: str,
    *,
    database_url: str,
    asset_store_root: Path,
    storage_fs_root: Path,
) -> RunView:
    conn = await asyncpg.connect(database_url.replace("+asyncpg", ""))
    try:
        return await _assemble(conn, ref, Path(asset_store_root), Path(storage_fs_root))
    finally:
        await conn.close()


async def _assemble(
    conn: asyncpg.Connection, ref: str, asset_store_root: Path, storage_fs_root: Path
) -> RunView:
    gaps: list[str] = []
    run_row, leg_row, run_id, workspace_id, document_id = await _resolve(conn, ref, gaps)

    document_row = await _load_document(
        conn, ref, workspace_id, document_id, gaps, from_leg=leg_row is not None
    )
    if document_row is not None:
        workspace_id = document_row["workspace_id"]
        document_id = document_row["id"]

    if leg_row is None:
        leg_row = await _load_leg(conn, run_row, workspace_id, document_id, gaps)
    if leg_row is None:
        gaps.append(
            "no design_leg row — the frozen context bundle is a leg-scoped artifact, so a "
            "document that was never opened as a chat leg (or an editor-only edit session) "
            "simply has no bundle to show"
        )

    brief = _load_bundle(leg_row, storage_fs_root, gaps)
    scene = _decode(document_row["current_scene_json"]) if document_row else None
    if document_row is not None and not scene:
        gaps.append("design_document.current_scene_json is empty — the document holds no scene")

    envelopes = await _load_envelopes(conn, workspace_id, document_id, gaps)
    events = await _load_events(conn, run_id, gaps)
    assets = await _load_assets(conn, scene, workspace_id, asset_store_root, storage_fs_root, gaps)

    manifest = {
        "ref": ref,
        "workspace_id": workspace_id,
        "run": run_row,
        "leg": leg_row,
        "document": (
            {
                "id": document_row["id"],
                "title": document_row["title"],
                "doc_kind": document_row["doc_kind"],
                "current_version": document_row["current_version"],
                "effective_brand_kit_id": document_row["effective_brand_kit_id"],
                "effective_brand_kit_version": document_row["effective_brand_kit_version"],
                "created_at": document_row["created_at"],
                "updated_at": document_row["updated_at"],
            }
            if document_row
            else None
        ),
        "counts": {
            "envelopes": len(envelopes),
            "events": len(events),
            "assets": len(assets),
        },
        "gaps": gaps,
    }
    return RunView(
        manifest=manifest,
        brief=brief,
        scene=scene,
        envelopes=envelopes,
        events=events,
        assets=assets,
    )


# --- resolution -------------------------------------------------------------------------------


async def _resolve(
    conn: asyncpg.Connection, ref: str, gaps: list[str]
) -> tuple[dict | None, dict | None, str | None, str | None, str | None]:
    """``ref`` → ``(run_row, leg_row, run_id, workspace_id, document_id)``."""
    if ref.startswith("run_"):
        run_row = _row(
            await conn.fetchrow(
                "SELECT run_id, workspace_id, status::text AS status, document_id, leg_id,"
                " execution_id, checkpoint_thread_id, kind::text AS kind, created_at, updated_at"
                " FROM design_agent_run WHERE run_id = $1",
                ref,
            )
        )
        if run_row is not None:
            return run_row, None, ref, run_row["workspace_id"], run_row["document_id"]
        # Fallback: the run_event stream. EVIDENCE 2026-08-23 — `run_event.run_id` is a uuid
        # column that is NULL for every design row; a design run's id lives in `subject_id`
        # under `subject_kind = 'design_run'`. (The brief's `run_id = ref` predicate would
        # match nothing; this is the corrected join.)
        event = await conn.fetchrow(
            "SELECT workspace_id FROM run_event"
            " WHERE subject_kind = 'design_run' AND subject_id = $1 ORDER BY seq LIMIT 1",
            ref,
        )
        if event is None:
            raise RunViewNotFound(f"no run, document, or leg matches ref {ref!r}")
        gaps.append(
            "no design_agent_run row for this run — resolved from the run_event stream alone "
            "(the platform inline lane records no design_agent_run row), so the run's status, "
            "kind, and document link are unavailable"
        )
        return None, None, ref, event["workspace_id"], None

    if ref.startswith("doc_"):
        return None, None, None, None, ref

    try:
        leg_id = _uuid.UUID(ref)
    except ValueError as error:
        raise RunViewNotFound(
            f"ref {ref!r} is neither a run id (run_…), a document id (doc_…), nor a leg UUID"
        ) from error
    leg_row = _row(await conn.fetchrow(_LEG_SELECT + " WHERE id = $1", leg_id))
    if leg_row is None:
        raise RunViewNotFound(f"no design_leg matches ref {ref!r}")
    return None, leg_row, None, leg_row["workspace_id"], leg_row["document_id"]


async def _load_document(
    conn: asyncpg.Connection,
    ref: str,
    workspace_id: str | None,
    document_id: str | None,
    gaps: list[str],
    *,
    from_leg: bool,
) -> dict | None:
    if document_id is None:
        # The ref RESOLVED — only a ref matching no row at all raises. A run can name no
        # document, and `design_leg.document_id` is nullable (migration 549de68ae3b9), so a leg
        # closed before a document was born is a real, showable state: the leg block, its frozen
        # bundle, and this gap are exactly what the debugger needs to see.
        gaps.append(
            (
                "this leg bound no document (design_leg.document_id is NULL — e.g. a leg closed "
                "out_of_scope before a document was born), so there is no scene, no envelopes, "
                "and no assets to show"
            )
            if from_leg
            else "this run names no document — nothing to show for scene/envelopes/assets"
        )
        return None

    columns = (
        "SELECT id, workspace_id, title, doc_kind::text AS doc_kind, current_scene_json,"
        " current_version, effective_brand_kit_id, effective_brand_kit_version, created_at,"
        " updated_at FROM design_document"
    )
    if workspace_id is not None:
        rows = await conn.fetch(
            columns + " WHERE id = $1 AND workspace_id = $2", document_id, workspace_id
        )
    else:
        # Document ids are workspace-local (PK is `(id, workspace_id)`), so a bare doc ref can in
        # principle match more than one workspace. Say so rather than picking silently.
        rows = await conn.fetch(columns + " WHERE id = $1 ORDER BY created_at", document_id)
    if not rows:
        if ref == document_id:
            raise RunViewNotFound(f"no design_document matches ref {ref!r}")
        gaps.append(
            f"design_document {document_id} is gone — the run/leg still names it, but the row "
            "is not in this database"
        )
        return None
    if len(rows) > 1:
        gaps.append(
            f"document id {document_id} exists in {len(rows)} workspaces (doc ids are "
            "workspace-local); showing the oldest — pass a run or leg ref to disambiguate"
        )
    return _row(rows[0])


_LEG_SELECT = (
    "SELECT id, workspace_id, thread_id, state, bundle_artifact_ref, document_id,"
    " document_version_guard, brand_kit_id, brand_kit_version, close_reason, closed_by_run_id,"
    " created_at, updated_at FROM design_leg"
)


async def _load_leg(
    conn: asyncpg.Connection,
    run_row: dict | None,
    workspace_id: str | None,
    document_id: str | None,
    gaps: list[str],
) -> dict | None:
    if run_row is not None and run_row.get("leg_id") is not None:
        # `_stamp` already stringified the uuid for the manifest; the column still wants a UUID.
        found = _row(
            await conn.fetchrow(_LEG_SELECT + " WHERE id = $1", _uuid.UUID(str(run_row["leg_id"])))
        )
        if found is not None:
            return found
    if document_id is None or workspace_id is None:
        return None
    found = _row(
        await conn.fetchrow(
            _LEG_SELECT + " WHERE document_id = $1 AND workspace_id = $2"
            " ORDER BY created_at DESC LIMIT 1",
            document_id,
            workspace_id,
        )
    )
    if found is not None:
        # A document accumulates legs across turns, so the newest is a GUESS, not this run's own
        # leg. Say so — otherwise the view silently presents another turn's frozen bundle as the
        # context this run actually ran against, which is worse than showing no bundle at all.
        gaps.append(
            f"leg {found['id']} resolved by document recency, not by the run's own leg_id — its "
            "frozen context bundle may belong to a DIFFERENT turn on this document"
        )
    return found


# --- the three homes --------------------------------------------------------------------------


def _load_bundle(leg_row: dict | None, storage_fs_root: Path, gaps: list[str]) -> dict | None:
    """The frozen context bundle. ``bundle_artifact_ref`` is a FULL storage key
    (``{workspace_id}/{digest}`` — verified live), so it is joined onto the root verbatim."""
    if leg_row is None:
        return None
    ref = leg_row.get("bundle_artifact_ref")
    if not ref:
        gaps.append(
            "design_leg.bundle_artifact_ref is NULL — the leg froze no context bundle "
            "(it may have been opened but never run)"
        )
        return None
    # A key is DATA (it reaches the filesystem), so an absolute or `..`-bearing ref is refused
    # rather than joined — the same posture as `clue_storage.fs.FsStorage._path`. This view is
    # read-only, so the blast radius is reading a file outside the store, not writing one.
    pure = PurePosixPath(str(ref))
    if pure.is_absolute() or ".." in pure.parts:
        gaps.append(
            f"design_leg.bundle_artifact_ref {ref!r} escapes the storage root (absolute or "
            "'..'-bearing key) — refused unread"
        )
        return None
    path = storage_fs_root.joinpath(*pure.parts)
    if not path.is_file():
        gaps.append(
            f"bundle blob not on this machine's storage root ({path}) — durable blobs live "
            "wherever that deployment's storage backend put them, so a bundle written by "
            "another machine, backend, or a since-purged artifact is simply unreadable here"
        )
        return None
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError) as error:
        gaps.append(f"bundle blob at {path} is unreadable as JSON ({error})")
        return None


async def _load_envelopes(
    conn: asyncpg.Connection, workspace_id: str | None, document_id: str | None, gaps: list[str]
) -> list[dict]:
    if document_id is None or workspace_id is None:
        return []
    rows = await conn.fetch(
        "SELECT id, batch_id, seq, envelope_version, base_revision, actor_kind, actor_id,"
        " source::text AS source, intent, checkpoint_label, touched_targets_json,"
        " operations_json, reverts_batch_id, reapplies_batch_id, created_at"
        " FROM design_edit_envelope WHERE document_id = $1 AND workspace_id = $2 ORDER BY seq",
        document_id,
        workspace_id,
    )
    if not rows:
        gaps.append(
            "no design_edit_envelope rows for this document — no edit has been committed "
            "through the envelope path (a scene can still exist from its birth write)"
        )
    return [_row(r, "touched_targets_json", "operations_json") for r in rows]


async def _load_events(
    conn: asyncpg.Connection, run_id: str | None, gaps: list[str]
) -> list[dict]:
    if run_id is None:
        # Never silently empty: the stream is keyed by design run id, so a document- or
        # leg-shaped ref has nothing to join on even when runs exist for that document.
        gaps.append(
            "no events — the run_event stream is keyed by design run id and this ref names no "
            "run; re-run the view with a run_… ref to see the turn's event trail"
        )
        return []
    rows = await conn.fetch(
        "SELECT seq, workspace_id, topic, subject_kind, subject_id, payload, created_at"
        " FROM run_event WHERE subject_kind = 'design_run' AND subject_id = $1 ORDER BY seq",
        run_id,
    )
    if not rows:
        gaps.append(
            f"no run_event rows for run {run_id} — the stream is retained per deployment and "
            "a design run that never emitted (or whose rows were pruned) has none"
        )
    return [_row(r, "payload") for r in rows]


async def _load_assets(
    conn: asyncpg.Connection,
    scene: dict | None,
    workspace_id: str | None,
    asset_store_root: Path,
    storage_fs_root: Path,
    gaps: list[str],
) -> list[AssetView]:
    records = (scene or {}).get("assets") or {}
    if not isinstance(records, dict):
        # Corrupt is not the same fact as empty, and a scene whose asset table is the wrong
        # SHAPE is precisely the sort of thing this view exists to make visible.
        gaps.append(
            f"scene['assets'] is a {type(records).__name__}, not an object — the asset table is "
            "malformed, so no asset states could be resolved (this is corrupt, not empty)"
        )
        return []
    if not records:
        return []

    digests: list[str] = []
    for record in records.values():
        digest = _asset_digest(record)
        if digest:
            digests.append(digest)
    live = await _live_durable_rows(conn, digests)

    assets: list[AssetView] = []
    for asset_id, record in records.items():
        record = record if isinstance(record, dict) else {}
        media = record.get("media") or {}
        digest = _asset_digest(record)
        cache_path = durable_path = None
        if digest and workspace_id:
            candidate = asset_store_root / workspace_id / "sha256" / digest[:2] / digest
            cache_path = candidate if candidate.is_file() else None
            candidate = storage_fs_root / workspace_id / _DESIGN_KEY_SEGMENT / digest
            durable_path = candidate if candidate.is_file() else None
        assets.append(
            AssetView(
                asset_id=str(record.get("id") or asset_id),
                label=record.get("label"),
                digest=digest,
                media_type_hint=media.get("mime_type"),
                cache_path=cache_path,
                durable_path=durable_path,
                durable_row=bool(digest) and digest in live,
            )
        )

    undigested = sorted(a.asset_id for a in assets if not a.digest)
    if undigested:
        gaps.append(
            f"{len(undigested)} of {len(assets)} scene assets carry no content digest "
            f"({', '.join(undigested[:8])}) — nothing to look up in either byte home"
        )
    nowhere = sorted(
        a.asset_id
        for a in assets
        if a.digest and not (a.cache_path or a.durable_path or a.durable_row)
    )
    if nowhere:
        gaps.append(
            f"{len(nowhere)} of {len(assets)} scene assets have no bytes in either home and no "
            f"live artifact row ({', '.join(nowhere[:8])}) — the cache is a per-machine "
            "materialization and the durable blob may live on another deployment's storage "
            "backend, so absence here is not proof the bytes were never produced"
        )
    # The divergence worth surfacing loudest: the row promises bytes the route would serve, but
    # neither byte home on THIS machine has them.
    rowless_bytes = sorted(
        a.asset_id for a in assets if a.durable_row and not (a.cache_path or a.durable_path)
    )
    if rowless_bytes:
        gaps.append(
            f"{len(rowless_bytes)} scene assets have a LIVE artifact row but no bytes on this "
            f"machine ({', '.join(rowless_bytes[:8])}) — the row may be another workspace's "
            "(the /asset-store predicate is workspace-unscoped) or its blob may sit on another "
            "deployment's storage backend"
        )
    return assets


def _asset_digest(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    digest = ((record.get("media") or {}).get("digest") or {}).get("value")
    return str(digest) if digest else None


async def _live_durable_rows(conn: asyncpg.Connection, digests: list[str]) -> set[str]:
    """The `/asset-store` route's row predicate, re-derived read-only.

    Mirrors ``clue_design.storage.read_public_design_blob``: any LIVE row (``erased_at``/
    ``purged_at`` both NULL) in the ``design`` namespace holding this content hash. Deliberately
    workspace-UNSCOPED, exactly like the route (ruling R-D4-7) — this answers "would
    ``/asset-store/{digest}`` find a row?", which is the fact the view reports.
    """
    if not digests:
        return set()
    rows = await conn.fetch(
        "SELECT DISTINCT content_sha256 FROM artifact"
        " WHERE content_sha256 = ANY($1::text[])"
        " AND split_part(storage_key, '/', 2) = $2"
        " AND erased_at IS NULL AND purged_at IS NULL",
        digests,
        _DESIGN_KEY_SEGMENT,
    )
    return {str(r["content_sha256"]) for r in rows}
