# ARV2 R3 — the committee step and the person agent's content, substance for founder review (2026-09-09, rev 2)

**Status: SUBSTANCE APPROVED 2026-09-09 (every §7 item ruled; see §7) — nothing here is a catalog file
yet; the R3 plan writes the files verbatim from this document.**

**Rev 2 (2026-09-09) — the founder's rulings on §7, and the dummy-frontend walk.** (1) Self-announced
new-job and relocation posts may be hooks; wedding and baby posts are biography only, `outreach_safe=false`.
(2) **No new field for the unique insight** — the live contact page (walked at
`/accounts/zafran-security/contacts/nick-fisher` and read in the frontend's own code) has no insight slot;
personal facts reach the page only as items the display composes from the section recipes' allowed
fields. The narrow follow-up therefore writes the fact it finds into the **existing** facet field it
actually is (a hobby, a publication, a talk, a quote) at **priority 1**, with a store-only write marker
`unique_insight: true` for grading. Nothing changes in the frontend. (3) `committee_cap` default 5. (4)
Media on by default, at most **3 items per person**, as the setting `CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS`
(default 3, in `.env.example`). (5) Cost estimate accepted; no cap change. (6) `reports_to` only from ATS
reporting lines and the person's own statements. (7) Recall script extended to the ten answer-key people,
measured on the first live ten-person run. Also in rev 2: §3.1–§3.3 carry no references to documents
outside the agent's own catalog and context (skill text names only tools and things the agent can see;
provenance sits in founder-only notes), and §0 lists the exact fields the two live pages read.

Per the skill-authoring rule, the
substance of every agent-facing file is put in front of the founder and discussed before any
`platform/agents/catalog/entity-research/arv2-person/v1/` file is written. Once approved, an Opus
implementer writes the files verbatim from this document, the reviewer (Fable) checks them against it,
and the R3 plan's composition sha-pins the profile. This is the same procedure S7 followed for the account
agent (`2026-09-07-arv2-s7-agent-content-substance.md`), and the account agent's constitution, audit
skill and manual are the base this document only states **deltas** against.

**Rulings already taken (founder, 2026-09-08) and honoured here:** every confirmed committee member gets a
person agent, up to `committee_cap`; a human can launch research for any particular contact on demand;
email export for every member; media per person on by default. **Settled by the Exa experiment
(2026-09-08):** the person deep call stays in report mode — the claims-shaped schema cut assertions to a
third and packed several facts per quote, which would hit a quote-heavy person dossier hardest.

Sources (read in full): master plan §9 Track R row R3 and Appendix A; the two PoC person charters —
`.context/arv2-clue-sample-v3/step8_person_deep.py` (professional profile, eight sections, the
compliance charter) and `.context/arv2-person-depth/p3_deep.py` (personal dossier, eight sections, the
sensitivity floor and the `[ORIGIN - NOT AN OUTREACH HOOK]` rule); `PERSON-DEPTH-REPORT.md` §2 (the ten
people), §4 (cost), §5 (which angles earned their cost, media, what to add to the charter permanently,
the two operational findings); the registered `contact.*` / `contact.facet.*` fields in
`platform/api/clue_api/arv2/catalog_seed.py`; the R2 re-run evidence (`.context/arv2-r2-acceptance/rerun/`)
for what the shared write path now does.

## 0. What the person agent is, mechanically

The **same** runtime as the account agent, pointed at a different subject: one LangGraph agent per
confirmed committee member on the existing fleet, the same `ToolRuntime` (one `ProviderCaller` per hop,
buffered sinks, the halt latch, per-provider semaphores, refusal memory, `write_each`), the same
`LenientClaimWriter` as the one gate, the same ledger rows including model spend. What changes:

