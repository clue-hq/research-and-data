# Media and social sources: ledger

Everything we tested for finding, reading and checking what a person says in public: podcasts, videos,
LinkedIn and X. What each source costs, how well it did, the people we tried it on, and what we propose to
keep. Nothing here is built yet; every change below is waiting on a design discussion with the founder.

Started 2026-11-09. Tests ran 2026-11-08/09 unless a row says otherwise. Raw outputs are in the session
scratchpad, not in the repo.

People used as test cases are public executives: the U.S. Bank committee from rounds r40b–r42b, and the
gift pilot's recipients (`~/gift-poc`, `~/daymaker-rea`).

## 0. Decisions (founder, 2026-11-09)

1. **One shared channel** for every media and social source: podcast and video discovery, transcription,
   LinkedIn posts and video, X posts and video, handle finding. Account research, person research and the
   direct-mail (gift) research all use it. Designed with the founder and approved before any code.
2. **Delete the self-introduction speaker check** in the same change that builds the shared channel. Its
   footprint (found 2026-11-09), all of which goes or is redesigned:
   - `quality_media.py` `SpeakerIntroduction`, `TranscriptSupport.introduction` and the regex in
     `validate_transcript`, with its warning "The quoted voice is not corroborated as this person";
   - `media_types.py` the `evidence_backed` attribution value and its validator;
   - `media_claims.py` the "strong" rule that writes `attribution: evidence_backed | unverified`;
   - `quality_pages.py:211`, which refuses any contact quote from a transcript that is not `evidence_backed`
     as a primary quote, and `display/evidence.py:177`, which demotes it to a source excerpt. **So today a
     person's own words from a podcast or talk can never appear on their page as a quote.**
   - tests in `tests/arv2/test_quality_media_db.py` and `tests/arv2/test_media_research.py`.

3. **Metadata can confirm or rule out a recording, never block it (founder, 2026-11-09).** If the title,
   description, tags or links clearly name our person, that is trustworthy confirmation. A recording is out
   of scope only when its metadata clearly shows a namesake: a different person with the same name, shown
   by links or other clear proof. When the metadata is unclear, says nothing, or its proof is weak, the
   recording is not rejected: we transcribe it and the model judges from the transcript. No rule-based or
   string-matching identity checks; the model decides from what it knows about the person and the transcript.

4. **Quotes from recordings: no word matching (founder, 2026-11-09).** The agent keeps the transcript line as
   it was transcribed, as the proof, in its findings and the claim. The page writer writes the same line for
   the reader with spelling and punctuation corrected; it rewrites, it does not copy mechanically. No code
   compares the two, and no code checks the finding's line against the transcript character for character.
5. **Speaker identification uses Jev (founder, 2026-11-09).** How lines are credited to the person (by
   passage or by speaker label) is not decided yet.

**Principle (founder, 2026-11-09):** only what the person has made public. A private account gives nothing,
and we never try to get past that (no sign-in, no stealth). The treg providers read public pages logged out;
they return "private" for private accounts and charge nothing.

## 0a. What each source can be used for today

Status: **works** (tested, use it), **limited** (works with a stated limit), **untested**, **drop**.

