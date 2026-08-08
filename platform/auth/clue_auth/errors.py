"""Stable domain errors for the provider-neutral identity substrate."""

from __future__ import annotations


class AuthIdentityError(RuntimeError):
    """Base class for identity-substrate failures."""


class IdentityConflictError(AuthIdentityError):
    """An external identity cannot be linked to the requested internal user."""


class LifecycleTransitionError(AuthIdentityError):
    """A requested user, identity, membership, or invitation transition is invalid."""


class MembershipPermissionError(AuthIdentityError):
    """The supplied membership cannot administer the requested workspace operation."""


class InvitationUnavailableError(AuthIdentityError):
    """An invitation is absent, expired, revoked, accepted by another user, or mismatched."""