- **Subject.** `JobScope` gains `subject_kind: account | person` and, for a person, the contact entity id,
  the confirmed name / title / LinkedIn URL / current employer, and the **verified employment history**
  (the identity lock the PoC used to rule out same-name people). The account it belongs to stays on the
  scope so account context (ICP, persona map, the account's own claims) is readable.
- **Job rows.** One `arv2_research_job` per person, `subject_type='person'`, `subject_entity_id` = the
  contact entity, under the same run as the account job that produced it (or a run of its own when
  launched on demand). No new tables; one migration adds the two columns and relaxes the account-id
  constraint.
- **Tools.** The twelve account tools, with `structure_material(subject_kind="person")` admitted (it is
  refused today), `lookup_people` replaced by `lookup_person` (name-scoped AI Ark enrichment + the
  **email export** for the confirmed member), `read_media_feeds` as improved in the R2 follow-ups
  (alternates), and one new narrow tool, `unique_insight` (§3.3). `research_deep` stays report mode.
- **Catalog.** Its own folder `entity-research/arv2-person/v1/{profile,prompt,dossier,audit,manual}.md`.
  The profile is sha-pinned as the launch authorization; the person launch records its digest.
- **Compliance pass in code**, after structuring, before the claims are readable (§5). The prompt states
  the floor too, but the code decides.
- **Field catalog — exactly what the two live pages read (rev 2, from the frontend walk).** The person
  agent's catalog is the union of the fields the contact page's deterministic slots and the two pages'
  section recipes consume; nothing else is written, and no new field is registered.
  *Deterministic slots on the contact page:* `contact.current_title` (Title), `contact.persona` and
  `contact.role_on_committee` (persona chip, influence, "why they matter" rationale), `core.work_email`
  (Email — the export claim is written **here**, not to a new field), `contact.linkedin_url`,
  `contact.network_statistics` (followers) and `contact.member_badges` (creator badge),
  `contact.current_location`, `contact.facet.best_channel`, `contact.facet.alma_mater` (Education),
  `contact.facet.career_history` (tenure: earliest start at the current employer), `contact.reports_to`
  (direct reports), `contact.headline`, `contact.x_url`.
  *Facets the section recipes compose into items:* `contact.facet.hobby`, `voice_quote` (with
  `media_url` + `media_timestamp` in the value so the Sources row shows the timestamp), `recent_post`,
  `publications`, `career_history`, `hooks`, `openers`, `stated_interests`, `communication_style`,
  `conference_talk`, `public_appearances`, `certifications`, `self_summary`; plus the R2 account fields
  the contact recipes also read (requisitions, tooling, pain, outcomes, ABM maturity).
  *Registered but not read by any page* (still written when found, for the answer key and the store):
  `other_roles`, `recent_award`, `stated_skills`, `education_highschool`, `excluded_lookalike`.
  Note: `alma_mater`, `career_history`, `publications`, `public_appearances`, `stated_interests` and
  `communication_style` are registered by the older profiling pack, not the ARV2 pack; the R3 plan names
  them in the person catalog explicitly so the agent can write them. Every facet row carries a
  `use_class_hint` and a shorter TTL already; the R2 follow-ups make each field's shape visible to the
  agent at write time.

## 1. The committee step (before any person agent runs)

Owned by the **account** agent's finalization today (`account.committee_candidate` claims: name, title,
persona, LinkedIn, `confirmed_by`, or a vacant seat). R3 adds the step that turns a candidate into a
subject:

1. **Web-confirm first, provider second** (master plan). A candidate is confirmed only on a non-provider
   URL — team page, funding announcement, the person's own LinkedIn via Exa search, an ATS reporting
   line. `confirmed_by` is already required for a named candidate; R3 adds the **current-employer
   exact-match** check against the account (the same-name trap) before any spend.
