"""M8.4 contact profiling worker — end-to-end (DB-gated) + AspectWorker conformance.

profile_contact fills the facet gaps (tagging every claim), returns handoff-shaped profile_claims,
and requests facet sub-workers only within the per-tier recursion budget.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AspectContext,
    AspectWorker,
    IdentityBinding,
    ProfileClaimView,
    WorkerStatus,
)
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.profiling.contact import ContactProfileAspectWorker, profile_contact
from clue_research.profiling.fields import FACET_STATED_INTERESTS
from clue_research.sources import bind_resolver, clear_resolver_bindings

from ..conftest import (
    TEST_FACET_SOURCE,
    FakeFacetResolver,
    insert_test_account,
    insert_test_contact,
    register_facet_source,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = UUID("66666666-6666-6666-6666-666666666666")
_TENANT = "acme"
_FACET_SOURCE = TEST_FACET_SOURCE


_DEFAULT_SPAN = object()  # sentinel: distinguishes "use the default span" from "explicitly None"


def _resolver(
    values: list[str], *, on_handle: bool = True, span: object = _DEFAULT_SPAN
) -> FakeFacetResolver:
    evidence = f"Jane CFO: {', '.join(values)}." if span is _DEFAULT_SPAN else span
    return FakeFacetResolver(
        tier=4,
        extractions=[
            {
                "value_json": values,
                "evidence_span": evidence,
                "source_url": "https://linkedin.com/in/jane-cfo"
                if on_handle
                else "https://blog.x/p",
                "confidence": 0.95,
            }
        ],
    )


def test_aspect_worker_conformance() -> None:
    worker = ContactProfileAspectWorker(session_factory=rollback_conn)
    assert isinstance(worker, AspectWorker)
    assert worker.aspect == "contact.facet"


def test_profile_contact_tags_every_claim(require_profiling_db: None) -> None:
    async def scenario() -> None:
        clear_resolver_bindings()
        bind_resolver(_FACET_SOURCE, _resolver(["robotics", "trail running"]))
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                await register_facet_source(conn)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)
                result = await profile_contact(
                    conn,
                    contact_entity_id=contact.id,
                    account_entity_id=account.id,
                    run_id=_RUN,
                    workspace_id=_TENANT,
                    tier="top",
                    field_keys=[FACET_STATED_INTERESTS],
                )
                assert result.fields_filled == 1
                assert len(result.profile_claims) == 1
                view = result.profile_claims[0]
                assert isinstance(view, ProfileClaimView)
                # every contact claim carries BOTH governance tags (AC).
                assert view.identity_binding is not None
                assert view.use_class is not None
                assert view.identity_binding is IdentityBinding.STRONG  # verified handle
                # the written claim agrees.
                written = await claims_for(
                    conn,
                    contact.id,
                    FACET_STATED_INTERESTS,
                    scope=WorkspaceScope.for_workspace(_TENANT),
                )
                assert len(written) == 1
                assert written[0].identity_binding is not None
                assert written[0].use_class is not None
        finally:
            clear_resolver_bindings()

    run_async(scenario())


def test_tier4_without_span_stays_unverified(require_profiling_db: None) -> None:
    async def scenario() -> None:
        clear_resolver_bindings()
        bind_resolver(_FACET_SOURCE, _resolver(["robotics"], span=None))  # tier-4, no evidence span
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                await register_facet_source(conn)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)
                await profile_contact(
                    conn,
                    contact_entity_id=contact.id,
                    account_entity_id=account.id,
                    run_id=_RUN,
                    workspace_id=_TENANT,
                    tier="top",
                    field_keys=[FACET_STATED_INTERESTS],
                )
                scope = WorkspaceScope.for_workspace(_TENANT)
                written = (await claims_for(conn, contact.id, FACET_STATED_INTERESTS, scope=scope))[
                    0
                ]
                assert written.evidence_span is None
                assert written.is_promotable is False  # tier-4 without a span never promotes
        finally:
            clear_resolver_bindings()

    run_async(scenario())


def test_facet_subworker_requested_only_with_budget(require_profiling_db: None) -> None:
    async def scenario() -> None:
        clear_resolver_bindings()
        # A rich facet: a list with >= facet_subworker_min_values (3) items.
        bind_resolver(_FACET_SOURCE, _resolver(["robotics", "running", "chess"]))
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                await register_facet_source(conn)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)

                with_budget = await profile_contact(
                    conn,
                    contact_entity_id=contact.id,
                    account_entity_id=account.id,
                    run_id=_RUN,
                    workspace_id=_TENANT,
                    tier="top",
                    field_keys=[FACET_STATED_INTERESTS],
                    facet_subworker_budget=2,
                )
                assert len(with_budget.facet_requests) == 1
                assert with_budget.facet_requests[0]["aspect"] == FACET_STATED_INTERESTS

                # idempotent re-run with no budget → no sub-worker requested.
                no_budget = await profile_contact(
                    conn,
                    contact_entity_id=contact.id,
                    account_entity_id=account.id,
                    run_id=_RUN,
                    workspace_id=_TENANT,
                    tier="low",
                    field_keys=[FACET_STATED_INTERESTS],
                    facet_subworker_budget=0,
                )
                assert no_budget.facet_requests == ()
        finally:
            clear_resolver_bindings()

    run_async(scenario())


def test_aspect_worker_research_bridges_context(require_profiling_db: None) -> None:
    async def scenario() -> None:
        clear_resolver_bindings()
        bind_resolver(_FACET_SOURCE, _resolver(["robotics", "running", "chess"]))
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                await register_facet_source(conn)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)

                @asynccontextmanager
                async def session_factory() -> AsyncIterator[AsyncConnection]:
                    yield conn

                worker = ContactProfileAspectWorker(session_factory=session_factory)
                ctx = AspectContext(
                    entity_id=contact.id,
                    project_run_id="77777777-7777-7777-7777-777777777777",
                    run_id=_RUN,
                    tier="top",
                    aspect="contact.facet",
                    field_keys=(FACET_STATED_INTERESTS,),
                    depth=0,
                    params={
                        "account_entity_id": str(account.id),
                        "workspace_id": _TENANT,
                        "icp_key": "default",
                        "icp_version": 1,
                        "max_facet_workers_per_aspect": 2,
                    },
                )
                result = await worker.research(ctx)
                assert result.status is WorkerStatus.OK
                assert result.aspect == "contact.facet"
                assert len(result.claim_refs) == 1
                assert result.detail["fields_filled"] == 1
                assert result.detail["facet_requests"]  # budget>0 + rich facet → requested
        finally:
            clear_resolver_bindings()

    run_async(scenario())
