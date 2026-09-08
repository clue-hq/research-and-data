# ARV2 R3 — the committee step and the person agent's content, substance for founder review (2026-09-09, rev 1)

**Status: DRAFT FOR REVIEW — nothing here is a catalog file yet.** Per the skill-authoring rule, the
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
- **Field catalog.** The `contact.*` professional layer (title, headline, job function, level, location,
  `reports_to`, `x_url`, badges, network statistics) and the `contact.facet.*` personal layer (`hooks`,
  `openers`, `voice_quote`, `self_summary`, `hobby`, `other_roles`, `conference_talk`, `recent_award`,
  `certifications`, `stated_skills`, `education_highschool`, `best_channel`, `excluded_lookalike`,
  `recent_post`). Every facet row carries a `use_class_hint` and a shorter TTL already; the R2
  follow-ups make each field's shape visible to the agent at write time.

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
   `contact.email` claim with `use_class=professional-public`, `identity_binding=strong`, and the export
   call as its source. No email is ever synthesised; an export that returns nothing is an honest empty.
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
   post — and never searched for or inferred from any other source. (See §7 open question 1 on whether a
   self-announced milestone may be an opener.)
7. **Do not write "likely", "probably", "appears to" in place of evidence.** NOT FOUND, with the channels
   checked, is the answer.

## 3. `dossier.md` — the person dossier skill

### 3.1 The ladder, with what each rung is for

Free-first, then the sweep, then one deep call, then the two narrow follow-ups. Costs from the ten-person
PoC run (`PERSON-DEPTH-REPORT.md` §4–5).

1. **Read what the account job left** — the committee claim, `confirmed_by`, the account's own claims
   (the "already established" block, compacted per the R2 follow-ups). The person's LinkedIn page via Exa
   contents (indexed text; LinkedIn-native video is never fetched).
2. **`lookup_person`** — the AI Ark record and email export (§1.2). Deterministic claims land in code.
3. **The trimmed sweep — six angles, unrestricted queries, name-quoted and context-rich.** From §5a, in
   the order they earned their keep: (A12) *prior employer + long-form voice* — the best angle, run first;
   (A1) `"name" podcast interview guest`; (A4) authored articles / bylines; (A6) university / alumni —
   delivered alma mater 10/10, and Tyler Chonoles's whole life-outside-work profile came from a college
   golf roster; (A10) volunteer / board / community, down-weighted; (A11) hometown / local press,
   down-weighted. **Cut** (zero unique URLs in ten people): domain-restricted podcast directories, video
   sites, Substack/Medium, X/Bluesky/Reddit; awards lists. `includeDomains` is a trap: it forces a
   same-name stranger. Personal site / GitHub folds into A12.
4. **One deep call** (`research_deep`, report mode) with the charter in §3.2 and the known sources and
   media listed first ("ALREADY-KNOWN SOURCES — read these FIRST"). Charter at the **front** of the query:
   the PoC saw a silent truncation when it sat behind a long preamble. The thin-response guard already
   exists (results < 12 or cost < $0.018 → retry once).
5. **Media, where it exists (on by default).** Every YouTube URL through Exa contents first (the ASR
   transcript for ~$0.001–0.004, no key); Gemini for MP3 audio and timestamps; **verify who speaks**
   before quoting (`speaker_unverified` already exists); LinkedIn-native and X-native video never fetched.
   `read_media_feeds(alternate_urls=[…])` from the R2 follow-ups.
6. **Structuring** — one broad `structure_material(subject_kind="person")` against the contact catalog,
   then **one narrow `unique_insight` call** ("the ONE thing a generic enrichment tool would never
   surface") — $0.0018 each in the PoC, hit rate 3/10 → 10/10; model conservatism, not missing data.
   Never let one broad extraction decide whether something exists.
7. **Finalize** — the person receipt: depth summary, the not-found list with channels checked, the
   same-name log, three openers.

### 3.2 The person charter — ten sections (the two PoC charters merged)

`step8` (professional, eight sections) and `p3_deep` (personal, eight sections) overlap on identity,
career, education, writing/talks, how they buy, hooks and openers; they differ in that `step8` has *what
they own today* and `p3_deep` has *life outside work*, *voice*, *unique insight*, *what we could not
find* and the *same-name log*. Merged:

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
  question. It writes to a registered field of its own, proposed as `contact.facet.unique_insight`
  (string, `use_class_hint=personal-public-non-sensitive`, TTL 75d): a new pack row shipped with its
  data migration (the R2-close lesson: a pack-row change always ships with its migration). See §7
  question 2 for the alternative of folding it into `self_summary`.
- `voice_quote` carries `media_url` and `timestamp` as first-class sub-fields (PoC §5d); the registered
  object already has the shape — the structuring prompt must ask for the timestamp explicitly.
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
person claim, logged per action, nothing dropped whole:

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
| `person_not_admitted` | `structure_material(subject_kind="person")` for a subject with no contact entity | Confirm the member first (`lookup_person`); a vacant seat is not a person |

The tool table gains `lookup_person`, `unique_insight`, and the `alternate_urls` argument on media.

## 7. What still needs the founder's word before the files are written

1. **Self-announced family milestones as openers.** The charter allows recording a person's own wedding
   / new-baby / relocation post as biography. May an opener use one (e.g. congratulations on a new
   role, yes; on a baby, probably not)? Recommendation: **new-job and relocation posts may be hooks;
   wedding and baby posts are biography only, `outreach_safe=false`.**
2. **`contact.facet.unique_insight` as a new registered field** (with its migration) vs. folding the
   insight into `self_summary`. Recommendation: **its own field** — the display treats it as the
   headline of the contact page, and the PoC scored depth on it.
3. **Default `committee_cap`** for the fan-out. R2's launches used 5; the PoC committees were 3–6.
   Recommendation: **5**, human-adjustable per launch.
4. **Media on by default — bound it.** Ruling is on by default; proposal: at most **two media items per
   person** and the existing per-job media-seconds ceiling; more on demand.
5. **Cost to expect per person, honestly.** PoC provider spend was $0.07–0.10 (trimmed sweep + deep +
   structuring + media where present) plus ~0.5 AI Ark credit per lookup and the email-export credit
   (to measure on the first live person). The **model spend** the R2 re-run revealed (~7¢ per round) will
   dominate: a person agent at 6–10 rounds is **$0.40–0.70 of model spend**, so ≈ $0.50–0.80 per person
   all-in before AI Ark credits. Ten people ≈ $6–8 + ~7 credits. Say now if that changes the cap.
6. **The `reports_to` field** — derive from ATS reporting lines and the person's own statements only
   (never inferred from titles). Confirm that is the rule.
7. **Answer-key measurement** — extend `scripts/arv2_answer_key_recall.py` to the ten people
   (`contact.*` / `contact.facet.*` keys, same leaf-value grading). Recommendation: yes, in the R3 plan,
   measured on the first live ten-person run, which is also where the R2 follow-ups get measured.

## 8. What R3 does not do

No contact-level display work beyond the D2 contact page that exists; no discovery (R4); no change to the
account agent beyond the committee step's confirmation check; the ten answer-key people and the two
committees are the whole scope. The person deep call stays in report mode (Exa experiment). The
`claims_people.json` answer key remains the truth the run is graded against.
