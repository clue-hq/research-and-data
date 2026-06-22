"""The discovery orchestrator — the *expand* pattern over grounded channels (M6.1 / ENG-128).

``discover`` turns a confirmed ICP spec into a stream of grounded :class:`CandidateHypothesis`. It
reads the ICP's discovery strategy, plans per-channel queries (config or LLM, query-only), and runs
the **expand pattern**: rounds of *parallel* fan-out across the planned channels, deduping each
round's records in-stream (by the M2 identity normalizers), accumulating per-channel yield, and
checking the stopping rule (marginal-yield drop or budget cap) between rounds. It stops on the first
firing stop condition, or when every channel runs out of planned work (``EXHAUSTED``).

The anti-fabrication guarantee is structural and total: candidates are built only from
:class:`CandidateRecord`\\s that real channels return; the LLM only widens the *queries*. With all
channels returning nothing, ``discover`` emits zero candidates regardless of query planning.

Admission to the store is **not** here — that is the existence/identity gate (M6.2). ``discover``
only proposes; nothing is persisted.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from clue_research.core import CostCents, ICPSpec, LLMGateway, RunId
from clue_research.discovery_scoring.discovery.channels import (
    ChannelRegistry,
    DiscoveryChannel,
    DiscoveryQuery,
)
from clue_research.discovery_scoring.discovery.hypothesis import (
    LOOKALIKE_CHANNEL,
    CandidateHypothesis,
    CandidateRecord,
)
from clue_research.discovery_scoring.discovery.query_planning import plan_queries
from clue_research.discovery_scoring.discovery.stopping import StoppingReason, StoppingRule
from clue_research.discovery_scoring.discovery.strategy import (
    DEFAULT_DISCOVERY_CONFIG,
    DiscoveryConfig,
    DiscoveryStrategy,
)
from clue_research.identity import registrable_domain


class ChannelYield(BaseModel):
    """Per-channel running yield for one discovery run — the substrate M6.5 (coverage) and Doc C §6
    (per-source yield) read, keyed by ``(run_id, source_key)`` (the run id is on the result)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    queries_issued: int = 0
    records_returned: int = 0  # raw records the channel returned (pre-dedup)
    new_candidates: int = 0  # records that survived in-stream dedup (the channel's fresh yield)
    errors: int = 0  # channel calls that raised (isolated; a coverage gap M6.5 can surface)
    cost_cents: CostCents = Decimal(0)


