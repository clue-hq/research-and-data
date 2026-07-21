"""The read seam — deterministic, inject-only context assembly (Doc M §10–§11).

Consumers never query memory storage; a recipe execution asks for context, this engine produces
the bundle: gate (deterministic filter) → rank (one lexicographic sort under bundle budgets) →
assemble (stability order — cache semantics, ZERO priority semantics; labels carry all meaning)
→ label everything → journal.

The journal is contractual (REQ-12): **ids + label metadata + what was excluded and why — never
bodies** (structurally: the journal table has no content column). Same store state + same
request ⇒ byte-identical bundle; the journal's ``bundle_hash`` witnesses it.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import MemoryCaps, Settings
from clue_core import (
    AssemblyRequest,
    MemoryBundle,
    MemoryBundleEntry,
    MemoryScopeType,
    MemoryStatus,
)
from clue_memory import _store
from clue_memory.lifecycle import losing_comparison, rank_key
from clue_memory.model import Memory
from clue_memory.switch import is_memory_enabled

#: Assembly order over scopes — the stable prefix first (brand changes least). Doc M §10.3:
#: this order is CACHE semantics; no future implementer may read priority into position.
_STABILITY_ORDER = (
    MemoryScopeType.WORKSPACE,
    MemoryScopeType.BRAND,
    MemoryScopeType.PRODUCT,
    MemoryScopeType.PROJECT,
)


class Assembly:
    """The one :class:`~clue_core.ContextAssembly` implementation."""

    def __init__(self, conn: AsyncConnection, *, settings: Settings, caps: MemoryCaps) -> None:
        self._conn = conn
        self._settings = settings
        self._caps = caps

    async def assemble(self, request: AssemblyRequest) -> MemoryBundle | None:
        conn = self._conn
        stack = request.scope_stack

        # No memory step at all (None, not an empty bundle): the recipe declared no types —
        # research unbiased by preference is a feature — or the kill-switch is off (the switch
        # audit is the record; assembly writes nothing).
        if not request.requested_types:
            return None
        if not await is_memory_enabled(conn, stack.workspace_id, self._settings):
            return None

        scopes: list[tuple[MemoryScopeType, str]] = [
            (MemoryScopeType.WORKSPACE, stack.workspace_id),
            (MemoryScopeType.BRAND, stack.brand_id),
        ]
        if stack.product_id is not None:
            scopes.append((MemoryScopeType.PRODUCT, stack.product_id))
        if stack.project_id is not None:
            scopes.append((MemoryScopeType.PROJECT, stack.project_id))

        included: list[Memory] = []
        excluded: list[tuple[Memory, str]] = []  # (record, losing comparison)
        for scope_type, scope_id in sorted(scopes, key=lambda s: _STABILITY_ORDER.index(s[0])):
            records = await _store.list_records(
                conn,
                workspace_id=stack.workspace_id,
                statuses=(MemoryStatus.ACTIVE,),  # the gate: active only, tenant-filtered
                scope_type=scope_type,
                scope_id=scope_id,
                types=request.requested_types,
            )
            ranked = sorted(records, key=rank_key)
            budget = self._caps.bundle_budget_for(scope_type.value)
            included.extend(ranked[:budget])
            # Budget exclusion is NOT dormancy: the record stays active, merely lost today's
            # ranking — journaled with the losing comparison (Doc M §14).
            last_winner = ranked[:budget][-1] if ranked[:budget] else None
            for record in ranked[budget:]:
                assert last_winner is not None
                excluded.append(
                    (record, f"bundle budget {budget}: " + losing_comparison(record, last_winner))
                )

        bundle = MemoryBundle(
            workspace_id=stack.workspace_id,
            recipe=request.recipe,
            entries=tuple(
                MemoryBundleEntry(memory_id=m.memory_id, body=m.body, label=m.to_label())
                for m in included
            ),
        )
        journal_id = await self._journal(request, bundle, included, excluded)
        return bundle.model_copy(update={"journal_id": journal_id})

    async def _journal(
        self,
        request: AssemblyRequest,
        bundle: MemoryBundle,
        included: list[Memory],
        excluded: list[tuple[Memory, str]],
    ) -> str:
        """Ids + label metadata + exclusions + the determinism hash — never bodies."""
        stack = request.scope_stack
        included_meta = [
            {
                "memory_id": m.memory_id,
                "scope_type": m.scope_type.value,
                "scope_id": m.scope_id,
                "type": m.type.value,
                "provenance_class": m.provenance_class.value,
                "trust_grade": m.trust_grade,
                "cycles_since_confirmed": m.cycles_since_confirmed,
                "confirmation_count": m.confirmation_count,
                "claim_ref_count": len(m.claim_refs),
            }
            for m in included
        ]
        excluded_meta = [
            {"memory_id": m.memory_id, "losing_comparison": why} for m, why in excluded
        ]
        # Cross-branch tension (Doc M §10): sibling-scope (product × project) entries of the
        # same type are included-and-labeled, never arbitrated; the journaled pairs are the
        # empirical evidence a future type→scope validity matrix is designed from (§17).
        by_branch: dict[MemoryScopeType, list[Memory]] = {}
        for m in included:
            by_branch.setdefault(m.scope_type, []).append(m)
        pairs = [
            {"a": a.memory_id, "b": b.memory_id, "type": a.type.value}
            for a in by_branch.get(MemoryScopeType.PRODUCT, ())
            for b in by_branch.get(MemoryScopeType.PROJECT, ())
            if a.type == b.type
        ]
        return await _store.insert_bundle_journal(
            self._conn,
            workspace_id=stack.workspace_id,
            recipe=request.recipe,
            requested_types=json.dumps([t.value for t in request.requested_types]),
            scope_stack=json.dumps(
                {
                    "workspace_id": stack.workspace_id,
                    "brand_id": stack.brand_id,
                    "product_id": stack.product_id,
                    "project_id": stack.project_id,
                }
            ),
            included=json.dumps(included_meta),
            excluded=json.dumps(excluded_meta),
            cross_branch_pairs=json.dumps(pairs),
            bundle_hash=bundle.bundle_hash(),
        )
