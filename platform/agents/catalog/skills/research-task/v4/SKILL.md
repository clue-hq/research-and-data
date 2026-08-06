---
schema_version: "1"
kind: skill
name: research-task
version: v4
summary: Review bounded research plans and verify durable results without launching superseded entity orchestration.
roles:
  - research
readiness_requirements:
  - delegation.task_exact
  - delegation.canonical_sources_available
tools:
  - name: run_verification
    version: "1"
    input_schema_sha256: a331a001f6b269a9daa97f2d861342d7dfae86a0e75a942ca8f1f4f9d302b0b2
    output_schema_sha256: d93aeddfdd146ca7bc8dba48b2fcac40415934659c495905255dae3ceb32d91b
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Bounded research-specialist task

Open this skill only for the exact delegated research review or verification task. Account and
contact entity research is now owned by separately launched fleet units constructed through
`langchain.agents.create_agent()`. Do not imitate, launch, or replace those units.

Read the task artifact and granted originals. Inventory exact entities, fields, directional
questions, evidence gaps, source plans, committee/contact scope, privacy posture, budget, durable
result refs, and review refs. For a pre-launch review, analyze only. For a post-run review, inspect
the durable research view and name accepted, conflicting, rejected, null, and unresolved outcomes.

Use `run_verification@1` only when the exact project run has reached its governed verification
boundary. A provider receipt, fleet return, or partial claim set is not verified merely because it
exists. Unsupported is a correct outcome. Never claim completion for an account/contact job whose
accepted finalization receipt is absent.

Write `outputs/research-strategy.md` with the task class, exact inputs, evidence/result refs,
source and scope analysis, unresolved risks, cost/gate status, and recommended next action. Refuse
with `blocked` when identity is ambiguous, required originals are absent, personal-data authority
is missing, or a policy/budget gate rejects the work.
