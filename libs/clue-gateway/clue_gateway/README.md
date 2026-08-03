# `gateway/` — the shared LLM gateway client (M0.4)

The single egress for every **direct** LLM response-generation or embedding call the subsystem
makes. The gateway is to models what the `Resolver` protocol is to data sources: provider/model is
**config, not code** (conventions §2/§4). Live text generation uses OpenRouter's OpenAI-compatible
`/responses` endpoint; Clue owns and replays durable conversation state because that endpoint is
stateless on OpenRouter.

## Layout
- **Protocol + value types:** `clue_core.gateway` (`LLMGateway`, `Message`, `Completion`,
  `EmbeddingResult`, `TokenUsage`, `Vector`) — the shared contract every call site imports.
- **Config:** `clue_config.gateway.GatewayConfig` — base URL, per-call-site model ids,
  timeout/retry, fallback model, `stub` flag, and the per-model price table (policy-as-data; folded
  into the layered `Config`).
- **This package:** `OpenRouterGateway` (live, the only place `openai` is imported), `StubGateway`
  (deterministic, offline — the CI path), `TracingGateway` (emits the `llm.gateway_call` span), and
  `build_gateway(config, api_key)` (the stub/live toggle behind the seam).

## Invariants
- **No live call in CI.** `build_gateway` returns the stub when `config.stub` is set *or* no
  `OPENROUTER_API_KEY` is present; CI sets no key.
- **One model SDK egress.** `openai` is imported only here (import-linter Rule 4b); swapping the
  model — or OpenRouter for another OpenAI-compatible gateway — is a config change.
- **Responses, not Chat Completions.** Both direct leaf calls and governed deep-agent calls emit
  native Responses inputs, tool schemas, reasoning controls, and input/output token usage. Endpoint
  contract tests fail if the governed path regresses to `/chat/completions`.
- **Every call is observable.** Stub and live alike emit `llm.gateway_call` with `model`, token
  usage, and `cost_cents`.
- **Carve-out:** Exa Deep / Parallel Task (M11) are tier-4 research-product *resolvers* with their
  own keys — not gateway calls.
