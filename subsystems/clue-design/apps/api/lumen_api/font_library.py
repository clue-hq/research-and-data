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

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from py_lumen_config import settings

JsonObject = Dict[str, Any]
logger = logging.getLogger("lumen_api.font_library")

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
        logger.warning("font library manifest unreadable at %s: %s", path, error)
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("families"), list):
        logger.warning("font library manifest at %s has no families list", path)
        return None
    _cache.update(path=path, mtime=mtime, manifest=parsed)
    return parsed


_spec_cache: dict = {"key": None, "spec": None}


def library_font_spec() -> Optional[JsonObject]:
    """The library as a helper font spec, or None when the library is absent.
    The store root is environment-level (the library is not per-app-instance):
    LUMEN_ASSET_STORE_ROOT or asset-store beside the configured database.

    Only faces whose bytes EXIST in that store are promised: the manifest is
    checked in, but the blobs are materialized per environment, so an
    unprovisioned (or differently-rooted, e.g. test-tmp) store must degrade to
    the pre-library behavior rather than spray LUMS0101 warnings for families
    the design never asked for. A scene that genuinely uses an unprovisioned
    family still fails loudly — the family is unknown to the FontManager and
    raster export reports the LUMS0100 fallback. LUMS0101 stays reserved for
    bytes that vanish between this check and the helper read."""
    parsed = manifest()
    if parsed is None:
        return None
    store_root = Path(settings.effective_asset_store_root)
    cache_key = (id(parsed), str(store_root))
    if _spec_cache["key"] == cache_key:
        return _spec_cache["spec"]
    faces = []
    missing: list[str] = []
    for family in parsed["families"]:
        if not isinstance(family, dict):
            continue
        for face in family.get("faces") or []:
            if not (isinstance(face, dict) and face.get("digest")):
                continue
            digest = str(face["digest"])
            if (store_root / "sha256" / digest[:2] / digest).is_file():
                faces.append({"digest": digest, "family": family.get("family")})
            else:
                missing.append(str(family.get("family")))
    if missing:
        logger.warning(
            "font library partially provisioned at %s — %d face(s) missing "
            "(families: %s); run scripts/provision_font_library.py",
            store_root,
            len(missing),
            ", ".join(sorted(set(missing))),
        )
    spec = (
        {"store_root": str(store_root), "faces": faces} if faces else None
    )
    _spec_cache.update(key=cache_key, spec=spec)
    return spec
