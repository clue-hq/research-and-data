# 2026-08-24 — Deepagent speed/quality forensics → Fast Loop v1 spec draft

## What happened
Analyzed the 2026-08-24 Stuttgart manual-test logs (platform-api / design-api /
fleet-worker / fleet-worker-2 + `.deepagent-workspace` run traces) for why
scene-ad generation took 20–43 min. Then studied the founder-supplied Moda.app
architecture/skills transcript and drafted the restructure spec.

## Established facts (measured, dedup'd — fleet logs write every line twice)
- Wall time ≈ 99% sequential LLM calls in both long runs. Engine is ms-fast
  (compile ~100ms, preflight ~250ms); APIs healthy.
- `run_9269a8…`: 20m42s, 68 calls, 4.46M input tokens, died on OpenRouter 403
  (weekly key limit) at finalize; save-on-finalize discarded a valid scene.
- `run_7d4ba182…`: 43m18s, 178 calls, 13.5M input tokens, 3 review rounds,
  first preview only at +15.4 min; "succeeded" but export blocked by LUMV0820.
- Call sinks: ~75 calls to first preview (asset-preview bug → disk hunting:
  71 reads/43 greps/22 ls; LUMV0820 impossible-repair probing), 25-call
  reviewer round-trips ×2–3, micro-edit drip (14 compiles ≈ 24 calls for
  iterations 21–34).
- Bugs confirmed: (1) `tools/substrate.py` ~1442 concatenates durable-storage
  refs onto engine-cache root → every `view("asset:…")` = `asset_missing_file`;
  (2) LUMV0820 unrepairable in DSL yet blocks all export; (3) export failure
  message is screen-reader-only in `image-export-menu.tsx`; (4) scene text
  inspector (`AdTextInspector`) has NO content field and canvas double-click
  text is out of AD4.C v1 scope — text *content* uneditable in scene editor
  (write path exists: `structuredEdits.modifyNodeEdit` text.content);
  (5) fleet-worker logs duplicated line-for-line; (6) frontend SSE 5-min body
  timeout leaves stale "Working" UI.
- `render_preview` is orchestrator-only (`harness.py`); author has `view` but
  cannot render its own edits — root of the review round-trips.
- Moda study: single agent, no reviewer, pushed per-turn context (canvas
  index + computed type scale + skill in force), declarative whole-page
  markup, mandatory self-screenshot, ~100-line opinionated format skills
  (defaults + named tests + banned lists + override clause). ~4–5 calls/page.

## Founder rulings (2026-08-24)
- Variants: wanted soon, but do NOT change single-artboard model now (R1).
- Clarifying questions: conditional — assess brief sufficiency, ask 2–4
  batched questions only when material gaps exist, else defaults+record_gap (R2).
- Hard requirement: generation ≤10 min, target ~5.
- Direction agreed in discussion: retire separate reviewer for scene turns,
  fold checklist into author self-audit (author gets render_preview).

## Artifact produced
`subsystems/clue-design/docs/deepagent-fast-loop-v1-spec.md` — DRAFT awaiting
founder review. Contains: frozen baseline + gates (≤45 calls, ≤10 min, TTFP
≤4 min), P0 bug fixes (asset previews, LUMV0820 repairability, export
severity split, checkpoint commits), loop redesign (frame payload, author
micro-loop with render, reviewer→self-audit, deterministic autofix, tool
routing rule, budgets, conditional clarification), format-skill library spec
+ full `linkedin-square-ad` pilot skill draft, instrumentation/rollout plan,
open questions.

## Phase 1 EXECUTED + INTEGRATED 2026-08-24 (same day, later session)
Spec ratified (R1–R6 recorded; commit `59b557931`). Five Opus worktree agents
ran Phase 1 in parallel; EVERY one was independently verified before merge
(base ancestry attested, diffs read, tests re-run by the orchestrator,
red-cases proven for P0.1 asset-preview E2E and the obs cross-package guard).
Merged into `integration/frontend-design-part-iv-v4` as five --no-ff merges
ending `b0ecf2f16`:
- P0.1 `30481ca51` — asset previews resolve BY DIGEST via
  `clue_design.storage.location_digest`/`blob_path_for_digest`; PLUS the
  missing durable→cache read-through in `brand_kit_asset_manifest` (2nd real
  defect). Archive copy (`lumen_pipeline_archive/tools.py:1218`) still buggy,
  deliberately (frozen).
