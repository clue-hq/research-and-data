# Account discovery (ARV2 R4) audit — 2026-09-28

Analysis only; no code changed. Follows the founder discussion on discovery over-finding
(target 5 → ~30 accounts). Evidence: `clue_san-salvador` (every lane DB carries the same four
runs; this workspace's `.env` points at `clue_dubai`, which does not exist), the raw provider
bodies under `san-salvador/.artifacts`, Exa's create-search API reference, and one free
`GET /websets/{id}`.

## Findings (most severe first)

1. **The relaxed/top-up search has never worked live.** `add_search` sends
   `exclude: [{source: "search", ...}]`; Exa answers 400 "Expected 'import' | 'webset'"
   (run `21910e1d`, 2026-09-12 08:18:06). The caller returns 4xx as `client_error` without
   raising, `add_search` never checks the status, the driver logs `relaxed_search_unnamed` and
   lands the run `completed` at 8 of 15.
2. **Exa's default `behavior` is `override`** (replace the webset's items, re-evaluate against the
   new criteria). We never send `behavior`, so a fixed exclude would still override the strict
   results. Any top-up design needs `append` or a new webset per search (probe live first).
3. **Websets bills on find, we price on read.** Run `ee79d837` halted at 7 found (Answer 402);
   Exa shows that webset completed at 35 found. About 28 × $0.045 is missing from the ledger. No
   cancel call exists.
4. **Recall estimate is paid for and never parsed.** Exa returns `recall.expected.total` (300,
   bounds 160–650 on `f1549f76`); `_recall_estimate` looks for other keys, so every run stores null.
5. Flat `strict_count=35`, no stop at target, and every verified company is auto-added to the
   project (ruling 2026-09-11), so over-finding also floods the project.
6. Run id = hash(project, ICP, target, provider ask, relaxed flag, gate keys): asking again with
   the same number replays the finished run and finds nothing.
7. Workspace-wide dedupe: an account another project already has is `duplicate_of_existing` and
   never added to this project. `not_chosen_before` is dead since the auto-add ruling.
8. stage0-interview v38 §7b tells the agent to offer a relaxed pass (no tool for it;
   `request_relaxed_pass` is CLI-only) and says the human adds accounts to the project (they are
   already added).
9. The website-domain answer is trusted without guards; 4/76 domains were rewritten, e.g.
   Charlottesville Gastroenterology Associates → gastrohealth.com (parent network).
10. 72/76 fits land High; exclusions are never asked (known, recorded at R4 close-out).

Correction to the earlier transcript: Exa accepts 1–5 criteria. The cap of 3 is our own choice,
made after the R4 experiment where all 5 gates starved a search.

Open founder decisions: which top-up mechanism (new webset per search vs append), whether a
repeat ask is a new run, whether a matching account from another project joins this one, and
how strictly to treat the website-domain answer.
