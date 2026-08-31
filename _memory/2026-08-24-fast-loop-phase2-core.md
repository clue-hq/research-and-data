# 2026-08-24 — Deepagent Fast Loop v1, Phase 2 CORE (§5.1/5.2/5.3/5.5/5.6/5.7)

Worktree `agent-aa9b9b3d374f6b9fd`, base `9409fda71`
(`integration/frontend-design-part-iv-v4`, Phase 1 merged). Spec:
`subsystems/clue-design/docs/deepagent-fast-loop-v1-spec.md` — each §5 section
below now carries an **As built** note in the spec itself; this file is the
session record and the residual list.

NOT in scope here, owned by parallel agents: **§5.4** deterministic autofix,
**§6/§8** the `linkedin-square-ad` format skill.

## The flag

`LUMEN_AGENT_FAST_LOOP` (default **OFF**) → `AgentRuntimeConfig.fast_loop`.
Everything below is gated on it; flag-off is byte-identical and pinned by the
first section of `tests/test_fast_loop.py` (prompt equality against the raw
templates, tool lists, absent metrics keys) plus the 644 pre-existing tests
passing untouched.

Config surface (`py_lumen_config/config.py` → `lumen_agent/config.py`):

| env | field | default |
|---|---|---|
| `LUMEN_AGENT_FAST_LOOP` | `fast_loop` | `False` |
| `LUMEN_AGENT_SCENE_REVIEWER` | `scene_reviewer` (R3 kill-switch) | `False` |
| `LUMEN_AGENT_FAST_LOOP_MAX_LLM_CALLS` | `fast_loop_max_llm_calls` | `45` |
| `LUMEN_AGENT_FAST_LOOP_WALL_CLOCK_S` | `fast_loop_wall_clock_s` | `600.0` |
| `LUMEN_AGENT_FAST_LOOP_INNER_ITERATIONS` | `fast_loop_inner_iterations` | `4` |
| `LUMEN_AGENT_FAST_LOOP_PINNED_KNOWLEDGE` | `fast_loop_pinned_knowledge` | `None` |

`AgentRuntimeConfig.scene_reviewer_enabled` = `(not fast_loop) or scene_reviewer`
is the ONE expression of R3. Budgets fail loudly at startup if non-positive.

## What landed where

- **§5.1** `lumen_agent/frame.py` (new). `build_frame_payload(tools)` → the
  author's SYSTEM prompt (cache-stable prefix, paid once). Brand card + resolved
  **type ramp** + scene digest + asset index + pinned knowledge **bodies**.
  Ramp floors are the spec's own §8 numbers as fractions of the canvas short edge
  (0.0593·1080=64 display, 0.0204·1080=22 body); kit sizes scale by
  short_edge/1080 clamped [0.5,4.0]; **no page yet → fractions + worked 1080
  example, never invented dimensions** (create turns start with zero pages).
  Round direction is NOT composable at assembly, so §5.1's other half is
  prompt-side: direction inline in the `task` delegation + an explicit
  no-`ls`/`glob`/`grep` rule.
- **§5.2** `tools/render.py` — `make_render_preview_tool(tools, checkpoint=…)`,
  two instances; author gets `checkpoint=False`. `tools/substrate.py` —
  `compile_dsl_block` refuses past the per-round inner-iteration cap.
  `prompts.py` — the compile→preflight→render→LOOK→self-audit→one-batched-fix
  loop, render/look mandatory.
- **§5.3** `harness.py` — the reviewer subagent is filtered out of `subagents`
  under the flag (tool-absence, M8D-R1 pattern); its prompt/model/ToolStrategy
  all still built. `prompts.py` — orchestrator steps 5–7 replaced by judging
  `critique.json`; author writes it.
- **§5.5** `prompts.TOOL_ROUTING_RULE`, once per flag-on prompt.
- **§5.6** `lumen_agent/budget.py` (new) + `run_metrics.py` +
  `harness._finalize_on_budget_exhausted`.
- **§5.7** `prompts._ORCHESTRATOR_CLARIFICATION_GATE` +
  `harness._materialized_skill_index`.

## Decisions worth not re-deriving

1. **Author renders do NOT checkpoint** (the P0.4 interaction the task flagged).
   A checkpoint must keep meaning "a round was ACCEPTED and its scene is
   durable". The author renders MID-round by design — its first render of a
   round is often of a design its own next self-audit rejects — so committing
   those would weaken the claim to "somebody rendered" and mint a document
   version per inner iteration instead of per accepted round. The frontend reads
   checkpoints as progress; P0.4's replay guard reads the last as best surviving
   state; both depend on "accepted". Implemented as a closure flag on the tool
   (the substrate cannot tell who is calling — the tool object is the only thing
   that differs between roles). Documented at the trigger site in `render.py`
   and amended into `tests/test_scene_checkpoint.py`'s docstring, which used to
   assert "render_preview is ORCHESTRATOR-ONLY".
2. **Budget = langchain callback with `raise_error = True`.** Verified in
   langchain-core 1.5.1 `callbacks/manager.py::handle_event`: without that flag a
   handler exception is logged and swallowed, i.e. the ceiling would silently
   become a suggestion. Checked before counting (45 ⇒ 45th runs, 46th refuses);
   sticky. Announced outside the budget's own lock to avoid a lock-order
   inversion with the logger/metrics locks.
3. **Inner-iteration cap = tool REFUSAL, not exception.** Checked before the
   iteration bump, so a refused compile costs no iteration, no metric and no
   scene touch; nothing rolls back. An exception here would have discarded a
   perfectly good scene, which is the exact P0.4 failure mode.
