# 2026-06-19 — OpenRouter as the single LLM gateway (spec docs + Linear)

## Decision
All *direct* LLM calls the subsystem makes itself route through ONE shared `LLMGateway` client
wrapping **OpenRouter** (OpenAI-compatible). One `CLUE_OPENROUTER_API_KEY`; the model id is config
per call site (not code); every call emits an `llm.gateway_call` trace span (token + cost_cents);
deterministic stub mode in CI (no live calls). The gateway is to models what the `Resolver` protocol
is to data sources. Owned by **M0.4** (config/secrets); the "LLM client from M0" that M9 etc. referenced
is now concretely this gateway.

## Direct-LLM call sites → gateway
M5.2 ICP synthesis · M6.1 discovery query-planning · M8.3 committee role-inference ·
M9.3 faithfulness judge · M9.6 eval rubric scorers · M12.1 value-narrative positioning.

## Carve-out (important, technical, not a preference)
**Exa Deep (M11.1) and Parallel Task (M11.2) are NOT routed through OpenRouter.** They are tier-4
*research-product* APIs (grounded synthesis), not OpenAI-compatible chat/completion endpoints, so they
stay as their own resolvers behind the `Resolver` protocol with their own keys
(`CLUE_EXA_API_KEY` / `CLUE_PARALLEL_API_KEY`). OpenRouter is a chat/completion router and cannot proxy
them. Only a future tier-4 resolver implemented as a *direct* model call would use the gateway.

## Files changed (spec docs + config; no app code touched)
- `docs/specs/_conventions.md` — §2 new "One LLM gateway egress" rule; §4 `LLMGateway` protocol block;
  §6 stack line names OpenRouter.
- `docs/specs/M00-…` — M0 intro deliverable + M0.4 (OPENROUTER_API_KEY in secrets, the gateway client
  deliverable, seam accessor, acceptance criterion) + M0.5 `llm.gateway_call` reserved span + M0.6 stub.
- `docs/specs/M05-…` §M5.2, `M06-…` §M6.1, `M08-…` §M8.3 (+ milestone gateway/resolver split note),
  `M09-…` §M9.3/§M9.6 (+ M0 dep note), `M11-…` carve-out (Explicitly-NOT bullet + M11.1/M11.2),
  `M12-…` §M12.1.
- `docs/architecture/clue-hq-research-layer-architecture.md` §12 stack — added an "LLM gateway" row +
  noted the judge routes through it (kept consistent with conventions §6, which mirrors substrate §12).
- `.env.example` — added `CLUE_OPENROUTER_API_KEY` (CLUE_ prefix, per the Secrets convention).

## Linear (Research Subsystem project) — annotated, NOT description-rewritten
Added one comment recording the decision + spec backlink to each LLM ticket:
ENG-120 (M0.4, gateway owner), ENG-107 (M5.2), ENG-128 (M6.1), ENG-142 (M8.3), ENG-139 (M9.3),
ENG-156 (M9.6), ENG-158 (M12.1), and the **carve-out** comments on ENG-143 (Exa Deep) / ENG-148
(Parallel Task). Comments were chosen over editing descriptions to avoid clobbering the authored bodies;
the authoritative detail lives in the now-updated specs the bodies already link to.

## Notes / follow-ups
- No application code changed (still no LLM SDK dependency; gateway lands when M0.4 is implemented).
  When M0.4 is built: add the OpenRouter client to the shared package, wire the `llm.gateway_call` span,
  and the CI stub. `pyproject` will then need an OpenAI-compatible client dep (e.g. `openai`/`httpx`),
  added under the resolvers/gateway import-rule boundary.
- Env var spelled `CLUE_OPENROUTER_API_KEY` to match `Secrets` env_prefix=CLUE_; specs say
  `OPENROUTER_API_KEY` generically — keep these reconciled when implementing.
- Open question left for the user: whether embeddings (pgvector candidate sets / client-knowledge
  retrieval) should also egress through this gateway or a dedicated embedding provider — flagged, not
  decided. Gateway `embed()` is in the §4 contract as an option.