| Job | Source | Status | Note |
|---|---|---|---|
| Find the person's X and Facebook handles | PDL person enrichment | works | All 10 X and 5 FB handles found by any route; 0 wrong; about $0.28 a match |
| Find the Instagram account | Same-handle check, logged out | limited | 5 of 6 found; gives name and post count only |
| Find personal sites and blogs | Exa search, then page fetch | works | The gift pilot's richest stories came from own sites and old blogs |
| Find podcasts by person | Podcast Index `byperson` + `byterm` | works | Free; matched every hand-found podcast for Ann and Dilip; noisy for common names |
| | Apple Podcasts search | works | Free; fills feed links |
| | Listen Notes, Podscan, Spotify, Podchaser | drop | Founder 2026-11-09: Podcast Index + Apple are enough |
| Find videos and talks by person | YouTube Data API search, quoted name | works | Free to about 100 searches a day; 5/5 Ann, 3/3 Dilip; skip personal and family channels |
| | Exa on youtube.com | limited | 4 of 5 for Ann; fallback |
| | Conference and webinar sites (RSAC, BrightTALK, ON24, Gartner) | drop | Founder 2026-11-09: a talk counts only when it is also on YouTube, LinkedIn, X or a podcast. Exa on these sites found real talks only for Rob and Karl (BrightTALK), namesakes for Kuhn and Rossmann, nothing on RSAC, ON24 or Gartner |
| Read a podcast | Publisher transcript | works | First choice |
| | Deepgram by audio link | works | About $0.0043/min, speaker labels |
| Read a YouTube video | Captions via treg | works | $0.0019; no speaker names |
| | Gemini | limited | Fallback; refused when length unknown or over budget |
| Read the person's LinkedIn posts | treg `fetchinio.linkedin.user.posts` | works | Full history; Ann 80 (8/8 hand posts) |
| | Exa on linkedin.com in date windows | limited | Fallback; coverage unknown |
| See what they liked on LinkedIn | treg `fetchinio.linkedin.user.reactions` | works | Found Kuhn's like of an Illumio VP's post |
| See their LinkedIn comments | treg `harvestapi.linkedin.user.comments` | untested | Next test |
| Find LinkedIn posts that mention them | treg LinkedIn post search | limited | Recent and popular only; namesakes |
| Read LinkedIn video (any length) | Video link from the posts tool → Deepgram | works | 52-min stream transcribed; link expires in about a week |
| | ScrapeCreators LinkedIn transcript | drop | Often unavailable |
| Read the person's X posts | TikHub timeline (treg) | works | 0.1¢ a page, about 3 s; current; depth limit and replies unknown |
| | Wayback archive + X embed | limited | Free deep history for heavy posters; gaps, slow, undocumented endpoint |
| | ScrapeCreators user posts | drop | Top-tweets sample only |
| Read X video up to 2 min | ScrapeCreators X transcript | works | $0.0019 |
| Read X video over 2 min | Tweet lookup → MP4 link → Deepgram | works | 18-min video transcribed |
| Read Instagram posts | treg `scrapecreators.instagram.user.posts` | works on public accounts | $0.0019/page, 2–6 s, next-page cursor, captions, dates, video links. Public control (garyvee) 26 posts; Dave's public @davegerhardt 27 posts (Sep 2025–Nov 2026, Exit Five content confirms him). Private accounts return "Profile is restricted", not charged |
| | treg `tikhub.x.instagram-v2-fetch-user-posts` | limited | Worked on the public control (12 posts); refused every one of our people (400, not charged) |
| Is the Instagram account private? | treg `scrapecreators.instagram.user.profile` | works | $0.0019; Rob, Nick Fisher, Lisa Kant and Ana: private. Gift-pilot people's personal accounts are mostly private, so Instagram will often give nothing |
| Read Instagram video up to 2 min | treg `scrapecreators.x.v2-instagram-media-transcript` | works | $0.0019; 117-s video gave 291 words; 279-s video refused (same 120-s limit as X) |
| Read Instagram video over 2 min | Video link from the posts tool → Deepgram | works | File downloads without sign-in; Deepgram matched the 17-s reel; long-video run not repeated (same path as X) |
| Read Facebook posts | treg `scrapecreators.x.v1-facebook-profile-posts` | works on public posts | $0.0019 a page of 3 posts, 4–12 s, cursor; text, date, reactions, comments, video file links (`sdUrl`/`hdUrl`, download without sign-in, so long video goes to Deepgram). Lisa Kant and Nick Fisher: "Profile is private", not charged. Rob: only 9 public posts in all (2012–2021; paging stopped after 3 pages, 18 s, 0.4 ¢). Brooke and Mandar: public posts, but those read were family or religious, which are off limits |
| | treg `anyapi.facebook.user.posts` | untested | Needs POST; not retried |
| Confirm the person is the speaker | – | none | Current check to be deleted; new design pending |

