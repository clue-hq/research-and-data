# Document families and ownership

This table maps every preserved reference document. The keys are Conduit fixtures for coverage auditing, not production keys for every brand. The JSON catalog contains requested headings and a corrected dependency graph for this reference. Production expands selected offerings and supported buying motions dynamically.

| Reference document | Proposed task/mode | What scales |
| --- | --- | --- |
| Company overview (`company-overview`) | [overview](prompts/01-company.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Commercial model & market context (`commercial-model`) | [commercial-model](prompts/04-commercial-and-integrations.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Product catalog & capability map (`products-capabilities`) | [catalog](prompts/02-catalog.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| AI Agents (`product-agents`) | [product](prompts/03-product.md) | Discover per relevant offering; never hardcode these Conduit product keys. |
| Inbox (`product-inbox`) | [product](prompts/03-product.md) | Discover per relevant offering; never hardcode these Conduit product keys. |
| Guest Portals (`product-portals`) | [product](prompts/03-product.md) | Discover per relevant offering; never hardcode these Conduit product keys. |
| Workflows (`product-workflows`) | [product](prompts/03-product.md) | Discover per relevant offering; never hardcode these Conduit product keys. |
| Operator & internal AI availability (`product-operator`) | [capability](prompts/03-product.md) | Discover per relevant offering; never hardcode these Conduit product keys. |
| Developer platform & custom workflows (`product-developers`) | [capability](prompts/03-product.md) | Discover per relevant offering; never hardcode these Conduit product keys. |
| Integrations & implementation readiness (`integrations`) | [integrations](prompts/04-commercial-and-integrations.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Pricing & packaging (`pricing`) | [pricing](prompts/04-commercial-and-integrations.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Customer evidence & usable proof (`customer-evidence`) | [proof](prompts/05-customer-proof.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Alternatives & differentiation (`alternatives`) | [alternatives](prompts/06-alternatives.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Positioning & brand promise (`brand-messaging`) | [positioning](prompts/07-brand-messaging.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Brand voice & language (`brand-voice`) | [voice](prompts/07-brand-messaging.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Audience-to-message map (`message-map`) | [message-map](prompts/07-brand-messaging.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Campaign writing examples & rules (`writing-examples`) | [writing-examples](prompts/07-brand-messaging.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| ICP strategy & segment priorities (`ideal-customers`) | [strategy](prompts/08-icp.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| ICP · hotel operators (`icp-hotels`) | [profile](prompts/08-icp.md) | Discover per supported buying motion; no fixed segment count. |
| ICP · vacation-rental operators (`icp-rentals`) | [profile](prompts/08-icp.md) | Discover per supported buying motion; no fixed segment count. |
| Buying committee & professional personas (`buyer-roles`) | [personas](prompts/09-buyers-and-jobs.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Qualification & account research playbook (`buying-triggers`) | [qualification](prompts/08-icp.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Buyer problems & desired results (`customer-jobs`) | [jobs](prompts/09-buyers-and-jobs.md) | One per relevant company scope, or summarize per-ICP outputs where appropriate. |
| Visual identity & logo pack (`visual-identity`) | [asset](prompts/12-asset-context.md) | Existing asset pipeline; no new knowledge agent_context. Reference document is preserved, not mandatory production output. |
| Library organization & research guide (`library-guide`) | [registry-guide](prompts/11-formatting.md) | Render from approved document registry; do not research or author company facts. |

## Friendly folders and file ownership

- Company owns identity, company system and commercial context.
- Product owns the discovered catalog, individual offering guides, integration routes and pricing. Pricing is authoritative in one place; other documents cite it.
- Proof owns attributable customer results, review evidence and comparisons. Product guides reference scoped proof rather than adopting unrelated metrics.
- Audience owns buyer jobs, proposed ICP strategy/profiles, professional personas and qualification. Host-rendered summaries avoid redundant research per ICP.
- Brand & messaging owns observed positioning/voice, proposed message maps and illustrative drafts. This is the principal new research family; its folder/kind and downstream indexing require a contract review.
- Assets contains ads, website images, logo variants and usage context. The preserved Design document may be displayed as a generated identity summary, not another factual-research agent.
- Library help describes organization from registry metadata; it is not a brand-research output.

## Dynamic cardinality and scope

A one-product startup may need one product guide and one provisional ICP. A large vendor needs a catalog selection and continuation plan, not one vague portfolio report or thousands of automatic deep calls. Preserve product and segment IDs across reruns; record additions/retirements as proposals. Cover every selected product with terminal research status before dependent synthesis. Product guides need only product-specific commercial evidence, so they do not wait on an unrelated portfolio-wide report.

The 25 reference documents equal 23 researched/model-backed briefs plus two manual guide/identity documents; they are not 25 separate production agents. A worker runs the same task prompt with a different scoped request. Broad brand context and a project-specific ICP remain separate scopes.

## Generic filesystem proposal

```text
company/overview.md
company/commercial-model.md
product/catalog.md
product/<stable-product-slug>.md
product/integrations.md
product/pricing.md
proof/customer-reviews.md
proof/customer-evidence.md
proof/alternatives.md
audience/customer-jobs.md
audience/icp-strategy.md
audience/icp-<stable-key>.md
audience/persona-<stable-key>.md
audience/qualification.md
brand/positioning.md
brand/voice.md
brand/message-map.md
brand/writing-examples.md
```

The extra reviews file preserves existing platform behavior; it is not present as a separate final V2 reference document. Buyer-role overview can be rendered from per-ICP persona files. Do not rename existing current paths without a versioned migration/alias decision. Users see titles, not these filenames. Brand-folder placement is proposed, not installed.
