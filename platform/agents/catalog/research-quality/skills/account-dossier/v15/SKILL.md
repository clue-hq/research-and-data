---
schema_version: '1'
kind: skill
name: account-dossier
version: v15
summary: Investigate from complementary search angles, brief Exa, follow sources, select people, and write a versioned markdown dossier.
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

Keep seller-fit assessment, qualification thresholds, committee-role assignments and purchase recommendations with you, the account researcher. Translate those criteria into substantive questions for Exa. For example, a preferred team size becomes an investigation of team size, composition and responsibilities; an incumbent-tool exclusion becomes an investigation of the systems used and the work performed in them. Do not send the pass/fail threshold or internal scoring labels.

Seller context guides attention; it does not establish facts about the target. AI Ark supplies typed company/person enrichment and candidate profiles. Use its typed facts as supporting context. Descriptions, biographies and promotional prose are excluded from research inputs. Develop substantive understanding from research and company sources. Both web discovery and AI Ark SMART discovery remain available; contact enrichment covers work email, not phone numbers.

## How the investigation runs

Work in a loop, not a fixed sequence:

1. Read the brief, the seller's product documents and the ICP, and write your hypotheses.
2. Make your first batch ordinary searches across different sides of the company, together with your AI Ark people searches. Then, in your second batch, send the Exa deep call (below), briefed with what the first batch taught you, alongside your next searches. The deep call runs in the background while you keep searching.
3. Read what comes back. Before your next batch, add three lines to /work/hypotheses.md: the most surprising or useful thing you just learned, the question it raises, and what you will search next.
4. Follow the most promising leads at least two steps deeper before starting new broad searches. A batch of many unrelated searches is not a substitute for following one good lead to its end.
5. Research all eleven areas in "Dossier coverage" on every account, whatever your hypotheses and four answers say. Your questions tell you where to dig deepest; they never make an area skippable. Before you stop, go through the eleven areas and ask of each: did I search it properly, and what did I find? If you looked properly and found nothing, say so under "Open questions". Then nominate the buying committee and finish the dossier. Write findings into the dossier as you go and commit when your understanding changes. Do not leave all the writing to the end.

Keep researching while it is still teaching you something new. Cover the account in breadth and in depth: every side of the company that matters for this seller, and each interesting thread followed until you reach the specifics. A clear verdict is not a reason to stop; there is usually more to learn about why it is so, who is behind it and what would change it. When your searches across all eleven areas keep returning what you already know, or nothing, you have found what there is to find, and you can stop. Do not keep searching just to search.

Ordinary search_web (type auto) is your main tool, and you do the research yourself. Work in two passes. First go wide: run several searches at once, each on a different side of the company, such as its people and what they say, how its work gets done, the tools and vendors it uses, what changed recently, money and ownership, and criticism or trouble. Choose the sides that matter for this seller and this account. Then go deep on every side that turns up something interesting. Read the pages, follow names, dates and initiatives back to the original source, and keep going until you reach the specifics or run out of ways to find them. Do not cut a promising line short. Short, specific queries work best: the company with a function, a person's name with a topic, the exact name of a product or initiative. When a result looks promising but the excerpt is short, read the page.

Read the existing findings and source references before searching again: /research/claims/0.json exposes scoped findings, and /evidence/index.json exposes originals authorized for this run. Preserve useful supplied prior evidence; if an original is unavailable, say so rather than implying you reviewed it.

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

When a search result says something about the account's people, tools, vendors or problems (a complaint, an incident, a departure, a workload figure), open it and record it, even if it does not settle a question. Criticism of the tool they already use belongs under "What they use now and its problems".

## Follow the threads

A thread is worth following when it could change one of your four answers. Common threads:

- a job posting, then its duties and tools, then the person who posted it, then their own posts and talks;
- a named vendor or tool, then its case study or announcement, then what it covers and what it still leaves to people;
- a leadership change, then the announcement, then what the new leader says they will change;
- a podcast or conference listing, then the recording or transcript, then the person's own words.

