"""Authorize ephemeral scene preferences on the platform loop from a design worker thread.

The closure holds only a frozen envelope. Every model call rechecks platform authority and
resolves the original selection through the shared memory seam; no memory body is cached.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from sqlalchemy import text

from clue_api.agent_turn_scope_pin import get_agent_turn_scope_pin
from clue_api.agent_turn_wiring import is_agent_turn_privacy_tombstoned
from clue_api.design_loop_bridge import PlatformLoopBridge
from clue_api.design_memory import (
    DESIGN_MEMORY_RECEIPT_POLICY,
    DESIGN_MEMORY_RECIPE,
    design_memory_payload_hash,
)
from clue_config import Settings
from clue_core import (
    AssemblyRequest,
    ContextAssembly,
    MemoryBundle,
    MemorySelectionPin,
    MemorySelectionStale,
    MemorySelectionUnavailable,
    MemoryType,
    ScopeStack,
)
from clue_db import ConnFactory, transaction
from clue_design.brand import get_brand_kit
from clue_design.envelopes import DesignTurnEnvelope
from clue_design.sessions import design_session_id

type PreferenceResult = MemoryBundle | MemorySelectionStale | MemorySelectionUnavailable
type PreferenceResolver = Callable[[], PreferenceResult]
type PreferenceResolverFactory = Callable[[DesignTurnEnvelope], PreferenceResolver | None]
_T = TypeVar("_T")


class DesignMemoryRuntimeError(RuntimeError):
    """A body-free failure to authorize or reach the platform memory read seam."""


def _bridge_error(code: str) -> DesignMemoryRuntimeError:
    """This surface's spelling of a shared bridge code, so the four names never moved."""

    return DesignMemoryRuntimeError(f"design_memory_{code}")


def build_configured_design_preference_resolver_factory(
    *, settings: Settings, memory: ContextAssembly, conn_factory: ConnFactory = transaction
) -> PreferenceResolverFactory | None:
    """Stage production context until output-history erasure and preference writes are validated."""
    if not settings.design_runtime_enabled or not settings.design_preference_context_enabled:
        return None
    return build_design_preference_resolver_factory(memory=memory, conn_factory=conn_factory)


