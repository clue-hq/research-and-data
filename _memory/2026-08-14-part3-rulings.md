# 2026-08-14 — Part III rulings ratified; spec frozen; surveys digested

Branch `integration/frontend-design-part-iii` context. Part III (design-agent integration)
opened after the stability arc closed (lumenFetch defaults + guards, `<img>` content-addressed
serving, editor CI, API route-table seam guard — see the 2026-08-12 notes).

## What happened

Three parallel Part-III grounding surveys ran 2026-08-14 (platform agent runtime + lane-D
turn ingestion; design agent runtime + fleet; C8 context assembly + bundle ingredients).
Full reports are in the session transcript; the load-bearing facts are baked into
**`docs/specs/PD-part3-agent-integration.md`** — the ratified implementation contract
(founder sign-off 2026-08-14 on all five rulings D1–D5). Read THAT spec first; this note is
the trail.

## The five rulings (summary — spec §1 is authoritative)

- **D1**: HITL = durable `design_leg` row + ingestion routing rule ("open leg on thread
  gets the message"), NOT a LangGraph `interrupt` (repo has zero interrupts + standing
  rulings against; and the design checkpoint can't capture the working substrate anyway —
  resume-as-restart is honest, `lumen_agent/checkpoint.py`). Turn-terminal legs make the
  kill/resume gate test pass on today's substrate; mid-turn kill stays fence-protected
  restart.
- **D2**: ONE platform role `AgentRole.DESIGN` = the composite design deepagent; the
  orchestrator/author/reviewer trio stays internal to the design runtime on `design_job`
  (a doorway, not a container; no DESIGN_AUTHOR/REVIEWER roles).
- **D3**: design-leg turns execute on the design fleet lane AND land as `agent_turn` rows
  (role=design, parent_execution_id); leg lifecycle on the chat turn stream; `design.*`
  progress stays on the design_run subject; one-stream rendering = Part IV.
- **D4**: per-thread single-flight stands; concurrent design sessions = across threads.
  (Resolves the PD-part2 §353 open leaning — the fleet DOES host the design deepagent.)
- **D5**: bundle carries nullable binding_set_ref/template_revision_ref + brief (no
  fabricated content plane); document pin = CAS guard on current_version; brand-kit pin
  fail-closed (silent default fallback becomes an error when a pin is present).

## Survey facts most likely to be re-needed (with pointers)

- Delegation-bundle precedent to copy: `ProjectContextArtifact` research-directive,
  `account_research_turn_wiring.py:380-403`. Bundle rides `DesignTurnEnvelope.config`.
- Routing decision points: hardcoded `role=AgentRole.HEAD_OF_ABM` at
  `agent_turn_fleet_wiring.py:413` (worker) + accept-time visibility at `router.py:500`.
- focus_refs is live but triple-narrowed to account|contact: `chat/schemas.py:139`,
  DB CHECK `39513bbba38a:44`, reader if/elif `account_research_turn_wiring.py:193-225`
  (unknown types silently dropped at `context.py:425-426`).
- Role vocabulary = 3 DB CHECKs (`7e9269ed8a81` agent_turn_role; `6628a407e993`
  agent_plan_role + agent_delegation_roles) + closed Literal on SpecialistTaskEnvelope.
- 47 design tools registered with authority `()` reason `design_agent_not_wired_until_part_iii`
  (`agent_registry_wiring.py:328-376`); granting flips the exact-equality audit.
- Gateway move breakage list (design survey §c): extra_body not settable (loses OpenRouter
  replica pinning → ~95% cached-prefill economics), multimodal preflight needs a
  capability seam, Responses-API translation of image tool-result blocks UNVERIFIED (probe
  first — highest-risk item), per-role attribution needs one authority (design builds
  3 model instances per role; platform ledger has no role column; cost_millicredits
  hardcoded 0 at `agent_runtime_wiring.py:240`).
- Design runtime has NO cross-turn conversation history (fresh agent + scene re-POST per
  turn) — leg history store is net-new under any design.
- `previous_turn_outcome` has zero senders anywhere (clarification policy never fires in
  prod); Part IV owes it a surface.
- FreshWakeSpecialistRunner asserts zero history (`specialist_wiring.py:199-211`) — the leg
  needs its own runner, not a parameter.
- Two design package roots: durable DAL `subsystems/design/clue_design/`; apps
  `subsystems/clue-design/`. Cite carefully.

