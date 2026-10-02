---
schema_version: "1"
kind: skill
name: icp-authoring
version: v3
summary: "Draft an ideal customer profile as a document under project/, apply it automatically with the project product set."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Author an ideal customer profile

Write the ICP document, then use `configure_project_targeting` to apply it automatically.

Draft only from `brand/knowledge/` (company/overview.md, product/catalog.md, the product files,
proof/customer-reviews.md, the existing audience/icp-*.md) and from what the human told this project
(project/decisions.md). Every hard gate must trace to one of those; if it cannot, leave it out.
Never invent a product id: take `product_ids` from product/catalog.md's front matter.

Save it under `project/` wherever makes sense — `project/audience/icp-<key>.md` is the usual place.
Put `icp_key` in the front matter, a lowercase kebab-case key, because that key is how the targeting tool
finds the document you mean. Write the whole file in the shape the existing ICP files use:
`kind: icp-definition`, `icp_key`, `product_ids`, `hard_gates` (each `{key, rule, test}`),
`exclusions`, `persona_map` (only the roles that exist at this account type), `qualifier_fields`;
then the body in priority order: who fits and why, the list math, disqualifiers and red flags, the
client's own phrasing quoted from the files, the qualification-floor verdict. A project's variant of
a brand profile needs its own key and `derived_from: <brand key>` in the front matter.

Then call `configure_project_targeting` with that key. The tool automatically confirms and pins
the exact document with the project's product set. Explain what was applied and continue the
user's task in the same turn; no approval card or additional confirmation question is needed.
If the tool cannot find the document, check the exact `icp_key`, fix it, and call again.

Do not write a profile before the founding questions are answered, and never one the human did not
ask for.
