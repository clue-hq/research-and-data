# ARV2 onboarding O4 — the synthesis agent (branch `onboarding/o4-synthesis-agent`)

Date: 2026-09-07 → 2026-09-08. Plan: `ARV2-ONBOARDING-PLAN.md` §5. Worktree DB: `clue_o4_agent`
(throwaway, per-branch). **No live turn has run — the plan's Step 4 acceptance walk is
founder-triggered and was deliberately not executed here.** Nothing below reports live cost,
rounds or wall time, because none exist yet.

## What the lane built

**The role.** `AgentRole.ONBOARDING_SYNTHESIS = "onboarding_synthesis"`
(`platform/agents/clue_agents/contracts.py`). Two migrations, chained off the O1+D1 join
`3742d1281a10`:

- `000b9d8bb17b` — widens the three role CHECKs `agent_turn_role` / `agent_plan_role` /
  `agent_delegation_roles` (same coordinated shape as `549de68ae3b9`, which admitted `design`).
- `dfb9fa040b13` — the **fourth** role CHECK, `agent_model_call_role`, as its own revision. That
  vocabulary was added later by the P3.2 attribution migration `65880921cd52` and is therefore
  absent from the role list every earlier widening copied, so the first migration missed it. Every
  governed turn stamps one `agent_model_call` row per model round, so a synthesis turn failed at
  its FIRST model call. Found live by the turn-runner test, not by review.

`uv run alembic heads` → `dfb9fa040b13 (head)`, one line.

**The tool.** `exa_search_evidence@1` (`platform/api/clue_api/onboarding_evidence_tools.py`) — the
role's one spendable call, over O2's fixed persona-evidence template. Registered
**unconditionally** in the toolbelt, granted to `onboarding_synthesis` only, and **fail-closed**:
`build_toolbelt(secrets=None)` (the default) means *no credentials*, so the tool registers and then
refuses `exa_not_configured` before any spend. Resolving that default to `Secrets()` inside
`build_toolbelt` would make every test toolbelt compose a live billable Exa client off any `.env`
with a key in it. Production roots pass a real `Secrets` explicitly.

**The recipe.** `onboarding-synthesis-unit@1`
(`platform/execution/recipes/onboarding-synthesis-unit-v1.json`): barrier → one `agent`-authority
gate `onboarding_synthesis_interactions` → barrier. `tool_allowlist` and the gate's
`dynamic_tool_allowlist` are both exactly `["exa_search_evidence@1"]`; the gate statically requires
the `audience-persona@v1` skill and `dynamic_pin_kinds: ["skill"]` re-observes it per dynamic child.

**The catalog.** Profile `onboarding-synthesis@v1`, `status: active`, one tool, two skills
(`icp-synthesis@v1`, `audience-persona@v1`), prompt `onboarding-synthesis@v1`, model
`x-ai/grok-4.6` at the model's default reasoning (ruling O-D1; `ONBOARDING_SYNTHESIS_AGENT_MODEL`
overrides, `_EFFORT` stays blank). Resolved pins:

| resource | version | sha256 |
|---|---|---|
| profile `onboarding-synthesis` | v1 | `9ca9e369845390a0e79b304cd04e711876f90225ae158d9b9f021c15755c0095` |
| prompt `onboarding-synthesis` | v1 | `f8f87351b9555a9d4eb19faee7ad23743dd15f31af13c99f20088458f0be3a6b` |
| skill `icp-synthesis` | v1 | `d41309b202587a3043d762c211bdd5d8246154b5dccf252faba286214a4e1d67` |
| skill `audience-persona` | v1 | `1355c87c8652eecdf2f6c2b02363f067d0f9d717cc59ecde4abdd55a6ec99552` |
| tool `exa_search_evidence@1` | in/out | `77e25c57…842858d` / `f2ecfbb9…4b4cc45a` |

**Resource manifest `aggregate_sha256` =
`3acf3a890b0132a7d2b3e768a7c376a83b419c2dbf3db6ecedb43c38038015d2`.**

**The runner.** `platform/api/clue_api/onboarding_synthesis_wiring.py` —
`OnboardingSynthesisLauncher`. Deliberately **outside** `clue_api/arv2/`: composing a governed
deepagent turn means importing the agent/execution substrate, which the ARV2 lane may not do. Its
shape is the account-research unit runner with the account scope replaced by the **brand** scope:

1. read the brand's current servable knowledge documents (max version per path, status in
   `ready|proposed|confirmed`, bytes present); refuse `empty` unless both `company-overview` and
   `product-catalog` are there;
2. materialize each read-only under `inputs/brand/knowledge/<path>` as a `WorkspaceSeedFile`, with
   an explicit collision check against the canonical context paths;
3. `ensure_onboarding_project` — the deterministic per-brand system `project` row;
4. start + drive the durable C5 execution (`operation_id_from_key(run_id, "onboarding-synthesis-unit@1")`);
5. acquire the one-execution workspace lease, persist the four trusted artifacts (synthesis card,
   $5 record-only budget envelope, resource manifest, user message);
6. `AgentTurnRequest` with `turn_id = uuid5(TURN_NAMESPACE, run_id)`, replay short-circuit on a
   committed outcome;
7. run the turn, decide the gate `complete`, assert the recipe completed;
8. register each identified `outputs/` file as a versioned `brand_knowledge_document`.

Failure law: **every** failure is an `OnboardingSynthesisResult` (`completed|empty|failed`), never
a raise — the driver records step outcomes. Cost is summed from the evidence tool's own durable
receipts, not guessed.

## Rulings this lane took

1. **Per-brand system project row, born `archived`.** `agent_turn.project_id` and
   `execution.project_id` are real FKs, so a governed turn must belong to a project. Onboarding is
   not a marketing motion, so the row is a scope anchor with no product and `status = 'archived'` —
   never something a marketer opens.
2. **Inputs under `inputs/brand/knowledge/`.** The knowledge documents are workspace **input
   files** read with the framework's `read_file`, not context candidates. L3 is generous (brand
   card, budget envelope, synthesis card); L4 memory and L6 conversation are **zero** — this
   surface has neither.
3. **The `audience-persona` skill is the evidence tool's pin.** `exa_search_evidence@1` declares
   `pin_requirements=("skill",)`: it is spendable only inside a slot that pinned the skill telling
   the model what evidence is *for*.
4. **Document identity comes from front matter**, via `clue_api/arv2/knowledge_frontmatter.py`
   (the inverse of `onboarding_documents.render_markdown`). An output whose front matter is
   unreadable, whose `kind` is not producible here, or which carries no `icp_key` is **skipped and
   logged, never a failure** — the turn's other documents are real, and an unidentifiable file is
   honestly not a document. `icp-definition` is born `proposed` (a proposal a human confirms);
   `audience-persona` is born `ready`.
5. **`build_toolbelt(secrets=...)` is fail-closed** (above). The default is *no credentials*.
6. **A flat skill file exists only for the pin resolver.**
   `platform/agents/skills/audience-persona-v1/SKILL.md` is a duplicate the execution layer's flat
   skill discovery needs to resolve the recipe's `skill` pin. **The catalog copy
   (`platform/agents/catalog/skills/audience-persona/v1/SKILL.md`) is authoritative** — it is what
   the profile sha-pins and what the agent reads. The stub says so in its own body.
7. **The fourth role CHECK is its own revision** (`dfb9fa040b13`), not an amendment of
   `000b9d8bb17b` — the first was already applied to the throwaway DB, and the house rule is
   forward-only reversible revisions.
8. **The profile resolves WITHOUT a surface.** A surface is a *narrowing*, and the registry refuses
   one that withholds nothing. This role's whole reviewed authority already **is**
   `exa_search_evidence@1`, so the unit surface and the full surface are the same set; the recipe
   slot is the real second ceiling.

## What is composed, and what waits for the O3 merge

`fleet_main._serve` now composes the launcher behind `CLUE_ONBOARDING_V2_ENABLED`
(`Settings.onboarding_v2_enabled`, default `false`, already in `.env.example`):

- `build_agent_platform_components(...)` is now built when **`chat_enabled or
  onboarding_v2_enabled`** (it was chat-only). The onboarding turn needs the same profiles /
  models / workspaces / artifacts / turn journal, so the one composition is shared rather than
  duplicated. It still happens **before** `register_execution_control_tools` — that ordering is
  load-bearing (the C6 tool-authority audit covers exactly the model-facing `build_toolbelt`
  surface, and the run-control tools widen the shared registry afterwards).
