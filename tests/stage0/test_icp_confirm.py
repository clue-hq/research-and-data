"""DB-backed tests for M5.2 — confirm → compile → diff (``confirm_icp``).

Covers every confirm-flow acceptance criterion: the confirmed spec is produced by the M3 compiler
(not authored inline) and is reproducible (same ``plan_hash`` on re-compile); edits round-trip
(removed absent, added present) and the suggested-vs-confirmed diff is persisted claim-native;
multiple ICPs compile to independent, separately-versioned specs (D5); a pre-run cost estimate is
returned; and a mock M6 (compile + source-profile serve + rubric score) runs purely from the spec.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ICPCreatedFrom, ICPStatus, ReuseScope
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.icp import (
    compile_field_plan,
    get_active_icp,
    get_icp_version,
    list_icp_keys,
    list_icp_versions,
    rubric_from_slot,
    score,
    serve_source_profile,
)
from clue_research.stage0 import (
    ICP_CONFIRM_DIFF,
    ClientKnowledgeBaseRef,
    ICPProposal,
    ICPProposalEdits,
    confirm_icp,
    synthesize_icps,
)
from clue_research.stage0.fields import (
    CLIENT_CUSTOMER,
    CLIENT_DELIVERED_VALUE,
    CLIENT_DIFFERENTIATOR,
    CLIENT_ICP_EVIDENCE,
    CLIENT_PRODUCT,
    CLIENT_VALUE_PROP,
)
from tests._run_lineage import assert_written_claims_are_attributable
from tests.stage0._fakes import build_client_kb
from tests.stage0.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db")

_CLIENT = "tenant-confirm"

_ASSERTED: dict[str, object] = {
    CLIENT_VALUE_PROP: "We sell a data infrastructure platform",
    CLIENT_PRODUCT: "data infrastructure platform for analytics teams",
    CLIENT_DIFFERENTIATOR: "the fastest query engine",
    CLIENT_DELIVERED_VALUE: "customers buy us for migration speed",
    CLIENT_ICP_EVIDENCE: {"industries": ["data_infra"], "sizes": ["mid-market"], "geos": ["US"]},
    CLIENT_CUSTOMER: [{"name": "BigCo", "domain": "bigco.example"}],
}


async def _floor_proposal(
    conn: AsyncConnection, suffix: str
) -> tuple[ClientKnowledgeBaseRef, ICPProposal]:
    """Build a KB + synthesize the floor proposal; return (ref, proposal)."""
    ref = await build_client_kb(conn, workspace_id=_CLIENT, suffix=suffix, asserted=_ASSERTED)
    (proposal,) = (await synthesize_icps(conn, ref, workspace_id=_CLIENT)).proposals
    return ref, proposal


def test_confirm_creates_compiled_active_spec() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref, proposal = await _floor_proposal(conn, "create")
            confirmation = await confirm_icp(
                conn, proposal, workspace_id=_CLIENT, client_entity_id=ref.client_entity_id
            )

            assert confirmation.ref.icp_key == "primary"
            assert confirmation.ref.icp_version == 1
            assert confirmation.diff.is_empty  # confirmed as proposed → empty diff

            spec = await get_active_icp(conn, _CLIENT, "primary")
            assert spec is not None
            assert spec.status is ICPStatus.ACTIVE
            assert spec.created_from is ICPCreatedFrom.SYNTHESIS  # produced as a synthesis spec
            assert spec.field_keys  # active field set populated
            assert "data_infra" in spec.enabled_packs

            # the plan is the COMPILER's output (not authored inline) and is non-trivial
            plan = await compile_field_plan(conn, spec)
            assert plan.scoring_fields
            assert plan.plan_hash

    run_async(_run())


def test_confirm_is_reproducible_from_pinned_version() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref, proposal = await _floor_proposal(conn, "repro")
            confirmation = await confirm_icp(
                conn, proposal, workspace_id=_CLIENT, client_entity_id=ref.client_entity_id
            )

            pinned = await get_icp_version(conn, _CLIENT, "primary", confirmation.ref.icp_version)
            assert pinned is not None
            # recompiling the pinned (client, icp_key, version) yields the identical plan
            hash_a = (await compile_field_plan(conn, pinned)).plan_hash
            hash_b = (await compile_field_plan(conn, pinned)).plan_hash
            assert hash_a == hash_b

    run_async(_run())


def test_confirm_round_trips_edits_and_persists_diff() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref, proposal = await _floor_proposal(conn, "edits")
            # drop the growth signal (removes its unique narrative field), drop a firmographic
            # field, and add an unrelated registered scoring field.
            edits = ICPProposalEdits(
                removed_signal_classes=("growth",),
                removed_field_keys=("core.primary_domain",),
                added_field_keys=("core.work_email",),
                notes="enterprise focus",
            )
            confirmation = await confirm_icp(
                conn,
                proposal,
                edits,
                workspace_id=_CLIENT,
                client_entity_id=ref.client_entity_id,
            )

            spec = await get_icp_version(conn, _CLIENT, "primary", confirmation.ref.icp_version)
            assert spec is not None
            # added present, removed absent (the growth narrative field leaves with its signal)
            assert "core.work_email" in spec.field_keys
            assert "core.primary_domain" not in spec.field_keys
            assert "account.hiring_velocity_eng" not in spec.field_keys

            diff = confirmation.diff
            assert not diff.is_empty
            assert "core.work_email" in diff.added_field_keys
            assert "core.primary_domain" in diff.removed_field_keys
            assert "account.hiring_velocity_eng" in diff.removed_field_keys
            assert diff.removed_signal_classes == ("growth",)
            assert diff.notes == "enterprise focus"

            # the diff is persisted claim-native (one immutable icp.confirm_diff claim, private)
            scope = WorkspaceScope.for_workspace(_CLIENT)
            diff_claims = await claims_for(
                conn, ref.client_entity_id, ICP_CONFIRM_DIFF, scope=scope
            )
            assert len(diff_claims) == 1
            value = diff_claims[0].value_json
            assert isinstance(value, dict)
            assert value["icp_key"] == "primary"
            assert value["icp_version"] == 1
            persisted = value["diff"]
            assert isinstance(persisted, dict)
            added = persisted["added_field_keys"]
            assert isinstance(added, list)
            assert "core.work_email" in added
            assert diff_claims[0].reuse_scope is ReuseScope.TENANT_PRIVATE
            # FI-2 P2: the diff claim's run is a workspace-level stage-0 run (no project).
            await assert_written_claims_are_attributable(
                conn,
                diff_claims[0].run_id,
                kind="stage0",
                workspace_id=_CLIENT,
                project_id=None,
            )

    run_async(_run())


def test_confirm_multiple_icps_are_independent_specs() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref, proposal = await _floor_proposal(conn, "multi")
            first = await confirm_icp(
                conn, proposal, workspace_id=_CLIENT, client_entity_id=ref.client_entity_id
            )
            second = await confirm_icp(
                conn,
                proposal,
                ICPProposalEdits(icp_key="secondary"),
                workspace_id=_CLIENT,
                client_entity_id=ref.client_entity_id,
            )

            assert first.ref.icp_key == "primary"
            assert second.ref.icp_key == "secondary"
            assert first.ref.icp_version == 1
            assert second.ref.icp_version == 1  # a separate lineage, not a v2 of the first
            assert set(await list_icp_keys(conn, _CLIENT)) == {"primary", "secondary"}
            assert await get_active_icp(conn, _CLIENT, "primary") is not None
            assert await get_active_icp(conn, _CLIENT, "secondary") is not None

    run_async(_run())


def test_confirm_is_idempotent_on_identical_reconfirm() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref, proposal = await _floor_proposal(conn, "idem")
            first = await confirm_icp(
                conn, proposal, workspace_id=_CLIENT, client_entity_id=ref.client_entity_id
            )
            second = await confirm_icp(
                conn, proposal, workspace_id=_CLIENT, client_entity_id=ref.client_entity_id
            )
            # an identical re-confirm reuses the active spec — no v2, no second diff claim
            assert first.ref.icp_version == 1
            assert second.ref.icp_version == 1
            assert len(await list_icp_versions(conn, _CLIENT, "primary")) == 1
            scope = WorkspaceScope.for_workspace(_CLIENT)
            diff_claims = await claims_for(
                conn, ref.client_entity_id, ICP_CONFIRM_DIFF, scope=scope
            )
            assert len(diff_claims) == 1

            # an EDITED re-confirm is genuinely different → it appends a new version (append-only)
            edited = await confirm_icp(
                conn,
                proposal,
                ICPProposalEdits(removed_field_keys=("core.primary_domain",)),
                workspace_id=_CLIENT,
                client_entity_id=ref.client_entity_id,
            )
            assert edited.ref.icp_version == 2
            assert len(await list_icp_versions(conn, _CLIENT, "primary")) == 2

    run_async(_run())


def test_confirm_returns_pre_run_estimate() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref, proposal = await _floor_proposal(conn, "estimate")
            confirmation = await confirm_icp(
                conn, proposal, workspace_id=_CLIENT, client_entity_id=ref.client_entity_id
            )
            est = confirmation.estimate
            # default cost-dial priors: 500 discovered, 20% deep, (5+1)/account + 500/deep account
            assert est.discovered_count == 500
            assert est.projected_deep_count == 100
            assert est.estimated_cost_cents == Decimal("53000")
            assert est.cost_per_account_cents > 0

    run_async(_run())


def test_downstream_consumes_only_the_compiled_spec() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref, proposal = await _floor_proposal(conn, "seam")
            confirmation = await confirm_icp(
                conn, proposal, workspace_id=_CLIENT, client_entity_id=ref.client_entity_id
            )
            spec = await get_icp_version(conn, _CLIENT, "primary", confirmation.ref.icp_version)
            assert spec is not None

            # a mock M6 runs purely from the ICP spec — no access to the proposal internals:
            plan = await compile_field_plan(conn, spec)  # field plan (discovery + Pass A/B fields)
            served = await serve_source_profile(conn, spec)  # source profile (from enabled_packs)
            rubric = rubric_from_slot(spec.scoring_rubric)  # the scoring rubric
            assert plan.scoring_fields
            assert served.packs == ("data_infra",)
            assert served.default  # data_infra authored source priors
            assert rubric is not None
            result = score(rubric, {}, entity_id=ref.client_entity_id)  # scores with no data → 0.0
            assert result.fit_score == 0.0
            assert result.rubric_version == rubric.version

    run_async(_run())
