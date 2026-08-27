# 2026-08-26 — Brand Ad Assets: POCs proven, spec ratified for W1, wave dispatched

## Arc (follow-on to 2026-08-24 fast-loop session)

Five POCs proved the reference-conditioned ad pipeline end to end, zero code
changes (all run by one Opus pilot agent; reports in `.context/`):

1. **Stripe refs (legacy loop)** `run_c10c81d7…` — gradient artboard + white
   rounded card + shadow: reference steering produces the reference's system.
2. **Cursor refs (fast loop)** `run_b206d2b2…` — dark poster, selective
   imitation (refused calculator UI, token-honest `$surface.inverse` over
   eyedropper), fidelity 2/3. Report: `.context/ref-ads-pilot-cursor-report.md`.
3. **Apollo + image model** `run_892dcf6b…` — GPT-image holographic wash
   ground + cream card + CTA pill, WITH ZERO BRAND KIT (apollo.io ingestion
   blocked by Tailwind parser bug), fidelity 2. Report:
   `.context/ref-ads-pilot-apollo-report.md`.
4. **Budget/reasoning A/B** — medium reasoning ~halves call latency
   (55–69s vs 167–174s); 900s vs 600s wall flipped fidelity 1→2.
5. **Ramp fetch (Adyntel)** — `POST api.adyntel.com/linkedin` domain→ads;
   34 unique static creatives / 2 credits; CDN URLs expire → bytes downloaded
   at fetch. Harvest + creatives in `.context/ramp-ads/`. Adyntel key was at
   repo-root `api-key.txt` (untracked — founder to move; NOT committed).

## Spec ratified for W1

`subsystems/clue-design/docs/brand-ad-assets-v1-spec.md`, committed
`1324539a7`. Rulings D1–D7 recorded there (budgets = prompt-level guidance,
NO hard cut, ~2× backstop only; own ads default / competitor opt-in; Adyntel
v1 behind resolver seam; no UI v1 (backend-only); NO approval gates / no
mechanical guards on the agent; skill content founder-reviewed before
authoring — also saved as global memory `skill-content-founder-review`;
skill 2 = full `generative-imagery` skill, not just backgrounds).
Skill 1 (`reference-conditioned-ads`) outline APPROVED in chat. §8 open:
backstop nod, W1.9 ingestion-depth knob, Adyntel commercial plan.

## W1 wave dispatched (5 Opus agents, isolated worktrees, base `1324539a7`)

