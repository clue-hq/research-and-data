---
schema_version: "1"
kind: skill
name: stage0-interview
version: v2
summary: Gather and route Stage 0 evidence from live readiness gaps without bypassing human gates.
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

# Stage 0 interview

Ask from the current readiness gaps, not from a fixed questionnaire. Preserve the user's exact
turn before classification, and use existing evidence before requesting it again.

Route information by species:

- verifiable facts go through governed claim-producing paths with evidence;
- advisory preferences and behavioral learnings go through scoped memory when that seam is
  available;
- project-specific intent remains project state;
- unsupported new field or source shapes remain explicit proposals only after their replay-safe
  agent tools are admitted;
- other volunteered statements remain durable interview evidence.

Never infer confirmation. Only a human confirms the project product and ICP or records an
override. Evaluate the three readiness gates separately. You may explain what remains missing and
prepare the confirmed run, but you cannot cross a human gate yourself.

Empty, unresolved, or awaiting-input is valid. Fabricated certainty is not.
