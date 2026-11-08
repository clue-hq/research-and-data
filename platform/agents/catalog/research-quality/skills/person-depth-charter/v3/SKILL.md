---
schema_version: '1'
kind: skill
name: person-depth-charter
version: v3
roles:
- account_research
readiness_requirements: []
tools: []
summary: Complete explicit person research questions to carry into the initial Exa
  assignment.
framework: deepagents
framework_version: '>=0.6,<0.7'
---

# Person-depth Exa assignment

SUBJECT: {person_name}; known aliases: {known_aliases_or_none_supplied}.
Selected profile: {profile_url_if_available}.
Source-reported role and company: {title}, {company_name} ({company_domain}).
Known career and location context: {relevant_prior_employers_and_location_with_uncertainty}.
Research date: {research_date}. Recent-activity window: {nine_month_window_start}–{research_date}.

PURPOSE AND CONTEXT
{Briefly explain the selected seller offering, the account situation, why this person was selected,
and the account agent's substantive research questions. Distinguish observations from hypotheses.
Give Exa the necessary context here: it cannot open our internal brief or document references.
Do not ask for a qualification verdict, committee-role assignment or recommendation to buy.}

Research this already-selected individual deeply, both professionally and as a person. Seller
context guides some questions; it does not restrict the investigation to work relevant to that
seller. Use the nine-month window for recent activity. Older interviews, interests and
accomplishments remain relevant; date them accurately.

Person research is not a resume. Reading out someone's profile, job history or school is not
research. Titles, tenure and what they "own" are the least valuable findings you can produce.

Produce a detailed Markdown dossier covering the following sections and explicit subquestions.
Keep the research specific. Preserve partial answers and useful unexpected discoveries. When
material is unavailable, say what was not found rather than inventing an answer. Do not repeatedly
bury supported findings under caveats: collect remaining gaps in the final section.

## 1. Voice — how they think, in their own words

- LinkedIn comes first: every post they wrote, every article, every repost with their own comment,
  every comment on someone else's post, and their About text. A like is not their own words, so it never counts as their voice. But record a like or repost of the seller's content, a competitor's content, or a post about the problem the seller solves. It shows what catches their attention. Cite the liked post's URL and say that it was a like. Cite the post's
  own URL; the profile URL is only for plain profile facts. If you saw a post only in their profile's activity, search its words to find its own URL before you save the finding. If you can't find it, say in the finding that it was seen in their profile activity and that its own URL was not found.
- Seek substantive verbatim quotations from long-form material as well: podcasts, webinars, talks,
  interviews, AMAs or authored articles.
- For each quotation give speaker/author, source title or show, URL, date when known, and a
  timestamp when supplied by the transcript or recording evidence. Never invent timing.
- Prefer passages revealing reasoning, tradeoffs, priorities, working methods, lessons or
  frustrations over company boilerplate. Include relevant context so the meaning survives.
- If no substantial long-form voice is located, say so and preserve useful shorter first-person
  posts separately. A press-release quote is a press quote, not evidence of a long-form interview.
- Do not attribute a host's question, colleague's words, company repost or anonymous quotation
  to this person. If attribution remains uncertain, describe the passage and the uncertainty.

## 2. What they are dealing with now
- The problems they are dealing with, what they are building, changing, hiring for or worried about,
  preferably in their own words.

- Dated developments in the specified nine-month window: appointments, promotions, departures,
  team building, hiring statements, new programs, public priorities, publications, awards or other
  meaningful activity. Separate announcements, intentions, open requisitions and completed events.
- Explain what changed and who said so. Distinguish publication/event dates from crawl dates.
  Label older material used for context rather than presenting it as a current development.
- Preserve public professional disagreements or contrary reporting relevant to the person and
  their work, with attribution and any response. Do not present an allegation as a settled fact.

## 3. Professional identity, judgment and evaluation methods
- What energises them at work and how they talk about their teams, in their own words.

- What they are visibly proud of, including specific accomplishments and their explanation of
  what mattered; quote them where available. Attribute claimed results and distinguish team credit.
- Stated pet peeves, frustrations and things they say are broken. What have they tried to change?
- How they assess vendors, tools, partners or technology; evaluation criteria, tradeoffs, pilot
  success/failure, rollout lessons and practical constraints they have actually described.
- Tools or approaches they publicly praise, criticize, use or recommend. Preserve the relevant
  employer and time period. Prior experience does not establish the current company's stack.
- Working methods, collaboration, decision-making and stated success metrics. Preserve examples
  that reveal their professional perspective without inventing a psychological profile.
- Investigate the work named in the assignment, but do not turn general interest in AI, hiring,
  a title or a workflow into proof of purchasing authority or purchase intent.

## 4. What the account already has
- In the account's own statements and in this person's About text and posts: what is already in
  place of what the seller sells, delivered programs, tools and controls.
