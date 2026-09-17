name: arv2-person-manual
version: v1

# Person tool operations manual

Your eleven tools, what each one settles, and the exact move each refusal wants.

## The loop rule

Every governed refusal arrives as a tool result shaped
`{"error": "governed_research_rejection", "code": "…", "detail": "…", "recoverable": true, "reaction": "…"}`.
It spent nothing, suspended nothing and ended nothing. It is a correction, not a verdict on the
job, and its `reaction` field is that code's row in the table below.

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
| `subject_lock_failed` | Either this job carries no confirmed LinkedIn URL for the person — nothing can be locked to them, so no provider record may be written onto them — or the confirmed employer or employment history does not match the account (the same-name trap, caught at launch). | This candidate is not the person; record the lookalike; no person job. |
| `page_unavailable` | The page was fetched and came back with no text. | Record the URL as unreadable; try a different known URL, never a search for the same page. |
| `email_export_empty` | The provider export returned no email for this member. It arrives as the `email_export_empty` result field of `lookup_person`, never as a refusal. | Record no email; the member is still researched. |
| `feed_not_found` | No podcast RSS or YouTube URL resolved for the named person. | Every URL given failed to load (the message names each with its error). If you have not yet passed alternates — the podcast's other feed host, the YouTube upload of the same episode — call once more with them in alternate_urls; otherwise media stays empty for this person; move on. |
| `episode_not_found` | The feed loaded, but it holds no episode matching what you named. | The feed has no matching episode; media stays empty for this person. |
| `media_ceiling_reached` | The enforced media-seconds ceiling would be exceeded by this item. | Skip this item; the reservation was released; do not shorten and retry. |
| `media_cap_reached` | This person already has the configured number of media items (default 3). | Media for this person is complete; do not call read_media_feeds again for them. |
| `enclosure_too_large` | The episode's audio enclosure is bigger than the download ceiling. | Skip this item; do not retry with another URL for the same episode. |
| `native_video_rejected` | You asked for a native video download; only the YouTube words path is admitted. | Use the YouTube words path (page text), never a video download. |
| `speaker_unverified` | The transcript's speaker could not be verified as the subject. | Quote nothing from this transcript; record the item as unattributed media. |
| `deep_thin_response` | The deep call was attempted twice and its report came back empty. | Both deep attempts came back thin; structure what the free sources yielded; do not call research_deep again. |
| `structuring_unparseable` | The structuring reply failed the bundle-fence parse. | Resend the same material once; if it fails again record the subject as unstructured. |
| `insight_not_found` | `unique_insight` found nothing beyond a standard profile. | Record "thin public footprint" with channels checked; move on. |
| `already_established` | You asked for a fact the already-established block already holds. The wire form is `already_established:<field>` and names it. | Drop that field from the call; it is already recorded. |
| `identical_call_repeated` | Same tool, same arguments, after a refusal. No provider was touched. | Change the arguments the way the earlier refusal named, make the call it named, or finalize honestly. |
| `too_many_parallel_calls` | You issued more tool calls in one round than the per-round ceiling allows; the excess were refused, not the round. | Re-issue the refused calls in the next round; the calls within the per-round ceiling ran. |
| `finalization_already_proposed` | `finalize_research` has already been accepted for this job. | The decision is made; stop. |
| `tool_error` | The tool raised something unexpected and wrote nothing. The wire form is `tool_error:<exception>` and names the exception class. | The tool failed for a reason outside your control; record the gap and continue. |
| `invalid_arguments` | An argument failed the tool's schema, or asked for something this profile does not admit. | Correct the named argument and call again. |

## The tool contract

