"""The write seam (Doc M §7–§9) — every writer submits here; no writer inserts rows.

The enforcement chain runs identically for every writer (kickoff interview, future distiller,
mid-run agents): kill-switch → scope shape → deterministic person-adjacency guards → born trust
→ reconciliation (pre-checks, then the judge) → persist + journal → store-cap enforcement.

Three distinct refusal shapes, deliberately not interchangeable (Doc M §7/§17a):

- :class:`~clue_core.MemoryDisabled` — quiet typed no-op; the user chose this state.
- :class:`~clue_core.MemoryRejected` — a well-formed proposal the species/body rules refuse.
- :class:`~clue_core.MemoryPreconditionFailed` — the proposal is *malformed* (raises).

Scope validity is the schema's job: a dangling or cross-workspace scope id dies as a raw
``IntegrityError`` from the composite FKs (spine style — deliberately not caught here).
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import MemoryCaps, Settings
from clue_core import (
    BORN_STATUS,
    BORN_TRUST,
    TRUST_MAX,
    TRUST_MIN,
    MemoryAccepted,
    MemoryDisabled,
    MemoryEventType,
    MemoryPreconditionFailed,
    MemoryRejected,
    MemoryScopeType,
    MemoryStatus,
    MemorySubmission,
    ReconcileJudge,
    ReconcileJudgment,
    ReconcileVerdictKind,
    SubmissionOutcome,
)
from clue_memory import _store
from clue_memory.lifecycle import backfill_slot, enforce_store_cap
from clue_memory.model import Memory
from clue_memory.reconcile import Disposition, decide, has_deterministic_match
from clue_memory.switch import is_memory_enabled

# Deterministic person-adjacency guards: verbatim contact data in a body is personal data the
# writer must have subject-bound (the semantic layer — the judge's body_ok — runs after).
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


class WriteSeam:
    """The one :class:`~clue_core.MemoryWriteSeam` implementation. Storage access and the
    judge are bound at construction; the seam is connection-free to its callers."""

    def __init__(
        self,
        conn: AsyncConnection,
        judge: ReconcileJudge,
        *,
        settings: Settings,
        caps: MemoryCaps,
    ) -> None:
        self._conn = conn
        self._judge = judge
        self._settings = settings
        self._caps = caps

    async def submit(self, submission: MemorySubmission) -> SubmissionOutcome:
        conn = self._conn

        # 1. Kill-switch — a quiet typed no-op, not an error (the user chose this state).
        if not await is_memory_enabled(conn, submission.workspace_id, self._settings):
            return MemoryDisabled()

        # 2. Scope shape (the id itself is validated by the schema's composite FKs on insert).
        _check_scope_shape(submission)

        # 3. Fail-closed subject binding (Doc M §16.1): person-adjacent content without a
        #    resolved subject is a malformed proposal.
        if submission.subject_entity_id is None and (
            _EMAIL.search(submission.body) or _PHONE.search(submission.body)
        ):
            raise MemoryPreconditionFailed(
                "person-adjacent content (verbatim contact data in the body) requires "
                "subject_entity_id — stamp the resolved contact entity or route the fact "
                "to the claim store"
            )

        # 4/6. Reconciliation over active ∪ dormant of the same (workspace, scope, type) —
        #      never active-only (the zombie-twin guard, Doc M §9).
        candidates = await _store.list_records(
            conn,
            workspace_id=submission.workspace_id,
            statuses=(MemoryStatus.ACTIVE, MemoryStatus.DORMANT),
            scope_type=submission.scope.scope_type,
            scope_id=_scope_instance_id(submission),
            type_=submission.type,
        )
        candidate_views = tuple(c.to_candidate() for c in candidates)
        judgment = (
            None
            if has_deterministic_match(submission, candidate_views)
            else await _judge_or_none(self._judge, submission, candidates)
        )
        decision = decide(submission, candidate_views, judgment)
        if isinstance(decision, MemoryRejected):
            return decision

        # 7. Execute the disposition + journal every transition + enforce the store cap.
        by_id = {c.memory_id: c for c in candidates}
        if decision.verdict is ReconcileVerdictKind.NOOP:
            target = by_id[decision.target_memory_id or ""]
            return await self._confirm(submission, target, decision)
        if decision.verdict in (ReconcileVerdictKind.UPDATE, ReconcileVerdictKind.SUPERSEDE):
            target = by_id[decision.target_memory_id or ""]
            return await self._supersede(submission, target, decision)
        return await self._add(submission, decision)

    # --- dispositions -------------------------------------------------------

    async def _add(self, submission: MemorySubmission, decision: Disposition) -> MemoryAccepted:
        born_status = (
            MemoryStatus.PROPOSED
            if decision.park_proposed
            else BORN_STATUS[submission.provenance_class]
        )
        memory = await self._insert_from(submission, born_status)
        await _store.insert_event(
            self._conn,
            memory_id=memory.memory_id,
            workspace_id=memory.workspace_id,
            event_type=MemoryEventType.CREATED,
            actor=submission.provenance_class.value,
            to_status=born_status,
            cause=decision.cause or None,
        )
        if born_status is MemoryStatus.ACTIVE:
            await self._enforce_cap(memory)
        return MemoryAccepted(
            verdict=ReconcileVerdictKind.ADD, memory_id=memory.memory_id, status=born_status
        )

    async def _confirm(
        self, submission: MemorySubmission, target: Memory, decision: Disposition
    ) -> MemoryAccepted:
        """NOOP restatement: counter up, freshness reset, trust raised; a dormant target
        REACTIVATES with its history intact — user re-statement is the strongest evidence the
        eviction was wrong (Doc M §9)."""
        conn = self._conn
        await _store.record_confirmation(
            conn, target.memory_id, trust_grade=min(TRUST_MAX, target.trust_grade + 1)
        )
        await _store.insert_event(
            conn,
            memory_id=target.memory_id,
            workspace_id=target.workspace_id,
            event_type=MemoryEventType.CONFIRMED,
            actor=submission.provenance_class.value,
            cause=decision.cause or None,
        )
        status = target.status
        if target.status is MemoryStatus.DORMANT:
            await _store.set_status(conn, target.memory_id, MemoryStatus.ACTIVE)
            await _store.insert_event(
                conn,
                memory_id=target.memory_id,
                workspace_id=target.workspace_id,
                event_type=MemoryEventType.REACTIVATED,
                actor=submission.provenance_class.value,
                from_status=MemoryStatus.DORMANT,
                to_status=MemoryStatus.ACTIVE,
                cause="restatement of a dormant record — promotion, not a zombie ADD",
            )
            status = MemoryStatus.ACTIVE
            await self._enforce_cap(target)
        return MemoryAccepted(
            verdict=ReconcileVerdictKind.NOOP, memory_id=target.memory_id, status=status
        )

    async def _supersede(
        self, submission: MemorySubmission, target: Memory, decision: Disposition
    ) -> MemoryAccepted:
        """UPDATE (refinement) / SUPERSEDE (contradiction): a successor row replaces the old
        record, trail preserved via the ``superseded_by`` link — never a silent delete."""
        conn = self._conn
        contradiction = decision.verdict is ReconcileVerdictKind.SUPERSEDE
        if contradiction:
            # Direct evidence against the old record (Doc M §12): trust down, journaled.
            await _store.set_trust(conn, target.memory_id, max(TRUST_MIN, target.trust_grade - 1))
            await _store.insert_event(
                conn,
                memory_id=target.memory_id,
                workspace_id=target.workspace_id,
                event_type=MemoryEventType.CONTRADICTED,
                actor=submission.provenance_class.value,
                cause=decision.cause or None,
            )
        born_status = BORN_STATUS[submission.provenance_class]
        successor = await self._insert_from(submission, born_status)
        await _store.set_status(
            conn, target.memory_id, MemoryStatus.SUPERSEDED, superseded_by=successor.memory_id
        )
        await _store.insert_event(
            conn,
            memory_id=target.memory_id,
            workspace_id=target.workspace_id,
            event_type=MemoryEventType.SUPERSEDED,
            actor=submission.provenance_class.value,
            from_status=target.status,
            to_status=MemoryStatus.SUPERSEDED,
            cause=f"superseded by {successor.memory_id}: {decision.cause}".strip(": "),
        )
        await _store.insert_event(
            conn,
            memory_id=successor.memory_id,
            workspace_id=successor.workspace_id,
            event_type=MemoryEventType.CREATED,
            actor=submission.provenance_class.value,
            to_status=born_status,
            cause=("contradicts " if contradiction else "refines ") + target.memory_id,
        )
        if born_status is MemoryStatus.ACTIVE:
            await self._enforce_cap(successor)
        elif target.status is MemoryStatus.ACTIVE:
            # The old record freed an active slot and the successor is only proposed.
            await backfill_slot(
                conn,
                workspace_id=target.workspace_id,
                scope_type=target.scope_type,
                scope_id=target.scope_id,
                caps=self._caps,
            )
        return MemoryAccepted(
            verdict=decision.verdict, memory_id=successor.memory_id, status=born_status
        )

    # --- helpers ------------------------------------------------------------

    async def _insert_from(self, submission: MemorySubmission, status: MemoryStatus) -> Memory:
        return await _store.insert_memory(
            self._conn,
            workspace_id=submission.workspace_id,
            scope_type=submission.scope.scope_type,
            scope_id=submission.scope.scope_id,
            type_=submission.type,
            trigger=submission.trigger,
            body=submission.body,
            provenance_class=submission.provenance_class.value,
            trust_grade=BORN_TRUST[submission.provenance_class],
            status=status,
            creating_quote=submission.creating_quote,
            subject_entity_id=submission.subject_entity_id,
            source_thread_id=submission.source_thread_id,
            claim_refs=submission.claim_refs,
        )

    async def _enforce_cap(self, memory: Memory) -> None:
        await enforce_store_cap(
            self._conn,
            workspace_id=memory.workspace_id,
            scope_type=memory.scope_type,
            scope_id=memory.scope_id,
            caps=self._caps,
        )


def _scope_instance_id(submission: MemorySubmission) -> str:
    """The canonical scope-instance key (== workspace_id for workspace scope)."""
    return (
        submission.workspace_id
        if submission.scope.scope_type is MemoryScopeType.WORKSPACE
        else submission.scope.scope_id or ""
    )


def _check_scope_shape(submission: MemorySubmission) -> None:
    scope = submission.scope
    if scope.scope_type is MemoryScopeType.WORKSPACE:
        if scope.scope_id not in (None, submission.workspace_id):
            raise MemoryPreconditionFailed(
                "workspace scope carries no separate scope_id (the workspace IS the instance)"
            )
    elif scope.scope_id is None:
        raise MemoryPreconditionFailed(
            f"{scope.scope_type.value} scope requires a scope_id naming a spine row"
        )
    elif scope.scope_type is MemoryScopeType.ACCOUNT:
        # account scope_id is a workspace-local account_entity uuid; the id's shape is validated
        # here, its existence/workspace-locality by the schema's composite FK (IntegrityError,
        # deliberately uncaught — a dangling/cross-workspace account dies there).
        try:
            UUID(scope.scope_id)
        except (ValueError, AttributeError) as exc:
            raise MemoryPreconditionFailed(
                "account scope_id must be a workspace-local account_entity uuid"
            ) from exc


async def _judge_or_none(
    judge: ReconcileJudge,
    submission: MemorySubmission,
    candidates: list[Memory],
) -> ReconcileJudgment | None:
    """The fail-safe boundary: any judge failure ⇒ ``None`` ⇒ the engine parks the submission
    ``proposed`` (never a silent activation — the memory-poisoning posture)."""
    try:
        return await judge.judge(submission, tuple(c.to_candidate() for c in candidates))
    except Exception:  # noqa: BLE001 — deliberately broad: ANY judge failure fails safe
        return None
