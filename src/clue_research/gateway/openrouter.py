"""The live OpenRouter-backed ``LLMGateway`` (M0.4) — the single egress for direct LLM calls.

Wraps **OpenRouter** (OpenAI-compatible) via the ``openai`` client, which is imported **only here**
(the model analogue of a provider resolver; import-linter Rule 4b keeps every other package from
constructing a model SDK). The client is built behind an injectable ``client_factory`` seam, so the
gateway's *logic* — message mapping, token-usage extraction, cost computation, and fallback-model
retry — is unit-testable with a fake, while production lazy-imports the real SDK. The requested
``model`` is config (conventions §4): swapping it is a config change, not code.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import SecretStr

from clue_research.config.gateway import GatewayConfig
from clue_research.core.gateway import Completion, EmbeddingResult, Message, TokenUsage

# A zero-arg factory returning an OpenAI-compatible client (duck-typed: ``.chat.completions.create``
# and ``.embeddings.create``). The default builds the real ``openai`` client; tests inject a fake.
ClientFactory = Callable[[], Any]


class OpenRouterGateway:
    """Live :class:`~clue_research.core.gateway.LLMGateway` backed by OpenRouter."""

    def __init__(
        self,
        config: GatewayConfig,
        api_key: SecretStr,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._client_factory = client_factory or self._default_client_factory
        self._client: Any | None = None

    def _default_client_factory(self) -> Any:
        # Lazy import: only the live path needs the SDK, so CI's stub path never imports it. The
        # import lives here and nowhere else (import-linter Rule 4b), so provider stays swappable.
        import openai

        return openai.OpenAI(
            base_url=self._config.base_url,
            api_key=self._api_key.get_secret_value(),
            max_retries=self._config.max_retries,
            timeout=self._config.timeout_s,
        )

    def _client_(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        payload = [{"role": m.role.value, "content": m.content} for m in messages]
        last_exc: Exception | None = None
        for candidate in self._candidates(model):
            try:
                resp = self._client_().chat.completions.create(
                    model=candidate, messages=payload, **opts
                )
            except Exception as exc:  # normalize SDK errors → try fallback, else re-raise
                last_exc = exc
                continue
            return self._to_completion(resp, candidate)
        assert last_exc is not None  # the loop always runs ≥ once, so a failure set last_exc
        raise last_exc

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        resp = self._client_().embeddings.create(model=model, input=inputs)
        vectors = tuple(list(item.embedding) for item in resp.data)
        usage = self._usage(resp)
        answered = getattr(resp, "model", None) or model
        return EmbeddingResult(
            model=answered,
            vectors=vectors,
            usage=usage,
            cost_cents=self._config.cost_cents(answered, usage),
        )

    def _candidates(self, model: str) -> list[str]:
        """The model id then, if configured and different, the fallback model id."""
        fallback = self._config.fallback_model
        if fallback and fallback != model:
            return [model, fallback]
        return [model]

    def _to_completion(self, resp: Any, requested_model: str) -> Completion:
        choice = resp.choices[0]
        usage = self._usage(resp)
        # The model that actually answered (may be the fallback) — recorded for honest provenance.
        answered = getattr(resp, "model", None) or requested_model
        return Completion(
            model=answered,
            text=choice.message.content or "",
            usage=usage,
            cost_cents=self._config.cost_cents(answered, usage),
            finish_reason=getattr(choice, "finish_reason", None),
        )

    @staticmethod
    def _usage(resp: Any) -> TokenUsage:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return TokenUsage()
        return TokenUsage(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
