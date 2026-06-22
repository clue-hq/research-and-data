"""The discovery-channel seam — grounded, swappable, config-selected (M6.1 / ENG-128).

``DiscoveryChannel`` is to *finding entities* what ``core.Resolver`` is to *enriching a field*: a
narrow, provider-agnostic contract behind which any grounded provider (structured-DB ICP search like
Apollo/ZoomInfo, web entity discovery like Exa Websets / Parallel FindAll, a curated directory, a
lookalike expander) hides. M6 owns this seam rather than reusing ``core.Resolver`` because the two
have fundamentally different shapes: ``Resolver.resolve(entity, field)`` *enriches a known entity*
and structurally cannot *produce* a new one, whereas discovery starts from a query and yields
candidate records. Keeping it source-keyed means swapping a channel's provider — or adding a new
directory — is a registration/config change, invisible to the orchestrator and the gate (the same
"nothing downstream knows a provider's name" discipline the ``Resolver`` seam enforces).

Why not in ``core``: the concrete grounded providers do not exist in M4 yet (M4 built enrichment
resolvers only), and ``core`` is frozen — promoting this protocol to ``core`` is a deliberate
re-freeze for when real providers land. Until then the seam lives here; channels are bound into a
:class:`ChannelRegistry` at the ``api`` composition root (or in tests, via doubles).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_research.core import EntityId
from clue_research.discovery_scoring.discovery.hypothesis import CandidateRecord


class DiscoveryQuery(BaseModel):
    """One unit of work handed to a :class:`DiscoveryChannel`: the channel to hit, the ICP filters
    to apply, the (LLM- or config-planned) free-text query intents to expand, an optional lookalike
    seed, and a hard record ``limit`` so a single call cannot run away."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: str  # the target source_key
    icp_filters: dict[str, JsonValue] = {}  # structured ICP filters (industry, size band, geo …)
    queries: tuple[
        str, ...
    ] = ()  # planned free-text query intents (empty = pure structured search)
    seed_entity_id: EntityId | None = None  # the seed to expand from (lookalike channels)
    limit: int = 50  # max records this call may return (a per-call recall cap)


@runtime_checkable
class DiscoveryChannel(Protocol):
    """A grounded, entity-producing channel (M6.1). It declares the ``source_key`` it serves and
    returns **real records only** for a query — every :class:`CandidateRecord` it yields is grounded
    (a ``source_record_ref`` / ``source_url`` from the underlying source), enforced at construction.
    Async because a channel does provider IO; ``@runtime_checkable`` lets the registry assert
    conformance structurally (``source_key`` + ``discover``), while mypy checks the full signature.

    Contract: a channel never fabricates. A miss is an **empty list** (a correct, empty result the
    orchestrator advances past), never an invented company. A transient provider fault should raise
    (so the run can retry) rather than be swallowed into an empty result — mirroring the M4 resolver
    fault discipline.
    """

    source_key: str

    async def discover(self, query: DiscoveryQuery) -> list[CandidateRecord]: ...


class ChannelRegistry:
    """The bound set of discovery channels, keyed by ``source_key`` — the config seam.

    The orchestrator queries the intersection of the ICP's planned channels and what is bound here,
    so a channel named in the discovery strategy but not bound (no provider wired) is skipped, and
    swapping a provider is a re-``register`` under the same key (no orchestrator change). Wired at
    the ``api`` composition root in production; populated with doubles in tests.
    """

    def __init__(self, channels: tuple[DiscoveryChannel, ...] = ()) -> None:
        self._by_key: dict[str, DiscoveryChannel] = {}
        for channel in channels:
            self.register(channel)

    def register(self, channel: DiscoveryChannel) -> None:
        """Bind (or rebind, last-write-wins) a channel under its ``source_key``."""
        self._by_key[channel.source_key] = channel

    def get(self, source_key: str) -> DiscoveryChannel | None:
        return self._by_key.get(source_key)

    def keys(self) -> frozenset[str]:
        return frozenset(self._by_key)

    def select(self, channel_keys: tuple[str, ...]) -> tuple[tuple[str, DiscoveryChannel], ...]:
        """Resolve the strategy's named channels to bound ``(source_key, channel)`` pairs, in the
        strategy's order, dropping any channel that is named but not bound (deduped, first-seen)."""
        selected: list[tuple[str, DiscoveryChannel]] = []
        seen: set[str] = set()
        for key in channel_keys:
            if key in seen:
                continue
            channel = self._by_key.get(key)
            if channel is not None:
                selected.append((key, channel))
                seen.add(key)
        return tuple(selected)


__all__ = ["DiscoveryQuery", "DiscoveryChannel", "ChannelRegistry"]
