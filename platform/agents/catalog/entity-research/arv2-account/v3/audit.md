name: arv2-account-audit
version: v3

# The fabrication audit

1. After structuring and before finalize, call `verify_links` over every claim this job wrote that
   cites a URL. The tool fetches each URL once (Exa `/contents`, cached per run), runs
   `substring_verdict(quote, page_text)` and returns EXACT / PARTIAL / NOT_FOUND per claim, plus
   `fetch_failed` for URLs that would not load.
2. The result is written as an **annotation** on each claim, never as a deletion or a blocker
   (`CLUE_EVIDENCE_VERBATIM_CHECK=off` by default means the annotation is recorded and not
   displayed). Each annotation records *why* it reached its verdict — `on_page`, `partial_on_page`,
   `page_empty`, `page_unreachable`, `not_on_page`, `second_hand_from_report` (the quote is real but
   was read out of a report about the account rather than off the page it cites) or `quoted_context`
   (the quote sat in your own notes, so no page is fetched) — because a dead link, an empty page and
   an invented quote each want a different repair. The honest defect rate of the PoC runs was 6–9 %
   paraphrased spans; the audit makes it visible.
3. A NOT_FOUND quote whose page did load is reported in the finalization summary by claim id; you
   may issue one narrower `fetch_page` to find the passage on the right page, then stop.
4. Media `verify_links` resolves the pinned transcript artifact and exact character span.
   It never checks an episode's HTML for spoken words or retranscribes. NOT_FOUND, unavailable,
   suspect quality, unknown speaker/timing and superseded-version findings stay visible.
5. The audit never re-buys research. Its budget is contents calls only.

## Provider evidence and replay

Inspect provider references through the local result reader; URL checks apply to web claims only.
Keep the agent's committee-role assessment separate from provider facts. A failed or erased
source is unavailable evidence, never permission to reconstruct a profile from memory. Contact
channels are independently unresolved until their own identity and claim writes succeed.
