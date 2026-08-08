"""FI-2 slice 2, Task 1 — the C7 ``allowed_run_ids`` supply is ``run_lineage``, and only that.

Before this slice the C7 read family pinned its ``project_run_pinned`` routes with a hand-assembled
tuple — ``(request.project_run_id, scope.account_run.id)`` — written out at four separate sites. It
was a *second* claim→project attribution mechanism living alongside ``run_lineage``, and it was
incomplete: an M8D research run stamps every claim with a **per-tool-call derived** run id (see
``clue_api.exa_entity_research_tools``), which is registered in ``run_lineage`` under its project
run but appears in neither leg of that tuple. Those claims were invisible to the pinned sections.

The change has exactly two delta classes against that tuple, and they move in opposite directions:

* **Gained — M8D per-tool-call derived runs.** They are registered in ``run_lineage`` under their
  project run and were in neither leg of the tuple, so they now appear in the pinned sections.
  A fix; proved exactly below.
* **Preserved, not lost — the two legs the tuple carried.** ``account_run.id`` (leg 2) is now
  registered at its own mint site (``durable.account_run``), and the project run's *own* id (leg 1
  — the shape the committee and enrichment writers stamp) is registered by those live writers and,
  for rows written before FI-2, by ``project_lens_backfill``'s ``committee_lineage`` source. On a
  pre-FI-2 database the backfill is what makes ``legacy − lineage == ∅`` true; without it the
  committee professional pack, the one production CONTACT ``project_run_pinned`` family, would
  drop out of the lens.

This module is the equivalence proof the migration is gated on:

* :func:`test_lineage_supply_is_byte_identical_to_the_legacy_tuple_supply` — where the legacy supply
  was complete (a direct claim and a derived root keyed on the account run, plus a
  foreign-project-run pair that must stay out of both reader paths), the composed view is
  **byte-identical** under both supplies.
* :func:`test_lineage_supply_adds_exactly_the_m8d_derived_run_claims` — the documented delta: add
  M8D-shaped derived-run claims and the lineage supply gains **exactly** those statements while the
  legacy supply still cannot see them. A fix, deliberately tested, not a silent behaviour change.
* :func:`test_a_resolvable_scope_always_supplies_its_account_run` — the non-emptiness invariant the
  migration rests on: a C7 scope resolves only when its ``account_run`` row exists, and that row's
  mint site registers lineage, so the supply is never empty for a view that can be served.

Both C7 reader paths are driven: the direct-claim reader *and* the derived-claim reader, whose
pinned filters are written differently in ``claimstore.research_view_queries`` (an empty supply
drops everything on the first and nothing on the second — see the residual in the task report).
"""

from __future__ import annotations