## Next

P3.1 (schema/vocabulary) ∥ P3.2 (gateway move — start with the Responses-API image probe)
per spec §4. No implementation had started as of this note.

## P3.1 SHIPPED + P3.2 probe PASSED (2026-08-14, same session)

- **P3.1 committed `4c0ef79b`**: AgentRole.DESIGN + 3 CHECK widenings (migration
  `549de68ae3b9`, up-down-up green); `design_leg` + append-only exit journal + one-open-
  per-thread partial unique + `clue_design/legs.py` DAL (state machine, fail-closed
  tenancy, out_of_scope requires pending ref, reopen keeps journal); design_agent_run
  leg/execution linkage; focus_refs triple widening incl. validated_context_refs
  design_document branch (string ids; CAS-pin stale refusal) + L5 card reader branch
  (v0 documents = unversioned cards — DomainObjectRef floors at 1, caught by test);
  previous_turn_outcome platform field CHECK-bounded on agent_turn_submission.
  Frozen-contract digests revised in-commit (C8 precedent). 11 new tests; 139 then 213
  green in combined regressions; lint-imports 26/26; ruff+mypy clean.
- **P3.2 probe (`scripts/p32_probe_responses_api_images.py`, run live on
  openai/gpt-5.6-terra via damascus workspace .env key): ALL THREE PASS.**
  (A) image block in HumanMessage → vision works through GovernedAgentChatModel;
  (B) THE risk — the exact lumen_agent view.py shape, text+image content blocks inside
  ToolMessage in a tool-call round trip → the model SEES the image (named the color)
  through use_responses_api=True / output_version=responses/v1;
  (C) forced tool call with a VisualCritique-like pydantic schema through bind_tools'
  provider_compatible_tool_schema rewriting → parses back correct.
  Telemetry confirms remaining P3.2 build items: cached_input_tokens=0 (no
  usage.include/provider-sort extra_body yet → GatewayConfig passthrough still needed
  for the ~95% prefill economics), cost_cents=0 (no price-table entry), truthful
  clue_answering_model stamped.
- **P3.2 remaining build (next work unit):** GatewayConfig extra_body passthrough;
  supports_image_input capability seam on AgentModelProvider (replaces the raw-key
  preflight); per-role ModelPolicy; ONE durable per-role usage authority (role into the
  gateway ledger, retire design-local double-count); design harness onto
  AgentModelProvider.build ×3 (one instance per role — attribution mechanism).

## P3.2 checkpoint 1 SHIPPED (2026-08-14, commit 61cdebad)

Gateway-library half of the move, live-verified ("no compromise" mandate honored):
- GatewayConfig.openrouter_provider_sort + openrouter_usage_include (policy-as-data,
  default OFF) → provider threads extra_body onto the Responses request.
- build(role=...) → attribution_role on GovernedAgentChatModel: rides
  response_metadata.clue_role + llm.gateway_call span (new ATTR_AGENT_ROLE in clue_obs,
  allowlisted) + model_call_usage record via record_model_call(role=). ONE per-role
  authority; one-instance-per-role stays the mechanism.
