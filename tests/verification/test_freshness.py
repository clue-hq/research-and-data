"""M9.5 (ENG-149) — freshness TTL engine + re-research cadence.

Every §M9.5 acceptance criterion has a dedicated test. The pure layer (``staleness`` /
``retention_horizon_for`` / ``CadencePolicy`` / ``FreshnessImpl.evaluate``, and the pure
``merge_claims`` interaction that proves "expired never wins over fresh") runs without a database
(in ``make check``); the scan behaviour (``due_for_refresh`` / ``due_for_age_out`` /
``record_re_research_candidates`` / ``load_cadence_policy``) is exercised against a live Postgres
(skips without one, like the M9.1–M9.4 suites) because it reads ``claim`` /
``field_definition.freshness_ttl`` / ``cadence_policy`` and emits ``re_research_candidate`` rows.

The engine has no LLM call (staleness is deterministic), so the DB tests inject the test's own
rollback-bound connection and assert the candidates, the emission queue, the span, and the metrics.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import (
    ALL_TENANTS,
    DEFAULT_MERGE_POLICY,
    current_value,
    insert_claim,
    merge_claims,
    register_field,
)
from clue_research.config.policy import RetentionTtls
from clue_research.config.schema import FreshnessTtls
from clue_research.core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldClass,
    FreshnessState,
    IdentityBinding,
    PassKind,
    ResearchMode,
    UseClass,
    new_claim_id,
    new_entity_id,
    new_run_id,
)
from clue_research.core.field import FieldDef
from clue_research.core.verification import Freshness
from clue_research.obs import SPAN_VERIFICATION_FRESHNESS, InMemorySink, collect_spans
from clue_research.verification import (
    DEFAULT_CADENCE_POLICY,
    METRIC_FRESHNESS_DUE,
    METRIC_FRESHNESS_SCANNED,
    METRIC_FRESHNESS_STALE,
    AgeOutCandidate,
    CadencePolicy,
    FreshnessImpl,
    load_cadence_policy,
    reference_time,
    retention_horizon_for,
    staleness,
)
from clue_research.verification.freshness import (
    ATTR_FRESHNESS_DUE,
    ATTR_FRESHNESS_EXPIRED,
    ATTR_FRESHNESS_OP,
    ATTR_FRESHNESS_SCANNED,
    ATTR_FRESHNESS_STALE,
)

from .conftest import rollback_conn, run_async

# A fixed reference instant so every staleness verdict is deterministic (M09 §M9.5 acceptance).
NOW = datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)


def _claim(
    field_key: str = "account.recent_funding",
    *,
    observed_days_ago: float | None = None,
    collected_days_ago: float = 0.0,
    tier: int = 2,
    entity_id: EntityId | None = None,
    entity_type: EntityType = EntityType.ACCOUNT,
    use_class: UseClass | None = None,
    identity_binding: IdentityBinding | None = None,
    research_mode: ResearchMode = ResearchMode.ACCOUNT_PROFILING,
    value: object = "x",
) -> Claim:
    """A field claim with a controllable observed/collected time (the freshness inputs)."""
    observed_at = NOW - timedelta(days=observed_days_ago) if observed_days_ago is not None else None
    method = (
        ExtractionMethod.LLM_SYNTHESIS
        if tier == 4
        else ExtractionMethod.API
        if tier == 1
        else ExtractionMethod.SCRAPE
    )
    return Claim(
        entity_id=entity_id or new_entity_id(),
        entity_type=entity_type,
        field_key=field_key,
        value_json=value,  # type: ignore[arg-type]
        source_url="https://src.example.com/x",
        source_key="crm",
        source_tier=tier,
        extraction_method=method,
        evidence_span="evidence" if tier == 4 else None,
        confidence=0.9,
        observed_at=observed_at,
        collected_at=NOW - timedelta(days=collected_days_ago),
        run_id=new_run_id(),
        research_mode=research_mode,
        identity_binding=identity_binding,
        use_class=use_class,
    )


def _facet_claim(
    *,
    observed_days_ago: float,
    use_class: UseClass = UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
    entity_id: EntityId | None = None,
    value: object = "rock climbing",
) -> Claim:
    """A ``contact.facet.*`` personal claim (strong-bound, so it is merge-eligible) for the
    retention/age-out tests — the personal field-class is the one that goes ``EXPIRED``."""
    return _claim(
        field_key="contact.facet.hobby",
        observed_days_ago=observed_days_ago,
        tier=2,
        entity_id=entity_id,
        entity_type=EntityType.CONTACT,
        use_class=use_class,
        identity_binding=IdentityBinding.STRONG,
        research_mode=ResearchMode.CONTACT_PROFILING,
        value=value,
    )


# --- pure unit (no DB) ------------------------------------------------------


def test_staleness_fresh_stale() -> None:
    ttl = timedelta(days=90)
    fresh = staleness(
        claim_id=new_claim_id(), reference_time=NOW - timedelta(days=10), now=NOW, ttl=ttl
    )
    stale = staleness(
        claim_id=new_claim_id(), reference_time=NOW - timedelta(days=120), now=NOW, ttl=ttl
    )
    assert fresh.state is FreshnessState.FRESH and fresh.age_days == pytest.approx(10.0)
    assert stale.state is FreshnessState.STALE and stale.age_days == pytest.approx(120.0)
    assert fresh.ttl_days == pytest.approx(90.0)


def test_staleness_no_ttl_is_always_fresh() -> None:
    # no TTL declared -> never stale (mirrors merge._is_fresh's None-TTL semantics).
    s = staleness(
        claim_id=new_claim_id(), reference_time=NOW - timedelta(days=9999), now=NOW, ttl=None
    )
    assert s.state is FreshnessState.FRESH and s.ttl_days is None


def test_staleness_expired_takes_precedence_over_stale() -> None:
    # past the retention horizon -> EXPIRED (checked first), even though it is also past the TTL.
    s = staleness(
        claim_id=new_claim_id(),
        reference_time=NOW - timedelta(days=200),
        now=NOW,
        ttl=timedelta(days=90),
        retention_horizon=timedelta(days=180),
    )
    assert s.state is FreshnessState.EXPIRED


def test_staleness_within_retention_is_stale_not_expired() -> None:
    s = staleness(
        claim_id=new_claim_id(),
        reference_time=NOW - timedelta(days=120),
        now=NOW,
        ttl=timedelta(days=90),
        retention_horizon=timedelta(days=180),
    )
    assert s.state is FreshnessState.STALE


def test_staleness_future_observed_clamped_fresh() -> None:
    # clock skew: a future observed_at reads as 0 days old, fresh (never negative age).
    s = staleness(
        claim_id=new_claim_id(),
        reference_time=NOW + timedelta(days=5),
        now=NOW,
        ttl=timedelta(days=90),
    )
    assert s.state is FreshnessState.FRESH and s.age_days == 0.0


def test_staleness_deterministic_given_fixed_now() -> None:
    # AC7: re-evaluation is idempotent/deterministic given a fixed now.
    cid = new_claim_id()
    ref = NOW - timedelta(days=100)
    first = staleness(claim_id=cid, reference_time=ref, now=NOW, ttl=timedelta(days=90))
    second = staleness(claim_id=cid, reference_time=ref, now=NOW, ttl=timedelta(days=90))
    assert first == second


def test_reference_time_prefers_observed_then_collected() -> None:
    with_observed = _claim(observed_days_ago=30, collected_days_ago=1)
    assert reference_time(with_observed) == NOW - timedelta(days=30)
    no_observed = _claim(observed_days_ago=None, collected_days_ago=7)
    assert reference_time(no_observed) == NOW - timedelta(days=7)


def test_retention_horizon_by_use_class() -> None:
    r = RetentionTtls()
    # only personal field-classes age out; firmographic/account classes never do.
    assert retention_horizon_for(FieldClass.ACCOUNT, None, r) is None
    assert retention_horizon_for(FieldClass.CORE, UseClass.PERSONAL_PUBLIC_NON_SENSITIVE, r) is None
    # personal: shorter horizon for more sensitive data (sensitive shortest).
    assert (
        retention_horizon_for(FieldClass.CONTACT_FACET, UseClass.SENSITIVE, r)
        == r.sensitive_claim_ttl
    )
    assert (
        retention_horizon_for(FieldClass.CONTACT_FACET, UseClass.PROFESSIONAL_PUBLIC, r)
        == r.professional_claim_ttl
    )
    assert (
        retention_horizon_for(FieldClass.CONTACT, UseClass.PERSONAL_PUBLIC_NON_SENSITIVE, r)
        == r.personal_claim_ttl
    )
    # an UNSTAMPED use_class (None) carries no retention horizon — we never guess one for an
    # unclassified claim (a plain contact.* may be born use_class=None); M10 stamps it first.
    assert retention_horizon_for(FieldClass.CONTACT, None, r) is None
    assert retention_horizon_for(FieldClass.CONTACT_FACET, None, r) is None


def test_cadence_policy_defaults_from_freshness_ttls() -> None:
    # the field-class TTL defaults are sourced from the shared FreshnessTtls shape (no second copy).
    ttls = FreshnessTtls().by_field_class
    assert DEFAULT_CADENCE_POLICY.ttl_for(FieldClass.CORE) == ttls["core"]
    assert DEFAULT_CADENCE_POLICY.ttl_for(FieldClass.ACCOUNT) == ttls["account"]
    assert DEFAULT_CADENCE_POLICY.ttl_for(FieldClass.CONTACT_FACET) == ttls["contact.facet"]
    # cadence falls back to the class TTL when unset; pack (unlisted) falls back to ~90-day default.
    assert DEFAULT_CADENCE_POLICY.cadence_for(FieldClass.ACCOUNT) == ttls["account"]
    assert DEFAULT_CADENCE_POLICY.ttl_for(FieldClass.PACK) == DEFAULT_CADENCE_POLICY.default_ttl
    assert DEFAULT_CADENCE_POLICY.default_ttl == timedelta(days=90)


def test_cadence_policy_field_class_ttl_ordering() -> None:
    # AC2: a signal-bearing account field is staler-sooner than a core firmographic; a
    # contact.facet personal field is staler-sooner than an account firmographic.
    p = DEFAULT_CADENCE_POLICY
    assert p.ttl_for(FieldClass.ACCOUNT) < p.ttl_for(FieldClass.CORE)
    assert p.ttl_for(FieldClass.CONTACT_FACET) < p.ttl_for(FieldClass.ACCOUNT)


def test_evaluate_signal_vs_firmographic() -> None:
    # AC2 via evaluate: at the same age, the shorter-TTL class goes stale, the longer stays fresh.
    engine = FreshnessImpl()
    core = _claim(field_key="core.employee_count", observed_days_ago=200, value=100)
    account = _claim(field_key="account.hiring_velocity_eng", observed_days_ago=200, value=12)
    assert engine.evaluate(core, now=NOW).state is FreshnessState.FRESH  # 200 < 365
    assert engine.evaluate(account, now=NOW).state is FreshnessState.STALE  # 200 > 180


def test_evaluate_ttl_override_wins() -> None:
    engine = FreshnessImpl()
    claim = _claim(field_key="core.employee_count", observed_days_ago=200, value=100)
    # the class default (365d) says fresh; an explicit 30d override says stale (the merge path).
    assert engine.evaluate(claim, now=NOW).state is FreshnessState.FRESH
    assert engine.evaluate(claim, now=NOW, ttl=timedelta(days=30)).state is FreshnessState.STALE


def test_evaluate_personal_claim_expires() -> None:
    engine = FreshnessImpl()
    # a contact.facet claim 200d old is past the 180d personal retention horizon -> EXPIRED.
    claim = _facet_claim(observed_days_ago=200)
    assert engine.evaluate(claim, now=NOW).state is FreshnessState.EXPIRED


def test_freshness_impl_satisfies_protocol() -> None:
    assert isinstance(FreshnessImpl(), Freshness)


def test_expired_never_wins_over_fresh_in_merge() -> None:
    # AC1 (pure): the merge prefers a FRESH claim; a past-TTL (stale OR expired) claim only wins as
    # a fallback when nothing fresh exists, so an expired claim never beats a fresh one. We also
    # assert the M9.5 verdicts that classify the two claims, tying the engine to the merge.
    entity = new_entity_id()
    fresh = _claim(entity_id=entity, observed_days_ago=5, value="fresh")
    stale = _claim(entity_id=entity, observed_days_ago=400, value="stale")
    ttl = timedelta(days=180)
    cv = merge_claims([fresh, stale], ttl, DEFAULT_MERGE_POLICY, NOW)
    assert cv is not None
    assert cv.value_json == "fresh"  # the fresh claim wins over the past-TTL one
    assert cv.freshness_state is FreshnessState.FRESH
    engine = FreshnessImpl()
    assert engine.evaluate(fresh, now=NOW, ttl=ttl).state is FreshnessState.FRESH
    assert engine.evaluate(stale, now=NOW, ttl=ttl).state is FreshnessState.STALE


def test_migration_defaults_match_code_defaults() -> None:
    """Pure no-DB drift guard (runs in ``make check``): the migration's CHECK constraints and the
    code defaults stay aligned — the cadence/ttl columns are positive intervals and the
    re_research_candidate priority is non-negative (mirrors the M9.2/M9.3/M9.4 static guards)."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/cb39832d29bb_m9_5_freshness_cadence_re_research_.py"
    ).read_text()
    # the migration reuses the existing field_class enum (no new enum) and the cadence columns are
    # guarded positive — the engine's CadencePolicy enforces the same (ttl/cadence are timedeltas).
    assert "field_class field_class NOT NULL" in " ".join(src.split())
    assert "cadence_policy_ttl_positive" in src
    assert "cadence_policy_cadence_positive" in src
    assert "re_research_candidate_priority_nonneg" in src
    # no claim ALTER / trigger change / new enum (the M9 isolation contract).
    assert "ALTER TABLE claim" not in src
    assert "CREATE TYPE" not in src


