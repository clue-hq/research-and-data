# Web SOLO mode — one deepagent, three pairs of eyes (founder ruling 2026-09-04)

**Status: BUILT, tests green, not yet benchmarked live.** Next step: rerun the OpenAI×CFO
campaign-page brief (same diagnostic rig as `_memory`-recorded 2026-09-01 run) and compare
wall-clock + quality.

## Motive — the 2026-09-01 diagnostic run

The Stripe→OpenAI-CFO ABM page took **56.8 min** (135 model calls; orchestrator 39 /
author 86 / reviewer 10; 97% of wall-clock was grok-4.6 latency; 13.9M prompt tokens, 89%
cached). ~20–25 min was pure TRIO COORDINATION: every author delegation started fresh
(4 passes × skill re-reads + library re-survey + fact re-grounding ≈ 10–12 min), the
orchestrator spent ~6–8 min writing briefs and digesting work it didn't watch happen, and
discoveries died at the delegation boundary (the orchestrator found OpenAI's mark in
Stripe's own harvested logo wall; no author pass ever heard about it — the page shipped
Stripe-only). The old `_ROUND_MUTATION_BUDGET = 14` also forced a from-empty ABM build
(shells + ~7 bands × compose+insert > 14 mutations) to die mid-build BY CONSTRUCTION,
costing a full triage/re-brief/re-discovery cycle. Founder target: ≤10–15 min, same or
better quality.

## The ruling

1. **One agent.** `LUMEN_AGENT_WEB_SOLO=1` (default OFF in code; ON in dev env). Both web
   subagents quarantined — D-F7's tool-absence pattern, widened — and the orchestrator
   model carries the union toolset (director's read/render/judge + author's full write
   surface). Neither subagent model is instrumented in solo (attribution honesty).
2. **The persona is founder-specified**: the solo prompt tells the agent it IS three
   practitioners — THE DIRECTOR (intent), THE DESIGNER (craft, a working designer with a
   marketer's ear), THE JUDGE (verdict, judging **as the customer the page was built
   for**, cold, attachment-free). "The judge outranks the designer's fondness for what it
   just built." No direction-by-delegation; plan → build → render → self-review micro-loop.
3. **plan.md is the working memory**: first write of the turn, must-land-first section
   ordering (chrome/hero/CTA before nice-to-haves so an interrupted build ends coherent),
   statuses kept current so the agent could resume from the file alone after context
   compaction (deepagents-native pruning is the mechanism; no new machinery).
4. **Read once, up front, batched** — skills/recipe/library survey in the first batched
   responses; re-reading a skill mid-build is named a process defect in the prompt.
5. **`_ROUND_MUTATION_BUDGET` 14 → 75** — a runaway backstop, no longer a pacing device.
   Render-reset unchanged. (In solo the agent renders its own previews anyway.)

## What was built (all in `subsystems/clue-design/`)

- `packages/py-lumen-config/py_lumen_config/config.py`: `lumen_agent_web_solo` flag.
- `apps/agent_runtime/lumen_agent/config.py`: `web_solo` on AgentRuntimeConfig + from_env.
- `apps/agent_runtime/lumen_agent/prompts_web.py`: `build_web_solo_prompt(...)` — the
  merged persona prompt (~27k chars rendered). Every operative block carried from the
  trio builders (tokens, geometry utilities, icon vocabulary, grounding, ABM law incl.
  markers/derive/publish/prepared-for, release law R-X9, the SHARED clone-review rubric,
  ship bar, scoped turns, discipline). Solo-specific additions: the persona, the 6-step
  turn shape, must-land-first plan ordering, "read once" law, one-loop review expectation.
- `apps/agent_runtime/lumen_agent/harness_web.py`: solo branch — subagents ternary
  (short-circuits so subagent dicts/models never construct), tool-union block, prompt
  switch, `skills=` passed to create_deep_agent in solo (the agent is the skills reader),
  quarantine log event `web_subagents_quarantined` reason `web_solo_2026_09_04`.
- `apps/agent_runtime/lumen_agent/tools/web_substrate.py`: budget 75 with ruling comment.
- `apps/agent_runtime/tests/test_web_solo_mode.py`: 5 tests — no subagents + full write
  surface + skills in solo; persona + rubric + no-delegation-promised in the prompt;
  trio path byte-identical flag-off; account/hotlink blocks conditional; budget == 75.
- Env parity (rule 2026-08-31): `LUMEN_AGENT_WEB_SOLO=1` + the two pre-existing web flags
  (`WEB_FAST_LOOP`/`WEB_REVIEWER`, previously env-only) documented in `.env`, root
  `.env.example`, subsystem `.env.example`.

