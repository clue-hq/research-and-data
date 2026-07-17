"""Config-bounded LLM query planning (M6.1 / ENG-128; staged-flow §7d).

The one place an LLM touches discovery — and it touches **queries only, never entities**. Given a
channel and the ICP filters, the planner may expand a richer set of search query *intents* (strings)
to hand the grounded channel. It is structurally impossible for this to fabricate a candidate: a
planned query is just a string passed to a :class:`DiscoveryChannel`, which returns only real
records (or nothing). Even if the model emitted a company name as a "query", the channel would
return that company's real record or an empty result — never an ungrounded candidate. The model id
is config (``DiscoveryConfig.query_planner_model``); with no gateway/model the planner falls back to
the strategy's static, human-authored queries (deterministic, no LLM in the loop).
"""

from __future__ import annotations

import json

from clue_core import LLMGateway, Message, Role
from clue_research.discovery_scoring.discovery.strategy import DiscoveryConfig, DiscoveryStrategy

# The hard instruction: expand QUERIES, never companies. The grounding guarantee does not *depend*
# on the model obeying this (the channel grounds every candidate regardless) — it is here so the
# planner spends its budget on useful search intents, not on inventing names that get discarded.
_SYSTEM_PROMPT = (
    "You plan web/database SEARCH QUERIES to discover companies matching an ICP. "
    "Output ONLY search query strings (one per line) — NEVER specific company names, and never a "
    "list of companies. The queries run against grounded data sources that return real records; "
    "your job is to widen recall, not to name companies."
)

_MAX_PLANNED_QUERIES = 12


def _parse_query_lines(text: str) -> tuple[str, ...]:
    """Parse the model's reply into a deduped, bounded tuple of non-empty query strings."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*0123456789. ").strip()
        if line and line not in seen:
            seen.add(line)
            out.append(line)
        if len(out) >= _MAX_PLANNED_QUERIES:
            break
    return tuple(out)


def plan_queries(
    *,
    channel: str,
    strategy: DiscoveryStrategy,
    config: DiscoveryConfig,
    gateway: LLMGateway | None,
) -> tuple[str, ...]:
    """The planned query intents for ``channel``: the strategy's static queries, optionally widened
    by the LLM planner. With no gateway or no configured model, returns the static queries verbatim
    (deterministic). Never returns or implies a specific entity — only query strings.
    """
    static = strategy.static_queries.get(channel, ())
    if gateway is None or config.query_planner_model is None:
        return static

    user = Message(
        role=Role.USER,
        content=(
            f"Channel: {channel}\n"
            f"ICP filters: {json.dumps(strategy.icp_filters, sort_keys=True, default=str)}\n"
            f"Seed/static queries: {list(static)}\n"
            "Produce additional search queries to widen recall for this channel."
        ),
    )
    completion = gateway.complete(
        model=config.query_planner_model,
        messages=[Message(role=Role.SYSTEM, content=_SYSTEM_PROMPT), user],
    )
    planned = _parse_query_lines(completion.text)
    # Union static + planned (static first, deduped) — both are query intents, never entities.
    seen = set(static)
    return static + tuple(q for q in planned if q not in seen)


__all__ = ["plan_queries"]
