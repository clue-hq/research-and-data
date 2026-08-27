"""Durable custody for cloned sections (clone-fidelity F1.2).

The seam between the write-time primitives (sanitize → annotate → scope → address) and the two
places a fragment actually lives: its canonical payload in the design blob namespace, and its
row in ``design_web_fragment``. Modeled on :mod:`lumen_ingestion.site_snapshot`, which does the
same job for F0's captures — bytes through
:func:`clue_design.storage.register_design_bytes`, rows through the DAL, one bridged transaction
per logical operation (the O5 rule).

**Creation is the only payload write.** :func:`create_web_fragment` runs the primitives, mints
the id from the result, stores the payload and the preview, and inserts the row. Re-running it
with identical inputs is a complete no-op: the id is the same, the content-addressed blob keys
are the same, and the row insert converges. There is deliberately no update function —
:func:`set_web_fragment_status` moves the row's lifecycle flag and nothing else, and the table's
trigger makes that a guarantee rather than a habit.

**Reads are fail-closed.** An absent fragment, another tenant's fragment, and a fragment whose
payload blob a purge destroyed all raise the same refusal, so existence never leaks and a caller
never receives a half-loaded artifact to improvise around.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from clue_design import web_fragments as dal
from clue_design.storage import (
    SOURCE_KEY_WEB_FRAGMENT,
    read_design_bytes,
    register_design_bytes,
)
from clue_design.web_fragments import FRAGMENT_STATUSES
from clue_storage import StorageBackend

from ..design_store import DesignStoreBridge
from .artifact import (
    FRAGMENT_PAYLOAD_MEDIA_TYPE,
    FragmentArtifact,
    build_fragment_artifact,
    parse_fragment_payload,
)
from .refs import FragmentRefused
from .slots import SlotSpec

#: ``source_key`` on the ``artifact`` rows this seam writes (observability, not identity).
WEB_FRAGMENT_SOURCE_KEY = SOURCE_KEY_WEB_FRAGMENT

_DEFAULT_PREVIEW_MEDIA_TYPE = "image/png"


@dataclass(frozen=True)
class LoadedFragment:
    """One fragment read back out of durable custody: its row and its payload, together."""

    row: dict[str, Any]
    payload: dict[str, Any]

    @property
    def fragment_id(self) -> str:
        return str(self.row["fragment_id"])

    @property
    def html(self) -> str:
        return str(self.payload["html"])

    @property
    def css(self) -> str:
        return str(self.payload["css"])

    @property
    def slot_manifest(self) -> dict[str, Any]:
        return dict(self.payload["slot_manifest"])


def create_web_fragment(
    storage: StorageBackend,
    *,
    workspace_id: str,
    html: str,
    css: str,
    rehosted: Mapping[str, str],
    source_url: str,
    section_role: str,
    slots: Sequence[SlotSpec] = (),
    label: str | None = None,
    source_kit_id: str | None = None,
    source_kit_version: int | None = None,
    preview: bytes | None = None,
    preview_media_type: str = _DEFAULT_PREVIEW_MEDIA_TYPE,
    provenance: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], FragmentArtifact]:
    """Mint one fragment and give it durable custody. Returns ``(row, artifact)``.

    Every refusal happens BEFORE any I/O: the primitives run first, so an unrehostable reference
    or a bad slot key costs nothing but the exception. Once they pass, the payload blob, the
    preview blob and the row land in ONE transaction — a committed row naming bytes that never
    landed would be a dangling artifact reference nothing downstream could tell from a real one.
    """
    if (source_kit_id is None) != (source_kit_version is None):
        raise FragmentRefused(
            "fragment.source_kit_incomplete",
            "a fragment names both its source kit id and version, or neither",
        )

    preview_digest = _digest(preview) if preview is not None else None
    artifact = build_fragment_artifact(
        html=html, css=css, rehosted=rehosted, slots=slots, preview_digest=preview_digest
    )

    async def _persist(conn: Any) -> dict[str, Any]:
        await register_design_bytes(
            conn,
            storage,
            workspace_id=workspace_id,
            data=artifact.payload_bytes,
            media_type=FRAGMENT_PAYLOAD_MEDIA_TYPE,
            source_key=WEB_FRAGMENT_SOURCE_KEY,
        )
        if preview is not None:
            await register_design_bytes(
                conn,
                storage,
                workspace_id=workspace_id,
                data=preview,
                media_type=preview_media_type,
                source_key=WEB_FRAGMENT_SOURCE_KEY,
            )
        return await dal.insert_web_fragment(
            conn,
            workspace_id=workspace_id,
            fragment_id=artifact.fragment_id,
            source_kit_id=source_kit_id,
            source_kit_version=source_kit_version,
            source_url=source_url,
            section_role=section_role,
            label=label,
            payload_digest=artifact.payload_digest,
            preview_digest=preview_digest,
            provenance=dict(provenance or {}),
        )

    return DesignStoreBridge(workspace_id)._run(_persist), artifact


def read_web_fragment(
    storage: StorageBackend, *, workspace_id: str, fragment_id: str
) -> LoadedFragment:
    """One fragment with its payload — the read F1.3's render arm and F1.5's export go through."""

    async def _read(conn: Any) -> LoadedFragment:
        row = await dal.get_web_fragment(
            conn, workspace_id=workspace_id, fragment_id=fragment_id
        )
        data = await read_design_bytes(
            conn, storage, workspace_id=workspace_id, sha256=row["payload_digest"]
        )
        return LoadedFragment(row=row, payload=parse_fragment_payload(data))

    return DesignStoreBridge(workspace_id)._run(_read)


def web_fragment_exists(*, workspace_id: str, fragment_id: str) -> bool:
    """Whether this workspace holds this fragment — the reference gate's probe, no bytes read."""
    return (
        DesignStoreBridge(workspace_id)._run(
            lambda conn: dal.find_web_fragment(
                conn, workspace_id=workspace_id, fragment_id=fragment_id
            )
        )
        is not None
    )


def list_web_fragments(
    *, workspace_id: str, section_role: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    """This workspace's fragment rows, newest first. Digests only; no blob is read."""
    return DesignStoreBridge(workspace_id)._run(
        lambda conn: dal.list_web_fragments(
            conn, workspace_id=workspace_id, section_role=section_role, status=status
        )
    )


def set_web_fragment_status(
    *, workspace_id: str, fragment_id: str, status: str
) -> dict[str, Any]:
    """Move one fragment's lifecycle flag. The only mutation this registry has."""
    return DesignStoreBridge(workspace_id)._run(
        lambda conn: dal.set_web_fragment_status(
            conn, workspace_id=workspace_id, fragment_id=fragment_id, status=status
        )
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "FRAGMENT_STATUSES",
    "WEB_FRAGMENT_SOURCE_KEY",
    "LoadedFragment",
    "create_web_fragment",
    "list_web_fragments",
    "read_web_fragment",
    "set_web_fragment_status",
    "web_fragment_exists",
]
