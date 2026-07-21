"""M8A.6 AC-4 — a deep contact's born ``identity_binding`` is the authoritative M9 verdict.

The deferred M9.4×M8.4 stamp (CLAUDE.md), closed at the deep composition root: the composition
injects ``verification.classify_binding`` (behind M8.4's ``BindingClassifier``) into the contact
callable, so a ``contact.facet.*`` claim written by ``profile_contact`` is **born** with the
immutable binding the M9 classifier would assign — not the M8 default placeholder. These drive the
deep contact callable with the composition's wired classifier and assert the born column equals the
``classify_binding`` verdict — STRONG on a verified handle, WEAK (unpromotable) on a same-name hit.
"""

from __future__ import annotations

from uuid import UUID

from clue_core import (
    Claim,
    ICPCreatedFrom,
    ICPSpec,
    IdentityBinding,
)
from clue_research.api.deep import build_deep_phase_handler
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.profiling import profile_contact
from clue_research.profiling.contact.binding import BindingClassifier
from clue_research.profiling.fields import FACET_STATED_INTERESTS
from clue_research.sources import bind_resolver, clear_resolver_bindings
from clue_research.verification import classify_binding
from tests.profiling.conftest import (
    FakeCommitteeSource,
    FakeFacetResolver,
    FakeGateway,
    insert_test_account,
    insert_test_contact,
    register_facet_source,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = UUID("a4a4a4a4-a4a4-a4a4-a4a4-a4a4a4a4a4a4")
_TENANT = "acme"
_FACET_SOURCE = "exa_deep"


def _composition_classifier() -> BindingClassifier:
    """The binding classifier the deep composition root wires (the authoritative M9 verdict behind
    M8.4's seam) — the object ``profile_contact`` is handed in production."""
    return build_deep_phase_handler(
        spec=ICPSpec(workspace_id=_TENANT, icp_key="seg1", created_from=ICPCreatedFrom.SYNTHESIS),
        gateway=FakeGateway(),
        committee_sources=[FakeCommitteeSource(source_key="apollo_people", tier=2)],
    ).binding_classifier


def _profile_one_facet(
    *, resolver: FakeFacetResolver, manifest_tier: int = 4
) -> tuple[Claim, object, object]:
    """Drive the deep ``profile_contact`` for one facet field with the composition's classifier;
    return the written facet claim + its contact + account. ``manifest_tier`` registers the facet
    source's test manifest at that tier (the shared engine enforces claim tier == manifest tier)."""

    async def scenario() -> tuple[Claim, object, object]:
        clear_resolver_bindings()
        bind_resolver(_FACET_SOURCE, resolver)
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                await register_facet_source(conn, tier=manifest_tier)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)
                await profile_contact(
                    conn,
                    contact_entity_id=contact.id,
                    account_entity_id=account.id,
                    run_id=_RUN,
                    workspace_id=_TENANT,
                    tier="top",
                    field_keys=(FACET_STATED_INTERESTS,),
                    binding_classifier=_composition_classifier(),
                )
                written = (
                    await claims_for(
                        conn,
                        contact.id,
                        FACET_STATED_INTERESTS,
                        scope=WorkspaceScope.for_workspace(_TENANT),
                    )
                )[0]
                return written, contact, account
        finally:
            clear_resolver_bindings()

    return run_async(scenario())


def _verdict(written: Claim, contact: object, account: object) -> IdentityBinding:
    return classify_binding(
        written,
        contact,  # type: ignore[arg-type]
        account_name=account.canonical_name,  # type: ignore[attr-defined]
        account_aliases=tuple(getattr(account, "aliases", ()) or ()),
    ).strength


def test_born_binding_strong_on_verified_handle(require_profiling_db: None) -> None:
    """A facet whose evidence sits on the contact's verified handle is born STRONG — and the born
    column equals the authoritative ``classify_binding`` verdict (M9.4 AC-4, deep path)."""
    written, contact, account = _profile_one_facet(
        resolver=FakeFacetResolver(
            tier=4,
            extractions=[
                {
                    "value_json": ["robotics"],
                    "evidence_span": "Jane CFO at Acme Robotics writes about robotics.",
                    "source_url": "https://linkedin.com/in/jane-cfo",  # the verified handle
                    "confidence": 0.95,
                }
            ],
        )
    )
    assert written.identity_binding is _verdict(written, contact, account)
    assert written.identity_binding is IdentityBinding.STRONG


def test_born_binding_weak_and_unpromotable_on_same_name(require_profiling_db: None) -> None:
    """A lower-tier, name-only, off-handle facet is born WEAK — equal to the authoritative verdict,
    and unpromotable (the same-name trap that never drives outreach)."""
    # Founder-sanctioned re-fixture (claim_tagger consolidation): the tier-3 fake binds behind a
    # genuine tier-3 test manifest — the shared engine enforces claim tier == manifest tier.
    written, contact, account = _profile_one_facet(
        manifest_tier=3,
        resolver=FakeFacetResolver(
            tier=3,  # tier-3 scrape: written-but-weak (a tier-4 same-name is rejected outright)
            extractions=[
                {
                    "value_json": ["gardening"],
                    "evidence_span": "Jane CFO enjoys gardening.",  # name-only, off-handle
                    "source_url": "https://random-blog.example/post",
                    "confidence": 0.9,
                }
            ],
        ),
    )
    assert written.identity_binding is _verdict(written, contact, account)
    assert written.identity_binding is IdentityBinding.WEAK
    assert written.is_promotable is False


def test_composition_classifier_is_the_verification_adapter() -> None:
    """The composition's classifier is the M9 ``classify_binding`` adapter (not the M8 default) — so
    the born binding above is the authoritative verdict, not the placeholder (DB-free check)."""
    from clue_research.api.composition import VerificationBindingClassifier

    assert isinstance(_composition_classifier(), VerificationBindingClassifier)
