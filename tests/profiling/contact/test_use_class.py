"""M8.4 extraction-time use-class tagging (pure — no DB) — Doc D §2.

Non-escalatable fields tag at their hint; escalatable interests/causes escalate to sensitive on a
religious/political/health marker; a causes claim de-escalates only when evidently benign.
"""

from __future__ import annotations

import pytest

from clue_core import FieldDef, UseClass
from clue_research.profiling.contact.use_class import DEFAULT_USE_CLASS_TAGGER
from clue_research.profiling.fields import (
    FACET_ALMA_MATER,
    FACET_CAUSES,
    FACET_COMMUNICATION_STYLE,
    FACET_PACK,
    FACET_STATED_INTERESTS,
)

_FIELDS: dict[str, FieldDef] = {s.field_def.field_key: s.field_def for s in FACET_PACK}

# The escalatable facet fields — every one must escalate to sensitive on a special-category marker
# (so a future escalatable field cannot ship without this coverage).
_ESCALATABLE_FIELDS: list[str] = [
    s.field_def.field_key
    for s in FACET_PACK
    if (s.field_def.validation or {}).get("use_class_escalatable")
]


def test_non_escalatable_field_tags_at_hint() -> None:
    # communication_style → professional-public (hint), regardless of evidence.
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_COMMUNICATION_STYLE],
        {"style_label": "direct", "summary": "crisp technical posts"},
        "He writes about distributed systems.",
    )
    assert tag is UseClass.PROFESSIONAL_PUBLIC


def test_alma_mater_is_personal_non_sensitive() -> None:
    tag = DEFAULT_USE_CLASS_TAGGER.tag(_FIELDS[FACET_ALMA_MATER], ["MIT"], "Studied at MIT.")
    assert tag is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE


def test_professional_interest_stays_non_sensitive() -> None:
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_STATED_INTERESTS],
        ["robotics", "trail running"],
        "Loves robotics and running.",
    )
    assert tag is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE


def test_religious_interest_escalates_to_sensitive() -> None:
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_STATED_INTERESTS],
        ["volunteering"],
        "Active in his church community and Bible study.",
    )
    assert tag is UseClass.SENSITIVE


def test_causes_religious_is_sensitive() -> None:
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_CAUSES],
        [{"cause": "faith-based charity", "context": "supports a religious mission"}],
        "Donates to a religious mission.",
    )
    assert tag is UseClass.SENSITIVE


def test_causes_benign_de_escalates() -> None:
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_CAUSES],
        [{"cause": "climate", "context": "environmental conservation nonprofit"}],
        "Backs an environmental conservation nonprofit.",
    )
    assert tag is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE


def test_causes_ambiguous_stays_sensitive() -> None:
    # No sensitive marker and no clearly-benign marker → fail safe to sensitive (causes default).
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_CAUSES],
        [{"cause": "a local community group"}],
        "Supports a local community group.",
    )
    assert tag is UseClass.SENSITIVE


def test_political_interest_escalates() -> None:
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_STATED_INTERESTS],
        ["volunteering"],
        "Ran as a candidate in a local election campaign.",
    )
    assert tag is UseClass.SENSITIVE


def test_health_interest_escalates() -> None:
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_STATED_INTERESTS],
        ["advocacy"],
        "A vocal mental health advocate after a cancer diagnosis.",
    )
    assert tag is UseClass.SENSITIVE


def test_marker_in_value_only_escalates() -> None:
    # The marker is only in the value_json (not the evidence span) — _flatten must still catch it.
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_CAUSES],
        [{"cause": "ministry outreach"}],
        "Supports a community group.",
    )
    assert tag is UseClass.SENSITIVE


@pytest.mark.parametrize("field_key", _ESCALATABLE_FIELDS)
def test_every_escalatable_field_escalates_on_marker(field_key: str) -> None:
    # A political marker in the evidence escalates every escalatable field to sensitive.
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[field_key],
        ["x"],
        "Backs a political campaign candidate.",
    )
    assert tag is UseClass.SENSITIVE
