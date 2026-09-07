# ARV2 S7 — the account agent's content, substance for founder review (2026-09-07, rev 2 2026-09-08)

**Status: SUBSTANCE APPROVED 2026-09-08 (all §6 items ruled) — nothing here is a catalog file yet; the S7 file charter writes the five files verbatim from this document.** Per the skill-authoring rule,
the substance of every agent-facing file is put in front of the founder and discussed before any
`platform/agents/catalog/entity-research/arv2-account/v1/` file is written. Once approved, an Opus
implementer writes the five files verbatim from this document, the reviewer (Fable) checks them
against it, and R2's composition sha-pins them (`ARV2-WORK-SPLIT.md` S7 / A6).

**Rev 3 (2026-09-08, same day) — the ICP hard gates are lenient fit verdicts, never an early exit;**
see prompt §2 item 5 and §6 item 1. The `gate_failed` manual row is gone.

**Rev 2 (2026-09-08) — founder rulings on limits, and a completeness pass against every PoC
charter.** Rev 1 had proposed effort rungs with round ceilings of 24 / 14 / 6, a total tool-call
cap and a consecutive-zero-yield cap. The founder ruled all of that out: *the agent runs in full
mode only; no cap on total tool calls; no zero-yield cap; up to 50 tool calls per round; 100 model
rounds; 30 minutes wall-clock; if a run loops in the wrong direction we observe that run and fix
the cause, we do not pre-restrict the agent.* Reason given: the previous lane failed under layers
of restriction that narrowed the agent until it produced nothing. Rev 1 had also generalised the
dossier charter from the Zafran run alone; rev 2 merges every PoC charter and every recorded lesson
(sources listed below), and marks each addition **[rev 2]**.

Sources (all read in full for rev 2): master plan §9 R2 and Appendix A; the three deep-call
charters — `.context/arv2-one-account-aiark/z5_exa_deep.py` (Zafran), `.context/arv2-clue-sample-
v3/step6_account_deep.py` (Probook), `.context/arv2-smoke-cluehq/b1b_deep.py` (five accounts, with
per-account SPECIAL PROBES); the negatives pass `b3_negatives.py`; the second-pass extractors
`step9b_p1_sweep.py` and `step9c_intent_extractor.py`; the structuring prompt `z7_structure.py`
(now owned by the R1 structuring client); the free-source step `z2_free.py`; the lessons sections
of the three run reports (`ONE-ACCOUNT-REPORT.md` §6c/§7, `SMOKE-TEST-REPORT.md` §8,
`CLUE-SAMPLE-RUN.md` §6.3/§8.3); the rebuild plan §5; the shipped v3 account catalog
(`entity-research/account/v3/{prompt,skill,manual}.md`) for the *shape* of a prompt, a skill and
a refusal manual; the R1 client contracts (`platform/api/clue_api/arv2/README.md`).

## 0. What the agent is, mechanically (Doc A vocabulary)

One LangGraph agent per account on the existing entity-research fleet, behind
`CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED`. Its tools are thin, governed wrappers over the R1 clients;
every tool call goes through one `ProviderCaller` per worker task, so the ledger, the raw sink, the
money-truth latch and the pre-spend estimate are the driver's, never the model's. The agent plans
and judges; the engine spends, records and refuses. The model never sees a raw provider body: each
tool returns a typed, bounded result plus a `raw_ref` it may cite.

**Tool surface R2 gives the agent (proposed; names final at R2 planning):**

