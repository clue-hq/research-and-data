---
schema_version: "1"
kind: skill
name: account-research-briefing
version: v3
summary: "Before launching account deep research, write one project-specific delegation brief in directive_text, with account placeholders and references to the complete pinned documents."
roles:
  - head_of_abm
readiness_requirements: []
tools:
  - name: launch_arv2_account_research
    version: "1"
    input_schema_sha256: 57638dc151a30c67905105bfe4d0a86650ccb31dc9675e3880fe173e17d88c2e
    output_schema_sha256: 44180afee6410fe56bc94c928b5cbb543fa3bf175d4755b66b87f3abf690906a
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Brief the account researcher

Open this skill before `launch_arv2_account_research`. You, the Head of ABM, write
the research assignment. The account researcher receives your brief directly and
can consult the complete pinned documents separately. Write as a knowledgeable
colleague delegating an investigation: explain who the seller is, what matters
for this project, and what the researcher needs to find out.

## Read, understand, then brief

Use `project/status.md` and `project/decisions.md` for the project's assignment,
selected products, targeting pins and user instructions. Read the selected ICP
and associated personas, the seller's company overview, and each selected
product's research from the project/brand library. Follow the actual document
references in the indexes and targeting receipt.

A project may pin a brand ICP or its own variant. The same applies to personas.
Use the project's selection, not whichever brand document happens to be newest.
Keep products distinguishable. State a missing or unresolved persona briefly;
use the selected ICP's role map where available rather than silently borrowing
another ICP's personas. Missing commercial details remain unspecified.

Turn that material into the kind of brief shown below. Do not paste document
frontmatter, complete ICP rules, persona profiles, product documents or raw
catalogs. Preserve the useful meaning: the product's actual capabilities, the
reasons to investigate a workflow, the questions qualification raises, and the
responsibilities behind the buying roles. Pricing, proof and integrations only
belong in the brief when documented and useful. Include their important limits.

## One brief for the run

Write the shared brief once for this seller, project, product selection and
research scope. Put it in the existing launch input `directive_text`; do not
launch a second agent to write it. Use `{{account_name}}` and
`{{account_domain}}` wherever the target's identity is needed. The job substitutes
those two tokens using its actual account. No other placeholder is supported.

Launch the selected accounts together with that same brief. Do not write fifty
copies, list every account inside it, or insert one account's location, known
people or research conclusions into a brief shared by other accounts. Relevant
account-specific context comes from that job's identity and existing evidence.
For a single-account run, include established namesake distinctions and any
account-specific assignment the user supplied. Reuse the briefing on a later
run only after checking that the project choices and assignment still match.

Pass the exact ICP artifact key/digest and product-selection version through
their existing launch arguments. Preserve the requested scope and person limit;
`committee_cap` is a committee size setting, not a separate person-job cap. Do
not invent a tool argument or promise a hard limit this launch cannot enforce.

## Shape and length

The example below is the target length, level of detail and writing style.
Match its roughly 600-word scale: a readable assignment, not a one-paragraph
summary or an expanded source dump. This is writing guidance, not a word-count
gate. Use short sections, a few concrete investigation bullets, and a small
product table only when it helps. Do not add a generic essay on ABM, framework
tools, filesystem operation, claim schemas or display recipes.

Cover these subjects in this order, combining adjacent sections when natural:

1. **Your assignment:** account, seller, project objective and research scope.
2. **Who you are researching for:** selected products and the work they improve.
3. **Commercial context and proof:** relevant evidence and its limits.
4. **The project's targeting lens:** selected ICP, meaningful questions, buying
   signals and evidence that could weaken fit. Qualification gaps do not stop
   research.
5. **Systems worth investigating:** documented priorities and product-specific
   compatibility limits.
6. **Buying responsibilities:** buyer, champion, users, evaluators and potential
   blockers as search directions, adapted to the actual organization.
7. **Target and existing knowledge:** identity, whether this is fresh research
   or a continuation, important known uncertainties and useful prior references.
8. **Scope and expected research:** hiring/media where relevant, person scope,
   work email, source preservation and explicit uncertainty.
9. **Complete references:** a short reference list for the full selected ICP,
   personas, seller overview and selected product documents.

The final reference list names the actual documents and their known pinned
versions or identifiers. The quality research agent opens `/research/context.json`
to obtain their job-scoped `document_paths`, then reads the complete originals
as needed. Do not invent IDs, copy parent-only workspace paths as if the child
could open them, or paste originals into the brief. When a document is unavailable,
say so; a reference is not proof that it was loaded successfully. Older research
bundles may supply ICP/personas inline and lack these document views. Do not
claim the full reference handoff is available there or silently switch runtimes.

