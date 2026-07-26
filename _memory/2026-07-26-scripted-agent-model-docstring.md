# 2026-07-26 — ScriptedAgentChatModel docstring clarity

Clarified docs on `platform/agents/clue_agents/model.py` after the class purpose was hard to
read from the one-liner docstring alone.

## Change
- Module + class docstring: test-only fake `BaseChatModel`; replays canned `AIMessage`s;
  not production.
- `bind_tools` docstring: accepts binding so agent construction matches prod; tool calls come
  from the scripted messages, not from schemas.

No behavior change.
