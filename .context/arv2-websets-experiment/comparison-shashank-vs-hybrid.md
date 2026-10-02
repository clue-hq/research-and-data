# Shashank's v3 discovery vs the hybrid run — same ICP, same day, same grader (2026-09-10)

**His method, run verbatim** (`.context/arv2-shashank-v3-rerun/`, his `step1_discovery.py` and
`clue_lib.py` copied unchanged): three Exa `/search` queries, `type=auto`, 10 results each, text
bundled, published after 2025-06-01. $0.021, about 8 seconds.

**Ours** (`hybrid/`): one Exa webset in company mode with the ICP's three page-answerable gates as
criteria, then our probe on every company. Webset 150 credits (≈ $0.67 Pro), 7 min 21 s; probe
$0.105, ~100 s.

**Grader for both**: the same probe code (stage from one cheap search, geography from the record
plus datelines, hiring and intent from the company's own job board). Vertical fit for his
candidates was judged by hand from the announcements, since no webset criterion ran on them.

## 1. Finding companies

| | His three queries | Our webset |
|---|---|---|
| Pages returned | 30 | — |
| Distinct **companies** among them | **6**, all from query 1 (Lassie, Probook, Pie, Rebar, GenHealth.ai, Avoca) | **15** |
| Non-company pages | 24: query 2 = 10 job posts (Clera, Verso/Hexa, two Pear portfolio companies, Jampack, Salesjack, Optimal AI, Prairie, Careerium — enterprise, industrial, CPG, Paris; none a vertical SMB SaaS); query 3 = 10 sales-advice pages and podcasts | 0 |
| Known-good accounts surfaced (Probook, Lassie) | both | both (Probook with the wrong website, `probook.com`) |
| Overlap between the two lists | Lassie, Probook, Rebar (Rebar was in this morning's webset) | |
| Cost per distinct company | $0.0035 | ≈ $0.052 incl. the probe |
| Time | 8 s | 7.5 min |

Query 1 is the only one of his three that finds companies; queries 2 and 3 find content *about*
the ICP. His own v3 report recorded exactly this. Today's query 1 also surfaced Rebar and
GenHealth.ai that the morning run did not — Exa's index moves day to day.

## 2. Grading, same probe on both lists

| Company | From | stage | geo | hiring | intent | fit | Note |
|---|---|---|---|---|---|---|---|
| Probook | his (and ours, wrong URL) | ✅ | ✅ | ✅ 5 GTM of 13 (Ashby) | ✅ "Outbound pipeline: Build and execute…" | **100 High** | the only company passing all four gates from either list |
| Lassie | both | ✅ | ✅ | ✅ 4 GTM of 16 (Ashby) | ❓ Q7 only | 87 High | |
| Rebar | both | ✅ | ❓ "European" in a Crunchbase highlight (a false alarm from the dateline check) | ✅ 3 GTM of 7 (Ashby) | ✅ "…outbound sales" | 87 High | |
| Pie | his | ✅ | ✅ | ❓ | ❓ | 75 | I guessed `pie.com` as its site, which the rules forbid; the fetch failed. Vertical is horizontal "Main Street", unclear by hand |
| GenHealth.ai | his | ✅ (Series A 2026-09-08) | ✅ | ❓ careers page only | ❓ | 75 | medical back office, vertical pass by hand |
| Avoca | his | ✅ **wrong** — Series B, April 2026; the votes tied 4–4 between 'series a' and 'series b' and the tie fell the wrong way | ✅ | ❓ | ❓ | 75 | the probe's stage regex failed here even after today's fixes |
| Boostly | ours | ✅ | ✅ | ✅ | ✅ | 100 High | |
| Snout, INFI, Superorder, BeyondTrucks, Equal Parts | ours | ✅ | ✅ | ❓ | ❓ | 75 High | no readable board |
| Patientdesk, 1Fort, &AI, DentalHQ, Lasso MD | ours | ❌ pre-seed/seed | ✅ | ❓ | ❓ | 50 Medium | Websets admitted them as Series A |
| Levanta | ours | ❌ Series B | ❓ | ✅ | ✅ | 62 | |
| Digs | ours | ✅ | ❓ | ❌ no GTM on Greenhouse | ❓ | 50 | |

## 3. What the comparison says

1. **On finding companies, the webset is better and the difference is not close.** Fifteen real
   companies against six, with no noise pages against twenty-four. Both find the two known-good
   accounts. His query 1 is a good *angle*; his queries 2 and 3 are not discovery.
2. **On judging, neither method is trustworthy as built.** His proof of concept judged by having the
   agent read pages by hand — general, and correct on Probook, but fifteen extra calls for one
   account. Our probe judged with regexes — fast and cheap, but it mis-graded Avoca today (Series B
   read as Series A), flagged Rebar's geography on a stray word, and cannot read most job boards.
   Websets' own verdicts were wrong six times in fifteen. Every judging method that guesses from
   patterns or from a provider's label failed somewhere on this small set.
3. **The two known-good accounts pass only when the judging reads the company's own pages** — the
   Ashby board and the announcement — and quotes them. That is the property to build on, not the
   regex and not the provider label.
4. **His method is cheaper and faster by a wide margin** ($0.021 and 8 s against about $0.80 and
   8 min). At the scale of the exit gate that gap does not matter; at production scale it is an
   argument for running the search angle first and the webset second, not for choosing one.

**Conclusion for the discussion:** finding = the union of angles, of which his query 1 and the
webset are the two proven ones; judging = the ICP's own gate text read against fetched evidence by
a model that must quote, which is what his proof of concept did by hand and what none of today's
code does.
