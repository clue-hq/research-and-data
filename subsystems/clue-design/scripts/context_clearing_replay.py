"""Replay a finished design run's messages through the context-clearing rule (read-only, free).

Rebuilds the run's message history from LangGraph's checkpoint_writes, then for each model call
compares what was sent (everything before that call) with what clearing would have sent. Token
counts use LangChain's approximate counter, so compare the two columns, not absolute dollars.

Usage (repo root):
    set -a; source .env; set +a
    .venv/bin/python subsystems/clue-design/scripts/context_clearing_replay.py dsess_b5f568ded78d5224abafd1d836c670f0
Env: CLUE_DATABASE_URL (the lane DB; the +asyncpg driver suffix is stripped).
"""

from __future__ import annotations

import os
import sys

import psycopg
from langchain_core.messages import AIMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "agent_runtime"))
from lumen_agent.context_clearing import clear_superseded_tool_results  # noqa: E402


def load_messages(dsn: str, thread_id: str) -> list:
    serde = JsonPlusSerializer()
    rows = psycopg.connect(dsn).execute(
        "select type, blob from checkpoint_writes where thread_id=%s and channel='messages' "
        "order by checkpoint_id, task_id, idx",
        (thread_id,),
    ).fetchall()
    messages, seen = [], set()
    for typ, blob in rows:
        value = serde.loads_typed((typ, blob))
        for message in value if isinstance(value, list) else [value]:
            key = getattr(message, "id", None) or id(message)
            if key not in seen:
                seen.add(key)
                messages.append(message)
    return messages


def main() -> None:
    thread_id = sys.argv[1]
    dsn = os.environ["CLUE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    messages = load_messages(dsn, thread_id)
    call_points = [i for i, m in enumerate(messages) if isinstance(m, AIMessage)]
    total_now = total_cleared = 0
    print(f"{'call':>4} {'sent today':>12} {'with clearing':>14}")
    for n, index in enumerate(call_points, start=1):
        history = messages[:index]
        now = count_tokens_approximately(history)
        cleared = count_tokens_approximately(clear_superseded_tool_results(history))
        total_now += now
        total_cleared += cleared
        print(f"{n:>4} {now:>12,} {cleared:>14,}")
    print(f"total {total_now:,} -> {total_cleared:,} ({100 * (1 - total_cleared / max(total_now, 1)):.0f}% less)")


if __name__ == "__main__":
    main()
