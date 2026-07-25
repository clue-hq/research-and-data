"""The :class:`HandoffPublisher` adapter seam — the transport the content layer consumes (M12.3 /
D2).

The boundary the subsystem ends at (overview §3) is the ``account_handoff`` *contract*, not a
specific transport. **What** the content layer ingests, and **how** (REST pull vs. event push vs. a
design-system-specific adapter), is the open dependency D2. So the notify side of the emit path is
an
injected adapter: the durable :class:`~clue_research.narrative.handoff_events` outbox is always the
source of truth (a puller can read it regardless), and a ``HandoffPublisher`` is the optional push
on
top of it. Swapping the publisher (pull → push → bespoke adapter) requires **no change to the
``account_handoff`` schema or to any upstream producer** (M12.3 AC8 seam test) — that is exactly
where D2 gets resolved later, by adding/configuring an adapter, not by reshaping the contract.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clue_research.narrative.handoff_events import HandoffEvent


@runtime_checkable
class HandoffPublisher(Protocol):
    """Notify a content-layer consumer that one assembled handoff is ready to fetch.

    ``publish`` is called **once per newly-emitted** outbox row (the emit path fires it only when
    :func:`~clue_research.narrative.handoff_events.emit_handoff_event` actually inserted), so a
    publisher never has to dedupe re-entries itself. It carries only the :class:`HandoffEvent`
    coordinates — never claim bodies (substrate §5b) — so the consumer pulls the object over the
    read API. An implementation must NOT write back into the claim store (the one-directional rule,
    substrate §5c)."""

    async def publish(self, event: HandoffEvent) -> None: ...


class OutboxHandoffPublisher:
    """The default **pull** publisher: the durable outbox row *is* the signal, so ``publish`` is a
    no-op. A content-layer consumer polls
    :func:`~clue_research.narrative.handoff_events.list_handoff_events`. This is the conservative,
    Postgres-only default (no outbound network, nothing to fail); a push transport (webhook,
    message bus, a D2 design-system adapter) is a drop-in swap behind the same Protocol."""

    async def publish(self, event: HandoffEvent) -> None:  # noqa: D401 — intentional no-op
        return None


class RecordingHandoffPublisher:
    """A test/diagnostic publisher that captures each published :class:`HandoffEvent` in order — the
    in-memory stand-in for a real push transport, used to prove the seam swap (AC8) and the
    exactly-once push (a re-entry must not re-publish)."""

    def __init__(self) -> None:
        self.published: list[HandoffEvent] = []

    async def publish(self, event: HandoffEvent) -> None:
        self.published.append(event)
