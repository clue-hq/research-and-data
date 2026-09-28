"""Trace-serializer tests: what a recorded message carries into the run trace.

Founder ruling 2026-09-18 (design session continuity): the model's own reasoning
text is part of the session RECORD, so ``_message_to_dict`` records it whenever the
provider returned one. Whether that reasoning is re-SENT as context on the next turn
is a separate, per-provider decision the gateway owns
(``clue_gateway.openrouter_chat._retain_reasoning``).
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from lumen_agent.trace_callbacks import _message_to_dict


def test_reasoning_text_is_recorded_when_the_provider_returned_it() -> None:
    with_reasoning = AIMessage(
        content="done",
        additional_kwargs={"reasoning_content": "I compared the two layouts."},
    )
    assert _message_to_dict(with_reasoning)["reasoning_content"] == "I compared the two layouts."
    assert "reasoning_content" not in _message_to_dict(AIMessage(content="done"))


def test_blank_reasoning_text_is_not_recorded() -> None:
    """A provider that returns an empty or whitespace-only reasoning field adds
    nothing to the record — an absent key, never an empty one."""
    for blank in ("", "   \n\t"):
        message = AIMessage(content="done", additional_kwargs={"reasoning_content": blank})
        assert "reasoning_content" not in _message_to_dict(message)
