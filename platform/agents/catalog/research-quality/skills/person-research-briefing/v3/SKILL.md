---
schema_version: '1'
kind: skill
name: person-research-briefing
version: v3
summary: Write a concise person-specific delegation before starting research on an already-discovered person.
roles:
- account_research
readiness_requirements: []
tools: []
framework: deepagents
framework_version: '>=0.6,<0.7'
---

# Brief the person researcher

Read this skill before nominating a selected person for depth research. You, the
account research agent, write the assignment in `research_brief` on
`nominate_committee_candidate` or `nominate_web_committee_candidate`. This is a
separate person job, so give its researcher enough context to begin intelligently.
Write as a knowledgeable colleague delegating an investigation. Do not launch
another agent merely to write the brief.

## Understand, then delegate

Use the Head-of-ABM assignment, the project's pinned seller/product/ICP/persona
context, your account findings, and the selected person's discovery record.
A project may select brand definitions or its own variants; keep its actual pins.
Reuse what you have read. Consult missing originals when useful, without repeating
preparation or waiting for every possible account finding before delegating.

Write one brief for this person. Explain the purpose, the seller's relevant
capabilities, the target's situation, why you selected this person, what is known,
and what the investigation should uncover. Distinguish observed responsibilities
from your hypothesis about a buying role. Preserve useful product-specific limits
and context gaps without inventing pricing, integrations, outcomes or proof.

Keep the brief readable, with short sections and concrete questions. Around
750 words is acceptable when useful; shorter is fine too. This is flexible writing
guidance, never a hard cap, rejection rule or truncation limit. Do not omit useful
context or charter specificity just to meet a word count.
Do not paste full documents, the entire account dossier, field catalogs or generic
ABM explanations. Do not explain the framework's built-in filesystem tools.

## Shape of the brief

1. **Your assignment:** the known person's name, aliases/profile when available,
   target company/domain, seller, purpose and reason for selection.
2. **Who we are researching for:** selected offering, the work it helps with and
   the relevant project/persona lens, with important limits.
3. **What the account research already found:** useful source-backed observations,
   person-specific leads, prior findings and uncertainties. Past experience does
   not establish the current company's systems or the person's present remit.
4. **Where to go deeper:** a few questions arising from this account and person;
   authored posts, interviews, hiring statements, earlier employers or other
   promising leads already located. Under this same heading, briefly summarize
   the person-depth charter's coverage using the specifics below; do not merely
   say "apply the complete charter." These are directions, not conclusions.
5. **Expected result and references:** source-linked findings, useful exact quotes,
   dates/attribution, uncertainty and follow-ups; references to complete originals.

## Preserve person depth

Your questions supplement the full person-depth charter; they never replace it
or reduce it to seller-fit questions. Include a short, explicit coverage reminder
under "Where I would like you to go deeper":

- **Background:** hometown/upbringing; education, subjects, years, student activities and awards; first jobs and career origin; publicly described military, sport, arts or other non-corporate experience; languages.
- **Life outside work, as self-shared:** hobbies, sports, pets and milestones; volunteering, boards, mentoring, alumni service and causes; side projects, newsletters and communities; recommended books, podcasts, tools and people.
- **Voice:** seek 3–5 revealing verbatim quotes from interviews, podcasts, talks, webinars or authored work, with source names, URLs, dates and timestamps where available. Say when substantial long-form material is unavailable.
- **Professional identity:** personal responsibilities, accomplishments and pride; stated frustrations and things they consider broken; how they evaluate vendors/tools and tools they have named.
- **Distinctive findings and gaps:** retain the strongest quote-backed insight beyond a standard profile and other useful discoveries. State missing categories and channels checked; note same-name sources actually encountered and why they concern someone else. These notes do not create verification blockers.

This reminder does not replace the detailed charter. Preserve its explicit
subquestions in the later Exa request, rather than reducing them to vague headings.
The person researcher writes that request; this delegation is not an automatic
appendix to Exa. Outreach copy belongs to a later writing step.

Research an already selected person; do not delegate committee discovery again.
Reuse the acquired profile. Work-email enrichment remains available; no paid phone
enrichment. Source-reported affiliation is sufficient to proceed. State ambiguity
without requiring location, employment or corroboration proofs or hiding findings.

## Complete originals remain available

