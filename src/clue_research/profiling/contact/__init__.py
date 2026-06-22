"""`clue_research.profiling.contact` — Contact Profiling (mode M4 / M8.4).

For each verified committee member, gather "everything publicly true about *this verified person*",
tagging every claim's ``identity_binding`` + ``use_class`` born-correct (the make-or-break,
staged-flow §6). The trunk is :func:`profile_contact` (+ :class:`ContactProfileAspectWorker` for the
M7 graph); it computes gap fields, fills them through the facet-aware fill, and requests facet
sub-workers within the per-tier recursion budget. See ``docs/specs/M08-deep-profiling.md`` §M8.4.
"""

from __future__ import annotations

from clue_research.profiling.contact.binding import (
    DEFAULT_BINDING_CLASSIFIER,
    BindingClassifier,
    BindingInput,
    DefaultBindingClassifier,
)
from clue_research.profiling.contact.fill import FacetFillResult, fill_contact_field
from clue_research.profiling.contact.gaps import compute_contact_gap_fields
from clue_research.profiling.contact.results import (
    DEFAULT_CONTACT_PROFILE_CONFIG,
    ContactProfileConfig,
    ContactProfileResult,
)
from clue_research.profiling.contact.use_class import (
    DEFAULT_USE_CLASS_TAGGER,
    UseClassTagger,
)
from clue_research.profiling.contact.worker import (
    ContactProfileAspectWorker,
    profile_contact,
)

__all__ = [
    # worker entrypoint + M7 adapter
    "profile_contact",
    "ContactProfileAspectWorker",
    # result / config
    "ContactProfileResult",
    "ContactProfileConfig",
    "DEFAULT_CONTACT_PROFILE_CONFIG",
    # gap computation + fill
    "compute_contact_gap_fields",
    "fill_contact_field",
    "FacetFillResult",
    # extraction-time taggers (the make-or-break)
    "BindingClassifier",
    "BindingInput",
    "DefaultBindingClassifier",
    "DEFAULT_BINDING_CLASSIFIER",
    "UseClassTagger",
    "DEFAULT_USE_CLASS_TAGGER",
]