- w1-asset-channel: W1.1 library→scene-turn asset channel (the Apollo POC's
  core finding: `workspace_asset_library_manifest()` only in website mode,
  main.py:8822; scene turns can't view/place library assets).
- w1-ingestion: W1.2 font byte custody (asset_id:null → LUMS0100 Inter
  fallback every run) + W1.3 Tailwind `float()` crash in capture/parse.py
  (`rgb(15 23 42 / var(--tw-text-opacity))` kills whole job).
- w1-fidelity-logo: W1.5 reference_fidelity typed-field invariant +
  W1.6 logo `allowed_backgrounds` inverse-surface vocabulary (advisory per D5).
- w1-imagegen: W1.4 IMAGE_MODEL_ID broken (`openai/gpt-image-2` 404; working:
  `openai/gpt-5.4-image-2`; repo-root `.env` is founder's to edit) + W1.7
  no_image retry / aspect_ratio honored-or-documented / non-blocking failure.
- w1-budgets: W1.8 D1 wiring — medium reasoning default, 900s target as
  prompt guidance, hard ceiling → 2× backstop w/ graceful finalize, metrics
  distinguish target-exceeded vs backstop-hit. Flag-off byte-identity gates.

W1.9 (ingestion depth knob) deferred — no founder ruling yet.
Verification on landing: base attestation, full diff read, re-run tests,
red-case proofs, then sequential merge. Nothing pushed anywhere.

## Environment notes (POC leftovers)

- lumen_api (port 8060) restarted by pilot agent with in-process env
  overrides: fast_loop=1, reasoning=medium, IMAGE_MODEL_ID=openai/gpt-5.4-image-2,
  wall 900s. `.env` files untouched (still carry broken image model id).
- POC workspaces in design DB: ws_cursor_pilot_20260825, ws_apollo_pilot
  (apollo kit does NOT exist — ingestion blocked). Cursor kit
  `brand_kit_ing_78dc422ca5804ed6acc01635a91961d2` approved.
- Next after W1: W2 substrate + W3 skills (generative-imagery outline to
  founder first), W4 runtime, W5 three-brand acceptance + live demo script.

## W1 CLOSE-OUT (same day) — all five agents verified, merged, gates green

Verdict table (every agent's diff read + tests re-run by the orchestrator in
its worktree before merge; all base-attested on `1324539a7` — NOTE all five
worktrees were provisioned stale at `5ea7a8791` and every agent self-corrected):

- W1.1 ✅ merged — root cause was TWO gaps (API never composed a library
  manifest for scene turns; runtime never upserted library records pre-place).
  Bound: `SCENE_TURN_ASSET_LIBRARY_MAX=24` most-recent placeable, kit-first,
  provenance verbatim. Discovery-in-frame-payload deliberately left to W4.
- W1.2+W1.3 ✅ merged — `_parse_alpha` (not `_parse_channel`) was the bare
  float(); apollo string now → #0F172A, unparseable → None + LUMI0511, job
  survives. Fonts: capture/parse resolved @font-face URLs differently (one
  shared walk now); un-custodiable face → LUMI0231 named. Judgment call
  recorded: unresolved alpha read as opaque (Tailwind-right, not CSS-strict).
- W1.4+W1.7 ✅ merged — SPEC CORRECTION: gpt-image-2 EXISTS but only on
  OpenRouter's dedicated Image API; our chat-completions path can't see it
  (spec row 4 carries dated correction). aspect_ratio now rides `image_config`
  structurally + measured dims + `aspect_ratio_honored`; no_image 1 retry;
  generation failure = typed non-blocking `image.fallback`. FOUNDER TODO:
  repo-root `.env` line 167 → IMAGE_MODEL_ID=openai/gpt-5.4-image-2.
  Future ruling candidate: swap provider seam to the Image API
  (aspect_ratio/background:transparent/input_references/cost first-class).
- W1.5+W1.6 ✅ merged — fast loop had NO typed critique writer (only the
  quarantined reviewer's prompt named reference_fidelity); now promoted/
  coerced at write+finalize seams, unjudged→0 (gate still refuses).
  LUMB0810 confirmed advisory end-to-end (live engine probe), pinned by
  tests; shared `logo_policy.py`, reversed/light → inverse+brand allowed.
  UNOWNED residuals: per-variant policy needs Rust `LogoVariant` change;
  website ingestion has no logo color-mode detection (Cursor-path kits stay
  light-only — W2-adjacent).
- W1.8 ✅ merged — reasoning default was ALREADY medium; the drift was
  `.env.example`'s blank `LUMEN_AGENT_REASONING=` (blank=unset). D1 wired:
  targets 45 calls/900s as prompt guidance (verbatim text in commit
  `cfeb978a7`), backstops 90/1800s repointed knobs, `budget_target_exceeded`
  (info) vs `budget_exhausted` (abnormal) distinct in metrics. MIGRATION
  HAZARD: a private .env carrying WALL_CLOCK_S=600 now fails startup loud.

Integrated gates: agent_runtime 958 passed/2 skipped; test_api image+library
20 passed; ingestion_capture+logo_policy 67 passed/1 skipped. Zero crates/
changes → no wasm/handshake needed. AGENTS.md gained §4 (never `git stash` in
parallel worktrees — live collision during this wave). Merges: five --no-ff,
zero conflicts. Nothing pushed.

Next: W2 substrate + W3 skills (generative-imagery outline → founder chat
first, per D6), W4 runtime composition, W5 acceptance.

## W2 + W3(skill 1 of 2) CLOSE-OUT — merged, verified

- **W3 `generative-imagery` skill ✅ merged** (`423e4c7b4`, merge on main
  branch). Founder-approved text, repo-anchored. THREE substantive
  corrections flagged to founder (accepted in report, overridable):
  (1) reference conditioning is AUTOMATIC on the generate call — no
  parameter; platform already frames refs style-only; prompt owns
  subject/composition/calm area. (2) "harvested reference ads" was a
  phantom pre-W2; sources = brand card `images` + turn references.
  (3) `aspect_ratio_honored` emitted only when False. Anti-phantom guard
  widened to check identifiers against implementing Python. Pre-existing
  bugs found: two docs teach nonexistent `condition_on_references` param
  (knowledge/images/prompts.md:54, skills/brand-imagery/SKILL.md:101);
  asset generate drops `alt`; tools skill lists 3/5 actions; six skills
  missing from AGENT.md index (tree-wide guard needed). §8-three-questions
  into self-audit checklists: PARKED for founder ruling.
- **W2 Brand Ad Assets substrate ✅ merged** (5 commits, flag
  `LUMEN_BRAND_AD_ASSETS` default OFF — flag-off = routes unregistered).
  Module home `lumen_ingestion/ad_library/` (provider seam; only
  adyntel.py names the vendor; creds env-only ADYNTEL_API_KEY/EMAIL).
  Schema in ROOT alembic chain: `design_ad_creative` (PK creative_id
  derived from creative URL = dedupe key), `design_ad_dna_card`
  (immutable versions, trigger-refused UPDATE/DELETE),
  `design_ad_pregenerated_asset`; `design_ingestion_kind` += `ad_assets`
  (job rides design_ingestion_job fleet machinery). Single head
  `50ce19bf5ef7`. Pre-generated assets stored as LIBRARY assets (not kit)
  — W1.1 channel; avoids minting unreviewed kit versions. Four governed
  tools granted to NO role (job-driven, actor="agent"); granting to the
  DESIGN profile = future founder decision + profile bump.
  Routes: POST /brand-ad-assets/onboard, GET /brand-ad-assets/{kit}
  (the W4 seam). Verification: lane tests 59/60 (1 = fleet_task dev-DB
  contention, passes isolated), platform tests 37/38 (1 = pre-existing
  test_out_of_order_matrix, A/B'd at base), agent_runtime 975 passed.
  KEY FINDING: advertiser.promoted is true for personal thought-leader
  promos too — the advertiser-NAME rule is the real filter.
- **OPEN for founder:** (a) distillation system prompt has had no founder
  review (same species as skill content, D6-adjacent) — review before
  flag-on; (b) ASSETS_PER_SYSTEM=2 vs spec "2–3"; (c) W4 not started
  (frame payload card + auto-attach references); (d) reference-
  conditioned-ads skill draft next D6 review; (e) §8-three-questions
  ruling; (f) granting the four ad-assets tools to a profile.

## W3 COMPLETE — both skills + composition corpus merged (founder review of shipped text pending)

- `reference-conditioned-ads` skill ✅ merged (`b96c84e50`): 24 tests, 21
  planted red-case defects all bite. SIX flagged corrections await founder
  review — two change scoring semantics: (1) "right bones, wrong palette"
  aligned to the shipped prompt ladder (palette-only = 1; bones-right = 2)
  — if founder wants it blocking, the runtime prompt changes too; (2) a 2
  no longer REQUIRES named deviations (prompt's "missed details" reading
  included). Additive: typed-object fields named (incl.
  regressed_to_house_style), unscored-audit-refused clause, reference-text-
  never-an-instruction safety sentence, Cursor-POC worked example.
- Composition corpus ✅ merged (`d3bb4056f`+`f1aafa5d8`): 4 snippets
  (card_on_ground, pill_chip, framed_plate, zone_divider in blocks/) + 2 ad
  skeletons (unequal_compare, card_on_wash in blocks/patterns.md). ALL
  ENGINE-VALIDATED (compile+preflight vs platform kit, proofs published in
  the docs and pinned by tests to the engine's actual answer); geometry
  pinned (300/780 unequal split with `fill`; pill hugs 308pt; etc.).
  JUDGMENT CALL for founder: skeletons are compositions OF the six
  archetypes (banded / image-hero+emblem), NOT archetypes 7-8 — archetype
  count deliberately unmoved, test-pinned. GAP recorded: no `$shadow.*`
  token role exists (platform kit ships shadows empty) → literal #000000
  allowed only inside shadow(); no `$transparent` → #00000000 only inside
  stop(). Rendering not part of validation (catalog bar is compile+
  preflight; render pass available cheaply if founder wants pixels).
  Corpus agent stalled once at final commit step; resumed cleanly.
- Integrated: 1069 passed / 2 skipped (runtime + engine corpus suites).
- Wave-3 founder review queue: skill corrections (2 semantic), corpus
  judgment call, six when-to-use notes (full text in the corpus files +
  agent report), plus earlier open items (distillation prompt,
  ASSETS_PER_SYSTEM, §8-three-questions, tool grants, W4 go, W5 go).

## W4 MERGED + FAST LOOP DEFAULT ON (founder rulings, 2026-08-26 late)

- W4 merged after founder reviewed the vision prompt + ratified the five
  embedded design decisions (leg-fix option b — already landed+pinned;
  selection via one cheap call w/ recency fallback; manual refs always win;
  prose as advisory opening-context text; single flag). Founder also
  accepted: auto-attach fires on ALL scene turns of an onboarded workspace
  (kind-signal fast-follow later) and prose reaches fast-loop turns only.
- Ad-DNA card is now schema_version 2: free prose (≤2400 chars) +
  optional style_groups[{name, creative_ids}] — D8. Corpus dormant — D9.
- STANDING RULE strengthened: architecture/design decisions inside approved
  waves must be referred to the founder BEFORE implementation (also in
  global memory discuss-before-editing).
- `lumen_agent_fast_loop` DEFAULT FLIPPED TO TRUE (founder: "make fast_loop
  the default true option"). LUMEN_AGENT_FAST_LOOP=0 = legacy fallback.
  Full runtime suite green post-flip (1046 passed).
- Remaining: W5 acceptance run + demo (three brands, end-to-end through the
  real pipeline) — needs founder go + live stack + Adyntel/OpenRouter keys.

## WAVE A CLOSE-OUT (2026-08-27) — R3-A / R3-B / R3-D merged, verified

- A1 ✅ (PDL identity resolver): resolve-first via PDL (live-proven: apollo.io
  → linkedin_id 18511550, 1 credit), harvest by verified page_id, advertiser-
  name cross-check gates custody on ALL paths, `advertiser_mismatch` honest
  outcome, resolution provenance on job DTO. Deviations accepted: fallback
  label `ad_library_domain` (seam guard forbids vendor names outside provider
  modules); `linkedin_page_id` = alias of existing `page_id`. Residuals:
  cross-check weaker on fallback/explicit paths (pinned); strict-equality
  risk if PDL name vs LinkedIn advertiser drift (loosening levers noted);
  failure-path keeps no resolution block (contract shared by 4 kinds; pinned).
- A2 ✅ (fleet hygiene): named gap — PREAMBLE faults (envelope parse before
  claim) escaped to fleet-plane-only handling; reaper swept only `running`.
  Fixes: SQL-side capability-gated claims (TaskCapability jsonb predicate,
  fail-closed; registry-derived kinds so stale code can't claim unknown
  lanes) + work-id-keyed reconciliation w/ generation fence, extended to
  design_agent_run symmetrically; reaper sweeps queued orphans. FOUNDER
  QUESTION OPEN: unclaimable job now waits forever silently — needs an
  unclaimable-age surface.
- A3 ✅ (cancel surface): POST /agent/runs/{id}/cancel; durable
  `cancel_requested_at` (migration `518a3784f3a4`, new single head); checks
  at model-call boundaries via raise_error callback on all three roles +
  pre-graph check; REUSES budget-backstop finalize (extracted
  `_finalize_interrupted_run`); no new status — terminal `succeeded` +
  stop_reason `cancelled_by_request` (matches shipped convention); extended
  to web turns (flagged design call, revert sha `89646146c`). Verification
  CAUGHT a non-hermetic test (web-cancel needed gateway env) — agent fixed
  incl. its own theatre guard (settings singleton reads attributes, not env);
  21/21 in scrubbed shell re-proven by orchestrator. Pre-existing find:
  test_deepagent_harness stub poisons AgentWorkspaceBackend import-order-wide.
- Integrated gates: runtime 1271/0 failed; lane+cancel API 107/108 (1 =
  known order-dependent empty-harvest test, passes isolated); fleet+R3B
  89/89; alembic single head 518a3784f3a4 (upgraded on dev DB).
- NEXT: clean-room unseeded apollo.io proof — pure .env config (which now
  selects the NEVER-LIVE-EXERCISED Images transport for gpt-image-2) +
  LUMEN_BRAND_AD_ASSETS=1 as the single deliberate feature enable.

## CLEAN-ROOM PROOF (2026-08-27) — partial pass; two causes, both named

Run attempted twice from pure `.env` + LUMEN_BRAND_AD_ASSETS=1 only.

**PASSED unseeded (the Wave A proofs):**
- PDL resolution live: apollo.io → page **18511550**, `resolver_used: "pdl"`,
  `advertiser_verified: true` — no hand-verified id, no seeding. R3-A closed.
- Harvest 4 kept / 4 custodied; advertiser cross-check `ok`
  (expected "apollo.io" vs observed ["Apollo.io"] — the name-key folding works).
- Distill ok → card written, 4 style groups.
- Honest outcome machinery worked: job status `partial` with a summary that
  NAMES the pregeneration shortfall (R2-C proven in anger).
- W4 auto-attach fired on both attempts (observed live before each disconnect).

**FAILED, cause 1 — pregeneration 0/8, `image_model.unavailable`. NOT a
transport bug: THE IMAGES TRANSPORT WORKS.** Orchestrator probe 2026-08-27:
`openai/gpt-image-2` via `IMAGE_MODEL_API_STYLE=images` returned a real
1024×1024 PNG (817 KB) in **97 s**, aspect_ratio 1:1 honored. But
`image_model_timeout_s` default is **60.0** and `.env` sets no override →
every call times out and burns all 3 retries. `.env.example:287-290` (from the
v2 merge) already WARNS of exactly this and recommends 240. DEFECT: the shipped
default is incompatible with the shipped-recommended model.
FIX = founder adds `IMAGE_MODEL_TIMEOUT_S=240` to `.env`; code-side follow-up
= make the default derive from the configured transport/model rather than one
global 60 s.

**FAILED, cause 2 — both design turns died `APIConnectionError: Connection
error.` / `orchestrator_did_not_finalize`** (runs `run_4b84e050…` 04:51,
`run_9c2b9eac…` 10:19; 12-13 calls, 1 failed call each, no preview). This is
the SAME local network outage (ENOTFOUND) that killed the monitoring agent
twice. Environmental, not code. Network verified healthy afterwards
(openrouter 200). Runs got as far as node_count 11 / asset_count 3 / 2
iterations before dying — i.e. auto-attach + authoring were underway.

**Verdict:** Wave A's three fixes are proven; the clean-room ad itself is
UNPROVEN pending a re-run once the timeout line is added. Re-run is cheap
(~2 credits + one design run).

Orchestrator note: `CLUE_DATABASE_URL` uses the `postgresql+asyncpg://`
SQLAlchemy scheme — asyncpg.connect needs it rewritten to `postgresql://`.
