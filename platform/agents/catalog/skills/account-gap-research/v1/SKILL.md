---
schema_version: "1"
kind: skill
name: account-gap-research
version: v1
summary: Run bounded, replay-safe coverage rounds for one admitted account while preserving engine authority.
roles:
  - account_research
readiness_requirements:
  - account.entity_resolved
  - account.plan_pinned
  - account.budget_admitted
  - account.coverage_ledger_available
tools:
  - name: research_account_gaps
    version: "2"
    input_schema_sha256: 78a44346c88752e3efcf8809b49ed09aaa7a7182bb80e5072b673ec62e4ac635
    output_schema_sha256: ef4959afdd7669c57dfa2f4d531e47e85b2315935f1f663de292b652475f661e
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Governed per-account gap research

Use this skill only for the one account and durable plan named in the turn.

1. Read the complete planned gap list, prior attempt and decision refs, budget remainder, and
   allowed strategy transitions. Never add an unplanned field.
2. Rank fields by decision value. Select a bounded subset no larger than the tool and tier caps.
   Use the next explicit durable round number; never reuse or skip a round.
3. Call `research_account_gaps@2`. A normal call executes the existing pre-spend gate, source
   waterfall, promotability filter, budget record, independent evaluator, and append-only coverage
   ledger. The returned claim ids are references, not permission to restate unsupported bodies.
4. Follow only `next_strategy` behavior admitted by the engine. Evaluator recommendations are
   advisory context. They never create `filled`, `unfilled_terminal`, `blocked_by_policy`, or
   `budget_exhausted`.
5. If further work appears wasteful, call the tool with `propose_stop=true`, no strategy hint, the
   next round, and the remaining planned gaps. This journals the sole C1 evaluator's challenge but
   creates no attempt or terminal decision. Preserve those gaps and finalize `blocked`.
6. Complete only when every initially planned gap has an engine-authored terminal decision. Report
   coverage-decision, attempt, evaluator-advice, claim, operation, and execution refs. Never claim
   verification or committee/contact completion; the existing outer deep pipeline owns those
   later stages.

V1 deliberately has no facet subagent. The field subset plus governed waterfall already supplies
bounded decomposition, while another research agent would add shared-envelope and evaluator
ambiguity without demonstrated quality benefit.