2. **`lookup_person`** — one AI Ark name-scoped call per confirmed member, then the **email export** for
   every member (ruling). The provider record's deterministic fields (title, headline, location, badges,
   network statistics, employment history) are mapped **in code** to `contact.*` claims, the way the AI
   Ark company record is mapped to `core.*` today, each citing the record's JSON path. Email is a
   `core.work_email` claim (the field the contact page's Email slot reads) with
   `use_class=professional-public`, `identity_binding=strong`, and the export call as its source. No
   email is ever synthesised; an export that returns nothing is an honest empty.
3. **The contact entity is created here** (`insert_contact_entity`, workspace-scoped, keyed to the
   account), with the employment history kept as the lock. A vacant seat creates no contact and no job.
4. **Fan-out.** For every confirmed member up to `committee_cap`, one person job is created and enqueued
   after commit (the R2 launch pattern). **On demand:** the launch CLI and the toolbelt tool accept
   `--contacts <ids>` / `contact_entity_ids[]`, so a human can research any particular contact — a member
   the cap excluded, or a contact confirmed later — without re-running the account.

## 2. `prompt.md` — deltas to the constitution

The account constitution (twelve rules: one subject, evidence law, NOT FOUND is correct, company-claim vs
third-party, never invent a person, primary sources first, contested items CONFIRMED/DENIED/UNRESOLVED,
lenient gates, negatives born unsafe, the refusal contract, the stop policy, finalize) carries over. Person
deltas, each from a PoC rule the ten-person run needed:

1. **Target lock by employment history.** "The subject is exactly this person: `{name}`, `{title}` at
   `{company}`, LinkedIn `{url}`, known roles `{priors}`. Anyone with the same or a similar name whose
   history does not match is a different person. Name every same-name person you met and discarded, and
   why." The discarded ones become `contact.facet.excluded_lookalike` claims — the lock is *proven*, not
   assumed.
2. **Never attribute a colleague's or a company account's words to the person.** A company post that
   merely mentions them is a company source about them, not their voice. A media item named after the
   company is not a personal voice source until the transcript proves who speaks (two of ten PoC media
   items were colleagues).
3. **Prefer the person's own words** — posts, talks, interviews, bylines — over third-party profiles;
   aggregator and people-directory pages are the weakest evidence and are labelled as such.
4. **The sensitivity floor, stated plainly.** Do not record, quote, hint at or infer: health or medical
   information; religion or faith; political opinions, party affiliation or activism; sexuality or gender
   identity; family tragedy, bereavement, divorce or illness; anything about children or other minors;
   trade-union membership; criminal or legal matters; home address, personal phone, personal email. If a
   source contains these, ignore that part. (The code pass in §5 enforces this regardless.)
5. **Allowed background, with one tag.** Military or intelligence service, competitive sport and the
   arts are background. A national-origin or migration story the person told **first-person** may be
   recorded as biography, tagged `[ORIGIN - NOT AN OUTREACH HOOK]`, and is born `outreach_safe=false`.
6. **Family milestones only when self-announced** — their own wedding, relocation, new-job or new-baby
   post — and never searched for or inferred from any other source. A self-announced **new job or
   relocation** may be a hook. A **wedding or a baby** is biography only: recorded, born
   `outreach_safe=false`, never in a hook or an opener (founder ruling 2026-09-09).
7. **Do not write "likely", "probably", "appears to" in place of evidence.** NOT FOUND, with the channels
   checked, is the answer.

## 3. `dossier.md` — the person dossier skill

### 3.1 The ladder, with what each rung is for

**What this section is.** The ladder is the order in which the person agent does its work: the free and
already-known sources first, then the paid searches, then the one expensive deep call, then the two
narrow follow-ups, then structuring and the receipt. It is the skill's spine; the charter in §3.2 is
*what to find*, the ladder is *where to look, in what order, and when to stop*. Written as the agent
reads it — it names only tools the agent has and things the agent can see. Nothing below points at a
document outside the agent's own catalog and context.

1. **Start from what the account job already found.** Read the committee claim that named this
   person and the URL that confirmed them, then the account's own claims (the "already established"
   block in your context). Read the person's LinkedIn page as indexed text through `fetch_page`. Never
   fetch LinkedIn-native video.
