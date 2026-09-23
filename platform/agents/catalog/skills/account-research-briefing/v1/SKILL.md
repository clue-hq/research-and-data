---
schema_version: "1"
kind: skill
name: account-research-briefing
version: v1
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

The two examples below are the target length, level of detail and writing style.
Match their roughly 600-word scale: a readable assignment, not a one-paragraph
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

## Example: Clue to Zafran Security

These two examples preserve the approved preview's substance and scale. They
illustrate historical project context, not facts to reuse for another seller or
current run. The account names below become the two tokens in a shared brief.
Reference lists use document names because no actual run's IDs are asserted here.

### Your assignment

Research Zafran Security at zafran.io for Clue. Understand its business,
go-to-market organization, account-based selling activities and campaign-production
needs. Investigate whether Clue's capabilities are relevant, including evidence
that weakens that proposition.

Research the account comprehensively, then select one relevant buying-committee
person for person-depth research. Choose that person from the research and persona
context; no individual is preselected.

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

Adapt the titles to Zafran's actual organization. These are search directions,
not established committee assignments.

### Target and existing knowledge

Target: Zafran Security, zafran.io. This is a fresh-research assignment: historical
Zafran findings and previously selected contacts are not preloaded. Headquarters,
current leadership, funding, tools and operational needs are research questions.

### Scope and expected research

Full account research, hiring evidence and relevant media; person-depth research
for one selected person; work-email enrichment. Preserve source URLs, dates,
original provider reports and meaningful quotations. Explain uncertainty and
acquisition gaps. The account's need for Clue must emerge from the evidence.

### Complete references

Consult the pinned Clue seller/product brief, clue-abm-buyers v1 ICP and associated
persona document through the document references in `/research/context.json`.

## Example: Insight Health to Premier Gastroenterology

### Your assignment

Research Premier Gastroenterology at pgalr.com, the Little Rock account, for
Insight Health's selected GI workflow products. Understand how the practice
handles incoming referrals and documents, pre-visit history, and Direct
Access/Open Access Colonoscopy intake. Investigate whether the selected products
address an evidenced need. Identify the people responsible for these workflows
and their purchasing decisions.

### Who you are researching for

The seller is Insight Health. This project selects three products:

| Product | Relevant capability in the retained product research |
| --- | --- |
| MagicDocs | Processes incoming faxes and clinical documents, matches them to patients, and creates structured work in the EHR, with exception review. |
| Intake AI Agent / Lumi | Collects pre-visit medical histories through voice or text and produces structured notes for provider review. |
| Direct Access Colonoscopy AI intake | Supports GI history capture, clinic-defined screening criteria, reminders and progression toward scheduling through the DAC workflow. |

These descriptions come from seller-product research dated 11 September 2026.

### Commercial context and proof

The retained sources describe MagicDocs as quote-based, Intake AI Agent as priced
per completed intake, and DAC intake as priced per completed assessment with an
additional successful-scheduling fee. Exact prices are not supplied.

Intake's retained product research includes named testimonials from pain-management
and neurosurgery users. These are not GI-specific proof. The DAC product research
contains vendor benefit claims but no established named customer case study for
that exact product. Do not turn vendor claims into promised outcomes for Premier.

### The project's targeting lens

Apply gi-specialty-ambulatory-groups, content version 4: a project-specific GI
variant of the broader specialty-practice ICP. The selected buying context is
US gastroenterology and ambulatory GI operations. Investigate:

- Gastroenterology, endoscopy and Direct Access/Open Access Colonoscopy services.
- Referral instructions, fax/document intake, screening packets and pre-visit
  questionnaires.
- Evidence of missing records, chart preparation, prior-authorization workload
  or scheduling friction.
- Treating locations and whether document/referral work is centralized.
- The production EHR and relevant workflow vendors.
- Changes in facilities, staffing, leadership or service offerings that could
  affect these workflows.

A published referral fax number establishes an intake channel; it does not
establish high volume or a staffing bottleneck. Seek evidence for those separately.
Record qualification gaps without stopping the research.

### Systems worth investigating

The pinned ICP prioritizes athenahealth, NextGen, AdvancedMD, DrChrono, Office
Practicum and Epic ambulatory. Keep product-specific compatibility distinct:
the retained DAC document describes an EHR referral-queue connection but does
not name a particular EHR vendor. Do not assume every integration mentioned
elsewhere by Insight Health applies to all three products.

### Buying responsibilities to investigate

Use the roles explicitly included in this project's ICP:

- Economic buyer: GI practice owner, president/CEO, clinical executive or
  operations leader.
- Champion: practice administrator, referral-management leader, DAC/endoscopy
  coordinator or GI physician lead.
- Users: referral, authorization, front-desk and endoscopy-scheduling staff.
- Technical evaluator: EHR/IT, health-information or informatics leadership.
- Potential blockers: privacy/compliance, medical-records ownership or physicians
  concerned about workflow accuracy.

### Persona context gap

The retained run recorded a persona-lineage mismatch. A GI persona document
exists, but its successful selection for that run is not established. Continue
using the role map in the pinned ICP; do not silently substitute another
specialty's persona document.

### Target and existing knowledge

Target: Premier Gastroenterology, pgalr.com, Little Rock, Arkansas. This assignment
uses a fresh-research baseline rather than importing earlier research conclusions.
No person, EHR vendor, accreditation or operational bottleneck is pre-established.

### Scope and expected research

Full account research, buying-committee discovery and person research. A new
person-count limit is not being set by this brief. Preserve original reports,
pages, hiring evidence and relevant media. Explain how findings relate to the
three selected products, distinguishing observed workflows from your interpretation
of their commercial relevance.

### Complete references

Consult the pinned Insight Health company overview, the three selected product
documents and gi-specialty-ambulatory-groups content v4 through
`/research/context.json`. The persona selection remains unresolved as noted above.