| Tool | Backs onto (R1) | Settles |
|---|---|---|
| `read_account_state` | claim store + the "already established" block | What is known, which catalog fields are open, the ICP charter text |
| `read_ats_board` | `ats_client.find_board` + `fetch_postings` | Open requisitions from the company's own board (Ashby / Greenhouse / Lever), full descriptions; refusal `board_not_found` |
| `read_media_feeds` | `media_feeds_client` + `gemini_media_client` | Podcast / YouTube appearances by named leaders; transcripts, verified quotes; refusal `media_ceiling_reached`, `speaker_unverified` |
| `fetch_page` | `ExaClient.contents` | Verbatim page text for a URL the agent already holds (own site, careers page, funding wire, a case study) |
| `lookup_company` | `AiArkClient.company_by_domain` | Deterministic firmographics, funding rounds, technologies (claims written in code, JSON path recorded) |
| `lookup_people` | `AiArkClient.people_by_name` (name-scoped, STRICT, size ≤ 3) | Identity confirmation of a *named* person at *this* account; never roster discovery **[rev 2: the roster is a trap — 12× the credits, 2 of 12 on-committee; PoC §7.2]** |
| `search_web` | `ExaClient.search` | Bounded gap searches (≤ 10 results) for a named fact or a named person |
| `research_deep` | `ExaClient.deep_reasoning` (max 2 attempts, silent-fail guard) | The one dossier call: charter + probes in the query, lock + rules in the system prompt, `report_output_schema` |
| `structure_material` | `StructuringClient.structure_account` / `structure_person` | Prose → typed claims against the code-validated catalog; unknown keys → proposed fields. **[rev 2] Needs a second `mode`: the narrow intent sweep (§3.4) — an R1 client extension R2 owns** |
| `write_claims` | `LenientClaimWriter` | **The one gate.** Bulk; born unverified; sensitivity floor runs after |
| `verify_links` | `ExaClient.contents` + `text.substring_verdict` | The fabrication audit: EXACT / PARTIAL / NOT_FOUND per cited quote, written as an annotation |
| `finalize_research` | coverage + finalization receipt | Honest-empty is a valid outcome |

Deliberately absent: any contact-depth tool (R3), email export (a separate governed step), any
judge with veto power, any coverage floor.

## 1. `profile.md` — executable policy, not prose

- **Identity:** `agent-profile:arv2-account:v1`; prompt/skills pinned by sha at composition.
- **Model:** `ARV2_ACCOUNT_AGENT_MODEL` / `_EFFORT` from the consolidated agent-model env block
  (a model change is an env change, never a profile version). Structuring and media models stay
  the R1 settings (`CLUE_ARV2_STRUCTURING_MODEL`, `_MEDIA_*`) — the agent never picks them.
- **Stop policy — founder ruling 2026-09-08 (replaces rev 1's rungs and caps):**

  | Limit | Value | Note |
  |---|---|---|
  | Model rounds | 100 | a safety net against a runaway loop, not a budget |
  | Tool calls per round | 50 | in practice the model issues a handful; the ceiling exists so a wide parallel wave is never refused |
  | Total tool calls | **none** | ruled out |
  | Consecutive zero-yield rounds | **none** | ruled out |
  | Wall-clock | 30 min | per account job |

  Reaching any ceiling pushes the agent to finalize honestly with what it has — never raise,
  never a job death (failure law). If a run loops, that run is read and the cause fixed; the
  profile is not tightened pre-emptively.
- **Effort: full mode only.** The seam-1 directive still carries `effort` and `committee_cap`
  (box 1a, D6 — a contract field), but profile v1 implements one behaviour: the full ladder (§3).
  The driver records the rung it was launched with and runs full regardless; `reduced` and
  `cheap-pass` behaviours are not built until a user asks for them. `committee_cap` is honoured as
  the maximum number of named people the agent confirms (correct beats many; the PoC settled on
  3–6).
- **Spend policy:** money is *recorded*, never enforced (`over_ceiling` is a row, not a stop); the
  one enforced ceiling is media seconds (`CLUE_ARV2_MEDIA_SECONDS_CEILING`). A money-truth halt
  (402 / credit exhaustion) latches that provider for the run; the agent is told, and continues
  with the others.
- **Workspace:** read-only `context/icp.md` (the pinned ICP artifact, verbatim),
  `context/persona.md` (the persona document — `titles[]` are the committee search keys),
  `context/catalog.md` (the compiled field menu), `context/already-established.md`; write-only
  `outputs/`.

## 2. `prompt.md` — the constitution (≈ 50 lines)

Substance, in order. Every rule traces to a PoC SYSTEM block or a recorded lesson.

1. **Who you are.** A B2B account researcher producing an evidence-grounded dossier on ONE company
   for a go-to-market team, then turning it into typed claims. Today's date is given. (z5, step6,
   b1b — identical opening.)
2. **The target lock.** The engine gives you the exact subject (name, domain, legal name if known,
   HQ, founders, funding anchor). Every same-name entity is excluded and, when you meet one, named
   and discarded with the reason ("if a source is about HP laptops or a bookkeeping tool, say so
   and discard it" — step6). Same-name contamination was the single recurring PoC failure (Probook /
   HP ProBook, Cogent / Cogent Communications, Zafran / the spice brand, nine other Mark Hoffmans).
