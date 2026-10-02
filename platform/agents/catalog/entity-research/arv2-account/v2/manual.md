name: arv2-account-manual
version: v2

# Account tool operations manual

Your research tools, what each one settles, and the exact move each refusal wants.

## The loop rule

Every governed refusal arrives as a tool result shaped
`{"error": "governed_research_rejection", "code": "…", "detail": "…", "recoverable": true, "reaction": "…"}`.
It is a correction, not a verdict on the job. Pre-dispatch refusals spend nothing; a provider
failure or an unknown dispatch may already have spent, as its durable receipt records. Its
`reaction` field is the code's row in the table below.

Never send an identical call after a refusal. The refusal is deterministic: the same arguments
produce the same refusal forever. After any refusal you have exactly three admissible moves —
change the arguments the way the `detail` names, make the different call it names, or finalize
honestly with the gap.

Three codes carry a suffix on the wire: `provider_halted`, `already_established` and `tool_error`
arrive as `provider_halted:<provider>`, `already_established:<field>` and `tool_error:<exception>`.
The base code before the colon is the row key and decides the reaction.

## Refusal to reaction

| Refusal | Means | Reaction |
|---|---|---|
| `provider_halted` | Money truth: 402 or credit exhaustion latched this provider for the run. The wire form is `provider_halted:<provider>` and names it. | Continue with the other providers and note the gap; never retry that provider in this job. |
| `board_not_found` | No ATS board link on the careers page and no evidenced candidate. | Fetch the careers page itself with fetch_page; hiring is a gap only after both were read; never guess a slug. |
| `board_fetch_failed` | The board was found; fetching its postings failed after retries. | Record hiring as an honest gap; do not re-fetch the board. |
| `page_unavailable` | The page was fetched and came back with no text. | Record the URL as unreadable; try a different known URL, never a search for the same page. |
| `company_not_found` | The company lookup returned nothing for that domain. | AI Ark has no record for this domain; continue from the web sources. |
| `feed_not_found` | No podcast RSS or YouTube URL resolved for the named leader. | Every URL given failed to load (the message names each with its error). If you have not yet passed alternates — the podcast's other feed host, the YouTube upload of the same episode — call once more with them in alternate_urls; otherwise media stays empty for this person; move on. |
| `episode_not_found` | The feed loaded, but it holds no episode matching what you named. | The feed has no matching episode; media stays empty for this person. |
| `media_ceiling_reached` | The enforced media-seconds ceiling would be exceeded by this item. | Skip this item; the reservation was released; do not shorten and retry. |
| `enclosure_too_large` | The episode's audio enclosure is bigger than the download ceiling. | Skip this item; do not retry with another URL for the same episode. |
| `native_video_rejected` | You asked for a native video download; only the YouTube words path is admitted. | Use the YouTube words path (page text), never a video download. |
| `speaker_unverified` | The transcript's speaker could not be verified as the named person. | Quote nothing from this transcript; record the item as unattributed media. |
| `deep_thin_response` | The deep call was attempted twice and its report came back empty. | Both deep attempts came back thin; structure what the free sources yielded; do not call research_deep again. |
| `structuring_unparseable` | The structuring reply failed the bundle-fence parse. | Resend the same material once; if it fails again record the subject as unstructured. |
| `already_established` | You asked for a fact the already-established block already holds. The wire form is `already_established:<field>` and names it. | Drop that field from the call; it is already recorded. |
| `identical_call_repeated` | Same tool, same arguments, after a refusal. No provider was touched. | Change the arguments the way the earlier refusal named, make the call it named, or finalize honestly. |
| `too_many_parallel_calls` | You issued more tool calls in one round than the per-round ceiling allows; the excess were refused, not the round. | Re-issue the refused calls in the next round; the calls within the per-round ceiling ran. |
| `finalization_already_proposed` | `finalize_research` has already been accepted for this job. | The decision is made; stop. |
| `tool_error` | The tool failed; consult its saved operation and claim receipts for partial results. The wire form is `tool_error:<exception>` and names the exception class. | The tool failed for a reason outside your control; record the gap and continue. |
| `invalid_arguments` | An argument failed the tool's schema, or asked for something R2 does not admit. | Correct the named argument and call again. |

## The tool contract

