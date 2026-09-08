"""The keys the governed agent model stamps on an answer — a dependency-free leaf.

They live in their own module, importing nothing, so a consumer that only needs to *read* what a
model call cost can do so without dragging in the live OpenRouter client (and with it the vendor
SDK that import-linter Rule 4b keeps behind this package). ``clue_gateway.agent_model`` is what
writes them; ``clue_api.arv2`` is what reads them.
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "ANSWERING_MODEL_KEY",
    "COST_CENTS_KEY",
    "COST_SOURCE_KEY",
    "REQUESTED_MODEL_KEY",
    "ROLE_KEY",
    "CostSource",
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
