"""M10.2 — use-class tagging: the versioned special-category lexicon + tag-distribution metric.

M8.4 owns the tagger (`profiling/contact/use_class.py`) and its extraction-time wiring; the M8 suite
(`tests/profiling/contact/test_use_class.py`) locks the tagging *behaviour*. M10.2 adds (and these
tests verify): the Art. 9 special-category lexicon as **versioned config** (so the set is editable
without code — the M10.2 acceptance criterion) and the at-rest **tag-distribution** observability
(Doc C §6 / Doc D §5, separate from the accuracy axis). All pure — no DB.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_research.config import (
    DEFAULT_USE_CLASS_LEXICON,
    JurisdictionPolicy,
    UseClassLexicon,
)
from clue_research.core import (
    Claim,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    new_entity_id,
    new_run_id,
)
from clue_research.obs import (
    METRIC_USE_CLASS_TOTAL,
    InMemorySink,
    record_use_class_distribution,
)
from clue_research.profiling.contact.use_class import DEFAULT_USE_CLASS_TAGGER, UseClassTagger
from clue_research.profiling.fields import FACET_CAUSES, FACET_PACK, FACET_STATED_INTERESTS

_FIELDS = {s.field_def.field_key: s.field_def for s in FACET_PACK}


# --- the lexicon is versioned config ---------------------------------------------------------


def test_default_lexicon_carries_art9_markers() -> None:
    # the default lexicon reproduces the Art. 9 / reasonable-person-private set the tagger used to
    # hardcode (so moving it to config did not change the default behaviour).
    sensitive = DEFAULT_USE_CLASS_LEXICON.sensitive_markers
    for marker in ("church", "election", "cancer", "lgbtq", "racial", "mental health"):
        assert marker in sensitive
    for benign in ("climate", "open source", "scholarship"):
        assert benign in DEFAULT_USE_CLASS_LEXICON.benign_cause_markers
    assert DEFAULT_USE_CLASS_LEXICON.version == 1


def test_default_tagger_reads_config_lexicon() -> None:
    # regression: the default tagger (now lexicon-backed) still escalates a religious interest.
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_STATED_INTERESTS], ["volunteering"], "Active in his church community."
    )
    assert tag is UseClass.SENSITIVE


def test_adding_a_sensitive_marker_reclassifies_with_zero_code() -> None:
    # THE M10.2 acceptance criterion: extending the Art. 9 set is a *config* edit, not code.
    field = _FIELDS[FACET_STATED_INTERESTS]
    value = ["yoga"]
    span = "Practises yoga and meditation daily."
    # default lexicon: "yoga" is not a special-category marker → stays at the field hint.
    assert (
        DEFAULT_USE_CLASS_TAGGER.tag(field, value, span) is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE
    )
    # a policy that treats yoga as religion-adjacent: add the marker — no tagger code changes.
    stricter = UseClassTagger(
        lexicon=UseClassLexicon(
            sensitive_markers=(*DEFAULT_USE_CLASS_LEXICON.sensitive_markers, "yoga")
        )
    )
    assert stricter.tag(field, value, span) is UseClass.SENSITIVE


def test_benign_cause_markers_are_config() -> None:
    # the de-escalation side is config too: a cause the default keeps sensitive (fail-safe) can be
    # marked benign via config.
    field = _FIELDS[FACET_CAUSES]
    value = [{"cause": "a quilting circle"}]
    span = "Runs a local quilting circle."
    assert (
        DEFAULT_USE_CLASS_TAGGER.tag(field, value, span) is UseClass.SENSITIVE
    )  # ambiguous → safe
    lenient = UseClassTagger(
        lexicon=UseClassLexicon(
            benign_cause_markers=(*DEFAULT_USE_CLASS_LEXICON.benign_cause_markers, "quilting")
        )
    )
    assert lenient.tag(field, value, span) is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE


_DOC_D_CATEGORY_EVIDENCE = {
    "religion": "Active in his church community.",
    "politics": "Ran in a local election campaign.",
    "health": "A vocal mental health advocate.",
    "sexual_orientation": "Helps run a gay rights group.",
    "ethnicity": "Leads an ethnic heritage society.",
    "trade_union": "Serves as a trade union representative.",
    "biometric_genetic": "Volunteers for a genetic research registry.",
    "family_children": "Open about a long fertility journey.",
    "financial": "Has written about a past bankruptcy.",
}


@pytest.mark.parametrize("category", sorted(_DOC_D_CATEGORY_EVIDENCE))
def test_each_doc_d_category_escalates_an_escalatable_usable_field(category: str) -> None:
    # Every Doc D §2 category must escalate an escalatable *usable-hint* field (stated_interests) to
    # SENSITIVE — for these, a miss fails OPEN, so a future category drop must fail the build.
    tag = DEFAULT_USE_CLASS_TAGGER.tag(
        _FIELDS[FACET_STATED_INTERESTS], ["volunteering"], _DOC_D_CATEGORY_EVIDENCE[category]
    )
    assert tag is UseClass.SENSITIVE, f"{category} did not escalate to sensitive"


def test_removing_a_sensitive_marker_de_escalates_with_zero_code() -> None:
    # The config path is bidirectional: removing a marker (keeping the set non-empty) de-escalates,
    # zero code. Catches a broken impl that ignores the injected lexicon.
    field = _FIELDS[FACET_STATED_INTERESTS]
    span = "Active in his church community."
    assert DEFAULT_USE_CLASS_TAGGER.tag(field, ["volunteering"], span) is UseClass.SENSITIVE
    without_church = UseClassTagger(
        lexicon=UseClassLexicon(
            sensitive_markers=tuple(
                m for m in DEFAULT_USE_CLASS_LEXICON.sensitive_markers if m != "church"
            )
        )
    )
    assert (
        without_church.tag(field, ["volunteering"], span) is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE
    )


def test_custom_marker_fires_via_value_json_alone() -> None:
    # the injected lexicon must drive the value_json path too, not only the evidence span.
    field = _FIELDS[FACET_STATED_INTERESTS]
    stricter = UseClassTagger(
        lexicon=UseClassLexicon(
            sensitive_markers=(*DEFAULT_USE_CLASS_LEXICON.sensitive_markers, "yoga")
        )
    )
    assert stricter.tag(field, ["yoga"], evidence_span=None) is UseClass.SENSITIVE
    assert (
        DEFAULT_USE_CLASS_TAGGER.tag(field, ["yoga"], evidence_span=None)
        is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE
    )


def test_marker_case_is_normalized() -> None:
    # a non-lowercase custom marker must still fire (matching is over lowercased text).
    field = _FIELDS[FACET_STATED_INTERESTS]
    stricter = UseClassTagger(
        lexicon=UseClassLexicon(
            sensitive_markers=(*DEFAULT_USE_CLASS_LEXICON.sensitive_markers, "Yoga")
        )
    )
    assert stricter.tag(field, ["yoga"], "Practises yoga daily.") is UseClass.SENSITIVE


def test_empty_sensitive_markers_rejected() -> None:
    # an empty special-category set would silently disable Art. 9 escalation — must fail loud.
    with pytest.raises(ValidationError, match="sensitive_markers must be non-empty"):
        UseClassLexicon(sensitive_markers=())


def test_blank_marker_rejected() -> None:
    # a blank marker substring-matches everything (the benign side would de-escalate all) — reject.
    with pytest.raises(ValidationError, match="non-empty"):
        UseClassLexicon(benign_cause_markers=("climate", "  "))
    with pytest.raises(ValidationError, match="non-empty"):
        UseClassLexicon(sensitive_markers=("church", ""))


def test_jurisdiction_policy_carries_the_default_lexicon() -> None:
    # the lexicon is per-client overlayable (policy-as-data), like regime_mapping.
    assert JurisdictionPolicy().use_class_lexicon == DEFAULT_USE_CLASS_LEXICON


# --- tag-distribution observability --------------------------------------------------------------


def _facet_claim(use_class: UseClass) -> Claim:
    return Claim(
        entity_id=new_entity_id(),
        entity_type=EntityType.CONTACT,
        field_key="contact.facet.recent_post",
        value_json="a public post",
        source_url="https://example.com/post",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
        identity_binding=IdentityBinding.STRONG,
        use_class=use_class,
    )


def _account_claim() -> Claim:
    return Claim(
        entity_id=new_entity_id(),
        entity_type=EntityType.ACCOUNT,
        field_key="account.recent_funding",
        value_json={"amount_usd": 1.0},
        source_url="https://example.com/funding",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
    )


def test_record_use_class_distribution_counts_per_use_class() -> None:
    sink = InMemorySink()
    claims = [
        _facet_claim(UseClass.PROFESSIONAL_PUBLIC),
        _facet_claim(UseClass.PROFESSIONAL_PUBLIC),
        _facet_claim(UseClass.SENSITIVE),
        _facet_claim(UseClass.PERSONAL_PUBLIC_NON_SENSITIVE),
        _account_claim(),  # no use_class (not personal) → must not be counted
    ]
    record_use_class_distribution(claims, sink=sink)
    assert sink.counter(METRIC_USE_CLASS_TOTAL, use_class="professional-public") == 2.0
    assert sink.counter(METRIC_USE_CLASS_TOTAL, use_class="sensitive") == 1.0
    assert sink.counter(METRIC_USE_CLASS_TOTAL, use_class="personal-public-non-sensitive") == 1.0
    # the account claim carries no use_class and is not counted on any label
    total = sum(sink.counter(METRIC_USE_CLASS_TOTAL, use_class=uc.value) for uc in UseClass)
    assert total == 4.0
