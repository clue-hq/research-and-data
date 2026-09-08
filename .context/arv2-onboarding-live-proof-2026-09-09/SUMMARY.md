# Live proof 2026-09-09 — Insight Health run eef4a3fd (both lanes, merged code, post-restart worker)
Requested 2026-09-08T19:31:21Z (UTC). Run `completed`, 734 s, $2.782 (prior runs: 856 s / 1019 s).

## Synthesis split (O4 follow-up) — spec §6 checks
| check | result |
|---|---|
| ICPs servable while personas still running | ICP turn 159→457 s; 3 ICP rows registered at 457 s (7m37s after request; prior runs 14–17 min); persona steps opened at 457 s |
| three persona steps concurrent, run completed | persona 457→692 / 734 / 734 s, all `completed`; run `completed` |
| no new ICP path; keys reused | same three keys, all at version 3 (superseding v2) |
| persona `icp_version` == ICP row version | 3 / 3 / 3 |
| 15 evidence invocations, none under the ICP turn | 5 + 5 + 5 under the three persona executions; 0 under the ICP execution |
| hang guard | not tripped |
Note: the ICP turn took 299 s, not the ~150 s hoped — call 1 opened with the core docs in context (44k tokens), but the agent then read product files one call at a time (calls 2–7, ~110 s) as the v2 skill asks, then wrote (143 s), then four short calls (~45 s). Follow-up: ask for the product reads in one batch.

## Catalog identity ladder (O3 follow-up) — Task 6 checks
| check | result |
|---|---|
| no duplicate product row minted | 21 lineup entries: 18 `alias_reused` (exact spelling), 1 `created` (high, model: "EHR Partnership", own page /ehr-partnership, a partner program), 2 `unresolved_ambiguous` |
| products before → after | 27 → 28 (the one genuinely new page) |
| model stage | one `catalog-reconcile` call, 1 candidate vs 27 on file, 8.6 s, $0.00187, ledger + raw under `.artifacts/arv2/onboarding/<run>/catalog-reconcile/` |
| alias write-back | none needed: every matched name folded exactly onto the row it matched (no drift this run) |
| the two ambiguous entries | `Aura™ AI Scribe` and `Aura™ Anywhere` each fold onto TWO existing rows (the un-marked and the marked duplicates minted by earlier runs before the mark-stripping fix) — the ladder refuses to choose, mints nothing; those pre-existing duplicate pairs are the product-set gate's (O6) to merge |
Files: post-response.txt, poll.log (48 polls), steps-final.txt, run-final.txt, products-before/after.txt, audience-before/after.txt, audience-after-icp-turn.txt.
