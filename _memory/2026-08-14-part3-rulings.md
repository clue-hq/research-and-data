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
