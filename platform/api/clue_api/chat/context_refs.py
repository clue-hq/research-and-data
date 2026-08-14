"""Production-safe, body-free read of one turn's exact context receipt."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from clue_projections import TurnContextReceiptView

__all__ = [
    "TurnContextRefsResponse",
    "TurnContextRefsWire",
    "context_refs_response",
]


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ContextRefWire(_Wire):
    disposition: str
    ordinal: int
    ref_kind: str
    artifact_key: str | None
    artifact_sha256: str | None
    object_type: str | None
    object_id: str | None
    object_version: int | None
    content_sha256: str | None
    materialized_path: str | None
    token_count: int | None
    exclusion_reason_code: str | None


class ContextLayerRefsWire(_Wire):
    ordinal: int
    layer: str
    token_budget: int
    token_count: int
    included_count: int
    excluded_count: int
    refs: tuple[ContextRefWire, ...]


class TurnContextRefsWire(_Wire):
    turn_id: str
    state: Literal["pending", "available"]
    context_bundle_id: str | None = None
    schema_version: str | None = None
    policy_version: str | None = None
    token_counter_version: str | None = None
    aggregate_sha256: str | None = None
    assembled_at: str | None = None
    layers: tuple[ContextLayerRefsWire, ...] = ()


class TurnContextRefsResponse(_Wire):
    data: TurnContextRefsWire


def context_refs_response(
    *,
    turn_id: str,
    receipt: TurnContextReceiptView | None,
) -> TurnContextRefsResponse:
    if receipt is None:
        return TurnContextRefsResponse(data=TurnContextRefsWire(turn_id=turn_id, state="pending"))
    return TurnContextRefsResponse(
        data=TurnContextRefsWire(
            turn_id=turn_id,
            state="available",
            context_bundle_id=str(receipt.context_bundle_id),
            schema_version=receipt.schema_version,
            policy_version=receipt.policy_version,
            token_counter_version=receipt.token_counter_version,
            aggregate_sha256=receipt.aggregate_sha256,
            assembled_at=receipt.assembled_at.isoformat(),
            layers=tuple(
                ContextLayerRefsWire(
                    ordinal=layer.ordinal,
                    layer=layer.layer,
                    token_budget=layer.token_budget,
                    token_count=layer.token_count,
                    included_count=layer.included_count,
                    excluded_count=layer.excluded_count,
                    refs=tuple(
                        ContextRefWire(
                            disposition=ref.disposition,
                            ordinal=ref.ordinal,
                            ref_kind=ref.ref_kind,
                            artifact_key=ref.artifact_key,
                            artifact_sha256=ref.artifact_sha256,
                            object_type=ref.object_type,
                            object_id=ref.object_id,
                            object_version=ref.object_version,
                            content_sha256=ref.content_sha256,
                            materialized_path=ref.materialized_path,
                            token_count=ref.token_count,
                            exclusion_reason_code=ref.exclusion_reason_code,
                        )
                        for ref in layer.refs
                    ),
                )
                for layer in receipt.layers
            ),
        )
    )