# --- DB-gated behaviour -----------------------------------------------------


def _engine(
    conn: AsyncConnection,
    *,
    policy: CadencePolicy = DEFAULT_CADENCE_POLICY,
    sink: InMemorySink | None = None,
) -> FreshnessImpl:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return FreshnessImpl(policy=policy, conn_factory=factory, sink=sink)


async def _candidate_rows(conn: AsyncConnection) -> int:
    return int(
        (await conn.execute(text("SELECT count(*) FROM re_research_candidate"))).scalar_one()
    )


@pytest.mark.usefixtures("require_verification_db")
def test_due_for_refresh_returns_stale_and_due_ranked() -> None:
    # AC4: due_for_refresh returns exactly the stale-and-due (entity, field) candidates, ranked by
    # (priority=lowest tier asc, due_at asc); a fresh claim is excluded; it does not fetch/persist.
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity1 = new_entity_id()
            entity2 = new_entity_id()
            # entity1.f1: tier-2, 300d old -> stale & due (account ttl 180d).
            c1 = _claim(field_key="account.f1", entity_id=entity1, tier=2, observed_days_ago=300)
            # entity1.f2: tier-1, 300d old -> stale & due, more trusted -> priority 1 (refresh 1st).
            c2 = _claim(field_key="account.f2", entity_id=entity1, tier=1, observed_days_ago=300)
            # entity2.f1: tier-3, 5d old -> FRESH -> excluded.
            c3 = _claim(field_key="account.f1", entity_id=entity2, tier=3, observed_days_ago=5)
            for c in (c1, c2, c3):
                await insert_claim(conn, c, validate_field=False)

            candidates = await _engine(conn).due_for_refresh(now=NOW)
            keys = [(str(c.entity_id), c.field_key, c.priority) for c in candidates]
            assert keys == [
                (str(entity1), "account.f2", 1),  # priority 1 (tier-1) ranks first
                (str(entity1), "account.f1", 2),
            ]
            assert candidates[1].stale_claim_ids == (c1.id,)
            # detection is a pure read — it persists nothing (M7 records explicitly).
            assert await _candidate_rows(conn) == 0

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_due_for_refresh_scoped_to_entity() -> None:
    # the optional entity_ids bound the scan (a per-account refresh scope).
    async def _run() -> None:
        async with rollback_conn() as conn:
            e1, e2 = new_entity_id(), new_entity_id()
            await insert_claim(
                conn,
                _claim(field_key="account.f1", entity_id=e1, observed_days_ago=300),
                validate_field=False,
            )
            await insert_claim(
                conn,
                _claim(field_key="account.f1", entity_id=e2, observed_days_ago=300),
                validate_field=False,
            )
            scoped = await _engine(conn).due_for_refresh(entity_ids=(e1,), now=NOW)
            assert {str(c.entity_id) for c in scoped} == {str(e1)}

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_per_field_ttl_override_makes_stale_sooner() -> None:
    # AC2 (per-field): a field with an explicit field_definition.freshness_ttl shorter than its
    # class default goes stale at that TTL — the same TTL the merge reads, so the two stay aligned.
    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_field(
                conn,
                FieldDef(
                    field_key="account.fast_signal",
                    value_type="int",
                    pass_kind=PassKind.SCORING,
                    freshness_ttl=timedelta(days=14),  # far shorter than account's 180d default
                ),
            )
            entity = new_entity_id()
            # 30d old: stale under the 14d per-field override, fresh under the 180d class default.
            # account.slow_fact is unregistered -> it falls back to the 180d account class TTL.
            override = _claim(
                field_key="account.fast_signal", entity_id=entity, observed_days_ago=30, value=1
            )
            default = _claim(field_key="account.slow_fact", entity_id=entity, observed_days_ago=30)
            await insert_claim(conn, override, validate_field=False)
            await insert_claim(conn, default, validate_field=False)
            candidates = await _engine(conn).due_for_refresh(now=NOW)
            fields = {c.field_key for c in candidates}
            assert "account.fast_signal" in fields  # the per-field override fired
            assert "account.slow_fact" not in fields  # still fresh at the class default

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_per_field_ttl_shortens_cadence_even_with_class_cadence_row() -> None:
    # regression guard: a per-field freshness_ttl (14d) must still shorten the refresh cadence even
    # when a cadence_policy row exists for the class (refresh_cadence=90d) — the scan takes the
    # sooner of the two, so the field is due at its own 14d rate, not stuck stale-but-never-due.
    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_field(
                conn,
                FieldDef(
                    field_key="account.fast_signal",
                    value_type="int",
                    pass_kind=PassKind.SCORING,
                    freshness_ttl=timedelta(days=14),
                ),
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO cadence_policy
                        (policy_id, client_id, field_class, ttl, refresh_cadence, version)
                    VALUES (:pid, NULL, CAST('account' AS field_class), :ttl, :cadence, 1)
                    """
                ),
                {"pid": "acct-90d", "ttl": timedelta(days=90), "cadence": timedelta(days=90)},
            )
            policy = await load_cadence_policy(conn)
            claim = _claim(field_key="account.fast_signal", observed_days_ago=30, value=1)
            await insert_claim(conn, claim, validate_field=False)
            candidates = await _engine(conn, policy=policy).due_for_refresh(now=NOW)
            # 30d > the 14d per-field TTL -> due, despite the 90d class cadence row.
            assert [c.field_key for c in candidates] == ["account.fast_signal"]

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_config_swap_changes_staleness_no_code() -> None:
    # AC5: flipping the cadence_policy TTL for a field-class in config changes refresh behaviour
    # with no code change. A 100d account claim is fresh under the 180d default, stale under a 30d.
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            # account.swap_test is unregistered -> the account class TTL (180d) governs it.
            claim = _claim(field_key="account.swap_test", entity_id=entity, observed_days_ago=100)
            await insert_claim(conn, claim, validate_field=False)

            # default policy: 100 < 180 -> fresh -> no candidate.
            assert await _engine(conn).due_for_refresh(now=NOW) == ()

            # insert a global cadence_policy row shrinking the account TTL to 30d.
            await conn.execute(
                text(
                    """
                    INSERT INTO cadence_policy
                        (policy_id, client_id, field_class, ttl, refresh_cadence, version)
                    VALUES (:pid, NULL, CAST(:fc AS field_class), :ttl, :cadence, 1)
                    """
                ),
                {
                    "pid": "test-account-30d",
                    "fc": "account",
                    "ttl": timedelta(days=30),
                    "cadence": timedelta(days=30),
                },
            )
            policy = await load_cadence_policy(conn)
            assert policy.ttl_for(FieldClass.ACCOUNT) == timedelta(days=30)
            # same claim, swapped policy: 100 > 30 -> stale & due -> one candidate (no code change).
            candidates = await _engine(conn, policy=policy).due_for_refresh(now=NOW)
            assert [c.field_key for c in candidates] == ["account.swap_test"]

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_load_cadence_policy_prefers_client_then_global_then_default() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # no rows -> the built-in default.
            assert await load_cadence_policy(conn) == DEFAULT_CADENCE_POLICY
            # a global row and a per-client row for the same class; the client scope wins.
            for pid, client, days in (
                ("global-acct", None, 50),
                ("client-acct", "client-x", 7),
            ):
                await conn.execute(
                    text(
                        """
                        INSERT INTO cadence_policy
                            (policy_id, client_id, field_class, ttl, refresh_cadence, version)
                        VALUES (:pid, :client, CAST('account' AS field_class), :ttl, :ttl, 1)
                        """
                    ),
                    {"pid": pid, "client": client, "ttl": timedelta(days=days)},
                )
            global_policy = await load_cadence_policy(conn)
            client_policy = await load_cadence_policy(conn, client_id="client-x")
            assert global_policy.ttl_for(FieldClass.ACCOUNT) == timedelta(days=50)
            assert client_policy.ttl_for(FieldClass.ACCOUNT) == timedelta(days=7)
            # an unspecified class still falls back to the FreshnessTtls default.
            assert client_policy.ttl_for(FieldClass.CORE) == FreshnessTtls().by_field_class["core"]

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_merge_keeps_stale_usable_and_status_unchanged() -> None:
    # AC1 (DB): a past-TTL claim stays usable-but-refresh-eligible (the merge returns it as the
    # current value flagged stale when nothing fresher exists), and going stale never touches its
    # verification_status (the accuracy verdict is orthogonal).
    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_field(
                conn,
                FieldDef(
                    field_key="account.lonely_fact",
                    value_type="str",
                    pass_kind=PassKind.DEEP,
                    freshness_ttl=timedelta(days=180),
                ),
            )
            entity = new_entity_id()
            stale = _claim(
                field_key="account.lonely_fact",
                entity_id=entity,
                observed_days_ago=400,
                value="old",
            )
            await insert_claim(conn, stale, validate_field=False)
            status_before = (
                await conn.execute(
                    text("SELECT verification_status FROM claim WHERE id = :id"), {"id": stale.id}
                )
            ).scalar_one()

            # the only claim is stale -> still the current value, flagged stale (never dropped).
            cv = await current_value(conn, entity, "account.lonely_fact", scope=ALL_TENANTS)
            assert cv is not None
            assert cv.value_json == "old"
            assert cv.freshness_state is FreshnessState.STALE
            # the freshness engine agrees it is stale...
            assert (await _engine(conn).due_for_refresh(now=NOW))[
                0
            ].field_key == "account.lonely_fact"
            # ...and verification_status is untouched by any of it.
            status_after = (
                await conn.execute(
                    text("SELECT verification_status FROM claim WHERE id = :id"), {"id": stale.id}
                )
            ).scalar_one()
            assert status_before == status_after == "unverified"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_due_for_age_out_surfaces_expired_personal_only() -> None:
    # AC6: personal claims past the retention horizon are surfaced (EXPIRED) for M10.5 age-out; a
    # non-personal stale account claim is NOT an age-out candidate (it refreshes, never erases),
    # and a fresh personal claim is not surfaced.
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            expired = _facet_claim(observed_days_ago=200, entity_id=entity)  # > 180d retention
            fresh = _facet_claim(observed_days_ago=5, entity_id=new_entity_id())
            old_account = _claim(
                field_key="account.f1", observed_days_ago=400
            )  # stale, no retention
            for c in (expired, fresh, old_account):
                await insert_claim(conn, c, validate_field=False)

            aged = await _engine(conn).due_for_age_out(now=NOW)
            assert [str(c.claim_id) for c in aged] == [str(expired.id)]
            assert isinstance(aged[0], AgeOutCandidate)
            assert aged[0].field_key == "contact.facet.hobby"
            # the expired personal claim is NOT a refresh candidate (it ages out, not refreshes).
            refresh = await _engine(conn).due_for_refresh(now=NOW)
            assert str(expired.id) not in {str(cid) for c in refresh for cid in c.stale_claim_ids}

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_sensitive_personal_claim_expires_sooner() -> None:
    # the retention horizon is shorter for sensitive data (30d) than ordinary personal data (180d),
    # and the AgeOutCandidate reports the actual retention horizon it crossed (NOT the field TTL).
    async def _run() -> None:
        async with rollback_conn() as conn:
            sensitive = _facet_claim(observed_days_ago=40, use_class=UseClass.SENSITIVE)
            ordinary = _facet_claim(observed_days_ago=40)  # personal-public, 180d horizon
            for c in (sensitive, ordinary):
                await insert_claim(conn, c, validate_field=False)
            aged = await _engine(conn).due_for_age_out(now=NOW)
            assert {str(c.claim_id) for c in aged} == {
                str(sensitive.id)
            }  # only the 30d one expired
            # the surfaced candidate carries the 30d sensitive retention horizon, not the 90d
            # contact.facet freshness TTL (those are different quantities).
            assert aged[0].retention_days == RetentionTtls().sensitive_claim_ttl.days

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_unstamped_use_class_contact_does_not_age_out() -> None:
    # a plain contact.* claim born with use_class=None has no retention horizon (we never guess one
    # for an unclassified claim) -> it is never EXPIRED and never surfaced for age-out.
    async def _run() -> None:
        async with rollback_conn() as conn:
            claim = _claim(
                field_key="contact.role_on_committee",
                entity_type=EntityType.CONTACT,
                observed_days_ago=900,  # ancient, but unclassified -> no age-out
                research_mode=ResearchMode.CONTACT_PROFILING,
                use_class=None,
                identity_binding=IdentityBinding.STRONG,
                value="champion",
            )
            await insert_claim(conn, claim, validate_field=False)
            aged = await _engine(conn).due_for_age_out(now=NOW)
            assert aged == ()

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_record_re_research_candidates_idempotent() -> None:
    # the emission queue is append-only + idempotent: recording the same due window twice is a noop.
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            await insert_claim(
                conn,
                _claim(field_key="account.f1", entity_id=entity, observed_days_ago=300),
                validate_field=False,
            )
            engine = _engine(conn)
            candidates = await engine.due_for_refresh(now=NOW)
            assert candidates
            first = await engine.record_re_research_candidates(conn, candidates)
            second = await engine.record_re_research_candidates(conn, candidates)
            assert first == len(candidates)  # all newly inserted
            assert second == 0  # re-emitting the same window inserts nothing
            assert await _candidate_rows(conn) == len(candidates)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_scoring_stub_discounts_stale_signal() -> None:
    # AC3: the scoring layer (M6.3, here a local stub) reads the freshness signal and discounts a
    # stale claim. M9.5 only exposes the signal; the discount math is M6.3's.
    def _m63_discount(state: FreshnessState) -> float:
        return {FreshnessState.FRESH: 1.0, FreshnessState.STALE: 0.5, FreshnessState.EXPIRED: 0.0}[
            state
        ]

    async def _run() -> None:
        async with rollback_conn() as conn:
            engine = _engine(conn)
            fresh = engine.evaluate(_claim(field_key="account.f1", observed_days_ago=5), now=NOW)
            stale = engine.evaluate(_claim(field_key="account.f1", observed_days_ago=400), now=NOW)
            assert _m63_discount(stale.state) < _m63_discount(fresh.state)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_freshness_metrics_emitted() -> None:
    async def _run() -> tuple[int, int, int]:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            await insert_claim(
                conn,
                _claim(field_key="account.f1", entity_id=entity, observed_days_ago=300),
                validate_field=False,
            )
            await insert_claim(
                conn,
                _claim(field_key="account.f2", entity_id=entity, observed_days_ago=5),
                validate_field=False,
            )
            sink = InMemorySink()
            # Scope the scan to this test's entity: due_for_refresh's scan is global by default, so
            # the emitted scanned/stale/due counts would otherwise pick up committed claims left by
            # other tests when the whole suite shares one DB. Scoping keeps the asserted counts
            # deterministic without depending on a pristine table.
            await _engine(conn, sink=sink).due_for_refresh(entity_ids=(entity,), now=NOW)
            # the scan metrics carry an op="refresh" label (distinct from the age-out series).
            return (
                int(sink.counter(METRIC_FRESHNESS_SCANNED, op="refresh")),
                int(sink.counter(METRIC_FRESHNESS_STALE, op="refresh")),
                int(sink.counter(METRIC_FRESHNESS_DUE, op="refresh")),
            )

    scanned, stale, due = run_async(_run())
    assert scanned == 2 and stale == 1 and due == 1
    # the expired metric is only emitted when > 0; with no expired claim it is absent (0).


@pytest.mark.usefixtures("require_verification_db")
def test_freshness_span_emitted_with_counts() -> None:
    def _run() -> None:
        async def _inner() -> None:
            async with rollback_conn() as conn:
                entity = new_entity_id()
                await insert_claim(
                    conn,
                    _claim(field_key="account.f1", entity_id=entity, observed_days_ago=300),
                    validate_field=False,
                )
                # Scope the scan to this test's entity so the span counts stay deterministic under a
                # shared DB (the default scan is global; see the metrics test above).
                await _engine(conn).due_for_refresh(entity_ids=(entity,), now=NOW)

        run_async(_inner())

    with collect_spans() as exporter:
        _run()
    spans = [s for s in exporter.get_finished_spans() if s.name == SPAN_VERIFICATION_FRESHNESS]
    assert spans, "the freshness engine must emit its dedicated span"
    attrs = dict(spans[0].attributes or {})
    # one stale, due account claim -> scanned/stale/due == 1, expired == 0. M9-local span attrs go
    # through obs value-shape redaction, which renders the small int counts as their string form.
    assert str(attrs[ATTR_FRESHNESS_OP]) == "refresh"
    assert str(attrs[ATTR_FRESHNESS_SCANNED]) == "1"
    assert str(attrs[ATTR_FRESHNESS_STALE]) == "1"
    assert str(attrs[ATTR_FRESHNESS_DUE]) == "1"
    assert str(attrs[ATTR_FRESHNESS_EXPIRED]) == "0"


@pytest.mark.usefixtures("require_verification_db")
def test_discovery_claims_excluded_from_scan() -> None:
    # the scan is over field claims; a discovery-provenance claim (admission evidence, not a field
    # value) is never a re-research candidate even if old.
    async def _run() -> None:
        from clue_research.core import ClaimFlavor, DiscoveryProvenance

        async with rollback_conn() as conn:
            entity = new_entity_id()
            run = new_run_id()
            discovery = Claim(
                entity_id=entity,
                entity_type=EntityType.ACCOUNT,
                field_key="account.candidate",
                value_json="found",
                source_url="https://exa.local/x",
                source_tier=2,
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.9,
                observed_at=NOW - timedelta(days=900),
                collected_at=NOW - timedelta(days=900),
                run_id=run,
                research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                claim_flavor=ClaimFlavor.DISCOVERY,
                discovery_provenance=DiscoveryProvenance(
                    entity_id=entity,
                    found_via="exa_search",
                    matched_signal="icp match",
                    discovery_confidence=0.8,
                    run_id=run,
                    research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                ),
            )
            await insert_claim(conn, discovery, validate_field=False)
            assert await _engine(conn).due_for_refresh(now=NOW) == ()

    run_async(_run())
