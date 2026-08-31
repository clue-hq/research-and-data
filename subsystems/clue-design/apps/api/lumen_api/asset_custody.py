"""Asset custody across the Python/Rust seam (Part II D4 Round B, ruling R-D4-1).

**Platform storage is the durable home of every design asset byte.** The Rust engine cannot
talk to ``clue_storage`` — it reads and writes a plain content-addressed tree — so it keeps a
*transient, per-workspace materialization cache* at
``{cache_root}/{workspace_id}/sha256/{ab}/{digest}``: the engine's own layout, byte-for-byte
unchanged (``store_resolver.rs``/``digest_relative_path``), simply rooted below a workspace
directory. Nothing durable lives there. Wiping the whole tree must lose nothing, which this
module is what enforces, in two directions:

* **write-back** — after any engine call that put bytes into the cache, :func:`register_engine_write`
  reads them straight back out and registers them durably through
  :class:`~lumen_api.design_store.DesignBlobStore`, then re-points the asset record's
  ``media.location`` (and its thumbnail's) at the storage key (ruling R-D4-4);
* **read-through** — before any engine call that will *read* bytes it did not just write,
  :func:`ensure_materialized` pulls each referenced digest out of platform storage and lands it
  in the cache.

Two rules keep the pair honest. First, **resolve by digest, never by path**: a stored
``opaque_ref`` is one of three historical shapes and is never interpreted as a filesystem path
(``clue_design.storage.location_digest``). Second, **materialization is fail-soft while
registration is not**: a digest that is durably absent is skipped here so the caller degrades
exactly as it did when the blob was missing from the local tree (a skipped font face, a warned
image), whereas a failed register is a real custody failure and propagates.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from clue_storage import StorageError
from py_lumen_obs import get_logger

from clue_design.storage import (
    SOURCE_KEY_ASSET,
    SOURCE_KEY_ENGINE_ARTIFACT,
    design_location,
    location_digest,
)

from .database import NotFoundError
from .design_store import CustodyState, DesignBlobStore
from .observability import log_event

JsonObject = Dict[str, Any]

_logger = get_logger("lumen_api.asset_custody")

__all__ = [
    "SOURCE_KEY_ASSET",
    "SOURCE_KEY_ENGINE_ARTIFACT",
    "cache_blob_path",
    "cache_relative_path",
    "ensure_materialized",
    "read_asset_bytes",
    "record_digests",
    "register_engine_write",
    "register_scene_asset_backstop",
    "register_web_asset_backstop",
    "scene_asset_digests",
    "write_cache_blob",
]

_OCTET_STREAM = "application/octet-stream"


# --------------------------------------------------------------------------------------------
# The engine's cache layout (fixed contract — mirrors crates/.../digest_relative_path)
# --------------------------------------------------------------------------------------------


def cache_relative_path(digest: str) -> str:
    """``sha256/{ab}/{digest}`` — the engine's relative blob path. Do not "improve" this."""
    return f"sha256/{digest[:2]}/{digest}"


def cache_blob_path(cache_dir: str | Path, digest: str) -> Path:
    """Where the engine expects one digest's bytes inside a workspace's cache dir."""
    return Path(cache_dir) / cache_relative_path(digest)


