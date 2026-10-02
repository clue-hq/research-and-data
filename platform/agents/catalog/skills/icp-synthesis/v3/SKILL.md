---
schema_version: "1"
kind: skill
name: icp-synthesis
version: v3
summary: Produce two to three ideal customer profiles as ICP artifacts (front matter + body) from the onboarding research documents; every gate traces to a file.
roles:
  - onboarding_synthesis
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# ICP synthesis

Produce two to three ideal customer profiles for the client. Each profile is one markdown file
outputs/audience/icp-<key>.md in the ICP artifact format (front matter + body, see the format
block below). Decide the number of profiles from the product lineup and the customer segments in
inputs/brand/knowledge/company/overview.md: one profile per distinct buyer motion, not one per
product. Each profile names the product_ids it sells, from
inputs/brand/knowledge/product/catalog.md. Read the product research file for each product a
profile names (inputs/brand/knowledge/product/<slug>.md) before writing that profile's gates.
Read all of those files in one step: issue every read_file call together in a single turn, not
one file per turn, so the reading costs one round instead of many.

ICPs already on file. When the user message lists ICPs already on file, they are in your context
under their paths (inputs/brand/knowledge/audience/icp-<key>.md). For each buyer motion you
would propose, first check whether an ICP on file already describes that motion. If it does,
reuse its icp_key exactly and rewrite the profile from the current research; a re-run refines a
profile, it does not rename it. Propose a new icp_key only for a buyer motion that no ICP on file
describes. Do not carry a key forward just to fill a slot: if the research no longer supports an
ICP on file, leave it out and say so in your finalize_turn message.

For each profile:
- hard_gates: pass/fail rules with a test a researcher can run (industry, size band, geography,
  stack or system in use, hiring, regulatory status). Write the rule and its test.
- exclusions: who is explicitly out, and why.
- persona_map: which of economic_buyer, champion, user, technical_evaluator, blocker exist at
  this account type, each with the titles that hold it.
- qualifier_fields: the client-specific facts research must find per account, each as
  {field_key, description}; the description is the research instruction. Reuse an existing key
  when one fits; otherwise name a new one under account.*.
- body: the human-readable definition in priority order; TAM/list-math estimate and whether to
  widen, tier or shrink; disqualifiers and red flags; the client's own phrasing of who they sell
  to, quoted from inputs/brand/knowledge/company/overview.md or reviews; the qualification-floor
  verdict.

Every gate must trace to something in the files: a customer segment, a named customer, a
regulatory posture, an integration, a review theme. If you cannot trace it, drop it. Set
status: proposed. Never write a project id, a version number or a product id you were not given.
Do not call any evidence tool in this task; the profiles come from the files.

## The ICP artifact format (write exactly this front matter)

```yaml
---
kind: icp-definition
icp_key: <lowercase-kebab, unique per brand, e.g. multi-specialty-groups>
version: 1
status: proposed
product_ids: [<product ids from inputs/brand/knowledge/product/catalog.md front matter>]
hard_gates:
  - {key: <stable_key>, rule: <one sentence>, test: <how a researcher checks it>}
exclusions: [<one sentence each>]
persona_map:
  economic_buyer: {titles: [<title strings>]}
  champion: {titles: [...]}
  user: {titles: [...]}
  technical_evaluator: {titles: [...]}
  blocker: {titles: [...]}
qualifier_fields:
  - {field_key: <account.some_key>, description: <the research instruction>, display: rail}
---
```

Omit a persona_map role that does not exist at this account type. The body follows the front matter.
