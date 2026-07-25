"""The discovery strategy + config — interpreting the opaque ICP slot (M6.1 / ENG-128).

``ICPSpec.discovery_strategy`` is stored by M3 as an opaque ``dict[str, JsonValue]`` (M3 owns the
durable slot; **M6 owns its meaning** — D5/D6). This module is that interpretation: a typed
:class:`DiscoveryStrategy` (which channels to query, the ICP filters to apply, lookalike seeds, and
per-channel canned queries used when no LLM planner is configured) plus a :class:`DiscoveryConfig`
of the stopping/budget knobs (D7 — versioned config, never constants). A strategy may override the
config knobs per ICP; :meth:`DiscoveryStrategy.resolve_config` merges them.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from clue_core import CostCents, EntityId
from clue_research.discovery_scoring.discovery.hypothesis import LOOKALIKE_CHANNEL

__all__ = [
    "DiscoveryConfig",
    "DEFAULT_DISCOVERY_CONFIG",
    "DiscoveryStrategy",
    "DiscoveryStrategyError",
    "LOOKALIKE_CHANNEL",
]


class DiscoveryStrategyError(ValueError):
    """Raised when ``ICPSpec.discovery_strategy`` is malformed (e.g. a non-UUID seed id)."""


class DiscoveryConfig(BaseModel):
    """The stopping/budget knobs for a discovery run (D7 — versioned config). Defaults are
    deliberately conservative starting points to confirm against real campaigns, not policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Sliding window (in expand rounds) over which the marginal-yield rate is measured.
    window_size: int = Field(default=3, ge=1)
    # Stop when the new-candidate rate over the window drops below this (0..1).
    marginal_yield_threshold: float = Field(default=0.1, ge=0.0, le=1.0)
    # Discovery spend cap (sum of channel cost_cents). None = no cap (bounded only by yield/rounds).
    discovery_budget_cap_cents: CostCents | None = None
    # Max records a single channel call may return (a per-call recall cap; the orchestrator trims
    # each channel's results to this so one round's spend/volume is bounded).
    per_query_limit: int = Field(default=50, ge=1)
    # Pure safety backstop on expand rounds. The expand loop provably terminates by queue exhaustion
    # (finite queries/seeds, ≥1 popped per round), so this only fires in a pathological config; the
    # default is deliberately far above any realistic per-channel query/seed count so it never
    # truncates legitimate work — when it *does* fire the run reports StoppingReason.ROUND_CAP (an
    # honest "stopped with work still queued"), never a false EXHAUSTED.
    max_rounds: int = Field(default=1000, ge=1)
    # The gateway model id for LLM query planning; None disables planning (use the strategy's static
    # queries verbatim). A model string here never lets the LLM emit entities — only query intents.
    query_planner_model: str | None = None


DEFAULT_DISCOVERY_CONFIG = DiscoveryConfig()


def _as_str_tuple(value: JsonValue | None) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _as_cost(value: JsonValue | None) -> CostCents | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise DiscoveryStrategyError(f"discovery budget cap {value!r} is not a number")
    try:
        cost = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DiscoveryStrategyError(f"discovery budget cap {value!r} is not a number") from exc
    if cost < 0:
        raise DiscoveryStrategyError(f"discovery budget cap {value!r} must be >= 0")
    return cost


def _as_positive_int(value: JsonValue | None, name: str) -> int | None:
    """Parse an optional positive-int knob from the slot — ``bool`` is *not* an int here, and a
    value < 1 is a config error (caught at the boundary, not deep in ``StoppingRule``)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DiscoveryStrategyError(f"discovery {name} {value!r} must be an integer")
    if value < 1:
        raise DiscoveryStrategyError(f"discovery {name} {value!r} must be >= 1")
    return value


def _as_unit_float(value: JsonValue | None, name: str) -> float | None:
    """Parse an optional 0..1 knob from the slot (``bool`` excluded; out-of-range is an error)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiscoveryStrategyError(f"discovery {name} {value!r} must be a number in 0..1")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise DiscoveryStrategyError(f"discovery {name} {value!r} must be in 0..1")
    return number


class DiscoveryStrategy(BaseModel):
    """The typed view of ``ICPSpec.discovery_strategy`` (M6's interpretation of the opaque slot)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channels: tuple[
        str, ...
    ] = ()  # source_keys to query, in priority order (may include lookalike)
    icp_filters: dict[str, JsonValue] = {}  # structured filters handed to every channel
    seed_entity_ids: tuple[
        EntityId, ...
    ] = ()  # lookalike seeds (resolved customer/seed/import ids)
    static_queries: dict[str, tuple[str, ...]] = {}  # per-channel canned queries (no-LLM fallback)
    # Optional per-ICP overrides of the DiscoveryConfig knobs (None = inherit the run's config).
    marginal_yield_threshold: float | None = None
    discovery_budget_cap_cents: CostCents | None = None
    window_size: int | None = None
    per_query_limit: int | None = None
    query_planner_model: str | None = None

    @classmethod
    def from_slot(cls, slot: Mapping[str, JsonValue]) -> DiscoveryStrategy:
        """Parse the opaque ``ICPSpec.discovery_strategy`` dict. An empty slot yields an empty
        strategy (no channels → a discovery run that correctly finds nothing), never an error."""
        if not slot:
            return cls()
        seeds: list[EntityId] = []
        for raw in _as_str_tuple(slot.get("seed_entity_ids")):
            try:
                seeds.append(EntityId(UUID(raw)))
            except (ValueError, AttributeError, TypeError) as exc:
                raise DiscoveryStrategyError(
                    f"discovery seed_entity_id {raw!r} is not a valid UUID"
                ) from exc
        raw_static = slot.get("static_queries")
        static_queries: dict[str, tuple[str, ...]] = {}
        if isinstance(raw_static, dict):
            for channel, queries in raw_static.items():
                static_queries[str(channel)] = _as_str_tuple(queries)
        raw_filters = slot.get("icp_filters")
        icp_filters: dict[str, JsonValue] = (
            dict(raw_filters) if isinstance(raw_filters, dict) else {}
        )
        planner = slot.get("query_planner_model")
        return cls(
            channels=_as_str_tuple(slot.get("channels")),
            icp_filters=icp_filters,
            seed_entity_ids=tuple(seeds),
            static_queries=static_queries,
            marginal_yield_threshold=_as_unit_float(
                slot.get("marginal_yield_threshold"), "marginal_yield_threshold"
            ),
            discovery_budget_cap_cents=_as_cost(slot.get("discovery_budget_cap_cents")),
            window_size=_as_positive_int(slot.get("window_size"), "window_size"),
            per_query_limit=_as_positive_int(slot.get("per_query_limit"), "per_query_limit"),
            query_planner_model=str(planner) if isinstance(planner, str) else None,
        )

    def resolve_config(self, config: DiscoveryConfig) -> DiscoveryConfig:
        """Merge this strategy's per-ICP overrides onto the run ``config`` (override > default)."""
        updates: dict[str, object] = {}
        if self.marginal_yield_threshold is not None:
            updates["marginal_yield_threshold"] = self.marginal_yield_threshold
        if self.discovery_budget_cap_cents is not None:
            updates["discovery_budget_cap_cents"] = self.discovery_budget_cap_cents
        if self.window_size is not None:
            updates["window_size"] = self.window_size
        if self.per_query_limit is not None:
            updates["per_query_limit"] = self.per_query_limit
        if self.query_planner_model is not None:
            updates["query_planner_model"] = self.query_planner_model
        return config.model_copy(update=updates) if updates else config