- W0 `19144ee25` — `run_metrics.py` accumulator; summary into run.jsonl +
  metrics.json + run_event stream + run-view README; emits in finally, never
  raises. Web harness deliberately unwired; `autofix_count` awaits §5.4.
- P0.2/P0.3 `d1c9884db` — LUMV0820 root cause: DSL's only slot constructor was
  text_short → image slots born policy-less. Fixed at birth
  (`ImagePolicy::default()`) + `#slot:key image_policy(...)` (compile-time
  guard `LUMD0276`); `export_policy.py` fail-closed blocking/advisory split
  (advisory = only LUMV0820, justified); finalize refuses on blocking export
  errors. Engine stamp now `4efb25b7eb70`; wasm rebuilt, HANDSHAKE OK.
- P0.4 `457287dfa` — round acceptance exists nowhere in code (prompt-driven
  loop); checkpoint trigger = orchestrator's per-round `render_preview` ok;
  `_LegSceneCommitter` owns every durable write; replay guard
  `scene_checkpoint_committed`/`_own_checkpoint_version`; leg-only. Residual:
  takeover refuses-after-checkpoint rather than resuming (goes with §5.6).
- small-bugs `15c713a26`/`bf425d092`/`3d696570e` — visible export failure
  (`role="alert"`, reuses inspectorStatusError idiom; was a re-lift REGRESSION
  — standalone editor was never broken); one root console handler cross-package
  (root cause: two StreamHandlers, NOT double registration); undici
  `bodyTimeout: 0` dispatcher for SSE proxies only.
Verification env notes: shared venvs' editable installs shadow worktree code —
run with PYTHONPATH pointing at worktree copies; 2 `test_asset_custody` +
2 `test_fleet_wiring` failures are PRE-EXISTING at base in this env (proven at
59b55793 via throwaway worktree — clean up /tmp/verify-base-59b55793 when done).
Worktree provisioning served 3/5 agents a stale base (5ea7a879); all
self-corrected; final commits all verified on 59b55793.
Integrated gates green: agent_runtime 643 passed; frontend scene-export 52/52 +
lint clean; obs 7/7; dsl_compiler 135; helper rebuilt; HANDSHAKE OK.
FULL-SUITE GATE VERDICT (completed later same session): Rust 815 passed across
workspace + all lumen-core targets EXCEPT `visual_regression` (does not COMPILE
— baseline PNGs absent from the repo; pre-existing) and 4 `lumen-skia` goldens
(golden_effects_card/golden_a4_effects/+2 — fail identically at base;
pre-existing missing-golden class). apps/api full: 669 passed / 18 failed —
ALL 18 reproduce at base 59b55793 with a BASE-BUILT helper (16 =
test_custom_component_{compiler,publish,runtime}+test_agent_custom_components,
need the constrained-worker runtime this env lacks; 2 = test_asset_custody
public-route env cases). ZERO regressions from the five merges. §3 gate met.
TRIAGE TRAP recorded: a base-control run MUST use a base-built
`LUMEN_CORE_HELPER` — pointing base code at the integrated helper produced ~30
false failures (engine-stamp mismatch) before being caught.

## Not done / next
- BASELINE RE-RUN (§7 calibration): run the Magic Doc brief end-to-end on this
  branch, compare run_metrics vs frozen 178 calls/43 min. Needs a live stack.
- Phase 2: `LUMEN_AGENT_FAST_LOOP` loop redesign + `linkedin-square-ad` pilot
  skill (spec §5/§6/§8).
- High-value one-liner follow-ups found by agents, NOT yet fixed: stale
  "Working…" render (`use-project-chat-controller.ts:477` missing
  `attached.current.delete(turnId)`), reconnect budget never resets
  (`chat-stream.repository.ts:123`), backend SSE keepalive
  (`chat/stream.py:442`), editor TS hardcodes `image_policy: null`
  (`operations.ts` — the remaining born-broken hole), advisory-warnings UI is
  a TWO-COPY job (platform + subsystem exportRunner both drop `warnings` at
  the parser; FE13 precedent at `onboarding.ts:123`).
- Scene text-content editing needs a founder presentation ruling (dummy
  frontend is presentation truth).
- Stuttgart `.env` was set to `LUMEN_AGENT_REASONING=medium` (other session).

