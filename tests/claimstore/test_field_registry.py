"""M1.3 (ENG-117) — the field_definition registry, namespace rules, seed pack, and validation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy import text

from clue_core import Claim, FieldClass, FieldDef, PassKind, ReuseScope
from clue_research.claimstore import (
    FieldRedefinitionError,
    UnknownFieldError,
    ValueSchemaError,
    get_field,
    insert_claim,
    list_fields,
    load_core_pack,
    register_field,
    validate_value,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

_SCORING_SEED = {
    "core.employee_count",
    "core.primary_domain",
    "core.work_email",
    "core.primary_tech_stack",
    "account.recent_funding",
}
_DEEP_SEED = {
    "account.hiring_velocity_eng",
    "account.operational_pain",
    "account.strategic_moves",
    "account.resonance.culture",
    "contact.facet.recent_post",
}


def test_field_definition_schema_present() -> None:
    """Migration created field_definition with every §4 column plus the M1.3 extensions."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            cols = set(
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'field_definition'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        expected = {
            "field_key",
            "value_type",
            "validation",
            "tier_plan",
            "freshness_ttl",
            "pass_kind",
            "gate",
            "field_class",
            "value_schema",
            "corroboration_min",
            "description",
            "active",
            "pack",
            "version",
            "created_at",
        }
        assert expected <= cols, f"missing field_definition columns: {expected - cols}"

    run_async(_run())


def test_registry_enums_match_core() -> None:
    """field_pass / field_class pg_enums stay in lock-step with core PassKind / FieldClass."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT t.typname, e.enumlabel FROM pg_type t "
                        "JOIN pg_enum e ON e.enumtypid = t.oid "
                        "WHERE t.typname IN ('field_pass','field_class')"
                    )
                )
            ).all()
        by_type: dict[str, set[str]] = {}
        for typname, label in rows:
            by_type.setdefault(typname, set()).add(label)
        assert by_type["field_pass"] == {m.value for m in PassKind}
        assert by_type["field_class"] == {m.value for m in FieldClass}

    run_async(_run())


def test_field_definition_has_reuse_scope_column() -> None:
    """ENG-165 W1: the additive reuse_scope column is present on field_definition."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            cols = set(
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'field_definition'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert "reuse_scope" in cols

    run_async(_run())


def test_register_field_roundtrips_reuse_scope() -> None:
    """ENG-165 W1: a declared reuse_scope round-trips; an identical re-register is a no-op; changing
    it is a redefinition (a field's data-class is part of its contract)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fd = FieldDef(
                field_key="account.test_private",
                value_type="str",
                pass_kind=PassKind.SCORING,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
            )
            await register_field(conn, fd, value_schema={"type": "string"})
            stored = await get_field(conn, "account.test_private")
            assert stored is not None and stored.reuse_scope is ReuseScope.TENANT_PRIVATE
            # identical re-register is a no-op
            await register_field(conn, fd, value_schema={"type": "string"})
            # changing the declared scope is a redefinition (bump the version instead)
            with pytest.raises(FieldRedefinitionError):
                await register_field(
                    conn,
                    fd.model_copy(update={"reuse_scope": ReuseScope.PUBLIC_FOOTPRINT}),
                    value_schema={"type": "string"},
                )

    run_async(_run())


def test_scoring_output_keys_reserved_tenant_private() -> None:
    """ENG-165 W4: account.scoring.fit / .intent are seeded as Pass-A SCORING fields declared
    tenant_private — closing the 'ReusePolicy names account.scoring. but no field reserves it'
    gap (M2.5)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            for key in ("account.scoring.fit", "account.scoring.intent"):
                fd = await get_field(conn, key)
                assert fd is not None, f"{key} not registered"
                assert fd.pass_kind is PassKind.SCORING
                assert fd.reuse_scope is ReuseScope.TENANT_PRIVATE
                assert fd.field_class is FieldClass.ACCOUNT

    run_async(_run())


def test_register_rejects_unknown_namespace() -> None:
    """A field_key in an unregistered (non-canonical, undeclared-pack) namespace is rejected."""

    async def _run() -> None:
        fd = FieldDef(field_key="accont.headcount", value_type="int", pass_kind=PassKind.SCORING)
        async with rollback_conn() as conn:
            with pytest.raises(ValueError, match="unregistered namespace"):
                await register_field(conn, fd)

    run_async(_run())


def test_register_accepts_each_canonical_and_a_pack() -> None:
    """register_field accepts a key in each canonical namespace and a declared <pack>. namespace."""

    canonical = [
        "core.test_field",
        "account.test_field",
        "account.resonance.test_field",
        "contact.test_field",
        "contact.facet.test_field",
    ]

    async def _run() -> None:
        async with rollback_conn() as conn:
            for key in canonical:
                fd = FieldDef(field_key=key, value_type="str", pass_kind=PassKind.DEEP)
                await register_field(conn, fd, value_schema={"type": "string"})
                assert await get_field(conn, key) is not None
            # a vertical pack field, with the pack declared. Use a test-only namespace: production
            # packs (e.g. the icp starter packs' `healthcare.npi`) are COMMITTED by other tests on
            # a persistent schema, and re-registering one of their keys with a different definition
            # would (correctly) raise FieldRedefinitionError on a rerun.
            pack_fd = FieldDef(
                field_key="maritime.imo_number", value_type="str", pass_kind=PassKind.SCORING
            )
            await register_field(conn, pack_fd, pack="maritime", value_schema={"type": "string"})
            stored = await get_field(conn, "maritime.imo_number")
            assert stored is not None and stored.field_class is FieldClass.PACK
            # pack field without a declared pack is rejected
            with pytest.raises(ValueError, match="unregistered namespace"):
                await register_field(
                    conn,
                    FieldDef(field_key="fintech.mrr", value_type="int", pass_kind=PassKind.SCORING),
                )

    run_async(_run())


