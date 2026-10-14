"""An operator gives an existing user one more workspace they own (2026-10-14).

Self-serve signup is first-time setup only, so a user who already has a workspace gets a second
one through this operator path instead: the workspace, its one brand (``POST /onboarding`` needs
exactly one), and an active owner membership, for a user found by email. No signup record is
written; nothing about the user's existing workspaces changes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_auth import (
    list_user_memberships,
    provision_additional_workspace,
    provision_self_serve_workspace,
)
from clue_auth.errors import IdentityConflictError, ProvisioningValidationError
from clue_auth.store import suspend_platform_user, update_platform_user_email
from clue_spine import list_brands_for_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_auth_db")


async def _existing_user(conn, *, subject: str, email: str):
    first = await provision_self_serve_workspace(
        conn,
        provider_key="clerk",
        provider_subject=subject,
        first_name="Shank",
        last_name="Keshri",
        job_role="Founder",
        company_name="Clue HQ",
        company_website="https://cluehq.example",
    )
    await update_platform_user_email(conn, first.user.user_id, email)
    return first


def test_creates_an_owned_workspace_with_one_brand_for_an_existing_user() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await _existing_user(conn, subject="addws-1", email="addws1@example.com")
            result = await provision_additional_workspace(
                conn,
                email="  AddWS1@Example.com ",
                company_website="https://acme.example",
                company_name="Acme",
            )
            assert result.user.user_id == first.user.user_id
            assert result.workspace.name == "Acme"
            assert result.workspace.workspace_id != first.workspace.workspace_id
            assert result.membership.role_key == "owner"
            assert result.membership.status == "active"
            assert result.company_website == "https://acme.example"
            brands = await list_brands_for_workspace(conn, result.workspace.workspace_id)
            assert [b.brand_id for b in brands] == [result.brand.brand_id]
            memberships = await list_user_memberships(conn, first.user.user_id)
            assert {m.workspace_id for m in memberships if m.status == "active"} == {
                first.workspace.workspace_id,
                result.workspace.workspace_id,
            }
            signup_rows = (
                await conn.execute(
                    text("SELECT count(*) FROM self_serve_provisioning WHERE user_id = :u"),
                    {"u": first.user.user_id},
                )
            ).scalar_one()
            assert signup_rows == 1

    run_async(scenario())


def test_a_blank_name_is_derived_from_the_website() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _existing_user(conn, subject="addws-2", email="addws2@example.com")
            result = await provision_additional_workspace(
                conn, email="addws2@example.com", company_website="https://www.acme.example/"
            )
            assert result.workspace.name == "Acme"

    run_async(scenario())


def test_a_second_run_for_the_same_company_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _existing_user(conn, subject="addws-3", email="addws3@example.com")
            await provision_additional_workspace(
                conn, email="addws3@example.com", company_website="https://acme.example"
            )
            with pytest.raises(IdentityConflictError, match="already owns"):
                await provision_additional_workspace(
                    conn, email="addws3@example.com", company_website="https://acme.example"
                )

    run_async(scenario())


@pytest.mark.parametrize(
    "website", ["acme.example", "https://acme", "https://acme .example", "", "   "]
)
def test_a_website_that_is_not_an_http_url_is_refused(website: str) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _existing_user(conn, subject="addws-4", email="addws4@example.com")
            with pytest.raises(ProvisioningValidationError) as refused:
                await provision_additional_workspace(
                    conn, email="addws4@example.com", company_website=website
                )
            assert refused.value.code == "COMPANY_WEBSITE_REQUIRED"

    run_async(scenario())


def test_an_unknown_email_is_refused_before_any_write() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            before = (await conn.execute(text("SELECT count(*) FROM workspace"))).scalar_one()
            with pytest.raises(IdentityConflictError, match="no Clue user"):
                await provision_additional_workspace(
                    conn, email="nobody@example.com", company_website="https://acme.example"
                )
            after = (await conn.execute(text("SELECT count(*) FROM workspace"))).scalar_one()
            assert after == before

    run_async(scenario())


def test_an_email_shared_by_two_users_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _existing_user(conn, subject="addws-5a", email="shared@example.com")
            await _existing_user(conn, subject="addws-5b", email="Shared@Example.com")
            with pytest.raises(IdentityConflictError, match="more than one"):
                await provision_additional_workspace(
                    conn, email="shared@example.com", company_website="https://acme.example"
                )

    run_async(scenario())


def test_a_suspended_user_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await _existing_user(conn, subject="addws-6", email="addws6@example.com")
            await suspend_platform_user(conn, first.user.user_id)
            with pytest.raises(IdentityConflictError, match="not active"):
                await provision_additional_workspace(
                    conn, email="addws6@example.com", company_website="https://acme.example"
                )

    run_async(scenario())
