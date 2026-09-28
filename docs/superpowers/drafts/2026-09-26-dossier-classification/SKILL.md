---
name: dossier-field-classification
summary: Classify account and person findings faithfully without losing evidence or forcing field matches.
---

# Dossier field classification — draft shared charter supplement

Status: exact proposed researcher guidance for an isolated classification trial. Not installed in
any launch manifest. The dossier schema/importer must support the proposed classification before
these instructions are activated. Read alongside the full claim-ready account/person dossier skill;
this supplement does not replace its source review, granularity, public-statement or conflict rules.

## Why this work matters

Your dossier is the bridge between acquired research and durable evidence used for account/person
pages, ICP assessment and later campaign work. A fact placed in the wrong field can be more
misleading than a missing field: a hiring requirement can become a false installed-system claim,
a customer benefit can become the target's own performance, or a professional title can become
invented buying authority. Broad categories can also route irrelevant material into many sections.

Your responsibility is faithful meaning and useful retrieval. Preserve every meaningful acquired
observation and reported statement. Classification must help readers find it without changing its
subject, scope, speaker, time or certainty. Do not simplify away the words that made a public
statement significant just to populate a typed field. A small generic finding with accurate
categories is better than a confidently misclassified value. An uncategorized or uncertain finding
is retained for review, not discarded to make a classification report look complete.

## Four separate decisions

1. `claim_type`: observation or reported_statement, according to what the source establishes.
2. Field: the registered question this finding actually answers, under the subject and workspace.
3. Categories: reusable topics actually present in the evidence, potentially more than one.
4. Review and interpretation: preserve uncertainty, duplicate/conflict relationships and optional
   agent interpretation separately. These are neither field types nor evidence categories.

A dossier section is a writing aid, not a field definition. A frontend section is a consumer, not
a category. One claim can support several frontend sections without becoming several claims.

## Use the supplied registry, not field-name intuition

Read the relevant workspace-scoped field catalog and category definitions, including installed
industry fields and any project/brand context needed to understand the assignment. Batch independent
reads and reuse the definitions already inspected. Do not load every industry pack indiscriminately.

For a candidate field, inspect its definition, subject/entity kind, value schema, unit/cardinality,
source constraints and scope. A familiar name does not establish that it fits. Choose the narrowest
existing field that accurately expresses the assertion; do not choose a narrower field merely
because its name contains a keyword from the source. Use the provided registry version/reference.

Seller products and pinned ICP/personas help identify significant evidence. They are not target
facts. A preferred employee range, desired tool or ideal persona cannot populate a target claim.
Field descriptions are instructions about meaning; examples in them are not source evidence.

## Classify each finding while writing it

Work incrementally on meaningful findings, not an exhaustive preliminary classification inventory.

- Identify the actual subject and the specific assertion: who did/said what, for which organization,
  at what time, and with what support? A person's statement about a customer remains about that
  customer; it does not become the employer's own operation.
- Preserve the full source-grounded finding, attribution, source references, public wording,
  qualifications and review links before deciding its structured representation.
- Select a matching registered field only when both meaning and value shape fit. Supply an exact
  typed value if supported; do not invent missing precision, units, list members or dates.
- Otherwise retain account.research_finding or contact.research_finding with precise categories
  and a brief reason why a narrower field does not fit. This is a valid result, not failed work.
- Choose categories supported by the assertion itself. Multiple categories are useful when each
  adds a genuine retrieval dimension; do not attach every remotely related tag.
- Preserve the optional seller-relevance interpretation outside the factual finding. Hypothesized
  buying roles and inferred pressures do not become operational pain or purchase-intent facts.
- Before moving on, compare with existing entries. Reclassifying or attaching another category to
  the same fact does not justify a second finding. Distinct events and statements stay separate.

A typed representation is not a replacement for the retained finding. For example, an integer
headcount value must remain traceable to the exact reported number, provider, time and qualification.
A single number cannot carry a speaker's reasoning. Do not create a shortened statement solely to
fit a scalar field. Do not silently change conflict status to make a value acceptable.

## Category discipline

Use the supplied category vocabulary and meanings. The examples below describe proposed vocabulary;
the trial must supply the actual definitions. Never assume these names are already registered.

- `public_statements`: substantive attributed words or views. A routine identity/title record does
  not earn this tag merely because its profile is public.
- `hiring`: recruitment activity or role requirements. A vacancy describes an intended remit, not
  proof the team currently performs it or has a measured capacity problem.
- `responsibilities`: explicit remit or ownership. A title alone does not establish an entire remit.
- `workflows`: a described process, actors, sequence or handoff. Do not tag every tool name as a
  workflow when the evidence describes no process.
- `technology`: named tools/systems and their qualified relationship to an entity. Preserve whether
  current use, a requirement, personal experience, former-employer use or a customer system.
- `operational_needs`: source-stated needs or constraints. A seller's possible benefit belongs in
  interpretation and does not justify this category by itself.
- `strategic_priorities` / `initiatives`: stated direction versus a concrete program or action.
  An announcement can support both; a general ambition does not establish a launched program.
- `funding` / `financial_performance` / `scale`: financing, operating performance and size are
  different concepts. Funding is not revenue, spend or an allocated buying budget.
- Person background, education, authored work, interests and projects: classify their actual
  content using supplied definitions; do not tag every personal project as a company initiative.

