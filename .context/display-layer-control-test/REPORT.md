# Display-layer control test — how should claim rows become page copy?

**Date:** 4 Sep 2026. **Data:** the real Zafran Security run (174 claims → 89 rows for Nick Fisher's contact
page, 159 rows for the account Insights page). **Harness:** `control_test.py` in this folder; every raw
response is in `raw/`, every rendered page in `out/`, every score in `results.jsonl`.

Three questions were asked:

1. **One call per section, or the whole page in one call?**
2. **Can a cheaper OpenRouter model write the page as well as `gpt-5.6-luna`?** (including the Meta
   Muse Spark 1.3 contributor model the founder named)
3. **Where does the cost go, and how do we cut it without losing quality?**

## 0. The answer in five lines

- **Per section, in parallel, with Luna.** Same faithfulness as whole-page (zero leaks, zero non-verbatim
  quotes in every Luna run), zero off-recipe citations (whole-page drifted 3–6 per page), each section
  regenerable on its own, and a failed section costs one retry instead of one page. Latency is the same
  as a whole-page call once sections run in parallel (~15 s).
- **No cheaper model passes.** Every cheaper model failed at least one non-negotiable: unsafe facts in
  outreach copy (Gemini 2.5 Flash Lite, GPT-5 mini, Llama 4 Maverick), paraphrase inside quotation marks
  (Mistral, GLM, Gemini), invented product claims (Qwen), or unusable latency (DeepSeek 4 min, GLM 16
  min, Qwen/Llama/Nano 2–2.5 min). The Muse Spark 1.3 contributor model is gated behind an 18+
  attestation on the OpenRouter account and could not be called; Muse Glimmer 30B, the callable Meta
  model, was the best of the cheap set on the contact page and inconsistent on Insights.
- **Luna is already the cheap layer:** $0.004–0.011 per page cold, $0.004–0.008 warm. An account's full
  set (overview + insights + five contacts) is about **5 cents**. A thousand accounts is ~$50, against
  ~$150+ of research spend for the same thousand. Do not optimise the model; optimise *when* pages are
  regenerated.
- **The savings that matter:** regenerate only sections whose cited claims changed (per-section mode
  makes this possible); keep a stable prompt prefix so OpenAI's cache pays (measured: 76,634 of 76,649
  prefix tokens served from cache, $0.0251 → $0.0077); generate contact pages lazily on first open;
  use the `:batch` endpoints (50% off) for nightly refreshes. **Do not lower Luna's reasoning effort:**
  at `effort: low` the contact page cited an unsafe claim inside Openers and Angles in both runs (3
  citations each, against 0 in every default-effort run) and it was not cheaper ($0.0067 vs $0.0044–0.0052). The
  reasoning budget is what enforces the safety rule.
- **Two defects belong upstream, not in the prompt:** (a) the same fact stored twice with different
  `outreach_safe` flags (the cocktail hobby: `zaf-110` safe, `zaf-160` unsafe because it adds a Patreon
  detail) confused every model *and* the judge; (b) the eight unsafe rows contain three near-duplicate
  pairs, so every model's "do not mention" list was either padded or incomplete. Dedupe at the claim
  store; the display layer should see one fact, one flag.

## 1. What was measured

