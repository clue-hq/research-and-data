# 2026-08-24 — Fast Loop Phase 2 §5.4: deterministic autofix below the model

Base `9409fda71` (`integration/frontend-design-part-iv-v4`, P0 fixes + W0
run_metrics merged). Commit **`64b52710d`**. Worktree
`agent-a1e0d4194e1ca18d3`. Parallel agent owns §5.1–5.3/5.5–5.7; `harness.py`
and `prompts.py` were NOT touched.

## What shipped

A code loop (compile → preflight → patch → re-preflight) between the engine and
the author, inside `preflight_design`. The author only ever sees the
post-autofix diagnostic set.

**`apps/agent_runtime/lumen_agent/autofix.py` (new, pure — no I/O, no engine
client).** `plan_autofix(scene, diagnostics)` returns closed-form patches;
`run_autofix(...)` drives the bounded loop with `apply_operations` and
`preflight` injected as callables (which is what makes it unit-testable without
a helper binary).

**Two classes ship, one is excluded:**

| class | codes | patch |
|---|---|---|
| `text_box_hug` | LUMV0902, LUMV0903 | set the failing `fixed` SizeSpec dimension(s) to `hug` |
| `slot_fixture` | LUMV0509, LUMV0800-on-a-slot | `validation.samples = [<bound text node's content>]` |
| ~~`token_fallback`~~ | LUMB0201/0301/0401 | **EXCLUDED — see below** |

## Scouting evidence (this is the load-bearing part)

The engine's `Diagnostic` (`crates/lumen-core/src/diagnostics.rs:35-43`) is
**six fixed keys** — `severity, phase, code, message, subject, hint` — derived
serde, **no structured payload, no extension point**. Every number lives in the
prose. So:

- **No diagnostic reports the needed width/height.** The measurement exists and
  is thrown away: `layout.rs:1159-1172` computes `measured.width/height`,
  compares, discards. `TextMeasureOutput` is not `Serialize`; `TextFit`
  (`layout.rs:1896`) is private and keeps only `fits` + `line_count`. There is
  **no `measure_text` helper action** (33 actions, `main.rs:604-632`), and the
  authoritative `SkiaTextMeasurer` is injected server-side (`main.rs:1179`).
  → Python cannot measure. **`hug` is therefore the fix**: it hands the sizing
  decision back to the engine's own measurer, needing no number from us. This
  is a reinterpretation of the spec's "measured `s(w,hug)` widening", not a
  skip — the spec assumed a payload that does not exist.
- **Token fallback is dead code.** `TokenFallbackPolicy::UseFallbacks`
  (`brand.rs:1594`) is declared and **never constructed**
  (`grep -rn UseFallbacks crates apps packages` → exactly one hit, the
  declaration); `options.fallback` is never read. Preflight computes **no**
  fallback value, so there is nothing for this loop to apply, and choosing a
  substitute colour/type token is judgment. Recorded in code at
  `autofix.EXCLUDED_CLASSES` so nobody re-scouts it.
- **LUMV0800/0801/0802/0803 are each overloaded** across 2–3 meanings, and the
  Python normalizer drops `phase` (`substrate.py:~4700`). Disambiguation is
  `subject.kind`. LUMV0800-on-a-node ("exceeds exportable bounds") has no
  autofix; LUMV0800-on-a-slot does.
