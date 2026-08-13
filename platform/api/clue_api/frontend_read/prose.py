"""Typed FI-2 reads for Lane-E account/contact prose claims.

Lane E owns synthesis and writes ``account.summary`` / ``contact.overview`` into the claim store.
FI-2 owns the Accounts wire, so it projects those current claims into one small state machine rather
than leaving the frontend to infer synthesis completion from unrelated facts or research status.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.accounts_list import WireModel
from clue_core import Claim, EntityId
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    claims_for_entities,
    current_value,
)

ACCOUNT_SUMMARY_FIELD = "account.summary"
CONTACT_OVERVIEW_FIELD = "contact.overview"


class ProseState(StrEnum):
    AVAILABLE = "available"
    NOT_COMPOSED = "not_composed"
    RESTRICTED = "restricted"


class ProseResearchOutcome(StrEnum):
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"


class ProseRead(WireModel):
    """A prose value, an honest absence, or a value the read layer cannot display."""

    state: ProseState
    paragraphs: tuple[str, ...] = ()
    research_outcome: ProseResearchOutcome | None = None


class ProseContractError(ValueError):
    """A current prose claim violates the registered Lane-E value contract."""


def _available(value: object) -> ProseRead:
    if not isinstance(value, dict):
        raise ProseContractError("current prose value must be an object")
    raw_paragraphs = value.get("paragraphs")
    if not isinstance(raw_paragraphs, list) or not raw_paragraphs:
        raise ProseContractError("current prose value must contain paragraphs")
    if any(not isinstance(item, str) or not item.strip() for item in raw_paragraphs):
        raise ProseContractError("current prose paragraphs must be non-empty strings")
    raw_outcome = value.get("research_outcome")
    if not isinstance(raw_outcome, str):
        raise ProseContractError("current prose value has an invalid research outcome")
    try:
        outcome = ProseResearchOutcome(raw_outcome)
    except ValueError as exc:
        raise ProseContractError("current prose value has an invalid research outcome") from exc
    return ProseRead(
        state=ProseState.AVAILABLE,
        paragraphs=tuple(raw_paragraphs),
        research_outcome=outcome,
    )


async def read_prose(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    field_key: str,
    scope: WorkspaceScope,
    display_allowed: Callable[[Claim], bool] | None = None,
) -> ProseRead:
    """Read one current prose claim without leaking a withheld/unpromotable value.

    A live raw claim with no displayable current truth is ``restricted``: the platform holds a
    synthesis record, but this read is not permitted to serve it. No live claim is
    ``not_composed``. The distinction prevents a rejected, weakly-bound, or policy-denied claim
    from being mislabeled as research that never happened.
    """

    raw_claims = await claims_for_entities(
        conn,
        [entity_id],
        [field_key],
        scope=scope,
    )
    merged = await current_value(conn, entity_id, field_key, scope=scope)
    if merged is None:
        return ProseRead(state=ProseState.RESTRICTED if raw_claims else ProseState.NOT_COMPOSED)

    winner = (await claims_by_ids(conn, [merged.provenance.claim_id], scope=scope)).get(
        merged.provenance.claim_id
    )
    if winner is None or (display_allowed is not None and not display_allowed(winner)):
        return ProseRead(state=ProseState.RESTRICTED)
    return _available(merged.value_json)


__all__ = [
    "ACCOUNT_SUMMARY_FIELD",
    "CONTACT_OVERVIEW_FIELD",
    "ProseContractError",
    "ProseRead",
    "ProseResearchOutcome",
    "ProseState",
    "read_prose",
]
