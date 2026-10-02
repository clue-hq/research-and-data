"""Body-free scene preference selection and conservative platform privacy dependencies.

This producer never resolves memory bodies. The runtime consumer separately checks the frozen
selection at its model boundary. Selection dependencies are intentionally conservative: they
can require erasure even when a runtime failed before using the selected advice.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid5

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentTurnRequest,
    ContextAssemblyReceipt,
    ContextBundleManifest,
    ContextLayer,
    ContextLayerManifest,
    ContextReceiptRef,
    DomainObjectRef,
    LayerBudget,
)
from clue_api.agent_turn_scope_pin import AgentTurnScopePinRow
from clue_core import (
    AssemblyRequest,
    ContextAssembly,
    MemorySelectionPin,
    MemorySelectionUnavailable,
    MemoryType,
    ScopeStack,
)
from clue_design.brand import get_brand_kit
from clue_design.errors import DesignNotFoundError

DESIGN_MEMORY_RECIPE = "scene-preferences-v1"
DESIGN_MEMORY_RECEIPT_POLICY = "design-memory-selection-v1"


class DesignMemoryScopeError(ValueError):
    """No coherent canonical brand can authorize this scene's preference selection."""


def design_memory_payload_hash(payload: dict[str, Any]) -> str:
    """Bind the conservative dependency receipt to the exact body-free envelope slot."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


async def freeze_design_memory(
    conn: AsyncConnection,
    *,
    memory: ContextAssembly,
    scope_pin: AgentTurnScopePinRow,
    turn_request: AgentTurnRequest,
    leg: dict[str, Any],
) -> dict[str, Any]:
    kit_id, kit_version = leg.get("brand_kit_id"), leg.get("brand_kit_version")
    if kit_id is None or kit_version is None:
        raise DesignMemoryScopeError("scene preferences require a pinned canonical brand kit")
    try:
        kit = await get_brand_kit(
            conn,
            workspace_id=scope_pin.workspace_id,
            brand_kit_id=str(kit_id),
            version=int(kit_version),
        )
    except DesignNotFoundError as exc:
        raise DesignMemoryScopeError(
            "the pinned brand kit is unavailable in this workspace"
        ) from exc
    if kit.get("brand_id") != scope_pin.brand_id:
        raise DesignMemoryScopeError(
            "the pinned brand kit does not match the trusted project brand"
        )
    request = AssemblyRequest(
        scope_stack=ScopeStack(
            workspace_id=scope_pin.workspace_id,
            brand_id=scope_pin.brand_id,
            product_id=scope_pin.product_id,
            project_id=scope_pin.project_id,
        ),
        recipe=DESIGN_MEMORY_RECIPE,
        requested_types=(MemoryType.PREFERENCE,),
    )
    selection = await memory.select(request)
    if isinstance(selection, MemorySelectionPin) and selection.request != request:
        raise DesignMemoryScopeError("the memory read seam returned a different selection scope")
    return {
        "version": 1,
        "turn_id": str(turn_request.turn_id),
        "execution_id": str(turn_request.constitution.execution_id),
        "request": request.model_dump(mode="json"),
        "selection": selection.model_dump(mode="json"),
    }


def selection_dependency_receipt(
    payload: dict[str, Any], *, request: AgentTurnRequest
) -> ContextAssemblyReceipt | None:
    """Use existing privacy indexes; do not claim a complete seven-layer runtime context.

    The seven required containers hold only body-free dependency descriptors in L4. Their
    hashes describe those descriptors, not resolved memory bodies, and rendered-body tokens
    are zero. The consumer owns the separate actual-consumption receipt.
    """
    constitution = request.constitution
    if constitution.brand_id is None:
        raise DesignMemoryScopeError("scene preference dependencies require a canonical brand")
    selection_request = AssemblyRequest.model_validate(payload["request"])
    if (
        payload["version"] != 1
        or payload["turn_id"] != str(request.turn_id)
        or payload["execution_id"] != str(constitution.execution_id)
        or selection_request.scope_stack
        != ScopeStack(
            workspace_id=constitution.workspace_id,
            brand_id=constitution.brand_id,
            product_id=constitution.product_id,
            project_id=constitution.project_id,
        )
        or selection_request.recipe != DESIGN_MEMORY_RECIPE
        or selection_request.requested_types != (MemoryType.PREFERENCE,)
    ):
        raise DesignMemoryScopeError("the frozen memory selection has different turn authority")
    selected = payload["selection"]
    if selected.get("status") == "unavailable":
        MemorySelectionUnavailable.model_validate(selected)
        return None  # memory-off is no step, not an empty context bundle
    pin = MemorySelectionPin.model_validate(selected)
    if pin.request != selection_request:
        raise DesignMemoryScopeError("the frozen memory pin and request disagree")
    refs = (
        DomainObjectRef(
            workspace_id=constitution.workspace_id,
            object_type="memory_bundle_journal",
            object_id=str(pin.journal_id),
            version=pin.version,
        ),
        *(
            DomainObjectRef(
                workspace_id=constitution.workspace_id,
                object_type="scoped_memory",
                object_id=memory_id,
                version=None,
            )
            for memory_id in pin.selected_ids
        ),
    )
    digests = tuple(hashlib.sha256(ref.model_dump_json().encode()).hexdigest() for ref in refs)
    return ContextAssemblyReceipt(
        manifest=ContextBundleManifest(
            context_bundle_id=uuid5(request.turn_id, DESIGN_MEMORY_RECEIPT_POLICY),
            execution_id=constitution.execution_id,
            schema_version="1",
            layers=tuple(
                ContextLayerManifest(
                    layer=layer,
                    source_refs=refs if layer == ContextLayer.L4_MEMORY else (),
                    content_sha256s=digests if layer == ContextLayer.L4_MEMORY else (),
                    token_count=0,
                )
                for layer in ContextLayer
            ),
            aggregate_sha256=design_memory_payload_hash(payload),
            assembled_at=request.requested_at,
        ),
        policy_version=DESIGN_MEMORY_RECEIPT_POLICY,
        token_counter_version="unrendered-selection-v1",
        budgets=tuple(LayerBudget(layer=layer, max_tokens=0) for layer in ContextLayer),
        refs=tuple(
            ContextReceiptRef(
                layer=ContextLayer.L4_MEMORY,
                disposition="included",
                ordinal=index,
                ref=ref,
                content_sha256=digest,
                token_count=0,
            )
            for index, (ref, digest) in enumerate(zip(refs, digests, strict=True))
        ),
    )
