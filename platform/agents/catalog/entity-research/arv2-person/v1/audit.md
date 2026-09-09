name: arv2-person-audit
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
   was read out of a report about the person rather than off the page it cites),
   `second_hand_from_company` (the quote was lifted from a company post about the person, so it is
   not the person's voice) or `quoted_context` (the quote sat in your own notes, so no page is
   fetched) — because a dead link, an empty page and an invented quote each want a different repair.
   Paraphrased spans are a real and recurring defect of this work; the audit is what makes them
   visible.
3. A NOT_FOUND quote whose page did load is reported in the finalization summary by claim id; you
   may issue one narrower `fetch_page` to find the passage on the right page, then stop.
4. Media quotes are already exact-substring-verified against the transcript by the media client; the
   audit records that verdict without refetching audio.
5. The audit never re-buys research. Its budget is contents calls only.
6. **Speaker attribution audit.** For every `voice_quote` taken from media, the transcript segment
   must be attributed to the subject (the media client's speaker verdict). A quote whose speaker is
   not verified is recorded `speaker_unverified` and is barred from hooks and openers.
7. **Attribution audit.** For every quote: a quote lifted from a company post about the person is
   `second_hand_from_company`, not the person's voice.
8. **Lock audit.** The `excluded_lookalike` log must be non-empty, or it must state "no same-name
   sources met".