- clue_core.gateway.TokenUsage contract-delta: additive cached_prompt_tokens (default 0)
  populated from usage_metadata.input_token_details.cache_read; logged in
  model_call_usage (tracing's "deliberately absent" note retired).
- OpenRouterAgentModelProvider.supports_image_input(model_id) — catalog-backed
  True/False/None, fetched once per instance, caller decides failure hardness.
- Offline: 4 new tests in tests/gateway/test_agent_model.py (mock Responses endpoint
  wire-shape assertions; default config sends neither knob); core/gateway/obs suites
  green; ruff+mypy clean.
- LIVE probe #2 (scripts/p32_probe_economics.py, gpt-5.6-terra): extra body ACCEPTED by
  the Responses endpoint; second same-prefix call cached 4624/4636 prompt tokens
  (99.7% prefill hit — the design cache economics survive the governed gateway);
  role=design_author on metadata + usage log; catalog vision=True.

## P3.2 remaining (checkpoints 2–3, next work unit)

2. Durable ledger: agent_model_call ADD COLUMN role (+ migration) and thread role from
   the runtime writer (find INSERT INTO agent_model_call; cost_millicredits=0 residual
   at agent_runtime_wiring.py:240 — decide record-or-redefer, never double count).
3. Design harness switch: lumen_agent/llm.py builds the trio via
   OpenRouterAgentModelProvider.build ×3 (role labels; per-role reasoning maps into
   GatewayConfig.agent_reasoning or per-model entries — check _reasoning_request;
   temperature: pass 1.0 to approximate today's unset; max_output_tokens from
   LUMEN_AGENT_MAX_TOKENS else a bounded default); multimodal preflight
   assert_all_role_models_support_image_input → provider.supports_image_input
   (fail-closed on False, decide None-handling); retire attach_usage_capture
   double-count (gateway record is authority; keep design trace_callbacks); keep
   cache-stability (append-only history + provider_sort pinning — proven live).
   GATE: a real end-to-end design turn on the gateway (fleet or direct harness) with
   images flowing, per-role attribution once, prefill ratio preserved.

## P3.2 checkpoint 2 SHIPPED (2026-08-14)

Durable per-role ledger attribution:
- Migration 65880921cd52: agent_model_call ADD COLUMN role (nullable text, CHECK over the
  six-role vocabulary; historical rows honestly NULL). up-down-up green.
- AgentModelCallReceipt.role: AgentRole | None (additive); DbAgentTurnJournal
  .record_model_call threads it through INSERT + the replay-compare (a different role
  under the same id = "different immutable receipt").
- Producer (DurableAgentModelCallHandler): resolve_model_call_role(response_metadata,
  constitution_role) — per-call clue_role label wins (the design trio's
  three-roles-in-one-turn case), constitution role else; unknown labels fall back, the
  recording path never fails on attribution; on_llm_error stamps the constitution role.
- cost_millicredits=0 residual DECIDED: stays 0, re-deferred with an in-code ruling —
  real cost is measured ONCE at the gateway (clue_cost_cents + span); cents→millicredits
  conversion belongs to the uncomposed millicredits milestone owner; never record cost in
  both places.
- Tests: tests/api/test_p32_model_call_role_db.py (role round trip both shapes,
  replay-immutability, CHECK bound, resolve-role unit incl. unknown-label fallback; the
  seeded turn itself exercises role='design' through the P3.1-widened agent_turn CHECK).
  Neighbor regression: runtime-wiring + turn-wiring + agents = 198 passed, 1 failed —
  the DOCUMENTED pre-existing lane-D red (test_durable_turn_history_replay..., red on
  pristine origin/main; not ours). ruff + mypy clean.

Remaining: checkpoint 3 only (design harness switch + real end-to-end design turn gate).

## P3.2 checkpoint 3 SHIPPED (commit 1d916f64) — gate: gateway properties PASS, one open item

Harness switch complete (init_model = governed adapter, role labels design_*, usage
capture retired, vision guard on the capability seam, provider catalog dual-shape parse,
tests rewritten to the new contracts; design suite 548 passed / 2 skipped).

**LIVE gate on gpt-5.6-terra (CLI, real spend), two runs:**
- ALL gateway properties PASS at scale: run 2 = 3,362 model calls, every one role-tagged
  (orchestrator 12 / author 12 / reviewer 3,338); cached prefill on 3,341/3,362 calls,
  MEAN RATIO 0.992; ZERO design-local usage events (single authority holds); previews
  rendered through the engine helper (iterations/003/preview.png) — images flowing.
- OPEN ITEM: the turn did not finalize — the REVIEWER loops (3,338 tiny calls, repeating
  an IDENTICAL read_file(rounds/round_1/critique.json, limit=5, offset=0) with only 3
  view_called events), hitting GraphRecursionError 9999; the harness honestly failed the
  turn (guaranteed-honest-finalize worked). Both runs show the same runaway.
  PRIME SUSPECT: the governed baseline _reasoning_request sends effort=NONE for gpt-5.6
  models, while the old design path sent NO reasoning field (provider default) — a
  no-reasoning reviewer degrades into myopic identical-call loops. Decisive experiment
  IN FLIGHT: rerun with LUMEN_AGENT_REASONING=medium (overrides the baseline wholesale;
  workspace /tmp/p32-gate-workspace3). If it finalizes → fix is policy (design sets an
  explicit effort; consider changing the design default in py_lumen_config), not code.
  If it still loops → dig into the Responses-loop/ToolStrategy interaction next
  (deepagents reviewer stop condition under the governed wrapper).

## P3.2 gate — provider-shape findings ledger (2026-08-14, runs 3-5)

Run-by-run on gpt-5.6-terra (all with the switch code; MAX_ITERATIONS=1):
- runs 1-2 (effort inherited = platform NONE baseline): reviewer myopic loop (3,338
  identical read_file calls) → recursion limit. ROOT CAUSE of the loop. Fixed by policy:
  lumen_agent_reasoning default now "medium" (commit c11dc5e2).
- run 3 (medium): trio healthy (9/13/5) → upstream OpenAI server_error through all SDK
  retries at the reviewer's first HEAVY multimodal continuation (req_2b21168af2ca4...).
- run 4 (medium, ratified default): same — healthy 14/15/3, same upstream 500 at the
  same shape, 12.5 min of retries.
- run 5 (medium + fallback claude-opus-4.8, commit 7b9fdeb9): the 500 recurred, the
  fallback fired and hit a NEW wall: 404 "request contains encrypted reasoning ...
  produced under a different model. Encrypted payloads can only be replayed to the
  endpoint that created them." **FINDING — cross-model fallback is structurally unsafe
  for Responses histories carrying encrypted reasoning items.** GovernedAgentChatModel
  replays the full history to the fallback candidate; with reasoning items in history
  the fallback can only be same-endpoint. Follow-up options: same-family-only fallback
  policy; or the gateway strips encrypted reasoning items on cross-model failover
  (lossy); or no fallback for reasoning histories. Design default stays
  fallback=None (honest hard failure).
- Correlation: effort=none image calls SUCCEEDED (runs 1-2 progressed previews);
  effort=medium heavy-image continuations 500 upstream (3/3 runs). Run 6 IN FLIGHT:
  effort=low, no fallback — testing whether low keeps the reviewer sane while avoiding
  the 500-triggering shape.
- Constant across ALL runs: role-tagged attribution once per call, zero design-local
  usage events, ~0.9-0.99 cached-prefill ratios, previews rendering, honest finalize
  on every failure. The gateway properties of the gate are proven regardless of the
  provider-shape endgame.

## P3.2 GATE PASSED — slice CLOSED (2026-08-14, run 7)

**A real end-to-end design turn finalized on the platform gateway**: status=accepted,
stop_reason="Visual reviewer accepted the rendered artboard with all user requirements
satisfied", zero gaps, preflight passed, preview.png rendered
(/tmp/p32-gate-workspace7/run_7f14cd98943c4a09b6e24d86b0f62921).

Winning configuration (RECOMMEND as the design deployment default): orchestrator+author
on openai/gpt-5.6-terra, reviewer on anthropic/claude-opus-4.8 via the existing per-role
override (LUMEN_AGENT_MODEL_REVIEWER), reasoning=medium (the ratified default), no
fallback. Gate telemetry: 45 calls — orchestrator 22 (terra) / author 19 (terra) /
reviewer 4 (opus), TRUTHFUL served-model attribution per role; mean cached-prefill 0.94;
zero design-local usage events. Rationale: terra's Responses endpoint 500s on
reasoning+heavy-multimodal continuations (4/4 runs) — the reviewer is exactly that
shape, and per-role models are the first-class answer (each subagent owns its own
conversation, so no cross-model replay issue).

Standing follow-ups out of the gate saga (owners when picked up):
1. GATEWAY: cross-model fallback vs encrypted reasoning items (run-5 404) — same-family
   fallback policy, or strip reasoning items on cross-model failover, or refuse
   fallback for reasoning histories. GovernedAgentChatModel-level decision.
2. PROVIDER-SHAPE: terra + reasoning + heavy image continuation 500s upstream — track;
   revisit when the provider fixes it (the per-role split sidesteps it meanwhile).
3. Design .env guidance: document the recommended trio config in the design
   .env.example when P3.3 lands the catalog profile (the profile is the durable home
   for per-role model policy).

**P3.2 status: COMPLETE.** All six checkpoint-1..3 commits + policy fixes on branch;
next slice per PD-part3 §4: P3.3 (catalog registration).

## P3.3 SHIPPED (2026-08-14) — catalog registration complete

- Catalog entries: `prompts/design/v1/SYSTEM.md` (the composite's platform-facing
  identity: the D2 doorway framing, the leg contract, exit discipline, fail-closed brand
  pin) + `profiles/design/v1/profile.yaml` — role=design, prompt content-pinned, skills
  [] (the trio's 13 skills stay design-runtime-internal), ALL 49 governed design tools
  pinned with real schema digests (generated from the live tool registry — the registry
  validates pins == grants exactly), model policy = the P3.2-gate-ratified face
  (terra, bounded output 32768, temperature 1.0, turn_timeout 1800s), zero delegation
  (the trio is internal, not platform delegation).
- `C6_ACTIVE_PROFILE_VERSIONS[DESIGN] = "v1"`; the registry's per-role pins==grants
  validation loop now derives from that table (covers design automatically).
- THE FLIP: all 49 `design_*` authority entries `()` → `(AgentRole.DESIGN,)`; the 49
  `design_agent_not_wired_until_part_iii` reserved reasons retired; staging comments
  updated in agent_registry_wiring.py + design_tools.py.
- Audit trail updated as reviewed decisions, never weakened: the authority-audit test's
  decision table records the P3.3 grant (count stays 102 — a grant, not a tool); the
  head-of-abm resource-map test now asserts the design plane is role-unavailable with
  reason "not_admitted_for_role" (same honest shape as any other-role grant) and the
  retired reason can never resurface; catalog strict-inventory gains the two design
  addresses; NEW positive pin test_design_profile_resolves_with_the_full_granted_write_
  surface (v1, 49 pins, all AVAILABLE from design's own view, no delegation).
- Verified: 221 passed across tests/agents + registry wiring + runtime wiring + the
  P3.2 role ledger; ruff + lint-imports (26/26) clean.

## P3.4 SHIPPED (2026-08-14) — the leg engine

All six spec items landed, TDD'd against the riyadh DB (55030). Detail note:
`_memory/2026-08-14-p34-leg-engine.md`. Summary:

- **Delegation entry `open_design_leg@1`** (`design_leg_tools.py`), granted to HEAD_OF_ABM:
  derives everything from the presenting turn (TRUSTED_TURN_FIELD, gate-tool precedent),
  validates D5 pins (document CAS from durable row; fail-closed brand (id,version)),
  freezes the §2.3 bundle (canonical JSON, 24k byte cap = half the 48k L3 layer),
  opens the leg with a turn-derived id (replay converges). Ceremony: profile v24,
  C6 authority 102→103, trial withholds it, recipe0-stage0@7 (slot + graph allowlist +
  compat mirror), RECIPE_0_TOOL_ADDRESSES cert, Stage0StepPinProvider project pin via
  the injected turn ref (explicit-absence idiom).
- **Routing rule** (`agent_turn_fleet_wiring.py`): the worker reads
  `get_open_leg_for_thread` in the submission transaction; open leg → design path
  (head-of-abm engine, C5 recipe, profile checks all untouched); else unchanged.
  `_execute_watched` refactored to take the turn body as a callable — stop semantics +
  exact-artifact boundary shared by both paths.
- **Leg turn runner** (`design_leg_wiring.py::DesignLegTurnRunner`): agent_turn row
  role=design parented under leg.parent_execution_id (execution derived uuid5(turn));
  design run id derived from turn id (crash re-join, never re-run); run stamped
  leg_id+execution_id (create_run gained the params); bundle rides the constitution as
  ProjectContextArtifact AND by value in DesignTurnEnvelope.config (request/
  delegation_bundle/history/leg blocks; scene from the stored document); success =
  committed AgentFinalizeEnvelope AWAITING_INPUT with open_gate_refs=(leg) → replay
  short-circuit for free; failure = mark_unfinalized("design_leg_turn_failed"), leg stays
  open, NO manufactured finalize. No platform workspace lease (workspace_root_id =
  "design-leg:<id>", documented).
- **Execution lane**: `design_fleet.InlineDesignLaneDriver` drives the real
  DesignJobWorkHandler inline under a real work lease — NOT a queue hop, because
  LeasedWorkWorker drains one task at a time per process; an AGENT_TURN handler awaiting
  a queued design_job would deadlock a single-worker deployment against itself. Same
  claim CAS/fences. fleet_main wires it under design_runtime_enabled; disabled →
  fail-loud unavailable lane.
- **Leg-scoped history (§2.4)**: `load_design_leg_history` (role='design' +
  parent_execution_id join — leg-scoped even for turns whose run never got created);
  `load_head_of_abm_history` (role <> 'design') now IS the conversation engine's load
  (conversation_turns.py) — head-of-abm never ingests leg transcripts. Summaries at
  close = P3.5.
- **Speaker projection**: `design_legs_for_threads` anti-join; ThreadWire.speaker
  (ThreadSpeakerWire role/design_leg_id/design_leg_state, None = not derived); the
  thread listing derives it; TurnAcceptedWire.routed_to (accept-time visibility, both
  fresh + replay paths, read in the accept transaction).
- **Gate test** `tests/api/test_p34_leg_loop_gate_db.py`: strategy turn →
  open_design_leg → 2 design turns with design_document focus refs through the REAL
  ProjectConversationTurnRunner → head-of-abm sentinel 0 calls, no recipe executions,
  roles design×2 + head_of_abm×1, envelopes carry focus refs + scene + leg history,
  §2.4 scoping both sides. Plus test_p34_design_leg_tool_db (6), engine (4), speaker (2).

## P3.5 SHIPPED (2026-08-14) — finish_design_leg + mis-exit reopen

Spec §2.2 in full, TDD'd (tests/api/test_p35_finish_design_leg_db.py, 5 tests, plus the
loop-gate extension). Summary:

- **`finish_design_leg@1`** (design_leg_tools.py), granted to `AgentRole.DESIGN`
  (authority 103→104; design profile v1 gains its 50th pin) — the ONLY path to
  `closed`. Engine-validated: only the leg's own design turn may close it (role +
  parent-execution match, `design_leg_exit_wrong_turn` otherwise); reason vocabulary
  closed at the Literal. Persists the summary artifact + a durable thread message
  (uuid5(turn,"leg_summary")), journals append-only (summary_refs carries
  closing_turn_id / summary_message_id / document version at close /
  redelivered_turn_id), flips the leg, decided_by_run_id = the turn's derived design
  run. Turn-level `final.json`/`finalize_run` untouched (spec reconciliation).
- **out_of_scope re-delivery is DERIVED, never model-authored**: the pending message is
  the presenting turn's own captured user message; re-submitted as a fresh head-of-abm
  submission under a derived idempotency key (`design-leg-redelivery:<leg>:<turn>`) —
  same bytes, same submitter, same context refs; replay converges on one redelivered
  turn. dispatch_next_thread_turn offered in the close transaction (no-op while the
  thread's own task is in flight).
- **§2.4's other half**: `load_head_of_abm_history` now includes design-turn messages
  whose id the exit journal names (`summary_refs->>'summary_message_id'`) — the journal
  is the authority for what crosses the boundary; transcripts stay excluded.
- **Replay-before-open-leg ordering is load-bearing**: a stale retry of a close whose
  leg was since deliberately REOPENED replays the original journaled decision and never
  re-closes the reopened leg.
- **Mis-exit reopen** = `open_design_leg.reopen_leg_id` (the §2.1 "re-delegation names
  this leg id" edge): validates closed + same-thread + no other open leg; reopens the
  SAME leg (original bundle/pins/history/parent execution survive; journal survives);
  output gains `reopened`. Refusals: `design_leg_reopen_not_found` /
  `design_leg_reopen_wrong_thread` / `design_leg_reopen_not_closed` /
  `design_leg_already_open`. open_design_leg@1's v1 schema evolved in-train
  (reopen_leg_id + reopened); head-of-abm v24 digests + manifest aggregate refreshed
  per the P3.1 in-commit ritual (new aggregate 0c1210fc…).
- Gate scenarios (spec §4 P3.5) green: lock-in returns summary + head-of-abm resumes
  (loop-gate extension: after close the routing rule sends the next message down the
  head-of-abm path and the design lane sees no third dispatch); out-of-scope answers
  without repetition; reopen restores context (leg history resumes across the close).

Residual for the design-side owner (P3.7/design): the design ORCHESTRATOR does not yet
hold a live bridge to invoke platform tools mid-turn — finish_design_leg is registered,
granted, and engine-complete, but has zero production callers until the harness bridge
lands (same shape as `previous_turn_outcome`'s zero-senders precedent, recorded in
`_memory/2026-08-14-p34-leg-engine.md` residuals).

Part III standing: P3.0 spec, P3.1, P3.2 (gate passed), P3.3, P3.4, **P3.5 — DONE**.
Next per spec §4: P3.6 (evals & resilience: exit-judgment golden set, kill-worker/resume
leg test, single-flight + cross-thread concurrency) then P3.7 (stream bridging + close-out).