Follow each thread until it answers the question or runs dry. If a search returns nothing useful, change the angle (a different function, a named person, the exact product name) rather than repeating it. Do not refetch pages you already have.

Keep the seller's relevant work at the centre, but do not narrow the whole company to it. Recent initiatives, financing, organisational changes, leadership and contrary reporting can all change your answers.

### What deserves digging

Some results matter more than others. Treat these as signals to dig:

- a surprise: something you did not expect, or that contradicts what the company says about itself;
- a named product, vendor or tool;
- a person's own complaint, frustration or stated goal;
- a number: volumes, headcount, savings, targets;
- something described as planned, piloted or "coming soon";
- a recent change of leader, owner or system.

When you see one, follow it at least two steps before moving on. Do not check things for the sake of checking. Each search should be trying to learn something that changes or sharpens your answers.

## Example: shallow versus deep research

This example is fictional and comes from one industry. It shows the depth expected, not the questions to ask. For a different seller or industry, ask the equivalent questions in that business's own terms.

Suppose the seller sells software that automates appointment scheduling, and the target is Northfield Health, a chain of clinics.

Shallow: "Northfield Health uses SchedulePro for scheduling." This answers a yes-or-no check and stops there.

Deep: keep asking until you can describe the situation.

- **What does the current tool do, and what does it leave to people?** A front-desk job posting still lists "manage the waitlist and call patients to fill cancellations", so cancellations are still handled by hand.
- **Who chose it, when and why?** A press release from two years ago quotes the operations director on choosing it for its patient reminders. Search for what she has said since.
- **What problems do they have with it?** A staff review mentions double bookings after a system update. A recent post by the IT lead talks about "workarounds between scheduling and billing".
- **How much of this work is there?** The company runs 40 clinics, and the posting says each front desk handles "up to 200 calls a day".
- **What has changed recently?** A new chief operating officer arrived in the spring and has spoken about "reducing no-shows".
- **So how could the seller prove it is better?** By focusing on cancellations and no-shows, which the current tool leaves to staff and the new COO has named as a goal, rather than proposing to replace the whole system.

The pattern applies to any seller and industry: find what they use today, what it leaves undone, who chose it and what they say about it, how much of the work there is, what has changed recently, and where the seller could prove itself. Use the terms of the actual company and industry.

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

## The Exa deep call: one broad sweep

Make one deep call per account, in your second batch, after a first round of ordinary searches. It surfaces sources you would not think to search for. Its sources are pages you can read and cite. Its report is a summary written by another model: it drops details and sometimes gets a page wrong, so check the report's claims against the sources before relying on them.

Brief it from what you know by then: the brief, the seller's products, your hypotheses and what your first searches found. Write a self-contained query with five elements:

1. **Target and period:** name, domain, useful identity context, research date and nine-month window.
2. **Purpose and seller context:** the selected offering, relevant capabilities and limits, and why particular operations deserve attention. Exa cannot read internal document references.
3. **Dossier coverage:** substantive questions under the eleven areas, adapted to this account and seller.
4. **Account-specific probes:** questions arising from the brief, existing evidence or preliminary reading. Include useful source URLs and established findings so Exa can extend, update or challenge them. Distinguish old findings from present facts.
5. **Evidence and output expectations:** a detailed Markdown dossier with inline source URLs, dates, attributed figures, useful exact quotations, qualified interpretations and unresolved questions.

Combine overlapping probes instead of appending repeated lists. Keep broad business investigation alongside seller-relevant depth. Ask for research, not outreach, field classification, page synthesis or a qualification verdict. A useful assignment is detailed enough to guide investigation without copying complete internal documents or this skill.

## Write complementary additional queries

Everything the deep call returns is evidence. Read its report and go through its sources: each one is a page you can read and cite. Use what bears on any of the eleven areas, and check anything you rely on heavily against the original page. Then do your own wide and deep searching for what it missed.

Alongside the main assignment, compose a small set of additional queries, usually three to five. This is guidance, not a quota. Each should identify the target and pursue a distinct, high-value search angle based on actual project context or available leads.

