"""M2.5 (ENG-124) — the reuse classifier + amortization/degradation/DSAR (identity layer).

The write-side seam: classify ``(field_key, method, tier) → reuse_scope`` from versioned policy,
stamp the claim, and (read-side) amortize public claims, degrade safely, and select the DSAR set.
"""

from __future__ import annotations

import pytest

from clue_research.claimstore import TenantScope, current_value, insert_claim
from clue_research.core import (
    ExtractionMethod,
    FreshnessState,
    ReuseScope,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.identity import (
    ReusePolicy,
    classify_reuse_scope,
    dsar_private_claims,
    reusable_public_value,
    stamp_reuse,
)

from .conftest import rollback_conn, run_async


def _claim(entity: object, field: str, value: object, method: ExtractionMethod) -> object:
    return account_claim(
        entity_id=entity,  # type: ignore[arg-type]
        field_key=field,
        value_json=value,  # type: ignore[arg-type]
        source_tier=1,
        extraction_method=method,
        source_url="https://api.example.com" if method is ExtractionMethod.API else None,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode="account_profiling",  # type: ignore[arg-type]
    )


# --- classifier (pure) ------------------------------------------------------
@pytest.mark.parametrize(
    ("field", "method", "expected"),
    [
        ("core.employee_count", ExtractionMethod.API, ReuseScope.PUBLIC_FOOTPRINT),
        ("account.recent_funding", ExtractionMethod.API, ReuseScope.PUBLIC_FOOTPRINT),
        ("account.primary_tech_stack", ExtractionMethod.SCRAPE, ReuseScope.PUBLIC_FOOTPRINT),
        # CRM-imported facts are inherently client-private (substrate §2 / §4).
        ("core.employee_count", ExtractionMethod.CRM_IMPORT, ReuseScope.TENANT_PRIVATE),
        # personal / facet and resonance are tenant-private.
        ("contact.facet.recent_post", ExtractionMethod.API, ReuseScope.TENANT_PRIVATE),
        ("account.resonance.culture", ExtractionMethod.LLM_SYNTHESIS, ReuseScope.TENANT_PRIVATE),
    ],
)
def test_classifier_maps_substrate_examples(
    field: str, method: ExtractionMethod, expected: ReuseScope
) -> None:
    assert classify_reuse_scope(field, method, 1) is expected


def test_disabling_reuse_makes_everything_private() -> None:
    """ReusePolicy(enabled=False) is the safe-degradation switch — even a public field classifies
    tenant-private."""
    off = ReusePolicy(enabled=False)
    assert (
        classify_reuse_scope("core.employee_count", ExtractionMethod.API, 1, off)
        is ReuseScope.TENANT_PRIVATE
    )


def test_stamp_reuse_sets_scope_and_tenant() -> None:
    """stamp_reuse classifies + binds the tenant for private claims, and drops it for public."""
    entity = new_entity_id()
    public = stamp_reuse(
        _claim(entity, "core.employee_count", 1, ExtractionMethod.API),  # type: ignore[arg-type]
        tenant_id="tenant-a",
    )
    assert public.reuse_scope is ReuseScope.PUBLIC_FOOTPRINT and public.tenant_id is None
    private = stamp_reuse(
        _claim(entity, "core.employee_count", 1, ExtractionMethod.CRM_IMPORT),  # type: ignore[arg-type]
        tenant_id="tenant-a",
    )
    assert private.reuse_scope is ReuseScope.TENANT_PRIVATE and private.tenant_id == "tenant-a"


# --- amortization / degradation / DSAR (DB) ---------------------------------
pytestmark = pytest.mark.usefixtures("require_identity_db")


def test_amortization_reuses_a_fresh_public_claim() -> None:
    """A fresh public-footprint claim is reusable (the resolver skips the re-spend)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            claim = stamp_reuse(
                _claim(entity, "core.employee_count", 250, ExtractionMethod.API),  # type: ignore[arg-type]
                tenant_id="tenant-a",
            )
            await insert_claim(conn, claim, validate_field=False)
            reused = await reusable_public_value(conn, entity, "core.employee_count")
            assert reused is not None
            assert reused.value_json == 250
            assert reused.freshness_state is FreshnessState.FRESH  # → resolver reuses, no new spend

    run_async(_run())


def test_safe_degradation_isolates_a_normally_public_claim() -> None:
    """With reuse disabled, a normally-public claim becomes tenant-private and B cannot see A's."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            claim = stamp_reuse(
                _claim(entity, "core.employee_count", 250, ExtractionMethod.API),  # type: ignore[arg-type]
                tenant_id="tenant-a",
                policy=ReusePolicy(enabled=False),
            )
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            await insert_claim(conn, claim, validate_field=False)
            b = TenantScope.for_tenant("tenant-b")
            assert await current_value(conn, entity, "core.employee_count", scope=b) is None
            a = TenantScope.for_tenant("tenant-a")
            assert await current_value(conn, entity, "core.employee_count", scope=a) is not None

    run_async(_run())


def test_dsar_selects_only_tenant_private_claims() -> None:
    """The DSAR selector returns exactly the entity's tenant-private claims (the data subject's
    set), leaving public company facts out of the erasure set."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            public = stamp_reuse(
                _claim(entity, "core.employee_count", 250, ExtractionMethod.API),  # type: ignore[arg-type]
                tenant_id="tenant-a",
            )
            private = stamp_reuse(
                _claim(entity, "account.crm_note", {"note": "x"}, ExtractionMethod.CRM_IMPORT),  # type: ignore[arg-type]
                tenant_id="tenant-a",
            )
            await insert_claim(conn, public, validate_field=False)
            await insert_claim(conn, private, validate_field=False)
            dsar = list(await dsar_private_claims(conn, entity))
            assert len(dsar) == 1
            assert dsar[0].reuse_scope is ReuseScope.TENANT_PRIVATE
            assert dsar[0].field_key == "account.crm_note"

    run_async(_run())
