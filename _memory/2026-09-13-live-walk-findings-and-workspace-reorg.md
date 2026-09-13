# 2026-09-13 — live walk findings (plan 4 in anger) and the workspace reorganisation rulings

**Lane:** `research-streaming`, worktree `san-salvador`, stack on profile v49 / recipe v26.
**Branch state:** rebased onto `origin/brand-context-polish` (`dedd196b2`, one alembic head).

## The failed turn (thread `thr_befd7bf520e95e73bf66eac9f189d355`, 05:23 UTC)

The founder asked "what was researched about Arthur Direct Care?"; the turn died `runtime_error`.
Worker logs (`/tmp/san-salvador_fleet_worker_{2,3,4}.log`) show five distinct causes:

1. **`read_discovery_run@1` fails its own output contract, every call.** `DiscoveryCandidateView.pass_`
   has only `serialization_alias="pass"`; the tool dumps by alias and the toolbelt runner re-validates
   the JSON against the same model, which accepts only `pass_` → "Field required" ×8. The offline
   test asserts on the dumped dict and never goes through `validate_tool_result`. **Defect, ours.**
2. **`read_account_research@1` claims read exceeds the 16 KiB governed-receipt bound**
   (`clue_agents.execution.GovernedOperationReceipt`, `reference_values` > 16_384 bytes). Bounds
   MAX_CLAIMS=120 / EVIDENCE_CHARS=240 / BODY_CHARS=6000 were set without that cap; Arthur Direct
   Care's 72 claims overflow it. The overview path (6 sections × 6000 chars) has the same exposure.
   **Defect, ours.**
3. **`overview_not_written` was honest.** Overview blocks are written lazily by `ensure_page` on the
   first account-page view (a spend path). Of five "Researched" accounts only two have overviews.
   "Researched" = research job completed, not overview written. Decision open: render at research
   completion.
4. **The agent guessed `field_prefix="firmographic"`** → `no_claims_under_prefix`. Real prefixes on
   the account: `core.*`, `account.icp_fit_verdict`, `account.committee_candidate`,
   `account.resonance`, … The refusal names no prefixes; the tool description only shows one example.
5. **The turn died because `_MAX_GOVERNED_TOOL_FAILURES = 3` is per turn across all tools**
   (`agent_runtime_wiring._tool_failure`). Five parallel account reads → fourth refusal raised
   `RuntimeError`, LangGraph cancelled the two in flight (asyncpg `CancelledError`). Pre-existing
   runtime rule; honest read refusals should not spend it (ruling W10 below).

DB facts used (lane DB via `CLUE_DATABASE_URL`, TCP 55040): Arthur Direct Care
`4da436a7-0936-4e19-b858-4f8c9f25ea3d`, 72 claims, account job `completed`, 0 `display_block` rows;
Aura Psychiatry / Preferred Primary Care have 6 live overview blocks each.

## The workspace as it is today (verified on disk)

`CLUE_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces-san-salvador/<ws>/<project>/<execution>/`
— one directory **per turn** (execution id derived from the turn id; turn id = uuid5(workspace,
thread, idempotency key); thread id = uuid5(workspace, operation id) at create-thread or Home
bootstrap). Layout `.deepagent/ inputs/ context/ work/ delegations/ outputs/`; inputs and context
are materialized from rows filtered by workspace/project (brand knowledge ≈ 330 KB copied per turn);
thread history (L6) is read from `agent_thread_message`, never from files; `outputs/` snapshots to
artifacts at close; retention 24 h; quota 200 files / 10 MiB per turn. Isolation is per workspace
(tenant), enforced by fd-anchored `O_NOFOLLOW` walks, 0700 dirs, segment validation, ambient
`workspace_id` from the membership-proved principal (`WORKSPACE_FORBIDDEN` on mismatch).

## Rulings taken (founder, in discussion) → `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md`

W1 four levels (workspace library / project library / thread scratchpad / turn); W2 the project
library is a materialized view of rows, mounted as a versioned root (read-through, write-through);
W3 pinned/current version only in view; W4 artifacts by reference; W5 thread scratchpad persists;
W6 (option B, chosen later the same day) the project is written with deepagents' own `write_file`/`edit_file`
over a versioned root — no new governed tool — folder decides kind, one skill per kind; W7 the pin gate stays human; W8 personas written by the Head of ABM, not via an
onboarding run; W9 reads page (`offset`/`limit`/`next_offset`) and spill to `reads/` above the
receipt bound, plus `read_claims@1` and `read_artifact@1`; W10 honest read refusals do not spend
the failure budget; W11 brand knowledge mounted once per version. Constraints kept: Postgres is
the truth, versioned documents, human pins, no agent claim writes, replay pins, DSAR, 16 KiB
receipts. Build order in the spec §6; the two contract/receipt defects ship first as a hotfix.

