---
schema_version: "1"
kind: skill
name: stage0-interview
version: v3
summary: Run gap-led Stage 0 from URL or current truth, route every information species, and stop at human and deterministic gates.
roles:
  - head_of_abm
readiness_requirements:
  - stage0.project_product_confirmed
  - stage0.client_knowledge_sufficient
  - stage0.icp_confirmed
tools:
  - name: evaluate_stage0_readiness
    version: "1"
    input_schema_sha256: 6f05bf3d679213612f091e377029ec36100cae34abf084433f92d0d195d8245c
    output_schema_sha256: a4b0ee832c7a8fda7f62e811ab2651de2255b2d3b5020e29ce3b73b5d2f1e56b
  - name: propose_field
    version: "1"
    input_schema_sha256: 04f91da8afd3ab16b736d33d54c96b0a90dd34e4ecebacfb0db3c34a451a3aac
    output_schema_sha256: 4ca8488a8703406e64e4a8ba49bc17c5da2aa78f7f5cce104343eb77d68e3a84
  - name: propose_source
    version: "1"
    input_schema_sha256: a4590108f093a8a424a8b1c48b2cc0670527c1b7a3f608e70babdd32ae9f1f5b
    output_schema_sha256: 708d9b5075c72103232daa51c12cbb83a5fe5bdf638bfa79659193f2324a851e
  - name: record_interview_answer
    version: "1"
    input_schema_sha256: 27aecb580de94d3ffd3f1ddc8091ed8c579057dcd3a01e81cf7a6a287d46a955
    output_schema_sha256: 5f0e0fe7baad009e16af713744ef7abbc390615d627a69f5f25c43eb8734e7a8
  - name: start_confirmed_project_run
    version: "1"
    input_schema_sha256: 06ff2d5f230e15452cabd6eb6e2da877f32db3e0bbf577f0bdc2eebee3f7ae46
    output_schema_sha256: 4b621e2cbd05d503e2433b7698d87e9d7d69956d8a94084225ca6d5b13e122f9
  - name: start_recon
    version: "1"
    input_schema_sha256: 2772b762ce341e63bf7bcddbd9bb6dc66e6d87261306c13b7265229dc09e4391
    output_schema_sha256: a999f4e0508d93733369d35bb2d7f9c621ebf2f0fe8405fc7c605206b3d2eba4
  - name: submit_ingestion
    version: "1"
    input_schema_sha256: affae45f798ec731c0a2495f50f037d4bdd22debd6eb32c2b903d19422330da1
    output_schema_sha256: 8e2acc7a8819cb1eaff07dc0fa6f8a90b824572e5fb39cbf34a5380f3f1319bf
  - name: submit_onboarding_input
    version: "1"
    input_schema_sha256: 024e5880512fcfd9f0f38cf19e3edeb4b6485fe4604265dd89fdc6e3cc680aa6
    output_schema_sha256: db82dc8abe7cbb3d2e7537ad18328eb29e78c9c1e1671c2bd5ba3b370d818ecf
  - name: synthesize_icps
    version: "1"
    input_schema_sha256: 6872dd97eacfd19f02726a49b9d3fdb6f23f81ffde23ebed8971200ed31f50b1
    output_schema_sha256: a745ce146398d43c80bc8fdd220d86ec5c1fe70972f228f312f18d1b441997f3
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Stage 0 vertical

Open this skill when the project is in Stage 0 or the user is establishing product and ICP truth.
Do not preload or apply it to unrelated stages.

## 1. Establish current truth

Read the supplied stage, product, readiness, project, and focus context before asking anything.
Separate known-current, known-stale, contradicted, missing, and merely assumed values.

- URL-only: capture the URL as onboarding input, then start one governed recon. Fast recon gives
  the conversational starting point; background recon may continue without blocking useful
  questions.
- Known product: show the current product candidate and ask the human to confirm or correct it.
- Stale product: name the stale evidence and ask for the smallest refresh needed.
- Contradiction: preserve the new exact quote and route it as a correction; do not silently rewrite
  the prior claim or memory.

## 2. Ask from gaps, never from a questionnaire

Use deterministic readiness results and current evidence to choose the next material question.
Ask one compact question when possible. A question is material only if its answer can change:

- which product the project represents;
- a motion-specific ICP boundary or exclusion;
- a readiness metric or evidence floor;
- a missing source/field proposal;
- a project-specific constraint needed to start the confirmed run.

Do not ask for facts already present and current. Do not enumerate every possible ICP dimension.
Your judgment decides what is useful to ask; it does not decide readiness.

## 3. Preserve and route information by species

Capture the exact user turn as an artifact before routing statements.

- **Claim:** a verifiable fact, with exact quote offsets, entity, registered field, evidence, and
  correction lineage when applicable.
- **Memory:** an advisory preference or behavioral learning through the scoped-memory seam. Memory
  never becomes fact.
- **Project intent:** a choice or constraint local to this project.
- **Field/source proposal:** a novel typed field or source goes through `propose_field` or
  `propose_source`; proposal creation grants no promotion or trust authority.
- **Artifact/upload:** submit an already captured workspace artifact through `submit_ingestion`
  with explicit material context. Raw bytes arrive through the human/API upload boundary, not
  through model-controlled filesystem invention.
- **Unmapped evidence:** preserve it as durable interview evidence and surface the mapping gap.

Never paraphrase a user statement as its canonical evidence. Never use a proposal id as if it were
an approved field/source. Sensitive/contact data remains subject to its existing gates.

## 4. Synthesize and stop at human gates

After enough grounded product context exists, synthesize ICP options. Present assumptions,
exclusions, missing evidence, and the proposed motion. The human alone:

- confirms the project product;
- confirms or edits the ICP;
- records a readiness override.

These tools are intentionally absent. Ask for the action rather than simulating it.

Evaluate product, client-knowledge, and ICP/discovery readiness separately. Pass exact claim,
memory, artifact, gap, proposal, and ingestion references into readiness evaluation. Your
`agent_sufficiency_status` is advisory and cannot turn a failing deterministic result into ready.

Call `start_confirmed_project_run` only when durable product and ICP confirmations exist and the
discovery readiness decision is ready or has a durable human override. The tool and Recipe #1
router revalidate every lineage and gate. If they refuse, report the refusal and remain
`awaiting_input` or `blocked`; never claim the project started.
