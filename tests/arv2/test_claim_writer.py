"""The lenient claim writer (master plan §2 principle 2, §4): store, stamp, mark — never refuse."""

from __future__ import annotations

import pytest

from clue_api.arv2.claim_writer import TIER_FOR_METHOD, ClaimDraft, LenientClaimWriter
from clue_core import (
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    ReuseScope,
    UseClass,
    new_run_id,
)
from clue_research.claimstore import claims_by_ids
from clue_research.claimstore.registry import (
    FieldRegistryScope,
    UnknownFieldError,
    ValueSchemaError,
    get_effective_field,
)
from clue_research.claimstore.tenancy import WorkspaceScope
from clue_research.identity import insert_account_entity, insert_contact_entity
from tests._workspace import seed_workspace

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def _setup(conn):  # type: ignore[no-untyped-def]
    ws = await seed_workspace(conn, "ws_writer")
    account = await insert_account_entity(
        conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=ws
    )
    contact = await insert_contact_entity(
        conn,
        account_entity_id=account,
        full_name="Nick Fisher",
        linkedin_url="https://www.linkedin.com/in/nicholastfisher",
    )
    return ws, account, contact


def _draft(ws: str, entity, entity_type: EntityType, **overrides: object) -> ClaimDraft:  # type: ignore[no-untyped-def]
    base: dict[str, object] = {
        "entity_id": entity,
        "entity_type": entity_type,
        "field_key": "core.account_name",
        "value_json": "Zafran Security",
        "extraction_method": ExtractionMethod.API,
        "run_id": new_run_id(),
        "research_mode": ResearchMode.ACCOUNT_PROFILING,
        "workspace_id": ws,
        "source_url": "https://api.ai-ark.com/v1/companies",
    }
    base.update(overrides)
    return ClaimDraft(**base)  # type: ignore[arg-type]


def test_tier_and_scope_are_stamped() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, account, _ = await _setup(conn)
            receipt = await LenientClaimWriter(lenient=True).write(
                conn, _draft(ws, account, EntityType.ACCOUNT)
            )
            stored = (
                await claims_by_ids(
                    conn, [receipt.claim_id], scope=WorkspaceScope.for_workspace(ws)
                )
            )[receipt.claim_id]
            assert stored.source_tier == TIER_FOR_METHOD[ExtractionMethod.API] == 1
            assert stored.reuse_scope is ReuseScope.TENANT_PRIVATE and stored.workspace_id == ws
            assert receipt.markers == {} and receipt.registered_field is False

    run_async(_run())


def test_facet_governance_defaults_are_stamped_and_marked() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, _, contact = await _setup(conn)
            receipt = await LenientClaimWriter(lenient=True).write(
                conn,
                _draft(
                    ws,
                    contact,
                    EntityType.CONTACT,
                    field_key="contact.facet.recent_post",
                    value_json="Hiring an ABM manager",
                    extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                    evidence_span="Hiring an ABM manager",
                    source_url="https://www.linkedin.com/posts/x",
                ),
            )
            stored = (
                await claims_by_ids(
                    conn, [receipt.claim_id], scope=WorkspaceScope.for_workspace(ws)
                )
            )[receipt.claim_id]
            assert stored.identity_binding is IdentityBinding.WEAK
            assert stored.use_class is UseClass.PROFESSIONAL_PUBLIC
            assert receipt.markers == {
                "identity_binding_defaulted": True,
                "use_class_defaulted": True,
            }

    run_async(_run())


def test_missing_url_is_marked_in_lenient_mode_and_refused_in_strict_mode() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, account, _ = await _setup(conn)
            receipt = await LenientClaimWriter(lenient=True).write(
                conn, _draft(ws, account, EntityType.ACCOUNT, source_url=None)
            )
            assert receipt.markers == {"source_missing": True}
            with pytest.raises(ValueError, match="source_url"):
                await LenientClaimWriter(lenient=False).write(
                    conn, _draft(ws, account, EntityType.ACCOUNT, source_url=None)
                )
            human = await LenientClaimWriter(lenient=False).write(
                conn,
                _draft(
                    ws,
                    account,
                    EntityType.ACCOUNT,
                    extraction_method=ExtractionMethod.HUMAN,
                    source_url=None,
                ),
            )
            assert human.markers == {}

    run_async(_run())


def test_unknown_key_registers_a_proposed_field_in_lenient_mode() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, account, _ = await _setup(conn)
            draft = _draft(
                ws,
                account,
                EntityType.ACCOUNT,
                field_key="account.claimed_customer_logos_v2",
                value_json=["OpenAI"],
                field_description="Logos on the site",
            )
            with pytest.raises(UnknownFieldError):
                await LenientClaimWriter(lenient=False).write(conn, draft)
            receipt = await LenientClaimWriter(lenient=True).write(conn, draft)
            assert receipt.registered_field is True and receipt.markers == {"proposed_field": True}
            resolved = await get_effective_field(
                conn, scope=FieldRegistryScope.for_workspace(ws), field_key=draft.field_key
            )
            assert resolved is not None and resolved.description == "Logos on the site"
            pack_draft = _draft(
                ws,
                account,
                EntityType.ACCOUNT,
                field_key="vertical_saas.core_banking_vendor",
                value_json="Temenos",
            )
            assert (
                await LenientClaimWriter(lenient=True).write(conn, pack_draft)
            ).registered_field is True

    run_async(_run())


def test_schema_miss_is_stored_with_a_marker_in_lenient_mode() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, account, _ = await _setup(conn)
            draft = _draft(
                ws,
                account,
                EntityType.ACCOUNT,
                field_key="core.employee_count",
                value_json="about 170",
            )
            with pytest.raises(ValueSchemaError):
                await LenientClaimWriter(lenient=False).write(conn, draft)
            receipt = await LenientClaimWriter(lenient=True).write(conn, draft)
            assert receipt.markers == {"schema_valid": False}
            stored = (
                await claims_by_ids(
                    conn, [receipt.claim_id], scope=WorkspaceScope.for_workspace(ws)
                )
            )[receipt.claim_id]
            assert stored.value_json == "about 170" and stored.write_markers == {
                "schema_valid": False
            }

    run_async(_run())


def test_caller_markers_and_priority_pass_through() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws, account, _ = await _setup(conn)
            receipt = await LenientClaimWriter(lenient=True).write(
                conn,
                _draft(
                    ws,
                    account,
                    EntityType.ACCOUNT,
                    signal_priority=1,
                    outreach_safe=False,
                    markers={"pipe_joined_key": "a|b"},
                ),
            )
            stored = (
                await claims_by_ids(
                    conn, [receipt.claim_id], scope=WorkspaceScope.for_workspace(ws)
                )
            )[receipt.claim_id]
            assert stored.signal_priority == 1 and stored.outreach_safe is False
            assert stored.write_markers == {"pipe_joined_key": "a|b"}

    run_async(_run())
