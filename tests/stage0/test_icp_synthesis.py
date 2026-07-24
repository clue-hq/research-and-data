"""DB-backed tests for M5.2 — ICP synthesis (``synthesize_icps``).

Covers: the deterministic floor returns ≥1 proposal with all six Doc B §3 elements, each justified
by **real** Client-KB claim ids (no fabrication); the LLM path is config-bounded (off-set field/pack
names are dropped) and can split into multiple ICPs (D5); any LLM/parse failure degrades to the
floor (the config is always the floor — the no-LLM path still completes).
"""

from __future__ import annotations

import json

import pytest

from clue_research.stage0 import read_client_kb_claims, synthesize_icps
from clue_research.stage0.fields import (
    CLIENT_CUSTOMER,
    CLIENT_DELIVERED_VALUE,
    CLIENT_DIFFERENTIATOR,
    CLIENT_ICP_EVIDENCE,
    CLIENT_PRODUCT,
    CLIENT_VALUE_PROP,
)
from clue_research.stage0.icp_types import ICPProposal
from tests.stage0._fakes import FakeGateway, build_client_kb
from tests.stage0.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db")

_CLIENT = "tenant-synth"

# A client whose own prose ("data infrastructure") matches the data_infra starter pack.
_ASSERTED: dict[str, object] = {
    CLIENT_VALUE_PROP: "We sell a data infrastructure platform",
    CLIENT_PRODUCT: "data infrastructure platform for analytics teams",
    CLIENT_DIFFERENTIATOR: "the fastest query engine",
    CLIENT_DELIVERED_VALUE: "customers buy us for migration speed",
    CLIENT_ICP_EVIDENCE: {"industries": ["data_infra"], "sizes": ["mid-market"], "geos": ["US"]},
    CLIENT_CUSTOMER: [{"name": "BigCo", "domain": "bigco.example"}],
}


def _all_justifying(proposal: ICPProposal) -> set[object]:
    """Every claim id cited across the proposal's six elements."""
    ids: set[object] = set(proposal.justifying_claim_ids)
    ids |= set(proposal.firmographic.justifying_claim_ids)
    ids |= set(proposal.source_profile.justifying_claim_ids)
    for t in proposal.technographic:
        ids |= set(t.justifying_claim_ids)
    for s in proposal.candidate_signals:
        ids |= set(s.justifying_claim_ids)
    for w in proposal.rubric.weights:
        ids |= set(w.justifying_claim_ids)
    for seed in proposal.seed_accounts:
        ids |= set(seed.justifying_claim_ids)
    return ids


def test_floor_proposal_has_all_six_elements() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await build_client_kb(
                conn, workspace_id=_CLIENT, suffix="floor", asserted=_ASSERTED
            )
            proposals = await synthesize_icps(conn, ref, workspace_id=_CLIENT)

            assert len(proposals) >= 1
            p = proposals[0]
            # all six elements: 1 firmographic, 2 technographic (matched to data_infra from the
            # client prose), 3 two-tier signals, 4 seeds (M5.4's → empty), 5 source, 6 rubric
            assert p.firmographic.field_keys
            assert p.firmographic.industry == "data_infra"
            assert any(t.pack_key == "data_infra" for t in p.technographic)
            assert p.candidate_signals
            assert p.seed_accounts == ()
            assert p.source_profile.packs == ("data_infra",)
            assert p.rubric.weights

    run_async(_run())


def test_floor_justifying_ids_are_real_client_claims() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await build_client_kb(
                conn, workspace_id=_CLIENT, suffix="just", asserted=_ASSERTED
            )
            kb = await read_client_kb_claims(
                conn, ref.client_entity_id, workspace_id=_CLIENT, version=ref.client_kb_version
            )
            real_ids = {claim.id for claim in kb.values()}
            assert real_ids  # the KB is non-empty

            (proposal,) = await synthesize_icps(conn, ref, workspace_id=_CLIENT)
            cited = _all_justifying(proposal)
            assert cited  # every proposal cites its evidence
            # no element is justified by an invented id — every citation is a real client claim
            assert cited <= real_ids

    run_async(_run())


