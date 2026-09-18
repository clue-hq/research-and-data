# 2026-09-18 — Design session continuity (one artifact, one design session)

Founder ruling after studying the design deepagent's per-turn context: the per-turn restart shape
(new run id, new context window, new `run_<id>` folder every turn; D5 "resume-as-restart") is
rejected. Target: one design **document** = one design **session** — one workspace folder, one
continued LangGraph thread (checkpointer keyed to the session), previous turns' tool calls,
results, previews and critiques stay in context. Compaction/offloading = the deepagents library's
own `SummarizationMiddleware` (already installed by the harness) and its tool-result eviction —
**no new mechanism**. Session folder synced to storage at turn end. Reasoning text stored always;
feeding it back is per provider. Sub-agents stay per task. One run per turn, the CAS, one open leg
per thread and the same-document queue (also ruled 2026-09-18) all stay.

Design note: `docs/superpowers/specs/2026-09-18-design-session-continuity-design.md` (for review;
no plan, no code). Structural change is the tool substrate (`tools/substrate.py` mints
`run_id`/`trace_dir` per construction) becoming session-bound and reloading the scene from the
document; `checkpoint.py`'s restart branch becomes the resume branch.

Other rulings the same day: same-document race → queue the second thread (not refuse); cold-start
materialization, embedded design-API worker, inline-lane constant worker id → later; JSON image
cache → only if small. Next discussions in order: full (non-summarized) Head-of-ABM strategy
handoff to the design leg; account binding with claim-store context.
