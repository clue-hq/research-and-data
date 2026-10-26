# 2026-09-29 — Head-of-ABM continuation, prompt caching and compaction

Spec `docs/superpowers/specs/archive/2026-09-29-head-of-abm-continuation-and-compaction-design.md`;
plan `docs/superpowers/plans/2026-09-29-head-of-abm-continuation-and-compaction.md`.
Branch `codex/ai-ark-committee-discovery-spec-v1`, commits `cdec04fa7..` (local only).

## What shipped

- **Compaction for every governed agent** (`platform/agents/clue_agents/compaction.py`):
  `ClueSummarizationMiddleware` (our own class) + `compact_conversation`, sized from the model's
  real window (OpenRouter catalogue `context_length`, `libs/clue-gateway/clue_gateway/model_windows.py`;
  override `CLUE_AGENT_CONTEXT_WINDOW_TOKENS`). Grok 4.6 (500k) compacts at 450k, keeps ~50k.
  Unknown window → fixed 170k / keep 6 messages. deepagents' own summariser is removed by ONE
  harness profile keyed `clue-openrouter-agent`, excluded by **exact class** — never by the name
  "SummarizationMiddleware", which would also remove ours. Guard test:
  `tests/agents/test_compaction.py::test_every_governed_agent_has_exactly_our_summariser`.
  Evicted history goes to `/work/conversation_history/<graph thread>.md` (graph thread = the
  turn's **execution id**); a role that cannot write `work/` still compacts, keeps no file.
- **Head of ABM v69**: `max_file_bytes` 4 MB (one eviction on a 500k window ≈ 1.6 MB).
- **Continuation** (`platform/api/clue_api/conversation_continuation.py`, engine
  `conversation_turns.py::_continuation_for`): a project-conversation turn resumes the saved
  graph state of the thread's latest *finished* Head-of-ABM turn (finalization `completed` or
  `awaiting_input`, no later failed/cancelled/abandoned/tombstoned event) under the same profile
  sha + resource manifest sha, and appends: gap messages (Head-of-ABM role-scoped view — design
  leg transcripts never, journaled exit summary yes), this turn's cards (L2–L5), the message (L7).
  L1 is not re-sent; its manifest still records it. Receipt payload gains `continuation`.
  Settledness is checked **before assembly** through the turn's own graph (a turn has one
  context receipt; the durable runner abandons a turn on any exception). Otherwise: fresh, as
  before — including when the saved state cannot be read (`agent_turn.continuation_unreadable`).
  Stage-0 trial surface: always fresh.
- Settings (all in `.env.example`): `CLUE_HEAD_OF_ABM_CONTINUATION_ENABLED=true`,
  `CLUE_AGENT_CONTEXT_WINDOW_TOKENS=` (blank = catalogue), `CLUE_AGENT_COMPACT_TRIGGER_FRACTION=0.90`,
  `CLUE_AGENT_COMPACT_KEEP_FRACTION=0.10`, `CLUE_AGENT_COMPACT_TRIGGER_TOKENS=170000`,
  `CLUE_AGENT_COMPACT_KEEP_MESSAGES=6`.

## Measuring

`set -a; source .env; set +a; .venv/bin/python scripts/turn_cache_report.py --since 2026-09-29`
prints each Head-of-ABM turn's first-call input tokens, cached tokens, share, and whether it was
continuable. **Baseline before this change (clue_dubai, 2026-09-28):** the first call caches a
flat 41,472 tokens (the system prompt) or 128/0 after a pause; the history and cards are billed
in full every turn. The share looked 87–94% only because those threads' histories were short.

## Owed (founder-triggered, spends money)

1. Two turns on one chat within a few minutes → the second turn's first call cached ≫ 41,472
   (the whole previous turn), share ≥ ~90% and growing with the thread.
