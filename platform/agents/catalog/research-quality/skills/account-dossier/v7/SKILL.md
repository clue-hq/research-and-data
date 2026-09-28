---
schema_version: '1'
kind: skill
name: account-dossier
version: v7
summary: Investigate from complementary search angles, brief Exa, follow sources and select people.
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

## Investigate before briefing Exa

Batch independent reads of the brief, skills and relevant pinned context. Reuse completed reads;
reopen a source for a specific missing detail. Read the available existing findings and source
references before searching again. /research/claims/0.json exposes scoped findings, while
/evidence/index.json exposes originals authorized for this run. These are not an unrestricted
archive of past runs. Preserve useful supplied prior evidence; a new dossier omitting it does
not invalidate it. If an original is unavailable, say so rather than implying you reviewed it.

Before the main deep assignment, choose several complementary ordinary search_web calls
(type=auto) based on the seller, account and open questions. Useful angles include the operating
model; relevant teams and hiring; public professional statements; workflows and systems; and
financing, leadership or organizational changes. Adapt the angles to the actual work the seller
helps with. Additional queries on a deep request do not replace these preliminary searches.
There is no fixed search count or mandatory call per heading.

Start with a modest useful batch, read what comes back and pursue promising leads selectively.
If a preliminary source is slow or unavailable, proceed with available context and include the
unresolved question. Do not exhaust all channels, repeat preparation or keep rephrasing an
unproductive query. Existing synchronous execution and supported batches remain unchanged;
do not assume a pending provider call runs in the background.

Keep a concise source-linked working note in /work/pre-deep-review.md: established findings,
relevant people and statements, unresolved leads and precise questions for Exa. Launch the deep
call when this gives you a useful assignment; do not wait for every research gap to close.

## Research priorities and depth

Allocate attention according to this project, with the following priorities:

1. Relevant people describing their work, priorities, decisions, initiatives and hiring in their own public professional statements.
2. Concrete operating initiatives, workflows and stated constraints.
3. Responsibilities, handoffs, tools, vendors, channels and execution details.
4. Consequential financing, leadership changes and adverse reporting, even without an immediate seller connection.
5. General background needed to understand the above.

Follow useful leads. A hiring announcement can identify its author and their wider professional statements. A named initiative can lead to an interview explaining how it works. A departure can lead to succession information and a company response. Do not stop at titles or headlines, or require quantified pain or purchase intent before considering a finding useful.

## Discover the relevant team, then investigate what its people say

Use the Head-of-ABM brief and selected ICP/personas to identify functions relevant to this
account investigation. Look for executives, team leaders and the practitioners who would do
the work. Do not restrict discovery to the most senior titles or assume the same functions
matter at every company. Ordinary preliminary searches should include these teams alongside
the company angles in the discovery guidance.

As sources identify people, keep a compact working note of their name, source-reported title,
responsibilities, employer context, profile/source URL and useful public statements. Distinguish
observed responsibilities from a possible buying role. Search the discovered person's own posts,
articles, interviews or hiring announcements when they can explain relevant work, initiatives,
decisions, frustrations or execution methods. Use names only after finding them in actual
context or sources. Include executive perspectives and the voices of people performing the work.
An individual's earlier-career statement can explain their experience; it does not establish the
current company's systems or current practices.

This is account investigation, not a personal dossier for everyone mentioned. Preserve useful
professional quotations and the actual workflow details they reveal. Do not replace these with
a list of people and titles, and do not drop their statements when expanding company coverage.

## Pursue a discovered person's relevant professional statements

A title, biography or company-news repost does not answer how someone runs the relevant function.
When a discovered person matters to the brief but their working methods remain unclear, choose
a focused ordinary search about that person and the work. Do not rely solely on a broad company
search or a deep additional query containing several names. For example, use
"{discovered name} {company} {relevant function} hiring workflow automation campaigns" with
terms adapted to the seller and the person's actual remit. This is a query shape, not a fixed
vocabulary or a required search for everyone. Follow useful first-person posts, authored articles,
interviews and hiring announcements; expand relevant sources when excerpts omit their substance.
If results are mainly publicity, change the angle to responsibilities or a discovered initiative.
Do not infer that operating statements do not exist merely because one search did not find them.

## Discover systems through work before guessing brands

Use the relevant function and workflow to discover tools that were not already expected. For
example, a GTM investigation can search "{company} marketing operations revenue operations
integrations job responsibilities" or "{company} account research enrichment outbound workflow".
Other sellers require other functions and terms. A list of familiar vendors can supplement this
investigation, but should not stand in for understanding the work. Follow relevant operations
vacancies, hiring authors, implementation descriptions and professional statements. Read duties,
integrations, automation and named-system passages, not only the introductory job summary.

Keep the source's relationship explicit: an internal workflow, candidate proficiency, earlier
employer experience, customer integration or product compatibility example mean different things.
Record unexpected products when sources name them; do not turn compatibility examples into the
company's installed stack. Do not supply benchmark answers as assumed search targets.

## Recognize when a result is a lead, not a sufficient answer

Ordinary search text is a bounded excerpt. An excerpt ending mid-passage, a named tool without
surrounding responsibilities, a promising job title, an interview listing, a new initiative or
a reference to a relevant department can justify a targeted page read. Open the specific original
page when more of it could answer a concrete question; use the returned complete source record,
including fresh highlights and useful links. A familiar URL may provide new information.

For example, a relevant operations vacancy may reveal workflow ownership, systems, handoffs and
automation expectations beyond its opening paragraph. Read the substantive duties and tool
sections before concluding that no operating detail was found. A leader's hiring post may name
the responsible team and link to the vacancy; follow that relationship if it matters. A product
announcement may point to a release note or official explanation of what actually changed.