## Verification

`pytest` (subsystem venv, PYTHONPATH=.:apps/api:apps/agent_runtime): test_web_solo_mode +
test_web_review_gate + test_web_substrate all green (127), plus adjacent suites
(abm_assembly, design_guidance_wiring, cloned_sections, account_logo_bind,
brand_brief_consumption, cancellation) all green (167). Only lint finding on touched files
is the pre-existing F841 `workspace_str` (present at HEAD; left alone).

## Open items / risks

- **Live benchmark not yet run** — the whole point. Rerun the same OpenAI×CFO brief with
  the stack's worker restarted (worker must pick up the new code + env), watch with the
  same timing extraction (`.context/run-diagnostics/` rig), compare quality on the three
  axes (persona depth in copy, brand fidelity, logo/honesty handling).
- **Fresh-eyes loss** is the named quality risk (the 2026-09-01 navy-contrast blocker was
  caught by a reviewer who didn't build the page). Mitigations shipped: same rubric bytes,
  `review_cloned_page` mechanical walk unchanged, plan's pre-written Review tasks, and the
  judge persona explicitly told its attachment is the enemy. Watch this axis in the rerun.
- The conversion-copywriting SKILL.md YAML defect from the 2026-09-01 run was ALREADY
  fixed on this branch (`cefee3601`, 2026-09-03) — the run predated the fix; the stale
  materialized copy re-syncs via the content stamp on the next turn. No action.
- Realistic landing zone on grok-4.6 (~41 tok/s): 12–15 min. If still above target after
  the rerun, next levers are output-token discipline in the mega planning calls and the
  per-model latency itself (env-first model config makes swaps one-line now).

## Benchmark run #1 (Ramp × CFO, 2026-09-04) — 16.6 min build, LOST to a latent commit-gate bug, now fixed

Solo verified live (single orchestrator role, zero `task` calls). Model span 19:14:54→19:31:31
= **16.6 min**, 39 calls (vs trio 56.8 min / 135 calls), 3.7M prompt tokens (88% cached).
Read-once law held (skills+recipes+survey in 3 batched calls); vendor-first logo pulled Ramp's
real family off the Brandfetch CDN first try (vs 5×403 on the OpenAI run); native compaction
fired once (~71s "SESSION INTENT" summary) and the agent resumed from plan.md cleanly; the
micro-loop caught and repaired two real defects (hero swirl height at 768/375, phone-header CTA
clipping). Agent's finalize described the on-brief page (nine bands, Stripe×Ramp co-brand with
the real lockup, one CTA → the Issuing/Treasury/Capital form, "Prepared for Ramp" only).

**But the run row says `failed`: `web_turn.operations_incomplete`** — the API's replay-equality
commit gate. Root cause (proven offline by replaying the ledger against the pre-turn doc):
the accepted full-page ingest came back WITHOUT `asset_ing_01fbbe4c…` (the Stripe network-motif
raster — registered mid-turn, viewed, deliberately not placed), while the append-only ledger
kept its `upsert_asset`; replay carried the asset, the final doc did not, docs differed by
exactly that one entry, commit refused, 16.6 minutes discarded.
`_page_replacement_operations`' docstring states the invariant; it expresses only children +
custom CSS, so a core-side asset drop is unexpressible in ops. The trio never tripped it
because its authors placed every asset they registered; solo's `fetch_logo` registers the
whole family (place one cell of eight) → near-certain trigger.

**Fix (committed with this note):** the `_submit_page` accept path carries `before`'s asset
map forward into the ingested doc (`setdefault` per asset — a registered asset is turn library
state, not garbage), covering author AND patch origins (all three live `author_web_page`
submissions were REJECTED; the page actually landed via `patch_web_page`'s accept — same
`_submit_page` seam). Offline proof: replay == final after carry-forward, byte-equal.
Red-proofed test `test_unplaced_registered_asset_survives_full_page_author_and_replay`
simulates the drop at the ingest seam (the live-only trigger condition involves brand-kit
state my hermetic probes did not reproduce; the seam simulation pins the invariant against
ANY core drop condition).

Also observed, minor: a stale plan.md from a previous brief on the same document was correctly
detected and amended ("The existing plan is a billing campaign, not this Ramp ABM brief") —
consider stamping the brief hash into plan.md so a mismatched plan archives instead of
continuing; and three small sequential read_file calls (~1 min) where the read-once law wants
batching.

**Next: restart the fleet worker (it runs pre-fix code) and rerun the same Ramp brief.**
Projection: the page that took 16.6 min now COMMITS; timing should repeat or improve
(no stale plan detour on a fresh doc).