- Any sign that the account is already the seller's customer.

## 5. Public writing, appearances and source leads

- Authored articles, personal sites, blogs, newsletters, Substack/Medium posts, interviews, AMAs,
  podcasts, webinars, conference panels, keynotes and videos. Include title, venue/show,
  publisher, date and URL where available; identify the substantive sources among the results.
- Work out where people in this industry and role speak: trade press, podcasts, conferences,
  webinars, vendor case studies that quote them, local press, earlier employers' sites,
  universities and associations.
- Search known aliases and relevant earlier employers, institutions, projects and communities.
  Do not require every source to mention the current employer; valuable voice often predates it.
- Distinguish authored work, first-person posts, quoted interviews, reposts, comments, company
  announcements and third-party profiles. A company recording that mentions them may not feature them.
- Preserve promising media URLs even when only the listing or show notes are accessible. State
  whether the retrieved material is a transcript, article, show notes, excerpt or listing.

## 6. Life outside work — as they themselves describe it
- Hobbies, sports, causes, volunteering, mentoring, and books and podcasts they recommend, and how
  they talk about their teams, only as they made it public themselves. Preserve their words and
  concrete details. An alma mater alone is not personal research.
- Side projects, books they wrote, newsletters and communities they run or built outside their main
  role. Follow a discovered project beyond the profile label.
- Distinguish a recommendation from a like, repost, passing mention, skills list or employer's tool
  requirement.
- Never collect family or children, health, religion, politics, finances, salary, where they live,
  legal matters or anything about someone with the same name.

## 7. Current role and career, as context
- Their current role, employer and start date, from the newest dated source. For anyone who joined
  or left in the past year, confirm where they work now from a dated source, not a data provider.
- What they personally own: functions, teams, workflows, programs and decisions, where described.
  Separate ownership from collaboration or influence; a title alone is not proof.
- Their job history in brief. Give detail only where a past role bears on what the seller sells,
  with what they did there. How they explain career moves, preferably in their own words.

## 8. Distinctive findings beyond a standard profile

- Identify the strongest well-supported discovery that a basic contact-enrichment record would
  miss. Explain the concrete finding in a short paragraph with its quotation or precise evidence
  and URL. Do not manufacture novelty or claim no one else could have discovered it.
- Keep other useful distinctive discoveries too: an unexpected project, accomplishment,
  formative experience, personal interest, working method or revealing account of a decision.
- Investigate leads that emerge even when they have no obvious seller connection. If the public
  material remains thin, state that limitation and the channels actually checked.

## 9. Gaps, conflicts and same-name sources encountered

- What could not be reached: what was wanted, the routes tried, why each failed and what was done
  instead. Say so when little LinkedIn activity was found, so thin results are not read as silence.
- Categories still unanswered, partial answers, inaccessible material and useful next leads.
  Distinguish "not found in the checked sources" from "not searched" and "could not access."
  Name only channels actually checked; absence in this research is not proof of nonexistence.
- Conflicting dates, responsibilities or other accounts, with source URLs and what each says.
  Retain supported detail while leaving unresolved questions explicit.
- List any sources actually encountered that concern a different person of the same name,
  with URLs and the relevant distinction. Mark uncertain matches honestly. Do not invent a
  namesake list or require independent employment/location proof before returning the dossier.

KNOWN FINDINGS AND SOURCE LEADS — extend, update or challenge; do not merely repeat
{Relevant established findings, dates, attribution and public URLs from the account brief and
acquired sources. Mark excerpts as excerpts, and distinguish observations from the parent's
interpretations. Include known aliases and prior-employer leads only when supplied or discovered.}

KNOWN MEDIA AND WRITING
{Relevant article, post, podcast, talk or video URLs and what is already available: transcript,
show notes, indexed text, listing, or inaccessible. Include useful passages when needed; do not
imply Exa can open our internal artifact paths. Say when no such leads are available.}

PERSON-SPECIFIC QUESTIONS
{A few focused questions arising from this person's brief and available evidence. Integrate
overlapping questions once. Keep the full charter above even when the brief emphasizes one area.}

KNOWN SAME-NAME EXCLUSIONS
{Only actual exclusions supplied or encountered, with reasons/URLs where known; otherwise none supplied.}

OUTPUT EXPECTATIONS
Place source URLs beside the findings they support; use exact quotations where meaningful and
paraphrases outside quotation marks. Keep original attribution, dates, career context and
uncertainty. Never splice separate passages into a purportedly verbatim quote. Review retrieved
source material for useful details omitted from the draft before declaring a category empty.
Return research, not cold-approach openers, outreach copy, claim-field classification, page
synthesis, seller-fit scoring or a purchasing verdict. Do not invent facts, sources or quotations.
