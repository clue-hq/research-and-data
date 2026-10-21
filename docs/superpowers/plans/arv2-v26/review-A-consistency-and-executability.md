# ARV2 v26 — Review A: cross-document consistency and executability

**Status:** adversarial review, 2026-10-07, read-only. Reviewer A. Checkout `fa4bed77b` (branch
`shank-audit-account-research-cost-optimization`); every `path:line` below was re-read in this
checkout. **Set reviewed:** `01-evidence-all-production-runs.md` (01), `01b-follow-up-chains-and-nothing-lost.md`
(01b), `02-codebase-map-research-lane.md` (02), `03a-runtime-and-toolbelt-mechanics.md` (03a),
`03-target-architecture-v26.md` (03), `04-implementation-spec-w0-w4.md` (04), the founder-reviewed
plan `docs/superpowers/plans/2026-10-06-account-research-v26-cost-and-speed-plan.md` (plan), and the
rulings in the charter. 05 (verification) was not read. "Doc L123" = that document's line 123 in
the working tree at review time.

**Headline.** The evidence record (01, 01b, 02, 03a) is accurate: of 100+ `path:line` citations
spot-checked, 12 are wrong or stale and 4 code *claims* are wrong (§2). The two forward documents
(03 and 04) were written in parallel and **describe two different builds**: different recipe
integers, different judge tool surface, different role name, different pool/marker names,
different waits, different settings (03 §10 lists ~70 `CLUE_ARV2_V26_*` settings; 04 §9 lists 31
with other names), different quote rule, different follow-up table shape and path, different
contact-page mechanism. 40 contradictions are tabulated in §1. 04 as written has 70 open
implementer questions (§4), 13 of which block coding (marked **B**: Q9, Q20, Q23, Q26, Q30, Q35,
Q49, Q51, Q56, Q62, Q63, Q66, Q69). **Not ready for Aryan**; the minimal edit list is §6.

**Counts:** 40 cross-document contradictions (§1) · 12 wrong/stale citations + 4 wrong code
claims (§2) · 70 open implementer questions in 04, 13 blocking (§4) · 19 missing pieces (§5).

**Authority order I applied when naming a winner** (the set states none; 04 L8-10 says "03a §8
wins per the charter", 03 L8-9 diverges from 03a with arithmetic, 04 §0.5/§0.6 diverge from 03a
with reasons): the plan and the rulings win on *what* (budgets, caps as floors, AT-1…9); 04 wins
on *mechanism and names* where it gives a verified reason (it is the document Aryan codes from);
03 wins on the *contract and arithmetic* where 04 is silent or thinner (classes, server-side
derivations, context-cap arithmetic, waits); 01b wins on *data* (rule rows, cap evidence); code
wins over all four where they disagree with it.

---

## 1. Cross-document contradictions

Columns: what the documents say (with lines), which should win, the fix. "r26/r27" = 04's two
recipe integers; "v26" = the program.