## Owed

- The plan-1…4 live walk remains owed; the checklist given to the founder this session (27 items)
  supersedes the per-note lists in scope but not in SQL.
- Hotfix on the current tools before the reorganisation: `pass` alias on input, byte-bounded reads,
  prefixes in the `no_claims_under_prefix` refusal, W10 in the runtime.
- Decision: render the overview at research completion vs on first view.

## Plans drawn (2026-09-13, later) — `docs/superpowers/plans/2026-09-13-lane-plan-index.md`

Lane 1: `2026-09-13-read-tools-hotfix.md` (plan 0), `2026-09-13-workspace-multi-root-backend.md`
(1), `2026-09-13-workspace-libraries.md` (2), `2026-09-13-versioned-project-root-and-document-skills.md`
(3), `2026-09-13-paged-and-spilled-reads.md` (4). Lane 2: `2026-09-12-plan-tab-frontend.md`
(re-activated; auto-open keyed on the plan part, not the tool call) and
`2026-09-13-markdown-editor-toolbar.md`. Version ladder: skill v27…v31, profile v50…v54, recipe
v26 → v27 (plan 3 drops three tools) → v28 (plan 4 adds two reads). Ruling P3-a in plan 3:
personas keep the existing `audience/persona-<key>.md` path (the spec's `personas/` folder was
illustrative). Not started; the hotfix is first.

## Operating manual study (2026-09-13, evening) — `docs/superpowers/specs/2026-09-13-head-of-abm-operating-manual-design.md`

Five parallel read-only inventories (7,266 lines, every claim `file:line`) now live under
`docs/superpowers/research/2026-09-13-head-of-abm-manual/` (A tools, B context/workspace, C domain
model, D authority/gates/screens, E runtime/siblings). Headline: 21 tools granted, 16 taught, 3
dead (`get_research_view@1` flag-off + pins `project_run`; the directive pair feeds ungranted
consumers) and `submit_ingestion@1` unwired; 22 domain terms with no word; status vocabularies
only in `#:` comments; the 161-field registry surfaced nowhere; 27 runtime facts never told (3-refusal
budget shared and per-parallel-call, 2 finalize repairs, 16 KiB receipt, 52 supersteps/300 s, only
`finalize_turn.user_message` reaches the human, `status.md` frozen per turn vs live reads);
prompt-only rules (never widen the set, routing-receipt guard is trial-only); prompt teaches
delegation the surface withholds; `product/catalog.md` carries no product ids. The design proposes
`.deepagent/manual/<version>/` (13 chapters, generated where code is the source, hand-written where
judgment is), disclosed through the capability map, cross-referenced by path, drift-tested,
pinned in the profile; §7 maps 17 defects to lanes; §9 lists five founder decisions. `.superpowers/`
added to `.gitignore` (it was not ignored).

## Hotfix proven (2026-09-13, night) — lane-1 plan 0 landed, `4f1421cbf..HEAD`

Six commits on `research-streaming` (SDD, Opus implementers, controller-reviewed): `0b1975628`
(`read_discovery_run` accepts the schema's `pass` on input; `serialize_by_alias` so the runner's
canonical form spells it `pass` too), `bbe859ed8` (claims paged by `offset`/`next_offset` under a
12 KiB budget measured in the receipt's own encoding; a long overview clipped and flagged;
`offset_past_end` / `offset_not_paged` refusals), `653f7e7fb` (`prefixes` = the account's servable
claim families, gate before filter; `no_claims_under_prefix` lists them; the Task-1 `frozen=True`
class kwarg dropped for mypy), `2c89ebee4` (skill v27 §7c + §1 onboarding pointer, profile v50,
registry + `composer_context` at v50, the project-conversation framing sentence rewritten), and
`423e5bb40` (W10: a `PreconditionFailed` from a READ tool is unbudgeted — neither counts nor
raises; `agent.tool_repair` carries `budgeted`). Recipe stays 26. Gates: ruff/lint-imports clean
on the touched files; offline 4-file run green except the pre-existing design grok-vs-terra red;
DB read-tools suite 23/23.

**Live walk on the lane stack (v50 workers, started 20:23 IST).** The signed-in test workspace
(`ws_2875e9e3…`) does not hold Arthur Direct Care (that row is in `ws_869a9f51…`), so the re-ask
used the equivalent researched account of project `prj_82aef3f5…` — Prevea Health, 79 claims,
overview written — in the project's second thread `thr_fd34ee23…`:

- "Can you tell me what was researched about Prevea Health?" → turn `19e3d6a5…` on
  `head-of-abm v50`: `read_project_accounts(query="Prevea Health")` → `read_account_research`
  overview (10 194 B) → claims offset 0 (13 034 B) → offset 17 (13 356 B) → offset 37 (11 734 B,
  `next_offset` null) → `awaiting_input` in 102 s. The answer cites status, held-back count
  ("Eighteen outreach-unsafe claims were held back"), the committee, and says where the file is
  weak for DAC Agent. Zero `agent.tool_repair` lines.
- "What did the last discovery run for this project find?" → turn `d0e7a77e…`:
  `read_discovery_run` (5 181 B) completes and the answer lists all 34 candidates with their
  pass verdicts and fits; `awaiting_input` in 67 s.

```
SELECT n.tool_name, count(*) FROM execution_node n WHERE n.kind='tool'
  AND n.tool_name IN ('read_account_research','read_discovery_run')
  AND n.created_at > now() - interval '1 hour' GROUP BY 1;
read_account_research|4
read_discovery_run|1
```

Not exercised live: `overview_not_written` (both researched accounts here have overviews) and a
wrong `field_prefix` (the model never guessed one — §7c says never invent a prefix); both are
proven by the DB tests. Stack note: `next dev --hostname localhost` binds `[::1]:3020` only, so
the headless `/browse` Chromium (IPv4) got a connection error; the frontend was restarted with
`--hostname 0.0.0.0` for the walk (the runbook script still starts it the old way; the founder's
own browser falls back to v4/v6 and never noticed). The `up` script also aborted once on
`rm -rf apps/frontend/.next` racing the dying next-server — re-running the frontend step by hand
was enough.