from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.research_view_readers import (
    ResearchViewScopeResolver,
    ResolvedResearchViewScope,
)
from clue_api.research_view_runtime import ProductionResearchViewComposer
from clue_core import (
    AccountStatus,
    Claim,
    ClaimFlavor,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    PassKind,
    ProjectPhase,
    ProjectRunId,
    ResearchMode,
    ResearchSectionKind,
    ResearchStatement,
    ResearchSubjectRef,
    ResearchSupportRef,
    ResearchSupportRole,
    ResearchView,
    ResearchViewReadRequest,
    ReuseScope,
    RunId,
    VerificationStatus,
    account_claim,
    new_operation_id,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import (
    DerivationStore,
    ResearchViewFieldRoute,
    SeedField,
    WorkspaceScope,
    insert_claim,
    load_pack,
    record_run_lineage,
    record_verification,
    runs_for_project_run,
)
from clue_research.durable import (
    AccountRunStatus,
    ensure_project_run,
    insert_account_run,
)
from clue_research.identity import insert_account_entity, stamp_reuse
from clue_spine import create_brand, create_product, create_project
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WORKSPACE = "c7-lens-equivalence"
_PRODUCT = "prd-c7-lens"
_ICP_KEY = "enterprise"
_PINNED_LEGACY = "account.resonance.lens_probe_legacy"
_PINNED_DERIVED = "account.resonance.lens_probe_derived"
_PINNED_ROOT = "account.resonance.lens_probe_root"
# Mirrors ``clue_api.exa_entity_research_tools``' per-tool-call run derivation: the id every M8D
# claim actually carries, which the legacy ``(project_run_id, account_run.id)`` tuple never held.
_TOOL_CALL_NAMESPACE = uuid5(NAMESPACE_URL, "clue-hq:test:c7-lens:tool-call")


class _LegacyTupleScopeResolver:
    """The pre-slice-2 supply, preserved here so the migration can be proved against it.

    Resolves the production scope, then overwrites its lineage-backed ``allowed_run_ids`` with the
    exact two-element tuple the four supplier sites used to hand-assemble.
    """

    def __init__(self) -> None:
        self._delegate = ResearchViewScopeResolver()

    async def resolve(
        self, conn: AsyncConnection, request: ResearchViewReadRequest
    ) -> ResolvedResearchViewScope:
        scope = await self._delegate.resolve(conn, request)
        return replace(
            scope,
            allowed_run_ids=(str(request.project_run_id), str(scope.account_run.id)),
        )


class _Fixture:
    def __init__(
        self,
        *,
        request: ResearchViewReadRequest,
        account_id: EntityId,
        account_run_id: RunId,
        project_id: str,
    ) -> None:
        self.request = request
        self.account_id = account_id
        self.account_run_id = account_run_id
        self.project_id = project_id


async def _seed(conn: AsyncConnection) -> _Fixture:
    """One project run, one account, one account run, and three ``project_run_pinned`` routes.

    Two direct routes and one **derived** route: the migrated supply feeds both readers, and their
    pinned filters are written differently in ``research_view_queries.py`` (the direct one drops a
    non-matching claim, the derived one skips it), so the byte-equivalence proof has to drive both.
    """

    await seed_workspace(conn, _WORKSPACE)
    brand = await create_brand(conn, workspace_id=_WORKSPACE, name="C7 lens brand")
    await create_product(
        conn,
        workspace_id=_WORKSPACE,
        brand_id=brand.brand_id,
        product_id=_PRODUCT,
        name="C7 lens product",
    )
    project = await create_project(
        conn,
        workspace_id=_WORKSPACE,
        brand_id=brand.brand_id,
        product_id=_PRODUCT,
        name="C7 lens project",
    )
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=_WORKSPACE,
        icp_key=_ICP_KEY,
        icp_version=1,
        phase=ProjectPhase.HANDOFF,
    )
    account_id = await insert_account_entity(
        conn,
        canonical_name="C7 Lens Target",
        primary_domain="c7-lens.example",
        status=AccountStatus.ACTIVE,
        workspace_id=_WORKSPACE,
    )
    account_run_id = new_run_id()
    await insert_account_run(
        conn,
        account_run_id=account_run_id,
        project_run_id=project_run_id,
        entity_id=account_id,
        tier="top",
        status=AccountRunStatus.DONE,
    )
    await load_pack(
        conn,
        tuple(
            SeedField(
                field_def=FieldDef(
                    field_key=field_key,
                    value_type="str",
                    pass_kind=PassKind.DEEP,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                ),
                value_schema={"type": "string"},
                research_view_route=ResearchViewFieldRoute(
                    field_key=field_key,
                    entity_type=EntityType.ACCOUNT,
                    section_kind=ResearchSectionKind.INSIGHTS,
                    ordinal=200 + index,
                    context_scope="project_run_pinned",
                ),
            )
            for index, field_key in enumerate((_PINNED_LEGACY, _PINNED_DERIVED, _PINNED_ROOT))
        ),
    )
    request = ResearchViewReadRequest(
        workspace_id=_WORKSPACE,
        project_id=project.project_id,
        project_run_id=project_run_id,
        subject_entity_id=account_id,
        subject_entity_type=EntityType.ACCOUNT,
    )
    return _Fixture(
        request=request,
        account_id=account_id,
        account_run_id=account_run_id,
        project_id=project.project_id,
    )


async def _write_claim(
    conn: AsyncConnection,
    fixture: _Fixture,
    *,
    field_key: str,
    value: str,
    run_id: RunId,
) -> UUID:
    claim = account_claim(
        entity_id=fixture.account_id,
        field_key=field_key,
        value_json=value,
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        confidence=0.9,
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url=f"https://c7-lens.example/{field_key}",
        evidence_span=value,
    )
    claim_id = await insert_claim(conn, stamp_reuse(claim, workspace_id=_WORKSPACE))
    await record_verification(conn, claim_id, status=VerificationStatus.VERIFIED)
    return UUID(str(claim_id))


