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
from .cssscope import ScopedCss, rewrite_declaration_urls, scope_fragment_css
from .refs import (
    ASSET_URL_PREFIX,
    FRAGMENT_ID_RE,
    FragmentRefused,
    asset_url,
    asset_url_digest,
    fragment_wrapper_class,
)
from .sanitize import DROPPED_ELEMENTS, SanitizedHtml, sanitize_fragment_html
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
    "DROPPED_ELEMENTS",
    "FRAGMENT_ID_RE",
    "FRAGMENT_PAYLOAD_SCHEMA_VERSION",
    "MAX_FRAGMENT_SLOTS",
    "SLOT_KINDS",
    "SLOT_MARKER_ATTR",
    "AnnotatedHtml",
    "FragmentArtifact",
    "FragmentRefused",
    "SanitizedHtml",
    "ScopedCss",
    "SlotSpec",
    "annotate_fragment_slots",
    "asset_url",
    "asset_url_digest",
    "build_fragment_artifact",
    "canonical_bytes",
    "fragment_wrapper_class",
    "parse_fragment_payload",
    "sanitize_fragment_html",
    "scope_fragment_css",
    "slot_key_is_valid",
]
