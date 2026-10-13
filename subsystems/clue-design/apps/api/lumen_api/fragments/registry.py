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
from clue_design.web_fragments import (
    FRAGMENT_STATUS_DORMANT,
    FRAGMENT_STATUSES,
    require_birth_status,
    require_degraded_pair,
    require_derivable,
    require_derived_pair,
    require_known_status,
)
from clue_storage import StorageBackend

from ..design_store import DesignStoreBridge
from .artifact import (
    FRAGMENT_PAYLOAD_MEDIA_TYPE,
    FragmentArtifact,
    build_fragment_artifact,
    parse_fragment_payload,
)
from .cssscope import PRELUDE_REFERENCE_REFUSE
from .href_repair import HrefRepair, build_href_repair
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

    @property
    def asset_digests(self) -> list[str]:
        """The digests of every byte this artifact displays — its rehosted images and fonts.

        The markup and the CSS name them as ``/asset-store/<digest>``; this list is the
        artifact's own record of the set, which is what a delivery build walks to decide which
        bytes must travel with the page.
        """
        return [
            str(digest) for digest in (self.payload.get("asset_digests") or [])
        ]


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
    prelude_reference: str = PRELUDE_REFERENCE_REFUSE,
    status: str | None = None,
    degraded: bool = False,
    degraded_reason: str | None = None,
    derived_from: str | None = None,
    derived_reason: str | None = None,
    source_fragment_id: str | None = None,
    native_dependencies: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], FragmentArtifact]:
    """Mint one fragment and give it durable custody. Returns ``(row, artifact)``.

    Every refusal happens BEFORE any I/O: the primitives run first, so an unrehostable reference
    or a bad slot key costs nothing but the exception. Once they pass, the payload blob, the
    preview blob and the row land in ONE transaction — a committed row naming bytes that never
    landed would be a dangling artifact reference nothing downstream could tell from a real one.

    **The three F3.0 birth facts** (``status``, the degraded marker, the lineage pair) are stated
    HERE because this is the only moment they can be: the row is immutable-except-for-judgements
    from the next line onward. ``status`` lets a hidden-on-source section be born ``dormant``
    (D-F8) instead of being minted ``draft`` and then demoted, which would leave a window in
    which the kit cascade could release it. ``derived_from``/``derived_reason`` is how a repair
    says whose repair it is (D-F6) — a repair is a NEW fragment through this same path, never an
    edit of the original.

    The rules those three obey are the DAL's, imported rather than restated: this seam only
    translates them into the fragment refusal taxonomy the mint pipeline already reports on, so a
    producer gets ``fragment.*`` codes instead of a raw ``ValueError`` from two layers down.

    ``source_fragment_id`` is an internal hint from a repair's workspace-resolved original,
    allowing the normal scoper to retarget inspected CSS. It does not change custody, release,
    lineage validation, or expose a new tool argument.
    """
    if (source_kit_id is None) != (source_kit_version is None):
        raise FragmentRefused(
            "fragment.source_kit_incomplete",
            "a fragment names both its source kit id and version, or neither",
        )
    if status is not None:
        _refusing("fragment.status_unknown", require_known_status, status)
        # And narrower than the vocabulary: a producer may not mint straight into a human's
        # decision (ruling R-I5). See `BIRTH_STATUSES`.
        _refusing("fragment.status_not_birthable", require_birth_status, status)
    _refusing("fragment.degraded_reason_missing", require_degraded_pair, degraded, degraded_reason)
    _refusing("fragment.derived_incomplete", require_derived_pair, derived_from, derived_reason)

    preview_digest = _digest(preview) if preview is not None else None
    artifact = build_fragment_artifact(
        html=html,
        css=css,
        rehosted=rehosted,
        slots=slots,
        preview_digest=preview_digest,
        prelude_reference=prelude_reference,
        source_fragment_id=source_fragment_id,
        native_dependencies=native_dependencies,
    )

    return _persist_fragment_artifact(
        storage, workspace_id=workspace_id, artifact=artifact, source_url=source_url,
        section_role=section_role, label=label, source_kit_id=source_kit_id,
        source_kit_version=source_kit_version, preview=preview,
        preview_media_type=preview_media_type, provenance=provenance, status=status,
        degraded=degraded, degraded_reason=degraded_reason,
        derived_from=derived_from, derived_reason=derived_reason,
    )