| # | Topic | 03 | 04 | 03a / plan / 01b | Winner | Fix |
|---|---|---|---|---|---|---|
| C1 | **Recipe integers and what is gated on ≥ 26** | One recipe: `v26`/`v26-person` are the judge profiles, `CURRENT_RECIPE_VERSION = 26`, every pipeline behaviour gated `>= 26` (L40-43, L1379-1395, §3.6.1, §9.1) | Two mints: **26** = week-1 (W1-2/3/5/9/12/13/14, P1, W1-8, W1-10), **27** = the pipeline (W3-*), `uses_extraction`, per-role roles/budgets, pool in L7 (L43-59) | 03a §2.1 L237-240 "a v26 recipe needs … `CURRENT_RECIPE_VERSION = 26`"; plan §5 L471 "behind `CLUE_ARV2_RECIPE_VERSION=26`" | **04** (shape changes in week 1 force a mint; 03a §2.1 proves it) | 03: every "recipe ≥ 26" that names the pre-step, `acquire@2` candidates, the brief, per-role allowances, clearing values, floor-at-import, media gate, brief-fed pages → "≥ 27"; §9.1 `CURRENT_RECIPE_VERSION` → 27 at the W3 mint; add one line "recipe 26 = week-1 mint, 27 = pipeline" |
| C2 | **Recipe selection settings** | `CLUE_ARV2_RECIPE_VERSION` default **25** + `CLUE_ARV2_RECIPE_V26_WORKSPACES` (L1381-1386, §10 C1 L1447-1448) | `CLUE_ARV2_RECIPE_VERSION` **blank** (= current) + `CLUE_ARV2_RECIPE_PILOT_VERSION` + `CLUE_ARV2_RECIPE_PILOT_WORKSPACES` (P5 L273-297) | 03a §8a L717-718: `CLUE_ARV2_ACQUISITION_PLAN_ENABLED` "per workspace with `CLUE_ARV2_RECIPE_VERSION=26`" | **04** (generic pilot, reusable for 27 and later) | 03 §9.1, §9.2, §10 C1 → 04's three lines; 03a §8a footnote |
| C3 | **Contact lane role name and model lines** | `person_research`, `PERSON_RESEARCH_AGENT_MODEL`/`_EFFORT` (L698, L1542, L1401, App B L1619) | `CONTACT_RESEARCH = "contact_research"`, `CONTACT_RESEARCH_AGENT_MODEL`/`_EFFORT` (W3-26 L1109-1138, §9 L1679) | plan item 26 unnamed; 03a §2.2 L266-272 unnamed | **04** (`contact` is the product noun; `ResearchRunKind.CONTACT_RESEARCH="contact_research"` already exists in `libs/clue-core/clue_core/entity_research.py:75` — harmless, different enum) | 03: rename in §3.6.1, §8.1 (trace `person-research.turn` → `contact-research.turn`), §9.2, §10 C7, App B |
| C4 | **Judge tool surface and how the brief is emitted** | `acquire@2`, `search_evidence@2`, **`submit_brief@1`** (new; validates, derives `review`, restores quotes from candidates, marks over-cap, checks interpretation presence, resolves candidate ids, checks `not_found` op ids, then runs the `finish_dossier` body) — dossier tools **not pinned**, nominate **none** (§3.6.1 L701-712, §3.7 L779-832, App A.2) | r27 pins `acquire@2`, `search_evidence@3`, nominate ×2 `@3`, `save_dossier_section@2`, `update_dossier_findings@2`, validate/finish/begin/discard `@1`; the brief is emitted via `save_dossier_section@2` one section per class → `validate` → `finish` (W3-24 L1413-1425, §8.1 L1624); **no `submit_brief`**, none of 03's nine derivations | plan item 24 "the §1 brief as the output schema" | **Undecided — must be one.** 04's path reuses W1-2 and the unchanged import; 03's path is two rounds and does the derivations that make a defaulted item import `supported`, restore evidence from the candidate, and enforce AT-4. Recommend 04's tool set **plus** the derivations as an r27 branch of `FinishDossierTool.apply` (or `submit_brief@1` as 03) | 04 W3-24: add a numbered "server defaults at finish (r27)" list = 03 §3.7 steps 1-9; prompt instructs saving every class section in ONE round (see Q98); 03 §3.6.1/§3.7 then match whichever |
| C5 | `search_evidence` version pinned by the judge | `@2` (L701) | `@3` (W1-3 L462-473, r26 and r27) | — | **04** | 03 §3.6.1 → `@3` |
| C6 | **`acquire_research_evidence@2` input** | adds `purpose? ≤ 200`, `follows?` (candidate/template/operation id) — "`follows` is what plan AT-9 counts" (L734-736) | "`invoke` is `@1`'s with the receipt builder" — input unchanged (W1-5 L558-559); W3-24 adds nothing; but App A L1760 and §8.4 rely on AT-9 chain recall | plan AT-9 L513-516 | **03** (AT-9 cannot be computed without the lead) | 04 W1-5: `AcquireResearchInput2` gains `purpose`, `follows`; W3-22 `PlanLedger` row gains `follows` (C34) |
| C7 | `acquire@2` receipt `status` literal | `completed\|refused\|outcome_unknown` (L739-741) | `completed\|refused\|unavailable\|tool_error\|outcome_unknown` (W1-5 L549) | plan W1-5 L417 "real outcome (`unavailable`, `tool_error`) in the receipt status" | **04** (plan) | 03 §3.6.3 |
| C8 | Candidates inline in the receipt | ≤ 24 (`CLUE_ARV2_V26_RECEIPT_CANDIDATES_MAX`) + `candidates_path` = new view `/research/operations/<id>/candidates.json` (L718-719, L742-745, §10 C7) | items ≤ 20 / receipt ≤ 10 KiB (W1-5 L552-557); r27 "up to the 10 KiB cap in `receipt.candidates`" (W3-24 L1400); full list at `/research/operations/<id>/0.json` | 03a §8b L744-745 same as 04 | **04/03a** (no new view) | 03 §3.6.2-3.6.3, §5.3 placeholder text, §10 C7 row |
| C9 | **Pool artifact, marker kinds, materialised path** | `application/vnd.clue.research-v26-pool+json`; markers `research_v26_candidates:<job>:<plan_sha>` (first pool) **and** `research_v26_pool_final` (after gap); `inputs/pool-<subject>.json`; `research_v26_compile:<context>`, `research_v26_committee` (L252-253, L654-660, L989-990) | `candidates-account.json`/`candidates-contact.json`; one marker `research_candidates:<job>:<plan_sha>` (W3-21 L1320-1327); `inputs/candidates-<kind>.json` (W3-24 L1390) | 03a §5.4 L541-545 `research_candidates`; §8c L775 `inputs/candidates-<subject>.json` | **04/03a names**; but **two markers** are needed by C11 | 03 renames; 04 adds `research_candidates_first` (after A1+B) beside the final marker, and A0/compile markers |
| C10 | **No-repurchase within an account** | pool-read rule over `arv2_evidence_source` by `source_url` (+ `v26_pool_read` local op) and byte-identical `search_web` reuse (§3.3.4 L459-473) | `SiblingDedup.find_sibling` over `arv2_research_operation` `(ws, run, account, kind, request_sha256)`, account kinds only (W3-22 L1262-1269) | plan W2-18 "by plan"; AT "zero repurchased `(kind, request_sha256)`" | **04** for searches and fetches keyed on request sha (the acceptance metric is request-sha based); URL-keyed reuse only if `max_chars` differs between lanes — it does not (both 8000) | 03 §3.3.4 → 04's helper; keep 03's "measured duplicates" counter |
| C11 | **What each judge waits for** | contact judge waits ≤ `CLUE_ARV2_V26_ACCOUNT_POOL_WAIT_S` (120 s) for the account's **first** pool; account judge waits ≤ `CLUE_ARV2_V26_PEOPLE_POOL_WAIT_S` (240 s, poll 5 s) for every child's **final** pool (§3.6.4 L754-761, §5.6) | person pre-step waits ≤ `CLUE_ARV2_CONTACT_WAIT_FOR_ACCOUNT_S` (240 s) for the parent's `research_candidates` — which 04 writes **after A3 + gap** (L1320-1335); **no** account-side wait for children | plan §2 L252-254 "C-account: … + the people candidates [rev]"; L262-266 contact judge "without waiting for the account judge" | **03** (plan AT-8 and the contact's early start both need the two-stage design); 04's "A1+B ≈ t+3 min" (L1332) contradicts its own marker placement | 04 W3-21: first-pool marker after A1+B; person waits on it (120 s); account pre-step waits ≤ 240 s for children's final pools before the turn is assembled |
| C12 | **AT-8 — the account judge receives the people candidates** | people slice: top 20 per contact from each contact's final pool (§4.3 L983-986; §4.4) | `candidates-account.json` carries `people: [A0 records + their candidates]` (L1326-1327); AT-8 = "the account judge's L7 carries `people`" (L1376, App A L1759). A0 records are AI Ark `provider_record` rows whose prose is dropped (`enrichment_only`; 03 §3.5.1 L579-580) → ≈ 0 candidates | plan AT-8 L512 "receives the people candidates; the org-sequence finding is emitted" | **plan/03** | 04 W3-21 step 2 + AT-8 test: contacts' research candidates present in the account L7; org-sequence finding asserted on the replay |
| C13 | **Persona set for A0** | `economic_buyer, champion, technical_evaluator, blocker, user` (L321) — the `Persona` enum (`libs/clue-core/clue_core/enums.py:358-367`) | `champion, economic_buyer, technical_evaluator, blocker, influencer` (W1-9 L686-687, W3-21 L1339-1341) | plan §2 L211 same as 04 | **03/code** (`influencer` is not a `Persona` value; `role_search_body` and `persona_map` key on the enum) | 04 W1-9, W3-21; plan footnote |
| C14 | A0 call count and pacing floor | 6 AI Ark calls (company_lock + 5 roles) = **63 s** floor (L321-327) | "5 role searches ≈ **52 s** floor" + `company_lock` (L1374, W3-21 step 3) | plan L210-212 "52 s" | **03** (`company_lock` is a paced AI Ark call — `account_research_tools.py:468-492`) | 04 W3-21 acceptance; plan note |
| C15 | AI Ark credits per account + 5 | 0.1 + 5×5×0.5 + 5 exports × 1.0 = **17.6** (L1144-1145) | 12.5 ceiling for role searches (L1343); acceptance "~11 credits" (L1458) | plan L333 "≈ 10.7 (5×5×0.5 + company + 5 exports × 0.6)" — the arithmetic itself is 15.6 | **03** (`PERSON_CREDITS_PER_RESULT` 0.5, export estimate 0.5+0.5 — `ai_ark_client.py:71-73`) | 04 W3-24 acceptance, plan §3 |
| C16 | Cost ceiling per account + 5 | **$9.0 Flash / $7.7 Luna** with D8/D9 pinned, explained (L1156-1163) | "hard ceiling ≈ **$5–6**" (W3-24 L1458-1459) | plan L319-324 "max after pinning ≈ $5/$6" | **03** (it charges gap rounds, the full op budget, the clearing miss and page repairs) | 04 W3-24 acceptance → "expected $3–4, ceiling ≈ $9 (03 §5.5)"; plan §3 note |
| C17 | Expected cost | $3.48 Flash / $2.72 Luna (L1155) | "$3–4" | plan $4.06 / $2.81 | agree within $0.6 (03 says so) — record, no fix | — |
| C18 | **Extractor model default** | `RESEARCH_EXTRACT_AGENT_MODEL` ships **blank**; composition refuses `extractor_model_unset` (L588-590, §10 C6 L1509) | `CLUE_ARV2_EXTRACT_MODEL=google/gemini-3.8-flash` default; `RESEARCH_EXTRACT_AGENT_MODEL=` blank fallback (W3-23 L1197-1206) | 03a §8b L752-754 "falling back to a new `arv2_extract_model` setting (D4)"; plan D4 open | **04** (parity needs a documented default; D4 replaces it) | 03 §3.5.2, §10 C6 |
| C19 | **Extractor batching / concurrency / bounds** | chunk 20 000, batch 4 ≤ 24 000, overlap 500, `max_tokens` 6 000, per-job 6 **and** per-process 16, wall 180 s, retries 1 (L593-605, §10 C6) | sources < 6 000 packed ≤ 4, chunk 12 000, overlap 500, `CLUE_ARV2_EXTRACT_CONCURRENCY=8` (per job only), no per-process cap, no wall, no `max_tokens`, no retry setting (L1163-1165, L1193-1201) | 03a §8b `CLUE_ARV2_EXTRACT_CONCURRENCY` default 8 | **04 names + 03's per-process semaphore and bounds** (6 jobs × 8 = 48 OpenRouter streams otherwise) | one table in 04 §9 + W3-23; 03 §10 C6 mirrors it |
| C20 | **Quote rule implementation** | `substring_verdict(span, source) == "EXACT"` per span (`arv2/text.py`: NFKC, straight quotes, whitespace, case-fold, **non-alphanumerics blanked** — a superset of AT-7) (L612-619) | new `quote_verdict`: "the new function **keeps punctuation** so a quote is verbatim" (L1180-1185) | plan AT-7 L507-511; 01b §5 L318: also fold literal `\n`, strip boundary punctuation, digits/dates exact | **plan AT-7 + 01b, implemented as 03** (keeping punctuation fails 01b's "near-verbatim: boundary punctuation 8" and the 41/43 target) | 04 W3-23: reuse `substring_verdict` per span; add `\n` folding and 01b's digit rule; delete "keeps punctuation" |
| C21 | Elision marker | `[…]` (L612-613) | `[…]` (L1184) | plan `[…]`; 01b L318 "explicit `…` marker" | `[…]` | 01b footnote |
| C22 | **Class caps** | Stack 4, Committee 8, Watch-outs 3; own-words 6, problem-now 3, proud-of 2, hooks 3 (§2.1 L97-119, §10 C2) | same, baked into the v10/v6 skills (W1-14 L863-865, L872-873) | 01b §0 L13 and §6 L374-376: caps **cut A-class** on 3 accounts (Stack 8, Committee 10, Watch-outs 4) and on the richest contacts (own-words 8, problem-now 5, proud-of 3, hooks 4); plan §1 L160-161 says the caps were set so nothing seller-critical is dropped | **01b is the evidence the plan asked for** → founder ruling needed | 06 decision row; until ruled, 03 §2.1 / 04 W1-14 / §9 C2 defaults = 01b's; 03 App C alignment rule extended to caps |
| C23 | **Follow-up rule table — path, shape, vocabulary** | `platform/agents/catalog/research-quality/followups/v1/rules.json`, sha-pinned in the launch map (→ `plan_sha`); rows `{rule_id, subject, trigger{class, any_of \| attribute \| ledger}, operation{kind, query, dated, num_results}, max_per_trigger, max_per_round, dedupe}` (§3.4 L526-552) | `platform/api/clue_api/arv2/followup_rules.json` (first JSON inside the package), rows `{lead_kind, lead_pattern, operation, argument_template, min_support_accounts, examples}`, closed `lead_kind` set of **7** (W0 L119, L145-147); W3-22 hard-codes the plan's **5** floor rules in code (L1270-1273) | 01b §3 T6 + floor L183-199: **11** floor pairs keyed `person-name, vendor-stack, quoted-phrase, url-in-result, subject-site-page, event-talk-media, prior-employer-affiliation, education-prior-employer, departure-succession, job-listing, committee-candidate`; delivered as `.artifacts/arv2-research-runs-20261007/fixtures/rule_table.json` `{method, pairs}` (L444) | **03 shape + path** (sha-pinned data, not code), **01b rows** (7 of 01b's 11 kinds are absent from 04's closed set) | 04 W0: consume 01b's fixtures; W3-22: load 03's `rules.json`; App B path |
| C24 | Follow-up per-round caps | `FOLLOWUP_OPS_PER_ROUND_ACCOUNT` 8 / `_PERSON` 4, ≤ 2 rounds, App C "→ 01b maxima + 1" (L558-562, §10 C5) | `CLUE_ARV2_PLAN_FOLLOWUP_ROUNDS=2`, no per-round op cap (L1286) | plan A3 "≤ 2 rounds" | **03** | 04 W3-22 + §9 |
| C25 | Gap round | `GAP_OPS_PER_CLASS` 2, `GAP_ROUNDS_MAX` 1, `MIN_REMIT` 1, committee gap **nominates** through the web-nomination body (§3.5.7 L677-684, §3.2 L369) | one round, no per-class cap, `CLASS_MINIMUMS` without `remit`, no nomination (L1276-1278) | plan AT-2 | **03** | 04 W3-22 |
| C26 | **Tool-result clearing: values and exclude list** | r27 judge: trigger 45 000/42 000, **keep 4**, excludes only `submit_brief`+`finalize_turn` — `acquire@2` receipts ARE cleared; cap 60 000/56 000; arithmetic shows keep 6 + acquire excluded overruns the cap by round 9 (§5.3 L1064-1089) | W1-1 (all recipes): 100 000/100 000, keep 6, excludes acquire + 7 dossier tools, windows 200 000 (L326-363); W3-24 r27: trigger = cap − 10 000 (= 50 000/46 000), **keep 6**, exclude list unchanged (L1411-1412) | 03a §8d L793-795 excludes acquire | **04's setting family, 03's r27 values and exclude list** (03's arithmetic is correct given the pool sits in the prefix) | 04 W3-24 step 4: r27 clears `acquire@2`; keep 4; 45 000/42 000; W1-1's exclude list is r25/r26 only |
| C27 | Operation-budget count predicate | `kind LIKE 'quality_tool:%'` (L1096) | `… AND state <> 'failed'` (L1402-1403) — argument refusals create a `failed` row (`quality_provider_tools.py:151-153`, `:301-315`) | — | **04** | 03 §5.4 |
| C28 | **Deferred contact page — the fleet unit** | `arv2_display_page` task with `payload.writer="brief-v26"`; the display handler branches to the page-writer runtime; enqueued by contact settle (a), **account settle for every terminal child** (b), sweep (c) (§3.8 L836-846, App A.6) | research kind `arv2_account_research` continuation `"contact_page"`, `_contact_page_continuation` runs `write_job_pages` under `_jobs`; enqueued by contact settle when the parent is ready, else the sweep (§0.5, P1) — reason: the frontend never serves Luna blocks for a quality subject (`frontend_read/display_pages.py:346-375`, verified) | 03a §8f L835-858: display kind + its own `ensure_page` (claim-driven Luna writer) | **04** (verified reason; no display-handler change) | 03 §3.8, §6.1, App A.6 → 04's; 03a §8f note; 04 P1 states that case (b) is covered by the sweep within 10 s |
| C29 | **Insights `context-only` and the Miscellaneous dump** | `CLUE_ARV2_V26_MISC_SECTION=off\|on` (on = dump filtered to `outreach_safe` ∧ `professional-public`) (L854-857, §10 C8); `watch_out` still shared into insights/`context-only` (§2.1 L103) | `stops_miscellaneous(scope)` recipe ≥ 26, no setting (W1-13 b); **(d) drops `context-only` from insights for r26** — reverses the 2026-09-29 placement, flagged for the founder (L822-827) | 02 §10.13 ruling "keep watch-outs like it was before"; plan D3 covers only the dump | **03 (ruling stands)** unless the founder rules | 04 W1-13(d) → a decision row in 06; default stays 03's; pick one of setting vs recipe gate |
| C30 | **Class → section map for per-section pages** | §2.1 table (e.g. `why-they-fit` ← initiative + stack; `how-to-approach` ← initiative, pain, committee; `why-this-person` ← remit, proud_of, career_arc; `angles` ← own_words, proud_of) | W3-25 L1472-1478 (`why-they-fit` ← initiative, motion_proof; `how-to-approach` ← interpretations of trigger/initiative/pain; `angles` ← the account slice; `why-this-person` ← remit, proud_of; no `career_arc`) | — | **03 §2.1** (the contract) | 04 W3-25 cites 03 §2.1 and deletes its own map |
| C31 | Account refresh scope | only `CLUE_ARV2_V26_ACCOUNT_REFRESH_SECTIONS=buying-committee,how-to-approach`, iff packet sha changed (L871-874) | every section whose slice sha changed (L1483-1486) + W1-10 page-level skip | plan D5 | **04** (superset, same cost when nothing changed) | 03 §3.8 |
| C32 | Media switch | `CLUE_ARV2_V26_MEDIA_ENABLED` + 4-condition boot gate (ffprobe present, Deepgram key + one `ok` ledger row, host resolution, receipts) (§7 L1284-1297) | `CLUE_ARV2_MEDIA_ENABLED` (W1-12), no boot gate; W4-2 adds the Deepgram key to required keys only when enabled | plan W1-12 gates in `build_*_tools` on recipe < 26 | **04 name; 03 conditions 1-2 as a boot check in W4** | 03 §7, §10 C1; 04 W4 gains `shutil.which("ffprobe")` + key check at composition |
| C33 | **Person compliance floor at import** | predicate → `(not advisory) or recipe >= 26`; the floor runs on every contact claim (§2.5 L224-229, App A.8) | "the person-floor exemption for advisory recipes (`quality_claims.py:587-590`) is **untouched** (02 §10 item 21: parked ruling)" (§11 L1731-1732) | plan §0 item 26 names the leak; 02 §10.3 (master-plan law: the floor "runs by default and redacts/marks, never drops"); 02 §10.21 parks *stopping collection*, not the floor | **03** — but it is a founder ruling | 06 decision row; 04 gains an r27 item implementing 03 §2.5 (or records the refusal) |
| C34 | **The acquisition ledger the judge reads** | per-op `{op, kind, template, query, state, result_count, http_status, candidates, rejected, follows, pool_read, provider_ms}` + trailer `{minimums before/after, budget, absent_pools}` (§4.2 L960-974) | `PlanLedger` row `{operation_id, kind, label, state, result_count, http_status, error_code, reused_from}` — no `follows`, no candidate counts, no trailer (W3-22 L1259-1261) | plan AT-2 (minimums shown), AT-9 (`follows`) | **03** | 04 W3-22 |
| C35 | **Migrations** | "**No migration**: every durable addition is … an `input_refs` key or an `artifact_reference` kind" (§1.1 L56-59, §9.4, App A.9) — yet 03's own `person_research` role needs the role-CHECK migration (§2 row W2) | three migrations (§10 L1693-1706): W2-17 indexes, W2-19 lazy bytes, W3-26 roles | — | **04** | 03 §1.1, §9.4, App A.9 |
| C36 | `max_output_tokens` on the judge profiles | 15 000 / 12 000 (L703) | 16 384 / 12 288 (L1417-1419) | v25 pins 16 384 | **04** | 03 §3.6.1, §10 C7 |
| C37 | Skills pinned by the judge profiles | "none read at runtime" yet "the resource map still lists `governed-evidence@5`" (L699-700) — self-contradictory | `campaign-brief-account/v1`, `campaign-brief-contact/v1`, `governed-evidence/v5`, `person-research-briefing/v5` (L1426-1430, §8.1) | — | **04** | 03 §3.6.1 row |
| C38 | **Who enqueues the person jobs after A0** | "in the same transaction's post-commit step, `enqueue_launched_jobs`" from the pre-step (L347-348, L1195) | "born `not_started`; W1-8's sweep offers them within 10 s" (L1355) | code: the pre-step runs inside `ResearchUnitRuntime` (03a §8a), composed without a queue (`fleet_main.py:790-792`); the queue is the driver's (`account_research_driver.py:2490`) | **04/code** | 03 §3.2, §6.1 |
| C39 | W0 deliverables vs what 01b already produced | — | new `scripts/arv2_v26_mine_runs.py`; chains at `.artifacts/arv2-v26-replay/<account>/chains.json`; `tests/arv2/v26/nothing_lost_accounts.json`; manifest (W0 L117-140) | 01b §8 L442-446: `fixtures/{chains,nothing_lost}/<account>.json`, `rule_table.json`, `quote_fidelity.json`, `summary.json` + seven scripts already exist under `.artifacts/arv2-research-runs-20261007/fixtures/` (verified; `nothing_lost/` holds **6** files — `nyc.gov` is missing although 01b T11 lists it) | **01b** (done) | 04 W0: consume 01b's fixtures; specify only the conversion to the committed files and the pool freeze (which 01b does not do); add the nyc.gov fixture |
| C40 | Parallel-branch independence | — | §7.1 L1560 "task branches that never touch the same file" — but W1-3 and W1-4 both edit `quality_views.py` and `quality_workspace.py`; W1-5 and W1-12 both edit `quality_provider_tools.py` (04 L1565-1567 lists it as a conflict file) | — | fact | 04 §7.1: W1-3/W1-4 and W1-5/W1-12 integrate in sequence |

Lesser mismatches, recorded without a row: 03 §3.3.3 issues `enrich_contact` only (`P_enrich`) while 04 W3-22 issues `lookup_person` (seeded → saved record + enrich) — equivalent on a seeded job; 03 `CLUE_ARV2_V26_DEEP_SURFACE` (D8) vs 04 silent — `type=deep-reasoning` is hard-coded (`exa_client.py:523`), so D8 is already pinned by code (record it); 03 `CLUE_ARV2_V26_EXTRACT_DEEP_RESULT_TEXT=true` (D9 second half) vs 04 silent; 03 `MAX_PARALLEL_JOBS` 4 → 6 after W2-15 vs 04 silent; 03 §6.1 `input_refs.v26_stage` progress vs 04 silent (§5 M7); 03 §8 spans/metrics/`CLUE_RELEASE` vs 04 W2-20 only (§5 M8); 03 L7 bounds `CLUE_ARV2_V26_L7_MAX_TOKENS_*` vs 04 budgets `(…,120000,…,120000)` that "record, do not refuse".

---

## 2. Claims vs code

Spot-checked 100+ citations across 02, 03a, 03 and 04, prioritising the ones the design leans on.
Verdict: **correct** unless marked. Line numbers are the checkout's.

### 2.1 Wrong, stale or incomplete (12 citations, 4 code claims)

| # | Where | Claim | Actual |
|---|---|---|---|
| W1 | 04 W3-26 L1129-1130 | "`agent_model_call.role` has no CHECK (02 §3.8) — verify" | **Wrong.** `agent_model_call_role CHECK (role IS NULL OR role IN (…))` exists — `alembic/versions/65880921cd52…py:36-40` (re-installed by `c237eb027732`). 02 §3.8 never said "no CHECK". |
| W2 | 04 W3-26 L1126-1128 | the migration extends "the two role CHECKs — `arv2_quality_execution.role` and `agent_turn.role`" | **Incomplete.** Four more enumerate roles: `agent_plan_role` (`6628a407e993…py:59-62`), `agent_delegation_roles` (`f4b30cb3d088…py:27-30`), `agent_model_call_role` (W1), and `quality_execution_role` ties **root** rows to `'account_research'` (`f4b30cb3d088…py:70-72`) — the predicate must admit `contact_research` at `parent_execution_id IS NULL`. The first governed tool call of a contact turn would fail the `agent_plan` INSERT. |
| W3 | 04 W1-6 L590-591 | "the two composition roots (`quality_research_wiring.py:369-388` and the Head-of-ABM assembler in `agent_turn_wiring.py`)" | **Wrong file, wrong count.** `build_agent_context_assembler` is defined in `agent_platform_wiring.py:514`; roots: `conversation_turns.py:797` (Head-of-ABM), `account_research_turn_wiring.py:829`, `onboarding_synthesis_wiring.py:512`, `quality_research_wiring.py:368`. |
| W4 | 04 W1-10 L725 | `page_writer.py:308` — "today fixed `("overview", "insights")`" | `:314` (`:308` is `texts = finding_texts(...)`). |
| W5 | 04 P4 L264, W1-11 L755, plan P4 | `docs/agents/skill-and-profile-authoring.md:21` "Current code selects Head of ABM v58" | the sentence is at `:24`. |
| W6 | 03 §3.5.3 L615 | `arv2/text.py:44-78` | the file is 67 lines; `substring_verdict` = `:44-67`. |
| W7 | 03 §3.9 L911 | "`ready_person_jobs`'s guard pattern, `quality_person_release.py:94-96`" | the privacy guards are `:85-87`; `:94-96` are bind parameters. |
| W8 | 04 W2-16 L959 | "verifies each distinct `original_key` once (`:191-194` today runs per source)" | the per-source verify is `quality_evidence.py:204-206`; `:191-194` are `record_artifact`/`storage.put`. |
| W9 | 04 W3-22 L1295 | "DB: `tests/arv2/test_research_operations_db.py` — `find_sibling` finds…" (written as an existing file to extend) | does not exist; it is a new file. |
| W10 | 04 P5 L288 | "`NominateCommitteeTool` pins the person bundle with the parent's recipe (`quality_committee_tool.py:208-214`)" | `:213-218`. |
| W11 | 04 §10 L1703 | "`uv run alembic heads`, 291 files" | 292 files; head `4a94970221e9` ✓. |
| W12 | 04 W1-9 L686-687, W3-21 L1339-1341; plan L211 | buying role `influencer` | not a `Persona` value — `libs/clue-core/clue_core/enums.py:358-367` (`champion, economic_buyer, technical_evaluator, blocker, user`). |
| K1 | 04 W3-21 L1374; plan L210-212 | "A0 ≤ 60 s + pacing (5 role searches ≈ 52 s floor)" | `company_lock` is paced too (`account_research_tools.py:468-492` wraps every `ai_ark` hop) → six calls, 63 s (03 §3.2 is right). |
| K2 | 03 §3.2 L347-348, §6.1 L1195 | A0 enqueues the person jobs "in the same transaction's post-commit step" | the pre-step runs inside `ResearchUnitRuntime` (`quality_research_wiring.py:781-1140`), which has no queue; `fleet_main.py:790-792` composes it with `connections=transaction` only; the queue lives on the driver (`account_research_driver.py:2490`). 04's "the sweep offers within 10 s" is what the code allows. |
| K3 | 03 §3.5.6 L669-673 | the extractor call's request/response "envelope is the raw-response artifact of the call, bound through the operation's derivation like any other provider body" | with `call_provider("extract", hop)` and no operation (03a §8b, 04 W3-23) there is no `arv2_research_operation` row; `index_acquisition` **skips** `openrouter` rows (`quality_acquisition.py:53`), and `_drain` binds nothing to the subject. The raw artifact (which carries the request = the contact's quoted text, 02 §3.6) is an **unbound** artifact — a DSAR residue of the `[M10.5×M9.3]` class, not "like any other provider body". |
| K4 | 01b T11 L431-440 vs disk | nothing-lost fixtures for seven accounts | `.artifacts/arv2-research-runs-20261007/fixtures/nothing_lost/` holds six (`nyc.gov.json` absent); `chains/` holds seven. |

### 2.2 Verified correct (selection; the ones the design depends on)

| # | Doc | Claim | Checked at |
|---|---|---|---|
| V1 | 02 §3.3, 03 §3.3.6, 03a §5.2 | operation identity `uuid5("arv2-operation:v1:<ws>:<job>:<kind>:<sha(request)>")`, `ON CONFLICT DO NOTHING`, 2 h lease, `running` past lease → `unknown/dispatch_outcome_unknown`; `finish` fenced on `owner_token` and `state IN (running, unknown)`; `body()` refuses non-success | `research_operations.py:27-30, 57-100, 148-158, 170-206` |
| V2 | 02 §1.2, 03a §5.3 | `begin_job` claims `not_started\|suspended\|in_progress` and bumps `attempt`; `finish_job`/`suspend_job` `WHERE attempt=:attempt AND status='in_progress'` | `account_research_store.py:309-336, 339-406` |
| V3 | 02 §1.2/§3.16, 03a §6 | `_db_lock` one per handler; `_connection()` = `async with self._db_lock, self._conn_factory()`; `ToolRuntime(conn_factory=self._connection, pacing_conn_factory=self._conn_factory)` | `account_research_driver.py:504, 1016-1019, 1257-1271`; module docstring `:19-27` |
| V4 | 02 §2.3, 03a §2.3/§6, 04 W1-7 | `_perform_hop` holds `_semaphore(provider)` across the `to_thread` call **and** the `finally: _drain`; `_SERIAL_PROVIDERS={"ai_ark","media"}`; AI Ark pacing lock + `sleep(min_gap)` in `_hop`; `call_provider` shields the hop; `operate` = begin → call_provider → `recover_acquisitions` → `body` | `account_research_tools.py:216, 433-453, 462-492, 500-575, 596-687, 698-728` |
| V5 | 03a §2.1, 02 §5.6 | ladder `v25`/`v25-person` for `version >= 25` only for `ACCOUNT_RESEARCH`; `active_roles={ACCOUNT_RESEARCH}` for ≥ 20; `quality_tools` registers 28 classes + `AcquireResearchTool(make_default=True)`; `make_default=tool.version=="1"` | `quality_research_wiring.py:211-252, 255-260, 312-349` |
| V6 | 03a §2.1 | the v25 profile pins prompt sha `08bceab5…`, four skills, tools with input/output shas; `max_output_tokens 16384`, `max_plan_nodes 64`, `max_model_rounds 100` | `profiles/quality-account-research/v25/profile.yaml:1-30, 69, 99-101` |
| V7 | 02 §1.6, 03a §8f, 04 W1-8 | `ready_person_jobs` CASE at `:89-92` (recipe ≥ 18 ⇒ `EXISTS artifact_reference READY_KIND`); `mark_account_import_ready` writes the row for any subject ≥ 18 and the reference only for accounts | `quality_person_release.py:16-17, 29-63, 66-104` |
| V8 | 02 §1.6, 03a §5.6, 04 P1 | `_account_dossier_for_person` → `read_parent_dossier` when `parent_job_id`; raises when the parent has no import | `page_writer_runtime.py:405-416`; `quality_person_release.py:107-125` |
| V9 | 03a §5.5, 04 W1-3 | `check_finalizable` refuses while `unresolved_interaction_failures` exist; runs before the completion guard and the snapshot | `agent_execution_wiring.py:2096-2109`; `agent_runtime_wiring.py:1288-1294, 1351` |
| V10 | 03 §3.5.3, 04 W3-23, plan W3-23 | `substring_verdict` EXACT/PARTIAL; `normalize_for_match` blanks non-`[a-z0-9 ]` | `arv2/text.py:25-41, 44-67` |
| V11 | 03a §7.1/§2.3, 03 §3.9 | `quality_meter.usage` sums `provider_call_ledger phase='result'` by `entity_research_job_id` + `agent_model_call` via `arv2_quality_execution` + allowance counters | `quality_meter.py:38-66` |
| V12 | 02 §3.15, 03 §3.2 | `stop_contact_jobs` and the claim-writer block filter `profile_ref IN ('agent-profile:arv2-person:v2','…:v3')`; quality person jobs carry `…:v4` | `research_operations.py:292-293`; `claim_writer.py:142-146`; `quality_committee_tool.py:219` |
| V13 | 03a §2.1, 04 §0.2 | `validate_plan` refuses `tool_schema_mismatch` on either sha | `agent_execution_wiring.py:1420-1434` |
| V14 | 03a §2.1 | descriptor shas over both models; `model_description` outside the schema | `envelope.py:168-170, 350-352, 378-379` |
| V15 | 02 §2.2, 04 W1-2 | `Review` `extra=forbid`, status literal of 5, linkage validator; `Finding.claim_type` literal of 2; `Entry` id pattern; `EntryReview.contract` re-validates through `Review` | `dossier_findings.py:16-48`; `dossier_json.py:17-40` |
| V16 | 02 §2.2, 04 W1-2 | `SaveDossierSectionTool.apply` returns `{saved:false, error}` on `ValueError`, persists at `:261-267`; `_lock` advisory `research-dossier:{ws}:{job}`; `uses_json_dossier` ≥ 16; role check `account_research` | `quality_json_dossier.py:44-48, 152-159, 198, 224-274` |
| V17 | 02 §4, 04 W1-4 | `render_view` treats `limit<=0 or limit==2000` as unbounded; docstring claims deepagents supplies 2000; deepagents 0.6.12 default `limit=100` | `quality_workspace.py:43-55`; `.venv/…/deepagents/middleware/filesystem.py:257-258` |
| V18 | 02 §4, 04 W1-3 | `_passage` 256-char segments; operations view `kind LIKE 'quality_tool:%'`, role `account_research` only; `als` refuses all but `/`, `/dossier`; `agrep` refusal text | `quality_views.py:45-57, 214-237, 417-436`; `quality_workspace.py:131-136` |
| V19 | 02 §2.2, 04 W1-3 | `search_evidence@2` drops the ±160-char `context`; `SearchPathEvidenceInput.source_path` | `quality_tools.py:275-286, 357-384`; `quality_evidence.py:597-630` |
| V20 | 02 §1.4, 03a §8b, 04 W1-5 | `acquire@1`: validation → `reserve` → `operations.begin` → lost race replays → `tool.ainvoke` → result artifact + `agent_artifact_subject` + `research_tool_output` + derivation from every job source → operation update → receipt with `result_path` | `quality_provider_tools.py:124-324` |
| V21 | 04 §0.7, 03 §3.2 | `discover_people` refuses until `deep_attempted` (an `account_deep` row not `running`); `company_lock` follows | `committee_discovery.py:244-258`; `research_operations.py:209-220` |
| V22 | 03a §8a, 03 §3.2, 04 W3-21 | nominate body: job row `FOR NO KEY UPDATE`, `ensure_generation`, `quality_person_job_id`, `submit_proposal`, `link_selection_claim`, `save_person_brief` (first creation only), `create_job(... profile_sha256=bundle_pin(load_quality_resources("arv2-person", version=parent recipe)))`, `register_child` | `quality_committee_tool.py:87-101, 158-222` |
| V23 | 02 §1.6, 04 W1-10 | `pending_continuations` recipe ≥ 20 clause with the import-ready exception | `quality_generation.py:390-434` |
| V24 | 03a §1.1 | middleware order: `ToolRepairRounds`, `ExactAgentToolSurface`, `TurnBudget`, `*self._middleware`, summariser, `compact_tool`; `system_prompt=resolved_profile.prompt_body`; role passed to `_build_model`; `compaction_for(model_id)` in a thread | `runtime.py:606-623, 625-671` |
| V25 | 03a §4.3, 04 W1-6 | `IdentityLayerSource.load` emits the `system_prompt` as a `role="system"` candidate; continuation skips L1 (`emit`) | `context.py:275-299, 800-801, 899-900, 961-964` |
| V26 | 03a §4.1 | trigger/keep = window × fractions; fallback 170 000 / 6 messages; `trim_tokens_to_summarize=None`; `compact_conversation` with `system_prompt=None` | `compaction.py:54-56, 107-133` |
| V27 | 03a §4.2 | `ClearToolUsesEdit(trigger=100_000, clear_at_least=0, keep=3, clear_tool_inputs=False, exclude_tools=(), placeholder)`; `awrap_model_call` deep-copies and overrides the request only | `.venv/…/langchain/agents/middleware/context_editing.py:58-77, 257-292`; langchain 1.3.14, deepagents 0.6.12, langgraph 1.2.6 present |
| V28 | 03a §4.2 | summariser also fires on last reported usage | `…/summarization.py:596-603` |
| V29 | 03a §1.1 | `MAX_TOOL_REPAIR_ROUNDS=10`; counts batches whose `ToolMessage` JSON carries `governed_repair_budgeted: true` (state, not request) | `tool_recovery.py:12-62` |
| V30 | 03a §1.3 | `SPILL_THRESHOLD_BYTES=12 KiB`, `RECEIPT_REFERENCE_VALUES_MAX_BYTES=16 KiB`, `MAX_RUNTIME_MODEL_ROUNDS=500`, `operation_id_for_plan_node` | `clue_agents/execution.py:50-62, 144-156, 242-245` |
| V31 | 03a §1.2 | `invoker.invoke` opens `governed.<name>@<version>` (retriever for READ); journal COMPLETED → replayed; A9 key `execution:<id>:operation:<op>` | `invoker.py:176-215, 239-245, 273` |
| V32 | 03a §1.2 | `node_key = agent_<name>_<sha(tool_call_id)[:24]>`; `recover()` re-reads every receipt; READ tools refused only by `PreconditionFailed` are not budgeted | `agent_runtime_wiring.py:897-922, 978-997, 1004-1024` |
| V33 | 02 §5.1, 03a §2.2 | `<ROLE>_AGENT_MODEL` read at `registry.py:395`; effort at the gateway from `role`; `AgentRole` members | `registry.py:375-407`; `agent_model.py:1228-1232`; `contracts.py:220-236` |
| V34 | 02 §1.1, 04 P5 | launch reads `arv2_account_profile_sha256(version=catalog_version)`; `enqueue_launched_jobs` after commit; `quality_person_job_id`; typed refusal codes | `account_research_launch.py:134-151, 190-204, 469-508, 1174-1193` |
| V35 | 02 §1.1, 04 W1-11, P4 | the launch tool's description says to read `.deepagent/skills/account-research-briefing/v3/SKILL.md`; HoA v70 pins prompt v18 sha `3de3db26…`, skills stage0-interview v43, account-research-briefing v3, icp-authoring v3; `C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM]="v70"`; prompt v18 §"Account deep research" at `:86-95` | `account_research_launch.py:1319-1330`; `platform/agents/catalog/profiles/head-of-abm/v70/profile.yaml:1-20`; `agent_registry_wiring.py:257`; `shasum` of `prompts/head-of-abm/v18/SYSTEM.md` |
| V36 | 02 §1.5, 04 W1-13/W3-25 | `SECTIONS` 6/5/6; `GUIDE_VERSION="v1"`; `write_checked` one repair; `write_account_pages` fixed pages | `page_writer.py:38-65, 94-108, 200-237, 300-355` |
| V37 | 02 §1.5, 04 W1-13 | `render_findings` emits `Caveat:` lines and no interpretation; `finding_texts`; `WITHHELD_STATUSES={"wrong_entity"}` | `page_writer_view.py:19, 68-96` |
| V38 | 02 §3.12, 04 W1-13 | Miscellaneous dump from `uncovered_findings`; `context-only` `shared_from=("overview","watch-outs")`; the system-row upsert | `quality_pages.py:531-571`; `display/recipes.py:109-117, 314-334` |
| V39 | 04 §0.5 | frontend read serves `read_page` or an empty block and never falls through to Luna when a quality context exists | `frontend_read/display_pages.py:349-381` |
| V40 | 03a §5.6, 03 §3.8 | `_offer_display_page`: display kind, `reopen_terminal=True`, dedup `arv2-display-page:account:<id>:<page>`, called only from the legacy `_settle`; display handler → `ensure_page`; composed only with `CLUE_ARV2_DISPLAY_GENERATE_ON_READ` + OpenRouter key | `account_research_driver.py:2046-2095`; `display/fleet_handler.py:106-145, 213-226` |
| V41 | 02 §3.5, 04 W2-16/W2-19 | `prepare_source` identity, `record_artifact` → `put` → `retain` → verify original → derivation; `publish_sources` manifest `FOR UPDATE`; readers' availability filter; a person reads account-level sources | `quality_evidence.py:160-215, 240-263, 420-428, 444-460, 497-504, 540-565` |
| V42 | 03 §3.5.1, 04 W3-24 | `exa_source_texts` returns `text` + `highlights/<i>`; `index_acquisition` skips `openrouter`/`model` rows; `_index_receipts` reads the original per row | `quality_acquisition.py:29-56, 123-200, 269-281` |
| V43 | 03 §3.3.2-3.3.3, 02 §2.3 | `search_body` keys; `deep_reasoning_body` hard-codes `type="deep-reasoning"` and replaces `contents` when given; defaults `num_results` 8 / 40 / 20 | `exa_client.py:407-454, 520-541`; `account_research_tools.py:1008, 1086, 1103` |
| V44 | 03 §3.2 | `COMPANY_CREDITS_PER_RESULT` 0.1, `PERSON_CREDITS_PER_RESULT` 0.5, export estimate 0.5 + 0.5; `SENIORITY_VALUES`; `role_search_body` refuses unknown values; `export_email` on id or URL | `ai_ark_client.py:70-84, 259-275, 926-950` |
| V45 | 02 §2.3, 04 W1-14 | both brief modules read `provider-requests/*/v1/request-config.json` for `outputSchema`/`contents` only; `uses_person_exa_brief` ≥ 11, `uses_account_discovery` ≥ 12 | `person_exa_brief.py:11-55`; `account_exa_brief.py:11-55` |
| V46 | 02 §6, 04 W1-1/P5 | settings fields and defaults (`arv2_account_max_model_rounds` 350, `…_tool_calls_per_round` 50, `…_max_runtime_s` 0, `…_max_parallel_jobs` 4, `…_provider_concurrency` 4, `arv2_ai_ark_min_gap_s` 10.5, compaction fractions, `agent_model_context_windows` + `NoDecode` validator) and their `.env.example` lines | `settings.py:397-403, 447-459, 476-480, 698-702, 1166-1171`; `.env.example:20-22, 151-160, 181-194, 201-205, 217, 273-283, 317, 334, 366-425` |
| V47 | 03a L4-5 | "same code as `496956c98` for every file cited" | `git diff --stat 496956c98 HEAD` touches three docs only |
| V48 | 04 §8.3 | the five hard-coded tests (`== 25`, skill versions, `n + "@1"` allowlist, newest `recipe-v*.json`, `input_refs == CURRENT`) | `tests/arv2/test_quality_json_dossier.py:30, 40-52, 63-69, 86`; `test_quality_owned_narrative.py:64`; `test_account_research_port.py:26-27`; `test_quality_driver_db.py:155`; `test_quality_reconciliation_db.py:569` |
| V49 | 04 §0.1 | DB fixtures skip without `CLUE_DATABASE_URL`; `make db-smoke`; `testpaths` | `tests/claimstore/conftest.py:56-62`; `Makefile:94-97`; `pyproject.toml:136-137` |
| V50 | 04 W2-15 | the lock sites (job row `FOR NO KEY UPDATE`, manifest `FOR UPDATE`, `research-dossier`, `dossier-import`, `quality-proposal`) | `quality_committee_tool.py:93-96`; `quality_evidence.py:257-263`; `quality_json_dossier.py:152-159`; `dossier_import.py:164-167`; `quality_claims.py:205-208` |
| V51 | 04 W3-23 | the `structure_material` precedent: `openrouter_chat_request` → `ProviderCaller.call(CallSpec(provider="openrouter", …, cost_reader, halt_rule))` | `structuring_client.py:1187-1213` |
| V52 | 04 W1-1 | `tests/agents/test_compaction.py` harness; `build_compaction_middleware` seam | `test_compaction.py:23-48` |
| V53 | 02 §7.2, 04 W4 | the runtime image installs no ffmpeg; `ffprobe` shelled at `media_recording.py:103` | `docker/backend/Dockerfile:43-46`; `media_recording.py:99-108` |
| V54 | 02 §1.2, 04 W3-21 | `_run`: `begin_job` → `_compose` → `set_job_stage("deep_research")` → `_tool_runtime` → `async with self._jobs` → runner → `_write_pages` → `_settle_quality` | `account_research_driver.py:1159-1192` |
| V55 | 02 §1.5 | `_write_pages` gates on `writes_pages_separately`, `needs_review/page_writer_failed`; `_settle_quality` meter → coverage → finish → … → `ready_person_jobs` → `_offer_committee` after the block | `account_research_driver.py:1796-1831, 1833-1958` |
| V56 | 02 §1.2 | the handler composes only with the four keys + `ARV2_ACCOUNT_AGENT_MODEL`; `page_writer_models`; the queue | `account_research_driver.py:2436-2491` |

---

## 3. Rulings compliance

| Ruling | Honoured at | Not honoured / at risk |
|---|---|---|
| **No light/deep contact tiers; every contact full depth** | 03 §1 L24-25, §3.3.3 (same A2 for every contact), §3.6.1 (same judge budget 12/15 for every contact); 04 L12-13, W3-21 (every nominated contact gets a job), W3-22 `person_plan` | (a) **04 has no web-gap committee fill** (03 §3.2 failure row 4, App A.10): when AI Ark returns < 4 records, 04 researches fewer contacts — the ruling needs contacts to exist first. (b) D9 (12 × 4 k) is a founder decision, not a tier — fine, but 04 W1-14 applies it at r26 to today's agent as well; note it reduces per-contact acquired text 4× on v25-style runs before the extractor exists. (c) 01b §6: the output caps cut A-class items on the richest contacts (C22) — depth of *research* is kept, depth of the *served brief* is not; needs the ruling. |
| **Committee = top 4–5** | `committee_cap` default 5 (02 §1.1; 03 §3.1 L271; 04 W3-21 L1346); `MIN_COMMITTEE` 4 (03 §2.1; 04 `CLASS_MINIMUMS`); alternates beyond 5 are brief items, not jobs (03 §3.2; 04 W3-21) | 01b T8: FirstFleet carried 10 A-class committee items vs cap 8 — the cap is on brief items, not on contacts; consistent with the ruling. |
| **Account + contacts start together at approval; nothing waits on the account dossier except the contact page** | 03 §3.2 (jobs created at the end of A0 ≈ t+63 s, "no import gate"), §3.6.4 (contact waits ≤ 120 s on the account's first *pool*, never the dossier); 04 P1/W1-8 (release at nomination, r26), W3-21 (person jobs born at A0; wait on `research_candidates`, not the import); the contact page waits on `arv2_research_import_ready` in both | (a) 04's contact pre-step waits ≤ 240 s on the account's **final** pool (after A3 + gap), which 03 §5.6 places at ≈ t+200 s — a 3–4 min wait on every contact's critical path (C11). (b) 04 W1-8/W1-9 release r26 contacts before any account claim exists but leave `person_task_instruction(account_dossier_available=recipe>=18)` (`account_research_driver.py:1407-1410`) telling them the parent dossier is readable (Q9), and the v26-person prompt/skills still name `/research/parent-account-dossier.json` (02 §4) (Q41). |
| **The agent keeps its investigative follow-ups; the rule table is a floor; follow-ups cheap via candidate-returning tools** | 03 §3.4 ("the floor"), §3.6.2 (judge budget 30/15 ops, 20/12 rounds; `acquire@2` returns candidates), §4.5; 04 W3-22 (A3 ≤ 2 rounds), W3-24 step 2/3 (candidates from the tool, op budget as a refusal value); plan §2 C budgets match in both | (a) 03 §3.6.1 removes `research_deep` from the judge's operations — consistent with the plan's "search, fetch, AI Ark, ATS" list; record it as deliberate. (b) 04 W3-22 hard-codes 5 floor rules and a 7-kind closed set while 01b found 11 pairs with strict A-class yield in ≥ 2 accounts (C23) — the floor is thinner than the evidence. (c) **The judge's emission rounds eat the budget** (Q98): with one `save_dossier_section@2` per class (9 account / 8 contact classes) + validate + finish + `research.json` + finalize, a contact spends ≥ 12 of its 12 rounds emitting unless the prompt mandates one batched round. |
| **v26 is a new recipe/profile on the existing governed runtime, not a rewrite** | 03 §1.1 item 1, §3.6 ("nothing in the graph, the middleware order, checkpointing, `finalize_turn` or `recover()` changes"); 04 §11 (what is not changed) | Platform touches that are *not* rewrites but are A-owned and must be named as such: W1-6 (shared `clue_agents/context.py` + 4 composition roots, affects Head-of-ABM/onboarding/account-research-turn), W1-7 (`_perform_hop` split), W2-15 (`_db_lock` removal from tool transactions), W3-21 (`ResearchUnitRuntime.run` reorder, `prepare_authority` hoist), W3-26 (5 CHECK constraints), 03 §3.9 (`add_job_spend` store write; account-turn artifacts bound to contacts). None rewrites the toolbelt/journal/replay/DSAR paths. |
| **No mechanical word-counting of agent prose** | 03 L30, §2.1 ("presence check … not a word count"), §10 ("any count of words in prose" deliberately not added); 04 W3-25 "no word counts, 02 §10 item 11" | Borderline, acceptable: `CLUE_ARV2_V26_QUOTE_MAX_CHARS` 600 (a field bound on a verbatim quote), `QUOTE_ELISION_MIN_WORDS` 8 (plan AT-7's own rule). Acceptance metrics that count ("overview word count ≤ 60 %", "contact dossier findings ≤ 25" — 04 W1-13/W1-14) are replay measurements, not code gates; say so in 04. |
| **`.env.example` parity** | 03 §10 (every setting with its line); 04 §9 (every flag with owner and default); both state the rule | The two sheets disagree on names and defaults (C2, C18, C19, C26, C32) — parity cannot be met against two sheets. |
| **Alembic hash ids** | 04 §10 ("hash id from `uv run alembic revision -m`; one head; `make db-smoke`") | 03 §1.1 "No migration" (C35); 03's `person_research` role needs one. |

---

## 4. Executability of 04 — questions an implementer must ask

`B` = blocks coding of that item; otherwise a decision the implementer would otherwise make silently.

**W0**
- Q1. Which inputs: 01b's existing `fixtures/{chains,nothing_lost,rule_table.json}` or a re-mine with the new `scripts/arv2_v26_mine_runs.py` (which uses `substring_verdict` PARTIAL — a different method from 01b §1)? (C39)
- Q2. Where does the rule table live — inside the Python package (`clue_api/arv2/followup_rules.json`, the first JSON there; not scanned by `tests/arv2/test_import_guard.py`) or in the catalog, sha-pinned (03 §3.4)? (C23)
- Q3. The closed `lead_kind` set has 7 values; 01b's floor has 11 kinds and `AcquisitionName` has no `lookup_person`-by-name for `person-name` leads (seeded jobs refuse name search — `committee_discovery.py:697-710`). Which operation does a `person-name` lead issue on a contact job?
- Q4. Fallback pool build "under a replay workspace through `ToolRuntime.operate`": `operations.begin` is `INSERT … SELECT FROM arv2_research_job` — which run/job rows exist in the replay workspace, and who creates them (a launch on a throwaway DB? the production DB?).
- Q5. `nothing_lost/nyc.gov.json` is absent on disk (K4) — regenerate or drop nyc.gov from the manifest?
- Q6. `pool_sha256` over a directory — define the file order and what is hashed (bytes of `<operation_id>.json` sorted by id?).
- Q7. The replay runner/loader (pool → `ScriptedTransport` scripts keyed by request sha) is "L7's harness" (05, unwritten) but RC-1 is Friday of week 1 (§7.5). What is the interface the pools must satisfy?

**P1**
- Q8. `defers_contact_page` = recipe ≥ 26 and `catalog_version == "v4"` — gate on `writes_pages_separately(scope)` too (recipe ≥ 25 is implied by ≥ 26; fine) — state it.
- Q9. **B** `person_task_instruction(account_dossier_available=recipe>=18)` (`account_research_driver.py:1407-1410`) still tells an r26 contact its parent dossier is available; must become `18 <= recipe < 26` or the r26 person prompt must stop reading it.
- Q10. `_contact_page_continuation` calls `self._compose(conn, job)` — `_compose_quality` also issues the `UPDATE … quality_recipe_version` (`:1333-1344`) and `person_scope_for`; it runs today only after `begin_job`. Confirm it is safe on a terminal row (no `set_job_stage`).
- Q11. `self._page_writer is None` on the continuation → which `WorkResult`? (`_write_pages` returns `page_writer_not_composed`.)
- Q12. The continuation's dedup key includes `ready_version`; a parent revision (`import_revision`) bumps `dossier_version` → a second contact page task — intended (page follows the newest import) or not?
- Q13. `contact_pages_due` joins `display_block … (contact, subject_entity_id, 'contact')` "under the generation's `context_id`" — `display_block.context_id` ✓ exists (02 §3.12); state the join.

**P3 / P4 / P5**
- Q14. P3's `.env.example` comment-only change: the parity rule says the set `.env` value wins and the example follows; the batch-worker values 12/20 live in `/srv/clue/env` — who sets them and when (before W2-15 only)?
- Q15. P4 output "one line in `_memory/`" — the authoring doc line is `:24` (W5).
- Q16. P5: `recipe_version_for` refuses `> CURRENT_RECIPE_VERSION` → the r27 pilot requires `CURRENT_RECIPE_VERSION = 27` first, which flips every `== CURRENT` test (§8.3) and `expected_pin`'s scan — fine, but §9.2 of 03 (the rollout order) and 04 P5 must say "mint 27 → bump CURRENT → default 26 + pilot 27" in one place (04 L282-283 does; 03 §9.2 differs).

**W1-1**
- Q17. Which exclude list applies at r27 (C26)? As written, W3-24 inherits W1-1's list (acquire excluded) and 03 §5.3 shows the cap is then exceeded by round 9.
- Q18. Two per-role window settings coexist (`CLUE_ARV2_*_CONTEXT_WINDOW_TOKENS` 200 000 from W1-1; `CLUE_ARV2_JUDGE_*_CONTEXT_TOKENS` 60 000 from W3-24) — which wins at r27, and is the r27 trigger derived (cap − 10 000) or set?
- Q19. `tests/agents/test_context.py:128` asserts `len(first.messages) == 7`; W1-6 makes it 6 — update the assertion (04 says "messages[0] is the L7 human message" but not the count).

**W1-2**
- Q20. **B** `claim_type` gains `synthesis`/`not_found` on `FindingV2`, but the importer validates the stored dump with strict `Entry`/`Finding` (`claim_type: Literal["observation","reported_statement"]`, `dossier_findings.py:41`) → every r27 document with a synthesis item fails `parse_json_dossier` at import. Widen `Finding.claim_type` (shape change on `@1`? no — `Finding` is not a tool model) or import through `EntryV2`.
- Q21. `EntryReviewV2.defaulted` must survive `EntryReview.contract`'s round-trip through `Review` (`extra="forbid"`) — exclude it in that validation.
- Q22. The `normalized[].dropped_keys` list: `extra="ignore"` discards silently; the tool must validate with `extra="allow"` first to know what it dropped — say so.
- Q23. **B** `claim_kind="inference"` for synthesis (L416): is `inference` a value the claim writer / `FindingProposal.claim_kind` accepts today (`dossier_import.py:71` uses `attributed_statement`/… )? If not, W1-2 adds a claim-kind value with no definition of how `eligible_sql` treats it.

**W1-3**
- Q24. `SearchEvidenceOutput3` with `source_id: UUID | None` changes the output sha → `search_evidence@3` ✓; but the `@2` path must stay registered for r25 replay — confirm `quality_tools` keeps both (it does by class list) — state the class name registered.
- Q25. `als("/operations")` lists `kind LIKE 'quality_tool:%'` only — r27 pre-step operations (`account_search`, `v26_followup:*`) are invisible to `ls`; intended?

**W1-4**
- Q26. **B** How does `CLUE_ARV2_VIEW_FORMAT`/`MAX_CHARS` reach `render_view` (module function) and `ResearchViewMount` (constructed in `research_backend(...)` without settings)? Constructor plumbing is unspecified.
- Q27. `limit in (100, 2000)` makes an explicit `limit=100` serve the whole document — intended? (A model asking for 100 lines gets 80 000 chars.)
- Q28. The continuation path `/research/operations/<id>/<N>.json` reuses the `_OPERATION` offset slot as a *character* offset while today's `N` is also a character offset (`_passage(start)`) — consistent; say so, since `/evidence/<name>.json` has no offset form.

**W1-5**
- Q29. `Candidate.cls` serialised as `class` on a strict `ToolOutput`: `validate_tool_result` validates the JSON-mode dump against `output_model` — an alias needs `populate_by_name`/`by_alias` handling; specify.
- Q30. **B** `outcome: {provider, kind, result_count, http_status}` and `ledger: {operation_id, kind, dropped}` as nested dicts on a `strict=True, extra="forbid"` model — declare nested `ToolOutput` models (names) or `dict[str, JsonValue]`.
- Q31. `@2` is built "beside `@1` with the same `acquisition_runtime`" — `quality_tools()` registers `AcquireResearchTool(acquisition_runtime)` by instance; the runtime's writer replacement at `qrw:522-532` keys `tools.get("acquire_research_evidence","1")` — the loop over versions must also cover the `research_backend(capabilities=…)` lookup at `:740`. State both.

**W1-6**
- Q32. Four composition roots, not two (W3) — do `account_research_turn_wiring.py:829` and `onboarding_synthesis_wiring.py:512` take the switch?

**W1-7**
- Q33. `_dispatch` must keep the `job_available` refusal and the halt latch inside the semaphore block and still land (`_land` in `finally`) — the pseudo-code says so; confirm `result=None` on refusal paths feeds `semantic_empty=False`.
- Q34. For `ai_ark`, `asyncio.gather(sleep(gap), _land)` runs `_land` under the pacing lock's `pacing_conn` transaction while `_drain` opens `self._conn_factory()` (the `_db_lock`ed driver connection) — no deadlock, but the AI Ark lock is now held through a `_db_lock` wait; acceptable?

**W1-8 / W1-9**
- Q35. **B** A privacy-stopped r26 child never gets `terminal_status` (`status` `failed` is not in the job CHECK, 02 §3.2) → W1-10's "no child without `terminal_status`" never becomes true → the account refresh never fires. Define the terminal predicate for stopped children.
- Q36. W1-9 step 2 tells the r26 agent to call `lookup_company` then `discover_people` per role with `size: 5` — but `discover_people` requires `rationale`, `evidence_refs`, `role_key`, titles; the prompt must name the titles source (W3-21's `ROLE_TITLE_TEMPLATES` do not exist at r26).
- Q37. The r26 person prompt/skills (W1-14 item 5, W1-9 step 3) must drop `/research/parent-account-dossier.json` (02 §4) — not stated.

**W1-10**
- Q38. The skip compares `page_inputs(...).sha256` with the live block's `dependency_manifest`. What is in `page_inputs.sha256` (`quality_page_inputs.py:53-114`)? If it includes the generation's `input_revision`, every child result changes it and the skip never fires.

**W1-11**
- Q39. `platform/agents/catalog/manual/tool_notes.yaml` names `account-research-briefing` (verified) → `make manual-check` fails unless the manual is re-minted; the registry comment (`agent_registry_wiring.py:252-256`) says the conversation recipe "pins exact addresses" and moved 32 → 33 on the last HoA mint — does v71 need a recipe bump and a manual version? Not in §8.
- Q40. `agent_registry_wiring.py` references `account-research-briefing` (grep hit) — for what (a required-skill check that would refuse v71 at boot)?

**W1-12**
- Q41. `tests/arv2/test_quality_media_db.py:40` "runs with the setting true (fixture override)" — `Settings` is frozen (`settings.py:146`); the override mechanism (monkeypatch env + `Settings(_env_file=None)`?) is unspecified.

**W1-13**
- Q42. (d) is a reversal of a ruling — founder decision, not an implementer's (C29).
- Q43. `GUIDE_VERSION` from `settings.arv2_page_guide_version`: `page_writer.py` has no settings import; `guide()` and `_guides_sha()` (`page_writer_runtime.py:179-181`) read the module constant — plumbing unspecified.

**W1-14**
- Q44. `person_exa_arguments`/`person_search_contents` take no scope or settings (`person_exa_brief.py:24-55`) — the "for recipe ≥ 26" cap application needs both threaded from `account_research_tools.py:1389, 1428, 2019`; specify the signature change.
- Q45. Who writes the content of the eight new skill/prompt/provider-request folders (L) and by when — §7.5 gives Wednesday; the rubric harness (≥ 70 % A/B) is 05's.

**W2**
- Q46. W2-16: `DrainReport` is a frozen dataclass in `libs/clue-spend` (A) — `raw_bodies: Mapping[str, bytes]` keeps every raw body in memory until the drain returns; bound?
- Q47. W2-15: `_job_connections` replaces `conn_factory` for the `ToolRuntime` and the page writer, but `operations.begin`/`finish`/`body` and `_drain` all open their own connections — with `arv2_job_max_db_connections=2` and `_drain` + `index_acquisition` + `body` in sequence this is fine; with `asyncio.gather` over a plan of 10 operations (W3-22) each `_drain` needs a connection → the per-job semaphore of 2 serialises the batch's drains. Intended?
- Q48. W2-19 downgrade "refuse while any row has `artifact_key IS NULL`" — on a `make db-smoke` run (up → down → up) on a throwaway DB there are no rows; fine. State that production downgrade requires a materialise-all script (none specified).

**W3-26**
- Q49. **B** The migration must widen five constraints (W2): `agent_turn_role`, `agent_plan_role`, `agent_delegation_roles`, `agent_model_call_role`, `quality_execution_role` (root predicate). Copy exact bodies.
- Q50. `AgentRole.CONTACT_RESEARCH` absent from `C6_ACTIVE_PROFILE_VERSIONS` — confirm `build_agent_profile_registry` tolerates an inactive member (it does for `RESEARCH_CLAIMS`); state it.

**W3-23**
- Q51. **B** Quote rule: `quote_verdict` "keeps punctuation" vs `substring_verdict` (C20) — which?
- Q52. The hop must build the OpenRouter request with a key/base URL — from `_LiveClients.openrouter_api_key`/`openrouter_base_url` (`account_research_driver.py:2471-2475`)? The `ToolRuntime.clients` attribute to read is unnamed.
- Q53. `finding_proposal` "marks such findings `outreach_safe=False`" — `FindingProposal` has no such field in `dossier_import.py:41-72`; which marker carries it (`write_markers`? `claim.outreach_safe` column exists, 02 §3.9)?
- Q54. The `replay` pytest marker must be registered (pyproject `markers`) or `make check` warns/fails — unspecified.
- Q55. DSAR: the extractor's raw request/response artifact is unbound (K3) — bind it (`agent_artifact_subject` + derivation to the pool) or strip the request from the envelope.

**W3-22**
- Q56. **B** Template vocabulary: the eight account searches need `{seats}`, `{category_tools}`, `{problem_terms}`, `{icp_terms}` and the charter needs `{{seller_pitch}}`, `{{icp_summary}}`, `{{product_names}}` — 04 has no A0.0 compile (03 §3.2) and the personas are prose with no title list (`quality_context.py:355-360`); where do the values come from?
- Q57. `followups(candidates, issued)` matches triggers on `Candidate.finding` tokens — 03 §3.4 adds `attribute` and `ledger` trigger kinds (ATS empty ⇒ hiring search) — in or out?
- Q58. AT-2's committee gap round: searches only, or nominate through `NominateBriefedWebCommitteeTool`'s body as 03 §3.2 (needed for "every contact full research" on thin AI Ark coverage)?

**W3-21**
- Q59. `prepare_authority(execution)` before the request exists needs `role` — from `resolved.profile.role` (fine) — and `bind_execution` needs `self.limits` (built in `build_quality_job_runner` before `run`) ✓; state it.
- Q60. `rank_candidates` score (role-fit rank × 3 + seniority × 2 + footprint × 1) differs from 03's (`role_fit 1.0/0.5`, seniority map, `3·role_fit + 2·seniority + footprint`) — one formula, unit-tested with the same fixture.
- Q61. Person jobs "born `not_started`; W1-8's sweep offers them within 10 s" — the sweep runs on every worker; the parent's `_settle_quality` also calls `ready_person_jobs` — fine; but the nominate body's `FOR NO KEY UPDATE` on the parent job row from inside the pre-step holds the lock for the whole A0 (6 × 10.5 s)? Specify per-contact transactions.

**W3-24**
- Q62. **B** Where do 03 §3.7's server-side derivations live (C4)?
- Q63. **B** Emission rounds vs budget (rulings §3): mandate one batched round for all class sections, or raise the contact cap.
- Q64. The pool rides the task artifact as `"candidates": <pool JSON>` and becomes the L7 `HumanMessage(content=candidate.body)` — the body is the JSON dump of the whole task artifact (`qrw:867-879`); the L7 then embeds JSON-in-JSON (the thing W1-4 removes from views). Render the pool as a text block instead?
- Q65. The L5 `ContextCandidate(materialized_path="inputs/candidates-<kind>.json")` — which layer source emits it (`_Contexts.assemble` uses `_PinnedContextOnly()` for cards/memory; L5 is which `ContextLayer` member)? Name the source class.
- Q66. **B** The r27 prompt's finish sequence names `save_dossier_section@2 … → finish_dossier → /outputs/research.json → finalize_turn`; the `completion_guard` builds `research.json` from storage (`qrw:1013-1062`) — does the judge still write `/outputs/research.json` itself (v25 does)? Say which.

**W3-25**
- Q67. Class map (C30).
- Q68. `rewrite_account_pages` r27 "only sections whose slice sha changed" stores `section_inputs` in the writer artifact — but the first write's artifact must also store them; state it for `write_job_pages`.

**§7 / §8**
- Q69. **B** `test_skill_references.py:42-80` asserts byte-equivalence of the v21 and v20 prompts with one path substituted; a "(26, 25) pair" cannot use that assertion because W1-9/W1-14 rewrite the prompt. Define the new assertion (every `{{skills.*}}` renders; every mounted path exists).
- Q70. §7.1's "never touch the same file" is false for W1-3/W1-4 and W1-5/W1-12 (C40) — integration order for those pairs.

---

## 5. Missing pieces

| # | What | Where it is mentioned | Where it should land |
|---|---|---|---|
| M1 | **The `profile_ref` v4 privacy-stop fix** (`stop_contact_jobs` and the claim-writer block filter `…:v2/:v3` only — V12) | 03 §3.2 L383-387 "A-owned, blocking for v26"; 02 §3.15 | 04 has no item. Add **P6** (A, S): add `'agent-profile:arv2-person:v4'` to both filters; DB test: a privacy-stop on a v4 person job sets `input_refs.privacy_stopped` and the claim writer refuses. Blocks 03 §3.9 and every DSAR row. |
| M2 | **Person compliance floor at import** | 03 §2.5; plan §0 item 26 | 04 §11 refuses it (C33). A founder decision row + an r27 item. |
| M3 | **A0.0 context compile** (role titles per persona, Exa template vocabulary, with `DEFAULT_ROLE_TITLES` fallback) | 03 §3.2, App A.1 | 04 has `ROLE_TITLE_TEMPLATES` data + optional persona frontmatter only; the eight account templates have no vocabulary source (Q56). Add to W3-21/W3-22. |
| M4 | **Web-gap committee fill** when AI Ark yields < 4 | 03 §3.2 failure row, App A.10 | absent from 04 (rulings §3). Add to W3-22 gap round. |
| M5 | **Account judge ← people slice** with a bounded wait; the first-pool marker for contacts | 03 §3.6.4, §4.3 | 04 W3-21/W3-24 (C11, C12). |
| M6 | **`follows` on the ledger + the trailer** (minimums before/after, budget) | 03 §4.2 | 04 W3-22 (C34); AT-9 depends on it. |
| M7 | **Stage progress** (`input_refs.v26_stage` and the card mapping onto `research_progress.py:161-164` fractions) | 03 §6.1 | 04 silent; without it the progress card reads "researching 0.0" for the whole pre-step. |
| M8 | **Observability**: `arv2.v26.*` spans and attributes, the metric set, `CLUE_RELEASE` set by `deploy/vm/deploy.sh`, trace tags `account:<domain>`/`job:<id>` (02 §8.1 records both absent on v4) | 03 §8 | 04 has only W2-20. Add an item (A/L split) — the replay gate dashboards (03 §8.4) read these. |
| M9 | **Langfuse 100 MB trace cap** | plan §8 "unaddressed"; 03a §3.4 (per-job traces since R3) | nothing measures per-job trace size; add an RC-1 acceptance "max trace bytes per job" and a note that the pre-step's ~100 provider spans are 8 k-masked. |
| M10 | **The production DB queries** (01 §7: provider spend per run, job rows/outcomes, rewrite ownership, evidence volume, model-call cross-check, page bodies, Deepgram rows/`which ffprobe`) | 01 §7; plan D6 | no owner, no date. Add to W0 (A, day 1): queries 1, 2, 5, 7 settle D8 (deep-report price), the live fleet values and the ffprobe fact; needed before P3/W2-20 numbers mean anything. |
| M11 | **Fleet env verification** (`/srv/clue/env`: `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS`, `CLUE_FLEET_WORKER_CONCURRENCY`, `CLUE_DB_POOL_SIZE`, `CLUE_DEEPGRAM_API_KEY`, `CLUE_RELEASE`) and the production code version on 10-06 (01 §1.1 "not visible") | plan §8; 01 §1.1; 04 P3 (values "untracked") | one checklist line in P3/P4 with `deploy/check_prod_env.py` output pasted into `_memory/`. |
| M12 | **Replay runner / pool loader interface** | 04 §7.3 "L7's harness owns the runner"; 05 unwritten | 04 must state what the pools must provide (request-sha-keyed `ScriptedTransport` scripts, the job/run rows a replay needs — Q4, Q7), or RC-1 on day 5 is unexecutable. |
| M13 | **Head-of-ABM v71 re-mint procedure** (manual `tool_notes.yaml`, conversation recipe pin precedent, `make manual-check`) | 04 W1-11 (one line), §8 (research mints only) | §8 gains an HoA column or W1-11 gains the steps (Q39-Q40). |
| M14 | **Persona vocabulary** (`user`, not `influencer`) and the 63 s A0 floor | 03 §3.2 | 04 W1-9, W3-21; plan §2 footnote (W12, K1). |
| M15 | **DSAR binding of pre-step and extractor artifacts** (the extractor's raw envelope; the account turn's L7/model-input artifacts bound to every committee contact — 03 §3.9 row 4 "A-owned change") | 03 §3.9; 03a §7.3 | 04 silent (K3, Q55). |
| M16 | **Two markers / wait semantics** | 03 §3.5.5 | 04 W3-21 (C9, C11). |
| M17 | **Gap-round and follow-up caps as settings** (`GAP_OPS_PER_CLASS`, `FOLLOWUP_OPS_PER_ROUND_*`, `EXTRACT_DEEP_RESULT_TEXT`, extractor bounds) | 03 §10 C4-C6 | 04 §9 (C19, C24, C25). |
| M18 | **`CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` 4 → 6 after W2-20 reads ~0** | 03 §6.2, §10 C9 | 04 W2-15 acceptance or P3. |
| M19 | **A decision register for the items the set re-opens**: caps (C22), `context-only` (C29), the floor (C33), D4 pick (C18), D6, the brief emission path (C4) | 06 (unwritten) | the founder reads 06 before 04 is handed over; 04 §0 "six decisions it makes once" should list the ones it *cannot* make. |

---

## 6. Verdict

**Not ready to hand to Aryan.** The evidence (01, 01b, 02, 03a) is sound and the plan's intent is
honoured by both forward documents, but 03 and 04 specify two different builds, and 04 — the
document an engineer would code from — still has 13 blocking questions (the **B** rows of §4: Q9,
Q20, Q23, Q26, Q30, Q35, Q49, Q51, Q56, Q62, Q63, Q66, Q69) and omits the privacy-stop fix the
design's DSAR table depends on. The minimal edits that make the set
hand-over-able, in order:

1. **04 §0.2 + 03 §1.1/§3.6.1/§9.1/§10** — one recipe numbering (adopt 04's 26/27); global edit of
   03's "≥ 26" pipeline gates to "≥ 27" (C1). *A/L: synthesis, 1 h.*
2. **04 W3-24 ↔ 03 §3.6.1/§3.7** — one judge tool surface; add 03 §3.7's nine server-side
   defaults to 04 as a concrete item (`FinishDossierTool` r27 branch or `submit_brief@1`); widen
   `Finding.claim_type` (Q20); define `claim_kind` for synthesis (Q23); mandate one batched emission
   round (Q63); state who writes `/outputs/research.json` (Q66). (C4)
3. **04 W3-21 ↔ 03 §3.6.4/§4.3** — two markers; contact waits on the account's first pool (120 s);
   account pre-step waits for the children's final pools and embeds the people slice; AT-8 tests the
   candidates, not the key (C9, C11, C12).
4. **04 W0 + W3-22 ↔ 01b §3/§8 + 03 §3.4** — consume 01b's fixtures; rule table in the catalog with
   03's shape and 01b's eleven floor pairs; `follows` + trailer on the ledger; per-round caps; the
   template vocabulary source (A0.0 compile) and the web-gap fill (C23, C24, C25, C34, M3, M4, Q56).
5. **04 W3-26** — the migration widens `agent_turn_role`, `agent_plan_role`, `agent_delegation_roles`,
   `agent_model_call_role` and the `quality_execution_role` root predicate; delete the "no CHECK"
   sentence; 03 drops "No migration" and renames `person_research` → `contact_research` (W1, W2,
   C3, C35).
6. **04 W3-23 ↔ 03 §3.5.3 + 01b §5** — quote rule = `substring_verdict` EXACT per span + 01b's
   `\n` and digit rules; one extractor-bounds table with 04's names and 03's per-process semaphore;
   D4 default policy; bind the extractor artifact (C18, C19, C20, K3).
7. **04 W1-1/W3-24 ↔ 03 §5.3** — r27 clearing: trigger 45 000/42 000, keep 4, `acquire@2` NOT
   excluded; one window setting family (C26, Q17, Q18).
8. **04** — add P6 (profile_ref v4 fix, M1); fix `person_task_instruction` and the person
   prompt's parent-dossier reads for r26 (Q9, Q37); the privacy-stopped-child terminal predicate
   (Q35); `CLUE_ARV2_VIEW_FORMAT` plumbing (Q26); nested receipt models (Q29, Q30); the HoA
   assembler root and the four roots (W3, Q32); `page_writer.py:314` (W4); `:24` (W5); the
   `test_skill_references` assertion (Q69); §7.1's branch pairs (C40); persona `user` and the 63 s
   floor (W12, K1); credits 17.6 and ceiling $9/$7.7 in acceptance lines (C15, C16).
9. **04 §9 ↔ 03 §10** — one parameter sheet: 04's names, 03's rows where 04 is silent (gap/follow-up
   caps, `EXTRACT_DEEP_RESULT_TEXT`, waits, L7 bounds, metrics flag); mark D4/D8/D9 rows; note
   D8 is already pinned by `exa_client.py:523`.
10. **03 §3.8/§6.1/App A.6 + 03a §8f** — the contact page is 04's research-kind continuation; 03 §3.2
    nomination enqueue → the sweep (C28, C38, K2).
11. **06 (decision register)** — caps per 01b (C22), `context-only` (C29), the floor (C33), D4, D6,
    emission path (C4), with the default each document carries until ruled.
12. **01b** — add the `nyc.gov` nothing-lost fixture (K4); `…` → `[…]` (C21).

With 1–10 applied, 04 reads as one build, the citations an implementer would follow are right,
and every remaining question is a founder decision recorded in 06 rather than a silent choice.

---

## Re-check (post-reconciliation)

**Scope.** Re-ran §1 (contradiction sweep) and §4 (executability) over the current
`00, 01, 01b, 02, 03a, 03, 04, 05, 06` and `RECONCILIATION-RULINGS.md` (R1–R20), and verified
that the §2 fixes landed. Same checkout (`fa4bed77b`); every line number below is the working-tree
line at re-check time. Coordinator's adjudication request (per-round follow-up caps) is answered
first.

### Adjudication: per-round follow-up caps = 11 / 8

Canonical value **11 account / 8 contact** (01b T1 per-run maxima 21/14 over ≤ 2 rounds, + 1 per
round). Current state: **no document still says 8/4** — 03 §3.4 L653, 03 §10 C5 L1791-1792,
03 App C L1960, 04 W3-22 L1076-1077 and L1090, 04 §9 L1514 all carry 11/8, and 05 §3 AT-3 (d) and
§3.1 read the setting. Lines that must change: **none**. One wording residue to keep consistent
with the value: 03 §3.4's example rule (L608) shows `"max_per_round": 4` — that is a per-rule cap,
not the per-round setting; add "(per rule; the per-round cut is `…_OPS_PER_ROUND_*`)" so a reader
does not take 4 for the old contact value.

### Did the §2 citation fixes land? Yes, all 12 + 4

Verified by grep over the set: no residue of `text.py:44-78` (03 now `:44-67`), of
`quality_person_release.py:94-96` (03 §3.9 now `:85-87`), of `page_writer.py:308` (04 now `:314`),
of `skill-and-profile-authoring.md:21` (04 now `:24`), of `quality_evidence.py:191-194` (04 now
`:204-206`), of "291 files", of `influencer` as a persona (04 L636 "never `influencer`"), of
`agent_turn_wiring.py` as the Head-of-ABM assembler root (04 W1-6 L554-556 names the four real
roots), of "`agent_model_call.role` has no CHECK" (04 W3-26 L938-947 names all five constraints and
calls the old sentence wrong); 02 §3.8 L763-780 now enumerates the six role predicates; 03a §5.4/§7.3
and §8a/§8b carry the sweep-enqueue and the unbound-envelope corrections (03a L16, L722, L779,
L807); 03 §3.2 L368 and 04 W3-21 L1150-1151 say 63 s and 17.6 credits; the `nyc.gov` nothing-lost
fixture is on disk (K4 closed).

### Remaining contradictions: 26 (8 are name/shape splits that would put Aryan's code and 05's gate at odds)

| # | Topic | Where they disagree | One-line fix (winner) |
|---|---|---|---|
| R-1 | **Marker kinds and pool media type** | 03 §3 L283-284, §3.5.5 L771-776, §6.3 L1508-1510: `research_compile`, `research_committee`, `research_candidates_first` (first) / `research_candidates` (final), `application/vnd.clue.research-candidates+json`; 04 W3-21 L1127-1131, L1139, L1167, L1170: `research_v26_compile`, `research_v26_committee`, `research_v26_candidates` (first) / `research_v26_pool_final` (final), `…research-v26-pool+json`; 05 L59, L304, L481 use 03's names but L59 says 03 uses the old ones | 03's names (05 already keys on them); 04 W3-21 and its tests → 03's; 05 L59 drop the parenthetical |
| R-2 | Materialised pool path | 03 §4.3 L1183, L1191 and 03a §8c L849-865 `inputs/candidates-<kind>.json`; 04 W3-24 L1210, L1295 `inputs/pool-<subject>.json`; 05 L798 `inputs/pool-*.json` | `inputs/candidates-<kind>.json` (03/03a); 04 L1210/L1295 and 05 L798 |
| R-3 | **The candidates view** | 03 §3.6.1 L831, §3.6.2 L847-850, §5.3 L1264-1265: no new view — `/research/operations/<id>/0.json` is *rendered* as the candidates block; the clearing placeholder names `0.json`; 04 W1-4 L475-479, W1-5 L522-523, W1-1 L341, W3-24 L1244 and 05 L798: a new `/research/operations/<id>/candidates.json`, `0.json` refused for r27 judges | 04/05 (a refusal on `0.json` makes the raw-reads cap measurable); 03 §3.6.1/§3.6.2/§5.3 adopt `candidates.json` |
| R-4 | `CLUE_ARV2_V26_RECEIPT_CANDIDATES_MAX` | 03 §3.6.2 L847, §10 L1831: **20**; 04 W1-5 L525-526, W3-24 L1244, L1281, §9 L1516: **24** | 20 (03 §5.2's receipt arithmetic uses 20); 04's four sites |
| R-5 | **Media switch name — swapped** | 03 §7 L1536-1537, L1545, §10 L1739 `CLUE_ARV2_MEDIA_ENABLED` "(04 W1-12's name)"; 04 W1-12 L721-729, L738, W4 L1364, L1384, §9 L1505 `CLUE_ARV2_V26_MEDIA_ENABLED` "(03's)" | it gates every recipe → `CLUE_ARV2_MEDIA_ENABLED` per 04 §0.8's own rule; 04's six sites |
| R-6 | **Extractor model default** | 03 §3.5.2 L685-688, §10 L1801: `google/gemini-3.8-flash` default; 00 L26, L114 "Flash extractor, the default"; 04 §0.6 L82-83, W3-23 L978-979, §9 L1515: blank + refuse `extractor_model_unset` "(03 §3.5.2, R7)"; 06 D4 L40 "Luna or Flash" | Flash default (03/00; parity needs a value); 04's three sites; 06 D4 default → "Flash (Luna if the one-time AT-1 comparison, 03 §3.5.2, prefers it)" |
| R-7 | **`entities[].kind` enum — final at the r26 mint (R13)** | 03 §4.1 L1127-1128: 10 kinds (`… prior_employer, subject_site_page, title`); 04 W1-5 L511-512, W3-23 L991-992: 8 kinds (`… phrase, employer`); 03 §3.4 rows 5, 7, 8 trigger on `entity:subject_site_page` / `entity:prior_employer` | 03's 10 (three floor rows need them); 04 L511-512, L991-992 |
| R-8 | Candidate id address | 03 §4.1 L1120 `sha256(class ‖ url ‖ normalize(quote\|raw))` "(04 W1-5's address)"; 04 W1-5 L501 `sha256(source_id ‖ class ‖ …)` | 03's (the same quote from two operations is one id — the sibling rule and AT-9 rely on it); 04 L501 |
| R-9 | **`Finding.claim_type` widened on `Finding` itself** | 03 §2.2 L159-162, §4.6 L1214-1216, App B L1948: yes; 04 W1-2 L377-380: **no** (it would move `save_dossier_section@1`'s input sha and every v16–v25 pin; `FindingV2`/`EntryV2` + importer `entry_model`) | 04 (code reason); 03's three sites |
| R-10 | **Failed section at publish** | 03 §3.8 L1048-1050: the page is **not** published (one transaction); 04 W3-25 L1319-1322: the failed section is withheld, the rest publish | 03 (never a partial page is the reason the transaction is one); 04 L1319-1322 |
| R-11 | `CLUE_ARV2_V26_ACCOUNT_REFRESH_SECTIONS` | 03 §10 L1866-1870: deliberately absent; 04 W3-25 L1329-1330, §9 L1517: present | drop it (04) |
| R-12 | Two setting names | 03 §10 L1769 `…_ACCOUNT_SITE_PAGES_MAX`, L1776 `…_PERSON_POST_PAGES_MAX`; 04 W3-22 L1086-1087, §9 L1513, L1524 `…_ACCOUNT_SITE_FETCH_MAX` / `…_PERSON_POST_FETCH_MAX` | 03's names (R7); 04's three sites |
| R-13 | **Two sheets (R7 not yet met)** | 03 §10 lacks `CLUE_ARV2_V26_ACQUISITION_PLAN_ENABLED` (04 L1084), the W1/W2 flags (04 §9 L1506-1508) and `CLUE_ARV2_V26_AS_OF_DATE` (05 L255, L1078); 04 §9 lacks `…_EXTRACT_MAX_CALLS_ACCOUNT/PERSON` (03 L705, L1810), `…_EXTRACT_MIN_CHUNK_CHARS` (03 L756, L1808), `…_MODEL_RETRY_DELAY_S` (03 L917, L1829), `…_AS_OF_DATE`; 05's gate refuses a run whose `settings_in_force` differs from 03 §10 (L431-433) | 03 §10 gains the five rows; 04 §9 regenerated from it in one pass |
| R-14 | **Model-failure terminal state** | 03 §3.6.5 L917: `suspend_job` + `available_at`, resume from checkpoint (claimable); 04 W3-24 L1259-1262: "lands `needs_review/model_unavailable` and is suspended for retry" — `needs_review` is not claimable (03 §6.3 L1526); 05 §4.5(b) L841, §6.1 item 11 L945 `needs_review/model_unavailable` | 03's; 04/05 either drop the code or define it as the state after the retry budget is exhausted |
| R-15 | **Where R16(b) is implemented (also a wrong code claim)** | 03 §10 C7 L1828 and 04 W3-24 L1258-1259 name `quality_research_wiring.py:785-794` as the research model's build site — it only overrides `model_id`; the chain is read by `GovernedAgentChatModel` from `GatewayConfig.fallback_models` (`agent_model.py:1047`; `clue_config/gateway.py:100, 182, 191`), the provider is built once by `build_agent_model_provider(config)` (`agent_model_wiring.py:13`) and `AgentModelProvider.build(model_id, …, role)` (`clue_agents/ports.py:200-208`) has no fallback parameter | W3-24 item 7 becomes an A change in `agent_model_wiring.py` / `ports.py` (a `fallback_models` override on `build`, or a role→chain map); 03 §10 "where read" follows |
| R-16 | Rule-table row shape and row count | 03 §3.4 L601-620: `operations[]`, trigger kinds `entity \| class_terms \| attribute \| ledger \| result`, 11 rows only (L646-647: one-account pairs "are not rows"); 04 W0 L127: `operation` singular, kinds `class+any_of`, `class+attribute`, `ledger`, `entity`, no `result`, **plus seven agent-option rows**; 04 W3-22 L1070-1073 | 03's shape and 11 rows; 04 W0 L127, W3-22 L1070-1073 |
| R-17 | r27 account profile skills | 03 §3.6.1 L827 pins `person-research-briefing/v5` on the account profile; 04 W3-24 L1270-1272, §8.1 L1464 do not | drop it (A0 nominates in code with a template brief, 03 §3.2 L387); 03 L827 |
| R-18 | **Stale numbers** | 04 W3-24 L1300 "modeled ceiling ≈ $9.0 / $7.7"; 05 L546, L1004 "$9.0 / $7.7"; 05 L547 "ceiling $2.48 + $0.25"; 05 L601 "275 operations"; 05 L922 "providers ≤ $2.73"; 05 L561, L607 "≈ $21 Flash"; 00 L26-27, L114 "~11 credits" | 03 §5.5's: $9.4 / $8.1; $3.16 + $0.25; 351; ≤ $3.41 (+$3.00 D8); ≈ $22.7–25.8 (or "see 03 §5.5"); 17.6 credits |
| R-19 | Who offers the contact jobs | 05 §4.1 L551 "A0 enqueues in the same post-commit step, 03 §3.2" | the sweep, ≤ 10 s (03 §3.2 L390-399; 04 W3-21 L1160-1163); 05 L551 |
| R-20 | AT-9 gating lines | 05 §3 AT-9 L482: floor 1.0 gating **and** chain recall ≥ 0.90 per account gating **and** judge-only ≥ 0.75 reported; 00 L137 and 06 L13, L58 "≥ 0.90"; 04 §7.3 L1427 and App A L1601: floor 1.0 + judge-only 0.75 only | 04 adds line (ii) |
| R-21 | The Miscellaneous dump on r26 | 06 risk 14 L26 "W1-13 closes the dump for r26"; 06 D13 L49 "gated, not silent" (04 W1-13(d)); 04 W1-13(b) L749-754: r26 **keeps** the dump (D3 is the founder's), (d) **withdrawn** | 06 L26 → "closed for r27 by `CLUE_ARV2_V26_MISC_SECTION=off`; r26 keeps it (D3)"; 06 D13 → "not changed; ruling stands (04 §0.9)" |
| R-22 | P6 test file and filter form | 04 P6 L309 `tests/arv2/test_privacy_stop_v4_db.py`, filter `LIKE 'agent-profile:arv2-person:v%'`; 05 §6.1 item 10 L939 `tests/arv2/test_research_operations_db.py::test_privacy_stop_sets_input_refs_on_v4_person_job` and "the r26/r27 person profile refs" (there are none — `profile_ref` is catalog-versioned, `quality_committee_tool.py:219`); 03 §3.2 L438 "adds `…:v4`" | 04's file and prefix match; 05 L939 and 03 L438 |
| R-23 | Envelope binding site | 03 §3.5.6 L794-797: the caller (pre-step / `acquire@2`) records it; 04 W3-23 L1010-1014: `_drain` for `extract-*` labels; 06 risk 18 L30 "`acquire@2` binds it" | 04's `_drain` (one site, both callers); 03 L794-797, 06 L30 |
| R-24 | Migration count wording | 03 §1.1 L71-77 "One migration, no more … six role CHECKs", §9.4 L1711; 04 §10 L1533-1541: three (W2-17, W3-26, W2-19 after RC-2), "five" constraints (L938-944), and L1540 "03 §1.1's 'no migration' is superseded" (stale) | 03: "one migration in this design (W2 adds two indexes, W2-19 later)"; both: "five constraints, six predicates"; 04 L1540 reworded |
| R-25 | A0 duration | 00 L85 "≤ 60 s"; 03 §3.2 L368, 04 L1151 "63 s floor" | 00 → "≈ 63 s" |
| R-26 | A1 call count | 03 §3.3.2 L455 "≈ 27 provider calls" vs §3.3.8 L578-579 "≤ 25" | 03 heading → "≤ 25" |

Of the original 40: 14 closed outright (C1, C2, C5, C6, C7, C11, C12, C13, C14, C15, C20, C22,
C23, C27-C40 family), 12 closed by a ruling that both sides now carry (C4, C9 names aside, C10,
C17, C19, C21, C24, C25, C26, C28, C29, C33, C35), and the rest reduced to the name/number splits
above. 26 remain; **R-1, R-2, R-3, R-4, R-5, R-7, R-12, R-13** are the ones where 04's code and
05's harness would read different strings — those are the ones that cost a week if Aryan picks
one and the gate expects the other.

### Wrong citations / code claims remaining: 1 wrong, 5 stale cross-cites

| # | Where | Claim | Actual |
|---|---|---|---|
| W-R1 | 03 §10 L1828; 04 W3-24 L1258-1259 | the research roles' model is built at `quality_research_wiring.py:785-794`, where `CLUE_ARV2_V26_FALLBACK_MODELS` replaces the global chain | `:785-794` only swaps `model_id` on the resolved profile; the chain is `GatewayConfig.fallback_models` (`clue_config/gateway.py:100, 182, 191`) read in `GovernedAgentChatModel` (`agent_model.py:1047`) through `build_agent_model_provider(config)` (`agent_model_wiring.py:13`); `AgentModelProvider.build` (`ports.py:200-208`) has no fallback parameter → the change is in `libs/clue-gateway` / `agent_model_wiring.py` (A), not `qrw` (= R-15) |
| W-R2 | 05 §1.1 L59 | "03 §3.5.5 called the same two `research_v26_candidates` / `research_v26_pool_final`" | 03 §3.5.5 L774-776 now uses `research_candidates_first` / `research_candidates`; it is 04 W3-21 that still uses the old names (= R-1) |
| W-R3 | 03 §4.1 L1120-1121 | the id is "04 W1-5's `(class, quote or typed_value, url)` address" | 04 W1-5 L501 now addresses on `source_id` (= R-8) |
| W-R4 | 04 §0.6 L83 | blank + refuse "(03 §3.5.2, R7)" | 03 §3.5.2 L685-688 ships `google/gemini-3.8-flash` (= R-6) |
| W-R5 | 03 §10 L1739 | `CLUE_ARV2_MEDIA_ENABLED` "(04 W1-12's name)" | 04 W1-12 L729 uses `CLUE_ARV2_V26_MEDIA_ENABLED` (= R-5) |
| W-R6 | 04 W1-12 L735 | `test_quality_media_db.py:72, :293` | `:72, :289` (trivial) |

Verified correct among the newly cited sites: `quality_claims.py:115` (`inference` is an existing
`claim_kind`) and `:345-349` (the `ClaimSupport` rule does not bind a synthesis that cites only
`SourceSupport`s — Q23 holds); `dossier_import.py:76-78` (`identity_binding=WEAK` for persons,
`outreach_safe=False` for every finding — Q53 holds); `contracts.py:952` `L5_FOCUS` and
`context.py:625` `TurnLayerSource` (Q65 holds; `build_agent_context_assembler`,
`agent_platform_wiring.py:514-527`, has no `focus_source` parameter today — 04's "new argument"
is correctly flagged as an A change); `manual/tool_notes.yaml:88` and the comment-only references
at `agent_registry_wiring.py:221, :235` (Q39/Q40 hold); `Makefile:44-50` (`manual`,
`manual-check`); `account_research_driver.py:937-945` (the sweep's missing-results selection);
`a3602967bb73:138` (the status CHECK); `quality_views.py:308` (a real `account_research` check —
the context view's `capabilities_path`); `ledger.py:258-266`; `65880921cd52:20-25` and
`c237eb027732:29-41`; `quality_page_inputs.py:77-90` (the committee contacts are folded in — Q38
holds).

### Remaining blocking implementer questions: 7 (all "pick a side", none a design change) + 1 carried

| # | Question | Blocks | Answer to write |
|---|---|---|---|
| B-1 | Which reference kinds, media type, materialised path and candidates-view path do I code? (R-1, R-2, R-3) | W1-4, W1-5, W3-21, W3-24, 05's harness | 03's marker names; `inputs/candidates-<kind>.json`; the `candidates.json` view with `0.json` refused |
| B-2 | Which `entities[].kind` values go into `Candidate` — the enum is frozen at the r26 mint (R13)? (R-7) | W1-5 | 03 §4.1's ten |
| B-3 | Where do I switch the fallback chain off for research roles? (R-15) | W3-24 item 7 | `AgentModelProvider.build(..., fallback_models=())` from `agent_model_wiring.py`; `qrw` passes it by role |
| B-4 | Do I widen `Finding.claim_type` (03) or not (04)? (R-9) | W1-2 | not (04's sha reason) |
| B-5 | On a failed section, publish the rest or nothing? (R-10) | W3-25 | nothing (03) |
| B-6 | After the model retry budget: `suspended` or `needs_review/model_unavailable`? (R-14) | W3-24 item 7, 05 Q10 | `suspended` with `available_at` (03); `needs_review/model_unavailable` only after N suspends (set N) |
| B-7 | Which sheet do I code `Settings` from — 03 §10 or 04 §9? (R-13; 05 refuses to grade a run whose values differ from 03 §10) | every settings item; `tests/arv2/test_settings.py` | one merged sheet (R-13's fix) |
| Q39 (part) | carried from 04 §12 with its recommended answer | W1-11 | as 04 §12 |

04 §12's claim that 69 of 70 original questions are resolved is accurate; the seven above are new,
created by the reconciliation edits landing on different documents with different words.

### Missing pieces still unplaced: 3

- 05 §2.6 items 1–2 — the `transport_factory` parameter on `Arv2AccountResearchWorkHandler` /
  `build_arv2_account_research_handler` and a transport seam on `page_writer_runtime.provider_model_call`
  (A, one line each) — have no 04 item; 05 says the harness will monkey-patch for the first dry
  run "which must not be the lasting answer". Add to 04 as a W0/W3 line.
- 05 §2.6 item 8 — `tests/arv2/v26/conftest.py::pool(account)` through `publish_sources` — has no
  04 item.
- `CLUE_ARV2_V26_AS_OF_DATE` (05 L255, L1078) — in no sheet (R-13).

### Numbers in 00 and 06 against the reconciled 03 §5.5 and 03 §2

- **Match:** expected $3.48 Flash / $2.72 Luna (00 L26, L114; 06 L15); realistic ≈ $4.3 (00 L28,
  L114; 06 L15); modeled ceiling $9.4 / $8.1 (00 L29 "$9.4", L114; 06 L15); structural ≈ $22.7–25.8
  Flash / $17.9–21.0 Luna (06 L15 exact; 00 L29, L114 rounded "≈ $23–26 / $18–21" — acceptable);
  the caps (00 L103-106 "own words ×8"; 06 risk 7 L19 and D-rows carry 01b §6's values, matching
  03 §2.1 L122-144 and §10 C2 L1747-1749).
- **Do not match:** 00 L26-27 and L114 "~11 AI Ark credits" (03 §5.5 L1348: **17.6**); 00 L85
  "≤ 60 s" (63 s); 06 risk 14 L26 and D13 L49 on W1-13 (R-21). 00 L29 "$9.4 modeled" states the
  Flash number only — fine.

### Verdict

Materially better and now one build: the recipe integers, the judge surface (`submit_brief@1`),
the role (`person_research`), the two markers and two waits, the clearing values, the quote rule,
the 11-row floor, the caps, the contact-page continuation, P6, the R16 caps and the two ceilings
are stated the same way in 03, 04 and 05, and every citation fix from my §2 landed. **Not yet
hand-over-able as it stands**, for one reason: eight name/shape splits (R-1–R-5, R-7, R-12, R-13)
and one wrong build site (R-15) would make the code Aryan writes from 04 disagree with the strings
05's gate reads and with the sheet 05 refuses to grade against — and `Candidate`'s enum (R-7) is
frozen at the r26 mint, so that one cannot be fixed later without a third profile set. All 26
residuals are mechanical (pick the side named above; ≈ 35 line edits across 03, 04, 05, 00, 06),
none re-opens a ruling, and none needs a founder decision beyond D4's default wording. **Ready for
Aryan the moment that pass lands**, with the week-1 order unchanged (P6 → P5 → W1 → r26 mint →
RC-1).

---

## Re-check 2 (after applying the re-check's fixes under the coordinator's rulings)

**What was applied** (every edit is in the working tree, uncommitted; files touched: 00, 03, 03a,
04, 05, 06 — 02 needed nothing):

- **R-1–R-26, all 26**, with the rulings: 03's names everywhere (marker kinds `research_compile` /
  `research_committee` / `research_candidates_first` / `research_candidates`, media type
  `application/vnd.clue.research-candidates+json`, path `inputs/candidates-<kind>.json`, the
  `candidates.json` view with `0.json`/`<N>.json` refused — 03 §3.6.1/§3.6.2/§3.6.3/§5.3 now say
  so and 04 W3-21/W3-24, 05 §1.1/§3 AT-8/§4.5 use the same strings); `entities[].kind` = 03's ten,
  frozen at the r26 mint (04 W1-5, W3-23); `RECEIPT_CANDIDATES_MAX` = 20 (04's four sites);
  `CLUE_ARV2_MEDIA_ENABLED` (04's six sites + `arv2_media_enabled`); `…_SITE_PAGES_MAX` /
  `…_POST_PAGES_MAX` (04's three sites); the extractor default `google/gemini-3.8-flash` with a
  blank value refusing `extractor_model_unset` (04 §0.6, W3-23; 06 D4); `Finding` NOT widened —
  03 §2.2/§4.6/App B now carry 04 W1-2's `FindingV2`/`EntryV2` + `@1`-sha reason; a failed section
  → the page is not published (04 W3-25 = 03 §3.8); no `ACCOUNT_REFRESH_SECTIONS` anywhere;
  model failure = suspend with `available_at`, and a **new setting** `CLUE_ARV2_V26_MODEL_RETRY_SUSPENDS=3`
  (03 §3.6.5, §10 C7; 04 W3-24 item 7, §9; 05 §4.5(b), §6.1 item 11, §7 item 3) makes
  `needs_review/model_unavailable` reachable only past it; the R16(b) seam corrected to
  `GatewayConfig.fallback_models` → `build_agent_model_provider` → a `fallback_models` override on
  `AgentModelProvider.build` (03 §10 C7, 04 W3-24 item 7); rule rows = the 11 only, shape
  `operations[]`, five trigger kinds (04 W0 deliverable 1 + its test, W3-22); r27 account skills
  without `person-research-briefing` (03 §3.6.1); 03 §5.5's numbers in 04 W3-24, 05 §4.1/§4.2/§5/§6
  (9.4/8.1, $3.16 + $0.25, 351, ≤ $3.41, ≈ $22.7–25.8 / $17.9–21.0) and 00 (17.6 credits, ≤ 63 s,
  ≤ 25 + 5 × ≤ 19 calls); the sweep offers the contact jobs (05 §4.1); AT-9's three lines in
  04 §7.3 and App A; 06 risk 14 / D13 aligned to 04 W1-13(b) and the withdrawn (d); P6's test file
  and prefix filter in 05 §6.1 and 03 §3.2; `_drain` binds the extractor envelope (03 §3.5.6,
  06 risk 18); "one migration from this design (W2's two are W2's own), five constraints / six
  predicates" in 03 §1.1/§9.4/App A-9/App B, 04 W3-26/§10; A1 ≤ 25 / A2 ≤ 19 in 03's headings;
  the `max_per_round` per-rule note after 03 §3.4's example.
- **The one sheet (ruling 9):** 03 §10 gained **C0** (the r26/W2 switches of 04 W1-1/W1-4/W1-6/
  W1-7/W1-13/W2-15/W2-17/W2-19/P3 and `CLUE_ARV2_PAGES_PER_SECTION`), `…_ACQUISITION_PLAN_ENABLED`,
  `…_AS_OF_DATE`, `…_MODEL_RETRY_SUSPENDS` and `ARV2_PERSON_AGENT_MODEL_EFFORT` (comment row);
  04 §9 was regenerated from it (group, name, default, item), and its old "rows 03 §10 must adopt
  from here" paragraph is gone. A mechanical diff of the backticked setting names in 03 §10 vs
  04 §9 (`…_` expanded) shows 107 shared names and **no real difference** — the leftovers are
  03's `…_PERSON_…` / `_EFFORT` pair abbreviations and three mentions that are not rows
  (`ACCOUNT_RESEARCH_AGENT_MODEL` as a location, `CLUE_AGENT_FALLBACK_MODELS` as the replaced
  chain, `…_ACCOUNT_REFRESH_SECTIONS` in the deliberately-absent list); a value diff over every
  `NAME=value` `.env.example` line in 03 §10 against 04 §9's inline value finds none.
- **The 1 wrong + 5 stale citations (W-R1–W-R6)** — all corrected or made true by the fix of the
  thing they described (`:72, :289`; the fallback-chain site; 05 §1.1's marker parenthetical;
  03 §4.1's "04 W1-5's address"; 04 §0.6's "(03 §3.5.2)"; 03 §10's "(04 W1-12's name)").
- **The 7 pick-a-side questions B-1–B-7** — each now has one answer in every document (above).
- **Q39 (part)** — decided in 04 §12 (no recipe bump; carried as W1-11 step 3); 04 §12 now says
  70 of 70.
- **The 3 missing pieces** — 04 W0 deliverable 7 (the handler `transport_factory`, the page-writer
  transport seam, `tests/arv2/v26/conftest.py::pool`; A-owned; Appendix B lists the file);
  `…_AS_OF_DATE` in both sheets; 05 §7 items 1 and 3 marked adopted.

**Sweep after the edits** (same method as §1 and the first re-check): a grep over the set for every
residue string of R-1–R-26 and W-R1–W-R6 (old marker names, `research-v26-pool`, `inputs/pool-`,
`candidates-<subject>`, `_SITE_FETCH_MAX`/`_POST_FETCH_MAX`, `RECEIPT_CANDIDATES_MAX` 24,
`V26_MEDIA_ENABLED`, `ACCOUNT_REFRESH_SECTIONS=`, `$9.0`, `$7.7`, `$2.48`, `$2.73`, `275
operations`, `≈ $21`, the briefing skill on the account profile, `W1-13(d))`, `≤ 60 s`, `~11`,
`phrase|employer`, `only flag 03 lacks`, the old P6 test name, `pool_final`, `seven remaining`,
`class+any_of`, the old test enum, "on `Finding` itself", `Luna or Flash`, `≈ 27 provider`,
"`acquire@2` itself", `22 + 5×`, the old fallback build site, the old model-failure sentence, "the
rest publish") returns **0 hits**; every table row in 00/03/04/05/06 still has balanced pipes.

### Final counts

| | Re-check 1 | **Re-check 2** |
|---|---|---|
| Cross-document contradictions | 26 | **0** |
| Blocking implementer questions | 7 (+ Q39 carried) | **0** (Q39 decided) |
| Wrong citations / stale cross-cites | 1 + 5 | **0** |
| Missing pieces | 3 | **0** |

One note that is not a contradiction and needs no decision: 03 §5.5's provider maximum counts
A1 as 23 and A2 as 17 (the expected template counts) while 03 §3.3.8's bounds are ≤ 25 / ≤ 19
(the conditional homepage/profile and the ≤ 4 R10 pages at their caps). The difference is 2 + 5 × 2
= 12 searches ≈ $0.11 on a $3.41 line and the gate recomputes its own structural figure from
`settings_in_force` (05 §4.2), so I left 03 §5.5's arithmetic as the author wrote it; if the author
wants the maximum to equal the bound, the line is "351 → 363 operations, $3.16 → $3.27, $3.41 →
$3.52" and the three Flash/Luna totals move by ≈ $0.1.

### Verdict

**Ready for Aryan.** The nine documents now carry one vocabulary (03's), one settings sheet
(03 §10, with 04 §9 regenerated from it and mechanically identical), one `Candidate` shape frozen
at the r26 mint, one answer to every question an implementer would otherwise have to pick, and the
same numbers in 00, 03, 04, 05 and 06. Nothing in this pass re-opened a ruling (R1–R20 and the nine
coordinator rulings of this round were applied as written); the only new mechanism is the
`MODEL_RETRY_SUSPENDS` setting that gives `needs_review/model_unavailable` a defined trigger. Order
of work unchanged: P6 → W0 (incl. deliverable 7) → P1–P5 → W1 → r26 mint → RC-1.