## P0.4 checkpoint commits — DONE 2026-08-24 (worktree `agent-a39b7db549641ba99`)
Spec §4 P0.4 implemented; the spec entry now carries the as-built record.

**Where round acceptance turned out to live.** Nowhere, as code — the scene
orchestrator loop is entirely prompt-driven (`prompts._ORCHESTRATOR_TEMPLATE`
steps 3–8, one `agent.invoke` at `harness.py:381`, `recursion_limit=200`). No
Python reads `rounds/index.md` or `rounds/round_N/critique.json`; both are
model-written free text. `LumenTurnState.current_round` is never written after
init. So the only Python-observable round boundary is **`render_preview`** —
orchestrator-only (author tool list has no render) and run once per round at
prompt step 5. A render returning `status=ok` with no validation errors is the
acceptance signal used. `export_preview_bundle` already refuses unresolved
token paints, so reaching it also means preflight ran after the last mutation.

**Write path.** Reused exactly: `design_apply_operations` →
`_advance_scene_state` → `HybridRepository.update_document_state` →
`clue_design.documents.update_document_state`. New `_LegSceneCommitter` in
`lumen_api/main.py` owns every write the turn makes; `_persist_leg_scene_proposal`
now writes only the ledger tail. Version arithmetic is `base + len(ops)` either
way, so the head is unchanged — only the number of `design_edit_envelope`
batches differs.

**Replay.** `scene_checkpoint_committed` run events are the durable mark;
`_own_checkpoint_version` reads them so a redrive recognises its own work and
refuses (`agent_turn.interrupted_after_checkpoint`) instead of double-applying
or falsely blaming a human. Takeover does NOT resume from the checkpoint —
that is the recorded residual.

**Files:** `lumen_agent/tools/substrate.py` (`SceneCheckpoint`,
`checkpoint_scene`, `latest_preflight_has_errors`), `lumen_agent/tools/render.py`
(the trigger), `lumen_agent/harness.py` (plumbing), `lumen_api/main.py`
(committer, replay guard, `_call_turn_override` back-compat seam),
+ `apps/api/tests/test_scene_turn_persist.py` section (i),
+ `apps/agent_runtime/tests/test_scene_checkpoint.py` (new).

**Tests run (focused only; the full design suite was NOT run — >1h):**
`test_scene_turn_persist.py` 32 passed · `test_scene_checkpoint.py` 8 passed ·
`test_web_turns.py`+`test_write_path_governance.py`+`test_run_view.py` 46 passed ·
`tests/design/test_design_fleet_turns_db.py`+`test_p37_design_entry_consumption.py`
12 passed · runtime `test_deepagent_harness/test_view_and_finalize_hygiene/
test_export_token_refusal/test_retokenize/test_checkpoint_resume` 92 passed.
Env: `CLUE_DATABASE_URL=…@localhost:55040/clue`,
`LUMEN_CORE_HELPER=subsystems/clue-design/target/release/lumen-api-helper`
(built with `cargo build -p lumen-api-helper --release`), `CLUE_STORAGE_FS_ROOT`
pointed at a scratch dir. NOTE: the API-tests and agent_runtime-tests trees both
ship a `tests/conftest.py`, so they collide if collected in ONE pytest run —
invoke them separately.

**Residuals.**
1. Takeover does not resume from a checkpoint (refuses honestly instead).
2. If the `scene_checkpoint_committed` emit fails (e.g. no run row), a redrive
   reads its own move as a human conflict — wrong message, still safe (refuses).
3. Checkpointing splits one turn's undo history into several envelopes. Intended,
   but the editor's undo UX over agent turns has not been re-reviewed.
4. Not gated on preflight-clean, by design — see the spec entry. Revisit once
   P0.2/P0.3 land.

