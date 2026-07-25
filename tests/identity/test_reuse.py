"""M2.5 (ENG-124) — the reuse classifier + amortization/degradation/DSAR (identity layer).

The write-side seam: classify ``(field_key, method, tier) → reuse_scope`` from versioned policy,
stamp the claim, and (read-side) amortize public claims, degrade safely, and select the DSAR set.
"""

from __future__ import annotations

import pytest

from clue_core import (
    ExtractionMethod,
    ReuseScope,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.claimstore import WorkspaceScope, current_value, insert_claim
from clue_research.identity import (
    ReusePolicy,
    classify_reuse_scope,
    dsar_private_claims,
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
        # per-client/ICP scoring outputs are tenant-private (M2.5 acceptance criterion).
        ("account.scoring.fit", ExtractionMethod.API, ReuseScope.TENANT_PRIVATE),
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


def test_classify_consults_declared_scope_before_prefix() -> None:
    """ENG-165 W1/W2: the field's declared scope is authoritative over the namespace-prefix
    heuristic (both directions), but a tenant-private *method* still escalates (source-based)."""
    # declared private wins even for a core.* field the prefix heuristic would call public
    assert (
        classify_reuse_scope(
            "core.employee_count",
            ExtractionMethod.API,
            1,
            declared_scope=ReuseScope.TENANT_PRIVATE,
        )
        is ReuseScope.TENANT_PRIVATE
    )
    # declared public overrides the account.scoring. prefix (which would otherwise mark it private)
    assert (
        classify_reuse_scope(
            "account.scoring.fit",
            ExtractionMethod.API,
            1,
            declared_scope=ReuseScope.PUBLIC_FOOTPRINT,
        )
        is ReuseScope.PUBLIC_FOOTPRINT
    )
    # ...but a crm_import (client data) still escalates a declared-public field to private
    assert (
        classify_reuse_scope(
            "account.scoring.fit",
            ExtractionMethod.CRM_IMPORT,
            1,
            declared_scope=ReuseScope.PUBLIC_FOOTPRINT,
        )
        is ReuseScope.TENANT_PRIVATE
    )


def test_stamp_reuse_sets_scope_and_tenant() -> None:
    """stamp_reuse classifies + binds the tenant for private claims, and drops it for public."""
    entity = new_entity_id()
    public = stamp_reuse(
        _claim(entity, "core.employee_count", 1, ExtractionMethod.API),  # type: ignore[arg-type]
        workspace_id="tenant-a",
    )
    assert public.reuse_scope is ReuseScope.PUBLIC_FOOTPRINT and public.workspace_id is None
    private = stamp_reuse(
        _claim(entity, "core.employee_count", 1, ExtractionMethod.CRM_IMPORT),  # type: ignore[arg-type]
        workspace_id="tenant-a",
    )
    assert private.reuse_scope is ReuseScope.TENANT_PRIVATE and private.workspace_id == "tenant-a"


def test_stamp_reuse_fails_loud_for_a_private_claim_with_no_tenant() -> None:
    """A claim that classifies tenant_private with no workspace_id supplied is a wiring error —
    refused, never silently written public (fail-closed, M4.5 decision #6). A public claim with no
    tenant is fine (it is tenant-less by definition)."""
    entity = new_entity_id()
    with pytest.raises(ValueError, match="tenant_private"):
        stamp_reuse(
            _claim(entity, "core.employee_count", 1, ExtractionMethod.CRM_IMPORT),  # type: ignore[arg-type]
            workspace_id=None,
        )
    public = stamp_reuse(
        _claim(entity, "core.employee_count", 1, ExtractionMethod.API),  # type: ignore[arg-type]
        workspace_id=None,
    )
    assert public.reuse_scope is ReuseScope.PUBLIC_FOOTPRINT and public.workspace_id is None


# --- degradation / DSAR (DB) ------------------------------------------------
# (cross-tenant amortization retired [B3×research] 2026-07-23 — accounts are workspace-local, so
# the old ``reusable_public_value`` amortization test is gone with the hook.)
pytestmark = pytest.mark.usefixtures("require_identity_db")


def test_safe_degradation_isolates_a_normally_public_claim() -> None:
    """With reuse disabled, a normally-public claim becomes tenant-private and B cannot see A's."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            claim = stamp_reuse(
                _claim(entity, "core.employee_count", 250, ExtractionMethod.API),  # type: ignore[arg-type]
                workspace_id="tenant-a",
                policy=ReusePolicy(enabled=False),
            )
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            await insert_claim(conn, claim, validate_field=False)
            b = WorkspaceScope.for_workspace("tenant-b")
            assert await current_value(conn, entity, "core.employee_count", scope=b) is None
            a = WorkspaceScope.for_workspace("tenant-a")
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
                workspace_id="tenant-a",
            )
            private_a = stamp_reuse(
                _claim(entity, "account.crm_note", {"note": "x"}, ExtractionMethod.CRM_IMPORT),  # type: ignore[arg-type]
                workspace_id="tenant-a",
            )
            # Another tenant's private claim on the SAME entity must stay out of A's DSAR set.
            private_b = stamp_reuse(
                _claim(entity, "account.crm_note", {"note": "y"}, ExtractionMethod.CRM_IMPORT),  # type: ignore[arg-type]
                workspace_id="tenant-b",
            )
            await insert_claim(conn, public, validate_field=False)
            await insert_claim(conn, private_a, validate_field=False)
            await insert_claim(conn, private_b, validate_field=False)
            dsar = list(await dsar_private_claims(conn, entity, "tenant-a"))
            assert len(dsar) == 1  # only tenant A's private claim — not the public, not tenant B's
            assert dsar[0].reuse_scope is ReuseScope.TENANT_PRIVATE
            assert dsar[0].workspace_id == "tenant-a"
            assert dsar[0].value_json == {"note": "x"}

    run_async(_run())
