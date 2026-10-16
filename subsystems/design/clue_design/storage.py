"""Design byte storage on the platform substrate (Part II slice D4) — the ONE design write path.

Design *metadata* moved to Postgres in D1–D3; this module moves design *bytes* off the
API-local ``asset-store/`` tree and onto :mod:`clue_storage` (fs/S3 behind
``StorageBackend``), with an ``artifact`` row per blob.

**The key namespace (ruling R-D4-2): ``{workspace_id}/design/{sha256}`` — never bare
``{workspace_id}/{sha256}``.** The bare shape is the *claim-evidence* namespace
(:func:`clue_storage.protocol.artifact_key`), and the platform's DSAR erasure decides whether an
evidence blob may be destroyed by counting the live **claims** that cite its key
(``clue_storage.artifacts.live_claim_count`` → ``erase_if_unreferenced``). A design blob is
cited by design rows, never by claims, so under the bare shape a design blob that happened to
share bytes with an evidence snapshot — or simply any design key handed to the sweep — would
count *zero* citers and be purged out from under the design subsystem. The ``design`` segment
makes the two namespaces **structurally disjoint**, so no claim-refcount decision can ever reach
design bytes. (The DB's ``artifact_key_encodes_scope`` CHECK admits exactly these two shapes.)

**One namespace, not three (ruling R-D4-3).** Component sources/bundles/css/first-frames and
publish delivery assets all land here; the content address *is* the identity, so the old
``custom-components/`` and ``publish/`` sub-trees (and the publish ``{digest}.meta.json``
sidecar, whose only payload was the media type) are gone — ``media_type`` lives on the
``artifact`` row. ``source_key`` on the row records which producer wrote the blob
(``design_custom_component`` / ``design_publish_asset``) and is observability, not identity.

**Row before blob.** :func:`register_design_bytes` records the ``artifact`` row *first* and puts
the blob only if absent — the same ordering (and for the same reason) as
:func:`clue_storage.snapshot.flush_snapshots`: the row's lock is what serializes a writer against
a concurrent erasure/purge, and recording resurrects a row a prior purge erased. Callers own the
transaction (the O5 rule — one logical operation, one transaction); nothing here commits.

Reads are **fail-closed** like the rest of the DAL: an absent digest, a digest belonging to
another workspace, an erased/purged row, and missing bytes all raise the same
:class:`~clue_design.errors.DesignNotFoundError`, so existence never leaks across tenants.
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design.errors import DesignNotFoundError
from clue_storage.artifacts import get_artifact, mark_erased, record_artifact
from clue_storage.protocol import StorageBackend, StorageError, content_address

#: The namespace segment that keeps design keys disjoint from claim-evidence keys (R-D4-2).
DESIGN_KEY_SEGMENT = "design"

#: ``source_key`` vocabulary for the ``artifact`` rows this seam writes (observability only).
SOURCE_KEY_CUSTOM_COMPONENT = "design_custom_component"
SOURCE_KEY_PUBLISH_ASSET = "design_publish_asset"
#: D4 Round B — the MAIN asset store's producers.
SOURCE_KEY_ASSET = "design_asset"  # registered library assets, incl. their thumbnails
SOURCE_KEY_ENGINE_ARTIFACT = "design_engine_artifact"  # derive/export artifacts, ref previews
SOURCE_KEY_FONT = "design_font"  # font-library faces
SOURCE_KEY_INGEST_STAGING = "design_ingest_staging"  # uploaded bytes awaiting an ingestion job
#: Clone-fidelity F0.1 — one website capture's own bytes: post-JS HTML, each fetched stylesheet,
#: and the full-page screenshot. Cited by ``design_site_snapshot`` rows, never by an asset record:
#: these are the SOURCE a later clone tier reads, not library media a document places.
SOURCE_KEY_SITE_SNAPSHOT = "design_site_snapshot"
#: Clone-fidelity F1.2 — one cloned section's immutable artifact: the canonical JSON payload
#: (sanitized html, scoped css, asset digests, slot manifest, preview digest) and the preview
#: image itself. Cited by ``design_web_fragment`` rows. Distinct from the snapshot key because a
#: snapshot is what a site LOOKED like and a fragment is what we now hold and will render.
SOURCE_KEY_WEB_FRAGMENT = "design_web_fragment"
#: Lane B (Contract 4) — an agent-written Puck section's source, compiled module and CSS, cited by
#: ``design_site_section`` rows. NEVER public: :func:`read_public_design_blob` skips this key, so
#: ``/asset-store/{digest}`` and the page origin cannot serve agent code. The editor gets a module
#: through a short-lived signed link; the renderer reads it with the workspace-scoped read.
SOURCE_KEY_SITE_SECTION = "design_site_section"

#: The ``media.location.provider`` label a D4 asset record carries (ruling R-D4-4). The bytes it
#: names live in platform storage under :func:`design_storage_key`, never on a local disk.
DESIGN_LOCATION_PROVIDER = "clue-storage"
#: Labels minted before D4 (``local-store``: the API-local content-addressed tree) and by the
#: engine's own fixtures (``opaque_asset_store``). Readers dual-accept them forever: an asset
#: record is durable JSON on scenes and registry rows that nothing rewrites in place.
LEGACY_LOCATION_PROVIDERS = frozenset({"local-store", "opaque_asset_store"})
#: Every provider label that means "these bytes are ours, resolvable by digest".
STORED_LOCATION_PROVIDERS = frozenset({DESIGN_LOCATION_PROVIDER}) | LEGACY_LOCATION_PROVIDERS

_SHA256_SHAPE = re.compile(r"^[0-9a-f]{64}$")

#: How many workspaces' rows the unscoped public read will try before giving up. Identical
#: design bytes held by many tenants is normal (a shared stock image, a shared font face); a
#: bound keeps one pathological digest from turning a 404 into a full-table scan.
_PUBLIC_READ_CANDIDATES = 50


def location_digest(location: object) -> str | None:
    """The sha256 a ``media.location`` block names, or ``None`` when it names none.

    **Resolve by digest, never by path.** Three ref shapes exist in the wild — the engine's
    ``sha256/{ab}/{digest}``, D4's ``{workspace}/design/{digest}``, and a bare digest — and the
    only thing they agree on is the trailing segment. Taking that segment (and gating it on the
    sha256 shape) is what lets one reader serve records written before, during, and after the
    D4 move without ever interpreting a stored ref as a filesystem path.
    """
    if not isinstance(location, dict):
        return None
    if location.get("provider") not in STORED_LOCATION_PROVIDERS:
        return None
    ref = location.get("opaque_ref")
    if not isinstance(ref, str) or not ref:
        return None
    tail = ref.rsplit("/", 1)[-1]
    return tail if _SHA256_SHAPE.fullmatch(tail) else None


def design_location(storage_key: str) -> dict[str, object]:
    """The ``media.location`` block for a blob now living in platform storage (R-D4-4)."""
    return {
        "provider": DESIGN_LOCATION_PROVIDER,
        "opaque_ref": storage_key,
        "url": None,
    }


def design_storage_key(workspace_id: str, sha256: str) -> str:
    """The storage key for one design blob: ``{workspace_id}/design/{sha256}``.

    Validated rather than trusted — a key is *data* (it can reach the filesystem/S3 backend), so
    a malformed digest or an empty workspace is refused here instead of minting a key that
    escapes the namespace. Deterministic from ``(workspace, bytes)`` alone, which is what lets a
    caller stamp the key onto a design row before any I/O.
    """
    if not workspace_id or "/" in workspace_id:
        raise ValueError(f"invalid design storage workspace {workspace_id!r}")
    if not _SHA256_SHAPE.fullmatch(sha256):
        raise ValueError(f"invalid design storage digest {sha256!r}")
    return f"{workspace_id}/{DESIGN_KEY_SEGMENT}/{sha256}"


async def register_design_bytes(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    data: bytes,
    media_type: str,
    source_key: str,
) -> str:
    """Durably store one design blob and return its storage key. **The only write path.**

    Row before blob (see the module docstring): the ``artifact`` upsert takes the row lock and
    clears any stale erasure state, and only then is the blob put — skipped when it already
    exists, which is the common case since the key is content-addressed. Registering identical
    bytes again is therefore idempotent end to end: one row, one blob, the same key.
    """
    digest = content_address(data)
    storage_key = design_storage_key(workspace_id, digest)
    await record_artifact(
        conn,
        storage_key=storage_key,
        workspace_id=workspace_id,
        content_sha256=digest,
        media_type=media_type,
        size_bytes=len(data),
        source_key=source_key,
    )
    if not await storage.exists(storage_key):
        await storage.put(storage_key, data, media_type=media_type)
    return storage_key


async def read_design_blob(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    sha256: str,
) -> tuple[str, bytes]:
    """Read one design blob **by digest** as ``(media_type, data)``, gated on a live ``artifact``
    row in this workspace.

    Resolving by digest (not by a stored path) is deliberate: the key is derived here from
    ``(workspace, digest)``, so a legacy ``opaque_ref`` recorded by the API-local store era is
    never interpreted as a path, and a caller cannot smuggle a key of its own choosing.

    The row's ``media_type`` comes back with the bytes because it is the metadata that replaced
    the publish store's ``{digest}.meta.json`` sidecar (R-D4-3) — a caller that needs both must
    not have to make two round trips (and, across the D4 sync bridge, two transactions) for one
    logical read.

    Raises :class:`DesignNotFoundError` — the same refusal for a digest that does not exist, one
    that belongs to another workspace, one whose row a DSAR purge erased, and one whose bytes are
    missing from the backend.
    """
    storage_key = design_storage_key(workspace_id, sha256)
    record = await get_artifact(conn, storage_key)
    if record is None or record.erased_at is not None or record.purged_at is not None:
        raise DesignNotFoundError("design_blob", sha256)
    try:
        data = await storage.get(storage_key)
    except StorageError as error:
        raise DesignNotFoundError("design_blob", sha256) from error
    return record.media_type, data


async def read_design_bytes(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    sha256: str,
) -> bytes:
    """The bytes alone — :func:`read_design_blob` for callers that carry their own media type."""
    _media_type, data = await read_design_blob(
        conn, storage, workspace_id=workspace_id, sha256=sha256
    )
    return data


async def read_public_design_blob(
    conn: AsyncConnection, storage: StorageBackend, *, sha256: str
) -> tuple[str, bytes]:
    """Read one design blob by digest **without a workspace** — the ``GET /asset-store/{digest}``
    backing read (ruling R-D4-7).

    **Deliberately workspace-UNSCOPED, and this is the one read that is.** The route it serves is
    O4-exempt by an earlier ruling: a published page's ``<img>``/``@font-face`` fetches and the
    editor's origin-``null`` srcdoc preview iframe cannot send ``X-Workspace-Id`` (a custom
    header there turns the request into a preflight the wildcard CORS response cannot satisfy).
    Before D4 the route served a single global content-addressed tree, so preserving today's
    behaviour means resolving the digest across every tenant's rows rather than none. Content
    addressing is not authorization — an unguessable sha256 is the only gate, exactly as before
    — and the Part-IV custody decision (which the route's own comment records) owns tightening
    it.

    Scoped to the ``design`` namespace so a claim-evidence snapshot (whose keys are
    ``{workspace}/{digest}``) can never be served here, and to LIVE rows so a purged blob 404s.
    The candidate order is deterministic (oldest row, then key) so repeated requests cannot flap
    between two rows' media types — but a candidate whose bytes the backend cannot produce is
    SKIPPED rather than fatal: the rows are only metadata, and refusing to serve bytes that
    demonstrably exist because some other tenant's row happens to be older would be a 404 the
    caller can neither explain nor fix. The scan is bounded; identical bytes held by more
    workspaces than that are still served from the first live one. It never serves an
    agent-written section's bytes (``SOURCE_KEY_SITE_SECTION``, Contract 4).
    """
    if not _SHA256_SHAPE.fullmatch(sha256):
        raise DesignNotFoundError("design_blob", sha256)
    result = await conn.execute(
        text(
            "SELECT storage_key, media_type FROM artifact "
            "WHERE content_sha256 = :sha AND split_part(storage_key, '/', 2) = :segment "
            "AND erased_at IS NULL AND purged_at IS NULL "
            "AND source_key IS DISTINCT FROM :site_section "
            "ORDER BY created_at, storage_key LIMIT :limit"
        ),
        {
            "sha": sha256,
            "segment": DESIGN_KEY_SEGMENT,
            "site_section": SOURCE_KEY_SITE_SECTION,
            "limit": _PUBLIC_READ_CANDIDATES,
        },
    )
    for row in result.mappings().all():
        try:
            data = await storage.get(str(row["storage_key"]))
        except StorageError:
            continue
        return str(row["media_type"]), data
    raise DesignNotFoundError("design_blob", sha256)


async def delete_design_bytes(
    conn: AsyncConnection, storage: StorageBackend, *, workspace_id: str, sha256: str
) -> bool:
    """Destroy one design blob and tombstone its ``artifact`` row. Returns whether it was live.

    The design counterpart of ``clue_storage.artifacts.erase_if_unreferenced`` +
    ``purge_erased_artifacts``, minus the claim refcount: **no claim ever cites a design key**
    (that is precisely what the ``design`` namespace segment guarantees — R-D4-2), so the
    refcount guard those helpers exist to arbitrate is vacuous here. The caller owns the real
    reference decision instead (the asset hard-delete GC refuses while any asset record or
    document scene still names the digest).

    Two accepted residuals, both bounded and both the *safe* direction:

    * The blob delete happens inside the caller's transaction rather than after it commits (the
      O5 bridge is one transaction per call). A rollback after the delete would leave a row
      claiming a blob that is gone — a dangling reference, never a live row citing destroyed
      evidence, and the next register re-puts the bytes.
    * A concurrent :func:`register_design_bytes` of the same content resurrects the row
      (``record_artifact`` clears erasure state by design). The bytes come back with it, so the
      outcome is "the blob survived", not a row/blob split.
    """
    storage_key = design_storage_key(workspace_id, sha256)
    record = await get_artifact(conn, storage_key)
    if record is None or record.erased_at is not None or record.purged_at is not None:
        return False
    await mark_erased(conn, storage_key)
    await storage.delete(storage_key)
    await conn.execute(
        text("UPDATE artifact SET purged_at = now() WHERE storage_key = :storage_key"),
        {"storage_key": storage_key},
    )
    return True


async def design_bytes_exist(conn: AsyncConnection, *, workspace_id: str, sha256: str) -> bool:
    """Whether this workspace holds a live ``artifact`` row for ``sha256`` (no blob I/O).

    The row is the durable record of the blob's existence, so this is the cheap probe; a caller
    that needs the bytes themselves (and the backend's word for it) calls
    :func:`read_design_bytes`.
    """
    record = await get_artifact(conn, design_storage_key(workspace_id, sha256))
    return record is not None and record.erased_at is None and record.purged_at is None
