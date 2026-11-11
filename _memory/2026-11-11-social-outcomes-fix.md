# 2026-11-11 — social readers: failures never reported as answers (review finding I1)

Branch `trial/research-quality`, commits 25de51b1d (code + tests) and e766c1eba (docs); review tags
`review/social-outcomes/start` / `end`.

- `clue_api/footprint/social.py`: each reader returns a `PageRead` (posts / closed / failure); one loop
  (`_history`) decides complete / partial / unavailable / private / not_found. "not found" and "private"
  only from replies probed live 2026-11-11 (sources ledger §0a). X has no not-found reply (TikHub 400 is
  generic) — reported as a failure naming both readings.
- treg has a halt rule (402, or 401 with `X-Treg-Error: 1`); the reader keeps what it read and sets
  `SocialHistory.halted`; `footprint_operations._social` latches `runtime.halted["treg"]`.
- Receipt: `outcome_code` → `error_code` (history_partial, history_unavailable, provider_halted,
  account_not_found, account_private); reason on the first preview line ("Report") and in `recovery`.
  Output schema of acquire v3 is unchanged (no new statuses), so recipe 44's pins still hold.
- `AcquireResearchToolV3.begin_dispatch`: an identical call after history_partial/history_unavailable
  runs as attempt n (`{"arguments": …, "attempt": n}`), never after an uncertain dispatch.
- Tests: tests/footprint/test_social_outcomes.py (85), tests/arv2/test_social_receipts.py, 3 DB tests in
  test_acquire_v3_db.py (run on clue_research_trial_test). 313 related tests green.
- Owed: founder approval of the new agent-facing report/recovery sentences (`footprint_operations._outcome`).
- Not covered here (separate findings): I2/I3 recording searches, I5 PDL failure in find_handles,
  I8 short-link redirects, the rest of the review list in docs/superpowers/specs/research-quality/review-2026-11-11/.

## Continued 2026-11-11 — I2, I3, I4, I5 + C1, I6, I8 (review tags review/footprint-failures/start..end)

- Searches return a `Tally` (`clue_api/footprint/search_tally.py`): complete / partial / unavailable;
  `SourceStopped` for a paid source refusing to sell; codes searches_partial / searches_unavailable.
  YouTube quota = note, rate limit = failure; Exa stop latched as `exa` only (never podcast_index /
  youtube_data). `footprint_operations._exa` checks status and raises the stop at once if latched.
- find_handles → `(candidates, Tally)`, runs under label `footprint_handles`; `pdl_person` → `PdlLookup`;
  PDL halt rule 402/401; `keep_handles_only` raw scrubber (C1); handles_partial / handles_unavailable.
- Receipt rule: a failure that brought nothing back is `refused`, never `empty`.
- X: own = author.rest_id == data.user.rest_id (fallback data.user.profile); kind `in_feed` for
  another account's non-retweet; preview names its author.
- Short links: `short_links.expand(links)` → `Expanded(addresses, failed)` on
  `PublicMediaTransport(follow_redirects=False)`; not a provider call (no ledger/evidence/trace);
  tests/footprint/conftest.py blocks real link opens.
- Founder rulings: retries re-run the whole call; C1 folded into I5.
- 402 related tests green (DB tests on clue_research_trial_test).
- Owed: founder approval of the new agent-facing sentences (receipt report/recovery lines and the
  `in_feed` preview title).
