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

import itertools
import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import MemoryCaps, Settings
from clue_core import (
    AssemblyRequest,
    MemoryBundle,
    MemoryBundleEntry,
    MemoryProvenanceClass,
    MemoryScopeType,
    MemorySelectionPin,
    MemorySelectionStale,
    MemorySelectionUnavailable,
    MemoryStatus,
)
from clue_memory import _store
from clue_memory.lifecycle import losing_comparison, rank_key
from clue_memory.model import Memory
from clue_memory.switch import is_memory_enabled

#: Assembly order over scopes — the stable prefix first (brand changes least), the least-stable
#: scope (account) last. Doc M §10.3: this order is CACHE semantics; no future implementer may
#: read priority into position.
_STABILITY_ORDER = (
    MemoryScopeType.WORKSPACE,
    MemoryScopeType.BRAND,
    MemoryScopeType.PRODUCT,
    MemoryScopeType.PROJECT,
    MemoryScopeType.ACCOUNT,
)

#: The sibling branch scopes (Doc M §4): a three-way branch over orthogonal axes. Cross-branch
#: tension among any two present at assembly is surfaced and journaled, never arbitrated (§10).
_BRANCH_SCOPES = (
    MemoryScopeType.PRODUCT,
    MemoryScopeType.PROJECT,
    MemoryScopeType.ACCOUNT,
)


class Assembly:
    """The one :class:`~clue_core.ContextAssembly` implementation."""

    def __init__(self, conn: AsyncConnection, *, settings: Settings, caps: MemoryCaps) -> None:
        self._conn = conn
        self._settings = settings
        self._caps = caps

    @staticmethod
    def _canonical_request(request: AssemblyRequest) -> AssemblyRequest:
        return request.model_copy(
            update={"requested_types": tuple(sorted(set(request.requested_types)))}
        )

    async def select(
        self, request: AssemblyRequest
    ) -> MemorySelectionPin | MemorySelectionUnavailable:
        request = self._canonical_request(request)
        bundle = await self.assemble(request)
        if bundle is None:
            return MemorySelectionUnavailable(
                reason="memory_disabled" if request.requested_types else "no_requested_types"
            )
        assert bundle.journal_id is not None
        return MemorySelectionPin(
            request=request,
            journal_id=UUID(bundle.journal_id),
            selected_ids=tuple(entry.memory_id for entry in bundle.entries),
            bundle_hash=bundle.bundle_hash(),
        )

    async def resolve(
        self, request: AssemblyRequest, pin: MemorySelectionPin
    ) -> MemoryBundle | MemorySelectionStale | MemorySelectionUnavailable:
        request = self._canonical_request(request)
        if request != pin.request:
            return MemorySelectionStale(reason="request_mismatch")
        journal = await _store.get_bundle_journal(self._conn, str(pin.journal_id))
        if journal is None:
            return MemorySelectionUnavailable(reason="journal_unavailable")
        # JSONB is decoded by the store driver. Compare every authority-bearing field before
        # reading any memory body; an editable pin is not a capability or a source of truth.
        if (
            journal["workspace_id"] != request.scope_stack.workspace_id
            or journal["recipe"] != request.recipe
            or journal["scope_stack"] != request.scope_stack.model_dump(mode="json")
            or journal["requested_types"] != [t.value for t in request.requested_types]
            or tuple(entry["memory_id"] for entry in journal["included"]) != pin.selected_ids
            or journal["bundle_hash"] != pin.bundle_hash
        ):
            return MemorySelectionStale(reason="journal_mismatch")
        if not request.requested_types:
            return MemorySelectionUnavailable(reason="no_requested_types")
        if not await is_memory_enabled(
            self._conn, request.scope_stack.workspace_id, self._settings
        ):
            return MemorySelectionUnavailable(reason="memory_disabled")
        records = await _store.get_selected_records(
            self._conn, workspace_id=request.scope_stack.workspace_id, memory_ids=pin.selected_ids
        )
        by_id = {record.memory_id: record for record in records}
        if len(by_id) != len(pin.selected_ids) or any(
            record.status != MemoryStatus.ACTIVE for record in records
        ):
            return MemorySelectionUnavailable(reason="selected_memory_unavailable")
        bundle = MemoryBundle(
            workspace_id=request.scope_stack.workspace_id,
            recipe=request.recipe,
            journal_id=str(pin.journal_id),
            entries=tuple(
                MemoryBundleEntry(memory_id=mid, body=by_id[mid].body, label=by_id[mid].to_label())
                for mid in pin.selected_ids
            ),
        )
        # The hash covers body, trigger, scope, type, provenance, trust, counters and claim refs.
        # Even a still-active changed record must not be served as the original selection.
        if bundle.bundle_hash() != pin.bundle_hash:
            return MemorySelectionStale(reason="bundle_changed")
        return bundle

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
        if stack.account_entity_id is not None:
            scopes.append((MemoryScopeType.ACCOUNT, str(stack.account_entity_id)))

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
        # Cross-branch tension (Doc M §10): sibling-scope entries of the same type are
        # included-and-labeled, never arbitrated. Product / project / account are a three-way
        # branch, so every unordered pair of present sibling branches is journaled ("a" from the
        # earlier branch in stability order) — the empirical evidence a future type→scope validity
        # matrix is designed from (§17).
        by_branch: dict[MemoryScopeType, list[Memory]] = {}
        for m in included:
            by_branch.setdefault(m.scope_type, []).append(m)
        pairs = [
            {"a": a.memory_id, "b": b.memory_id, "type": a.type.value}
            for earlier, later in itertools.combinations(_BRANCH_SCOPES, 2)
            for a in by_branch.get(earlier, ())
            for b in by_branch.get(later, ())
            if a.type == b.type
        ]
        return await _store.insert_bundle_journal(
            self._conn,
            workspace_id=stack.workspace_id,
            recipe=request.recipe,
            requested_types=json.dumps([t.value for t in request.requested_types]),
            scope_stack=stack.model_dump_json(),
            included=json.dumps(included_meta),
            excluded=json.dumps(excluded_meta),
            cross_branch_pairs=json.dumps(pairs),
            bundle_hash=bundle.bundle_hash(),
        )


