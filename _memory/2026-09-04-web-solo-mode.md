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

## Quality regression diagnosis (Ramp run) — why ZERO clones were used, and the fixes

Founder's observation confirmed by the plan the agent wrote: **all nine bands COMPOSE-VOCAB**,
zero pins, zero `compose_web_section` calls — while the survey had found a RICH library
(14 Stripe sections, 7 heroes, 8 proof bands, nav, footer, all released). The trio's OpenAI
run composed its gap-bands in the RAW lane (real remixed CSS) and pinned real clones; solo's
page was pure vocabulary → generic template in Stripe colors. Not drift — three specific,
quotable defects, each visible in the agent's own plan:

1. **The ABM marker law forced the vocabulary lane.** Plan: "Use `data-var=account.name`…
   COMPOSE-VOCAB (`abm_hero`) remixing ancestor frag_591d…; do not pin." The agent reasoned
   markers ⇒ vocabulary, not knowing/not believing that a CLONE'S SLOT VALUES carry
   `{{account.*}}` markers. FIX: new ABM block law — "PINNING IS STILL THE TOP RUNG …
   'it needs markers' is NOT a reason to compose"; COMPOSE-VOCAB now requires a plan
   justification naming why all five other sources cannot serve.
2. **The abm-page recipe literally said `author_web_page` FIRST.** The "Order of operations"
   line predates the raw lane and taught the full-vocabulary page. FIX: recipe rewritten —
   pins/variants/raw compositions first, author_web_page reserved for attribute-bearing
   bands, largest verb last if at all (supersession note in the recipe).
3. **Chicken-and-egg lane conditional.** "RAW is the default on a clone-bearing page" — a
   create turn's page starts empty, so the condition never fired and vocabulary became the
   default. FIX: "RAW is THE DEFAULT IN ANY WORKSPACE WITH RELEASED CLONES — 'the page has
   no clones yet' is never the reason."
   Secondary casualty now noted: with zero clones on the page, `review_cloned_page`
   self-disabled ("not applicable"), so the mechanical fidelity gate never ran either.

