---
schema_version: "1"
kind: skill
name: account-gap-research
version: v3
summary: Drive bounded account-global coverage rounds from the typed durable result projection.
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
2. Treat the round number as account-global. On every normal round, submit all unresolved planned
   fields that fit the tool's field cap so each field can traverse the bounded waterfall before the
   shared round ceiling. Do not spend a global round rotating to one fresh field. If the planned
   list exceeds the tool cap, preserve the excess as explicitly blocked because the current engine
   cannot guarantee full traversal for it.
3. Use the next explicit durable round number; never reuse or skip a round. Omit `strategy_hint`
   unless prior durable decisions name the same exact next engine strategy for every submitted
   field. A source-family label such as `official_site` is not a strategy key.
4. Call `research_account_gaps@2`. A normal call executes the existing pre-spend gate, source
   waterfall, promotability filter, budget record, independent evaluator, and append-only coverage
   ledger. The returned `references` object is the durable ledger projection for this turn:
   `terminal=false` plus a positive `remaining_gap_count` means call the next round immediately,
   not that the ledger is missing. The returned claim ids are references, not permission to
   restate unsupported bodies.
5. Follow only `next_strategy` behavior admitted by the engine. Evaluator recommendations are
   advisory context. They never create `filled`, `unfilled_terminal`, `blocked_by_policy`, or
   `budget_exhausted`.
6. Use `propose_stop=true` only when an explicit upstream instruction asks for a stop challenge;
   do not self-stop after an ordinary successful non-terminal round. A stop proposal journals the
   sole C1 evaluator's challenge but creates no attempt or terminal decision. Without that explicit
   instruction or a real tool error, continue account-global rounds until `terminal=true`.
7. Complete only when every initially planned gap has an engine-authored terminal decision. Report
   coverage-decision, attempt, evaluator-advice, claim, operation, and execution refs. Never claim
   verification or committee/contact completion; the existing outer deep pipeline owns those
   later stages.

V3 deliberately has no facet subagent. Batched account-global rounds plus the governed waterfall
already supply bounded decomposition, while another research agent would add shared-envelope and
evaluator ambiguity without demonstrated quality benefit.
