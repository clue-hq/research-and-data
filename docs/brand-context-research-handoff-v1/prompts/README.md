# Prompt assembly index

These are proposed research instructions, not installed platform skills or proven historical API inputs. Load [00-research-system.md](00-research-system.md) plus exactly one applicable task file and the host-generated request context described in [the design](../02-pipeline-design.md). Prompt files describe behavior; the host supplies the separate JSON Schema.

| File | Intended executor | Mode/output |
| --- | --- | --- |
| [01-company.md](01-company.md) | Exa Agent | Company overview |
| [02-catalog.md](02-catalog.md) | Existing Exa deep-reasoning catalog passes | Catalog discovery and classification |
| [03-product.md](03-product.md) | Exa Agent per selected offering | Product/capability guide |
| [04-commercial-and-integrations.md](04-commercial-and-integrations.md) | Exa Agent per requested document | Commercial model, pricing, integrations |
| [05-customer-proof.md](05-customer-proof.md) | Exa Agent | Reviews and attributed customer evidence |
| [06-alternatives.md](06-alternatives.md) | Exa Agent | Alternatives and differentiation |
| [07-brand-messaging.md](07-brand-messaging.md) | Exa Agent with completed inputs | Positioning, voice, message map, draft examples |
| [08-icp.md](08-icp.md) | Exa Agent with completed research | Strategy, per-motion ICP, qualification |
| [09-buyers-and-jobs.md](09-buyers-and-jobs.md) | Exa Agent plus existing Exa role-evidence calls | Jobs first, personas after ICP |
| [10-evidence-review.md](10-evidence-review.md) | Separate evidence-review task | Findings only; no approval |
| [11-formatting.md](11-formatting.md) | Python first; optional cheap repair model | Meaning-preserving Markdown |
| [12-asset-context.md](12-asset-context.md) | Existing visual asset classifier | Asset descriptions and usage context |

The catalog task retains `product_catalog_output_schema()` and the existing merge/reconciliation path. Persona evidence retains `persona_evidence_output_schema()`. Do not send a deep nested Agent schema to `/search` deep-reasoning. The proposed general research schema applies to Agent tasks 01, 03–09. Review/format/asset tasks have their own contracts described in their files; they do not masquerade as research-document output.

New documents and skills are versioned proposals. The production profile/registry must be changed intentionally by the implementer; placing these files here does not make them callable in Clue.