**plan.md cross-run leak (founder correction #1) fixed:** the plan lived at the SHARED
`.deepagent-workspace/workspace/plan.md` (bare relative path against the backend root) —
which is exactly how the Ramp run inherited the billing campaign's 380-line plan. The solo
prompt now interpolates the RUN-SCOPED path (`/{run_id}/workspace/plan.md`, passed from the
harness's scaffold) and names the leak. NOTE: the trio prompts still say bare
`workspace/plan.md` — same latent leak there; left untouched this pass (trio is dormant
behind the flag), recorded here so it isn't rediscovered.

Next: rerun the Ramp brief on the fixed prompt + the asset-carry-forward commit-gate fix.
Watch for: pins + raw compositions in the tool trace, `review_cloned_page` actually running,
plan.md landing in the run dir, and the commit succeeding.

## Clone-dominant refactor (founder ruling 2026-09-04, second pass)

Founder's principle, verbatim in spirit: the clone path — PIN → REBIND → DERIVE-VARIANT →
COMPOSE-RAW — must DOMINATE every surface the agent reads; the vocabulary lane is taught
completely but always as the LAST RESORT, never the highlight. Verified in code first:
personalization markers DO work on cloned sections — the F1.4 derive (`derive.rs`
`apply_fragment_slots`, ruling R24-2 in `lumen_api/fragments/abm_page.py`) substitutes
`{{account.name}}`/`{{account.domain}}`/`{{account.logo}}` in fragment SLOT VALUES, the logo
riding as text on an image slot. The Ramp agent's "needs data-var → must be vocabulary" was a
wrong mechanism. Limits: a marker needs a slot (else derive a variant, whose texts become new
slots); `data-slot-when` presence gating is vocabulary-only.

Every vocabulary nudge found and rewritten (all in `subsystems/clue-design/`):
- Solo prompt (`prompts_web.build_web_solo_prompt`): ABM block now LEADS with slot-value
  markers on clones, data-var demoted to last resort; shell fallback names the lane (a
  raw-lane variant of the cloned nav/footer with the exits stripped — never a vocabulary
  header); BUILD step is an explicit 5-rung ladder climbed in order, stopping at the first
  that serves, rung recorded per band in the plan, "a reason to skip a pin is a reason to
  step ONE rung down, never to the bottom"; lanes bullet and `author_web_page` bullet say
  LAST RESORT in so many words.
- Tool descriptions (in model context every call): `assemble_abm_page` docstring + module
  comment ("composed by the ordinary authoring vocabulary in between" — the exact sentence
  that taught the Ramp page) rewritten; `author_web_page` docstring opens "THE LAST-RESORT
  LANE" and lists the four rungs above it; `author_web_subtree` says a cloned section is
  never edited with it.
- Shared docs: create-website SKILL.md gains a preface declaring itself the vocabulary
  lane's contract and the last resort in a clone-rich workspace; campaign-page-workflow
  step 7 and edit-website's compose sequence say "raw is the default in a workspace with
  released clones; vocabulary is the last resort"; abm-page recipe's order-of-operations
  already fixed in the prior commit.
- Trio prompts (dormant behind the flag) deliberately untouched; they carry the same older
  nudges — recorded here.
Tests: solo prompt test pins the ladder order (PIN before "5. The vocabulary lane") and the
last-resort wording. Suites green: solo, substrate, abm_assembly, review_gate,
design_guidance_wiring, cloned_sections.
Next: rerun Ramp; the verdict is the tool trace (insert/assemble/repair/compose calls, not
author_web_page) and whether `review_cloned_page` runs.

## Benchmark runs #2 and #3 (Ramp, 2026-09-04) — both killed by OpenRouter mid-generation; four fixes shipped

**Run 2** (fresh doc, pre-clone-first-fix prompt): died at 6 min — a 136s grok generation on
/responses returned `Auth context expired` (server_error item). Fix: design runtime now routes
non-OpenAI ids over chat-completions (`LUMEN_AGENT_OPENROUTER_CHAT_COMPLETIONS=1`).
**Run 3** (clone-first prompt, chat-completions): the quality thesis PROVED — plan.md in the run
dir, every section source a real clone (PIN hero frag_591d…, PIN released navy repair, PIN+variant
grid/close, shells), `assemble_cloned_sections` → 4 pinned, then the campaign bands built in the
RAW lane (`compose_web_section` ×5, released + pinned; not one vocabulary band), the mechanical
`review_cloned_page` walk actually ran (6/6 observations), the judge caught three real blockers
(duplicate close, missing footer, unresolved `{{account.name}}` — correct: no account card) and
repaired header/hero/why in the raw lane. Then died at 34.7 min: a 236s generation (close-band
rewrite) returned `{'message': 'Auth context expired.', 'code': 502}` — ON CHAT-COMPLETIONS.
So it is the long-generation window (~2–4 min), not the endpoint. Nothing committed (web turns
persist once at the end).

Fixes shipped from run 3's trace (all committed):
1. **Tool-call serialization** (`37f1bba7b`): batched `assemble` + 2× `asset` ran in parallel
   threads; the asset tools committed a pre-assembly doc snapshot 27ms after the assembly landed
   and erased four pinned bands (lost update). Every tool handed to the agent now holds one
   re-entrant lock (`serialize_tool_calls`); schema preserved via functools.wraps.
2. **`inspect_cloned_section`** (`7056d600c`): no tool had ever exposed a clone's HTML/CSS —
   search lists slots + preview handle, view shows a picture — so "remix the original's actual
   CSS" was un-followable; the agent grepped the filesystem (other runs' dirs included) and the
   trio's old "raw" compositions were from memory too. New read tool returns html+css+slots via
   `registry.read_source`; rungs 3–4 of the ladder point at it.
3. **Campaign variants are lineage roots** (same commit): `_resolve_lineages` took the newest
   healthy descendant regardless of why it was derived, so a released one-CTA variant of Stripe's
   canonical hero would have hijacked every future pin. The agent refused DERIVE-VARIANT for that
   (true) reason. Variants (note prefix "campaign variant", embedded in derived_reason) no longer
   supersede; skill + solo prompt say so.
4. **Same-model transient retry in the governed gateway** (this commit): `Auth context expired`
   / 5xx / overloaded on the LAST candidate retries twice on the same model (a configured fallback
   still wins first, as before); ChatOpenAI's own max_retries never sees error payloads delivered
   inside a 200. Tests: retried-then-recovered, exhausted-still-raises, non-transient-not-retried.

Still open, in order of expected impact on the next run: a re-survey of the library mid-repair
(~2 min; the read-once law slipping under repair pressure — prompt line for the repair step);
insert-index confusion when pinning the footer "last" (it overwrote the close; the agent
recovered but spent a loop); plan writes of 8–9k tokens are the run's longest single calls and
sit in the kill window even on chat-completions — consider asking for a shorter plan or
splitting it. Web-turn progressive persistence (scene mode has it) is the structural answer to
"one killed call discards the run"; recorded, not started.

## Benchmark run #4 (Ramp × CFO, 2026-09-04 11:02 IST) — ACCEPTED in 15.9 min, committed, 6 clones pinned

Run `run_5989158a6730448bb69061496e15184e` (outer `run_26bdb352…`), same brief, fresh chat, solo +
chat-completions, all four run-3 fixes live. Diagnostics: `.context/run-diagnostics/ramp-run4-*.log`.

Numbers: wall 956s (15.9 min) vs 41.5 min (run 3, failed) vs ~57 min (trio). Model time 908s over
28 calls (run 3: 61 calls); tools+overhead 48s. Six calls >60s, longest 133s (the 7.3k-token
plan write). Zero transient errors, zero retries fired. Two compactions (66s + ~37s). Commit:
`design_apply_web_operations_completed` → `design_job.finished succeeded` (ledger replay held:
17 ops = 8 insert_node, 8 upsert_asset, 1 remove_node).

Behaviour (all run-3 fixes verified in anger): batched assemble+asset registrations did not lose
the assembly (lock); `inspect_cloned_section` used 8×, 12k cap held (117k-char homepage hero
truncated); no wander into other runs' dirs; plan.md in the run dir (14k chars, one amendment,
`edit_file` diffs not rewrites after the initial write); DERIVE-VARIANT used on the close band
(`frag_2f42f278b795efef`, released, noted as lineage successor of the composed close, NOT of a
Stripe original); one raw composition (how-we-work band); review walk clean; self-judge caught
the close band's gray wings at 1440 and fixed it in one iteration. Page: 7 sections, 1440/768/375
all sound; hero → "why" gap is generous (~400px) but not broken.

Findings for the founder (unfixed, need rulings):
- **Library pollution by released campaign bands.** The six pins were run 3's OWN raw-lane
  outputs (`frag_8dd7a2df` header, `frag_f855f401` hero, `frag_90b5f22c` why, `frag_1bc1630e`
  close) — Ramp-specific copy released into the workspace library, surveyed as ordinary Stripe
  sections. Windfall for the same account; wrong for any other account. Ruling needed: scope
  account-personalized releases to their campaign (hide from the generic survey) vs keep as
  reusable per-account bands.
- **No account card on the leg again** → `{{account.*}}` unusable, `bind_account_logo`
  impossible, "Ramp" hard-coded. The leg is opened without an account; harness-side.
- **Exit judge cannot build** (`agent model timeout must be positive and no greater than
  gateway policy`: DESIGN profile timeout > gateway timeout) → fail-safe CONTINUE every turn.
  Known "lock it in" blocker; not a regression.
- Agent chose `limit: 8` on every library search (run 3 used 20/50) — may hide candidates in a
  larger library.
- Campaign shells still unreleased (need human kit re-approval) → hand-composed header/footer
  lineage persists.

## Edit turn on run 4's page (2026-09-04 11:34 IST) — ACCEPTED in 5.9 min, DERIVE-VARIANT used correctly

Run `run_3f4f7843eb6c4f9682d57520073c3a76`, user ask: "use the three product-UI images as the card
backgrounds instead of strips under the text". 12 model calls, wall ~6 min (finalize 05:52, commit
06:10:04Z succeeded). Shape of the turn was exactly the ladder: view doc → locate the pinned "why"
band → `inspect_cloned_section` (2.5k html / 2.3k css) → baseline render → plan (5.8k tokens, 97s,
the longest call) → ONE `repair_cloned_section` raw rung=2 on `frag_90b5f22c9065d904` →
`frag_bddd989fe5497209` released+pinned in place → render → review walk clean → finalize. Its own
note: "REBIND could not restack layout; PIN kept images below text" — the variant rung chosen for
the right reason. Untouched sections stayed byte-identical. Visual verified at 1440: three cards
with full-bleed image fills + white fade under the copy; readable. Advisory it flagged itself: on
375 the Visa wordmark sits near the last body line.