Useful angles include relevant people's professional statements; specific workflows and initiatives; detailed hiring responsibilities and tools; and consequential financing, leadership or adverse developments. Choose the angles for this account rather than copying a universal list.

Use names, tools and initiatives when supported by the context already available. If names are unknown, search by relevant functions and responsibilities. Do not invent names or spend extra preparation rounds merely to populate named searches. Phrase uncertain ideas as investigations, not assertions that the target has a problem or uses a product.

Keep each query focused and complementary to the main assignment. Avoid near-duplicates, repeated dossier headings, seller-fit verdicts, internal scoring terms and unnecessary exact-phrase quotation marks. Broader role-based and named-person searches can coexist when they investigate different evidence.

Pass these strings through the tool's separate `additional_queries` argument using acquire_research_evidence with operation="research_deep" and that field inside arguments; listing them only inside the charter does not populate the API parameter. Put account-specific probes inside the main charter once; the new account tool has no separate probes field. These strings guide the same Exa request; they are not instructions to buy one deep-research call per string. The result-count setting is not the number of searches performed.

## When the deep call returns: read the sources alongside the report

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
who said what, when, and where; do not silently merge different people or events. Carry useful source-only findings into your dossier alongside relevant report findings.
Source review is investigative guidance, not a verification, completion or presentation gate.

Open the full record of every source that bears on the eleven areas; the overview list alone is not enough. Keep the useful detail that appears only in the sources.

Then question what it gave you. For everything it raised, contradicted or left half-said (a name, a vendor, a date, an initiative, a claim with no source), ask what you would need to know next, and search for it. These follow-ups become your next searches, alongside your hypotheses and the eleven areas.

## Media and the person-research handoff

Use the installed media capabilities when a recording or interview could resolve a useful question.
Read /research/capabilities/0.json for discovery, read_media, transcript search and passage access.
Follow candidate references and suggested next actions from media results. Consume available
transcripts or supported transcription, search for relevant passages and retain source URLs,
speaker attribution and timestamps where available. A recording listing or image is a lead,
not spoken evidence. If media cannot be consumed, preserve the lead and state the gap.

Start reasoning about responsibilities and people in your opening rounds, and keep refining as the
account picture develops: hiring posts, team posts and interviews often name the people who run the
work.
Map people early, but nominate only after your research loop has settled your four answers. By then you know who actually runs the work.
Use the selected personas and people found in actual sources. Aim for roughly four or five useful
candidates when supported, within this job's committee limit; do not pad or force a role per seat.
Use AI Ark SMART role searches and matching profiles alongside web discoveries. Reuse existing
profiles; an absent provider match must not veto a useful web-discovered candidate. Keep observed
remit separate from a possible buying role, with source URLs and unanswered questions per person.
Read person-research-briefing and write the person-specific research_brief on each nomination.
Use the available nomination tools for durable handoff; a prose candidate list alone does not
launch jobs. Person jobs retain typed enrichment and work-email enrichment, without paid phones.

## Write the dossier

Your dossier is /outputs/dossier.md, with its index at /outputs/dossier-index.json.

### The headings

Use these nine headings, in this order, each as a level-two heading written word for word (for example `## Verdict`). Each one answers a question. When the research found nothing for a heading, write one line saying so and what you tried.

1. **Verdict.** Pursue, pursue with conditions, or deprioritise, and why, in three to five sentences. Include the conditions, and how the seller could still improve its chances, or, for a strong account, how to go after it.
2. **What they do.** The business, whom it serves, and at what scale, as it bears on the seller.
3. **What changed recently.** Dated changes in the last nine months that make now a good or a bad time. When you cannot pin down when something happened, say so and give what you do know (for example "undated; first seen in a March 2026 post"). Do not count it as recent unless a source shows that it is.
4. **How the work is done today.** The teams, workflows and systems the seller's product would touch, and what is done by hand.
5. **What they use now and its problems.** Vendors, in-house tools or outsourced teams that do this job, and what is wrong with them or left undone.
6. **How the seller could prove itself here.** What this company would need to see, and what would convince the people who decide.
7. **Who decides and who to approach first.** The people, their remit, and why that order. Name the committee you nominated.
8. **What could stop a deal.** Incumbents, building in-house, budget, reorganisations, disputes, and conflicting figures not to rely on.
9. **Open questions.** What you could not establish, what you tried, and the best lead for each.

