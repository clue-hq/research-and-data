"""The retention/objection **tombstone-before-merge-read** sweep, wired ahead of the HANDOFF phase.

This closes the load-bearing ordering invariant (CLAUDE.md ``[M9.5×M1.2/M10.5]``): a personal claim
past its *retention* horizon can still be **fresh to the merge**, because the retention TTL is
shorter than the field freshness TTL (``RetentionTtls.sensitive_claim_ttl``=30d <
``FreshnessTtls.contact.facet``=90d, intentional minimization — Doc D §4). The M1.2 merge computes
FRESH/STALE from ``freshness_ttl`` only and has **no** retention/objection awareness, so a 40-day
sensitive ``contact.facet`` claim is EXPIRED-to-retention yet FRESH-to-merge — it would win
``current_value`` and cross the M12 handoff to the content layer unless it is tombstoned **first**.
M12 is deliberately built to *not* special-case ``EXPIRED`` (PF-1 D-EXP) on the standing assumption
that this sweep runs before its merge read; this handler is what makes that assumption true.

M12's :class:`~clue_api.handoff_wiring.HandoffPhaseHandler` assembles + materialises +
emits inside its ``run`` (the merge read), so :class:`RetentionSweepHandoffHandler` runs the M10.5
:class:`~clue_research.compliance.RetentionSweep` **before** delegating to it:

1. ``sweep_expired`` over the run's accounts + committee contacts — tombstones retention-EXPIRED
   personal claims (D-EXP) so the merge stops serving them;
2. ``sweep_objections`` — re-applies every standing Art. 21 objection (operator-wide; a bounded scan
   of ``outreach_objected``), tombstoning objected contacts' live ``contact.facet.*`` hooks (D-OBJ);
3. delegate to the inner HANDOFF handler, which now assembles over the post-tombstone merge.

Registered last-write-wins for ``ProjectPhase.HANDOFF`` (replacing M12's direct registration), so a
campaign-run reaching handoff sweeps before it serves. The sweeps are idempotent (an already-
tombstoned claim is no longer live), so a crash-resume re-entry is safe. ``api`` is the
import-linter-exempt seam, so this composes the otherwise-independent ``compliance`` (M10) and
``narrative``/handoff (M12) packages (nothing imports ``api`` — Rule 5).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from clue_api.verification.handler import ContactResolver, VerificationAccountResolver
from clue_core import (
    EntityId,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    ProjectPhase,
)
from clue_db import ConnFactory, transaction
from clue_obs.otel import MetricSink
from clue_research.compliance import RetentionSweep
from clue_research.durable import register_phase_handler
from clue_research.identity import contact_ids_for_account
from clue_research.verification import FreshnessImpl
from clue_storage import StorageBackend

# Reuse the VERIFICATION resolver seams (DRY): the same "run's high-tier accounts" and "an account's
# committee contacts" concepts scope the age-out to exactly the entities this run's handoff reads.
HandoffAccountResolver = VerificationAccountResolver


@runtime_checkable
class RetentionSweeping(Protocol):
    """The slice of M10.5 :class:`~clue_research.compliance.RetentionSweep` this handler drives —
    typed structurally (conventions §2) so the handler is fake-testable without a DB. The real sweep
    satisfies it (asserted at the composition root)."""

    async def sweep_expired(
        self,
        *,
        entity_ids: tuple[EntityId, ...] | None = None,
        field_keys: tuple[str, ...] | None = None,
    ) -> object: ...

    async def sweep_objections(self) -> object: ...


class RetentionSweepHandoffHandler:
    """The ``ProjectPhase.HANDOFF`` handler that runs the retention/objection sweep **before** the
    inner M12 handoff (so the assembler's merge read sees the post-tombstone state)."""

    phase: ProjectPhase = ProjectPhase.HANDOFF

    def __init__(
        self,
        *,
        sweep: RetentionSweeping,
        inner: PhaseHandler,
        account_resolver: HandoffAccountResolver,
        contact_resolver: ContactResolver | None = None,
    ) -> None:
        self._sweep = sweep
        self._inner = inner
        self._account_resolver = account_resolver
        self._contact_resolver = contact_resolver

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        """Tombstone EXPIRED + objected personal claims for the run, then delegate to the inner
        handoff handler. Augments the inner result's references-only payload with sweep counts."""
        entity_ids = await self._run_entity_ids(ctx)
        # EXPIRED retention age-out, scoped to the run's entities (so one client's handoff does not
        # re-sweep every tenant). Skip when the run has no high-tier accounts — passing an empty set
        # must NOT widen to an operator-wide scan.
        retention_tombstoned = 0
        if entity_ids:
            expired = await self._sweep.sweep_expired(entity_ids=entity_ids)
            retention_tombstoned = len(getattr(expired, "tombstoned_claim_ids", ()))
        # Standing Art. 21 objections are operator-wide (a bounded ``outreach_objected`` scan) and
        # near-absolute, so re-applied every handoff regardless of the run's entity set.
        objected = await self._sweep.sweep_objections()
        objection_tombstoned = len(getattr(objected, "tombstoned_claim_ids", ()))

        result = await self._inner.run(ctx)
        payload = dict(result.payload)
        payload["retention_tombstoned"] = retention_tombstoned
        payload["objection_tombstoned"] = objection_tombstoned
        return result.model_copy(update={"payload": payload})

    async def _run_entity_ids(self, ctx: PhaseContext) -> tuple[EntityId, ...]:
        """The run's high-tier accounts plus their committee contacts — the entities whose personal
        claims this run's handoff could surface, hence the age-out scope."""
        ids: list[EntityId] = []
        for spec in await self._account_resolver(ctx):
            ids.append(spec.entity_id)
            if self._contact_resolver is not None:
                ids.extend(await self._contact_resolver(spec.entity_id))
        return tuple(ids)


def build_retention_sweeping_handoff_handler(
    *,
    inner: PhaseHandler,
    account_resolver: HandoffAccountResolver,
    session_factory: ConnFactory = transaction,
    govern_contacts: bool = True,
    health_sink: MetricSink | None = None,
    storage: StorageBackend | None = None,
) -> RetentionSweepHandoffHandler:
    """Wrap M12's ``inner`` HANDOFF handler with the M10.5 retention/objection sweep.

    Constructs the M9.5 :class:`~clue_research.verification.FreshnessImpl` (the ``due_for_age_out``
    source) and the M10.5 :class:`~clue_research.compliance.RetentionSweep` over it; scopes the
    age-out to the run's accounts + (when ``govern_contacts``) their committee contacts via
    :func:`clue_research.identity.contact_ids_for_account`.

    Pass a B2 ``storage`` backend so tombstoning an EXPIRED/objected personal claim also performs
    the refcounted deletion of any snapshot it was the last live citer of (B2.5); the sweep's
    scan-all purge additionally converges any erased-but-unpurged marks a crashed earlier purge left
    behind. Without it the intent (``erased_at``) is still stamped and a later storage-wired sweep
    converges.
    """
    freshness = FreshnessImpl(conn_factory=session_factory, sink=health_sink)
    sweep = RetentionSweep(
        freshness, conn_factory=session_factory, sink=health_sink, storage=storage
    )

    contact_resolver: ContactResolver | None = None
    if govern_contacts:

        async def resolve_contacts(account_entity_id: EntityId) -> Sequence[EntityId]:
            async with session_factory() as conn:
                return await contact_ids_for_account(conn, account_entity_id)

        contact_resolver = resolve_contacts

    return RetentionSweepHandoffHandler(
        sweep=sweep,
        inner=inner,
        account_resolver=account_resolver,
        contact_resolver=contact_resolver,
    )


def register_retention_sweeping_handoff_handler(
    *,
    inner: PhaseHandler,
    account_resolver: HandoffAccountResolver,
    storage: StorageBackend | None,
    session_factory: ConnFactory = transaction,
    govern_contacts: bool = True,
    health_sink: MetricSink | None = None,
) -> RetentionSweepHandoffHandler:
    """Build + register the retention-sweeping HANDOFF handler into the M7 phase registry
    (last-write-wins over M12's direct ``register_handoff_phase_handler``).

    ``storage`` is a **required** keyword on this production registration surface (unlike
    :func:`build_retention_sweeping_handoff_handler`, where it defaults to ``None``): tombstoning an
    EXPIRED/objected personal claim must make its refcounted blob-deletion decision explicit — pass
    ``build_storage_backend()`` to enable the deletion, or ``None`` for the intent-only path (a
    later storage-wired sweep converges). Forgetting it is a ``TypeError``, never a silent
    no-deletion registration."""
    handler = build_retention_sweeping_handoff_handler(
        inner=inner,
        account_resolver=account_resolver,
        session_factory=session_factory,
        govern_contacts=govern_contacts,
        health_sink=health_sink,
        storage=storage,
    )
    register_phase_handler(handler)
    return handler


# Static-time conformance: the wrapper is a ``core.PhaseHandler``, and the real M10.5 RetentionSweep
# satisfies the structural ``RetentionSweeping`` seam the handler is typed against.
_HANDLER_IS_A_PHASE_HANDLER: type[PhaseHandler] = RetentionSweepHandoffHandler
_SWEEP_IS_A_RETENTION_SWEEPING: type[RetentionSweeping] = RetentionSweep
