"""What one OpenRouter call actually cost, read off OpenRouter's own usage block.

One rule for every caller (the ARV2 provider ledger and the governed agent gateway), so the spend
totals mean the same thing everywhere. ``cost_details.upstream_inference_cost`` wins over ``cost``:
a call made with the account's own provider key (BYOK) reports ``cost: 0`` while the provider still
charged, so reading ``cost`` alone would record a real spend as free. When a BYOK call does report
a ``cost``, that is OpenRouter's own BYOK fee, paid on top of the upstream charge, so the two are
summed.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

__all__ = ["openrouter_charged_usd"]


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float | str):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return None


def openrouter_charged_usd(usage: Mapping[str, object] | None) -> Decimal | None:
    """USD charged for one call, or ``None`` when the usage block does not say."""
    if not isinstance(usage, Mapping):
        return None
    details = usage.get("cost_details")
    upstream = (
        _decimal(details.get("upstream_inference_cost")) if isinstance(details, Mapping) else None
    )
    fee = _decimal(usage.get("cost"))
    if upstream is None:
        return fee
    if usage.get("is_byok") is True and fee is not None:
        return upstream + fee
    return upstream
