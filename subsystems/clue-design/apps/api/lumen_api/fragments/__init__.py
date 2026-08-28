"""The fragment registry and its write-time primitives (clone-fidelity F1.2).

A *fragment* is one verbatim cloned section of a real website, made safe once and then frozen:
sanitized markup with slot markers, CSS scoped so it cannot escape the section, the digests of
every byte it displays, and a preview image — all content-addressed under a
``frag_<16 hex>`` id that a ``WebNodeKind::Fragment`` document node pins.

The pieces, in the order a fragment goes through them:

* :mod:`~lumen_api.fragments.refs` — what a fragment may point at (the fail-closed reference gate)
* :mod:`~lumen_api.fragments.sanitize` — the one-time D-F4 sanitizer
* :mod:`~lumen_api.fragments.slots` — the slot-marker annotator and its manifest
* :mod:`~lumen_api.fragments.cssscope` — the CSS scoper
* :mod:`~lumen_api.fragments.artifact` — content addressing, the payload shape
* :mod:`~lumen_api.fragments.registry` — durable custody: bytes to the design blob namespace,
  rows to ``design_web_fragment``
"""

from __future__ import annotations

from .artifact import (
    FRAGMENT_PAYLOAD_SCHEMA_VERSION,
    FragmentArtifact,
    build_fragment_artifact,
    canonical_bytes,
    parse_fragment_payload,
)
from .cssscope import (
    PRELUDE_REFERENCE_MODES,
    PRELUDE_REFERENCE_REFUSE,
    PRELUDE_REFERENCE_STRIP,
    ScopedCss,
    rewrite_declaration_urls,
    scope_fragment_css,
)
from .degraded import (
    DEGRADED_REASON_DEAD_HEIGHT,
    DEGRADED_REASONS,
    REPAIR_NOTE_MAX_CHARS,
    REPAIR_RUNGS,
    degraded_headline,
    repair_reason,
)
from .refs import (
    ASSET_URL_PREFIX,
    FRAGMENT_ID_RE,
    FragmentRefused,
    asset_url,
    asset_url_digest,
    fragment_wrapper_class,
)
from .registry import (
    FRAGMENT_STATUS_DORMANT,
    FRAGMENT_STATUSES,
    WEB_FRAGMENT_SOURCE_KEY,
    LoadedFragment,
    create_web_fragment,
    list_web_fragments,
    read_web_fragment,
    set_web_fragment_degraded,
    set_web_fragment_status,
    web_fragment_exists,
)
from .sanitize import (
    DROPPED_ELEMENTS,
    SanitizedHtml,
    parse_srcset_candidates,
    sanitize_fragment_html,
)
from .slots import (
    MAX_FRAGMENT_SLOTS,
    SLOT_KINDS,
    SLOT_MARKER_ATTR,
    AnnotatedHtml,
    SlotSpec,
    annotate_fragment_slots,
    slot_key_is_valid,
)

__all__ = [
    "ASSET_URL_PREFIX",
    "DEGRADED_REASONS",
    "DEGRADED_REASON_DEAD_HEIGHT",
    "DROPPED_ELEMENTS",
    "FRAGMENT_ID_RE",
    "FRAGMENT_PAYLOAD_SCHEMA_VERSION",
    "FRAGMENT_STATUSES",
    "FRAGMENT_STATUS_DORMANT",
    "MAX_FRAGMENT_SLOTS",
    "PRELUDE_REFERENCE_MODES",
    "PRELUDE_REFERENCE_REFUSE",
    "PRELUDE_REFERENCE_STRIP",
    "REPAIR_NOTE_MAX_CHARS",
    "REPAIR_RUNGS",
    "SLOT_KINDS",
    "SLOT_MARKER_ATTR",
    "WEB_FRAGMENT_SOURCE_KEY",
    "AnnotatedHtml",
    "FragmentArtifact",
    "FragmentRefused",
    "LoadedFragment",
    "SanitizedHtml",
    "ScopedCss",
    "SlotSpec",
    "annotate_fragment_slots",
    "asset_url",
    "asset_url_digest",
    "build_fragment_artifact",
    "canonical_bytes",
    "create_web_fragment",
    "degraded_headline",
    "fragment_wrapper_class",
    "list_web_fragments",
    "parse_fragment_payload",
    "parse_srcset_candidates",
    "read_web_fragment",
    "repair_reason",
    "sanitize_fragment_html",
    "scope_fragment_css",
    "set_web_fragment_degraded",
    "set_web_fragment_status",
    "slot_key_is_valid",
    "web_fragment_exists",
]
