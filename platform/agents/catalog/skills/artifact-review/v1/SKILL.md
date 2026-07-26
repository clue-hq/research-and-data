---
schema_version: "1"
kind: skill
name: artifact-review
version: v1
summary: Review one immutable exemplar for evidence, policy, persona, brand, schema, and slot fit.
roles:
  - reviewer
readiness_requirements:
  - review.canonical_artifact_granted
  - review.criteria_granted
tools:
  - name: compose_handoff
    version: "1"
    input_schema_sha256: 96917935663e83ac72f50764d2b65d3c837c5e3ba05206aa6b996d692fbf9a0d
    output_schema_sha256: 986b87c66d09bbbbebeff5a386b103bd2a4202d0f02d5fb8aae64b8e15ab05c5
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Immutable exemplar review

Open this skill only for a delegated exemplar review.

1. Read the exact canonical artifact and criteria. If the original is absent, stop; a paraphrase
   is not review evidence.
2. Check factual support and target binding first, then appropriateness/policy, persona and offer
   fit, brand voice, content schema, design slots, and handoff completeness.
3. Classify each finding as `blocking`, `safe_suggestion`, `intentional_deferral`,
   `missing_evidence`, or `human_gate`. Cite the exact file/ref and location.
4. Never edit the canonical artifact. Never promote claims or convert a suggestion into approval.
5. Write `outputs/review-verdict.md` with a disposition (`pass`, `revise`, or `blocked`), stable
   reason codes, findings, cited refs, and the smallest next action.

A `pass` is a critique result, not human approval or publication authority. Finalize only after the
verdict artifact is durable.
