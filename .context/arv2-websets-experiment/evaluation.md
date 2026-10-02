# Exa Websets vs Exa `/search` for account discovery — evaluation (Fable, 2026-09-10)

Same input for every arm: the v3 proof of concept's ICP (founder ruling 1 in
`.context/arv2-clue-sample-v3/BRIEF.md`). Discovery only; no Websets enrichment. Raw responses in
`raw/`, every call in `ledger.json`, tables in `summary.md`.

**Grading standard.** A company passes when its **most recent** round is a Series A or A-extension
announced within ~24 months of 2026-09-09, it is headquartered in the US, and it sells software or
AI into one fragmented SMB vertical. Stage was checked independently for every Websets company with
one cheap `/search` each (`raw/probe_stage_*.json`, $0.007 × 25 = $0.175), not taken from Websets'
verdict. Hiring and intent were not graded here: W3 leaves them to our own probe by design, and W5
returned one company.

## Results

| Arm | Calls | Distinct companies | Pass | Unclear | Fail | Wall time | Spend |
|---|---|---|---|---|---|---|---|
| S — `/search`, 3 v3 queries | 3 | 4 (+7 job-post employers, none in a vertical) | 2 (Lassie, Probook) | 1 (Pie) | 1 (Avoca) | 6 s | $0.021 |
| W3 — webset, 3 verifiable criteria, count 25 | 1 + polls | 25 (449 analyzed) | **14** | 4 | 7 | ~5 min | 250 credits ≈ $1.12 Pro / $1.53 Core |
| W5 — webset, all 5 gates as criteria, count 25 | 1 + polls | 1 (334 analyzed, search limit hit) | 1 (Outmarket AI) | 0 | 0 | ~8 min | 10 credits ≈ $0.045 |

Overlap: W3 found Lassie; it did not surface Probook or Pie before its count of 25 filled. S found
none of W3's other 13 passes. The two mechanisms find largely different companies.

### Arm S, per company

- **Lassie** — $35M Series A 2026-06-03, SF, dental. Pass.
- **Probook** — $34M Series A 2026-06-23, NY, home services. Pass (the v3 selection).
- **Pie** — $19.5M Series A 2026-06-30, Main Street SMBs. Unclear: horizontal SMB growth tool, not one vertical; weakest intent in the v3 report.
- **Avoca** — Series B, $125M at $1B, 2026-04-27. Fail (stage), as the v3 report ruled.
- Query 2 returned nine Ashby job posts (Clera, Verso, two Pear portfolio companies, Jampack, Salesjack, Optimal AI, Prairie) — enterprise, industrial, CPG, or Paris; none a vertical SMB SaaS. Query 3 returned sales advice. Both reproduce the proof of concept's negative finding exactly.

### Arm W3, per company (Websets said yes to all three criteria for all 25)

| # | Company | Stage probe | Verdict | Note |
|---|---|---|---|---|
| 1 | Avoca | Series B 2026-04 | Fail | my criterion said "announced a Series A within 24 months"; its 2025 A satisfies that literally. Wording error, not a Websets error |
| 2 | Archy | Series B 2025-10 ($20M, TCV) | Fail | same wording gap |
| 3 | Patientdesk.ai | $1M pre-seed 2026-02, $2.8M seed 2026-04 | **Fail** | Websets reasoning claimed "latest funding activity was a Series A" — a fabricated verdict |
| 4 | Auto Hauler Exchange | $5M Series A 2025-02 | Pass | marketplace for car haulers; borderline "software" |
| 5 | Toothio | "$5M additional" 2024-10, unlabelled | Unclear | staffing marketplace, not software |
| 6 | Equal Parts | $23M Series A 2026-02 | Unclear | an insurance-agency roll-up that acquires agencies; not a pure SaaS seller |
| 7 | Lassie | Series A 2026-06 | Pass | |
| 8 | Paxton | $22M Series A 2025-01 | Pass | legal |
| 9 | Anchor | $20M Series A 2025-01 | Pass | accounting firms; Israeli-founded, NY listed as HQ |
| 10 | Field Materials AI | $10.5M Series A 2025-04 | Pass | construction contractors |
| 11 | FurtherAI | $25M Series A 2025-10 | Unclear | insurance MGAs, brokers and carriers; carriers are not SMBs |
| 12 | Wisdom | $21M Series A 2025-08 | Pass | dental RCM |
| 13 | Revv | $20M Series A 2024-11 | Pass | auto repair shops; near the window edge |
| 14 | Zuma | "Series A in early 2024" per a job post; Websets cites 2025-03 | Unclear → likely Fail on window | conflicting dates |
| 15 | SimplyAgree | $3M unattributed VC 2024-11 | **Fail** | Websets cited Tracxn's "Series A" label; press says unattributed |
| 16 | Toma | $17M Series A 2025-06 | Pass | car dealerships |
| 17 | OneCrew | $7.5M Series A 2025-08 | Pass | paving contractors |
| 18 | Lucio AI | $5M 2025-10, **Bengaluru-based** | **Fail** | Websets said US HQ; NY is an office |
| 19 | Rebar (withrebar.ai) | $14M Series A 2026-03 | Pass | HVAC, electrical, plumbing |
| 20 | FirmPilot | $22M Series A-1 2026-02 | Pass | law firms |
| 21 | PointOne | $16M Series A 2026-03 | Pass | law firms |
| 22 | VITL | $7.5M Series A 2026-03 | Pass | cash-pay clinics and pharmacies |
| 23 | Hona | $9.5M Series A **2024-06** | **Fail** | 27 months; Websets dated the same announcement 2026-07-07 |
| 24 | SingleFile | $9M Series A 2025-02 | Pass | legal and compliance filing |
| 25 | Rebar (rebar.is) | same press release as #19 | **Fail** | a different 4-person company credited with #19's round — entity conflation |

