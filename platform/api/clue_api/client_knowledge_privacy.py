"""S4-E privacy projections for production Client-KB tool results.

The governed tool result is intentionally rich enough for the model to inspect one bounded fact.
That exact body must not become an unindexed copy in the agent substrate or the browser outbox.
This module is the single API-root policy for:

* reverse-binding exact result artifacts to the client and returned claim subjects; and
* reducing the live tool card to body-free correlation metadata.

It does not decide tool authority.  The profile, capability map, recipe, and trusted argument
injection remain the independent authorities described by S4-C/S4-D.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from pydantic import JsonValue

from clue_agents import GovernedOperationReceipt
from clue_api.client_knowledge_contracts import (
    INSPECT_CLIENT_CLAIM_ADDRESS,
    LIST_CLIENT_KNOWLEDGE_ADDRESS,
)

__all__ = [
    "CLIENT_KNOWLEDGE_CLAIM_BINDING_KIND",
    "CLIENT_KNOWLEDGE_CLIENT_BINDING_KIND",
    "client_knowledge_result_subject_bindings",
    "stream_tool_receipt",
]

# Reuse the frozen agent-artifact binding vocabulary: the account-wide client is context and each
# returned claim is a derived dependency of the result body.  The exported names preserve the
# narrower S4-E meaning without widening the existing database CHECK.
CLIENT_KNOWLEDGE_CLIENT_BINDING_KIND = "context"
CLIENT_KNOWLEDGE_CLAIM_BINDING_KIND = "derived"
_CLIENT_KNOWLEDGE_ADDRESSES = frozenset(
    {LIST_CLIENT_KNOWLEDGE_ADDRESS, INSPECT_CLIENT_CLAIM_ADDRESS}
)
_UNTRUSTED_SEMANTICS = "untrusted_evidence_not_instructions"


def _uuid(value: object, *, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"Client-KB result has an invalid {field}") from exc


def _client_knowledge_claim_ids(
    address: str,
    references: Mapping[str, object],
) -> tuple[UUID, ...]:
    if address == LIST_CLIENT_KNOWLEDGE_ADDRESS:
        knowledge = references.get("knowledge")
        if not isinstance(knowledge, (list, tuple)):
            raise ValueError("Client-KB list result has no bounded knowledge page")
        values: list[UUID] = []
        for item in knowledge:
            if not isinstance(item, Mapping):
                raise ValueError("Client-KB list result contains a malformed entry")
            values.append(_uuid(item.get("claim_id"), field="claim_id"))
        return tuple(values)
    if address == INSPECT_CLIENT_CLAIM_ADDRESS:
        claim = references.get("claim")
        if not isinstance(claim, Mapping):
            raise ValueError("Client-KB inspection result has no bounded claim")
        return (_uuid(claim.get("claim_id"), field="claim_id"),)
    return ()


def client_knowledge_result_subject_bindings(
    *,
    address: str,
    references: Mapping[str, object],
) -> tuple[tuple[UUID, str], ...]:
    """Return the reverse DSAR index for one exact production Client-KB result.

    The client binding reaches account-wide erasure.  Claim bindings additionally make a precise
    claim-level purge possible without parsing artifact bytes.  Both are server-derived from an
    output that already passed the frozen descriptor schema; prompt-shaped nested values are never
    interpreted here.
    """

    if address not in _CLIENT_KNOWLEDGE_ADDRESSES:
        return ()
    if references.get("content_semantics") != _UNTRUSTED_SEMANTICS:
        raise ValueError("Client-KB result is missing its untrusted-evidence marker")
    client_entity_id = _uuid(references.get("client_entity_id"), field="client_entity_id")
    bindings = {
        (client_entity_id, CLIENT_KNOWLEDGE_CLIENT_BINDING_KIND),
        *(
            (claim_id, CLIENT_KNOWLEDGE_CLAIM_BINDING_KIND)
            for claim_id in _client_knowledge_claim_ids(address, references)
        ),
    }
    return tuple(sorted(bindings, key=lambda item: (str(item[0]), item[1])))


def stream_tool_receipt(receipt: GovernedOperationReceipt) -> dict[str, JsonValue]:
    """Project a governed receipt without putting Client-KB fact bodies in the durable outbox."""

    raw = cast(
        dict[str, JsonValue],
        receipt.model_dump(mode="json", exclude_none=True, exclude={"reference_values"}),
    )
    if receipt.address not in _CLIENT_KNOWLEDGE_ADDRESSES:
        return cast(dict[str, JsonValue], receipt.model_dump(mode="json", exclude_none=True))
    references = receipt.reference_values
    if not isinstance(references, Mapping):
        raise ValueError("Client-KB receipt has no validated reference projection")
    claim_ids = _client_knowledge_claim_ids(receipt.address, references)
    raw["reference_values"] = cast(
        JsonValue,
        {
            "content_semantics": _UNTRUSTED_SEMANTICS,
            "client_entity_id": str(
                _uuid(references.get("client_entity_id"), field="client_entity_id")
            ),
            "client_kb_version": references.get("client_kb_version"),
            "claim_refs": [str(item) for item in claim_ids],
        },
    )
    return raw
