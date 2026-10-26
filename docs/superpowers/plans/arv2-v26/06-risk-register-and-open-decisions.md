# 06 — Risk register and open decisions (ARV2 v26 program)

**Status:** 2026-10-07, written after the two adversarial reviews (`review-A-*.md`, `review-B-*.md`)
and the reconciliation round (`RECONCILIATION-RULINGS.md`). Each risk names the document and
section that carries its mitigation, so a reader can check that the mitigation exists rather than
take this table's word for it. P = probability, I = impact on the founder's three goals (cost,
time, depth).

## 1. Risks

| # | Risk | P | I | Mitigation in the set (where) | Residual |
|---|---|---|---|---|---|
| 1 | The follow-up floor cannot express a chain the corpus shows (six of the eighteen pairs needed an `entity` trigger kind) → depth below today on a new account | was high | depth | R9: `entity` trigger kind + candidate-field variables + extractor `entities[]` (03 §3.4, §4.1; 04 W3-22/23); the judge keeps a budgeted investigative loop (03 §3.6; 20/12 rounds, 30/15 operations); AT-3 over all 11 floor pairs and AT-9 chain recall ≥ 0.90 per account (05 §3); the new **offline expressibility check in W0/W1** (05 §3.1) proves every mined chain is reproducible by rule or by a budgeted judge operation before any model runs | A chain kind that no production run has yet shown. Caught by AT-9 on the pilot; the pre-decided response is to raise the operation budget, then add the trigger kind |
| 2 | The brief is emitted through the old save/validate/finish sequence and a contact spends its round budget emitting | was high (03↔04 contradiction) | cost, time | R3: one `submit_brief@1` tool with server-side review derivation and one batched emission round (03 §3.7; 04 W3-24) | None once 04 reflects R3 (verified by the review-A re-check) |
| 3 | The modeled cost ceiling ($9) is not the structural ceiling: output per round, extraction output, raw-view reads, fallback-model repricing and page re-offers had no setting | medium | cost (the determinism ask) | R16: four new settings — no raw-view reads for r27 judges, fallback chain off for research roles, extraction output cap per call, page attempt ceiling (03 §5.5, §10; 04 §9; 05 §4.5) — and 03 §5.5 now states both ceilings | The expected case ($3.48 Flash / $2.72 Luna; ≈ $4.3 at the corpus's follow-up rate) is verified to the cent by review B; 03 §5.5 states the modeled ceiling ($9.4 / $8.1) and the structural ceiling from settings alone (≈ $22.7–25.8 / $17.9–21.0), gated in 05 §4 |
| 4 | Code-driven acquisition drops fetches today's agent relied on (homepage, site pages, LinkedIn profile, own posts; ≈118 possible A-class findings in the corpus) | was high | depth | R10: four fetch templates added to A1/A2 (03 §3.3; 04 W3-22), ≈ $0.12 per account + 5 contacts | None beyond the pool fixtures' coverage |
| 5 | The committee-role vocabulary compiled from persona prose (A0.0) has no oracle for non-marketing verticals | medium | depth, determinism | `DEFAULT_ROLE_TITLES` fallback per persona (03 §3.2); frozen fixture + ICP front-matter `search_terms:` override (05 §3 row 13) | A new vertical's first account needs the override reviewed once |
| 6 | Tool-result clearing configured differently from the context arithmetic → compaction fires and the `compaction_events = 0` gate fails | was high | cost | R6: one clearing configuration (03 §5.3) copied into 04 W1-1/W3-24 and 05; AT-gate on compaction events (05 §4) | None once 04 reflects R6 |
| 7 | Caps cut seller-critical items (26 of 401 at the plan's first values) | certain at the old values | depth | R10: caps set to the all-accounts maxima from 01b §6 (Stack 8, Committee 10, Watch-outs 4; contact own-words 8, problem-now 5, proud-of 3, hooks 4) in 03 §2/§10 | A future account above these maxima; 05 §5.2 raises after RC-2 with the number |
| 8 | Extraction truncation on a dense batch yields zero candidates; a 429 storm leaves silent holes | medium | depth, determinism | halve-on-length chunking and a loud `extract_incomplete` outcome (03 §3.5; 04 W3-23); AT-1 candidate recall ≥ 0.95 with the stronger-extractor fallback pre-decided (05 §3) | — |
| 9 | Page re-offer loop with no ceiling | low–medium | cost, time | R16(d): `CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS` (03 §10; 04) | — |
| 10 | Two mints and inconsistent setting names cost Aryan an integration pass | was high | time | R2/R7: r26 (week 1) and r27 (pipeline) with one settings sheet (03 §10) from which 04 §9 and 05 are regenerated; the re-mint checklist (04 §8) | Two mints are deliberate: W1 must ship and be measured (RC-1) before W3 |
| 11 | Removing the worker-wide `_db_lock` trades serialisation for deadlocks / pool exhaustion | medium | time | W2 order 20 → 16 → 17 → 15 → 19: instrument first, size the pool and pgbouncer (P3), lock-order review, kill switch `CLUE_ARV2_JOB_MAX_DB_CONNECTIONS=0`, concurrency DB test (04 §4) | The gain from removing the lock is attributed, not yet measured; item 20 measures it first |
| 12 | Contacts started at nomination end in `needs_review` because the page writer needs the parent import | was certain | time | P1 deferred contact page as a research-kind continuation (04 §2.1; 03 §6; 03a §8 confirms soundness: idempotent enqueue, `reopen_terminal`, shared lease) with the `contact_pages_due` exclusion of current pages | — |
| 13 | A contact privacy-stop never reaches current (v4) contact jobs | certain today | compliance | P6 (04 §2; 05 §6 go/no-go line): fix the `profile_ref` v2/v3 filter in `stop_contact_jobs` / `claim_writer` — **blocking before any pilot, and a production defect independent of this program** | None after P6 |
| 14 | The person compliance floor is off for every recipe ≥ 6; private findings are stored unfiltered | certain today | compliance | R15: restored at import for r27 (03 §3.7); founder decision D11 | Until r27, the Miscellaneous dump is the leak path: r26 keeps it (D3 is the founder's; 04 W1-13(b)), and `CLUE_ARV2_V26_MISC_SECTION=off` closes it on r27 |
| 15 | Media research is dead weight (0 transcripts in 21 attempts) and the skills demand it | certain today | cost, time | W1-12 gates the operations off for r26+ and strikes the instructions; W4 lists the four conditions to switch it on (03 §7) | D1 |
| 16 | Production code version and the live fleet env are unverified; Langfuse carries no release tag | certain | measurement | 03 §8 release tag on traces; 05 §7 spans/metrics before RC-2; 01 §7 queries for the DB (D6) | Until D6, provider prices (the Exa deep report) are inferred (≈ $0 at the current tier) |
| 17 | Fleet capacity binds once runs are short (6 jobs per account at t=0 vs 12 slots) | medium | time | W2-20 raises `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` after the lock is gone (04 §4) | — |
| 18 | The extractor's raw request/response envelope is an unbound artifact → DSAR would miss it | was certain | compliance | `_drain` binds it — for calls labelled `extract-*`, one site for both callers — with a subject row and derivation rows (03 §3.5.6; 03a §7.3/§8b; 04 W3-23) | — |
| 19 | The pre-step cannot enqueue contact jobs itself (`ResearchUnitRuntime` has no queue) | — | correctness | A0 writes the job rows; the driver's 10 s sweep offers them (03 §3.2; 04 W3-21) | ≤ 10 s added to contact start |
| 20 | The `Candidate` model must be final at the r26 mint because `@2` is minted once | — | time | `Candidate` incl. `entities[]` and ledger `follows` specified in 03 §4.1 and frozen in W1-5 (04) | A later field means `@3` and a third profile set |

## 2. Decisions for the founder

| # | Decision | Default in the set | Why it is yours |
|---|---|---|---|
| D1 | Media: keep off (W1-12) until W4's four conditions hold, or fix now | **Off** | Spend on a path that cannot transcribe today |
| D3 | Stop the Miscellaneous dump for r26+ (reverses the 2026-09-29 ruling) | **Stop** | It reverses your ruling; it is the main leak path for private findings |
| D4 | Cheap model for extraction (B) and pages (E); Grok stays the judge | **Flash** (the 03 §10 C6 default; Luna is an env change if the one-time AT-1 comparison prefers it), replay-gated | $2.72–3.48 vs $6.5 all-Grok; quality gated by AT-1/AT-6 |
| D5 | Account pages at ~minute 5 with one refresh only if the committee section changed | **Yes** | Product behaviour |
| D6 | Read-only production database user for Aryan/analysis | **Yes** | Closes the deep-report price and live-fleet blind spots |
| D7 | Owner for the Head-of-ABM launch latency (W1-11) | assign | 4 minutes on every request |
| D8 | Exa deep-report tier pinned per request | **current tier (≈ $0)** | $0.50/report would add $3.00 per account |
| D9 | Person Exa request caps (per-result text, numResults) | **4k chars × 12** | The largest single cost line; a setting, not an experiment |
| D10 | Approve the discovered committee before contact research starts, or automatic | **Automatic** | Speed vs control |
| D11 | Person compliance floor restored at import for r27 | **Restore** | It changes what is stored about people |
| D12 | Two recipe mints (r26 week 1, r27 pipeline) rather than one | **Two** | Week 1's gains ship and are measured before W3; costs one extra re-mint |
| D13 | The "Context only" section placement for r26 pages — 04 W1-13's earlier (d) proposed dropping it | **withdrawn; the 2026-09-29 placement stands** (04 §0.9, W1-13(b)) | Recorded so the withdrawal is visible; nothing left to decide |

## 3. What is deterministic, what is measured once, what is estimated

- **Deterministic by construction (settings in 03 §10, gated in 05 §4):** provider-call counts and
  templates; follow-up floor (11 pairs) and ≤ 2 floor rounds; judge round/operation/context/output
  caps; no raw-view reads by r27 judges; fallback chain off; extraction output cap; page attempt
  ceiling; clearing configuration; section counts; AI Ark pacing; Exa request sizes; prices.
- **Measured once, with a pre-decided fallback (05 §3):** extractor candidate recall (AT-1 ≥ 0.95 →
  stronger extractor); chain recall (AT-9 ≥ 0.90 → raise operation budget, then add a trigger
  kind); nothing-lost lists (AT-6); quote rule (AT-7, 0 false accepts); the lock-wait number
  (W2-20) before the lock is removed.
- **Estimated until D6/D8/D9:** the Exa deep-report price; live fleet env values; the exact
  expected cost ($2.72–3.48 is verified arithmetic on the corpus's token volumes, not a run).
