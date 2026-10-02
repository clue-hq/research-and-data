# R2 facts — the M8D agent runtime, why R2 does NOT reuse it, catalog + model + prompt assembly (scouted 2026-09-08)

## DECISION (Fable, 2026-09-08): R2 runs its own `langchain.agents.create_agent` loop inside `clue_api/arv2/`,
not the M8D `EntityResearchAgentFactory/Runtime`. Facts that force it:
1. `EntityResearchStopPolicy` (`platform/agents/clue_agents/entity_research_contracts.py:124-129`) has hard bounds
   `max_model_rounds le=64`, `max_tool_calls ge=1 le=256` (required), `max_parallel_tools le=16`,
   `max_consecutive_zero_yield ge=1` (required) — the founder ruling (100 rounds, 50 per round, NO total or
   zero-yield cap) is unrepresentable.
2. `EntityAgentToolSurface._surface_is_complete` (`libs/clue-core/clue_core/entity_research.py:242-272`) hard-codes
   the M8D tool-name allowlist; any new tool name is rejected.
3. Caps use `ModelCallLimitMiddleware(..., exit_behavior="error")` → `ModelCallLimitExceededError` raises and the job
   fails (`entity_research_runtime.py:1017`, `:1281-1288`); the ARV2 failure law needs "end + finalize".
4. It is the quarantined old lane (`CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false`, master plan §11) and is bound to
   `entity_research_job` rows (journal/guard/batches/checkpointer). Master plan §9 R2: "own driver".
What IS copied (as patterns, not imports): sha-pinned profile ref (`agent-profile:<name>:<version>` + sha256 of
`profile.md`), resource bundle = profile + prompt + skills each `(kind, ref, version, sha256, body)`, the system
prompt assembly (profile section, prompt body, skill sections, an immutable context block), the refusal envelope
`{"error":"governed_research_rejection","code":…,"detail":…,"recoverable":true,"guidance":…}`, identical-read
refusal (`_MAX_IDENTICAL_READS = 3`, code `identical_read_loop`), empty-turn repair (`empty_model_turn`, 3 repairs).

## LangChain facts (`.venv/lib/python3.12/site-packages/langchain/agents/middleware/`)
`ModelCallLimitMiddleware(thread_limit=None, run_limit=None, exit_behavior: Literal["end","error"]="end")` —
`"end"` ends the graph gracefully (model_call_limit.py:126-183). `ToolCallLimitMiddleware(tool_name=None,
thread_limit, run_limit, exit_behavior="continue"|"error"|"end")` (tool_call_limit.py). `create_agent(model, tools,
system_prompt, middleware, response_format, checkpointer, name)`. `StructuredTool.from_function(coroutine=fn,
name=, description=, args_schema=PydanticModel, handle_validation_error=..., handle_tool_error=True)`; handler
`async def f(**values) -> str|dict`. `AgentMiddleware` hooks: `abefore_model(state, runtime)` with
`@hook_config(can_jump_to=["end"])` returning `{"jump_to": "end", ...}`; `aafter_model`; `awrap_model_call`;
`awrap_tool_call`.

## Model
`clue_agents.ports.AgentModelProvider.build(*, model_id: str, timeout_s: float, max_retries: int, max_output_tokens: int,
temperature: float, role: str | None = None) -> BaseChatModel` (`platform/agents/clue_agents/ports.py:164-176`).
Production impl `clue_gateway.OpenRouterAgentModelProvider(config: GatewayConfig, api_key: SecretStr, *, http_client=None,
http_async_client=None)` (`libs/clue-gateway/clue_gateway/agent_model.py:581-598`); `build` validates
`timeout_s <= config.timeout_s`, `max_retries <= config.max_retries`, `0<=temperature<=2`. Composition helper:
`clue_api.agent_model_wiring.build_agent_model_provider(*, config: GatewayConfig, secrets: Secrets) -> AgentModelProvider`
(outside arv2 — arv2 constructs `OpenRouterAgentModelProvider` directly; `clue_gateway` is on the allowlist).
Gateway effort env: `f"{role.upper()}_AGENT_MODEL_EFFORT"` read inside the gateway when `role` is passed
(`agent_model.py:798-801`) → pass `role="arv2_account"` so `ARV2_ACCOUNT_AGENT_MODEL_EFFORT` applies.
Model id env: R2 reads `ARV2_ACCOUNT_AGENT_MODEL` itself (the deepagents `_env_model_policy` path is not on this lane).
`.env.example:213-238` is the consolidated "Agent model configuration" block (add both lines there).
`GatewayConfig` (`libs/clue-config/clue_config/gateway.py:76`); settings builder in the same file (see plan Task 5);
`timeout_s=settings.gateway_timeout_s` (60 in this deployment).

## Existing catalog (shape reference only)
`platform/agents/catalog/entity-research/account/{v1,v2}/profile.md` (3 header lines `role:`, `framework:`,
`contract:` + one paragraph), `v3/{prompt.md,skill.md,manual.md}` (skill/manual open with bare `name:`/`version:`
lines; NOT parsed — only bytes are hashed). `entity-research/**` is loaded by plain `Path.read_text` + sha256, not by
`clue_agents.catalog`. `docs/agents/skill-and-profile-authoring.md` §"Safe change workflow" (:75-108): copy to next
version, never edit a published version; hash with `shasum -a 256`.

## Workspace
The create_agent runtime has NO filesystem workspace; resources reach the model as system-prompt sections. R2 does
the same: ICP text, persona text, catalog menu, already-established block, directive → system-prompt context
sections + `read_account_state` on demand. (`WorkspaceSeedFile`/`materialize_bytes` belong to the deepagents turn
runtime and are not used here.)
