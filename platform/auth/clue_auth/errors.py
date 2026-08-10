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


class PrincipalError(AuthIdentityError):
    """Stable authentication/authorization failure safe to expose at an HTTP edge."""

    code = "AUTHENTICATION_REQUIRED"
    status_code = 401

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AuthenticationRequired(PrincipalError):
    code = "AUTHENTICATION_REQUIRED"
    status_code = 401


class SessionInvalid(PrincipalError):
    code = "SESSION_INVALID"
    status_code = 401


class AuthenticationUnavailable(PrincipalError):
    """The configured identity provider cannot currently verify otherwise-usable sessions."""

    code = "AUTHENTICATION_UNAVAILABLE"
    status_code = 503


class IdentityNotProvisioned(PrincipalError):
    code = "IDENTITY_NOT_PROVISIONED"
    status_code = 403


class UserDisabled(PrincipalError):
    code = "USER_DISABLED"
    status_code = 403


class WorkspaceForbidden(PrincipalError):
    code = "WORKSPACE_FORBIDDEN"
    status_code = 403


class PermissionDenied(PrincipalError):
    code = "PERMISSION_DENIED"
    status_code = 403


class MembershipStateChanged(PrincipalError):
    code = "MEMBERSHIP_STATE_CHANGED"
    status_code = 409
