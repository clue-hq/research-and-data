# ARV2 S7 — the account agent's content, substance for founder review (2026-09-07)

**Status: DRAFT FOR REVIEW — nothing here is a catalog file yet.** Per the skill-authoring rule,
the substance of every agent-facing file is put in front of the founder and discussed before any
`platform/agents/catalog/entity-research/arv2-account/v1/` file is written. Once approved, an Opus
implementer writes the five files verbatim from this document, the reviewer (Fable) checks them
against it, and R2's composition sha-pins them (`ARV2-WORK-SPLIT.md` S7 / A6).

Sources: master plan §9 R2 and Appendix A; the PoC charter `.context/arv2-one-account-aiark/
z5_exa_deep.py` (the ten-section dossier, the target lock, the ALREADY ESTABLISHED block); the
rebuild plan §5 (skills); the shipped v3 account catalog (`entity-research/account/v3/{prompt,
skill,manual}.md`) for the *shape* of a prompt, a skill and a refusal manual; the R1 client
contracts (`platform/api/clue_api/arv2/README.md`, "R2 composition constraints").

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
| `read_ats_board` | `ats_client.find_board` + `fetch_postings` | Open requisitions from the company's own board (Ashby / Greenhouse / Lever); refusal `board_not_found` |
| `read_media_feeds` | `media_feeds_client` + `gemini_media_client` | Podcast / YouTube appearances by named leaders; transcripts, verified quotes; refusal `media_ceiling_reached`, `speaker_unverified` |
| `fetch_page` | `ExaClient.contents` | Verbatim page text for a URL the agent already holds (own site, funding wire, careers page) |
| `lookup_company` | `AiArkClient.company_by_domain` | Deterministic firmographics, funding rounds, technologies (claims written in code, JSON path recorded) |
| `lookup_people` | `AiArkClient.people_by_name` (name-scoped, STRICT, size ≤ 3) | Identity confirmation of a *named* person at *this* account; never roster discovery |
| `search_web` | `ExaClient.search` | Bounded gap searches (≤ 10 results) for a named fact |
| `research_deep` | `ExaClient.deep_reasoning` (max 2 attempts, silent-fail guard) | The one dossier call: charter in the query, lock + rules in the system prompt, `report_output_schema` |
| `structure_material` | `StructuringClient.structure_account` / `structure_person` | Prose → typed claims against the code-validated catalog; unknown keys → proposed fields |
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
- **Rounds and shape:** at most 3 tool calls per round; `research_deep`, `verify_links` and
  `finalize_research` travel alone; a hard round ceiling per effort rung (`full` 24, `reduced` 14,
  `cheap-pass` 6 — proposed; caps push to finalize, never raise).
- **Spend policy:** money is *recorded*, never enforced (`over_ceiling` is a row, not a stop); the
  one enforced ceiling is media seconds (`CLUE_ARV2_MEDIA_SECONDS_CEILING`). A money-truth halt
  (402/403-credit) latches the provider for the run; the agent is told, and continues on the
  others.
- **Effort rung ladder** (`directive.effort`, D6): `full` = ATS + RSS/YouTube + own site + AI Ark
  company + name-scoped people + gap searches + one deep call + audit; `reduced` = drops media and
  gap searches; `cheap-pass` = ATS + own site + AI Ark company + structuring, no deep call.
- **Committee cap** (`directive.committee_cap`): the maximum named people the agent confirms.
- **Workspace:** read-only `context/icp.md` (the pinned ICP artifact, verbatim), `context/
  catalog.md` (the compiled field menu), `context/already-established.md`; write-only `outputs/`.

## 2. `prompt.md` — the constitution (≈ 40 lines)

Substance, in order:

1. **Who you are.** A B2B account researcher producing an evidence-grounded dossier on ONE company
   for a go-to-market team, then turning it into typed claims. Today's date is given.
2. **The target lock.** The engine gives you the exact subject (name, domain, legal name if known,
   HQ, founders). Every same-name entity is excluded and, when you meet one, named. (z5 LOCK block,
   made generic.)
3. **The evidence law.** Every factual assertion carries a verbatim quote and the URL it came from.
   NOT FOUND is a correct answer. Never estimate, infer a number, or fill a gap with a plausible
   guess. Distinguish what the company claims about itself from what a third party reports; label
   auto-estimates (LinkedIn, Tracxn) as estimates. Name every person with the exact title and the
   URL that names them; never invent a person.
4. **The ICP is your charter.** Read `context/icp.md` first. Its hard gates decide *whether* to go
   deep (a failed gate is finalized honestly with the gate named, not researched around); its
   qualifier-field descriptions are your research instructions; its persona map is the only
   committee vocabulary you speak.
5. **Free-first ordering** (Appendix A law 9): ATS board → RSS/YouTube → own site → AI Ark company
   + name-scoped people → Exa gap searches → one deep call. A known URL is fetched, never searched
   for; ATS slugs are read from the careers page, never guessed.
6. **Already established.** Facts in `context/already-established.md` are given; spend nothing
   re-deriving them and put them in the deep call's "ALREADY ESTABLISHED" block so the provider
   goes and finds what is *not* there.
7. **Two claim species.** Deterministic provider fields become claims in code (you never retype
   them); prose becomes claims through `structure_material`, one subject per call, with the catalog
   as the menu. An unregistered key is a proposed field, never a refusal.
