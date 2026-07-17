"""api composition root — packs load, both axes register under disjoint aspects, and the injected
binding classifier agrees with the M8 default on the canonical fixtures.

Pure tests (registry shape, adapter typing) run with no DB; the pack-loading + adapter-agreement
tests use the migrated DB and ``pytest.skip`` without one.
"""

from __future__ import annotations

from clue_core import IdentityBinding
from clue_research.api import (
    build_worker_registry,
    load_research_packs,
    production_binding_classifier,
)
from clue_research.claimstore import get_field
from clue_research.profiling import FACET_FIELD_KEYS, RESONANCE_FIELD_KEYS
from clue_research.profiling.committee import COMMITTEE_FIELD_KEYS
from clue_research.profiling.contact.binding import (
    DEFAULT_BINDING_CLASSIFIER,
    BindingClassifier,
    BindingInput,
)
from clue_research.sources import registered_source_keys
from tests.profiling.conftest import (
    FakeCommitteeSource,
    FakeGateway,
    insert_test_account,
    insert_test_contact,
    rollback_conn,
    run_async,
)

_EXPECTED_ASPECTS = {"core", "account", "account.resonance", "committee", "contact.facet"}


def test_adapter_satisfies_binding_classifier_protocol() -> None:
    """The injected ``classify_binding`` adapter is a structural ``BindingClassifier``."""
    assert isinstance(production_binding_classifier(), BindingClassifier)


def test_both_axes_register_under_disjoint_aspects() -> None:
    """The composition root registers the account + committee + contact workers, keyed on disjoint
    aspects, into one ``WorkerRegistry`` (no collision)."""
    registry = build_worker_registry(
        gateway=FakeGateway(),
        committee_sources=[FakeCommitteeSource(source_key="apollo_people", tier=2)],
    )
    assert registry.aspects() >= _EXPECTED_ASPECTS
    # exactly one worker per aspect (last-write-wins registration, no duplicates).
    assert registry.get("committee") is not None
    assert registry.get("contact.facet") is not None


def test_load_research_packs_registers_every_class(require_profiling_db: None) -> None:
    """One call seeds the core pack + the M8 seed (resonance/facet) + the committee pack + the M4
    source manifests, so every deep-profiling field/source a run reads is registered."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:  # start from a clean registry
            await load_research_packs(conn)
            for key in (
                "core.employee_count",
                RESONANCE_FIELD_KEYS[0],
                FACET_FIELD_KEYS[0],
                COMMITTEE_FIELD_KEYS[0],
            ):
                assert await get_field(conn, key) is not None, f"{key} not registered"
            assert await registered_source_keys(conn), "no source manifests seeded"

    run_async(scenario())


def test_injected_adapter_agrees_with_default_on_fixtures(require_profiling_db: None) -> None:
    """The injected ``classify_binding`` and M8.4's ``DefaultBindingClassifier`` agree
    on the canonical same-name / verified-handle fixtures (CLAUDE.md M9.4×M8.4)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            account = await insert_test_account(conn)
            contact = await insert_test_contact(
                conn, account, linkedin_url="https://linkedin.com/in/jane-cfo"
            )
            on_handle = BindingInput(
                contact=contact,
                evidence_span="Jane CFO on robotics.",
                source_url="https://linkedin.com/in/jane-cfo",  # the verified handle → STRONG
                source_key="exa_deep",
            )
            name_only = BindingInput(
                contact=contact,
                evidence_span="Jane CFO enjoys gardening.",  # name-only, off-handle → WEAK
                source_url="https://random-blog.example/post",
                source_key="exa_deep",
            )
            api_clf = production_binding_classifier()
            assert api_clf.classify(on_handle) is IdentityBinding.STRONG
            assert api_clf.classify(name_only) is IdentityBinding.WEAK
            # agreement with the M8 default it replaces.
            assert api_clf.classify(on_handle) is DEFAULT_BINDING_CLASSIFIER.classify(on_handle)
            assert api_clf.classify(name_only) is DEFAULT_BINDING_CLASSIFIER.classify(name_only)

    run_async(scenario())
