"""DB-backed tests for the M3.3 industry-packs framework (ENG-115).

One test per M3.3 acceptance criterion: registering a pack authors field + source-profile rows; the
read seams return them; the starter packs reproduce staged-flow §7c weight orderings; per-client
overrides resolve over the default and are versioned; two packs compose; ``validate_pack`` names
offenders; a pack can contribute a resonance field-class; and registration is idempotent.
"""

from __future__ import annotations

import pytest

from clue_core import FieldClass, FieldDef, PassKind, ResearchScope, ReuseScope
from clue_research.claimstore import SeedField, get_field, list_fields
from clue_research.icp import (
    DATA_INFRA,
    FRONTIER_AI,
    HEALTHCARE_PRACTICE,
    Pack,
    PackRedefinitionError,
    PackValidationError,
    SourceProfileRedefinitionError,
    SourceWeight,
    UnknownPackError,
    WeightedSource,
    get_pack,
    get_pack_field_set,
    get_pack_source_profile,
    list_packs,
    load_starter_packs,
    register_pack_catalog,
    register_source_profile,
    register_source_profile_override,
    validate_pack,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_icp_db")

_HI = SourceWeight.HIGH
_MED = SourceWeight.MEDIUM
_LO = SourceWeight.LOW


def _keys_weights(sources: tuple[WeightedSource, ...]) -> list[tuple[str, SourceWeight]]:
    return [(s.source_key, s.weight) for s in sources]


def test_register_pack_adds_fields_and_source_profile() -> None:
    """Registering a pack writes its <pack>.* fields into M1.3 and its source profile to the catalog
    — with no pipeline change beyond the registration (substrate §3 payoff 1)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_pack_catalog(conn, HEALTHCARE_PRACTICE)

            rec = await get_pack(conn, "healthcare_practice")
            assert rec is not None
            assert rec.namespace == "healthcare"

            # field-set half landed in the M1.3 registry
            assert await get_field(conn, "healthcare.npi") is not None
            fields = await get_pack_field_set(conn, "healthcare_practice")
            assert [f.field_key for f in fields] == ["healthcare.npi"]

            # source-profile half landed in the catalog (staged-flow §7c priors)
            profile = await get_pack_source_profile(conn, "healthcare_practice")
            assert _keys_weights(profile.default) == [
                ("npi", _HI),
                ("cms", _HI),
                ("google_places", _HI),
                ("job_boards", _HI),
                ("journals", _LO),
            ]

    run_async(_run())


def test_pack_field_is_tier1_deterministic() -> None:
    """healthcare.npi compiles a tier-1 deterministic tier_plan (registry sources)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_pack_catalog(conn, HEALTHCARE_PRACTICE)
            (npi,) = await get_pack_field_set(conn, "healthcare_practice")
            assert npi.field_key == "healthcare.npi"
            assert npi.tier_plan == ("npi", "cms")
            assert npi.pass_kind is PassKind.SCORING

    run_async(_run())


def test_starter_packs_reproduce_staged_flow_weightings() -> None:
    """All three starter packs load as data and reproduce their staged-flow §7c weight orderings."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_starter_packs(conn)

            assert [p.pack_key for p in await list_packs(conn)] == [
                "data_infra",
                "frontier_ai",
                "healthcare_practice",
            ]

            frontier = await get_pack_source_profile(conn, "frontier_ai")
            assert _keys_weights(frontier.default) == [
                ("arxiv", _HI),
                ("semantic_scholar", _HI),
                ("github", _HI),
                ("research_x", _HI),
                ("press_releases", _MED),
                ("glassdoor", _LO),
            ]

            data_infra = await get_pack_source_profile(conn, "data_infra")
            assert _keys_weights(data_infra.default) == [
                ("job_postings", _HI),
                ("builtwith", _HI),
                ("engineering_blogs", _MED),
            ]

            # rank is the explicit 1-based consult order
            assert [s.rank for s in frontier.default] == [1, 2, 3, 4, 5, 6]

    run_async(_run())


def test_per_client_override_beats_default_and_leaves_base_unchanged() -> None:
    """A per-client override resolves as override > pack default; the base profile is untouched and
    other clients still see the base."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_pack_catalog(conn, HEALTHCARE_PRACTICE)
            await register_source_profile_override(
                conn,
                "healthcare_practice",
                "client_x",
                [
                    WeightedSource(source_key="cms", weight=_HI, rank=1),
                    WeightedSource(source_key="npi", weight=_MED, rank=2),
                ],
            )

            over = await get_pack_source_profile(
                conn, "healthcare_practice", workspace_id="client_x"
            )
            assert [s.source_key for s in over.default] == ["cms", "npi"]

            # base unchanged (no client) and a different client sees the base
            base = await get_pack_source_profile(conn, "healthcare_practice")
            assert [s.source_key for s in base.default][:2] == ["npi", "cms"]
            other = await get_pack_source_profile(
                conn, "healthcare_practice", workspace_id="client_y"
            )
            assert [s.source_key for s in other.default] == [s.source_key for s in base.default]

    run_async(_run())


def test_override_is_versioned_latest_wins() -> None:
    """Bumping an override's version is append-only; resolution reads the latest version."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_pack_catalog(conn, DATA_INFRA)
            await register_source_profile_override(
                conn,
                "data_infra",
                "c",
                [WeightedSource(source_key="builtwith", weight=_HI, rank=1)],
            )
            await register_source_profile_override(
                conn,
                "data_infra",
                "c",
                [WeightedSource(source_key="job_postings", weight=_HI, rank=1)],
                version=2,
            )
            resolved = await get_pack_source_profile(conn, "data_infra", workspace_id="c")
            assert [s.source_key for s in resolved.default] == ["job_postings"]

    run_async(_run())


def test_per_field_class_slot_and_fallback() -> None:
    """A field-class-specific source slot is served for that class; other classes fall back to the
    pack-wide default."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_pack_catalog(conn, DATA_INFRA)
            await register_source_profile(
                conn,
                "data_infra",
                [WeightedSource(source_key="glassdoor", weight=_HI, rank=1)],
                field_class=FieldClass.ACCOUNT_RESONANCE,
            )
            profile = await get_pack_source_profile(conn, "data_infra")
            assert [
                s.source_key for s in profile.for_field_class(FieldClass.ACCOUNT_RESONANCE)
            ] == ["glassdoor"]
            # a class with no specific slot falls back to the pack-wide default
            assert [s.source_key for s in profile.for_field_class(FieldClass.CORE)] == [
                "job_postings",
                "builtwith",
                "engineering_blogs",
            ]

    run_async(_run())


def test_two_packs_compose_with_disjoint_field_sets() -> None:
    """Enabling two packs composes (dedups) field sets; each pack's <pack>.* set is its own."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_pack_catalog(conn, FRONTIER_AI)
            await register_pack_catalog(conn, DATA_INFRA)

            assert [f.field_key for f in await get_pack_field_set(conn, "frontier_ai")] == [
                "frontier_ai.arxiv_activity"
            ]
            assert [f.field_key for f in await get_pack_field_set(conn, "data_infra")] == [
                "data_infra.migration_signal"
            ]
            # both source profiles are independently retrievable
            assert (await get_pack_source_profile(conn, "frontier_ai")).default
            assert (await get_pack_source_profile(conn, "data_infra")).default

    run_async(_run())


def test_pack_contributes_resonance_field_class_by_registration() -> None:
    """A pack can contribute an account.resonance.* field-class via registration (Doc C §2) — it
    becomes a shared canonical row, not a <pack>.* field."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_pack_catalog(conn, FRONTIER_AI)

            res = await get_field(conn, "account.resonance.research_prestige")
            assert res is not None
            assert res.field_class is FieldClass.ACCOUNT_RESONANCE

            # it is NOT a <pack>.* field, so get_pack_field_set omits it ...
            assert "account.resonance.research_prestige" not in {
                f.field_key for f in await get_pack_field_set(conn, "frontier_ai")
            }
            # ... but it is reachable via the shared field-class listing
            resonance = await list_fields(conn, field_class=FieldClass.ACCOUNT_RESONANCE)
            assert "account.resonance.research_prestige" in {f.field_key for f in resonance}

    run_async(_run())


def test_registration_is_idempotent_but_redefinition_is_rejected() -> None:
    """Re-registering an identical pack is a no-op; a conflicting redefinition is rejected."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_pack_catalog(conn, HEALTHCARE_PRACTICE)
            await register_pack_catalog(conn, HEALTHCARE_PRACTICE)  # idempotent no-op

            conflict = Pack(
                pack_key="healthcare_practice",
                namespace="healthcare",
                title="A DIFFERENT TITLE",
            )
            with pytest.raises(PackRedefinitionError):
                await register_pack_catalog(conn, conflict)

    run_async(_run())


def test_source_profile_redefinition_rejected() -> None:
    """Re-registering a source slot/version with different content is rejected (append-only)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_pack_catalog(conn, DATA_INFRA)
            # identical re-register of the existing pack-wide v1 slot is a no-op
            await register_source_profile(
                conn,
                "data_infra",
                [
                    WeightedSource(source_key="job_postings", weight=_HI, rank=1),
                    WeightedSource(source_key="builtwith", weight=_HI, rank=2),
                    WeightedSource(source_key="engineering_blogs", weight=_MED, rank=3),
                ],
            )
            with pytest.raises(SourceProfileRedefinitionError):
                await register_source_profile(
                    conn,
                    "data_infra",
                    [WeightedSource(source_key="builtwith", weight=_HI, rank=1)],
                )

    run_async(_run())


def test_validate_pack_names_unregistered_field() -> None:
    """validate_pack fails (naming the offender) when a declared field_key is not registered."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ghost = Pack(
                pack_key="ghostpack",
                namespace="ghostpack",
                title="Ghost",
                field_set=(
                    SeedField(
                        field_def=FieldDef(
                            field_key="ghostpack.nope",
                            value_type="str",
                            pass_kind=PassKind.SCORING,
                            # declared so it clears the W5 reuse_scope authoring guard and the test
                            # reaches the *unregistered-field* check it is asserting.
                            reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
                        ),
                        pack="ghostpack",
                    ),
                ),
            )
            with pytest.raises(PackValidationError) as exc:
                await validate_pack(conn, ghost)
            assert "ghostpack.nope" in str(exc.value)

    run_async(_run())


def test_validate_pack_names_unknown_source_key() -> None:
    """validate_pack fails (naming the offender) when a referenced source_key is not in the supplied
    source-manifest namespace (the M4 join, late-bound)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_pack_catalog(conn, HEALTHCARE_PRACTICE)
            with pytest.raises(PackValidationError) as exc:
                await validate_pack(conn, HEALTHCARE_PRACTICE, known_source_keys={"npi"})
            # cms / google_places / job_boards / journals are not in {"npi"}
            assert "cms" in str(exc.value)
            # with the full set, it passes
            await validate_pack(
                conn,
                HEALTHCARE_PRACTICE,
                known_source_keys={"npi", "cms", "google_places", "job_boards", "journals"},
            )

    run_async(_run())


def test_pack_field_must_declare_research_scope() -> None:
    """FI-2 P3: a <pack>.* field with no declared species is rejected at authoring too, so
    ``validate_pack`` never returns clean for a pack ``register_field`` would refuse."""

    def _pack(research_scope: ResearchScope | None) -> Pack:
        return Pack(
            pack_key="speciespack",
            namespace="speciespack",
            title="Species pack",
            field_set=(
                SeedField(
                    field_def=FieldDef(
                        field_key="speciespack.metric",
                        value_type="int",
                        pass_kind=PassKind.SCORING,
                        reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
                        research_scope=research_scope,
                    ),
                    pack="speciespack",
                ),
            ),
        )

    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(PackValidationError, match="research_scope"):
                await validate_pack(conn, _pack(None))
            with pytest.raises(PackValidationError, match="research_scope"):
                await register_pack_catalog(conn, _pack(None))
            # declaring a species lets it through
            await register_pack_catalog(conn, _pack(ResearchScope.PROJECT_NEUTRAL))
            stored = await get_field(conn, "speciespack.metric")
            assert stored is not None
            assert stored.research_scope is ResearchScope.PROJECT_NEUTRAL

    run_async(_run())


def test_pack_field_must_declare_reuse_scope() -> None:
    """ENG-165 W5: a <pack>.* field with no declared reuse_scope is rejected at authoring (no safe
    default for a pack namespace); declaring it lets the pack register."""

    def _pack(reuse_scope: ReuseScope | None) -> Pack:
        return Pack(
            pack_key="scopepack",
            namespace="scopepack",
            title="Scope pack",
            field_set=(
                SeedField(
                    field_def=FieldDef(
                        field_key="scopepack.metric",
                        value_type="int",
                        pass_kind=PassKind.SCORING,
                        reuse_scope=reuse_scope,
                        # Species is orthogonal (FI-2 P3) and equally must-declare for a pack
                        # field; declared here so this test exercises the reuse_scope guard alone.
                        research_scope=ResearchScope.PROJECT_NEUTRAL,
                    ),
                    pack="scopepack",
                ),
            ),
        )

    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(PackValidationError, match="reuse_scope"):
                await validate_pack(conn, _pack(None))
            with pytest.raises(PackValidationError, match="reuse_scope"):
                await register_pack_catalog(conn, _pack(None))
            # declaring a scope lets it through
            await register_pack_catalog(conn, _pack(ReuseScope.PUBLIC_FOOTPRINT))
            stored = await get_field(conn, "scopepack.metric")
            assert stored is not None and stored.reuse_scope is ReuseScope.PUBLIC_FOOTPRINT

    run_async(_run())


def test_unknown_pack_raises() -> None:
    """Reading a pack that was never cataloged raises UnknownPackError."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(UnknownPackError):
                await get_pack_field_set(conn, "does_not_exist")

    run_async(_run())