## §7 ACCEPTANCE RUN #1 — flag ON, live, 2026-08-24 17:04 IST (colombo stack)
Brief: Magic Doc LinkedIn square ad (audience/offer/tone stated), grok-4.6
medium, LUMEN_AGENT_FAST_LOOP=1. Run `run_4b5dd17f9e944269b94ca45d3bd6d9f2`,
doc `doc_aa05eefa9d85555fa6b2b45ffbc159a0` → v73, renders (full-bleed statement
skeleton, brand purple, pink CTA).
SCORECARD vs §1 gates: wall 10m05s (~gate limit; budget fired at 600s,
graceful finalize, stop_reason=budget_exhausted_wall_clock) · calls 36/45 ✅
(author 21 / orch 15 / reviewer 0 — R3 held live) · TTFP 6m09s vs ≤4m ❌ ·
input 2.57M ≤3M ✅ · rounds 2 ✅ · usable doc ✅ (P0.4 checkpoints saved work).
vs baseline: 43m18s→10m05s (4.3×), 178→36 calls (4.9×), 13.5M→2.57M tokens.
Defect: headline/body OVERLAP visible in v73 (budget cut round 2 before the
fix landed). autofix_count=0 (no class fired). 7 calls >30s — per-call latency
is now the dominant cost; TTFP is the gate to attack next.
Also proven live in browser: editor renders new-engine wasm, selection+
inspector OK, export 200 (964KB PNG), visible export-failure alert (403 case),
scene_reviewer_quarantined[fast_loop_v1_r3] in prod logs.
Env notes: colombo frontend needed CLUE_APP_ORIGIN=http://localhost:3000
override (.env.local pins :3033 → ALL mutations 403 at CSRF gate — fix the
file or serve on 3033); granted mem_verify_fastloop_0824 membership row (dev
DB) for ws_8040 access; frontend vendor wasm synced from fresh build
(UNCOMMITTED apps/frontend/public/vendor/wasm change); colombo .env still has
LUMEN_AGENT_REASONING=high (worker was started with medium override).
Chat-flow paper cut (2nd occurrence today): first message only OPENS the leg
(open_awaiting_user) — 14 min lost waiting. Product question: leg-opening
brief that is generation-complete should carry into the design turn.

## §7 ACCEPTANCE RUN #2 — tuned loop + R6 skills, 2026-08-24 19:36 IST
Run `run_bcdcf3e484fd48b7805c8eb561a64854`, doc `doc_ac8a96ae…` → v97.
30 calls (author 23 / orch 7 / reviewer 0) · wall 10m13s (budget-cut AGAIN) ·
TTFP 5m33s · 1 round · autofix fired 4× (first live firings) · 2.03M input
tokens · 8 calls >30s. vs run #1: calls 36→30, orch 15→7 (GET-TO-THE-AUTHOR
worked), tokens 2.57M→2.03M, TTFP 6m09→5m33.
Result: NO collision (run-1 defect class gone; clearance advisory + no-collisions
eyes test in force) but polish is budget-cut: black-on-purple headline contrast,
tiny body, oversized CTA label, dead middle band. completed_with_warnings.
VERDICT: loop structure is now lean — wall time is LATENCY-bound: ~20s/call
mean × 30 calls ≈ 10 min. Round-boundary budget rule can't help a single long
round. The remaining lever is the MODEL CONFIG decision (deliberately not taken
by agents): faster model for orchestrator and/or author
(LUMEN_AGENT_MODEL / LUMEN_AGENT_MODEL_ORCHESTRATOR env knobs exist).
At ~8s/call the same 30 calls ≈ 4 min → polish round fits, quality recovers.

## Founder quality verdict on run #2 output (2026-08-24 evening) — "still looks slop"
Verbatim gist: two solid saturated kit colors with a non-pairing text color;
token picked, zero second thought on how the combination READS; never considers
a softer shade the kit offers. Preview defects confirmed at full res: black
$text.primary on saturated brand purple, saturated pink CTA plate on purple,
EMPTY white plate where the logo should be, CTA label bottom-aligned in an
oversized fixed-size plate. Diagnosis accepted: corpus had a numeric contrast
floor and NO color-judgment doctrine.
→ Dispatched color-craft wave: new skills/color-and-contrast (on-color pairing
law, shade-not-just-token, saturated-on-saturated separator, roles/families +
hard reject test, contrast-before-harmony by LOOKING), composed into all five
format skills + on-color-pairing self-audit test + CTA hug-plate rule anchored
to blocks/actions. Playbook test runs (before/after, stat-proof,
product-as-hero briefs) queued AFTER this lands.
OPEN: model-speed A/B decision still unanswered — at ~20s/call every run's
polish round gets budget-cut, which is itself a quality ceiling.
UNINVESTIGATED: why the logo lockup rendered as an empty plate in run #2
(asset placed but no image drawn — check final_scene fills/asset refs).
