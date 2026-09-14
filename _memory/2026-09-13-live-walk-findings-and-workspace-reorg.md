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

## Plan 2b proven (2026-09-14) — the operating manual, `7d4c2def9..HEAD`

Eight commits (SDD, Opus implementers, controller-reviewed; order 1→3→2→4→5 by ruling): `e6b87359e`
the builder (`clue_agents.manual` renders; `clue_api.manual_build --write|--check|--link` is the
toolbelt-aware entry point because agents may not import clue_api; `make manual` / `manual-check` /
`manual-link`) and the four generated chapters (`manual-tools` 79 KB: 21 tools in profile order with
descriptor inputs/outputs, `#:` vocabularies lifted from the model source, refusal codes and next moves
from the founder-review file `platform/agents/catalog/manual/tool_notes.yaml` (119 codes);
`manual-fields` from the committed `fields.json` snapshot, 161 keys; `manual-errors`; `manual-limits`
with every number imported); `f3a4cf475` the implementer's builder memory note; `738496a81`+`2251a4dd6`
the eleven hand-written chapters (each with a `<!-- sources -->` line; the two authority chapters mark
every rule `(enforced)`/`(asked of you)`); `b7a3d5386` ten drift guards (`tests/agents/test_manual_drift.py`:
generated chapters current, tool coverage, enum ownership, fields, links, pin + map ≤ 4 KB, refusal codes
both ways, builder pin, markers, front matter); `fc2dbfd78` profile v54 pins v31 + prompt v10 + fifteen
chapters, prompt v10 drops the withheld delegation paragraph and points at the manual, skill v31 points
at chapters (and drops the false "platform refuses an unrouted finalization" claim), ten tool
descriptions end with their manual anchor (no digest moved), the `--link` pass rewrote 146 tokens;
`fade39b90` the L1 identity budget raised 24,000 → 40,000 bytes on the production conversation and the
Stage-0 trial (policies v2) with an offline guard (prompt ≤ 80% of L1), after the first live turn on v54
failed at context assembly (resolved prompt 23,727 B, 273 B of headroom). Recipe stays 26.

**Founder decisions ruled provisionally (all four are text-only to overturn; each names the chapters):**
(1) routing-receipt guard is trial-only, production refuses nothing — `manual-turn`, `manual-gates-authority`,
skill v31 §6; (2) `assumptions` are stored and never shown — `manual-turn`; (3) no spend gate on the three
ARV2 launches; the ICP pin and product set are the only authority; persona synthesis and a design leg's
first message spend without a gate — `manual-gates-authority`, `manual-siblings`; (4) `route_key` stays free
text; the chapter lists the closed vocabulary `(asked of you)` — `manual-documents-decisions`.
**Founder content review is pending on the committed v1 chapters** (ruling M9): a correction re-mints
the chapter as v2 and the profile as v55.

**Live walk** (thread `thr_fd34ee23…`, v54, after the L1 fix): "what do outreach unsafe and sensitive
mean?" → `read_file` of `manual-claims` and a correct distinction; "what do suspended and needs_review
mean?" → `manual-accounts-research` (paused by a worker restart vs failed awaiting a human; pause/resume
human-only); "can you approve the budget?" → `manual-gates-authority`, a correct refusal naming the
human-only `adjust_budget`, the two gates it can open and the absence of a budget gate. Zero repair
lines; `record_interview_answer` the only governed node per turn. The first attempt on v54 (turn
`3b443795…`) failed before the model with `required l1_identity context exceeds its hard layer budget`;
it remains at `requested` with a failed fleet task, superseded by the later turns.

Deferred: prompt v10's front-matter summary still mentions delegation; `record_interview_answer` has a
frozen fallback description; the C8 trial keeps the fifteen chapters while withholding the Stage-0
skill; 255 B of disclosure headroom under the 4 KB heuristic and `tool_notes.yaml`'s "taught by" version
is hand-maintained; a turn assembled under policy v1 and re-driven after the bump would raise on its
context receipt id; chapter lengths exceed the 2–6 KB aim (gates 10.5 KB, glossary 16 KB).

