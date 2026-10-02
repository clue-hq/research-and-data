---
schema_version: '1'
kind: skill
name: account-dossier
version: v2
summary: Prepare an account-specific Exa dossier assignment and complementary additional
  queries.
roles:
- account_research
readiness_requirements: []
tools: []
framework: deepagents
framework_version: '>=0.6,<0.7'
---

# Account dossier and Exa briefing

You are investigating one target account for the seller and project described in the Head-of-ABM delegation brief. Understand the work the seller helps with, then investigate the target's actual business, people and operating situation.

## Understand the assignment

Read the delegation brief and consult the referenced seller, selected-product, project-pinned ICP and persona documents where needed. A project may use a brand definition or its own variant; follow its selected references. Preserve the selected offering's capabilities and limits. Missing context remains a stated gap, not a reason to substitute another seller's proposition.

Keep seller-fit assessment, qualification thresholds, committee-role assignments and purchase recommendations with the parent research agent. Translate those criteria into substantive questions for Exa. For example, a preferred team size becomes an investigation of team size, composition and responsibilities; an incumbent-tool exclusion becomes an investigation of the systems used and the work performed in them. Do not send the pass/fail threshold or internal scoring labels.

Seller context guides attention; it does not establish facts about the target. AI Ark supplies typed company/person enrichment and candidate profiles. It may provide supporting context, but its description must not become the company's narrative by direct copying. Use substantive research and company sources for that understanding. Both web discovery and AI Ark SMART discovery remain available; contact enrichment covers work email, not phone numbers.

## Prepare without repetitive work

Batch independent reads of skills and context documents. Reuse completed reads; reopen a source for a specific missing detail rather than starting preparation again. You may inspect relevant official pages, job descriptions or existing research to sharpen the assignment. If a preliminary source is slow or unavailable, proceed with the context available and include the unresolved question.

Launch the Exa assignment promptly once it is useful. Do not wait to exhaust company pages, hiring, people discovery or media. Those remain part of the wider investigation. Use the existing synchronous tool behavior and supported batches; do not assume a pending call runs in the background. No preparation timer or mandatory preliminary-research checklist applies.

## Research priorities and depth

Allocate attention according to this project, with the following priorities:

1. Relevant people describing their work, priorities, decisions, initiatives and hiring in their own public professional statements.
2. Concrete operating initiatives, workflows and stated constraints.
3. Responsibilities, handoffs, tools, vendors, channels and execution details.
4. Consequential financing, leadership changes and adverse reporting, even without an immediate seller connection.
5. General background needed to understand the above.

Follow useful leads. A hiring announcement can identify its author and their wider professional statements. A named initiative can lead to an interview explaining how it works. A departure can lead to succession information and a company response. Do not stop at titles or headlines, or require quantified pain or purchase intent before considering a finding useful.

## Dossier coverage

Adapt these eleven areas to the target and assignment. They guide depth, not equal-length sections or one tool call per heading. For a healthcare seller, relevant operations could be referral intake and clinical administration; do not automatically substitute a marketing investigation.