2. A long thread compacts once (look for one summarisation call in `agent_model_call` and the
   file under the thread workspace's `work/conversation_history/`), later turns do not re-compact.

## Known / residual

- Pre-existing failure, unchanged (confirmed on base `c3ce9f7`):
  `tests/api/test_production_context_s31_fleet_db.py::test_real_fleet_chain_keeps_original_pin_through_checkpoint_finalization_and_replay`.
- Pre-existing agents failures, unchanged: `test_runtime::test_real_deepagent_tool_call_uses_exact_governed_descriptor_wrapper`,
  `::test_stage0_final_response_reports_the_gate_and_does_not_claim_a_confirmed_icp`.
- Checkpoints now grow faster (each continued turn's execution stores the conversation so far).
  DSAR erasure already deletes every later turn's checkpoints on the thread (thread closure).
- A true process-death redelivery is proven at the runtime level only
  (`tests/agents/test_runtime_continuation.py`); through the engine an in-process exception is
  journaled `abandoned`.
- Scripted test models must issue unique tool-call ids per turn (a continued conversation drops
  a repeated id) — `_ScriptedModels` in the O6 test now does.
- Deferred minors (final self-review): a failed catalogue fetch is cached as "unknown" until
  restart (170k fallback) and is a one-time sync fetch on the event loop; the image-history cap
  no longer bounds images already inside a continued conversation (compaction does); a turn in
  flight across the release (fresh first attempt, continued redelivery) conflicts on its receipt
  and fails once; compaction is sized to the primary model even if the fallback model answers.

## Live proof 1 — prompt caching (2026-09-29, clue_dubai, thread thr_4a22561d…)

PASSED. Turn 1 (v69, fresh): first call 38,511 input / 0 cached; its last call 58,760 input.
Turn 2 (continued: receipt L6 = 0 items, i.e. no rebuilt history; L1 recorded, not re-sent): first
call 64,060 input / **58,752 cached (92%)** — the whole of turn 1 (58,760) came from cache, vs the
old flat 41,472. No `continuation_fallback` in worker logs. Compaction proof (part 2) still owed.

## Live proof 2 — compaction (2026-09-29, same thread, temporary window override)

- 100k window (turn a95c309a): compacted once — summary call 9,155 input, then 40,326 → 42,198
  on the compacted conversation; offload 263 KB at `work/conversation_history/df3a81cb….md`.
  FOUND: LangChain's `trim_tokens_to_summarize=4000` default meant the summary saw only the last
  ~4k tokens of ~65k evicted. Fixed in `ffc517cfc` (`trim_tokens_to_summarize=None`; founder:
  keep the shape — recent ~10% verbatim, older part summarised, full original offloaded).
- 50k window, with the fix (turn 0d366136): each summary call's input (14.1k, 14.2k) now
  covers its whole evicted part (~10k + ~8k tokens of offloaded text + the summary prompt).
  It compacted TWICE in that one turn: an artifact of the tiny test window — ~30k of the 45k
  trigger is the fixed system prompt + tools, leaving ~15k of room that one turn's tool work
  refills. On Grok's 500k window the fixed part is ~6%.
- Research-quality threads also compacted under the override (every agent compacts, as designed).
- LangGraph warns "Deserializing unregistered type clue_agents.contracts.* … will be blocked in a
  future version" on continuation reads → follow-up: register our types
  (`allowed_msgpack_modules`) before a LangGraph upgrade, or continuation silently turns fresh.
- `.env` restored to `CLUE_AGENT_CONTEXT_WINDOW_TOKENS=` (parity with .env.example); workers
  restarted 22:59. One old worker (PID 962, 50k) was left draining a design-leg turn it had claimed.

## Stop left the design leg `running` (live, 2026-09-29 ~23:08) — fixed `39553a036`

Stopping a design-leg turn cancelled its run and recorded the turn `cancelled/stop_requested`,
but nothing moved the leg out of `running`: the chat showed "Agent is designing", queued every
later message, and a second Stop had nothing to cancel. Only crashes (`_contain_crash`) handed a
leg back; the Stop path (`_finish_stop` → `DesignLegTurnRunner.await_stopped_turn`) never did.
Fix: `await_stopped_turn` now hands a running leg back with its `leg.awaiting_user` frame. Test
`test_a_stopped_design_turn_hands_the_leg_back` (RED→GREEN). The live leg `2ecb9600…` was handed
back by a one-off using the same transition; workers restarted 23:16. Pre-existing, unrelated
failure found: `test_p36_leg_resilience_db::test_a_worker_killed_after_the_design_work_landed_…`
(asserts a crashed leg stays `running`, contradicted by the 2026-09-20 crash hand-back).

## LangGraph "Deserializing unregistered type" — research (no change made yet)

Why: CVE-2026-28277 / GHSA-g48c-2wqr-h844 (Check Point, disclosed 2025-11) — msgpack checkpoint
decoding could rebuild arbitrary Python objects, so anyone able to write checkpoint bytes could
execute code; chained with a SQLite-checkpointer SQL injection (CVE-2025-67644) it was RCE. Also
CVE-2025-64439 (the "json" fallback mode). Our stack: langgraph 1.2.6, checkpoint 4.1.1, Postgres
saver 3.1.0 — patched, running PERMISSIVE (allows all, warns).
What LangGraph offers instead of a hand list: strict mode `LANGGRAPH_STRICT_MSGPACK=true`, which
at graph compile time derives the allowlist from the graph's state schema (walks TypedDict /
Pydantic fields / enums / dataclasses) plus a curated core set. Our `ClueDeepAgentState` types
`constitution: AgentConstitution`, `context_manifest: ContextBundleManifest`, so every warned
type is reachable. Escape hatch for types stored under `Any`: `JsonPlusSerializer(
allowed_msgpack_modules=[(module, name), …])` on the saver's serde. Owed: flip strict on in
`.env`/`.env.example`, run the suites, and add explicit entries only for anything blocked.