- **Freehand text-fit is already downgraded to warning** by the engine
  (`layout.rs:1187-1197`: "a human resizing a pinned text box below its content
  is explicit intent"), and `relayout_final` (`instance.rs:953-975`) downgrades
  the same three codes under clip/ellipsis/ask-agent slot policy. Filtering on
  `severity == "error"` inherits **both** rulings for free.
- Excluded as guesswork: LUMV0904 (max_lines — engine never says the needed
  count), LUMV0810/0812/0813 (fixture fit — no needed size; `line_count` only
  in prose).

## Safety design

- **Derive, never string-parse.** Every patch comes from `(code, subject)` +
  the scene state it points at.
- **Rollback is structural.** The working scene is never mutated before
  verification, so a rejected patch needs no undo path — the original scene and
  diagnostic simply stand.
- **Verification is the engine's, not the planner's** (`autofix._verify`):
  target keys gone AND no new `(code, kind, id)` key AND error count did not
  rise AND total count did not rise.
- **Guards** on `text_box_hug`: error severity, not `locked`, not
  `position_mode == absolute`, dimension currently `fixed` (a `hug` is already
  the answer, a `token` carries a brand binding, a `fill` is stated intent).
- **Bounded:** `max_passes` (default 2) + no-progress exit + never retry a
  diagnostic key. Engine exceptions are treated as "not applicable".

## Wiring

- `preflight_design` (`tools/substrate.py`): the loop runs after the core
  preflight, before the summary. `_run_autofix` injects the two engine calls;
  accepted patches set `self.scene`, append `scene_update_sources`, and go on
  the **proposal ledger** (`_log_scene_operations("autofix", …)`) — the editor's
  Accept replays that list and never sees the working scene, so an unlogged
  autofix would vanish there. Never raises: a failure records
  `autofix_failed` and the preflight proceeds unchanged.
- Payload/artifact: an `autofix` block on the `preflight_design` result +
  `iterations/NNN/autofix.json`, carrying applied AND rolled-back entries with
  reasons (the rolled-back ones are the §5.4 "note that autofix was attempted").
- Config: `LUMEN_AGENT_FAST_LOOP` (default false) +
  `LUMEN_AGENT_AUTOFIX_MAX_PASSES` (default 2, validated `>= 0`) in
  `py_lumen_config`; `AgentRuntimeConfig.fast_loop` / `.autofix_max_passes` with
  an `.autofix_passes` accessor that returns 0 whenever the flag is down, so no
  caller has to check both. **Added here because the parallel core agent had
  not landed it yet — identical name/default-off semantics; merge reconciles.**
- Metrics (closes W0's named residual): `RunMetrics.record_autofix` →
  `autofix_count` / `autofix_rolled_back` / `autofix_by_class` in the snapshot,
  in `summarize_line`, in the CLI trace viewer (`trace.py::_format_summary`),
  and in the run-view README table (`scripts/run_view.py`).
- `retokenize._empty_patch` → public `empty_node_patch` (one shared full-shape
  NodePatch builder; a second hand-written copy of that field list is exactly
  the drift that produces a "missing field" helper refusal months later).

## Verified against the REAL engine (not only the test double)

Ad-hoc probe against `lumen-api-helper` (colombo prebuilt), scenes authored
through the real DSL compiler:

- **Red:** `headline text "…" s(120,20) wrap(false) slot(campaign.headline)`
  → PRE `LUMV0509, LUMV0902, LUMV0903, LUMV0810` → **POST `[]`**, one pass,
  both classes, zero model calls.
- **Rollback:** the same node inside `box fr s(160,60) clip(true)` → planned,
  applied to a copy, re-preflight introduced `LUMV0801` → **rolled back**,
  `POST == PRE` verbatim, reason `"introduced LUMV0801/headline"`.

**That live run caught a real defect in the first version.** The DSL's
`slot(key)` constructor sets `placeholder` to the bound node's own text, so
every DSL-authored text slot arrives with a placeholder AND a LUMV0509. My
first `_has_no_fixture` used the UNION of both codes' preconditions and
therefore declined **every slot the class exists to fix** — the class was dead
on its only production path. Fixed: the precondition is now per-code, matching
each diagnostic's own engine rule (`validation.rs:545` counts only
samples/worst_case/validation.max_length — a placeholder does NOT satisfy
LUMV0509; `layout.rs::slot_fixtures` counts the whole list — a placeholder DOES
satisfy LUMV0800). Pinned by
`test_a_placeholder_blocks_lumv0800_but_not_lumv0509`.

## Tests

`apps/agent_runtime/tests/test_autofix.py` (30) + 3 in `test_run_metrics.py`.
The fake engine is a **miniature** of the real one (it re-derives diagnostics
from whatever scene it is handed, using layout.rs's rules) rather than a
script, so every acceptance is a genuine re-measurement. Covers: red case per
class, rollback case per class, every planner guard, the LUMV0800 overload, the
excluded classes, the pass cap (against a stub planner that would never stop),
`max_passes=0` → zero engine calls, no-progress exit, engine-refusal
degradation, and the four substrate-seam properties (flag-off byte-identical /
applied+committed+ledgered / rolled-back+uncommitted / never fails the turn).

Commands (design toolchain; full design suite NOT run — >1h):

```
PYTHONPATH=<wt>/subsystems/clue-design:<wt>/subsystems/clue-design/apps/api:\
<wt>/subsystems/clue-design/apps/agent_runtime:\
<wt>/subsystems/clue-design/packages/py-lumen-config:\
<wt>/subsystems/clue-design/packages/py-lumen-obs:<wt>/subsystems/design \
<colombo>/.venv/bin/python -m pytest apps/agent_runtime/tests      # 677, exit 0
… -m pytest apps/api/tests/test_run_view.py                        # 83,  exit 0
… -m pytest apps/api/tests/test_scene_turn_persist.py \
            apps/api/tests/test_write_path_governance.py           # 51,  exit 0
```

Base was 644 outcomes; 677 = 644 + 30 + 3. Zero failures, zero regressions.

### ENV NOTE (cost me ~30 min — read before running design tests here)

The only COMPLETE python env on this machine is
`/Users/aryankeshri/conductor/workspaces/research-and-data/colombo/.venv`. The
repo-root `.venv` lacks `py_lumen_obs`/`selectolax`; the design-local
`singapore/subsystems/clue-design/.venv` lacks `sqlalchemy`/`clue_storage`.
**Blending two venvs via PYTHONPATH produces 19 spurious failures** (langchain/
deepagents version skew, all in `test_deepagent_harness` /
`test_deepagent_per_role_models` / `test_run_metrics` harness tests) — I
confirmed they were identical at base before discarding that approach. Use the
colombo interpreter with all worktree paths FIRST on PYTHONPATH so its editable
installs (which point at the colombo checkout) are shadowed. Also: the
agent_runtime and apps/api test trees each ship a `tests/conftest.py`, so they
collide if collected in ONE pytest run — invoke separately.

## For the core §5.1–5.3/5.5–5.7 agent

- **Config collision:** I added `lumen_agent_fast_loop` +
  `lumen_agent_autofix_max_passes` to `py_lumen_config/config.py` and
  `fast_loop` / `autofix_max_passes` / `autofix_passes` to
  `AgentRuntimeConfig`. Same name, same default-off. Reconcile at merge; keep
  the `autofix_passes` accessor (it is the single place the flag and the cap
  are combined).
- **Prompt hook you may want (I did not edit `prompts.py`):** the author's
  preflight result can now carry an `autofix` block. Worth one line in the
  author prompt: *"`preflight_design` may report `autofix` — repairs already
  applied for you, and `rolled_back` attempts whose mechanical fix the engine
  refused. Do not re-apply either; the diagnostics you see are the ones that
  still need you."* Without it the block is silently ignored, which is safe but
  wastes the rolled-back signal.
- The §5.2 micro-loop's "→ [deterministic autofix pass, §5.4] → re-preflight"
  step is **already inside `preflight_design`**. The loop does not need a
  separate step or a separate tool call.

## Residuals / follow-ups (none block)

1. **Not exercised on a live end-to-end run.** Both classes are proven against
   the real helper on hand-authored scenes, but the §7 acceptance run (Magic
   Doc brief, flag on) has not happened. `autofix_count` on that run is the
   real measurement.
2. **`raw_preflight` after an accepted autofix** is the winning re-preflight's
   summary, matched by scene identity. If that match ever fails, `has_errors`
   falls back to the engine's own rule (`any severity == error`,
   `preflight.rs:219`) rather than defaulting to clean — deliberate, because a
   silently-clean summary could let a blocking export error past the P0.3
   finalize guard.
3. **Governance diagnostics are not recomputed** after autofix — they judge the
   pre-resolution authored scene and re-running them on the resolved scene
   would report LUMB0805/0804/0806 regardless of authoring quality (the K4
   artifact). Advisory either way; commented at the site.
4. **`slot_fixture` writes `samples`, never `worst_case`.** The longest
   plausible content is a content judgment, so it stays with the author. If
   LUMV0509 keeps surviving in practice this is the knob to revisit.
5. **A class that keeps rolling back costs two engine calls per attempt** and
   hands back the same diagnostic. `autofix_rolled_back` / `autofix_by_class`
   exist to make that visible; narrow or retire a class whose rejection rate is
   high rather than leaving it running.
6. **Multi-pass is mostly theoretical** under the current verification rule: a
   patch that reveals a new diagnostic is rejected by construction, so a true
   cascade cannot occur. Termination comes from the no-progress exit and the
   never-retry rule; the cap is the last line of defence and is tested as such
   (against a stub planner). Default 2 is cheap insurance, not a schedule.
7. **The archive copy** `lumen_pipeline_archive/retokenize.py` still has the
   private `_empty_patch`. Deliberately untouched (frozen).
