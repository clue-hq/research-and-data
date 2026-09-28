"""Frozen row models for Lane B's Clue-owned identity substrate."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from clue_core import UtcDatetime

UserStatus = Literal["active", "suspended", "disabled"]
AuthIdentityStatus = Literal["active", "unlinked", "revoked"]
MembershipStatus = Literal["invited", "active", "suspended", "revoked"]
InvitationStatus = Literal["pending", "accepted", "revoked", "expired"]
RoleKey = Literal["owner", "admin", "operator", "viewer"]


class PlatformUser(BaseModel):
    """A durable Clue human identity; provider identifiers never replace ``user_id``.

    ``first_name``/``last_name``/``job_role`` are the onboarding profile (FI-4 D-3). They are
    personal data — ``erase_platform_user`` clears all three alongside ``display_name``.
    ``job_role`` is a self-described job title and never an authorization role.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    job_role: str | None = None
    email: str | None = None
    status: UserStatus
    created_at: UtcDatetime
    suspended_at: UtcDatetime | None = None
    disabled_at: UtcDatetime | None = None


class AuthIdentity(BaseModel):
    """One replaceable external-subject lookup mapped to a canonical user."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    auth_identity_id: str
    user_id: str
    provider_key: str
    provider_subject: str
    status: AuthIdentityStatus
    linked_at: UtcDatetime
    revoked_at: UtcDatetime | None = None


class WorkspaceMembership(BaseModel):
    """A human user's internal authorization relationship to one workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    membership_id: str
    workspace_id: str
    user_id: str
    role_key: RoleKey
    status: MembershipStatus
    created_at: UtcDatetime
    activated_at: UtcDatetime | None = None
    revoked_at: UtcDatetime | None = None
    # The workspace's display name, filled by the database loader's join; None only for loaders
    # that do not read the workspace row. Users are shown a name, never a workspace id.
    workspace_name: str | None = None


class WorkspaceInvitation(BaseModel):
    """A provisioning row. The bearer token digest is deliberately not exposed here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invitation_id: str
    provider_invitation_id: str | None = None
    workspace_id: str
    invited_address: str
    role_key: RoleKey
    status: InvitationStatus
    expires_at: UtcDatetime
    invited_by_membership_id: str
    accepted_by_user_id: str | None = None
    created_at: UtcDatetime
    accepted_at: UtcDatetime | None = None
    revoked_at: UtcDatetime | None = None


class SelfServeProvisioningRecord(BaseModel):
    """The FI-4 D-2 idempotency record; part of the DSAR bundle (website may identify)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    auth_identity_id: str
    user_id: str
    workspace_id: str
    brand_id: str
    company_website: str | None
    created_at: UtcDatetime


class IdentityBundle(BaseModel):
    """The internal identity part of the B1 DSAR/access surface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user: PlatformUser
    auth_identities: tuple[AuthIdentity, ...]
    memberships: tuple[WorkspaceMembership, ...]
    accepted_invitations: tuple[WorkspaceInvitation, ...]
    self_serve_provisionings: tuple[SelfServeProvisioningRecord, ...] = ()


class IdentityErasureResult(BaseModel):
    """Counts from a deterministic identity-profile erasure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    auth_identities_revoked: int
    memberships_revoked: int
    invitation_addresses_erased: int
    provisioning_websites_erased: int = 0
    artifact_marks_deleted: int = 0
