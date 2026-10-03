"""The immutable, content-addressed fragment artifact (clone-fidelity F1.2, plan §1).

One artifact IS one cloned section: sanitized markup with its slot markers, scoped CSS, the
digests of every byte it displays, the slot manifest, and a preview image. The registry row
(:mod:`clue_design.web_fragments`) holds the digests and the provenance; these bytes hold the
content, in the design blob namespace, exactly as F0's site snapshots do.

**The id is the content.** ``fragment_id = "frag_" + sha256(identity bytes)[:16]``, so two
harvests that produce the same section produce the same fragment and dedup for free, and a
fragment cannot be edited into a different fragment while keeping its name.

**Where the identity bytes differ from the stored payload, and why.** The plan writes "sha256
over the canonical payload bytes", but the payload's ``css`` is scoped under
``.lumen-frag-<id>`` — it contains the id. Hashing it would ask the id to be a fixed point of a
function of itself, which has no solution. So the identity bytes are the canonical form of the
payload BEFORE scoping — the same fields, with ``css`` holding the reference-resolved but
unscoped source rules — and the stored payload is that identity plus the two things derived
from the id (the scoped ``css`` and the ``fragment_id`` field itself). Scoping is a pure
deterministic function of ``(identity, id)``, so every property the plan wanted still holds:
identical sections ⇒ identical identity bytes ⇒ identical id ⇒ byte-identical stored payload,
and one changed byte anywhere ⇒ a different id. The registry row records the stored payload's
own digest separately, so the blob is still addressable by what it literally is.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .cssscope import PRELUDE_REFERENCE_REFUSE, scope_fragment_css
from .native import validate_native_dependencies
from .refs import FragmentRefused, fragment_wrapper_class
from .sanitize import sanitize_fragment_html
from .slots import SlotSpec, annotate_fragment_slots

#: Ordinary captures retain v1 identity bytes. Declared native dependencies opt
#: into v2 below; readers accept both and never infer a controller from markup.
FRAGMENT_PAYLOAD_SCHEMA_VERSION = 1

FRAGMENT_PAYLOAD_MEDIA_TYPE = "application/json; charset=utf-8"


@dataclass(frozen=True)
class FragmentArtifact:
    """A minted fragment: its id, its payload, and the exact bytes that payload serializes to."""

    fragment_id: str
    payload: dict[str, Any]
    payload_bytes: bytes
    payload_digest: str
    notes: tuple[str, ...]

    @property
    def wrapper_class(self) -> str:
        return fragment_wrapper_class(self.fragment_id)


def canonical_bytes(value: Any) -> bytes:
    """The one canonical JSON encoding used for both the identity and the stored payload.

    Sorted keys and no incidental whitespace, so nothing about dict ordering or formatting can
    change an id. ``ensure_ascii=False`` keeps real text (a section's copy is rarely ASCII) as
    UTF-8 rather than as escape sequences — the encoding is fixed either way, so the choice only
    decides which one, and readable stored bytes are worth more than short ones here.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def build_fragment_artifact(
    *,
    html: str,
    css: str,
    rehosted: Mapping[str, str],
    slots: Sequence[SlotSpec] = (),
    preview_digest: str | None = None,
    prelude_reference: str = PRELUDE_REFERENCE_REFUSE,
    source_fragment_id: str | None = None,
    native_dependencies: dict[str, Any] | None = None,
) -> FragmentArtifact:
    """Sanitize, annotate, scope and address one section, in that order.

    Order matters. Sanitization runs first because everything after it works on markup we have
    already vouched for. Annotation runs on the sanitized tree, so a slot can never be stamped
    onto an element the sanitizer was about to remove. The id needs the annotated html and the
    resolved references, and the scoper needs the id — so scoping is last, and is the only step
    that runs after the fragment has a name.

    A refusal anywhere aborts: there is no partial artifact, and nothing is written.

    ``prelude_reference`` is forwarded verbatim to :func:`~lumen_api.fragments.cssscope
    .scope_fragment_css` — including to the throwaway probe pass below, so the two passes cannot
    disagree about which rules exist and the identity bytes describe the CSS that will be stored.
    ``source_fragment_id`` is the repair path's internal scoping hint, not permission to skip
    sanitization or reference validation. Ordinary captures retain their existing identity.
    """
    sanitized = sanitize_fragment_html(html, rehosted=rehosted)
    annotated = annotate_fragment_slots(sanitized.html, slots)
    dependencies = (
        validate_native_dependencies(annotated.html, native_dependencies)
        if native_dependencies is not None else None
    )
    version = 2 if dependencies is not None else FRAGMENT_PAYLOAD_SCHEMA_VERSION

    # The CSS is scoped against the FINAL id, but its references must be resolved before the id
    # exists (they are part of the identity). Scoping under a throwaway id resolves and records
    # them; the real scope pass below re-runs over the same source with the minted id.
    probe = scope_fragment_css(
        css, fragment_id=_PROBE_ID, rehosted=rehosted, prelude_reference=prelude_reference,
        source_fragment_id=source_fragment_id,
    )

    digests = tuple(sorted(set(sanitized.asset_digests) | set(probe.asset_digests)))
    identity = {
        "schema_version": version,
        "html": annotated.html,
        "source_css": css,
        "asset_digests": list(digests),
        "slot_manifest": annotated.slot_manifest,
        "preview_digest": preview_digest,
    }
    if source_fragment_id is not None:
        # The same input bytes can mean different selectors depending on which source scope
        # is being replaced. Address the normalized output, not that caller-local namespace.
        identity["source_css"] = probe.css
        identity["source_css_normalized"] = True
    if dependencies is not None:
        identity["native_dependencies"] = dependencies
    fragment_id = "frag_" + hashlib.sha256(canonical_bytes(identity)).hexdigest()[:16]

    scoped = scope_fragment_css(
        css, fragment_id=fragment_id, rehosted=rehosted, prelude_reference=prelude_reference,
        source_fragment_id=source_fragment_id,
    )
    payload = {
        "schema_version": version,
        "fragment_id": fragment_id,
        "html": annotated.html,
        "css": scoped.css,
        "asset_digests": list(digests),
        "slot_manifest": annotated.slot_manifest,
        "preview_digest": preview_digest,
    }
    if dependencies is not None:
        payload["native_dependencies"] = dependencies
    payload_bytes = canonical_bytes(payload)
    return FragmentArtifact(
        fragment_id=fragment_id,
        payload=payload,
        payload_bytes=payload_bytes,
        payload_digest=hashlib.sha256(payload_bytes).hexdigest(),
        notes=tuple([*sanitized.notes, *annotated.notes, *scoped.notes]),
    )


def parse_fragment_payload(data: bytes) -> dict[str, Any]:
    """Read a stored payload back, refusing anything that is not one.

    Fail-closed on the way out as well as in: a blob that does not carry the shape this module
    wrote is not "mostly a fragment", it is a corrupt or foreign blob, and the renderer must not
    be handed a dict with a missing ``html`` key to improvise around.
    """
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FragmentRefused(
            "fragment.payload_unreadable", f"fragment payload is not JSON: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise FragmentRefused("fragment.payload_unreadable", "fragment payload is not an object")
    missing = [
        key
        for key in ("schema_version", "fragment_id", "html", "css", "asset_digests", "slot_manifest")
        if key not in payload
    ]
    if missing:
        raise FragmentRefused(
            "fragment.payload_unreadable",
            f"fragment payload is missing {', '.join(missing)}",
        )
    if payload["schema_version"] not in (1, 2):
        raise FragmentRefused(
            "fragment.payload_schema_unknown",
            f"fragment payload schema {payload['schema_version']!r} is not "
            "one of 1, 2",
        )
    if payload["schema_version"] == 2:
        validate_native_dependencies(payload["html"], payload.get("native_dependencies"))
    elif "native_dependencies" in payload:
        raise FragmentRefused("fragment.payload_schema_unknown", "native dependencies require schema 2")
    return payload


#: A syntactically valid id used only to resolve the CSS's references before the real id exists.
#: Its scoped output is thrown away; only the digests it collected are kept.
_PROBE_ID = "frag_" + "0" * 16
