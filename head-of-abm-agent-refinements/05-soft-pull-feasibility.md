# 05 — Soft pull: what we can actually fetch, verified

**Date:** 2026-08-31 · **Method:** live probes from this session (each line below was actually attempted, not assumed), plus proven facts from the platform's prior live runs (the $0.51 cluehq.ai smoke test, the three ARV2 sample runs, the AI Ark canary). The six Opus research agents running in this session each append their own per-domain fetchability registers to their files (02, 03, 04, 06, 07, 08); this file is the consolidated verdict.

## 1. The probe results (wave 1, this session)

| Source | Probe | Verdict | Route that works |
|---|---|---|---|
| **ColdIQ blog** (`coldiq.com/blog`) | Direct fetch | ✅ **OPEN.** Full hub page readable, no bot-blocking, articles behind normal links. | Direct fetch / Exa contents. Full-article harvest is trivially feasible. |
| **LinkedIn** (`linkedin.com/company/coldiq/posts`) | Direct fetch | 🔒 **AUTH WALL.** Returns footer shell only. | **Exa index** (proven repeatedly in our live runs: it returned verbatim LinkedIn post text for Blumberg/Eliadis/Hoffman, profile career histories, the Erika Noll CEO confirmation). Also: creators' newsletter mirrors and personal sites carry the same content un-walled. Never scrape LinkedIn directly (ToS + wall). |
| **X / Twitter** (`x.com/karpathy`) | Direct fetch | 🔒 **HTTP 402.** Hard block. | Exa/Google-indexed copies, syndicated quotes in articles, creators' newsletters. Direct X data at scale = paid API only; not worth it for wave 1. |
| **Reddit JSON** (`reddit.com/r/ABM/top.json`) | Harness fetcher + browser-UA curl | ⚠️ **PARTIAL.** Harness fetcher refuses reddit.com; browser-UA curl gets the JS app shell, not JSON. | Official OAuth API (free tier, 100 QPM) or `.json` endpoints with a descriptive custom User-Agent, or `old.reddit.com`. Agent 08 pins the exact working recipe. Reddit content is fully public data; volume is modest. |
| **YouTube transcripts** | `uvx yt-dlp --version` | ✅ **WORKS LOCALLY** (yt-dlp 2026.08.19 via uvx, no install needed). | `yt-dlp --write-auto-subs --skip-download` per video for transcript harvest; episode/show-notes pages via Exa as the lighter first rung. |
| **github.com/jenna-russell/storyscope** | Direct fetch | ✅ **OPEN.** 61,608 stories, 304 narrative features, XGBoost human-vs-AI classifiers (93.2% accuracy), HuggingFace dataset available. | Direct + raw.githubusercontent.com + HF dataset download. |
| **github.com/blader/humanizer** | Direct fetch | ✅ **OPEN.** The 35 anti-AI-writing patterns (derived from Wikipedia "Signs of AI writing"), two-pass rewrite method, voice-matching. | Direct + raw files. Immediately usable as seed for our voice constitution. |
| **Anthropic published system prompts** | Direct fetch | ✅ **OPEN** (note: `docs.claude.com` 301-redirects to `platform.claude.com`; follow it). | Direct fetch of the release-notes/system-prompts page + the engineering blog. |
| **x1xhlol/system-prompts-and-models-of-ai-tools** | Direct fetch | ✅ **OPEN.** 143.3k stars, fresh (updated 2026-07). Folders incl. Cursor, Devin, v0, Manus, Windsurf, Warp, Perplexity, Anthropic. | Direct + raw.githubusercontent.com per file. |
| **developer.melissa.com / docs.melissa.com** | (prior session) | 🔒 Blocked. | Their GitHub OpenAPI specs (already used for the ARV2 Melissa contract). Not needed for this program; listed for completeness. |

## 2. Facts inherited from prior live runs (already paid for; do not re-learn)

- **Exa reads the walled gardens for us, legally-cleanly (licensed index):** LinkedIn posts and profiles, Facebook posts, Instagram, PDFs all came back with verbatim text in the ARV2 sample runs. This is the single most important acquisition fact: *the two most valuable ABM-creator platforms (LinkedIn, X) are auth-walled directly but reachable through the index we already pay for.*
- **Exa contents ≈ $0.004/page, search ≈ $0.007/query, deep-reasoning ≈ $0.02–0.03/call; bundling result text into search calls costs $0.000 extra.** The whole cluehq.ai smoke test (124 calls, 40 free fetches, 203 claims) cost $0.51.
- **Plain direct fetch beat expectations:** 40/40 un-blocked in the smoke test; Scrapling (stealth) was needed **zero** times and stays benched until a real 403 appears.
- **Free ATS APIs (Ashby/Greenhouse/Lever) are wide open** and were the star signal source. (Not central to *this* program, but the same lesson applies: look for the free structured API before scraping.)
- **The fetch ladder is ratified:** direct GET → free official API → Exa contents → Exa deep → stealth only on a real block.

## 3. Consolidated verdict for the training-data program

