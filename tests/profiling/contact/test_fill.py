"""M8.4 facet-aware fill (DB-gated).

Drives a fake facet resolver and asserts M8.4 *re-tags* every claim with the authoritative per-claim
identity_binding + use_class (overriding the resolver's placeholders) before writing — and that a
resolver-absent field yields a correct flagged-empty output.
"""

from __future__ import annotations

from uuid import UUID

from clue_core import IdentityBinding, ResearchMode, UseClass
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.profiling.contact.fill import fill_contact_field
from clue_research.profiling.fields import FACET_STATED_INTERESTS
from clue_research.sources import bind_resolver, clear_resolver_bindings

from ..conftest import (
    FakeFacetResolver,
    icp_spec,
    insert_test_account,
    insert_test_contact,
    register_facet_source,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = UUID("55555555-5555-5555-5555-555555555555")
_TENANT = "acme"
# The seeded facet fields' tier_plan source (resolver-absent in prod; we bind a fake here).
_FACET_SOURCE = "exa_deep"


async def _field_def(conn, field_key):  # type: ignore[no-untyped-def]
    from clue_research.claimstore import get_field

    field = await get_field(conn, field_key)
    assert field is not None
    return field


def test_no_resolver_yields_flagged_empty(require_profiling_db: None) -> None:
    async def scenario() -> None:
        clear_resolver_bindings()
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            field = await _field_def(conn, FACET_STATED_INTERESTS)
            result = await fill_contact_field(
                conn, contact, account, field, run_id=_RUN, workspace_id=_TENANT, tier="top"
            )
            assert result.claim_refs == []
            assert result.stop_reason == "no_resolver"

    run_async(scenario())


def test_fill_retags_binding_and_use_class(require_profiling_db: None) -> None:
    """A religious interest on the contact's verified handle → written STRONG + SENSITIVE, over the
    resolver's placeholder (WEAK + professional)."""

    async def scenario() -> None:
        clear_resolver_bindings()
        resolver = FakeFacetResolver(
            tier=4,
            extractions=[
                {
                    "value_json": ["bible study", "robotics"],
                    "evidence_span": "Jane CFO is active in her church and Bible study.",
                    "source_url": "https://linkedin.com/in/jane-cfo",  # the verified handle
                    "confidence": 0.95,
                }
            ],
        )
        bind_resolver(_FACET_SOURCE, resolver)
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                await register_facet_source(conn)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)
                field = await _field_def(conn, FACET_STATED_INTERESTS)
                result = await fill_contact_field(
                    conn, contact, account, field, run_id=_RUN, workspace_id=_TENANT, tier="top"
                )
                assert len(result.claim_refs) == 1
                written = (
                    await claims_for(
                        conn,
                        contact.id,
                        FACET_STATED_INTERESTS,
                        scope=WorkspaceScope.for_workspace(_TENANT),
                    )
                )[0]
                # M8.4 re-tagged: verified handle → STRONG; religious marker → SENSITIVE.
                assert written.identity_binding is IdentityBinding.STRONG
                assert written.use_class is UseClass.SENSITIVE
                assert written.research_mode is ResearchMode.CONTACT_PROFILING
                assert written.source_key == _FACET_SOURCE
                assert written.run_id == _RUN
                assert written.workspace_id == _TENANT
        finally:
            clear_resolver_bindings()

    run_async(scenario())


def test_fill_rejects_tier4_same_name_stranger(require_profiling_db: None) -> None:
    """Target-lock (Decision 13): a tier-4 (LLM) facet claim that only name-matches a stranger is
    rejected BEFORE write — nothing lands on the contact's entity_id."""

    async def scenario() -> None:
        resolver = FakeFacetResolver(
            tier=4,
            extractions=[
                {
                    "value_json": ["gardening"],
                    "evidence_span": "Jane CFO enjoys gardening.",  # name only, off-handle blog
                    "source_url": "https://random-blog.example/post",
                    "confidence": 0.9,
                }
            ],
        )
        bind_resolver(_FACET_SOURCE, resolver)
        async with rollback_conn() as conn:
            await seed_packs(conn)
            await register_facet_source(conn)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            field = await _field_def(conn, FACET_STATED_INTERESTS)
            result = await fill_contact_field(
                conn, contact, account, field, run_id=_RUN, workspace_id=_TENANT, tier="top"
            )
            assert result.claim_refs == []  # tier-4 same-name claim never written
            written = await claims_for(
                conn,
                contact.id,
                FACET_STATED_INTERESTS,
                scope=WorkspaceScope.for_workspace(_TENANT),
            )
            assert written == []

    run_async(scenario())