- `build_toolbelt(..., secrets=secrets)` — added at the fleet root, so the evidence tool gets a
  real Exa client in production instead of refusing `exa_not_configured`.
- `synthesis_launcher = build_onboarding_synthesis_launcher(...)` when the flag is on, else `None`;
  one `onboarding_synthesis.launcher_composed` info line records which.

**Waiting for the O3 merge (a sibling branch, not in this tree):**

1. **The `synthesis=` handoff.** O3's `OnboardingRunWorkHandler` does not exist here. The merge
   edit is one line — `OnboardingRunWorkHandler(..., synthesis=synthesis_launcher)` — at the marked
   comment in `fleet_main._serve`. Until then the launcher is composed and parked.
2. **The Alembic merge.** This branch's head is `dfb9fa040b13`; O3's is `af3cf1541ebe`. Both chain
   off `3742d1281a10`, so the integration needs `alembic merge -m "merge dfb9fa040b13+af3cf1541ebe"
   dfb9fa040b13 af3cf1541ebe` — never a hand-renumber, and `alembic heads` must return to one line.

The web process (`projections_main`) is deliberately **not** changed: it never runs the synthesis
turn (the launcher is a fleet-root composition, and the tool is granted to the
`onboarding_synthesis` role only), so passing `secrets` into its `build_toolbelt` would widen a
credential surface for no consumer.

## Carry-over fixes made in the close-out commit

- **`supersedes_document_id` was never written.** `_register_documents` computed the next version
  and retired the old row, but left the new row's `supersedes_document_id` NULL, so the version
  chain was only inferrable from the ordering. One read now returns both the next version and the
  previous highest-version *servable* document id, and the insert names it. Red-proofed: with the
  value forced back to `None` the new assertion fails.
- **The frozen contract digests were stale.** `tests/agents/test_contracts.py`'s
  `test_frozen_contract_json_schema_digests` was **red on this branch** before this task: adding
  `AgentRole.ONBOARDING_SYNTHESIS` moved the five digests whose schema embeds the role enum
  (`AgentProfile`, `AgentConstitution`, `AgentTurnRequest`, `AgentPlan`, `DelegationRequest`) and
  the in-commit contract-delta ritual was not performed. Done here, with the delta named in a
  comment. **Proven to be exactly that delta and nothing else**: recomputing the digests with the
  new enum member temporarily removed reproduces all eleven pre-lane values byte for byte.

## Known red, NOT this lane's

`tests/api/test_agent_registry_wiring.py::test_design_profile_resolves_with_the_full_granted_write_surface`
fails: `platform/agents/catalog/profiles/design/v1/profile.yaml` carries the **malformed** model id
`openai/x-ai/grok-4.6` (a doubled provider prefix — `openai/` in front of `x-ai/`) where the test
expects `openai/gpt-5.6-terra`. Pre-existing: `git log` on that file shows the last touch is
`00f510f38 "cleaning and organisation"`, well before this lane. Every other profile writes
`x-ai/grok-4.6` correctly. **This needs an owner** — it is either a bad grok cutover on the design
profile or a stale expectation in the test, and nobody on Track O can decide which.

## Gates run

- `tests/agents tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py
  tests/api/test_onboarding_evidence_tools.py tests/api/test_onboarding_synthesis_wiring_db.py
  tests/db/test_arv2_onboarding_synthesis_role_migration.py tests/arv2
  --ignore-glob='*_live.py'` → **1 failed, 603 passed** (the one failure is the pre-existing
  `design@v1` model id above).
- `uv run alembic heads` → `dfb9fa040b13 (head)`.
- Standing-rule greps (`client_kb_version|readiness_decision|project_run_stage0_pins|
  evaluate_stage0_readiness` over `clue_api/onboarding_*.py` + the three catalog dirs) → **zero
  hits**. The profile lists **exactly one** tool.
- ruff check + format --check clean on every touched file; `uv run mypy
  platform/api/clue_api/onboarding_synthesis_wiring.py platform/api/clue_api/fleet_main.py` clean.

No secrets or keys are recorded here.

