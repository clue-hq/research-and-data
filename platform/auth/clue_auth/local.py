"""Explicit local/test authenticator; production configuration must reject it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from clue_auth.errors import AuthenticationRequired
from clue_auth.principal import AuthenticationRequest, ExternalSession


class LocalFixtureAuthenticator:
    """Authenticate an opaque local subject that must still resolve through ``auth_identity``."""

    provider_key = "local_fixture"

    async def authenticate(self, request: AuthenticationRequest) -> ExternalSession:
        subject = request.local_subject.strip() if request.local_subject else ""
        if not subject:
            raise AuthenticationRequired("local fixture subject is required")
        now = datetime.now(UTC)
        return ExternalSession(
            provider_key=self.provider_key,
            provider_subject=subject,
            session_id=f"local:{subject}",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            authenticated_at=now,
        )
