"""Count an agent conversation in the model's real tokens.

Compaction and result clearing both fire on a token threshold, and a character estimate misjudges
real tokens differently for every model. Run 4 (2026-10-10): compaction set at 150k estimated
tokens fired at about 128k real GPT-6.1-Sol tokens. LangChain's own correction does not help:
it only trusts a reply whose provider label equals the model's (ours says ``openai``, our model
says ``clue-openrouter-agent``), and it only ever scales the estimate up. Most of the models we run
have no local tokenizer.

The provider does count every request exactly: a reply's ``usage_metadata["input_tokens"]``. So
the summariser records on each reply its estimate of the request that produced it
(:data:`PROMPT_ESTIMATE_KEY`), and the newest reply's real count divided by that estimate is the
conversation's real-token rate. Any list of messages is then counted as its estimate times that
rate: exactly the provider's count for what it has already seen, and the same model's measured
rate for whatever was added since. Before the first reply the count is the plain estimate.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.utils import count_tokens_approximately

__all__ = [
    "PROMPT_ESTIMATE_KEY",
    "ContextTokenCounter",
    "estimate_tokens",
    "real_token_ratio",
    "record_prompt_estimate",
]

#: ``response_metadata`` key on each reply: our estimate of the request that produced it.
PROMPT_ESTIMATE_KEY = "clue_prompt_estimate_tokens"


def estimate_tokens(messages: Sequence[BaseMessage], tools: Sequence[Any] | None = None) -> int:
    """The character-based estimate (LangChain's ``count_tokens_approximately``)."""
    return count_tokens_approximately(messages, tools=list(tools) if tools else None)


def real_token_ratio(messages: Sequence[BaseMessage]) -> float | None:
    """Real tokens per estimated token, from the newest reply that carries both counts."""
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        sent = message.response_metadata.get(PROMPT_ESTIMATE_KEY)
        real = (message.usage_metadata or {}).get("input_tokens")
        if isinstance(sent, int) and sent > 0 and isinstance(real, int) and real > 0:
            return real / sent
    return None


def record_prompt_estimate(response: Any, estimate: int) -> None:
    """Record ``estimate`` on every reply in a model response.

    ``response`` is a ``ModelResponse`` or an ``ExtendedModelResponse`` wrapping one.
    """
    response = getattr(response, "model_response", response)
    for message in getattr(response, "result", None) or ():
        if isinstance(message, AIMessage):
            message.response_metadata[PROMPT_ESTIMATE_KEY] = estimate


class ContextTokenCounter:
    """A token counter in real tokens (see the module docstring).

    The rate comes from the newest counted reply in the messages it is given; a list without one
    (a slice of the conversation) is counted at the last rate seen.
    """

    def __init__(self) -> None:
        self.ratio: float | None = None

    def __call__(
        self, messages: Sequence[BaseMessage], *, tools: Sequence[Any] | None = None
    ) -> int:
        ratio = real_token_ratio(messages)
        if ratio is not None:
            self.ratio = ratio
        estimate = estimate_tokens(messages, tools)
        return estimate if self.ratio is None else math.ceil(estimate * self.ratio)
