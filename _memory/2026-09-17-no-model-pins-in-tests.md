# 2026-09-17 — Ruling: no test asserts WHICH model a default or pin names

Founder ruling (2026-09-17): which model an agent, judge or synthesis step uses is an env
setting (`<ROLE>_AGENT_MODEL`, `CLUE_*_MODEL`), and today everything is `x-ai/grok-4.6`. A test
that asserts a default or catalog pin equals a particular model is useless and gets removed; what
a test may check is that the id is WELL-FORMED. The motivating defect: `design@v1` carried
`openai/x-ai/grok-4.6` (doubled vendor prefix, fixed in `1899e893d`) and the pinning test was
asserting an older wrong value instead of the shape.

## What changed
- `tests/_model_ids.py`: `assert_well_formed_model_id(value, *, routed=True)` — one vendor segment
  then the model name for OpenRouter-routed ids; provider-native shape for e.g. the Gemini
  transcription model. Rejects the doubled prefix, blanks and whitespace.
- Pins replaced by shape checks: `tests/test_config_settings.py` (synthesis default literal,
  stage0 extraction model), `tests/gateway/test_gateway.py` (code-default judge model),
  `tests/api/test_agent_registry_wiring.py` (design profile pin),
  `tests/arv2/test_settings.py` (five ARV2 model fields → `MODEL_ID` sentinel; the .env.example
  parity check now compares the example to the live code default instead of a literal),
  `tests/arv2/test_onboarding_settings.py` (reconcile model; the synthesis-agent env lines are
  checked for presence and shape, not value).
- `tests/api/test_home_project_bootstrap_db.py` echoes `PROJECT_CONVERSATION_MODEL_ID` instead of
  a literal.
- Left alone on purpose: tests that feed a model string in as a fixture and assert it comes out
  the other side (gateway receipts, Langfuse attrs, cost ledger, env-override mechanics). Those
  test plumbing, not a model choice.

## Follow-up (not done)
- `chat/router.py:580-582` hardcodes the conversation profile's label/description as "Grok 4.6";
  if the model moves via env the label will lie. Derive the label from the model id or make it
  a setting — founder's call.
