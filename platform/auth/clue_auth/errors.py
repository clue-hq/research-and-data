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


class InvitationAddressMismatch(InvitationUnavailableError):
    """The provider-verified address differs from the invitation delivery target."""


class PrincipalError(AuthIdentityError):
    """Stable authentication/authorization failure safe to expose at an HTTP edge."""

    code = "AUTHENTICATION_REQUIRED"
    status_code = 401

    def __init__(
        self, message: str, *, subject: str | None = None, user_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        #: Who was refused, for the operator log only — never for the response body. ``subject``
        #: is the provider's verified subject (a Clerk user id) when the refusal happened after
        #: the token was verified; ``user_id`` the Clue user when identity had resolved. Both
        #: ``None`` for a refusal before either was known (no token, a bad signature).
        self.subject = subject
        self.user_id = user_id


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


class ProvisioningConflict(PrincipalError):
    """Self-serve provisioning cannot proceed for this identity (suspended/inconsistent state)."""

    code = "PROVISIONING_CONFLICT"
    status_code = 409


class ProvisioningValidationError(PrincipalError):
    """A self-serve submission does not carry enough to provision (422).

    The one refusal here whose ``code`` is per-instance rather than per-class: the submission
    can be short of different things, and the caller names which one so the HTTP envelope
    carries it verbatim (``COMPANY_NAME_REQUIRED``) without a class per field.
    """

    code = "PROVISIONING_INVALID"
    status_code = 422

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
