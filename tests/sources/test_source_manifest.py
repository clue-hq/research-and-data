"""M4.2 acceptance: the Source Registry + capability manifests (ENG-111).

One test per acceptance criterion: the migration's enums match core; seeds load idempotently with
the right tier/modality/binding; ``register_source`` validates ``yields`` against the M1.3 registry;
``sources_for`` answers capability queries; ``get_resolver`` raises for a resolver-absent source;
``active=false`` hides without deleting; no secret lands in the table; nothing branches on
``provider``; and ``registered_source_keys`` completes M3.3's late-bound ``validate_pack`` join.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_config import redact
from clue_core import EntityScope, IdentityBinding, Modality, SourceManifest
from clue_research.icp import (
    Pack,
    PackSourceSlot,
    PackValidationError,
    SourceWeight,
    WeightedSource,
    validate_pack,
)
from clue_research.sources import (
    NoResolverBoundError,
    RegistrySourceManifest,
    SourceManifestRedefinitionError,
    SourceYieldError,
    bind_resolver,
    get_resolver,
    get_source,
    list_sources,
    register_source,
    registered_source_keys,
    seed_source_manifests,
    sources_for,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

# RegistrySourceManifest-level fields (everything else is a core SourceManifest field).
_WRAPPER_FIELDS = frozenset(
    {"active", "version", "provider", "auth_ref", "requires_adapter", "rate_limit"}
)


def _manifest(source_key: str, **overrides: object) -> RegistrySourceManifest:
    """A minimal valid registry manifest; kwargs route to the wrapper or the core manifest."""
    wrapper = {k: overrides.pop(k) for k in list(overrides) if k in _WRAPPER_FIELDS}
    base: dict[str, object] = {
        "source_key": source_key,
        "modality": Modality.STRUCTURED,
        "entity_scope": EntityScope.ACCOUNT,
        "yields": ("account",),
        "tier": 1,
    }
    base.update(overrides)
    return RegistrySourceManifest(manifest=SourceManifest(**base), **wrapper)  # type: ignore[arg-type]


# --- enum parity (the migration's pg enums mirror core) ---------------------


def test_db_enums_match_core() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=False) as conn:
            for typ, enum in (("modality", Modality), ("entity_scope", EntityScope)):
                labels = (
                    (
                        await conn.execute(
                            text(
                                "SELECT e.enumlabel FROM pg_enum e "
                                "JOIN pg_type t ON t.oid = e.enumtypid "
                                "WHERE t.typname = :t ORDER BY e.enumsortorder"
                            ),
                            {"t": typ},
                        )
                    )
                    .scalars()
                    .all()
                )
                assert list(labels) == [m.value for m in enum], typ

    run_async(_run())


# --- seeds + capability shape ----------------------------------------------


def test_seed_manifests_load_idempotently() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            first = await registered_source_keys(conn)
            await seed_source_manifests(conn)  # second load is a no-op
            assert await registered_source_keys(conn) == first
            assert {
                "clay",
                "apollo",
                "builtwith",
                "crm",
                "firecrawl_site",
                "exa_deep",
                "sumble_organizations",
                "sumble_jobs",
                "sumble_tech_stack",
            } <= first

    run_async(_run())


def test_crm_is_tier1_strong_binding() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            crm = await get_source(conn, "crm")
            assert crm is not None
            assert crm.tier == 1
            assert crm.modality is Modality.STRUCTURED
            assert crm.identity_binding_strength is IdentityBinding.STRONG

    run_async(_run())


def test_firecrawl_is_tier2_text_with_adapter() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            fc = await get_source(conn, "firecrawl_site")
            assert fc is not None
            assert fc.tier == 2
            assert fc.modality in {Modality.TEXT, Modality.PDF}
            assert fc.requires_adapter == "firecrawl_html"

    run_async(_run())


def test_structured_providers_are_tier1_structured() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            for key in (
                "clay",
                "apollo",
                "zoominfo",
                "builtwith",
                "npi",
                "duns",
                "cik",
                "lei",
                "sumble_organizations",
                "sumble_jobs",
                "sumble_tech_stack",
            ):
                src = await get_source(conn, key)
                assert src is not None, key
                assert src.tier == 1, key
                assert src.modality is Modality.STRUCTURED, key

    run_async(_run())


def test_permitted_account_source_yields_are_pinned_to_the_31_ownership_table() -> None:
    """The four permitted account field-sources declare exactly the §3.1 rows they own.

    ``yields`` is what the M4.6 planner reads to answer "which source can populate this field", so
    these four tuples decide whether the fixed 21-field account profile is plannable at all — and,
    just as load-bearing, which provider is *not* offered a field it does not own. ``exa_deep``
    deliberately no longer yields the whole ``account`` class: that claimed
    ``account.hiring_velocity_eng``, which §3.1 grants Sumble Jobs alone. The two remaining class
    tokens are whole-class ownership (§3.1's six ``account.resonance.*``, §7.1's nine
    ``contact.facet.*``). Any change here is a contract change, not a tidy-up.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            actual = {}
            for key in ("sumble_organizations", "sumble_jobs", "sumble_tech_stack", "exa_deep"):
                source = await get_source(conn, key)
                assert source is not None, key
                actual[key] = source.yields
            assert actual == {
                "sumble_organizations": (
                    "core.employee_count",
                    "core.primary_domain",
                    "core.industry",
                    "core.hq_location",
                    "core.company_about",
                    "core.company_linkedin_url",
                    "account.total_funding",
                    "account.recent_funding",
                ),
                "sumble_jobs": ("account.hiring_velocity_eng",),
                "sumble_tech_stack": ("core.primary_tech_stack",),
                "exa_deep": (
                    "core.company_about",
                    "core.industry",
                    "core.annual_revenue",
                    "account.total_funding",
                    "account.recent_funding",
                    "account.operational_pain",
                    "account.strategic_moves",
                    "account.resonance",
                    "contact.facet",
                ),
            }

    run_async(_run())