## 0b. Google search (checked 2026-11-09, not adopted)

- Google's own Custom Search JSON API is closed to new customers and stops working on 1 January 2027
  (developers.google.com/custom-search). There is no official whole-web Google API to build on.
- Third-party result providers (SerpApi, DataForSEO and others, reachable through treg) scrape Google. Google
  sued SerpApi in December 2025 for circumventing its SearchGuard protection (DMCA claims); reports say the
  court has since granted SerpApi's motion to dismiss. Legal risk is not settled.
- Through treg's routed `treg.google.serp.organic`, a `site:` query with a quoted name that finds nothing is
  a "miss" and falls through every provider, each billing: one call took 24–61 s and cost 1–2 ¢. The 32-search
  test was stopped part-way after about 23 ¢.
- Founder decision: no Google search.

## 1. What is wrong today

| Problem | Evidence |
|---|---|
| The agent has one media search, and it rarely uses it | `discover_media` (`media_tools.py:144`) is one Exa search (20 results, LinkedIn and X dropped). In run 4 Ann's agent never called it; most people got one call and no follow-up. |
| Podcast Index and YouTube are not tools | Podcast Index is used only inside `read_media`, to find a known YouTube video's podcast twin by show name (`media_sources.py`, `_feeds_from_directories`). The YouTube Data API is used only to read a known video's details (`youtube_details`). Neither searches by person. Provider log: run 4 had 8 Podcast Index calls and 4 YouTube calls (all inside one `read_media`) against 314 Exa searches; run 5 had none against 304. |
| The prompt says what, not how | Person prompt v30 line 28 lists where people speak and says "transcribe every recording"; nothing says how to find a recording. Tool descriptions are one line. |
| Generic search finds namesakes | Exa's media candidates were mostly other people with the same name (for example a 57-minute golf podcast for the wrong Dave Kuhn). Ann's talks were never found. |
| LinkedIn and X video are never read | `read_media` refuses them ("LinkedIn and X video is never read"). |
| Speaker check is unfit | `validate_transcript` (`quality_media.py:169`) credits a quote to the person only if the agent points to a passage where they say "I am / I'm / my name is <exact full name>" in the same speaker label. Hosts usually introduce guests, and transcription misspells names (Deepgram wrote "Venkatachary"), so real recordings come out "unverified". **Founder ruling 2026-11-09: discard this check entirely; redesign it together before any code.** |
| Social coverage is hit-and-miss | The only LinkedIn route is `search_web` on linkedin.com in monthly windows (Exa). Runs cited Ann's posts 26 and 18 times, Boerio 39, several people 0–7; reactions only by chance; no X source at all. |

## 2. Podcast and video discovery