1. **Business and operating model.** Offering, delivery model, business units, locations, sales motion and published packaging/pricing. Explain whom the target serves at a high level. Do not compile customer-logo inventories or investigate its customers' operations.
2. **Ownership, financing and resources.** Ownership, funding rounds, strategic investments, workforce estimates and reported financial performance. Capture dates, stated uses of proceeds and conflicting estimates with attribution.
3. **Strategy and active initiatives.** Launches, expansion, partnerships, reorganizations and operating programs. Explain what changed, the work involved and whether it is announced, planned or executed.
4. **Workflows and operating demands.** Relevant teams, tasks, handoffs, systems, workload, workarounds, goals and stated constraints. Preserve concrete steps even when costs, delays or capacity are unquantified.
5. **Hiring and organizational change.** Distinctive responsibilities, reporting lines, tools, geography and team-building mandates. Follow hiring-post authors. Distinguish listing dates, currently open vacancies, closed listings and confirmed appointments.
6. **Tools, vendors and execution approaches.** Named systems and their uses, internal automation, agencies and contractors. Separate actual use from candidate experience, integrations and partnerships. A failed search does not establish non-use.
7. **People and organizational responsibilities.** Relevant executives and practitioners, remit, reporting relationships, appointments and departures. Investigate decision processes where sources explain them, without asking Exa to assign seller-specific champion, buyer or blocker labels.
8. **Public professional voice and working culture.** Posts, interviews, talks, podcasts, professional articles, why-I-joined accounts and firsthand descriptions of initiatives. Preserve the speaker/author, context, date, useful quotation or faithful paraphrase, and source URL. A recording title or promotional description is not spoken testimony.
9. **Timing and meaningful developments.** Dated changes that explain the company's present direction. Explain supported connections without inventing causation, urgency or purchasing plans; avoid repeating entire findings.
10. **Contrary evidence and business risks.** Leadership departures and succession, growth or financial pressure, restructuring, disputes, acquisition reporting and substantive criticism. Attribute allegations and include available company responses. Internal hiring or automation alone is neither positive nor negative seller fit.
11. **Unexpected findings and open questions.** Follow consequential discoveries beyond the starting questions. Preserve partial answers, identify remaining uncertainty and name useful follow-up leads.

Use the nine calendar months ending on the supplied research date for recent developments and state the dates explicitly. Older evidence may explain current circumstances; label it historical. Do not inherit an older brief's six-month emphasis or pretend an undated source is recent.

## Write the main Exa assignment

Write a self-contained query with five elements:

1. **Target and period:** name, domain, useful identity context, research date and nine-month window.
2. **Purpose and seller context:** the selected offering, relevant capabilities and limits, and why particular operations deserve attention. Exa cannot read internal document references.
3. **Dossier coverage:** substantive questions under the eleven areas, adapted to this account and seller.
4. **Account-specific probes:** questions arising from the brief, existing evidence or preliminary reading. Include useful source URLs and established findings so Exa can extend, update or challenge them. Distinguish old findings from present facts.
5. **Evidence and output expectations:** a detailed Markdown dossier with inline source URLs, dates, attributed figures, useful exact quotations, qualified interpretations and unresolved questions.

Combine overlapping probes instead of appending repeated lists. Keep broad business investigation alongside seller-relevant depth. Ask for research, not outreach, field classification, page synthesis or a qualification verdict. A useful assignment is detailed enough to guide investigation without copying complete internal documents or this skill.

## Write complementary additional queries

Alongside the main assignment, compose a small set of additional queries, usually three to five. This is guidance, not a quota. Each should identify the target and pursue a distinct, high-value search angle based on actual project context or available leads.

Useful angles include relevant people's professional statements; specific workflows and initiatives; detailed hiring responsibilities and tools; and consequential financing, leadership or adverse developments. Choose the angles for this account rather than copying a universal list.

Use names, tools and initiatives when supported by the context already available. If names are unknown, search by relevant functions and responsibilities. Do not invent names or spend extra preparation rounds merely to populate named searches. Phrase uncertain ideas as investigations, not assertions that the target has a problem or uses a product.

Keep each query focused and complementary to the main assignment. Avoid near-duplicates, repeated dossier headings, seller-fit verdicts, internal scoring terms and unnecessary exact-phrase quotation marks. Broader role-based and named-person searches can coexist when they investigate different evidence.

Pass these strings through the tool's separate `additional_queries` argument using acquire_research_evidence with operation="research_deep" and that field inside arguments; listing them only inside the charter does not populate the API parameter. Put account-specific probes inside the main charter once; the new account tool has no separate probes field. These strings guide the same Exa request; they are not instructions to buy one deep-research call per string. The result-count setting is not the number of searches performed.

## After Exa returns: read the sources alongside the dossier