2. **`lookup_person`.** One provider record for this exact person, plus the email export. Every field
   the record answers is written as a claim in code, citing the record — you do not retype it.
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
4. **One deep call** (`research_deep`, report mode) with the charter in §3.2. Put the charter at the
   **front** of the query, then the sources and media you already know are about this person under the
   heading "ALREADY-KNOWN SOURCES — read these FIRST", then the probes. A long preamble before the
   charter can make the call answer only part of it. If the report comes back thin, the tool retries
   once on its own; you do not.
5. **Media, where it exists.** Media is on by default, at most three items per person (the operator can
   change the number in the environment; the tool refuses `media_cap_reached` past it). For a YouTube appearance,
   `read_media_feeds` reads the indexed transcript first and only transcribes audio when there is no
   indexed text. Give every other place the same appearance may load from as `alternate_urls`. A quote
   from a transcript is usable only when the speaker is verified as this person; a media item named
   after the company is not the person's voice until the transcript proves who speaks. Never fetch
   LinkedIn-native or X-native video.
6. **Structuring, then the narrow follow-up.** One broad `structure_material(subject_kind="person")`
   over everything retrieved, against the contact catalog. Then one `unique_insight` call asking a
   single question: the one thing about this person a generic enrichment tool would never surface. Ask
   it even when the broad pass returned nothing distinctive — a broad extraction routinely answers "thin
   footprint" for a person whose material plainly holds a published book or a competition win. Never let
   one broad extraction decide whether something exists.
7. **Finalize.** The receipt: the depth summary, the not-found list with the channels you checked, the
   same-name log, and the three openers.

**Provenance, for the founder — not part of the skill text.** The order and the cuts in rung 3 come from
the ten-person depth run recorded under `.context/arv2-person-depth/` (`PERSON-DEPTH-REPORT.md` §4–5):
searches 1–6 above are its angles A12, A1, A4, A6, A10, A11; the cut angles (A2, A3, A5, A7, A9)
found zero unique URLs across ten people and cost 27% of the run; the university angle delivered the
alma mater 10/10. The "charter at the front" rule comes from one silently truncated deep call in that
run. The narrow `unique_insight` call took the hit rate from 3/10 to 10/10 at $0.0018 each. The R2
follow-ups slice (`2026-09-09-arv2-r2-followups.md`) supplies the compacted established block and the
media `alternate_urls` the ladder relies on.

### 3.2 The person charter — ten sections

The charter is the list of what the deep call must find about the person, in numbered sections it must
answer in order, writing "NOT FOUND" for anything it cannot evidence. It is skill text: it names no
document outside the agent's context.

*Provenance, for the founder — not part of the skill text:* the ten sections merge the two
proof-of-concept person charters in `.context/arv2-clue-sample-v3/step8_person_deep.py` (professional,
eight sections) and `.context/arv2-person-depth/p3_deep.py` (personal, eight sections). They overlap on
identity, career, education, writing and talks, how they buy, hooks and openers; the first adds *what
they own today*, the second adds *life outside work*, *voice*, *unique insight*, *what we could not
find* and the *same-name log*.

1. **Identity confirmation and same-name log** — the primary sources tying this exact person to this
   company and title, with dates; every same-name person encountered, the URL, and how they were ruled
   out. (Both charters; the log is what proves the lock held.)
2. **Career and what they own today** — every role with organisation, title, dates and responsibility;
   anything to do with outbound, demand generation, ABM, target-list building, sales development or GTM
   tooling highlighted; the current role's scope, who reports to them, which open requisitions report
   into them, what they have said publicly about what they are building.
3. **Background** — hometown; alma mater(s) with degree, subject, years, societies, teams, awards; first
   jobs and how they got into the field, in their own words; military / competitive-sport / arts
   background; languages; high school when self-published.