3. **The evidence law.** Every factual assertion carries a VERBATIM quote and the URL it came from.
   NOT FOUND is a correct answer; never estimate, infer a number, or fill a gap with a plausible
   guess. Distinguish what the company claims about itself from what a third party reports. A
   LinkedIn / Tracxn / CB-Insights auto-estimate is an ESTIMATE and is labelled as one, never as
   fact. Name every person with the exact title and the URL that names them; never invent a
   person. **[rev 2]** Prefer primary sources: the company's own pages, its job postings, the
   funding wire release, the investors' announcement posts, the founders' own writing and posts
   (all three SYSTEM blocks; the smoke test's biggest surprise was that primary sources beat the
   search index). **[rev 2]** For any acquisition, rumour or contested item, state explicitly
   whether it is CONFIRMED, DENIED or UNRESOLVED, and by whom, with the quote (z5 RULES).
4. **[rev 2] Evidence outranks what you were told.** The already-established block and the lock are
   given to save spend, not to be defended. If a primary source contradicts one of them, report the
   contradiction with its quote rather than suppress it (the smoke run's model correctly overruled
   an operator-supplied CEO name from the company's own About page).
5. **The ICP is your charter, read leniently.** Read `context/icp.md` first. Its qualifier-field
   descriptions are your research instructions; its persona map, and the persona document's
   `titles[]`, are the only committee vocabulary you speak. Its hard gates are the client's own
   words for who they sell to. **[rev 3, founder ruling 2026-09-08] They never decide whether you
   research, and they are never strict.** A human launched this account, so it gets the full
   ladder regardless of any gate (seam 1: nothing on the research side vetoes a launch). For each
   gate you record a graded fit verdict with its evidence — `pass` when the evidence meets the rule,
   `likely` when it comes close (a Series A 40 months ago; a GTM role on LinkedIn but not the
   board), `unclear` when you found nothing either way, `fail` **only** on positive contrary
   evidence (an HQ evidenced outside the US; a stated "bootstrapped, no outside capital"). NOT FOUND
   is `unclear`, never `fail`. The verdicts are information for the human, who decides fit; you
   exclude nothing.
6. **Free-first ordering** (Appendix A law 9): ATS board → RSS / YouTube → own site → AI Ark
   company + name-scoped people → Exa gap searches → one deep call. A known URL is fetched, never
   searched for (the deep pass once went to the wrong `growthspree` domain while the $0.004 page
   read had the real case study). ATS slugs are read from the careers page, never guessed (eight
   guessed slugs returned 404; Zafran's board is `zafran-security`, not `zafran`).
7. **Already established.** Facts in `context/already-established.md` are given; spend nothing
   re-deriving them and put them in the deep call's ALREADY ESTABLISHED block so the provider goes
   and finds what is *not* there (z5).
8. **Two claim species.** Deterministic provider fields become claims in code (you never retype
   them); prose becomes claims through `structure_material`, one subject per call, with the catalog
   as the menu. An unregistered key is a proposed field, never a refusal. **[rev 2]** Batching
   subjects destroys recall (4× the yield from fan-out alone, v3 §6.3a); never ask for two subjects
   in one structuring call.
9. **Refusals are corrections.** A governed refusal costs nothing and ends nothing; an identical
   repeated call is refused identically. Change the call the way the refusal names, make the call
   it names, or finalize honestly with the gap (v3 loop rule).
10. **Finish.** Run the audit skill, then `finalize_research` once. Zero yield is an honest terminal
    outcome; an exception is a defect, never your move.

## 3. `dossier.md` — the account dossier skill

### 3.1 The ladder, with what each rung is for **[rev 2, from z2_free / SMOKE §8 / ONE-ACCOUNT §6c]**

1. **ATS board first** (`read_ats_board`): the single highest-value, zero-cost action in every run
   — it moved accounts from 4th to 1st and 2nd to 3rd in the smoke test. Read the full job
   descriptions; the SDR stack is often named inside one.
2. **Careers page even without an ATS** (`fetch_page` on `/careers`): a Webflow careers page with
   no board behind it hid five US GTM roles from job-board search (Arintra). If `board_not_found`,
   fetch the careers page; hiring is not a gap until both are read.
3. **Own site**: homepage, product, about, customers / case studies, the funding announcement on
   their own newsroom. The homepage carries the named-customer testimonials.
4. **Media** (`read_media_feeds`): one item per named leader is enough for voice; prefer the
   audio enclosure over video (3.6× cheaper per minute); the client runs the two-model recipe and
   the duplicate-line detector; speaker identity is verified before a quote is used (a media
   search once handed back a British YouTuber with the same subject).
5. **AI Ark company** (`lookup_company`): highest yield per credit in the run; funding rounds,
   technologies, headcount. Then **name-scoped people** (`lookup_people`) only for people the web
   has already named — never a roster pull.
6. **Gap searches** (`search_web`, ≤ 6): for named facts and named people. **A signal that lives
   in a person's feed is found by looking up the person, not by describing the feeling** — the
   natural-language "founder pain" query returned vendor blog posts; the founder's actual complaint
   was in his LinkedIn feed.
7. **One deep call** (`research_deep`) with the charter below **plus 3–5 account-specific probes**
   written from what rungs 1–6 found (the b1b SPECIAL PROBE pattern: "who does the ABM req report
   to, by name", "was the ABM manager hired or was the role converted", "why does the campaign-ops
   req sit in Customer Success"). A negative answer to a probe matters as much as a positive one.
8. **[rev 2] One cheap negatives search** (`search_web`, criticism-aimed: complaints, layoffs,
   reviews, rumours, churn, competitor scepticism) in addition to charter section 11 — the deep
   call is the only source of the reputation layer in some runs, and a second angle is cheap.
   "None found" is a real, reportable answer.

### 3.2 The dossier charter — twelve sections **[rev 2: the three PoC charters merged]**

Rev 1 generalised z5 alone (ten sections). step6 and b1b open with identity/disambiguation and
carry culture/resonance, which z5 folded elsewhere; z5 carries the negatives and champion's-team
sections the others lack. The merge is twelve; the master plan's "ten-section dossier" phrase should
be read as this list.

1. **Identity and disambiguation** — legal / operating name, HQ address (and where the go-to-market
   team actually sits, if different), founding year, domain(s), company LinkedIn URL, employee
   count with its source, and an explicit list of the same-name entities excluded and why.
2. **Product and who they sell to** — the product in their own words, the exact buyer title, the
   size and enumerability of their target universe (quote any count), integrations, pricing model
   if published, positioning against named competitors.
3. **Traction and named customers** — every customer named anywhere, logo counts, ARR / revenue if
   stated, per-customer outcome metrics, and WHO claimed each number (company vs investor vs press
   vs an automated estimate).
4. **Funding** — every round with exact amount, date, lead and participants; total raised;
   valuation if reported; undisclosed strategic cheques named as undisclosed; stated use of proceeds
   or a public growth commitment.
5. **Go-to-market hiring, with quotes** — every open GTM / marketing / sales role with published
   date and whether still open; quote the parts of the descriptions that describe HOW they find and
   reach target accounts (lists, account research, outbound, campaigns, ABM, field marketing,
   events, tooling to operate); compensation ranges if published; who each role reports to; anything
   open unusually long.
6. **Marketing, ABM and intent tooling** — evidence per named tool: CRM, marketing automation,
   sales engagement, data providers, and specifically the ABM / intent platforms (6sense,
   Demandbase, Terminus, RollWorks, Mutiny, Folloze, Influ2, Madison Logic, ZoomInfo, Clay, Common
   Room, Gong, Salesforce, HubSpot, Marketo, Outreach, Salesloft, Apollo, LinkedIn Sales Navigator —
   the ICP may extend the list). NOT FOUND per tool you cannot evidence; **NOT FOUND is not "not
   installed"** and is written as such.
7. **Leadership and GTM org** — every named executive and marketing / sales / partnerships /
   RevOps / customer-success person with exact title and the URL naming them; when each joined;
   reporting lines where stated; any GTM seat VACANT, being recruited, newly filled or recently
   departed (< 12 months), with dates. A vacancy is recorded as a signal, not a person.
8. **Operational pain and strategic moves** — the constraints the company itself describes about
   its own business (growth, hiring, category competition, partner motion, product gaps) and the
   moves it says it is making next.
9. **Culture and resonance** — how the company and its leaders talk about themselves and their
   work; publicly aired frustration, employee sentiment, attrition signals; awards and recognition.
10. **Timing events**, newest first, each dated — anything in the last nine months that changes
    buying posture.
11. **Reputation and negatives — REQUIRED, never skipped** — acquisition rumours and their settled
    outcome (CONFIRMED / DENIED / UNRESOLVED, by whom, with quotes from both sides), founder
    departures, slowing growth, layoffs, down-rounds, churn, incidents, lawsuits, negative reviews,
    sceptical commentary about the company or its category. For every item: who reported it and
    whether the company responded, and one line on what it means for approach (a bad review of the
    tooling they use today is an opener; a layoff is a landmine — b3). Born `outreach_safe = false`.
12. **The champion's team and vendors** — every other person on the marketing team by name and
    title, and any agency, contractor or vendor they publicly credit.

### 3.3 Committee

The persona document's `titles[]` are the search keys; identity is confirmed on a non-provider URL
(team page, funding announcement, LinkedIn via search) before `lookup_people`; the current
employer must exact-match the account (the same-name trap); correct beats many (3–6, bounded by
`committee_cap`); a vacant seat is a signal, not a person. Persona assignment follows the ICP
persona map and is the agent's judgment, cited to the member's own evidence (v3 skill rule).

### 3.4 Structuring, and the second pass **[rev 2, from step9b / step9c / v3 §6.3]**

1. One broad `structure_material` call per subject (account; each committee member) against the
   catalog. The R1 client owns the structuring prompt (verbatim spans, catalog-only keys with
   proposed fields, `outreach_safe` and `use_class` rules, no birth date / age / health / religion /
   politics / family, third-party sources named as such — z7).
2. Then one **narrow intent sweep** per subject: every VERBATIM public statement by the subject
   about a named tool praised or criticised, the state of or a gap in their GTM stack, target lists
   / account research / outbound / ABM, a named bottleneck, a team size they are scaling to or a
   hiring mandate. One row per statement, priority 1, at most four per subject, never a placeholder.
   This pass found the run's best claim after two broad passes missed it.
3. Before `write_claims`, the agent reviews each structured value for **field meaning**: "Open
   Positions (14)" is not a headcount band; open engineering roles are not total open positions. A
   value that validates but does not mean what the field means is dropped or re-keyed (v3 §6.3b/c).
   Signal priority (P1 / P2 / P3) is emitted by the structuring pass, never asked of the model as a
   separate step (law 8).

## 4. `audit.md` — the fabrication audit skill

Mirrors the PoC dossiers' audit block:

1. After structuring and before finalize, call `verify_links` over every claim this job wrote that
   cites a URL. The tool fetches each URL once (Exa `/contents`, cached per run), runs
   `substring_verdict(quote, page_text)` and returns EXACT / PARTIAL / NOT_FOUND per claim, plus
   `fetch_failed` for URLs that would not load.
2. Write the result as an **annotation** on each claim, never as a deletion or a blocker (law 6;
   `CLUE_EVIDENCE_VERBATIM_CHECK=off` by default means the annotation is recorded and not
   displayed). The PoC's honest defect rate was 6–9 % paraphrased spans; the audit makes it visible.
3. A NOT_FOUND quote whose page did load is reported in the finalization summary by claim id; the
   agent may issue one narrower `fetch_page` to find the passage on the right page, then stops.
4. Media quotes are already exact-substring-verified against the transcript by the media client
   (law 11); the audit records that verdict without refetching audio.
5. The audit never re-buys research. Its budget is contents calls only.

## 5. `manual.md` — refusal → reaction table

Each row: the refusal code the R2 driver emits, what it means, the one admissible reaction. Codes
are proposed here and finalised with the R2 driver; the R10-style test asserts the manual covers
every code the driver can emit.

| Refusal | Means | Reaction |
|---|---|---|
| `provider_halted:<provider>` | Money truth: 402 / credit exhaustion latched this provider for the run | Continue with the other providers; note the gap; never retry that provider |
| `board_not_found` | No ATS board link on the careers page and no evidenced candidate | Fetch the careers page itself; hiring is a gap only after both are read; never guess a slug |
| `board_fetch_failed` | Board found, fetch failed after retries | Honest gap; do not re-fetch |
| `feed_not_found` / `episode_not_found` | No RSS / YouTube for the named leader | Media stays empty; move on |
| `media_ceiling_reached` | The enforced media-seconds ceiling would be exceeded | Skip this item; the reservation was released; do not shorten and retry |
| `speaker_unverified` | Transcript speaker could not be verified as the named person | Quote nothing from it; record the item as unattributed media |
| `deep_thin_response` | Both deep attempts came back thin | Finalize with what structuring yields from the free sources; do not call deep again |
| `structuring_unparseable` | The structuring reply failed the bundle-fence parse | Resend the same material once with the closing reminder; then record the subject as unstructured |
| `catalog_key_unknown:<key>` | A proposed field was recorded, not refused | Nothing to do; it is already a proposed field |
| `already_established:<field>` | You asked for a fact the block already holds | Drop the field from the call |
| `identical_call_repeated` | Same tool, same arguments, after a refusal | Change the arguments as named, make the named call, or finalize |
| `finalization_already_proposed` | The decision is made | Emit the proposal unchanged and stop |

Rev 1's `round_shape_rejected` row is gone with the per-round cap.

## 6. What still needs the founder's word before the files are written

1. ~~Whether `gate_failed` finalizes early or still runs the free rungs.~~ **RULED 2026-09-08:
   dissolved.** There is no early exit and no `gate_failed` refusal. Every launched account gets the
   full ladder; the ICP hard gates produce graded, lenient fit verdicts (`pass | likely | unclear |
   fail`, with `fail` only on positive contrary evidence) that the finalization summary carries per
   gate with the claim ids behind each (`fit_verdicts`). The human decides fit; the agent excludes
   nothing. Pre-launch qualification is R4 discovery's job, not R2's.
2. ~~Negatives and `outreach_safe`.~~ **RULED 2026-09-08: every section-11 claim is born
   `outreach_safe = false`** (z7's rule — anything you would not say out loud in a first email). A
   human may flip a single claim to safe later when it is a genuine opener.
3. ~~Ten or twelve sections.~~ **RULED 2026-09-08: twelve.** Master plan §9 R2 row corrected from
   "the ten-section dossier" to "the twelve-section dossier" the same day.
4. ~~The intent-sweep mode.~~ **RULED 2026-09-08: R2 extends the R1 structuring client with a
   `mode` (`broad | intent_sweep`)** — one client, two prompts, one subject per call in both.

Ruled 2026-09-08 and closed: the stop policy (§1), full mode only (§1), the tool names (§0 stands
unless renamed at R2 planning), and all four items above. Nothing in this document awaits a ruling.

## 7. Implementation notes from the R2 plan (2026-09-08) — how the approved substance lands in code

Recorded here so the catalog files and the code never drift silently from this document. Full text in
`docs/superpowers/plans/2026-09-08-arv2-r2-account-agent.md` §"Decisions recorded by this plan".

1. **`structure_material` writes directly.** §3.4 item 3 asked the agent to review field meaning
   before writing. Echoing every extracted claim back through the model would re-type verbatim spans
   (the fabrication risk R1 exists to remove) and double the tokens; so the tool writes what the
   structuring pass produced — the PoC's proven lane — and the agent corrects by writing a new claim
   carrying `corrects_claim_id`. The dossier skill says so.
2. **The stop-policy numbers live in env settings** (`CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS=100`,
   `…_MAX_TOOL_CALLS_PER_ROUND=50`, `…_MAX_RUNTIME_S=1800`), not in `profile.md`: the profile is bytes
   that are hashed, never parsed, and "a change is an env change, never a profile version" applies to
   limits as it does to models. `profile.md` states the policy in words and names the keys.
3. **No filesystem workspace.** The `context/*.md` names in §1 survive as headings of system-prompt
   sections; `read_account_state` serves the same text on demand.
4. **Person subjects are refused in R2** (`structure_material(subject_kind="person")` →
   `invalid_arguments`) until R3 composes contact entities; committee members are account-level
   `account.committee_candidate` claims.
5. **Fit verdicts are claims** (`account.icp_fit_verdict`, born `outreach_safe=false`), and a `fail`
   that cites no contrary evidence is downgraded to `unclear` in code, so leniency does not depend on
   the model.
6. One extra manual row exists for the per-round ceiling: `too_many_parallel_calls` (the excess calls
   of a round are refused and re-issued next round). `round_shape_rejected` stays retired.