class DiscoveryResult(BaseModel):
    """The output of a discovery run: the candidate stream the gate (M6.2) consumes, the per-channel
    yield counters, and *why* the run stopped (which M6.5 turns into a coverage statement)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    candidates: tuple[CandidateHypothesis, ...] = ()
    per_channel_yield: tuple[ChannelYield, ...] = ()
    stopping_reason: StoppingReason = StoppingReason.EXHAUSTED
    total_cost_cents: CostCents = Decimal(0)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def yield_for(self, source_key: str) -> ChannelYield | None:
        """The per-channel yield for ``source_key`` (queryable by ``(run_id, source_key)``)."""
        for cy in self.per_channel_yield:
            if cy.source_key == source_key:
                return cy
        return None


@dataclass
class _ChannelAcc:
    """Mutable per-channel accumulator (collapsed into a frozen ``ChannelYield`` at the end)."""

    queries_issued: int = 0
    records_returned: int = 0
    new_candidates: int = 0
    errors: int = 0
    cost_cents: Decimal = Decimal(0)


def _dedup_key(record: CandidateRecord) -> tuple[str, str]:
    """The in-stream dedup key: the candidate's own **registrable domain** — the deterministic
    strong key the M2 identity service keys on — so a company found via two channels collapses once.

    A record with no own domain falls back to its unique grounding handle (record ref, else URL), so
    distinct domain-less candidates are **not** collapsed here. This deliberately biases to
    *under*-collapse: the authoritative dedup (fuzzy name/geo, platform-URL disambiguation) is the
    existence/identity gate's job (M6.2). Over-collapse would silently lose a real, distinct account
    M6.2 could never recover; an emitted duplicate is merely merged at the gate. We therefore do
    **not** dedup on ``source_url`` (a platform URL like a shared LinkedIn/Crunchbase host would
    fold two different companies) nor on a legal-suffix-stripped name (folds "Acme Group" and "Acme
    Holdings")."""
    if record.candidate_domain:
        domain = registrable_domain(record.candidate_domain)
        if domain:
            return ("domain", domain)
    return ("ref", record.source_record_ref or record.source_url or "")


def _build_work_items(
    channel_key: str,
    strategy: DiscoveryStrategy,
    config: DiscoveryConfig,
    gateway: LLMGateway | None,
) -> list[DiscoveryQuery]:
    """Plan a channel's queue of :class:`DiscoveryQuery` work items (one popped per expand round).

    Lookalike → one item per seed; a query-driven channel → one item per planned query; a pure
    structured-filter channel (no planned queries) → a single filter-only item."""
    planned = plan_queries(channel=channel_key, strategy=strategy, config=config, gateway=gateway)
    if channel_key == LOOKALIKE_CHANNEL:
        return [
            DiscoveryQuery(
                channel=channel_key,
                icp_filters=strategy.icp_filters,
                queries=planned,
                seed_entity_id=seed,
                limit=config.per_query_limit,
            )
            for seed in strategy.seed_entity_ids
        ]
    if planned:
        return [
            DiscoveryQuery(
                channel=channel_key,
                icp_filters=strategy.icp_filters,
                queries=(query,),
                limit=config.per_query_limit,
            )
            for query in planned
        ]
    return [
        DiscoveryQuery(
            channel=channel_key, icp_filters=strategy.icp_filters, limit=config.per_query_limit
        )
    ]


async def discover(
    *,
    spec: ICPSpec,
    run_id: RunId,
    channels: ChannelRegistry,
    gateway: LLMGateway | None = None,
    config: DiscoveryConfig = DEFAULT_DISCOVERY_CONFIG,
) -> DiscoveryResult:
    """Run mode-M1 discovery for ``spec`` and return the grounded candidate stream + yield + stop
    reason. Pure of persistence (admission is M6.2); deterministic given fixed channel outputs."""
    strategy = DiscoveryStrategy.from_slot(spec.discovery_strategy)
    effective = strategy.resolve_config(config)
    selected = channels.select(strategy.channels)

    queues: dict[str, deque[DiscoveryQuery]] = {}
    channel_by_key: dict[str, DiscoveryChannel] = {}
    order: list[str] = []
    for key, channel in selected:
        items = _build_work_items(key, strategy, effective, gateway)
        if items:
            queues[key] = deque(items)
            channel_by_key[key] = channel
            order.append(key)

    acc: dict[str, _ChannelAcc] = {key: _ChannelAcc() for key in order}
    seen: set[tuple[str, str]] = set()
    candidates: list[CandidateHypothesis] = []
    rule = StoppingRule(
        window_size=effective.window_size,
        marginal_yield_threshold=effective.marginal_yield_threshold,
        budget_cap_cents=effective.discovery_budget_cap_cents,
    )
    cap = effective.discovery_budget_cap_cents
    stopping_reason = StoppingReason.EXHAUSTED
    rounds = 0

    while any(queues[key] for key in order):
        if rounds >= effective.max_rounds:
            stopping_reason = StoppingReason.ROUND_CAP  # honest: stopped with work still queued
            break
        rounds += 1
        active = [(key, queues[key].popleft()) for key in order if queues[key]]
        # Isolate per-channel faults: a channel that raises contributes nothing this round (a
        # coverage gap M6.5 can surface via its error count) but never aborts discovery or discards
        # the other channels' already-grounded results.
        results = await asyncio.gather(
            *(channel_by_key[key].discover(item) for key, item in active),
            return_exceptions=True,
        )

        round_new = 0
        round_seen = 0
        round_cost: Decimal = Decimal(0)
        budget_hit = False
        for (key, item), result in zip(active, results, strict=True):
            acc[key].queries_issued += 1
            if isinstance(result, BaseException):
                acc[key].errors += 1
                continue
            for record in result[: item.limit]:  # enforce the per-call recall cap
                acc[key].records_returned += 1
                acc[key].cost_cents += record.cost_cents
                round_seen += 1
                round_cost += record.cost_cents
                dedup_key = _dedup_key(record)
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    acc[key].new_candidates += 1
                    round_new += 1
                    candidates.append(
                        CandidateHypothesis.from_record(
                            record, matched_channel=key, seed_entity_id=item.seed_entity_id
                        )
                    )
                # Hard budget stop at record granularity: the cap is a ceiling, not a soft, between-
                # rounds boundary — stop consuming the moment cumulative spend reaches it.
                if cap is not None and rule.spent_cents + round_cost >= cap:
                    budget_hit = True
                    break
            if budget_hit:
                break

        rule.record_round(new_candidates=round_new, records_seen=round_seen, cost_cents=round_cost)
        if budget_hit:
            stopping_reason = StoppingReason.BUDGET_CAP
            break
        reason = rule.reason()
        if reason is not None:
            stopping_reason = reason
            break

    return DiscoveryResult(
        run_id=run_id,
        candidates=tuple(candidates),
        per_channel_yield=tuple(
            ChannelYield(
                source_key=key,
                queries_issued=acc[key].queries_issued,
                records_returned=acc[key].records_returned,
                new_candidates=acc[key].new_candidates,
                errors=acc[key].errors,
                cost_cents=acc[key].cost_cents,
            )
            for key in order
        ),
        stopping_reason=stopping_reason,
        total_cost_cents=rule.spent_cents,
    )


__all__ = ["discover", "DiscoveryResult", "ChannelYield"]