async def _write_derived_root(
    conn: AsyncConnection,
    fixture: _Fixture,
    *,
    value: str,
    run_id: RunId,
    support_claim_id: UUID,
) -> UUID:
    """A derived root on the pinned derived route — the ``DbDerivedClaimReader``'s input."""

    derived = Claim(
        entity_id=fixture.account_id,
        entity_type=EntityType.ACCOUNT,
        field_key=_PINNED_ROOT,
        value_json=value,
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.8,
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        claim_flavor=ClaimFlavor.DERIVED,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=_WORKSPACE,
        verification_status=VerificationStatus.VERIFIED,
    )
    await DerivationStore().create(
        conn,
        derived,
        ResearchSubjectRef(
            entity_id=fixture.account_id,
            entity_type=EntityType.ACCOUNT,
            canonical_entity_version=1,
        ),
        (
            ResearchSupportRef(
                claim_id=ClaimId(support_claim_id),
                role=ResearchSupportRole.DIRECT_EVIDENCE,
                ordinal=0,
            ),
        ),
        workspace_id=_WORKSPACE,
        operation_id=new_operation_id(),
        scope=WorkspaceScope.for_workspace(_WORKSPACE),
    )
    return UUID(str(derived.id))


async def _foreign_project_run(conn: AsyncConnection, fixture: _Fixture) -> RunId:
    """A second project run of the SAME project, with its own registered research run.

    Its claims must stay out of this project run's pinned sections under both supplies: the pin is
    project-**run**-scoped, and migrating to lineage must not silently widen it to the project.
    """

    other_project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=other_project_run_id,
        project_id=fixture.project_id,
        workspace_id=_WORKSPACE,
        icp_key=_ICP_KEY,
        icp_version=1,
        phase=ProjectPhase.HANDOFF,
    )
    foreign_run_id = new_run_id()
    await record_run_lineage(
        conn,
        run_id=UUID(str(foreign_run_id)),
        workspace_id=_WORKSPACE,
        kind="entity_research",
        project_id=fixture.project_id,
        project_run_id=UUID(str(other_project_run_id)),
    )
    return foreign_run_id


def _payload(view: ResearchView) -> str:
    """The full view payload minus the one non-deterministic field (``composed_at``)."""

    return view.model_dump_json(exclude={"composed_at"})


def _statement_claim_ids(view: ResearchView) -> set[UUID]:
    return {
        UUID(str(item.claim_id))
        for section in view.sections
        for item in section.items
        if isinstance(item, ResearchStatement)
    }


async def _compose_both(
    conn: AsyncConnection, request: ResearchViewReadRequest
) -> tuple[ResearchView, ResearchView]:
    conn_factory = conn_session_factory(conn)
    legacy = await ProductionResearchViewComposer(
        conn_factory=conn_factory,
        scope_resolver=_LegacyTupleScopeResolver(),  # type: ignore[arg-type]
    ).compose(request)
    lineage = await ProductionResearchViewComposer(conn_factory=conn_factory).compose(request)
    return legacy, lineage


