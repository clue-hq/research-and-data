"""DB-backed tests for the M3.1 versioned ICP spec data model (ENG-104).

One test per acceptance criterion: create persists an immutable versioned row; an edit appends a new
version (parent_version set) leaving the prior byte-identical; multiple icp_keys per client coexist
(D5); activation archives the prior atomically (exactly one active); a field-key absent from M1.3
registry / a pack absent from the M3.3 catalog is rejected at write naming the offender; diff_icp
reports the structural delta; a pinned version is reproducible after later edits. Plus the
append-only DB trigger and enum-parity with core.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ICPCreatedFrom, ICPStatus
from clue_research.icp import (
    HEALTHCARE_PRACTICE,
    ICPSpecValidationError,
    UnknownICPSpecError,
    activate_icp_version,
    create_icp_spec,
    diff_icp,
    get_active_icp,
    get_icp_version,
    list_icp_keys,
    list_icp_versions,
    register_pack_catalog,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_icp_db")


async def _enum_labels(conn: AsyncConnection, type_name: str) -> list[str]:
    result = await conn.execute(
        text(
            "SELECT e.enumlabel AS label FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = :name ORDER BY e.enumsortorder"
        ),
        {"name": type_name},
    )
    return [str(row["label"]) for row in result.mappings().all()]


def test_create_persists_immutable_versioned_row() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            spec = await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.employee_count", "core.primary_domain"),
                label="v1",
            )
            assert spec.version == 1
            assert spec.parent_version is None
            assert spec.status is ICPStatus.DRAFT
            assert spec.field_keys == ("core.employee_count", "core.primary_domain")
            assert await get_icp_version(conn, "acme", "default", 1) == spec

    run_async(_run())


def test_edit_appends_version_and_prior_is_byte_identical() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            v1 = await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.employee_count",),
                activate=True,
            )
            v2 = await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.CLIENT_EDIT,
                field_keys=("core.employee_count", "core.primary_domain"),
            )
            assert v2.version == 2
            assert v2.parent_version == 1
            assert v2.status is ICPStatus.DRAFT
            # prior version unchanged (still active, byte-identical to the returned object)
            v1_again = await get_icp_version(conn, "acme", "default", 1)
            assert v1_again == v1
            assert v1_again is not None and v1_again.field_keys == ("core.employee_count",)
            assert v1_again.status is ICPStatus.ACTIVE

    run_async(_run())


def test_multiple_icp_keys_per_client_coexist() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="enterprise",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.employee_count",),
            )
            await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="smb",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.primary_domain",),
            )
            assert await list_icp_keys(conn, "acme") == ["enterprise", "smb"]
            ent = await get_icp_version(conn, "acme", "enterprise", 1)
            smb = await get_icp_version(conn, "acme", "smb", 1)
            assert ent is not None and ent.field_keys == ("core.employee_count",)
            assert smb is not None and smb.field_keys == ("core.primary_domain",)

    run_async(_run())


def test_activation_archives_prior_atomically_one_active() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.employee_count",),
                activate=True,
            )
            await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.CLIENT_EDIT,
                field_keys=("core.primary_domain",),
            )
            await activate_icp_version(conn, "acme", "default", 2)

            active = await get_active_icp(conn, "acme", "default")
            assert active is not None and active.version == 2
            v1 = await get_icp_version(conn, "acme", "default", 1)
            assert v1 is not None and v1.status is ICPStatus.ARCHIVED
            versions = await list_icp_versions(conn, "acme", "default")
            assert sum(1 for s in versions if s.status is ICPStatus.ACTIVE) == 1

    run_async(_run())


def test_unknown_field_key_rejected_at_write() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            with pytest.raises(ICPSpecValidationError) as exc:
                await create_icp_spec(
                    conn,
                    client_id="acme",
                    icp_key="default",
                    created_from=ICPCreatedFrom.SYNTHESIS,
                    field_keys=("core.employee_count", "account.ghost_field"),
                )
            assert "account.ghost_field" in str(exc.value)

    run_async(_run())


def test_unknown_pack_rejected_at_write() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            with pytest.raises(ICPSpecValidationError) as exc:
                await create_icp_spec(
                    conn,
                    client_id="acme",
                    icp_key="default",
                    created_from=ICPCreatedFrom.SYNTHESIS,
                    field_keys=("core.employee_count",),
                    enabled_packs=("nonexistent_pack",),
                )
            assert "nonexistent_pack" in str(exc.value)

    run_async(_run())


def test_enabled_pack_validates_against_m33_catalog() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            await register_pack_catalog(conn, HEALTHCARE_PRACTICE)  # M3.3 catalog + healthcare.npi
            spec = await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="health",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("healthcare.npi",),
                enabled_packs=("healthcare_practice",),
            )
            assert spec.enabled_packs == ("healthcare_practice",)
            assert spec.field_keys == ("healthcare.npi",)

    run_async(_run())


def test_diff_icp_reports_structural_delta() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            v1 = await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.employee_count", "core.primary_domain"),
                discovery_strategy={"channels": ["web"]},
                source_profile_ref={"ref": "v1"},
                scoring_rubric={"fit": {"weight": 1}},
            )
            v2 = await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.CLIENT_EDIT,
                field_keys=("core.employee_count", "core.work_email"),
                discovery_strategy={"channels": ["web", "events"]},
                source_profile_ref={"ref": "v2"},
                scoring_rubric={"fit": {"weight": 2}},
            )
            delta = diff_icp(v1, v2)
            assert delta.added_field_keys == ("core.work_email",)
            assert delta.removed_field_keys == ("core.primary_domain",)
            # every "changed slot" flag is positively exercised (acceptance: report changed
            # rubric/source-profile/discovery refs)
            assert delta.scoring_rubric_changed is True
            assert delta.source_profile_changed is True
            assert delta.discovery_strategy_changed is True
            # a spec diffed against itself reports no changes (the False branch)
            same = diff_icp(v1, v1)
            assert same.added_field_keys == () and same.removed_field_keys == ()
            assert same.scoring_rubric_changed is False
            assert same.source_profile_changed is False
            assert same.discovery_strategy_changed is False

    run_async(_run())


def test_field_keys_and_packs_deduped_on_write() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            await register_pack_catalog(conn, HEALTHCARE_PRACTICE)
            spec = await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.employee_count", "core.employee_count", "healthcare.npi"),
                enabled_packs=("healthcare_practice", "healthcare_practice"),
            )
            # duplicates collapse, first-seen order preserved (the stored set is canonical)
            assert spec.field_keys == ("core.employee_count", "healthcare.npi")
            assert spec.enabled_packs == ("healthcare_practice",)

    run_async(_run())


def test_pinned_version_reproducible_after_later_edits() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            v1 = await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.employee_count",),
            )
            snapshot = await get_icp_version(conn, "acme", "default", 1)
            for fields in [("core.primary_domain",), ("core.work_email",)]:
                await create_icp_spec(
                    conn,
                    client_id="acme",
                    icp_key="default",
                    created_from=ICPCreatedFrom.CLIENT_EDIT,
                    field_keys=fields,
                )
            assert await get_icp_version(conn, "acme", "default", 1) == snapshot == v1

    run_async(_run())


def test_append_only_trigger_rejects_content_update_allows_status() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.employee_count",),
            )
            # mutating a content column is rejected by the append-only trigger
            sp = await conn.begin_nested()
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        "UPDATE icp_spec SET label = 'hacked' "
                        "WHERE client_id = 'acme' AND icp_key = 'default' AND version = 1"
                    )
                )
            await sp.rollback()
            # a status transition is allowed
            await conn.execute(
                text(
                    "UPDATE icp_spec SET status = 'active' "
                    "WHERE client_id = 'acme' AND icp_key = 'default' AND version = 1"
                )
            )
            active = await get_active_icp(conn, "acme", "default")
            assert active is not None and active.version == 1

    run_async(_run())


def test_activate_unknown_version_raises() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            with pytest.raises(UnknownICPSpecError):
                await activate_icp_version(conn, "acme", "default", 99)

    run_async(_run())


def test_icp_spec_enums_match_core() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            assert await _enum_labels(conn, "icp_status") == [s.value for s in ICPStatus]
            assert await _enum_labels(conn, "icp_created_from") == [c.value for c in ICPCreatedFrom]

    run_async(_run())
