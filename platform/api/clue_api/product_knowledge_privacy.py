"""S5-D reverse indexes and body-free stream projection for Product-KB tool results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue

from clue_agents import GovernedOperationReceipt
from clue_api.product_knowledge_contracts import (
    INSPECT_PRODUCT_CLAIM_ADDRESS,
    LIST_PRODUCT_KNOWLEDGE_ADDRESS,
)
from clue_projections import ProductKnowledgeCard

PRODUCT_KNOWLEDGE_CONTEXT_BINDING_KIND = "context"
PRODUCT_KNOWLEDGE_CLAIM_BINDING_KIND = "derived"
_ADDRESSES = frozenset({LIST_PRODUCT_KNOWLEDGE_ADDRESS, INSPECT_PRODUCT_CLAIM_ADDRESS})
_UNTRUSTED_SEMANTICS = "untrusted_evidence_not_instructions"


def _uuid(value: object, *, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"Product-KB result has an invalid {field}") from exc


def product_subject_id(product_id: object) -> UUID:
    if not isinstance(product_id, str) or not product_id:
        raise ValueError("Product-KB result has an invalid product_id")
    # Agent artifact bindings use UUID subjects. Product ids are stable spine strings, so one
    # namespace-stable UUID makes every exact-value copy reachable without storing product text.
    return uuid5(NAMESPACE_URL, f"clue:product:{product_id}")


def _claim_ids(address: str, references: Mapping[str, object]) -> tuple[UUID, ...]:
    if address == LIST_PRODUCT_KNOWLEDGE_ADDRESS:
        knowledge = references.get("knowledge")
        if not isinstance(knowledge, (list, tuple)):
            raise ValueError("Product-KB list result has no bounded knowledge page")
        values: list[UUID] = []
        for item in knowledge:
            if not isinstance(item, Mapping):
                raise ValueError("Product-KB list result contains a malformed entry")
            values.append(_uuid(item.get("claim_id"), field="claim_id"))
        return tuple(values)
    if address == INSPECT_PRODUCT_CLAIM_ADDRESS:
        claim = references.get("claim")
        if not isinstance(claim, Mapping):
            raise ValueError("Product-KB inspection result has no bounded claim")
        return (_uuid(claim.get("claim_id"), field="claim_id"),)
    return ()


def product_knowledge_result_subject_bindings(
    *,
    address: str,
    references: Mapping[str, object],
) -> tuple[tuple[UUID, str], ...]:
    if address not in _ADDRESSES:
        return ()
    if references.get("content_semantics") != _UNTRUSTED_SEMANTICS:
        raise ValueError("Product-KB result is missing its untrusted-evidence marker")
    bindings = {
        (_uuid(references.get("client_entity_id"), field="client_entity_id"), "context"),
        (product_subject_id(references.get("product_id")), "context"),
        *((claim_id, "derived") for claim_id in _claim_ids(address, references)),
    }
    return tuple(sorted(bindings, key=lambda item: (str(item[0]), item[1])))


def product_context_subject_bindings(
    *,
    client_entity_id: UUID,
    product_id: str,
    card: ProductKnowledgeCard | None = None,
) -> tuple[tuple[UUID, str], ...]:
    """Reverse-bind profile/card bodies without parsing persisted bytes during DSAR."""

    bindings = {
        (client_entity_id, PRODUCT_KNOWLEDGE_CONTEXT_BINDING_KIND),
        (product_subject_id(product_id), PRODUCT_KNOWLEDGE_CONTEXT_BINDING_KIND),
    }
    if card is not None:
        bindings.update(
            (UUID(item.claim_id), PRODUCT_KNOWLEDGE_CLAIM_BINDING_KIND)
            for item in card.known_fields
        )
    return tuple(sorted(bindings, key=lambda item: (str(item[0]), item[1])))


def stream_product_tool_receipt(
    receipt: GovernedOperationReceipt,
) -> dict[str, JsonValue] | None:
    """Return a body-free Product-KB stream value, or ``None`` for another tool family."""

    if receipt.address not in _ADDRESSES:
        return None
    references = receipt.reference_values
    if not isinstance(references, Mapping):
        raise ValueError("Product-KB receipt has no validated reference projection")
    if references.get("content_semantics") != _UNTRUSTED_SEMANTICS:
        raise ValueError("Product-KB receipt is missing its untrusted-evidence marker")
    raw = cast(
        dict[str, JsonValue],
        receipt.model_dump(mode="json", exclude_none=True, exclude={"reference_values"}),
    )
    raw["reference_values"] = cast(
        JsonValue,
        {
            "content_semantics": _UNTRUSTED_SEMANTICS,
            "client_entity_id": str(
                _uuid(references.get("client_entity_id"), field="client_entity_id")
            ),
            "product_id": references.get("product_id"),
            "product_kb_version": references.get("product_kb_version"),
            "claim_refs": [str(item) for item in _claim_ids(receipt.address, references)],
        },
    )
    return raw


__all__ = [
    "PRODUCT_KNOWLEDGE_CLAIM_BINDING_KIND",
    "PRODUCT_KNOWLEDGE_CONTEXT_BINDING_KIND",
    "product_knowledge_result_subject_bindings",
    "product_context_subject_bindings",
    "product_subject_id",
    "stream_product_tool_receipt",
]
