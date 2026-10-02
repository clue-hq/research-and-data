# Hybrid discovery PoC — evaluation (Fable, 2026-09-10)

**What ran.** One Exa webset (entity=company, 35 requested, three criteria: US HQ; *most recent*
round is a Series A or A-extension within 24 months; sells software/AI to one fragmented SMB
vertical) over the v3 ICP. Then our probe graded every returned company on the four ICP hard gates
in code: stage from one cheap Exa search ($0.007), geography from the Websets HQ field cross-checked
against datelines, hiring from the company's own Ashby/Greenhouse/Lever board (free), intent from
the GTM postings' text (the ICP's Q1 phrases, quoted), employees > 800 as an exclusion. Fit =
passes / gates with unclear as half a pass; bands are the accounts list's own (High ≥ 0.70,
Medium ≥ 0.40). Files: `run_hybrid.py`, `hybrid_results.md` (table + every reason and reference),
`hybrid_graded.json`, raw under `../raw/hybrid_*`, ledger `../ledger.json`.

## Numbers

| | |
|---|---|
| Websets: found / analyzed / requested | 15 / 333 / 35 — it hit its search limit before filling the count |
| Websets time to idle | 7 min 21 s |
| Websets credits (10 per all-green) | 150 ≈ $0.67 Pro / $0.92 Core |
| Probe: stage searches | 15 × $0.007 = $0.105; ATS and careers reads free |
| Probe wall time | ~100 s for 15 companies |
| Our stage verdicts vs Websets' | Websets said all 15 satisfy the stage criterion; **we pass 9, fail 6** (four pre-seed/seed: Patientdesk, 1Fort, &AI, DentalHQ, Lasso MD; one Series B: Levanta) |
| Boards read | 4 (Digs, Lassie, Levanta, Boostly) + Probook once its real URL is used |
| Full passes (all four gates) | 1 (Boostly) + Probook with its real URL |
| Bands | High 7, Medium 8, Low 0 |

## Observations, in order of weight

1. **Websets is the right long-list builder, and it is still wrong on stage 40% of the time even
   with the criterion written correctly.** Six of fifteen "most recent round is Series A" verdicts
   were false (pre-seed and seed companies, one Series B). Our probe caught all six for seven
   thousandths of a dollar each. The design stands: Websets proposes, the probe grades.
2. **The pool is smaller than the ask.** With honest criteria Exa exhausted its search at 15 matches
   from 333 candidates. "Ask for 35" does not yield 35; the count is an upper bound, and R4 should
   read `found` versus `analyzed` as a signal that the ICP is narrow rather than retry.
3. **Websets' URL for a company can be wrong, and that poisons every downstream read.** It returned
   `probook.com` for Probook (the real site is `probook.ai`). With the wrong URL the probe found no
   board and no HQ → Medium 62 unclear. With the right URL: Ashby board, 13 roles, 5 GTM, an SDR
   posting saying "Outbound pipeline: build and execute…" → High 87 with stage, hiring and intent
   all passed. R4 must verify the URL (the announcement's own link to the company site, or the
   domain the stage probe's results agree on) before the dedupe and the reads run on it.
4. **Free ATS reads cover four of fifteen companies.** Small Series A companies use Gem, Workable,
   Rippling or a hand-built page. The first careers-page fallback (regex over page text) produced
   false positives — "Dental Marketing Solutions" and a Google Tag Manager id read as GTM job
   titles — so it was replaced by an honest `unclear` that hands the human the careers page URL.
   Hiring/intent therefore stay unclear for most of the list until more board providers are read.
5. **Stage classification needs three rules, all found by this run:** (a) decide by the most recent
   *announcement*, not by the most recent page (a 2026 LinkedIn profile page repeating "seed"
   outvoted BeyondTrucks' 2024 Series A); (b) within that date, majority vote, a title mention
   counting three (a seed announced together with the A is an A: Probook 'series a' 17 vs 'seed'
   12); (c) fall back to profile pages only when no announcement carries a label (Lasso MD).
6. **Intent is only ever proven from a posting's text.** Two passes (Levanta, Boostly) plus Probook
   with the right URL, every one with a verbatim quote and the posting URL. Lassie has four GTM
   openings but no Q1 language, so it stays unclear on intent — Q7 alone is one Tier-2 signal, and
   the ICP asks for two.
7. **Nobody scored Low.** Every company Websets admitted is at least US + vertical, so the floor is
   Medium 50. The bands would spread once exclusions (B2C, ABM platform present, > 800 employees)
   are graded from page text; only the employee count was checked here.

## What this settles for the R4 substance document

- Keep §2 (Websets, three criteria) and §3 (the probe) as ruled; add: URL verification before
  dedupe/reads; the three stage rules above; careers page = unclear + reference, never a pass;
  `found < requested` is a normal outcome recorded on the run, not an error.
- The board reader should grow beyond Ashby/Greenhouse/Lever (Gem, Workable, Rippling have public
  JSON too) — a follow-up with measured coverage, not a guess.
- Cost per graded company on this run: ≈ $0.052 at Pro (webset credits + probe), all of it recorded,
  none of it capped.
