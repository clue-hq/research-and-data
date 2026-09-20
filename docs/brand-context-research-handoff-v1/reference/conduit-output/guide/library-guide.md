This library organizes one company's public evidence into documents that support specific sales and campaign decisions. The folder name tells a reader where to look; each document also carries a stable internal identifier, source references and dependencies for an agent. The same evidence can support several decisions without creating several conflicting versions of the fact.

## What belongs in each folder

| Folder | Documents and ownership | Use it to answer |
| --- | --- | --- |
| Company | Company overview; commercial model and market context | What business is this, how does it earn revenue, and which market does it serve? |
| Product | Catalog, individual product guides, Operator availability, developer capabilities, integrations and pricing | Which specific capability addresses the problem, and what are its limits and prerequisites? |
| Brand & messaging | Positioning, voice, message map and proposed writing examples | What should we say, why does it matter, and how should it sound? |
| Audience | ICP strategy, hotel and rental profiles, buying committee, qualification and buyer problems | Which account is worth pursuing, who matters, what evidence is missing, and what question comes next? |
| Proof | Customer evidence and alternatives | What supports the argument, and how narrowly may we use a result or comparison? |
| Design | Identity pack and usage guide | Which original logo or asset fits this surface, and what is its source? |

Assets has its own unified library: website images, product visuals, customer logos and LinkedIn ads. Ads are a source filter inside Assets, not a separate knowledge folder. A product page is a knowledge source; a screenshot from that page is an asset; the asset links back to the relevant product guide.

## Why there are multiple product documents

The catalog explains the product system. The AI Agents, Inbox, Guest Portals and Workflows guides each explain a different buying decision: purpose, users and buyers, capabilities, limitations, workflows, integration dependencies, pricing/package fit, differentiation, evidence and discovery questions. Operator and developer capabilities have their own guides because an internal assistant, an API and a marketed product are not interchangeable.

Pricing is owned by one rate-card document. Product guides can cite its package context, but cannot invent a standalone product price. Proof owns named customer outcomes. Audience documents use those cases to propose a fit hypothesis; they cannot turn a case's unit count or savings into a universal qualification rule. Brand voice owns inferred writing guidance, not new product facts.

## What triggers each step

| Trigger | Research action | Output and dependency |
| --- | --- | --- |
| A company website is supplied | Resolve company/domain; inspect homepage, about, product navigation and original brand assets | Initial company identity and visible asset candidates; rich research continues in the background |
| A distinct product is found | Read its official page, relevant documentation, integration/setup pages and applicable case studies | A dedicated product guide; catalog updated without treating every SEO use-case page as a product |
| Company and product evidence is available | Compare official positioning and language with named customer situations | Positioning, voice and message map; all remain proposed guidance |
| Product, integration, price and customer evidence is complete enough | Build account fit and buyer-role hypotheses; identify commercial unknowns | ICP strategy, segment profiles and qualification decisions |
| An original image or ad is acquired | Retain original bytes and source identity; inspect content and composition | Human description and structured Agent context in Assets |
| A source changes or a user corrects a document | Revisit the owning fact and its dependants | A new revision; earlier drafts and human decisions must remain recoverable |

In this rework, company/product/proof writing runs in bounded parallel jobs. Messaging waits for its product and proof dependencies; audience writing follows, and the qualification playbook waits for the ICP strategy. Exact source passages and source links are checked before a draft enters the viewer. These structural checks do not prove that every inference is correct; semantic review remains a separate step.

## What an agent receives

Human documents use headings, prose and tables. Their structured record adds the document's purpose, decisions supported, source IDs, dependencies, unresolved questions and proposed qualification criteria. Selecting an asset exposes a concise description first. **Agent context** adds observed visual content, interpreted use, composition/crop guidance, related product documents, audience hypotheses, restrictions, source identity and original file hash. A badge means context exists, not that the image or claim has been approved for a campaign.

“Buyer problems & desired results” is the plain-language name for jobs and outcomes: what work the buyer needs to accomplish, what fails in the present approach, and what improvement they would measure. It is the bridge from product capability to a relevant sales argument.

## How this maps to Clue today

The platform audit was read-only. Existing knowledge records already carry path, title, kind, version, status, product or ICP identity, Markdown, front matter and source references. Current knowledge folders are Company, Product, Audience and Proof. Design is owned by the brand kit. The additional Brand & messaging folder is an experiment proposal and would require an explicit future contract change.

The current brand kit has logo variants with asset identity, color mode and dimensions; logos and images also have title, description and usage notes. The frontend mapper currently chooses description **or** usage note for its description field, so useful guidance can disappear from the visible card. A future contract should preserve both, add a versioned structured context record, and keep human approval distinct from analysis completion. No such platform change was made here.

The existing onboarding driver begins ICP synthesis after its company/catalog phase while deeper product research continues. The proposed improvement is a useful preliminary profile early, followed by an evidence-informed revision after the relevant product reports arrive. This experiment demonstrates that ordering; it does not deploy it.

## Review and maintenance

Public sources can contradict one another or omit commercial details. Missing evidence produces a specific question, not an invented revenue band, buyer title, logo variant or guaranteed result. Approval should resolve consequential policies such as target geography, minimum deal size, serviceability and campaign claim wording. After approval, an integration should use the platform's existing claim, artifact, tenancy and versioning seams. The standalone files are review artifacts, not a parallel production source of truth.