1. **Tier A (harvest now, full text, high volume):** ColdIQ blog + other agency blogs, Fullfunnel.io, creator newsletters (Substack/beehiiv are open web), the two GitHub anti-slop repos + HF dataset, the system-prompt corpus, Anthropic engineering posts, podcast show-notes pages.
2. **Tier B (harvest via Exa index, per-item, quote-with-citation):** LinkedIn posts of the creator roster, X threads, anything walled. Store verbatim text with source URL exactly like the claim store does; this mirrors the platform's own provenance discipline.
3. **Tier C (needs one small setup step):** Reddit (custom-UA or OAuth app), YouTube transcripts (yt-dlp works; per-channel batch).
4. **Tier D (do not touch directly):** LinkedIn/X direct scraping, Glassdoor/G2 bulk export. Quote what the index carries, per item, with citation.
5. **Licensing posture:** we are building (a) distilled knowledge skills, (b) small verbatim exemplar libraries with attribution, (c) eval sets. All three are quote-with-citation uses over public or index-licensed content, consistent with how the research product itself already operates. Bulk re-publication or model fine-tuning on scraped creator content is the only posture that would change the legal analysis; file 08 recommends against fine-tuning anyway.

## 4. What this means for "how deep can we go"

- **Depth is effectively unlimited on Tier A** (full-text, free or near-free).
- **Tier B depth is bounded by Exa's index coverage per creator**, which prior runs showed is good for active LinkedIn creators (recent posts included). Expect strong coverage of exactly the high-signal creators we want, weaker coverage of low-engagement accounts, which is fine.
- **The binding constraint is curation, not acquisition.** At ~$0.004–0.007 per item, a 5,000-item corpus costs roughly $25–35 of Exa spend plus agent time. The expensive step is distillation into skills and exemplars with founder taste applied, which is exactly where the multi-agent evaluate-what-they-bring-back loop (file 08) earns its place.

---

## 5. Wave-2 corrections (from the six deep-research agents; these override anything above that conflicts)

The six Opus agents ran hundreds of live probes after this file's wave-1 pass. Where they contradict wave 1, **they win** — each item below is verified in the named file:

1. **Reddit is OUT, and not for technical reasons.** The public `.json` API returns 403 on every UA across 10 subreddits (tested twice, independently — file 04), `robots.txt` is `Disallow: /`, the Public Content Policy makes commercial use contract-only, Developer Terms bar AI-model training, and Reddit is actively litigating both direct and indirect acquisition (v. Anthropic; v. Perplexity/SerpApi — file 08). Weak fallbacks exist (`.rss`, Arctic Shift academic dumps) but the ruling in file 08 stands: human reading → first-party notes only. r/coldemail is banned anyway.
2. **YouTube defaults OFF** despite yt-dlp working end-to-end (file 04 proved a real .vtt pull from Clay's channel): YouTube ToS bans automated access and the API policies cap stored data at 30 days (file 08). The legitimate substitute covers the same voices: **podcast RSS transcripts** — four B2B shows publish full machine-readable transcripts inside their feeds (Exit Five 259 episodes, GTMnow 257, Full-Funnel 223, Demandbase's The Prompt 218; verified downloads, file 04).
3. **The best routes are better than expected:** Substack full-text RSS (8 publications verified shipping complete article bodies, plus an undocumented `/api/v1/archive` backfill endpoint), sitemap harvests (clay.com 16,796 URLs; coldiq.com 6,306 with 378 blog posts), and Common Crawl coverage of fullfunnel.io/strategicabm (file 04).
4. **Exa: cheaper, but not a bypass.** Real pricing is ~$0.001/page contents (contents free inside `/search` for 10 results). But Exa honors robots.txt/noindex, its docs claim no LinkedIn-post/X/Reddit/YouTube index coverage, and its ToS bars derivative works from Exa-obtained text. Hence the **origin-fetch rule (R3, file 08): Exa discovers; persisted corpus text is fetched from the origin.** (LinkedIn-post text seen in past Exa deep-research runs is opportunistic synthesis, not a bulk route.) A written-permission ask to Exa is a queued founder decision.
5. **X: drop it.** 402s everywhere, logged-out HTML carries no tweet text, and the XCancel mirror got a cease-and-desist from X Corp on 2026-08-24 (file 04).
6. **LinkedIn: mirror-first.** Post bodies were unretrievable by every unauthenticated route file 04 tried; the working strategy is the creators' own mirrors (newsletters, personal sites, podcast appearances), documented as 7 ranked routes in file 04.
7. **Newly found blocks:** gtmnow.com and 6sense (403/bot-gated), momentumabm.com (504 on every attempt — retry later; it holds the category's legitimizing stats), thecmo.com (403), ColdIQ `/guides/*` email-gated at step 3 (steps 1–2 harvestable; policy call queued).
8. **Net effect on the program:** Phase 1 stays a one-day, ~$45–75, ~4,000-record harvest (file 08), with ~90% of it free direct fetch. The walled-garden problem dissolves because the same practitioners publish the same ideas on open surfaces: newsletters, podcasts, and blogs are the corpus; LinkedIn/X are merely where the ideas get promoted.