| Tool | Backs onto | Settles |
|---|---|---|
| `read_account_state(section)` | claim store + the "already established" block | What is known, which catalog fields are open, the ICP charter text |
| `read_ats_board(company_url)` | `ats_client.find_board` + `fetch_postings` | Open requisitions from the company's own board (Ashby / Greenhouse / Lever), full descriptions |
| `fetch_page(url, max_chars)` | `ExaClient.contents` | Verbatim page text for a URL you already hold (own site, careers page, funding wire, a case study) |
| `search_web(query, num_results, include_domains, start_published_date)` | `ExaClient.search` | Bounded gap searches (≤ 10 results) for a named fact or a named person |
| `lookup_company(domain)` | `AiArkClient.companies_exact` + saved company lock | Deterministic firmographics, funding rounds, technologies — every registered field the record carries is claimed in code, JSON path recorded |
| `discover_people(role_key, rationale, evidence_refs, titles, seniority, functions, page, size)` | AI Ark SMART title search | Unknown people at the engine-locked company; saved result and candidate references, pagination and employment conflicts |
| `read_people_result(result_ref, candidate_refs)` | Verified saved provider response | Full scrubbed profiles without another purchase |
| `read_media_feeds(person_name, person_role, feed_url, youtube_url, alternate_urls, episode_title_contains, episode_number)` | `media_feeds_client` + `gemini_media_client` | Podcast / YouTube appearances by named leaders; transcripts, verified quotes |
| `research_deep(charter, probes, same_name_exclusions, num_results)` | `ExaClient.deep_reasoning` (max 2 attempts, silent-fail guard) | The one dossier call: charter + probes in the query, lock + rules in the system prompt, a report schema |
| `structure_material(subject_kind, subject_name, subject_domain_or_company, linkedin_url, sources[{url, kind, text, title}], notes, mode, already_known)` | `StructuringClient.structure_account` | Prose to typed claims against the code-validated catalog; unknown keys become proposed fields; `mode` is `broad` or the narrow `intent_sweep` |
| `write_claims(claims[...])` | `LenientClaimWriter` | **The one gate.** Bulk; born unverified; the sensitivity floor runs after; each claim is written on its own, so one unwritable value is reported in `write_failures` and the rest still land |
| `verify_links(claim_ids)` | `ExaClient.contents` + `text.substring_verdict` | The fabrication audit: EXACT / PARTIAL / NOT_FOUND per cited quote, written as an annotation |
| `finalize_research(summary, fit_verdicts, gaps, committee_candidates)` | coverage + finalization receipt | Honest-empty is a valid outcome. One verdict per ICP gate, keyed by the gate's `key` (case and stray spaces are folded to the ICP's own spelling): a gate the ICP still does not name is refused `invalid_arguments` naming the keys it does, and a gate you did not assess is filled `unclear` / "not assessed" by the tool; a repeated gate keeps your first answer and comes back in `duplicate_gates`. Each `committee_candidates` entry may also carry `rationale` (one sentence on why this person matters to the deal) and `influence` (`High`, `Medium` or `Low`); both are optional and both ride onto the member's own committee claim |

Notes that decide calls, not style:

- `structure_material` takes one subject per call and writes the claims it extracts. In R2 the only
  admitted `subject_kind` is `account`; `person` is refused `invalid_arguments` until R3 composes
  contact entities.
- `structure_material` takes its material as `sources` (one to twelve), never as one string: each
  source is a page, posting, report, transcript or provider record, with the URL it came from. A
  quote may only come from inside a source, and the claim cites that source's URL. Your own reading
  of the material goes in `notes`, which is background and can never be quoted — a claim quoting it
  is written with its quote marked NOT FOUND. Its result adds `dropped_rows` (rows the mode's cap
  discarded) and `write_failures` (`field_key` + `error` for any draft the claim store refused; the
  rest of the batch still landed, so re-write only what is named there).
- `write_claims` takes at most fifty claims in one call. Web committee claims written directly
  need a `confirmed_by` URL. Provider candidates go through `finalize_research` with
  `evidence_kind="provider_candidate"` and `candidate_ref`; their saved source supplies the facts. `account.reputation_risk` and `account.icp_fit_verdict` are always
  written `outreach_safe = false`. Like `structure_material`, its result carries `write_failures`
  (`field_key` + `error` for any claim the store refused); every other claim in the call landed, so
  re-write only what is named there.
- `research_deep` returns a thin report rather than refusing it; `deep_thin_response` fires only
  when the report text is empty.
- Deliberately absent: any contact-depth tool (that is R3), email export (a separate governed
  step), any judge with veto power, any coverage floor.

## v2 discovery and channels

An account deep attempt must finish before `discover_people`. After exhausted failure, record the
gap and continue. AI Ark is the primary role-based committee source; web evidence fills gaps.
Use `read_people_result` for full source profiles and `candidate_ref` for provider selection.
A source handle is scoped to its account job. Never substitute a different company or forge a
candidate. Unfilled role does not imply vacancy. Choose useful people, deduplicate, then cap.

Person jobs reuse the saved profile. `enrich_contact` requests email and phone independently;
failed or missing contact details do not block depth. Repeated requests reuse the operation.
A running/unknown operation may have spent: record the uncertainty and do not change its inputs
merely to retry. Erased evidence is unavailable; do not recreate it in job receipts.

`discover_people` uses company-scoped SMART titles; `read_people_result` expands saved profiles without spend.
