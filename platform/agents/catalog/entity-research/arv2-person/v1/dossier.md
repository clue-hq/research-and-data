name: arv2-person-dossier
version: v1

# The person dossier

## The ladder, and what each rung is for

The ladder is the order in which you do your work: the free and already-known sources first, then
the paid searches, then the one expensive deep call, then the two narrow follow-ups, then
structuring and the receipt. It is this skill's spine; the charter below is *what to find*, the
ladder is *where to look, in what order, and when to stop*.

1. **Start from what the account job already found.** Read the committee claim that named this
   person and the URL that confirmed them, then the account's own claims (the "already established"
   block in your context). Read the person's LinkedIn page as indexed text through `fetch_page`.
   Never fetch LinkedIn-native video.
2. **`lookup_person`.** One provider record for this exact person, plus the email export. Every
   field the record answers is written as a claim in code, citing the record — you do not retype it.
   The one argument is the LinkedIn URL the committee step confirmed, which is in your context. If
   the lock carries no LinkedIn URL for this person, do not guess one: skip `lookup_person`, say so
   in `not_found`, and continue the ladder.
3. **The sweep — six searches, unrestricted, each with the person's quoted name and their context.**
   Run them in this order, because it is the order in which they pay off:
   1. prior employer plus long-form voice (podcast, interview, talk) — run this one first;
   2. `"<name>" podcast interview guest`;
   3. authored articles and bylines;
   4. university and alumni pages — this is where the alma mater comes from, and sometimes a whole
      life-outside-work profile (a college team roster, a student society page);
   5. volunteering, boards, community — lower weight;
   6. hometown and local press — lower weight.
   Do **not** run domain-restricted searches (podcast directories, video sites, Substack or Medium,
   X, Bluesky, Reddit) or awards-list searches: restricting the domain forces the search engine to
   return *something* from that domain, and that something is a same-name stranger. Personal sites
   and GitHub come out of search 1 when they exist.
4. **One deep call** (`research_deep`, report mode) with the charter below. Put the charter at the
   **front** of the query, then the sources and media you already know are about this person under
   the heading "ALREADY-KNOWN SOURCES — read these FIRST", then the probes. A long preamble before
   the charter can make the call answer only part of it. If the report comes back thin, the tool
   retries once on its own; you do not.
5. **Media, where it exists.** Media is on by default, at most three items per person (the operator
   can change the number in the environment; the tool refuses `media_cap_reached` past it). For a
   YouTube appearance, `read_media_feeds` reads the indexed transcript first and only transcribes
   audio when there is no indexed text. Give every other place the same appearance may load from as
   `alternate_urls`. A quote from a transcript is usable only when the speaker is verified as this
   person; a media item named after the company is not the person's voice until the transcript
   proves who speaks. Never fetch LinkedIn-native or X-native video.
6. **Structuring, then the narrow follow-up.** One broad `structure_material(subject_kind="person")`
   over everything retrieved, against the contact catalog. Then one `unique_insight` call asking a
   single question: the one thing about this person a generic enrichment tool would never surface.
   Ask it even when the broad pass returned nothing distinctive — a broad extraction routinely
   answers "thin footprint" for a person whose material plainly holds a published book or a
   competition win. Never let one broad extraction decide whether something exists.
7. **Finalize.** The receipt: the depth summary, the not-found list with the channels you checked,
   the same-name log, and the three openers.

## The person charter — ten sections

The charter is the list of what the deep call must find about the person, in numbered sections it
must answer in order, writing "NOT FOUND" for anything it cannot evidence.

1. **Identity confirmation and same-name log** — the primary sources tying this exact person to this
   company and title, with dates; every same-name person encountered, the URL, and how they were
   ruled out. The log is what proves the lock held.
2. **Career and what they own today** — every role with organisation, title, dates and
   responsibility; anything to do with outbound, demand generation, ABM, target-list building, sales
   development or GTM tooling highlighted; the current role's scope, who reports to them, which open
   requisitions report into them, what they have said publicly about what they are building.
3. **Background** — hometown; alma mater(s) with degree, subject, years, societies, teams, awards;
   first jobs and how they got into the field, in their own words; military / competitive-sport /
   arts background; languages; high school when self-published.
4. **Public writing, talks and podcasts** — every post, article, byline, webinar, panel or podcast
   appearance with title, venue, date, URL; the most substantive one quoted.
5. **Life outside work — only as they state it themselves** — hobbies and sports they posted about;
   pets; self-announced milestones; causes, volunteering, boards, mentoring, alumni service; side
   projects, newsletters, communities; books, podcasts, tools and people they publicly recommend.
6. **Voice — three to five verbatim quotes from long-form material** — podcasts, webinars, talks,
   interviews, AMAs, authored articles; each with source, URL, date, and timestamp for audio/video;
   quotes that reveal how they think, not company boilerplate; if the only long-form material is a
   company press quote, say so.
7. **Professional identity and how they buy** — what they personally own; what they are visibly
   proud of (quoted); stated pet peeves and things they say are broken; how they evaluate and buy
   software; tools publicly praised or criticised; methodologies; stated metrics; communication
   style (quoted).
8. **Unique insight** — the one thing a generic enrichment tool would never surface, one paragraph,
   quote-backed; else "NOT FOUND — thin public footprint" naming the channels checked.
9. **Three grounded openers** — each: the one-sentence opener, the specific hook, the verbatim quote
   behind it, the URL. No generic openers, no flattery, nothing tagged origin.
10. **What we could not find** — the categories that came back empty and the source types checked.

The lock and the evidence rules ride in the deep call's **system prompt**, not in the charter body;
the tool puts them there, you do not.

## Structuring, and the narrow follow-up

0. **Give it sources, not a wall of text.** Every page, posting, report or transcript goes in as its
   own source with the URL it came from; your own reading of the material goes in `notes`. Quotes
   may only come from inside a source, and a claim cites the URL of the source its quote is actually
   in — so a quote can never end up attributed to a page that did not carry it. Nothing in `notes`
   can be quoted: it names no source, and a claim quoting it is recorded with the quote marked
   NOT FOUND.
1. `unique_insight(subject)` asks one question with the person's material behind it: the one thing
   about this person a generic enrichment tool would never surface. **It registers no field.** The
   fact it finds is written to the existing facet field it actually is — a `hobby`, a `publication`,
   a `conference_talk`, an `other_roles` seat, a `voice_quote` — at **priority 1**, so the display
   ranks it first when it composes the openers, and with the write marker `unique_insight: true`,
   which lives on the claim row in the store only. The receipt reads that marker to say whether the
   insight was found. If nothing distinctive exists, the receipt records "thin public footprint"
   with the channels checked and no claim is written.
2. `voice_quote` carries `media_url` and `media_timestamp` inside its value; the registered object
   already has the shape, and the display's Sources row shows the timestamp when the value carries
   it, so ask for the timestamp explicitly.
3. `hooks` and `openers` stay list fields; every opener names its hook and the hook names its
   quote — the structuring pass writes them together, and an opener whose hook has no quote is
   dropped, never written.
