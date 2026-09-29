# 2026-09-29 — research agents back on Grok 4.6, effort medium

Founder request. Reverses the 2026-09-28 Muse Spark switch (`2026-09-28-research-muse-model.md`),
same seven knobs: RESEARCH / ACCOUNT_RESEARCH / RESEARCH_CLAIMS / RESEARCH_NARRATIVE / ARV2_ACCOUNT /
ARV2_PERSON `_AGENT_MODEL=x-ai/grok-4.6` with `_AGENT_MODEL_EFFORT=medium`, and
`CLUE_ARV2_DISPLAY_MODEL=x-ai/grok-4.6` (+ its settings.py default). `.env` and `.env.example` at
parity. Env-only as the model ruling requires; no profile/prompt change.
Live quality research (account and person) calls run under the gateway role `account_research`,
so `ACCOUNT_RESEARCH_AGENT_MODEL_EFFORT` is the knob that actually applies to them.
The display/reconciliation model has no effort knob: it runs at Grok's provider default.
Muse-specific gateway workarounds (`openrouter_chat.py` schema guidance, no forced tool_choice)
stay; they are model-conditional and dormant under Grok.
Owed: a live research run to confirm served model + reasoning effort in agent_model_call.
