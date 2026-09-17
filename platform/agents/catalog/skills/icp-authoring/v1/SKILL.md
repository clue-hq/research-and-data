---
schema_version: "1"
kind: skill
name: icp-authoring
version: v1
summary: "Draft this project's ICP at project/audience/icp-<key>.md from the brand's knowledge, then open its confirmation gate."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Author an ideal customer profile

You may write an ICP document. You may not confirm one — the human does that through the gate.

Draft only from `brand/knowledge/` (company/overview.md, product/catalog.md, the product files, proof/customer-reviews.md, the existing audience/icp-*.md) and from what the human told this project (project/decisions.md). Every hard gate must trace to one of those; if it cannot, leave it out. Never invent a product id: take `product_ids` from product/catalog.md's front matter.

Write the whole file — front matter and body — in the shape the existing ICP files use: `kind: icp-definition`, `icp_key`, `product_ids`, `hard_gates` (each `{key, rule, test}`), `exclusions`, `persona_map` (only the roles that exist at this account type), `qualifier_fields`; then the body in priority order: who fits and why, the list math, disqualifiers and red flags, the client's own phrasing quoted from the files, the qualification-floor verdict. A project variant of a brand profile needs its own lowercase kebab-case key and `derived_from: <brand key>` in the front matter.

Save it with `write_file` at `project/audience/icp-<key>.md`. The platform stores it as a proposed version and tells you if the key is taken or a product id is unknown; fix exactly what it names and write again. In the same turn, open the ICP confirmation gate on that key and end the turn awaiting the human. Do not write a profile before the founding questions are answered, and never one the human did not ask for.
