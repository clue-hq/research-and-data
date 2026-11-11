# 2026-11-12 — Podcast identity merge (review finding I14)

Branch `trial/research-quality`, tags `review/podcast-identity/start..end`, plan
`docs/superpowers/plans/2026-11-12-podcast-identity-merge.md`.

- Problem: `find_podcasts` merged results on show name + title, so two different "Episode 12"s
  became one lead with mixed audio/description and one episode vanished.
- Fix (`footprint/podcast_search.py`): leads keep `guid`, `show_id`, `source_ids`; `audio_key`
  and `feed_key` normalise links (tracker unwrapping, scheme/case/www/query rules); `_group`
  (union-find) merges only on source id, GUID+same show, same audio, or same show+title+day+length;
  Exa on show name+title+day. Missing never matches. `_combine` builds a lead from proven members
  only (fixed source order; heard names only from Exa).
- Data (r44a stored replies): ids present on ~100% of Apple/PI results; replay 945 -> 948 leads;
  only wrong/unproven merges split.
- Open: Task 4 "may be the same episode as #N" overview note waits for founder wording approval;
  volume (drop PI byterm, per-source caps) is a separate founder decision.
- Tests: tests/footprint + test_acquire_v3 + test_quality_recipe_43 = 282 passed (offline).