# --- sources_for capability query ------------------------------------------


def test_sources_for_techstack_returns_structured_sources_not_firecrawl() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            keys = await sources_for(conn, "core.primary_tech_stack", tier=1)
            assert keys == ["builtwith", "sumble_tech_stack"]
            assert "firecrawl_site" not in await sources_for(conn, "core.primary_tech_stack")

    run_async(_run())


def test_sources_for_contact_returns_people_sources() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            keys = await sources_for(conn, "contact.*", entity_scope="contact")
            assert set(keys) == {
                "apollo",
                "zoominfo",
                "crm",
                # Slice 10 widens Sumble People from account-only committee enumeration to the
                # exact-person Contact email capability as well. The no-reveal committee request
                # remains a separate transport contract.
                "sumble_people",
                # Governed internal classification of an already-admitted contact. This is
                # registered for exact pre-spend identity but remains unbound as a waterfall
                # resolver unless an explicit source profile selects it.
                "llm_role_inference",
            }  # contact-yielding, scope contact/both
            assert "builtwith" not in keys  # account-only, no contact yields

    run_async(_run())


def test_sources_for_class_yield_covers_specific_key() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            keys = await sources_for(conn, "account.recent_funding", tier=1)
            assert "apollo" in keys  # exact key yield
            assert "duns" in keys  # yields the "account" class, which covers a concrete account key
            assert "builtwith" not in keys  # yields only core.primary_tech_stack

    run_async(_run())


# --- yields validation against the field registry ---------------------------


def test_register_rejects_unregistered_yield_naming_offender() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            bad = _manifest("ghost", yields=("core.employee_count", "core.does_not_exist"))
            with pytest.raises(SourceYieldError, match="does_not_exist"):
                await register_source(conn, bad)

    run_async(_run())