def _two_icp_json() -> str:
    """An LLM response naming two ICPs, with off-set names sprinkled in to prove the hard guard."""
    return json.dumps(
        {
            "icps": [
                {
                    "icp_key": "enterprise",
                    "label": "Enterprise data infra",
                    "firmographic": {"industry": "data infra", "size_band": "enterprise"},
                    "firmographic_field_keys": ["core.employee_count", "core.bogus_field"],
                    "enabled_packs": ["data_infra", "nonexistent_pack"],
                    "technographic_field_keys": ["data_infra.migration_signal", "core.work_email"],
                    "candidate_signals": [
                        {
                            "signal_class": "funding",
                            "proxy_field_keys": ["account.recent_funding"],
                            "narrative_field_keys": ["account.operational_pain"],
                        }
                    ],
                    "rubric": {
                        "fit": [
                            {"field_key": "core.employee_count", "weight": 2.0},
                            {"field_key": "account.scoring.fit", "weight": 1.0},
                        ],
                        "intent": [{"field_key": "account.recent_funding", "weight": 3.0}],
                        "fit_threshold": 0.6,
                        "intent_threshold": 0.4,
                    },
                },
                {
                    "icp_key": "midmarket",
                    "label": "Mid-market",
                    "firmographic": {"industry": "data infra", "size_band": "mid-market"},
                    "firmographic_field_keys": ["core.employee_count"],
                    "enabled_packs": ["data_infra"],
                    "technographic_field_keys": ["data_infra.migration_signal"],
                    "candidate_signals": [
                        {"signal_class": "hiring", "proxy_field_keys": ["core.primary_tech_stack"]}
                    ],
                    "rubric": {
                        "fit": [{"field_key": "core.employee_count", "weight": 1.0}],
                        "intent": [],
                        "fit_threshold": 0.5,
                        "intent_threshold": 0.3,
                    },
                },
            ]
        }
    )


def test_llm_multi_icp_split_and_config_bounding() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await build_client_kb(
                conn, workspace_id=_CLIENT, suffix="multi", asserted=_ASSERTED
            )
            gateway = FakeGateway(_two_icp_json())
            proposals = await synthesize_icps(
                conn, ref, workspace_id=_CLIENT, gateway=gateway, synthesis_model="fake/model"
            )

            assert len(proposals) == 2  # the LLM split into two ICPs (D5)
            assert {p.icp_key for p in proposals} == {"enterprise", "midmarket"}
            assert len(gateway.calls) == 1
            assert gateway.calls[0][0] == "fake/model"

            enterprise = next(p for p in proposals if p.icp_key == "enterprise")
            # the hard config guard: off-set field/pack names are dropped, never proposed
            assert "core.bogus_field" not in enterprise.firmographic.field_keys
            assert "core.employee_count" in enterprise.firmographic.field_keys
            assert enterprise.source_profile.packs == ("data_infra",)  # nonexistent_pack dropped
            techno_keys = {t.field_key for t in enterprise.technographic}
            assert "data_infra.migration_signal" in techno_keys
            assert "core.work_email" not in techno_keys  # not a data_infra pack field → dropped
            rubric_keys = {w.field_key for w in enterprise.rubric.weights}
            assert "account.scoring.fit" not in rubric_keys  # a score OUTPUT, not a scoring input
            assert "core.employee_count" in rubric_keys

    run_async(_run())


def test_llm_failure_degrades_to_floor() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await build_client_kb(
                conn, workspace_id=_CLIENT, suffix="fail", asserted=_ASSERTED
            )

            # a raising gateway → the deterministic floor stands (never propagates the failure)
            raising = await synthesize_icps(
                conn,
                ref,
                workspace_id=_CLIENT,
                gateway=FakeGateway(raise_exc=True),
                synthesis_model="fake/model",
            )
            assert [p.icp_key for p in raising] == ["primary"]

            # unparseable output → floor
            garbage = await synthesize_icps(
                conn,
                ref,
                workspace_id=_CLIENT,
                gateway=FakeGateway("not json at all"),
                synthesis_model="fake/model",
            )
            assert [p.icp_key for p in garbage] == ["primary"]

            # a gateway with no model id is not used at all → floor
            no_model = await synthesize_icps(
                conn, ref, workspace_id=_CLIENT, gateway=FakeGateway(_two_icp_json())
            )
            assert [p.icp_key for p in no_model] == ["primary"]

    run_async(_run())
