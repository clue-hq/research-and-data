"""Who is asking, for the open operator routes and scripts (spec 2026-10-25 §8 D1).

The ``/ops/v1`` routes carry no sign-in (founder ruling 2026-10-25), so every call names the
operator by ``operator_email``. It must belong to an existing Clue user — the onboarding run's
requester is a foreign key — and it is SELF-DECLARED: the audit trail records who the caller said
they were.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class OpsRefused(Exception):
    """A named refusal: the HTTP status, a stable code and a plain message."""

    def __init__(
        self, status: int, code: str, message: str, *, detail: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.detail}


@dataclass(frozen=True)
class Operator:
    user_id: str
    email: str

    @property
    def actor(self) -> str:
        return f"operator:{self.email}"


async def resolve_operator(conn: AsyncConnection, email: str) -> Operator:
    address = email.strip().casefold()
    user_ids = (
        (
            await conn.execute(
                text("SELECT user_id FROM platform_user WHERE lower(email) = :email"),
                {"email": address},
            )
        )
        .scalars()
        .all()
    )
    if len(user_ids) != 1:
        raise OpsRefused(
            422,
            "operator_unknown",
            f"operator_email {address!r} must name exactly one existing Clue user",
        )
    return Operator(user_id=str(user_ids[0]), email=address)