def test_validate_value_accepts_and_rejects() -> None:
    """validate_value accepts a payload matching value_schema and rejects a mismatch / unknown."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            # account.recent_funding requires {amount_usd: number}
            await validate_value(conn, "account.recent_funding", {"amount_usd": 5_000_000})
            with pytest.raises(ValueSchemaError, match="missing required key"):
                await validate_value(conn, "account.recent_funding", {"round": "Series A"})
            with pytest.raises(ValueSchemaError, match="expected number"):
                await validate_value(conn, "account.recent_funding", {"amount_usd": "lots"})
            # core.primary_tech_stack is an array of strings
            await validate_value(conn, "core.primary_tech_stack", ["python", "rust"])
            with pytest.raises(ValueSchemaError, match="expected string"):
                await validate_value(conn, "core.primary_tech_stack", ["python", 7])
            # unknown field is rejected
            with pytest.raises(UnknownFieldError):
                await validate_value(conn, "core.not_registered", 1)

    run_async(_run())


def test_insert_claim_refuses_invalid_payload(make_account: Callable[..., Claim]) -> None:
    """insert_claim rejects a claim whose value_json fails the field's value_schema."""

    async def _run() -> None:
        bad = make_account(value_json={"round": "Series B"})  # missing required amount_usd
        good = make_account(value_json={"amount_usd": 12_000_000})
        async with rollback_conn() as conn:
            with pytest.raises(ValueSchemaError):
                await insert_claim(conn, bad)
            claim_id = await insert_claim(conn, good)
        assert claim_id is not None

    run_async(_run())


def test_seed_pack_loads_idempotently() -> None:
    """Loading the core pack twice is a no-op (no error, no duplicate rows)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            before = (
                await conn.execute(text("SELECT count(*) FROM field_definition"))
            ).scalar_one()
            await load_core_pack(conn)  # already seeded by the session fixture
            after = (await conn.execute(text("SELECT count(*) FROM field_definition"))).scalar_one()
        assert before == after

    run_async(_run())


def test_list_fields_partitions_by_pass() -> None:
    """list_fields(pass='scoring') vs ('deep') partition the seeded fields correctly."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            scoring = {f.field_key for f in await list_fields(conn, pass_kind=PassKind.SCORING)}
            deep = {f.field_key for f in await list_fields(conn, pass_kind=PassKind.DEEP)}
        assert scoring >= _SCORING_SEED
        assert deep >= _DEEP_SEED
        assert scoring.isdisjoint(_DEEP_SEED)
        assert deep.isdisjoint(_SCORING_SEED)

    run_async(_run())


def test_governed_field_classes_are_deep() -> None:
    """The resonance + facet seed rows load as deep pass with their governed field-class set."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            facets = await list_fields(conn, field_class="contact.facet.*")
            resonance = await list_fields(conn, field_class=FieldClass.ACCOUNT_RESONANCE)
        # Membership, not exact equality: on a persistent schema other suites COMMIT further
        # governed fields (e.g. the icp starter packs' `account.resonance.research_prestige`).
        # The seed rows must be present, and EVERY governed-class row — seeded or committed by
        # another pack — must satisfy the deep-pass + field-class invariant.
        assert "contact.facet.recent_post" in {f.field_key for f in facets}
        assert all(
            f.pass_kind is PassKind.DEEP and f.field_class is FieldClass.CONTACT_FACET
            for f in facets
        )
        assert "account.resonance.culture" in {f.field_key for f in resonance}
        assert all(
            f.pass_kind is PassKind.DEEP and f.field_class is FieldClass.ACCOUNT_RESONANCE
            for f in resonance
        )

    run_async(_run())


def test_get_hiring_velocity_matches_substrate_example() -> None:
    """get_field('account.hiring_velocity_eng') returns the substrate §3 worked-example shape."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fd = await get_field(conn, "account.hiring_velocity_eng")
        assert fd is not None
        assert fd.tier_plan == ("sumble_jobs", "linkedin_jobs", "exa")
        assert fd.freshness_ttl == timedelta(days=30)
        assert fd.pass_kind is PassKind.DEEP
        assert fd.gate == "tier>=3"

    run_async(_run())


def test_two_packs_disjoint_load_and_redefinition_rejected() -> None:
    """Disjoint packs both load; re-registering an existing key with a different def is rejected."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            # Test-only namespaces (see test_register_accepts_each_canonical_and_a_pack): the
            # production `healthcare` starter pack may already be COMMITTED on a persistent schema.
            await register_field(
                conn,
                FieldDef(
                    field_key="maritime.imo_number", value_type="str", pass_kind=PassKind.SCORING
                ),
                pack="maritime",
            )
            await register_field(
                conn,
                FieldDef(field_key="fintech.mrr", value_type="int", pass_kind=PassKind.SCORING),
                pack="fintech",
            )
            assert await get_field(conn, "maritime.imo_number") is not None
            assert await get_field(conn, "fintech.mrr") is not None

            # idempotent re-register of an identical seed field is a no-op
            await register_field(
                conn,
                FieldDef(
                    field_key="core.employee_count",
                    value_type="int",
                    tier_plan=("clay", "apollo", "sumble_organizations"),
                    freshness_ttl=timedelta(days=90),
                    pass_kind=PassKind.SCORING,
                ),
                value_schema={"type": "integer"},
                description="Total headcount.",
            )
            # but a *different* definition for an existing key is rejected
            with pytest.raises(FieldRedefinitionError):
                await register_field(
                    conn,
                    FieldDef(
                        field_key="core.employee_count", value_type="str", pass_kind=PassKind.DEEP
                    ),
                )

    run_async(_run())
