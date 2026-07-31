# OpenRouter Responses API migration — 2026-07-31

## Scope and decision

- Branch: `platform/clue-trial`.
- OpenRouter remains the only live model gateway. No native OpenAI account/key path was added.
- Both model-egress implementations now use the OpenAI-compatible Responses API:
  - direct leaf calls (`OpenRouterGateway`) call `OpenAI.responses.create`;
  - governed DeepAgents calls force `ChatOpenAI(use_responses_api=True)`.
- The provider-neutral `LLMGateway` contract and all call sites remain unchanged.
- OpenRouter Responses is stateless. Clue continues to replay full durable history and does not use
  `previous_response_id` or `store: true`.

## Wire contract

- Requests use typed `input` message items, `max_output_tokens`, native `reasoning`, and flattened
  Responses function-tool schemas.
- Responses read `output_text` / `output[].content[]`, `input_tokens` / `output_tokens`, response
  status, errors, and the actual answering model.
- Embeddings remain on the SDK embeddings resource; this change is text-generation only.
- `langchain-openai==1.4.1` and `openai==2.48.0` are installed. The explicit OpenAI SDK floor is now
  `>=2.45,<3`, matching the LangChain integration's supported major range.

## LangChain capability ruling

- The installed LangChain integration emits native `/responses` traffic and preserves the standard
  capabilities Clue currently needs: reasoning controls, function calls and outputs, streaming,
  structured Responses content, and usage metadata.
- It is not a universal OpenRouter extension layer: provider-specific non-standard response fields
  may not be preserved. Keep those out of platform contracts; if a future feature requires one,
  extend or replace only the gateway adapter after a contract test.
- The regression test verifies `/responses`, native parameters, flattened tools, full stateless
  function-call replay, and absence of `previous_response_id`.

## Verification

- Focused gateway and agent suites: green.
- API/fleet/projection wiring suites: green (DB-gated tests skipped where configured).
- Mypy: 454 source files clean.
- Import-linter: 24 contracts kept, 0 broken.
- `uv lock --check`: green.
- Full pytest completed. One DB test was denied a local socket inside the sandbox and passed when
  rerun with local Postgres access. One unrelated pre-existing failure remains:
  `tests/memory/test_memory_offline.py::test_no_production_code_outside_memory_touches_the_substrate`
  flags `platform/api/clue_api/trial/stage0_runtime.py`.
- Repo-wide Ruff remains blocked by unrelated existing formatting debt in 19 C7-era files and
  `T201` findings in untracked `.claude/.codex` skill copies. All changed Python files pass Ruff.
- Live native-SDK smoke through OpenRouter Responses:
  `openai/gpt-5.6-terra` returned `OK`, 11 input tokens, 5 output tokens, status `completed`.
- Live LangChain function-call smoke through OpenRouter Responses returned `RecordValue` with
  `{"value": "responses-ok"}`, 51 input tokens and 19 output tokens.

## Sources checked

- OpenRouter Responses overview and stateless constraint:
  https://openrouter.ai/docs/api/reference/responses/overview
- OpenRouter Responses basic usage and history shape:
  https://openrouter.ai/docs/api/reference/responses/basic-usage
- LangChain `ChatOpenAI` Responses behavior and provider-extension caveat:
  https://docs.langchain.com/oss/python/integrations/chat/openai
