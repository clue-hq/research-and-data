# 2026-10-04 — Agent model fallback chain + first-chunk / call deadlines

Why: ~07:57–08:16 UTC grok-4.6's xAI endpoint stalled (OpenRouter status −2, ~81% uptime): production turns got
zero chunks for 300 s (`agent_timeout`) and a non-streamed design-leg exit-judge call hung 12m48s (keep-alives
defeat the per-read timeout). A raw probe at ~09:40 reproduced it (1 of 3 calls: 310 s, no tokens). grok-4.7 was
healthy (1.4–1.6 s). For our OpenRouter account grok-4.6 has only xAI standard endpoints (Bedrock + xai/zdr/us
filtered by "regional surcharge", priority tiers not opted into), so provider-level fallback had nowhere to go.

Founder ruling: every agent model call falls back to `x-ai/grok-4.7`, then `meta/muse-spark-1.3`.
Added on branch fix/vm-design-workspace-root (PR #96):
- Settings `CLUE_AGENT_FALLBACK_MODELS` (default `x-ai/grok-4.7,meta/muse-spark-1.3`; JSON or comma list; blank =
  none) and `CLUE_AGENT_FIRST_TOKEN_TIMEOUT_S` (default 120; 0 = none) → `default_gateway_config()` →
  `GatewayConfig.fallback_models` / `first_token_timeout_s`. Defaults match .env.example, so production gets them
  from the deploy (no env change).
- `GovernedAgentChatModel`: streamed candidates must send a FIRST chunk within the deadline (stream closed, next
  candidate); later pauses untouched (LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S=300 still governs). All candidates
  stalling fails fast (FirstChunkTimeout is not "transient", so the chain is not retried 3×). Opt-in
  `call_deadline_s` (provider `build(..., call_deadline_s=)`) bounds each non-streamed candidate.
- Exit judge builds with `call_deadline_s=45` (fallback, then its fail-safe CONTINUE).
- Design runtime (`lumen_agent/llm.py::_governed_provider`) reads the same two settings (in its cache key).
- NOT a total deadline for every non-streamed call: profile timeout_s (e.g. 30 s) is a per-read timeout and long
  legit generations would break.
Verified: new tests RED→GREEN (gateway 6, settings 1, judge 1, design 2); tests/gateway, tests/agents, tests/deploy
and the API wiring/naming/preflight/prose suites pass; ruff/mypy/lint-imports clean. Pre-existing design failures
(also fail with the old llm.py): test_tool_surfaces_are_exactly_the_ledger, test_the_account_reads_are_registered_*[True].
Owed: a production observation of a real fallback (Langfuse clue-prod: answering model ≠ requested).