The brief guides investigation, not the answer: a published fax number is not a
workload estimate; a plausible job title is not a proven champion; an absent
search hit is not proof a tool is unused. Describe uncertainties without adding
verification, location or presentation blockers. Current provider policy is
AI Ark for basic typed company/person enrichment and work email, either AI Ark
or web search for people discovery, and Exa/source research for substantive
findings. No paid phone enrichment. The account researcher writes its own Exa
research query from the assignment and evidence; do not send this briefing as an
unconditional automatic appendix to every provider call.

## Example: Clue to Acme

**Example context:** Clue is a platform for agentic ABM for midsize B2B companies.
It helps lean go-to-market teams research accounts and buying committees and
produce personalized campaigns across more accounts. That positioning explains
why this brief investigates account-based selling, campaign workload, marketing
team capacity, existing ABM tools, and marketing/revenue buying responsibilities.

Acme (`acme.example`) is a fictional target used to illustrate the briefing style.
The seller and ICP details below are example context, not facts to reuse for
another project. In a shared run brief, replace the account name and domain with
`{{account_name}}` and `{{account_domain}}`. Reference lists use document names
because no actual run's IDs are asserted here.

### Your assignment

Research Acme at acme.example for seller Clue. Understand its business,
go-to-market organization, account-based selling activities and campaign-production
needs. Investigate whether Clue's capabilities are relevant, including evidence
that weakens that proposition.

Research the account comprehensively, then select the relevant buying-committee
people for person-depth research: aim for four or five when the research supports them,
never more than the job's committee limit, and do not pad. Choose them from the research
and persona context; no individual is preselected.

### Who you are researching for

The selected seller/product is Clue. Its retained product brief describes
“Agentic ABM for modern GTM teams”: account and committee research, campaign briefs,
personalized microsites, paid media and direct mail.

The central proposition is helping a team produce account-specific campaigns
across more accounts without proportionately increasing the people needed for
research, strategy, copy, design and coordination. Relevant documented capabilities
include custom research, buying-committee mapping, brand intelligence, coordinated
activation and engagement intelligence.

### Seller context limits

This product brief reflects material captured on 31 August 2026. It contains no
published pricing, customer case studies or named CRM integration list. Treat its
capability descriptions as retained seller statements, not newly verified product
availability. Closed-won and closed-lost patterns are not supplied.

### The project's targeting lens

Apply the pinned clue-abm-buyers, version 1 ICP and its associated persona document.
Its preferred profile is a US-headquartered B2B software company with a recent
priced Series A or later round, an enterprise or named-account selling motion,
and a relatively small marketing team. The document describes roughly 30–300
employees as the preferred range.

Investigate:

- Open GTM roles whose responsibilities include account research, list building,
  ABM or integrated campaigns.
- Any stated target-account list size relative to the team serving it.
- Leaders' own statements about outbound cost, campaign workload or production
  constraints.
- Funding explicitly allocated to GTM expansion.
- Recent marketing, growth or revenue leadership appointments.
- Named customers, selling motion, events and field-marketing activity.
- CRM, outbound and ABM systems actually mentioned in sources.

The ICP flags existing enterprise ABM platforms, direct competitors, consumer-only
businesses and predominantly self-service selling motions as potential reasons
for poor fit. Record these findings without stopping the investigation.

### Tools and systems worth investigating

The ICP specifically names 6sense, Demandbase, Terminus, RollWorks, Mutiny,
Folloze, Influ2 and Madison Logic. Also capture relevant CRM and sales-engagement
tools found during research. “Not found in the sources searched” must remain
distinct from “the company does not use it.”

### Buying responsibilities to investigate

- Economic buyer: CEO, CRO or CMO.
- Champion: marketing/growth leadership, demand generation or an ABM owner.
- Users: demand-generation, marketing and sales-development staff.
- Technical evaluator: RevOps, marketing operations or technical leadership.
- Potential blockers: finance, procurement or security.

Adapt the titles to Acme's actual organization. These are search directions,
not established committee assignments.

### Target and existing knowledge

Target: Acme, acme.example. This is a fresh-research assignment: historical
Acme findings and previously selected contacts are not preloaded. Headquarters,
current leadership, funding, tools and operational needs are research questions.

### Scope and expected research

Full account research, hiring evidence and relevant media; person-depth research
for each selected person; work-email enrichment. Preserve source URLs, dates,
original provider reports and meaningful quotations. Explain uncertainty and
acquisition gaps. The account's need for Clue must emerge from the evidence.

### Complete references

Consult the pinned Clue seller/product brief, clue-abm-buyers v1 ICP and associated
persona document through the document references in `/research/context.json`.