Do not manufacture a category or field key inside a stored finding. If the available vocabulary
misses a meaningful concept, preserve it generically and record a scoped proposal with the proposed
meaning, subject, expected value shape and why existing fields do not fit. Use a registry tool only
if actually provided and authorized. Proposing a field is not registering it; never create global
industry definitions from one account's observations. A missing field must not block the finding.

## Worked examples — fictional evidence, not facts to copy

### Headcount versus team size or a range

Source: an enrichment provider reports 167 employees for Acme.
Wrong: put 167 in a marketing-team-size field or change it to the seller's desired headcount.
Better: if the supplied definition matches total headcount, choose core.employee_count with integer
167. Keep provider attribution and observed date in the finding/provenance; category scale.

If the only source says 100–200 employees, do not invent a midpoint or place a string in an integer
field. Use a matching range field if supplied, otherwise retain the range in a generic finding.
If another dated source reports a different number, preserve both observations and the applicable
conflict assessment; do not average them. Publication date alone does not make an older measurement
current, and routine growth at different times is not automatically a contradiction.

### Required tool versus installed tool

Source: a vacancy says the successful applicant needs HubSpot experience.
Wrong: core.primary_tech_stack = ["HubSpot"], claiming the company uses it.
Better: retain an attributed hiring requirement, categories hiring and technology. Use a specific
requirement field only if its definition matches; otherwise account.research_finding is appropriate.
If a source actually describes operating a HubSpot workflow, preserve that narrower usage assertion
and its scope instead of retroactively strengthening the vacancy's evidence.

### Public voice and a multi-tool workflow

Source: a leader says, "Every Monday we combine website visits and CRM ownership before sending
our reps a prioritized account list. The difficult part is keeping ownership current."
Wrong: replace this with "The company uses CRM and needs automation," or store it only as a tool list.
Better: preserve the statement and attribution, including the ownership-maintenance constraint.
Categories public_statements and workflows apply; operational_needs applies to the stated constraint.
Use a matching rich-statement field if present; otherwise use the subject's research_finding field.
A possible seller solution belongs in agent_interpretation. Do not add purchase intent.

### Professional title and buying role

Source: a current profile lists an individual as VP Finance.
Wrong: classify this as economic buyer or claim they approve software purchases.
Better: use a matching current-title field only when its definition/source rules match this record,
with the original date and uncertainty. A possible economic-buyer role is a separate interpretation.
If the title is from a previous employer, it belongs in employment history rather than current title.

### Accreditation and unrelated credentials

Source: a hospital has a registry identifier; a physician holds board certification.
Wrong: put either fact in an ambulatory-center accreditation field.
Better: use the registry-identifier field for the correct organization, and a credential field for
the correct person, only if defined. Otherwise preserve the respective observations generically.
Do not attach the physician's credential to the organization. Do not use generic fallback as a way
to assert a wrong-entity fact; preserve the mismatch in the finding's review metadata.

### Customer versus target outcomes

Source: Acme quotes a customer saying its response time fell by 40%.
Wrong: Acme's own operational response time fell by 40%.
Better: preserve Acme's attributed customer-outcome report, with the customer's identity and metric
scope. Do not populate Acme's internal performance field. It can inform product understanding
without being evidence of Acme's own operational pain or a new claim about an unbound entity.

### Research gaps versus source disclosure

Researcher conclusion: "We did not find a campaign budget."
Wrong: a supported account finding tagged financial_performance or a zero budget value.
Better: research notes. No source asserted a budget amount or absence.
If a source explicitly says the company declined to disclose its budget, that disclosure is a
reported statement; it still does not establish the budget value.

## Apply the same discipline across dossier sections

| Material | Classification emphasis |
| --- | --- |
| Identity, size and geography | Exact entity, unit, reported value/range and time; preserve estimates |
| Offering and operations | Target's business model or actual processes; keep seller capabilities separate |
| Hiring and organization | Open role versus employee, intended remit versus observed ownership |
| Tools and systems | Installed/current use versus requirement, mention, customer tool or past experience |
| Financing, growth and launches | Independent events, funding versus revenue, intention versus outcome |
| Leadership and public statements | Speaker, original words, statement context and actual subject |
| Person career and education | Correct individual, employer/institution, period and explicit credential |
| Personal projects and interests | Self-disclosed or clearly attributed evidence; no company attribution or personality inference |
| Conflicts and qualifications | Preserve both source assertions and references; keep categories independent of review status |
| Fit arguments and open questions | Attached interpretation or notes, not new factual claims |

## Review and correct the saved dossier

Comprehensively and critically review the saved entries against this supplement and the full
claim-ready dossier skill. Review sources → entries for lost substance, and entries → sources for
unsupported additions. Check the actual chosen field meaning and value schema, not just whether
JSON parses. Check subjects, time, units and relationship direction; check category specificity and
that public wording remains intact. Distinguish separate signals from duplicate copies.

If you find a defect, correct the entry using the available dossier edit/revision tools. Do not
merely note it and leave a misleading classification in place. If classification remains uncertain,
retain the finding with an honest generic classification/reason; do not discard it or invent the
missing evidence. Use the existing revision workflow after import rather than rewriting frozen
history. Research questions stay in notes. Finish with actual validation/import receipts; successful
parsing or import proves mechanics, not complete or correct classification.