**Configs.** Two pages (contact = Nick Fisher, insights = the account). Luna three ways — `whole`
(one call), `section_min` (one call per section, only that section's recipe claims), `section_cached`
(one call per section, the *full* claim set as an identical prefix, the section as the suffix, calls in
sequence so the provider cache can hit). Nine other models whole-page. Two runs of everything.

**Mechanical checks (code, no model):** quotes verbatim? (every quoted span ≥4 words must be a substring
of a claim value/quote) · numbers in the payload? (every number ≥13 must appear in the claims) · claim
ids valid? · sentences without a claim id · unsafe rows cited outside "Do not mention" · off-recipe
citations (a claim whose field key is not in that section's allowed list) · P1 coverage · use-lines on
the contact page · claim ids typed into prose · sections present.

**Blind judge:** `anthropic/claude-sonnet-5`, given the same claims, the section instructions and the
output, not told the model. Scores 1–5 for faithfulness / specificity / actionability / clarity /
structure, overall 1–10, one sentence on the worst problem. The insights page was re-judged under a
page-aware rubric after the first pass penalised the absence of `sendLine` on a page that does not ask
for one.

**Harness lessons** (they are findings too — each one would have bitten the production prompt):
1. "Every quotation mark wraps verbatim claim text" collided with "put the sendable line in quotes":
   Luna's openers became quoted claim fragments. Fix: a separate `sendLine` field.
2. Models type claim ids into prose (`[zaf-088]`); the frontend would render them literally. Counted as
   `ids typed in prose`; the production prompt needs one line forbidding it.
3. Straight-quote pairing must be sequential, not regex-paired, or a closing mark pairs with the next
   opening one and every model looks like it paraphrases.
4. Luna's whole-page call produced one malformed page in three (closed the sections array after
   section 1); gpt-5-nano produced one section of six twice. Whole-page failure is all-or-nothing.

<!-- TABLES -->
### Table A — Luna, three ways of calling it (every run)

| page | mode | rep | cost | calls | latency total / longest call | prompt tok | cached tok | output tok | judge /10 | faith /5 | off-recipe cites | ids typed in prose | items |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| contact | whole | r1 | $0.0044 | 1 | 24.1s / 24.1s | 15,159 | 15,156 | 3,436 | 5 | 4 | 6 | 0 | 22 |
| contact | whole | r2 | $0.0045 | 1 | 24.1s / 24.1s | 15,159 | 15,156 | 3,506 | 6 | 3 | 3 | 0 | 23 |
| contact | section_cached | r1 | $0.0251 | 5 | 44.7s / 12.1s | 76,649 | 0 | 4,930 | 7 | 5 | 0 | 6 | 21 |
| contact | section_cached | r2 | $0.0077 | 5 | 42.0s / 9.4s | 76,649 | 76,634 | 5,150 | 6 | 4 | 5 | 0 | 22 |
| contact | section_min | r1 | $0.0125 | 5 | 56.4s / 14.3s | 17,260 | 0 | 6,814 | 5 | 4 | 0 | 8 | 23 |
| contact | section_min | r2 | $0.0081 | 5 | 51.6s / 14.8s | 17,260 | 17,245 | 6,449 | 7 | 4 | 0 | 0 | 23 |
| contact | whole_low | r1 | $0.0067 | 1 | 22.0s / 22.0s | 15,159 | 0 | 2,441 | 3 | 4 | 6 | 0 | 20 |
| contact | whole_low | r2 | $0.0067 | 1 | 21.4s / 21.4s | 15,159 | 0 | 2,437 | 3 | 4 | 5 | 0 | 19 |
| insights | whole | r1 | $0.0112 | 1 | 28.6s / 28.6s | 25,097 | 0 | 4,142 | 5 | 4 | 3 | 0 | 24 |
| insights | whole | r2 | $0.0041 | 1 | 20.1s / 20.1s | 25,097 | 25,094 | 3,014 | 7 | 4 | 3 | 0 | 22 |
| insights | section_cached | r1 | $0.0464 | 6 | 68.7s / 17.0s | 151,407 | 0 | 7,162 | 6 | 4 | 7 | 19 | 23 |
| insights | section_cached | r2 | $0.0118 | 6 | 57.0s / 12.7s | 151,407 | 151,389 | 7,273 | 6 | 4 | 2 | 36 | 24 |
| insights | section_min | r1 | $0.0149 | 6 | 66.2s / 14.5s | 20,841 | 0 | 8,077 | 6 | 4 | 0 | 14 | 27 |
| insights | section_min | r2 | $0.0106 | 6 | 63.0s / 12.2s | 20,841 | 20,823 | 8,496 | 4 | 4 | 0 | 12 | 27 |
| insights | whole_low | r1 | $0.0095 | 1 | 22.2s / 22.2s | 25,097 | 0 | 2,690 | 7 | 5 | 9 | 0 | 20 |
| insights | whole_low | r2 | $0.0044 | 1 | 26.9s / 26.9s | 25,097 | 25,094 | 3,227 | 6 | 4 | 14 | 0 | 20 |

### Table B-contact — every model, whole page in one call (mean of 2 runs)

| model | $/M in / out | cost per page | latency | usable JSON | judge /10 | faith /5 | action /5 | unsafe leaks | quotes not verbatim | numbers not in payload | off-recipe cites | ids typed in prose | items |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| meta/muse-glimmer-30b | 0.30 / 1.10 | $0.0100 | 16s | 2/2 | 6 | 4 | 3.50 | 0 | 0 / 6 | 0 / 20 | 4.50 | 0 | 22 |
| gpt-5.6-luna | 0.20 / 1.20 | $0.0000 | 24s | 2/2 | 5.50 | 3.50 | 3.50 | 0 | 0 / 4 | 0 / 16 | 4.50 | 0 | 22 |
| gpt-5-mini | 0.25 / 2.00 | $0.0200 | 104s | 2/2 | 4.50 | 3.50 | 3 | 1 | 0 / 2 | 1 / 18 | 10 | 0 | 20 |
| deepseek-v4-flash | 0.089 / 0.177 | $0.0000 | 84s | 2/2 | 4.50 | 3 | 3.50 | 0 | 0 / 11 | 0 / 14 | 4 | 3.50 | 20 |
| gemini-2.5-flash-lite | 0.10 / 0.40 | $0.0000 | 11s | 2/2 | 4 | 3 | 2.50 | 1 | 0 / 4 | 0 / 12 | 21.50 | 0 | 18 |
| qwen3.7-flash | 0.03 / 0.13 | $0.0000 | 120s | 2/2 | 4 | 2 | 3 | 0 | 0 / 19 | 0 / 14 | 1.50 | 19.50 | 18 |
| mistral-small-2603 | 0.15 / 0.60 | $0.0000 | 14s | 2/2 | 3.50 | 2.50 | 2.50 | 0 | 0.50 / 6 | 0 / 16 | 8.50 | 0 | 16 |
| llama-4-maverick | 0.20 / 0.70 | $0.0100 | 104s | 2/2 | 3.50 | 2.50 | 2.50 | 1.50 | 0 / 0 | 0 / 10 | 11 | 36 | 16 |
| gpt-5-nano | 0.05 / 0.40 | $0.0100 | 120s | 1/2 | 3 | 4 | 3 | 0 | 0 / 0 | 0 / 12 | 3 | 0 | 9 |
| meta/muse-spark-1.3-contributor | 0.10 / 0.20 | $0.0000 | 0s | 0/2 | — | — | — | 0 | 0 / 0 | 0 / 0 | 0 | 0 | 0 |
| glm-5.3-flash | 0.075 / 0.25 | $0.0000 | 275s | 0/2 | — | — | — | 0 | 0 / 0 | 0 / 0 | 0 | 0 | 0 |

### Table B-insights — every model, whole page in one call (mean of 2 runs)

| model | $/M in / out | cost per page | latency | usable JSON | judge /10 | faith /5 | action /5 | unsafe leaks | quotes not verbatim | numbers not in payload | off-recipe cites | ids typed in prose | items |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| glm-5.3-flash | 0.075 / 0.25 | $0.0200 | 960s | 2/2 | 7 | 3.50 | 4 | 0 | 1 / 59 | 0 / 74 | 0.50 | 0 | 25 |
| gpt-5.6-luna | 0.20 / 1.20 | $0.0100 | 24s | 2/2 | 6 | 4 | 3 | 0 | 0 / 8 | 0 / 38 | 3 | 0 | 23 |
| meta/muse-glimmer-30b | 0.30 / 1.10 | $0.0100 | 110s | 2/2 | 5.50 | 4 | 3 | 0 | 0 / 14 | 0 / 42 | 0.50 | 0 | 21 |
| gpt-5-mini | 0.25 / 2.00 | $0.0300 | 139s | 2/2 | 5.50 | 4 | 3 | 0 | 1 / 16 | 0 / 38 | 9.50 | 4 | 24 |
| mistral-small-2603 | 0.15 / 0.60 | $0.0100 | 19s | 2/2 | 4.50 | 3 | 3 | 0 | 4 / 8 | 0.50 / 40 | 9.50 | 0 | 20 |
| deepseek-v4-flash | 0.089 / 0.177 | $0.0000 | 239s | 2/2 | 4 | 3 | 3 | 0 | 0 / 8 | 0.50 / 34 | 8 | 0 | 22 |
| qwen3.7-flash | 0.03 / 0.13 | $0.0000 | 156s | 2/2 | 3.50 | 3 | 3.50 | 0 | 0 / 16 | 0 / 34 | 11 | 0 | 20 |
| gemini-2.5-flash-lite | 0.10 / 0.40 | $0.0000 | 14s | 2/2 | 3 | 3 | 2.50 | 2.50 | 0.50 / 5 | 0 / 22 | 10.50 | 0 | 22 |
| llama-4-maverick | 0.20 / 0.70 | $0.0100 | 138s | 2/2 | 3 | 3 | 2 | 0 | 0.50 / 6 | 0 / 28 | 5 | 40.50 | 20 |
| gpt-5-nano | 0.05 / 0.40 | $0.0100 | 150s | 2/2 | 2.50 | 3 | 2 | 0 | 0 / 1 | 0 / 16 | 2.50 | 0 | 12 |
| meta/muse-spark-1.3-contributor | 0.10 / 0.20 | $0.0000 | 0s | 0/2 | — | — | — | 0 | 0 / 0 | 0 / 0 | 0 | 0 | 0 |

### Table C — the judge's single worst problem per model (contact page, run 2)

| model | worst problem |
|---|---|
| gpt-5.6-luna | The Angles > Landing Page item cites zaf-090 (account.abm_program_maturity) and zaf-089 (account.gtm_tooling_stack), neither of which is in that section's allowedFieldKeys list, a clear structure violation, and the writer also skirts the unsafe-hobby rule by o |
| meta/muse-glimmer-30b | The openers section uses the cocktail-hobby fact twice (the channel/book opener and the 'expensive/time-consuming' voice quote opener) but only tags one as a personal-life hook, violating the 'at most once' rule and duplicating the strongest opener's angle. |
| gpt-5-mini | The openers section builds an item on claim zaf-160 (Patreon/kitchen-filming hobby detail) which is marked outreachSafe=false, while that same claim is simultaneously listed as forbidden in the do_not_mention section — a direct breach of the 'unsafe facts only |
| gemini-2.5-flash-lite | The Patreon/'films in his kitchen' fact (zaf-160) is marked outreachSafe:false and correctly gets a 'do not mention' entry, yet the writer also uses that same claim as supporting fact in the why_this_person and openers sections that go straight into send-ready |
| deepseek-v4-flash | The do-not-mention section is incomplete (skips unsafe claims zaf-138 'competitive differentiation struggles' and zaf-160 'Patreon monetized hobby') and several items in problem_now/angles cite fieldKeys outside the section's allowedFieldKeys list (e.g., zaf-1 |
| qwen3.7-flash | The do-not-mention section omits two outreachSafe=false claims (zaf-139 Amex funding detail, zaf-160 Patreon/hobby monetization) and the openers section then builds a send-ready line straight from the adjacent 'safe' Patreon quote (zaf-104), effectively smuggl |
| mistral-small-2603 | Both 'Angles' items and one 'Openers' item pull from fieldKeys explicitly disallowed for those sections (account.hiring_velocity, account.abm_program_maturity, account.gtm_tooling_stack, contact.facet.self_summary), and a real unsafe fact (the Amex Ventures fu |
| llama-4-maverick | Nearly every 'problem_now' and 'angles' item ignores the instruction to describe the person's problem and instead inserts generic Clue-pitch filler ('Clue can support this effort by providing account discovery, research...') tagged to claims that don't support |

Spend: generation $0.499 across 56 page runs; judging $10.19.
<!-- /TABLES -->

## 2. Question 1 — per section or whole page?

What the numbers say (Table A):

- **Faithfulness is identical.** Every Luna run, all three modes: 0 unsafe leaks, 0 non-verbatim quotes,
  0 numbers outside the payload, 0 invalid claim ids.
- **Recipe discipline is not.** Whole-page cited outside the section's allowed field keys 3–6 times per
  page (a landing-page angle built on the hiring data, funding facts inside "Why this person"). With
  `section_min` that is physically impossible: the model only receives the section's claims. The
  `section_cached` variant, which sees everything, drifted again (2–7).
- **Judge scores are within noise at n=2:** contact 5.5 (whole) vs 6.0 (section_min) vs 6.5
  (section_cached); insights, page-aware rubric, 6.0 (whole) vs 5.0 (section_min) vs 6.0
  (section_cached). The one section_min insights run that scored 4 had left every "What it means for
  us:" line blank in Contact insights — a formatting failure a schema check catches, not a quality
  ceiling. The judge's repeated complaint about per-section output was repetition across sections (the
  ABM-req fact appearing in three sections) — the price of sections not seeing each other.
- **Formatting differed:** per-section Luna typed claim ids into prose (6–36 per page), whole-page never
  did. A one-line prompt fix, but real.
- **Cost:** whole $0.004–0.011; `section_min` $0.008–0.015; `section_cached` $0.008 warm / $0.025–0.046
  cold. Absolute differences are under a cent per page.
- **Latency:** whole 20–29 s; sections 42–69 s in sequence, but the longest single section was 9–17 s,
  so in parallel a page is ready in ~15 s.
- **Failure shape:** whole-page fails as a page (1 in 3 Luna calls malformed in the smoke; 2 of 2 nano
  calls partial). Per-section fails as a section.

**Recommendation:** `section_min`, all sections fired in parallel, Luna, plus three prompt lines: never
type claim ids into prose; write dates as "17 June 2026"; each section is told the H2s already used by
the sections generated before it *when regenerating incrementally* (on first generation, accept some
overlap or run a cheap dedupe pass). The cached-prefix trick is only worth it when calls are sequential;
in parallel it does not hit, and `section_min`'s inputs are small anyway (3–4k tokens per call).

## 3. Question 2 — a cheaper model?

Table B, both pages. The two non-negotiables are the *unsafe leaks* and *quotes not verbatim* columns;
a model that fails either cannot write outreach copy no matter its price.

- **Gemini 2.5 Flash Lite** ($0.003, 11 s): fastest and cheapest, and it put unsafe claims into
  outreach sections on both pages (1 and 2.5 per page) and drew off-recipe 10–22 times. Openers read as
  compliments ("sounds delicious!"). Out.
- **GPT-5 mini** ($0.019–0.031): costs *more* than Luna, takes 100–140 s, leaked once. Out.
- **GPT-5 nano** ($0.007–0.009): 2–2.5 min, and produced one section of six twice; incomplete pages. Out.
- **DeepSeek V4 Flash** ($0.004): the best prose of the cheap set and the only model that cross-referenced
  people, but it upgrades inference into fact ("Zafran explicitly does not use 6sense", "Vari is actively
  seeking the right ABM platform" — neither is in a claim), and 84–240 s per page. Out for now.
- **Qwen 3.7 Flash** ($0.002): invented a product claim in a send line ("our enriched data cuts
  list-building time by half"), mislabelled RSM reqs as SDR roles, 120–155 s. Out.
- **Mistral Small** ($0.004, 14 s): paraphrased inside quotation marks (4 per insights page), misgendered
  the CEO, dropped two committee members from "Contact insights". Out.
- **Llama 4 Maverick** ($0.006): leaked, typed 36–40 claim ids into prose, invented outreach lines nobody
  asked for, and wrote as if Clue were pitching to *partner with* Zafran. Out.
- **GLM 5.3 Flash** ($0.004 contact / $0.021 insights): the contact call spent its entire budget on
  reasoning and returned nothing, twice; the insights page took **16 minutes** and scored the highest of
  any model with the judge. Unusable operationally.
- **Muse Glimmer 30B** ($0.005, 16 s contact / 110 s insights): contact page judge 5 and 7, zero leaks,
  zero non-verbatim quotes, off-recipe 4.5; on Insights one run produced one item per section. The only
  cheap model worth a second look, and only for the contact page.
- **Muse Spark 1.3 contributor:** blocked — OpenRouter returns HTTP 403 `age_18plus` on this account.
  Tick the attestation at openrouter.ai/settings/preferences and `python3 control_test.py --run` will
  fill in its four rows without touching anything else.

**Recommendation:** stay on Luna. The cheap models do not fail on style; they fail on the two rules the
product cannot bend on, and Luna's whole-account cost is already about five cents.

## 4. Question 3 — the cost side, with quality held

Where a Luna page's cost goes (Table A): input tokens dominate a cold call (15–25k in vs 3–8k out), and
OpenAI caches a repeated prefix at a 90% discount — the same contact page cost $0.0044 warm against a
cold-equivalent of ~$0.011. So the levers, in order of what they save:

1. **Regenerate only what changed.** Store each section with the claim ids it cites; when a claim is
   superseded, regenerate that section, not the page. This is the largest saving over the life of an
   account and it needs per-section generation.
2. **Generate contact pages lazily** on first open for P2/P3 committee members (Ben Seri's page has no
   reader until someone clicks). Roughly halves contact-page volume.
3. **Stable prefix, variable suffix.** System prompt + client context + claims first, section
   instruction last, and fire the first section alone before the rest so the cache is warm: measured
   $0.0251 → $0.0077 on the contact page, $0.0464 → $0.0118 on Insights.
4. **Batch endpoints** (`openai/gpt-5.6-luna:batch`, 50% off) for nightly re-verification runs where
   nobody is waiting.
5. **Trim the payload:** drop P3 `core.*` boilerplate and truncate long arrays (career histories are
   ~300 tokens each) — the Insights payload is 25k tokens and could be ~15k. Untested here; expected
   30–40% off cold input.
6. **Reasoning effort — measured, and rejected.** At `reasoning: {effort: "low"}` Luna used ~110–170
   reasoning tokens instead of 415–5,237, was *not* cheaper on a cold call ($0.0067 vs $0.0044–0.0052),
   and on the contact page cited the unsafe hobby claim (`zaf-160`, the Patreon-monetisation version)
   inside "Openers" and "Angles" in both runs, three citations per run. The judge still gave it 3/10 with
   faithfulness 4 — the leak is invisible to a reader, which is exactly why the mechanical check exists.
   Keep the default effort.

And the two upstream fixes from §0: one fact one flag, and dedupe the unsafe near-duplicates in the
claim store. They cost nothing and remove the single most common judge complaint.

## 5. Files

- `control_test.py` — harness (`--smoke`, `--run`, `--rescore`, `--judge`, `--report`); `debug_metrics.py`
  lists a run's exact violations; `report_tables.py` renders the tables above.
- `results.jsonl` — every run with metrics and judge scores (`judge_v1` = the first insights rubric).
- `out/*.md` — every generated page, readable; `raw/*.json` — every API response.
- `summary.md` / `summary.json` — the aggregate table.