4. **Public writing, talks and podcasts** — every post, article, byline, webinar, panel or podcast
   appearance with title, venue, date, URL; the most substantive one quoted.
5. **Life outside work — only as they state it themselves** — hobbies and sports they posted about;
   pets; self-announced milestones; causes, volunteering, boards, mentoring, alumni service; side
   projects, newsletters, communities; books, podcasts, tools and people they publicly recommend.
6. **Voice — three to five verbatim quotes from long-form material** — podcasts, webinars, talks,
   interviews, AMAs, authored articles; each with source, URL, date, and timestamp for audio/video;
   quotes that reveal how they think, not company boilerplate; if the only long-form material is a
   company press quote, say so.
7. **Professional identity and how they buy** — what they personally own; what they are visibly proud
   of (quoted); stated pet peeves and things they say are broken; how they evaluate and buy software;
   tools publicly praised or criticised; methodologies; stated metrics; communication style (quoted).
8. **Unique insight** — the one thing a generic enrichment tool would never surface, one paragraph,
   quote-backed; else "NOT FOUND — thin public footprint" naming the channels checked.
9. **Three grounded openers** — each: the one-sentence opener, the specific hook, the verbatim quote
   behind it, the URL. No generic openers, no flattery, nothing tagged origin.
10. **What we could not find** — the categories that came back empty and the source types checked.

The compliance charter and sensitivity floor sit in the deep call's **system prompt** (as `LOCK_TEMPLATE`
+ `EVIDENCE_RULES` do for the account), not in the charter body.

### 3.3 The narrow follow-up, and structuring

- `unique_insight(subject)` — one structuring-client call with the person's material and the single
  question: the one thing about this person a generic enrichment tool would never surface. **It
  registers no field.** The fact it finds is written to the existing facet field it actually is — a
  `hobby`, a `publication`, a `conference_talk`, an `other_roles` seat, a `voice_quote` — at
  **priority 1**, so the display ranks it first when it composes the openers, and with the write marker
  `unique_insight: true`, which lives on the claim row in the store only (the read surface never serves
  markers; the frontend does not change). The recall measurement and the receipt read that marker to say
  whether the insight was found. If nothing distinctive exists, the receipt records "thin public
  footprint" with the channels checked and no claim is written. (Founder ruling 2026-09-09, from the
  dummy-frontend walk: the live contact page composes personal facts into openers and angles from the
  section recipes' allowed fields and has no insight slot; a `unique_insight` field would be stored and
  never shown.)
- `voice_quote` carries `media_url` and `media_timestamp` inside its value; the registered object already
  has the shape, the display's Sources row shows the timestamp when the value carries it, and the
  structuring prompt must ask for the timestamp explicitly.
- `hooks` and `openers` stay list fields; every opener names its hook and the hook names its quote — the
  structuring pass writes them together, and an opener whose hook has no quote is dropped, never written.

## 4. `audit.md` — deltas

Same fabrication audit as the account (quote on the cited page; verdict + reason), plus:

- **Speaker attribution audit** for every `voice_quote` from media: the transcript segment must be
  attributed to the subject (the existing `verify_speaker` verdict), else the quote is recorded
  `speaker_unverified` and barred from hooks and openers.
- **Attribution audit** for every quote: a quote lifted from a company post about the person is
  `second_hand_from_company` (a new reason beside `second_hand_from_report`), not the person's voice.
- **Lock audit**: the `excluded_lookalike` log must be non-empty or state "no same-name sources met".

## 5. The coded compliance pass (after structuring, before readability)

Master plan R3, exit gate wording, and PoC §5d ("put the floor in code"): a deterministic pass over every
person claim, logged per action. Personal contact details are dropped whole; a value that is *entirely*
sensitive is dropped, because redaction would leave nothing; everything else is redacted by sentence and
marked:

1. **Minors redaction** — any reference to children / minors in a value or quote is redacted from the
   value even when self-published; the claim keeps a `redacted: minors` marker.
