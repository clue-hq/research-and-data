"""FI-2 P3 — ``research_scope``, the field-species attribute (spec §4/§5).

Species is *registry data*, exactly like ``reuse_scope``: a nullable declaration on the field
definition, a class/key default in ``core`` when it is undeclared, and a fail-loud guard so a
``<pack>.*`` field cannot enter the registry without declaring one. These tests pin the founder-
ratified species table (§5.2), the declaration→default precedence, the registration guard, and the
DB value domain.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clue_core import (
    FieldClass,
    FieldDef,
    PassKind,
    ResearchScope,
    ReuseScope,
    classify_field_key,
    default_research_scope,
    resolve_research_scope,
)
from clue_research.claimstore import (
    ResearchScopeError,
    get_field,
    register_field,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def _default_for(field_key: str) -> ResearchScope:
    return default_research_scope(classify_field_key(field_key), field_key)


# --- (c) the ratified default table (§5.2) ---------------------------------


@pytest.mark.parametrize(
    ("field_key", "expected"),
    [
        # relative: definitionally ICP/product/campaign-relative
        ("account.scoring.fit", ResearchScope.PROJECT_RELATIVE),
        ("account.scoring.intent", ResearchScope.PROJECT_RELATIVE),
        ("account.scoring.tier", ResearchScope.PROJECT_RELATIVE),
        ("account.value_narrative", ResearchScope.PROJECT_RELATIVE),
        ("contact.persona", ResearchScope.PROJECT_RELATIVE),
        ("contact.role_on_committee", ResearchScope.PROJECT_RELATIVE),
        # neutral: world-facts about the account/contact
        ("core.employee_count", ResearchScope.PROJECT_NEUTRAL),
        ("core.account_name", ResearchScope.PROJECT_NEUTRAL),
        ("account.recent_funding", ResearchScope.PROJECT_NEUTRAL),
        ("account.operational_pain", ResearchScope.PROJECT_NEUTRAL),
        ("account.strategic_moves", ResearchScope.PROJECT_NEUTRAL),
        ("account.resonance.culture", ResearchScope.PROJECT_NEUTRAL),
        ("contact.current_title", ResearchScope.PROJECT_NEUTRAL),
        ("contact.facet.recent_post", ResearchScope.PROJECT_NEUTRAL),
        ("client.value_prop", ResearchScope.PROJECT_NEUTRAL),
    ],
)
def test_the_ratified_species_table_is_the_default(field_key: str, expected: ResearchScope) -> None:
    assert _default_for(field_key) == expected


def test_the_field_key_alone_decides_the_default() -> None:
    """``field_class`` is accepted for symmetry with ``default_reuse_scope`` but must never change
    the answer — a mismatched pair cannot silently downgrade a ratified relative key."""

    for wrong_class in FieldClass:
        assert (
            default_research_scope(wrong_class, "account.scoring.fit")
            is ResearchScope.PROJECT_RELATIVE
        )
        assert (
            default_research_scope(wrong_class, "contact.persona") is ResearchScope.PROJECT_RELATIVE
        )
        assert (
            default_research_scope(wrong_class, "core.employee_count")
            is ResearchScope.PROJECT_NEUTRAL
        )


def test_a_scoring_field_is_relative_by_prefix_not_by_enumeration() -> None:
    # The family is the unit: a future account.scoring.* score inherits the species.
    assert _default_for("account.scoring.propensity") is ResearchScope.PROJECT_RELATIVE


# --- (b) precedence: declared beats default --------------------------------


def test_a_declaration_overrides_the_default_in_both_directions() -> None:
    neutral_by_default = FieldDef(
        field_key="core.employee_count",
        value_type="int",
        pass_kind=PassKind.SCORING,
        research_scope=ResearchScope.PROJECT_RELATIVE,
    )
    relative_by_default = FieldDef(
        field_key="account.scoring.fit",
        value_type="object",
        pass_kind=PassKind.SCORING,
        research_scope=ResearchScope.PROJECT_NEUTRAL,
    )
    assert resolve_research_scope(neutral_by_default) is ResearchScope.PROJECT_RELATIVE
    assert resolve_research_scope(relative_by_default) is ResearchScope.PROJECT_NEUTRAL


def test_an_undeclared_field_resolves_to_its_default() -> None:
    undeclared = FieldDef(
        field_key="account.value_narrative",
        value_type="object",
        pass_kind=PassKind.DEEP,
    )
    assert undeclared.research_scope is None
    assert resolve_research_scope(undeclared) is ResearchScope.PROJECT_RELATIVE


def test_an_unknown_species_string_cannot_inhabit_a_field_def() -> None:
    with pytest.raises(ValueError):
        FieldDef(
            field_key="core.employee_count",
            value_type="int",
            pass_kind=PassKind.SCORING,
            research_scope="per_campaign",  # type: ignore[arg-type]
        )


# --- (a) the declaration round-trips through the registry ------------------


def test_a_declared_species_round_trips_through_register_and_load() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            declared = FieldDef(
                field_key="account.experiment_species",
                value_type="str",
                pass_kind=PassKind.DEEP,
                research_scope=ResearchScope.PROJECT_RELATIVE,
            )
            await register_field(conn, declared)
            loaded = await get_field(conn, "account.experiment_species")
            assert loaded is not None
            assert loaded.research_scope is ResearchScope.PROJECT_RELATIVE
            assert resolve_research_scope(loaded) is ResearchScope.PROJECT_RELATIVE
            # Idempotent re-registration of the identical definition stays a no-op.
            await register_field(conn, declared)

    run_async(_run())


def test_an_undeclared_field_stores_null_and_resolves_by_default() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await register_field(
                conn,
                FieldDef(
                    field_key="core.experiment_neutral",
                    value_type="str",
                    pass_kind=PassKind.SCORING,
                ),
            )
            stored = (
                await conn.execute(
                    text(
                        "SELECT research_scope FROM field_definition "
                        "WHERE field_key = 'core.experiment_neutral'"
                    )
                )
            ).scalar_one()
            assert stored is None
            loaded = await get_field(conn, "core.experiment_neutral")
            assert loaded is not None
            assert resolve_research_scope(loaded) is ResearchScope.PROJECT_NEUTRAL

    run_async(_run())


def test_changing_a_registered_field_species_is_a_redefinition() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            base = FieldDef(
                field_key="account.experiment_species",
                value_type="str",
                pass_kind=PassKind.DEEP,
                research_scope=ResearchScope.PROJECT_NEUTRAL,
            )
            await register_field(conn, base)
            with pytest.raises(Exception) as exc:
                await register_field(
                    conn, base.model_copy(update={"research_scope": ResearchScope.PROJECT_RELATIVE})
                )
            assert "already registered" in str(exc.value)

    run_async(_run())


# --- (d) a <pack>.* field must declare its species -------------------------
# Registration is the last of three gates; the two authoring gates are tested beside their
# reuse_scope twins — tests/icp/test_packs_framework.py (pack authoring) and
# tests/proposals/test_proposals.py (field-proposal payload validation).


def test_an_undeclared_pack_field_is_refused_before_any_write() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            with pytest.raises(ResearchScopeError):
                await register_field(
                    conn,
                    FieldDef(
                        field_key="acmepack.foo",
                        value_type="str",
                        pass_kind=PassKind.SCORING,
                        reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
                    ),
                    pack="acmepack",
                )
            # The guard runs before any execute, so the transaction is untouched and usable.
            assert await get_field(conn, "acmepack.foo") is None

    run_async(_run())


def test_a_declared_pack_field_registers() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await register_field(
                conn,
                FieldDef(
                    field_key="acmepack.foo",
                    value_type="str",
                    pass_kind=PassKind.SCORING,
                    reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
                    research_scope=ResearchScope.PROJECT_NEUTRAL,
                ),
                pack="acmepack",
            )
            loaded = await get_field(conn, "acmepack.foo")
            assert loaded is not None
            assert loaded.research_scope is ResearchScope.PROJECT_NEUTRAL

    run_async(_run())


def test_a_client_field_is_exempt_from_the_must_declare_rule() -> None:
    # client.* dynamic Client-KB fields are workspace-scoped by construction and default neutral
    # (§5.2); the must-declare rule targets industry packs.
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await register_field(
                conn,
                FieldDef(
                    field_key="client.experiment_hook",
                    value_type="str",
                    pass_kind=PassKind.SCORING,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                ),
                pack="client",
            )
            loaded = await get_field(conn, "client.experiment_hook")
            assert loaded is not None
            assert loaded.research_scope is None
            assert resolve_research_scope(loaded) is ResearchScope.PROJECT_NEUTRAL

    run_async(_run())


# --- (e) the DB value domain -----------------------------------------------


def test_every_species_member_is_accepted_by_the_check_constraint() -> None:
    """The Python vocabulary and the DB CHECK cannot drift apart."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            for index, species in enumerate(ResearchScope):
                await register_field(
                    conn,
                    FieldDef(
                        field_key=f"core.species_probe_{index}",
                        value_type="str",
                        pass_kind=PassKind.SCORING,
                        research_scope=species,
                    ),
                )
            stored = set(
                (
                    await conn.execute(
                        text(
                            "SELECT research_scope FROM field_definition "
                            "WHERE field_key LIKE 'core.species_probe_%'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert stored == {species.value for species in ResearchScope}

    run_async(_run())


def test_the_check_constraint_rejects_a_bogus_species() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            with pytest.raises(IntegrityError, match="field_definition_research_scope"):
                await conn.execute(
                    text(
                        "INSERT INTO field_definition "
                        "(field_key, value_type, pass_kind, field_class, research_scope) "
                        "VALUES ('core.bogus_species', 'str', 'scoring', 'core', 'per_campaign')"
                    )
                )

    run_async(_run())


def test_the_workspace_registry_check_rejects_a_bogus_species() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            constraint = (
                await conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'workspace_field_definition_research_scope'"
                    )
                )
            ).scalar_one()
            assert "project_neutral" in constraint and "project_relative" in constraint

    run_async(_run())


def test_the_workspace_registry_defaults_a_client_field_to_neutral() -> None:
    """``workspace_field_definition`` forces neutral the way it forces tenant_private."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            default = (
                await conn.execute(
                    text(
                        "SELECT column_default FROM information_schema.columns "
                        "WHERE table_name = 'workspace_field_definition' "
                        "AND column_name = 'research_scope'"
                    )
                )
            ).scalar_one()
            assert default is not None and "project_neutral" in default

    run_async(_run())


# --- the shipped declarations match the ratified table ---------------------


@pytest.mark.parametrize(
    "field_key",
    ["account.scoring.fit", "account.scoring.intent", "account.scoring.tier"],
)
def test_the_seeded_scoring_fields_declare_relative(field_key: str) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:  # seeds the core pack
            loaded = await get_field(conn, field_key)
            assert loaded is not None
            assert loaded.research_scope is ResearchScope.PROJECT_RELATIVE

    run_async(_run())


def test_a_seeded_neutral_field_declares_nothing() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            for field_key in ("account.operational_pain", "account.resonance.culture"):
                loaded = await get_field(conn, field_key)
                assert loaded is not None
                assert loaded.research_scope is None
                assert resolve_research_scope(loaded) is ResearchScope.PROJECT_NEUTRAL

    run_async(_run())