| Source | How it searches | Cost | Results on our test people | Verdict |
|---|---|---|---|---|
| Exa (today's `discover_media`) | Web search on the topic or name | about $0.005/search | Mostly namesakes. Limited to youtube.com it found 4 of Ann's 5 talks. | Keep as a fallback, not the main route |
| **Podcast Index `search/byperson`** | Episodes tagged or titled with the person | Free (our key is set) | Ann 3/3 hand-research podcasts (Citi "The Cyber World", FS-ISAC FinCyber Today, Leader's Edge 2019); Dilip 4 (CIO Classified, Technovation, CIO Leadership Live, Inspired Execution); Boerio FIRST 2014. Noisy for common names (Carrara: about 40 "Pete" shows; Kuhn: a German role-playing podcast). Found the same episodes Podchaser listed. | **Keep, as an agent tool** |
| **YouTube Data API `search.list`** | Normal query, quoted name | 100 quota units per search; 10,000 free a day (about 100 searches) | Ann 5/5 plus CIS 2016, Peerlyst 2015 (3 parts), NYU Law 2016, Cyber Investing Summit; Dilip 3/3 plus a 2022 CIO interview; Carrara 1/1. Personal and family channels show up (Boerio, Amit) and must be skipped. | **Keep, as an agent tool** |
| Apple Podcasts search | Episode search by term | Free | Already used inside `read_media` and by the gift pilot's `find_podcasts`. | Keep inside the podcast tool |
| treg `treg.youtube.search.videos` | Query | $0.001–0.015/call | Works; no better than our own API key. | Not needed while our key has quota |
| Podchaser | Guest credits | $25/mo (yearly) for 1,000 requests; $240/mo for 10,000 | Same podcasts as Podcast Index on Ann and Dilip. | Drop unless guest credits prove better on more people |
| Listen Notes | Episode search | 300 requests/month free; $200/mo for 5,000 | Not yet tested (founder trying it). | Open |
| Podscan | Transcript search across podcasts | 10-day trial; $100/mo for 2,000/day | Demo too loose to judge; URL lookups returned 404. Founder trying it. | Open |
| treg Spotify search | Query | $0.0019 | Not tested. | Open |
| Conference and webinar libraries (RSA, Gartner, BrightTALK, vendor webinars) | Site by site | – | No catalog tool exists; reachable through Exa or YouTube when uploaded. | No action yet |

Note: the gift pilot's `find_podcasts` (`~/gift-poc/tools/gt.py`) already searches Apple + Podcast Index
`byperson` + `byterm` and ranks episodes naming the company and person first. Our platform agent has none
of this.

## 3. Transcription

| Route | What it handles | Cost | Tested on | Result | Verdict |
|---|---|---|---|---|---|
| Publisher transcript (RSS `podcast:transcript`, show pages) | Podcasts that publish one | Free | Already in `read_media` | Best quality when present | Keep, first choice |
| **YouTube captions via treg** (`scrapecreators.x.v1-youtube-video-transcript`) | Any YouTube video with captions | $0.0019 | Ann's 5 videos | All 5 returned (1,000–9,000 words), lower-case auto captions, no speaker names. Direct `timedtext` fetch from our IP returned empty. | **Keep, before Gemini** |
| Gemini on YouTube (today) | Video without captions | Model cost; refused when duration is unknown or over budget | Runs 4/5 | Works; slower and dearer than captions | Keep as fallback |
| **Deepgram nova-3 by link** (today, for podcast audio) | Any audio or video file link, with speaker labels | About $0.0043/min | X: Theo Von, 18 min (2,338 words). LinkedIn: Dilip's "CIO Leadership Live", 52 min (9,263 words, 2 speakers). | Full transcripts both times | **Keep; extend to X and LinkedIn video** |
| ScrapeCreators X transcript | X video up to 120 s | $0.0019 | Short clips; an 18-min and a 3-min video | Clips under 2 min work. Longer ones are refused; `allow_long_transcription=true` returned success with an empty transcript. | Keep for short clips only |
| ScrapeCreators LinkedIn post transcript | LinkedIn video | $0.0019 | Several posts | Often unavailable | Drop in favour of file + Deepgram |

### Long X and LinkedIn video (2026-11-09)

1. **Get the file link.** X: `scrapecreators.x.v1-twitter-tweet` ($0.0019) returns plain MP4 links at 5 sizes
   plus the length (`duration_millis`). LinkedIn: `fetchinio.linkedin.user.posts` (already used for posts)
   returns the `dms.licdn.com` MP4 link and the length, at no extra cost.
2. **Transcribe the link** with the Deepgram path `read_media` already has.
3. Both files downloaded without sign-in. LinkedIn links are signed and expire (this one in about a week), so
   transcribe at once and never store the link. X links did not show an expiry.

Spend for the two tests: about 31 ¢ (0.19 ¢ treg, the rest Deepgram).

## 4. Speaker confirmation (open, to design with the founder)

The current self-introduction check is to be discarded (section 1). Ideas collected so far, none agreed:

- Check before transcribing: name plus the employer at the time of the recording in the title, description
  or channel.
- Accept a host's introduction of the guest, not only self-introduction; match names allowing for
  transcription misspellings.
- Name the speakers with a model given the known names (for example AssemblyAI speaker identification), then
  credit only that speaker's lines.
- Voice matching against a known recording of the person (pyannote), later.
- Rule: a recording counts only if the person is a confirmed named speaker; a quote counts only from that
  speaker's lines.

### 4.1 Tests run 2026-11-09

**Speaker metadata from each platform** (Dilip Venkatachari and Ann Barron-DiCamillo samples):

| Source | What names the people in it | Result |
|---|---|---|
| Podcast Index (`/episodes/byid`) | `persons` field (the podcast:person tag) | Empty on all 6 sample episodes; no feed used the tag. |
| Podcast RSS item | Description text; sometimes links | All 6 descriptions name the guest, their role and employer, and usually the host. CIO Classified links the guest's and host's LinkedIn profiles in the item. |
| YouTube Data API (`videos.list`) | Title, description, tags | The name is in the title or description of most hits; tags sometimes list every speaker (nasscom: three names). One CIO Classified video links the guest's LinkedIn. Namesakes appear ("Leslie Ann Barron"). An old hit names an earlier employer (Compass Labs), so the employer check needs the person's career history. |
| LinkedIn posts (fetchinio) | Post text | The text names co-panelists in plain words. The tool returns no tagged-profile links. A post in a person's feed can be someone else's (a Meera Mani post appeared in Dilip's feed). |
| X tweet | `entities.user_mentions` when the author tags someone | The field exists in the tweet format. The one sample had no mentions, so this is untested. |

**Speaker identification by an LLM**: the diarised Deepgram transcript, what we know about the person, and
the recording's metadata, sent to the person-agent model (`openai/gpt-6.1-sol`):

| Recording | Hard part | Answer | Correct? |
|---|---|---|---|
| Citi "The Cyber World" podcast, 37 min, 4 labels | Two guests both called Ann | Speaking. Speaker 1 is the person. Some of her lines also sit under Speaker 2 (the opening teaser, and before 33:22). Host questions are merged into some labels. | Yes. It caught the diarisation errors. |
| Dilip's LinkedIn live, 52 min, 2 labels | Name misspelled "Venkatachary"; no caption | Speaking. Speaker 0 is mostly Dilip. Some of his answers sit under the host's label (02:23, 50:21). | Yes |
| "Dr. David Kuhn" IEP podcast, 42 min | Namesake | Different person (a clinical psychologist). | Yes |

- **Time and cost.** About 20 s per recording and 11k–16k input tokens. Deepgram for the two new episodes
  cost about $0.34.
- **A cheap model is not enough.** `gemini-3.5-flash-lite` (3 s, $0.004) picked the right label on Citi but
  said the "labels are consistent throughout", which is wrong.
- **Correction: `typesafe/jev-router` is not Jev.** The first Jev test sent the chat prompt to
  `typesafe/jev-router`, a router that hands each call to some chat model. Logged over 12 more calls, it
  picked DeepSeek v4.1 Flash, Claude Sonnet 5.5 or Gemini 3.8 Flash, so those results say nothing about
  Jev. Discarded.
- **Jev 1.14 (`typesafe/jev-1.14`, the model the founder chose).** Jev writes no text; it answers typed
  questions with probabilities through OpenRouter's Decisions API (`POST /api/alpha/decisions`, no tunable
  parameters). Every call answered as `typesafe/jev-1.14-20261014`.
  - `state` (an object): `person_we_research` (the same profile as above), `what_we_know_about_the_recording`
    (show, episode, description), `transcript_diarised` (lines `[mm:ss] Speaker N: text`), and a note that
    labels can be wrong and names misspelled.
  - Questions (agreed with the founder 2026-11-09):
    - `presence` (choice): "Is the person we research (person_we_research) in this recording?" Options
      `speaking`, `only_mentioned`, `different_person`, `unclear`.
    - `is_speaking` (noul): "Does the person we research speak in this recording?" True: they are one of the
      voices. False: they do not speak here, or the speaker is someone else with the same name.
    - `speaker_label` (choice): "Using the facts in person_we_research (their employer, roles and career),
      which speaker label is that exact person? If the speaker who shares the name is someone else (a
      namesake), the answer is none." One option per label ("Speaker N is the person described in
      person_we_research") plus `none` ("they do not speak, or the voice with that name belongs to a
      namesake").
  - Results, 5 runs per recording:

    | Recording | presence | is_speaking | speaker_label |
    |---|---|---|---|
    | Citi (two Anns) | speaking 0.96–0.98 | 0.93–0.95 | Speaker 1 0.86–0.89 (none 0.11–0.14) |
    | Dilip LinkedIn live | speaking 0.98–0.99 | 0.96–0.97 | Speaker 0 0.89–0.93 (none 0.07–0.11) |
    | Kuhn namesake | different_person 0.97–0.98 | 0.10–0.14 | none 1.00 |

    All 15 correct; runs agree within about 0.04. 1.2–1.5 s and $0.0005–$0.0008 per call (16k–18k input
    tokens). The first wording of the label question ("which label mostly carries the voice of the person")
    picked the namesake's label on Kuhn at about 0.66; the reworded question above fixed it.
  - Limit: Jev answers only the questions asked. It does not list passages where the diarisation mixed
    people up, as the chat models did unprompted; crediting passage by passage would need one question per
    passage.
- **Lesson.** Who is in the recording is easy for a strong model. The real risk is diarisation: a speaker
  label is not always one person. Proposal, not agreed: credit lines to the person passage by passage rather
  than by whole label.

## 5. LinkedIn

| Source | What it gives | Cost | Tested on | Result | Verdict |
|---|---|---|---|---|---|
| Exa on linkedin.com in date windows (today) | Posts that Exa indexed | about $0.005/search | Runs 4/5; gift pilot (Dave 24 → 112 posts with 4 windows) | Coverage unknown and uneven | Keep as fallback |
| **treg `fetchinio.linkedin.user.posts`** | The person's own posts, paged (≤50 a page), with video links | $0.0015/page | Ann 80 posts back to 2013 (all 8 hand-research posts); Dilip 38 (7 of 9); Carrara 23 (6 of 13); Kuhn 0; Rossmann 0 | Full own-post history | **Keep** |
| **treg `fetchinio.linkedin.user.reactions`** | Posts they liked or reacted to | $0.0015/page | Ann 155, Carrara 173, Kuhn 38 (incl. his like of an Illumio VP's post, 2026-02-10), Rossmann 6 | Finds likes Exa only hits by chance | **Keep** |
| treg `harvestapi.linkedin.user.comments` | Their comments on others' posts | $0.004 | Not tested | Should cover most of Carrara's missing hand items | Test next |
| treg `scrapecreators.x.v1-linkedin-search-posts` | Posts mentioning a name | $0.0019 | Ann, Dilip | Recent and popular only; namesakes for common names | Optional |
| Logged-out profile page (`~/daymaker-rea/linkedin-test`, 2026-11-04) | Last 9–13 activity items | Free | 11 gift-pilot people | Served for 9 of 11; activity tabs blocked (HTTP 999); search needs sign-in | Superseded by the treg tools |
| Wayback archive of post IDs | Archived post URLs | Free | 8 people | Dave 78, Rob 4, Lisa 1, five people 0 | Drop |

Founder decision 2026-11-09: reading LinkedIn through a third party, without signing in, is acceptable.
Legal note from the pilot: hiQ v. LinkedIn ended in a judgment against hiQ; get legal review before relying
on this in production.

## 6. X

| Source | What it gives | Cost and time | Tested on | Result | Verdict |
|---|---|---|---|---|---|
| **Wayback CDX + X embed endpoint** (`~/daymaker-rea/x-pilot`) | Every archived tweet ID, read one by one, author checked | Free; about 145 s per handle for discovery plus 20 reads (1 s per read); 0.07–0.24 s CPU | 10 gift-pilot handles (2026-11-05) | Deep for heavy accounts (Dave 8,174 IDs back to 2009; Rob 1,633). Gaps: a hole in 2023, nothing that was never archived, renamed handles break the author check, 7 of 10 lookups hit 503/504, endpoint undocumented. Includes replies. | Keep as a free deep-history extra for heavy posters only |
| **treg TikHub `tikhub.x.user.posts`** | The live timeline, about 20 tweets a page with a cursor; retweets marked | $0.001/page; about 3 s a page | Same handles (2026-11-09) | Rob: 15 pages, 288 tweets (183 own) from Apr 2022 to Nov 2026 in 46 s for 1.5 ¢. Dave: 15 pages, 281 (270 own) from Aug 2025 to Oct 2026, 41 s, 1.5 ¢. Current tweets the archive lacks (Rob's newest 4 Nov). Works on the renamed handle (Ana). Other handles: 20 tweets each on page 1. @wmannab: refused, not charged. We stopped at 15 pages, so the depth limit is unknown. Replies appear to be left out. | **Keep, main X source** |
| treg ScrapeCreators `scrapecreators.x.user.posts` | X's "top tweets" sample, no cursor | $0.0019/call | Same handles | Dave 101; most others only 5. Charged even for a missing account. | Drop |
| PDL person enrichment (`~/daymaker-rea/handle-test`) | X and Facebook handles | about $0.28 a match | 20 people | Found all 10 X and all 5 Facebook handles found by any route; 6/6 X handles independently confirmed; 0 wrong people | Keep for finding handles |
| Same-handle Instagram check (Scrapling, logged out) | Instagram account name and post count | Free | 20 people | Found 5 of 6 Instagram accounts; bios and posts need a provider | Keep for finding handles |

Comparison on the same people: the archive is free and reaches older history; TikHub is current, fast
(seconds not minutes), handles renames, needs no author check, and costs a tenth of a cent a page.

## 7. Proposed keep and drop (to agree with the founder)

**Keep and build**
1. Person media search as agent tools: Podcast Index `byperson`/`byterm`, Apple, and YouTube search with the
   quoted name, each result shown with title, channel or show, date and description for the agent to judge.
2. Prompt guidance on how media research works: search by quoted name; check name and employer at the time
   before transcribing; skip personal and family channels.
3. Transcription order: publisher transcript → YouTube captions (treg) → Deepgram by file link (also for X
   and LinkedIn video) → Gemini.
4. LinkedIn own posts and reactions through treg once the profile URL is confirmed; comments after testing.
5. X timeline through TikHub once the handle is confirmed; handles from PDL.
6. A new speaker-confirmation design (section 4), agreed first.

**Drop**: ScrapeCreators X user posts, ScrapeCreators LinkedIn transcripts, the Wayback route for LinkedIn,
Podchaser (unless guest credits prove better), the self-introduction check.

**Open**: Listen Notes, Podscan, Spotify search, LinkedIn comments, TikHub's depth limit and replies,
legal review of third-party LinkedIn and X collection, whether the archive is worth keeping for deep X
history.

## 8. Gift (direct mail) research: notes for the shared-or-separate decision

From the gift pilot (`~/gift-poc`, write-ups in `clue-training-corpus/40_gift_agent_poc`):

- One agent (v1.5) with a story-researcher and a gift-finder skill; 16.7–35.9 min and $1.81–4.54 per person
  on gpt-6.1-sol; matched the founder's real gift on 2 of 3 scored people in comparison 1.
- Its unit is a **story**: a scene in the person's own words, with about 100 words of surrounding context,
  age and ownership, the objects in it, and off-limits material marked by place only.
- Off limits for gifts: family, health, religion, politics, money, appearance, where they live. People-search
  and data-broker sites never used.
- Its research contains no X, Instagram or Facebook links at all (handle test, 2026-11-03).