2. **Origin / nationality / faith** — recorded as biography only, `outreach_safe=false`, barred from
   `hooks` / `openers` (an opener that rests on one is dropped with a marker).
3. **The sensitivity floor** — health, politics, sexuality, family tragedy, union, criminal: a value
   matching the floor is redacted with a `redacted: <category>` marker; the claim is not deleted (the
   record that something was found and removed is itself the audit).
4. **Unevidenced rows** — a row with no quote or no URL is marked `unevidenced`; purged only when
   `CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=true` (default false, in `.env.example`).
5. **Personal contact details** — home address, personal phone, personal email never written (the
   professional email from the export is the only email).
6. **Every action logged** to the job receipt (`compliance_log`), so the display can say what was removed
   and why without showing it.

Jurisdiction stays a per-client switch; v1 is the strict posture for everyone.

## 6. `manual.md` — deltas

Refusal codes the person driver adds or changes (reaction in the agent's terms):

| Code | When | Reaction |
| --- | --- | --- |
| `subject_lock_failed` | The confirmed employer / history does not match the account (same-name trap at launch) | This candidate is not the person; record the lookalike; no person job |
| `email_export_empty` | The provider export returned no email | Record no email; the member is still researched |
| `speaker_unverified` (existing) | Transcript speaker is not the subject | Quote nothing from it; record the item unattributed |
| `insight_not_found` | `unique_insight` found nothing beyond a standard profile | Record "thin public footprint" with channels checked; move on |
| `media_cap_reached` | This person already has the configured number of media items (default 3) | Media for this person is complete; do not call `read_media_feeds` again for them |
| `person_not_admitted` | `structure_material(subject_kind="person")` for a subject with no contact entity | Confirm the member first (`lookup_person`); a vacant seat is not a person |

The tool table gains `lookup_person`, `unique_insight`, and the `alternate_urls` argument on media.

## 7. Founder rulings (2026-09-09) — all seven items closed

1. **Self-announced family milestones.** RULED: new-job and relocation posts may be hooks; wedding and
   baby posts are biography only, `outreach_safe=false`, never in a hook or an opener. (§2 item 6.)
2. **Unique insight.** RULED from the dummy-frontend walk: **no new field**. The narrow follow-up writes the
   fact into the existing facet it is, at priority 1, with the store-only marker `unique_insight: true`.
   `self_summary` stays the person's own words. Nothing changes in the frontend. (§3.3.)
3. **Default `committee_cap`.** RULED: 5, human-adjustable per launch.
4. **Media bound.** RULED: on by default, at most **3 items per person**, as the setting
   `CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS` (default 3, mirrored in `.env.example`), beside the existing
   per-job media-seconds ceiling. The tool refuses `media_cap_reached` past it. (§3.1 rung 5, §6.)
5. **Cost.** RULED: the estimate (≈ $0.50–0.80 per person all-in before AI Ark credits, model spend
   dominating; ten people ≈ $6–8 + ~7 credits) is accepted and changes no cap. The email-export credit is
   measured on the first live person.
6. **`reports_to`.** RULED: derived only from ATS reporting lines and the person's own statements, never
   inferred from titles.
7. **Answer-key measurement.** Accepted as recommended (the founder closed the list without objection):
   `scripts/arv2_answer_key_recall.py` is extended to the ten people (`contact.*` / `contact.facet.*`
   keys, leaf-value grading, insight presence read from the `unique_insight` marker), measured on the
   first live ten-person run, which is also where the R2 follow-ups are measured.

## 8. What R3 does not do

No contact-level display work beyond the D2 contact page that exists; no discovery (R4); no change to the
account agent beyond the committee step's confirmation check; the ten answer-key people and the two
committees are the whole scope. The person deep call stays in report mode (Exa experiment). The
`claims_people.json` answer key remains the truth the run is graded against.