async def _authorize(
    envelope: DesignTurnEnvelope, conn_factory: ConnFactory
) -> tuple[AssemblyRequest, MemorySelectionPin | MemorySelectionUnavailable]:
    async with conn_factory() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT r.payload, r.work_id, r.checkpoint_thread_id, r.document_id, "
                        "r.execution_id, r.leg_id, r.status, r.cancel_requested_at, "
                        "t.id AS turn_id, t.project_id, t.thread_id, t.role, "
                        "t.parent_execution_id AS turn_parent, e.project_id AS execution_project, "
                        "e.parent_execution_id AS execution_parent, "
                        "l.parent_execution_id AS leg_parent, l.thread_id AS leg_thread, "
                        "l.brand_kit_id, l.brand_kit_version "
                        "FROM design_agent_run r "
                        "JOIN agent_turn t ON t.execution_id=r.execution_id "
                        "AND t.workspace_id=r.workspace_id "
                        "JOIN execution e ON e.id=r.execution_id "
                        "AND e.workspace_id=r.workspace_id "
                        "JOIN design_leg l ON l.id=r.leg_id AND l.workspace_id=r.workspace_id "
                        "WHERE r.run_id=:run AND r.workspace_id=:workspace"
                    ),
                    {"run": envelope.run_id, "workspace": envelope.workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["payload"] != envelope.model_dump(mode="json"):
            raise DesignMemoryRuntimeError("design_memory_stored_authority_mismatch")
        box, leg = envelope.config["design_memory"], envelope.config["leg"]
        if (
            row["status"] not in {"queued", "running"}
            or row["cancel_requested_at"] is not None
            or row["role"] != "design"
            or str(row["work_id"]) != str(envelope.work_id)
            or row["checkpoint_thread_id"] != envelope.checkpoint_thread_id
            # Session continuity (2026-09-18): a document-pinned leg turn's checkpoint thread
            # is the DOCUMENT's session, not this run — and that naming is the turn's own
            # authority, derived here from the envelope's own workspace and document rather
            # than trusted from it. A document-less turn keeps the D5 run-as-thread.
            or envelope.checkpoint_thread_id
            not in {
                envelope.run_id,
                design_session_id(envelope.workspace_id, str(envelope.document_id or "")),
            }
            or row["document_id"] != envelope.document_id
            or box["version"] != 1
            or box["turn_id"] != str(row["turn_id"])
            or box["execution_id"] != str(row["execution_id"])
            or leg["agent_turn_id"] != str(row["turn_id"])
            or leg["execution_id"] != str(row["execution_id"])
            or leg["leg_id"] != str(row["leg_id"])
            or leg["thread_id"] != row["thread_id"]
            or row["thread_id"] != row["leg_thread"]
            or row["project_id"] != row["execution_project"]
            or row["execution_parent"] != row["leg_parent"]
            or row["turn_parent"] != row["leg_parent"]
            or leg["brand_kit_id"] != row["brand_kit_id"]
            or leg["brand_kit_version"] != row["brand_kit_version"]
        ):
            raise DesignMemoryRuntimeError("design_memory_turn_authority_mismatch")
        if await is_agent_turn_privacy_tombstoned(
            conn, workspace_id=envelope.workspace_id, turn_id=row["turn_id"]
        ):
            raise DesignMemoryRuntimeError("design_memory_privacy_tombstoned")
        scope = await get_agent_turn_scope_pin(
            conn, workspace_id=envelope.workspace_id, turn_id=row["turn_id"]
        )
        if scope is None or scope.project_id != row["project_id"]:
            raise DesignMemoryRuntimeError("design_memory_scope_unavailable")
        request = AssemblyRequest(
            scope_stack=ScopeStack(
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                product_id=scope.product_id,
                project_id=scope.project_id,
            ),
            recipe=DESIGN_MEMORY_RECIPE,
            requested_types=(MemoryType.PREFERENCE,),
        )
        if AssemblyRequest.model_validate(box["request"]) != request:
            raise DesignMemoryRuntimeError("design_memory_scope_mismatch")
        kit = await get_brand_kit(
            conn,
            workspace_id=scope.workspace_id,
            brand_kit_id=row["brand_kit_id"],
            version=row["brand_kit_version"],
        )
        if kit.get("brand_id") != scope.brand_id:
            raise DesignMemoryRuntimeError("design_memory_kit_mismatch")
        selected = box["selection"]
        if selected.get("status") == "unavailable":
            return request, MemorySelectionUnavailable.model_validate(selected)
        pin = MemorySelectionPin.model_validate(selected)
        if pin.request != request:
            raise DesignMemoryRuntimeError("design_memory_selection_scope_mismatch")
        # A queued takeover must not read before the producer's conservative erasure
        # dependencies have committed. Its retry can reconstruct that body-free receipt.
        receipt = await conn.execute(
            text(
                "SELECT 1 FROM agent_context_bundle WHERE workspace_id=:workspace "
                "AND turn_id=:turn AND execution_id=:execution AND policy_version=:policy "
                "AND aggregate_sha256=:digest"
            ),
            {
                "workspace": scope.workspace_id,
                "turn": row["turn_id"],
                "execution": row["execution_id"],
                "policy": DESIGN_MEMORY_RECEIPT_POLICY,
                "digest": design_memory_payload_hash(box),
            },
        )
        if receipt.first() is None:
            raise DesignMemoryRuntimeError("design_memory_dependencies_unavailable")
        return request, pin


def build_design_preference_resolver_factory(
    *,
    memory: ContextAssembly,
    conn_factory: ConnFactory = transaction,
    loop: asyncio.AbstractEventLoop | None = None,
    timeout_s: float = 10.0,
) -> PreferenceResolverFactory:
    """Capture the pool-owning loop; block only the design worker, with a bounded wait."""
    # The three bridge codes keep this surface's own spelling, so nothing a caller matches on
    # moves: ``platform_loop`` → ``design_memory_platform_loop``, and so on.
    bridge = PlatformLoopBridge(loop=loop, timeout_s=timeout_s, error=_bridge_error)

    def wait(operation: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
        try:
            return bridge.wait(operation)
        except DesignMemoryRuntimeError:
            raise
        except Exception:
            # Pydantic/DB/provider-like adapters may put inputs into exception strings.
            raise DesignMemoryRuntimeError("design_memory_authorization_unavailable") from None

    def factory(envelope: DesignTurnEnvelope) -> PreferenceResolver | None:
        if envelope.kind != "agent_turn" or "design_memory" not in envelope.config:
            return None
        frozen = DesignTurnEnvelope.model_validate(envelope.model_dump(mode="json"))
        _, selected = wait(lambda: _authorize(frozen, conn_factory))
        if isinstance(selected, MemorySelectionUnavailable):
            return None

        async def resolve() -> PreferenceResult:
            request, pin = await _authorize(frozen, conn_factory)
            if isinstance(pin, MemorySelectionUnavailable):
                return pin
            result = await memory.resolve(request, pin)
            # Erasure/fencing may commit while the shared seam is reading. Do not release
            # a resolved body until that in-flight read has passed a fresh authority check.
            await _authorize(frozen, conn_factory)
            return result

        return lambda: wait(resolve)

    return factory
