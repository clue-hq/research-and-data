"""Replay a finished design run's messages through the context-clearing rule (read-only, free).

Rebuilds the run's message history from LangGraph's checkpoint_writes, then for each model call
compares what was sent (everything before that call) with what clearing would have sent.

Tokens are estimated: text at ~4 characters per token, screenshots at width x height / 750
(LangChain's approximate counter treats an image as a few text tokens, which undercounted the
Syracuse replay). The system prompt and tool definitions are not in the saved history; pass
their size per call as the optional second argument (about 48000 for the website agent, read
from the first call's billed prompt tokens) to see per-call totals comparable to the bill.

Usage (repo root):
    set -a; source .env; set +a
    .venv/bin/python subsystems/clue-design/scripts/context_clearing_replay.py <thread_id> [fixed]
    e.g. ... context_clearing_replay.py dsess_b5f568ded78d5224abafd1d836c670f0 48000
Env: CLUE_DATABASE_URL (the lane DB; the +asyncpg driver suffix is stripped).
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys

import psycopg
from langchain_core.messages import AIMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "agent_runtime"))
from lumen_agent.context_clearing import clear_superseded_tool_results  # noqa: E402

#: What an image counts for when its bytes cannot be decoded.
UNREADABLE_IMAGE_TOKENS = 1500


def _image_tokens(part: dict) -> int:
    image_url = part.get("image_url")
    url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url or "")
    try:
        width, height = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size
    except Exception:
        return UNREADABLE_IMAGE_TOKENS
    return width * height // 750


def estimate_tokens(messages: list) -> int:
    """Text at ~4 characters per token, tool-call arguments included; images by pixel area."""
    total = 0
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            total += len(json.dumps([call.get("args") for call in message.tool_calls])) // 4
        content = message.content
        if isinstance(content, str):
            total += len(content) // 4
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("image_url", "image"):
                total += _image_tokens(part)
            else:
                total += len(part.get("text", "") if isinstance(part, dict) else str(part)) // 4
    return total


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
    fixed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    dsn = os.environ["CLUE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    messages = load_messages(dsn, thread_id)
    call_points = [i for i, m in enumerate(messages) if isinstance(m, AIMessage)]
    total_now = total_cleared = 0
    print(f"{'call':>4} {'sent today':>12} {'with clearing':>14}")
    for n, index in enumerate(call_points, start=1):
        history = messages[:index]
        now = estimate_tokens(history) + fixed
        cleared = estimate_tokens(clear_superseded_tool_results(history)) + fixed
        total_now += now
        total_cleared += cleared
        print(f"{n:>4} {now:>12,} {cleared:>14,}")
    saved = 100 * (1 - total_cleared / max(total_now, 1))
    print(f"total {total_now:,} -> {total_cleared:,} ({saved:.0f}% less)")


if __name__ == "__main__":
    main()
