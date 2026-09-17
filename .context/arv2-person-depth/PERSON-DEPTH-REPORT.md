# ARV2 Person-Depth run — personal research on 10 people, and what Google's media models would have cost

**Run date:** 2026-09-01 → 2026-09-02. **Working dir:** `.context/arv2-person-depth/`.
**Spent: $1.29 of the $2.00 ceiling. AI Ark credits used: 0 of 5.** Measured phase time: **8.8 minutes**.
**Nothing was written to the database. Nothing was committed.**

---

## 0. What changed versus the smoke test

The cluehq.ai smoke test researched these same 10 people **professionally** — title, employer, career
history, buying-committee role, email. It never ran the personal charter. So it produced a
work profile, not a person.

This run added the missing half. Same 10 people, same locked LinkedIn identities (no identity was
re-bought), but the question changed from *"what is their job?"* to *"who are they, in their own
words, and what could you honestly open a conversation with?"*

What that bought, concretely:

| | Smoke test | This run |
|---|---|---|
| People researched personally | 0 | 10 |
| Alma mater found | not sought | **10 / 10** |
| A hobby, side project or book found | not sought | **7 / 10** |
| A "unique insight" a generic tool would miss | not sought | **10 / 10** |
| Long-form spoken voice (podcast/video) located | 0 | **3 / 10 people, 5.0 hours of audio** |
| Verbatim quote + URL on every recorded item | partial | **enforced in code — 2 unevidenced rows were purged automatically** |

**The single best thing found:** Zafran's VP Marketing, Nick Fisher, is a **cocktail YouTuber who
published a book** — *Cocktail Chemistry: The Art and Science of Drinks from Iconic TV Shows and
Movies*. He wrote: *"If we've worked together you may have discovered my little side hobby as a
cocktail YouTuber"* and *"today i'm celebrating a milestone that i set out to achieve when starting
the channel over 6 years ago: publishing a book!"*
(`linkedin.com/posts/nicholastfisher_if-weve-worked-together-you-may-have-discovered-activity-6932337822636937217-ptV7`).
No enrichment tool on the market returns that. The smoke test called him "the second call, not the
first" and knew nothing else about him.

---

## 1. The Google multimodal media layer

### 1a. The key was not there — checked twice, as instructed

`CLUE_GEMINI_API_KEY` was **absent at the start of the run** and **still absent when re-read
immediately before the media phase**. The `.env` file's modification time never changed (Aug 29
17:48). So the Gemini transcription + `gemini-embedding-2` retrieval demo **did not run**. What
follows is (a) what the honest fallback actually delivered, and (b) the exact price of the missing key.

### 1b. The fallback, and a hard finding: YouTube's free caption endpoint is dead

The brief's fallback was "YouTube caption tracks via the public `timedtext` endpoint — no key".
**That path no longer works.** Every one of the 5 YouTube videos *lists* an English auto-generated
caption track in its player response — and every request for the actual text returns
**HTTP 200, `Content-Type: text/html`, and zero bytes**. We tried seven request forms to be sure:

`baseUrl` as served · `&fmt=json3` · `&fmt=srv3` · `&fmt=vtt` · `&fmt=ttml` ·
the classic `?lang=en&v=<id>` · `&kind=asr` · `&c=WEB`, with a browser UA, a `Referer` of the watch
page and an `Origin` header. **All seven: 200 / 0 bytes.**

This is YouTube's PO-token clampdown. Treat the free caption endpoint as gone.

### 1c. What rescued it: Exa's index already holds the YouTube transcript

The fallback-of-the-fallback worked and is the practical finding of this section. An Exa
`/contents` call on the **YouTube watch URL** returns the **full auto-caption transcript as text** —
for **4 of 5** videos — at about **$0.001–0.004 per video**. It has **no timestamps**, but it has the words.