## Plan 3 landed (2026-09-14) — the versioned project root, `7a4bd36cb` (base `0c4be79b8`)

Six commits (SDD, Opus implementers, controller-reviewed, tasks in order 1→6): `da7e4e7c3`
`clue_agents/bridge.py` — `AsyncBridge`, a process-local loop so a *sync* deepagents backend can await
(sync `run`, timeout → `BridgeTimeout`, re-entry → RuntimeError); `93451dabf` the versioned mount
(`MountMode "versioned"`, `MountRequest.project_writer: VersionedRootWriter | None`,
`clue_agents/versioned_root.py` with `VersionedWriteOutcome`/`VersionedWriteRefused`, backend
`written_documents`; `edit_text_sync` reads the library bytes and writes through the writer,
`materialize_bytes` refused); `1158039bb` `clue_api/project_root_writer.py` + `write_project_persona`
in `arv2/project_documents.py` (one transaction per write on the bridge loop's own engine — never
`clue_db.transaction`, whose engine belongs to the serving loop); `391f6adcb` the wiring — one
`ProjectRootWriter` per turn, finalize merges the turn's written documents into `domain_refs`, object
types `project_document` / `project_icp_document` / `project_persona_document` → cards
"Plan" / "ICP" / "Personas"; `9db12cef6`+`7a4bd36cb` the grant — skills `icp-authoring@v1`,
`persona-authoring@v1`, `plan-authoring@v1`, `stage0-interview@v32`, `head-of-abm@v55`,
`recipe0-stage0-v27.json` with `CONVERSATION_RECIPE_VERSION = 27`, and the operating manual re-minted
at v2 across all fifteen chapters (`MANUAL_VERSION = "v2"`, `PROFILE_VERSION = "v55"`;
`SKILLS_BLOCK_MAX_BYTES` 4096 → 4608). Recipe 27 is promoted on the lane DB (workers' boot seeding).

**Version ladder:** profile `head-of-abm@v55` / skill `stage0-interview@v32` / `recipe0-stage0-v27.json`
(`CONVERSATION_RECIPE_VERSION = 27`) / manual `manual-*@v2` ×15; prompt stays v10. v54 / v31 / recipe 26
/ manual v1 are byte-untouched for replay. `project` joins the profile's `writable_prefixes`.

**The mount.** `project/` opens as `mode="versioned"`: read-through from the compiled project library,
write-through to `ProjectRootWriter`, with `versions` loaded from the tree's `index.json`
(`ProjectLibraryIndexCard.files[].version`, path minus `project/`; `version: null` = compiled). The
expected version is the mounted file's version, never a model argument. After an accepted write the
library is re-materialized and the mount's `reopen` always opens the **shared** library (never a pinned
replay tree), so the agent reads back what it wrote.

**Kinds by folder** (ruling P3-a — the platform's existing paths, amending spec §4.1/§4.4's `personas/`):
`audience/icp-<key>.md` → ICP proposal, born `proposed`, refusals are the ICP writer's own
(`icp_key_invalid`, `icp_front_matter_invalid`, `icp_key_taken_by_brand`, `icp_key_taken_by_project`,
`derived_from_not_found`, `icp_document_version_race`); `audience/persona-<key>.md` → persona, born
`ready`, **pinned ICP key only** (`icp_not_pinned`, `persona_front_matter_invalid`); `plan.md` → plan,
born `ready` (`revision_conflict: plan.md is at version N, you read version M — read it again`,
`body_empty`); `status.md` / `decisions.md` / `index.json` / `artifacts/**` → `compiled_file_read_only`;
anything else → `unknown_project_path` (the message names the three writable paths). The backend
surfaces a refusal as the write tool's `conflict: <code>: <message>`.