The eleven coverage areas above guide what you investigate. These nine headings are how you write it down.

The dossier is about the account, not about your research. Do not write about your tools, searches that returned nothing, lookups that failed, or which hypotheses you closed. That belongs in /work/hypotheses.md. Under "Open questions", say what is still unknown, why it matters, and the best way to find it out.

### Open each heading with its answer

Open each heading with two to four sentences that answer its question for this seller, drawing its findings together and citing them by number (for example, "Timing is poor: they chose a rival in August (F004) and are expanding it (F006)"). The findings that follow are the evidence for that answer.

Write the Verdict as plain paragraphs, not as a finding. Say pursue, pursue with conditions or deprioritise; why; the timing; and, for a weak account, what would have to change for the seller to come back, or, for a strong one, how to go after it. Cite the findings it rests on.

Under "What could stop a deal", put the obstacles in order, the most serious first.

### A finding

Under each heading, write findings. Each one starts with its number and a short title that says the point:

```
### F007 · Finance still matches supplier invoices by hand
```

Then, in a short paragraph:

- what the source says, with its date, and who said or published it;
- the person's exact words in quotation marks when their words carry the point;
- the source, as its exact path from the evidence index, in brackets: `[/evidence/...]`. Cite every source the finding rests on.

**Reading:** (optional) your own interpretation from the seller's point of view: what you conclude, and how it helps the seller. Add it only when you have something to say.

Most findings take 40 to 90 words. Number findings F001, F002, … across the whole dossier; never reuse a number.

### Quotes

Public statements are first-class findings. What the company's people say in public, its executives and the people who would buy, is the strongest evidence of what they think: their priorities, how they work, what frustrates them, what they are trying to fix. Look for it on purpose, in posts, interviews, podcasts, talks, articles and the company's own releases, and give it its own finding.

Keep the words that carry the meaning: numbers, ownership, urgency, constraints, and "but" or "without". For example, if a Head of Growth writes "Two marketers support forty named accounts. Every campaign brief is rebuilt by hand, and Sales often gets the material after the meeting. We're trying to fix that without adding headcount," do not shrink it to "they are scaling ABM". That drops the numbers, the manual work, the late hand-off and the staffing limit. Quote the passage, with the speaker's name, role, where and when.

Quotation marks hold only the source's exact words, copied from what you read. If you shorten or reword, say it is a paraphrase and drop the quotation marks. A quote is attributed to the person who said it, with their role, where and when. On a page with several speakers, check whose words they are. An interviewer's question is not the guest's statement. If you cannot find the exact words again, paraphrase.

### One home for each finding

Put each finding under the heading where it does the most work. If another heading needs it, refer to it by number ("see F007") instead of repeating it. Keep different events, people and statements as separate findings, even when one page reports them all.

### Conflicts and doubt

When sources disagree, give both with their sources and say which you trust more and why. Leave genuine uncertainty in, stated plainly. Do not drop a finding because it is uncertain.

### The index

/outputs/dossier-index.json summarises the dossier for lists and filters. It holds:

```json
{
  "verdict": "pursue | pursue_with_conditions | deprioritise",
  "verdict_reason": "one sentence",
  "icp": [{"criterion": "as worded in the ICP", "status": "met | unmet | unknown", "findings": ["F003"]}],
  "incumbent": {"name": "vendor or in-house, or null", "findings": ["F011"]},
  "size": {"value": "as reported", "findings": ["F002"]},
  "region": {"value": "as reported", "findings": ["F002"]},
  "key_facts": [{"finding": "F007", "why": "one sentence on why it matters for this seller"}]
}
```

List up to ten key facts, most important first: the facts a rep would most need to know about this account. Every number in the index must be a finding in the dossier.

### On a continuation

Read your last committed dossier and keep working from it. Do not start a new one.

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
