"""The ``LLMGateway`` protocol + its value types — the model-egress seam (M0.4, conventions §4).

The model analogue of the :class:`~clue_core.resolver.Resolver` seam: every *direct* LLM
response-generation or embedding call the subsystem makes goes through **one** shared gateway
whose provider/model is config, not code. The faithfulness judge (M9.3), the eval rubric scorers
(M9.6), discovery query-planning (M6.1), ICP synthesis (M5.2), committee role-inference (M8.3) and
value-narrative positioning (M12.1) all bind to this one contract — "the LLM client from M0" the
later specs reference *is* this gateway. No component constructs a model-vendor SDK directly.

The **protocol and value types live here in ``core``** (the shared-contracts package) so every call
site imports one shape; the **concrete OpenRouter client and the deterministic CI stub live in
``clue_gateway``**, which imports ``obs`` to emit the ``llm.gateway_call`` span — ``core``
may not (the ``obs → config → core`` layering, M0.1). This mirrors ``core.Resolver`` (protocol here)
↔ ``resolvers/<provider>`` (implementations there).

**Carve-out (conventions §2):** Exa Deep and Parallel Task (M11) are tier-4 *research-product*
resolvers behind the :class:`Resolver` protocol with their own keys — **not** gateway calls.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from clue_core.primitives import CostCents

# An embedding vector — a plain list of floats (the OpenAI-compatible embedding shape).
Vector = list[float]


class Role(StrEnum):
    """Provider-neutral message role accepted by the response-generation gateway."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    """One message in a ``complete`` request (provider-neutral)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Role
    content: str


class TokenUsage(BaseModel):
    """Prompt/completion token counts reported by the model — the cost-and-yield substrate.

    Recorded on every :class:`Completion`/:class:`EmbeddingResult` and emitted on the
    ``llm.gateway_call`` span (M0.5) so per-call-site token spend is measurable (Doc C §6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    # Contract-delta P3.2 (PD-part3 delta 6): the provider-reported cached-prefill share of
    # ``prompt_tokens`` (0 when the provider reports none) — the measurable economics the
    # OpenRouter ``usage.include`` passthrough exists for. Additive with a default, so every
    # existing constructor and stored shape parses unchanged.
    cached_prompt_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Completion(BaseModel):
    """The result of a response-generation call through the gateway.

    ``model`` is the id that *actually* answered (may differ from the requested id if the
    configured fallback was used) — recorded so provenance/observability reflects reality, not the
    request. ``finish_reason`` preserves the provider terminal status (or incomplete reason) behind
    the stable internal contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    text: str
    usage: TokenUsage = TokenUsage()
    cost_cents: CostCents = Decimal(0)
    finish_reason: str | None = None


class EmbeddingResult(BaseModel):
    """The result of an embedding call: one :data:`Vector` per input, in input order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    vectors: tuple[Vector, ...] = ()
    usage: TokenUsage = TokenUsage()
    cost_cents: CostCents = Decimal(0)


@runtime_checkable
class LLMGateway(Protocol):
    """The single egress for direct model calls — the model analogue of ``Resolver``.

    ``model`` is a config-supplied id (e.g. ``"anthropic/claude-…"``) resolved per call site, so a
    model swap (or an OpenRouter → another OpenAI-compatible gateway swap) is a config change, never
    a code change in any caller. Implementations wrap one ``OPENROUTER_API_KEY``, emit the
    ``llm.gateway_call`` span with token usage + ``cost_cents``, and ship a deterministic stub. The
    live OpenRouter adapter uses the OpenAI-compatible Responses API; callers stay independent of
    that wire schema. ``@runtime_checkable`` lets a factory assert conformance structurally; mypy
    checks signatures.
    """

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion: ...

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult: ...