Deferred from the SDD ledger (for the final review / the lane backlog): runner-wide `by_alias`
in `validate_tool_output_references`; one pathological claim value can still exceed the receipt
(plan 4's spill); overview clip measures bytes and clips characters; the `GovernedToolFailure`
body still says "correct … and call again" for an unbudgeted read refusal (manual-errors
chapter); `arv2/README.md:1863` still names v49; the pre-existing design profile red resolves to
a doubly-prefixed `openai/x-ai/grok-4.6`.

## Plan 1 proven (2026-09-13, night) — thread-rooted workspace, `9b364ae0a..HEAD`

Nine commits (SDD, Opus implementers, controller-reviewed): `24650d9f2` mount table on the backend
(`WorkspaceMount`/`MountMode`, reserved first segment → own anchored fd, read-only or read-write, one
quota); `234b889b5` + `20feb88e0` the factory rooted at `<ws>/projects/<project>/threads/<thread>/`
(`WorkspaceIdentity.thread_id`, `MountRequest(brand, project_library)` honoured, one live lease per
thread, `lease.release()` in a `finally` at all five acquire sites, purge/erase by thread, the
workspace thread segment = the turn row's `thread_id` everywhere); `b23af9e88` per-turn materialize
(`reset_materialized_trees`, per-lease `materialized` guard, verify-or-rebuild, `snapshot_outputs
(empty_after=True)`); `8e919c06d` + `64030afc6` + `8d26b12a8` the runtime empties outputs at finalize,
profile v51 (readable seven / writable `scratch, work, outputs` / 400 files / 20 MiB) and skill v28
(§1 names `scratch/`), the factory tolerates a partially frozen tree; `447419972` cleanup purges
threads (migration `5e78522ddf48`: `thread_id` column + `thread_purge` action; newest turn terminal and
older than the window, or thread archived; dedupe per newest turn); `5e2557a73` the pin comment.
Recipe stays 26. Layout as landed (ruling R1, amended twice): `_LAYOUT = (.deepagent, inputs,
context, scratch, reads, work, outputs)`; `context/` stays because the assembler writes it; `work/`
stays readable AND writable on v51 because the delegation ceiling intersects a child's workspace with
the parent's on both lists (dropping it silently took the specialists' scratch pad away — measured).

**Live walk on the lane stack** (workers on v51 from 22:11 IST, lane DB at `5e78522ddf48`), thread
`thr_fd34ee23…` of project `prj_82aef3f5…`:
- Turn `357c028b…` ("write a note into scratch/notes.md…"): completed in 90 s on v51; the model wrote
  `scratch/notes.md` (1 024 B, 0600) through the built-in write tool; after finalize `outputs/` is
  empty; on disk the thread directory is `…/projects/prj_82aef…/threads/thr_fd34ee…/` with
  `.deepagent context inputs` at 0500 and `outputs reads scratch work` at 0700.
- Turn `f03c161b…` ("quote the notebook"): same `workspace_root_id` (`awr_f55e31bc…`), completed in
  50 s; `inputs/user-message.txt` held the second message while `scratch/notes.md` was byte-identical
  (sha `20668325…`); the answer quoted the notebook's "Two researched accounts" section verbatim and
  made no governed account read (`execution_node`: `record_interview_answer` ×1 only). Exactly one
  directory under `threads/`.

Stack note again: `next dev --hostname localhost` binds `[::1]` only; for the headless walk the
frontend was restarted with `--hostname 0.0.0.0` (the runbook's `up` worked cleanly this time).
Known: `tests/api/test_client_knowledge_privacy_s4e_db.py::test_dsar_reaches_every_agent_copy…` asserts
whole-table counts and only passes on an empty DB (72 live `agent_tool_result` rows here) — needs a
throwaway DB. Legacy `<ws>/<project>/<execution>/` directories are left in place (ruling R6).

Deferred (ledger minors): flock scope if a read-write mount is ever shared; root `ls` hashes every
mount file; constructor fd ownership on validation failure; a resume that rebuilds `MountRequest`
differently conflicts (fail-closed); `cleanup_recorded` projection has no action filter; the design
profile red is a doubled provider prefix (`openai/x-ai/grok-4.6`).

## Plan 2 proven (2026-09-14, early) — workspace libraries, `09739f3cb..HEAD`

Eleven commits (SDD, Opus implementers, controller-reviewed), run in the order 1→2→3→5→4→6 so every
intermediate state kept the files readable somewhere: `3b236c669` `LibraryTree` (atomic read-only trees
under an anchored parent; one superseded generation kept for in-flight readers; the scope audit accepts
0500 beside 0700); `20dab21d7`+`037de8aae` the brand library at `<ws>/library/brand/<brand>/<version>/`
(content-addressed by the knowledge pin digest; index compiled unbounded and refused if it would omit);
`d1dd28b8c` the project library at `<ws>/projects/<project>/library/` (digest over eight row sources incl.
`project_account`; one version per path with the pinned ICP winning in both scopes; `artifacts/index.json`
by reference through the gallery's own query); `f77603bfa`+`781fd1495` profile v52 (readable +`brand`,
`project`), skill v29, prompt v9 (both onboarding pointers name the `/onboarding` flow); `710f83d2f` the
turn mounts both libraries, the seeds stop, the pin records the library incl. its manifest, replay mounts
a per-turn `pinned-<turn12>` tree only when the live digest moved (removed in the turn's `finally`), the
context card is the pinned manifest at `context/project/project_library_index.json`; `ce74995b7`
`ProjectLibraryRefresher` after the plan write, the human PUT, ICP authoring, the ICP pin, and DSAR
(forced, on both erasure paths; the API process now composes its own factory on the shared root);
`670c76e3d` skill v30 / profile v53 — the brand manifest is `brand/index.json` (the plan's skill text said
`brand/knowledge/index.json`; the first live turn on v52 hit "file does not exist"). Recipe stays 26.
Onboarding synthesis keeps its own `inputs/brand/knowledge/` seeds (own profile/prompt/skill; not on the
mount path). The two seed helpers stay as uncomposed functions with seed-legal defaults.

**Live walk** (thread `thr_fd34ee23…`, project `prj_82aef3f5…`): turn `e1519ad1…` on v52 read
`project/status.md` from the mount ("Accounts in this project: 34" — matches the library; only
`record_interview_answer` as a governed node; pin = 5 library files incl. `index.json`; no `pinned-*`
tree left); turn `303d57ff…` on v53 read `brand/index.json` (24 documents, omitted_count 0) and
`brand/knowledge/company/overview.md` ("# Company overview"). On disk: `library/brand/brd_1703…/
f5fc1189d03aa8f3/{index.json, knowledge/}` (0400/0500), `projects/prj_82aef…/library/{artifacts/,
audience/, decisions.md, index.json, status.md}`, the thread's `inputs/` holding only
`user-message.txt`, `context/project/project_library_index.json` present. The API twins booted with the
workspace root (the dev-stack script exports it to them).

Numbering note for plan 2b: it planned skill v30 / profile v53; those are now taken (v31 / v54 next).
Deferred (ledger minors): a microsecond "not materialized" window between the two renames; the plan-1
mount open does not apply LibraryTree's stricter 0500 audit; no reclamation of superseded brand
versions; cross-process first-write race on an absent brand version; a running discovery run's tallies
refresh when it settles; brand-vs-project same-path version comparison is cross-scope; the chat-router
pin hook has no test of its own; `erase_artifacts` refreshes only projects of the turns it touched;
whole-table-count tests (privacy files, `test_production_context_s3_db.py`) need a throwaway DB.
