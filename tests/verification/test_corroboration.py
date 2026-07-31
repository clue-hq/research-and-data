"""M9.2 (ENG-134) — corroboration rules: ≥N independent tier≤3 promotion + conflict flags.

Every §M9.2 acceptance criterion has a dedicated test. The pure machinery (equality modes, agreement
grouping, the independence union-find) runs without a database (in ``make check``); the
``Corroborator.evaluate`` behaviour is exercised against a live Postgres (skips without one, like
M9.1 / claim-store suites) because it reads the field registry + claim store and writes the
``verification_status`` / ``corroborations`` verdict and ``conflict_flag`` rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import MergePolicy as ConfigMergePolicy
from clue_core import (
    DEFAULT_NUMERIC_ABS_TOLERANCE,
    DEFAULT_NUMERIC_REL_TOLERANCE,
    DEFAULT_SEMANTIC_JACCARD_THRESHOLD,
    AccountStatus,
    Claim,
    ClaimId,
    DisplayDecision,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    OutreachDecision,
    PassKind,
    ResearchAvailability,
    ResearchConflictState,
    ResearchItemState,
    ResearchMode,
    VerificationStatus,
    new_claim_id,
    new_entity_id,
    new_run_id,
)
from clue_obs.otel import InMemorySink
from clue_research.claimstore import (
    ALL_WORKSPACES,
    CorroborationConfig,
    MergePolicy,
    current_value,
    get_corroboration_config,
    insert_claim,
    record_verification,
    register_field,
)
from clue_research.identity import insert_account_entity
from clue_research.verification import (
    CorroborationPolicy,
    Corroborator,
    EqualityMode,
    ValueGroup,
    group_by_agreement,
    independent_source_count,
    values_agree,
)
from clue_research.verification.corroboration import (
    METRIC_CORROBORATION_CONFLICTS,
    METRIC_CORROBORATION_PROMOTED,
)
from tests._workspace import DEFAULT_TEST_WORKSPACE, seed_workspace

from .conftest import rollback_conn, run_async

_POLICY = CorroborationPolicy()


# --- pure unit (no DB) ------------------------------------------------------


def _claim(
    *,
    value: object = "x",
    tier: int = 3,
    source_key: str | None = "exa",
    host: str | None = "a.com",
    status: VerificationStatus = VerificationStatus.UNVERIFIED,
    entity_type: EntityType = EntityType.ACCOUNT,
) -> Claim:
    """A minimal in-memory claim for the pure grouping/independence helpers (no DB)."""
    # A host-less claim uses ``human`` (no source_url required); otherwise method follows the tier.
    method = (
        ExtractionMethod.HUMAN
        if host is None
        else {
            1: ExtractionMethod.API,
            2: ExtractionMethod.SCRAPE,
            3: ExtractionMethod.SCRAPE,
            4: ExtractionMethod.LLM_SYNTHESIS,
        }[tier]
    )
    return Claim(
        entity_id=new_entity_id(),
        entity_type=entity_type,
        field_key="account.probe",
        value_json=value,  # type: ignore[arg-type]
        source_url=f"https://{host}/path" if host else None,
        source_key=source_key,
        source_tier=tier,  # type: ignore[arg-type]
        extraction_method=method,
        evidence_span="ev" if tier == 4 else None,
        confidence=0.9,  # type: ignore[arg-type]
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        verification_status=status,
    )


def test_values_agree_exact() -> None:
    assert values_agree("Snowflake", "Snowflake", mode=EqualityMode.EXACT, policy=_POLICY)
    assert not values_agree("Snowflake", "snowflake", mode=EqualityMode.EXACT, policy=_POLICY)
    # objects compare order-independently.
    assert values_agree({"a": 1, "b": 2}, {"b": 2, "a": 1}, mode=EqualityMode.EXACT, policy=_POLICY)


def test_values_agree_numeric_tolerance() -> None:
    # within 5% relative tolerance corroborate; well outside it conflict.
    assert values_agree(1000, 1024, mode=EqualityMode.NUMERIC_TOL, policy=_POLICY)
    assert not values_agree(1000, 2000, mode=EqualityMode.NUMERIC_TOL, policy=_POLICY)
    # a non-numeric value under numeric mode falls back to exact equality.
    assert values_agree("v1", "v1", mode=EqualityMode.NUMERIC_TOL, policy=_POLICY)
    assert not values_agree("v1", "v2", mode=EqualityMode.NUMERIC_TOL, policy=_POLICY)


def test_values_agree_semantic() -> None:
    # the spec fixture: "Snowflake" vs "uses Snowflake" corroborate; vs "Databricks" conflict.
    assert values_agree("Snowflake", "uses Snowflake", mode=EqualityMode.SEMANTIC, policy=_POLICY)
    assert not values_agree("Snowflake", "Databricks", mode=EqualityMode.SEMANTIC, policy=_POLICY)
    # non-string under semantic mode → exact fallback.
    assert values_agree(7, 7, mode=EqualityMode.SEMANTIC, policy=_POLICY)
    assert not values_agree(7, 8, mode=EqualityMode.SEMANTIC, policy=_POLICY)


def test_group_by_agreement_splits_distinct_values() -> None:
    a = _claim(value="Snowflake", host="a.com", source_key="exa")
    b = _claim(value="uses Snowflake", host="b.com", source_key="parallel")
    c = _claim(value="Databricks", host="c.com", source_key="clay")
    groups = group_by_agreement([a, b, c], mode=EqualityMode.SEMANTIC, policy=_POLICY)
    assert len(groups) == 2  # {a, b} agree; c is its own group
    assert {a.id, b.id} == {x.id for x in groups[0]}
    assert [c.id] == [x.id for x in groups[1]]


def test_independent_source_count_distinct_host_and_key() -> None:
    a = _claim(host="a.com", source_key="exa")
    b = _claim(host="b.com", source_key="parallel")
    assert independent_source_count([a, b]) == 2


def test_independent_source_count_same_vendor_counts_once() -> None:
    a = _claim(host="a.com", source_key="exa")
    b = _claim(host="b.com", source_key="exa")  # same vendor (source_key)
    assert independent_source_count([a, b]) == 1


def test_independent_source_count_same_domain_counts_once() -> None:
    a = _claim(host="a.com", source_key="exa")
    b = _claim(host="www.a.com", source_key="parallel")  # same domain (www stripped)
    assert independent_source_count([a, b]) == 1


def test_independent_source_count_chain_collapses() -> None:
    # A~B share a key, B~C share a host → one connected component (conservative anti-gaming).
    a = _claim(host="a.com", source_key="k1")
    b = _claim(host="b.com", source_key="k1")
    c = _claim(host="b.com", source_key="k2")
    assert independent_source_count([a, b, c]) == 1


def test_independent_source_count_anonymous_claims_collapse() -> None:
    a = _claim(host=None, source_key=None)
    b = _claim(host=None, source_key=None)
    assert independent_source_count([a, b]) == 1  # no identifiable origin → one component
    assert independent_source_count([]) == 0


def test_host_parsing_ipv6_and_scheme_less() -> None:
    from clue_research.verification.corroboration import _host

    # IPv6 authorities are not corrupted by port-stripping (urlsplit.hostname strips brackets/port).
    assert _host("https://[2001:db8::1]/path") == "2001:db8::1"
    assert _host("https://[2001:db8::1]:8443/path") == "2001:db8::1"
    # a scheme-less but real authority is still recognised (source_url is an unvalidated string).
    assert _host("acme.com/path") == "acme.com"
    # userinfo + port + www are stripped; case-folded.
    assert _host("https://user:pw@WWW.Acme.com:443/x") == "acme.com"
    assert _host(None) is None


def test_independent_source_count_distinct_ipv6_hosts() -> None:
    a = _claim(host="[2001:db8::1]", source_key="exa")
    b = _claim(host="[2001:db8::2]", source_key="parallel")
    # two genuinely distinct IPv6 hosts must not collapse (the old rsplit(':') bug).
    assert independent_source_count([a, b]) == 2


def test_default_policy_tiers() -> None:
    assert _POLICY.corroboration_tier_ceiling == 3
    assert _POLICY.conflict_tier_threshold == 2


def test_conflict_tier_threshold_aligns_across_policies() -> None:
    """Drift guard (pure, runs in ``make check`` — no DB): the conflict tier band must match across
    every layer that owns a copy of it, so a conflict the corroborator raises is the same conflict
    the merge view flags. Until the default is sourced from one M0.4 seam (backlog [M9.2×M0.4]), the
    static check turns silent drift into a loud build failure."""
    band = CorroborationPolicy().conflict_tier_threshold
    assert (
        band == MergePolicy().conflict_tier_threshold
    )  # claimstore merge layer (the engine reads)
    assert band == ConfigMergePolicy().conflict_tier_threshold  # config/schema.py M0.4 seam shape


def test_equality_tolerances_align_across_policies() -> None:
    """Drift guard (pure, ``make check`` — no DB): the numeric / semantic tolerances on the
    corroborator's :class:`CorroborationPolicy` and the merge's :class:`MergePolicy` must match each
    other AND the shared ``core`` defaults — so the mode-aware merge conflict check ([M9.2×M1.2])
    decides "two authoritative sources agree" identically to the corroborator. Silent drift (one
    layer loosens a tolerance) would re-split the two surfaces; this makes it a build failure."""
    corr = CorroborationPolicy()
    merge = MergePolicy()
    cfg = ConfigMergePolicy()  # the M0.4 config/schema seam shape
    assert (
        corr.numeric_rel_tolerance
        == merge.numeric_rel_tolerance
        == cfg.numeric_rel_tolerance
        == DEFAULT_NUMERIC_REL_TOLERANCE
    )
    assert (
        corr.numeric_abs_tolerance
        == merge.numeric_abs_tolerance
        == cfg.numeric_abs_tolerance
        == DEFAULT_NUMERIC_ABS_TOLERANCE
    )
    assert (
        corr.semantic_jaccard_threshold
        == merge.semantic_jaccard_threshold
        == cfg.semantic_jaccard_threshold
        == DEFAULT_SEMANTIC_JACCARD_THRESHOLD
    )


def test_corroboration_config_defaults() -> None:
    cfg = CorroborationConfig()
    assert cfg.corroboration_min == 1
    assert cfg.single_source_sufficient is False
    assert cfg.equality_mode == "exact"


def test_value_group_model_shape() -> None:
    vg = ValueGroup(
        representative_value="x",
        claim_ids=(new_claim_id(),),
        independent_sources=2,
        meets_threshold=True,
        promoted=True,
    )
    assert vg.independent_sources == 2 and vg.promoted


# --- DB-gated corroboration behaviour ---------------------------------------


def _corroborator(conn: AsyncConnection, *, sink: InMemorySink | None = None) -> Corroborator:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return Corroborator(conn_factory=factory, sink=sink)


async def _account(conn: AsyncConnection) -> EntityId:
    await seed_workspace(conn, DEFAULT_TEST_WORKSPACE)
    return await insert_account_entity(  # type: ignore[return-value]
        conn,
        canonical_name="Acme",
        primary_domain="acme.com",
        status=AccountStatus.ACTIVE,
        workspace_id=DEFAULT_TEST_WORKSPACE,
    )


async def _register(
    conn: AsyncConnection,
    field_key: str,
    *,
    corroboration_min: int = 1,
    single_source_sufficient: bool = False,
    equality_mode: str = "exact",
    value_type: str = "str",
    value_schema: dict[str, object] | None = None,
) -> None:
    await register_field(
        conn,
        FieldDef(field_key=field_key, value_type=value_type, pass_kind=PassKind.SCORING),
        corroboration_min=corroboration_min,
        single_source_sufficient=single_source_sufficient,
        equality_mode=equality_mode,
        value_schema=value_schema,
    )


async def _add_claim(
    conn: AsyncConnection,
    entity_id: EntityId,
    field_key: str,
    value: object,
    *,
    tier: int,
    source_key: str,
    host: str,
    run_id: object | None = None,
) -> ClaimId:
    method = {
        1: ExtractionMethod.API,
        2: ExtractionMethod.SCRAPE,
        3: ExtractionMethod.SCRAPE,
        4: ExtractionMethod.LLM_SYNTHESIS,
    }[tier]
    claim = Claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=value,  # type: ignore[arg-type]
        source_url=f"https://{host}/path",
        source_key=source_key,
        source_tier=tier,  # type: ignore[arg-type]
        extraction_method=method,
        evidence_span="ev" if tier == 4 else None,
        confidence=0.9,  # type: ignore[arg-type]
        run_id=run_id or new_run_id(),  # type: ignore[arg-type]
        research_mode=ResearchMode.ACCOUNT_PROFILING,
    )
    return await insert_claim(conn, claim)


async def _state(conn: AsyncConnection, claim_id: ClaimId) -> tuple[str, int]:
    row = (
        await conn.execute(
            text("SELECT verification_status, corroborations FROM claim WHERE id = :id"),
            {"id": claim_id},
        )
    ).first()
    assert row is not None
    return row[0], row[1]


async def _conflict_flag_count(conn: AsyncConnection, entity_id: EntityId, field_key: str) -> int:
    row = (
        await conn.execute(
            text(
                "SELECT count(*) FROM conflict_flag "
                "WHERE entity_id = :e AND field_key = :f AND resolved_by IS NULL"
            ),
            {"e": str(entity_id), "f": field_key},
        )
    ).scalar_one()
    return int(row)


async def _pg_enum_labels(conn: AsyncConnection, type_name: str) -> set[str]:
    result = await conn.execute(
        text(
            "SELECT e.enumlabel FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid WHERE t.typname = :n"
        ),
        {"n": type_name},
    )
    return set(result.scalars().all())


@pytest.mark.usefixtures("require_verification_db")
def test_equality_mode_enum_matches_db() -> None:
    """The DB equality_mode enum stays in lock-step with EqualityMode (drift guard)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            labels = await _pg_enum_labels(conn, "equality_mode")
        assert labels == {m.value for m in EqualityMode}

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_threshold_2_not_verified_on_one_tier3_source() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.lb", corroboration_min=2)
            a = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="exa", host="a.com"
            )
            result = await _corroborator(conn).evaluate(entity, "account.lb", scope=ALL_WORKSPACES)
            status, corr = await _state(conn, a)
            assert status == "unverified" and corr == 1
            assert result.promoted_claim_ids == ()
            assert not result.conflict

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_threshold_2_verified_on_two_independent_tier3_sources() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.lb", corroboration_min=2)
            a = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="exa", host="a.com"
            )
            b = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="parallel", host="b.com"
            )
            result = await _corroborator(conn).evaluate(entity, "account.lb", scope=ALL_WORKSPACES)
            assert (await _state(conn, a)) == ("verified", 2)
            assert (await _state(conn, b)) == ("verified", 2)
            assert set(result.promoted_claim_ids) == {a, b}

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_two_claims_from_same_vendor_count_as_one() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.lb", corroboration_min=2)
            a = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="exa", host="a.com"
            )
            b = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="exa", host="b.com"
            )  # same vendor
            await _corroborator(conn).evaluate(entity, "account.lb", scope=ALL_WORKSPACES)
            assert (await _state(conn, a)) == ("unverified", 1)
            assert (await _state(conn, b)) == ("unverified", 1)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_threshold_1_promotes_on_single_confident_claim() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.nlb", corroboration_min=1)  # non-load-bearing default
            a = await _add_claim(
                conn, entity, "account.nlb", "v", tier=3, source_key="exa", host="a.com"
            )
            await _corroborator(conn).evaluate(entity, "account.nlb", scope=ALL_WORKSPACES)
            assert (await _state(conn, a)) == ("verified", 1)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_tier1_single_source_sufficient_verified_without_corroboration() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(
                conn, "account.regid", corroboration_min=2, single_source_sufficient=True
            )
            a = await _add_claim(
                conn,
                entity,
                "account.regid",
                "ABC123",
                tier=1,
                source_key="registry",
                host="reg.gov",
            )
            await _corroborator(conn).evaluate(entity, "account.regid", scope=ALL_WORKSPACES)
            # a lone tier-1 deterministic claim verifies despite corroboration_min=2.
            assert (await _state(conn, a))[0] == "verified"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_single_source_sufficient_does_not_promote_a_tier3_claim() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(
                conn, "account.regid", corroboration_min=2, single_source_sufficient=True
            )
            # single_source_sufficient is a *tier-1* affordance; a lone tier-3 claim still needs N.
            a = await _add_claim(
                conn, entity, "account.regid", "X", tier=3, source_key="exa", host="a.com"
            )
            await _corroborator(conn).evaluate(entity, "account.regid", scope=ALL_WORKSPACES)
            assert (await _state(conn, a))[0] == "unverified"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_two_tier2_sources_disagree_raise_conflict_and_no_silent_pick() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.lb", corroboration_min=2)
            a = await _add_claim(
                conn, entity, "account.lb", "X", tier=2, source_key="exa", host="a.com"
            )
            b = await _add_claim(
                conn, entity, "account.lb", "Y", tier=2, source_key="parallel", host="b.com"
            )
            result = await _corroborator(conn).evaluate(entity, "account.lb", scope=ALL_WORKSPACES)
            assert result.conflict
            assert set(result.conflicting_claim_ids) == {a, b}
            # no value silently chosen: neither claim is promoted.
            assert (await _state(conn, a))[0] == "unverified"
            assert (await _state(conn, b))[0] == "unverified"
            # a conflict_flag row is raised...
            assert await _conflict_flag_count(conn, entity, "account.lb") == 1
            # ...and the merge result carries the conflict flag (substrate §1).
            cv = await current_value(conn, entity, "account.lb", scope=ALL_WORKSPACES)
            assert cv is not None and cv.conflict

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
@pytest.mark.parametrize(
    ("field_key", "equality_mode", "left", "right"),
    [
        ("account.c7_headcount", "numeric_tol", 1000, 1024),
        ("account.c7_tech", "semantic", "Snowflake", "uses Snowflake"),
    ],
)
def test_c7_equality_agreement_aligns_corroboration_merge_and_item_state(
    field_key: str,
    equality_mode: str,
    left: object,
    right: object,
) -> None:
    """C7.1 joint consumer test: canonical differences that agree never become review-required."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(
                conn,
                field_key,
                corroboration_min=2,
                equality_mode=equality_mode,
                value_type="int" if equality_mode == "numeric_tol" else "str",
                value_schema={"type": "number" if equality_mode == "numeric_tol" else "string"},
            )
            await _add_claim(
                conn, entity, field_key, left, tier=2, source_key="exa", host="a.example"
            )
            await _add_claim(
                conn, entity, field_key, right, tier=2, source_key="parallel", host="b.example"
            )

            corroboration = await _corroborator(conn).evaluate(
                entity, field_key, scope=ALL_WORKSPACES
            )
            merged = await current_value(conn, entity, field_key, scope=ALL_WORKSPACES)
            assert merged is not None
            assert not corroboration.conflict
            assert not merged.conflict

            # Provisional C7 item-state adapter: C7.3 will own the full governance projection, but
            # this locks the prerequisite now so it cannot reinterpret canonical inequality as a
            # review conflict.
            state = ResearchItemState(
                availability=ResearchAvailability.AVAILABLE,
                verification=VerificationStatus.VERIFIED,
                freshness=merged.freshness_state,
                conflict=(
                    ResearchConflictState.REVIEW_REQUIRED
                    if merged.conflict
                    else ResearchConflictState.NONE
                ),
                display_decision=DisplayDecision.ALLOWED,
                outreach_decision=OutreachDecision.NOT_APPLICABLE,
                reason_codes=("review_required",) if merged.conflict else (),
            )
            assert state.conflict is ResearchConflictState.NONE
            assert "review_required" not in state.reason_codes

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_c7_equality_disagreement_aligns_corroboration_merge_and_item_state() -> None:
    """C7.1 converse: genuine mode-aware disagreement remains review-required end to end."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            field_key = "account.c7_tech_conflict"
            await _register(
                conn,
                field_key,
                corroboration_min=2,
                equality_mode="semantic",
            )
            await _add_claim(
                conn,
                entity,
                field_key,
                "Snowflake",
                tier=2,
                source_key="exa",
                host="a.example",
            )
            await _add_claim(
                conn,
                entity,
                field_key,
                "Databricks",
                tier=2,
                source_key="parallel",
                host="b.example",
            )
            corroboration = await _corroborator(conn).evaluate(
                entity, field_key, scope=ALL_WORKSPACES
            )
            merged = await current_value(conn, entity, field_key, scope=ALL_WORKSPACES)
            assert merged is not None
            assert corroboration.conflict
            assert merged.conflict

            state = ResearchItemState(
                availability=ResearchAvailability.AVAILABLE,
                verification=VerificationStatus.FLAGGED,
                freshness=merged.freshness_state,
                conflict=ResearchConflictState.REVIEW_REQUIRED,
                display_decision=DisplayDecision.ALLOWED,
                outreach_decision=OutreachDecision.NOT_APPLICABLE,
                reason_codes=("review_required",),
            )
            assert state.conflict is ResearchConflictState.REVIEW_REQUIRED
            assert state.reason_codes == ("review_required",)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_open_conflict_suppresses_a_would_promote_group() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.lb", corroboration_min=2)
            # a/b: a tier-3 group that on its own meets threshold 2 and would promote...
            a = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="exa", host="a.com"
            )
            b = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="parallel", host="b.com"
            )
            # ...but two tier-2 sources disagree, so the whole field is held for review.
            await _add_claim(
                conn, entity, "account.lb", "Z", tier=2, source_key="clay", host="c.com"
            )
            await _add_claim(
                conn, entity, "account.lb", "W", tier=2, source_key="bing", host="d.com"
            )
            result = await _corroborator(conn).evaluate(entity, "account.lb", scope=ALL_WORKSPACES)
            assert result.conflict
            assert result.promoted_claim_ids == ()  # the open conflict blocks ALL promotion
            assert (await _state(conn, a))[0] == "unverified"
            assert (await _state(conn, b))[0] == "unverified"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_flagged_claim_does_not_corroborate_its_neighbours() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.lb", corroboration_min=2)
            a = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="exa", host="a.com"
            )
            b = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="parallel", host="b.com"
            )
            # a is flagged for human review → it must NOT count as an independent corroboration, so
            # b alone (1 source) stays below threshold 2.
            await record_verification(conn, a, status=VerificationStatus.FLAGGED)
            await _corroborator(conn).evaluate(entity, "account.lb", scope=ALL_WORKSPACES)
            assert (await _state(conn, a))[0] == "flagged"  # untouched by the corroborator
            assert (await _state(conn, b)) == ("unverified", 1)  # only b counts

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_non_transitive_numeric_conflict_is_not_masked() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(
                conn,
                "account.headcount",
                corroboration_min=2,
                equality_mode="numeric_tol",
                value_type="int",
                value_schema={"type": "number"},
            )
            # three authoritative (tier-2) sources: 960 / 1000 / 1040 at rel-tol 0.05. 1000 bridges
            # both, but 960 vs 1040 disagree (80 > 52) — the conflict must not hide behind 1000.
            lo = await _add_claim(
                conn, entity, "account.headcount", 960, tier=2, source_key="exa", host="a.com"
            )
            await _add_claim(
                conn, entity, "account.headcount", 1000, tier=2, source_key="parallel", host="b.com"
            )
            hi = await _add_claim(
                conn, entity, "account.headcount", 1040, tier=2, source_key="clay", host="c.com"
            )
            result = await _corroborator(conn).evaluate(
                entity, "account.headcount", scope=ALL_WORKSPACES
            )
            assert result.conflict
            assert set(result.conflicting_claim_ids) == {lo, hi}  # the bridging 1000 is not flagged
            assert result.promoted_claim_ids == ()

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_idempotent_re_evaluation_writes_no_new_rows() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.lb", corroboration_min=2)
            a = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="exa", host="a.com"
            )
            b = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="parallel", host="b.com"
            )
            # and an authoritative conflict so a conflict_flag is written too.
            c = await _add_claim(
                conn, entity, "account.lb", "Z", tier=2, source_key="clay", host="c.com"
            )
            d = await _add_claim(
                conn, entity, "account.lb", "W", tier=2, source_key="bing", host="d.com"
            )

            first = await _corroborator(conn).evaluate(entity, "account.lb", scope=ALL_WORKSPACES)
            state_a1, state_b1 = await _state(conn, a), await _state(conn, b)
            flags1 = await _conflict_flag_count(conn, entity, "account.lb")

            second = await _corroborator(conn).evaluate(entity, "account.lb", scope=ALL_WORKSPACES)
            # same verdicts, and crucially no extra conflict_flag row.
            assert (await _state(conn, a)) == state_a1
            assert (await _state(conn, b)) == state_b1
            assert await _conflict_flag_count(conn, entity, "account.lb") == flags1 == 1
            assert first.conflict and second.conflict
            assert first.promoted_claim_ids == second.promoted_claim_ids
            # claims c/d unused beyond seeding the conflict.
            assert c and d

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_numeric_tolerance_corroborates_and_separates() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(
                conn,
                "account.headcount",
                corroboration_min=2,
                equality_mode="numeric_tol",
                value_type="int",
                value_schema={"type": "number"},
            )
            a = await _add_claim(
                conn, entity, "account.headcount", 1000, tier=3, source_key="exa", host="a.com"
            )
            b = await _add_claim(
                conn, entity, "account.headcount", 1024, tier=3, source_key="parallel", host="b.com"
            )  # within 5% → corroborates a
            c = await _add_claim(
                conn, entity, "account.headcount", 5000, tier=3, source_key="clay", host="c.com"
            )  # far off → its own group
            await _corroborator(conn).evaluate(entity, "account.headcount", scope=ALL_WORKSPACES)
            assert (await _state(conn, a)) == ("verified", 2)
            assert (await _state(conn, b)) == ("verified", 2)
            assert (await _state(conn, c)) == ("unverified", 1)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_semantic_equality_corroborates_and_separates() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.tech", corroboration_min=2, equality_mode="semantic")
            a = await _add_claim(
                conn, entity, "account.tech", "Snowflake", tier=3, source_key="exa", host="a.com"
            )
            b = await _add_claim(
                conn,
                entity,
                "account.tech",
                "uses Snowflake",
                tier=3,
                source_key="parallel",
                host="b.com",
            )
            c = await _add_claim(
                conn, entity, "account.tech", "Databricks", tier=3, source_key="clay", host="c.com"
            )
            await _corroborator(conn).evaluate(entity, "account.tech", scope=ALL_WORKSPACES)
            assert (await _state(conn, a))[0] == "verified"
            assert (await _state(conn, b))[0] == "verified"
            assert (await _state(conn, c))[0] == "unverified"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_changing_threshold_changes_promotion_with_no_code_change() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            # threshold 1 → a single tier-3 claim promotes.
            await _register(conn, "account.thresh1", corroboration_min=1)
            a = await _add_claim(
                conn, entity, "account.thresh1", "v", tier=3, source_key="exa", host="a.com"
            )
            # threshold 2 → the same single-source shape does not promote.
            await _register(conn, "account.thresh2", corroboration_min=2)
            b = await _add_claim(
                conn, entity, "account.thresh2", "v", tier=3, source_key="exa", host="a.com"
            )
            corroborator = _corroborator(conn)
            await corroborator.evaluate(entity, "account.thresh1", scope=ALL_WORKSPACES)
            await corroborator.evaluate(entity, "account.thresh2", scope=ALL_WORKSPACES)
            assert (await _state(conn, a))[0] == "verified"
            assert (await _state(conn, b))[0] == "unverified"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_tier4_left_to_the_judge_but_corroborations_recorded() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.lb", corroboration_min=2)
            a = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="exa", host="a.com"
            )
            b = await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="parallel", host="b.com"
            )
            # a tier-4 synthesized claim agreeing with the two tier-3 sources.
            t4 = await _add_claim(
                conn, entity, "account.lb", "v", tier=4, source_key="gpt", host="llm.local"
            )
            await _corroborator(conn).evaluate(entity, "account.lb", scope=ALL_WORKSPACES)
            # tier-3 promoted; tier-4 stays unverified (M9.3's faithfulness judge owns it) but its
            # corroborations count is set (independent tier≤3 sources = 2).
            assert (await _state(conn, a)) == ("verified", 2)
            assert (await _state(conn, t4)) == ("unverified", 2)
            assert b  # used

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_metrics_emitted() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            sink = InMemorySink()
            entity = await _account(conn)
            await _register(conn, "account.lb", corroboration_min=2)
            await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="exa", host="a.com"
            )
            await _add_claim(
                conn, entity, "account.lb", "v", tier=3, source_key="parallel", host="b.com"
            )
            await _corroborator(conn, sink=sink).evaluate(
                entity, "account.lb", scope=ALL_WORKSPACES
            )
            assert sink.counter(METRIC_CORROBORATION_PROMOTED, field_key="account.lb") == 2
            assert sink.counter(METRIC_CORROBORATION_CONFLICTS, field_key="account.lb") == 0

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_record_verification_cannot_promote_spanless_tier4() -> None:
    """The claim-store verdict helper respects the 0002 CHECK backstop (defense in depth)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.synth", corroboration_min=1)
            # a span-less tier-4 claim: allowed to exist as unverified, never promotable.
            claim = Claim(
                entity_id=entity,
                entity_type=EntityType.ACCOUNT,
                field_key="account.synth",
                value_json="v",
                source_url="https://llm.local/x",
                source_key="gpt",
                source_tier=4,  # type: ignore[arg-type]
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                evidence_span=None,
                confidence=0.9,  # type: ignore[arg-type]
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
            )
            cid = await insert_claim(conn, claim)
            # the 0002 CHECK claim_tier4_verified_requires_span rejects the in-place promotion.
            with pytest.raises(IntegrityError):
                await record_verification(conn, cid, status=VerificationStatus.VERIFIED)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_get_corroboration_config_reads_registered_config() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "account.cfg",
                corroboration_min=3,
                single_source_sufficient=True,
                equality_mode="semantic",
            )
            cfg = await get_corroboration_config(conn, "account.cfg")
            assert cfg == CorroborationConfig(
                corroboration_min=3, single_source_sufficient=True, equality_mode="semantic"
            )
            assert await get_corroboration_config(conn, "account.missing") is None

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_single_tier2_vs_tier3_is_not_a_conflict() -> None:
    """A lone tier-2 source disagreeing with a tier-3 source is not a tier≤2 conflict (the band is
    shared with the merge layer; the pure alignment is asserted in
    ``test_conflict_tier_threshold_aligns_across_policies``)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = await _account(conn)
            await _register(conn, "account.lb", corroboration_min=2)
            # a single tier-2 disagreeing with a tier-3 is NOT a tier≤2 conflict (only one tier≤2).
            a = await _add_claim(
                conn, entity, "account.lb", "X", tier=2, source_key="exa", host="a.com"
            )
            b = await _add_claim(
                conn, entity, "account.lb", "Y", tier=3, source_key="parallel", host="b.com"
            )
            result = await _corroborator(conn).evaluate(entity, "account.lb", scope=ALL_WORKSPACES)
            assert not result.conflict
            assert await _conflict_flag_count(conn, entity, "account.lb") == 0
            assert a and b

    run_async(_run())
