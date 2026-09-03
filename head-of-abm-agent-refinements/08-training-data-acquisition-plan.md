# 08 — Training-data acquisition plan for the Head of ABM agent

**Status:** proposal for founder ratification · **Date:** 2026-08-31 · **Scope:** how Clue acquires,
stores, distills, and governs the written corpus that makes the Head of ABM agent good at ABM.
**Companion evidence:** every capability claim in this doc is listed in §7 (Verification register)
with the method used to check it. Claims I could not verify are marked **UNVERIFIED** inline.
**Related:** `docs/specs/ARV2-smoke-test-findings.md` (the measured cost/latency numbers used here),
`docs/specs/ARV2-sources-and-variables-architecture.md`, `docs/architecture/clue-hq-platform-agent-runtime.md`
(Doc A — what *skill* means mechanically), `docs/architecture/clue-hq-verification-layer.md` lineage
(M9.x — the claim discipline this program mirrors).

---

## Executive summary

1. **Do not fine-tune.** Build a cited corpus → distilled *skill knowledge packs* + *exemplar libraries* + *golden eval sets*. A fine-tune cannot cite its sources, and citation is the product.
2. The corpus is **not** the claim store. It never writes to `claim`; it feeds skills. Enforced as a seam, same discipline as `subsystems/`.
3. **Standing rule — never store what we can't cite.** Every record carries `source_url`, `fetched_at`, `terms_class`, `retention_class`. A record that fails the check is deleted, not quarantined.
4. **Origin-fetch rule (new, load-bearing).** Exa's ToS §4.2(a) bars copying/creating derivative works from information "obtained from or through the Services." So Exa is used for **discovery (URLs, ranking)**; the *text we persist* is fetched from the origin, which is also better provenance. Exa honors robots.txt and `noindex` — it is not a bot-wall bypass.
5. Phase 1 seed corpus ≈ **3,500–4,500 records** across 10 source classes, ~90% acquired by free direct fetch (sitemap / RSS / ATS APIs / podcast RSS), for **~$45–75 all-in** and ~1 working day of unattended fleet time.
6. The highest-yield, lowest-risk, most *differentiating* source is the one nobody scrapes: **free ATS job-req APIs** (Ashby/Greenhouse/Lever, verified live, no auth) — buyers describing their own ABM pain in their own words. The smoke test proved hiring facts drove **every** ranking change.
7. Second-highest yield: **podcast transcripts published in the RSS feed itself** (Podcasting 2.0 `<podcast:transcript>`). Verified live: 3 of 10 sampled B2B-marketing feeds publish full machine-readable transcripts, free, no auth, no ToS problem.
8. LinkedIn, X, and G2 are **derived-only** classes: structured observations plus ≤25-word quotes with links, never bulk copies. YouTube is default-off. This is a ToS and GDPR decision, not squeamishness — and it costs us almost nothing in agent quality.
9. Reddit is **out of scope as an automated source.** Verified: blanket `Disallow: /`, `.json` 403 regardless of User-Agent, old.reddit behind a login wall, and — decisively — Reddit's Public Content Policy makes *any commercial use* contract-only, while its Developer Terms §4.2 forbid AI-model training without permission. We read Reddit like humans and cite it; we do not ingest it.
10. Distillation mirrors the platform's claim discipline: cheap-model extraction → mandatory verbatim evidence span → cross-source corroboration (≥2 *independent domains*, at least one non-vendor) → founder review gate → versioned skill release, with a CI check that fails if any assertion's citation does not resolve.
11. Total year-1 program cost ≈ **$400–700** in provider spend plus ~20 founder-hours of review. A fine-tune program costs 10–30× that and is stranded by every model upgrade.
12. Three founder decisions are required before Phase 1 runs — YouTube posture, Exa written-permission ask, and creator-PII retention ceiling (§8).

---

## 0. The three standing rules

Everything below is an application of these. They are the part worth memorizing.

**R1 — Corpus ≠ claim store.** The claim store holds *account truth* about a client's market, with
provenance, under DSAR. The corpus holds *craft knowledge* about how ABM is practised. They never
mix: no corpus record is ever inserted as a `claim`, and no account claim is ever distilled into a
skill. Mixing them would (a) pollute account truth with vendor marketing and (b) drag third-party
creator PII into the tenant data model. Mechanically: the corpus lives outside
`subsystems/research/`, imports nothing from it, and is consumed only by skill-build tooling.

**R2 — Never store what we can't cite.** Every corpus record must carry a resolvable
`source_url`, a `fetched_at`, a `terms_class`, and a `retention_class`. A fetch that produces text
we cannot attribute to a specific URL is discarded at ingest — the same posture as
"a claim with no evidence span cannot be promoted." An empty slot is a correct output.

**R3 — Origin-fetch rule.** Search indexes (Exa) are used to *find* and *rank* URLs. The bytes we
persist are fetched from the origin whenever the origin permits it. Three reasons, in order of
weight: (i) Exa's ToS §4.2(a) prohibits copying/creating derivative works from information obtained
through the service, so persisting Exa page text is a live legal question (§5.2); (ii) origin
fetches give us the canonical URL, the publication date, and the exact bytes for an evidence span;
(iii) it's cheaper — a direct GET measured 0.22s and $0 in the smoke test. When the origin refuses
(Cloudflare 403, auth wall), the class becomes **derived-only** — we keep observations and short
quotes, not the document.

---

## 1. Source classes & routes

### 1.0 Class summary

| # | Class | Route (primary) | Fallback | Verbatim storage | Yield (Phase 1) | Cost / 100 items |
|---|---|---|---|---|---|---|
| C1 | Agency & vendor GTM blogs | direct GET via `sitemap.xml` / RSS | Exa discovery → origin GET; skip if origin 403 | **Yes** (`verbatim_ok`) | ~1,200–1,500 posts | **$0.00** (bandwidth) |
| C2 | Creator newsletters (Substack/beehiiv/WP) | RSS `content:encoded` (full text, verified) | sitemap backfill for archive depth | **Yes** (free posts only) | ~600 posts | **$0.00** |
| C3 | LinkedIn posts | Exa `/search` (`people`/site-scoped) → **derived-only** | founder's own feed, manually saved | **No** (`derived_only`) | ~200 observations | ~$0.70 (search) |
| C4 | X posts | Exa/Google indexed copies → **derived-only** | skip | **No** | ~100 observations | ~$0.70 |
| C5 | Reddit threads | **None automated.** Founder reads; insights entered as first-party notes citing the URL | official Data API **only under a commercial licence** | **No** (`founder_note`) | ~40 founder notes | **$0.00** |
| C6 | YouTube transcripts | **founder decision required** (§8-D1); default = creator-hosted transcript pages only | podcast RSS (C7) covers most of the same voices | **No** by default | 0–150 | $0.00–$0.36/hr audio |
| C7 | Podcast transcripts & show notes | iTunes Search API → RSS → `<podcast:transcript>` (srt/txt/vtt) | show notes from `<description>`; Whisper $0.006/min | **Yes** (publisher-published) | ~240 transcripts + ~500 note sets | **$0.00** (or $0.36/audio-hr) |
| C8 | Vendor case-study pages | direct GET (verified open) | Exa discovery → origin GET | **Yes** | ~300 | **$0.00** |
| C9 | G2 / review content | **none — skipped in bulk**; Exa snippets for triangulation only | licensed G2 data product if ever needed | **No** | ~50 snippets | ~$0.70 |
| C10 | System-prompt repos & published prompts | `raw.githubusercontent.com` GET; Anthropic's published prompts | — | **Read-only, pattern notes** (GPL-3.0 hazard, §5.4) | ~40 files | **$0.00** |
| C11 | Papers | arXiv API / Semantic Scholar API; HF datasets where licensed | abstract-only | metadata + abstract; full text only if CC | ~30 | **$0.00** |
| **C12** | **ATS job reqs (first-party route)** | **Ashby/Greenhouse/Lever public APIs (verified, no auth)** | `/careers` page GET | **Yes** (public job ads) | ~900 reqs | **$0.00** |
| **C13** | **Clue's own runs** | internal — smoke-test dossiers, run artifacts, founder edits | — | **Yes** (first-party) | 203 claims + growing | **$0.00** |

C12 and C13 are additions to the brief. They are the two classes that are simultaneously the
cheapest, the least legally encumbered, and the only ones a competitor cannot copy.

---

### C1 — Agency & vendor GTM blogs

**Acquisition.** `GET /sitemap.xml` (or `/rss.xml`, `/feed`) → filter to article paths → direct GET
each article → readability extraction → store.

**Verified live (2026-08-31, plain curl with a descriptive UA):**

| Domain | Result |
|---|---|
| `coldiq.com/sitemap.xml` | **200**, 6,306 URLs, **378** under `/blog/` |
| `coldiq.com/blog/<slug>` | **200**, full article HTML |
| `clay.com/blog` | **200** (Webflow, sitemap available) |
| `lemlist.com/blog` | **200** |
| `gong.io/blog` | **200** |
| `blog.hubspot.com/marketing/rss.xml` | **200**, 2.4 MB RSS |
| `demandbase.com/blog/` | **200** |
| `6sense.com/blog/` | **403** — Cloudflare interstitial ("Just a moment…") |
| `gtmnow.com/feed/` | **403** |

**Expected yield.** 12–15 seeded domains × 80–400 posts = **1,200–1,500 articles**, ~1,500 words
each (~2,000 tokens). This is the corpus's backbone.

**Cost / 100.** $0.00 in provider spend. Wall-clock ~40s per 100 at 1 req/s per host with 8 hosts in
parallel.

**Rate limits.** None published; we self-impose **1 request/second per host**, `Retry-After`
honored, exponential backoff on 429/503, a hard per-host daily cap of 500 fetches, and a descriptive
User-Agent with a contact address (`clue-corpus-research/0.1 (+https://cluehq.ai; team@cluehq.ai)` —
the UA used for every probe in §7).

**ToS / licensing posture.** Publicly published marketing content, robots-permitted, fetched at
human-ish rates. We store it **internally** for retrieval and distillation; we never republish it.
Public output quotes ≤25 words with attribution and a link. `terms_class: open_web_published`.
**Must not do:** ignore `robots.txt`, fetch faster than 1 rps/host, republish an article, or present
a vendor's claim as ours without attribution.

