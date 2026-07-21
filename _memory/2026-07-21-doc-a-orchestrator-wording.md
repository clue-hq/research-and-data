# 2026-07-21 — Doc A §1.4 orchestrator wording

Tightened Doc A (`clue-hq-platform-agent-runtime.md`) §1.4 bullet 1: "one LLM loop" → the
deepagent orchestrator (`create_deep_agent`), with an explicit "not a hand-rolled single LLM
loop" note. Aligns the bullet with the section intro (`deepagents`/LangGraph stack) so readers
don't collapse the assembly into a bare ReAct loop.
