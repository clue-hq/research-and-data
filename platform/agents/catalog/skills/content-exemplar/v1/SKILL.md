---
schema_version: "1"
kind: skill
name: content-exemplar
version: v1
summary: Draft one traceable ABM exemplar from approved evidence, narrative, brand, and slot inputs.
roles:
  - content_drafter
readiness_requirements:
  - content.approved_evidence_refs
  - content.schema_or_slot_contract
tools:
  - name: compose_handoff
    version: "1"
    input_schema_sha256: 96917935663e83ac72f50764d2b65d3c837c5e3ba05206aa6b996d692fbf9a0d
    output_schema_sha256: 986b87c66d09bbbbebeff5a386b103bd2a4202d0f02d5fb8aae64b8e15ab05c5
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# One-account content exemplar

Open this skill only for one delegated exemplar.

1. Read the task and granted canonical evidence, narrative, brand, persona, schema, and slot files.
2. Build an input ledger: every factual statement maps to an approved ref; every stylistic choice
   maps to brand or explicit task intent. Mark unsupported ideas as excluded.
3. Draft exactly one exemplar for the requested account/contact/channel. Do not create scaled
   variants, run a campaign, or manufacture a new claim.
4. Preserve the content-schema and design-slot contract. If either is missing, produce a blocked
   draft skeleton that names the missing contract rather than guessing it.
5. Write `outputs/content-exemplar.md` with the exemplar, evidence annotations, assumptions,
   exclusions, schema/slot mapping, and unresolved requirements.

`compose_handoff` may read or assemble an admitted handoff; it does not grant approval, truth, or
scaled-production authority. Finalize only after the exemplar file is durable.