Two things to keep in view: the plan write is still the single longest generation on an edit
turn (97s for a one-section change — a "small edit → short plan" rule would shave ~1 min); and
this variant IS a lineage successor of `frag_90b5f22c…` (a run-3 raw composition, itself
Ramp-specific), which is fine — but it means the library-pollution question above now has a
3-deep Ramp lineage in it.

Follow-up shipped (`0cb70f806`): the solo prompt's plan step now SIZES THE PLAN TO THE CHANGE —
full plan only for a new page/rebuild; a bounded edit gets one short paragraph per touched
section (brief words verbatim, rung + why lower rungs cannot, imagery decision, one proving
check) and "untouched" for the rest. Pinned in `test_web_solo_mode.py`. Needs a fleet-worker
restart to take effect (prompt is built in-process).

## Multi-page turn: fill a hand-added /issuing page + one home link (2026-09-04 14:14 IST) — ACCEPTED in 20.7 min

Run `run_7b137c26991b4bdebac5dac6ce1fe8dd`. Founder added the page from the (repaired) inspector
Page section (doc v8), then briefed: fill /issuing (7 sections, Issuing-only proof facts, same
header/close/footer as home) and change ONE thing on home (a secondary hero link to /issuing).
Wall 1241s, model 1189s over 47 calls, 2 compactions, zero transient errors; committed → doc v9,
both pages 7 sections. Longest call 190s = the full plan (10.7k tokens) — correct per the
plan-sizing rule (a NEW page gets the full plan; the home change got the bounded paragraph).
Behaviour: `list_pages` on call 2; `switch_page` to issuing BEFORE the assemble; 7 clones pinned
in one call (home's header/hero/proof/session/close/footer + the why band as the levers'
ancestor); hero and proof handled by REBIND alone; two DERIVE-VARIANTs (levers, session);
provenance cited on stripe.com/issuing + the earn-revenue guide + docs (the "$1 or $1M same APIs"
stat traces to the issuing page copy); switched back to home, derived a hero variant for the
link (first side-by-side, then restacked under the CTA after its own render check); home ops =
2 remove + 2 insert on the hero only — verified in the final render. Pins render exact fragment
bytes (no lineage resolution at render), so the home hero variant did not leak into /issuing's
pinned hero; the agent inspected that itself (Amendment 3).
Residual to watch: the raw-lane repair of a non-variant lineage still releases as a successor
("future pins of those lineages may resolve to the last repair") — the library-pollution
ruling above now has a 4-deep Ramp lineage in it.
