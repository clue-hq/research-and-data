"""The keys the governed agent model stamps on an answer — a dependency-free leaf.

They live in their own module, importing nothing beyond the standard library, so a consumer that
only needs to *read* what a model call cost can do so without dragging in the live OpenRouter
client (and with it the vendor SDK that import-linter Rule 4b keeps behind this package).
``clue_gateway.agent_model`` is what writes them; the readers are here too —
:func:`cost_cents_from_metadata` is the single parse of the stamp, so every ledger that records a
model call's cost agrees on what the three authority words mean.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Literal, get_args

__all__ = [
    "ANSWERING_MODEL_KEY",
    "COST_CENTS_KEY",
    "COST_SOURCE_KEY",
    "REQUESTED_MODEL_KEY",
    "ROLE_KEY",
    "CostSource",
    "cost_cents_from_metadata",
]

#: The model id that actually answered (an OpenRouter fallback can differ from the requested one).
ANSWERING_MODEL_KEY = "clue_answering_model"
#: The model id the call site asked for.
REQUESTED_MODEL_KEY = "clue_requested_model"
#: What the call cost, in cents, as a string so the ``Decimal`` survives a JSON round trip.
COST_CENTS_KEY = "clue_cost_cents"
#: Which of the three cost authorities answered — see :data:`CostSource`.
COST_SOURCE_KEY = "clue_cost_source"
#: The attribution role the model instance was built for.
ROLE_KEY = "clue_role"

#: ``metered`` — the provider reported what the call cost; ``estimate`` — our own price sheet
#: answered, from the served model's listed rates; ``unpriced`` — the model is on no sheet, so the
#: cost is a blank rather than a zero anyone measured.
CostSource = Literal["metered", "estimate", "unpriced"]

_COST_SOURCES: frozenset[str] = frozenset(get_args(CostSource))


def cost_cents_from_metadata(
    metadata: Mapping[str, object],
) -> tuple[Decimal | None, CostSource | None]:
    """Read the cost stamp off one answer's ``response_metadata``.

    Returns ``(cents, source)``. ``source`` is the stamped word when it is one of the three
    :data:`CostSource` values, else ``None``. ``cents`` is a ``Decimal`` only for a ``metered`` or
    ``estimate`` answer whose ``clue_cost_cents`` parses; an ``unpriced`` answer carries a zero
    that means "no rate", and that must never become a measured zero — so it reads as ``None``.
    Every reader of the stamp (the conversation-turn recorder, the ARV2 research agent) goes
    through here so the two ledgers can never disagree on what a stamp means.
    """
    raw_source = metadata.get(COST_SOURCE_KEY)
    source: CostSource | None = (
        raw_source if isinstance(raw_source, str) and raw_source in _COST_SOURCES else None  # type: ignore[assignment]
    )
    if source is None or source == "unpriced":
        return None, source
    raw = metadata.get(COST_CENTS_KEY)
    if raw is None:
        return None, source
    try:
        return Decimal(str(raw)), source
    except InvalidOperation:
        return None, source