Strict precision on the three criteria: **14 / 25 = 56%**. Counting the four unclear as passes:
72%. Of the seven fails, two are my criterion's wording (Avoca, Archy) and five are Websets'
own errors: one fabricated stage, one wrong HQ, one wrong date, one mislabelled round, one entity
conflation.

### Arm W5

One company after 334 candidates: **Outmarket AI** (insurance brokerages; $17M Series A 2026-05;
SF; open SDR and AE roles; an SDR posting that says "build and execute outbound sequences … targeting
commercial insurance agencies that fit our ICP"). Every verdict checks out and the references are
real. The per-criterion success rates explain the starvation: US HQ 82%, vertical 16%, stage 6.6%,
**hiring 3.7%, intent 2.7%**. Websets stopped at its search limit with the count unfilled. The two
gates that need today's ATS board and a reading of job-description language are exactly the two
Websets cannot verify at scale.

## Cost, per qualified company

| Path | Spend | Qualified (strict) | Per qualified company |
|---|---|---|---|
| S, discovery only | $0.021 | 2 | $0.011 |
| S, with the hand verification the v3 agent did (v3 ledger: ~$0.035 per selected) | | | ~$0.035 |
| W3 at Pro ($0.00449/credit) + my stage probe | $1.12 + $0.175 | 14 | **$0.093** |
| W3 at Core ($0.006125/credit) + probe | $1.53 + $0.175 | 14 | $0.122 |
| W5 at Pro | $0.045 | 1 | $0.045 (but one company per ~8 min) |

Fixed cost sits on top: the API needs a paid plan (Core $49/mo for 8,000 credits ≈ 800 all-green
results; Pro $449/mo for 100,000). This run used 260 credits. The API exposes no credit counter; the
figures above use the documented 10 credits per all-green result.

## What this says

1. **Websets finds far more of the right companies than the search queries, and mostly different
   ones.** Fourteen strict passes against two. The v3 queries' real yield was one query and four
   companies; Websets' entity mode is the answer to the proof of concept's negative finding that
   prose ICP queries return content about the ICP rather than members of it.
2. **Websets' verdicts cannot be the qualifier.** Five of twenty-five verdicts were wrong in ways
   that matter for a cohort (a pre-seed called Series A, an Indian company called US, a 2024 round
   dated 2026, a duplicate entity). Our own stage probe caught every one for $0.007 a company. R4's
   design stands: Websets proposes, our probe grades, the human approves.
3. **Criteria must be written the way the ICP means them.** "Announced a Series A within 24 months"
   admitted two Series B companies. "Most recent round is a Series A or A-extension" is the
   criterion. Three verifiable criteria; hiring and intent left to the ATS read and the probe (W5
   proves that putting them in the webset starves it).
4. **Cost per qualified company is roughly 3× the search path once verification is counted, and the
   fixed plan fee decides the rest.** At the R4 exit gate (one 20-account cohort) Core's $49 covers
   it many times over; at production volumes the note's crossover arithmetic applies.
5. **Latency is minutes.** Fine for a fleet job with a waiting state; not a synchronous tool.

## Recommendation for R4

Use Websets as the **candidate source** behind R4's discovery interface, with three criteria and a
count above the cohort size (over-discover), then run our own qualifier probe (stage from the
announcement, hiring from the ATS board, geography from the site) and write pass/fail/unclear
verdicts with references into ARV2's candidate rows for the approval card. Keep `/search` for the
domain lock and for one-off lookups. Do not use Websets enrichments (AI Ark owns enrichment). Do not
revive the old M06A pipeline; this is a thin client next to `exa_client.py`. The plan tier
(Core vs Pro) is a procurement ruling, not a design one.
