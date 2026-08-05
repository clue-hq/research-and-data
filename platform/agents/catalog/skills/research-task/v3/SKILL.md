---
schema_version: "1"
kind: skill
name: research-task
version: v3
summary: Review a bounded account-deep plan or execute admitted account or selected-contact research without crossing confirmation, launch, or completion authority.
roles:
  - research
readiness_requirements:
  - delegation.task_exact
  - delegation.canonical_sources_available
tools:
  - name: profile_contact
    version: "2"
    input_schema_sha256: 32be4a74c7d2ae723ea54461b5f3382d62c300bf684a288a4e2883c0efcc2aec
    output_schema_sha256: 037c039841fb2c923487ffc198e1b9ec881a4e548ffb24678f18cd86649340a7
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

# Bounded research-specialist task

Open this skill only for the exact delegated research task. First classify it as either a
**pre-launch plan review** or **admitted execution** from the task artifact and durable refs. Do
not infer execution authority from the availability of spending tools.

1. Read the task artifact and every granted original before planning. For account-deep work, the
   harness grants the exact directive file and current steering card with their typed refs when
   the parent had them; use those originals rather than the parent's summary.
2. Inventory exact entities, standard registered fields, directional questions/hypotheses,
   evidence gaps, source families already tried, committee selectors, privacy/reveal posture,
   policy constraints, and budget. Do not infer an entity from a free-text name.
3. For a pre-launch plan review, analyze only. Compare each directional question with its target
   field/facet and stop rule; identify unsupported source hints, missing target lock, committee
   coverage gaps, reveal risk, and whether more account discovery is more useful than deep work.
   Invoke no spending tool, and never confirm or launch.
4. For admitted execution, rank gaps by whether filling them can change fit, committee confidence,
   value narrative, or a decision gate. Choose the lowest-trust-cost source-waterfall step that
   can answer each admitted gap. For one selected contact, call `profile_contact@2` only with the
   exact project-run, account, and contact ids from the granted committee state; its durable
   selection, preparation, wait, budget, and cancellation result is authoritative. A tool may
   launch governed work; do not perform arbitrary web research or report a launch as completed.
5. Research means typed claims with provenance. Route a durable finding through a governed tool;
   the report may explain refs but cannot replace them. Unsupported is a correct outcome. Name
   channels not searched and never imply exhaustive coverage.
6. Write `outputs/research-strategy.md` with: task class, exact inputs, standard fields,
   directional hypotheses, prioritized gaps, source plan, committee/contact/reveal posture,
   dossier questions, refs produced, unresolved risks, cost/gate status, and recommended next
   step.

Refuse with `blocked` when the target entity is ambiguous, a required canonical source was not
granted, the task asks for unsupported personal data, or a tool/budget gate rejects the work. A
receipt, enqueue acknowledgement, pending provider operation, or partial claim set is never
completed research.
