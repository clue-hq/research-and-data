# ARV2 v26 — follow-up chains and the nothing-lost fixtures (all production runs)

*Lane L2 · 2026-10-07 · source corpus `.artifacts/arv2-research-runs-20261007/` (42 runs: 7 accounts, 35 contacts) · fixtures and scripts in `.artifacts/arv2-research-runs-20261007/fixtures/` (untracked; the corpus is research about real people — this document carries counts, classes, operation kinds and at most name + title + employer).*

This document extends the Dialpad-only depth review (`.artifacts/account-research-cost-20261006/depth-review/`) to **every production run**: every acquisition operation is classified as template-coverable / follow-up / waste, every finding is rated A/B/C with the same rubric and mapped back to the operations that produced its cited evidence, and the per-account **nothing-lost** and **chain** fixtures for AT-6 / AT-9 are built from all seven accounts rather than one. The v26 plan it feeds is `docs/superpowers/plans/2026-10-06-account-research-v26-cost-and-speed-plan.md` (§1 brief classes and caps, A3 guaranteed follow-ups, AT-6/7/9); the operation-mix evidence is `01-evidence-all-production-runs.md` §4.

## 0. Headline

- **Follow-ups are 58 % of completed acquisition operations** (404 of 699; 103 of 179 on account runs, 301 of 520 on contact runs). 214 of the 404 carry a trigger term that is *verifiably* present in an earlier result stored in the corpus; 190 carry a specific name/term/URL that the corpus cannot show (search-result text is not stored), so they are follow-ups by construction but unverified. Hop depth is almost always 1: only 5 follow-ups (1 %) are follow-ups of follow-ups.
- **401 of 1,782 findings are A-class** (23 %; 159 on accounts, 242 on contacts; the Dialpad account, Flynn and Wall carry the depth reviewer's own ratings, the other 39 runs are rated here with the same rubric — §2 states the agreement).
- **Between 16 % and 60 % of A-class value depends on follow-ups.** 65 A-class findings (16 %) cite evidence that *only* a follow-up operation could have produced (the strict lower bound); 242 (60 %) have at least one follow-up among the operations that could have produced their evidence; 159 (40 %) are produced by template operations alone. The spread is the corpus's batch ambiguity, not a judgement call: operations issued in the same round are admitted within seconds and share one block of evidence numbers, so a finding cited from that block maps to the batch, not to one query (§1.2). The lower bound alone already says a fixed per-subject plan without follow-ups loses one A-class finding in six; the per-trigger table (§3) says which follow-ups to guarantee.
- **The floor** (§3): nine (trigger → operation) pairs produced strict-attributed A-class findings in at least two accounts — *person named in a result → profile/name search*, *exact phrase from a result (title, programme, award) → phrase search*, *vendor named → vendor/customer-story search*, *URL in a result → fetch*, *talk/podcast/event named → search*, *subject's own site page in a result → fetch*, *prior employer or board named → search*, *person named → LinkedIn profile fetch*, *education / prior-employer disambiguation → search*. Three more pairs the plan already mandates (departure → successor, job listing → fetch the posting, committee candidate → profile + posts) show up in one account each here and should stay. "Fetch the full posting" is the single biggest *possible* yield in Loopio (17 A-class findings) — it is batch-ambiguous only because the postings arrived in the same round as the hiring search.
- **Caps** (§6): the account caps hold for Trigger (max 8 of 10), Initiative (3 of 5), Pain (2 of 5), Motion (4 of 5), Not-found (2 of 3). They **cut A-class findings in Stack (max 8 vs 4; three accounts over), Committee (10 vs 8; one account) and Watch-outs (4 vs 3; one account)**. Recommend Stack 4 → 8 (the benefits and fleet accounts carry 5–8 incumbent vendors — TPA, PBM, clinic operator, stop-loss, HRIS, telematics, ELD — and every one is a fit/do-not-say item), Committee 8 → 10 (alternates), Watch-outs 3 → 4. On contacts: own-words 6 cuts two of 35 contacts (Henderson 10, Flynn 8) — recommend 8; problem-now 3 cuts four contacts (max 7) — recommend 5; proud-of 2 → 3; hooks 3 → 4; remit "2" is exceeded by 15 contacts only because the runs record the same title from 3–5 sources — keep 2 and merge corroborating records into one item.
- **Quote fidelity** (§5): 1,946 quoted spans in the findings. Where the cited source's text is stored (fetched pages: 89 quotes with one certain producer), **62 % are verbatim** under the normaliser; the near-misses are boundary punctuation, a clipped clause, or a number/date inside the span; the remainder fall beyond the trace store's 8 k-character window and cannot be judged. AT-7 stands with two additions: the normaliser must also fold escape sequences (`\n`) and boundary punctuation, and digits/dates inside a span must match exactly (they are the drift that survives everything else). 50 spans (2.6 %) splice with an ellipsis — allow it only with an explicit marker.
- **Negative space, multi-source, namesakes** (§7): 277 findings (16 %) cite ≥ 2 sources (76 of 401 A-class); 96 findings are explicit not-found statements (12 A-class, led by Mortenson's "no public medical-trend complaint" and Dialpad's "CMO departure without a named successor"); 91 findings (5 %) are namesake / different-person exclusions, concentrated on contacts (25 of 35 contacts carry at least one; six on Cindy Lyons and Alex Pace); 17 are explicit misattribution guards.

## 1. Method

### 1.1 Inputs and the three joins

Every run's ordered operation sequence (`sequences/<trace>.json`), the tool I/O (`raw/<trace>.json`: `save_dossier_section` / `update_dossier_findings` inputs carry the findings; `fetch_page`, `research_deep`, `read_ats_board`, `discover_people`, `read_people_result`, `lookup_person`, `discover_media` outputs carry text, titles and names for the 33 v2-pulled traces; the 9 traces pulled through v1 carry inputs only), `runs.csv` for lineage. The two account runs that share one trace (McKee Foods, Mortenson) are split by matching each save/update/glob row's start second to its own sequence.

1. **Findings** — the last save/update of each finding id wins (1,782 findings; counts match `validate_dossier` to ±1 on every run).
2. **Evidence → operation** — findings cite `/evidence/NNNN-slug.json` records, operations write `/research/operations/<op>/0.json` result files, and nothing in the corpus lists which records an operation created. The map is reconstructed from the numbering: evidence numbers are one counter per account family (the account run numbers 1..N; its five contact runs continue the counter, interleaved); each operation's records are one contiguous block that starts with a `provider-record` entry; blocks are laid down in admission order; a `research-report` record belongs to a `research_deep` operation and that operation's block also holds the pages its report cites. Operations admitted within 8 s of each other form one **admission group** whose internal order is unrecoverable. The map is a bounds-propagation over groups (per-kind block minima/maxima; hard anchors from `research-report` numbers and the account's `validate_dossier` record count; soft anchors from the agent's read order — it reads an operation's result file, then the records it listed — kept only as the maximum consistent chain), then narrowed by the citing run (own operations, then the parent account's), by fetched-page / people / media titles, and never by keyword overlap (the same page surfaces for several queries). **Validation against the depth reviewer's Dialpad map (30 records with known producers): 0 disagreements; every known producer is inside the candidate set; 2 records resolve to one operation, 28 to the batch.** Over all 930 cited records: 308 resolve to one operation, 238 to 2–3 candidates, 383 to a wider batch, 1 unresolved.
3. **Operation class** — *template-coverable* = issued by the fixed per-subject plan from the brief alone (company lookup, ATS board, deep report, the six account themes, the six contact themes, the subject's homepage / board / LinkedIn, enrichment, role searches, one media discovery, fetches of pages the deep report cites); *follow-up* = the query / URL / arguments carry a specific term — a name, a quoted title or phrase, a vendor, a place, an organisation, a URL — that is not the subject or the seller's vocabulary; *verified* when the term is present in an earlier result stored in the corpus (an operation output, an evidence record the run read, a finding or working note it saved, or the parent account run's), *inferred* otherwise. Unverified vendor names inside a stack-themed query count as the seller's stack vocabulary (template). *Waste* = refused (54), exact repeat or re-fetch (14), or completed with no record ever read or cited (102 — 39 searches, 38 fetches, 12 media discoveries, 10 person lookups, 3 people searches). Trigger kinds are assigned by rule from the term and the query shape; **hop depth** = 1 + the depth of the operation that produced the trigger (template = 0).

### 1.2 What "strict" and "possible" mean

A finding's provenance is the union of candidate producers over its cited records. **Strict** follow-up attribution: at least one cited record can only have come from follow-up operations. **Possible**: at least one candidate producer is a follow-up. **Template-only**: every candidate is a template operation. The gap between strict and possible is batch ambiguity (a round-9 batch of five name searches shares one block), not rating uncertainty; the rule table (§3) reports both, and the floor is chosen on strict counts.

### 1.3 Rating

A = seller-critical (a dated trigger, a pain, an initiative, a buyer/role with evidence, a why-now, a usable hook or the subject's own recent words on their work); B = useful context; C = filler (process narration, aggregator estimates, namesake inventories, education entries, early-career roles, typed enrichment lists, recording listings). Seller relevance is per workspace: Clue (ABM / marketing production) for Dialpad and Loopio; Samsara (fleet safety / telematics) for FirstFleet and J. Rayl; Garner Health (employer health benefits) for McKee Foods, Mortenson and NYC DDC/OLR — read from the deep-report charters. The Dialpad account, Andrew Flynn and Emily Wall carry the depth reviewer's A lists unchanged; the other 39 runs were rated by hand on the finding list with a rule-based first pass (the rules alone over-rate: 44 vs the reviewer's 20 A on the Dialpad account, 21 vs 16 on Flynn, 10 vs 11 on Wall — hence the hand pass). Class per A finding follows the §1 brief classes (account: trigger / initiative / pain / motion & proof / stack / committee / watch-outs / not-found / firmographics; contact: remit / problem-now / own-words / proud-of / hooks / career-arc / do-not-mention).

## 2. Operations: template-coverable, follow-up, waste

## T1 — Acquisition operations per run: template-coverable / follow-up / waste
| Run | Kind | ops | template | follow-up (verified / inferred) | refused | repeat / refetch | unused results | follow-up share of completed |
|---|---|---|---|---|---|---|---|---|
| dialpad.com | account | 32 | 20 | 12 (4 / 8) | 0 | 0 | 0 | 38% |
| Andrew Flynn | person | 17 | 6 | 10 (8 / 2) | 1 | 0 | 6 | 62% |
| Emily Wall | person | 19 | 6 | 13 (8 / 5) | 0 | 0 | 2 | 68% |
| Jenny Coupe | person | 17 | 7 | 8 (4 / 4) | 2 | 0 | 4 | 53% |
| Meaghan Edelstein | person | 18 | 7 | 11 (5 / 6) | 0 | 1 | 1 | 61% |
| Sarah Rolfing | person | 16 | 7 | 9 (1 / 8) | 0 | 0 | 0 | 56% |
| firstfleetinc.com | account | 23 | 11 | 9 (2 / 7) | 3 | 0 | 3 | 45% |
| Austin Henderson | person | 13 | 5 | 5 (3 / 2) | 3 | 0 | 1 | 50% |
| Bronson Laney | person | 17 | 7 | 8 (7 / 1) | 2 | 0 | 6 | 53% |
| John Cole | person | 20 | 6 | 13 (7 / 6) | 1 | 0 | 9 | 68% |
| Rebecca Wilson | person | 16 | 5 | 9 (4 / 5) | 2 | 0 | 4 | 64% |
| Robb Getts | person | 21 | 5 | 12 (6 / 6) | 4 | 0 | 0 | 71% |
| jrayl.com | account | 29 | 10 | 15 (5 / 10) | 4 | 5 | 0 | 60% |
| Gene Shippy | person | 18 | 9 | 3 (2 / 1) | 6 | 4 | 2 | 25% |
| Justin Yoder | person | 14 | 7 | 7 (4 / 3) | 0 | 0 | 3 | 50% |
| Matthew Parks | person | 12 | 8 | 4 (3 / 1) | 0 | 0 | 0 | 33% |
| Ryan Richards | person | 18 | 6 | 11 (7 / 4) | 1 | 0 | 4 | 65% |
| Toni Roberts | person | 12 | 6 | 6 (2 / 4) | 0 | 0 | 4 | 50% |
| loopio.com | account | 25 | 11 | 14 (7 / 7) | 0 | 0 | 0 | 56% |
| Alex Pace | person | 17 | 10 | 7 (6 / 1) | 0 | 0 | 2 | 41% |
| Alison Hayter | person | 12 | 6 | 5 (2 / 3) | 1 | 0 | 0 | 45% |
| Michelle Oke | person | 12 | 7 | 5 (4 / 1) | 0 | 0 | 0 | 42% |
| Siobhan Mondesire | person | 19 | 7 | 9 (6 / 3) | 3 | 0 | 8 | 56% |
| Vincent Lo | person | 21 | 8 | 13 (8 / 5) | 0 | 0 | 5 | 62% |
| mckeefoods.com | account | 31 | 10 | 21 (4 / 17) | 0 | 0 | 1 | 68% |
| Andy Lang | person | 28 | 9 | 10 (8 / 2) | 9 | 4 | 0 | 53% |
| Chris McKee | person | 14 | 4 | 10 (4 / 6) | 0 | 0 | 1 | 71% |
| Cindy Lyons | person | 15 | 8 | 7 (7 / 0) | 0 | 0 | 5 | 47% |
| Don Gladden | person | 12 | 7 | 5 (4 / 1) | 0 | 0 | 5 | 42% |
| Kyler Vann | person | 16 | 6 | 10 (3 / 7) | 0 | 0 | 4 | 62% |
| mortenson.com | account | 37 | 10 | 19 (4 / 15) | 8 | 0 | 1 | 66% |
| Athena Burkholder | person | 13 | 5 | 8 (5 / 3) | 0 | 0 | 0 | 62% |
| Jean McGrory | person | 13 | 5 | 8 (5 / 3) | 0 | 0 | 2 | 62% |
| John Bachhuber | person | 13 | 6 | 7 (2 / 5) | 0 | 0 | 0 | 54% |
| Patrick Locken | person | 17 | 6 | 11 (6 / 5) | 0 | 0 | 3 | 65% |
| Robin Ritter | person | 18 | 4 | 14 (7 / 7) | 0 | 0 | 3 | 78% |
| nyc.gov | account | 17 | 4 | 13 (4 / 9) | 0 | 0 | 0 | 76% |
| Beth Kushner | person | 17 | 8 | 7 (7 / 0) | 2 | 0 | 5 | 47% |
| Claire Levitt | person | 11 | 4 | 6 (5 / 1) | 1 | 0 | 1 | 60% |
| Octavia McCormick-Sharf | person | 12 | 3 | 9 (8 / 1) | 0 | 0 | 3 | 75% |
| Renee Campion | person | 14 | 5 | 8 (7 / 1) | 1 | 0 | 1 | 62% |
| Sang Hong | person | 17 | 4 | 13 (9 / 4) | 0 | 0 | 3 | 76% |
| **all 42** | | 753 | 295 | 404 (214 / 190) | 54 | 14 | 102 | 58% |
| *account runs* | | 194 | 76 | 103 (30 / 73) | 15 | 5 | 5 | 58% |
| *person runs* | | 559 | 219 | 301 (184 / 117) | 39 | 9 | 97 | 58% |

Reading: contact runs are two-thirds follow-ups because every query after the first round names the subject *plus* something learned (a prior employer, a programme, a colleague, a post). Account runs are 58 % follow-ups; the 10-03 (v24) account runs issued 19–21 follow-ups each against 10 template operations. **Waste**: 54 refused operations (22 `search_web` invalid-argument refusals, 21 `read_media`, 5 `research_deep` argument refusals on Mortenson before its one accepted report, 4 `lookup_person` subject-lock failures, 2 DB errors), 14 exact repeats (5 on J. Rayl, 4 each on Gene Shippy and Andy Lang), and 102 completed operations whose records were never opened nor cited (14 % of completed; `search_web` 39, `fetch_page` 38).

## T2 — Follow-up operations by trigger kind and issued operation kind (all runs)
| Trigger kind | search_web | fetch_page | lookup_person | read_media | other | total | verified | depth 2+ |
|---|---|---|---|---|---|---|---|---|
| person-name | 63 | 5 | 0 | 0 | 0 | 68 | 45 | 0 |
| url-in-result | 0 | 61 | 0 | 0 | 0 | 61 | 11 | 0 |
| quoted-phrase | 46 | 0 | 0 | 0 | 0 | 46 | 38 | 0 |
| own-post | 0 | 34 | 0 | 0 | 0 | 34 | 4 | 0 |
| vendor-stack | 28 | 0 | 0 | 0 | 0 | 28 | 22 | 2 |
| subject-site-page | 0 | 27 | 0 | 0 | 0 | 27 | 4 | 0 |
| education-prior-employer | 22 | 0 | 0 | 0 | 0 | 22 | 16 | 0 |
| event-talk-media | 18 | 4 | 0 | 0 | 0 | 22 | 16 | 1 |
| other-specific | 17 | 0 | 0 | 0 | 0 | 17 | 6 | 1 |
| title-in-posting | 12 | 0 | 0 | 0 | 0 | 12 | 10 | 0 |
| prior-employer-affiliation | 9 | 0 | 0 | 0 | 0 | 9 | 9 | 0 |
| location-community-personal | 6 | 0 | 0 | 0 | 0 | 6 | 5 | 0 |
| customer-case-study | 6 | 0 | 0 | 0 | 0 | 6 | 5 | 0 |
| post-by-other | 0 | 6 | 0 | 0 | 0 | 6 | 0 | 0 |
| site-restricted | 5 | 0 | 0 | 0 | 0 | 5 | 3 | 0 |
| funding-financial | 5 | 0 | 0 | 0 | 0 | 5 | 2 | 0 |
| job-listing | 1 | 4 | 0 | 0 | 0 | 5 | 4 | 0 |
| initiative-program | 5 | 0 | 0 | 0 | 0 | 5 | 5 | 1 |
| profile-aggregator | 0 | 3 | 0 | 0 | 0 | 3 | 1 | 0 |
| press-release-url | 0 | 3 | 0 | 0 | 0 | 3 | 0 | 0 |
| departure-succession | 3 | 0 | 0 | 0 | 0 | 3 | 3 | 0 |
| vendor-customer-page | 0 | 3 | 0 | 0 | 0 | 3 | 1 | 0 |
| partner-channel | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| location | 2 | 0 | 0 | 0 | 0 | 2 | 2 | 0 |
| award-analyst | 2 | 0 | 0 | 0 | 0 | 2 | 2 | 0 |
| regulatory-filing | 0 | 2 | 0 | 0 | 0 | 2 | 0 | 0 |

Reading: the agent's follow-ups are overwhelmingly **names** (68 person-name searches and profile fetches), **URLs seen in results** (61 fetches, 34 own-post fetches, 27 subject-site pages), **exact phrases** (46 quoted-title/programme/award searches) and **vendors** (28). The kinds the v26 plan lists as its floor are rare in the corpus as explicit operations: departure → successor 3, job listing → fetch posting 5, partner/channel 2, award/analyst 2, regulatory filing 2. Depth-2 chains: 5.

## 3. Follow-up rule table and the floor

## T5 — Trigger kinds behind A-class findings (a finding counts once per trigger kind of its follow-up operations)
| Trigger kind | A findings (strict) | A findings (possible) | accounts (families) with ≥1 A | runs |
|---|---|---|---|---|
| person-name | 41 | 113 | 7 | 29 |
| other-specific | 11 | 64 | 6 | 14 |
| vendor-stack | 14 | 47 | 5 | 15 |
| subject-site-page | 12 | 38 | 4 | 12 |
| quoted-phrase | 11 | 36 | 7 | 19 |
| url-in-result | 5 | 36 | 7 | 16 |
| title-in-posting | 1 | 33 | 5 | 10 |
| education-prior-employer | 2 | 31 | 5 | 12 |
| event-talk-media | 7 | 30 | 6 | 9 |
| own-post | 4 | 17 | 4 | 7 |
| post-by-other | 2 | 17 | 3 | 5 |
| job-listing | 0 | 17 | 1 | 3 |
| initiative-program | 10 | 13 | 1 | 5 |
| partner-channel | 0 | 10 | 1 | 2 |
| funding-financial | 3 | 9 | 2 | 6 |
| prior-employer-affiliation | 5 | 8 | 4 | 4 |
| profile-aggregator | 2 | 6 | 2 | 2 |
| location | 0 | 5 | 1 | 2 |
| vendor-customer-page | 2 | 4 | 2 | 2 |
| site-restricted | 1 | 3 | 2 | 2 |
| customer-case-study | 0 | 2 | 2 | 2 |
| location-community-personal | 0 | 2 | 1 | 1 |
| press-release-url | 2 | 2 | 1 | 1 |
| departure-succession | 0 | 2 | 1 | 1 |

## T6 — Follow-up rule table: (trigger kind → operation kind) pairs, counts and A-class yield
| Trigger kind → op | ops | runs | accounts | A findings (strict / possible) | accounts with A (strict / possible) | floor? |
|---|---|---|---|---|---|---|
| person-name → search_web | 63 | 34 | 7 | 58 / 143 | 4 / 7 | **floor** |
| url-in-result → fetch_page | 61 | 29 | 7 | 6 / 47 | 3 / 7 | **floor** |
| quoted-phrase → search_web | 46 | 26 | 7 | 12 / 39 | 5 / 7 | **floor** |
| other-specific → search_web | 17 | 6 | 6 | 11 / 97 | 1 / 6 | **floor** |
| event-talk-media → search_web | 18 | 15 | 6 | 9 / 32 | 2 / 6 | **floor** |
| vendor-stack → search_web | 28 | 19 | 6 | 17 / 51 | 3 / 5 | **floor** |
| title-in-posting → search_web | 12 | 11 | 7 | 1 / 33 | 1 / 5 | **floor** |
| education-prior-employer → search_web | 22 | 22 | 7 | 2 / 31 | 2 / 5 | **floor** |
| subject-site-page → fetch_page | 27 | 12 | 5 | 16 / 44 | 2 / 4 | **floor** |
| own-post → fetch_page | 34 | 13 | 6 | 5 / 38 | 1 / 4 | **floor** |
| prior-employer-affiliation → search_web | 9 | 7 | 4 | 5 / 8 | 2 / 4 | **floor** |
| person-name → fetch_page | 5 | 3 | 3 | 14 / 20 | 2 / 3 | **floor** |
| post-by-other → fetch_page | 6 | 6 | 4 | 2 / 17 | 1 / 3 | **floor** |
| funding-financial → search_web | 5 | 4 | 3 | 3 / 9 | 1 / 2 | **floor** |
| profile-aggregator → fetch_page | 3 | 3 | 2 | 2 / 6 | 1 / 2 | **floor** |
| vendor-customer-page → fetch_page | 3 | 3 | 2 | 2 / 4 | 1 / 2 | **floor** |
| site-restricted → search_web | 5 | 5 | 3 | 1 / 3 | 1 / 2 | **floor** |
| customer-case-study → search_web | 6 | 5 | 4 | 0 / 2 | 0 / 2 | **floor** |
| job-listing → fetch_page | 4 | 2 | 1 | 0 / 25 | 0 / 1 |  |
| initiative-program → search_web | 5 | 3 | 1 | 10 / 13 | 1 / 1 |  |
| partner-channel → search_web | 2 | 2 | 1 | 0 / 10 | 0 / 1 |  |
| location → search_web | 2 | 2 | 2 | 0 / 5 | 0 / 1 |  |
| location-community-personal → search_web | 6 | 5 | 3 | 0 / 4 | 0 / 1 |  |
| press-release-url → fetch_page | 3 | 2 | 2 | 2 / 2 | 1 / 1 |  |
| departure-succession → search_web | 3 | 3 | 3 | 0 / 2 | 0 / 1 |  |
| event-talk-media → fetch_page | 4 | 3 | 2 | 0 / 0 | 0 / 0 |  |
| award-analyst → search_web | 2 | 2 | 2 | 0 / 0 | 0 / 0 |  |
| regulatory-filing → fetch_page | 2 | 2 | 2 | 0 / 0 | 0 / 0 |  |
| job-listing → search_web | 1 | 1 | 1 | 0 / 0 | 0 / 0 |  |

**Recommended floor** (strict A-class yield in ≥ 2 accounts, in order of strict yield), as the table-driven A3 step:

| # | Trigger (what the result contained) | Guaranteed operation | Evidence |
|---|---|---|---|
| 1 | a person named in any result (exec in a press item, predecessor, colleague on a post, name in a posting) | name + employer search, then profile fetch when a LinkedIn URL is returned | 58 strict / 143 possible A, 4 / 7 accounts; the profile fetch alone 14 / 20 A in 2 / 3 accounts |
| 2 | a vendor named in a result (incumbent tool, TPA/PBM, telematics, MAP) | vendor + subject search and the vendor's customer-story page | 17 / 51 A, 3 / 5 accounts |
| 3 | an exact phrase worth its own search (a job title, a programme or award name, a product line) | quoted-phrase search | 12 / 39 A, 5 / 7 accounts |
| 4 | a URL in a result that is not the homepage/board/profile | fetch it (press item, article, profile aggregator, filing) | 6 / 47 A, 3 / 7 accounts |
| 5 | a page on the subject's own site surfaced by a result (careers, benefits, news/blog, team pages) | fetch it | 16 / 44 A, 2 / 4 accounts |
| 6 | a talk, podcast, webinar or event named with the subject | search it (and `read_media` only when transcription is live) | 9 / 32 A, 2 / 6 accounts |
| 7 | a prior employer, board or association named on the profile | search it (contact hooks and do-not-mention) | 5 / 8 A, 2 / 4 accounts |
| 8 | education / prior-employer disambiguation for a common name | search it (namesake exclusion) | 2 / 31 A, 2 / 5 accounts — mostly produces C-class exclusions; keep as the namesake guard, not for value |
| 9 | a departure in a result | successor / vacancy search | 0 / 2 A in the corpus (Dialpad only: the "no named successor" not-found item) — keep, plan-mandated |
| 10 | a marketing/function job listing in a result | fetch the full posting | 0 / 25 A (Loopio: 17 possible, batch-ambiguous with the hiring search) — keep, plan-mandated |
| 11 | a committee candidate | profile + last posts | covered by #1 and the own-post fetch (5 / 38 A) — keep, plan-mandated |

Pairs that produced A-class findings in one account only (initiative/programme name → search: 10 strict A on Loopio; partner/channel; press-release URL; location) are agent-discretion follow-ups, not floor. Pairs that produced none (award/analyst, regulatory filing, event-talk → fetch) are cheap to keep as agent options.

**Templates the fixed plan is missing** (A-class findings whose only or main producers are follow-ups of a repeatable theme, §T7): (a) a **subject-site crawl** of `/careers`, `/benefits`, `/news|/blog|/press` and team pages — 44 possible / 16 strict A across four accounts (benefits pages and PDFs for the Garner accounts, tenFour posts for FirstFleet, the channel/press pages for Dialpad); the plan's "homepage + deep-cited pages" does not reach them; (b) the **pain / resonance** template the plan already adds — the 8 account-level pain items here came through the deep report or an article (Mortenson's travelling-workforce access problem, McKee's turnover and pharmacy-network dispute, Loopio's change-management post, NYC's comptroller health-cost note), never through a fixed search; (c) a **named-exec profile** template — for every leadership-change name the leadership search returns, fetch the profile (this is what produced Dialpad's CMO-tenure-ended and the no-successor item, FirstFleet's Henderson-moved-to-Werner item); (d) for contacts, an **own-post fetch** per result (the posts template finds the posts; the fetch of each post page is what yields the verbatim own-words: 38 possible A in four accounts).

## T7 — Where A-class findings come from, by template theme / follow-up trigger (possible attribution)
| Source theme or trigger | A findings | accounts | in current fixed plan? |
|---|---|---|---|
| deep-report | 199 | 7 | yes |
| FU:person-name | 113 | 7 | follow-up |
| leadership | 68 | 6 | yes |
| FU:other-specific | 64 | 6 | follow-up |
| FU:vendor-stack | 47 | 5 | follow-up |
| company-lookup | 41 | 6 | yes |
| hiring | 39 | 4 | yes |
| FU:subject-site-page | 38 | 4 | follow-up |
| homepage | 38 | 5 | yes |
| media-discovery | 38 | 6 | yes |
| FU:quoted-phrase | 36 | 7 | follow-up |
| FU:url-in-result | 36 | 7 | follow-up |
| FU:title-in-posting | 33 | 5 | follow-up |
| FU:education-prior-employer | 31 | 5 | follow-up |
| FU:event-talk-media | 30 | 6 | follow-up |
| business-model | 26 | 4 | yes |
| subject-linkedin | 25 | 5 | yes |
| person-lookup | 24 | 6 | yes |
| person-company-mentions | 24 | 4 | yes |
| role-search | 22 | 4 | yes |
| abm-programme | 20 | 1 | yes |
| person-talks | 19 | 4 | yes |
| FU:own-post | 17 | 4 | follow-up |
| FU:post-by-other | 17 | 3 | follow-up |
| role-search-read | 17 | 2 | yes |
| FU:job-listing | 17 | 1 | follow-up |
| FU:initiative-program | 13 | 1 | follow-up |
| FU:partner-channel | 10 | 1 | follow-up |
| FU:funding-financial | 9 | 2 | follow-up |
| FU:prior-employer-affiliation | 8 | 4 | follow-up |
| ats-board-fetch | 8 | 4 | yes |
| stack | 8 | 1 | yes |
| deep-cited-fetch | 7 | 2 | yes |
| deep-report-extra | 7 | 1 | no |
| FU:profile-aggregator | 6 | 2 | follow-up |
| person-posts | 5 | 2 | yes |
| FU:location | 5 | 1 | follow-up |
| FU:vendor-customer-page | 4 | 2 | follow-up |
| ats-board | 3 | 1 | yes |
| FU:site-restricted | 3 | 2 | follow-up |
| FU:customer-case-study | 2 | 2 | follow-up |
| news-funding | 2 | 1 | yes |
| FU:location-community-personal | 2 | 1 | follow-up |
| FU:press-release-url | 2 | 1 | follow-up |
| FU:departure-succession | 2 | 1 | follow-up |

## 4. Per-run results: A-class counts, follow-up share, chain depth

## T3 — Findings per run: A/B/C, and the A-class share traced to follow-ups
| Run | Kind | findings | A | B | C | A traced to follow-up (strict) | A possibly follow-up (any candidate) | A template-only | A unmapped/ambiguous | A max chain depth |
|---|---|---|---|---|---|---|---|---|---|---|
| dialpad.com | account | 57 | 20 | 36 | 1 | 2 | 15 | 5 | 0 | 1 |
| Andrew Flynn | person | 51 | 16 | 24 | 11 | 8 | 11 | 5 | 0 | 2 |
| Emily Wall | person | 37 | 11 | 4 | 22 | 2 | 11 | 0 | 0 | 1 |
| Jenny Coupe | person | 56 | 14 | 40 | 2 | 0 | 7 | 7 | 0 | 1 |
| Meaghan Edelstein | person | 45 | 11 | 26 | 8 | 0 | 8 | 3 | 0 | 1 |
| Sarah Rolfing | person | 36 | 5 | 25 | 6 | 2 | 3 | 2 | 0 | 1 |
| firstfleetinc.com | account | 77 | 27 | 50 | 0 | 0 | 6 | 21 | 0 | 1 |
| Austin Henderson | person | 59 | 17 | 35 | 7 | 2 | 6 | 11 | 0 | 1 |
| Bronson Laney | person | 26 | 6 | 16 | 4 | 0 | 2 | 4 | 0 | 1 |
| John Cole | person | 36 | 5 | 25 | 6 | 1 | 3 | 2 | 0 | 1 |
| Rebecca Wilson | person | 30 | 5 | 19 | 6 | 3 | 3 | 2 | 0 | 1 |
| Robb Getts | person | 41 | 11 | 26 | 4 | 3 | 7 | 4 | 0 | 1 |
| jrayl.com | account | 67 | 19 | 46 | 2 | 0 | 9 | 10 | 0 | 1 |
| Gene Shippy | person | 30 | 2 | 17 | 11 | 0 | 2 | 0 | 0 | 1 |
| Justin Yoder | person | 36 | 4 | 20 | 12 | 2 | 2 | 2 | 0 | 1 |
| Matthew Parks | person | 35 | 4 | 24 | 7 | 0 | 4 | 0 | 0 | 1 |
| Ryan Richards | person | 42 | 3 | 31 | 8 | 0 | 2 | 1 | 0 | 1 |
| Toni Roberts | person | 36 | 3 | 27 | 6 | 0 | 3 | 0 | 0 | 1 |
| loopio.com | account | 45 | 23 | 22 | 0 | 2 | 19 | 4 | 0 | 1 |
| Alex Pace | person | 37 | 6 | 21 | 10 | 0 | 0 | 6 | 0 | 0 |
| Alison Hayter | person | 45 | 7 | 25 | 13 | 0 | 2 | 5 | 0 | 1 |
| Michelle Oke | person | 43 | 12 | 22 | 9 | 0 | 1 | 11 | 0 | 1 |
| Siobhan Mondesire | person | 55 | 17 | 32 | 6 | 1 | 15 | 2 | 0 | 1 |
| Vincent Lo | person | 53 | 10 | 27 | 16 | 1 | 1 | 9 | 0 | 1 |
| mckeefoods.com | account | 60 | 23 | 37 | 0 | 1 | 13 | 10 | 0 | 1 |
| Andy Lang | person | 34 | 3 | 16 | 15 | 0 | 3 | 0 | 0 | 1 |
| Chris McKee | person | 54 | 6 | 13 | 35 | 0 | 5 | 1 | 0 | 1 |
| Cindy Lyons | person | 23 | 1 | 10 | 12 | 1 | 1 | 0 | 0 | 1 |
| Don Gladden | person | 38 | 3 | 14 | 21 | 0 | 3 | 0 | 0 | 1 |
| Kyler Vann | person | 26 | 4 | 15 | 7 | 4 | 4 | 0 | 0 | 1 |
| mortenson.com | account | 67 | 27 | 39 | 1 | 14 | 26 | 1 | 0 | 1 |
| Athena Burkholder | person | 27 | 4 | 16 | 7 | 0 | 4 | 0 | 0 | 1 |
| Jean McGrory | person | 46 | 5 | 28 | 13 | 1 | 2 | 3 | 0 | 1 |
| John Bachhuber | person | 37 | 11 | 19 | 7 | 2 | 7 | 4 | 0 | 1 |
| Patrick Locken | person | 32 | 7 | 20 | 5 | 0 | 0 | 7 | 0 | 0 |
| Robin Ritter | person | 47 | 7 | 32 | 8 | 3 | 7 | 0 | 0 | 1 |
| nyc.gov | account | 63 | 20 | 42 | 1 | 6 | 11 | 9 | 0 | 2 |
| Beth Kushner | person | 27 | 4 | 13 | 10 | 1 | 4 | 0 | 0 | 2 |
| Claire Levitt | person | 49 | 4 | 37 | 8 | 1 | 3 | 1 | 0 | 1 |
| Octavia McCormick-Sharf | person | 20 | 4 | 13 | 3 | 0 | 3 | 1 | 0 | 2 |
| Renee Campion | person | 43 | 8 | 29 | 6 | 1 | 2 | 6 | 0 | 2 |
| Sang Hong | person | 14 | 2 | 7 | 5 | 1 | 2 | 0 | 0 | 2 |
| **all 42** | | 1782 | 401 | | | 65 (16%) | 242 (60%) | 159 (40%) | 0 | |
| *account runs* | | 436 | 159 | | | 25 (16%) | 99 (62%) | 60 (38%) | 0 | |
| *person runs* | | 1346 | 242 | | | 40 (17%) | 143 (59%) | 99 (41%) | 0 | |

## T4 — Chain depth of A-class findings (depth 0 = template-only; 1 = one follow-up hop; 2 = a follow-up of a follow-up)
| Kind | depth 0 | depth 1 | depth 2 | unresolved (no candidate op) |
|---|---|---|---|---|
| account | 60 | 98 | 1 | 0 |
| person | 99 | 136 | 7 | 0 |

Reading: strict follow-up dependence is highest where the account run went deep on its own (Mortenson 14 of 27 A strict; NYC 6 of 20) and on contacts whose value is their own posts (Flynn 8 of 16; Kyler Vann 4 of 4). Template-only A is highest where the deep report did the work (FirstFleet 21 of 27; Michelle Oke 11 of 12; Patrick Locken 7 of 7). Depth-2 chains carry 8 A-class findings in all (one on the NYC account, seven on contacts — Flynn and the four NYC contacts).

## 5. Quote fidelity

- Quoted spans in findings: **1946** (in 1,782 findings; 50 contain an ellipsis splice).
- The corpus stores source text only for fetched pages, deep reports, ATS postings, people records and media descriptions, each cut at ~8 k characters by the trace store; Exa search results store no text. A span is therefore judged only where its cited record maps to exactly one operation that has text.
- **Single-producer, text-bearing subset: 488 spans** — verbatim 75, near-verbatim 21 (boundary punctuation 8, clipped clause 9, number/date inside the span 4), partial overlap 91, not in the stored window 301. Most of this subset is produced by `research_deep`, whose block holds the report's cited pages but whose *stored* text is the 8 k head of the report, so "not in the stored window" there is a storage artefact, not a paraphrase.
- **Fetched pages only (the record *is* the page): 89 spans — 55 verbatim (62 %), 2 near-verbatim (boundary punctuation), 4 partial, 28 beyond the 8 k window.** The deep-cited pages that were also fetched (`fetch_page + research_deep`, 5 spans) are 5/5 verbatim.
- Legitimately non-verbatim kinds: terminal punctuation added or dropped at the span boundary; a clause clipped at the end; a number or date restated inside the span (4 cases: a year, a contract length) — the last is the only kind that changes meaning.
- **AT-7**: confirm the mechanical rule (a quote must be found verbatim in the source text under the normaliser, else it is stored as a typed value with offset). Adjust the normaliser to NFKC + straight quotes + all dashes → `-` + whitespace **and literal escape sequences** collapsed + case-folded + **boundary punctuation stripped**; require digits and dates inside a span to match exactly; allow an ellipsis splice only with an explicit `…` marker and both halves verbatim.

## 6. Per-class counts versus the proposed caps

## T8 — A-class counts per class versus the proposed caps (accounts)
| Account | trigger (cap 10) | initiative (cap 5) | pain (cap 5) | motion_proof (cap 5) | stack (cap 4) | committee (cap 8) | watch_outs (cap 3) | not_found (cap 3) | firmographics | A total |
|---|---|---|---|---|---|---|---|---|---|---|
| nyc.gov | 4 | 0 | 1 | 2 | 4 | 5 | 4 **CUT** | 0 | 0 | 20 |
| firstfleetinc.com | 6 | 3 | 2 | 0 | 3 | 10 **CUT** | 3 | 0 | 0 | 27 |
| jrayl.com | 2 | 1 | 0 | 4 | 5 **CUT** | 6 | 1 | 0 | 0 | 19 |
| loopio.com | 8 | 3 | 1 | 3 | 3 | 4 | 1 | 0 | 0 | 23 |
| mortenson.com | 3 | 1 | 2 | 3 | 6 **CUT** | 7 | 2 | 2 | 1 | 27 |
| mckeefoods.com | 4 | 0 | 2 | 2 | 8 **CUT** | 4 | 2 | 0 | 1 | 23 |
| dialpad.com | 7 | 2 | 0 | 3 | 1 | 4 | 2 | 1 | 0 | 20 |
| **max seen** | 8 | 3 | 2 | 4 | 8 | 10 | 4 | 2 | | |

## T9 — A-class counts per class versus the proposed caps (contacts)
| Contact (account) | remit (cap 2) | problem_now (cap 3) | own_words (cap 6) | proud_of (cap 2) | hooks (cap 3) | career_arc (cap 1) | do_not_mention (cap 1) | A total |
|---|---|---|---|---|---|---|---|---|
| Andrew Flynn (dialpad.com) | 3 **CUT** | 2 | 8 **CUT** | 0 | 3 | 0 | 0 | 16 |
| Emily Wall (dialpad.com) | 2 | 2 | 5 | 2 | 0 | 0 | 0 | 11 |
| Jenny Coupe (dialpad.com) | 2 | 3 | 6 | 1 | 2 | 0 | 0 | 14 |
| Meaghan Edelstein (dialpad.com) | 5 **CUT** | 5 **CUT** | 1 | 0 | 0 | 0 | 0 | 11 |
| Sarah Rolfing (dialpad.com) | 2 | 2 | 0 | 1 | 0 | 0 | 0 | 5 |
| Austin Henderson (firstfleetinc.com) | 4 **CUT** | 0 | 10 **CUT** | 0 | 3 | 0 | 0 | 17 |
| Bronson Laney (firstfleetinc.com) | 2 | 0 | 1 | 3 **CUT** | 0 | 0 | 0 | 6 |
| John Cole (firstfleetinc.com) | 2 | 1 | 2 | 0 | 0 | 0 | 0 | 5 |
| Rebecca Wilson (firstfleetinc.com) | 1 | 0 | 3 | 1 | 0 | 0 | 0 | 5 |
| Robb Getts (firstfleetinc.com) | 3 **CUT** | 1 | 5 | 0 | 2 | 0 | 0 | 11 |
| Gene Shippy (jrayl.com) | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| Justin Yoder (jrayl.com) | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 4 |
| Matthew Parks (jrayl.com) | 4 **CUT** | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| Ryan Richards (jrayl.com) | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 3 |
| Toni Roberts (jrayl.com) | 2 | 0 | 0 | 1 | 0 | 0 | 0 | 3 |
| Alex Pace (loopio.com) | 4 **CUT** | 1 | 0 | 0 | 1 | 0 | 0 | 6 |
| Alison Hayter (loopio.com) | 4 **CUT** | 2 | 0 | 1 | 0 | 0 | 0 | 7 |
| Michelle Oke (loopio.com) | 4 **CUT** | 4 **CUT** | 3 | 0 | 1 | 0 | 0 | 12 |
| Siobhan Mondesire (loopio.com) | 2 | 7 **CUT** | 2 | 2 | 4 **CUT** | 0 | 0 | 17 |
| Vincent Lo (loopio.com) | 3 **CUT** | 2 | 5 | 0 | 0 | 0 | 0 | 10 |
| Andy Lang (mckeefoods.com) | 3 **CUT** | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| Chris McKee (mckeefoods.com) | 1 | 0 | 2 | 1 | 2 | 0 | 0 | 6 |
| Cindy Lyons (mckeefoods.com) | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| Don Gladden (mckeefoods.com) | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 3 |
| Kyler Vann (mckeefoods.com) | 2 | 0 | 1 | 0 | 1 | 0 | 0 | 4 |
| Athena Burkholder (mortenson.com) | 1 | 2 | 0 | 0 | 0 | 0 | 1 | 4 |
| Jean McGrory (mortenson.com) | 1 | 4 **CUT** | 0 | 0 | 0 | 0 | 0 | 5 |
| John Bachhuber (mortenson.com) | 4 **CUT** | 1 | 5 | 0 | 1 | 0 | 0 | 11 |
| Patrick Locken (mortenson.com) | 4 **CUT** | 0 | 2 | 0 | 1 | 0 | 0 | 7 |
| Robin Ritter (mortenson.com) | 2 | 1 | 1 | 1 | 2 | 0 | 0 | 7 |
| Beth Kushner (nyc.gov) | 4 **CUT** | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| Claire Levitt (nyc.gov) | 3 **CUT** | 0 | 0 | 1 | 0 | 0 | 0 | 4 |
| Octavia McCormick-Sharf (nyc.gov) | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 4 |
| Renee Campion (nyc.gov) | 3 **CUT** | 2 | 2 | 1 | 0 | 0 | 0 | 8 |
| Sang Hong (nyc.gov) | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| **max seen** | 5 | 7 | 10 | 3 | 4 | 0 | 1 | |

**Account caps.** A-class per class over the seven accounts: committee 40, trigger 34, stack 30, motion & proof 17, watch-outs 15, initiative 10, pain 8, not-found 3. Cuts at the proposed caps: Stack (J. Rayl 5, Mortenson 6, McKee Foods 8 vs 4 — seven A-class findings cut), Committee (FirstFleet 10 vs 8 — two cut), Watch-outs (NYC 4 vs 3 — one cut). Trigger (max 8), Initiative (3), Pain (2), Motion (4), Not-found (2) are never binding. **Recommend: Trigger 10, Initiative 5, Pain 5, Motion 5, Stack 8, Committee 10, Watch-outs 4, Not-found 3.** The Stack change matters most: for the benefits and fleet sellers the incumbent-vendor list *is* the fit assessment (TPA, PBM, stop-loss, clinic operator, HRIS, telematics, ELD, dash-cam), and each item is also a do-not-say.

**Contact caps.** A-class per class over 35 contacts: remit 90, own-words 67, problem-now 45, hooks 23, proud-of 16, do-not-mention 1. Cuts: own-words 6 (Henderson 10, Flynn 8 — six cut), problem-now 3 (Mondesire 7, Edelstein 5, Oke 4, McGrory 4 — eight cut), proud-of 2 (Laney 3), hooks 3 (Mondesire 4). Remit "2" is exceeded by 15 contacts, but only because the runs record one remit from three to five sources (profile, enrichment, org chart, bio); merged, no contact exceeds 2. **Recommend: remit 2 (merge corroborating records), problem-now 5, own-words 8, proud-of 3, hooks 4, career-arc 1, do-not-mention 1** (≈ 24 items). Median A per contact is 5; the caps bind only on the richest 4–5 contacts, which are exactly the ones the campaign will use.

## 7. Multi-source findings, negative space, namesakes

## T10 — Multi-source findings, negative-space findings and namesake / misattribution exclusions per run
| Run | Kind | findings | ≥2 sources (share) | ≥2 sources among A | multi-source kind mix (top) | negative-space (not found) | A among them | namesake / different-person | misattribution guards |
|---|---|---|---|---|---|---|---|---|---|
| dialpad.com | account | 57 | 6 (11%) | 5 | fetch_page+lookup_company+search_web 1, fetch_page+research_deep 1 | 2 | 2 | 0 | 1 |
| Andrew Flynn | person | 51 | 7 (14%) | 3 | research_deep+search_web 4, lookup_company+research_deep+search_web 3 | 3 | 2 | 4 | 0 |
| Emily Wall | person | 37 | 5 (14%) | 1 | fetch_page+lookup_person+read_people_result 1, fetch_page+search_web 1 | 3 | 0 | 3 | 0 |
| Jenny Coupe | person | 56 | 5 (9%) | 1 | research_deep 1, discover_media+discover_people+fetch_page+read_people_result+research_deep+search_web 1 | 0 | 0 | 0 | 0 |
| Meaghan Edelstein | person | 45 | 19 (42%) | 3 | fetch_page+search_web 9, fetch_page+research_deep 5 | 2 | 0 | 1 | 1 |
| Sarah Rolfing | person | 36 | 13 (36%) | 1 | fetch_page+search_web 8, discover_media+discover_people+fetch_page+research_deep+search_web 2 | 2 | 0 | 2 | 0 |
| firstfleetinc.com | account | 77 | 14 (18%) | 4 | research_deep 7, fetch_page+research_deep+search_web 2 | 1 | 0 | 0 | 0 |
| Austin Henderson | person | 59 | 3 (5%) | 2 | research_deep+search_web 2, fetch_page+research_deep 1 | 2 | 0 | 0 | 2 |
| Bronson Laney | person | 26 | 7 (27%) | 1 | search_web 3, lookup_person+research_deep+search_web 2 | 4 | 0 | 1 | 1 |
| John Cole | person | 36 | 7 (19%) | 2 | research_deep+search_web 4, search_web 1 | 3 | 0 | 4 | 0 |
| Rebecca Wilson | person | 30 | 6 (20%) | 1 | fetch_page+research_deep+search_web 4, fetch_page+search_web 1 | 5 | 0 | 4 | 0 |
| Robb Getts | person | 41 | 7 (17%) | 3 | search_web 3, fetch_page+lookup_person+research_deep+search_web 2 | 1 | 0 | 0 | 0 |
| jrayl.com | account | 67 | 3 (4%) | 1 | discover_media+fetch_page+research_deep+search_web 2, fetch_page+research_deep+search_web 1 | 2 | 0 | 1 | 0 |
| Gene Shippy | person | 30 | 5 (17%) | 2 | discover_media+fetch_page+search_web 4, fetch_page+research_deep+search_web 1 | 2 | 0 | 2 | 0 |
| Justin Yoder | person | 36 | 3 (8%) | 1 | research_deep 1, fetch_page+research_deep 1 | 0 | 0 | 3 | 2 |
| Matthew Parks | person | 35 | 2 (6%) | 0 | fetch_page+lookup_company+search_web 1, research_deep+search_web 1 | 5 | 0 | 5 | 2 |
| Ryan Richards | person | 42 | 5 (12%) | 0 | search_web 2, lookup_person+research_deep+search_web 1 | 1 | 0 | 3 | 0 |
| Toni Roberts | person | 36 | 2 (6%) | 0 | search_web 1, discover_media+fetch_page+research_deep+search_web 1 | 4 | 0 | 2 | 0 |
| loopio.com | account | 45 | 2 (4%) | 1 | discover_media+fetch_page+lookup_company+research_deep+search_web 1, fetch_page+lookup_company+search_web 1 | 1 | 1 | 0 | 0 |
| Alex Pace | person | 37 | 4 (11%) | 2 | fetch_page+research_deep 2, search_web 1 | 3 | 0 | 6 | 1 |
| Alison Hayter | person | 45 | 13 (29%) | 5 | fetch_page+lookup_company+research_deep+search_web 8, research_deep 3 | 4 | 0 | 2 | 0 |
| Michelle Oke | person | 43 | 11 (26%) | 4 | fetch_page+lookup_company+research_deep+search_web 2, research_deep 2 | 5 | 1 | 1 | 0 |
| Siobhan Mondesire | person | 55 | 8 (15%) | 2 | search_web 4, fetch_page+lookup_person+research_deep+search_web 2 | 0 | 0 | 2 | 0 |
| Vincent Lo | person | 53 | 16 (30%) | 5 | research_deep+search_web 11, research_deep 2 | 1 | 0 | 4 | 0 |
| mckeefoods.com | account | 60 | 9 (15%) | 3 | fetch_page+lookup_company+search_web 4, fetch_page+lookup_company+research_deep+search_web 3 | 1 | 0 | 1 | 0 |
| Andy Lang | person | 34 | 5 (15%) | 2 | lookup_person+research_deep+search_web 3, fetch_page+search_web 1 | 1 | 0 | 3 | 0 |
| Chris McKee | person | 54 | 12 (22%) | 1 | enrich_contact+fetch_page+lookup_person+search_web 4, research_deep+search_web 3 | 1 | 0 | 2 | 1 |
| Cindy Lyons | person | 23 | 1 (4%) | 0 | research_deep+search_web 1 | 5 | 0 | 6 | 0 |
| Don Gladden | person | 38 | 7 (18%) | 2 | fetch_page+lookup_company+research_deep+search_web 3, research_deep 2 | 6 | 1 | 3 | 2 |
| Kyler Vann | person | 26 | 2 (8%) | 1 | fetch_page+search_web 1, fetch_page+research_deep+search_web 1 | 2 | 0 | 1 | 2 |
| mortenson.com | account | 67 | 12 (18%) | 7 | fetch_page+search_web 3, research_deep+search_web 3 | 4 | 3 | 0 | 0 |
| Athena Burkholder | person | 27 | 9 (33%) | 3 | fetch_page+lookup_person+research_deep+search_web 6, fetch_page+search_web 1 | 1 | 0 | 4 | 0 |
| Jean McGrory | person | 46 | 1 (2%) | 0 | research_deep 1 | 3 | 2 | 3 | 0 |
| John Bachhuber | person | 37 | 3 (8%) | 0 | search_web 1, lookup_person+research_deep 1 | 2 | 0 | 2 | 1 |
| Patrick Locken | person | 32 | 5 (16%) | 0 | lookup_person+research_deep 4, fetch_page+research_deep+search_web 1 | 4 | 0 | 1 | 0 |
| Robin Ritter | person | 47 | 6 (13%) | 0 | fetch_page+search_web 2, fetch_page+research_deep+search_web 2 | 0 | 0 | 3 | 1 |
| nyc.gov | account | 63 | 9 (14%) | 5 | fetch_page+research_deep+search_web 4, research_deep 3 | 2 | 0 | 0 | 0 |
| Beth Kushner | person | 27 | 2 (7%) | 0 | fetch_page+search_web 1, search_web 1 | 3 | 0 | 5 | 0 |
| Claire Levitt | person | 49 | 4 (8%) | 0 | search_web 2, research_deep 1 | 0 | 0 | 3 | 0 |
| Octavia McCormick-Sharf | person | 20 | 7 (35%) | 2 | research_deep 3, fetch_page+research_deep+search_web 2 | 2 | 0 | 0 | 0 |
| Renee Campion | person | 43 | 6 (14%) | 0 | research_deep+search_web 2, discover_media+fetch_page+research_deep+search_web 2 | 1 | 0 | 1 | 0 |
| Sang Hong | person | 14 | 4 (29%) | 0 | research_deep 1, discover_media+fetch_page+research_deep+search_web 1 | 2 | 0 | 3 | 0 |
| **all** | | 1782 | 277 (16%) | 76 | | 96 | 12 | 91 | 17 |

Reading: 16 % of findings cite two or more records (19 % of A-class); the dominant two-source mix is a search result plus the deep report or a fetched page, i.e. corroboration between a snippet and the full page rather than two independent publishers. Negative-space findings (96) are mostly honest process statements ("no long-form interview located", "no original post in the window"); the 12 A-class ones are the ones the plan's Not-found class wants: a vacant or unnamed seat (Dialpad CMO, Mortenson's benefits leader search), an absent vendor relationship (Mortenson: no Garner customer evidence; Wall: no named ABM stack), a complaint that was looked for and not found (Mortenson medical-trend). Namesake exclusions are a contact-run cost: 91 findings, up to six per contact, almost all C-class; one do-not-mention per contact (the plan's cap) is the right output, the rest belongs in the acquisition ledger.

## 8. Fixtures

## T11 — Fixture sizes per account
| Account | account A findings | contact A findings (sum) | follow-up chains with ≥1 A finding (strict-backed) |
|---|---|---|---|
| dialpad.com | 20 | 57 | 37 (10) |
| firstfleetinc.com | 27 | 44 | 24 (10) |
| jrayl.com | 19 | 16 | 16 (1) |
| loopio.com | 23 | 52 | 21 (4) |
| mckeefoods.com | 23 | 17 | 37 (8) |
| mortenson.com | 27 | 34 | 45 (21) |
| nyc.gov | 20 | 22 | 24 (6) |

- `fixtures/nothing_lost/<account>.json` — per account and per contact, every A-class finding as `(class, key_phrase, date, source_kinds, n_sources, chain_depth, follow_up ∈ strict|possible|template|unresolved, trigger_kinds)`; these are the AT-6 replay fixtures (a v26 run on the same subject must reproduce each item by key phrase and class).
- `fixtures/chains/<account>.json` — per account, every follow-up operation that produced an A-class finding: trigger kind, trigger terms (names, titles, phrases, URL hosts), the operations that surfaced the trigger, the issued operation, hop depth, and the A-class findings it is the only producer of (`A_findings_strict`) or one producer of (`A_findings_possible`); these are the AT-9 chain fixtures.
- `fixtures/rule_table.json` — the §3 table with examples per pair.
- `fixtures/quote_fidelity.json` — every quoted span with its verdict; `fixtures/summary.json` — per-run numbers.
- Scripts beside them: `extract_findings.py`, `map_evidence.py`, `classify_ops.py`, `rate_findings.py` (+ `overrides.json` with the hand ratings), `build_outputs.py`, `quote_fidelity.py`, `write_doc.py`.

### 8.1 Chain digest per account (strict-backed chains; batch-ambiguous ones summarised)

### dialpad.com — 10 strict-backed chains, 27 batch-ambiguous chains
| Issued by | Trigger kind | Trigger (name / title / term / URL host) | Op | Hop | A-class findings whose cited evidence comes only from follow-up operations, this one among the candidates (run: id class; — = same run) |
|---|---|---|---|---|---|
| dialpad.com | person-name | linkedin.com/in | fetch_page | 1 | Emily: F001 remit; Emily: F024 problem_now; —: F019 trigger; —: F036 committee |
| Andrew Flynn | vendor-stack | Talkdesk Industries | search_web | 1 | —: F019 own_words; —: F022 own_words; —: F026 own_words; —: F027 own_words; —: F051 problem_now |
| Andrew Flynn | vendor-stack | Andy Talkdesk; Experience Clouds | search_web | 2 | —: F037 hooks; —: F040 hooks; —: F041 hooks |
| Andrew Flynn | person-name | Yes Entertainment | search_web | 1 | —: F037 hooks; —: F040 hooks; —: F041 hooks |
| Andrew Flynn | quoted-phrase | Marlins Cal Athletics Broncos | search_web | 1 | —: F037 hooks; —: F040 hooks; —: F041 hooks |
| Andrew Flynn | vendor-stack | Talkdesk | search_web | 2 | —: F037 hooks; —: F040 hooks; —: F041 hooks |
| Sarah Rolfing | quoted-phrase | Core Create; Creative Common Sense | search_web | 1 | —: F001 remit; —: F002 remit |
| Sarah Rolfing | person-name | Shilpa Narwade VP | search_web | 1 | —: F001 remit; —: F002 remit |
| Sarah Rolfing | url-in-result | sarahrolfing.weebly.com | fetch_page | 1 | —: F001 remit; —: F002 remit |
| Sarah Rolfing | profile-aggregator | theorg.com/org | fetch_page | 1 | —: F001 remit; —: F002 remit |

Batch-ambiguous chains (the operation is one of several same-batch candidates for the A-class findings; counts only): dialpad.com funding-financial→search_web (4 A), dialpad.com person-name→fetch_page (2 A), dialpad.com post-by-other→fetch_page (4 A), dialpad.com departure-succession→search_web (2 A), dialpad.com vendor-customer-page→fetch_page (2 A), dialpad.com site-restricted→search_web (2 A), dialpad.com title-in-posting→search_web (13 A), dialpad.com other-specific→search_web (13 A), Andrew partner-channel→search_web (4 A), Andrew person-name→search_web (4 A), Emily education-prior-employer→search_web (6 A), Emily event-talk-media→search_web (6 A), Emily vendor-stack→search_web (1 A), Emily quoted-phrase→search_web (1 A), Emily customer-case-study→search_web (1 A), Emily own-post→fetch_page (2 A), Emily own-post→fetch_page (2 A), Emily own-post→fetch_page (2 A), Jenny funding-financial→search_web (1 A), Jenny vendor-stack→search_web (1 A), Jenny url-in-result→fetch_page (1 A), Jenny own-post→fetch_.

### firstfleetinc.com — 10 strict-backed chains, 14 batch-ambiguous chains
| Issued by | Trigger kind | Trigger (name / title / term / URL host) | Op | Hop | A-class findings whose cited evidence comes only from follow-up operations, this one among the candidates (run: id class; — = same run) |
|---|---|---|---|---|---|
| Austin Henderson | own-post | linkedin.com/posts | fetch_page | 1 | —: F020 hooks |
| Austin Henderson | own-post | linkedin.com/posts | fetch_page | 1 | —: F053 own_words |
| John Cole | quoted-phrase | Four | search_web | 1 | —: F029 problem_now |
| John Cole | title-in-posting | Assistant Safety Director | search_web | 1 | —: F029 problem_now |
| Rebecca Wilson | own-post | linkedin.com/posts | fetch_page | 1 | —: F013 own_words |
| Rebecca Wilson | post-by-other | linkedin.com/posts | fetch_page | 1 | —: F005 proud_of; —: F011 own_words |
| Rebecca Wilson | own-post | linkedin.com/posts | fetch_page | 1 | —: F011 own_words |
| Rebecca Wilson | own-post | linkedin.com/posts | fetch_page | 1 | —: F011 own_words |
| Robb Getts | prior-employer-affiliation | Four Hitch Driver Appreciation Werner | search_web | 1 | —: F021 hooks; —: F024 own_words; —: F026 own_words |
| Robb Getts | vendor-stack | Motive | search_web | 1 | —: F021 hooks; —: F024 own_words; —: F026 own_words |

Batch-ambiguous chains (the operation is one of several same-batch candidates for the A-class findings; counts only): firstfleetinc.com vendor-stack→search_web (4 A), firstfleetinc.com url-in-result→fetch_page (2 A), Austin vendor-stack→search_web (3 A), Austin person-name→search_web (3 A), Austin vendor-stack→search_web (1 A), Bronson person-name→search_web (2 A), Bronson quoted-phrase→search_web (2 A), Rebecca event-talk-media→search_web (2 A), Rebecca quoted-phrase→search_web (2 A), Robb vendor-stack→search_web (5 A), Robb education-prior-employer→search_web (5 A), Robb location→search_web (5 A), Robb own-post→fetch_page (1 A), Robb own-post→fetch_page (1 A).

### jrayl.com — 1 strict-backed chains, 15 batch-ambiguous chains
| Issued by | Trigger kind | Trigger (name / title / term / URL host) | Op | Hop | A-class findings whose cited evidence comes only from follow-up operations, this one among the candidates (run: id class; — = same run) |
|---|---|---|---|---|---|
| Justin Yoder | vendor-customer-page | samsara.com/customers | fetch_page | 1 | —: F030 own_words; —: F031 own_words |

Batch-ambiguous chains (the operation is one of several same-batch candidates for the A-class findings; counts only): jrayl.com person-name→search_web (6 A), jrayl.com vendor-stack→search_web (6 A), jrayl.com url-in-result→fetch_page (2 A), jrayl.com subject-site-page→fetch_page (2 A), jrayl.com other-specific→search_web (2 A), jrayl.com vendor-stack→search_web (2 A), jrayl.com subject-site-page→fetch_page (1 A), jrayl.com subject-site-page→fetch_page (1 A), jrayl.com other-specific→search_web (5 A), jrayl.com other-specific→search_web (5 A), jrayl.com person-name→search_web (5 A), Justin education-prior-employer→search_web (4 A), Justin vendor-stack→search_web (4 A), Toni education-prior-employer→search_web (3 A), Toni quoted-phrase→search_web (3 A).

### loopio.com — 4 strict-backed chains, 17 batch-ambiguous chains
| Issued by | Trigger kind | Trigger (name / title / term / URL host) | Op | Hop | A-class findings whose cited evidence comes only from follow-up operations, this one among the candidates (run: id class; — = same run) |
|---|---|---|---|---|---|
| loopio.com | event-talk-media | Siobhan Mondesire | search_web | 1 | Siobhan: F040 problem_now; —: F017 initiative; —: F040 pain |
| loopio.com | vendor-stack | Demandbase HubSpot Salesforce | search_web | 1 | Siobhan: F040 problem_now; —: F017 initiative; —: F040 pain |
| loopio.com | funding-financial | Series C Insight Partners | search_web | 1 | Siobhan: F040 problem_now; —: F017 initiative; —: F040 pain |
| Vincent Lo | quoted-phrase | Novter Solutions; Quanser IBM Rational; World Unwired | search_web | 1 | —: F047 own_words |

Batch-ambiguous chains (the operation is one of several same-batch candidates for the A-class findings; counts only): loopio.com title-in-posting→search_web (3 A), loopio.com person-name→search_web (3 A), loopio.com url-in-result→fetch_page (11 A), loopio.com subject-site-page→fetch_page (10 A), loopio.com other-specific→search_web (9 A), loopio.com post-by-other→fetch_page (11 A), loopio.com other-specific→search_web (9 A), loopio.com job-listing→fetch_page (11 A), loopio.com job-listing→fetch_page (11 A), loopio.com person-name→fetch_page (1 A), Alex job-listing→fetch_page (3 A), Alison person-name→search_web (3 A), Michelle person-name→search_web (1 A), Michelle event-talk-media→search_web (1 A), Siobhan event-talk-media→search_web (9 A), Siobhan person-name→search_web (9 A), Siobhan person-name→search_web (9 A).

### mckeefoods.com — 8 strict-backed chains, 29 batch-ambiguous chains
| Issued by | Trigger kind | Trigger (name / title / term / URL host) | Op | Hop | A-class findings whose cited evidence comes only from follow-up operations, this one among the candidates (run: id class; — = same run) |
|---|---|---|---|---|---|
| mckeefoods.com | person-name | linkedin.com/in | fetch_page | 1 | Kyler: F001 remit; Kyler: F002 own_words; Kyler: F003 remit; Kyler: F026 hooks; —: F042 committee |
| mckeefoods.com | person-name | linkedin.com/in | fetch_page | 1 | Kyler: F001 remit; Kyler: F002 own_words; Kyler: F003 remit; Kyler: F026 hooks; —: F042 committee |
| Andy Lang | person-name | Barry Patterson | search_web | 1 | Kyler: F026 hooks |
| Andy Lang | url-in-result | 401k-lookup.com/Company401k | fetch_page | 1 | Kyler: F026 hooks |
| Cindy Lyons | education-prior-employer | McNeese State University | search_web | 1 | —: F001 remit |
| Cindy Lyons | quoted-phrase | McKeeFIT | search_web | 1 | —: F001 remit |
| Cindy Lyons | site-restricted | linkedin.com | search_web | 1 | —: F001 remit |
| Kyler Vann | url-in-result | github.com/kvann22 | fetch_page | 1 | —: F026 hooks |

Batch-ambiguous chains (the operation is one of several same-batch candidates for the A-class findings; counts only): mckeefoods.com person-name→search_web (11 A), mckeefoods.com other-specific→search_web (11 A), mckeefoods.com other-specific→search_web (11 A), mckeefoods.com person-name→search_web (2 A), mckeefoods.com url-in-result→fetch_page (1 A), mckeefoods.com url-in-result→fetch_page (2 A), mckeefoods.com url-in-result→fetch_page (2 A), mckeefoods.com url-in-result→fetch_page (2 A), mckeefoods.com url-in-result→fetch_page (2 A), mckeefoods.com other-specific→search_web (5 A), mckeefoods.com title-in-posting→search_web (5 A), mckeefoods.com quoted-phrase→search_web (2 A), mckeefoods.com person-name→search_web (2 A), mckeefoods.com url-in-result→fetch_page (1 A), Andy person-name→search_web (1 A), Andy education-prior-employer→search_web (1 A), Andy quoted-phrase→search_web (2 A), Andy prior-employer-affiliation→search_web (1 A), Andy person-name→search_web (1 A), Andy person-name→search_web (1 A),.

### mortenson.com — 21 strict-backed chains, 24 batch-ambiguous chains
| Issued by | Trigger kind | Trigger (name / title / term / URL host) | Op | Hop | A-class findings whose cited evidence comes only from follow-up operations, this one among the candidates (run: id class; — = same run) |
|---|---|---|---|---|---|
| mortenson.com | person-name | TPA UnitedHealthcare Blue Cross | search_web | 1 | —: F020 motion_proof; —: F021 stack; —: F024 watch_outs; —: F026 stack; —: F030 trigger; —: F031 committee; —: F032 committee; —: F037 stack; —: F038 stack; —: F051 initi |
| mortenson.com | other-specific | 5500; Form | search_web | 1 | —: F020 motion_proof; —: F021 stack; —: F024 watch_outs; —: F026 stack; —: F030 trigger; —: F031 committee; —: F032 committee; —: F037 stack; —: F038 stack; —: F051 initi |
| mortenson.com | person-name | Dan Johnson | search_web | 1 | —: F020 motion_proof; —: F021 stack; —: F024 watch_outs; —: F026 stack; —: F030 trigger; —: F031 committee; —: F032 committee; —: F037 stack; —: F038 stack; —: F051 initi |
| mortenson.com | press-release-url | mortenson.com/news-insights | fetch_page | 1 | —: F041 stack; —: F044 committee |
| mortenson.com | url-in-result | 401k-lookup.com/Company401k | fetch_page | 1 | —: F033 trigger |
| Jean McGrory | person-name | Digital River | search_web | 1 | —: F040 problem_now |
| Jean McGrory | education-prior-employer | University Iowa MBA | search_web | 1 | —: F040 problem_now |
| Jean McGrory | person-name | ADC Telecommunications | search_web | 1 | —: F040 problem_now |
| Jean McGrory | event-talk-media | SHRM WorldatWork | search_web | 1 | —: F040 problem_now |
| Jean McGrory | person-name | West HR | search_web | 1 | —: F040 problem_now |
| Jean McGrory | event-talk-media | Groundbreaking Women | search_web | 1 | Robin: F016 hooks |
| Jean McGrory | quoted-phrase | Star Tribune | search_web | 1 | Robin: F016 hooks |
| Jean McGrory | url-in-result | enr.com/groundbreaking-women-in-construction | fetch_page | 1 | Robin: F016 hooks |
| John Bachhuber | person-name | Derek Boll Mercer | search_web | 1 | Robin: F016 hooks; —: F004 remit; —: F014 own_words |
| John Bachhuber | quoted-phrase | 5500; Form | search_web | 1 | Robin: F016 hooks; —: F004 remit; —: F014 own_words |
| Robin Ritter | person-name | Cargill HR | search_web | 1 | —: F001 remit; —: F002 remit |
| Robin Ritter | event-talk-media | CHRO | search_web | 1 | —: F001 remit; —: F002 remit |
| Robin Ritter | prior-employer-affiliation | General Mills Director Supply Chain | search_web | 1 | —: F001 remit; —: F002 remit |
| Robin Ritter | event-talk-media | University Illinois Speech Communication | search_web | 1 | —: F001 remit; —: F002 remit |
| Robin Ritter | person-name | Debunking Executive Presence; Groundbreaking Women | search_web | 1 | —: F001 remit; —: F002 remit |
| Robin Ritter | subject-site-page | mortenson.com/team | fetch_page | 1 | —: F001 remit; —: F002 remit |

Batch-ambiguous chains (the operation is one of several same-batch candidates for the A-class findings; counts only): mortenson.com other-specific→search_web (3 A), mortenson.com url-in-result→fetch_page (1 A), mortenson.com subject-site-page→fetch_page (11 A), mortenson.com title-in-posting→search_web (11 A), mortenson.com customer-case-study→search_web (1 A), mortenson.com vendor-stack→search_web (1 A), mortenson.com subject-site-page→fetch_page (1 A), mortenson.com url-in-result→fetch_page (1 A), mortenson.com url-in-result→fetch_page (1 A), mortenson.com url-in-result→fetch_page (1 A), mortenson.com quoted-phrase→search_web (2 A), Athena person-name→search_web (2 A), Athena education-prior-employer→search_web (2 A), Athena url-in-result→fetch_page (1 A), Athena person-name→search_web (1 A), Athena person-name→search_web (1 A), John education-prior-employer→search_web (5 A), John person-name→search_web (5 A), Robin own-post→fetch_page (4 A), Robin own-post→fetch_page (4 A), Robin own-post→fetch_page .

### nyc.gov — 6 strict-backed chains, 18 batch-ambiguous chains
| Issued by | Trigger kind | Trigger (name / title / term / URL host) | Op | Hop | A-class findings whose cited evidence comes only from follow-up operations, this one among the candidates (run: id class; — = same run) |
|---|---|---|---|---|---|
| nyc.gov | subject-site-page | nyc.gov/site | fetch_page | 1 | Renee: F002 remit; Claire: F001 remit; Sang: F001 remit; —: F008 watch_outs; —: F027 trigger; —: F037 committee; —: F038 motion_proof; —: F039 committee; —: F053 pain; Be |
| nyc.gov | subject-site-page | council.nyc.gov/budget | fetch_page | 1 | —: F008 watch_outs |
| nyc.gov | subject-site-page | nyc.gov/assets | fetch_page | 1 | —: F008 watch_outs; —: F027 trigger; —: F039 committee |
| nyc.gov | initiative-program | Health Benefits Program | search_web | 1 | Renee: F002 remit; Claire: F001 remit; Sang: F001 remit; —: F008 watch_outs; —: F027 trigger; —: F037 committee; —: F038 motion_proof; —: F039 committee; —: F053 pain; Be |
| nyc.gov | person-name | Paul Ochoa DDC | search_web | 1 | Renee: F002 remit; Claire: F001 remit; Sang: F001 remit; —: F008 watch_outs; —: F027 trigger; —: F037 committee; —: F038 motion_proof; —: F039 committee; —: F053 pain; Be |
| nyc.gov | person-name | NYCE PPO EmblemHealth | search_web | 1 | Renee: F002 remit; Claire: F001 remit; Sang: F001 remit; —: F008 watch_outs; —: F027 trigger; —: F037 committee; —: F038 motion_proof; —: F039 committee; —: F053 pain; Be |

Batch-ambiguous chains (the operation is one of several same-batch candidates for the A-class findings; counts only): nyc.gov other-specific→search_web (1 A), nyc.gov other-specific→search_web (1 A), nyc.gov person-name→search_web (1 A), nyc.gov other-specific→search_web (1 A), nyc.gov url-in-result→fetch_page (6 A), nyc.gov other-specific→search_web (4 A), nyc.gov other-specific→search_web (4 A), Beth person-name→search_web (2 A), Beth initiative-program→search_web (2 A), Beth quoted-phrase→search_web (2 A), Claire event-talk-media→search_web (2 A), Claire person-name→search_web (2 A), Octavia person-name→search_web (2 A), Octavia quoted-phrase→search_web (2 A), Octavia quoted-phrase→search_web (2 A), Octavia prior-employer-affiliation→search_web (2 A), Sang initiative-program→search_web (1 A), Sang quoted-phrase→search_web (1 A).


## 9. Limits of this analysis

- The evidence → operation map is reconstructed; within a batch it cannot say which query produced a record (validated: 0 wrong producers on the 30 Dialpad records with known producers, but 28 of them resolve to the batch). Everything above therefore reports strict and possible bounds.
- 190 of 404 follow-ups are *inferred* (their trigger term is not visible in stored text because Exa search results store no text); their trigger kind is assigned from the query alone.
- Ratings on 39 of 42 runs are this lane's, on the reviewer's rubric; the three reviewer-rated runs agree 100 % by construction. The rule-based pass over-rated A by 1.3–2.2× before the hand pass, so a reader should expect ±15 % on any single run's A count and far less on the totals.
- Quote fidelity is judged on the 89 fetched-page spans with one certain producer; the deep-report spans cannot be judged in this corpus.
- The trigger-kind rules are heuristics: `person-name` is assigned to any 2–4-word capitalised term that is not a known vendor, so it also catches organisation and programme names (an upper bound on true person-name follow-ups); `quoted-phrase` covers any quoted multi-word search term.
- Stored outputs are cut at ~8 k characters; the v1-pulled traces (the 10-03 family and three 10-06 contacts) have no stored outputs at all, so their follow-ups are classified from queries and read order only.
