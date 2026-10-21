# ARV2 v26 — Review B: determinism, numbers, depth

**Adversarial review of the complete set (01, 01b, 02, 03, 03a, 04, 05) on four axes the founder
named: deterministic cost, no trial and error, deep research on every contact, and respect for
the build Aryan already has.** Read-only on main `fa4bed77b`, 2026-10-07. No `review-A-*.md`
existed when this was written, so the cross-document consistency findings that bear on the four
axes are included here (Appendix A); nothing else from that remit is attempted.

Data used: the seven documents; `.artifacts/arv2-research-runs-20261007/` (`runs.csv`,
`model-calls.csv`, `fixtures/chains/*.json`, `fixtures/nothing_lost/*.json`);
`.artifacts/account-research-cost-20261006/v26-cost-model/` (the earlier bottom-up model);
and four read-only code checks named where used (fleet queue `reopen_terminal`, the display
handler's failure path, the gateway fallback chain, `settings.py` round caps).

Vocabulary follows 05: **r26** = the week-1 mint, **r27** = the v26 pipeline (03's "recipe 26").
Prices are the plan's §3 sheet. "Modeled" = a number that depends on an assumed token count per
round; "structural" = what the settings alone guarantee with no assumption about model behaviour.

---

## 0. Summary verdict

The set is close and unusually well evidenced, but **not ready to hand to Aryan as written**, for
three reasons that each sit on one of the founder's axes:

1. **Cost is bounded, but the $9.0 ceiling is modeled, not structural.** Every path a run can
   spend on is count-capped by a named setting except four (judge output tokens per round, the
   gateway's fallback-model chain, the launch turn, and a page re-offer loop with no attempt
   cap). The settings alone bound an account + 5 contacts at ≈ **$22–27** (Flash), not $9.0; the
   $9.0 holds only if the judge emits ≈ 400 tokens on non-brief rounds and submits once. 05 §4.2
   enforces the modeled ceiling *after the fact* (fail > 1.10×), which is a gate, not a
   construction. Recomputed independently: expected **$3.48** (Flash) / **$2.72** (Luna) agrees
   with 03 §5.5 to the cent; the earlier model's $4.06 differs only by its larger D9 and page
   assumptions. Expected with a judge that actually investigates (12 account / 8 contact rounds,
   the corpus's follow-up share): ≈ **$4.5**.
2. **Depth is guaranteed for what the templates and rules can express — and the rule grammar in
   03 §3.4 cannot express six of 01b's eighteen floor pairs** (person named in a result, quoted
   phrase, URL in a result, subject-site page, talk/event, prior employer). Those are "lead"
   triggers (an entity mentioned inside a candidate), and the closed trigger set has only
   `class + any_of`, `class + attribute` and `ledger`. On Mortenson — the account with the most
   strict-backed chains (21) — 11 of its 14 strictly follow-up-dependent A-class account findings
   hinge on one batch of three searches that no rule can issue and only the compile's
   search-term vocabulary or the judge would reproduce. The A1/A2 templates also drop four
   template operations today's runs had (homepage fetch, subject-site pages, LinkedIn profile
   fetch, own-post fetch: 38 + 38 + 25 + 17 possible A findings in 01b T7). AT-9 would catch all of
   this at RC-2 — in week 5 — and its pre-decided fallback ("add a rule row") cannot fix a grammar
   gap without a code change and a mint.
3. **03 and 04 disagree on six mechanisms that decide cost and rounds** (Appendix A): the brief
   emission (`submit_brief@1` in one round vs the eleven-round save/validate/finish sequence),
   the clearing configuration (keep 4 / clear acquire receipts vs keep 6 / never clear them —
   03's own arithmetic shows the latter breaks the 60k cap by round 9), the extractor default
   (blank-and-refuse vs Flash), chunk and batch sizes, extraction concurrency, and the person
   floor (03 enables it at import for r27; 04 §11 says the advisory exemption is untouched as a
   parked ruling). An implementer reading 04 builds a judge that spends 11 of its 20 rounds on
   emission.

Eight genuine trial-and-error points remain (§3); seven are closable by writing the decision now
(written below), one (the D9 text cap) is a single bounded offline comparison, not a loop.

The minimal edits are in §6. The three that matter most: (a) add an `entity` trigger kind and
candidate-field variables to 03 §3.4/§4.1 so the floor is a floor; (b) make 04 W3-24 adopt
`submit_brief@1` and 03 §5.3's clearing config, and state the structural ceiling beside the
modeled one in 03 §5.5; (c) add the four missing templates to 03 §3.3 and set the C2 caps to
01b §6's numbers before W3, not after RC-2.

---

## 1. Is the cost ceiling bounded by construction?

### 1.1 Recomputation of 03 §5.5

Formula (03 §5.5, 05 §4.2): `cost = p_n·[O + (R−1)·g + miss] + p_c·Σ_{r=2..R} min(O+(r−1)·g, cap) + p_o·[(R−1)·400 + B]`,
Grok 4.6 at $2.00 / $0.50 / $6.00 per M.

| Line | 03 §5.5 | Recomputed here | Earlier model (v26-cost-model, Flash/Flash) | Note |
|---|---|---|---|---|
| Account judge, expected (R=7, B=9k) | $0.32 | **$0.324** (miss=0); $0.344 with the ≈10k suffix re-bill 03 §5.3 describes; **$0.414** if the formula's own `miss = T_role` term is applied (R·g+O = 59.6k > 45k) | $0.23 (R=7, O=28k) | 03's expected row drops the miss term its formula says applies; the gap is $0.02–$0.09 |
| Account judge, maximum (R=20, B=15k) | $1.00 | **$0.96** (the cached Σ with min(·,cap) is 1,066k, not 1,140k) | $0.55 (R=10) | 03 is conservative on the cached term |
| Contact judge, expected (R=5, B=5k) | $0.19 | **$0.186** | $0.19 | agrees |
| Contact judge, maximum (R=12, B=12k) | $0.62 | **$0.556** | $0.35 (R=8) | as above |
| Extraction, expected Flash (acct + 5) | $0.14 + $0.50 | **$0.139 + 5 × $0.097** | $0.24 + $1.07 | the earlier model assumed 20 × 10k person texts (pre-D9) and one source per call |
| Pages, expected Flash (D3 off) | $0.13 + $0.31 | **$0.131 + $0.309** | $0.15 + $0.30 | agrees |
| Providers, expected | $0.66 + $0.18 | **$0.655 + $0.172** | $0.69 + $0.10 | 03 uses 17.6 credits (role searches at size 5 × 0.5); the earlier model used 10.7 |
| **Expected total (Flash / Luna)** | **$3.48 / $2.72** | **$3.48 / $2.72** | $4.06 / $2.81 | arithmetic verified |
| **Modeled ceiling (Flash / Luna)** | **$9.0 / $7.7** | **$8.9 / $7.6** | $13.09 / $8.77 (pre-pin) | verified; see §1.3 for what it assumes |

Expected-case sensitivity that the set does not state: the judge is told to "investigate every
lead it judges worth a hop". On today's runs follow-ups are 58 % of completed operations
(01b T1: 12–21 per account run, 3–14 per contact run). If the r27 judge issues ≈ 12 operations
on an account (R ≈ 12) and ≈ 6 per contact (R ≈ 8), the judge line becomes $0.54 + 5 × $0.30 =
$2.04 instead of $1.25 and the total ≈ **$4.3** (Flash). Still far under the ceiling; worth
stating so the first RC-2 number is not read as a regression.

### 1.2 Every path by which an r27 run can spend, and what caps it

| # | Path | Capped by (setting, default) | Bounded? | What is missing |
|---|---|---|---|---|
| 1 | Judge model rounds | `…ACCOUNT_MAX_MODEL_ROUNDS` 20 / `…PERSON…` 12 (`TurnBudgetMiddleware` + `Allowance`; a failed call still counts a round) | **structural** | — |
| 2 | Judge output tokens | profile `max_output_tokens` 15,000 / 12,000 **per call** | structural per call; the formula assumes 400/round on non-brief rounds (corpus median 321, mean 721, p90 1,944, max 6,252 — `model-calls.csv`, 1,956 calls) | the ceiling's output term is modeled: structural bound = rounds × max_output = 300k / 144k tokens → **$1.80 / $0.86 per subject** vs $0.14 / $0.10 in 03 |
| 3 | Brief resubmits | `CLUE_ARV2_V26_BRIEF_RESUBMITS` 2 → up to 3 emissions | structural (inside rounds) | the formula charges one B; three brief rounds add up to 2 × 15k / 2 × 12k output = **+$0.18 account, +$0.72 for five contacts** |
| 4 | Repair rounds / finalize repairs | 10 / 2 (existing; inside `max_rounds`) | structural | — |
| 5 | Judge context size | cap 60k / 56k via compaction (fires at 54k / 50.4k); clearing at 45k / 42k keep 4 | structural **only if** every kept tool result is ≈ 3k tokens; a `read_file` of a `/evidence/` view is ≤ 80k chars = 20k tokens (W1-4's `CLUE_ARV2_VIEW_MAX_CHARS`), and `keep=4` keeps four of them → 36k + 80k → compaction fires (one full-miss rewrite) and 05's `compaction_events = 0` line fails | **missing:** an r27 per-role view cap — `CLUE_ARV2_V26_JUDGE_VIEW_MAX_CHARS` (16,000) — so a kept read is ≤ 4k tokens and 36k + 4 × 4k + 8k ≤ 60k holds; or drop `evidence` from the r27 profiles' readable set (the contract is "candidates, not pages") |
| 6 | Prefix-cache misses | none; the formula allows one miss of `T_role` | modeled; corpus: 51 of 1,914 post-round-1 calls were full misses (2.7 %; 03a's 13/592 is the 10-06 day only) → expected 0.2–0.5 misses per subject; worst case every round misses: 20 × 60k × $2/M = **$2.40** account | accept as modeled; the gate's ×1.10 tolerance covers the expected rate |
| 7 | Gateway fallback models | `CLUE_AGENT_FALLBACK_MODELS=x-ai/grok-4.7,meta/muse-spark-1.3` (global, per call, each model once — `agent_model.py:1047`); `CLUE_AGENT_FIRST_TOKEN_TIMEOUT_S=120` | **not in the sheet**: a fallback call is a full-context miss at the fallback model's new-input price, which the price sheet does not carry; bounded only by rounds | **missing:** either pin research roles to no fallback (`CLUE_ARV2_V26_JUDGE_FALLBACK_MODELS=` blank, read by `quality_research_wiring` when building the model) or add grok-4.7 / muse-spark prices to the sheet and the gate's Q2 |
| 8 | Judge provider operations | `…ACCOUNT_MAX_OPERATIONS` 30 / `…PERSON…` 15, counted in `operations.begin`'s transaction; refusal value | structural | state whether a `pool_read` inside `acquire@2` counts (it should not spend extraction twice: serve the source operation's stored `candidates`, do not re-run B) |
| 9 | A1/A2 templates | fixed counts (8 + 1 + 1 + ≤10; 6 + 1 + ≤6 + 1) | structural | — |
| 10 | A3 follow-ups | `FOLLOWUP_ROUNDS_MAX` 2 × `…OPS_PER_ROUND_ACCOUNT` 8 / `…PERSON` 4 | structural | the alignment rule ("01b maxima + 1") will raise these; 01b's per-run maxima are 21 account / 14 contact follow-ups, so the aligned caps would be ≈ 11 / 8 per round — restate the ceiling after alignment |
| 11 | Gap round | `GAP_ROUNDS_MAX` 1 × `GAP_OPS_PER_CLASS` 2 × classes with minimums (3 / 3) | structural | — |
| 12 | Web-gap committee | ≤ `committee_cap` searches + ≤ 5 paced `lookup_person` | structural | — |
| 13 | Extraction calls | batching (4 sources / 24k chars; chunks 20k) over a count-capped source set; `EXTRACT_RETRIES` 1; wall 180 s | structural in **count** (≈ 60 account + 5 × ≈ 30 contact expected, ≈ 1.6× with every follow-up and the judge's ops, ≈ 2× with retries); output per call `EXTRACT_MAX_OUTPUT_TOKENS` 6,000 | modeled in tokens: structural output bound ≈ 100 calls × 6k = 600k (account) + 250 × 6k = 1.5M (contacts) → **$2.25 + $5.6 Flash** vs $1.0 in 03; realistic because dense sources (ATS boards, report chunks) do emit thousands of tokens |
| 14 | Extraction retries on 429 | `ProviderCaller` 4 attempts × 12·(n+1) s backoff (≤ 120 s) inside a 180 s wall | no spend on a 429; **depth** risk: a storm → `extract_skipped/timeout` → silent holes (§2.4) | — |
| 15 | Deep-report price (D8) | `CLUE_ARV2_V26_DEEP_SURFACE` pins the surface; the price of that surface is a *fit* (−$0.002 per report over 12 runs), not a sheet entry; one thin-response retry per subject → ≤ 12 deep calls | structural in count, **unverified in price**; at $0.50 per report: +$3.00 expected, +$6.00 with every retry | until D6 (read-only production ledger) prices it, the ceiling must carry +$3.00 as a line, not a footnote |
| 16 | AI Ark credits | 1 company (0.1) + 5 roles × size 5 × 0.5 + 5 exports × 1.0 = 17.6; + 2.5 web-gap | structural (retries do not bill) | — |
| 17 | Pool-read duplicates | measured, not capped (`duplicate_fetch` counter) | bounded by operation counts (≤ $0.004 each) | — |
| 18 | Pages | 11 (→10) + 5 × 6 (→5) sections × (1 + `PAGE_SECTION_REPAIRS` 1); refresh 2 sections | structural: **$0.26 + $0.62 Flash** (03's $0.88 ceiling is right) | — |
| 19 | **Page re-offer loop** | 03 §3.8 (c) / 04 P1 step 5: the 10 s sweep re-offers a page with no live block, `reopen_terminal=True`; the display handler returns `failed, requeue=False` and relies on the next offer (`fleet_handler.py:161`); the fleet queue counts `attempts` but no worker or selector reads it as a ceiling (`queue.py:567` comment only) | **unbounded**: a section that fails its correctness check every time is rewritten about once a minute (≈ $0.025 Flash, ≈ $0.20 Grok per attempt) for as long as the sweep runs | **missing:** `CLUE_ARV2_V26_PAGE_REOFFERS_MAX` (3) read by `contact_pages_due` / the sweep selection (`WHERE t.attempts < :max`), after which the job stays `needs_review/page_section_failed` and only `manual_refresh` re-offers |
| 20 | Account refresh (D5) | one continuation per account (`pending_continuations` r27 predicate), ≤ 2 sections | structural | — |
| 21 | Launch turn (Head of ABM) | `CLUE_HEAD_OF_ABM_MAX_MODEL_ROUNDS` 350; W1-11 targets ≤ 2 calls | **not bounded** by any v26 setting; $0.30 is an assumption (today $0.28–0.78 per launch) | out of scope by ruling; say so in 03 §5.5 and exclude it from the gated total |
| 22 | Lease takeover / re-drive | pre-step stages replay from stored bodies (free); B re-extracts only operations without an `extraction` block (≤ the in-flight batch, ≤ 6 calls); the judge resumes from the checkpoint with its round counter in graph state | structural | the one real exposure is 03's: two drivers inside the 60 s staleness window (≤ 60 s of duplicated model calls) |
| 23 | Re-drive after `needs_review/quality_unit_incomplete` | "a fresh turn on the same pool" = a fresh 20/12-round budget | operator-triggered (`needs_review` is not claimable); uncapped in count | record in 05 §6.3 that a re-driven judge turn is a second full budget and must be counted by the gate as a separate turn |
| 24 | Compile (A0.0) | once per context, cached; 1 retry | structural ($0.007) | the output (titles + search terms) has no oracle — §2.3 item 3 |

### 1.3 Modeled vs structural ceiling

| Component | 03 §5.5 modeled ceiling (Flash) | Structural (settings only), cache-friendly | Structural, every call a full miss |
|---|---|---|---|
| Account judge | $1.00 | $3.2 | $4.7 |
| Five contact judges | $3.10 | $8.1 | $12.2 |
| Extraction | $1.0 | $7.9 (output at 6k tokens × every call) | same |
| Pages | $0.88 | $0.88 | same |
| Providers (D8 at the fitted ≈ $0) | $2.73 | $2.73 (+$3.0–6.0 if deep is $0.50) | same |
| Launch | $0.30 (assumed) | unbounded by v26 settings | — |
| **Total** | **$9.0** | **≈ $23** | **≈ $29** |

What this means for the founder's "deterministic" ask: the run **cannot** run away the way v25
does (350 rounds × 200k context; today $25 per account with no bound), and nothing in the
structural column is reachable without the judge emitting its maximum output on every round or
every call missing the cache — but the $9.0 is the number a *well-behaved* judge produces, and
05 §4.2 turns it into a gate (`realised > ceiling(R) × 1.10` fails) rather than a construction.
That is the honest framing and should be written into 03 §5.5 verbatim: *"$9.0 is the modeled
ceiling the gate enforces; the settings alone bound the run at ≈ $23; the three terms that
separate them are output tokens per round, resubmits and cache misses, each measured by Q2."*

Two cheap moves narrow the structural column without touching the founder's "money caps only
record" ruling (02 §10 item 3): (i) the per-role view cap of row 5 (keeps the context cap
structural); (ii) an extraction **call** count per subject, `CLUE_ARV2_V26_EXTRACT_MAX_CALLS_ACCOUNT`
(160) / `…_PERSON` (80), refusing further calls with `extract_skipped/budget` — a count cap, not
a money cap, and far above the expected 60 / 30. Lowering the judges' `max_output_tokens` is
not available (the brief needs 9–15k).

### 1.4 Verdict on §1

Bounded: yes, finitely, for the first time. By construction at $9.0: no — at ≈ $23. Four
settings must exist that do not (rows 5, 7, 13, 19) and two lines must be stated (rows 15, 21).

---

## 2. Is depth guaranteed, not hoped?

### 2.1 The walk: Mortenson (account + 5 contacts) through A0–A3 + the judge

Mortenson has the most strict-backed chains in the corpus (21 of 45) and the highest strict
share on an account run (14 of 27 A-class; 01b T3). Per `fixtures/chains/mortenson.com.json`
and `fixtures/nothing_lost/mortenson.com.json` (counts and trigger kinds only):

**Account (27 A: 14 strict, 12 possible, 1 template-only).** The 14 strict findings are
produced by five chains:

| Chain (trigger kind → op) | What the lead was | A findings (strict) | v26 mechanism that would issue it | Depends on |
|---|---|---|---|---|
| person-name → search_web ×2, other-specific → search_web | one round-9 batch: the incumbent TPA/carriers, "Form 5500", a named benefits executive | **11** (stack ×4, committee ×2, trigger, motion_proof, watch_outs, initiative) | `T_stack` fires only if the A0.0 compile's `category_tools` carries the vertical's vendor vocabulary (TPA, PBM, stop-loss, carrier); "Form 5500" only if `icp_terms`/`problem_terms` carry it; the named executive only via a rule on a `committee`/`trigger` candidate that can reference the person's name — **no such variable exists in §3.4's grammar** | the compile (a cached Flash output with no oracle) or the judge |
| press-release-url → fetch_page | the subject's own `/news-insights` page surfaced by a search | 2 (stack, committee) | no A1 template fetches subject-site pages; a rule needs a `source.url`/host attribute the closed trigger set lacks | the judge |
| url-in-result → fetch_page | a third-party filing aggregator page | 1 (trigger) | same | the judge |

So for Mortenson's account brief, the deterministic layer (templates + rules as specified)
reproduces the 1 template-only finding and plausibly the 12 batch-ambiguous ones (their batches
contain template operations), i.e. ≈ 13 of 27; **the other 14 (52 %) depend on the compile's
vocabulary or the judge's judgement.**

**Contacts (34 A: 14 template, 6 strict, 14 possible):**

| Contact | A | Chains behind the strict/possible ones | v26 |
|---|---|---|---|
| Patrick Locken | 7 | all template-only | reproduced by A2 |
| Robin Ritter | 7 (3 strict) | person-name ×2 (prior employers), event-talk ×2, prior-employer-affiliation, subject-site `/team` fetch → remit ×2; own-post fetches → own_words/proud_of | remit is template-coverable in v26 (the AI Ark record + `P_employer_mentions` on `{domain}` surface the team page as a 1,500-char result); the own-post fetches have no template (01b's missing template (d)); the prior-employer searches are "dropped by construction" at extraction, so the hooks that came through them fall to the judge |
| John Bachhuber | 11 (2 strict) | person-name (a named benefits consultant) → remit, own_words, and another contact's hook; quoted-phrase "Form 5500" | judge-only (entity trigger) |
| Jean McGrory | 5 (1 strict) | prior-employer ×3, education, event-talk, quoted-phrase, url → problem_now ×4 | the strict problem_now finding came from a prior-employer search — exactly the lead class v26 drops at extraction; judge-only |
| Athena Burkholder | 4 (0 strict) | batch-ambiguous | A2 plausible |

Depth-2 chains (Flynn, Dialpad): vendor-stack "Talkdesk" (depth 1, 5 strict A: own_words ×4,
problem_now) → two depth-2 searches (hooks ×3). Talkdesk is Flynn's *prior employer*: a
contact `career_arc` candidate. There is no contact `stack` class and `any_of` cannot enumerate
employer names, so no rule fires; the chain needs the judge to spend 3 of its 15 operations on
it across two rounds. The A3 executor does allow round 2 to chase round-1 candidates, so the
*mechanism* for depth 2 exists; the *trigger* does not.

### 2.2 Where depth depends on judgement rather than a rule or a budget

1. **The rule grammar.** 03 §3.4 admits triggers `class + any_of` (token match on the
   candidate's `finding`), `class + attribute (source.kind | attribution.kind | evidence.value_kind)`,
   and `ledger`. 01b's floor rows 1, 3, 4, 5, 6, 7 (person named, exact phrase, URL in a result,
   subject-site page, talk/event, prior employer/board) are all *entity* triggers — the thing to
   search is a name, phrase or URL found inside the candidate — and three of 03's own seed rows
   ("stack vendor named ⇒ vendor's customer page", "own post names an initiative ⇒ search the
   initiative", "talk found ⇒ fetch the event page") silently assume a variable (`{vendor}`,
   `{initiative}`, the event URL) that §3.4's template language (`{name}`, `{seat}`, subject and
   compile variables only) does not define. As written, the rules file can express 12 of 18
   floor pairs at most, and AT-3(c) — "every floor pair has a rule" — would be satisfied by rows
   that can never fire.
2. **The compile.** Every A1 template's vocabulary (`category_tools`, `problem_terms`,
   `icp_terms`, `seats`) is one Flash call per context, validated only for role titles against the
   AI Ark vocabularies. For a benefits seller the difference between a plan that finds the
   TPA/PBM/Form-5500 picture and one that does not is whether that call emitted those terms.
   No fixture, test or review covers it; it is cached, so a poor compile is *deterministically*
   poor for every account of the project.
3. **The judge's operation choices.** Budgeted (30 / 15) but not directed: the prompt says
   "investigate every lead worth a hop". AT-9's 0.90 per-account threshold on a live-judge test
   will be flaky for judge-only chains; it is deterministic only for rule/template-reproduced
   ones.
4. **Dated templates.** `P_news`, `P_team_postings`, `T_leadership`, `T_hiring`, `T_news_funding`,
   `T_pain`, `T_succession` carry `startPublishedDate = today − 270 d`. A `proud_of`/award item
   older than nine months (several in the corpus) is reachable only by the judge or the undated
   `P_bylines`/`P_talks`.

### 2.3 Does anything reduce per-contact depth relative to today?

| Change | Effect, quantified against 01b | Verdict |
|---|---|---|
| Contact caps at the plan's values (own_words 6, problem_now 3, proud_of 2, hook 3) | 01b T9: own_words cuts 2 contacts (6 A items), problem_now cuts 4 (8 items), proud_of 1 (1), hooks 1 (1) → **16 of 242 contact A items (6.6 %) imported but never served**; at 01b §6's recommendation (8 / 5 / 3 / 4) zero are cut. Account side: stack 4 cuts 7, committee 8 cuts 2, watch_out 3 cuts 1 → 10 of 159 (6.3 %) | a known loss with a known fix; 05 §5.2's reactive `caps_to_raise` defers it to after RC-2 for no reason |
| D9: person deep 20 × 10k → 12 × 4k chars | per-result page text −76 % (200k → 48k chars); the 52–60k report is unchanged. 01b cannot measure the effect (deep spans are judged only at the 8k head) | **only AT-1 at the freeze can**; route C freezes both the production request (10k × 20) and the v26 plan (4k × 12), so AT-1 can be run on both pools in one sitting — a single comparison, not a loop (§3) |
| The templates drop today's homepage / subject-site / LinkedIn-profile / own-post fetches | 01b T7: homepage 38 A (5 accounts), FU subject-site 38 (4), subject-linkedin 25 (5), FU own-post 17 (4), FU person-name → profile fetch 14 strict A in 2 of 3 accounts | **a real reduction**; cost of restoring: ≈ 4 account fetches + ≈ 5 per contact ≈ $0.12 per account + 5 |
| Extraction batching (4 sources / 24k chars) | unmeasured; AT-1's fallback is 4 → 2 | acceptable as a bounded experiment |
| `EXTRACT_MAX_OUTPUT_TOKENS` 6,000 with "no cap on candidates" | a call that truncates at 6k tokens is invalid JSON → one retry of the *same* request → `extract_failed` → **zero** candidates from that batch, not 55. ATS boards and report chunks are exactly the dense sources | a silent cliff; the fix is deterministic (split the batch/chunk in half on `finish_reason=length` and re-run) |
| 429 storm during B | `extract_skipped/timeout` after 180 s; the judge is told in the ledger and "may request them" | two runs of the same pool can differ; depth loss is silent unless the judge re-requests |
| The contact judge sees only the account's **first** pool, class-filtered to trigger/initiative/pain/stack (≤ 60) | no `committee` or `motion_proof` items reach the contact judge | fine for the contact brief; note that "angles" sections are written from the account slice (04 W3-25), so this bounds what a contact page can tie to |
| The account judge sees 20 candidates per contact | ≈ 1/6 of a contact's pool; ordered by class then confidence | adequate for the org-sequence finding; AT-8 covers it |
| Clearing keep=4 | a cleared receipt's candidates stay citable by id | no depth effect |
| No `research_deep` for the judge | the pre-step's two deep calls per subject are the only ones | fine (each has one thin retry) |

Net: at the plan's caps and templates, **v26 serves ≈ 6.5 % fewer A-class items than today by
cap alone and loses the template-coverable share of four fetch kinds (≈ 118 possible A findings
across the corpus, overlapping)**; with 01b's caps and the four templates restored, v26's
deterministic layer matches today's template layer and the only open question is the
judge-only 16 % (strict) to ≈ 40 % (possible) of follow-up value.

### 2.4 Is AT-9 (05 §3) sufficient to catch a shortfall before the pilot?

- **Timing:** yes. RC-2 runs twice before the pilot flip (05 §6.1), AT-9 is part of it.
- **Expressiveness of the fallback:** no. AT-9's pre-decided remedy is "a kind with ≥ 2 misses on
  ≥ 2 accounts gets a rule row (data)"; for entity-kind triggers there is no row that can be
  written. The remedy is an executor change (a new trigger kind, candidate-field variables) plus
  an extractor-prompt change (emit the entities) — code, a resource re-pin and therefore a mint,
  landing in week 5–6. Fix the grammar now (W3-22 design) and AT-3 becomes a real guard.
- **Its own determinism:** the offline mode answers follow-up searches from a BM25 index over the
  pooled sources; a judge query that production never issued is answerable only if its target is
  already in the universe. 05 §2.2 already says every RC run records, so the AT-9 that gates the
  pilot should be computed on the RC-2 run's **recorded** universe (live providers), with the
  offline number reported beside it; write that sentence into 05 §3 AT-9.
- **The assertion "every floor pair reproduced by a rule or template on ≥ 1 account (never
  judge-only)"** is the right one and, with the grammar fixed, is deterministic. Split AT-9 into
  that line (must be 1.0) and the judge-only chain recall (report ≥ 0.75, warn, do not gate) so
  live-judge variance cannot make the gate flaky.

---

## 3. Where this still requires trial and error

| # | Point | Default pre-decided? | Fallback pre-decided? | Measurable trigger to switch? | Verdict / the missing decision, written |
|---|---|---|---|---|---|
| 1 | D4 extractor model | **contradiction**: 03 §3.5.2 ships blank and refuses to compose; 04 W3-23 ships `google/gemini-3.8-flash` | Luna "is an env change" | none | **Decision:** ship Flash. At the freeze, run AT-1 once on Luna against the same pools (≈ $0.2); switch to Luna iff its recall ≥ Flash − 0.01 on every pool. One offline comparison; never re-tuned in production |
| 2 | D4 page model | Flash (04 W3-25) | Grok (env) | none | **Decision:** Flash; switch pages to Grok only if the founder's two readings at 05 §6.2 item 3 both fail on prose quality while the depth gate passes (quality, not cost, decides) |
| 3 | D9 person deep caps (12 × 4k; extract result texts) | yes | 4k → 6k (AT-1) | AT-1 < 0.95 with spans absent from every candidate | **bounded experiment, not a loop:** freeze both request shapes (production 20 × 10k and v26 12 × 4k) in the same freeze; run AT-1 on both; pin the smallest cap that holds ≥ 0.95. Done once |
| 4 | D8 deep surface / price | surface pinned | none if the pinned surface is not ≈ $0 | the first live ledger `cost_usd` on `exa` deep rows (Q1) | **Decision:** no behavioural switch exists or is wanted (every contact gets its deep call by ruling); the ceiling carries +$3.00 as a line until D6 prices it; a measured price > $0.10 per report raises the gate's ceiling, nothing else |
| 5 | Clearing trigger / keep | **contradiction**: 03 §5.3 45k/42k keep 4, acquire receipts cleared; 04 W3-24 trigger = cap − 10k, keep 6, acquire excluded | none | 05's `compaction_events = 0` | **Decision:** 03's values are the ones whose arithmetic closes; 04 W3-24 step 4 adopts them. Switch trigger: `compaction_events > 0` on any RC-2 subject → lower keep to 3 before touching the cap |
| 6 | Extraction batch / chunk | **contradiction**: 03 4 × 24k, chunks 20k; 04 4 × 6k, chunks 12k | 4 → 2 (AT-1) | AT-1 `quote_partial` dominant | **Decision:** 03's sizes (fewer calls, fewer boundary splits); truncation handled by halving, not retrying (§2.3) |
| 7 | Judge round / operation expectations (7 / 5; 30 / 15) | yes | raise budgets | `budget_use_ratio = 1.0` on > 20 % of jobs | decided; also state the ≈ $4.3 expected at realistic investigation (§1.1) |
| 8 | Class minimums | yes | lower the `…_MIN_*` | gap fires on > 2 of 7 accounts | decided |
| 9 | Pool waits (240 / 120 s) | yes | 240 → 360 | `wait_pools.absent > 0` | decided |
| 10 | Rater calibration | thresholds | hand rating by two people | κ < 0.60 etc. | decided |
| 11 | Replay transport semantic fallback | yes (BM25) | none | none | **Decision:** the pilot-gating AT-9 is computed on the RC-2 *recorded* universe; the offline number is diagnostic (§2.4) |
| 12 | `_db_lock` removal (W2-15) | measure first, flag rollback | `CLUE_ARV2_JOB_MAX_DB_CONNECTIONS=0` | W2-20 p95; pool timeouts | decided |
| 13 | The A0.0 compile's search terms | model output, cached | `DEFAULT_ROLE_TITLES` for titles only | none for search terms | **Decision (new):** the compile artifact for each pilot context is frozen as a fixture and read once by the founder (≈ 50 terms); the ICP document's front matter may carry `search_terms:` overrides (the same additive key 04 W3-21 allows for persona titles), and when present the compile copies them verbatim. Vocabulary becomes ICP-authored data; the model fills gaps only |
| 14 | Subject anchor rule | yes | tighten to 2 title tokens | AT-5 leak | decided |
| 15 | Caps (C2) | plan values | raise per 05 §5.2 after RC-2 | A-rated over-cap items on ≥ 2 accounts | **Decision:** adopt 01b §6 now (Stack 8, Committee 10, Watch-outs 4; own_words 8, problem_now 5, proud_of 3, hook 4) — the data already exists; no run is needed |
| 16 | Extraction under a 429 storm / wall-clock | skip and record | the judge "may request" | none | **Decision:** after the wall, re-run the skipped set once with the per-process semaphore halved; still skipped → the subject lands `needs_review/extract_incomplete` (loud), never a silently thinner pool |
| 17 | `MAX_PARALLEL_JOBS` 4 → 6 | yes | revert | W2-20 wait ≈ 0 | decided |
| 18 | Person-floor predicate | **contradiction** (03 §2.5 vs 04 §11) | — | — | a ruling, not an experiment: 03's version is the one that matches 02 §10 item 3 ("the floor runs by default and redacts, never drops"); ask the founder to rule it explicitly |

**Count:** of 18 points, 10 are already pre-decided with default, fallback and trigger. **Eight
remain** (1, 2, 4, 5, 6, 11, 13, 16); seven are decided above by writing, and one (3, D9) is a
single bounded offline comparison. Nothing in the set requires iterating in production.

---

## 4. Respecting the existing build

### 4.1 Every change to the runtime, journal, replay, claims import, DSAR and display paths

| Area | Change | Where | Justification in the set | Flag |
|---|---|---|---|---|
| Governed runtime (middleware) | `ContextEditingMiddleware` appended to the research bindings tuple; per-role window wrapper on `compaction_for` | W1-1; 03 §5.3 | request-only edit; checkpoints keep originals; 03a §4.2 proves `ToolRepairRounds` unaffected | none; keep 03's values (§3 row 5) |
| Governed runtime (context assembly, **shared with Head of ABM**) | L1 no longer appended as the first message (`agent_l1_as_message=false`) | W1-6 | ≈ 11 % of model spend today (01 T2.4) | changes production chat's request bytes; the stated tests (`test_context`, continuation byte-identity) suffice but the HoA replay should be listed in RC-1's acceptance explicitly |
| Research unit order (`ResearchUnitRuntime.run`) | `bind_execution`/`resolve_authority` hoisted before the pre-step; the pre-step runs before the task artifact; committed-outcome check after | W3-21; 03a §8a | the pool must be final before L7 (03a §5.4 item 5) | justified; a crash in the pre-step leaves an execution row with no turn — recoverable through markers; state it in 03 §6.3 |
| Journal / replay | the pre-step bypasses the C5 journal and A9 key; mitigated by operation rows, content-addressed pool artifacts, markers, derivation rows | 03 §3.3.6, §3.5.5; 03a §7.3 | the 3.3 s + 0.7–1.8 s envelope per governed call on ≈ 100 operations | justified; AT-3/`test_prestep_db` prove re-drive idempotency |
| New tools | `acquire_research_evidence@2`, `search_evidence@3`, `submit_brief@1` (03) / `save_dossier_section@2`, `update_dossier_findings@2` (04) | 03 §3.6–3.7; 04 W1-2/3/5 | shape changes are versions, pinned by new profiles | **03 vs 04 disagree on which emission tools the r27 judge uses** (Appendix A.1); 03 wins on cost |
| `discover_people` gate | the "attempted `account_deep` first" precondition relaxed for r26 | W1-9 | nominate-first is impossible under it | justified; recorded as a behavioural gate (04 §0.7) |
| Generation substrate | `ready_person_jobs` TRUE branch for r26; `pending_continuations` "every child terminal" predicate for r27 | W1-8, W1-10; 03 §6.1 | release at nomination; one continuation | justified |
| Claims import | `EntryV2`/`ReviewV2` lenient shapes; `claim_kind` mapping for `synthesis`/`not_found`; `value_json` extras (class, rank, candidate_ids, …); `review` derived server-side | W1-2; 03 §2.2, §3.7 | master plan already admits sub-fields; `finish_dossier` body unchanged | justified |
| **Person floor at import** | predicate `(not advisory) or recipe >= 27` | **03 §2.5 only**; 04 §11 says untouched | 03: the floor never ran on any recipe ≥ 6 | **lacks a ruling**; 02 §10 item 21 parks it; 03 and 04 contradict — the founder must rule (recommend 03's) |
| **DSAR filter bug** | `stop_contact_jobs` / `claim_writer` filter `profile_ref IN (…v2, …v3)` while jobs carry `…:v4` → a contact's privacy-stop never sets `privacy_stopped` on v4 jobs | **03 §3.2 "required fix"; absent from 04** | 03 §3.9 depends on it | a production privacy defect today, independent of v26; add to 04 as `P6` (A, S, gate *all*) in week 1 |
| DSAR bindings | the account turn's `AgentTurnRequest` lists every committee contact as a subject; pool artifacts subject-bound with derivation rows from every source | 03 §3.9 | late responses stay unreadable (02 §10 item 17) | justified; note the consequence (a contact erasure makes the account turn un-replayable) is accepted by ruling |
| Evidence substrate | W2-19 lazy indexing: `artifact_key`/`artifact_sha256` nullable + CHECK; materialise on first read | 04 W2-19 | artifacts per account −85 % | **not needed for v26's targets** (03 §5.6 assumes W2-20/16/17/15 only); a migration whose downgrade refuses while lazy rows exist; move after RC-2 |
| Display contract | section positions (boot upsert); Miscellaneous off and `context-only` dropped from insights for r26+ (reverses 2026-09-29 for r26 pages); per-section publish; `brief-v26` writer branch (03) or research-kind continuation (04) | W1-13; 03 §3.8; 04 P1 | D3 is the founder's; the `context-only` half is flagged for a ruling in 04 W1-13(d) | the `context-only` reversal is correctly flagged; per-section publish means a page is visibly partial for ≈ 50 s — confirm the frontend's quality-page read tolerates missing sections or publish the page's sections in one transaction (04 W3-25's wording is ambiguous) |
| Fleet | P1's contact page as a research-kind continuation (04) vs a display-kind task (03) | 04 §0.5 | 04 cites a concrete fact (the display handler writes Luna blocks the frontend never serves for a quality subject) | either; both need the re-offer attempt cap (§1.2 row 19) |
| Launch | `recipe_version_for(workspace)` selects the pinned profile sha | P5 | per-workspace rollout | justified; a relaunch after rollback is a new run (03 §3.1) — fine |
| Worker | `_db_lock` removed from tool transactions (W2-15), hop split (W1-7), index once per batch (W2-16), no recovery on success (W2-17) | 04 §4 | 03a §1.4's measured 28 s drain, 11 s semaphore wait | justified and sequenced (measure first); the lock-order review is the right gate |

Nothing in the set edits the middleware order, the 10 repair rounds, `finalize_turn`'s
separate-call rule, `validate_plan`, `invoker.py`, `runner.py`, the A9 key, `recover()`, the
receipt shapes, `arv2_research_operation`'s job-keyed identity, the provider ledger, the fleet
kinds, or the frontend's Zod schemas — 04 §11's list is accurate for 04; 03 adds the two DSAR
items above.

### 4.2 Sequencing: is W0 → W1 → W2 → W3 the lowest-risk order?

- **RC-1 on r26 is not wasted as a shakedown**: it exercises the harness seams (transport
  factory, pool, cassette), W2-20's measurement, the bleed-stop flags (W1-1/4/6/7/10/12/13) and
  pays for itself in the ≈ 3–4 weeks of production before r27 (≈ $25 → ≈ $15 per account).
- **The r26 *mint* is largely throwaway**: W1-9 (nominate-first prompt), W1-14's skill halves,
  W1-2's `@2` save/update tools (if 03's `submit_brief` is adopted), W1-3's `search_evidence@3`
  and W1-5's `items` half are replaced by r27's prompts, skills and `submit_brief`. That is ≈ one
  week of `L` effort, one profile/recipe/launch-map mint, the five hard-coded tests edited twice,
  and the r26/r27 numbering that 05 already had to translate.
- **Recommendation:** one mint, not two. Ship W1 as flag-gated items on v25 (W1-1, 4, 6, 7, 10,
  12 (the tool gate), 13(a)(c), P1, P3, P5, W1-11's HoA mint which is its own registry); keep
  W1-14's Exa v2 charters and D9 settings as the *only* r26 resource change if a bleed-stop on
  the person deep request is wanted before week 5 (it is the largest single provider line), gated
  by a flag rather than a recipe; re-key W1-8/W1-13(b)(d) gates to flags for the interim. Then
  the single r27 mint carries everything else. This removes a mint, a week of prompt work that
  r27 discards, and the "two recipe integers" decision (04 §0.2) entirely.
- **Within W3**: W3-26 (role + migration) first is right; W3-23 and W3-22 are leaf and start in
  week 2 — but W3-22's design (the rule grammar) must be settled *before* W0's rules file is
  cut, or W0 produces rows the executor cannot fire (§2.2 item 1).
- **W2-19** off the critical path (above). **W2-15** stays where it is.
- **Add before W3-21**: the DSAR v4 filter fix (P6) and the page re-offer cap, both small.

---

## 5. Top-10 risks (probability × impact on cost / time / depth)

| # | Risk | P | Impact | Mitigation in the set | Mitigation it lacks |
|---|---|---|---|---|---|
| 1 | The A3 rule grammar cannot express six of eighteen floor pairs; follow-up depth beyond the templates falls to the judge; AT-9's fallback cannot add the rows | high | depth, high | AT-9 at RC-2; judge budget 30/15 | an `entity` trigger kind + candidate-field variables + extractor `entities[]` (03 §3.4, §4.1; W3-22/23) — before W0's rules file is cut |
| 2 | 04 W3-24 emits the brief through the eleven-round save/validate/finish sequence 03 replaced | high (two documents) | cost + time, high (11 of 20 rounds) | 03 §3.7 `submit_brief@1`; 05 AT-4 assumes it | one line in 04 W3-24 adopting 03 |
| 3 | The $9.0 ceiling is modeled; output tokens per round, resubmits, fallback-model misses and 80k-char reads are not structurally capped | medium | cost, high (the founder's determinism ask) | 05 §4.2's ×1.10 gate; round/op/context caps | state both ceilings; view cap; fallback pin; extraction call cap (§1.3) |
| 4 | A1/A2 drop the homepage, subject-site, LinkedIn-profile and own-post fetches today's runs relied on | high | depth, medium-high (≈ 118 possible A in 01b T7) | the judge may fetch them | four templates (`T_homepage`, `T_site_pages` ≤ 4, `P_profile`, `P_post_pages` ≤ 4), ≈ $0.12 per account + 5 |
| 5 | The A0.0 compile's search vocabulary has no oracle and is cached per context | medium | depth + determinism, high for non-marketing verticals (Garner/Samsara) | `DEFAULT_ROLE_TITLES` for titles | frozen fixture + ICP front-matter `search_terms:` override (§3 row 13) |
| 6 | 04's clearing config (keep 6, acquire excluded, trigger cap − 10k) breaks 03's cap arithmetic; compaction fires; the `compaction_events = 0` gate fails | high if 04 is built as written | cost, medium | 03 §5.3's arithmetic | 04 W3-24 adopts 03 §5.3 |
| 7 | Caps at the plan's values cut 6.5 % of A-class served items (26 of 401 in the corpus) | certain | depth, low-medium | 05 §5.2 raises after RC-2 | set 01b §6's values now |
| 8 | Extraction truncation at 6k output tokens yields zero candidates from a dense batch; a 429 storm leaves silent holes | medium | depth, medium; determinism | one retry; AT-1 fallback | halve-on-length; loud `extract_incomplete` |
| 9 | Page re-offer loop with no attempt ceiling | low-medium | cost, medium (unbounded, slow) | none | `CLUE_ARV2_V26_PAGE_REOFFERS_MAX` |
| 10 | Two mints, two recipe integers, three setting-name schemes (03 `CLUE_ARV2_V26_*`, 04 `CLUE_ARV2_JUDGE_*`/`CLUE_ARV2_EXTRACT_*`, 05 mixing both) | high | time, medium (Aryan's integration pass; duplicate test edits) | 05's translation note | one mint; one name scheme (03's) with 04 §9 regenerated |

Also carried, below the top ten: the unpriced deep surface (+$3.0–6.0 if it is not ≈ $0); the
person-floor contradiction (a ruling); the DSAR v4 filter bug missing from 04; W2-19's migration
on the critical path; AI Ark paid-tier pacing unverified (time only: 63 s per account serial).

---

## 6. Verdict and the minimal edits

**Not ready to implement as written.** Ready after the edits below, which touch wording and
settings, not architecture; none re-opens a founder ruling except the person floor, which needs
one.

| # | Document · section | Change |
|---|---|---|
| 1 | 03 §3.4 (and §4.1, §3.5.2) | Add a fourth trigger kind `entity`: the extractor emits per candidate `entities: [{kind: person\|org\|vendor\|programme\|event\|url, text}]`; rules may trigger on `class + entity.kind` and templates may reference `{entity.text}`, `{candidate.source.url}`, `{candidate.typed_value}`; `max_per_round` applies per rule. Re-express the seed rows with these variables. AT-3(c) then checks that every floor pair's rule *fires* on a synthetic candidate, not merely exists |
| 2 | 04 W3-24 step 5 | Replace the `save_dossier_section@2 → validate_dossier → finish_dossier → finalize_turn` sequence with `submit_brief@1` (03 §3.7); drop the `@2` save/update tools from the r27 profiles; the brief skills describe the §2.3 record |
| 3 | 04 W3-24 step 4 | Clearing for r27 = 03 §5.3: trigger 45k / 42k, keep 4, `acquire_research_evidence` **cleared**, exclude only `submit_brief`/`finalize_turn`; context caps 60k / 56k. Delete "trigger = cap − 10,000; keep 6" |
| 4 | 03 §5.5 | Add the structural ceiling beside the modeled one (§1.3 table) and the sentence quoted in §1.3; add the +$3.00 D8 line as a line; exclude the launch turn from the gated total; note the ≈ $4.3 expected at realistic investigation |
| 5 | 03 §10 C7 / 04 §9 | New settings: `CLUE_ARV2_V26_JUDGE_VIEW_MAX_CHARS=16000` (r27 view cap per role, read by `render_view` when the reader is an r27 judge); `CLUE_ARV2_V26_JUDGE_FALLBACK_MODELS=` (blank; the research model is built without the global chain); `CLUE_ARV2_V26_EXTRACT_MAX_CALLS_ACCOUNT=160` / `…_PERSON=80`; `CLUE_ARV2_V26_PAGE_REOFFERS_MAX=3` |
| 6 | 03 §3.3.2 / §3.3.3 | Add `T_homepage` (`fetch_page https://{domain}`), `T_site_pages` (≤ 4 fetches: `/careers`, `/news\|/blog\|/press`, `/about\|/team`, `/benefits` when present in the homepage's links, 404 tolerated), `P_profile` (`fetch_page {linkedin_url}`, `max_chars` 8000), `P_post_pages` (≤ 4 `fetch_page` of `linkedin.com/posts/` URLs returned by `P_linkedin_posts`). Update the budgets (+4 account, +5 contact fetches ≈ $0.12) |
| 7 | 03 §10 C2 | Caps: Stack 8, Committee 10, Watch-outs 4; own_words 8, problem_now 5, proud_of 3, hook 4 (01b §6); 05 §5.2 keeps `caps_to_raise` as the guard |
| 8 | 03 §3.2 A0.0 | The compile honours an ICP front-matter `search_terms:` block verbatim when present; the compile artifact for each pilot context is frozen as a fixture (`tests/arv2/v26/fixtures/compile_<context>.json`) and reviewed once; a changed compile is a changed `plan_sha` (already true) |
| 9 | 03 §3.5.4 | Truncated output (`finish_reason=length`) → split the batch/chunk in half and re-run (deterministic), not a retry of the same request; after the wall, re-run skipped sources once, then `needs_review/extract_incomplete` |
| 10 | 03 §3.5.2 ↔ 04 W3-23 | One extractor default (`google/gemini-3.8-flash`), one batch/chunk shape (03's 4 × 24k / 20k), one concurrency pair (03's 6 per job / 16 per process); the Luna comparison is run once at the freeze (§3 row 1) |
| 11 | 05 §3 AT-9 | Split into the floor line (rule/template reproduction of every floor pair = 1.0, deterministic, gating) and judge-only chain recall (≥ 0.75, reported); the gating number is computed on the RC-2 recorded universe |
| 12 | 04 §2 | Add `P6` — the `profile_ref` v4 filter fix in `stop_contact_jobs` and `claim_writer` (03 §3.2), owner A, gate *all*, week 1, with a DB test that a v4 person job's privacy-stop sets `input_refs.privacy_stopped` |
| 13 | 03 §2.5 ↔ 04 §11 | One sentence from the founder on the person floor at import for r27; the set then says one thing |
| 14 | 04 §0.2, §7 | Collapse to one mint (§4.2): W1 ships as flags on v25; r27 is the only recipe mint; 04 §9 uses 03's setting names; W2-19 moves after RC-2 |
| 15 | 05 §6.3 | Add: a re-driven judge turn after `quality_unit_incomplete` is a second full budget and is counted as a separate turn by Q2; a page job past `PAGE_REOFFERS_MAX` stays `needs_review` until `manual_refresh` |

With edits 1–7 the three founder axes read: cost bounded at ≈ $23 structurally and gated at
$9.0 modeled (expected $3.5–4.3); depth from templates and rules equal to today's template layer
plus 01b's full floor, with the judge's 16–40 % budgeted and measured rather than hoped; and one
mint on a runtime whose journal, replay, import and DSAR paths are unchanged.

---

## Appendix A — cross-document contradictions that bear on determinism (03 vs 04 vs 05)

| # | Topic | 03 | 04 | 05 uses | Resolution |
|---|---|---|---|---|---|
| A.1 | Brief emission | `submit_brief@1`, one round + finalize (§3.7) | `save_dossier_section@2` per class → `validate_dossier` → `finish_dossier` → `finalize_turn` (W3-24) | 03's (`submit_brief` in AT-4) | 03 (edit 2) |
| A.2 | Clearing config for the r27 judge | 45k / 42k, keep 4, acquire receipts cleared (§5.3, with the arithmetic) | trigger = cap − 10k, keep 6, acquire excluded (W1-1 list reused by W3-24) | `compaction_events = 0` | 03 (edit 3) |
| A.3 | Extractor default | blank; composition refuses `extractor_model_unset` (§3.5.2, §10 C6) | `CLUE_ARV2_EXTRACT_MODEL=google/gemini-3.8-flash` with `RESEARCH_EXTRACT_AGENT_MODEL` blank falling back to it (W3-23) | D4 "the pick" | 04's default, 03's name (edit 10) |
| A.4 | Extraction batch / chunk / concurrency | 4 × 24k, chunk 20k + 500 overlap; 6 per job, 16 per process | < 6k sources ≤ 4 per call, chunk 12k; `CLUE_ARV2_EXTRACT_CONCURRENCY=8`, no process cap | — | 03 (edit 10) |
| A.5 | Person floor at import | runs for recipe ≥ 27 (§2.5) | advisory exemption untouched, parked ruling (§11) | — | ruling (edit 13) |
| A.6 | Setting names | `CLUE_ARV2_V26_*` throughout (§10) | `CLUE_ARV2_JUDGE_*`, `CLUE_ARV2_EXTRACT_*`, `CLUE_ARV2_PLAN_*`, `CLUE_ARV2_CONTACT_WAIT_FOR_ACCOUNT_S`, `CLUE_ARV2_RECIPE_PILOT_*` (§9) | 04's for P5 and judge budgets, 03's for the rest | one scheme; regenerate 04 §9 from 03 §10 (edit 14) |
| A.7 | Recipe numbering | pipeline = recipe 26 | pipeline = r27, week-1 mint = r26 | 04's | one mint makes it moot (edit 14) |
| A.8 | Deferred contact page | `arv2_display_page` task with a `brief-v26` writer branch (§3.8) | research-kind continuation on the research handler (§0.5, P1) | both handlers composed | either; both need the attempt cap (edit 5) |
| A.9 | DSAR v4 filter fix | required, blocking (§3.2) | absent | — | add P6 (edit 12) |
| A.10 | A3 per-round caps | 8 / 4, to be raised to "01b maxima + 1" (Appendix C) | `CLUE_ARV2_PLAN_FOLLOWUP_ROUNDS=2`, no per-round op cap named | — | 03's two settings; restate the ceiling once aligned (§1.2 row 10) |

## Appendix B — numbers used

- Corpus (42 runs): account rounds median 56 / max 74, evidence calls 29 / 37, model $4.92 / $7.82;
  person rounds 44 / 68, evidence calls 16 / 28, model $3.21 / $7.79 (`runs.csv`). Output tokens
  per model call: median 321, mean 721, p90 1,944, max 6,252 (`model-calls.csv`, 1,956 calls).
  Full prefix-cache misses after round 1: 51 of 1,914 (2.7 %).
- 01b: follow-ups 404 of 699 completed operations (58 %); 401 A-class findings, 65 strict (16 %),
  242 possible (60 %), 159 template-only (40 %); depth-2 chains 5 (8 A findings); floor pairs 18;
  caps cut 26 of 401 A items at the plan's values.
- Mortenson: 45 chains (21 strict-backed); account 27 A (14 strict, 12 possible, 1 template);
  contacts 34 A (14 template, 6 strict, 14 possible). Dialpad: 37 chains (10 strict-backed);
  account 20 A (2 / 13 / 5); contacts 57 A (12 strict, 28 possible, 17 template); Flynn carries
  the corpus's three depth-2 contact chains with 8 strict A of 16.
- Cost arithmetic: §1.1 and §1.3, recomputed from 03 §5.5's formula and prices with a script
  over the parameter sheet; the structural column uses rounds × `max_output_tokens`, the
  compaction trigger + one round's growth as the per-call input bound, and 6,000 tokens × calls
  for extraction.
