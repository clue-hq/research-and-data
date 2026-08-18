"""DB-backed tests for the M3.2 research-schema compiler (ENG-109).

One test per acceptance criterion: deterministic compile; scoring/deep partition matching the
registry pass tag (substrate §3 worked example); two-tier signal-class linking (Doc C §1); tier_plan
+ gate carried verbatim; enabling/disabling a pack injects/removes fields (vertical pluggability);
a missing field-key / unknown pack fails with a diagnostic and no partial plan; a per-ICP override
wins over the registry default. Plus dedup of icp∪pack overlap and compile_active_icp.
"""

from __future__ import annotations

import pytest

from clue_core import FieldDef, ICPCreatedFrom, ICPSpec, PassKind
from clue_research.claimstore import register_field
from clue_research.icp import (
    HEALTHCARE_PRACTICE,
    CompileError,
    FieldOverride,
    compile_active_icp,
    compile_field_plan,
    create_icp_spec,
    get_icp_version,
    register_pack_catalog,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_icp_db")


def _spec(**overrides: object) -> ICPSpec:
    """Build an in-memory ICPSpec (the compiler reads it; it need not be persisted)."""
    base: dict[str, object] = {
        "workspace_id": "acme",
        "icp_key": "default",
        "created_from": ICPCreatedFrom.SYNTHESIS,
    }
    base.update(overrides)
    return ICPSpec(**base)


def test_partitions_scoring_and_deep_matching_registry_pass() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            plan = await compile_field_plan(
                conn,
                _spec(
                    field_keys=(
                        "core.employee_count",
                        "core.primary_tech_stack",
                        "account.recent_funding",
                        "account.hiring_velocity_eng",
                        "account.operational_pain",
                        "account.strategic_moves",
                    )
                ),
            )
            assert {e.field.field_key for e in plan.scoring_fields} == {
                "core.employee_count",
                "core.primary_tech_stack",
                "account.recent_funding",
            }
            assert {e.field.field_key for e in plan.deep_fields} == {
                "account.hiring_velocity_eng",
                "account.operational_pain",
                "account.strategic_moves",
            }
            # every field lands in exactly one of the two passes
            assert len(plan.scoring_fields) + len(plan.deep_fields) == len(plan.fields)

    run_async(_run())


def test_field_plan_partitions_by_reuse_scope() -> None:
    """ENG-165 W3: the compiled plan partitions fields by resolved reuse scope — public-footprint
    facts (core.*/account.* defaults) vs tenant-private (the reserved account.scoring.* keys; the
    class-default resonance field). Every field lands in exactly one partition."""

    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            plan = await compile_field_plan(
                conn,
                _spec(
                    field_keys=(
                        "core.employee_count",  # default public
                        "account.recent_funding",  # default public
                        "account.scoring.fit",  # declared tenant_private (W4)
                        "account.resonance.culture",  # class default tenant_private
                    )
                ),
            )
            public = {e.field.field_key for e in plan.public_fields}
            private = {e.field.field_key for e in plan.tenant_private_fields}
            assert public == {"core.employee_count", "account.recent_funding"}
            assert private == {"account.scoring.fit", "account.resonance.culture"}
            # the two partitions are a clean cover of the plan
            assert len(plan.public_fields) + len(plan.tenant_private_fields) == len(plan.fields)
            assert public.isdisjoint(private)

    run_async(_run())


def test_compile_is_deterministic() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            spec = _spec(field_keys=("core.employee_count", "account.operational_pain"))
            first = await compile_field_plan(conn, spec)
            second = await compile_field_plan(conn, spec)
            assert first == second
            assert first.plan_hash == second.plan_hash

    run_async(_run())


def test_two_tier_signal_class_links_proxy_and_narrative() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            # intent signal class: a cheap scoring proxy + a deep narrative (Doc C §1)
            await register_field(
                conn,
                FieldDef(
                    field_key="account.job_openings_delta",
                    value_type="number",
                    tier_plan=("linkedin_jobs",),
                    pass_kind=PassKind.SCORING,
                    signal_class="intent",
                ),
            )
            await register_field(
                conn,
                FieldDef(
                    field_key="account.why_in_market",
                    value_type="str",
                    tier_plan=("exa", "parallel"),
                    pass_kind=PassKind.DEEP,
                    gate="deep-pass",
                    signal_class="intent",
                ),
            )
            plan = await compile_field_plan(
                conn, _spec(field_keys=("account.job_openings_delta", "account.why_in_market"))
            )
            assert len(plan.signal_classes) == 1
            link = plan.signal_classes[0]
            assert link.signal_class == "intent"
            assert link.scoring == ("account.job_openings_delta",)
            assert link.deep == ("account.why_in_market",)

    run_async(_run())


def test_tier_plan_and_gate_carried_verbatim() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            plan = await compile_field_plan(
                conn, _spec(field_keys=("account.hiring_velocity_eng",))
            )
            (entry,) = plan.fields
            # Sumble Jobs is the current deterministic first source; retain the historical
            # LinkedIn/Exa fallbacks verbatim behind it.
            assert entry.field.tier_plan == ("sumble_jobs", "linkedin_jobs", "exa_deep")
            assert entry.field.gate == "tier>=3"
            assert entry.field.pass_kind is PassKind.DEEP

    run_async(_run())


def test_enabling_pack_injects_fields_disabling_removes() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            await register_pack_catalog(conn, HEALTHCARE_PRACTICE)
            with_pack = await compile_field_plan(
                conn,
                _spec(
                    icp_key="health",
                    field_keys=("core.employee_count",),
                    enabled_packs=("healthcare_practice",),
                ),
            )
            keys = {e.field.field_key for e in with_pack.fields}
            assert "healthcare.npi" in keys
            npi = next(e for e in with_pack.fields if e.field.field_key == "healthcare.npi")
            assert npi.field.tier_plan == ("npi", "cms")  # tier-1 deterministic registries

            without = await compile_field_plan(
                conn, _spec(icp_key="plain", field_keys=("core.employee_count",))
            )
            assert "healthcare.npi" not in {e.field.field_key for e in without.fields}

    run_async(_run())


def test_missing_field_key_fails_with_diagnostic_no_partial_plan() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            with pytest.raises(CompileError) as exc:
                await compile_field_plan(
                    conn, _spec(field_keys=("core.employee_count", "account.ghost_field"))
                )
            assert "account.ghost_field" in str(exc.value)
            assert any("ghost_field" in d for d in exc.value.diagnostics)

    run_async(_run())


def test_unknown_pack_fails_with_diagnostic() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            with pytest.raises(CompileError) as exc:
                await compile_field_plan(
                    conn,
                    _spec(field_keys=("core.employee_count",), enabled_packs=("ghost_pack",)),
                )
            assert "ghost_pack" in str(exc.value)

    run_async(_run())


def test_per_icp_tier_plan_override_wins_over_registry_default() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            spec = _spec(field_keys=("account.recent_funding",))
            overridden = await compile_field_plan(
                conn,
                spec,
                overrides={"account.recent_funding": FieldOverride(tier_plan=("custom_resolver",))},
            )
            assert overridden.fields[0].field.tier_plan == ("custom_resolver",)
            # without the override, the registry default stands. ``exa_deep`` joined it when
            # contract §3.1's Exa-Deep-owned rows were made dispatchable (the composed Exa account
            # action refuses a field whose tier plan omits its source key).
            default = await compile_field_plan(conn, spec)
            assert default.fields[0].field.tier_plan == ("apollo", "exa", "exa_deep")

    run_async(_run())


def test_override_targeting_non_active_field_fails() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            with pytest.raises(CompileError) as exc:
                await compile_field_plan(
                    conn,
                    _spec(field_keys=("core.employee_count",)),
                    overrides={"core.work_email": FieldOverride(tier_plan=("x",))},
                )
            assert "core.work_email" in str(exc.value)

    run_async(_run())


def test_icp_and_pack_field_overlap_is_deduped() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            await register_pack_catalog(conn, HEALTHCARE_PRACTICE)
            plan = await compile_field_plan(
                conn,
                _spec(
                    icp_key="health",
                    field_keys=("healthcare.npi",),
                    enabled_packs=("healthcare_practice",),
                ),
            )
            npi_entries = [e for e in plan.fields if e.field.field_key == "healthcare.npi"]
            assert len(npi_entries) == 1  # appears once despite two contributors
            assert set(npi_entries[0].contributed_by) == {"icp", "pack:healthcare_practice"}

    run_async(_run())


def test_compile_active_icp_reads_the_active_spec() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            await create_icp_spec(
                conn,
                workspace_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.employee_count",),
                activate=True,
            )
            plan = await compile_active_icp(conn, "acme", "default")
            assert plan.icp_version == 1
            assert {e.field.field_key for e in plan.fields} == {"core.employee_count"}

    run_async(_run())


def test_pinned_version_recompiles_identically_after_refetch() -> None:
    """Criterion 1, clause 2: re-fetching the pinned ICP-spec version (the DB serialize→deserialize
    round-trip) and recompiling yields an identical plan — the reproducibility project-run re-entry
    (M6/M8 'execute exactly what was compiled') depends on."""

    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            await create_icp_spec(
                conn,
                workspace_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=(
                    "core.employee_count",
                    "account.recent_funding",
                    "account.operational_pain",
                ),
                activate=True,
            )
            first_spec = await get_icp_version(conn, "acme", "default", 1)
            assert first_spec is not None
            first_plan = await compile_field_plan(conn, first_spec)
            # re-fetch the same pinned version from the DB and recompile
            second_spec = await get_icp_version(conn, "acme", "default", 1)
            assert second_spec is not None
            second_plan = await compile_field_plan(conn, second_spec)
            assert first_plan == second_plan
            assert first_plan.plan_hash == second_plan.plan_hash

    run_async(_run())
