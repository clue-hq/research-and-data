name: arv2-account-audit
version: v1

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
4. Media quotes are already exact-substring-verified against the transcript by the media client; the
   audit records that verdict without refetching audio.
5. The audit never re-buys research. Its budget is contents calls only.
