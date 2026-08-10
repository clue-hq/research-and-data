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
    """A durable Clue human identity; provider identifiers never replace ``user_id``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    display_name: str | None = None
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


class WorkspaceInvitation(BaseModel):
    """A provisioning row. The bearer token digest is deliberately not exposed here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invitation_id: str
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


class IdentityBundle(BaseModel):
    """The internal identity part of the B1 DSAR/access surface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user: PlatformUser
    auth_identities: tuple[AuthIdentity, ...]
    memberships: tuple[WorkspaceMembership, ...]
    accepted_invitations: tuple[WorkspaceInvitation, ...]


class IdentityErasureResult(BaseModel):
    """Counts from a deterministic identity-profile erasure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    auth_identities_revoked: int
    memberships_revoked: int
    invitation_addresses_erased: int
