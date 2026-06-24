"""Extraction-time use-class tagging (M8.4 / Doc D §2).

Every ``contact.*``/``contact.facet.*`` claim is tagged ``use_class ∈ {professional-public,
personal-public-non-sensitive, sensitive}`` the moment it is extracted — independent of accuracy
(Doc D §2). M8.4 *tags*; the appropriateness/use *gate* and the postures are M10.

The tag starts from the field's per-field ``use_class_hint`` (the M8.5 seed) and is then computed
from the evidence: a field marked ``use_class_escalatable`` (``stated_interests``, ``causes``) whose
evidence is tied to a religious / political / health / special-category topic escalates to
``sensitive`` (Doc D §2 note). A ``causes`` claim is ``sensitive`` by default (religion/politics-
adjacent) and only de-escalates when the cause is evidently benign; the fail-safe direction is
*toward* sensitive (better to over-restrict a hook than misuse special-category data).

The special-category lexicon (the Art. 9 marker set + the benign-cause markers) is **versioned
config** — :class:`clue_research.config.UseClassLexicon` (M10.2) — so the Art. 9 set is editable
without code (policy-as-data, conventions §2; D8). M8 owns the tagger; M10 owns the lexicon it reads
and the use-gate/postures that act on the tag.
"""

from __future__ import annotations

from pydantic import JsonValue

from clue_research.config import DEFAULT_USE_CLASS_LEXICON, UseClassLexicon
from clue_research.core import FieldDef, UseClass

_HINT_KEY = "use_class_hint"
_ESCALATABLE_KEY = "use_class_escalatable"


def _flatten(value: JsonValue) -> str:
    """Flatten a value_json payload to a lowercase searchable string (objects/arrays included)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, (int, float, bool)):
        return str(value).lower()
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(v) for v in value)
    return ""


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _hint(field: FieldDef) -> UseClass:
    """The field's declared use-class hint, defaulting to professional-public (the least-restrictive
    default for a non-personal contact field)."""
    validation = field.validation or {}
    raw = validation.get(_HINT_KEY)
    if isinstance(raw, str):
        try:
            return UseClass(raw)
        except ValueError:
            pass
    return UseClass.PROFESSIONAL_PUBLIC


class UseClassTagger:
    """Compute a claim's use-class from the field hint + the evidence (M8.4).

    The special-category lexicon it escalates on is **config** (:class:`UseClassLexicon`, M10.2),
    injected here so the Art. 9 set is editable without code and a per-client lexicon can be
    supplied at the ``api`` composition root. The default lexicon reproduces the original hardcoded
    markers, so the default tagger's behaviour is unchanged."""

    def __init__(self, lexicon: UseClassLexicon = DEFAULT_USE_CLASS_LEXICON) -> None:
        self._lexicon = lexicon

    def tag(
        self, field: FieldDef, value_json: JsonValue, evidence_span: str | None = None
    ) -> UseClass:
        hint = _hint(field)
        validation = field.validation or {}
        if not validation.get(_ESCALATABLE_KEY):
            return hint  # a non-escalatable field is tagged at its declared hint

        text = f"{evidence_span or ''} {_flatten(value_json)}".lower()
        is_sensitive = _has_marker(text, self._lexicon.sensitive_markers)

        if hint is UseClass.SENSITIVE:
            # causes: sensitive by default; de-escalate only when evidently benign + not sensitive.
            if is_sensitive:
                return UseClass.SENSITIVE
            if _has_marker(text, self._lexicon.benign_cause_markers):
                return UseClass.PERSONAL_PUBLIC_NON_SENSITIVE
            return UseClass.SENSITIVE  # ambiguous → stay sensitive (fail safe)
        # a non-sensitive-hint escalatable field (e.g. stated_interests) escalates on a marker.
        return UseClass.SENSITIVE if is_sensitive else hint


DEFAULT_USE_CLASS_TAGGER = UseClassTagger()
