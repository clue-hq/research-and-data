"""M8.4 extraction-time identity-binding (pure — no DB) — the make-or-break.

A fact on the contact's verified handle (or co-occurring with strong identifiers) is STRONG; a
name-only match on a stranger's page is WEAK (the same-name trap). M8.4 tags; M9 drops weak.
"""

from __future__ import annotations

from clue_core import ContactEntity, IdentityBinding, new_entity_id
from clue_research.profiling.contact.binding import (
    DEFAULT_BINDING_CLASSIFIER,
    BindingInput,
    DefaultBindingClassifier,
)


def _contact(**kw: object) -> ContactEntity:
    base: dict[str, object] = {
        "id": new_entity_id(),
        "account_entity_id": new_entity_id(),
        "full_name": "Jane Smith",
        "linkedin_url": "https://linkedin.com/in/jane-smith",
    }
    base.update(kw)
    return ContactEntity.model_validate(base)


def test_verified_handle_is_strong() -> None:
    contact = _contact()
    binding = DEFAULT_BINDING_CLASSIFIER.classify(
        BindingInput(
            contact=contact,
            evidence_span="Jane posted about robotics.",
            source_url="https://linkedin.com/in/jane-smith",  # the contact's own handle
        )
    )
    assert binding is IdentityBinding.STRONG


def test_handle_match_is_path_specific_not_just_host() -> None:
    contact = _contact()
    # A *different* person's LinkedIn (same host, different path) must NOT count as the handle.
    binding = DEFAULT_BINDING_CLASSIFIER.classify(
        BindingInput(
            contact=contact,
            evidence_span="Jane Smith, a teacher, ...",
            source_url="https://linkedin.com/in/some-other-jane",
        )
    )
    assert binding is IdentityBinding.WEAK


def test_same_name_stranger_is_weak() -> None:
    contact = _contact()
    binding = DEFAULT_BINDING_CLASSIFIER.classify(
        BindingInput(
            contact=contact,
            evidence_span="Jane Smith volunteers at a shelter in Ohio.",  # name only, no employer
            source_url="https://some-blog.example/post/123",
            account_name="Acme Robotics",
        )
    )
    assert binding is IdentityBinding.WEAK


def test_name_plus_employer_co_occurrence_is_strong() -> None:
    contact = _contact()
    binding = DEFAULT_BINDING_CLASSIFIER.classify(
        BindingInput(
            contact=contact,
            evidence_span="Jane Smith, VP of Engineering at Acme Robotics, spoke about scaling.",
            source_url="https://conf.example/speakers",
            account_name="Acme Robotics",  # employer co-occurs with the name → this person
        )
    )
    assert binding is IdentityBinding.STRONG


def test_name_plus_geo_co_occurrence_is_strong() -> None:
    contact = _contact(geo={"city": "Austin"})
    binding = DEFAULT_BINDING_CLASSIFIER.classify(
        BindingInput(
            contact=contact,
            evidence_span="Jane Smith, based in Austin, gave a talk.",
            source_url="https://conf.example/speakers",
        )
    )
    assert binding is IdentityBinding.STRONG


def test_strong_manifest_prior_short_circuits() -> None:
    contact = _contact()
    binding = DEFAULT_BINDING_CLASSIFIER.classify(
        BindingInput(
            contact=contact,
            evidence_span="(from the client CRM)",
            source_url=None,
            manifest_prior=IdentityBinding.STRONG,
        )
    )
    assert binding is IdentityBinding.STRONG


def test_no_evidence_is_weak() -> None:
    contact = _contact()
    binding = DEFAULT_BINDING_CLASSIFIER.classify(BindingInput(contact=contact))
    assert binding is IdentityBinding.WEAK


def test_conforms_to_protocol() -> None:
    from clue_research.profiling.contact.binding import BindingClassifier

    assert isinstance(DefaultBindingClassifier(), BindingClassifier)