4. **Reviewer model still built while quarantined.** Costs nothing, keeps the
   role registered with run_metrics, so a quarantined run reports the reviewer at
   *zero calls* rather than omitting it — which `run_metrics.register_role`'s own
   docstring already anticipated as the interesting fact.
5. **Graceful finalize is status-honest**: `completed_with_warnings` only when
   the scene actually has nodes; `failed` otherwise; never `accepted`. A run that
   already wrote `final.json` keeps its own verdict.
6. **`agent_protocol`** is the GapArea used for a budget stop — the enum has no
   budget member and a made-up label only earns a `[reported area: …]` prefix.

## The format-skill interface (defined for the §6 agent)

Full table in the spec's §5.7 as-built note; declared in
`harness._materialized_skill_index`'s docstring, referenced BY NAME in the
flag-on orchestrator prompt so a §6.1-compliant skill plugs in with zero code
change:

- frontmatter `name:` / `description:` (description is what the composed skill
  index shows and what the orchestrator matches on — it must carry the trigger
  phrases);
- frontmatter `required_decisions:` — optional `{id, question, default}` list;
- frontmatter `pinned_knowledge:` — optional knowledge_docs-relative paths;
- section **`## Defaults & required decisions`** → the §5.7 gate reads this;
- section **`## Self-audit checklist`** → what §5.3's `critique.json` scores
  against.

Honest gaps in that interface: `required_decisions:` is declared but not consumed
in Python (the orchestrator reads the prose section); `pinned_knowledge:` cannot
be honoured yet because the frame payload is composed at ASSEMBLY time while
skill selection happens at runtime — `LUMEN_AGENT_FAST_LOOP_PINNED_KNOWLEDGE` is
that seam until pre-dispatch selection exists.

## Tests

New: `apps/agent_runtime/tests/test_fast_loop.py`, **53 tests** — flag-off
byte-identity (prompts, tool lists, metrics keys, and "fast-loop args with the
flag off change nothing"); author toolset includes render; the two-instance
checkpoint split; author renders still file into the round dir; inner-iteration
cap + per-round reset + absent when flag off; reviewer not dispatched;
kill-switch restores it intact; reviewer role still metric-registered;
orchestrator judges the self-audit / keeps review steps under the kill-switch;
tool-routing rule present flag-on and absent flag-off; frame payload sections +
pinned bodies + pin override + bad pin skipped; type ramp at 1080 / 2160 / no
canvas; scene digest cap; budget call + wall-clock limits, stickiness, metrics,
`raise_error`; graceful finalize both outcomes and the already-finalized case;
clarification gate both branches + tool-presence unchanged; skill index composed,
wrapped-description parsing, broken-file tolerance.

Commands (this env — the shared venv's editable installs shadow worktree code,
so PYTHONPATH must point at the worktree; `clue_design` lives in
`subsystems/design`; `selectolax` is missing from the repo-root `.venv`, so use
the colombo workspace venv):

```
cd <worktree>
W=$PWD
export PYTHONPATH="$W/subsystems/clue-design/apps/agent_runtime:\
$W/subsystems/clue-design/packages/py-lumen-config:\
$W/subsystems/clue-design/packages/py-lumen-obs:\
$W/subsystems/clue-design/apps/api:$W/subsystems/design"
cd subsystems/clue-design
<colombo>/.venv/bin/python -m pytest apps/agent_runtime/tests -q          # 697 pass
<colombo>/.venv/bin/python -m pytest apps/api/tests/test_scene_turn_persist.py \
    apps/api/tests/test_run_view.py apps/api/tests/test_web_turns.py -q   # 77 pass
```

Baseline before any edit: 644 pass, exit 0. After: 697 pass (644 + 53), exit 0.
The full design suite (>1h) was deliberately NOT run. The api and agent_runtime
trees each ship a `tests/conftest.py`, so they must be invoked separately.

## Residuals / follow-ups

1. **§7 acceptance is unrun** — the Magic Doc brief end-to-end under the flag,
   against the frozen 178 calls / 43m18s, needs a live stack. Nothing here has
   been exercised against a real model.
2. **The §5.6 watchdog is partial.** Nothing interrupts a call already in flight;
   the budget only refuses to START another. Replacing L3's SDK socket-silence
   timeout with a true wall-clock watchdog thread is still open.
3. **Subagent exception swallowing is unverified against the real deepagents
   `task` tool.** If it converts `BudgetExhausted` into a tool-error string, the
   orchestrator's next call raises against the same sticky budget — so the cost
   is one extra hop, not a runaway. Worth confirming on the first live run.
4. **The author's `critique.json` is model-written free text**, exactly as the
   reviewer's was — no Python reads or validates it (P0.4's forensics established
   that nothing reads `rounds/**`). If the self-audit needs to become
   load-bearing, that is a new mechanism, not a tightening of this one.
5. **`pinned_knowledge:` / `required_decisions:`** — see the interface gaps above.
6. **`_skill_description` is a hand-rolled two-key frontmatter reader**, not
   YAML. It handles the wrapped-continuation form the existing skills use and is
   tested; a skill using block scalars (`|`/`>`) or quoting oddities would render
   oddly in the index (never crash).
7. **Author renders bump `_preview_scene_version` / the L4b unchanged-scene
   fact.** Intended (the orchestrator should see "unchanged" when the author
   changed nothing since its own last render), but it means the orchestrator's
   verification render can now report `unchanged` where it previously always saw
   fresh pixels. Harmless — the checkpoint only fires on a validated raster
   either way — but worth watching on the first live run.
8. **Web turns untouched** by design (§3 non-goal): `harness_web` calls
   `_instrument` without a budget and never reads the flag.
