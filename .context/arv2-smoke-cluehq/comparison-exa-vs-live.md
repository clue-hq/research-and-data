# A1 — Exa's index vs. the live site, on our own website

**Subject:** `https://www.cluehq.ai` (Clue's own marketing site — a very young company).
**Run date:** 2026-08-31. **Method:** every URL fetched twice — once by direct HTTP (`urllib`,
browser User-Agent), once through Exa (`/contents`, cached *and* force-livecrawled) — plus two Exa
searches to ask what the index actually holds. All raw responses in `raw/`.

---

## 1. The scoreboard

| Probe | Method | HTTP | Wall-clock | Cost | What came back |
|---|---|---|---|---|---|
| `www.cluehq.ai` (root) | live urllib + browser UA | **200** | **0.33 s** | $0.00 | 27,311 bytes of server-rendered HTML → 135 lines of visible text |
| `www.cluehq.ai` (root) | Exa `/contents`, cached | 200 | **0.34 s** | **$0.001** | 4,477 chars of clean markdown, `source: "cached"` |
| `www.cluehq.ai` (root) | Exa `/contents`, `livecrawl:"always"` | 200 | **1.32 s** | $0.001 | 4,477 chars, `source: "crawled"` — **byte-identical** to the cached copy (sha256 `3fa7b632…`) |
| "Clue cluehq.ai agentic ABM platform…" | Exa `/search` type=auto | 200 | 1.16 s | $0.007 | 10 results — **cluehq.ai is result #1** |
| "Clue agentic ABM platform" `includeDomains:[cluehq.ai]` | Exa `/search` | 200 | 1.12 s | $0.007 | **exactly 1 result** — the homepage. Nothing else on the domain is indexed. |
| `/privacy`, `/terms`, `/product`, `/how-it-works`, `/pricing`, `/about` | live urllib | **404 ×6** | 0.12–0.18 s each | $0.00 | 9-byte body. None of these pages exist. |

**Totals for A1:** 11 live fetches ($0.00, ~6 s) + 4 Exa calls ($0.016, ~4 s of provider time).

---

## 2. Is cluehq.ai in Exa's index at all? — **Yes, and it ranks #1.**

The neural search `"Clue cluehq.ai agentic ABM platform AI agents for account-based marketing"`
returned `https://cluehq.ai/` in **position 1**, ahead of Factors.ai, Abmatic, GR0's ABM agent,
Amy, Octave, Clari and Clearcue. For a company this young with (as far as the index shows) one page
and no press, that is a better result than expected.

But the index is **one page deep**. The domain-restricted search returned exactly one URL. That is
not an Exa failure — it is *accurate*: the live site really is a single page. Every footer link
(`/privacy`, `/terms`) and every route a researcher would guess (`/product`, `/pricing`,
`/about`, `/how-it-works`) returns **404** on the live server. Exa can only hold what exists.

> **Incidental finding, worth fixing:** the footer publishes "Privacy Policy" and "Terms of
> Service" links that both 404. A buyer's lawyer or a security reviewer will click those.

---

## 3. Is the indexed copy current? — **Yes. Provably.**

The cheapest possible freshness test is: pull the cached copy, then pull the same URL with
`livecrawl:"always"`, and hash both. Here they are **identical** — same 4,477 characters, same
sha256. Exa's cached copy of cluehq.ai is not stale by even one character.

The extra $0.000 (same $0.001 price) and +1 second bought certainty. **This is a reusable trick:
a cached-vs-livecrawl hash comparison is a ~1-second, ~$0.002 freshness audit for any URL.**

---

## 4. Does Exa's copy *lose* anything vs. the live page?

Coverage is 99% — the entire narrative body of the site is present, cleanly structured as
markdown headings. Word-level diff of live-extracted text vs Exa text:

- **Only in the live page:** `product`, `company`, `contact`, `email`, `connect`, `legal`,
  `privacy`, `policy`, `terms`, `service`, `rights`, `introducing`, **`microsites`**, **`paid`**.
- **Only in Exa:** `introducingclue` (a whitespace-join artifact — Exa concatenates adjacent
  inline elements: "Introducing" + "Clue" → "IntroducingClue"; same artifact in
  "ABM was never limited by ambition.It was limited by the amount of work.").

Almost all the loss is nav/footer chrome — irrelevant. **One loss is not irrelevant:** the live
page carries a tab strip naming the five agents —

> "Deep Research · Campaign Brief · Microsites · Paid Media · Direct Mail"

— and Exa's extraction **drops that tab strip entirely** (hence the missing `microsites` and
`paid`). The concepts still appear in the prose below, so a reader recovers them; a *field
extractor* keyed on the product's own list of modules would come up empty. Interactive
tab/accordion labels are the failure mode to watch for, not whole pages.

---

## 5. Verdict — what this means for using Exa on very young companies

Exa handled a company that is weeks old, one page big, and behind Cloudflare better than the
prevailing "the index is always stale" worry suggests: the page was indexed, ranked #1 on a
natural-language description of the business, and the cached copy was **byte-identical to a fresh
crawl** — so for cluehq.ai there is currently no freshness gap at all. The real limitation is not
staleness, it is **depth and extraction fidelity**: Exa holds one URL for the domain (correctly —
that is all there is), and its markdown quietly drops interactive tab labels, which is exactly
where a young company's most concrete product facts (the names of its five agents) live. So the
operating rule for young accounts is: *trust Exa for discovery and for the narrative body, but do
not conclude "the company has no X" from Exa alone* — a $0 direct fetch of the homepage takes 0.33
seconds and returns 6× more raw text, and the cached-vs-livecrawl hash check costs $0.002 when
freshness genuinely matters (a funding page, a careers page, a pricing change).

**On scraping:** Cloudflare fronts this site (`server: cloudflare`, Cloudflare email-obfuscation
in the markup) and **plain `urllib` with a browser User-Agent still got a 200 in 0.33 s**. No
Scrapling, no headless browser, no proxy needed. One data point, not a law — but it supports a
fetch-ladder whose first rung is a cheap direct GET.