def test_lineage_supply_is_byte_identical_to_the_legacy_tuple_supply() -> None:
    """Where the legacy tuple was complete, the lineage supply changes nothing at all."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed(conn)
            foreign_run_id = await _foreign_project_run(conn, fixture)
            support_id = await _write_claim(
                conn,
                fixture,
                field_key=_PINNED_LEGACY,
                value="Pinned to this project run's account run.",
                run_id=fixture.account_run_id,
            )
            foreign_support_id = await _write_claim(
                conn,
                fixture,
                field_key=_PINNED_DERIVED,
                value="Belongs to another project run of the same project.",
                run_id=foreign_run_id,
            )
            # The derived reader's pinned filter, driven both ways: one root this project run may
            # see, one it may not.
            await _write_derived_root(
                conn,
                fixture,
                value="Derived under this project run's account run.",
                run_id=fixture.account_run_id,
                support_claim_id=support_id,
            )
            await _write_derived_root(
                conn,
                fixture,
                value="Derived under another project run of the same project.",
                run_id=foreign_run_id,
                support_claim_id=foreign_support_id,
            )

            legacy, lineage = await _compose_both(conn, fixture.request)

            assert _payload(legacy) == _payload(lineage)
            assert legacy.source_state_sha256 == lineage.source_state_sha256
            # The account-run claims are served on BOTH reader paths (not a vacuously empty
            # comparison), and the other project run's claims are served by neither supply.
            values = {
                item.value_json
                for section in lineage.sections
                for item in section.items
                if isinstance(item, ResearchStatement)
            }
            assert "Pinned to this project run's account run." in values
            assert "Derived under this project run's account run." in values
            assert "Belongs to another project run of the same project." not in values
            assert "Derived under another project run of the same project." not in values

    run_async(scenario())


def test_lineage_supply_adds_exactly_the_m8d_derived_run_claims() -> None:
    """The documented delta: per-tool-call M8D runs become visible, and nothing else changes.

    The legacy tuple held only ``(project_run_id, account_run.id)``, so a claim stamped with an
    M8D per-tool-call derived run id — registered in ``run_lineage`` under this very project run —
    was invisible to the pinned sections. Lineage sees it, on both reader paths (a direct claim and
    a derived root). The assertion is exact in both directions: the lineage view gains exactly those
    statements and loses none.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed(conn)
            legacy_claim_id = await _write_claim(
                conn,
                fixture,
                field_key=_PINNED_LEGACY,
                value="Pinned to this project run's account run.",
                run_id=fixture.account_run_id,
            )

            before_legacy, before_lineage = await _compose_both(conn, fixture.request)
            assert _payload(before_legacy) == _payload(before_lineage)
            assert _statement_claim_ids(before_lineage) == {legacy_claim_id}

            derived_run_id = RunId(
                uuid5(_TOOL_CALL_NAMESPACE, f"{fixture.account_run_id}:tool-call-1")
            )
            await record_run_lineage(
                conn,
                run_id=UUID(str(derived_run_id)),
                workspace_id=_WORKSPACE,
                kind="entity_research",
                project_id=fixture.project_id,
                project_run_id=UUID(str(fixture.request.project_run_id)),
            )
            tool_call_claim_id = await _write_claim(
                conn,
                fixture,
                field_key=_PINNED_DERIVED,
                value="Written by an M8D per-tool-call research run.",
                run_id=derived_run_id,
            )
            tool_call_root_id = await _write_derived_root(
                conn,
                fixture,
                value="Synthesized by an M8D per-tool-call research run.",
                run_id=derived_run_id,
                support_claim_id=tool_call_claim_id,
            )

            legacy, lineage = await _compose_both(conn, fixture.request)

            assert _statement_claim_ids(legacy) == {legacy_claim_id}
            assert _statement_claim_ids(lineage) == {
                legacy_claim_id,
                tool_call_claim_id,
                tool_call_root_id,
            }
            assert _statement_claim_ids(lineage) - _statement_claim_ids(legacy) == {
                tool_call_claim_id,
                tool_call_root_id,
            }
            assert _statement_claim_ids(legacy) - _statement_claim_ids(lineage) == set()
            # The legacy payload is unchanged by the derived claim — it truly could not see it.
            assert _payload(legacy) == _payload(before_legacy)

    run_async(scenario())


def test_a_resolvable_scope_always_supplies_its_account_run() -> None:
    """The non-emptiness invariant: an account run registers lineage at its own mint site.

    An empty supply would leave the pinned routes with nothing to pin against, so the migration
    depends on this: a C7 scope resolves only when the ``account_run`` row exists, and creating
    that row attributes it to the project run.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed(conn)
            supplied = await runs_for_project_run(
                conn,
                workspace_id=_WORKSPACE,
                project_run_id=ProjectRunId(fixture.request.project_run_id),
            )
            assert RunId(UUID(str(fixture.account_run_id))) in supplied

            scope = await ResearchViewScopeResolver().resolve(conn, fixture.request)
            assert scope.allowed_run_ids
            assert str(fixture.account_run_id) in scope.allowed_run_ids
            assert scope.allowed_run_ids == tuple(str(run_id) for run_id in supplied)

    run_async(scenario())