Treat the dossier as a useful synthesis, not an inventory of everything discovered. Open the
acquisition result's `source_navigation`: it links the original response, dossier and individual
source excerpts with their URLs. Read the dossier and scan the returned source excerpts broadly,
batching independent reads. Review all source-index pages; titles alone are not source content.
Give deeper attention to professional statements, operating workflows, responsibilities, tools,
hiring status, dates and contrary evidence, while remaining open to unexpected useful findings.

Preserve useful information that appears only in the sources. Expand compressed details when
they matter to this project's questions. If the dossier contradicts a source, explain precisely
what the source supports and correct your research notes with that source's URL. Neither a
provider summary nor a job requirement automatically establishes a deployed system, completed
initiative or buying intention. Check simple date/window comparisons when they affect a finding.

For example, a fictional Acme dossier says no evidence of a sales-engagement tool was found,
but its BDR job excerpt explicitly names a fictional tool, ReachPilot. Retain that the posting names ReachPilot;
do not repeat the dossier's non-finding or turn a hiring requirement into proof of company-wide
deployment. The same excerpt may contain account mapping and sales handoffs worth preserving.
This is an illustration of source use, not a required tool name or expected discovery.

Open an original page when an excerpt is insufficient for a specific ambiguity or promising
lead. Reuse already acquired text. Do not refetch every URL, repeat completed research, or seek
another source merely to permit a finding. Highlights are excerpts, not complete pages; a
podcast description is not a processed recording. Note unavailable material and continue.

Keep concise source-linked findings, interpretations and remaining questions for the existing
research handoff. Distinguish corrections to the dossier from new source-only detail. Preserve
who said what, when, and where; do not silently merge different people or events. Passing source
references to a specialist must include useful source-only findings, not just dossier passages.
Source review is investigative guidance, not a verification, completion or presentation gate.

## Teaching example: Clue → fictional Acme

This example is for your instruction only. Do not include it, its fictional findings, its dates or its names in a real account request.

Assume the supplied Clue brief describes agents for account and buying-committee research, campaign briefs and personalized campaign production with brand context and human review. Assume fictional Acme sells enterprise software, its current brief names growth leader Morgan Lee, and an available job description discusses coordinating webinars and field events. These are illustrative inputs, not independently established company facts.

An appropriate main assignment would read:

> Research Acme at acme.example as of 24 September 2026. Focus recent developments on 24 December 2025–24 September 2026, labelling older background. Clue's supplied offering supports account research and personalized campaign execution. Investigate how Acme's own commercial teams perform that work; do not assess whether Acme should buy Clue.
>
> Explain Acme's business and sales motion; ownership, financing and resources; strategy and active initiatives; account research, campaign-production and sales-handoff workflows; hiring and organizational changes; tools, vendors and internal approaches; relevant people's responsibilities; public professional statements and working practices; meaningful dated developments; contrary reporting and company responses; and unexpected findings and unresolved questions. Keep general background concise and pursue operational detail deeply. No downstream customer inventory is needed.
>
> The supplied role description mentions coordinating webinars and field events. Investigate who owns those activities, how account selection and follow-up work, what content or systems are involved and what the participants themselves say about execution. Morgan Lee is named in the supplied brief as a relevant growth leader: investigate their professional posts and interviews while noting any ambiguity about current responsibilities. Do not assume coordination is broken or that internal AI experiments imply buying intent.
>
> Return substantive Markdown research with source URLs beside findings, dates, useful quotations and explicit attribution. Preserve partial answers and separate stated activities, requirements and plans from interpretation. Follow useful discoveries beyond these questions and consolidate remaining gaps at the end.

Complementary additional queries could be:

```json
[
  "Acme acme.example Morgan Lee growth marketing public posts interviews campaign execution",
  "Acme acme.example webinar field event account selection sales follow-up workflow hiring",
  "Acme acme.example marketing operations content production tools agencies automation",
  "Acme acme.example financing leadership changes commercial growth challenges company response"
]
```

The main assignment explains the investigation. The extra queries direct attention to distinct evidence. On a real account, use its actual identity, date, selected offering, priorities and available leads.
