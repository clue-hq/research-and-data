"""M6.3 (ENG-138) — the Pass-A scoring engine, against a live Postgres.

One test per acceptance criterion: a decomposed fit/intent score where every sub-score links a
backing claim id; tier-1–3 only (zero tier-4/synthesis claims, and the deterministic-first tier
strip); a missing source yields an empty *flagged* field, never a fabricated proxy; re-running with
the same run is idempotent (no new claim, identical score); a sub-floor account is flagged
``non_fit`` and *not* excluded (D6); a new rubric version supersedes and bumps; and the score object
is tenant-private. The pure scorer itself is M3.4's (tested in ``tests/icp/test_rubric.py``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest

from clue_core import (
    EntityScope,
    ExtractionMethod,
    FieldClass,
    FieldDef,
    ICPCreatedFrom,
    Modality,
    PassKind,
    PreSpendDecision,
    PreSpendGate,
    PreSpendVerdict,
    ResearchMode,
    ReuseScope,
    SourceManifest,
    account_claim,
    new_run_id,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_for,
    get_field,
    insert_claim,
    load_core_pack,
    register_field,
)
from clue_research.discovery_scoring.scoring import (
    FIT_FIELD,
    INTENT_FIELD,
    SourceYieldRow,
    aggregate_yield,
    pass_a_fill_fields,
    score_account,
)
from clue_research.icp import (
    RubricEntry,
    ScoringRubric,
    ScoringTransform,
    SubRubric,
    compile_field_plan,
    create_icp_spec,
)
from clue_research.identity import insert_account_entity
from clue_research.sources import (
    RegistrySourceManifest,
    bind_resolver,
    register_source,
    unbind_resolver,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_discovery_db")

CLIENT = "acme"
ICP = "default"
_EMP = "core.employee_count"
_FUND = "account.recent_funding"


def _rubric(
    *, version: int = 1, fit_floor: float | None = None, emp_weight: float = 1.0
) -> ScoringRubric:
    """A two-field rubric: Fit = employee_count (linear 0..1000), Intent = recent_funding."""
    return ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(
                    field_key=_EMP,
                    weight=emp_weight,
                    transform=ScoringTransform.LINEAR,
                    params={"lo": 0, "hi": 1000},
                ),
            )
        ),
        intent=SubRubric(
            entries=(RubricEntry(field_key=_FUND, transform=ScoringTransform.BOOLEAN),)
        ),
        fit_floor=fit_floor,
        version=version,
    )


async def _seed_account(
    conn,
    *,
    name: str = "Acme Inc",
    domain: str = "acme.com",
    employee_count: int | None = 500,
    funding: bool = True,
):
    """An admitted account + its two scoring-proxy input claims (public footprint)."""
    eid = await insert_account_entity(
        conn, canonical_name=name, primary_domain=domain, workspace_id=CLIENT
    )
    if employee_count is not None:
        await insert_claim(
            conn,
            account_claim(
                entity_id=eid,
                field_key=_EMP,
                value_json=employee_count,
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://src/employees",
            ),
        )
    if funding:
        await insert_claim(
            conn,
            account_claim(
                entity_id=eid,
                field_key=_FUND,
                value_json={"amount_usd": 5_000_000, "round": "B"},
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://src/funding",
            ),
        )
    return eid


async def _score(conn, eid, *, rubric, run_id, icp_version: int = 1):
    return await score_account(
        conn,
        eid,
        rubric=rubric,
        fill_fields=[],
        run_id=run_id,
        workspace_id=CLIENT,
        icp_key=ICP,
        icp_version=icp_version,
    )


# --- pure (always-run) ------------------------------------------------------
def test_aggregate_yield_sums_by_source_and_class() -> None:
    rows = [
        SourceYieldRow(
            source_key="clay",
            field_class=FieldClass.CORE,
            claims_total=2,
            fields_filled=1,
            cost_cents=Decimal(3),
        ),
        SourceYieldRow(
            source_key="clay",
            field_class=FieldClass.CORE,
            claims_total=1,
            fields_filled=1,
            cost_cents=Decimal(2),
        ),
        SourceYieldRow(
            source_key="apollo",
            field_class=FieldClass.ACCOUNT,
            claims_total=1,
            fields_filled=0,
            cost_cents=Decimal(1),
        ),
    ]
    out = {(r.source_key, r.field_class): r for r in aggregate_yield(rows)}
    assert len(out) == 2
    clay = out[("clay", FieldClass.CORE)]
    assert clay.claims_total == 3 and clay.fields_filled == 2 and clay.cost_cents == Decimal(5)


# --- AC1: decomposed, every sub-score links a backing claim id --------------
def test_score_account_decomposes_with_evidence() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            eid = await _seed_account(conn)
            outcome = await _score(conn, eid, rubric=_rubric(), run_id=new_run_id())
            score = outcome.score

            assert outcome.written is True
            assert score.fit.value == pytest.approx(0.5)  # 500 / 1000
            assert score.intent.value == pytest.approx(1.0)  # funding present
            # distinct fit/intent, each decomposed; every component links >=1 claim id
            assert score.fit.components and score.intent.components
            for component in (*score.fit.components, *score.intent.components):
                assert component.evidence_claim_ids
            # the evidence index resolves each sub-score field to >=1 claim id
            assert set(score.evidence) == {_EMP, _FUND}
            assert all(len(ids) >= 1 for ids in score.evidence.values())

    run_async(_run())


# --- AC2: tier-1–3 only; zero tier-4 / synthesis claims ---------------------
def test_score_claims_are_tier1_and_not_synthesized() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            eid = await _seed_account(conn)
            await _score(conn, eid, rubric=_rubric(), run_id=new_run_id())
            for field_key in (FIT_FIELD, INTENT_FIELD):
                claims = await claims_for(
                    conn, eid, field_key, scope=WorkspaceScope.for_workspace(CLIENT)
                )
                assert len(claims) == 1
                assert 1 <= claims[0].source_tier <= 3
                assert claims[0].extraction_method is not ExtractionMethod.LLM_SYNTHESIS

    run_async(_run())


def test_pass_a_fill_strips_tier4_sources() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            await register_field(
                conn,
                FieldDef(
                    field_key="account.test_signal",
                    value_type="number",
                    tier_plan=("t1src", "t4src"),
                    pass_kind=PassKind.SCORING,
                ),
                value_schema={"type": "number"},
            )
            for source_key, tier in (("t1src", 1), ("t4src", 4)):
                await register_source(
                    conn,
                    RegistrySourceManifest(
                        manifest=SourceManifest(
                            source_key=source_key,
                            modality=Modality.STRUCTURED,
                            entity_scope=EntityScope.ACCOUNT,
                            yields=("account",),
                            tier=tier,
                        )
                    ),
                )
            spec = await create_icp_spec(
                conn,
                workspace_id=CLIENT,
                icp_key=ICP,
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("account.test_signal",),
                activate=True,
            )
            plan = await compile_field_plan(conn, spec)
            rubric = ScoringRubric(
                fit=SubRubric(
                    entries=(
                        RubricEntry(
                            field_key="account.test_signal", transform=ScoringTransform.IDENTITY
                        ),
                    )
                )
            )
            fill = await pass_a_fill_fields(conn, plan, rubric, max_source_tier=3)
            assert len(fill) == 1
            assert fill[0].tier_plan == ("t1src",)  # the tier-4 source is stripped

    run_async(_run())


def test_pass_a_provider_observes_gate_before_resolution() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            eid = await _seed_account(conn, employee_count=None)
            source_key = "pass_a_gate_probe"
            await register_source(
                conn,
                RegistrySourceManifest(
                    manifest=SourceManifest(
                        source_key=source_key,
                        modality=Modality.STRUCTURED,
                        entity_scope=EntityScope.ACCOUNT,
                        yields=(_EMP,),
                        tier=1,
                        cost_cents=Decimal(1),
                    )
                ),
            )
            field = await get_field(conn, _EMP)
            assert field is not None
            field = field.model_copy(update={"tier_plan": (source_key,)})
            events: list[str] = []

            class OrderedResolver:
                tier = 1

                def resolve(self, entity, resolved_field):
                    events.append("resolver")
                    return [
                        account_claim(
                            entity_id=entity.entity_id,
                            field_key=str(resolved_field.field_key),
                            value_json=500,
                            source_tier=1,
                            extraction_method=ExtractionMethod.API,
                            confidence=0.9,
                            run_id=new_run_id(),
                            research_mode=ResearchMode.ACCOUNT_PROFILING,
                            source_url="https://provider.example/employees",
                            evidence_span="500 employees",
                        )
                    ]

            class RecordingGate:
                async def check(self, request):
                    events.append("gate")
                    return PreSpendDecision(verdict=PreSpendVerdict.PASS)

            bind_resolver(source_key, OrderedResolver())
            try:
                await score_account(
                    conn,
                    eid,
                    rubric=_rubric(),
                    fill_fields=[field],
                    run_id=new_run_id(),
                    workspace_id=CLIENT,
                    icp_key=ICP,
                    icp_version=1,
                    pre_spend_gate=cast(PreSpendGate, RecordingGate()),
                )
            finally:
                unbind_resolver(source_key)
            assert events == ["gate", "resolver"]

    run_async(_run())


# --- AC3: missing source -> empty flagged field, not a fabricated proxy ------
def test_missing_source_yields_flagged_not_fabricated() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            # no employee_count claim → the Fit proxy has no source
            eid = await _seed_account(conn, employee_count=None)
            outcome = await _score(conn, eid, rubric=_rubric(), run_id=new_run_id())

            # the field is still produced, flagged empty (no fabricated value): no evidence claim id
            assert outcome.score.fit.value == pytest.approx(0.0)
            assert outcome.score.evidence[_EMP] == ()
            # no proxy claim was fabricated for the missing field
            emp_claims = await claims_for(
                conn, eid, _EMP, scope=WorkspaceScope.for_workspace(CLIENT)
            )
            assert emp_claims == []

    run_async(_run())


# --- AC4: idempotent on the (account, rubric_version) run --------------------
def test_rescore_same_run_writes_no_new_claim() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            eid = await _seed_account(conn)
            rubric = _rubric()
            run_id = new_run_id()

            first = await _score(conn, eid, rubric=rubric, run_id=run_id)
            second = await _score(conn, eid, rubric=rubric, run_id=run_id)

            assert first.written is True and second.written is False
            assert second.score.fit.value == first.score.fit.value
            assert second.score.intent.value == first.score.intent.value
            for field_key in (FIT_FIELD, INTENT_FIELD):
                live = await claims_for(
                    conn, eid, field_key, scope=WorkspaceScope.for_workspace(CLIENT)
                )
                assert len(live) == 1  # no duplicate score claim on replay

    run_async(_run())


# --- AC5: sub-floor account is flagged non_fit, not excluded (D6) -----------
def test_non_fit_flag_below_floor_and_not_excluded() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            eid = await _seed_account(conn, employee_count=500)  # fit = 0.5
            outcome = await _score(conn, eid, rubric=_rubric(fit_floor=0.7), run_id=new_run_id())

            assert outcome.score.non_fit_flag is True
            # flag-and-proceed: still scored + persisted, with the evidence behind the low fit
            assert outcome.score.evidence[_EMP]  # the backing claim id(s)
            fit = await claims_for(conn, eid, FIT_FIELD, scope=WorkspaceScope.for_workspace(CLIENT))
            assert len(fit) == 1 and fit[0].value_json["non_fit_flag"] is True
            # not flagged when comfortably above the floor
            ok = await _score(
                conn,
                await _seed_account(conn, domain="beta.example"),
                rubric=_rubric(fit_floor=0.2),
                run_id=new_run_id(),
            )
            assert ok.score.non_fit_flag is False

    run_async(_run())


# --- AC6: a new rubric version supersedes and bumps -------------------------
def test_new_rubric_version_supersedes_and_bumps() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            eid = await _seed_account(conn)

            v1 = await _score(
                conn, eid, rubric=_rubric(version=1), run_id=new_run_id(), icp_version=1
            )
            # a re-weighted v2 rubric on a new (icp_version) run
            v2 = await _score(
                conn,
                eid,
                rubric=_rubric(version=2, emp_weight=2.0),
                run_id=new_run_id(),
                icp_version=2,
            )

            assert v1.score.rubric_version == 1 and v2.score.rubric_version == 2
            assert v2.written is True
            live = await claims_for(
                conn, eid, FIT_FIELD, scope=WorkspaceScope.for_workspace(CLIENT)
            )
            assert len(live) == 1 and live[0].value_json["rubric_version"] == 2  # one live winner
            history = await claims_for(
                conn,
                eid,
                FIT_FIELD,
                scope=WorkspaceScope.for_workspace(CLIENT),
                include_superseded=True,
            )
            assert len(history) == 2  # the v1 score is superseded, not deleted

    run_async(_run())


# --- tenant scoping: the score object is tenant-private ----------------------
def test_score_object_is_tenant_private() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            eid = await _seed_account(conn)
            await _score(conn, eid, rubric=_rubric(), run_id=new_run_id())
            claims = await claims_for(
                conn, eid, FIT_FIELD, scope=WorkspaceScope.for_workspace(CLIENT)
            )
            assert claims[0].reuse_scope is ReuseScope.TENANT_PRIVATE
            assert claims[0].workspace_id == CLIENT
            # invisible to a public-only read (tenant isolation)
            public = await claims_for(conn, eid, FIT_FIELD, scope=WorkspaceScope.public_only())
            assert public == []

    run_async(_run())