| item | person | length | what the no-key path delivered |
|---|---|---:|---|
| Siemens Competition presentation | Vineet Edupuganti | 11:42 | **full transcript**, 11.7 kB |
| Silicon Valley Podcast Ep 297 | Vineet Edupuganti | 31:26 | **full transcript**, 34.4 kB |
| Cloud Security Podcast by Google EP265 | Alastair Paterson | 28:54 | **full transcript**, 33.3 kB (via the show's own YouTube mirror) |
| "Coffee and Compliance" | (Harmonic, not Ana) | 60:34 | full transcript, 25 kB — *but the guests are "Ed and James", not Ana Corio* |
| LangChain Max Agency clip | (Cogent, not Semien) | 0:50 | full transcript — *but the speaker is Geng Sng, not Alexander Semien* |
| Hacker Valley Studio | Vineet Edupuganti | 37:24 | **show notes only** (2.8 kB). MP3 resolves; nothing can read it. |
| Security You Should Know | Alastair Paterson | 29:51 | **show notes only** (1.8 kB) |
| Boardroom Club "AI Summit" | Sanaz Yashar | 42:49 | **show page only**. MP3 resolves; unreadable. |
| CU 2.0 Podcast Ep 273 | (UPTIQ, speaker unknown) | 56:00 | show notes only |
| Uptiq product video | (uncredited) | 2:54 | nothing — page chrome only |
| 2 LinkedIn-native videos | Semien, Marathe | — | **never fetched — `unfetchable_walled`, by rule** |

So: **5 of 10 podcast-and-video items are readable without a key; 5 are not.** The five that are
not are all **podcast MP3s** — the enclosure URL resolves fine, but audio is audio.

### 1d. The exact price of the missing key

Assumptions stated, not hidden: audio bills at **32 tokens per second**; 2.5 Flash-Lite is
**$0.30/1M audio-in** and **$0.40/1M text-out**; `gemini-embedding-2` is **$0.20/1M text** and
**$0.00016/second** for raw audio. Output size modelled at 150 spoken words/min × 1.35 tokens/word,
plus an `[MM:SS]` stamp every 15 seconds.

**Total inventory: 10 items, 18,196 seconds = 5.04 hours = 582,272 audio input tokens.**

| what | cost |
|---|---:|
| Transcribe all 5.04 h, timestamped, with Flash-Lite | **$0.2011** |
| Embed all those transcripts as text with `gemini-embedding-2` | **$0.0135** |
| Embed raw audio for the **two short clips only** (50 s + 2:54) | **$0.0358** |
| **Full media layer, done properly** | **$0.2504** |
| Rate per hour of audio transcribed | **$0.0399/h** |
| *If you instead embedded **raw audio for everything*** | ***$2.903*** |

**The ruling, with the numbers behind it:**
**Transcribe cheap with Flash-Lite, embed the text with `embedding-2`, and embed raw audio only for
short clips.** Embedding raw audio across the board costs **$2.90 versus $0.21** — **13.5× the entire
transcribe-plus-text-embed pipeline** — to answer the same questions. Raw-audio embedding earns its
price only where tone, laughter or a pause is the signal, and only on clips under ~3 minutes.

**And the key is cheap relative to what it unlocks.** Four cents an hour would have bought
timestamped, speaker-attributed transcripts of **all five podcast MP3s that are currently
unreadable** — including Sanaz Yashar's 43-minute Boardroom Club interview and Alastair Paterson's
30-minute Security You Should Know episode, both of which are the richest un-mined voice sources in
this set. **For 10 people, the whole media layer would have cost 25 cents — 19% of what this run
spent in total.** It is the best-value line item we did not buy.

### 1e. The retrieval demo we could not run — and what it would have proved

With a key, the plan was: chunk each transcript, embed with `embedding-2`, and run three queries
("what do they say about ABM/outbound tooling?", "what are they proud of?", "how do they evaluate
vendors?") by cosine similarity, returning hits **with timestamps**. We could not run it.

What we *can* say from the text we do have: **the timestamps are the missing product, not the
words.** We recovered ~79 kB of genuine spoken transcript for free, and pulled real quotes out of it
(Vineet's and Alastair's `voice_quote` rows below all come from these). What we could not produce is
a citation a human can *check in ten seconds* — "he says this at 14:32". For a claim-with-provenance
system, a media citation without a timestamp is a weak citation. **That, precisely, is what the
$0.04/hour buys.**

---

## 2. The ten people

Depth score is 0–100, computed in code (not by a model) from category coverage × evidence quality,
weighted: background 20, life-outside-work 20, voice 25, professional identity 15, unique insight 10,
openers 10. "Hooks" counts P1, outreach-safe, person-revealing items.

| # | Person | Role | Depth | Claims | Hooks | Charter categories filled |
|---|---|---|---:|---:|---:|---|
| 1 | **Nick Fisher** | VP Marketing, Zafran | **68.7** | 11 | 11 | 6/6 |
| 2 | **Sanaz Yashar** | Co-Founder & CEO, Zafran | **67.8** | 13 | 12 | 6/6 |
| 3 | **Alastair Paterson** | CEO & Co-Founder, Harmonic | **66.6** | 16 | 4 | 6/6 |
| 4 | **Ana Corio** | Dir. Demand Gen, Harmonic | **66.5** | 13 | 7 | 6/6 |
| 5 | **Vineet Edupuganti** | Co-Founder & CEO, Cogent | **63.5** | 14 | 9 | 5/6 |
| 6 | **Tyler Chonoles** | Growth & Demand Gen Mgr, Harmonic | **60.5** | 8 | 5 | 6/6 |
| 7 | **Alexander Semien** | Head of Growth, Cogent | **55.1** | 12 | 8 | 5/6 |
| 8 | **Mandar Marathe** | VP Marketing, UPTIQ | **54.4** | 11 | 2 | 5/6 |
| 9 | **Vari Kaur** | Head of Growth Marketing, Zafran | **53.4** | 12 | 6 | 5/6 |
| 10 | **Cameron Coles** | VP Marketing, Cogent | **53.0** | 9 | 8 | 5/6 |

**Average depth 61.0. Average hooks 7.2. 8 of 10 at or above the Insight-Health bar of ~5 hooks.**

Full evidence for every line below is in `claims_people.json` — **119 claim rows across the 10 people,
every one carrying a verbatim quote, a URL, a priority, a use-class and an identity binding** (verified: 0 rows missing either quote or URL) and in the ten `person_<key>.md` dossiers.

---

### 1. Nick Fisher — VP Marketing, Zafran Security — depth 68.7
- **Background:** MBA, Columbia Business School (2011–2013), with an exchange term at Berkeley Haas
  (2012). Career: Ipreo → Okta (Senior Director PMM, 2018–2021) → Sysdig (VP PMM, 2021–2024) → Zafran (Apr 2024).
- **Life outside work:** *"If we've worked together you may have discovered my little side hobby as
  a cocktail YouTuber"* — a channel he has run for 6+ years, which produced a **published book**,
  *Cocktail Chemistry: The Art and Science of Drinks from Iconic TV Shows and Movies*. He described
  the photo shoot as *"one of the most fun experiences of my life as we recreated movie scenes with
  famous cocktails."*
- **Voice:** he explains decisions in numbered criteria — *"For me, the decision to join a startup
  comes down to 3 basic criteria"* (his own LinkedIn Pulse article, *Why I joined Zafran Security*).
- **Unique insight:** the book. A published author on a subject entirely unrelated to his job.
- **Openers:** the book milestone; the three-criteria framing from his Pulse article; *"I'm honored
  to be leading the marketing team."*
- **Could not find:** hometown, languages, pets, MBA concentration, any podcast appearance.
- **Same-name risk was severe and was held:** every media item matching "Nick Fisher" in the sweep
  belonged to *different* people — an archery-business CEO, an outdoors-podcast guest, and a coaching
  infomarketer. None were admitted.

### 2. Sanaz Yashar — Co-Founder & CEO, Zafran Security — depth 67.8
- **Background:** BSc Biochemistry & Molecular Biology, Tel Aviv University (1999–2002); MBA,
  Ben-Gurion University (2008–2010). Career: Israeli intelligence → Cybereason (Director of
  Intelligence) → FireEye → Mandiant (Senior Manager) → founded Zafran (Nov 2022).
- **Life outside work:** *"Favorite Hobby: Thai Boxing."* She also publicly ties **Breaking Bad** and
  chemistry to her brand: *"Finay we branded my two first loves #chemistry and #breaking bad series
  with cyber exposure."*
- **Voice:** *"Personal confession: I never watch my own videos."* Speaker at RSAC 2026 and HumanX;
  appeared on CNBC's *Squawk on the Street*.
- **Unique insight:** **15 years in Unit 8200, promoted to officer in 2004** — an intelligence career
  that long predates her private-sector roles (Forbes).
- **Openers:** the Sequoia-led round; the ~80% MTTR reduction she cites for customers; the
  Breaking-Bad-plus-chemistry brand post.
- **Governance note — this is the one the pipeline caught.** Two things were flagged and handled in
  code, not left to a prompt:
  1. Her own post said she was *"Thinking to adopt a dog for my kids in #NYC."* Self-published or
     not, **the minors clause is absolute** — that element was stripped from the recorded value and
     the removal logged.
  2. Her first-person line *"Born in Iran, moved to Israel, studied #Biology and ended up in Cyber"*
     is recorded as biography but tagged **`outreach_safe: false`** and **barred from every hook and
     opener field**. Her *intelligence-service* career is a permitted background fact; her origin
     story is not an outreach hook. Both rulings are in `claims_people.json` under
     `sensitivity_redaction_log`.

### 3. Alastair Paterson — CEO & Co-Founder, Harmonic Security — depth 66.6
- **Background:** Master's, University of Bristol (2000–2004). Co-founded **Digital Shadows in 2011**
  and led it to a **$160M acquisition by ReliaQuest (July 2022)** before founding Harmonic. Board
  member, GBx, since Jul 2023.
- **Life outside work:** music — *"I was in school bands when I was a teenager, like 13, 14, and
  playing a concert for 400 people when I was 15."* Fitness — *"for me, fitness is big thing – I
  still play football, I run a lot, and I snowboard as often as possible."*
- **Voice (from the real transcript):** on the Cloud Security Podcast by Google EP265 he argues for
  enablement over prohibition — *"the way to approach it rather than just try and cut this stuff off
  is to say, okay, what are the use cases for each of my teams?"* He cites Harmonic's own research
  base: *"we just published some new research that has analysis for more than 22 million prompts."*
- **Unique insight:** the $160M exit, with the amount and date on the record.
- **Opener with the best texture:** he *"gave a guest talk to a third year class at the University of
  Bristol Centre for Innovation and Entrepreneurship"* and noted being in the same seat 20 years earlier.
- **Could not find:** exact degree subject, instrument or band names, current fitness cadence.
- He is the **richest media subject in the set** — 3 podcast appearances, one fully transcribed.

### 4. Ana Corio — Director of Demand Generation, Harmonic Security — depth 66.5
- **Background:** BA Marketing, Santa Clara University (Leavey School of Business, 2010–2014).
  CrowdStrike → Material Security (Director of Demand Gen, 2021–2024) → Harmonic (Sep 2024), where
  she was the **first marketing hire**.
- **Life outside work (as she states it):** her own between-jobs post — *"What does a #marketingnerd
  do for 1.5 weeks between jobs?"* — answers *"1. Hit the beach for a mind break. 🏖"* and
  *"3. Binge marketing content in specific areas of interest."*
- **Voice:** *"Kicking off demand generation and growth marketing at Harmonic: the easy button for
  enabling AI safely."* And on the Series A: *"First launch 👀........ Series A is LIVE!!!!!!!! 🚀"*
- **Unique insight:** she built **"The Frequency"** — *"So... we built 'The Frequency'. Monthly (to
  start), 5 min read, zero fluff."* A named content product, not a job title.
- **Directly useful for selling:** she names her stack in public — *"Utilized tools such as 6sense,
  Clearbit, Warmly, and Clay."*
- **Could not find:** hometown, languages, pets, any long-form media where she personally speaks. The
  Harmonic podcasts that surfaced under her name feature **her CEO and colleagues, not her** — verified
  from the transcripts, not assumed.

### 5. Vineet Edupuganti — Co-Founder & CEO, Cogent Security — depth 63.5
- **Background:** BS Electrical Engineering **and** MS Computer Science, Stanford. Before that:
  **Oregon Episcopal School, Portland, OR**.
- **Unique insight — the best "generic tools would never find this" item in the run:** he won the
  **2016 Siemens Competition Individual Grand Prize** as a high-school student for
  *"Development of a High-Performance Biodegradable Battery for Transient Electronics."* We have the
  full 11:42 presentation transcript, in which he thanks *"my mentor dr. Raj solanki of Portland
  State University for access to facilities equipment."*
- **Voice (from the 31-minute interview transcript):** *"building systems that have the right
  verification, transparency, uh demonstrate the reasoning chain and provide confidence to the end
  user, that becomes really critical."* And on his own start: *"my career, interestingly, didn't
  start there. So, it began as a machine learning engineer. I was working on generative AI of all
  things over a decade ago."*
- **Career:** ML engineer → Abnormal Security/AI (Head of Multi-Product Platform Division) → founded Cogent.
- **Could not find:** any hobby, any non-professional interest, any self-announced personal milestone.
  A completely work-facing public identity apart from the high-school science record.

### 6. Tyler Chonoles — Growth & Demand Gen Marketing Manager, Harmonic Security — depth 60.5
- **Background:** **Mathematics and Physics, Bowdoin College (2015–2019)**. Career: GRAIN Group
  (BI Architect) → The Trade Desk (Programmatic Trading Specialist, 2024–2026) → Harmonic (May 2026).
- **Life outside work — found on a source no enrichment tool indexes:** his **college golf team roster
  page**. *"Off the course, Tyler enjoys playing guitar and skiing"*, and *"Tyler also played
  basketball in school."*
- **Voice:** he is openly anti-hype, like his manager — *"Most AI security content out there is vendor
  noise dressed up as thought leadership. We're trying to do something different."* And:
  *"Most organizations can tell you which AI tools their teams are using. Very few can tell you what
  work is actually getting done inside them."*
- **Unique insight:** he **curates "The Frequency"** — Harmonic's site credits it *"Written by
  practitioners, curated by Tyler Chonoles at Harmonic."*
- **Note:** he and Ana Corio both have a real claim on The Frequency (she built it, he curates it).
  Useful — it is a shared, checkable reference point for either.

### 7. Alexander Semien — Head of Growth, Cogent Security — depth 55.1
- **Background:** BA Public Policy Analysis & Psychology, **Duke University**. Goes by **"Alex"** —
  his profile opens *"Hey 👋 I'm Alex."* Career: Abnormal Security (Director, Strategy & Analytics,
  2020–2023) → Sevco Security (VP PMM) → Cogent (Aug 2025).
- **Voice / self-description:** *"I like the early stages; no playbook, just a vision and a lot to
  figure out"* and *"I'm a marketer by title but a builder at heart."* On method:
  *"growth is an equation to be understood and optimized, not just gut feeling."*
- **Unique insight:** *"We started building an in-house AI operating system from day one"* and
  *"I set strategy and build the models."* A marketing leader claiming hands-on model authorship.
- **Speaking:** listed at **THREATCON1** with the talk *"We Can't Wait for Patch Tuesdays: The Case
  for AI Blue Teaming."* He also has four bylined posts on cogent.com.
- **Could not find:** any hobby, cause, or life-outside-work item at all. And **no long-form media
  in which he speaks** — the Cogent podcasts that surfaced feature his CEO and CTO, and his one
  on-camera appearance is a LinkedIn-native video, which we do not fetch.

### 8. Mandar Marathe — VP Marketing, UPTIQ — depth 54.4
- **Background:** **MBA, Mays Business School, Texas A&M (2006–2007)**. Co-founded **Koppr** with
  UPTIQ's CEO Snehal Fulzele (2019–2022) before joining UPTIQ in Jan 2025. Based in Pune.
- **Unique insight:** he is **visiting faculty at IIT Bombay's Shailesh J. Mehta School of
  Management** — *"I take a full 21-hour elective course on Digital Marketing for 2nd year MBA
  students at SJMSOM"* — and helped launch the executive programme *"Executive Leadership for CMOs
  in the Age of AI."*
- **Also holds:** Promoter at Elemnt Sports Science, EIR at MAGIC Business Incubator.
- **Voice:** thin. One post about an on-the-go conversation with colleague Craig McKeon on AI in marketing.
- **Could not find:** anything under life-outside-work, no award, no conference talk, no publication,
  no cause. **Lowest hook count in the set (2).** His one on-camera item is LinkedIn-native — walled.

### 9. Vari Kaur — Head of Growth Marketing, Zafran Security — depth 53.4
- **Background — new since the smoke test:** **MBA Marketing (2008–2010)** and **MCA (2001–2004)**,
  both **Punjab Technical University**. The smoke test never found her education.
- **Voice:** entirely LinkedIn. *"I specialize in full-funnel strategy development—from top-of-funnel
  lead acquisition to pipeline acceleration and sales enablement"*; *"Passionate about using AI and
  automation to optimize performance."*
- **Unique insight:** the honest answer is that her most distinctive public act is the ABM hiring
  post itself — *"Our marketing team at Zafran Security is expanding! 🚀 I'm hiring a Senior Manager,
  ABM & Integrated Campaigns."* That is a strong *buying* signal but a weak *personal* one.
- **Could not find:** hometown, languages, hobbies, pets, causes, awards, conference talks, any
  long-form voice at all. **Zero life-outside-work rows.**
- She is the clearest case in the run of a person who is **professionally loud and personally silent**.

### 10. Cameron Coles — VP of Marketing, Cogent Security — depth 53.0
- **Background:** **BSE Marketing, The Wharton School.** Career: Skyhigh Networks (author of their
  2015 cloud-adoption reports) → McAfee → Wiz (Head of Product & Content Marketing, 2021) →
  Cyberhaven (VP Marketing, 2022–2025) → Cogent (Nov 2025).
- **Voice:** *"Building AI for security means you don't get to be wrong. That conviction shapes
  everything Geng and the team build at Cogent."* On joining: *"Security teams are drowning in alerts
  and struggling to prioritize what actually matters. Vulnerability management is overdue for that
  transformation."*
- **Unique insight:** the weakest of the ten — a category-building positioning statement, not a
  personal fact.
- **Could not find:** hometown, degree years, hobbies, pets, causes, and **no long-form voice** despite
  a 10-year public writing history. He writes; he does not appear.
- **Process note:** his first deep-research call **failed** (see §5). The retry recovered him.

---

## 3. The segment truth — how much do cyber/SaaS operators actually expose?

The founder's quality bar is the Insight Health physician dossiers, which averaged ~5 usable hooks
per person. Here is the honest comparison, with numbers.

| | This set (10 cyber/SaaS operators) |
|---|---:|
| Average depth score | **61.0 / 100** |
| Average hooks per person | **7.2** |
| People at or above the ~5-hook bar | **8 / 10** |
| People with **any** life-outside-work item | **5 / 10** |
| People with a hobby, book, or side project | **7 / 10** |
| People with a hometown | **5 / 10** |
| People with an alma mater | **10 / 10** |
| People with **long-form spoken voice** where they verifiably speak | **3 / 10** |
| People with a unique insight | **10 / 10** |

**We clear the hook count but not in the same currency.** Physicians have a *public professional
record* — publications, trial registries, faculty pages, conference programmes, institutional bios —
that is indexed, dated, and attributable. Cyber and SaaS operators have **LinkedIn, and then a cliff.**

The evidence for that cliff is in the source-coverage matrix. Across all 10 people:

| source type | people it yielded for |
|---|---:|
| LinkedIn profile | **10 / 10** |
| LinkedIn posts | **10 / 10** |
| University / alumni pages | 5 / 10 |
| YouTube | 4 / 10 |
| Podcast directories | 4 / 10 |
| Substack / Medium | 4 / 10 |
| Data-broker directories | 4 / 10 |
| Podcast host sites | 3 / 10 |
| Company site (their own bylines) | 3 / 10 |
| Personal site / GitHub | 2 / 10 |
| Trade press | 2 / 10 |
| Conference / event pages | 1 / 10 |
| **X / Bluesky / Threads / Reddit** | **0 / 10** |

Three findings worth acting on:

1. **LinkedIn is not one source among many — it is the spine.** 10/10 on both profile and posts, and
   nothing else clears 5/10. For this segment, "personal research" is mostly *reading their own posts
   properly*, and everything else is upside.
2. **Public social media is dead for this segment.** Zero of ten people had an indexed X, Bluesky,
   Threads or Reddit presence worth citing. We spent $0.14 across two angles proving it. That is a
   permanent deletion, not a one-off miss.
3. **Seniority buys voice; it does not buy personality.** The three people with real spoken voice are
   all **CEOs** (Yashar, Paterson, Edupuganti). The three thinnest — Marathe, Kaur, Coles — are all
   **marketing leaders**, who publish constantly *about their company* and almost never about
   themselves. **The person most likely to buy your product is the person you can research least.**
   That is the central inconvenient finding of this run.
4. **The richest personal facts came from outside the professional web entirely** — a college golf
   roster (Chonoles), a high-school science competition video (Edupuganti), a cocktail-book
   announcement (Fisher), a university guest-lecture post (Paterson). None of these live in any
   B2B data source.

---

## 4. Time and money

**Total: $1.2862 of the $2.00 ceiling (64%). 0 of 5 AI Ark credits — identity was already locked, so
none was needed. 201 calls: 148 Exa, 31 free HTTP, 22 OpenRouter.**

### By phase

| Phase | Calls | Cost | Wall clock |
|---|---:|---:|---:|
| P1 — 12-angle sweep (131 searches billed: 120 distinct + 11 re-run in a one-person smoke test) | 121 | $0.840 | 41.9 s |
| P1c — LinkedIn `/contents` batch + 10 targeted searches | 11 | $0.080 | 4.6 s |
| P2 — media resolve, captions, transcripts (36 calls, mostly free HTTP) | 36 | $0.027 | 26.6 s |
| P3 — deep-reasoning, 10 people + 1 retry | 11 | $0.241 | 115.4 s |
| P4 — gpt-5-mini structuring, 12 calls | 12 | $0.080 | 287.4 s |
| P4b — unique-insight repair, 10 calls | 10 | $0.018 | 49.4 s |
| **Total** | **201** | **$1.2862** | **≈ 8.8 min** |

### By provider

| Provider | Calls | Cost | Wire seconds |
|---|---:|---:|---:|
| Exa | 148 | **$1.188** | 474.2 |
| OpenRouter (gpt-5-mini) | 22 | **$0.0982** | 336.5 |
| Live HTTP (YouTube, RSS, Apple) | 31 | $0.00 | 14.3 |
| AI Ark | 0 | $0.00 (0 credits) | — |

Exa breakdown: 133 `auto` searches **$0.924** · 11 `deep-reasoning` **$0.241** · 4 `contents` **$0.023**.
OpenRouter: 127,674 prompt tokens + 33,127 completion tokens = **$0.0982**.

### Per person

**$0.1286 per person, 53 seconds of measured phase time per person.** Broken down:
$0.084 sweep + $0.008 targeted + $0.003 media + $0.024 deep + $0.010 structuring.

### Production extrapolation

| Scale | Cost | Notes |
|---|---:|---|
| 1 person, this exact recipe | **$0.13** | |
| 1 person, **trimmed** recipe (see §5) | **$0.07** | drop 4 dead angles, halve the sweep |
| 1 person, trimmed **+ Gemini media** | **$0.10** | +$0.025 media, only for people who have media |
| 10-person committee | $1.29 → **$0.70 trimmed** | |
| 100 accounts × 4-person committee (400 people) | $51.44 → **$28 trimmed** | |
| 1,000 accounts × 4-person committee | $514 → **$280 trimmed** | |

**The media layer never dominates.** Even at full price it is 25¢ per *ten* people, because only
3 in 10 have any media at all. Cost is driven by the search sweep, and the sweep is where the waste is.

---

## 5. Recommendations

### 5a. Which source angles earned their cost, and which did not

We recorded all 120 distinct sweep queries verbatim (131 searches were billed; 11 of them were an
identical one-person smoke test that the full run overwrote) and then traced which angle **first surfaced a URL that
ended up cited in a final claim**. This is the honest measure — not "did it return results".

| Angle | Cited URLs it found | URLs **only** it found | Cost | Verdict |
|---|---:|---:|---:|---|
| **A12 — targeted "prior employer + long-form voice"** | 29 | **4** | $0.070 | **Best angle in the run. Keep, and run it first.** |
| **A1 — `"name" podcast interview guest`** | 24 | 3 | $0.070 | Keep |
| **A4 — authored articles / byline** | 19 | 2 | $0.070 | Keep |
| A10 — volunteer / board / community | 22 | 1 | $0.070 | Keep, downweight |
| A6 — university / alumni | 21 | 1 | $0.070 | **Keep — it delivered alma mater 10/10** |
| A11 — hometown / local press | 18 | 1 | $0.070 | Keep, downweight |
| A8 — personal site / GitHub | 23 | 0 | $0.070 | **Merge into A12** — found nothing unique |
| A7 — awards / "40 under 40" | 5 | 0 | $0.063 | **Cut.** Returned generic award lists, not people |
| A3 — podcast directories (`includeDomains`) | 3 | 0 | $0.070 | **Cut** — A1 already finds the podcasts |
| A2 — video (`includeDomains` YouTube/Vimeo) | 1 | 0 | $0.070 | **Cut** — found the target once in ten tries |
| A5 — Substack / Medium (`includeDomains`) | 0 | 0 | $0.070 | **Cut. Zero.** |
| A9 — X / Bluesky / Threads / Reddit | 0 | 0 | $0.070 | **Cut. Zero.** |

**Cutting A2, A3, A5, A7, A9 saves $0.343 (27% of the run) and loses nothing.** Merging A8 into A12
saves another $0.07. That is the trimmed recipe in the table above.

**Blunt lesson: `includeDomains` is a trap here.** All four domain-restricted angles (A2, A3, A5, A9)
are in the bottom five. Restricting the domain forces Exa to return *something* from that domain —
so it returns a same-name person or a topically-similar stranger. **The unrestricted, name-quoted,
context-rich query wins every time.**

### 5b. The deep-reasoning call is worth more than the sweep it feeds

**9 of the 56 finally-cited URLs (16%) were never seen by any of the 120 sweep queries** — they were
found by the deep-reasoning agent's own searching. And they were not marginal: they include **Nick
Fisher's cocktail-book post** (the single best hook in the run) and **Alastair Paterson's own
LinkedIn Pulse launch article**.

At **$0.024 per person** the deep call is **one-quarter the price of the sweep and finds material the
sweep cannot.** Rebalance: shrink the sweep to the six angles that earned their keep, and spend the
saving on nothing — the deep call is already only one per person and does not need a second.

### 5c. Media: what actually matters

1. **Buy the Gemini key.** $0.04 per hour of audio. It is the cheapest line item in the whole system
   and it unlocks the five podcast MP3s — including the two CEO interviews — that are otherwise dead weight.
2. **Transcribe with Flash-Lite, embed the text with `embedding-2`, embed raw audio only for clips
   under ~3 minutes.** $0.25 versus $2.90 for the same answers.
3. **Route every YouTube URL through Exa `/contents` first.** It returns the ASR transcript for
   ~$0.001–0.004 with no key at all, and worked on 4 of 5 videos. Use Gemini for what Exa cannot give
   you: **MP3 audio, and timestamps.**
4. **Treat YouTube's `timedtext` endpoint as permanently dead.** Delete that code path.
5. **Verify who actually speaks before you quote.** Two of our ten media items named the target's
   *company* but featured *colleagues* — Ana Corio's "Harmonic Security" podcast is Ed and James;
   Alexander Semien's "Cogent" clip is Geng Sng. Both were caught by reading the transcript. **A
   company-named media item is not a personal voice source until proven otherwise.**
6. **Never fetch LinkedIn-native or X-native video.** Two items recorded as `unfetchable_walled` and
   never touched. Keep that rule.

### 5d. What to add to the contact charter permanently

- **`contact.facet.hooks`, `contact.facet.openers`, `contact.facet.voice_quote`** — the three proposed
  fields all earned their place. `voice_quote` needs **`media_url` + `timestamp`** as first-class
  sub-fields; the timestamp is empty in this run and that is exactly the gap the Gemini key closes.
- **`contact.facet.education_highschool`** — emerged organically for Vineet Edupuganti and carried the
  best unique insight in the set. Worth registering.
- **A university-athletics / student-organisation source type.** Tyler Chonoles's whole
  life-outside-work profile came from a college golf roster page. No B2B data source has this.
- **An `outreach_safe` boolean on every facet claim.** This run proved it is needed: a true,
  well-sourced, self-published fact (Sanaz Yashar's origin story) can be correct to *record* and wrong
  to *use*. Accuracy and appropriateness are different gates and need different fields.
- **A code-enforced sensitivity floor, not a prompt-enforced one.** The models behaved well but not
  perfectly: the post mentioning her children passed both the deep-research prompt and the structuring
  prompt, and was caught only by the deterministic pass in `p5b_redact.py`. **Put the floor in code.**
- **A code-enforced "no quote, no URL, no claim" purge.** Two rows arrived with a value of "NOT FOUND"
  and no evidence. They were purged automatically. Keep that gate.

### 5e. Two operational findings worth remembering

- **Exa deep-reasoning fails silently and cheaply.** Cameron Coles's first call returned a report
  saying the prompt was *"truncated after the heading '2. LIFE OUTSIDE W'"* — even though we sent a
  complete 6,181-character query. The tell was in the metering: **9 results and $0.015, versus 18–20
  results and $0.023–0.025 for every healthy call.** A retry with the charter moved to the front of the
  prompt returned 20 results, $0.025, and 16.6 kB including his Wharton degree. **Add a cheap automatic
  guard: if a deep-reasoning call returns fewer than ~12 results or costs under $0.018, retry once.**
- **Ask a narrow question to get a distinctive answer.** The main structuring call returned "NOT FOUND
  — thin public footprint" for the unique insight on **7 of 10 people** whose dossiers plainly contained
  a published book, a college roster bio and a Siemens Competition win. One extra narrow call per
  person — *"find the ONE thing a generic enrichment tool would never surface"* — cost **$0.0018 each**
  and took the hit rate from **3/10 to 10/10**. Model conservatism, not missing data. **Never let one
  broad extraction call decide whether something exists.**

---

## Artifacts

| File | What it is |
|---|---|
| `claims_people.json` | Every typed claim: field key, value, verbatim quote, URL, P1/P2/P3, use-class, identity binding, `outreach_safe`, plus per-person depth score, unique insight, not-found list, and the redaction/purge logs |
| `media_index.json` | All 12 media items: duration, MP3/caption status, verified speaker, what the no-key fallback delivered, and the exact Gemini token/cost math per item |
| `person_<key>.md` × 10 | The raw deep-research dossiers |
| `transcripts/` | 12 transcripts and show-note files, incl. 4 full ASR transcripts (~79 kB of real spoken voice) |
| `sweep_digest.json` | All 120 distinct search queries **verbatim** (12 angles x 10 people) with everything each returned |
| `sweep_triage.json` | Per-person source-coverage matrix and strong-hit lists |
| `p5_tables.json` | Scoreboard, coverage matrix, angle productivity, segment truth, sensitivity audit |
| `cost_ledger.json` / `timing.json` | Every call: provider, cost, HTTP status, latency |
| `raw/` | Every raw API response, saved before parsing |
| `p_lib.py`, `roster.py`, `p1_*.py` … `p5b_redact.py` | The scripts, in run order |

**Honesty statement.** Nothing in this report is asserted without a verbatim quote and a URL in
`claims_people.json`. Where a person's public footprint is thin, it is reported thin — Vari Kaur,
Cameron Coles and Mandar Marathe are the three thinnest and are labelled as such. Two rows were
purged for lacking evidence, one element was redacted under the minors clause, and one first-person
biographical line is recorded but barred from outreach. The Gemini media layer did not run; its cost
is modelled from the published price sheet with every assumption stated.
