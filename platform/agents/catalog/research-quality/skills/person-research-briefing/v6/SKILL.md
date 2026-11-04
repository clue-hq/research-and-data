---
schema_version: '1'
kind: skill
name: person-research-briefing
version: v6
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
   Include everything you have already read that this person wrote, said or was
   quoted in — posts, comments, hiring posts, interviews, talks — with its URL,
   date and the exact passage. Also include pages you read that describe their
   role or team. The person researcher starts without your sources and may not
   find them again, so anything you read but leave out of the brief can be lost.
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

- **Voice:** their own words first, on LinkedIn and everywhere else: posts, articles, comments, interviews, podcasts, talks and webinars, with source names, URLs and dates. Say when substantial long-form material is unavailable.
- **Now:** the problems they are dealing with, what they are building, changing or hiring for.
- **Professional identity:** accomplishments and pride; stated frustrations and things they consider broken; how they evaluate vendors and tools, and tools they have named.
- **What the account already has** in place of what the seller sells, and any sign it is already the seller's customer.
- **Life outside work, as self-shared:** hobbies, sports, causes, volunteering, mentoring, and books or podcasts they recommend.
- **Distinctive findings and gaps:** retain the strongest quote-backed insight beyond a standard profile and other useful discoveries. State what could not be reached and the routes tried; note same-name sources actually encountered and why they concern someone else. These notes do not create verification blockers.

These directions add emphasis without narrowing the charter's detailed coverage.

### Expected result and further reading

Return findings with source URLs, useful quotations, dates, attribution and open
questions. Read Exa's sources alongside its dossier and follow promising leads.
Do not force a positive seller-relevance conclusion.

Consult the Clue seller/product brief, project-pinned ICP and persona through
`/research/context.json`; the completed account JSON dossier through
`/research/parent-account-dossier.json`; account claims through `/research/claims/0.json`;
and the saved hiring post, profile and other originals through the supplied
source references and `/evidence/index.json`.