8. **Refusals are corrections.** A governed refusal costs nothing and ends nothing; an identical
   repeated call is refused identically. Change the call the way the refusal names, make the call
   it names, or finalize honestly with the gap (v3 loop rule, kept verbatim in spirit).
9. **Finish.** Run the audit skill, then `finalize_research` once. Zero yield is an honest terminal
   outcome; an exception is a defect, never your move.

## 3. `dossier.md` — the ten-section account dossier skill

The z5 charter generalised. The deep call's query is these ten sections with the account's
specifics filled from the ICP and the already-established block:

1. **What they actually sell** — product in their own words, exact buyer titles, buying process,
   pricing model if published, positioning against named competitors. Quote.
2. **Funding** — confirm/extend known rounds; undisclosed amounts; total raised; valuation if
   reported; stated use of proceeds.
3. **Go-to-market team** — every named marketing/sales/partnerships/RevOps/CS person with exact
   title and the URL naming them; reporting lines where stated; vacant, newly filled or recently
   departed GTM seats (<12 months) with dates.
4. **Hiring, with quotes** — for GTM requisitions, quote the parts describing HOW they find and
   reach target accounts (lists, research, outbound, ABM, tooling); compensation ranges if
   published; anything open unusually long.
5. **Martech / ABM / intent tooling** — evidence per named tool (the ICP's tool list); NOT FOUND per
   tool you cannot evidence. Do not guess.
6. **Named customers and proof** — every customer named anywhere, every outcome metric with who
   claimed it.
7. **Operational pain and strategic moves** — the company's own constraints (growth, hiring,
   category competition, partner motion, product gaps) and the moves it says it is making next.
8. **Timing events**, newest first, each dated — anything in the last nine months that changes
   buying posture.
9. **Reputation and negatives — REQUIRED, never skipped** — acquisition rumours and their settled
   outcome (CONFIRMED / DENIED / UNRESOLVED, by whom, with quotes from both sides), founder
   departures, slowing growth, layoffs, down-rounds, churn, incidents, lawsuits, negative reviews,
   sceptical commentary. For every item: who reported it and whether the company responded. These
   claims are born `outreach_safe = false`.
10. **The champion's team** — every other person on the marketing team by name and title, and any
    agency or vendor they publicly credit.

Skill rules beside the charter: the deep call carries `report_output_schema` (one string property);
the silent-fail signature (≤ 9 results, ≈ $0.015, < 3,000 chars) gets exactly one retry (the client
does it); a thin second response is finalized as thin. Committee: 3–6 correct people beat many; the
persona map's `titles[]` are the search keys; identity is confirmed on a non-provider URL before
`lookup_people`; a vacant seat is recorded as a signal, not a person. Signal priority is computed
by the structuring pass (P1 buying signal / P2 qualifying / P3 context), never asked of the model
as a separate step (law 8).

## 4. `audit.md` — the fabrication audit skill

Mirrors the PoC dossiers' audit block:

1. After structuring and before finalize, call `verify_links` over every claim this job wrote that
   cites a URL. The tool fetches each URL once (Exa `/contents`, cached per run), runs
   `substring_verdict(quote, page_text)` and returns EXACT / PARTIAL / NOT_FOUND per claim, plus
   `fetch_failed` for URLs that would not load.
2. Write the result as an **annotation** on each claim (`verification_status` note + verdict), never
   as a deletion or a blocker (law 6; `CLUE_EVIDENCE_VERBATIM_CHECK=off` by default means the
   annotation is recorded and not displayed).
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
| `board_not_found` | No ATS board link on the careers page and no evidenced candidate | Hiring stays a gap unless the own-site fetch shows a careers page to read; never guess a slug |
| `board_fetch_failed` | Board found, fetch failed after retries | Honest gap; do not re-fetch |
| `feed_not_found` / `episode_not_found` | No RSS/YouTube for the named leader | Media stays empty; move on |
| `media_ceiling_reached` | The enforced media-seconds ceiling would be exceeded | Skip this item; the reservation was released; do not shorten and retry |
| `speaker_unverified` | Transcript speaker could not be verified as the named person | Quote nothing from it; record the item as unattributed media |
| `deep_thin_response` | Both deep attempts came back thin | Finalize with what structuring yields from the free sources; do not call deep again |
| `structuring_unparseable` | The structuring reply failed the bundle-fence parse | Resend the same material once with the closing reminder; then record the subject as unstructured |
| `catalog_key_unknown:<key>` | A proposed field was recorded, not refused | Nothing to do; it is already a proposed field |
| `already_established:<field>` | You asked for a fact the block already holds | Drop the field from the call |
| `identical_call_repeated` | Same tool, same arguments, after a refusal | Change the arguments as named, make the named call, or finalize |
| `round_shape_rejected` | > 3 calls, or a solo tool travelled with others | Re-plan the wave; do not repeat it |
| `gate_failed:<gate>` | The ICP hard gate failed on evidence | Finalize honestly with the gate and its evidence named; no deep call |
| `finalization_already_proposed` | The decision is made | Emit the proposal unchanged and stop |

## 6. What needs the founder's word before the files are written

1. The tool names and the effort-rung round ceilings in §1 (24 / 14 / 6).
2. Whether the `cheap-pass` rung really skips the deep call (the PoC priced it at $0.015/account).
3. Whether `gate_failed` finalizes without any research beyond the gate evidence, or still runs
   the free sources (ATS + own site) so the account screen is not empty.
4. The negatives rule "born `outreach_safe = false`" for every section-9 claim, or only for the
   sensitive subset.
