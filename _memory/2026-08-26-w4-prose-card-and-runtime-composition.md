# 2026-08-26 — Brand Ad Assets: prose ad-DNA card (Part A) + W4 runtime composition (Part B)

Base attested: `d2b6f8d06` (W3 close-out). Worktree branch
`worktree-agent-aa485c882810ee689`. Local commits only; nothing pushed.

## Founder rulings implemented (they OVERRIDE the spec)

- **D8 — the ad-DNA card is free prose.** The five-field `VisualSystem`
  taxonomy is rejected as over-specification. Card is now
  `{schema_version: 2, prose, style_groups: [{name, creative_ids}]}`.
  Style groups survive for exactly one reason: turn-time reference selection
  must know which described look covers which creatives.
- **D9 — the composition corpus is dormant.** W4 does not reference, load or
  point the agent at it. The corpus docs were not edited.
- D5 (no approval gates / no mechanical guards on the agent) and D1 (budgets
  are guidance) restated and honoured — W4 adds neither.

## Part A — what moved (commit `bfc67ba4d`)

`lumen_ingestion/ad_library/distill.py` rewritten: `StyleGroup` replaces
`VisualSystem`; `bounded_card` refuses a card with no prose (an empty card
recorded as a version is a confident lie); bounds are `MAX_PROSE_CHARS=2400`,
`MAX_STYLE_GROUPS=6`, `MAX_GROUP_NAME_CHARS=80`. The response envelope stays
schema-pinned (parsing must be reliable) but the schema no longer pins the
CONTENT — required keys are only `prose` and `style_groups`.

Consumers: `pregenerate.py` builds each background prompt from the prose
(bounded separately at `PROSE_IN_PROMPT_CHARS=900`) plus the group name;
`design_publish_ad_dna_card` refuses a prose-less card and reports
`style_group_count`; the onboarding job's evidence records `style_groups`.

**No migration.** `card_json` is jsonb; `schema_version` 1 → 2 is how a reader
tells the shapes apart. The durable `design_ad_pregenerated_asset.visual_system`
column KEEPS its W2 name and now carries the style-group name — renaming it
would be a migration that buys nothing. Same for the `visual-system:<name>`
asset tag.

## Part B — W4, where things hook

- **One hook covers both entry paths.** `run_agent_turn_preview` (design
  `lumen_api/main.py`) reads the lane once via `ad_runtime.read_ad_lane`, then
  auto-attaches only `if ad_lane is not None and not reference_assets`. The
  standalone `POST /agent/turns` route resolves manual refs in its handler and
  hands a resolved `None` in; the platform leg envelope carries no
  `reference_assets` key and takes the in-worker branch. Neither can miss it.
- **The leg-path blocker recorded in `_memory/2026-08-24-reference-images-plan-review.md`
  was ALREADY FIXED at this base** — `execute_agent_turn_job` reads
  `envelope.config.get("reference_assets", _REFERENCES_UNRESOLVED)`. Nothing
  new was needed. It is now pinned from both sides: a design-side test that a
  leg's own `reference_asset_ids` survive a key-less envelope and beat
  auto-attach (verified red with the sentinel removed), and a platform-side
  assertion in `tests/api/test_reference_images_contract.py` that the leg
  envelope must NOT carry the key.
- **The description lands in the frame payload.** New
  `AgentRuntimeConfig.ad_dna_card` (by value, like `brand_kit`);
  `lumen_agent/frame.py` renders a `## THE BRAND'S PUBLISHED-AD STYLES,
  DESCRIBED (advisory)` section right after the brand card, whose text says in
  words that it is context and that the brand card wins any disagreement.
  Frame payload is fast-loop-only, which is the demo path.
- **Selection v1** (`lumen_api/ad_runtime.py`): style-group name matched
  against the brief by ONE cheap bounded text call on the lane's existing
  model id (`LUMEN_AD_DNA_MODEL`, no new credential, `max_tokens=32`, brief
  truncated to 1200 chars). Skipped when there is one group. Deterministic
  fallback to the most recent creatives on: no card, no groups, a failed call,
  an invented name, or a group whose creatives no longer resolve. The answer
  is always matched against known names — a model cannot invent a group.
- **Asymmetry, deliberate:** a bad MANUAL attachment is a loud 422 (explicit
  user intent); a bad AUTO attachment costs the turn its references and never
  the turn.

## Tests

Design side (`.wt-pytest.sh`, PYTHONPATH pinned to the worktree):
`apps/api/tests/test_ad_assets_runtime_composition.py` (new, 19),
`test_ad_assets_distill_pregenerate.py` (20), `test_ad_assets_onboarding.py`,
`test_ad_library_*`, `apps/agent_runtime/tests/test_ad_dna_frame_context.py`
(new, 6), the full `apps/agent_runtime` suite, `apps/api/tests`.
Platform side: `tests/api/test_reference_images_contract.py`.

Red cases VERIFIED by probe (broke the code, watched the test fail, reverted):
1. manual-references-win (`if ad_lane is not None:` without the
   `not reference_assets` guard),
2. flag-off byte identity (`read_ad_lane`'s flag check removed),
3. the leg sentinel (`.get("reference_assets")` without the default).

## Residuals / follow-ups

- **The finalize gate's wording.** `substrate.py`'s reference-fidelity refusal
  says "this turn has user-attached references". On an auto-attached turn that
  is now inaccurate. Left untouched on purpose (the brief forbids touching
  loop mechanics); the gate's SUBSTANCE — did the run look at the references
  and judge fidelity — is exactly what W5 measures. Reword when someone is
  next in that file.
- **Auto-attach fires on every scene turn of a populated lane**, not only on
  ad-shaped ones: no artifact-kind signal reaches
  `AgentTurnPreviewRequest`. Consequence: a poster turn in an ad-onboarded
  workspace becomes a reference turn (fidelity stamp + accept bar). Judged
  correct for v1 and stated at the hook; revisit if a kind signal ever
  arrives.
- **The frame payload is fast-loop-only**, so a `LUMEN_AGENT_FAST_LOOP=0`
  scene turn gets auto-attached references but no described card. Deliberate
  (the fast loop is the demo path and the only composed-context surface).
- The selection call runs on the vision model id by default. It is a tiny
  text-only call, but an operator wanting a cheaper tie-break has no separate
  knob today — add one only if the cost shows up.