In the references section, name the actual seller overview, selected products,
pinned ICP/personas and their known versions or identifiers. The person worker's
`/research/context.json` provides `document_paths` for complete documents, the
selected identity, discovery references and account-research reference paths.

Account findings are at `/research/claims/0.json`; the account's original provider
reports, pages and available transcripts are indexed at `/evidence/index.json`.
Point to particular source IDs, evidence paths and public URLs when useful. Reuse
only references actually acquired for this account; never invent IDs or copy a
parent-only local workspace path as though the person worker could open it.
A public URL may need fetching; it is not a promise that a page is already saved.

The exact delegation is retained separately at `/research/person-brief/0.json`.
The brief is an instruction, not a source of factual evidence. The person agent
can selectively read complete originals; your summary must not stand in for them.
References do not imply successful access: mention missing material honestly.
The account may still be researching; describe current knowledge without claiming
its investigation is complete. Repeating a nomination reuses the existing person
job and its original assignment; it does not update a running job's brief.

## Example: Clue → Acme → Dana

Fictional teaching example only. Acme, Dana and the findings below are invented
solely to illustrate the writing style. Clue's example positioning is agentic ABM
for lean B2B go-to-market teams. Use real project context in actual briefs, and
replace the illustrative document names with actual references. Never copy this
example's people, facts or questions into another assignment.

### Your assignment

Research Dana, the selected Head of Growth Marketing at Acme (acme.example), for
seller Clue. I selected Dana because the retained hiring post describes building
an ABM program and coordinating integrated campaigns with Sales. Understand Dana's
responsibilities, priorities and working methods, alongside their broader
background, public voice and interests. The selected profile reference accompanies
this job; preserve any uncertainty it reports.

### Who we are researching for

Clue helps B2B teams research accounts and buying committees and produce
personalized campaigns, including microsites, paid media and direct mail. For
this project, we want to understand how Acme manages account-specific research,
campaign production and coordination as its activity grows.

Use the project's pinned ICP and persona documents for the targeting context.
Dana's title and hiring activity make the person worth investigating; neither
establishes purchasing authority or demand for Clue. The supplied example seller
brief has no named CRM integration list, so do not assume compatibility.

### What the account research already found

The saved hiring post seeks an ABM campaign manager who will collaborate with
Sales. Dana's profile describes marketing-operations experience at an earlier
employer. That is career context, not evidence of Acme's present systems. Current
team size, campaign workload and purchasing responsibility remain open questions.
Start with those original references and extend the investigation.

### Where I would like you to go deeper

- What does Dana personally own, and what are they trying to build?
- What do their own posts or interviews reveal about campaign execution,
  collaboration with Sales, automation and measurement?
- Does material from earlier roles explain their methods and evaluation criteria?
- Which background, interests, contributions or accomplishments help us understand
  the person beyond the job profile?

Alongside these account-specific questions, cover the complete person-depth charter:

- **Background:** hometown/upbringing; education, subjects, years, student activities and awards; first jobs and career origin; publicly described military, sport, arts or other non-corporate experience; languages.
- **Life outside work, as self-shared:** hobbies, sports, pets and milestones; volunteering, boards, mentoring, alumni service and causes; side projects, newsletters and communities; recommended books, podcasts, tools and people.
- **Voice:** seek 3–5 revealing verbatim quotes from interviews, podcasts, talks, webinars or authored work, with source names, URLs, dates and timestamps where available. Say when substantial long-form material is unavailable.
- **Professional identity:** personal responsibilities, accomplishments and pride; stated frustrations and things they consider broken; how they evaluate vendors/tools and tools they have named.
- **Distinctive findings and gaps:** retain the strongest quote-backed insight beyond a standard profile and other useful discoveries. State missing categories and channels checked; note same-name sources actually encountered and why they concern someone else. These notes do not create verification blockers.

These directions add emphasis without narrowing the charter's detailed coverage.

### Expected result and further reading

Return findings with source URLs, useful quotations, dates, attribution and open
questions. Read Exa's sources alongside its dossier and follow promising leads.
Do not force a positive seller-relevance conclusion.

Consult the Clue seller/product brief, project-pinned ICP and persona through
`/research/context.json`; account findings through `/research/claims/0.json`;
and the saved hiring post, profile and other originals through the supplied
source references and `/evidence/index.json`.
