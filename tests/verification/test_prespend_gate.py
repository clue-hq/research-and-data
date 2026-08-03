"""M9.1 (ENG-130) — pre-spend schema/identity gate.

Every §M9.1 acceptance criterion has a dedicated test. The pure helpers (``assemble_target_lock``,
``parse_gate_spec``, ``run_lock_token``) are exercised without a database (they run in ``make
check``); the gate's ``check`` is exercised against a live Postgres (skips without one, like the
claim-store/identity suites) because it reads the field registry, the entity store, and the
``source_manifest`` tier mapping, and writes the ``gate_decision`` audit row.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountEntity,
    AccountStatus,
    ContactEntity,
    EffectiveFieldSourcePlan,
    EffectiveSourceAuthorization,
    Entity,
    EntityScope,
    EntityType,
    EnumerationScope,
    FieldClass,
    FieldDef,
    ICPCreatedFrom,
    PassKind,
    PreSpendGate,
    PreSpendKind,
    PreSpendRequest,
    PreSpendVerdict,
    ResearchMode,
    SourceTier,
    new_entity_id,
    new_run_id,
)
from clue_obs.otel import InMemorySink
from clue_research.claimstore.registry import register_field
from clue_research.icp import (
    Pack,
    PackSourceSlot,
    SourceWeight,
    WeightedSource,
    create_icp_spec,
    register_pack_catalog,
    register_source_profile_override,
)
from clue_research.identity import (
    insert_account_entity,
    mark_merged,
)
from clue_research.sources import plan_sources
from clue_research.verification import (
    DEFAULT_PRE_SPEND_POLICY,
    GateSpec,
    PreSpendGateImpl,
    PreSpendPolicy,
    assemble_target_lock,
    load_pre_spend_policy,
    parse_gate_spec,
    run_lock_token,
)
from clue_research.verification.pre_spend import (
    METRIC_PRESPEND_BLOCKED,
    METRIC_PRESPEND_DECISIONS,
)
from tests._workspace import DEFAULT_TEST_WORKSPACE, seed_workspace

from .conftest import rollback_conn, run_async

# A minimal field def for the pure target-lock tests (no I/O).
_FIELD = FieldDef(field_key="core.employee_count", value_type="int", pass_kind=PassKind.SCORING)


# --- pure unit (no DB) ------------------------------------------------------


def test_parse_gate_spec_object_and_legacy() -> None:
    assert parse_gate_spec('{"requires_strong_key": true}') == GateSpec(requires_strong_key=True)
    assert parse_gate_spec('{"requires_official_domain": true}') == GateSpec(
        requires_official_domain=True
    )
    # legacy expressions / empty / non-object / unknown keys → no override (None)
    assert parse_gate_spec("tier>=1") is None
    assert parse_gate_spec("committee-gated") is None
    assert parse_gate_spec(None) is None
    assert parse_gate_spec("") is None
    assert parse_gate_spec("[1, 2]") is None
    assert parse_gate_spec('{"unknown_key": 1}') is None


def test_run_lock_token_is_the_run_id() -> None:
    run_id = new_run_id()
    assert run_lock_token(run_id) == str(run_id)


def test_assemble_target_lock_same_name_accounts_resolve_to_distinct_contexts() -> None:
    # the same-name trap: two real companies sharing a name resolve to distinct target locks.
    acme_com = AccountEntity(
        id=new_entity_id(),
        canonical_name="Acme",
        primary_domain="acme.com",
        workspace_id="ws-test",
    )
    acme_io = AccountEntity(
        id=new_entity_id(),
        canonical_name="Acme",
        primary_domain="acme.io",
        workspace_id="ws-test",
    )
    lock_com = assemble_target_lock(acme_com, _FIELD)
    lock_io = assemble_target_lock(acme_io, _FIELD)

    assert lock_com.canonical_domain == "acme.com"
    assert lock_io.canonical_domain == "acme.io"
    assert lock_com.canonical_domain != lock_io.canonical_domain
    assert lock_com.entity_id != lock_io.entity_id
    assert "acme.com" in lock_com.no_drift_instruction
    assert "acme.io" in lock_io.no_drift_instruction
    assert "do not drift" in lock_com.no_drift_instruction.lower()


def test_assemble_target_lock_account_without_domain_still_locks_by_name() -> None:
    nameless = AccountEntity(
        id=new_entity_id(),
        canonical_name="Stealth Co",
        primary_domain=None,
        workspace_id="ws-test",
    )
    lock = assemble_target_lock(nameless, _FIELD)
    assert lock.canonical_domain is None
    assert "Stealth Co" in lock.no_drift_instruction


def test_assemble_target_lock_contact_excludes_raw_email_and_flags_same_name_trap() -> None:
    contact = ContactEntity(
        id=new_entity_id(),
        account_entity_id=new_entity_id(),
        full_name="Jane Doe",
        linkedin_url="https://linkedin.com/in/jane",
        verified_email="jane@acme.com",
        workspace_id="ws-test",
    )
    lock = assemble_target_lock(contact, _FIELD)
    assert lock.canonical_domain is None
    assert "Jane Doe" in lock.no_drift_instruction
    assert "same-name trap" in lock.no_drift_instruction.lower()
    # the raw email is never placed in the prompt context — only a presence flag.
    assert lock.identifiers["has_verified_email"] is True
    assert "verified_email" not in lock.identifiers
    assert "jane@acme.com" not in str(lock.identifiers)


def test_default_policy_is_strict() -> None:
    assert DEFAULT_PRE_SPEND_POLICY.requires_strong_key is True
    assert DEFAULT_PRE_SPEND_POLICY.enforce_tier_in_plan is True
    assert DEFAULT_PRE_SPEND_POLICY.requires_in_flight_lock is True
    assert AccountStatus.CANDIDATE in DEFAULT_PRE_SPEND_POLICY.allowed_statuses
    assert AccountStatus.ACTIVE in DEFAULT_PRE_SPEND_POLICY.allowed_statuses


def test_impl_satisfies_the_frozen_prespend_gate_protocol() -> None:
    # the M9 impl is structurally the Beat-0 core seam other milestones call (no DB to build it).
    assert isinstance(PreSpendGateImpl(), PreSpendGate)


# --- DB-gated gate behaviour ------------------------------------------------


class _FakeLockReader:
    """A stand-in Redis reader returning a fixed holder token (or None for an unlocked entity)."""

    def __init__(self, holder: str | None) -> None:
        self._holder = holder

    async def get(self, name: str) -> object:
        return self._holder


def _gate(
    conn: AsyncConnection,
    *,
    policy: PreSpendPolicy = DEFAULT_PRE_SPEND_POLICY,
    lock_reader: _FakeLockReader | None = None,
    sink: InMemorySink | None = None,
) -> PreSpendGateImpl:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return PreSpendGateImpl(
        conn_factory=factory,
        policy=policy,
        lock_reader=lock_reader,
        record_decisions=True,
        sink=sink,
    )


async def _active_account(conn: AsyncConnection, *, name: str, domain: str | None) -> object:
    await seed_workspace(conn, DEFAULT_TEST_WORKSPACE)
    return await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=domain,
        status=AccountStatus.ACTIVE,
        workspace_id=DEFAULT_TEST_WORKSPACE,
    )


def _request(
    entity_id: object,
    *,
    field_key: str,
    tier: int,
    value: object | None = None,
    source_key: str | None = None,
    effective_source_plan: EffectiveFieldSourcePlan | None = None,
) -> PreSpendRequest:
    return PreSpendRequest(
        entity_id=entity_id,  # type: ignore[arg-type]
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        source_tier=tier,  # type: ignore[arg-type]
        source_key=source_key,
        effective_source_plan=effective_source_plan,
        run_id=new_run_id(),
        value_json=value,
    )


async def _decision_rows(conn: AsyncConnection, run_id: object) -> list[tuple[str, list[str]]]:
    rows = (
        await conn.execute(
            text("SELECT decision, reasons FROM gate_decision WHERE run_id = :r"),
            {"r": str(run_id)},
        )
    ).all()
    # ``reasons`` is jsonb; depending on the driver codec it comes back already-decoded or as text.
    return [(d, list(json.loads(r) if isinstance(r, str) else r)) for d, r in rows]


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
def test_pre_spend_verdict_enum_matches_core() -> None:
    """The DB pre_spend_verdict enum stays in lock-step with core.PreSpendVerdict (drift guard)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            labels = await _pg_enum_labels(conn, "pre_spend_verdict")
        assert labels == {m.value for m in PreSpendVerdict}

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_unknown_field_rejected_and_audited() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity_id = await _active_account(conn, name="Acme", domain="acme.com")
            req = _request(entity_id, field_key="core.not_a_real_field", tier=1)
            decision = await _gate(conn).check(req)
            assert decision.verdict is PreSpendVerdict.REJECT
            assert any("not registered" in r for r in decision.reasons)
            # the decision is recorded as an audit row.
            rows = await _decision_rows(conn, req.run_id)
            assert rows == [("reject", list(decision.reasons))]

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_tier_not_in_plan_rejected() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity_id = await _active_account(conn, name="Acme", domain="acme.com")
            # employee_count's tier_plan (clay, apollo) is all tier 1; tier 4 is unsanctioned.
            req = _request(entity_id, field_key="core.employee_count", tier=4)
            decision = await _gate(conn).check(req)
            assert decision.verdict is PreSpendVerdict.REJECT
            assert any("tier_plan" in r for r in decision.reasons)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_valid_request_passes_and_audited() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity_id = await _active_account(conn, name="Acme", domain="acme.com")
            req = _request(entity_id, field_key="core.employee_count", tier=1, value=42)
            decision = await _gate(conn).check(req)
            assert decision.verdict is PreSpendVerdict.PASS
            assert decision.reasons == ()
            rows = await _decision_rows(conn, req.run_id)
            assert rows == [("pass", [])]

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_exact_source_key_cannot_borrow_an_allowed_tier() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity_id = await _active_account(conn, name="Acme", domain="acme.com")
            # BuiltWith is registered at the same tier as employee_count's Clay/Apollo/Sumble
            # plan, but exact-provider authorization must reject it.
            req = _request(
                entity_id,
                field_key="core.employee_count",
                tier=1,
                source_key="builtwith",
            )
            decision = await _gate(conn).check(req)
            assert decision.verdict is PreSpendVerdict.REJECT
            assert any(
                "source_key" in reason and "tier_plan" in reason for reason in decision.reasons
            )

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_content_addressed_effective_plan_is_the_exact_gate_authority() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity_id = await _active_account(conn, name="Acme", domain="acme.com")
            await register_pack_catalog(
                conn,
                Pack(
                    pack_key="prespend_effective_plan",
                    namespace="prespend_effective_plan",
                    title="Pre-spend effective plan",
                    source_profile=(
                        PackSourceSlot(
                            field_class=FieldClass.ACCOUNT,
                            sources=(
                                WeightedSource(
                                    source_key="firecrawl_site",
                                    weight=SourceWeight.HIGH,
                                    rank=1,
                                ),
                                WeightedSource(
                                    source_key="exa_deep",
                                    weight=SourceWeight.MEDIUM,
                                    rank=2,
                                ),
                            ),
                        ),
                    ),
                ),
            )
            spec = await create_icp_spec(
                conn,
                workspace_id=DEFAULT_TEST_WORKSPACE,
                icp_key="prespend-effective-plan",
                created_from=ICPCreatedFrom.CLIENT_EDIT,
                field_keys=("account.operational_pain",),
                enabled_packs=("prespend_effective_plan",),
            )
            ordered = await plan_sources(
                conn,
                spec=spec,
                entity=Entity(entity_id=entity_id, entity_type=EntityType.ACCOUNT),
                field="account.operational_pain",
                mode=ResearchMode.ACCOUNT_PROFILING,
                entity_scope=EntityScope.ACCOUNT,
            )
            plan = ordered.effective_source_plan
            assert plan is not None
            assert {source.source_key for source in plan.sources} == {
                "firecrawl_site",
                "exa_deep",
            }
            forged = EffectiveFieldSourcePlan.compile(
                workspace_id=plan.workspace_id,
                icp_key=plan.icp_key,
                icp_version=plan.icp_version,
                field_key=plan.field_key,
                sources=(
                    *plan.sources,
                    EffectiveSourceAuthorization(
                        source_key="parallel_task", source_tier=SourceTier(4)
                    ),
                ),
            )
            forged_decision = await _gate(conn).check(
                _request(
                    entity_id,
                    field_key="account.operational_pain",
                    tier=4,
                    source_key="parallel_task",
                    effective_source_plan=forged,
                )
            )
            assert forged_decision.verdict is PreSpendVerdict.REJECT
            assert any("database-derived canonical" in reason for reason in forged_decision.reasons)
            assert (
                await conn.execute(text("SELECT count(*) FROM effective_field_source_plan"))
            ).scalar_one() == 0

            allowed = _request(
                entity_id,
                field_key="account.operational_pain",
                tier=2,
                source_key="firecrawl_site",
                effective_source_plan=plan,
            )
            assert (await _gate(conn).check(allowed)).verdict is PreSpendVerdict.PASS

            denied = _request(
                entity_id,
                field_key="account.operational_pain",
                tier=4,
                source_key="parallel_task",
                effective_source_plan=plan,
            )
            decision = await _gate(conn).check(denied)
            assert decision.verdict is PreSpendVerdict.REJECT
            assert any(plan.plan_sha256 in reason for reason in decision.reasons)

            audited = (
                (
                    await conn.execute(
                        text(
                            "SELECT source_key, effective_plan_sha256, effective_source_plan "
                            "FROM gate_decision WHERE run_id=:run_id"
                        ),
                        {"run_id": str(allowed.run_id)},
                    )
                )
                .mappings()
                .one()
            )
            assert audited["source_key"] == "firecrawl_site"
            assert audited["effective_plan_sha256"] == plan.plan_sha256
            assert audited["effective_source_plan"]["field_key"] == "account.operational_pain"
            frozen = (
                (
                    await conn.execute(
                        text(
                            "SELECT plan_sha256, plan_json FROM effective_field_source_plan "
                            "WHERE workspace_id=:workspace_id AND icp_key=:icp_key "
                            "AND icp_version=:icp_version AND field_key=:field_key"
                        ),
                        {
                            "workspace_id": spec.workspace_id,
                            "icp_key": spec.icp_key,
                            "icp_version": spec.version,
                            "field_key": "account.operational_pain",
                        },
                    )
                )
                .mappings()
                .one()
            )
            assert frozen["plan_sha256"] == plan.plan_sha256
            assert frozen["plan_json"] == plan.model_dump(mode="json")

            # The application uses insert-once semantics, and the database enforces the same
            # authority boundary against out-of-band rewrites or deletion.
            with pytest.raises(DBAPIError, match="effective field source plan is immutable"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE effective_field_source_plan SET source_profile_ref='{}'::jsonb "
                            "WHERE plan_sha256=:plan_sha256"
                        ),
                        {"plan_sha256": plan.plan_sha256},
                    )
            with pytest.raises(DBAPIError, match="effective field source plan is immutable"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "DELETE FROM effective_field_source_plan WHERE plan_sha256=:plan_sha256"
                        ),
                        {"plan_sha256": plan.plan_sha256},
                    )

            # Erasing the owning ICP is different from rewriting authority in place. The FK
            # cascade must be able to remove the plan so the new row cannot make tenant/ICP
            # lifecycle deletion impossible.
            async with conn.begin_nested() as erasure:
                await conn.execute(
                    text(
                        "DELETE FROM icp_spec WHERE workspace_id=:workspace_id "
                        "AND icp_key=:icp_key AND version=:icp_version"
                    ),
                    {
                        "workspace_id": spec.workspace_id,
                        "icp_key": spec.icp_key,
                        "icp_version": spec.version,
                    },
                )
                assert (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM effective_field_source_plan "
                            "WHERE plan_sha256=:plan_sha256"
                        ),
                        {"plan_sha256": plan.plan_sha256},
                    )
                ).scalar_one() == 0
                await erasure.rollback()

            # A later mutable source-profile row cannot widen an already-pinned ICP/field. The
            # execution plan may reorder/narrow the frozen members, but Parallel remains compiled
            # out and the authority digest is stable.
            await register_source_profile_override(
                conn,
                "prespend_effective_plan",
                DEFAULT_TEST_WORKSPACE,
                (
                    WeightedSource(source_key="parallel_task", weight=SourceWeight.HIGH, rank=1),
                    WeightedSource(source_key="firecrawl_site", weight=SourceWeight.HIGH, rank=2),
                    WeightedSource(source_key="exa_deep", weight=SourceWeight.MEDIUM, rank=3),
                ),
                field_class=FieldClass.ACCOUNT,
                icp_key=spec.icp_key,
                version=1,
            )
            replay_plan = await plan_sources(
                conn,
                spec=spec,
                entity=Entity(entity_id=entity_id, entity_type=EntityType.ACCOUNT),
                field="account.operational_pain",
                mode=ResearchMode.ACCOUNT_PROFILING,
                entity_scope=EntityScope.ACCOUNT,
            )
            assert replay_plan.effective_source_plan == plan
            assert "parallel_task" not in replay_plan.tier_plan()

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_enumeration_source_key_cannot_borrow_an_allowed_tier() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity_id = await _active_account(conn, name="Acme", domain="acme.com")
            decision = await _gate(conn).check(
                PreSpendRequest(
                    entity_id=entity_id,
                    entity_type=EntityType.ACCOUNT,
                    kind=PreSpendKind.ENUMERATION,
                    scope=EnumerationScope.COMMITTEE,
                    source_tier=SourceTier(1),
                    source_key="unregistered_same_tier_people_source",
                    run_id=new_run_id(),
                )
            )
            assert decision.verdict is PreSpendVerdict.REJECT
            assert decision.reasons == (
                "source_key 'unregistered_same_tier_people_source' is not registered",
            )

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_invalid_value_json_rejected() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity_id = await _active_account(conn, name="Acme", domain="acme.com")
            # core.employee_count value_schema is {"type": "integer"}; a string fails it.
            req = _request(entity_id, field_key="core.employee_count", tier=1, value="lots")
            decision = await _gate(conn).check(req)
            assert decision.verdict is PreSpendVerdict.REJECT
            assert any("schema" in r for r in decision.reasons)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_unresolved_entity_rejected() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # a random entity_id that resolves to no row (raw hypothesis / free-text name)
            req = _request(new_entity_id(), field_key="core.employee_count", tier=1)
            decision = await _gate(conn).check(req)
            assert decision.verdict is PreSpendVerdict.REJECT
            assert any("does not resolve" in r for r in decision.reasons)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_merged_entity_rejected() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            loser = await _active_account(conn, name="Old Acme", domain="old-acme.com")
            survivor = await _active_account(conn, name="Acme", domain="acme.com")
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)  # type: ignore[arg-type]
            req = _request(loser, field_key="core.employee_count", tier=1)
            decision = await _gate(conn).check(req)
            assert decision.verdict is PreSpendVerdict.REJECT
            assert any("merged" in r for r in decision.reasons)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_weakly_keyed_entity_rejected() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # active but no primary_domain → no strong key.
            entity_id = await _active_account(conn, name="Stealth Co", domain=None)
            req = _request(entity_id, field_key="core.employee_count", tier=1)
            decision = await _gate(conn).check(req)
            assert decision.verdict is PreSpendVerdict.REJECT
            assert any("strong key" in r for r in decision.reasons)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_inflight_lock_held_by_different_run_rejected() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity_id = await _active_account(conn, name="Acme", domain="acme.com")
            gate = _gate(conn, lock_reader=_FakeLockReader("some-other-run-token"))
            req = _request(entity_id, field_key="core.employee_count", tier=1)
            decision = await gate.check(req)
            assert decision.verdict is PreSpendVerdict.REJECT
            assert any("different run" in r for r in decision.reasons)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_inflight_lock_held_by_same_run_passes() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity_id = await _active_account(conn, name="Acme", domain="acme.com")
            req = _request(entity_id, field_key="core.employee_count", tier=1)
            # the run holds its own lock (token == run_lock_token(run_id)) → not a double-spend.
            gate = _gate(conn, lock_reader=_FakeLockReader(run_lock_token(req.run_id)))
            decision = await gate.check(req)
            assert decision.verdict is PreSpendVerdict.PASS

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_config_swap_relaxes_strong_key_with_no_code_change() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            entity_id = await _active_account(conn, name="Stealth Co", domain=None)
            req = _request(entity_id, field_key="core.employee_count", tier=1)
            # default policy rejects the domainless entity...
            assert (await _gate(conn).check(req)).verdict is PreSpendVerdict.REJECT
            # ...flipping the rule in config lets it through, with no code change.
            relaxed = PreSpendPolicy(requires_strong_key=False)
            assert (await _gate(conn, policy=relaxed).check(req)).verdict is PreSpendVerdict.PASS

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_load_pre_spend_policy_reads_the_most_specific_row() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # no row → built-in default.
            assert await load_pre_spend_policy(conn) == DEFAULT_PRE_SPEND_POLICY
            # a global default row overrides the built-in default.
            await conn.execute(
                text(
                    "INSERT INTO pre_spend_policy (policy_id, rules_json) "
                    "VALUES ('global', CAST(:r AS jsonb))"
                ),
                {"r": '{"requires_strong_key": false}'},
            )
            # a per-client row is more specific and wins for that client.
            await conn.execute(
                text(
                    "INSERT INTO pre_spend_policy (policy_id, workspace_id, rules_json) "
                    "VALUES ('acme', 'acme', CAST(:r AS jsonb))"
                ),
                {"r": '{"enforce_tier_in_plan": false}'},
            )
            glob = await load_pre_spend_policy(conn)
            assert glob.requires_strong_key is False
            acme = await load_pre_spend_policy(conn, workspace_id="acme")
            assert acme.enforce_tier_in_plan is False

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_duplicate_global_default_row_is_rejected() -> None:
    """B4 slice 1 (``[M9.1×M0.4]``): ``pre_spend_policy_scope_version`` is now ``NULLS NOT
    DISTINCT``, so the global-default slot (``workspace_id`` NULL, ``icp_version`` NULL) admits only
    ONE row per version — a second same-version global row is a write-time IntegrityError, not a
    silent duplicate the loader could resolve non-deterministically."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await conn.execute(
                text(
                    "INSERT INTO pre_spend_policy (policy_id, rules_json, version) "
                    "VALUES ('g1', CAST(:r AS jsonb), 1)"
                ),
                {"r": "{}"},
            )
            sp = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO pre_spend_policy (policy_id, rules_json, version) "
                        "VALUES ('g2', CAST(:r AS jsonb), 1)"  # same (NULL, NULL, 1) slot
                    ),
                    {"r": "{}"},
                )
            await sp.rollback()

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_load_pre_spend_policy_picks_the_latest_version_deterministically() -> None:
    """The loader is deterministic: the highest ``version`` within a scope wins, with the
    ``created_at``/``policy_id`` tie-break (B4 slice 1) as the belt for a pre-existing duplicate."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            # Two global rows at different versions — v2 must win (ORDER BY version DESC).
            await conn.execute(
                text(
                    "INSERT INTO pre_spend_policy (policy_id, rules_json, version) VALUES "
                    "('gv1', CAST(:a AS jsonb), 1), ('gv2', CAST(:b AS jsonb), 2)"
                ),
                {"a": '{"requires_strong_key": true}', "b": '{"requires_strong_key": false}'},
            )
            policy = await load_pre_spend_policy(conn)
            assert policy.requires_strong_key is False  # v2 (the latest version) won

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_per_field_gate_spec_overrides_a_relaxed_policy() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # a field whose gate_spec demands a strong key, even though the global policy does not.
            await register_field(
                conn,
                FieldDef(
                    field_key="core.gated_probe",
                    value_type="str",
                    pass_kind=PassKind.SCORING,
                    tier_plan=("clay",),
                    gate='{"requires_strong_key": true}',
                ),
            )
            entity_id = await _active_account(conn, name="Stealth Co", domain=None)
            req = _request(entity_id, field_key="core.gated_probe", tier=1)
            relaxed = PreSpendPolicy(requires_strong_key=False)
            decision = await _gate(conn, policy=relaxed).check(req)
            assert decision.verdict is PreSpendVerdict.REJECT
            assert any("strong key" in r for r in decision.reasons)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_blocked_pre_spend_metric_emitted() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            sink = InMemorySink()
            entity_id = await _active_account(conn, name="Acme", domain="acme.com")
            # a reject (tier 4 not in the tier-1 plan) increments both the decisions and blocked
            # counters, labelled by entity_type + source_tier.
            reject_req = _request(entity_id, field_key="core.employee_count", tier=4)
            await _gate(conn, sink=sink).check(reject_req)
            assert (
                sink.counter(METRIC_PRESPEND_BLOCKED, entity_type="account", source_tier="4") == 1
            )
            assert (
                sink.counter(METRIC_PRESPEND_DECISIONS, entity_type="account", source_tier="4") == 1
            )
            # a pass increments decisions but not blocked.
            pass_req = _request(entity_id, field_key="core.employee_count", tier=1, value=42)
            await _gate(conn, sink=sink).check(pass_req)
            assert (
                sink.counter(METRIC_PRESPEND_BLOCKED, entity_type="account", source_tier="1") == 0
            )
            assert (
                sink.counter(METRIC_PRESPEND_DECISIONS, entity_type="account", source_tier="1") == 1
            )

    run_async(_run())
