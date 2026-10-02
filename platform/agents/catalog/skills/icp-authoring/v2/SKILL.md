---
schema_version: "1"
kind: skill
name: icp-authoring
version: v2
summary: "Draft an ideal customer profile as a document under project/, ask the human once to pin it as the ICP, and open the confirmation gate on yes."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Author an ideal customer profile

You may write an ICP document. You may not confirm one — the human does that at the gate.

Draft only from `brand/knowledge/` (company/overview.md, product/catalog.md, the product files,
proof/customer-reviews.md, the existing audience/icp-*.md) and from what the human told this project
(project/decisions.md). Every hard gate must trace to one of those; if it cannot, leave it out.
Never invent a product id: take `product_ids` from product/catalog.md's front matter.

Save it under `project/` wherever makes sense — `project/audience/icp-<key>.md` is the usual place.
Put `icp_key` in the front matter, a lowercase kebab-case key, because that key is how the gate
finds the document you mean. Write the whole file in the shape the existing ICP files use:
`kind: icp-definition`, `icp_key`, `product_ids`, `hard_gates` (each `{key, rule, test}`),
`exclusions`, `persona_map` (only the roles that exist at this account type), `qualifier_fields`;
then the body in priority order: who fits and why, the list math, disqualifiers and red flags, the
client's own phrasing quoted from the files, the qualification-floor verdict. A project's variant of
a brand profile needs its own key and `derived_from: <brand key>` in the front matter.

Then ask the human once: pin this as the ICP? On yes, open the ICP confirmation gate on that key in
the same turn and end the turn awaiting them. The gate is the pin — there is nothing else to ask and
nothing else to write. If the gate says it cannot find a document for the key, check that the file
you wrote carries that exact `icp_key`, fix it, and open the gate again.

Do not write a profile before the founding questions are answered, and never one the human did not
ask for.