def test_fill_writes_lower_tier_weak_unpromotable(require_profiling_db: None) -> None:
    """A lower-tier (≤3) WEAK claim is written-but-unpromotable (it has a real source M9 can
    re-judge) — unlike a tier-4 same-name claim, which is rejected outright (Decisions 7/10)."""

    async def scenario() -> None:
        resolver = FakeFacetResolver(
            tier=3,  # a tier-3 scrape, not LLM synthesis
            extractions=[
                {
                    "value_json": ["gardening"],
                    "evidence_span": "Jane CFO enjoys gardening.",  # name only, off-handle
                    "source_url": "https://random-blog.example/post",
                    "confidence": 0.9,
                }
            ],
        )
        bind_resolver(_FACET_SOURCE, resolver)
        async with rollback_conn() as conn:
            await seed_packs(conn)
            # Founder-sanctioned re-fixture (claim_tagger consolidation): the shared engine
            # enforces claim.source_tier == manifest.tier, so the tier-3 fake now binds behind a
            # genuine tier-3 manifest (a version-bumped test-local variant of the source key)
            # instead of lying under the tier-4 seed. Product assertions below are unchanged.
            await register_facet_source(conn, tier=3)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            field = await _field_def(conn, FACET_STATED_INTERESTS)
            result = await fill_contact_field(
                conn, contact, account, field, run_id=_RUN, workspace_id=_TENANT, tier="top"
            )
            assert len(result.claim_refs) == 1
            written = (
                await claims_for(
                    conn,
                    contact.id,
                    FACET_STATED_INTERESTS,
                    scope=WorkspaceScope.for_workspace(_TENANT),
                )
            )[0]
            assert written.identity_binding is IdentityBinding.WEAK  # same-name trap → weak
            assert written.is_promotable is False  # weak contact claim never promotes

    run_async(scenario())


def test_facet_claims_are_workspace_scoped(require_profiling_db: None) -> None:
    """A facet claim is tenant-private: visible to its tenant, never another (substrate §2)."""

    async def scenario() -> None:
        bind_resolver(
            _FACET_SOURCE,
            FakeFacetResolver(
                tier=4,
                extractions=[
                    {
                        "value_json": ["robotics"],
                        "evidence_span": "Jane CFO at Acme Robotics: robotics.",
                        "source_url": "https://linkedin.com/in/jane-cfo",
                        "confidence": 0.95,
                    }
                ],
            ),
        )
        async with rollback_conn() as conn:
            await seed_packs(conn)
            await register_facet_source(conn)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            field = await _field_def(conn, FACET_STATED_INTERESTS)
            await fill_contact_field(
                conn, contact, account, field, run_id=_RUN, workspace_id=_TENANT, tier="top"
            )
            mine = await claims_for(
                conn,
                contact.id,
                FACET_STATED_INTERESTS,
                scope=WorkspaceScope.for_workspace(_TENANT),
            )
            assert len(mine) == 1
            other = await claims_for(
                conn,
                contact.id,
                FACET_STATED_INTERESTS,
                scope=WorkspaceScope.for_workspace("other_co"),
            )
            assert other == []  # another tenant never sees this private facet claim

    run_async(scenario())


def test_planner_declines_when_spec_authorizes_no_source(require_profiling_db: None) -> None:
    """When an ICP spec is supplied, M8.4 routes through the Source Planner — a bound resolver the
    planner does NOT authorize is not consulted (planner-gating), so the field stays flagged-empty.
    Contrast: with spec=None the field's tier_plan drives the (bound) resolver directly."""

    async def scenario() -> None:
        bind_resolver(
            _FACET_SOURCE,
            FakeFacetResolver(
                tier=4,
                extractions=[
                    {
                        "value_json": ["robotics"],
                        "evidence_span": "Jane CFO: robotics.",
                        "source_url": "https://linkedin.com/in/jane-cfo",
                        "confidence": 0.95,
                    }
                ],
            ),
        )
        async with rollback_conn() as conn:
            await seed_packs(conn)
            await register_facet_source(conn)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            field = await _field_def(conn, FACET_STATED_INTERESTS)
            # The bare ICP has no source profile → the planner authorizes nothing for this field.
            gated = await fill_contact_field(
                conn,
                contact,
                account,
                field,
                run_id=_RUN,
                workspace_id=_TENANT,
                tier="low",
                spec=icp_spec(),
            )
            assert gated.claim_refs == []
            # Sanity: with no spec, the field's tier_plan drives the (bound) resolver directly.
            direct = await fill_contact_field(
                conn, contact, account, field, run_id=_RUN, workspace_id=_TENANT, tier="top"
            )
            assert len(direct.claim_refs) == 1

    run_async(scenario())


def test_fill_is_idempotent(require_profiling_db: None) -> None:
    async def scenario() -> None:
        clear_resolver_bindings()
        resolver = FakeFacetResolver(
            tier=4,
            extractions=[
                {
                    "value_json": ["robotics"],
                    "evidence_span": "Jane CFO at Acme Robotics writes about robotics.",
                    "source_url": "https://linkedin.com/in/jane-cfo",
                    "confidence": 0.95,
                }
            ],
        )
        bind_resolver(_FACET_SOURCE, resolver)
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                await register_facet_source(conn)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)
                field = await _field_def(conn, FACET_STATED_INTERESTS)
                first = await fill_contact_field(
                    conn, contact, account, field, run_id=_RUN, workspace_id=_TENANT, tier="top"
                )
                second = await fill_contact_field(
                    conn, contact, account, field, run_id=_RUN, workspace_id=_TENANT, tier="top"
                )
                assert first.claim_refs == second.claim_refs  # reused, not double-written
                live = await claims_for(
                    conn,
                    contact.id,
                    FACET_STATED_INTERESTS,
                    scope=WorkspaceScope.for_workspace(_TENANT),
                )
                assert len(live) == 1
        finally:
            clear_resolver_bindings()

    run_async(scenario())