**Retired in words, not in code** (standing rule): `author_icp_document@1`, `write_project_document@1`,
`request_persona_synthesis@1` and the personas-only `onboarding_run.kind` entry point are ungranted at
v55 and absent from recipe 27, still registered and intact for replay of receipts pinned to recipe ≤ 26.
Docs: the module docstring of `platform/api/clue_api/persona_request_tools.py`, two retirement notes in
`platform/api/clue_api/arv2/README.md`, and `docs/specs/ARV2-ONBOARDING-PLAN.md` § "Addendum 2026-09-14".

**Rulings (controller, from the SDD ledger):**
- **P3-1** `bridge_transaction()` does *not* live in `clue_agents/bridge.py` — agents may not import
  `clue_db`; the transaction factory over the bridge's own engine lives in `clue_api/project_root_writer.py`.
- **P3-2** Task 2 adds `MountMode "versioned"` and `MountRequest.project_writer`; the factory opens
  `project` as versioned when a writer is given, loading versions from the tree's `index.json`.
- **P3-3** The versioned mount's `reopen` always opens the shared library, never the pinned replay tree —
  after a write the honest view is the refreshed library.
- **P3-4** `ProjectPersonaWrite` carries `brand_id` and the whole `document_text`; the writer parses and
  re-stamps front matter like `author_icp_document`, refusing `persona_front_matter_invalid` / `icp_not_pinned`.
- **P3-5** For `plan.md` the root writer strips a leading YAML front-matter block and passes only the body —
  the platform owns the plan's front matter.
- **P3-6** The finalize merge uses kind-bearing object types (`project_document`, `project_icp_document`,
  `project_persona_document`), titled "Plan" / "ICP" / "Personas"; the frontend never reads `object_type`.
- **P3-7** Versions are skill v32 / profile v55 / recipe 27; the prompt stays v10.
- **P3-8** The operating manual re-mints at v2 ×15 (a catalog version is immutable and v54's pins must keep
  resolving); eleven hand-written chapters lose the retired tools' sentences, four are re-rendered.
- **P3-9** The three addresses leave `RECIPE_0_TOOL_ADDRESSES` and recipe v27; the v24/v25 history tests
  become "retired at v27" assertions; a new test asserts v27 = v26 minus exactly the three.
- **P3-10** Test discipline as plans 1–2b: offline suites without `.env`; DB suites only on the lane DB with
  `--ignore-glob='*_live.py' -p no:cacheprovider`; never `*_live.py`; no `make check`.
- **P3-11** The recipe is promoted by the workers' boot seeding (`seed_system_recipes`), no hand SQL.
- **P3-12** `SKILLS_BLOCK_MAX_BYTES` 4096 → 4608 accepted — the heuristic predates three extra skill lines;
  the binding gate is the 80% L1 budget (7,337 B spare).
- **P3-13** The trial surface discloses the three document skills while mounting no writable `project/` —
  accepted as the same over-description the manual already carries there; noted in the test docstring.
- **P3-a** (from the plan) Persona documents live at `audience/persona-<key>.md`, the platform's existing
  path, amending spec §4.1/§4.4's `personas/` folder.

**Live proof — owed to the controller** (to run on the restarted stack): a new thread → "write the
personas" produces a `write_file` at `project/audience/persona-<key>.md` and a `ready` row; "write the
plan" produces `plan.md` v1 and the Plan card; edit the plan through the human PUT (v2); "add a step" in
a *new* thread produces v3 that keeps the human's edit.

**Deferred (ledger minors):** a `BridgeTimeout` is an unknown outcome (the writers' replay keys make a
retry idempotent); a refresh/reopen failure *after* a landed write surfaces as `conflict:` (the write is
durable, "read again" is honest); `MountRequest.__eq__` includes the writer instance; a persona/plan write
whose `turn_id` is not an `agent_turn` row raises a raw FK IntegrityError rather than a typed refusal;
`refresh()` rebuilds the whole library per accepted write; a written kind absent from
`PROJECT_DOCUMENT_OBJECT_TYPES` is durable but cardless (logged loudly); `tests/execution/test_recipes.py`
carries a pre-existing v16–v21 gap and lane-DB row collisions, and the design-profile model-id failure is
the pre-existing env-dependent one.
