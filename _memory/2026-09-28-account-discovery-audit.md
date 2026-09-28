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

## Fifth round — stale manual pointers (UNCOMMITTED by founder instruction)

Founder: fix the stale `Manual:` pointers, do not commit; live run next; commit once it passes.
- `clue_agents.manual.tool_manual_link(name)` builds each governed tool's closing pointer from
  `MANUAL_VERSION`; all 16 hard-coded pointers (15 at v5, 1 at v8, plus the two set to v12 by hand)
  now call it, so a manual re-mint moves every pointer. New guard
  `tests/agents/test_manual_drift.py::test_every_tool_description_points_at_its_own_entry_in_the_current_tools_chapter`
  (red-proved with a v5 pointer on run_python).
- manual-tools v12 regenerated (10 granted tools' pointers only); v66 pin `64518b15…`, registry
  digest `fb50edbe…`. v12/v66 amended in place: committed in bec02ba77 but never run anywhere.
- `tests/api/test_arv2_read_tools.py` read_claims pointer assertion now uses the helper.

## BLOCKER found 2026-09-28 ~19:05 IST — the 55040 Postgres is gone

`clue-pg-istanbul` (port 55040; clue_dubai, clue_jerusalem-v1, clue_san-salvador and ~40 lane
DBs) no longer exists — not in `docker ps -a`, nothing listens on 55040, no named volume left.
Also gone: clue-pg-{san-salvador,trenton,damascus,fredericton,addis-ababa}; clue-redis (6379) is
Exited. Not done by this session (it last used the server ~2 h earlier, successfully). Docker
kept no destroy events. Dangling volumes are three small PG16 dirs (46–125 MB) — not istanbul.
Only backup found: ~/clue-db-backups/clue_colombo-demo-success-2026-08-29.sql.gz. The live run is
blocked on a database; nothing was recreated pending the founder's call.
- Correction (founder, same evening): the founder deleted clue-pg-istanbul themselves.
- Full container/volume inventory (checked, not assumed; stopped volumes read via throwaway
  copies, since removed): papeete (55040) and san-diego (55050) never started, volumes empty;
  clue-postgres (dar-es-salaam volume) = 27 DBs, all 0 tables; dangling volumes 77b0/fd69 empty,
  7a76 (`clue`, a1c5b9842f0e) and e4df (`clue`, 44039cb83844) old schemas with no ICP-pin table;
  narrative-owner-test = 4c916b02ed9b, 0 pins; lome / jerusalem-v1 = empty `clue`. Only DBs with a
  pinned ICP: the zafran/premier research DBs. The single-DB zafran containers and
  finalization-repair are at f3eb43c7808f (another branch's revision, not on this branch).
  Branch-compatible with pins: clue-zafran-quality-live → clue_premier_r24_20260928
  (4c916b02ed9b, gi-specialty-ambulatory-groups), clue_zafran_r18_20260926 (4c916b02ed9b,
  clue-abm-buyers), plus older-revision ones that migrate forward.

## Sixth round — fresh-DB attempt, then stopped (founder: test after merging instead)

- Started clue-pg-papeete (:55040), created + migrated `clue_dubai` (fresh, 376 tables), moved
  this workspace's stack to 3025/8015/8025/8035 in .env + apps/frontend/.env.local (jerusalem's
  stack holds 3028-series; backups /tmp/dubai.env.bak, /tmp/dubai.env.local.bak), copied lome's
  lumen-api-helper (identical Rust source, built after the last crates change), `npm ci`, added
  untracked `scripts/dev_stack_dubai.sh`. Founder then said not to make the DB (testing after the
  merge to research-streaming): papeete stopped again; `clue_dubai` still exists inside it.
- Real bug found on the way (UNCOMMITTED fix): fresh-DB fleet workers cannot boot — recipe0-stage0
  v19 and v22-v28 pin the retired `open_design_leg@4` and fail promotion (`unknown_tool`,
  `version_mismatch`); all eight confirmed by running the worker's real startup with a
  collect-all seed on a scratch DB. Moved them to HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES (the
  v16-v18 precedent); scratch re-run: 0 failures. test_recipe_contracts' eight adjacency checks now
  assert replay-only membership (the v29 pattern); recipe tests green.
- Still uncommitted: the manual-pointer fix and this recipe fix. The live discovery run is owed
  on the merged branch.

## Seventh round — merged the research line, resumed the fresh-DB setup (deployment day)

- Founder: merge `codex/ai-ark-committee-discovery` (+ local) and continue the setup to find what
  breaks. No such branch; the match is `codex/ai-ark-committee-discovery-spec` (local a08daceb9 =
  remote 3918e1215 + 1). Pointer fix (5d9db9ffb) and fresh-DB recipe fix (d850ab23a) committed
  first; the other session's dirty `account_research_catalog.py` edit was set aside
  (/tmp/account_research_catalog.py.dirty-backup) and is byte-identical to the merged file.
- Merge `541268994`: 12 conflicts. v66/v39/manual v12 + tool_manual_link kept; their
  continuation_config plumbing, thin-response retry test and turn-budget note closure kept;
  manual-limits v12 regenerated (their reworded finalize message), v66 re-pinned, registry digest
  `1faebe0e…`; alembic join `d9f29ca9ca66` (97427f8eb3d6 + f3eb43c7808f). The v65 bundle was
  byte-identical on both sides. Their 8 `.artifacts/**/*.py` eval scripts fail ruff (not product
  code). `.env` given the 5 missing LUMEN_INGESTION_* keys.
- clue_dubai (papeete :55040) migrated to d9f29ca9ca66; stack started via
  scripts/dev_stack_dubai.sh on 3025/8015/8025/8035.
- Post-merge breakage found by the full offline run (48 failures; 19 pre-existing, 29 new):
  28 were ONE merge defect — both branches inserted `TurnBudgetMiddleware` into the Deep Agent
  middleware tuple and git kept both; LangChain refuses duplicate middleware, so every agent turn
  would fail at graph build. Fixed in e684d1c87 (runtime.py now == the research line's). The 29th:
  the research line set `CLUE_ARV2_DISPLAY_MODEL=meta/muse-spark-1.3` in .env.example without
  moving the Settings default; default now follows (founder's Muse request). All 29 green. The
  other 33 turn-budget files were checked byte-equal to the research line (no other doubling).
- This workspace's .env model keys aligned to Muse Spark 1.3 (was Grok/Luna, copied from jerusalem
  before the switch); backup /tmp/dubai.env.bak2. APIs + workers restarted to load the fixes.
