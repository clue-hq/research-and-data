# ARV2 smoke-test findings — exact results, the gap register, and recommendations

**Date:** 2026-08-31. Evidence: `.context/arv2-smoke-cluehq/` (SMOKE-TEST-REPORT.md, 702 lines,
+ per-account dossiers, 203-claim sample DB, full timing/cost ledgers, every raw response).
Two Opus agents (ICP Architect → Research Executor), grounded in www.cluehq.ai.

## 1. Exact results

**Run totals:** 124 provider calls · **$0.507 cash** · **32.5 AI Ark credits** (65% of ceiling —
credits, not cash, were the binding constraint) · 10.4 min provider wall-clock · 0 blocked
fetches · 0 fabrications detected · 180 explicit "NOT FOUND"s across five dossiers.

**Accounts (fit → researched intent):** Zafran 81→buying **90** (rank 4→**1**: ABM req live on
Ashby's API, **105 days unfilled**, ad describes Clue verbatim; published tools list = only
citable no-ABM-platform proof in the run) · Cogent 80→**88** (held: 10 live GTM reqs, 6 in 17
days; Head of Growth's public "need more teammates" post) · Harmonic 79.5→**62** (ABM req
**converted to a BDR seat**; the ad's "account mapping, outreach, direct mail, events" = 4 of
Clue's 5 agents) · Vendelux 66.5→75-but-**DISQUALIFIED** (their Meetings product = AI attendee
targeting; caught pre-outreach) · Uptiq 67.5→**33** (no US GTM hiring; marketing buyer in India).
**Agent A's core bet held: every ranking change was caused by a hiring fact, not a funding fact.**

**Committee/emails:** 53 people mapped; 6 email exports, **5 found, all `SMTP`+`VALID`**
(vari@ & nick@zafran.io, cameron@cogent.com, ana@ & tyler@harmonic.security), 5.0 credits; the
miss (Semien) is a provider defect, not a data gap. One same-name contamination caught.

**Sample DB:** 203 claims / 5 accounts / 53 contacts; 0 unregistered keys, 0 missing sources,
0 missing priorities; 6% paraphrased-quote defect rate, flagged row-by-row.

**Money:** per-account all-in $0.076–$0.173. Production: **$0.155 full depth** ($0.10 at volume
credits) / $0.086 reduced / $0.015 cheap pass. A 200-score→40-deep campaign ≈ **$9.20** provider
cost, vs the $93K–$230K ABM-manager salary bands these accounts themselves published.

**Latency:** Exa deep-reasoning 46.3s/call · gpt-5-mini 21.6s · AI Ark 1.3s · direct fetch 0.22s.

**Scraping:** 40 free fetches, **0 blocked**; Exa 16/17 = urllib 16/17 (same genuine 404).
**Scrapling needed zero times.** Free public ATS APIs (Ashby/Greenhouse/Lever) were the
decision-driver: $0, 1.3s, and caused every ranking change.

## 2. The gap register — what the issues actually are, with a recommendation each

| # | Gap (exact) | Severity | Recommendation |
|---|---|---|---|
| G1 | **No schema home for GTM hiring** — `account.hiring_velocity_eng` is engineering-only; every P1 signal lived in prose | **High — fix before next run** | Register `account.hiring.gtm_open_roles` (title, dept, published, days-open, salary band, still-listed, URL); worked example in the report |
| G2 | **AI Ark title filter is ignored** — "marketing" query returned 163 people led by sales; 12-person sample = 0 marketers | High | Never roster-sample. **Name-scoped lookups only** (12× cheaper, exact); names come from the web/ATS first — which is the web-first committee protocol already ruled |
| G3 | AI Ark search↔export disagree (Semien: search finds, export 404s same URL, twice) | Medium | File with vendor; fallback = web-sourced email patterns marked `pattern_inferred`, never bought blind |
| G4 | Agent A's hiring detector blind to non-ATS companies (Arintra: "zero hiring" — its /careers had 5 GTM roles incl. 2 marketing) | High | Discovery must read `/careers` pages, not only job-board indexes; add as a mandatory cheap fetch per finalist |
| G5 | Deep research searched for a KNOWN URL and hit the wrong domain (growthspree.com vs growthspreeofficial.com) | Medium | Charter rule: **a known URL is fetched, never searched for** |
| G6 | ATS slug guessing: 8/8 404s | Low | Read the careers page for the board link; never guess slugs |
| G7 | 6% paraphrased evidence quotes (13/203, flagged) | Medium | The `verify_links` audit step (already designed) becomes mandatory before claims serve |
| G8 | "Series A and above" excludes self-funded operators (Oscilar: 150+ ppl, $20M own capital, open outbound-marketing req) | **Founder ruling needed** | Either keep the rule strict, or add an equivalence clause ("or demonstrably funded/scaled equivalently") |
| G9 | "Founder ABM-pain" search angle = 100% vendor SEO; generic semantic ICP search returns competitors' blogs | Low (learned) | Rubric updated: signal-first job-req search is the primary angle (20/20 real companies; produced 4 of 5 picks) |
| G10 | cluehq.ai footer `/privacy` + `/terms` **404** (as do /product, /pricing, /about) | Trivial to fix, real | Fix on the live site this week |
| G11 | Own parser bug (email at `output[].address` not `.email`) — 6 exports briefly "not found" | Closed in-run | The save-raw-before-parse discipline recovered it at $0; keep as law |

## 3. Recommendations (the "which one" answers)

- **First account to approach: Zafran.** Champion = Vari Kaur (verified email), opener = her own
  105-day-old advert; LinkedIn first, email second, physical executive report to Nick Fisher as
  touch two. **Landmine: never mention the Calcalist/Cisco acquisition rumour** (publicly
  refuted). Risk note: acquisition talk can freeze spend — keep the first ask small; their
  2026-08-28 sales req suggests not frozen.
- **Best overall fit: Cogent** (92.5) — LinkedIn-first to Semien (no email buyable), email to
  Coles; mirror their own "3x team output" pitch; no category buzzwords (his stated pet peeve);
  position against their build-in-house roadmap as "makes that layer useful this quarter."
- **Stack verdict (which tools):** ratified by data — direct GET → **free ATS APIs (promote to
  first-class source)** → Exa contents → Exa deep-reasoning → stealth only on a real 403
  (Scrapling stays benched, 0-for-40 needed). AI Ark = identity/email (name-scoped only, G2);
  Exa = everything semantic; credits are the budget unit to watch, not dollars.
- **Verticals:** cybersecurity is where US ABM demand sits right now (3/5 picks, unprompted);
  healthcare is in build-mode (6 funded companies, zero GTM hiring) — deprioritize for now.

## 4. Model-trust evidence worth keeping
The research model **refused a false fact supplied by its own operator** (asserted CEO name),
citing the company's About page — and separated robot estimates from company-reported numbers
unprompted. The architecture's anti-fabrication bet, observed working against ourselves.
