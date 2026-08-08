"""B1 database acceptance: canonical ids, isolation, provisioning, lifecycle, and erasure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from clue_auth import (
    InvitationUnavailableError,
    MembershipPermissionError,
    accept_workspace_invitation,
    create_platform_user,
    create_workspace_invitation,
    create_workspace_membership,
    erase_platform_user,
    get_auth_identity,
    get_workspace_membership,
    hash_invitation_token,
    identity_bundle,
    link_auth_identity,
    provision_workspace_owner,
    revoke_workspace_membership,
)
from clue_spine import create_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_auth_db")

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def test_provider_swap_preserves_clue_user_and_membership_ids() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            provisioned = await provision_workspace_owner(
                conn,
                workspace_name="Acme",
                provider_key="clerk",
                provider_subject="provider-user-1",
                display_name="Ada",
                now=NOW,
            )
            replacement = await link_auth_identity(
                conn,
                user_id=provisioned.user.user_id,
                provider_key="enterprise-oidc",
                provider_subject="oidc-subject-9",
            )

            assert provisioned.user.user_id.startswith("usr_")
            assert provisioned.membership.membership_id.startswith("wsm_")
            assert replacement.auth_identity_id.startswith("aid_")
            assert replacement.user_id == provisioned.user.user_id
            membership = await get_workspace_membership(
                conn,
                workspace_id=provisioned.workspace.workspace_id,
                user_id=provisioned.user.user_id,
            )
            assert membership == provisioned.membership

    run_async(scenario())


def test_one_user_has_distinct_memberships_in_two_workspaces() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await provision_workspace_owner(
                conn,
                workspace_name="First",
                provider_key="clerk",
                provider_subject="multi-workspace-user",
                now=NOW,
            )
            second_workspace = await create_workspace(conn, name="Second")
            second_membership = await create_workspace_membership(
                conn,
                workspace_id=second_workspace.workspace_id,
                user_id=first.user.user_id,
                role_key="viewer",
                now=NOW,
            )

            assert second_membership.user_id == first.user.user_id
            assert second_membership.membership_id != first.membership.membership_id
            assert second_membership.workspace_id != first.membership.workspace_id
            assert (
                await get_workspace_membership(
                    conn,
                    workspace_id=first.workspace.workspace_id,
                    user_id=first.user.user_id,
                )
                == first.membership
            )

    run_async(scenario())


def test_invitation_acceptance_is_address_bound_and_same_user_replay_is_idempotent() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await provision_workspace_owner(
                conn,
                workspace_name="Acme",
                provider_key="clerk",
                provider_subject="owner",
                now=NOW,
            )
            raw_token = "one-time-secret"
            invitation = await create_workspace_invitation(
                conn,
                workspace_id=owner.workspace.workspace_id,
                invited_address="Person@Example.com",
                role_key="operator",
                token_digest=hash_invitation_token(raw_token),
                expires_at=NOW + timedelta(hours=1),
                invited_by_membership_id=owner.membership.membership_id,
                now=NOW,
            )

            with pytest.raises(InvitationUnavailableError, match="address"):
                await accept_workspace_invitation(
                    conn,
                    raw_token=raw_token,
                    verified_address="attacker@example.com",
                    provider_key="clerk",
                    provider_subject="attacker",
                    now=NOW,
                )
            assert (
                await get_auth_identity(conn, provider_key="clerk", provider_subject="attacker")
                is None
            )

            accepted = await accept_workspace_invitation(
                conn,
                raw_token=raw_token,
                verified_address="person@example.com",
                provider_key="clerk",
                provider_subject="invited-person",
                display_name="Person",
                now=NOW,
            )
            replayed = await accept_workspace_invitation(
                conn,
                raw_token=raw_token,
                verified_address="person@example.com",
                provider_key="clerk",
                provider_subject="invited-person",
                now=NOW,
            )

            assert accepted.invitation.invitation_id == invitation.invitation_id
            assert accepted.membership.role_key == "operator"
            assert accepted.membership.workspace_id == owner.workspace.workspace_id
            assert replayed == accepted

    run_async(scenario())


def test_invitation_cannot_cross_workspace_or_override_revocation() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await provision_workspace_owner(
                conn,
                workspace_name="First",
                provider_key="clerk",
                provider_subject="owner-1",
                now=NOW,
            )
            second = await provision_workspace_owner(
                conn,
                workspace_name="Second",
                provider_key="clerk",
                provider_subject="owner-2",
                now=NOW,
            )
            with pytest.raises(MembershipPermissionError, match="workspace"):
                await create_workspace_invitation(
                    conn,
                    workspace_id=second.workspace.workspace_id,
                    invited_address="person@example.com",
                    role_key="viewer",
                    token_digest=hash_invitation_token("cross-workspace"),
                    expires_at=NOW + timedelta(hours=1),
                    invited_by_membership_id=first.membership.membership_id,
                    now=NOW,
                )

            target = await create_platform_user(conn, display_name="Target")
            await link_auth_identity(
                conn,
                user_id=target.user_id,
                provider_key="clerk",
                provider_subject="target",
            )
            membership = await create_workspace_membership(
                conn,
                workspace_id=first.workspace.workspace_id,
                user_id=target.user_id,
                role_key="viewer",
                now=NOW,
            )
            await revoke_workspace_membership(conn, membership.membership_id, now=NOW)
            raw_token = "cannot-resurrect"
            await create_workspace_invitation(
                conn,
                workspace_id=first.workspace.workspace_id,
                invited_address="target@example.com",
                role_key="operator",
                token_digest=hash_invitation_token(raw_token),
                expires_at=NOW + timedelta(hours=1),
                invited_by_membership_id=first.membership.membership_id,
                now=NOW,
            )
            with pytest.raises(InvitationUnavailableError, match="cannot override"):
                await accept_workspace_invitation(
                    conn,
                    raw_token=raw_token,
                    verified_address="target@example.com",
                    provider_key="clerk",
                    provider_subject="target",
                    now=NOW,
                )

    run_async(scenario())


def test_identity_dsar_erases_provider_values_but_keeps_internal_audit_ids() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await provision_workspace_owner(
                conn,
                workspace_name="Acme",
                provider_key="clerk",
                provider_subject="owner-for-dsar",
                display_name="Owner Name",
                now=NOW,
            )
            raw_token = "dsar-invite"
            await create_workspace_invitation(
                conn,
                workspace_id=owner.workspace.workspace_id,
                invited_address="person@example.com",
                role_key="viewer",
                token_digest=hash_invitation_token(raw_token),
                expires_at=NOW + timedelta(hours=1),
                invited_by_membership_id=owner.membership.membership_id,
                now=NOW,
            )
            accepted = await accept_workspace_invitation(
                conn,
                raw_token=raw_token,
                verified_address="person@example.com",
                provider_key="clerk",
                provider_subject="subject-to-erase",
                display_name="Person To Erase",
                now=NOW,
            )
            original_user_id = accepted.user.user_id
            original_membership_id = accepted.membership.membership_id

            result = await erase_platform_user(
                conn, accepted.user.user_id, now=NOW + timedelta(minutes=1)
            )
            bundle = await identity_bundle(conn, accepted.user.user_id)

            assert result.auth_identities_revoked == 1
            assert result.memberships_revoked == 1
            assert result.invitation_addresses_erased == 1
            assert bundle is not None
            assert bundle.user.user_id == original_user_id
            assert bundle.user.display_name is None
            assert bundle.user.status == "disabled"
            assert bundle.memberships[0].membership_id == original_membership_id
            assert bundle.memberships[0].status == "revoked"
            assert bundle.auth_identities[0].provider_subject.startswith("erased:aid_")
            assert bundle.auth_identities[0].status == "revoked"
            assert bundle.accepted_invitations[0].invited_address.startswith("erased:wsi_")
            assert (
                await get_auth_identity(
                    conn, provider_key="clerk", provider_subject="subject-to-erase"
                )
                is None
            )

    run_async(scenario())
