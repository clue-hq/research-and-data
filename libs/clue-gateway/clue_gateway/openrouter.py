"""The live OpenRouter-backed ``LLMGateway`` (M0.4) — the single egress for direct LLM calls.

Wraps **OpenRouter's Responses API** via the OpenAI SDK, which is imported **only here** (the model
analogue of a provider resolver; import-linter Rule 4b keeps every other package from constructing a
model SDK). The client is built behind an injectable ``client_factory`` seam, so the gateway's
*logic* — Responses input mapping, output-text and token-usage extraction, cost computation, and
fallback-model retry — is unit-testable with a fake, while production lazy-imports the real SDK.
The requested ``model`` is config (conventions §4): swapping it is a config change, not code.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import SecretStr

from clue_config.gateway import GatewayConfig
from clue_core.gateway import Completion, EmbeddingResult, Message, TokenUsage

# A zero-arg factory returning an OpenAI-compatible client (duck-typed: ``.responses.create`` and
# ``.embeddings.create``). The default builds the real ``openai`` client; tests inject a fake.
ClientFactory = Callable[[], Any]


class GatewayError(RuntimeError):
    """A gateway call returned a malformed Responses payload.

    OpenRouter can surface an upstream-provider failure in a successful HTTP body carrying an
    ``error`` or no usable text output. Raising a typed error lets the fallback loop treat that like
    any other failure and gives the caller a clear message instead of leaking SDK-shape errors.
    """

    def __init__(
        self,
        message: str,
        *,
        completion: Completion | None = None,
        failure_code: str = "gateway_error",
    ) -> None:
        super().__init__(message)
        # A successful HTTP response can still be terminally unusable (for example, a response
        # that exhausted its output budget before emitting text).  Preserve only the bounded,
        # provider-neutral accounting metadata so durable callers can distinguish that known
        # outcome from a transport ambiguity.  The raw response/error body is deliberately absent.
        self.completion = completion
        self.failure_code = failure_code


class OpenRouterGateway:
    """Live :class:`~clue_core.gateway.LLMGateway` backed by OpenRouter."""

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
        input_items = [
            {
                "type": "message",
                "role": message.role.value,
                "content": [{"type": "input_text", "text": message.content}],
            }
            for message in messages
        ]
        wire_opts = dict(opts)
        # ``LLMGateway`` is provider-neutral and its pre-Responses callers use the conventional
        # ``max_tokens`` option.  OpenAI's Responses API names the same limit
        # ``max_output_tokens``.  Translate at this sole provider boundary instead of leaking the
        # vendor wire name through every judge/supervisor call site.
        legacy_max_tokens = wire_opts.pop("max_tokens", None)
        if legacy_max_tokens is not None:
            if "max_output_tokens" in wire_opts:
                raise ValueError("specify only one of max_tokens and max_output_tokens")
            wire_opts["max_output_tokens"] = legacy_max_tokens
        first_exc: Exception | None = None
        last_exc: Exception | None = None
        for candidate in self._candidates(model):
            try:
                resp = self._client_().responses.create(
                    model=candidate,
                    input=input_items,
                    **wire_opts,
                )
                error = getattr(resp, "error", None)
                if error is not None:
                    detail = getattr(error, "message", None) or str(error)
                    completion = self._to_completion(resp, candidate)
                    raise GatewayError(
                        f"gateway returned an error for model {candidate!r}: {detail}",
                        completion=completion,
                        failure_code="gateway_response_error",
                    )
                if not self._output_text(resp):
                    completion = self._to_completion(resp, candidate)
                    reason = completion.finish_reason or "unknown"
                    safe_reason = "".join(
                        character if character.isalnum() else "_" for character in reason.lower()
                    ).strip("_")[:48]
                    raise GatewayError(
                        f"gateway returned no output text for model {candidate!r}",
                        completion=completion,
                        failure_code=f"gateway_no_output_{safe_reason or 'unknown'}",
                    )
                return self._to_completion(resp, candidate)
            # Normalize SDK / malformed-response errors → try fallback, else re-raise below.
            except Exception as exc:
                first_exc = first_exc or exc
                last_exc = exc
                continue
        assert last_exc is not None  # the loop always runs ≥ once, so a failure set last_exc
        # Re-raise the fallback's error but chain the primary's so the first (more diagnostic)
        # failure is not lost when both candidates fail.
        if first_exc is not None and first_exc is not last_exc:
            raise last_exc from first_exc
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
        usage = self._usage(resp)
        # The model that actually answered (may be the fallback) — recorded for honest provenance.
        answered = getattr(resp, "model", None) or requested_model
        incomplete = getattr(resp, "incomplete_details", None)
        finish_reason = getattr(incomplete, "reason", None) or getattr(resp, "status", None)
        return Completion(
            model=answered,
            text=self._output_text(resp),
            usage=usage,
            cost_cents=self._config.cost_cents(answered, usage),
            finish_reason=finish_reason,
        )

    @staticmethod
    def _output_text(resp: Any) -> str:
        """Extract text from the SDK convenience property or standard output items."""

        text = getattr(resp, "output_text", None)
        if text:
            return str(text)

        parts: list[str] = []
        for output in getattr(resp, "output", None) or ():
            output_type = (
                output.get("type") if isinstance(output, dict) else getattr(output, "type", None)
            )
            if output_type != "message":
                continue
            content_items = (
                output.get("content", ())
                if isinstance(output, dict)
                else getattr(output, "content", ())
            )
            for content in content_items or ():
                content_type = (
                    content.get("type")
                    if isinstance(content, dict)
                    else getattr(content, "type", None)
                )
                if content_type != "output_text":
                    continue
                value = (
                    content.get("text")
                    if isinstance(content, dict)
                    else getattr(content, "text", None)
                )
                if value:
                    parts.append(str(value))
        return "".join(parts)

    @staticmethod
    def _usage(resp: Any) -> TokenUsage:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return TokenUsage()
        return TokenUsage(
            prompt_tokens=(
                getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0
            ),
            completion_tokens=(
                getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0) or 0
            ),
        )
