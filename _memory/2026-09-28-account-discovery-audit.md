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

## Follow-up session (same day) — what was done

Founder rulings: **(1)** each top-up search is a **new webset** that excludes the earlier websets
(`exclude: [{source: "webset", id}]`); **(2)** "find more" always starts a **new run**, with
everything earlier runs found excluded. Both are recorded for the three-search rebuild, which
is **not built yet**.

- **DB:** `clue_dubai` (:55040) cloned from `clue_jerusalem-v1` via pg_dump inside
  `clue-pg-istanbul`; `.artifacts` cloned with `cp -Rc` (APFS clone) from jerusalem-v1. Every
  non-test artifact row has its blob; 1738 `ws_test_*` rows lack blobs in jerusalem as well.
- **Relaxed-search retry (live):** the platform's exact request → 400 "expected import|webset"
  again (not credits; that would be 402). The corrected form — a NEW webset, `count: 2`, the
  relaxed criteria, `exclude: [{source: "webset", id: webset_01m2aajkp9266ept9yq3hmdkyd}]` —
  finished in 41 s with 2 new companies (Tryon Medical Partners, GracePointe Healthcare), neither
  in the original 8. Probe webset `webset_01m3j5rncn6z8fbkbr2yz323ep`, ≈20 credits (~$0.09),
  not on the platform ledger.
- **Money fix, commit `b5eab8961`:** `ExaWebsetsClient.cancel`; the driver cancels a non-idle
  webset when a run ends early (halt / wall clock / uncaught error) and reads it once more
  (receipt `webset_stopped`, `rows_priced_at_stop`); recall parsed from `recall.expected.total`
  and its 5 credits recorded on create; an Exa 4xx records zero instead of the estimate.
  Offline: 91 tests in the three touched files pass; tests/arv2+fleet offline show only the two
  failures that also fail on clean HEAD (import guard on quality files; account-research port
  pins) plus the three known `duration_of` collection errors.
- **Instructions (uncommitted, inside the turn-budget bundle):** stage0-interview v38 §7b and
  tool_notes corrected, manual-tools v11 regenerated, v65 pins and registry digest updated.
  tests/agents: 2 failures in test_runtime.py, identical on clean HEAD.
- Not done: the 16 tool descriptions still point at `manual-tools/v5` (one at v8), and several
  tool notes still cite `stage0-interview v33`. Cross-cutting, left for a separate pass.

## Third round (same day)

Founder rulings: a company another project already has IS added to this project when it fits
(verified against this project's ICP); the website-domain check stays as it is; start building
decisions 1 and 2; agent instructions change **only in new versions** — so the in-place v38 §7b
edit was reverted (v38, tool_notes, manual-tools v11, v65 pins and the registry digest are back
to the turn-budget session's bytes; digests `0db35b21…`, `d76c280e…`, `9b961077…` verified).
Build plan written: `docs/superpowers/plans/2026-09-28-arv2-discovery-exact-count-and-find-more.md`;
§4 holds four design choices awaiting founder sign-off before code (standing rule: design
decisions inside an approved goal are surfaced first). No code written for the rebuild yet.

## Fourth round — the rebuild (same day)

Founder go: "proceed with the implementation" — recommended answer taken on all four plan §4
choices (search 2 only when Exa filled search 1; turn-budget bundle committed first as
`e431744b7`; the deletions; wall clock per search). Cross-project ruling: an account of another
project IS verified against this ICP and added here. Website-domain check unchanged.

- Engine: migration `97427f8eb3d6` (`arv2_discovery_search`, run loses webset_id / strict_search_id /
  relaxed_search_id / strict_count / relaxed_requested, `not_chosen_before` → `found_before`);
  store search transitions + `project_found_domains` / `project_webset_ids`; Websets client
  `create(exclude_webset_ids)`, `find(external_id)`, `error` on every view/items result, message-
  first error text, `add_search` deleted; driver = three sequential searches, per-search wall clock,
  cross-project account reuse; launch identity = `request_key` (tool: `action_ref`; CLI:
  `--request-key`, default fresh); `CLUE_ARV2_DISCOVERY_STRICT_COUNT` removed (settings, .env,
  .env.example); CLI `--relaxed-pass` removed; `read_discovery_run` schema unchanged
  (`relaxed_requested` = the run made the relaxed search).
- Agent: `head-of-abm@v66` = v65 + `stage0-interview@v39` (§7b as approved) + `manual-*@v12`
  (discovery + glossary chapters rewritten; tools regenerated); tool notes updated; builder
  MANUAL_VERSION v12 / PROFILE_VERSION v66; registry digest `51aaa4de…`.
- DBs: `clue_dubai` upgraded to `97427f8eb3d6` (4 legacy runs backfilled as search 1). Throwaway
  `clue_dubai_disctest` holds the DB test runs. Migration up→down→up proven on an empty DB and on a
  copy of clue_dubai (webset ids + asks survive).
- Pre-existing reds confirmed on clean HEAD: tests/api/test_project_context_files_db.py::
  test_status_facts_are_workspace_scoped_and_keep_person_only_accounts (research-job FK) and
  tests/api/test_frontend_bulk_actions_discovery_db.py (401), plus the earlier offline ones.
- Owed: the live acceptance run (founder-triggered, spends money); the 16 stale `manual-tools/v5`
  pointers in other tools' descriptions.
