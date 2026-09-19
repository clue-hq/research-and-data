"""Runtime access to the curated font library (Track B).

The manifest (`apps/api/font-library/manifest.json`, generated + checked in by
`scripts/provision_font_library.py`) is the single source of truth: curated
families with per-weight static faces already materialized into the
content-addressed asset store, measured metrics, license, and agent-facing
tone/pairing notes.

Two consumers live here:

* `library_font_spec()` — the `{store_root, faces:[{digest, family}]}` spec
  the Rust helper understands. CoreClient injects it into every shaping
  request (preflight / export / layout geometry); the HELPER then lazy-loads
  only the faces whose family the scene or kit actually mentions, so passing
  the full library is cheap (digests only, no byte reads here).
* `manifest()` — served verbatim at `GET /font-library` for the editor
  (scene-driven face loading) and the agent teaching surface.

A missing or unreadable manifest disables the library (spec `None`) — the
pre-library behavior, never an error: environments that have not run the
provisioning script must keep working on bundled Inter alone.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from py_lumen_config import settings
from py_lumen_obs import get_logger

from clue_storage import StorageBackend

JsonObject = Dict[str, Any]
logger = get_logger("lumen_api.font_library")

_cache: dict = {"path": None, "mtime": None, "manifest": None}


def manifest_path() -> Path:
    return Path(settings.lumen_font_library_manifest_path)


def manifest() -> Optional[JsonObject]:
    """The parsed manifest, cached by (path, mtime) so re-provisioning is
    picked up without a server restart."""
    path = manifest_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    if _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["manifest"]
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        # A present-but-broken manifest is a provisioning bug — say so once
        # rather than silently running library-less.
        logger.warning(
            "font_library_manifest_unreadable", path=str(path), error=str(error)
        )
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("families"), list):
        logger.warning("font_library_manifest_no_families", path=str(path))
        return None
    _cache.update(path=path, mtime=mtime, manifest=parsed)
    return parsed


_spec_cache: dict = {"key": None, "spec": None}


def library_workspace_id() -> str:
    """The tenant whose durable storage holds the curated font faces (D4).

    The font library is deliberately ONE shared set, not per-tenant data: it is curated,
    openly-licensed Google Fonts, provisioned once per environment by
    ``scripts/provision_font_library.py`` against a single checked-in manifest. Its faces
    therefore live in one workspace's storage and are materialized into that workspace's engine
    cache; the spec's ``store_root`` points there, independently of whichever tenant's scene is
    being shaped (the helper takes library faces and scene assets from separate roots).

    RESIDUAL for the D4 close-out: this reads the dev-workspace env var, which is right for a
    single-environment deployment and for tests (each test gets its own workspace, so each test
    provisions and reads its own copy) but is not a real "platform-shared blob" model. Part IV
    (auth/tenancy) owns deciding whether the library gets a first-class shared namespace.
    """
    from .design_store import default_workspace_id

    return default_workspace_id()


def shared_library_font_bytes(
    asset_id: str, storage: StorageBackend
) -> tuple[str, bytes] | None:
    """Read only a manifest-listed, digest-verified face from the shared library.

    Library faces are provisioned once per environment. The editor's tenant-scoped asset
    route may use this fallback when its own registry has no record, but a font-looking id
    never grants access to an arbitrary asset or another tenant's storage.
    """
    from .asset_custody import location_digest, read_asset_bytes
    from .database import NotFoundError
    from .design_store import DesignBlobStore, HybridRepository

    parsed = manifest()
    if parsed is None:
        return None
    digest = next(
        (
            face.get("digest")
            for family in parsed["families"]
            if isinstance(family, dict)
            for face in family.get("faces") or []
            if isinstance(face, dict) and face.get("asset_id") == asset_id
        ),
        None,
    )
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return None

    workspace_id = library_workspace_id()
    repo = HybridRepository(workspace_id, ensure_workspace=False)
    try:
        record = repo.require_asset_record(asset_id)["asset"]
    except NotFoundError:
        return None
    media = record.get("media") or {}
    if (
        record.get("kind") != "font"
        or media.get("mime_type") != "font/ttf"
        or (media.get("digest") or {}).get("value") != digest
        or location_digest(media.get("location")) != digest
    ):
        return None
    blobs = DesignBlobStore(storage, workspace_id, ensure_workspace=False)
    data = read_asset_bytes(blobs, digest)
    if data is None or hashlib.sha256(data).hexdigest() != digest:
        return None
    return "font/ttf", data


def library_font_spec() -> Optional[JsonObject]:
    """The library as a helper font spec, or None when the library is absent.

    D4: the faces live in platform storage; this materializes each one into the LIBRARY
    workspace's engine cache (see :func:`library_workspace_id`) and points ``store_root`` there.
    Injected centrally at the ``CoreClient`` gateway, which has no request to take a tenant
    from — hence the library workspace rather than the caller's.

    Only faces whose bytes are durably present are promised: the manifest is
    checked in, but the blobs are provisioned per environment, so an
    unprovisioned store must degrade to
    the pre-library behavior rather than spray LUMS0101 warnings for families
    the design never asked for. A scene that genuinely uses an unprovisioned
    family still fails loudly — the family is unknown to the FontManager and
    raster export reports the LUMS0100 fallback. LUMS0101 stays reserved for
    bytes that vanish between this check and the helper read."""
    from clue_storage import storage_from_settings

    from .design_store import DesignBlobStore

    parsed = manifest()
    if parsed is None:
        return None
    workspace_id = library_workspace_id()
    store_root = Path(settings.effective_asset_store_root) / workspace_id
    cache_key = (id(parsed), str(store_root))
    if _spec_cache["key"] == cache_key:
        return _spec_cache["spec"]
    blobs = DesignBlobStore(storage_from_settings(), workspace_id)
    faces = []
    missing: list[str] = []
    for family in parsed["families"]:
        if not isinstance(family, dict):
            continue
        for face in family.get("faces") or []:
            if not (isinstance(face, dict) and face.get("digest")):
                continue
            digest = str(face["digest"])
            if _materialize_face(blobs, store_root, digest):
                spec_face: JsonObject = {
                    "digest": digest,
                    "family": family.get("family"),
                }
                # Manifest faces always carry a per-face weight/style; forward
                # them (validated) so the helper / web @font-face render each
                # face at its true weight instead of collapsing to 400/normal.
                weight = face.get("weight")
                if isinstance(weight, int) and not isinstance(weight, bool) and 1 <= weight <= 1000:
                    spec_face["weight"] = weight
                style = face.get("style")
                if style in ("normal", "italic"):
                    spec_face["style"] = style
                faces.append(spec_face)
            else:
                missing.append(str(family.get("family")))
    if missing:
        logger.warning(
            "font_library_partially_provisioned",
            store_root=str(store_root),
            missing_face_count=len(missing),
            missing_families=sorted(set(missing)),
            remedy="run scripts/provision_font_library.py",
        )
    spec = (
        {"store_root": str(store_root), "faces": faces} if faces else None
    )
    _spec_cache.update(key=cache_key, spec=spec)
    return spec


def _materialize_face(blobs: Any, store_root: Path, digest: str) -> bool:
    """Whether the engine can read this face, materializing it from durable storage on a miss.

    Fail-soft: a digest the environment never provisioned is simply absent, which is exactly the
    "unprovisioned library" degradation this module has always promised.
    """
    from .asset_custody import cache_blob_path, read_asset_bytes, write_cache_blob

    if cache_blob_path(store_root, digest).is_file():
        return True
    data = read_asset_bytes(blobs, digest)
    if data is None:
        return False
    write_cache_blob(store_root, digest, data)
    return True