**Failure fallbacks.** (1) robots disallow → drop the domain entirely. (2) Origin 403 (6sense,
gtmnow) → the domain becomes **derived-only**: Exa search gives us title/snippet, and we record an
observation with a link, never a stored copy. (3) Sitemap missing → RSS; RSS missing → seeded URL
list from Exa, capped at 50/domain. (4) Paywall → skip; we do not defeat paywalls, ever.

---

### C2 — Creator newsletters

**Acquisition.** RSS. **Verified live:** `lennysnewsletter.com/feed` returns **20 items** with
`<content:encoded>` blocks averaging **18,926 characters** — i.e. Substack RSS is *full-text* for
free posts. `saastr.com/feed/` returns 200. `growthunhinged.com/feed` returns **404** (custom-domain
Substack path differs — resolve per publication, don't assume `/feed`).

**Expected yield.** RSS windows are short (typically 20 items). Phase 1: 15 publications × 20 =
**300 current posts**; archive depth comes from each publication's sitemap (Substack exposes
`/sitemap.xml`) for another ~300, capped at 40 posts/publication to avoid over-weighting one voice.

**Cost / 100.** $0.00.

**Rate limits.** Same self-imposed 1 rps/host.

**ToS posture.** RSS is published *for syndication* — consuming it is its purpose. **Free posts
only.** If a feed item is truncated because the post is paid, we keep the excerpt and the link and
mark `retention_class: quote_only`. **Must not do:** use a paid subscription's cookies to harvest
paywalled posts into the corpus. A paid subscription entitles the founder to *read*, not the company
to *ingest*. **UNVERIFIED:** Substack's ToS language on automated RSS consumption (WebSearch budget
exhausted; RSS-as-syndication is the industry norm and Substack publishes the feeds unauthenticated).

**Failure fallbacks.** 404 on `/feed` → try `/rss`, `/feed.xml`, `/atom.xml`, then the publication's
sitemap; then drop.

---

### C3 — LinkedIn posts

**The honest position.** LinkedIn is a hard auth wall and its User Agreement §8.2 prohibits, in
terms (verified verbatim):

> "Develop, support or use software, devices, scripts, robots or any other means or processes (such
> as crawlers, browser plugins and add-ons or any other technology) to scrape or copy the Services"

and — the clause that matters most for an indirect route —

> "Copy, use, display or distribute any information (including content) obtained from the Services,
> whether directly or through third parties (such as search tools or data aggregators or brokers),
> without the consent of the content owner"

That second clause reaches *through* an index. It is a contract term, not a statute (hiQ established
that scraping public data isn't a CFAA crime, but hiQ still lost on breach of contract in 2022), and
LinkedIn enforces it (LinkedIn v. Proxycurl — **UNVERIFIED**, WebSearch budget exhausted; treat as
directional). So:

**Acquisition (permitted shape).** Exa `/search` for indexed copies → we read them → we record an
**observation record**: what pattern the post demonstrates, the author, the URL, the date, and a
**≤25-word verbatim quote** used as the evidence span. We do **not** persist the post body.

**Note on coverage.** Exa's docs (verified) document a `people` category over "1B+ public
professional profiles" and company pages — they do **not** document LinkedIn *post* coverage. Our
own prior runs did return verbatim LinkedIn post text, so retrieval works in practice but is
**not contractually guaranteed**. Plan for best-effort yield, never a required input.

**Expected yield.** ~200 observation records in Phase 1 (about 60 searches).
**Cost / 100.** ~$0.70 (Exa `/search` at $7/1k requests, contents free for the first 10 results).
**Rate limits.** Exa `/search` 10 QPS documented.

**ToS / licensing posture.** `terms_class: platform_restricted`, `retention_class: derived_only`,
`quote_budget_words: 25`. Named creators → `pii.contains_personal_data: true`, lawful basis
*legitimate interest*, retention ceiling 24 months, delete-on-request (§5.5).
**Must not do:** run any automated fetcher against `linkedin.com`; store post bodies; store profile
data; re-publish a creator's words as our own; use a creator's post as a *lead source* (that would
cross from craft-corpus into the account pipeline and break R1).

**Failure fallbacks.** Exa returns nothing → the founder's own saved-post list, entered by hand, is
the fallback and is also the highest-signal subset. This class is deliberately small.

---

### C4 — X posts

Same shape as C3, weaker yield. Direct fetches return **HTTP 402** to our fetchers (established).
X's ToS prohibits scraping; *X Corp. v. Bright Data* (N.D. Cal. 2024) went against X on preemption
grounds — **UNVERIFIED** here (WebSearch exhausted) and irrelevant to our posture, because we are
not scraping X either way. Exa's docs do **not** document X coverage (verified absence); the only
X mention in Exa's docs is a third-party Connect partner (Fiber.ai), billed separately.

**Route:** Exa/Google indexed copies → derived-only observation + ≤25-word quote.
**Yield:** ~100 observations. **Cost/100:** ~$0.70. **Fallback:** drop the class; C1/C2/C7 carry the
same practitioners' thinking in longer, cleaner, safely-storable form.

---

### C5 — Reddit threads

**Verified live 2026-08-31, and the answer is "don't."** Both the technical route and the contract
route are closed for a commercial product. This is the biggest single change from the brief's
assumptions, so the evidence is laid out in full.

*Technical probes (one request each, descriptive UA and Chrome UA):*

| Probe | Result |
|---|---|
| `www.reddit.com/robots.txt` | **200** — `User-agent: *` / **`Disallow: /`** + link to the Public Content Policy |
| `www.reddit.com/r/<sub>.json` | **403** with a descriptive UA **and** with a Chrome UA (body = HTML shell, not JSON) |
| `old.reddit.com/r/<sub>/top.json` | **302 → `/login/?reason=lor2`** |
| `old.reddit.com/r/<sub>/` | **302 → login** (Reddit began requiring login for logged-out old.reddit ~2026-06-30, citing "abusive scraping"; no shutdown date announced) |
| `www.reddit.com/r/<sub>/` (HTML) | 200 |
| `www.reddit.com/r/<sub>/.rss` | 200 — the last open anonymous route, and reportedly the next target |

*Contract terms (Reddit Developer Terms, effective 2024-09-24; Public Content Policy; Responsible
Builder Policy):*

- **§4.2** — may not use Reddit Services and Data "to train large language, artificial intelligence,
  or other algorithmic models or related services **without our permission**."
- **§3.3** — when user content is deleted, suspended, or modified, you must delete or modify your
  copy and related app content "**as soon as possible**." (Licensees get a Compliance API for this;
  free-tier developers do not.)
- **§7.3** — retention limits: update or delete Reddit data on request, on user deletion, or when
  retention is no longer necessary.
- **§5.2** — attribution requirements: link back, cite the username, mark it as from Reddit.
- **Public Content Policy** — Reddit content may be used "for non-commercial uses, such as learning
  and community, but talk to us if you have commercial purposes in mind." **A commercial ABM product
  is a commercial purpose regardless of request volume** — there is no QPM threshold to engineer
  under. The **Responsible Builder Policy** additionally requires explicit approval before accessing
  Reddit data at all.
- The free tier is real (**100 QPM per OAuth client id**; unauthenticated traffic is *blocked*, not
  throttled) — but the free tier's *terms* are the constraint, not its rate limit.

*Litigation posture (why "it's public" isn't a defence):* **Reddit v. Anthropic** (filed 2025-06-04,
CA Superior Court) pleads five **state-law** theories — breach of contract, unjust enrichment,
trespass to chattels, tortious interference, unfair competition — and **no copyright claim**; in
March 2026 the N.D. Cal. held those claims **not preempted** by the Copyright Act and remanded.
**Reddit v. Perplexity / SerpApi / Oxylabs / AWMProxy** (S.D.N.Y., filed 2025-10-22) targets
*indirect* acquisition — harvesting Reddit content out of Google's results — on DMCA §1201
anti-circumvention theories. Both cases are aimed precisely at the two shortcuts we might have
taken. Public Reddit corpora on Hugging Face / Academic Torrents carry uploader-asserted licenses
(CC-BY, MIT, ODC-BY) that **Reddit did not grant**, and none of them propagate deletions — they
launder nothing.

**Decision: no automated Reddit acquisition, no stored Reddit content.** The value (what buyers
complain about) is real but small relative to the exposure, and it is largely duplicated by C7
podcast Q&A and C12 job-ad language.

**What we do instead.** A human reading Reddit in a browser is a user, not a bot. The founder (or
anyone) may read threads and record a **first-party note** — their own words, their own analysis —
with the permalink as a pointer. The note is authored by us, so it is `terms_class: first_party`,
and it stores no Reddit content beyond, at most, a ≤15-word quote with username attribution and a
link, per §5.2. Target: ~40 notes across 8 communities. Yield per hour of reading is high; cost is
zero; exposure is zero.

**Re-open condition.** If Reddit ever becomes strategically necessary, the route is a **licensing
conversation with Reddit**, not a cleverer fetcher. Nothing in this plan should be read as
authorizing a workaround.

---

### C6 — YouTube transcripts

**Verified, and it changes the plan.** `uvx yt-dlp --version` → **2026.08.19** (works locally). But:

- **YouTube ToS**, verbatim: users may not access the Service "using any automated means (such as
  robots, botnets or scrapers)" except public search engines per robots.txt or with prior written
  permission; and may not "access, reproduce, download, distribute, transmit … any part of the
  Service or any Content" except as expressly authorized.
- **YouTube API Services Developer Policies III.E.6**, verbatim: "You and your API Clients must not
  … directly or indirectly, **scrape** YouTube Applications … **or obtain scraped YouTube data or
  content**." (So the "use a third-party transcript API" workaround is expressly anticipated.)
- **III.E.4.c/d:** stored API data must be refreshed or deleted within **30 calendar days** — which
  is fatal to a durable transcript corpus even via the sanctioned API.
- `captions.download` in Data API v3 only serves captions for videos **you own** (**UNVERIFIED**
  here — WebSearch exhausted — but it is the long-standing documented behavior; verify before use).