## Addendum — merged (2026-09-08)
Both lanes are on `integration/design-improvement`: O3 at merge `1250fe8af`, O4 at merge `e47ec67df`.
The two owed merge-time edits landed in `e47ec67df`: Alembic join **`9f81e5692fea`** over
`af3cf1541ebe` (O3) + `dfb9fa040b13` (O4) — one head, up→down→up verified on `clue_o3_driver`;
and the O3 ⇄ O4 handoff in `fleet_main` — `_SynthesisSeam` adapts `OnboardingSynthesisResult` to
the driver's `SynthesisOutcome` field for field and `_build_onboarding_handler(..., synthesis=)`
hands it to the onboarding driver (pinned by `test_the_synthesis_seam_hands_o4_outcomes_to_the_o3_handler`).
`clue_semarang` is at `9f81e5692fea`. Still not run: O3's acceptance run and O4's live turn
(both founder-triggered, both spend). Known reds not this work: `design@v1` malformed
`model_id`; `tests/db/test_db_migrations.py` needs an empty DB (sibling suites leave
`entity_research_job` fleet tasks behind).

## Addendum — live acceptance, Insight Health (2026-09-08, founder-triggered)
Three unseeded runs through the real path (`POST /onboarding` via the router in-process with the
test-user header → `DbOnboardingEnqueuer` → the semarang fleet worker → driver → synthesis turn),
workspace `ws-insight-health-o3` on `clue_semarang`, evidence in `.context/arv2-onboarding-o3-acceptance/`.
- **Run 1** `c960a7ea…` — O3 green in ~6 min ($2.55): overview/lineup/catalog_sync/reviews
  completed, 19 products minted + researched. Synthesis FAILED at profile resolution:
  `agent model timeout must be positive and no greater than gateway policy` (profile 120s vs the
  hard 30s `GatewayConfig.timeout_s` ceiling).
- **Run 2** `1eaa4293…` — O3 green ($2.25); lineup found 16 entries, 12 `alias_reused` + 4 `created`
  (reuse ladder proven live), every document at v2 with v1 superseded. Synthesis ran 4 min then
  `runtime_error`: every `exa_search_evidence@1` call refused `IncompatibleRecipe` —
  `conflicting_requirement` because the pin provider re-requested the skill the recipe already pins
  statically (bare `v1` next to a digest-pinned `v1`). The offline runner test never called the tool.
- **Run 3** `280cd8f5…` — **fully `completed`, no gaps, $2.97**: 21 products; synthesis completed in
  12 min wall, 18 model calls (1.34M in / 38k out tokens on grok-4.6), 15 evidence calls ($0.225),
  3 ICP documents `proposed` (454–519 words, 4–5 hard gates, all five persona roles) + 3 persona
  documents `ready` (2.7–2.8k words each, 8/18/13 evidence URLs), all `produced_by_turn_id` set.
  Spot-read: file-path citations on client facts, verbatim quotes with URLs from the evidence
  tool, no fictional names.
Fixes landed during acceptance (all on `integration/design-improvement`): `fad664b04` +
`8fb4c439e` (profile timeout; `CLUE_GATEWAY_TIMEOUT_S`, default 30, 60 here), `046b6ebc3`
(`CLUE_AGENT_MODEL_TIMEOUT_S` — one deployment-wide per-call timeout for every agent model call,
founder ruling; the model-catalog GET uses the gateway timeout), `3f8721af6` (pin provider no
longer re-pins the static skill). **Owed:** the scripted `exa_search_evidence` call added to
`tests/api/test_onboarding_synthesis_wiring_db.py` in `3f8721af6` is committed UNVERIFIED (founder
paused suite runs to get the live run back); run it, and decide whether a refused
`exa_not_configured` call needs a `FakeExa` in `for_tests`. Observations, not defects: the
lineup's `integration`/`partner_program` entries become product rows by contract (§5 line 168) —
the product-set gate is where a human prunes; near-duplicate names (AI Front Desk / AI FrontDesk
Agent) each cost a $0.10 research run; ARV2 JSONL ledger rows re-report a run's cumulative price
per poll, so a consumer must not sum polls (the step's `cost_usd` is authoritative);
`agent_model_call.cost_millicredits` is 0 for grok via OpenRouter (cost attribution gap, not this
lane). The semarang fleet worker was left running (`/private/tmp/semarang-fleet-worker.log`).
