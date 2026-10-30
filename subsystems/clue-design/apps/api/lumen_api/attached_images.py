"""Images sent in a chat thread become library images (spec 2026-10-30 §3.4).

The platform hands a leg turn the thread's files (duck-typed, the platform's ``AttachedFile``:
``filename``, ``media_type``, ``sha256``, ``data``, ``current``, ``viewable``, ``unavailable``).
Every image among them is registered in the workspace's image library through the same server-side
path a generated image takes (ingest, durable custody, ``design_register_asset_record``), so the
agent can crop it, place it and generate from it like any library image.

The library id is derived from the file's own sha256: a retried or taken-over turn registers the
same id again, and the library's upsert keeps one row. What is registered is the image the agent
may look at — the image itself, a PNG copy of a HEIC/AVIF/TIFF/BMP/ICO, or the SVG drawing; the
person's file in ``attachments/`` is never changed.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from py_lumen_obs import get_logger

__all__ = [
    "ATTACHED_IN_CHAT_TAG",
    "attached_asset_id",
    "attached_reference_ids",
    "register_attached_images",
]

logger = get_logger("lumen_api.attached_images")

ATTACHED_IN_CHAT_TAG = "attached-in-chat"


def attached_asset_id(sha256: str) -> str:
    """The library id of an attached image: one per file, whichever turn registers it."""

    return f"asset_att_{sha256[:32]}"


def register_attached_images(
    *,
    core: Any,
    blobs: Any,
    cache_dir: Any,
    invocations: Any,
    run_id: str,
    files: Sequence[Any],
) -> dict[str, str]:
    """Register every viewable attached image. Returns ``{original sha256: library asset_id}``.

    An image the engine refuses, or whose registration fails, is left out and logged: it is still
    a file in ``attachments/``, and a turn is never failed over it.
    """

    from clue_design.storage import SOURCE_KEY_ASSET

    from .asset_custody import register_engine_write

    registered: dict[str, str] = {}
    cache = Path(cache_dir)
    for item in files:
        if item.unavailable or item.viewable is None or item.sha256 in registered:
            continue
        data, media_type = item.viewable
        asset_id = attached_asset_id(item.sha256)
        try:
            cache.mkdir(parents=True, exist_ok=True)
            ingest = core.ingest_asset(
                store_root=str(cache),
                bytes_base64=base64.b64encode(data).decode("ascii"),
                asset_id=asset_id,
                label=item.filename[:200],
                declared_mime_type=media_type,
                filename=item.filename,
                kind="vector" if media_type == "image/svg+xml" else "raster_image",
                # The engine's AssetSource has no chat-attachment variant: an attached image is an
                # upload; that it came through the chat rides the tag and the provenance label.
                provenance={"source_label": "chat_attachment"},
                source={
                    "kind": "uploaded",
                    "asset_id": None,
                    "filename": item.filename,
                    "uploaded_by": None,
                },
                tags=[ATTACHED_IN_CHAT_TAG],
                raise_on_error=False,
            )
            if not ingest.get("ok"):
                logger.warning(
                    "attached_image.ingest_refused",
                    asset_id=asset_id,
                    error=str((ingest.get("error") or {}).get("message") or "unknown")[:200],
                )
                continue
            record = dict((ingest.get("asset") or {}).get("record") or {})
            register_engine_write(blobs, cache, source_key=SOURCE_KEY_ASSET, record=record)
            invocations.invoke(
                "design_register_asset_record",
                {"record": record},
                workspace_id=blobs.workspace_id,
                actor="agent",
                actor_id=run_id,
            )
        except Exception:  # noqa: BLE001 - an image that cannot be registered stays a file
            logger.warning("attached_image.register_failed", asset_id=asset_id, exc_info=True)
            continue
        registered[item.sha256] = str(record.get("id") or asset_id)
    return registered


def attached_reference_ids(
    existing: Sequence[str], files: Sequence[Any], registered: dict[str, str]
) -> list[str]:
    """An ad turn's references: the library images the message tagged, then the images it
    attached, without repeats, up to the per-turn cap. An image sent by an earlier message is in
    the library and the folder, but is not a reference of this turn."""

    from .main import REFERENCE_ASSETS_MAX

    attached = [registered[item.sha256] for item in files if item.current and item.sha256 in registered]
    return list(dict.fromkeys([*existing, *attached]))[:REFERENCE_ASSETS_MAX]