def write_cache_blob(cache_dir: str | Path, digest: str, data: bytes) -> Path:
    """Materialize one blob into the cache atomically.

    Atomic because a content-addressed path must never be observable half-written: a crash
    mid-write would park corrupt bytes at a *valid* digest path, and every later reader would
    trust them. Write a tmp sibling, ``os.replace`` into place (atomic on POSIX).
    """
    path = cache_blob_path(cache_dir, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{digest}.tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


def read_asset_bytes(blobs: DesignBlobStore, digest: Optional[str]) -> Optional[bytes]:
    """One asset's durable bytes by digest, or ``None`` when there are none.

    The PURE-PYTHON read shape: no engine-cache round trip (materializing bytes no engine call
    will read is pure waste), and the DAL's fail-closed refusal — absent, erased, or another
    tenant's — collapses to the single ``None`` every caller already renders as a 404 or a
    skipped-with-a-warning.
    """
    if not digest:
        return None
    try:
        return blobs.read(digest)
    except NotFoundError:
        return None


# --------------------------------------------------------------------------------------------
# Digest extraction
# --------------------------------------------------------------------------------------------


def record_digests(record: Optional[JsonObject]) -> List[Tuple[str, str]]:
    """``[(digest, media_type)]`` for an engine asset record's own bytes and its thumbnail.

    The primary digest comes from ``media.digest.value`` (the record's byte identity); the
    thumbnail's from its ``location``, because a thumbnail carries no digest block of its own.
    Order is stable (bytes first) and duplicates are dropped — a record whose thumbnail IS the
    asset (an already-small raster) must not register twice.
    """
    if not isinstance(record, dict):
        return []
    media = record.get("media") or {}
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()

    digest = ((media.get("digest") or {}).get("value")) if isinstance(media, dict) else None
    if isinstance(digest, str) and digest:
        out.append((digest, str(media.get("mime_type") or _OCTET_STREAM)))
        seen.add(digest)

    thumbnail = (media.get("thumbnail") or {}) if isinstance(media, dict) else {}
    thumb_digest = location_digest(thumbnail.get("location"))
    if thumb_digest and thumb_digest not in seen:
        out.append((thumb_digest, str(thumbnail.get("mime_type") or _OCTET_STREAM)))
    return out


def scene_asset_digests(scene: Optional[JsonObject]) -> List[str]:
    """Every digest the scene's embedded asset records name (bytes + thumbnails).

    The scene's ``assets`` map is the engine's own by-value asset table — the same one
    ``clue_design.assets.register_scene_assets`` promotes into the registry — so it is the
    authoritative list of what a render/export/derive of this scene will try to read.
    """
    if not isinstance(scene, dict):
        return []
    assets = scene.get("assets")
    if not isinstance(assets, dict):
        return []
    digests: List[str] = []
    for record in assets.values():
        for digest, _media_type in record_digests(record if isinstance(record, dict) else None):
            if digest not in digests:
                digests.append(digest)
    return digests


# --------------------------------------------------------------------------------------------
# Write-back (cache -> durable storage)
# --------------------------------------------------------------------------------------------


def register_engine_write(
    blobs: DesignBlobStore,
    cache_dir: str | Path,
    *,
    source_key: str,
    record: Optional[JsonObject] = None,
    relative_paths: Optional[Iterable[Any]] = None,
) -> None:
    """Give durable custody to the bytes an engine call just wrote into ``cache_dir``.

    Exactly one of ``record`` / ``relative_paths`` is meaningful per call (passing both is
    allowed and simply does both):

    * ``record`` — an engine **asset record**. Its own bytes and its thumbnail are registered,
      and then ``media.location`` / ``media.thumbnail.location`` are re-pointed at the storage
      keys (ruling R-D4-4). The record is mutated **in place** on purpose: it is about to be
      persisted (registry row, scene ``assets`` table, API response), and a record that still
      advertises a cache path would send every later reader to a directory that may be wiped.
    * ``relative_paths`` — raw engine outputs (export/derive artifacts) named by their
      ``sha256/{ab}/{digest}`` relative path. Accepts either a plain path string or the engine's
      artifact dict (``{"relative_path": ..., "mime_type": ...}``), so a caller can hand over the
      artifact list verbatim rather than restating it.

    Registration is idempotent (content-addressed key, row-before-blob), so re-registering bytes
    another turn already stored is one cheap upsert and no put. A cache file that is simply
    absent is skipped: the engine reports its own failures through diagnostics, and this must
    not turn "the engine declined to write an artifact" into an exception.
    """
    if record is not None:
        _register_record(blobs, cache_dir, record, source_key=source_key)
    for entry in relative_paths or ():
        _register_relative(blobs, cache_dir, entry, source_key=source_key)


def _register_record(
    blobs: DesignBlobStore,
    cache_dir: str | Path,
    record: JsonObject,
    *,
    source_key: str,
) -> None:
    media = record.get("media")
    if not isinstance(media, dict):
        return
    keys: Dict[str, str] = {}
    for digest, media_type in record_digests(record):
        path = cache_blob_path(cache_dir, digest)
        if not path.is_file():
            continue
        keys[digest] = blobs.register(
            path.read_bytes(), media_type=media_type, source_key=source_key
        )

    primary = (media.get("digest") or {}).get("value")
    if isinstance(primary, str) and primary in keys:
        media["location"] = design_location(keys[primary])
    thumbnail = media.get("thumbnail")
    if isinstance(thumbnail, dict):
        thumb_digest = location_digest(thumbnail.get("location"))
        if thumb_digest and thumb_digest in keys:
            thumbnail["location"] = design_location(keys[thumb_digest])


def _register_relative(
    blobs: DesignBlobStore,
    cache_dir: str | Path,
    entry: Any,
    *,
    source_key: str,
) -> None:
    if isinstance(entry, Mapping):
        relative = entry.get("relative_path")
        media_type = str(entry.get("mime_type") or _OCTET_STREAM)
    else:
        relative = entry
        media_type = _OCTET_STREAM
    if not isinstance(relative, str) or not relative:
        return
    path = Path(cache_dir) / relative
    if not path.is_file():
        return
    blobs.register(path.read_bytes(), media_type=media_type, source_key=source_key)


def register_scene_asset_backstop(
    blobs: DesignBlobStore,
    cache_dir: str | Path,
    scene: Optional[JsonObject],
) -> List[str]:
    """The scene-persist BACKSTOP: durably store any scene asset byte that is not stored yet.

    An agent turn generates imagery mid-run through the engine; the accept seam — where the
    scene is persisted and its assets promoted into the registry — is the moment those bytes
    become the workspace's. Every producer already writes back at its own site, so this pass is
    normally all skips; it exists so a producer that is *not* on an API route (a runtime tool, a
    future engine surface) cannot leave a scene citing bytes that only ever lived in a wipeable
    cache. One pass, skip-if-already-durable, and the media type is taken from the record.

    **Durable means the bytes come back, not that a row says they should** (genad2 walk,
    2026-08-23). This pass used to skip on ``blobs.exists`` — a ROW probe, "no blob I/O". A row
    and its blob can diverge (a backend root that moved between the writing process and the
    serving one, a database restored without its object store, an out-of-band delete), and under
    a row-only probe that divergence is PERMANENT: the row keeps answering yes, every later
    persist skips the digest, and the asset 404s on ``/asset-store/{digest}`` forever — a canvas
    painting an empty box while every server-side export, which reads the engine cache directly,
    still renders it. Probing for retrievable bytes (:meth:`DesignBlobStore.custody_states`)
    is what makes this pass *healing*: any cache-resident asset whose custody is broken — this
    turn's or any earlier turn's, since the whole scene's asset table is walked every time — is
    re-registered, and ``register`` is content-addressed and row-before-blob, so the repair is
    one upsert plus the missing put and re-running it changes nothing.

    **A backstop that cannot repair must not destroy the write.** Repairing custody talks to the
    backend, and a backend that is *itself* sick (unreachable, misconfigured) fails that call.
    Which failures are allowed to kill the persist is decided by what the digest already had:

    * ``ROW_ONLY`` — a REPAIR. Before this pass probed bytes, a digest with a row was skipped
      without touching the backend at all, so letting a failed repair raise here would turn a
      backend outage into a failed accept on scenes that used to persist fine. Logged and
      skipped: the asset is exactly as broken as it was a moment ago, and the next persist
      tries again.
    * ``ABSENT`` — a FIRST registration, and the propagating behaviour is unchanged from before
      this pass probed bytes. It has to stay loud: a scene is about to be persisted citing bytes
      nothing durable holds, which is the very fabrication this backstop exists to prevent.

    Returns the digests it newly registered (empty in the common case).
    """
    registered: List[str] = []
    assets = (scene or {}).get("assets") if isinstance(scene, dict) else None
    if not isinstance(assets, dict):
        return registered

    # Cache probe FIRST, durability probe second — deliberately, and not just for speed. A
    # digest with no cache file cannot be rescued here whatever the durable answer is, and the
    # durability probe is a round trip through the O5 bridge (its own engine, connection and
    # transaction). Ordering it this way makes the common case — a scene naming assets that were
    # already durable and never materialized — cost no database work at all.
    pending: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for record in assets.values():
        if not isinstance(record, dict):
            continue
        for digest, media_type in record_digests(record):
            if digest in seen:
                continue
            seen.add(digest)
            if cache_blob_path(cache_dir, digest).is_file():
                pending.append((digest, media_type))
    if not pending:
        return registered

    # ONE bridged call for the whole scene, not one per digest: the bridge builds and disposes an
    # engine per call, so probing serially made a 50-asset scene pay 50 of them on a path that
    # runs on every editor operation.
    states = blobs.custody_states(digest for digest, _media_type in pending)
    for digest, media_type in pending:
        state = states.get(digest, CustodyState.ABSENT)
        if state is CustodyState.READABLE:
            continue
        try:
            blobs.register(
                cache_blob_path(cache_dir, digest).read_bytes(),
                media_type=media_type,
                source_key=SOURCE_KEY_ASSET,
            )
        except StorageError as error:
            if state is not CustodyState.ROW_ONLY:
                raise
            log_event(
                _logger,
                logging.WARNING,
                "design_asset.custody_repair_failed",
                digest=digest,
                error=str(error),
                error_type=type(error).__name__,
            )
            continue
        registered.append(digest)
    return registered


def register_web_asset_backstop(
    blobs: DesignBlobStore,
    cache_dir: str | Path,
    web_doc: Optional[JsonObject],
) -> List[str]:
    """The same backstop, on the WebDoc side of the house.

    A ``WebDoc``'s ``assets`` is the identical by-value ``AssetRecord`` table a
    scene carries (``crates/lumen-web/src/doc.rs``), so the walk, the cache
    probe, the one bridged custody call and the repair/raise split are all
    shared verbatim — only the seam that calls it differs.

    It exists because the web commit path had no equivalent of the scene accept
    seam's backstop, so bytes an agent tool ingested mid-turn (a fetched account
    logo) reached durability only by whatever the engine cache happened to keep.
    A cache is wipeable; a committed document citing wiped bytes renders an
    empty box forever.
    """
    return register_scene_asset_backstop(blobs, cache_dir, web_doc)


# --------------------------------------------------------------------------------------------
# Read-through (durable storage -> cache)
# --------------------------------------------------------------------------------------------


def ensure_materialized(
    blobs: DesignBlobStore,
    cache_dir: str | Path,
    digests: Iterable[Optional[str]],
) -> None:
    """Make sure the engine can find each digest in ``cache_dir`` before it reads them.

    Fail-SOFT by design: a digest with no durable bytes is left absent, so the engine reports
    exactly the miss it always reported (LUME0210 / a skipped face / a warned image) instead of
    the request dying on a custody detail. A digest already present is not re-fetched — the
    cache is content-addressed, so presence is proof.
    """
    for digest in dict.fromkeys(d for d in digests if d):
        assert digest is not None  # narrowed by the comprehension above
        if cache_blob_path(cache_dir, digest).is_file():
            continue
        try:
            data = blobs.read(digest)
        except Exception:
            continue
        write_cache_blob(cache_dir, digest, data)


def materialize_scene_assets(
    blobs: DesignBlobStore,
    cache_dir: str | Path,
    scenes: Sequence[Optional[JsonObject]],
) -> None:
    """:func:`ensure_materialized` over every asset digest one or more scenes reference."""
    digests: List[str] = []
    for scene in scenes:
        for digest in scene_asset_digests(scene):
            if digest not in digests:
                digests.append(digest)
    ensure_materialized(blobs, cache_dir, digests)
