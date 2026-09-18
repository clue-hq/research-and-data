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

## Plan written (same day)
`docs/superpowers/plans/2026-09-18-design-session-continuity.md` — 10 tasks: (1) `clue_design.sessions`
(session id, last-written version, drift note) + `render_leg_turn_prompt(drift_note=)`; (2) envelope
`checkpoint_thread_id` = session id, `first_turn_of_leg`, run row stores the thread, same-document
wait in `_dispatch`; (3) `AgentRuntimeConfig.session_id` + session folder / `turn_dir` / round base
in both substrates; (4) backend scope `sessions/<id>` + own history file admitted; (5) `checkpoint.py`
continue/resume (human message stamped with the run id); (6) executors read the document, CAS base =
current version, drift note, brief/history gating, `session_id` into the runtime; (7) reasoning text
in the trace; (8) `session_sync.py` snapshot/restore via the blob store + manifest sha on the run
result; (9) erasure of the session folder/history; (10) gates + live acceptance. Founder note
2026-09-18: solo mode is the product shape (no author/reviewer sub-agents loaded) — the plan targets
the solo scene graph and the web graph. Facts the plan relies on: deepagents 0.6.12 installs
`SummarizationMiddleware` by default on `create_deep_agent` and explicitly on the solo graph; its
history file is `/conversation_history/<thread_id>.md` under the workspace backend, which the
`active_run_id` fence refuses today; `design_agent_run.checkpoint_thread_id` is deleted by erasure
already; `design_edit_envelope.base_revision` exists for the drift note. No migration, no env key.
