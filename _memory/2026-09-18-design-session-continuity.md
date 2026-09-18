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

## Execution (same day, SDD on `design/account-binding`, worktree san-salvador)
Commits: ae8c1d31c (T1 sessions substrate) · 14c445be3 + 9605f3481 (T2 envelope names the session,
same-document wait, design-memory authority fix) · cde9cfc67 (T3 session folder / turn_dir /
round base) · fc68309a5 (T4 backend scope `sessions/<id>` + own history file admitted) · cb3a459be +
d22a70e69 (T5 continue/resume; `AgentRuntimeConfig.run_id`) · 509ad2b9c + 99b1cc5f0 (T6 executors:
document read, fresh CAS base, drift note, brief/history gating, session only for LEG turns) ·
7650ae745 (T7 reasoning text in the trace) · 90a0c377a (T8 session sync/restore via the blob
store, `effective_runtime_config`) · f6fc4ea43 (T9 purger removes session folder + history; docs) ·
104a02000 (format). Ledger: `.superpowers/sdd/2026-09-18-design-session-continuity/progress.md`.

Rulings taken during execution: T2-1 design-memory authority accepts the session thread; T5-1 the
platform's run id is handed to the substrate so a retried run resumes; T6-1 a direct editor/BFF
turn joins no session (per-run folder, no drift note); T9-1 erasure extends the existing runtime
purger rather than adding a collaborator; T1-1/T1-2/T8-2/T8-3 minor.

Verified first-hand: ruff + format clean on the platform-side files; mypy 867 files clean;
lint-imports 28/0; no-DB runtime + purger suites 433 passed (exit 0); each task's suites re-run
after review while the DB was up (T1–T5). **OWED — the lane Postgres container
`clue-pg-istanbul` (:55040) was stopped externally at 14:20Z and again ~14:40Z (trenton lane
setup in progress); not restarted by the controller.** When it is back, with the stack DOWN:
`tests/design/test_p37_design_entry_consumption.py`, `tests/design/test_design_sessions_db.py`,
`tests/design/test_design_fleet_turns_db.py`, `tests/api/test_design_leg_session_db.py`,
`subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py test_web_turns.py
test_agent_run_write_lock.py`, then stack UP. Then the four live proofs (spec §7) plus the redrive
double-apply walk (T6-2) and a live erasure proof. Pre-existing reds recorded: image-model 401 test
in `test_web_substrate.py`, `test_reference_images_contract` stale SimpleNamespace.