| Tool | Backs onto | Settles |
|---|---|---|
| `read_person_state(section)` | claim store + the "already established" block | What is known about this person and their account, which catalog fields are open, the ICP charter text |
| `fetch_page(url, max_chars)` | `ExaClient.contents` | Verbatim page text for a URL you already hold (the person's LinkedIn page as indexed text, a personal site, a talk page, a byline) |
| `search_web(query, num_results, include_domains, start_published_date)` | `ExaClient.search` | The six unrestricted sweep searches (≤ 10 results) for this named person; a domain-restricted sweep returns a same-name stranger, so leave the domains empty |
| `lookup_person(linkedin_url)` | `AiArkClient.people_by_name` (name-scoped, STRICT) + the email export | Identity confirmation and the deterministic fields for *this* person at *this* account, plus their professional email. The name to search and the account to scope it to are the job's, so the one argument is the LinkedIn URL the record must match; the record is refused only if its current employer is a different company than this account. Every registered field the record carries is claimed in code, JSON path recorded; never a roster pull, and no email is ever synthesised. An employer the record cannot state is recorded as unverified, never refused. An export that finds no address comes back as a result field, not a refusal |
| `read_media_feeds(person_name, person_role, feed_url, youtube_url, alternate_urls, episode_title_contains, episode_number)` | `media_feeds_client` + `gemini_media_client` | Podcast / YouTube appearances by this person; transcripts, verified quotes; bounded by the per-person item cap |
| `research_deep(charter, probes, same_name_exclusions, num_results)` | `ExaClient.deep_reasoning` (max 2 attempts, silent-fail guard) | The one dossier call: charter + probes in the query, lock + rules in the system prompt, a report schema |
| `structure_material(subject_kind, subject_name, subject_domain_or_company, linkedin_url, sources[{url, kind, text, title}], notes, mode, already_known)` | `StructuringClient` | Prose to typed claims against the code-validated catalog; unknown keys become proposed fields; on a person job the subject_kind is `person` |
| `unique_insight(subject)` | `StructuringClient` (one narrow question) | The one thing about this person a generic enrichment tool would never surface, written into the existing facet field it actually is at priority 1 with the `unique_insight` marker; it registers no field |
| `write_claims(claims[...])` | `LenientClaimWriter` | **The one gate.** Bulk; born unverified; the sensitivity floor runs after; each claim is written on its own, so one unwritable value is reported in `write_failures` and the rest still land |
| `verify_links(claim_ids)` | `ExaClient.contents` + `text.substring_verdict` | The fabrication audit: EXACT / PARTIAL / NOT_FOUND per cited quote, written as an annotation |
| `finalize_research(summary, openers[{text, hook, quote, url}], hooks[], not_found[], same_name_log[{name_or_url, why_excluded}], reports_to{name, contact_id?, quote, url}\|null, gaps[])` | coverage + finalization receipt | Honest-empty is a valid outcome. The receipt: the depth summary, the three openers, the hooks, the not-found list with the channels you checked, the same-name log, who they report to, and the gaps. An opener whose `quote` is empty is dropped and named back to you; `reports_to` is written only when it carries the verbatim quote and the URL that state the reporting line. No fit verdicts and no committee candidates — those are the account job's |

Notes that decide calls, not style:

- `structure_material` takes one subject per call and writes the claims it extracts. On a person job
  the subject is this person and the `subject_kind` is `person`; an `account` subject is refused
  `invalid_arguments`, because every claim this job writes is stamped to the person.
- `structure_material` takes its material as `sources` (one to twelve), never as one string: each
  source is a page, posting, report, transcript or provider record, with the URL it came from. A
  quote may only come from inside a source, and the claim cites that source's URL. Your own reading
  of the material goes in `notes`, which is background and can never be quoted — a claim quoting it
  is written with its quote marked NOT FOUND. Its result adds `dropped_rows` (rows the mode's cap
  discarded) and `write_failures` (`field_key` + `error` for any draft the claim store refused; the
  rest of the batch still landed, so re-write only what is named there).
- `unique_insight` is asked once, after the broad structuring pass, and asked even when that pass
  returned nothing distinctive. When it finds nothing it refuses `insight_not_found`; that is a
  finding, and the receipt records "thin public footprint" with the channels checked.
- `write_claims` takes at most fifty claims in one call. A claim tagged
  `[ORIGIN - NOT AN OUTREACH HOOK]`, and a self-announced wedding or baby, are always written
  `outreach_safe = false` and never appear in a hook or an opener. Like `structure_material`, its
  result carries `write_failures` (`field_key` + `error` for any claim the store refused); every
  other claim in the call landed, so re-write only what is named there.
- After structuring, a deterministic compliance pass runs over every claim this job wrote before the
  claims are readable: minors redacted, origin and faith recorded as biography only, the sensitivity
  floor redacted with the category on the claim, rows with no quote or no URL marked `unevidenced`.
  A claim carrying a phone number, a personal email or a home address is **dropped whole**, whatever
  field it arrived on; a value whose every sentence is sensitive is dropped too, because redacting it
  leaves nothing; everything else is redacted sentence by sentence and marked with the category. Every
  action is logged to the receipt, so a claim you wrote and cannot find afterwards was removed there.
  `lookup_person`, `structure_material` and `unique_insight` each return a `compliance` list of the
  rows *their own call* produced, so an empty `written` is never ambiguous: it says whether nothing
  was found or the floor removed what was.
- `research_deep` returns a thin report rather than refusing it; `deep_thin_response` fires only
  when the report text is empty.
- Deliberately absent: the account-only tools — `read_account_state`, `read_ats_board`,
  `lookup_company`, `lookup_people` — the account job owns those and their results reach you through
  your context; any judge with veto power; any coverage floor.
