# Stage-0 Terra structured-output failure chain — verified 2026-07-31

Source: Codex investigation transcript (`.context/attachments/pxwnxL/pasted_text_2026-07-31_21-24-02.txt`,
runs `trial-65be885b9b0fe5ad`, `trial-live-aura-20260731-a1/b1` under `.context/sumble-trials/`).
All three defects independently re-verified in this checkout (branch `platform/clue-trial`). No code changed yet.

## Verified failure chain (a Stage-0 turn fails through three stacked defects)

1. **Provider rejects the tool schema batch (HTTP 400 before the model runs).**
   `CostCents = Annotated[Decimal, Ge(0)]` (`libs/clue-core/clue_core/primitives.py:66`) →
   `SourceManifestDraft.cost_cents` (`subsystems/research/clue_research/proposals/models.py:111`) →
   `propose_source@1` in the Head-of-ABM profile. Pydantic emits a negative-lookahead regex
   (`^(?!^[-+.]*$)...`) in the JSON schema; OpenRouter's Responses API rejects regex lookaround.
   All bound tool schemas are sent together, so one bad schema blocks every turn.
   `convert_to_openai_tool` (`libs/clue-gateway/clue_gateway/agent_model.py:74`) does no
   provider-subset sanitization and does not use `strict`.
2. **Governed wrapper rejects the model's valid tool call.**
   `agent_runtime_wiring.py:505` passes LangChain-validated kwargs (containing nested Pydantic
   `InterviewStatement` instances) directly into `PlanToolStep.arguments`, which is JSON-only →
   `arguments.statements.list.0: input was not a valid JSON value`. Affects every governed tool
   with nested models. Fix shape: `model_validate(kwargs).model_dump(mode="json")` at that seam.
3. **Model-facing finalize contract is looser than the durable envelope.**
   `ModelFinalizeRequest` (`agent_runtime_wiring.py:233`) allows `status=awaiting_input` +
   `failure_code`; `AgentFinalizeEnvelope.terminal_shape_is_honest` (`contracts.py:860`) rejects
   it → turn ends `missing_finalize` with no feedback to the model. Same class as the earlier
   `next_actions`-omitted repair: model boundary looser than the durable contract.

Also confirmed context: GPT-4.1-era run `trial-65be885b9b0fe5ad` had 7 turns, 0 agent plans,
0 tool results — the model chatted without proposing governed writes while claiming it had
"captured" state; nothing reached the Client KB, so ICP synthesis emitted the generic fallback.
Terra (with `tool_choice=required`) does propose the correct `record_interview_answer` call —
the platform, not the model, is now the blocker.

## Structured-output strategy assessment

Function-calling + `tool_choice="required"` + local Pydantic validation is the right architecture
for the governed loop. The gap is that model-facing schemas are generated from rich domain types
and never checked against the provider-supported JSON-schema subset, and model-facing contracts
are allowed to be looser than durable ones. Rule going forward: model-boundary schemas stay
JSON-simple and at-least-as-strict as their durable counterparts; provider compatibility is a
gateway-adapter concern with a repo-wide fail-closed gate.

## Test intent (user clarified 2026-07-31)

The CLI trial was NOT a full research-quality test. Its pass criteria are Stage-0 mechanics only:
conversation → durable interview statements + Client-KB claims → readiness decisions → enforced
product-confirmation gate → ICP grounded in the conversation with `justifying_claim_ids`.
Sumble/scoring/deep/C7 are later steps of the same journey, untested by design. Consequence:
Phase A alone does not make the trial passable — synthesis-input fix (project-state statements),
product gate, and receipts-honesty are part of the trial's own acceptance criteria, not polish.

## Agreed repair sequence (pending user discussion)

Phase A (transport blockers): (1) fix `CostCents`/schema emission + add repo-wide active-profile
tool-schema provider-subset gate; (2) JSON-normalize governed tool arguments + nested-model
regression matrix; (3) make `ModelFinalizeRequest` structurally match the envelope (discriminated
by status) + surface validation feedback to the model with the existing bounded retry.
Phase B (Stage-0 honesty): captured-language requires durable receipts; ICP synthesis must read
project-state statements; typed not-ready instead of generic ICP; readiness recompute; CLI
multiline input. Phase C: rerun Aura/neurosurgery acceptance trial, then supervised 3-credit
Sumble canary.