def create_href_repaired_fragment(
    storage: StorageBackend, *, workspace_id: str, replaces: str,
    replacements: Mapping[str, str] | None = None, label: str, derived_reason: str,
    provenance: Mapping[str, Any], label_replacements: Mapping[str, str] | None = None,
    text_edits: list[dict[str, str]] | None = None,
) -> tuple[dict[str, Any], HrefRepair, bool]:
    """Derive only from this workspace's stored sanitized source, then use ordinary custody."""
    source = read_web_fragment(storage, workspace_id=workspace_id, fragment_id=replaces)
    repair = build_href_repair(
        source.payload, replacements, label_replacements=label_replacements,
        text_edits=text_edits,
        text_edit_scope=("campaign_variant" if "campaign variant" in derived_reason.lower()
                         else "canonical_repair"),
    )
    converged = web_fragment_exists(
        workspace_id=workspace_id, fragment_id=repair.artifact.fragment_id
    )
    row, _ = _persist_fragment_artifact(
        storage, workspace_id=workspace_id, artifact=repair.artifact,
        source_url=source.row["source_url"], section_role=source.row["section_role"], label=label,
        source_kit_id=source.row.get("source_kit_id"),
        source_kit_version=source.row.get("source_kit_version"),
        provenance={**(source.row.get("provenance") or {}), **provenance},
        degraded=bool(source.row.get("degraded")),
        degraded_reason=source.row.get("degraded_reason"),
        derived_from=replaces, derived_reason=derived_reason,
    )
    return row, repair, converged


def _persist_fragment_artifact(
    storage: StorageBackend, *, workspace_id: str, artifact: FragmentArtifact,
    source_url: str, section_role: str, label: str | None = None,
    source_kit_id: str | None = None, source_kit_version: int | None = None,
    preview: bytes | None = None, preview_media_type: str = _DEFAULT_PREVIEW_MEDIA_TYPE,
    provenance: Mapping[str, Any] | None = None, status: str | None = None,
    degraded: bool = False, degraded_reason: str | None = None,
    derived_from: str | None = None, derived_reason: str | None = None,
) -> tuple[dict[str, Any], FragmentArtifact]:
    """Shared custody for a validated captured artifact or its typed href-only derivative."""
    preview_digest = _digest(preview) if preview is not None else None

    async def _persist(conn: Any) -> dict[str, Any]:
        # The lineage target is the one birth fact that cannot be checked before I/O — it is a
        # question about a ROW. Asked first, inside the same transaction, so a refusal aborts
        # before any byte is registered rather than leaving an orphan blob behind.
        if derived_from is not None:
            try:
                await require_derivable(
                    conn,
                    workspace_id=workspace_id,
                    fragment_id=artifact.fragment_id,
                    derived_from=derived_from,
                )
            except ValueError as error:
                raise FragmentRefused(
                    "fragment.derived_from_unresolved", str(error), reference=derived_from
                ) from error
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
            provenance=_with_payload_sizes(provenance, artifact),
            status=status or "draft",
            degraded=degraded,
            degraded_reason=degraded_reason,
            derived_from=derived_from,
            derived_reason=derived_reason,
        )

    return DesignStoreBridge(workspace_id)._run(_persist), artifact


def _refusing(code: str, check: Any, *args: Any) -> None:
    """Run one DAL rule and re-word its ``ValueError`` as this seam's typed refusal."""
    try:
        check(*args)
    except ValueError as error:
        raise FragmentRefused(code, str(error)) from error


def read_web_fragment(
    storage: StorageBackend, *, workspace_id: str, fragment_id: str
) -> LoadedFragment:
    """One fragment with its payload — the read F1.3's render arm and F1.5's publish go through."""

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


def list_web_fragment_lineage(
    *, workspace_id: str, fragment_id: str
) -> list[dict[str, Any]]:
    """One fragment's whole repair family, statuses unfiltered — the lineage resolver's input.

    The bounded alternative to reading every row in the workspace to answer a question about one
    family. See the DAL for why the read is two recursive halves and why it filters no status.
    """
    return DesignStoreBridge(workspace_id)._run(
        lambda conn: dal.list_web_fragment_lineage(
            conn, workspace_id=workspace_id, fragment_id=fragment_id
        )
    )


