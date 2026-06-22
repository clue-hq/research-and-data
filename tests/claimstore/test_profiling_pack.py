"""M8 tiny seed (ENG-136 / ENG-154) — the ``account.resonance.*`` + ``contact.facet.*`` field-class
registry pack and its governance/freshness/open-by-registration guarantees.

Two planes:

* **Pure (no DB)** — the pack's *shape* (classification into the governed field-classes, the facet
  freshness ceiling, the resonance firewall, the facet use-class hints) and the **structural
  governance** a facet claim rides (``core.claim`` validator + ``can_be_promoted``). These run in a
  plain ``make check``.
* **DB-gated** (``require_claimstore_db``) — registering the rows and asserting the M8.2/M8.5
  acceptance criteria against the live ``field_definition`` registry: rows present, ``pass=deep``,
  facet ``freshness_ttl`` < ``core.employee_count``, ``reuse_scope`` tenant-private, idempotent
  load, open-by-registration, ``value_schema`` validation. These ``pytest.skip`` without a DB.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from clue_research.claimstore import (
    FieldRedefinitionError,
    ValueSchemaError,
    get_field,
    list_fields,
    register_field,
    validate_value,
)
from clue_research.core import (
    Claim,
    EntityType,
    ExtractionMethod,
    FieldClass,
    FieldDef,
    IdentityBinding,
    PassKind,
    ResearchMode,
    ReuseScope,
    UseClass,
    can_be_promoted,
    classify_field_key,
    contact_claim,
    new_entity_id,
    new_run_id,
    resolve_reuse_scope,
)
from clue_research.profiling import (
    DEEP_PROFILING_PACK,
    FACET_FIELD_KEYS,
    FACET_PACK,
    RESONANCE_FIELD_KEYS,
    RESONANCE_PACK,
    load_deep_profiling_pack,
)
from clue_research.profiling.fields import (
    FACET_CAUSES,
    FACET_NICKNAME,
    FACET_PUBLICATIONS,
    RESONANCE_EMPLOYEE_SENTIMENT,
)

from .conftest import rollback_conn, run_async

_FIRMOGRAPHIC_TTL = timedelta(days=90)  # core.employee_count — the M8.5 AC1 ceiling
_VALID_USE_CLASSES = {uc.value for uc in UseClass}
# The two CORE_PACK proof rows + the icp resonance contribution — the seed must NOT redeclare these.
_FOREIGN_KEYS = {
    "account.resonance.culture",
    "contact.facet.recent_post",
    "account.resonance.research_prestige",
}


# --------------------------------------------------------------------------- pure (no DB)


def test_pack_keys_classify_into_governed_field_classes() -> None:
    """Every resonance key is ACCOUNT_RESONANCE and every facet key is CONTACT_FACET — so each rides
    the right machinery (the facet DB CHECK + use-gate, the resonance firewall). M8.2/M8.5."""
    assert RESONANCE_FIELD_KEYS  # non-empty
    assert FACET_FIELD_KEYS
    for key in RESONANCE_FIELD_KEYS:
        assert classify_field_key(key) is FieldClass.ACCOUNT_RESONANCE, key
    for key in FACET_FIELD_KEYS:
        assert classify_field_key(key) is FieldClass.CONTACT_FACET, key


def test_pack_is_disjoint_from_foreign_rows() -> None:
    """The seed leaves the two CORE_PACK proof rows and the icp resonance contribution alone (no
    FieldRedefinitionError at load; the class is federated across packs)."""
    seeded = set(RESONANCE_FIELD_KEYS) | set(FACET_FIELD_KEYS)
    assert seeded.isdisjoint(_FOREIGN_KEYS)


def test_every_field_is_deep_pass() -> None:
    for seed in DEEP_PROFILING_PACK:
        assert seed.field_def.pass_kind is PassKind.DEEP, seed.field_def.field_key


def test_resonance_tier_plan_ends_in_tier4_synthesis() -> None:
    """M8.2 AC1: a tier_plan ending in tier-4 synthesis (exa_deep / parallel_task)."""
    for seed in RESONANCE_PACK:
        assert seed.field_def.tier_plan, seed.field_def.field_key
        assert seed.field_def.tier_plan[-1] in {"exa_deep", "parallel_task"}, (
            seed.field_def.field_key
        )


def test_resonance_declares_the_sensitivity_firewall() -> None:
    """M8.2 AC6: every resonance field-def declares the account-scoped firewall (a named
    individual's special-category attribute must not be smuggled into a resonance value)."""
    for seed in RESONANCE_PACK:
        validation = seed.field_def.validation or {}
        assert validation.get("account_scoped") is True, seed.field_def.field_key
        assert validation.get("excludes_named_individual_special_category") is True, (
            seed.field_def.field_key
        )
        # account-scoped resonance carries no personal use-class hint
        assert "use_class_hint" not in validation, seed.field_def.field_key


def test_facet_freshness_ttl_shorter_than_firmographic() -> None:
    """M8.5 AC1: every facet field is staler-sooner than a firmographic fact (< 90d), and graded."""
    for seed in FACET_PACK:
        ttl = seed.field_def.freshness_ttl
        assert ttl is not None, seed.field_def.field_key
        assert ttl < _FIRMOGRAPHIC_TTL, (seed.field_def.field_key, ttl)


def test_facet_use_class_hints_present_and_valid() -> None:
    """M8.5 AC4: a per-field use-class hint is present and is a real UseClass value (a *starting
    point* M8.4 refines — not the authoritative tag)."""
    hints = {}
    for seed in FACET_PACK:
        validation = seed.field_def.validation or {}
        hint = validation.get("use_class_hint")
        assert hint in _VALID_USE_CLASSES, (seed.field_def.field_key, hint)
        hints[seed.field_def.field_key] = hint
    # spot-check the Doc D §2 hints the spec names verbatim
    assert hints[FACET_PUBLICATIONS] == UseClass.PROFESSIONAL_PUBLIC.value
    assert hints[FACET_CAUSES] == UseClass.SENSITIVE.value
    assert hints[FACET_NICKNAME] == UseClass.PERSONAL_PUBLIC_NON_SENSITIVE.value


def test_facet_fields_inherit_tenant_private_reuse_scope() -> None:
    """contact.facet/account.resonance default to TENANT_PRIVATE; the seed leaves reuse_scope unset
    and relies on that class default (matching the existing canonical rows)."""
    for seed in DEEP_PROFILING_PACK:
        assert seed.field_def.reuse_scope is None, seed.field_def.field_key  # unset → inherit
        assert resolve_reuse_scope(seed.field_def) is ReuseScope.TENANT_PRIVATE, (
            seed.field_def.field_key
        )


def _facet_claim(binding: IdentityBinding) -> Claim:
    return contact_claim(
        entity_id=new_entity_id(),
        field_key=FACET_NICKNAME,
        value_json="Bob",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
        identity_binding=binding,
        use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
        source_url="https://www.linkedin.com/in/bob",
    )


def test_facet_claim_weak_binding_is_not_promotable() -> None:
    """Structural governance the facet class rides: a WEAK-bound contact claim never promotes
    (better an empty hook than a same-name stranger's fact); a STRONG one is eligible."""
    assert can_be_promoted(_facet_claim(IdentityBinding.WEAK)) is False
    assert can_be_promoted(_facet_claim(IdentityBinding.STRONG)) is True


def test_facet_claim_requires_governance_tags() -> None:
    """A contact.facet.* field claim cannot even be CONSTRUCTED without identity_binding + use_class
    (core.claim validator, mirroring the DB CHECK) — governance is structural to the field-class, so
    the seed's facet field-defs need encode nothing for it."""
    with pytest.raises(ValidationError):
        Claim(
            entity_id=new_entity_id(),
            entity_type=EntityType.CONTACT,
            field_key=FACET_NICKNAME,
            value_json="Bob",
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.9,
            run_id=new_run_id(),
            research_mode=ResearchMode.CONTACT_PROFILING,
            source_url="https://www.linkedin.com/in/bob",
            # identity_binding / use_class deliberately omitted
        )


# --------------------------------------------------------------------------- DB-gated


@pytest.mark.usefixtures("require_claimstore_db")
def test_pack_registers_all_fields_as_deep() -> None:
    """M8.2 AC1 / M8.5 AC1: the rows are present, classified, and pass=deep."""

    async def _run() -> None:
        async with rollback_conn() as conn:  # seeds CORE_PACK
            await load_deep_profiling_pack(conn)
            for key in RESONANCE_FIELD_KEYS:
                fd = await get_field(conn, key)
                assert fd is not None, key
                assert fd.field_class is FieldClass.ACCOUNT_RESONANCE
                assert fd.pass_kind is PassKind.DEEP
            for key in FACET_FIELD_KEYS:
                fd = await get_field(conn, key)
                assert fd is not None, key
                assert fd.field_class is FieldClass.CONTACT_FACET
                assert fd.pass_kind is PassKind.DEEP

    run_async(_run())


@pytest.mark.usefixtures("require_claimstore_db")
def test_facet_ttl_strictly_under_registered_employee_count() -> None:
    """M8.5 AC1 against the live registry: every facet field's freshness_ttl < the registered
    core.employee_count ttl."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_deep_profiling_pack(conn)
            employee_count = await get_field(conn, "core.employee_count")
            assert employee_count is not None and employee_count.freshness_ttl is not None
            for key in FACET_FIELD_KEYS:
                fd = await get_field(conn, key)
                assert fd is not None and fd.freshness_ttl is not None, key
                assert fd.freshness_ttl < employee_count.freshness_ttl, key

    run_async(_run())


@pytest.mark.usefixtures("require_claimstore_db")
def test_fields_register_tenant_private() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_deep_profiling_pack(conn)
            for key in (*RESONANCE_FIELD_KEYS, *FACET_FIELD_KEYS):
                fd = await get_field(conn, key)
                assert fd is not None, key
                assert resolve_reuse_scope(fd) is ReuseScope.TENANT_PRIVATE, key

    run_async(_run())


@pytest.mark.usefixtures("require_claimstore_db")
def test_pack_loads_idempotently() -> None:
    """Loading twice is a no-op (a pack loads cleanly under any bootstrap order)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await load_deep_profiling_pack(conn)
            res1 = {
                f.field_key
                for f in await list_fields(conn, field_class=FieldClass.ACCOUNT_RESONANCE)
            }
            fac1 = {
                f.field_key for f in await list_fields(conn, field_class=FieldClass.CONTACT_FACET)
            }
            await load_deep_profiling_pack(conn)  # second load is a no-op (no redefinition error)
            res2 = {
                f.field_key
                for f in await list_fields(conn, field_class=FieldClass.ACCOUNT_RESONANCE)
            }
            fac2 = {
                f.field_key for f in await list_fields(conn, field_class=FieldClass.CONTACT_FACET)
            }
            # idempotent: re-loading adds no rows (robust to any rows already in the class)
            assert res1 == res2
            assert fac1 == fac2
            # and every seeded key is present
            assert set(RESONANCE_FIELD_KEYS) <= res2
            assert set(FACET_FIELD_KEYS) <= fac2

    run_async(_run())


@pytest.mark.usefixtures("require_claimstore_db")
def test_open_by_registration_new_fields() -> None:
    """M8.2 AC1 / M8.5 AC3: adding a new resonance/facet field is a single row insert, no code
    change — registered and picked up by list_fields."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await register_field(
                conn,
                FieldDef(
                    field_key="account.resonance.brand_warmth",
                    value_type="object",
                    pass_kind=PassKind.DEEP,
                    tier_plan=("exa_deep",),
                ),
            )
            await register_field(
                conn,
                FieldDef(
                    field_key="contact.facet.side_project",
                    value_type="str",
                    pass_kind=PassKind.DEEP,
                    freshness_ttl=timedelta(days=30),
                ),
            )
            res = await list_fields(conn, field_class=FieldClass.ACCOUNT_RESONANCE)
            fac = await list_fields(conn, field_class=FieldClass.CONTACT_FACET)
            assert "account.resonance.brand_warmth" in {f.field_key for f in res}
            assert "contact.facet.side_project" in {f.field_key for f in fac}

    run_async(_run())


@pytest.mark.usefixtures("require_claimstore_db")
def test_value_schema_accepts_and_rejects() -> None:
    """The declared value_schema validates payloads (the sentiment {label, polarity, summary}
    shape M8.2 quotes verbatim)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_deep_profiling_pack(conn)
            await validate_value(
                conn,
                RESONANCE_EMPLOYEE_SENTIMENT,
                {"label": "positive", "polarity": 0.8, "summary": "broadly upbeat"},
            )
            with pytest.raises(ValueSchemaError):  # missing required "label"
                await validate_value(conn, RESONANCE_EMPLOYEE_SENTIMENT, {"polarity": 0.8})
            with pytest.raises(ValueSchemaError):  # label not in enum
                await validate_value(conn, RESONANCE_EMPLOYEE_SENTIMENT, {"label": "ecstatic"})

    run_async(_run())


@pytest.mark.usefixtures("require_claimstore_db")
def test_redefinition_with_a_different_def_is_rejected() -> None:
    """A field's contract does not silently change underneath its claims (bump the version)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_deep_profiling_pack(conn)
            with pytest.raises(FieldRedefinitionError):
                await register_field(
                    conn,
                    FieldDef(
                        field_key=FACET_NICKNAME,
                        value_type="str",
                        pass_kind=PassKind.SCORING,  # changed from DEEP
                    ),
                )

    run_async(_run())
