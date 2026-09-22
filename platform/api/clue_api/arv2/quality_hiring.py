"""Posting observation is dated evidence, not an indefinite assertion of urgency."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any


def date_of(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None


def hiring_context(
    record: Mapping[str, Any], *, observed: date, confirmed_board: bool, listed: bool | None
) -> dict[str, Any]:
    closing = next(
        (
            record[k]
            for k in ("validThrough", "closingDate", "expiresAt", "closingAt")
            if record.get(k) is not None
        ),
        None,
    )
    status = str(record.get("status") or record.get("state") or "").casefold()
    closed = status in {"closed", "filled", "expired", "archived", "unpublished"} or listed is False
    elapsed = date_of(closing)
    state = (
        "closed"
        if closed
        else "historical"
        if elapsed and elapsed < observed
        else "open"
        if confirmed_board
        else "unknown"
    )
    return {
        "hiring_state": state,
        "observed_on": observed.isoformat(),
        "closing_at": closing,
        "source_status": status or None,
        "date_timezone": record.get("timezone"),
        "state_basis": "official_board_observation" if confirmed_board else "unconfirmed_listing",
        "qualifications": []
        if state == "open"
        else ["This listing does not establish a current opening or buying urgency."],
    }


def current_hiring_state(value: Mapping[str, Any], today: date | None = None) -> str:
    today = today or datetime.now(UTC).date()
    state = str(value.get("hiring_state") or "unknown")
    closing = date_of(value.get("closing_at"))
    if state == "open" and closing and closing < today:
        return "historical"
    return state if state in {"open", "closed", "historical", "unknown"} else "unknown"