def set_web_fragment_status(
    *, workspace_id: str, fragment_id: str, status: str
) -> dict[str, Any]:
    """Move one fragment's lifecycle flag — including the human activation of a dormant clone.

    Raises :class:`~clue_design.errors.DesignFragmentActivationError` when a dormant section with
    no preview is asked to wake (D-F8); see the DAL for why ``draft`` is gated alongside
    ``approved``.
    """
    return DesignStoreBridge(workspace_id)._run(
        lambda conn: dal.set_web_fragment_status(
            conn, workspace_id=workspace_id, fragment_id=fragment_id, status=status
        )
    )


def set_web_fragment_degraded(
    *, workspace_id: str, fragment_id: str, degraded: bool, reason: str | None = None
) -> dict[str, Any]:
    """Mark (or unmark) a harvested clone as broken, with the reason (D-F6).

    The second permitted mutation, and the second one that is a judgement rather than content.
    Deliberately NOT a status move: a degraded original stays approved and stays pinnable while
    it is the only thing that exists.
    """
    return DesignStoreBridge(workspace_id)._run(
        lambda conn: dal.set_web_fragment_degraded(
            conn,
            workspace_id=workspace_id,
            fragment_id=fragment_id,
            degraded=degraded,
            reason=reason,
        )
    )


def attach_web_fragment_preview(
    storage: StorageBackend,
    *,
    workspace_id: str,
    fragment_id: str,
    preview: bytes,
    preview_basis: str,
    media_type: str = _DEFAULT_PREVIEW_MEDIA_TYPE,
) -> dict[str, Any]:
    """Store an isolation-render PNG and hang it on a fragment that had no preview (F3.2, P-7).

    The blob and the row move in ONE transaction, like creation: a row naming bytes that never
    landed is a dangling reference nothing downstream could tell from a real one, and the reverse
    leaves a picture nobody can find.

    Deliberately NOT part of :func:`create_web_fragment`. A preview at MINT time is content — it
    is in the artifact's identity bytes, so a different picture is a different fragment — while
    this one is a picture taken of an already-minted artifact, after the fact, because nothing
    photographed it at birth. The DAL enforces the difference: once, never replaced.

    ``preview_basis`` is required rather than defaulted, and that is deliberate: P-7's whole
    labelling clause is that an isolation render must never pass for a source-site crop, and a
    default would be a caller forgetting to say which one this is.
    """
    digest = _digest(preview)

    async def _persist(conn: Any) -> dict[str, Any]:
        await register_design_bytes(
            conn,
            storage,
            workspace_id=workspace_id,
            data=preview,
            media_type=media_type,
            source_key=WEB_FRAGMENT_SOURCE_KEY,
        )
        return await dal.attach_web_fragment_preview(
            conn,
            workspace_id=workspace_id,
            fragment_id=fragment_id,
            preview_digest=digest,
            preview_basis=preview_basis,
        )

    return DesignStoreBridge(workspace_id)._run(_persist)


def _with_payload_sizes(
    provenance: Mapping[str, Any] | None, artifact: FragmentArtifact
) -> dict[str, Any]:
    """Stamp what was actually STORED onto the provenance the caller supplied.

    The producer cannot record this itself. A fragment's ``css`` is scoped under an id derived
    from the fragment's own content, so the stored bytes do not exist until the artifact is
    built — and the artifact is built HERE, one call after the provenance was assembled. Asking
    the producer for it would mean minting twice to measure once.

    So the seam that knows the answer writes it. The mint stage records what it MATCHED
    (``css.byte_length``, pre-scoping); this records what a reader will actually load, which is
    the number that matters when a picker offering a dozen sections is asked what it costs.
    """
    return {
        **dict(provenance or {}),
        "payload": {
            "bytes": len(artifact.payload_bytes),
            "css_bytes": len(str(artifact.payload.get("css") or "").encode("utf-8")),
            "html_bytes": len(str(artifact.payload.get("html") or "").encode("utf-8")),
        },
    }


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "FRAGMENT_STATUSES",
    "FRAGMENT_STATUS_DORMANT",
    "WEB_FRAGMENT_SOURCE_KEY",
    "LoadedFragment",
    "attach_web_fragment_preview",
    "create_web_fragment",
    "list_web_fragment_lineage",
    "list_web_fragments",
    "read_web_fragment",
    "set_web_fragment_degraded",
    "set_web_fragment_status",
    "web_fragment_exists",
]