# --- the human's own view of a scope's memory --------------------------------
#
# The assembly engine above serves *agents*; these two serve the surfaces where a human reads and
# edits their own notes. They live here — beside the read seam, inside the package — for the
# reason ``_store`` is private (Rule S1): a caller outside ``clue_memory`` may not query memory
# storage, so the package exports the one shape the caller actually needs instead.


async def list_project_memories(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> list[Memory]:
    """Active, user-stated project-scope memories, newest first — the project home's list.

    Deliberately narrower than the store's filter: the panel shows the notes a *human* stated
    (``user_stated``) and only those currently in force (``active``). An agent-observed record and
    a superseded one are real memories the agent still reasons over, but they are not this human's
    list of notes, and showing them here would invite a human to "delete" something they never
    wrote.
    """
    records = await _store.list_records(
        conn,
        workspace_id=workspace_id,
        statuses=(MemoryStatus.ACTIVE,),
        scope_type=MemoryScopeType.PROJECT,
        scope_id=project_id,
    )
    return sorted(
        (m for m in records if m.provenance_class is MemoryProvenanceClass.USER_STATED),
        key=lambda m: m.created_at,
        reverse=True,
    )


async def get_memory(conn: AsyncConnection, memory_id: str) -> Memory | None:
    """One record by id, or ``None`` — the read a writer does to render what it just submitted.

    Unscoped by design, exactly as the store's own read is: the caller already holds the id the
    write seam returned for its own tenant's submission. A surface that starts from a *user*-given
    id must check the workspace itself (:func:`clue_memory.retire` is the fail-closed example).
    """
    return await _store.get_memory(conn, memory_id)