If the returned page remains truncated or unavailable, use an alternative official page, linked
posting or a focused query containing the known title and organization. Do not blindly repeat
the same fetch or assume that requesting more characters guarantees a full page. Reuse material
already acquired. Do not crawl every URL or independently corroborate every statement.

## Let evidence guide a small number of useful follow-ups

Before the main deep request, update the source-linked pre-deep note with learned facts, the
relevant people and their statements, promising unresolved leads and precise research questions.
After the deep response, review it alongside sources and reassess the same questions.

Use the working note to prioritize the next useful action: the important unanswered question,
what the current sources establish, the likely source/query, and the value of resolving it.
For example, if the brief concerns campaign execution and you have only a marketing leader's
title plus a short operations vacancy, their own professional statements and the vacancy's duties
usually deserve attention before another customer-success story. Do not launch a dedicated
investigation of the target's customers unless the delegation explicitly calls for it. Preserve
basic commercial context already encountered. This prioritization does not remove broad company
coverage or require every gap to be closed. Stop unproductive repetition when the available
routes no longer add useful information, and report what remains unknown.

For each useful follow-up, identify what is already established, what is missing, why resolving
it would improve understanding and which source or query is likely to help. For a known URL,
prefer reading the page. For an unexplained system or initiative, search its exact discovered
name with the company and relevant function. For unclear ownership, follow the named team's
pages, job descriptions and professional statements. Use another deep assignment only for a
substantial question spanning multiple sources; supply the source URL, useful passage and
specific questions rather than asking to "research more deeply."

Keep the seller's relevant functions central without narrowing the whole company to them.
Briefly scan the eleven dossier areas after preliminary research and again after the main deep
response. Notice neglected areas that could materially change the account picture: recent
product or operating initiatives, financing, organizational changes, leadership and contrary
reporting. Investigate a meaningful omission when there is a useful route. This is judgment,
not eleven required searches, equal-length sections, a completion gate or an exhaustive crawl.

Preserve the strong professional-voice findings already acquired while adding company breadth.
Keep unsupported hypotheses visibly separate from source findings. Use the timing guidance below; do not turn coverage review into a verification requirement.

## Interpret missing results honestly

Distinguish "not found in this investigation" from "does not exist." An unsuccessful search
cannot establish no disputes, no operating problems or no use of a tool. When reviewing the
coverage, notice meaningful contrary evidence as well as supporting evidence. Follow a useful
route when warranted, without a mandatory risk search or a completeness gate. Retain supplied
older evidence with attribution and context rather than silently replacing it with a new
non-finding. Quote exact source wording; label shortened or normalized wording as a paraphrase.

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
source excerpts with their URLs. Ordinary searches, page reads and deep calls also return
`source_review_path`. Read its overview pages and follow relevant `full_source_path` references
for complete returned result records: text, highlights, links and any other supplied fields.
Read the dossier and scan the sources broadly, batching independent reads. Review all overview
pages; titles alone are not source content. `previous_capture` means the URL was captured earlier,
not that you read it or that its contents are unchanged. Inspect added/changed fields; fresh
highlights or links can reveal useful evidence even when the URL and text are familiar.
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

## Media and the person-research handoff

Use the installed media capabilities when a recording or interview could resolve a useful question.
Read /research/capabilities/0.json for discovery, read_media, transcript search and passage access.
Follow candidate references and suggested next actions from media results. Consume available
transcripts or supported transcription, search for relevant passages and retain source URLs,
speaker attribution and timestamps where available. A recording listing or image is a lead,
not spoken evidence. If media cannot be consumed, preserve the lead and state the gap.

Once the account picture is developed, reason about responsibilities and people worth researching.
Use the selected personas and people found in actual sources. Aim for roughly four or five useful
candidates when supported, within this job's committee limit; do not pad or force a role per seat.
Use AI Ark SMART role searches and matching profiles alongside web discoveries. Reuse existing
profiles; an absent provider match must not veto a useful web-discovered candidate. Keep observed
remit separate from a possible buying role, with source URLs and unanswered questions per person.
Read person-research-briefing and write the person-specific research_brief on each nomination.
Use the available nomination tools for durable handoff; a prose candidate list alone does not
launch jobs. Person jobs retain typed enrichment and work-email enrichment, without paid phones.

## Produce the account research dossier

Your research deliverable is your own sectioned JSON dossier, formed from the complete
investigation: searches, original pages, hiring sources, Exa reports and returned sources,
typed enrichment, media and follow-ups. Exa remains an evidence researcher; do not ask it
to write the platform storage schema. Read the complete claim-ready-account-dossier skill
at /.deepagent/skills/claim-ready-account-dossier/v2/SKILL.md and apply its section guide,
worked examples, public-statement fidelity, independent units and critical correction review.
Use save_dossier_section incrementally, validate_dossier for shape/reference feedback, and
finish_dossier for deterministic import after review. No claim-extraction specialist or
second authored Markdown report is needed. /research/dossier/latest.json exposes your
saved document, state and import receipt. Keep research questions and coverage notes under
/work/. Include interpretations only in their optional field, not as standalone facts.

Preserve original evidence references and source-only findings; your synthesis is not a
verbatim source. Save and import the initial account investigation without waiting for person
jobs. On subsequent continuations, read the existing dossier and receipt first. Reuse the
frozen account claims and existing person claims for narrative refresh; do not copy contact
findings into account claims or repeat completed acquisition/import. Note new research needs
separately; this import does not implement cross-entity reconciliation or claim correction.

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
