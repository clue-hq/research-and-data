---
schema_version: "1"
kind: skill
name: research-task
version: v1
summary: Turn an explicit research assignment into a bounded gap and source strategy with durable refs.
roles:
  - research
readiness_requirements:
  - delegation.task_exact
  - delegation.canonical_sources_available
tools:
  - name: profile_contact
    version: "1"
    input_schema_sha256: 4973ccc0586a48c43fe4351dd542034eae08880bd39031a8e1779b2f170e2a3f
    output_schema_sha256: 05910e17071f7c756123ebd4e6bf71593eeae20d48ff6ff9f15808479ffe067a
  - name: resolve_committee
    version: "1"
    input_schema_sha256: 8c32e979c0a7a1a49ea093e19ac0e9536d40b841dad386fb6ff31fa8125a8855
    output_schema_sha256: 8cbc508a6f14a781949ac413226fe346f7e07a4ffe69519f0226f7c1283beb25
  - name: run_deep_account
    version: "1"
    input_schema_sha256: 846e72bf981e77feba6f8e56e401168982f37b789e91edf96fc23017f5ad3d7f
    output_schema_sha256: 3038c313bfffccbf676f689f4ad856d026f8a135c7d0ce102c7e623aa6ad1f23
  - name: run_verification
    version: "1"
    input_schema_sha256: a331a001f6b269a9daa97f2d861342d7dfae86a0e75a942ca8f1f4f9d302b0b2
    output_schema_sha256: d93aeddfdd146ca7bc8dba48b2fcac40415934659c495905255dae3ceb32d91b
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Bounded research specialist task

Open this skill only for a delegated research task.

1. Read the task artifact and every granted original before planning. Do not substitute the
   parent's summary for an available canonical file.
2. Inventory the explicit domain refs, known evidence, unresolved fields, source families already
   tried, policy constraints, and budget. Do not infer an entity from a free-text name.
3. Rank gaps by whether filling them can change fit, committee confidence, value narrative, or a
   decision gate. Name channels not searched; never imply exhaustive coverage.
4. Choose the lowest-trust-cost source waterfall step that can answer each admitted gap. A tool may
   launch governed work; do not perform arbitrary web research or report a launch as a completed
   result.
5. Route any durable finding through a governed tool so the result is a claim/proposal/execution
   ref. The report may explain those refs but cannot replace them.
6. Write `outputs/research-strategy.md` with: task, exact inputs, prioritized gaps, source plan,
   dossier questions, refs produced, unresolved risks, cost/gate status, and recommended next step.

Refuse with `blocked` when the target entity is ambiguous, a required canonical source was not
granted, the task asks for unsupported personal data, or the tool/budget gate rejects the work.