**Recommendation: default OFF.** Do not run yt-dlp at corpus scale. The value YouTube adds
(practitioner talks) is ~90% duplicated by C7 podcast transcripts, which are *published for
syndication* and carry no equivalent restriction. Founder decision D1 (§8) can override with eyes
open; if it does, the constrained shape is: founder-owned or explicitly-permissioned channels only,
≤150 videos, `terms_class: platform_restricted`, `retention_class: derived_only`.

**Route if enabled:** `uvx yt-dlp --skip-download --write-auto-subs --sub-lang en --sub-format vtt`.
**Known failure modes:** "Sign in to confirm you're not a bot", PO-token/player-client requirements,
IP throttling — all of which mean the route is also *operationally* fragile, not just legally.
**Cost:** $0 for yt-dlp; $0.006/min ($0.36/audio-hour) if we transcribe with Whisper instead
(verified pricing), $0.003/min with `gpt-4o-mini-transcribe`.

**Preferred substitute:** creator-hosted transcript pages (many practitioners publish the transcript
on their own site — that's C1), plus C7.

---

### C7 — Podcast transcripts & show notes

**This is the sleeper source, and it is verified end-to-end.**

Route, all free and unauthenticated:
1. **iTunes Search API** — `https://itunes.apple.com/search?term=<topic>&entity=podcast&limit=N`
   returns `collectionName` + **`feedUrl`**. Verified 200, no key.
2. `GET <feedUrl>` → RSS.
3. Parse `<podcast:transcript url="…" type="…">` (Podcasting 2.0 namespace) → fetch → store.
4. No transcript tag → store `<description>` show notes (title, guest, links, summary).

**Verified sample (10 B2B-marketing feeds discovered via iTunes):**

| Show | Items | `<podcast:transcript>` tags |
|---|---|---|
| Full-Funnel B2B Marketing Show | ~83 | **223** (srt + txt + vtt per episode) |
| Demand Decoded | ~112 | **52** |
| Demand Generation Club | ~43 | **43** |
| 7 others | 25–143 | 0 |

A transcript URL was fetched successfully and returned real SRT text (speaker-labelled). So: **~30%
of B2B-marketing feeds publish full machine-readable transcripts, free**, and the rest still give us
show notes.

**Expected yield.** 20 shows seeded → ~6 with transcripts × ~40 episodes = **240 transcripts**
(~8,000 words each — the single richest per-document class in the corpus) + ~500 show-note records.
**Cost / 100.** $0.00. **Rate limits.** iTunes Search API is undocumented-but-throttled; we cap at
20 requests/minute. Feed hosts: 1 rps.

**ToS posture.** `terms_class: open_web_published`. An RSS feed with a `<podcast:transcript>` tag is
a publisher explicitly publishing a transcript in a machine-readable format for consumption — the
cleanest licensing posture of any spoken-word source. Store verbatim internally; quote ≤25 words
publicly with show + episode + link. **Must not do:** download and redistribute the audio; transcribe
audio from feeds whose terms forbid derivative works (default: only transcribe when a show has no
transcript *and* the founder wants that specific show).

**Failure fallbacks.** No transcript tag and the show matters → Whisper at $0.36/audio-hour, capped
at 20 hours in Phase 2 ($7.20). No feed → drop.

---

### C8 — Vendor case-study pages

**Acquisition.** Direct GET. **Verified:** `clay.com/customers` **200**,
`demandbase.com/resources/case-studies/` **200**. Discovery by sitemap filter (`/customers/`,
`/case-stud`, `/success`) plus Exa `/search` scoped by `includeDomains`.

**Why it matters.** These are the *structural* exemplars for the agent's own output: problem →
before-state → intervention → metric → quote. The agent will be asked to produce this shape
constantly, and imitating real ones beats describing them.

**Yield.** 25 vendors × ~12 = **300**. **Cost/100:** $0.00 direct; ~$0.70 if discovery needs Exa.
**Posture:** `open_web_published`, verbatim-storable, quote ≤25 words publicly. Every case study is
marked `commercial_interest: true` — their metrics are marketing claims and can never corroborate a
practice-tier assertion alone (§4.3).
**Fallback:** origin 403 → derived-only structural note (the *shape* is the asset, not the prose).

---

### C9 — G2 / review content

**Verified:** `g2.com/robots.txt` is broadly permissive (it explicitly allows GPTBot, ClaudeBot,
Google-Extended, CCBot…), **but** `g2.com/products/<x>/reviews` returns **403** to our fetcher —
bot-management at the edge, independent of robots.txt. Their ToS prohibits scraping and G2 sells
licensed data products.

**Decision: skip in bulk.** Take Exa-indexed snippets for occasional triangulation (~50 records,
derived-only, ≤25-word quotes), and revisit only if a customer engagement justifies a licensed feed.
Same posture for Capterra / TrustRadius / Gartner Peer Insights (**UNVERIFIED** individually).
**Must not do:** rebuild a review database, or use Scrapling/stealth fetching to defeat the 403.
That last point is general: *stealth fetching is for sites that block us accidentally, never for
sites that block us deliberately.* (Scrapling was needed 0 times in 40 fetches in the smoke test;
it stays benched.)

---

### C10 — System-prompt repos & published prompts

**Verified:** `github.com/x1xhlol/system-prompts-and-models-of-ai-tools` exists,
**143,261 stars**, license **GPL-3.0**, last push 2026-08-11, 1.5 MB;
`raw.githubusercontent.com/.../README.md` fetches fine. `github.com/blader/humanizer` — **MIT**,
39,310 stars. `github.com/jenna-russell/storyscope` — **MIT**, 181 stars; its dataset is
**`jjrussell10/storyscope` on Hugging Face, license `mit`, 10K–100K rows, parquet
(train/val/test/dev splits)**, fetchable via the HF API.

**The catch nobody flags: GPL-3.0 is a *distribution* license.** Reading the x1xhlol prompts to
learn structure is fine. Copying prompt text into a skill we ship would raise a copyleft question —
and, separately, those prompts are third-party works of uncertain provenance (leaked/extracted).
**Rule: read for patterns; never paste.** Record what we learned as a `pattern_note` with a
citation, in our own words. Anthropic's *published* system prompts are the one source we may quote
directly (published by the author for exactly this purpose) — still ≤25 words with citation.

`blader/humanizer` (MIT) and `jjrussell10/storyscope` (MIT) are both **directly usable**, including
the HF dataset — MIT permits use with attribution. StoryScope is the closest thing to a
ground-truth "AI-writing tells" dataset and is the natural seed for our anti-slop eval set (§3.4c).

**Yield:** ~40 prompt files read → ~25 pattern notes; 1 HF dataset (10K–100K rows).
**Cost/100:** $0.00. **Fallback:** none needed.

---

### C11 — Papers

**Route:** arXiv API and Semantic Scholar Academic Graph API (free key), abstracts + metadata;
full text only where the paper carries a CC license. **UNVERIFIED:** exact arXiv API rate limit
(commonly cited as ~1 request/3s) and Semantic Scholar's current free-tier limits — WebSearch budget
exhausted; verify before running the harvester.

**Why so small.** Academic literature on persuasion/personalization is useful for *framing* (and for
resisting vendor folklore), but the agent's job is operational. 30 papers, abstract-level, is enough
to give the skill packs a non-vendor spine.
**Posture:** metadata + abstract stored; full PDFs only for CC-licensed papers; quote ≤25 words.

---

### C12 — ATS job requisitions (the differentiator)

**Verified live, no auth, 2026-08-31:**

| Endpoint | Result |
|---|---|
| `https://boards-api.greenhouse.io/v1/boards/<slug>/jobs` | **200**, JSON, 363 KB for one company |
| `https://api.ashbyhq.com/posting-api/job-board/<slug>` | **200**, JSON, 2.3 MB for one company |
| `https://api.lever.co/v0/postings/<slug>?mode=json` | 404 on a bad slug → **slugs must be read off the careers page, never guessed** (smoke-test gap G6: 8/8 guessed slugs 404'd) |

**Why this is the top source.** The smoke test's central finding: *every* ranking change was caused
by a hiring fact, not a funding fact. A GTM job req is a buyer describing their own pain, budget,
tooling, and org design, in public, in their own words, dated, with a stable URL. For a
Head-of-ABM agent, a corpus of 900 GTM reqs teaches (a) the vocabulary buyers actually use,
(b) which pains are budgeted, (c) what "we have no ABM platform" looks like in evidence.

**Yield:** ~300 companies × ~3 GTM-relevant reqs = **900 documents**, plus a derived
`role-language` frequency table. **Cost/100:** $0.00, ~1.3s/call measured.
**Rate limits:** none published; self-cap 2 rps per ATS host.
**Posture:** `open_web_published`, verbatim-storable. Job ads name hiring managers occasionally →
run the PII flag. **Must not do:** treat a corpus job ad as an *account claim* (that's R1 — the
research pipeline fetches its own, freshly, per account).
**Fallback:** company `/careers` page GET (smoke-test gap G4: ATS-less companies were invisible).

---

### C13 — Clue's own runs (first-party)

Dossiers, claim bundles, founder edits, accepted/rejected drafts, the 203-claim sample DB, the
"refused a false fact supplied by its own operator" transcript. Zero acquisition cost, zero legal
risk, and the only corpus a competitor cannot replicate. **Every founder edit of an agent draft is a
labelled training pair** — capture them from day one; they are the seed of the eval set (§3.4c) and
the single most valuable thing in the program by month six.

---

## 2. The fetch fleet design

Three phases. The fleet is orchestrated by this codebase's Claude agents. **Design rule that keeps
it cheap: agents write and run fetchers; agents do not read the corpus into context.** A fetch agent
emits a script, runs it, and reports counts and failures. Content only enters a model's context in
the distillation pipeline (§4), where it is metered and batched.

### 2.1 Phase 1 — seed corpus (one working day)

**Goal:** ~3,500–4,500 records (~3,900 stored documents + ~390 derived-only observations and
founder notes), ~8–10M words, covering all zero-risk classes end to end.
**Agents:** 6, run in two waves of 3 (respecting the workspace's concurrent-subagent limit).

| Agent | Charter | Sources | Target | Wall-clock |
|---|---|---|---|---|
| **F1 — blog harvester** | Build the sitemap/RSS → article → readability pipeline; seed 15 domains; respect robots + 1 rps/host; emit `index/documents.jsonl` + raw text to the object store | C1 | 1,200–1,500 docs | ~2.5 h |
| **F2 — newsletter & case-study harvester** | Resolve each publication's feed path (don't assume `/feed`); pull full-text `content:encoded`; sitemap backfill capped at 40/pub; then the case-study sweep | C2, C8 | ~900 docs | ~2 h |
| **F3 — podcast harvester** | iTunes Search → feedUrl → RSS → `<podcast:transcript>` (prefer `text/plain`, fall back to vtt→srt); show notes otherwise | C7 | ~240 transcripts + ~500 notes | ~1.5 h |
| **F4 — ATS & careers harvester** | Company list → careers page → board link → Ashby/Greenhouse/Lever API → GTM-role filter → normalized job-ad records + role-language table | C12 | ~900 reqs | ~2 h |
| **F5 — derived-only observer** | Exa discovery for LinkedIn/X/G2; produce observation records with ≤25-word quotes — **never** page bodies. **Does not touch Reddit** (C5 is human-read only; F5 instead prepares a founder reading list of thread URLs) | C3, C4, C9 | ~350 observations + a 40-thread reading list | ~2 h |
| **F6 — curator / normalizer** | Runs *after* the others: dedup (§2.4), language + boilerplate filter, `commercial_interest` tagging, schema validation, corpus report; quarantine anything failing R2 | all | — | ~1 h |

**Wave plan.** Wave A = F1, F3, F4 (pure-free, no shared dependency). Wave B = F2, F5, F6.
**Total wall-clock:** ~6–8 hours unattended, plus ~1 hour of founder attention at the wave boundary.

**Phase 1 provider cost.**

| Line | Basis | Cost |
|---|---|---|
| Direct fetches (~3,400) | free | $0.00 |
| Exa `/search` for discovery + derived-only (~250 calls) | $7 / 1k requests | ~$1.75 |
| Exa extra results above 10 (~1,500) | $1 / 1k results | ~$1.50 |
| Exa `/contents` where origin refuses (~300 pages, text only) | $1 / 1k pages per content type | ~$0.30 |
| Exa `deep-reasoning` for ~15 synthesis questions | $15 / 1k requests | ~$0.23 |
| Reddit API | free tier | $0.00 |
| Fleet orchestration tokens (6 agents, code-writing not content-reading) | Opus 5 $5/$25 per MTok | ~$25–40 |
| **Phase 1 acquisition total** | | **~$30–45** |
| Distillation of the seed corpus (§4, batched) | see §4.6 | **~$15–30** |
| **Phase 1 all-in** | | **~$45–75** |

(For scale: the ARV2 smoke test ran 124 provider calls for **$0.507** in 10.4 provider-minutes with
0 blocked fetches. The acquisition fleet is the same shape of work, one order of magnitude wider,
and its dominant cost is *our own agent tokens*, not provider spend.)

### 2.2 Phase 2 — expansion (weeks 2–4, ~2 days of compute)

**Goal:** 10,000–12,000 documents; depth where Phase 1 found signal; the first eval set.

| Agent | Charter |
|---|---|
| **E1 — long-tail creator sweep** | 40 more newsletters/blogs found by citation-mining Phase 1 (who do the good posts cite?), not by SEO search — the smoke test's G9 finding is that generic ICP search returns 100% vendor SEO |
| **E2 — podcast back-catalogue** | All episodes of the 6 transcript-publishing shows + up to 20 Whisper-transcribed hours ($7.20) of the highest-value transcript-less show, founder-picked |
| **E3 — ATS longitudinal** | Re-pull the 300 companies weekly to build *change* records (a req that stays open 105 days is the signal — Zafran); adds the time dimension no competitor has |
| **E4 — exemplar miner** | Pull the actual artifacts out of the corpus: real cold emails quoted in posts, real sequences, real case-study skeletons; structure-abstract anything from a restricted class |
| **E5 — adversarial/negative miner** | What buyers say they hate: podcast Q&A segments, review snippets via Exa, rejected-draft postmortems from C13, plus the founder's Reddit reading notes (C5, human-sourced). Feeds the anti-slop eval set |
| **E6 — curator** | Dedup, cross-phase merge, corpus report v2, coverage gaps |

**Wall-clock:** ~14 hours of fleet time spread over 3 weeks. **Cost:** ~$90–160 acquisition
(dominated by orchestration tokens and the Whisper option) + ~$60–110 distillation.

### 2.3 Phase 3 — standing freshness (ongoing)

One scheduled agent, weekly:

- Delta-crawl every C1/C2 feed and sitemap (`If-Modified-Since` + `lastmod`), C7 feeds, C12 boards.
- Re-run the ~30 Exa discovery queries with a 7-day recency window.
- Re-validate a 5% sample of stored URLs (link rot → mark `source_gone: true`, keep the record and
  the quote, flag any assertion depending solely on it).
- Emit a weekly diff report: N new docs, N new candidate assertions, N assertions whose sole source
  died, N assertions past TTL.

**Freshness TTLs by topic class** (mirroring the platform's freshness discipline):
tooling/deliverability **180d**, channel tactics **365d**, positioning/psychology/org design **730d**.
An expired assertion is not deleted — it is *re-queued for corroboration* and marked `stale: true`
in the skill pack until refreshed.

**Cost:** ~$10–25/month (mostly orchestration), ~1 founder-hour/month.

### 2.4 Deduplication strategy

Five layers, cheapest first. Layer 4 is the one that actually protects the distillation.

| L | Key | Method | Action on hit |
|---|---|---|---|
| L0 | `url_key` | lowercase host minus `www.`, path minus trailing slash, query filtered to an allowlist, no fragment, AMP suffix stripped | skip fetch entirely |
| L1 | `content_sha256` | sha256 over NFKC-normalized, whitespace-collapsed, boilerplate-stripped text | keep first, record `duplicate_of` |
| L2 | near-duplicate | MinHash-LSH over 5-gram shingles, Jaccard ≥ 0.85 (`datasketch`) | keep the longest/earliest, cluster the rest |
| L3 | cross-platform syndication | embedding cosine ≥ 0.93 within ±30 days **and** same author | keep the **origin** copy (blog > newsletter > LinkedIn), link the rest |
| L4 | **assertion-level** | `assertion_key = uuid5(NS, normalized_assertion_text)` at distillation | merge; **corroboration counts distinct `(registrable_domain, author)` pairs, not documents** |

L4 exists because of a specific failure mode: one consultant publishes the same idea on their blog,
their newsletter, and LinkedIn. Counting documents would make that look like three-source
corroboration. Counting distinct (domain, author) pairs makes it one. This is the corpus analogue of
the platform's identity-resolution rule — everything keys on a resolved identity, never a string.

---

## 3. Corpus format & storage

### 3.1 Repository layout

Git holds the *citable spine*; blobs live in the platform's existing object storage
(`CLUE_STORAGE_BACKEND` / `CLUE_STORAGE_FS_ROOT` / S3 — reuse, don't reinvent), content-addressed
exactly like the platform's artifact store.

```
corpus/
  manifest.yaml                  # source registry: domain, route, robots-checked-at, cadence,
                                 #   terms_class, retention_class, commercial_interest, enabled
  index/
    documents.jsonl              # ONE LINE PER DOCUMENT — committed (metadata only, no body)
    observations.jsonl           # derived-only records (C3/C4/C5/C9) — committed
    duplicates.jsonl             # duplicate_of edges + cluster ids — committed
  derived/
    assertions.jsonl             # distilled assertions with source_ids + evidence spans
    conflicts.jsonl              # contradictory assertion pairs awaiting founder ruling
    exemplars.jsonl              # exemplar records (structure-abstracted where required)
  text/                          # GITIGNORED — mirrored to object storage
    <sha256[:2]>/<sha256>.txt    # content-addressed body, one file per document
  reports/
    corpus-report-<date>.md      # counts, coverage, failures, link rot
  .state/
    fetch-cursors.json           # per-source last-modified / last-seen cursors
```

**Why metadata-in-git, bodies-out:** the index is small, diffable, reviewable, and is the thing that
makes every citation resolvable in a code review. The bodies are large, legally sensitive, and
belong behind the same storage seam as the platform's evidence blobs. `text/` is in `.gitignore`;
`make corpus-sync` pushes/pulls it.

### 3.2 Document record schema

```json
{
  "doc_id": "uuid5(NS_CORPUS, url_key)",
  "url_key": "coldiq.com/blog/tavily-vs-exa",
  "source_url": "https://coldiq.com/blog/tavily-vs-exa",
  "canonical_url": "https://coldiq.com/blog/tavily-vs-exa",
  "source_key": "coldiq_blog",
  "platform": "blog|newsletter|linkedin|x|reddit|youtube|podcast|casestudy|review|repo|paper|ats|firstparty",
  "doc_type": "how_to|teardown|framework|cold_email_example|case_study|thread|transcript|show_notes|system_prompt|paper|job_ad|internal_run",
  "author": {"name": "…", "handle": "…", "org": "…", "is_personal_data": true},
  "published_at": "2026-06-14",
  "fetched_at": "2026-08-31T20:41:09Z",
  "fetch_route": "direct|rss|sitemap|exa_search|exa_contents|reddit_api|ats_api|podcast_rss|hf_dataset|internal",
  "http_status": 200,
  "text_ref": "corpus/text/9f/9f3c…c81.txt",
  "text_sha256": "9f3c…c81",
  "words": 1830,
  "token_estimate": 2440,
  "verbatim": true,
  "retention_class": "verbatim_ok|derived_only|quote_only",
  "terms_class": "open_web_published|platform_restricted|licensed_index|first_party|licensed_dataset",
  "license_note": "Publicly published vendor blog post; stored internally for retrieval; public use limited to ≤25-word quotation with attribution.",
  "robots_allowed": true,
  "robots_checked_at": "2026-08-31",
  "quote_budget_words": 25,
  "commercial_interest": true,
  "pii": {"contains_personal_data": true, "basis": "legitimate_interest",
          "retention_until": "2028-08-31", "subject_keys": ["sha256:…"]},
  "quality": {"lang": "en", "boilerplate_ratio": 0.08, "readability_ok": true},
  "dedup": {"content_sha256": "9f3c…c81", "cluster_id": "c-0412", "duplicate_of": null},
  "corpus_version": "2026-09"
}
```

An **observation record** (derived-only classes) replaces `text_ref` with:

```json
{"observation": "Opens with the prospect's own job-ad language, no product mention until line 4.",
 "quote": "we're hiring someone to own account-based everything",
 "quote_words": 8,
 "verbatim": false, "retention_class": "derived_only"}
```

**Invariants enforced at ingest (the R2 gate):** `source_url` present and absolute ·
`fetched_at` present · `terms_class` ∈ enum · `retention_class` consistent with the source
manifest · `verbatim == (retention_class == "verbatim_ok")` · a `derived_only` record has **no**
`text_ref` and `quote_words ≤ quote_budget_words` · `robots_checked_at` within 90 days.
Violations are **deleted**, not quarantined — quarantines rot into shadow corpora.

### 3.3 Chunking

- **Prose (C1, C2, C7, C8, C11):** heading-aware semantic chunks of **800–1,200 tokens** with
  **100-token overlap**; never split mid-list or mid-code-block. `chunk_id = "{doc_id}#{ordinal}"`,
  with `char_start`/`char_end` so every quote resolves to an exact span in the stored text — the
  corpus analogue of an evidence span.
- **Atomic documents (job ads, cold-email exemplars, system prompts, observations):** one chunk.
  Chunking a cold email destroys the thing that makes it an exemplar.
- **Transcripts:** chunk on speaker-turn boundaries up to 1,200 tokens; keep timestamps in metadata
  so a quote can cite `[42:15]`.
- Chunking is **derived, not stored in git** — it's regenerated by `make corpus-chunks` from the
  bodies, so we can change chunk policy without a corpus migration.

### 3.4 The four consumers

**(a) Distilled knowledge packs inside agent skills.** The primary consumer.

```
skills/head-of-abm/
  SKILL.md                       # ≤500 lines; routes to the packs (progressive disclosure)
  knowledge/
    icp-and-tiering.md           # each ≤2,500 tokens
    signal-reading.md
    committee-and-personas.md
    cold-email-craft.md
    multichannel-plays.md
    measurement-and-reporting.md
    anti-patterns.md
    sources.jsonl                # assertion_id → {assertion, tier, corroboration, doc_ids, ttl}
```

Every line of a pack that asserts something carries a bracketed id:

```markdown
- Lead with the account's own published language (job ads, careers pages, earnings calls) rather
  than a category claim; buyers recognize their own words and discount ours. [A-0142]
- A requisition left open >90 days is a stronger buying signal than a funding round. [A-0087]
```

and `sources.jsonl`:

```json
{"assertion_id":"A-0142","assertion":"Lead with the account's own published language…",
 "tier":"practice","corroboration":4,"independent_domains":4,"non_vendor_sources":2,
 "doc_ids":["…","…","…","…"],"spans":[{"doc_id":"…","char_start":4192,"char_end":4310}],
 "first_seen":"2026-09-02","ttl_days":730,"stale":false}
```

**(b) Few-shot exemplar libraries.** Real artifacts, annotated with *why* they work, keyed by
situation (`persona`, `signal_type`, `channel`, `stage`). Two storage modes, decided by the source's
`retention_class`:
- `verbatim_ok` source → the artifact is stored as written, with attribution.
- `platform_restricted` source → **structure-abstracted**: we store the skeleton (opening move,
  evidence type, ask shape, length, tone markers) and a ≤25-word quote, never the copy. This is a
  legal requirement *and* a quality win — the agent should learn the pattern, not parrot a stranger's
  email into a client's campaign.

**(c) Eval / golden sets.** Built from the corpus and from C13 (our own runs):
- *Judgment set:* account fact-pack → expected persona/angle/next-best-action, founder-labelled.
- *Craft set:* situation → a founder-graded A/B of two drafts (the real training signal).
- *Anti-slop set:* seeded from `jjrussell10/storyscope` (MIT) + our own rejected drafts — detect and
  penalize AI-writing tells.
- *Negative fixtures:* fabricated-metric traps, misattributed-quote traps, stale-tactic traps
  (advice that was true in 2022 and isn't now). Mirrors the M9.6 golden-set discipline already in
  this repo: each mechanism gets a case it must fail on.

**(d) Optional future fine-tune.** The format above (JSONL, message-shaped exemplars, graded pairs)
keeps the option open at zero extra cost. See the verdict below.

### 3.5 Recommendation: skills + exemplars, **not** fine-tuning

**Verdict: do not fine-tune. Ship skill packs, exemplars, and retrieval.** Revisit only if all three
of the following become true: (i) a stable style objective survives three model upgrades unchanged,
(ii) we hold >2,000 human-graded pairs, and (iii) prompt length — not judgment — is the binding
constraint on cost or latency.

| Dimension | Skills + exemplars + retrieval | Fine-tune |
|---|---|---|
| **Provenance** | Every assertion cites a URL; the agent can show its work | Weights cannot cite. Silently unfalsifiable — the exact failure mode the platform was built to avoid |
| **Cost (year 1)** | ~$400–700 all-in (§6) | Data prep + training + eval harness + re-runs; realistically $5–15k equivalent for a 2-person team, most of it *time* |
| **Model-upgrade resilience** | A better model instantly makes the same packs better | Every upgrade strands the tune; you re-train or stay behind. Frontier models moved multiple times in the last 12 months |
| **Iteration latency** | Edit a markdown file, ship. Minutes | Re-train + re-eval. Days |
| **Correctability** | A wrong assertion is one line, one commit, with its sources | A wrong behavior is diffuse; you can only re-train |
| **Legal surface** | Storage + quoting posture (§5), no training-corpus question | Training on platform-restricted text is exactly what Reddit/LinkedIn/YouTube terms target |
| **Availability** | Works today on the models we already pay for | No first-party fine-tuning surface exists for current Claude models (the API surface is Messages / Batches / Files / Models / Managed Agents). A tune means an OSS model on another provider — a second stack for 2 people to run |
| **What it's actually good at** | Knowledge, judgment, structure, citation | Style/format compression, latency, and cost at very high volume — none of which is our bottleneck |

Two supporting facts make the skills route strictly better economically: **prompt caching** (cached
prefix reads bill ~0.1× and can cut repeated-context cost up to ~90%) makes large knowledge packs
nearly free after the first call, and the **Batch API's 50% discount** makes bulk distillation cheap.
The thing a fine-tune would buy us — "sounds less like AI" — is better bought by an exemplar library
plus an anti-slop eval, which is precisely what `blader/humanizer` (39.3k stars, MIT, a *skill*, not
a tune) demonstrates.

---

## 4. The distillation pipeline

Raw corpus → skill knowledge, with the platform's claim discipline applied to craft knowledge.
Six stages. The rule that makes it trustworthy: **an assertion with no verbatim evidence span
cannot be promoted.**

### 4.1 D0 — Ingest & classify (deterministic + cheap model)

Owner: code, with one cheap-model call per document.
- Normalize (readability extraction, boilerplate strip, NFKC, language detect; drop non-English).
- Dedup L0–L3 (§2.4).
- Classify `doc_type`, topic tags, and `commercial_interest` (vendor-authored? gated CTA? product
  named in the first 200 words?).
- Enforce the R2 invariants; delete violations; write `documents.jsonl`.

Model: **Claude Haiku 4.5** ($1 / $5 per MTok), Batch API (−50%), prompt-cached rubric prefix.

### 4.2 D1 — Assertion extraction (cheap model, high recall)

For each chunk, extract candidate assertions in a strict schema:

```json
{"assertion":"…", "scope":"cold_email|tiering|committee|measurement|…",
 "doc_id":"…", "char_start":4192, "char_end":4310,
 "evidence_span":"…verbatim text from the document…",
 "hedge":"claim|opinion|anecdote|data", "sample_size": null,
 "commercial_interest": true}
```

Hard rejects at parse time: no `evidence_span`; span not found byte-for-byte in the stored text
(the same check the faithfulness judge applies); assertion longer than 240 characters; assertion
that contains an instruction addressed to an agent (prompt-injection guard, §5.6).

Model: **Haiku 4.5**, batched. Expected ~2.5 candidate assertions per document.

### 4.3 D2 — Corroboration & promotion (mid model)

Cluster candidates by `assertion_key` (L4). Then apply promotion policy — **policy is data, not
code**, in `corpus/policy/promotion.yaml`:

| Tier | Rule | How it appears in a pack |
|---|---|---|
| `practice` | ≥2 **independent domains** (distinct registrable domain *and* distinct author) **and** ≥1 source with `commercial_interest: false` | stated flatly |
| `anecdote` | 1 source, or all sources commercially interested | stated **with inline attribution**: "ColdIQ reports that…" |
| `contested` | corroborated on both sides of a contradiction | goes to `conflicts.jsonl`, never into a pack unresolved |
| `rejected` | span check failed, off-topic, or duplicate | dropped |

The `commercial_interest` rule is the direct answer to smoke-test finding **G9** ("founder ABM-pain
search angle = 100% vendor SEO"). A vendor blog is an advertisement with a citation format; it can
*participate* in corroboration but can never carry it alone.

Model: **Claude Sonnet 5** ($3 / $15), batched.

### 4.4 D3 — Conflict surfacing (mid model, no auto-resolution)

Marketing advice is contradictory by nature ("never use merge tags" vs "personalize every field").
The pipeline **must not average contradictions into mush**. D3 detects opposing assertion pairs
within a scope and writes them to `conflicts.jsonl` with both evidence sets and a proposed framing
("this is context-dependent on X"). Only the founder resolves a conflict, and the resolution is
itself recorded as an assertion with the conflict as its provenance.

### 4.5 D4 — Founder review gate (human, batched, capped)

The gate is where a 2-person startup stays sane. Rules:
- Review is **batched by scope**, not by document, and **capped at 150 assertions per session**,
  ordered by (corroboration count × scope priority).
- The reviewer sees: the assertion, its tier, the count of independent domains, and **the top 2
  evidence spans with links** — never the raw corpus.
- Four verbs: **approve · edit · demote · reject** (reject requires a one-line reason, which is
  itself stored — rejections are training data).
- Everything unreviewed stays out of the shipped pack. An unreviewed corpus is not a liability;
  an unreviewed *skill* is.
- Expected load: ~2.5 hours for the Phase 1 seed, then ~30 minutes/week.

### 4.6 D5 — Versioned skill release

- A release is a commit: pack markdown + `sources.jsonl` + a CHANGELOG entry naming what changed
  and why, versioned `head-of-abm/knowledge@MAJOR.MINOR.PATCH`.
- **CI gate `make corpus-check`** (fails the build):
  1. every `[A-####]` in every pack resolves in `sources.jsonl`;
  2. every assertion's `doc_ids` resolve in `index/documents.jsonl`;
  3. every `practice`-tier assertion satisfies the promotion policy (≥2 independent domains, ≥1
     non-vendor) — recomputed, not trusted;
  4. every evidence span still matches the stored text byte-for-byte;
  5. no pack exceeds its token budget;
  6. no assertion is past TTL without `stale: true`.
- **Rollback is a git revert.** That is the whole disaster-recovery plan, and it is enough.

**Distillation cost (Phase 1, ~3,500 docs ≈ 7M tokens of input):**

| Stage | Model | Tokens | List cost | Batched (−50%) |
|---|---|---|---|---|
| D0 classify | Haiku 4.5 | 7.0M in / 0.5M out | $9.50 | **$4.75** |
| D1 extract | Haiku 4.5 | 7.0M in / 2.5M out | $19.50 | **$9.75** |
| D2/D3 corroborate + conflict | Sonnet 5 | 1.4M in / 0.8M out | $16.20 | **$8.10** |
| D5 pack authoring | Opus 5 | 0.3M in / 0.15M out | $5.25 | n/a (interactive) |
| **Total** | | | **~$50** | **~$28** |

Use the Batch API for D0–D3 (they are not latency-sensitive) and prompt caching on every rubric
prefix. Phase 2's larger corpus roughly triples this; Phase 3's weekly delta is ~$3–8/week.

---

## 5. Risks & legal

Not legal advice; a set of operating rules with citations, to be reviewed by counsel before any
public product claim depends on the corpus.

### 5.1 Platform ToS realities (verified quotes)

| Platform | Verified language / behavior | Our posture |
|---|---|---|
| **LinkedIn** | UA §8.2: no "software, devices, scripts, robots … to scrape or copy the Services"; and no copying/using/displaying info obtained "whether directly or **through third parties (such as search tools or data aggregators or brokers)**" | No fetcher touches linkedin.com. Derived-only records, ≤25-word quotes, links out. We treat the third-party clause as reaching indexes, so we never bulk-store even indexed copies |
| **YouTube** | ToS: no access "using any automated means (such as robots, botnets or scrapers)" except search engines per robots.txt or written permission. Developer Policies **III.E.6**: must not "scrape YouTube Applications … or obtain scraped YouTube data or content". **III.E.4.c/d**: stored API data must be deleted/refreshed within **30 calendar days** | Default OFF (§8-D1). The 30-day rule alone makes a durable YouTube transcript corpus non-compliant even via the official API |
| **Reddit** | `robots.txt` = `Disallow: /`; `.json` → 403 on any UA; old.reddit → login wall. Developer Terms **§4.2** (no AI-model training without permission), **§3.3** (propagate deletions "as soon as possible"), **§7.3** (retention limits), **§5.2** (link + username attribution). Public Content Policy: non-commercial only, "talk to us if you have commercial purposes". Litigating scraping on **state-law** theories that survived copyright preemption (Reddit v. Anthropic, remanded Mar 2026) and on **DMCA §1201** against *indirect* harvesting (Reddit v. Perplexity/SerpApi/Oxylabs, SDNY) | **No automated acquisition, no stored Reddit content.** Human reading → first-party notes with permalinks; ≤15-word quote with username if quoted at all. Re-open only via a licence |
| **X** | ToS prohibits scraping; direct fetch returns 402 to us | Derived-only via indexed copies; no fetcher touches x.com |
| **G2** | robots.txt is permissive but review pages return 403 (edge bot-management); ToS prohibits scraping; they sell licensed data | Skipped in bulk. No stealth fetching to defeat a deliberate block |
| **Exa (our index)** | ToS §4.2(a): may not "copy … or **create derivative works from** … any information contained on, or obtained from or through, the Services" except browser cache "or as otherwise expressly permitted … by us in writing". §1.2(b): **the customer** warrants its use doesn't breach third-party terms. §7.1.2/§7.3: Exa disclaims third-party IP liability and the customer indemnifies. §4.2(f): no competitive product. Also: Exa honors robots.txt/`noindex` (`ROBOTS_FILTER_FAILED`) | **Origin-fetch rule (R3).** Exa for discovery/ranking; persisted text comes from origins. Where we must persist Exa-retrieved text, we hold it as derived-only until written permission exists (§8-D3). Note §1.2(b) means using a licensed index does **not** transfer the underlying-site ToS risk to Exa |

**Two corrections to prior assumptions, both important:** (1) Exa is **not** a bot-wall bypass — it
respects robots.txt and `noindex`, so a site that blocks us (6sense, G2) or forbids all crawling
(Reddit) is likely unavailable through Exa too; (2) Exa's public docs do **not** claim LinkedIn
*post*, X, Reddit, or YouTube coverage (only 1B+ people profiles and 50M+ company pages), so
LinkedIn-post retrieval — which we have observed working in live runs — is a best-effort bonus, not
a plannable input.

### 5.2 Copyright posture: quoting vs storing vs training

Three legally distinct acts; we do the first two and not the third.

- **Quoting** short excerpts with attribution and a link, for commentary/analysis: the strongest
  position. Our ≤25-word budget with citation is deliberately conservative.
- **Storing** full text internally for retrieval and analysis: reasonable for lawfully-accessed,
  robots-permitted, publicly-published pages; the crux is *how the copy was acquired*. **Bartz v.
  Anthropic** (Alsup, **2025-06-23**) is the cleanest available signal: training on **lawfully
  acquired** books was held to be fair use, while retaining **pirated** library copies was not —
  and the case settled for **$1.5B** (Sept 2025; final approval July 2026). The operative lesson for
  us is not about training at all: **acquisition legality is the pivot.** Hence R2/R3, robots
  compliance, no paywall circumvention, no stealth fetching of deliberate blocks.
- **Training.** Not doing it (§3.5). This also moots the hardest questions — *Thomson Reuters v.
  Ross* (Feb 2025; no fair use for a non-generative tool that competed with the source —
  **UNVERIFIED** in detail here, WebSearch budget exhausted), the EU DSM Art. 4 TDM opt-out and
  machine-readable reservations, and the EU AI Act's GPAI training-data transparency duties
  (**UNVERIFIED**). If a fine-tune is ever revisited, this section must be re-opened first, and the
  corpus filtered to `terms_class ∈ {open_web_published, first_party, licensed_dataset}` only.

**Rules that fall out of this:**
1. Never bypass a paywall, login, or a deliberate bot block.
2. Never store a document acquired in violation of a robots directive.
3. Never redistribute a stored document, in whole or in substantial part.
4. Public outputs quote ≤25 words with attribution + link (per-source override in the manifest).
5. `commercial_interest` sources may inform but never solely support a `practice`-tier assertion.

### 5.3 The "never store what we can't cite" rule, operationally

R2 is enforced in three places so it cannot rot: (i) the ingest validator deletes non-conforming
records; (ii) `make corpus-check` fails CI if any shipped assertion's citation doesn't resolve;
(iii) the weekly freshness agent re-validates a 5% URL sample and flags assertions whose sole source
has died. A dead source does **not** silently disappear — it flips the assertion to `stale: true`
and the pack renders it with a "source no longer reachable" marker until re-corroborated.

### 5.4 The GPL/leaked-prompt hazard (C10)

`x1xhlol/system-prompts-and-models-of-ai-tools` is **GPL-3.0** and contains third-party prompts of
uncertain provenance. GPL obligations attach on *distribution*, and our skills ship inside a
product. **Rule: read for patterns, never paste.** Pattern notes are written in our own words and
cite the file. Anthropic's officially published system prompts may be quoted (≤25 words, cited).
`blader/humanizer` and `jjrussell10/storyscope` are MIT — usable with attribution, and the
StoryScope HF dataset (MIT, 10K–100K rows, parquet) is directly ingestible as an eval seed.

### 5.5 PII handling for creator content

Creator posts are **personal data** about identifiable people. Posture:
- **Lawful basis:** legitimate interest (craft research), documented in `corpus/manifest.yaml` with
  a short balancing note per source class. **UNVERIFIED:** current ICO/EDPB web-scraping guidance
  specifics — WebSearch budget exhausted; have counsel confirm the LIA wording before Phase 2.
- **Minimization:** for derived-only classes we store the observation, the ≤25-word quote, the URL,
  and the author's *public professional identity* — never contact details, never inferred attributes,
  never anything special-category. If an observation works without the name, drop the name.
- **Retention:** 24-month ceiling on creator-attributed records (`pii.retention_until`), then either
  re-verify or drop. Reddit records inherit the platform's deletion expectations (quarterly
  permalink re-check; 404 → purge).
- **Erasure:** a `subject_keys` field (salted hashes) makes "delete everything about this person"
  a query, not an archaeology project. Handle requests at `team@cluehq.ai` within 30 days.
- **Hard separation from the product:** corpus PII never enters the claim store, never becomes a
  lead, never appears in a client deliverable except as an attributed ≤25-word quote (R1).

### 5.6 Prompt injection and corpus poisoning

The corpus is **untrusted input** — it is open-web text that an adversary can author.
- Distillation prompts **fence** document text with explicit markers and instruct the model to treat
  it as data, never instructions (the same mitigation the faithfulness judge already uses).
- D1 auto-rejects any candidate assertion phrased as an instruction to an agent.
- SEO-slop poisoning is handled by the `commercial_interest` rule and by *citation-mining* for
  Phase 2 expansion instead of keyword search (smoke-test G9: generic ICP search returned 100%
  vendor SEO and competitors' blogs).
- No corpus text is ever executed, and no corpus URL is auto-fetched from inside a distillation
  prompt.

### 5.7 Operational risks

| Risk | Mitigation |
|---|---|
| Source rot / link death | weekly 5% re-validation; `source_gone` flag; assertions flip to `stale` |
| Over-fitting to vendor marketing | `commercial_interest` promotion rule; non-vendor corroboration requirement |
| Corpus becomes a second source of truth | R1 seam; corpus imports nothing from the research subsystem and never writes claims |
| Founder review becomes the bottleneck | capped batches (150), priority ordering, unreviewed → not shipped |
| Silent drift between pack and sources | `make corpus-check` recomputes promotion policy on every CI run |
| A platform changes its terms | `manifest.yaml` carries `robots_checked_at` + `terms_reviewed_at`; the weekly agent flags anything older than 90 days |
| Cost surprise | every fleet run reports provider spend; Exa QPS caps (10 QPS `/search`) and per-host rate caps are configured, not hoped for |

---

## 6. Cost & time summary

| Phase | Agents | Wall-clock | Founder time | Acquisition $ | Distillation $ | Phase total |
|---|---|---|---|---|---|---|
| **Phase 1 — seed** (~3,000–4,000 docs) | 6 (2 waves of 3) | ~6–8 h unattended | ~3.5 h (1 h checkpoint + 2.5 h review) | $30–45 | $15–30 | **$45–75** |
| **Phase 2 — expansion** (~10–12k docs) | 6 | ~14 h over 3 weeks | ~6 h | $90–160 | $60–110 | **$150–270** |
| **Phase 3 — standing freshness** (per month) | 1 scheduled | ~1 h/week | ~1 h/month | $6–15 | $4–10 | **$10–25/mo** |
| **Year 1 total** | | | ~30 h | | | **≈ $400–700** |

Unit economics behind the table (all verified in §7):

| Unit | Cost | Latency |
|---|---|---|
| Direct origin GET | $0.00 | 0.22 s (measured, smoke test) |
| ATS API call (Ashby/Greenhouse/Lever) | $0.00 | 1.3 s (measured) |
| Podcast RSS + transcript fetch | $0.00 | ~1 s |
| Reddit Data API call (free tier) | $0.00 | ~0.5 s |
| Exa `/search` | $0.007 (+$0.001/result above 10) | ~1–3 s |
| Exa `/contents` | $0.001 per page **per content type** | ~1 s |
| Exa `deep-reasoning` search | $0.015 | 46.3 s (measured) |
| Whisper transcription | $0.006/min = **$0.36/audio-hour** | — |
| Haiku 4.5 distillation | $1 / $5 per MTok (−50% batched) | — |
| Sonnet 5 corroboration | $3 / $15 per MTok (−50% batched) | — |

**Reference point:** the ARV2 smoke test ran **124 provider calls for $0.507** in **10.4
provider-minutes**, 0 blocked fetches. The entire Phase 1 acquisition budget is roughly *sixty* such
smoke tests, and the dominant line item is our own agent tokens — which is why the "agents write
fetchers, they don't read corpora" rule (§2) is a cost control, not a style preference.

---

## 7. Verification register

Everything below was checked during this session on **2026-08-31**. Method codes: **[C]** = live
`curl`/HTTP probe from this workspace with UA `clue-corpus-research/0.1 (+https://cluehq.ai;
team@cluehq.ai)`; **[F]** = WebFetch of the primary document; **[A]** = delegated verification agent
with primary-source quotes; **[L]** = local command; **[R]** = repo evidence.
The session's **WebSearch budget was exhausted (200/200)** partway through, which is why several
case-law and secondary-source items below are marked UNVERIFIED — they need a follow-up pass.

### 7.1 Acquisition routes

| # | Claim | Method | Result |
|---|---|---|---|
| V1 | `coldiq.com/sitemap.xml` fetchable | [C] | **200**, 1.16 MB, **6,306 URLs**, **378** under `/blog/` |
| V2 | ColdIQ article pages fetchable | [C] | `coldiq.com/blog/tavily-vs-exa` → **200**, 235 KB |
| V3 | `coldiq.com/blog/rss.xml` | [C] | **404** — use the sitemap, not RSS |
| V4 | Clay / lemlist / Gong / Demandbase blogs open | [C] | all **200** |
| V5 | HubSpot marketing RSS open | [C] | **200**, 2.4 MB |
| V6 | 6sense blog blocked | [C] | **403**, Cloudflare "Just a moment…" interstitial |
| V7 | gtmnow.com feed blocked | [C] | **403 Forbidden** |
| V8 | Substack RSS is full-text | [C] | `lennysnewsletter.com/feed` → 20 items, 20 `<content:encoded>` blocks, **avg 18,926 chars** |
| V9 | Substack custom-domain `/feed` is not universal | [C] | `growthunhinged.com/feed` → **404** (resolve per publication) |
| V10 | `saastr.com/feed/` open | [C] | **200**, valid RSS |
| V11 | Reddit robots.txt | [C] | **200** — `User-agent: *` / **`Disallow: /`** + Public Content Policy link |
| V12 | Reddit `.json` route (www) | [C][A] | **403** with a descriptive UA **and** with a Chrome UA — not a UA problem; 403 body is the HTML web shell |
| V13 | Reddit `.json` route (old.reddit) | [C][A] | **302 → `/login/?reason=lor2…`**; `old.reddit.com/r/<sub>/` also 302s to login |
| V13a | Reddit anonymous routes that still work | [A] | `www.reddit.com/r/<sub>/` HTML → 200; `/r/<sub>/.rss` → 200 (the last open no-auth route) |
| V13b | old.reddit login wall is policy, not accident | [A] The Verge, ~2026-06-30 | Reddit: the logged-out old-Reddit experience is "a significant source of abusive scraping and automated traffic"; **no shutdown date announced** |
| V13c | Reddit free tier exists and its shape | [A] Reddit Data API Wiki | **100 QPM per OAuth client id** (10-min averaging); "Traffic not using OAuth or login credentials will be **blocked**"; mandatory UA format `<platform>:<app ID>:<version> (by /u/<user>)`; "**NEVER lie about your User-Agent**" |
| V13d | Reddit requires prior approval | [A] Responsible Builder Policy (updated ~mid-2026) | "You must request access and get explicit approval before accessing any Reddit data" |
| V13e | Pushshift is moderator-only; successors are unlicensed | [A] | Pushshift access "limited to moderation use cases only", 24-hour tokens; Arctic Shift / Watchful1 dumps state **no data license**; HF Reddit corpora carry **uploader-asserted** CC-BY/MIT/ODC-BY that Reddit never granted, and none propagate deletions |
| V14 | Greenhouse public board API needs no auth | [C] | `boards-api.greenhouse.io/v1/boards/stripe/jobs` → **200**, 363 KB JSON |
| V15 | Ashby posting API needs no auth | [C] | `api.ashbyhq.com/posting-api/job-board/ramp` → **200**, 2.3 MB JSON |
| V16 | Lever API rejects guessed slugs | [C] | `api.lever.co/v0/postings/netflix` → **404 `{"ok":false,"error":"Document not found"}`** — corroborates smoke-test G6 |
| V17 | iTunes Search API is free/no-auth and returns `feedUrl` | [C] | **200** JSON with `collectionName` + `feedUrl` for every query |
| V18 | Podcasting 2.0 transcripts exist in real B2B feeds | [C] | 10 feeds sampled: Full-Funnel B2B **223** tags, Demand Decoded **52**, Demand Generation Club **43**, 7 others 0 → **~30% coverage** |
| V19 | A `<podcast:transcript>` URL actually serves text | [C] | `transcription.spreaker.com/...srt` → **200**, speaker-labelled SRT; `.txt` and `.vtt` also offered |
| V20 | Podcast Index API needs auth | [C] | **401** "Authorization header value either not set or blank" (free key + SHA-1 auth; iTunes route avoids it) |
| V21 | Clay / Demandbase case-study pages open | [C] | both **200** |
| V22 | G2 robots.txt is permissive | [F] | allows GPTBot/ClaudeBot/Google-Extended/CCBot; blocks wget/HTTrack et al. |
| V23 | G2 review pages block us anyway | [C] | `g2.com/products/salesforce-sales-cloud/reviews` → **403** (edge bot-management) |
| V24 | `x1xhlol/system-prompts…` repo facts | [F] GitHub API | **143,261 stars**, license **GPL-3.0**, 1,524 KB, pushed **2026-08-11** |
| V25 | `blader/humanizer` | [F] GitHub API | **MIT**, 39,310 stars, pushed 2026-08-19 |
| V26 | `jenna-russell/storyscope` | [F] GitHub API | **MIT**, 181 stars, pushed 2026-04-22 |
| V27 | StoryScope HF dataset | [C] HF API | `jjrussell10/storyscope`, license **mit**, **10K<n<100K**, parquet train/val/test/dev |
| V28 | `raw.githubusercontent.com` fetch works | [C] | **200** on the repo README |
| V29 | yt-dlp available locally | [L] | `uvx yt-dlp --version` → **2026.08.19** |
| V30 | Workspace holds the needed keys | [R] | `.env` contains `CLUE_EXA_API_KEY`, `CLUE_OPENROUTER_API_KEY`, `CLUE_PARALLEL_API_KEY`, `CLUE_FIRECRAWL_API_KEY` (names only inspected; no values read) |

### 7.2 Costs, limits, and terms

| # | Claim | Method | Result |
|---|---|---|---|
| V31 | Exa `/search` price | [A] exa.ai/docs/reference/pricing | **$7 / 1k requests**, base covers **10** results; **$1 / 1k results** above 10 |
| V32 | Exa `/contents` price | [A] | **$1 / 1k pages, per content type** (text / highlights / summary each bill) |
| V33 | Contents ride free inside `/search` | [A] | "no extra charge up to 10 results per search" — prefer `/search`-with-contents over standalone `/contents` |
| V34 | Exa deep search prices | [A] | `deep-lite` **$12/1k**, `deep` **$12/1k**, `deep-reasoning` **$15/1k** |
| V35 | Exa has **no** `/research` endpoint | [A] | Removed 2026-05-01; deep research = `POST /search` with `type: deep\|deep-reasoning` |
| V36 | Exa rate limits | [A] | `/search` **10 QPS**, `/contents` **100 QPS**, `/answer` 10 QPS; custom QPS is Enterprise |
| V37 | Exa honors robots.txt / `noindex` | [A] | `ROBOTS_FILTER_FAILED` 403 on `/contents`; FAQ: a `noindex` page is not crawled → **not a bot-wall bypass** |
| V38 | Exa ToS restricts storing/deriving from retrieved info | [A] Exa_Labs_Terms_of_Service.pdf §4.2(a) | "may not … copy … or **create derivative works from** … any information … obtained from or through, the Services" except browser cache "or as otherwise expressly permitted … in writing" |
| V39 | Exa pushes third-party ToS/IP risk to the customer | [A] §1.2(b), §7.1.2, §7.3 | customer warrants no breach of third-party terms; Exa disclaims third-party IP liability; customer indemnifies |
| V40 | Exa documents **no** LinkedIn-post / X / Reddit / YouTube index coverage | [A] (absence across full docs corpus) | Only `people` (1B+ profiles) and `company` (50M+ pages); social-post coverage appears only via the third-party Fiber.ai Connect partner |
| V41 | Exa `livecrawl` string is deprecated | [A] | use `maxAgeHours` (−1…720); don't send both |
| V42 | LinkedIn UA §8.2 anti-scraping + third-party clause | [F] linkedin.com/legal/user-agreement | verbatim quotes in §5.1 |
| V43 | hiQ v. LinkedIn outcome shape | [F] Wikipedia | CFAA claim failed (public data); **hiQ breached the User Agreement** (Nov 2022) and settled → contract, not statute, is the live constraint |
| V44 | YouTube ToS automated-access ban | [F] youtube.com/t/terms | no "automated means (such as robots, botnets or scrapers)" except search engines per robots.txt or written permission |
| V45 | YouTube Developer Policies anti-scraping | [F] III.E.6 | "must not … scrape YouTube Applications … or **obtain scraped YouTube data or content**" |
| V46 | YouTube API 30-day storage cap | [F] III.E.4.c/d | authorized data "no longer than **30 calendar days**"; same for non-authorized data |
| V47 | Bartz v. Anthropic holding + settlement | [F] Wikipedia | Alsup **2025-06-23**: training on lawfully acquired copies = fair use; **pirated** library copies not; **$1.5B** settlement Sept 2025, final approval July 2026 |
| V48 | Whisper transcription price | [F] developers.openai.com/api/docs/pricing | **$0.006/min** (whisper & gpt-4o-transcribe); **$0.003/min** gpt-4o-mini-transcribe |
| V49 | Claude model prices for distillation | [skill] claude-api | Haiku 4.5 **$1/$5**, Sonnet 5 **$3/$15**, Opus 5 **$5/$25** per MTok; Batch API **50%** discount; cached prefix reads ~**0.1×** |
| V50 | No first-party Claude fine-tuning surface | [skill] claude-api | Documented surfaces are Messages, Batches, Files, Token Counting, Models, Managed Agents — no fine-tuning endpoint; a tune means an OSS model on another provider |
| V50a | Reddit Developer Terms (eff. **2024-09-24**) — the four operative clauses | [A] redditinc.com/policies/developer-terms | **§4.2** no LLM/AI-model training "without our permission" · **§3.3** delete/modify your copy "as soon as possible" on user deletion · **§7.3** retention/deletion on request · **§5.2** link back + cite username + mark as from Reddit |
| V50b | Reddit Public Content Policy — commercial use is contract-only | [A] support.reddithelp.com PCP + TechCrunch 2024-05-09 | "you can use Reddit content for non-commercial uses … but talk to us if you have commercial purposes in mind"; "we enter into licensing arrangements" |
| V50c | Reddit v. Anthropic — theory and status | [A] natlawreview, loeb.com | Filed **2025-06-04**; five **state-law** claims (contract, unjust enrichment, trespass to chattels, tortious interference, UCL), **no copyright claim**; **2026-03-30** N.D. Cal. held them **not preempted** and remanded |
| V50d | Reddit v. Perplexity / SerpApi / Oxylabs / AWMProxy | [A] Search Engine Land, Bloomberg | Filed **2025-10-22** (S.D.N.Y.) over **indirect** harvesting from Google results; **DMCA §1201** anti-circumvention theory; amended complaint Feb 2026; SerpApi MTD Mar 2026, undecided |
| V51 | Measured smoke-test economics | [R] `docs/specs/ARV2-smoke-test-findings.md` | **124 calls / $0.507 / 10.4 provider-min / 0 blocked fetches**; direct fetch 0.22 s; AI Ark 1.3 s; Exa deep-reasoning 46.3 s; Scrapling needed **0 of 40** times |
| V52 | Repo's Exa spec numbers already match reality | [A][R] | `ARV2-account-research-rebuild-plan.md` search/deep/deep-reasoning/contents prices verified exact; **`ARV2-sources-and-variables-architecture.md:111` overstates `/contents` at $0.004** (actual $0.001/page/content-type) — worth a one-line correction |

### 7.3 Explicitly UNVERIFIED (follow-up required)

| # | Item | Why it matters | How to close |
|---|---|---|---|
| U1 | The **Data API Terms** body text (a separate document from the Developer Terms; the page is JS-rendered and defeated every retrieval route tried) | May impose caching/retention limits stricter than the Developer Terms | Open `redditinc.com/policies/data-api-terms` in a browser. **Only matters if D2 re-opens Reddit** — under the recommended posture (no automated acquisition) it is moot |
| U1a | Reddit policy quotes were retrieved via a text-extraction proxy (reddit.com and redditinc.com are blocked to our fetch tool) | High-fidelity but second-hand | Re-check verbatim in a browser before any of the §5.1 Reddit quotes appears in a customer-facing or legal document |
| U2 | YouTube `captions.download` ownership restriction | Determines whether a sanctioned transcript route exists at all | Fetch the Data API captions reference |
| U3 | LinkedIn v. Proxycurl outcome | Sharpens how far the "through third parties" clause reaches | Case-law search once WebSearch budget resets |
| U4 | Thomson Reuters v. Ross details; X Corp v. Bright Data; Meta v. Bright Data | Background risk framing only — none changes our posture | Same |
| U5 | EU DSM Art. 3/4 TDM opt-out mechanics; EU AI Act GPAI transparency duties | Only bind us if we ever fine-tune | Revisit only under §3.5's re-open conditions |
| U6 | ICO/EDPB web-scraping legitimate-interest guidance | Shapes the LIA wording for creator PII | Counsel review before Phase 2 |
| U7 | Substack/beehiiv ToS language on automated RSS consumption | Low risk (feeds are published for syndication) | Fetch both ToS pages |
| U8 | arXiv API and Semantic Scholar current rate limits | Sizing only for C11 | Fetch both API docs before the harvester runs |
| U9 | Exa Websets per-item API metering; the real `numResults` plan ceiling; whether §4.2(a) is waived in an Enterprise MSA | The last one is a **blocking legal question** for any persisted Exa text | Written request to Exa (§8-D3); live-key test for `numResults` |
| U10 | Whether Exa can return Reddit/6sense content at all given robots blocks | Decides if C5/blocked-C1 have any index fallback | One live probe each with the workspace key |

---

## 8. Founder decisions required before Phase 1 runs

- **D1 — YouTube posture.** Recommended: **default OFF** (§C6). YouTube's ToS bans automated access,
  its Developer Policies ban obtaining scraped YouTube data, and the 30-day storage cap defeats a
  durable corpus. Podcast RSS (C7) covers substantially the same practitioners legitimately. Override
  only with a written scope (own/permissioned channels, ≤150 videos, derived-only).
- **D2 — Reddit: confirm the "human-read only" posture.** Recommended: **no automated acquisition,
  no stored Reddit content** (§C5). The blocker is not technical — it is that the Public Content
  Policy makes commercial use contract-only and Developer Terms §4.2/§3.3/§7.3 bind storage and
  model use, with Reddit actively litigating both direct and *indirect* acquisition. Overriding this
  means opening a licensing conversation with Reddit, not writing a fetcher.
- **D3 — Write to Exa.** Two asks in one email: (a) written permission to persist retrieved page
  text and evidence spans (ToS §4.2(a)), and (b) the DPA (the public ToS §5.4 links to a literal
  `[LINK]` placeholder). Until (a) lands, R3's origin-fetch rule is not just preferred — it is the
  compliance boundary, and it also protects the *research* claim store, which persists Exa-derived
  evidence today.
- **D4 — Creator-PII retention ceiling.** Recommended 24 months with quarterly permalink
  re-validation. Confirm, and confirm `team@cluehq.ai` as the erasure contact.
- **D5 — Seed list ownership.** The founder picks the 15 blog domains, 15 newsletters, and 20
  podcasts. This is a 30-minute task with outsized leverage: the seed list *is* the agent's taste.

## 9. What this program is actually buying

Not "more data." Three specific things a competitor can't copy quickly:

1. **A cited craft memory.** Every piece of advice the Head of ABM agent gives can name the
   practitioner and the post it came from. That is the same bet the research subsystem makes about
   facts, applied to judgment — and it is checkable, which means it can be *improved*.
2. **A buyer-language corpus from job ads (C12).** 900 GTM requisitions is a dataset of buyers
   describing their own pain, with dates and URLs, that no scraper-based competitor bothers to build
   because it isn't glamorous. The smoke test already proved it moves rankings more than funding data.
3. **A compounding first-party loop (C13).** Every founder edit of an agent draft is a labelled pair.
   By month six that is the most valuable corpus in the building, and it costs $0 to collect —
   provided we start capturing it in Phase 1 rather than remembering to later.

