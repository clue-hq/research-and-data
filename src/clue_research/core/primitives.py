"""Primitive value types shared across the subsystem (M0.2).

Identifiers and constrained scalars that the canonical contracts (claim, entity,
field_definition, source_manifest, account_handoff) are built from. Kept separate
so every other ``core`` module — and every downstream package — imports one shared
definition and never re-declares "an id" or "a 0..1 confidence".

The cardinal rule encoded here: **everything keys on a resolved ``EntityId``, never a
free-text name** (conventions §2). ``EntityId`` is a distinct (NewType) UUID, so a
company *name* is statically not an ``EntityId`` and, inside any model field typed
``EntityId``, a non-UUID value is rejected at validation time.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, NewType
from uuid import UUID, uuid4

from annotated_types import Ge, Le
from pydantic import AwareDatetime

# --- identifiers ------------------------------------------------------------
# Distinct id types. Only the identity service (M2) is allowed to mint an EntityId
# from a real-world entity; everything else receives one and passes it around.
EntityId = NewType("EntityId", UUID)
ClaimId = NewType("ClaimId", UUID)
RunId = NewType("RunId", UUID)
# The outer durable-execution job id (M7.3 ``campaign_run.id``). Distinct from ``RunId``, which is a
# *per-account* research run (``account_run.id`` — the ``claim.run_id`` provenance). One campaign
# run fans out into many account runs; distinct types stop the two ids being transposed.
CampaignRunId = NewType("CampaignRunId", UUID)


def new_entity_id() -> EntityId:
    """Mint a fresh ``EntityId``. In production the identity service (M2) owns this."""
    return EntityId(uuid4())


def new_claim_id() -> ClaimId:
    return ClaimId(uuid4())


def new_run_id() -> RunId:
    return RunId(uuid4())


def new_campaign_run_id() -> CampaignRunId:
    """Mint a fresh ``CampaignRunId``. The campaign-run state machine (M7.3) owns this."""
    return CampaignRunId(uuid4())


# --- constrained scalars ----------------------------------------------------
# Source-trust tier (substrate §4): 1 deterministic API · 2 official-source scrape ·
# 3 reputable third party · 4 LLM synthesis (last resort).
SourceTier = Annotated[int, Ge(1), Le(4)]

# Resolver-reported confidence in a claim's value, 0..1 (substrate §1).
Confidence = Annotated[float, Ge(0.0), Le(1.0)]

# Count of independent tier<=3 sources agreeing (substrate §1). Never negative.
Corroborations = Annotated[int, Ge(0)]

# Spend attributed to producing a claim, in cents. Never negative. ``Decimal`` (not float) so
# the DB ``numeric`` contract holds and budget sums (M7 hard caps) are exact, not float-rounded.
CostCents = Annotated[Decimal, Ge(0)]

# A 0..1 weight or score component.
UnitInterval = Annotated[float, Ge(0.0), Le(1.0)]

# Timestamps are timezone-aware (stored as UTC ``timestamptz`` per substrate §12; the
# DB layer M0.3 owns UTC coercion). A naive datetime is rejected at validation time.
UtcDatetime = AwareDatetime
