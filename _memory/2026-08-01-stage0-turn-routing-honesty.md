# Stage-0 turn routing honesty + per-turn readiness recompute (task 5)

Branch `platform/clue-trial`. Closes the third Phase-B defect from
`_memory/2026-07-31-stage0-structured-output-failure-chain.md`: the agent claimed "captured as
project state" across 7 turns with zero durable statements, and `readiness_decisions` stayed empty.

## What landed

1. **`count_statements_for_input`** (`clue_research/stage0/governed.py`) — routing receipts for one
   captured onboarding input, split `total` / `non_unmapped` (`StatementCounts`). This is the
   durable answer to "did this turn record anything?", asked without reading prose. It spans every
   route kind (unlike `read_statements`, which serves one route kind under a project) and keys on
   the onboarding input, because that is what identifies a single captured user turn.
2. **`Stage0RoutingReceiptGuard`** (`clue_api/stage0_trial.py`) — rides the existing
   `CompletionGuard` seam. Refuses `completed`/`awaiting_input` when a substantive turn has zero
   receipts; `failed`/`blocked` are never gated. "Substantive" is `is_pure_command()`, purely
   syntactic (single-line slash command with ≤3 args = command). Rejection message names
   `record_interview_answer` and the `unmapped` escape hatch, and rides task 3's bounded finalize
   repair — one visible retry, then still `missing_finalize`.
3. **Guard call site widened to `awaiting_input`** (`agent_runtime_wiring._finalize_tool`,
   `_GUARDED_STATUSES`). Consequence: `account_research_wiring.require_terminal` now returns early
   unless the status is `completed`, so its engine-terminal-coverage semantics are unchanged.
4. **`HeadOfAbmStage0Runtime.run(completion_guard=...)`** — optional, because only the calling
   surface knows this turn's onboarding input.
5. **`Stage0Trial._recompute_readiness`** — after any turn with ≥1 non-`unmapped` receipt, re-runs
   the existing C4 `evaluate_readiness` (gate `icp_synthesis`, `DEFAULT_STAGE0_POLICY.readiness`)
   over durable truth. No second readiness implementation. Decision id is
   `uuid5(turn_id, "...:gate:brand:confirmed_product:project:client:kb_version")` so a replay is
   idempotent and a context change records a new honest decision instead of tripping the
   evaluator's immutable-context replay check. Actor is `system` (DB CHECK pins the vocabulary).
6. **Catalog:** `skills/stage0-interview/v4` adds §3a "Report receipts, never claim capture";
   published bytes are immutable, so `profiles/head-of-abm/v6` pins it and
   `C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM] = "v6"`. New Head aggregate manifest digest
   `4c0f86939c0d23dbcb4e28cfd083f345868582592d10c4cafe5d55a0f88e7676`.

## Confirmed, not changed

`InterviewRoute.UNMAPPED` already needs only `route_key` + quote offsets (`_route_shape` imposes no
extra requirement), and `RecordInterviewAnswerInput` does not require a statement of any other
route. Nothing had to be relaxed for the escape hatch — pinned by a live DB test instead.

## Tests

`tests/api/test_stage0_routing_honesty.py` (17): the syntactic substantive/command split; DB tests
for refusal on both guarded statuses, UNMAPPED satisfying the guard, pure-command exemption,
`failed`/`blocked` never gated; DB tests for the readiness row (present + idempotent after a
material turn, absent after an unmapped-only turn); and two scripted-model runs through the real
deepagent loop — refuse → visible feedback → route → commit, and two receiptless attempts still
`missing_finalize`. RED evidence: with the guard call site disabled both scripted tests fail.

Suites green: `tests/agents tests/stage0 tests/api`. `make typecheck` and `make contracts` clean.
`make lint` has 17 pre-existing `ruff format` failures on this branch (905 formatted before my
change, 908 after — none of them mine).

## Open / handed on

* The pure-command rule is deliberately generous (a >4-token line starting with `/` is treated as
  substantive). Fail-open only in the sense that a real command is not forced to route; the honest
  escape hatch keeps the cost of a false negative at one `unmapped` route.
* Readiness is recomputed at gate `icp_synthesis` only. Its floor is permissive
  (`min_coverage_ratio=0.0`), so the verdict is usually `ready`; the value here is that the ledger
  exists and is explainable, not that the gate is discriminating. If the trial later wants a
  discovery/deep readiness view per turn, that is a policy decision on the floors, not new code.
* Ledgered, out of scope (final review): `brand_id` is model-supplied on Stage-0 tools while the
  constitution also carries it, and nested free-form payloads can carry `project_id` keys.