def test_register_accepts_resolving_yields() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ok = _manifest("good", yields=("core.employee_count", "contact", "account.resonance"))
            await register_source(conn, ok)
            assert await get_source(conn, "good") is not None

    run_async(_run())


# --- resolver binding -------------------------------------------------------


def test_get_resolver_raises_for_registered_but_unbound_source() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            # exa_deep is a registered tier-4 placeholder; its resolver lands in M11.
            assert await get_source(conn, "exa_deep") is not None

    run_async(_run())
    with pytest.raises(NoResolverBoundError, match="no resolver bound"):
        get_resolver("exa_deep")


def test_get_resolver_returns_bound_resolver() -> None:
    class _FakeResolver:
        tier = 1

        def resolve(self, entity: object, field: object) -> list[object]:
            return []

    resolver = _FakeResolver()
    bind_resolver("clay", resolver)
    assert get_resolver("clay") is resolver


# --- active flag ------------------------------------------------------------


def test_inactive_source_hidden_from_listings_but_not_deleted() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_source(conn, _manifest("dormant", active=True))
            # flip to inactive via a version bump (PK row update — auditability, not a delete)
            await register_source(conn, _manifest("dormant", active=False, version=2))
            assert "dormant" not in [s.source_key for s in await list_sources(conn)]
            assert "dormant" not in await sources_for(conn, "account")
            # row still exists and is reachable with active=None
            assert await get_source(conn, "dormant") is not None
            assert "dormant" in [s.source_key for s in await list_sources(conn, active=None)]

    run_async(_run())


# --- idempotency / versioning ----------------------------------------------


def test_redefinition_same_version_raises_but_version_bump_updates() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_source(conn, _manifest("acme", tier=1))
            # same version, different content -> rejected
            with pytest.raises(SourceManifestRedefinitionError, match="bump the version"):
                await register_source(conn, _manifest("acme", tier=2))
            # higher version -> versioned update
            await register_source(conn, _manifest("acme", tier=2, version=2))
            updated = await get_source(conn, "acme")
            assert updated is not None and updated.tier == 2 and updated.version == 2

    run_async(_run())


# --- no secret in the table -------------------------------------------------


def test_no_secret_value_in_table() -> None:
    # Scan EVERY text/jsonb column that could carry a stray value (not just auth_ref): a credential
    # must never be persisted. auth_ref holds an env-var *reference* (e.g. CLUE_CLAY_API_KEY), which
    # is not credential-shaped. (Backstop on top of the positive CLUE_* shape check on the seeds.)
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT source_key, provider, auth_ref, freshness_profile, "
                            "requires_adapter, rate_limit::text AS rate_limit FROM source_manifest"
                        )
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                for col, value in row.items():
                    if value is not None:
                        assert redact(value) != "***REDACTED***", f"{row['source_key']}.{col} leaks"

    run_async(_run())


# --- the late-bound validate_pack(known_source_keys=...) join (M3.3 ⨝ M4) ---


def test_registered_source_keys_completes_validate_pack_join() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            known = await registered_source_keys(conn)
            assert {"npi", "clay"} <= known

            ok_pack = Pack(
                pack_key="t_ok",
                namespace="testpack",
                title="T",
                source_profile=(
                    PackSourceSlot(
                        sources=(
                            WeightedSource(source_key="npi", weight=SourceWeight.HIGH, rank=1),
                        )
                    ),
                ),
            )
            await validate_pack(conn, ok_pack, known_source_keys=known)  # references only npi → ok

            bad_pack = Pack(
                pack_key="t_bad",
                namespace="testpack",
                title="T",
                source_profile=(
                    PackSourceSlot(
                        sources=(
                            WeightedSource(
                                source_key="ghost_source", weight=SourceWeight.HIGH, rank=1
                            ),
                        )
                    ),
                ),
            )
            with pytest.raises(PackValidationError, match="ghost_source"):
                await validate_pack(conn, bad_pack, known_source_keys=known)

    run_async(_run())
