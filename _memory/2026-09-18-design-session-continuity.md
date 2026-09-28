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
after review while the DB was up (T1–T5). The lane Postgres container `clue-pg-istanbul` (:55040) was stopped externally at 14:20Z and
~14:40Z (trenton lane setup); the founder restarted it and the DB gate then ran with the stack DOWN:
`tests/design/test_p37_design_entry_consumption.py`, `tests/design/test_design_sessions_db.py`,
`tests/design/test_design_fleet_turns_db.py`, `tests/api/test_design_leg_session_db.py`,
`subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py test_web_turns.py
test_agent_run_write_lock.py`, — all green (106 + 74 + 66; one T8 test fixed in 9807aa971 to mirror the candidate rebase); stack
UP after. Still owed, founder-triggered: the four live proofs (spec §7) plus the redrive
double-apply walk (T6-2) and a live erasure proof. Pre-existing reds recorded: image-model 401 test
in `test_web_substrate.py`, `test_reference_images_contract` stale SimpleNamespace.

## 2026-09-19 — exit judge v2: free reasoning, three engine actions, artifact + tags shown
Founder ruling: no enum of user intents for the judge — the reasons to leave a session or draft
another artifact are innumerable, and the model must reason freely. `clue_design.exit_judgment`
v2: the model answers `close_this_session`, `hand_message_to_strategy_agent`,
`current_artifact_accepted` and writes `reasoning` (required; blank = malformed = fail-safe
continue; strict booleans). `decide_exit` maps to the engine's unchanged close labels (hand-on →
`out_of_scope` re-delivery, wins over acceptance; accepted → `locked`; else `abandoned`), so the
finish tool, DB CHECKs, journal and frontend are untouched. The prompt (v2) now shows the judge
`<<<CURRENT_ARTIFACT>>>` (title, kind, account) and `<<<TAGS>>>` (labels resolved from
focus_refs: designs marked "(this artifact)", accounts, contacts, files, reference images, a
count of selected elements) and carries scenario guidance: another account / another format /
a tagged design as the basis for something new → close and hand on; a tagged design or account
used inside an edit or question about THIS artifact → stay. The reasoning rides the exit summary
head-of-abm resumes with (`exit_summary(reason, reasoning)`) and the journal; the crash-window
re-entry replays the JOURNALED summary so the governed operation's parameters match. Golden set:
22 fixtures (+5 `new_artifact`, +2 tagged-reference stays); `make eval-design-exit` demo updated.
Not a sub-agent of head-of-abm: one stateless model call in the fleet worker before each leg turn.

## 2026-09-19 — design note: seller + target-account context for the design agent
`docs/superpowers/specs/2026-09-19-design-agent-account-and-seller-context-design.md` (for review;
no plan, no code). Founder rulings: the brief stays the primary channel; the target account is
reached by TOOLS (grant `read_project_accounts@1`, `read_account_research@1`, `read_claims@1` to
the design role, injected into the design runtime through the same platform-loop bridge the
scoped-preference resolver uses); scope is the project, never a tag or an account-id field; the
seller's company/products (and maybe the pinned ICP) land as files under `workspace/seller/` in
the session workspace, listed like the brand card, never called optional; contact claims tool-only
under the existing use-class gate; multiple accounts per leg deferred; no mode switch across
1:1 / 1:few / generic. Skill text (account-adaptation "Reading the account", scene-brief-copy,
tools) needs founder review before landing.

## 2026-09-19 — closing: seller + target-account context shipped (SDD, `design-agent-account-context-transfer`)
The design note above was planned and executed the same day:
`docs/superpowers/plans/2026-09-19-design-agent-account-and-seller-context.md`, ledger
`.superpowers/sdd/2026-09-19-design-agent-account-and-seller-context/progress.md`. Five tasks,
Opus implementers, controller review per task, on branch `design-agent-account-context-transfer`
(created off the merge of PR #65; ruling PRE-3).

Commits: b41124757 (T1 — the three reads granted to the design role in the registry/catalog and
the authority dict) · 7fbcf3361 + 4c6ea695c (T2 — `DesignPlatformReads` over the ARV2 read tools,
paged, with a governed refusal reaching the design side as `refused:<codes>`) · 18c70fef9 (T3 —
host, leg handler, lane driver and executors thread `DesignPlatformReads` into the runtime config,
LEG turns only) · 3199204f1 (T4 — `lumen_agent/platform_reads.py`: the three tools, and the
seller's pinned knowledge written once per pin into a read-only `workspace/seller/` with an
`index.md`) · this commit (T5 — the skill text).

Rulings taken during execution (full text in the ledger): T1-1 the grant is
`read_account_research@2`, not `@1` — `@1` is frozen for replay and granted to nobody; T1-2 the
version fence reads the authority dict rather than a hard-coded role; T2-1 a governed refusal is
`refused:<reason codes>`, never `read_failed`, and `overview_not_written` is an ANSWER about a
researched account while `account_not_researched` is a REFUSAL of `section="claims"`; T2-2 `limit`
on the two paged reads; T2-3 the reads mint ad-hoc executions like the finisher (parenting to the
leg's execution is a later ruling); T4-1 the `seller/` read-only fence keys on the
`workspace/<name>/` segment pair so it holds on the unscoped web backend too; T4-2 the
account-adaptation skill already existed and Task 5 extends it.

T5 itself: `account-adaptation/SKILL.md` gains a "Reading the account" section (find the account,
read its research, ask a narrowed claims question, bind copy to the claim id you read);
`scene-brief-copy` names `seller/index.md` in the one gather; `tools` gains a "Platform reads"
section naming the three tools, the two refusal shapes (`{"error": "refused", "reasons": [...]}`
for a governed refusal, `{"error": "<code>"}` otherwise) and where they are absent (the editor's
own agent box and the CLI). **Skill text landed pending founder review** — the standing rule; the
full text is in the task-5 report,
`.superpowers/sdd/2026-09-19-design-agent-account-and-seller-context/task-5-report.md`.

Verified first-hand at T5: `test_format_skill_library.py` + `test_materialize_concurrency.py`
green (153), `test_scene_solo_runtime.py` green (22) — the frontmatter and a materialized
workspace still validate. One consequence recorded: the insert takes `account-adaptation/SKILL.md`
from 99 to 123 lines, past the stock `read_file` default limit of 100, so a default read of that
skill now returns a partial excerpt and the guidance-read middleware tells the agent to continue
with `offset=100` (`account-identity-composition/SKILL.md` was already 127 lines, so the library
already had one). The new section sits at lines 34-57, inside the first window; the tail that
falls outside it is the file's pre-existing closing paragraphs. The solo-runtime test's read now
passes an explicit `limit` so it still reads the whole resource.

Still owed, founder-triggered: the three live acceptance proofs of the note's §6 — (1) a 1:1 ad
for an account named only in words, whose trace shows `read_project_accounts` +
`read_account_research` and whose direction binds copy to a claim id from that read, with the
reads journaled under the design turn; (2) a generic creative on the same project making no
account read while `seller/` exists in the session workspace; (3) `read_claims` for a contact
answering under the use-class gate with nothing about that contact written into any session file.
