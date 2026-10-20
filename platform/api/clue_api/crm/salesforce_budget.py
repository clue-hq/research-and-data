"""Keep Clue to a small share of a Salesforce org's daily API allowance (R-7.5).

Salesforce gives each org one daily pool of API calls shared by every integration it runs, and a
pool that runs dry stops all of them. So before each Salesforce read Clue checks two things:

* its own calls today on this connection stay under ``share_pct`` % of the org's daily maximum
  (``CLUE_CRM_SALESFORCE_API_SHARE_PCT``, default 10), counted in our own database; and
* the org as a whole still has at least 10 % of its allowance left, whoever spent the rest.

The org's figures come from ``SALESFORCE_GET_ORG_LIMITS``, kept for five minutes per connection
so the check does not itself eat the allowance it protects. That lookup is counted too.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.crm.composio_gateway import ComposioGateway, composio_user_id
from clue_api.crm.connections import CrmConnection, count_salesforce_call

__all__ = [
    "API_DISABLED_MESSAGE",
    "ORG_LIMITS_ACTION",
    "CrmBudgetExhausted",
    "OrgApiLimits",
    "SalesforceBudget",
    "is_api_disabled",
]

ORG_LIMITS_ACTION = "SALESFORCE_GET_ORG_LIMITS"
#: Stop when the org as a whole has less than this share of its daily allowance left.
_ORG_FLOOR_PCT = 10
_CACHE_TTL_S = 300.0
API_DISABLED_MESSAGE = (
    "This Salesforce org does not allow API access, so Clue cannot read it. API access comes "
    "with Enterprise, Unlimited, Performance and Developer editions; on Professional Edition it "
    "is a paid add-on. Ask the person to enable it, or to give the numbers in the chat instead."
)


def is_api_disabled(error: str | None) -> bool:
    """Salesforce's own error code for an org without API access (e.g. Professional Edition)."""
    return error is not None and "API_DISABLED_FOR_ORG" in error


class CrmBudgetExhausted(Exception):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class OrgApiLimits:
    max: int
    remaining: int


class SalesforceBudget:
    """The guard ``run_crm_action`` calls before every Salesforce read."""

    def __init__(
        self,
        gateway: ComposioGateway,
        *,
        share_pct: int,
        version: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._gateway = gateway
        self._share_pct = share_pct
        self._version = version
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[UUID, tuple[float, OrgApiLimits]] = {}

    async def take_call(
        self, conn: AsyncConnection, *, connection: CrmConnection, today: date
    ) -> None:
        """Count one call, or raise :class:`CrmBudgetExhausted` without counting it."""
        limits = await self._limits(conn, connection=connection, today=today)
        if limits.remaining * 100 < limits.max * _ORG_FLOOR_PCT:
            raise CrmBudgetExhausted(
                "salesforce_api_share_exhausted",
                f"The Salesforce org has {limits.remaining} of its {limits.max} daily API calls "
                f"left (under {_ORG_FLOOR_PCT}%), so Clue has stopped reading it for today to "
                "leave the rest to the org's other tools.",
            )
        allowed = limits.max * self._share_pct // 100
        counted = await count_salesforce_call(
            conn, connection_id=connection.connection_id, today=today, allowed=allowed
        )
        if counted is None or allowed < 1:
            raise CrmBudgetExhausted(
                "salesforce_api_share_exhausted",
                f"Clue has used its share of this Salesforce org's daily API calls ({allowed} "
                f"calls, {self._share_pct}% of {limits.max}). Reading resumes tomorrow (UTC).",
            )

    async def _limits(
        self, conn: AsyncConnection, *, connection: CrmConnection, today: date
    ) -> OrgApiLimits:
        now = self._clock()
        with self._lock:
            cached = self._cache.get(connection.connection_id)
        if cached is not None and now - cached[0] < _CACHE_TTL_S:
            return cached[1]
        await count_salesforce_call(conn, connection_id=connection.connection_id, today=today)
        result = await self._gateway.execute(
            slug=ORG_LIMITS_ACTION,
            arguments={},
            connected_account_id=connection.composio_connected_account_id,
            user_id=composio_user_id(connection.workspace_id),
            version=self._version,
        )
        if not result.successful and is_api_disabled(result.error):
            raise CrmBudgetExhausted("salesforce_api_disabled", API_DISABLED_MESSAGE)
        limits = _parse(result.data) if result.successful else None
        if limits is None:
            raise CrmBudgetExhausted(
                "salesforce_limits_unavailable",
                "Could not read the Salesforce org's API limits, so Clue cannot tell whether "
                f"reading is safe. {result.error or ''}".strip(),
            )
        with self._lock:
            self._cache[connection.connection_id] = (now, limits)
        return limits


def _parse(data: Any) -> OrgApiLimits | None:
    for body in (data, data.get("data") if isinstance(data, dict) else None):
        daily = body.get("DailyApiRequests") if isinstance(body, dict) else None
        if isinstance(daily, dict):
            maximum, remaining = daily.get("Max"), daily.get("Remaining")
            if isinstance(maximum, int) and isinstance(remaining, int) and maximum > 0:
                return OrgApiLimits(max=maximum, remaining=remaining)
    return None
