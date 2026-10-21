# ARV2 v26 — 04. Implementation specification, W0–W4

**Lane L6 of the v26 document set. Status: reconciled draft, 2026-10-07 (round 2).** Written
against main `fa4bed77b`. Every `path:line` below was read in this checkout or is 02/03a's
corrected citation. This document supersedes §4–§5 of
`docs/superpowers/plans/2026-10-06-account-research-v26-cost-and-speed-plan.md` (the plan).
**Authority (RECONCILIATION-RULINGS.md R1):** 01/01b are the evidence authority, 02/03a the code
authority, 03 the design authority; 04 follows 03 line by line except where the rulings say 04's
decision won — R2 (two recipe integers), R11 (the contact page as a research-kind continuation),
R12 (the extractor as a leaf call), R13 (`acquire_research_evidence@2` minted once with the r27
shape). Where this document names a mechanism 03 states differently, the ruling that settles it is
cited in place.

**Binding rulings (2026-10-07) this spec implements and never re-opens:** every buying-committee
contact gets full research (no light/deep tiers); the account and all its contacts start together
at approval; the agent keeps its investigative follow-ups through candidate-returning tools and the
rule table is a floor; v26 is a new recipe/profile on the existing governed runtime; `.env.example`
parity for every setting at the moment it is introduced; Alembic hash ids and one head; every change
reversible without a revert (a flag or a recipe gate); no code counts words in agent prose.

---

## §0 How to read this document, the decisions it makes, and the ones it cannot

### 0.1 Owners, effort, gates, test tiers

- **Owner.** `A` = Aryan per `docs/specs/ARV2-WORK-SPLIT.md` §1.2: `alembic/**`, `libs/**`,
  `platform/api/clue_api/*_wiring.py`, `fleet_main.py`, `agent_registry_wiring.py`,
  `platform/agents/clue_agents/**`, `platform/fleet/**`, `platform/execution/**`, profile re-mints,
  merges. `L` = leaf code on a task branch `task/<id>-<slug>`: modules under
  `platform/api/clue_api/arv2/`, prompts/skills/resources under
  `platform/agents/catalog/research-quality/`, scripts, tests. An `L` item that adds a setting adds
  its `.env.example` line; it never changes an existing one.
- **Effort.** S ≤ ½ day, M ≤ 2 days, L > 2 days.
- **Gate vocabulary.** *all* = every recipe including v25 jobs in flight; *r26* = keyed on
  `input_refs.quality_recipe_version >= 26` (the week-1 mint); *r27* = `>= 27` (the W3 mint);
  *flag* = an operator setting with `.env.example` parity.
- **Test tiers.** *offline* = `make check` (`uv run pytest`, `pyproject.toml:136-138`). *DB* =
  tests on `tests/claimstore/conftest.py` fixtures (`require_claimstore_db`, `rollback_conn`,
  `run_async`), which skip without `CLUE_DATABASE_URL` (`conftest.py:57-61`). *smoke* =
  `make db-smoke` (`Makefile:94-97`). *replay* = the frozen-pool replay (§7.3), marked
  `@pytest.mark.replay`; the marker is registered under `[tool.pytest.ini_options] markers` in
  `pyproject.toml` so `make check` neither warns nor runs it (Q54).

### 0.2 Decision (R2): two recipe integers, one program

A tool's input/output *shape* change moves the sha the profile pins (03a §2.1;
`agent_execution_wiring.py:1420-1434` refuses a mismatch), so W1-2/W1-3/W1-5 are new tool
versions pinned by new profile folders — a mint; prompt/skill changes (W1-9/12/14) are a mint too.
**Recipe 26** = the week-1 mint (profiles `v26`/`v26-person`, `recipe-v26.json`,
`launch-v4-r26.json`); `CURRENT_RECIPE_VERSION` becomes 26 on day 4 of week 1. **Recipe 27** =
the W3 pipeline (`v27`/`v27-person`, `recipe-v27.json`, `launch-v4-r27.json`), selected per
workspace by P5 and promoted to the default only after RC-2 passes twice. Code gates say `>= 26`
or `>= 27`; 03's "recipe ≥ 26" pipeline gates read `>= 27` here (R2; 03 §9 adopts this).

### 0.3 Decision: the recipe a launch pins is a setting (P5)

No env selects the recipe today (`quality_catalog.py:14`; `account_research_launch.py:1177-1200`
reads `CURRENT_RECIPE_VERSION`). P5 (§2.5) adds the selector 03 §9.1 describes, with 04's three
lines (review A C2; R7 adds them to 03 §10).

### 0.4 Decision (R13): `acquire_research_evidence@2` is minted once, in r26, with its final shape

`AcquireResearchInput2` gains `purpose` and `follows` (03 §3.6.3; review A C6 — AT-9 is computed
from `follows`); `AcquireResearchReceipt2` carries `candidates: tuple[Candidate, ...]` (empty until
W3-23) and the ledger entry; `Candidate` (W1-5) is **final at the r26 mint**, including
`entities[]` (R9) and `follows`. W3 changes no tool shape.

### 0.5 Decision (R11): the deferred contact page is a research-kind continuation

The display kind's handler writes Luna blocks through `ensure_page` (`display/fleet_handler.py:
131-145`); the frontend never serves Luna blocks for a subject with a quality context
(`frontend_read/display_pages.py:349-381`); the page writer is composed only in the research
handler (`account_research_driver.py:2478-2480`). So P1 reuses the display kind's *properties*
(idempotent per subject/page, `reopen_terminal=True`, priority −80) on the research kind's
`handle()` dispatcher (`account_research_driver.py:518-519`). 03 §3.8/§6.1 align (R11).

### 0.6 Decision (R12): the extractor is a leaf call, not an `AgentRole`

`structure_material` precedent (`structuring_client.py:1187-1213`); model/effort from
`RESEARCH_EXTRACT_AGENT_MODEL` / `_EFFORT` read as the page writer reads its pair
(`page_writer_runtime.py:98-106`); the default ships as **`google/gemini-3.8-flash`** (03 §3.5.2,
§10 C6 — parity needs a value; a *blank* value refuses composition with `extractor_model_unset`
when an r27 pilot is configured) — D4's Luna pick is an env change after the one-time AT-1
comparison at the pool freeze. The contact
lane (W3-26) gets the role **`person_research`** (R4); user-facing text says "contact".

### 0.7 Decision: `discover_people`'s deep-first gate is relaxed for r26+

`committee_discovery.py:244-258` refuses until an `account_deep` row exists. Nominate-first
(W1-9) and A0 (W3-21) need it off: W1-9 relaxes it for `quality_recipe_version >= 26`; the r27
pre-step calls the `people_roles` body directly (03 §3.2). `L` code, `A` reads the diff.

### 0.8 Setting-name rule (R7)

One sheet, §9. Settings that exist only for the r27 pipeline carry 03 §10's names
(`CLUE_ARV2_V26_*`, `Settings` field `arv2_v26_<lower>`); settings that apply to every recipe
(W1/W2 flags, P5) are `CLUE_ARV2_*` without the `V26` infix. Every setting has exactly one name in
03, 04 and 05; 04 §9 is regenerated from 03 §10 plus the rows 03 lacks (P5, W1/W2, R16's four).

### 0.9 Decisions this document cannot make (review A M19) — recorded for 06

D3 Miscellaneous (03's `CLUE_ARV2_V26_MISC_SECTION=off` is the default carried); D4 the extractor
and page model (blank + refuse until set; the recommendation in §12 is Flash); D6 the read-only
production database user (W0 and P3 numbers depend on it); D8 the deep-report price (pinned by
code — `exa_client.py:523` hard-codes `type="deep-reasoning"`; the *price* is unverified until
D6); D9 the person Exa caps (12 × 4000, a single bounded offline comparison, 05); **D11** the person
compliance floor restored at import for r27 (R15, provisional ruling carried here); the insights
`context-only` section (03's ruling-stands default carried; review A C29).

---

## §1 W0 — fixtures, rule table, frozen pools, replay interface, production queries

**W0 — Consume 01b, freeze the pools, define the replay seam.** Owner `L` (fixtures, scripts) +
`A` (M10 queries, day 1; deliverable 7's three seams). Effort M. Deps none. Gate n/a.

**What already exists (01b §8, verified on disk, review A C39/K4 — the `nyc.gov` nothing-lost
fixture is present now):** `.artifacts/arv2-research-runs-20261007/fixtures/{chains,nothing_lost}/
<account>.json` for all seven accounts, `rule_table.json` (`{method, pairs[]}` with the T6 rows,
`floor: true` on the 18 floor pairs and the 11 recommended ones in order), `quote_fidelity.json`,
`summary.json`, and the seven scripts beside them. **W0 does not re-mine** (Q1): the mining
method is 01b's; the new script of the earlier draft is dropped.

**Deliverables.**

| # | Artifact | Path | Committed |
|---|---|---|---|
| 1 | The follow-up rules resource (R9): 01b T6's **11 recommended floor pairs verbatim** and nothing else (the one-account pairs are the judge's discretion, not rows — 03 §3.4), in 03 §3.4's row shape (`rule_id, subject, trigger, operations[], max_per_trigger, max_per_round, dedupe`) with 03 §3.4's five trigger kinds (`entity`, `class_terms`, `attribute`, `ledger`, `result`) and templates that use the candidate-field variables (`{entity.text}`, `{candidate.source.url}`, `{candidate.typed_value}`, `{name}`, `{seat}`, `{vendor}`) | `platform/agents/catalog/research-quality/followups/v1/rules.json` (sha-pinned in `launch-v4-r27.json`; not inside the Python package — Q2) | yes |
| 2 | AT-6 fixtures: account-level `(class, key_phrase, date)` tuples | `tests/arv2/v26/fixtures/nothing_lost_accounts.json` (copied from 01b's account entries; public company facts) | yes |
| 3 | AT-6/AT-9 contact-level fixtures and chains | stay under `.artifacts/arv2-research-runs-20261007/fixtures/` (personal data; gitignored); the committed `tests/arv2/v26/fixtures/replay_manifest.json` records each file's sha256 | manifest only |
| 4 | Frozen evidence pools | `.artifacts/arv2-v26-replay/<account>/pool/<operation_id>.json` (the stored result body) + `sources/<source_id>.json` (bytes) + `requests.json` (`{operation_id, provider, kind, request_sha256, request_body}`); `pool_sha256` = sha256 over the concatenation of each file's sha256, files sorted by relative path (Q6) | manifest only |
| 5 | The replay seam (M12, Q4, Q7): `tests/arv2/v26/replay.py` with `load_pool(account) -> ReplayPool` and `ReplayPool.transport() -> ScriptedTransport` whose scripts are keyed by `(provider, request_sha256)` (the `fingerprint` of `research_operations.py:27-30`) so a byte-identical request is served from the pool and an unknown request is answered by the BM25 fallback 05 §2.2 describes (recorded as `replay_fallback`); the replay runs on a **throwaway local DB** where `scripts/launch_arv2_account_research.py` creates the run/job rows (so `operations.begin`'s `INSERT … SELECT FROM arv2_research_job` finds them) | yes |
| 6 | Pool freeze script (03 §3.5.5): `scripts/arv2_v26_freeze_pool.py` — reads a job's operations, sources and (on r27) final pool and writes deliverable 4 | yes |
| 7 | The three A-owned harness seams of 05 §2.6 (items 1, 2, 8): (i) `transport_factory: Callable[[], Transport] = HttpxTransport` on `Arv2AccountResearchWorkHandler.__init__` and `build_arv2_account_research_handler`, threaded into `_tool_runtime` (`account_research_driver.py:1257-1271`) — one parameter, one line; (ii) the same seam on the page writer: `page_writer_runtime.provider_model_call` (`:109-176`) takes a transport/caller instead of building `HttpxTransport()` inline, so `--pages cassette` exists; (iii) `tests/arv2/v26/conftest.py::pool(account)`, loading `sources/*.json` into a migrated test DB as `arv2_evidence_source` rows + artifacts for one job through `publish_sources` (L writes, A reviews the write path). The harness's first dry run may monkey-patch `account_research_tools.HttpxTransport`; it is not the lasting answer | `account_research_driver.py`, `page_writer_runtime.py`, `tests/arv2/v26/conftest.py` | yes |

**How the pools are built.** Preferred: D6's read-only production user — `arv2_research_operation`
rows for the 2026-10-06 Dialpad/Loopio jobs (`artifact_key` → bytes through the storage backend),
`arv2_evidence_source` rows and bytes. Fallback if D6 is not granted by day 2: re-issue each
recorded request once (request bodies are whole in Langfuse tool inputs) under a replay workspace
on the local DB through `ToolRuntime.operate` (≈ $1 per account) and freeze those bodies. The
manifest records the method per account. Both the production request shape (20 × 10k) and the
D9 shape (12 × 4k) are frozen for the person deep call so AT-1 runs on both once (review B §3.3).

**M10 — production database queries (A, day 1, needs D6).** Run 01 §7's queries 1, 2, 5 and 7
(provider spend per run and operation incl. the Exa deep `cost_usd` — settles D8's price; job
rows/outcomes; the `agent_model_call` cross-check; Deepgram rows + `which ffprobe` on a batch
worker) and paste the results into `_memory/2026-10-07-arv2-v26-program.md`. P3's pool numbers
and W2-20's baseline are read against them.

**Tests.** Offline: `tests/arv2/v26/test_fixtures.py` — `rules.json` loads, every row's
`trigger.kind ∈ {entity, class_terms, attribute, ledger, result}`, every `operations[].kind ∈ AcquisitionName`
(`quality_provider_tools.py:45-59`), every 01b floor pair has ≥ 1 row, every template renders
against a synthetic candidate (AT-3(c) — a rule that cannot fire fails the test); the manifest's
shas match the files when the gitignored folder is present (skip with a named reason otherwise).

**Acceptance.** Manifest covers Dialpad + Loopio + their ten contacts; `rules.json` carries the
11 floor pairs; `nothing_lost_accounts.json` holds the plan §6 AT-6 Dialpad and Loopio tuples.

**Rollback.** n/a.

---

## §2 Prerequisites P1–P6

### 2.1 P1 — Deferred contact-page write (R11)

Owner `A`. Effort M. Deps none (W1-8, W3-21, W3-25 depend on it). Gate *r26* for the settle
path; the continuation itself is recipe-agnostic.

**Change.**

1. `arv2/quality_policy.py`: `defers_contact_page(scope) = writes_pages_separately(scope) and
   recipe >= 26` (Q8). `account_research_driver.py:_write_pages` (`:1796-1832`): `if
   scope.person_subject_id is not None and defers_contact_page(scope): return result`.
2. `_settle_quality` (`:1833-1958`): after `_offer_committee` (`:1948`), `await
   self._offer_contact_page(composition, ready_version)` where `ready_version` was read inside the
   settle transaction (`SELECT max(dossier_version) FROM arv2_research_import_ready WHERE job_id=
   :parent AND workspace_id=:ws`); NULL → nothing enqueued (the sweep does it later). The offer:
   `self._queue.enqueue(kind=FleetTaskKind.ARV2_ACCOUNT_RESEARCH, work_id=WorkId(job_id),
   dedup_key=f"arv2:contact-page:{job_id}:{ready_version}", priority=ARV2_DISPLAY_TASK_PRIORITY,
   payload={"continuation": "contact_page", "job_id", "run_id", "workspace_id", "parent_job_id",
   "ready_version"}, reopen_terminal=True)`; `self._queue is None` → log
   `arv2.contact_page_not_enqueued`. A parent revision bumps `ready_version` and produces one more
   task — intended: the page follows the newest import (Q12), bounded by the attempt ceiling below.
3. `handle` (`:516-519`): `payload["continuation"] == "contact_page"` →
   `_contact_page_continuation(context)`: read the job row (terminal; no `begin_job`); refuse
   `job_id ≠ work_id` as `:534-545` does; `composition = await self._compose(conn, job)` — safe on a
   terminal row: `_compose_quality` (`:1289-1433`) only re-reads pins, runs `person_scope_for`, and
   its `UPDATE … quality_recipe_version` is guarded `IS DISTINCT FROM` (idempotent); it never
   touches `stage`/`status` (Q10). Then: parent import-ready row absent → `WorkResult("failed",
   {"reason": "parent_not_ready"}, requeue=False)`; `self._page_writer is None` → `failed/
   page_writer_not_composed` (Q11; the sweep re-offers and a composed worker claims it); page
   already current → `completed/already_current`, where *current* = a live contextual
   `display_block` row for `(subject_kind='contact', subject_id=job.subject_entity_id,
   page='contact', context_id=run.context_id, superseded_at IS NULL)` whose `dependency_manifest`
   sha equals `page_inputs(conn, scope, context_id, page="contact").sha256` (Q13); else `await
   page_writer_runtime.write_job_pages(conn_factory=self._connection, storage=self._storage,
   scope=composition.scope, context_id=composition.run.context_id, models=self._page_writer)`
   inside `async with self._jobs`. Exceptions → `failed`, `requeue=False`,
   `arv2.contact_page_failed`.
4. `arv2/quality_person_release.py:contact_pages_due(conn, *, max_attempts, limit=200)`: children
   with `job.status='completed'`, recipe ≥ 26, parent carrying `READY_KIND`, **no current page
   under the definition of step 3** (so a done task is not re-opened on every tick — the
   coordinator's point 5), and whose `fleet_task` row for that dedup key, if any, has `attempts <
   max_attempts`. Returns `workspace_id, job_id, run_id, parent_job_id, ready_version`.
5. `sweep_quality` (`:907-1005`): after releasing `children`, enqueue each `contact_pages_due`
   row as in step 2. Dedup on `(kind, work_id, dedup_key)` makes a repeat a DB no-op
   (`clue_fleet/queue.py:177-187`).
6. **Attempt ceiling (R16(d)):** `CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS` (2). A dedup key whose task
   reached it is not re-offered; the job is stamped `input_refs.page_failed = <reason>` and only a
   `manual_refresh` signal re-offers. The same ceiling applies to the account refresh continuation
   (W1-10) and to W3-25's section failures.
7. `read_parent_dossier`'s raise (`page_writer_runtime.py:405-416`) stays; it is reached only
   from the continuation after the readiness check.

**Settings.** `CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS=2` (§9). The contact page's spend is job-stamped on
the ledger but not on the job row (`finish_job` already ran); 03 §3.9's `add_job_spend` (W3-27)
closes that for r27.

**Tests.** DB: extend `tests/arv2/test_quality_person_release_db.py:103` — a recipe-26 child that
settles before the parent's `FinishDossierTool` produces no `arv2:contact-page:*` task
(`_RecordingQueue`, `tests/arv2/test_account_research_driver.py:1183`); after the parent's
`finish_dossier`, `contact_pages_due` returns the child once, and nothing after the page is
published; a task at `max_attempts` is not returned. Offline: `tests/arv2/test_account_research_
driver.py` — the continuation with a missing parent returns `failed/parent_not_ready` without
calling the writer; with it present calls `write_job_pages` once (fake) and returns `completed`.

**Acceptance (RC-1).** Every contact that finished before its account has one page within 60 s
of the account's `finish_dossier`; zero `needs_review/page_writer_failed` for a missing parent.

**Rollback.** Launch at recipe 25 (P5).

### 2.2 P2 — The re-mint step

Procedure §8 (02 §5.6's eight steps made concrete for 26 and 27, plus the Head-of-ABM v71
column). Every `L` content item is inert until its mint lands; only the mint touches the five
hard-coded tests (§8.3).

### 2.3 P3 — Pool and pgbouncer sizing; fleet env verification (M11, M18)

Owner `A`. Effort S. Deps W2-20 (measure first), M10. Gate *flag* (env values).

**Change.** Batch workers (`/srv/clue/env`, set by Aryan before W2-15 lands — Q14):
`CLUE_DB_POOL_SIZE=12`, `CLUE_DB_MAX_OVERFLOW=20` (`libs/clue-db/clue_db/engine.py:101-106`);
`.env.example:20-22` keeps 5/10 with a comment naming the batch values and the arithmetic
(4 jobs × `CLUE_ARV2_JOB_MAX_DB_CONNECTIONS` 3 + driver + sweep + heartbeat ≤ 16). PgBouncer
`DEFAULT_POOL_SIZE` 20 → 40 only after W2-20 shows pool waits (`runbook.md:241-245`).
`CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` 4 → **6** per process after W2-15 when W2-20's wait reads
≈ 0 (M18; 03 §6.2). **Fleet env verification (M11):** run `deploy/check_prod_env.py` against
`/srv/clue/env` and paste `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS`, `CLUE_FLEET_WORKER_CONCURRENCY`,
`CLUE_DB_POOL_SIZE`, `CLUE_DEEPGRAM_API_KEY` (set/unset), `CLUE_RELEASE` and the image sha into
`_memory/` with M10's results; record the production code version of 2026-10-06 from the image
tag (`deploy/vm/deploy.sh:11-12`).

**Acceptance.** `pool_timeout` errors = 0 over RC-1; W2-20's wait p95 < 1 s after W2-15.
**Rollback.** Restore the env values.

### 2.4 P4 — Verify the live Head-of-ABM pair

Owner `A`. Effort S. `C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM] == "v70"`
(`agent_registry_wiring.py:257`); v70 pins prompt `v18` (sha `3de3db26…`) and skills
`stage0-interview v43`, `account-research-briefing v3`, `icp-authoring v3`. The authoring doc's
"Current code selects Head of ABM **v58**" is at `docs/agents/skill-and-profile-authoring.md:24`
(Q15, review A W5) — fixed in W1-11's branch. Confirm production ran v70/v18 on 2026-10-06 from
the launch trace's metadata `profile` (`agent_runtime_wiring.py:1475`).

### 2.5 P5 — Recipe selection per workspace

Owner `A`. Effort S. Gate *flag*. **Change.** `settings.py` (ARV2 block after `:398`):
`arv2_recipe_version: int | None = Field(None, ge=2)`, `arv2_recipe_pilot_version: int | None`,
`arv2_recipe_pilot_workspaces: tuple[str, ...] = ()` (comma list; the `NoDecode` +
`field_validator` pattern of `settings.py:698, 1166-1171`). `arv2/quality_catalog.py:
recipe_version_for(settings, workspace_id) -> int`: the pilot version for a listed workspace, else
`arv2_recipe_version or CURRENT_RECIPE_VERSION`; a version outside `range(2,
CURRENT_RECIPE_VERSION + 1)` refuses at launch with the typed `Arv2LaunchRefused("recipe_version_
unavailable")` (add to `account_research_launch.py:190-206`). The launch's
`arv2_account_profile_sha256` / `arv2_person_profile_sha256` (`:1177-1200`) call
`load_quality_resources(agent, version=recipe_version_for(…))`; the driver's stamp
(`:1333-1344`) follows. `NominateCommitteeTool` pins the person bundle with the parent's recipe
(`quality_committee_tool.py:213-218`) — unchanged. **Rollout order (Q16):** mint 27 → bump
`CURRENT_RECIPE_VERSION = 27` (the five tests move with it) → `CLUE_ARV2_RECIPE_VERSION=26` +
`CLUE_ARV2_RECIPE_PILOT_VERSION=27` + the pilot workspace → RC-2 twice → blank the default.
03 §9.1/§9.2 adopt these lines (R7).

**`.env.example`:**
```
# Recipe new launches pin (blank = the code's CURRENT_RECIPE_VERSION). A pilot version applies
# only to the listed workspaces; both must be minted recipes <= the current one.
CLUE_ARV2_RECIPE_VERSION=
CLUE_ARV2_RECIPE_PILOT_VERSION=
CLUE_ARV2_RECIPE_PILOT_WORKSPACES=
```

**Tests.** Offline: `tests/arv2/test_settings.py`; `tests/arv2/test_recipe_selection.py` (the
03 §9.3 name) — default, pilot, refusal. DB: `tests/arv2/test_account_research_launch_db.py` — a
pilot workspace's launch pins the pilot bundle sha, another the default. **Rollback.** Blank the
three lines.

### 2.6 P6 — The privacy-stop `profile_ref` filter (R14; blocking before any r27 pilot)

Owner `A`. Effort S. Deps none. Gate *all* (a production privacy defect independent of v26).

**Change.** `arv2/research_operations.py:stop_contact_jobs` (`:286-296`) and
`arv2/claim_writer.py` (`:138-150`) filter `profile_ref IN ('agent-profile:arv2-person:v2',
'agent-profile:arv2-person:v3')`, while every quality person job carries `…:v4`
(`quality_committee_tool.py:219`; `account_research_launch.py:915`). Both filters become
`profile_ref LIKE 'agent-profile:arv2-person:v%'` (one shared constant `PERSON_PROFILE_REF_PREFIX`
in `arv2/account_research_catalog.py`). Readers of `privacy_stopped` are unchanged
(`job_available`, `quality_evidence._subject`, `ready_person_jobs`, `pending_continuations`).

**Tests.** DB: new `tests/arv2/test_privacy_stop_v4_db.py` — a v4 person job's privacy-stop sets
`input_refs.privacy_stopped=true`, `job_available` turns false, the claim writer refuses a claim
for that contact, and the sweep offers no page for it. Smoke: none (no migration).

**Acceptance.** The test; 05 §6 carries it as a go/no-go line.
**Rollback.** None needed (a bug fix; the old filter was wrong for every v4 row).

---

## §3 W1 — Stop the bleeding (week 1)

Expected on r26 (plan §5): ~$12–17 and ~35–40 min per account; zero error rounds; contacts start
at minute ~2; pages shorter and decisive. Acceptance numbers in this section are **replay
measurements**, never code gates (02 §10 item 11).

### W1-1 — Tool-result clearing and per-role window (R6)

Owner `A` (bindings + settings); simulation script `L`. Effort S. Deps none. Gate *flag* (all
recipes; r27 reads its own values).

**Change.** `quality_research_wiring.py:bindings` (`:743-751`): the middleware tuple becomes
`(*dossier_middleware, SharedResearchAllowance(...), *clearing)` with `clearing =
(ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=T, keep=K, clear_at_least=0,
clear_tool_inputs=False, exclude_tools=X, placeholder=P)]),)` when `T > 0`
(`langchain.agents.middleware.context_editing`, langchain 1.3.14). Values by recipe
(`self.resource_version`) and subject kind:

| | recipe < 27 (W1-1) | recipe ≥ 27 (03 §5.3, R6) |
|---|---|---|
| `T` | `CLUE_ARV2_ACCOUNT_CLEAR_TRIGGER_TOKENS` 100000 / `…PERSON…` 100000 | `CLUE_ARV2_V26_ACCOUNT_CLEAR_TRIGGER_TOKENS` 45000 / `…PERSON…` 42000 |
| `K` | `CLUE_ARV2_CLEAR_KEEP_RESULTS` 6 | `CLUE_ARV2_V26_CLEAR_KEEP_RESULTS` 4 |
| `X` (never cleared) | `acquire_research_evidence, finalize_turn, save_dossier_section, update_dossier_findings, validate_dossier, finish_dossier, begin_dossier_revision, discard_dossier_revision` | `submit_brief, finalize_turn` — **`acquire@2` receipts are cleared** (03 §5.3's arithmetic; candidates stay citable by id) |
| `P` | `[cleared — re-read the path named in the call above if you need it]` | `[cleared — candidates remain citable by id; full list at /research/operations/<op>/candidates.json]` |
| window handed to `CompactionSettings` | `min(model window, CLUE_ARV2_ACCOUNT_CONTEXT_WINDOW_TOKENS 200000 / …PERSON… 200000)` | `min(model window, CLUE_ARV2_V26_ACCOUNT_CONTEXT_CAP_TOKENS 60000 / …PERSON… 56000)` |

The trigger is **set, not derived** (Q18). The window cap wraps `compaction_for` at `qrw:1090`
(`replace(settings, context_window=min(...))`; the seam takes any callable, `runtime.py:515,
619-623`); the settings comment states that with clearing on the summariser honours reported usage
(`summarization.py:598-603`) and is a backstop. The middleware lands after `TurnBudgetMiddleware`
and before the summariser (`runtime.py:656-665`); it edits the request only, so
`ToolRepairRoundsMiddleware` (state, `tool_recovery.py:32-46`) is unaffected. 03 §5.3's
steady-state arithmetic (36k opening + 4 kept receipts + 20 AI turns ≈ 56k < 60k) is why `keep=4`.

**Simulation (L).** `scripts/arv2_clearing_simulation.py` over
`.artifacts/arv2-research-runs-20261007/model-calls.csv`: re-price every run under `(T, K)` with
03a §4.4's prefix-cache arithmetic; expected −30–38 % model cost on the corpus.

**Tests.** Offline: `tests/agents/test_compaction.py` (harness `:23-48`) — seven tool results past
a 1,000-token trigger with `keep=6` → placeholders on all but six; `graph.aget_state` holds the
originals; an excluded tool's result is never cleared; a budgeted failure in the cleared window
still counts (state). DB: `tests/arv2/test_quality_driver_db.py` — the bindings tuple carries a
`ContextEditingMiddleware` with the r26 values for a recipe-26 job and the r27 values for 27.

**Acceptance.** RC-1: cached input share ≥ 85 % (01 §2.4: 77 %); no call above `T + 40k`.
RC-2: `compaction_events = 0` on every r27 subject (05).
**Rollback.** `*_CLEAR_TRIGGER_TOKENS=0` (both families) and the window caps `0`.

### W1-2 — Lenient finding schema: `save_dossier_section@2`, `update_dossier_findings@2`

Owner `L`. Effort M. Deps none; minted in r26. Gate *r26* (pins). Used by the r26 agents; r27
emits through `submit_brief@1` (W3-24) but shares the models.

**Change.**

1. `arv2/dossier_findings.py`: `ReviewV2(Review)` — `extra="ignore"`, `status` default
   `"supported"`, `reason` default `"review omitted"`, new `defaulted: bool = False`.
   `FindingV2(Finding)` — `extra="ignore"`, `review: ReviewV2 = Field(default_factory=lambda:
   ReviewV2(defaulted=True))`, `claim_type: Literal["observation", "reported_statement",
   "synthesis", "not_found"]`. **`Finding` itself is not widened** (Q20 refinement of R3):
   `SaveSectionInput.findings: list[Entry]` with `Entry(Finding)` puts `claim_type`'s enum in
   `save_dossier_section@1`'s input schema, so widening the base literal would move the `@1` sha and
   invalidate every v16–v25 pin. `assessment_for` appends `"Review omitted by the researcher;
   defaulted to supported"` when `review.defaulted`. The default is `supported`, never
   `insufficient_context` (R3).
2. `arv2/dossier_json.py`: `EntryReviewV2`, `EntryV2(FindingV2)` with the `id` pattern; its
   `contract` validator strips `defaulted` before the round-trip through `Review` (`extra=forbid`,
   Q21); `EntryV2.model_validator(mode="after")`: `synthesis` requires ≥ 2 `source_paths` with
   distinct source ids (AT-4), `not_found` requires ≥ 1 (the zero-result operation's
   `provider_record` path). `replace_section`/`update_findings` take `entry_model: type[Entry] =
   Entry`; the stored document is the **validated dump** (unknown keys dropped at save, the
   defaulted review materialised). To report what was dropped (Q22) the tool first validates a
   copy with `extra="allow"` and diffs the key sets. `parse_json_dossier` (the importer's entry
   point, `dossier_import.py`) takes `entry_model` and the import path passes `EntryV2` for
   `quality_recipe_version >= 26` documents — so a synthesis item in an r27 document parses (Q20).
3. `arv2/quality_json_dossier.py`: `SaveSectionInputV2(findings: list[EntryV2])`,
   `SaveDossierSectionTool2` (`version = "2"`), `UpdateDossierFindingsTool2`; both return the
   existing dict plus `"normalized": [{"id", "defaults": ["review"], "dropped_keys": [...]}]`.
   Registered in `quality_tools` (`qrw:211-252`; `make_default` stays `"1"`).
4. `arv2/dossier_import.py:finding_proposal` (`:41-79`): `claim_kind="inference"` for
   `synthesis` — an existing `ClaimProposal.claim_kind` value (`quality_claims.py:115`); its
   support rule (`:343-349`) concerns `ClaimSupport`, and a synthesis item cites ≥ 2
   `SourceSupport`s, so it is accepted (Q23); `"observation"` for `not_found`; unchanged otherwise.
5. Profiles `v26`/`v26-person` pin `save_dossier_section@2`, `update_dossier_findings@2`;
   `recipe-v26.json` lists them.

**Tests.** Offline: `tests/arv2/test_quality_json_dossier.py:86` keeps the `@1` strict case and
gains `test_save_schema_v2_defaults_review_ignores_unknown_keys_and_reports_them`;
`tests/arv2/test_dossier_json.py` gains AT-4's two cases. DB: `tests/arv2/test_dossier_import_db.py`
— a `@2` document with a defaulted review imports `conclusion='supported'` with the explanation
text, and `eligible_sql` (`subsystems/research/clue_research/claimstore/quality.py:49-87`) serves
it; a synthesis item imports as `inference` and is served.

**Acceptance.** RC-1: `schema_validation` = 0 (01 T3.1: 82).
**Rollback.** Recipe 25.

### W1-3 — Close the grep → search_evidence → finalize trap

Owner `L`. Effort M. Deps none. The tool version is minted in r26; the view changes are *all*.

**Change.**

1. `arv2/quality_views.py:ResearchViewMount.agrep(pattern, path, glob)`: for a path matching
   `_OPERATION` (dir or file) — authorise as `aread` (`:84-100`), load the body (`:214-237`),
   literal case-insensitive line match, deepagents' `GrepResult(matches=[{path, line, text}])`
   (0.6.12 `backends/protocol.py`), ≤ 50 matches, `text` ≤ 300 chars; for an evidence
   `SOURCE_PATH` — `search_source` (`quality_evidence.py:600-628`, `limit=20`) with each hit's
   `context` as `text`; otherwise `GrepResult(error="grep one file: /research/operations/<id>/
   0.json or /evidence/<name>.json; use search_evidence for offsets.")`.
   `EvidenceWorkspace.agrep` (`quality_workspace.py:131-136`) delegates for a single `SOURCE_PATH`.
2. `ResearchViewMount.als` (`:417-465`): `/research/operations` lists `/operations/<id>/0.json`
   (and `/candidates.json` where the result carries candidates) for **every** operation of the job
   — `quality_tool:%` and the r27 pre-step kinds alike (Q25: the ledger names them, so `ls` must
   too); `/research/capabilities`, `/research/documents`, `/research/claims` list their entries;
   unknown directories name the four listable ones.
3. `arv2/quality_tools.py`: `SearchPathEvidenceTool3(SearchPathEvidenceTool)` — `version = "3"`,
   `output_model = SearchEvidenceOutput3`: `source_id: UUID | None`, `operation_id: UUID | None`,
   `matches`, `next_start`, `contexts: tuple[str, ...]` (≤ 20 × ≤ 340 chars — the `context`
   `@2` drops, `quality_tools.py:275-286`), `refused: str | None`, `recovery: str | None`. An
   `_OPERATION` `source_path` searches the operation body (researcher roles only); every
   `EvidenceUnavailable`/`ValueError` is **returned** as `refused` (a completed operation: not
   `governed_repair_budgeted`, invisible to `check_finalizable`, `agent_execution_wiring.py:
   2096-2109`). `@2` (`SearchPathEvidenceTool`) stays registered for r25 replay (Q24); profiles
   `v26`/`v27` pin `search_evidence@3`.

**Tests.** DB: extend `tests/arv2/test_quality_path_tools_db.py:42`; new
`tests/arv2/test_quality_views_grep_db.py` (`agrep` on an operation; guidance error without a
path; `als("/operations")` lists this job's operations only). Offline: the r26 constants.

**Acceptance.** RC-1: `trap_grep_refused` = `trap_search_evidence_unavailable` =
`finalize_refused_unresolved_failures` = 0; `listing_refused` ≤ 2 per run.
**Rollback.** Additive views; the tool is recipe-pinned.

### W1-4 — Plain-text views, whole by default, capped; r27 raw-read refusal (R16(a))

Owner `L`. Effort M. Deps none. Gate *flag* (all recipes) + *r27* for the refusal.

**Change.** Plumbing first (Q26): a frozen `ViewSettings(format, max_chars, judge_raw_reads)`
dataclass in `arv2/quality_workspace.py`, built from `self.settings` in `bindings()` and passed
as `research_backend(..., views=ViewSettings(...))` → `ResearchViewMount(..., views=...)`;
`render_view(value, *, offset, limit, document: str | None = None, max_chars: int)`.

- `render_view`: the unbounded rule becomes `limit <= 0 or limit in (100, 2000)` (deepagents
  0.6.12's default `limit=100` is always forwarded, `filesystem.py:257-258`; an explicit 100 also
  serves the whole document — intended and documented, Q27); fix the docstring at `:46`.
- Operation bodies (`quality_views.py:214-237`) as plain text when `format == "text"`: header
  (`operation`, `status`, `result_count`, `source_review_path`, `cost`), the deep `report`
  verbatim, then one line per result `- [i] <title> — <url> (<kind>, <chars> chars) → <path>`;
  `search_web` results with highlights/snippet ≤ 600 chars; `fetch_page` the text; AI Ark/ATS/
  people operations stay JSON. Cap `CLUE_ARV2_VIEW_MAX_CHARS` (80000 = deepagents' own 20,000-token
  truncation, `filesystem.py:272`); past it `[truncated at N chars; continue at
  /research/operations/<id>/<N>.json]` — `N` is a character offset exactly as `_passage`'s
  `start` is today (Q28).
- Evidence bodies (`quality_workspace.py:77-83`): header + body verbatim, same cap; the tail of
  a capped source is reached through `search_evidence@3` offsets (there is no offset form of the
  evidence path, Q28).
- **r27 judges (R16(a)):** when `judge_raw_reads` is false and `resource_version >= 27`,
  `aread` of `/research/operations/<id>/0.json` or any `/evidence/*` body returns the refusal text
  `"Raw views are not readable in this recipe: cite candidates by id; the full candidate list is
  at /research/operations/<id>/candidates.json; use search_evidence for a literal check."`
  Readable: `/research/context.json`, `/research/claims/*`, `/research/operations/<id>/
  candidates.json` (new view, whole JSON — 03 §3.6.3), `/evidence/index.json`, the dossier
  views and `inputs/`. The refusal is a `ReadResult(error=…)`, not a tool failure.

**Settings.** `CLUE_ARV2_VIEW_FORMAT=text`, `CLUE_ARV2_VIEW_MAX_CHARS=80000`,
`CLUE_ARV2_V26_JUDGE_RAW_READS=false` (§9).

**Tests.** Offline: `tests/arv2/test_research_read_bounds.py:10` extended (100/2000 whole; 50
windows; cap + continuation; `json` reproduces today's segments). DB:
`tests/arv2/test_quality_evidence_db.py:87` (plain body); a recipe-27 mount refuses
`/evidence/0001-x.json` and serves `candidates.json`.

**Acceptance.** RC-1: read-only rounds ≤ 10 % (01 §3.9: 31 %); the deep report read in ≤ 2
windows. RC-2: zero raw-view reads by judges.
**Rollback.** `CLUE_ARV2_VIEW_FORMAT=json`; `CLUE_ARV2_V26_JUDGE_RAW_READS=true`.

### W1-5 — Content-bearing receipts: `acquire_research_evidence@2` (R13 — final shape)

Owner `L`. Effort M. Deps none; minted in r26. Gate *r26*.

**Change.** New `arv2/candidates.py` (every model a `ToolOutput`, nested models declared —
Q29/Q30):

- `Candidate`: `id: str` (`"c_" + sha256(class ‖ url ‖ normalize_for_match(quote|raw))[:12]`,
  03 §4.1 — the same quote from the same page found by two operations is one candidate), `cls: str = Field(alias="class")` with `model_config = ConfigDict(populate_by_name=
  True)` and dumps `by_alias=True` (the governed path validates the JSON-mode dump against
  `output_model`; both spellings validate — Q29), the class set of 03 §2.1 plus `unbound_hook`
  and `committee_alternate`; `finding: str`; `evidence: QuoteEvidence | TypedEvidence`
  (`{kind: "quote", quote, elided}` | `{kind: "typed", value_kind, value, source_offset, raw}`);
  `source: CandidateSource` (`source_id, path, url, title, kind, operation_id, template_id`);
  `attribution: CandidateAttribution` (`kind ∈ self|employer|first_party|third_party|
  provider_synthesis`, `speaker`); `date: str | None`, `date_basis`; `confidence: float`;
  `use_class: str | None`; `subject_anchor: SubjectAnchor | None` (`kind, value, matched`);
  **`entities: tuple[CandidateEntity, ...]`** (`kind ∈ person|org|vendor|programme|event|url|
  phrase|prior_employer|subject_site_page|title`, `text` — 03 §4.1's ten, frozen at the r26 mint) — R9; `follows: str | None` (the lead); `extractor: ExtractorStamp`;
  `verdict: CandidateVerdict` (`quote ∈ EXACT`, `floor: tuple[str, ...]`).
- `ReceiptOutcome(provider, kind, result_count: int | None, http_status: int | None)`,
  `ReceiptLedger(operation_id, kind, template, candidates: int, rejected: int, follows: str |
  None, pool_read: bool, provider_ms: int | None)`, `ReceiptItem(title, url, kind, published,
  snippet ≤ 600, path)`.

`arv2/quality_provider_tools.py`: `AcquireResearchInput2(ToolInput)` = `@1` + `purpose: str |
None` (≤ 200) + `follows: str | None` (03 §3.6.3). `AcquireResearchReceipt2(ToolOutput)`:
`operation_id`, `status: Literal["completed", "refused", "unavailable", "tool_error",
"outcome_unknown"]` (review A C7 — the plan's real outcomes), `result_path`, `candidates_path:
str | None` (`/research/operations/<id>/candidates.json`), `error_code`, `reason` (≤ 300 chars
from `detail`/`gaps`), `recovery`, `replayed`, `outcome: ReceiptOutcome`, `items: tuple[
ReceiptItem, ...]` (≤ 20), `candidates: tuple[Candidate, ...]` (≤ `CLUE_ARV2_V26_RECEIPT_
CANDIDATES_MAX` 20, empty until W3-23), `candidates_total: int`, `ledger: ReceiptLedger`. Status
mapping: `domain_state == "unavailable"` → `unavailable`; `value["error"]` starting
`tool_error:` → `tool_error`; the rest as `@1`. Items + candidates are truncated so the receipt
stays ≤ 10 KiB (`clue_agents/execution.py:57`). `AcquireResearchTool2(AcquireResearchTool)`,
`version = "2"`; `invoke` = `@1`'s steps with the receipt builder, `purpose`/`follows` written on
the operation's result value (`value["ledger"]`) so replay serves them. Registration: both
versions from one runtime; `ResearchUnitRuntime.__init__` (`qrw:522-532`) and `research_backend`
(`:740`) loop over `("1", "2")` for the writer replacement and the capabilities lookup (Q31).

**Tests.** DB: `tests/arv2/test_quality_provider_db.py` (pattern `:228`) — a scripted Exa search
→ `items` resolve under `/evidence/`, `candidates == ()`, `status == "completed"`, `ledger.follows`
echoes the input; `{"state": "unavailable", "gaps": [...]}` → `unavailable` + `reason`;
`tool_error:FileNotFoundError` → `tool_error`; a replayed call returns the same `follows`.
Offline: the item/candidate truncation at 20 / 24 / 10 KiB; `Candidate` round-trips `class`.

**Acceptance.** RC-1: no `completed` receipt for a failed media read; ≥ 40 % of operations whose
result file the agent never opens.
**Rollback.** Recipe 25 pins `@1`.

### W1-6 — Remove the duplicate L1 prompt

Owner `A` (shared `clue_agents`; affects every deepagent). Effort S. Gate *flag*.

**Change.** `platform/agents/clue_agents/context.py`: the L1 candidate (`IdentityLayerSource.load`,
`:275-299`) is still loaded, budgeted and recorded in the manifest, but not appended to
`messages` (`:961-964`) when `emit_identity_message` is false — the prompt reaches the model once
through `create_deep_agent(system_prompt=…)` (`runtime.py:640`) plus the resource map
(`:189-194`). The switch is a constructor argument of `build_agent_context_assembler`
(`agent_platform_wiring.py:514`), read from `settings.agent_l1_as_message` at its **four** roots
(review A W3/Q32): `conversation_turns.py:797` (Head-of-ABM), `account_research_turn_wiring.py:829`,
`onboarding_synthesis_wiring.py:512`, `quality_research_wiring.py:368`.

**Settings.** `agent_l1_as_message: bool = False`; `.env.example` after
`CLUE_AGENT_COMPACT_KEEP_MESSAGES`: `CLUE_AGENT_L1_AS_MESSAGE=false` (with the two-line comment).

**Tests.** Offline: `tests/agents/test_context.py:128` — the manifest still has seven layers;
`len(first.messages) == 6` when the switch is false (the fixture `_sources()` passes it; Q19) and
`messages[0]` is the L7 human message; `tests/agents/test_runtime_continuation.py`,
`test_context_continuation.py` byte-identical (continuations already skip L1, `context.py:899-900`).
RC-1 also replays one Head-of-ABM launch turn (review B §4.1).

**Acceptance.** RC-1: starting context ≈ 12–15k tokens (01 §6 item 5).
**Rollback.** `CLUE_AGENT_L1_AS_MESSAGE=true`.

### W1-7 — Release the provider slot when the provider answers

Owner `A`. Effort M. Gate *flag* (all recipes).

**Change.** `arv2/account_research_tools.py`: split `_perform_hop` (`:500-565`) into
`_dispatch(provider, fn, operation) -> _Dispatched(result, raw, ledger, error_code, semantic_empty)`
— the `async with self._semaphore(provider)` block holding the `job_available` refusal, the halt
check and `await asyncio.to_thread(fn, caller)`, the two `except` arms unchanged, `result=None` on
a refusal path so `semantic_empty` is false (Q33) — and `_land(dispatched, operation)` = today's
`finally` body. `_hop` (`:470-498`): non-AI-Ark providers `dispatch` then `land` **outside** the
semaphore in a `finally`; AI Ark: inside the advisory lock `await asyncio.gather(asyncio.sleep(
gap), self._land(...))` — the gap stays 10.5 s from dispatch end and the drain overlaps it. The
pacing transaction on `pacing_conn` and `_drain`'s `self._conn_factory()` are separate
connections; holding the AI Ark lock through a `_db_lock` wait is accepted until W2-15 removes
that wait (Q34). `settings.arv2_drain_outside_slot=false` restores the old order.

**Settings.** `CLUE_ARV2_DRAIN_OUTSIDE_SLOT=true` (§9).

**Tests.** Offline: `tests/arv2/test_account_research_tools.py` — concurrency 2, a 10 ms
transport, `_drain` monkeypatched to 200 ms: five `call_provider("exa", …)` → the third dispatch
starts before the first drain ends; every call drains once; a raising dispatch still drains; flag
false restores the old order; `ai_ark`: the second dispatch starts ≥ gap after the first's end and
≤ gap + drain + 50 ms.

**Acceptance.** RC-1: 03a §1.4 phase c median ≤ 1 s for batched calls (11.14 s today).
**Rollback.** `CLUE_ARV2_DRAIN_OUTSIDE_SLOT=false`.

### W1-8 — Release contacts at nomination (r26)

Owner `A`. Effort S. Deps **P1**. Gate *r26*.

**Change.** `arv2/quality_person_release.py:ready_person_jobs` (`:69-104`): the `CASE` at
`:89-92` gains `WHEN recipe >= :at_nomination THEN TRUE` (`RELEASE_AT_NOMINATION_RECIPE = 26`
beside `MIN_RECIPE`); the other conditions stay. The 10 s sweep (`sweep_quality`,
`account_research_driver.py:951-975`) selects and enqueues them with the launch's work id/dedup
key; the parent's settle finds none left.

**Terminal predicate for stopped children (Q35).** A privacy-stopped child never reaches
`completed`/`needs_review` (`status` has no `failed` value in `arv2_research_job_status`,
`a3602967bb73:138`; `stop_contact_jobs` only sets `input_refs.privacy_stopped`). Definition used by
W1-10, W3-21 and P1: `child_terminal = terminal_status IS NOT NULL OR job.status IN ('completed',
'needs_review') OR COALESCE(job.input_refs->>'privacy_stopped','false')='true'`. The sweep's
"missing results" selection (`:938-946`) additionally picks privacy-stopped children and
`record_child_result` (`quality_generation.py:268-318`) stamps `terminal_status='failed'` for
them (the CHECK admits `failed`, 02 §3.10), with the event digest over `{status, privacy_stopped}`.

**Tests.** DB: extend `tests/arv2/test_quality_person_release_db.py:103` (recipe 26 → the child
is ready right after `register_child`; 25 unchanged) and `:271` (a child finishing first ends
`completed`, its page comes through P1); a privacy-stopped child gets `terminal_status='failed'`
on the next sweep.

**Acceptance.** RC-1: nomination → first person job start ≤ 30 s (01 §6 item 18).
**Rollback.** Recipe 25.

### W1-9 — Nominate the committee first (r26)

Owner `L` (prompt, skill, the gate predicate; `A` reads it). Effort S. Minted in r26.

**Change.**

1. `arv2/committee_discovery.py:_discover_people` (`:244-258`): skip the `deep_attempted`
   refusal when `quality_recipe_version >= 26`.
2. `prompts/quality-account-research/v26/SYSTEM.md` replaces `v25:51-61`: first tool batch after
   `/research/context.json` and `/research/capabilities/0.json` — `lookup_company`, then one
   `discover_people` per persona of the pinned ICP's `persona_map` in the order
   `economic_buyer, champion, technical_evaluator, blocker, user` (the `Persona` enum,
   `libs/clue-core/clue_core/enums.py:358-367` — never `influencer`, review A W12), `size: 5`,
   `role_key = <persona>`, `rationale` = one line, `evidence_refs = []`, `titles` from the persona
   document's `titles:` front-matter list when present, else the standard title table in skill
   `person-research-briefing v5` (five personas × ≤ 6 titles; Q36). Nominate four or five within
   `committee_cap` with a brief that says the account picture is not yet known. Six paced AI Ark
   calls → a **63 s floor** (`company_lock` is paced too, `account_research_tools.py:468-492`;
   review A K1).
3. `skills/person-research-briefing/v5/SKILL.md`: the title table; "known findings" optional at
   nomination; the release paragraph (`v4:86-107`) says the person job starts immediately and reads
   the account's findings through `/research/claims/0.json`.
4. **Parent-dossier reads (Q9, Q37):** `person_task_instruction(account_dossier_available=…)`
   (`account_research_driver.py:1407-1410`) becomes `18 <= recipe < 26 and parent_job_id`;
   the r26 person prompt and skills (W1-14) name no `/research/parent-account-dossier.json`; the
   view path stays served (a released child may still read a parent that has imported).

**Tests.** DB: `tests/arv2/test_committee_discovery_v2_db.py` — at 26 `discover_people` succeeds
with no `account_deep` row; at 24 it refuses. Offline: `tests/agents/test_skill_references.py`
(see §8.3 for the new assertion); `test_quality_json_dossier.py` constants.

**Acceptance.** RC-1: first `discover_people` precedes the first `search_web` in every account
trace; first nomination ≤ +3 min.
**Rollback.** Recipe 25.

### W1-10 — Account pages once after the last contact; skip unchanged republishes

Owner `A`. Effort S. Gate *r26* for the predicate; the skip is *all*.

**Change.**

1. `arv2/quality_generation.py:pending_continuations` (`:390-434`): for recipe ≥ 26 the child
   clause becomes `NOT EXISTS (child c WHERE NOT child_terminal)` with W1-8's predicate; recipes
   20–25 keep the current clause.
2. `page_writer_runtime.rewrite_account_pages` (`:667-729`): before `write_pages`, compare each
   page's `page_inputs(...).sha256` with the live contextual block's `dependency_manifest` sha
   (the value `publish_page` stores from `expected_dependency_sha256`, `quality_pages.py:276-312`);
   all equal → `after_publish(conn)` and return, `arv2.page_writer.rewrite_skipped_unchanged`.
   **What the sha covers (Q38):** `page_inputs` (`quality_page_inputs.py:53-114`) folds the
   generation and the `claim_dependency_revision`/claim versions of the account **and every
   committee contact** for account pages, so a child's import changes it; the skip therefore
   fires only for a true no-op (replay, a repeated `manual_refresh`). The saving comes from the
   predicate in step 1 — one continuation per account — and, for r27, from W3-25's per-section
   packet shas. `write_account_pages` gains a `pages` parameter (today fixed at `page_writer.py:
   314`, review A W4).
3. The continuation honours `CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS` (P1 step 6).

**Tests.** DB: `tests/arv2/test_page_writer_runtime_db.py:210` — a second rewrite with no new
child result makes zero model calls and settles; `tests/arv2/test_quality_generation_db.py:34` —
at 26 a generation with one non-terminal child is not pending; with every child terminal (incl.
a privacy-stopped one stamped `failed`) it is.

**Acceptance.** RC-1: rewrites per account ≤ 1 (01 §6 item 21: 3–6).
**Rollback.** Recipe 25 for the rule; the skip is a byte-identical no-op.

### W1-11 — Launch latency: one direct call (D7)

Owner `A` (Head-of-ABM mint, selector) + `L` (text). Effort S. Deps **P4**.

**Decision.** The brief stays (seam 1) but is ≤ 1,500 characters written from what the chat
already has; no skill read before the launch; the research agent gets the pinned ICP/personas/
product through `/research/context.json` (`quality_views.py:238-310`).

**Change.** `account_research_launch.py:1319-1330` (description) and `prompts/head-of-abm/v19/
SYSTEM.md` (`v18:86-95`) carry the inline rule. `profiles/head-of-abm/v71/profile.yaml`: prompt
`v19`, skills = v70's minus `account-research-briefing`, tools unchanged. **Mint steps (M13, Q39,
Q40):** (1) the v71 folder + `agent_registry_wiring.py:257 → "v71"`; (2) the manual —
`platform/agents/catalog/manual/tool_notes.yaml:88` names the briefing skill, so the launch
tool's note is rewritten and the manual is re-minted per `make manual` / `make manual-check`
(`Makefile:44-50`); (3) the conversation recipe pins tool **addresses** (comment at
`agent_registry_wiring.py:252-256`); v71 changes no tool pin, so no recipe bump — the registry
references to the skill at `:221, :235` are comments, not checks, so boot does not refuse (Q40);
(4) `docs/agents/skill-and-profile-authoring.md:24` corrected.

**Tests.** Offline: `tests/agents/test_tool_authority_audit.py`, `tests/agents/test_catalog.py`
(the registry builds with v71), `tests/agents/test_manual_drift.py` + `make manual-check`.

**Acceptance.** Replay of the 2026-10-06 request: launch turn < 45 s, ≤ 2 model calls, 0 file
reads (01 §6 item 22). The launch turn is excluded from the r27 cost gate (03 §5.5; review B §1.2
row 21).
**Rollback.** `C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM] = "v70"`.

### W1-12 — Disable media operations (D1)

Owner `L`. Effort S. Minted in r26 (skills). Gate *flag* (all recipes) + *r26* skills.

**Change.** `AcquireResearchTool.__init__` (`quality_provider_tools.py:94-110`): when
`runtime.settings.arv2_media_enabled` is false, drop `MEDIA_OPERATIONS = {discover_media,
read_media, search_transcripts, open_transcript}` from `self.operations`; the catalogue omits them
and a call is the durable non-spending `operation_unavailable_for_subject` (`:133-134`). Skills:
`account-dossier v10` (drop `v9:254-261` and the media coverage line), `person-dossier v6` (drop
`v5:275-299`), `person-depth-charter v2` (voice from the person's own writing); the v26 prompts
drop their media sentences. The setting's name is 03 §10's `CLUE_ARV2_MEDIA_ENABLED` — it gates
every recipe, so no `V26` infix (§0.8; review A C32); W4 adds the boot gate.

**Settings.** `CLUE_ARV2_MEDIA_ENABLED=false` (§9).

**Tests.** DB: `tests/arv2/test_quality_provider_db.py` — with the flag false the catalogue lacks
the four and `read_media` returns `operation_unavailable_for_subject` with no transport and no
`arv2_media_*` rows. `tests/arv2/test_quality_media_db.py:40` builds its runtime with
`settings=SimpleNamespace(arv2_person_media_max_items=8, arv2_media_enabled=True)` — the
pattern the file already uses at `:72, :289` (Q41).

**Acceptance.** RC-1: media provider calls = 0 (01 T3.5).
**Rollback.** `CLUE_ARV2_MEDIA_ENABLED=true`.

### W1-13 — Pages: interpretations in; Miscellaneous per D3 (r27); section order

Owner `L`. Effort M. Gate: (a)(c)(e) *all*; (b) *r27* + setting.

**Change.**

(a) `page_writer_view.render_findings` (`:68-86`): add `  Interpretation: …` when present;
`finding_texts` (`:89-96`) includes it so `check_pages` accepts a sentence that paraphrases it.

(b) `quality_pages.read_page` (`:531-571`): the Miscellaneous dump runs iff `recipe < 27 or
settings.arv2_v26_misc_section == "on"`; with `on` on r27 the dump is filtered to claims that are
`outreach_safe` and `use_class = professional-public` (03 §3.8). **r26 keeps today's dump**: D3 is
the founder's and the 2026-09-29 ruling stands until taken (review A C29). The earlier draft's
(d) — dropping the insights `context-only` section — is **withdrawn**; 03 §2.1 keeps `watch_out`
shared into `context-only` (02 §10 item 13 ruling), recorded in §0.9.

(c) `display/recipes.py` system rows: positions overview `why-they-fit 0, why-now 1,
what-they-do 2, buying-committee 3, how-to-approach 4, watch-outs 5`; contact `problem-right-now 0,
why-this-person 1, openers 2, angles 3, do-not-mention 4, miscellaneous 5`; the boot upsert
(`recipes.py:314-334`) rewrites the `''` rows; `page_writer.py:SECTIONS` (`:41-66`) reorders.

(e) Guides `v2` (`research-page-writing`, `account-pages`, `contact-page`, `seller-brief`):
new order, the interpretation line, per-section text for W3-25. **Plumbing (Q43):**
`page_writer.py` has no settings import; `page_writer_models(settings, …)`
(`page_writer_runtime.py`) builds `PageWriterModels(..., guides=GuideSet(version=settings.
arv2_page_guide_version))`; `guide()`/`_guides_sha()` (`:179-181`) read the `GuideSet`, not the
module constant; `GUIDE_VERSION` becomes the default of `GuideSet.version`.

**Settings.** `CLUE_ARV2_PAGE_GUIDE_VERSION=v2`; `CLUE_ARV2_V26_MISC_SECTION=off` (§9).

**Tests.** Offline: `tests/arv2/test_page_writer.py` (interpretation line; v2 guides). DB:
`tests/arv2/test_quality_pages_db.py:91` — at 27 with `off` an uncited finding is not appended;
at 26 it is; `context-only` present in both. Recipe-position test under `tests/arv2/display/`.

**Acceptance.** RC-1 (replay measurement): the first seller-critical Dialpad finding in the first
two sections; overview length ≤ 60 % of the 10-06 pages.
**Rollback.** (b) the setting; (e) `CLUE_ARV2_PAGE_GUIDE_VERSION=v1`; (a)(c) additive.

### W1-14 — Seller-led skills and prompts (v26), compact Exa requests, D9 caps (R10)

Owner `L`. Effort L. Deps W0 (01b). Minted in r26. Gate *r26* + *flag* (the caps).

**Change.**

1. `skills/account-dossier/v10`, `claim-ready-account-dossier/v4`: the section guide becomes the
   03 §2.1 account classes with **01b §6's caps** (R10): Trigger 10, Initiative 5, Pain 5,
   Motion 5, **Stack 8, Committee 10, Watch-outs 4**, Not-found 3, Firmographics fixed; the eleven
   coverage areas (`v9:176-192`) go; rank within class, drop what no artifact can use; process
   narration is a `not_found` citing the operation's record path; `agent_interpretation`
   mandatory on Trigger/Initiative/Pain/Committee; stale narrative lines removed.
2. `person-dossier/v6`, `claim-ready-person-dossier/v4`, `person-depth-charter/v2`: the contact
   classes with 01b's caps — remit 2 (merge corroborating records), **problem-now 5, own-words 8,
   proud-of 3, hooks 4**, career-arc 1, do-not-mention 1 (≈ 24); the dropped categories out; no
   parent-dossier reads (Q37).
3. `provider-requests/account-deep/v2/exa-system.md`, `person-deep/v2/exa-system.md`: compact,
   evidence-first report; `request-config.json` v2 mirrors the settings as documentation.
   `account_exa_brief.py:11-55` / `person_exa_brief.py:11-58` resolve `RESOURCE_ROOT` per recipe
   (`v2` for ≥ 26).
4. **D9 caps as settings (Q44 — the signature change):** `person_exa_arguments(..., caps:
   PersonExaCaps)` and `person_search_contents(caps)` where `PersonExaCaps(deep_num_results,
   deep_text_max_chars, deep_highlight_max_chars, search_text_max_chars)` is built by the call
   sites (`account_research_tools.py:1389, 1428, 2019`) from `runtime.settings` for recipe ≥ 26
   and from the v1 config file otherwise; `_person_research_deep` clamps `num_results` to the cap.
   Names/defaults are 03 §10 C4: `CLUE_ARV2_V26_PERSON_DEEP_NUM_RESULTS=12`,
   `CLUE_ARV2_V26_PERSON_DEEP_TEXT_MAX_CHARS=4000`, `…_HIGHLIGHT_MAX_CHARS=1000`,
   `CLUE_ARV2_V26_PERSON_SEARCH_TEXT_MAX_CHARS=1500`.
5. Prompts `v26`/`v26-person`: W1-9's opening, W1-12's removal, the class/cap language, the
   unchanged dossier/finish/finalize mechanics (`v25:66-116`).

**Content owner and date (Q45):** `L` writes the eight folders by Wednesday of week 1 (§7.5); the
≥ 70 % A/B rubric is 05's harness; AT-6's nothing-lost tuples are the mechanical check here.

**Tests.** Offline: `tests/arv2/test_person_exa_brief.py` / `test_account_exa_brief.py` (v2 at
26, v1 at 25; the body carries `maxCharacters: 4000`/`numResults: 12` at 26); skill-reference
and constants tests.

**Acceptance.** RC-1: contact findings ≤ 25 per dossier (replay measurement; 01 §5: 14–77);
every AT-6 account tuple present, within its class cap, quote-verified, dated, URL-cited.
**Rollback.** Recipe 25; caps back to the v1 values.

---

## §4 W2 — Platform throughput (weeks 2–3, `A`-heavy)

Order: 20 → 16 → 17 → 15; **W2-19 moves after RC-2** (review B §4.2: not needed for v26's
targets, and its downgrade refuses while lazy rows exist). Target: `acquire_research_evidence` ≈
provider time + ≤ 8 s.

### W2-20 — Instrument the lock wait first

Owner `A`. Effort S. Gate *all* (observability). `account_research_driver.py:_connection`
(`:1016-1019`): time the `_db_lock` wait in `critical_section("arv2.db_lock.wait")` (03 §8.1), log
`arv2.db_lock_waited` with `wait_ms` at ≥ `CLUE_DB_CRITICAL_SECTION_LOG_MS`, record the histogram
`arv2.v26.db_lock_wait_ms` (03 §8.2's metric set, W3-27). Timers around `_drain`
(`account_research_tools.py:596-688`) and `recover_acquisitions` (`quality_acquisition.py:74+`):
`arv2.drain_completed{drain_ms, index_ms, recover_ms}`. **Test.** Offline: two concurrent
`_connection()` users → one `arv2.db_lock_waited` event (`_RecordingLog`, `test_account_research_
driver.py:1677`). **Acceptance.** p50/p95 `wait_ms` per worker over one RC-1 account.

### W2-16 — Index once per batch

Owner `A`. Effort M. Deps W2-20. Gate *all*. `libs/clue-spend/clue_spend/ledger.py:
drain_provider_calls` → `DrainReport.raw_bodies: Mapping[str, bytes]` (one batch's bodies, a few
MB at most — freed when the drain returns; Q46); `quality_acquisition._index_receipts`
(`:150-200`) reads `report.raw_bodies[key]` instead of `read_verified_artifact` (`:153-155`);
`committee_discovery.index_provider_artifacts` (`:136-189`) takes `(key, provider, operation)`
triples and skips non-AI-Ark rows before storage; `quality_evidence.prepare_sources(conn, storage,
scope, specs)` records rows sequentially, verifies each distinct `original_key` **once** (today
per source at `quality_evidence.py:204-206`, review A W8), then `asyncio.gather`s the `put`s under
`Semaphore(16)`; `publish_sources` (`:240-302`) unchanged. **Tests.** DB:
`tests/arv2/test_quality_evidence_db.py:248` with a counting storage fake (≤ 27 `put`s, one `get`
of the original per search); `tests/arv2/test_provider_ledger_db.py` (`raw_bodies`).
**Acceptance.** `index_ms` p50 ≤ 2 s per batched search. **Rollback.** None (same writes).

### W2-17 — No `recover_acquisitions` on the success path; two indexes

Owner `A`. Effort S. Deps W2-16. Gate *flag* + migration. `operate` (`account_research_tools.py:
721-725`): recover only when `not won` or `settings.arv2_recover_on_success`; `_settle_quality`
runs it once before `coverage`. Migration (hash id): `CREATE INDEX provider_call_ledger_job ON
provider_call_ledger (entity_research_job_id) WHERE phase = 'result'`, `CREATE INDEX
arv2_evidence_source_ledger ON arv2_evidence_source (workspace_id, ledger_id)`; downgrade drops
both. **Setting.** `CLUE_ARV2_RECOVER_ON_SUCCESS=false`. **Tests.** Offline: `operate` on a won
operation skips recovery (counter); smoke. **Rollback.** The flag; indexes harmless.

### W2-15 — Remove the worker-wide `_db_lock` from research tool transactions

Owner `A`. Effort L. Deps W2-20, P3, W2-16/17. Gate *flag*.

**Lock-order review first (in the PR):** job row `FOR NO KEY UPDATE` (`quality_committee_tool.py:
93-96`); generation `FOR NO KEY UPDATE` (`quality_generation.py:218-246`); manifest `FOR UPDATE`
(`quality_evidence.py:257-263`); advisory `research-dossier` (`quality_json_dossier.py:152-159`),
`dossier-import` (`dossier_import.py:164-167`), `quality-proposal` (`quality_claims.py:205-208`),
`ai-ark` (pacing connection); `artifact FOR SHARE` (`artifacts.py:120-140`). Order within one
transaction: job row → generation → manifest → artifact → advisory; the evidence authority's
shared job lock is never upgraded (`quality_json_dossier.py:153-155`).

**Change.** `_job_connections(job_id)`: a factory bounded by a per-job
`asyncio.Semaphore(settings.arv2_job_max_db_connections)` over the raw `self._conn_factory`;
`_tool_runtime` (`:1257-1271`), `_write_pages` (`:1819-1821`), `_rewrite_account` (`:866-870`) and
the pre-step use it when the setting is > 0, else `self._connection`. The driver's row transitions
and the sweep keep `_db_lock`. The default is **3** (Q47): an r27 plan gathers ~10 operations
whose `_drain`s each need a connection for milliseconds — the semaphore serialises only that DB
phase, never the provider wait — and 4 jobs × 3 + driver + sweep + heartbeat fits P3's pool
(12 + 20 overflow). **Setting.** `CLUE_ARV2_JOB_MAX_DB_CONNECTIONS=3` (0 = the shared
connection). **Tests.** Offline: a multi-connection `FakeConnFactory` (`tests/arv2/test_account_
research_driver.py:430` area) asserting ≤ N concurrent per job and interleaving across jobs; DB:
new `tests/arv2/test_quality_acquisition_concurrency_db.py` (two `operate`s of one job
concurrently → both publish, gap-free revisions, no deadlock in 10 s). **Acceptance.** W2-20's
`wait_ms` p95 ≈ 0; evidence calls ≈ provider + ≤ 8 s on the RC-1 timing re-run; then P3's
`MAX_PARALLEL_JOBS` 4 → 6. **Rollback.** `CLUE_ARV2_JOB_MAX_DB_CONNECTIONS=0`.

### W2-19 — Lazy indexing of Exa result texts (after RC-2)

Owner `A`. Effort L. Deps W2-16, W2-15, RC-2. Gate *flag* + migration. Mechanism unchanged from
the earlier draft: rows (deterministic `source_id`, revision, path, `metadata.lazy={original_key,
locator}`) without the normalised artifact; materialise on first `resolve_source`/`_body` under
`pg_advisory_xact_lock('research-source-materialize:'||source_id)`; readers treat a NULL key as
available iff the original is. Migration: drop the two `NOT NULL`s, add `arv2_evidence_source_lazy`
CHECK; downgrade refuses while lazy rows exist — a **production** downgrade therefore needs
`scripts/arv2_materialize_lazy_sources.py` (new; materialises every lazy row first; Q48). The r27
extractor reads operation bodies, not per-result sources, so most are never materialised.
**Setting.** `CLUE_ARV2_INDEX_LAZY=true`. **Tests.** DB (index lists every path; first read
materialises one artifact; erasure of the original makes the row unavailable); smoke.
**Rollback.** The flag.

### W2-18 — Account-level operation pool: design note only

No code in v26.0; `arv2_research_operation` stays job-keyed (`0ab01fe27c1e:57`); cross-job reuse
is 03 §3.3.4's pool-read rule (W3-22). Recorded in 06.

---

## §5 W3 — The r27 pipeline (weeks 3–5)

Mechanisms follow 03 §2–§6 line by line; the exceptions are the rulings R2/R11/R12/R13 and the
three facts 02/03a corrected since (the six-site role migration, the sweep as the only enqueuer,
the extractor envelope binding), each cited where it applies.

### W3-26 — The `person_research` role and model lines (R4)

Owner `A`. Effort M. Deps none. Gate *r27* + migration.

**Change.** `clue_agents/contracts.py:220-236`: `PERSON_RESEARCH = "person_research"`.
`quality_research_wiring.py`: `quality_profiles` (`:255-351`) — `active_roles` for
`version >= 27` = `{PERSON_RESEARCH}` when `person` else `{ACCOUNT_RESEARCH}`; every authority
set naming `ACCOUNT_RESEARCH` for the research tools (`:261-290`) also names `PERSON_RESEARCH`;
ladder `("v27-person" if person else "v27") if version >= 27 and role in {ACCOUNT_RESEARCH,
PERSON_RESEARCH}`; `run` (`:785`) resolves the role by subject kind for `resource_version >= 27`;
`AgentTurnRequest.constitution.role` (`:884`) and `bind_execution(role=…)` follow; the trace name
becomes `person-research.turn`. Role gates become `authority.role not in RESEARCHER_ROLES`
(`RESEARCHER_ROLES = frozenset({"account_research", "person_research"})` in
`arv2/quality_authority.py`) at `quality_provider_tools.py:142`, `quality_json_dossier.py:198`,
`quality_views.py:210, 215, 308`, `quality_tools.py:89`; `quality_committee_tool.py:88` stays
account-only. `build_agent_profile_registry` iterates `C6_ACTIVE_PROFILE_VERSIONS` only
(`agent_registry_wiring.py:960-1021`), so an enum member outside it is tolerated exactly as
`RESEARCH_CLAIMS` is (Q50). Reasoning effort reads `PERSON_RESEARCH_AGENT_MODEL_EFFORT`
(`agent_model.py:1228-1232`); the driver's `ARV2_PERSON_AGENT_MODEL` stays the model-id override.

**Migration (hash id, Q49 — every role constraint: five constraints, six predicates (02 §3.8), with the sites that install them):**
`agent_turn_role` (`7e9269ed8a81:70-72`, re-installed by `f4b30cb3d088:23-26`), `agent_plan_role`
(`6628a407e993:59-62`, re-installed by `f4b30cb3d088:23-26`), `agent_delegation_roles`
(`f4b30cb3d088:27-30`), `agent_model_call_role` (`65880921cd52:20-25`, re-installed by
`c237eb027732:29-41`), and the `quality_execution_role` **root predicate** (`f4b30cb3d088:70-72`:
`parent_execution_id IS NULL AND role='account_research'` → `role IN ('account_research',
'person_research')`). The earlier draft's "`agent_model_call.role` has no CHECK" was wrong
(review A W1). `upgrade` re-creates each with the widened list (the `_roles(values)` helper of
`f4b30cb3d088:21-30` is the template); `downgrade` refuses while any row carries
`person_research`, else restores the exact previous bodies.

**Settings.** `PERSON_RESEARCH_AGENT_MODEL=x-ai/grok-4.6`, `PERSON_RESEARCH_AGENT_MODEL_EFFORT=
medium` (model block, beside `ACCOUNT_RESEARCH_*`); the `ARV2_PERSON_AGENT_MODEL_EFFORT` comment
(`.env.example:419`) says "catalog v1–v3 only".

**Tests.** Offline: `tests/agents/test_contracts.py`; `test_quality_json_dossier.py` (the v27
person profile's role resolves); `tests/agents/test_agent_model_env_override.py`. DB:
`tests/arv2/test_quality_execution_db.py:56` with role `person_research`;
`test_quality_driver_db.py:155` (a 27 person job binds `person_research`; the first governed tool
call's `agent_plan` INSERT succeeds — the W2 failure mode). Smoke.

**Acceptance.** `agent_model_call.role = 'person_research'` on every r27 person call.
**Rollback.** Recipe 26; the migration is additive.

### W3-23 — The extractor (B) — leaf call (R12), 01b's quote rule (R8), 03's bounds

Owner `L` (leaf) + `A` (the envelope binding). Effort L. Deps W0, W1-5. Gate *r27* + settings.

**Change.** New `arv2/quality_extract.py`: `extract_sources(runtime, sources, *, subject,
classes) -> ExtractionResult(candidates, rejected, calls)` with `SourceText = (source_id, path,
url, title, date, text, kind)`, `SubjectSpec = (kind, name, domain, anchor)`.

- **Call** (03 §3.5.2): `openrouter_chat_request(model, messages=[system, user], temperature=0,
  max_tokens=CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS (2000, R16(c)), response_format=json_object,
  reasoning=effort)` through `runtime.call_provider("extract", hop)` with `CallSpec(provider=
  "openrouter", operation="chat/completions", label=f"extract-{operation_id}[-{chunk}]",
  estimate=SpendEstimate(usd=Decimal("0.01")), cost_reader=openrouter_cost_reader,
  halt_rule=openrouter_halt_rule, extras={job_id, workspace_id, purpose: "extract"})`
  (`structuring_client.py:1187-1213`); key/base URL from `runtime.clients.openrouter_api_key` /
  `openrouter_base_url` (`_LiveClients`, `account_research_driver.py:2471-2475`; Q52). Model
  `RESEARCH_EXTRACT_AGENT_MODEL` / `_EFFORT` (default `google/gemini-3.8-flash`, 03 §10 C6; a blank
  value refuses composition with `extractor_model_unset` when an r27 pilot is configured, §0.6).
- **Batching/bounds** (03 §3.5.2, review A C19): sources ≤ `EXTRACT_CHUNK_CHARS` (20000) packed
  `EXTRACT_BATCH_SOURCES` (4) per call up to `EXTRACT_BATCH_MAX_CHARS` (24000); larger sources
  chunked at 20000 with 500 overlap, absolute offsets carried; **a `finish_reason=length` reply
  splits the batch/chunk in half and re-runs** (deterministic, never a same-request retry — review
  B edit 9); invalid JSON → one repair retry (`EXTRACT_RETRIES` 1) then `extract_failed`;
  concurrency `_semaphore("extract")` = `EXTRACT_CONCURRENCY_PER_JOB` (6) plus a handler-wide
  `EXTRACT_CONCURRENCY_PER_PROCESS` (16) semaphore beside `_jobs`; wall `EXTRACT_WALL_S` (180):
  skipped sources are re-run once with the per-process semaphore halved, then the subject lands
  `needs_review/extract_incomplete` — never a silently thinner pool (review B §3.16).
- **Prompt** `platform/agents/catalog/research-quality/extractors/candidates/v1/SYSTEM.md`
  (sha-pinned in `launch-v4-r27.json`): the 03 §2.1 class table per subject kind, the quote rule,
  the anchor rule, the use-class rule, **`entities[]` per candidate** (R9: 03 §4.1's ten kinds — `person|org|vendor|
  programme|event|url|phrase|prior_employer|subject_site_page|title`), the output schema, no seller context.
- **Mechanical checks** (03 §3.5.3): the quote rule is **01b §5 implemented as an extension of
  `substring_verdict`** (`arv2/text.py:44-67`; R8): `normalize_for_match` (`:25-41`) gains folding
  of literal escape sequences (`\n`, `\t`), every dash to `-`, and boundary-punctuation stripping;
  `quote_verdict(quote, source_text)` splits on at most one `[…]`, requires ≥
  `QUOTE_ELISION_MIN_WORDS` (8) words per span when elided, accepts iff every span is `EXACT`
  and every digit/date token inside the span matches the source exactly (the one drift that
  survives the normaliser); `PARTIAL` rejects; `QUOTE_MAX_CHARS` 600. The earlier "keeps
  punctuation" wording is withdrawn (Q51). Typed values: the offset slice normalises to `raw` and
  parses by kind. Anchor (contacts): LinkedIn slug/URL **or** employer + ≥ 1 title token in the
  same source → `matched`; else `cls = unbound_hook`, imported with `write_markers.unbound=true`
  and withheld by the page view (`WITHHELD_STATUSES` gains the class; `FindingProposal` already
  sets `outreach_safe=False` and `identity_binding=WEAK` for every person finding —
  `dossier_import.py:76-78` — so the marker is what distinguishes it; Q53). Use-class override to
  `sensitive` on a `person_compliance.KEYWORDS` hit (`:53`). Every drop is counted; nothing raises.
- **DSAR binding of the envelope (coordinator point 3; review A K3/Q55; A-owned):** a
  `call_provider("extract", …)` has no operation, `index_acquisition` skips `openrouter` rows
  (`quality_acquisition.py:53`) and `_drain` binds nothing — so the raw envelope (which carries the
  request = the contact's quoted text) would be an unbound artifact. `_drain`
  (`account_research_tools.py:596-688`) gains, for calls labelled `extract-*`, an
  `agent_artifact_subject` row for the response artifact key (`ledger.py:258-266` is where the key
  is known) and `artifact_derivation` rows from each extracted source artifact to it, so erasure
  cascades (`artifact_erase_derivatives`, 02 §3.7).

**Settings** (03 §10 C6 names): `RESEARCH_EXTRACT_AGENT_MODEL=` (blank), `…_EFFORT=low`,
`CLUE_ARV2_V26_EXTRACT_BATCH_SOURCES=4`, `…_BATCH_MAX_CHARS=24000`, `…_CHUNK_CHARS=20000`,
`…_CHUNK_OVERLAP_CHARS=500`, `…_MAX_OUTPUT_TOKENS=2000`, `…_RETRIES=1`,
`…_CONCURRENCY_PER_JOB=6`, `…_CONCURRENCY_PER_PROCESS=16`, `…_WALL_S=180`,
`CLUE_ARV2_V26_QUOTE_ELISION_MIN_WORDS=8`, `CLUE_ARV2_V26_QUOTE_MAX_CHARS=600`,
`CLUE_ARV2_V26_EXTRACT_DEEP_RESULT_TEXT=true`; when D4 is set, `CLUE_AGENT_MODEL_CONTEXT_WINDOWS`
gains the model's window (guard `tests/test_agent_model_context_windows_settings.py:67`).

**Tests.** Offline: `tests/arv2/test_quality_extract.py` (packing; a 56k source → 3 chunks with
absolute offsets; halve-on-length; a non-verbatim quote dropped; unanchored → `unbound_hook`;
`entities[]` present); `tests/arv2/test_text.py` (01b §5 cases: NFKC, curly quotes, dashes,
whitespace, `\n`, boundary punctuation, case, one elision ≥ 8+8, a digit drift rejected, typed
title/date). DB: `_drain` binds the extract envelope to the subject with derivation rows. Replay:
`tests/arv2/v26/test_extract_recall.py` (AT-1 ≥ 0.95 on both frozen person request shapes; AT-7
≥ 41/43) — spends; `@pytest.mark.replay`.

**Acceptance.** AT-1, AT-5, AT-7; extraction ≤ $1.0 Flash / $0.3 Luna per account + 5 at the
ceiling (03 §5.5).
**Rollback.** `CLUE_ARV2_V26_ACQUISITION_PLAN_ENABLED=false` (W3-22) stops the pre-step's B; the
judge's `@2` extraction follows the same flag.

### W3-22 — Acquisition plans (A1/A2), the follow-up floor (A3), the gap round (R9, R10)

Owner `L` (pure modules) + `A` (the pool-read helper). Effort L. Deps W0, W1-9, W1-14, W3-23.
Gate *r27* + `CLUE_ARV2_V26_ACQUISITION_PLAN_ENABLED`.

**Change.** `arv2/acquisition_plan.py::plan(subject, compile, settings) -> AcquisitionPlan`
(pure; `plan_sha = sha256(canonical_json(plan))`; the date variable rounded to the month start —
03 §3.3.1). Templates are **03 §3.3.2/§3.3.3 plus the four R10 fetch templates**:

| Subject | Templates |
|---|---|
| account | `T_leadership, T_hiring, T_stack, T_news_funding, T_abm_programme, T_customers_proof, T_pain, T_succession` (8 searches, 03 §3.3.2 queries), `T_ats`, `T_account_deep` (charter from `provider-requests/account-deep/v2`), `T_cited_pages` (≤ 10), **`T_homepage`** (`fetch_page https://{domain}`), **`T_site_pages`** (≤ 4 fetches of `/careers`, `/news|/blog|/press`, `/about|/team`, `/benefits` when present among the homepage's links; 404 tolerated) |
| contact | `P_linkedin_posts, P_talks, P_bylines, P_employer_mentions, P_team_postings, P_news` (6 searches), `P_person_deep` (`provider-requests/person-deep/v2`, D9 caps), `P_cited_pages` (≤ 6), `P_enrich`, **`P_profile`** (`fetch_page {linkedin_url}`, `max_chars` 8000), **`P_post_pages`** (≤ 4 `fetch_page` of `linkedin.com/posts/` URLs returned by `P_linkedin_posts`); a web-gap contact prefixes `lookup_person(linkedin_url)` |

Variables come from the subject row, the kept AI Ark record and the **A0.0 compile** (W3-21;
Q56). `run_plan(runtime, plan, *, pool_read)` gathers per stage through the existing inner bodies
(`_search_web`, `_fetch_page`, `_research_deep`, `_read_ats_board`, `company_lock`,
`_lookup_person`, `_enrich_contact`) under the per-provider semaphores and the AI Ark lock;
`depends_on` orders the cited-page and post-page fetches after their producers. **Pool-read rule
(03 §3.3.4, A helper in `arv2/research_operations.py`):** before any `fetch_page`, look up an
account-level `arv2_evidence_source` by `source_url` for `(ws, run, account)`; a hit serves the
stored body to B and writes the free local operation `v26_pool_read`; a byte-identical `search_web`
already `succeeded` for the account job is served from its stored result (request-sha keyed,
account kinds only — never `person_*`); escapes are counted (`arv2.v26.duplicate_fetch`).

**The ledger entry per operation (03 §4.2; review A C34):** `{op, kind, template, query, state,
result_count, http_status, candidates, rejected, follows, pool_read, provider_ms}` plus the
trailer `{minimums: {class: {required, before_gap, after_gap}}, budget: {operations_max,
operations_used}, absent_pools | account_pool}`; `follows` is the triggering candidate id /
template id / operation id — what AT-9 reads.

**Follow-ups (R9):** `arv2/followups.py::plan_followups(pool, ledger, rules, round) ->
list[PlannedOperation]` (pure): rules from `followups/v1/rules.json` (W0 deliverable 1, sha-pinned
→ part of `plan_sha`); 03 §3.4's five trigger kinds — `class_terms` (`any_of` tokens of
`finding`), `attribute` (`source.kind`, `attribution.kind`, `evidence.value_kind`), `ledger` (a
template id in state `empty | failed`), **`entity`** (`classes + entity_kind`, templates
referencing `{entity.text}`, `{candidate.source.url}`, `{candidate.typed_value}`, `{name}`,
`{seat}`, `{vendor}`) and `result` (round 2 only: a round-1 result URL matching `when`) — each
rule carrying `operations[]` (round 1 and, where set, `round: 2`); every one of
01b's 11 floor pairs is expressible (review B §2.2); `max_per_trigger`/`max_per_round` per rule;
dedupe across both rounds and against the ledger; cut at `FOLLOWUP_OPS_PER_ROUND_ACCOUNT` /
`_PERSON` — **11 / 8**, 03 Appendix C's own rule ("01b maxima + 1": 01b T1 per-run follow-up
maxima 21 account / 14 contact over ≤ 2 rounds) now that 01b exists; 03 §10 C5 adopts the values.
Operations carry `kind="v26_followup:<rule_id>"`. ≤ `FOLLOWUP_ROUNDS_MAX` (2) rounds, each + B.
**Gap round** (03 §3.5.7): per class below its `MIN_*` (03 §2.1 — `trigger 3, committee 4,
initiative 1, own_words 2, problem_now 1, remit 1`), ≤ `GAP_OPS_PER_CLASS` (2), one round; the
**committee gap nominates** LinkedIn-bearing results through the web-nomination body up to
`committee_cap` (03 §3.2; M4; Q58).

**Settings** (03 §10 C4/C5): `CLUE_ARV2_V26_ACQUISITION_PLAN_ENABLED=true`, `AS_OF_DATE=` (blank =
today; the replay's `--as-of`, 05 §2.1), `ACCOUNT_SEARCH_NUM_RESULTS=8`, `ACCOUNT_SEARCH_TEXT_MAX_CHARS=1500`,
`ACCOUNT_DEEP_NUM_RESULTS=40`, `ACCOUNT_CITED_FETCH_MAX=10`, `ACCOUNT_SITE_PAGES_MAX=4` (R10),
`PERSON_SEARCH_NUM_RESULTS=8`, `PERSON_CITED_FETCH_MAX=6`, `PERSON_POST_PAGES_MAX=4` (R10),
`FETCH_MAX_CHARS=8000`, `RECENCY_DAYS=270`, `DEEP_SURFACE=search-deep-reasoning` (D8; already
pinned by `exa_client.py:523`), `ACQUIRE_WALL_S=300`, `SUBJECT_LOCK_RETRY_S=15`, `DRAIN_RETRIES=1`,
`FOLLOWUP_ROUNDS_MAX=2`, `FOLLOWUP_OPS_PER_ROUND_ACCOUNT=11`, `FOLLOWUP_OPS_PER_ROUND_PERSON=8`,
`GAP_ROUNDS_MAX=1`, `GAP_OPS_PER_CLASS=2`, the `CAP_*`/`MIN_*` rows (§9).

**Tests.** Offline: `tests/arv2/test_acquisition_plan.py` (account: 8 searches + ATS + deep +
homepage + ≤ 4 site pages + ≤ 10 cited; contact: 6 searches + deep + profile + ≤ 4 posts + ≤ 6
cited + enrich; byte-stable `fingerprint` across renders); `tests/arv2/test_followups.py` — AT-3:
each floor pair's rule fires on a synthetic candidate with the right `entities[]`, dedupe, no third
round, the 11/8 cut; AT-2: a pool missing `committee` yields the committee gap templates. DB:
new `tests/arv2/test_pool_read_db.py` (review A W9) — a URL already indexed for the account is
served without a provider call and writes `v26_pool_read`; never a `person_*` kind. Replay: AT-9
split (05 §3): floor-pair reproduction = 1.0 (gating) and judge-only chain recall ≥ 0.75 (reported).

**Acceptance.** ≈ 100–125 provider calls per account + 5 inside the first 3 min; zero
repurchased `(kind, request_sha256)` within an account; AT-2, AT-3, AT-9.
**Rollback.** `CLUE_ARV2_V26_ACQUISITION_PLAN_ENABLED=false`.

### W3-21 — Compile, committee and the pre-step (A0.0, A0; the two pool markers; the waits) (R5)

Owner `A` (the `qrw` reorder, the nominate refactor, the markers); `L` (`committee_rank.py`,
templates, the compile prompt). Effort L. Deps P1, P6, W1-8, W1-9, W3-22, W3-23, W3-26.
Gate *r27* + the W3-22 flag.

**Change.**

1. **`ResearchUnitRuntime.run` reorder (`qrw:781-1140`):** hoist `bind_execution` +
   `resolve_authority` out of `bindings()` (`:697-711`) into `prepare_authority(execution)`
   called after the lease (`:823-830`) — it needs the role (`resolved.profile.role`) and
   `self.limits` (built in `build_quality_job_runner`), both in hand (Q59). New order: recipe
   start → profile/model → lease → `prepare_authority` → **pre-step** → card/budget/manifest/task
   artifacts (the task embeds the pool, W3-24) → request → `turns.create` → `bindings` →
   committed-outcome check → `begin_runtime` → context assembly (03a §5.4 item 5). A crash inside
   the pre-step leaves an execution row with no turn; the markers make the re-drive resume at the
   first missing stage (03 §6.3).
2. **Stages and markers (03 §3, 03 §3.5.5 — R5's two pool markers), `arv2/prestep.py`:**

   | Job | Stages | Markers (`artifact_reference.reference_kind:reference_id`) |
   |---|---|---|
   | account | A0.0 compile → A0 committee → A1 → B → A3 (≤ 2, each + B) → gap (+ B) → wait for the children's **final** pools → C → E → settle | `research_compile:<context_id>` · `research_committee:<job>:<plan_sha>` · `research_candidates_first:<job>:<plan_sha>` (the **first** pool, after A1 + B) · `research_candidates:<job>:<plan_sha>` (after the gap round) |
   | contact | A2 → B → A3 → gap → wait for the account's **first** pool → C → settle → page (P1) | `research_candidates_first` · `research_candidates` |

   Each stage reads its marker and skips when present; the pool artifact
   (`application/vnd.clue.research-candidates+json` = `{subject, plan_sha, candidates[], ledger[],
   stats}`) is persisted content-addressed with `subject_bindings`, `project_bindings` and
   `artifact_derivation` rows from every source artifact (`quality_research_artifacts.persist_body`,
   03a §5.4 item 2); candidates also live inside each operation's result value
   (`value["candidates"]`, `value["extraction"]`) so B is per-operation idempotent. Progress rides
   `input_refs.v26_stage` (03 §6.1 vocabulary and fractions; M7) through a `set_job_input_ref`
   jsonb merge — no `stage` CHECK migration.
3. **A0.0 compile (03 §3.2; M3; Q56):** one `openrouter` leaf call per pinned context
   (`research_compile:<context_id>`, cached) producing `roles[{persona, titles, seniority,
   functions}]` + `search_terms{category_tools, problem_terms, icp_terms, seats}`, validated
   against `SENIORITY_VALUES`/`function_values()` (`ai_ark_client.py:76-82`), ≤ `ROLE_TITLES_MAX`
   (12) titles per persona; a persona with no valid titles uses `DEFAULT_ROLE_TITLES` (code
   constant per `Persona` value) and the ledger records `role_titles_source=default`. An ICP or
   persona document front-matter `titles:` / `search_terms:` block is copied **verbatim** when
   present (review B §3.13 — vocabulary becomes ICP-authored data); the compile artifact for each
   pilot context is frozen as `tests/arv2/v26/fixtures/compile_<context>.json` and read once.
   Model: `RESEARCH_EXTRACT_AGENT_MODEL`.
4. **A0 committee (03 §3.2):** `company_lock` then one `people_roles` per persona in the order
   `economic_buyer, champion, technical_evaluator, blocker, user` (`size = ROLE_SEARCH_SIZE` 5) —
   the `people_roles` body called directly, not `discover_people` — six paced AI Ark calls, a
   **63 s floor**; credits 0.1 + 12.5 + 5 exports × 1.0 = **17.6** per account + 5 (review A C15).
   Ranking `arv2/committee_rank.py` with **03's formula only** (Q60): `role_fit` 1.0/0.5,
   seniority map `{c_suite 1.0, owner/founder/partner 0.9, vp 0.8, head 0.7, director 0.6,
   manager 0.4, senior 0.3, other 0.1}`, footprint 1.0 if `linkedin_url`; `score = 3·role_fit +
   2·seniority + footprint`; best per persona then fill to `committee_cap`; ranks 2–
   `COMMITTEE_ALTERNATES_PER_ROLE` (3) become `committee_alternate` candidates in the account pool.
   Nomination = `nominate_candidate(conn, storage, scope, authority, args, *, actor_ref)`
   extracted verbatim from `NominateCommitteeTool.invoke` (`quality_committee_tool.py:82-232`) and
   called **once per contact in its own transaction** (the parent-row `FOR NO KEY UPDATE` is held
   per call, never across A0's 63 s; Q61) with the mechanical brief. **Enqueue (coordinator point
   2; review A C38/K2):** the pre-step runs inside `ResearchUnitRuntime`, composed without a
   queue (`fleet_main.py:790-792`); it writes the job rows and `register_child` only; the driver's
   sweep (`account_research_driver.py:951-975`, W1-8's TRUE branch) offers them within 10 s.
   Marker `research_committee`. Failure table = 03 §3.2 (429/5xx, halt, 0 or > 1 companies →
   `domain=` scope, < `MIN_COMMITTEE` → the web-gap round, DBAPIError drain retry).
5. **Waits (R5, 03 §3.6.4):** a contact pre-step waits ≤ `ACCOUNT_POOL_WAIT_S` (120 s, poll 5 s)
   for the parent's `research_candidates_first` (first pool ≈ t+90 s), then proceeds with the
   class-filtered slice present (possibly empty, recorded); the account pre-step, after its own
   final pool (`research_candidates`), waits ≤ `PEOPLE_POOL_WAIT_S` (240 s) until every registered child has
   `research_candidates` or is terminal (W1-8's predicate), then assembles the L7 with the
   **people slice** — top `PEOPLE_SLICE_PER_CONTACT` (20) candidates per contact by
   `class ∈ {remit, problem_now, own_words, proud_of}` then confidence — and the trailer's
   `absent_pools`. The turn's context is a recorded fact (its sha in the context receipt).
6. **DSAR bindings (M15; 03 §3.9, A-owned):** the account job's `AgentTurnRequest` lists every
   committee contact among its subjects so the L7 task artifact and the `agent-model-input`
   artifacts (`agent_runtime_wiring.py:163-196`) carry each contact's binding; a contact erasure
   then makes the account turn un-replayable — accepted (02 §10 item 17).

**Settings** (03 §10 C3/C7): `ROLE_TITLES_MAX=12`, `ROLE_SEARCH_SIZE=5`,
`COMMITTEE_ALTERNATES_PER_ROLE=3`, `PEOPLE_SLICE_PER_CONTACT=20`, `ACCOUNT_SLICE_MAX=60`,
`PEOPLE_POOL_WAIT_S=240`, `ACCOUNT_POOL_WAIT_S=120`, `L7_MAX_TOKENS_ACCOUNT=40000`,
`L7_MAX_TOKENS_PERSON=32000` (all `CLUE_ARV2_V26_*`).

**Tests.** Offline: `tests/arv2/test_committee_rank.py` (03's formula on one fixture). DB:
`tests/arv2/test_prestep_db.py` with `ScriptedTransport` (`clue_api.arv2.transport`, as
`tests/arv2/test_quality_provider_db.py:18`) — drive once → six AI Ark operations, `committee_cap`
person jobs `not_started` with briefs and `arv2_generation_child` rows, the four markers, a pool
artifact with derivation rows from every source, `input_refs.v26_stage` progression; re-drive
with a bumped attempt → zero transport calls, identical pool sha; a contact pre-step with no
parent pool after a 1 s (test) wait records `account_pool: "absent"`; **AT-8 (real, R5):** the
account L7 contains ≥ 1 candidate from each present contact's pool, and on the replay the
org-sequence finding (Dialpad: CMO departure → SVP Marketing hire) is emitted.

**Acceptance.** A0 ≤ 63 s + lock waits; person jobs offered before the account's first Exa
call; AT-8; the stage card never reads "researching 0.0" past t+10 s.
**Rollback.** `CLUE_ARV2_V26_ACQUISITION_PLAN_ENABLED=false`.

### W3-24 — The judges (C): `submit_brief@1`, one emission round, budgets, clearing (R3, R6)

Owner `L` (prompts, the tool body) + `A` (wiring, budgets, the mint). Effort L. Deps W3-21,
W3-22, W3-23, W3-26, W1-1, W1-2, W1-5. Gate *r27* + settings.

**Change.**

1. **The pool in context (03 §4.3; Q64, Q65):** the task artifact (`qrw:867-879`) gains
   `pool_text` — the pool and ledger **rendered as compact text** (one line per candidate:
   `c_id | class | date | url | finding | "quote"`; one line per ledger entry; the trailer), not
   JSON-in-JSON — and the research L7 source (`TurnLayerSource`, `clue_agents/context.py:625`)
   emits `objective + completion_contract + context block + pool_text` as the human message. The
   JSON pool is materialised as `inputs/candidates-<kind>.json` by a new `PoolFocusSource`
   (`ContextLayer.L5_FOCUS`, `contracts.py:952`) passed to `build_agent_context_assembler` through
   a new `focus_source` argument (`agent_platform_wiring.py:514`, A) and emitted as a
   `ContextCandidate(materialized_path=…)` (`context.py:144-158`). The research policy budgets
   `(24000, 0, 12000, 0, 2000, 0, 16000)` (`qrw:376-383`) become `(24000, 0, 12000, 0, 120000, 0,
   160000)` for `resource_version >= 27`; the hard bound is 03's `L7_MAX_TOKENS_*` trim per class
   by rank (never below a minimum), recorded in the trailer.
2. **`submit_brief@1` (R3; Q62, Q63) — `arv2/quality_brief_tool.py`:** input `{sections:
   [{section: <class id>, findings: [FindingRecord…]}], coverage_note?}` (03 §3.7); the nine
   server-side derivations **in 03 §3.7's order**: ids; evidence copied/restored from the cited
   candidate (re-verified with `quote_verdict`, `quote_restored` marked); `claim_type` default;
   **`review` derived, never asked** (`potential_conflict` / `wrong_entity` / else `supported`
   with `write_markers.review_defaulted=true`; never `insufficient_context`, never `duplicate`);
   `value_json` extras + `rank` + `personas`; over-cap marking (`write_markers.over_cap=true`,
   imported, never served — 01b §6 caps); interpretation presence on the marked classes
   (`errors[]`); `not_found` op ids and `synthesis` ≥ 2 distinct URLs (AT-4); contact `use_class`
   may only tighten, unanchored only under `hook`. `errors[]` non-empty → `{accepted: false,
   errors[], corrected_fields[]}` returned (a value, not a raise); else persist exactly as
   `_persist` (`quality_json_dossier.py:85-149`) and run the **unchanged `finish_dossier` body**
   (freeze, `import_id`, `import_research_dossier` → `submit_proposal` → claims, receipt,
   `mark_account_import_ready`) with the importer parsing through `EntryV2` (W1-2). Returns
   `{accepted: true, path, version, claim_ids[], import, over_cap, restored_quotes}`.
   `DOMAIN_IDEMPOTENT` on the document sha; a DB exception inside the import is the one raise
   (budgeted, `retry_of`-repairable). `BRIEF_RESUBMITS` (2): a third rejection → the model is
   told to `finalize_turn(status="blocked")` → `needs_review/brief_invalid`. **One emission
   round**: the prompt mandates a single `submit_brief` call carrying every class section.
3. **Finish sequence (Q66):** `submit_brief` → `finalize_turn(status="completed", user_message=
   <one paragraph>)` alone in its batch. The judge does **not** write `/outputs/research.json`:
   the completion guard builds it from storage for `uses_json_dossier` recipes
   (`qrw:1033-1054`), as it does today.
4. **Candidates from the tool (03a §8b):** `AcquireResearchTool2.invoke` runs `extract_sources`
   over the operation's result texts (`exa_source_texts`, `quality_acquisition.py:269-281`, plus
   the deep `report`) after `tool.ainvoke`, stores `value["candidates"]`/`["rejected"]`/
   `["extraction"]` so the `won=False` path serves them, applies the pool-read rule before
   dispatch, and returns ≤ `RECEIPT_CANDIDATES_MAX` (20) inline with `candidates_path`. A
   `pool_read` serves the source operation's stored candidates and never re-runs B.
5. **Operation budget (03a §8e; review A C27 — 04's predicate):** in `operations.begin`'s
   transaction, `SELECT count(*) FROM arv2_research_operation WHERE workspace_id=:ws AND job_id=
   :job AND kind LIKE 'quality_tool:%' AND state <> 'failed'` (argument refusals create `failed`
   rows, `quality_provider_tools.py:301-315`); ≥ `ACCOUNT_MAX_OPERATIONS` (30) / `PERSON_…` (15)
   → the non-spending refusal `{"state": "refused", "code": "operation_budget_exhausted",
   "recovery": "Submit the brief from the candidates you have; cite not_found items to the
   ledger."}` before `begin` (no row, no spend).
6. **Per-role rounds, windows, clearing:** `build_quality_job_runner` (`qrw:1233-1238`) builds
   the `Allowance` from `ACCOUNT_MAX_MODEL_ROUNDS` (20) / `PERSON_…` (12) for
   `resource_version >= 27` by subject kind; the context cap and clearing are W1-1's r27 column
   (60k/56k; 45k/42k; keep 4; `acquire@2` **cleared**; R6).
7. **Fallback chain off for research roles (R16(b); an A-owned seam):** the chain is
   `GatewayConfig.fallback_models` (`libs/clue-config/clue_config/gateway.py:100, 182, 191`), read
   by `GovernedAgentChatModel` (`agent_model.py:1047`) through the one provider
   `build_agent_model_provider(config)` builds (`agent_model_wiring.py:13`) —
   `quality_research_wiring.py:785-794` only overrides `model_id` and cannot switch it. The
   change: `AgentModelProvider.build(model_id, …, role, fallback_models: tuple[str, ...] | None =
   None)` (`clue_agents/ports.py:200-208`; the wiring's implementation threads it into the
   `GovernedAgentChatModel` it constructs, `None` = the config chain), and
   `quality_research_wiring.py:785-794` passes `tuple(settings.arv2_v26_fallback_models)` (blank →
   `()`) for `account_research` / `person_research`. A primary failure past the gateway's retries
   and first-token timeout **suspends** the turn (`suspend_job`, `available_at = now +
   MODEL_RETRY_DELAY_S` 60 s, resume from the checkpoint; ≤ `MODEL_RETRY_SUSPENDS` 3 per turn,
   counted on `input_refs.v26_model_suspends`); the next failure lands
   `needs_review/model_unavailable` — never a priced call on another model (03 §3.6.5).
8. **Profiles/prompts/skills (r27):** `profiles/quality-account-research/v27/profile.yaml`
   (role `account_research`; tools `acquire_research_evidence@2`, `search_evidence@3`,
   `submit_brief@1`; **no nominate, no dossier tools** — 03 §3.6.1; `max_output_tokens` 16384,
   review A C36) and `quality-person-research/v27-person/profile.yaml` (role `person_research`;
   same tools; 12288). `recipe-v27.json` allowlists the pinned tools plus `finish_dossier@1`
   (called internally). Prompts `v27`/`v27-person` are **self-contained** (03 §3.6.1: the
   contract, the judge's job, the tool semantics, the brief record, the finish sequence; ≈ 5k /
   4.5k tokens); skills pinned: `governed-evidence/v5` (one page, on demand) and the brief record
   skills `campaign-brief-account/v1`, `campaign-brief-contact/v1` (the 03 §2.3 record and the
   class table, read on demand — review A C37). Allowed operations: 03 §3.6.1 (no `research_deep`,
   no media). **Person floor (R15, D11):** `quality_claims.py:587-590`'s predicate becomes
   `(not advisory) or recipe >= 27`, so `apply_person_floor` runs on every contact claim at import
   for r27 (03 §2.5).

**Settings** (03 §10 C7 + R16): `ACCOUNT_MAX_MODEL_ROUNDS=20`, `PERSON_MAX_MODEL_ROUNDS=12`,
`ACCOUNT_MAX_OPERATIONS=30`, `PERSON_MAX_OPERATIONS=15`, `ACCOUNT_CONTEXT_CAP_TOKENS=60000`,
`PERSON_CONTEXT_CAP_TOKENS=56000`, `ACCOUNT_CLEAR_TRIGGER_TOKENS=45000`,
`PERSON_CLEAR_TRIGGER_TOKENS=42000`, `CLEAR_KEEP_RESULTS=4`, `BRIEF_RESUBMITS=2`,
`RECEIPT_CANDIDATES_MAX=20`, `FALLBACK_MODELS=` (blank), `MODEL_RETRY_DELAY_S=60`,
`MODEL_RETRY_SUSPENDS=3`, `JUDGE_RAW_READS=false` (all `CLUE_ARV2_V26_*`).

**Tests.** DB: `tests/arv2/test_quality_brief_tool_db.py` — the nine derivations (a defaulted
review imports `supported`; a judge quote that fails the rule is restored from the candidate; an
over-cap item imports with the marker and is absent from the page view; a synthesis with one URL
is an `errors[]` row; an unknown `not_found` op id likewise; a replayed call returns the same
import); `tests/arv2/test_quality_provider_db.py` — the (N+1)-th acquire returns
`operation_budget_exhausted` with no row and no transport, a later `completed` finalization passes
`check_finalizable`; scripted Exa + scripted OpenRouter → `receipt.candidates` pass
`quote_verdict`, one `provider_call_ledger` row `provider='openrouter'` job-stamped, a replay
returns the same candidates; `tests/arv2/test_quality_driver_db.py:155` — an r27 person job's
allowance is (12, …), an account's (20, …), the model is built with no fallback chain; the
person-floor predicate on an r27 contact claim. Offline: `tests/agents/test_context.py` style —
the r27 L7 human message contains `pool_text` and the L5 materialisation at `inputs/candidates-
account.json` with the same sha, verified on a second lease; the five hard-coded tests (§8.3).
Replay: AT-2, AT-4, AT-6, AT-8, AT-9.

**Acceptance (RC-2; 03 §5.5):** expected ≈ $3.48 Flash / $2.72 Luna per account + 5 (≈ $4.3 at
realistic investigation), **modeled ceiling $9.4 / $8.1** (+$3.00 while D8 is unpriced), the
structural ceiling 03 §5.5 states; judge rounds ≤ 20/12; `compaction_events = 0`; zero failed
saves, refused finishes, refused listings, media calls, raw-view reads, repurchases, misattributed
employer facts.
**Rollback.** The pilot workspace back to 26 (P5).

### W3-25 — Per-section parallel page writer, written once (03 §3.8)

Owner `L` (writer) + `A` (the refresh path). Effort M. Deps P1, W1-10, W1-13. Gate *flag*.

**Change.** `page_writer.write_account_pages` / `write_contact_page` (`:300-356`): with
`settings.arv2_pages_per_section`, one `write_checked` per section over the **section packet**
(03 §3.8: seller brief, subject identity, the v2 section guide, the class slice per **03 §2.1's
class → section map** — review A C30; the committee roster for `buying-committee`/
`how-to-approach`; for contact sections the account's trigger/initiative/pain items ≤
`PAGE_ACCOUNT_CONTEXT_ITEMS` (10)); free-named r25/r26 dossiers get the whole dossier per section.
Gathered under `Semaphore(settings.arv2_display_max_parallel)`; per-section timeout
`PAGE_SECTION_TIMEOUT_S` (120), `PAGE_SECTION_REPAIRS` (1); `check_pages` per section. **Publish
atomicity (review B §4.1):** a page's sections are published in **one transaction** by
`publish_written` (`page_writer_runtime.py:514-588`) with `PageDraft(sections=…)` per section,
so the page is never visibly partial; a section whose repair fails → the page is **not** published
(03 §3.8: the other sections' drafts are kept in the writer artifact), the job lands
`needs_review/page_section_failed:<key>`, and the next attempt (≤ `PAGE_MAX_ATTEMPTS`) re-runs only
the failed section and publishes the whole page. The writer artifact (`research_page_writer`) stores `section_inputs: {key:
sha}` on the **first** write too (Q68); `rewrite_account_pages` for r27 rewrites every section
whose packet sha changed (03 §10 deliberately carries no `ACCOUNT_REFRESH_SECTIONS` list, C31 —
the packets decide; same cost when nothing changed) under the single continuation of W1-10. Model
`RESEARCH_NARRATIVE_AGENT_MODEL` (D4; value blank until set, as the extractor).

**Settings.** `CLUE_ARV2_PAGES_PER_SECTION=true`; 03 §10 C8's `PAGE_SECTION_TIMEOUT_S=120`,
`PAGE_SECTION_REPAIRS=1`, `PAGE_ACCOUNT_CONTEXT_ITEMS=10`, `PAGE_MAX_ATTEMPTS=2`, `PAGE_WALL_S=300`.

**Tests.** Offline: `tests/arv2/test_page_writer.py` (N sections → N calls; a failing section
repairs alone; class slices cover every finding once; 03 §2.1's map). DB:
`tests/arv2/test_page_writer_runtime_db.py:210` (a changed committee packet republishes one
section; a page with one failed section publishes the others in one transaction); `:139`.
Replay: `scripts/trial_page_writer.py` timing.

**Acceptance.** Account pages ≤ 60 s after `submit_brief`; one refresh per account at most;
pages ≤ $0.13 account / ≤ $0.31 five contacts (Flash), ceiling 2× (03 §5.5).
**Rollback.** `CLUE_ARV2_PAGES_PER_SECTION=false`.

### W3-27 — Observability, release tag, job spend (03 §8, §3.9; M8, M9)

Owner `A` (metrics module, `deploy.sh`, `add_job_spend`) + `L` (span attributes in the leaf
modules). Effort M. Deps W2-20. Gate `CLUE_ARV2_V26_METRICS_ENABLED=true`.

Spans `arv2.v26.<stage>` with 03 §8.1's attributes; the judge trace tags gain `v26`,
`account:<domain>`, `job:<id>` (02 §8.1: absent on v4 today); the `arv2.v26.*` metric set of
03 §8.2 in `libs/clue-obs/clue_obs/otel/metrics.py:30-41`; `CLUE_RELEASE` set by
`deploy/vm/deploy.sh` from the git sha (03 §8.3); `add_job_spend` (fenced on `status=
'completed'`) so the refresh's and the contact page's ledger rows reach `arv2_research_job.
cost_usd` (02 §8.5 item 9). **Langfuse trace cap (M9):** RC-1 and RC-2 record the max trace
bytes per job (`langfuse-observations/*.json` sizes) with a ceiling of 50 MB per job (half the
100 MB limit); the pre-step's ≈ 100 provider spans are 8k-masked per string
(`clue_obs/langfuse.py:74`). **Tests.** Offline: metric names registered; `tests/arv2/
test_quality_meter_db.py` (DB) — `add_job_spend` adds a later ledger row to the job's `cost_usd`
once. **Rollback.** The metrics flag; `CLUE_RELEASE` blank.

---

## §6 W4 — Media (D1)

Owner `A` (image, keys, boot gate) + `L` (resolver). Effort M. Deps W1-5, W1-12. Gate
`CLUE_ARV2_MEDIA_ENABLED` + the boot gate.

- **W4-1 image:** `docker/backend/Dockerfile:43-46` adds `ffmpeg` (provides `ffprobe`,
  `media_recording.py:99-108`).
- **W4-2 boot gate (03 §7 conditions 1–2; review A C32):** with the flag true the research
  handler's composition (`account_research_driver.py:2436-2491`) refuses unless
  `shutil.which("ffprobe")` and `shutil.which("ffmpeg")` resolve **and** `CLUE_DEEPGRAM_API_KEY` is
  set **and** one `provider_call_ledger` row `provider LIKE 'deepgram%' AND outcome='ok'` exists
  (the operator's one-time smoke transcription); logged `arv2.v26.media_gate`.
- **W4-3 resolver:** `arv2/media_resolution.py` gains Apple Podcasts (iTunes lookup → `feedUrl`
  → RSS episode match), Podbean/Buzzsprout/Libsyn/Simplecast/Transistor/Captivate (page
  `<link type="application/rss+xml">` or the host's feed pattern); Spotify stays
  `no_supported_recording_link`. Recorded fixtures under `tests/arv2/fixtures/media/`.
- **W4-4 receipts:** W1-5's `unavailable`/`tool_error` statuses carry the outcome.
- **W4-5 into A2 (03 §7):** `discover_media(query="{full_name} {employer} (podcast OR webinar OR
  talk)")` → candidates whose title/description name the contact → ≤
  `CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS` (3) `read_media`; the transcript is a `transcript` source
  and B extracts `own_words` under the quote rule; `media_seconds` ride the existing ceiling.

**Acceptance.** ≥ 1 transcript per account where the replay's known recordings exist;
`ffprobe` errors = 0. **Rollback.** `CLUE_ARV2_MEDIA_ENABLED=false`.

---

## §7 Sequencing

### 7.1 Dependency graph and branch pairs

```
W0 (01b consumed; pools; replay seam) ───────────────┐   M10 queries (A, day 1, needs D6)
P4 → W1-11      P5      P6      P1 → W1-8            │
W1-1  W1-6  W1-7  W1-10  W1-2  W1-3  W1-4  W1-5  W1-9  W1-12  W1-13  W1-14
         └───────────── r26 MINT (day 4) ◄── W1-2/3/5/9/12/13/14 ─────────┘ → RC-1 (day 5)
W2-20 → P3 → W2-16 → W2-17 → W2-15                      (weeks 2–3; W2-19 after RC-2)
W3-26 ─┐   W3-23 (leaf, week 2) ─┐   W3-22 (leaf, week 2; needs W0's rules.json)
       └──► W3-21 ◄──────────────┴────────────┘ (weeks 3–4)
            W3-24 → W3-25 → W3-27 → r27 MINT (week 5) → RC-2 ×2 → pilot (P5)
W4 when D1 says so (after W1-5, W1-12)
```

Branches that touch the same files integrate **in sequence**, not in parallel (review A C40/Q70):
W1-3 then W1-4 (`quality_views.py`, `quality_workspace.py`); W1-5 then W1-12
(`quality_provider_tools.py`); W3-23 then W3-24 (`quality_provider_tools.py`,
`quality_extract.py`). Every other W1 `L` branch is file-disjoint. Shared files Aryan integrates
in one pass per workstream: `quality_research_wiring.py`, `settings.py`, `.env.example`.

### 7.2 Integration order

Week 1: P6 → P5 → W1-1 → W1-6 → W1-7 → W1-10 → P1 → W1-8 → the `L` branches in item order (the
two pairs above in sequence) → the r26 mint → W1-11. Weeks 2–3: W2-20 → P3 → W2-16 → W2-17 →
W2-15, each after its test and W2-20's number. Weeks 3–5: W3-26 → W3-23 → W3-22 → W3-21 → W3-24 →
W3-25 → W3-27 → the r27 mint → RC-2 twice → pilot. W2-19 after RC-2.

### 7.3 The two replay checkpoints (the harness is 05's; the seam is W0 deliverable 5)

- **RC-1 (end of week 1, recipe 26)** — Dialpad + Loopio + ten contacts on the frozen pools:
  cost ≤ $17 and time ≤ 40 min per account + 5; 01 T3.1's error classes at zero
  (`schema_validation`, `trap_*`, `finalize_refused_unresolved_failures`, media) and
  `listing_refused` ≤ 2 per run; cached input share ≥ 85 %; nomination → first person ≤ 30 s;
  rewrites ≤ 1; AT-6 account tuples present; one Head-of-ABM launch replay (W1-6); max Langfuse
  trace bytes per job ≤ 50 MB. A second RC-1 timing run after W2-15 reads evidence call ≈
  provider + ≤ 8 s.
- **RC-2 (end of week 5, recipe 27, pilot workspace)** — AT-1…AT-9 as 05 §3 defines them
  (AT-9's three lines, 05 §3: the floor line = 1.0 gating, chain recall ≥ 0.90 per account gating,
  judge-only recall ≥ 0.75 reported, computed on the RC-2 recorded universe); 03 §5.5's expected and ceiling numbers with 05 §4.2's ×1.10 gate;
  `compaction_events = 0`; the zero list of W3-24. Passes **twice** before `CLUE_ARV2_RECIPE_
  VERSION` moves to 27. A re-driven judge turn after `quality_unit_incomplete` is a second full
  budget and is counted as a separate turn (05 §6.3).

### 7.4 Definition of done

- **W0:** the six deliverables; `test_fixtures.py` green; M10 results in `_memory/`.
- **P1–P6:** merged; DB tests green on a migrated local DB; `.env.example` lines present;
  P6's go/no-go test green before any r27 pilot.
- **W1:** every item's tests green in `make check` (+ DB locally); the r26 mint passes §8.3 and
  `make manual-check`; RC-1 met; `_memory/` closing entry.
- **W2:** W2-20's number before/after each item; the RC-1 timing re-run; `make db-smoke` with
  W2-17's migration; the lock-order review in W2-15's PR; `MAX_PARALLEL_JOBS` 4 → 6 taken.
- **W3:** the r27 mint; RC-2 passed twice; the pilot workspace on 27 for one real request within
  03 §5.5's ceiling.
- **W4:** D1 taken; the boot gate green; ≥ 1 transcript on the replay.

### 7.5 Week 1, day by day

| Day | `A` | `L` (task branches) |
|---|---|---|
| Mon | P4 (1 h); P6; P5; W1-1; W1-6; M10 queries if D6 is granted | W0 (rules.json from 01b, fixtures, replay seam); W1-2; W1-3; W1-4 |
| Tue | W1-7; P1 | W1-5; W1-12; W1-9; the clearing simulation script |
| Wed | W1-8; W1-10; review the Mon/Tue `L` branches | W1-13; W1-14 (eight folders); W1-11 prompt/tool text |
| Thu | **r26 mint** (§8) — profiles, recipe, launch map, ladder, `CURRENT_RECIPE_VERSION = 26`, the five tests; integrate; `make check`; DB tests; W1-11's HoA v71 + manual | W0 pool freeze + manifest; replay dry-run on one contact |
| Fri | RC-1; numbers against §7.3; `_memory/` entry; decide the W2 start | RC-1 support; W0 fixtures finalised |

---

## §8 Re-mint checklist (recipe 26, recipe 27, Head-of-ABM v71)

### 8.1 Files per mint

| Step | Recipe 26 (week 1) | Recipe 27 (W3) | Head-of-ABM v71 (W1-11) |
|---|---|---|---|
| Profiles | `profiles/quality-account-research/v26/profile.yaml`, `quality-person-research/v26-person/profile.yaml` — `status: active`, prompt `v26`/`v26-person` shas; skills account: governed-evidence v4, account-dossier **v10**, person-research-briefing **v5**, claim-ready-account-dossier **v4**; person: governed-evidence v4, person-dossier **v6**, person-depth-charter **v2**, claim-ready-person-dossier **v4**; tools `search_evidence@3`, `acquire_research_evidence@2`, nominate ×2 `@3` (account only), `save_dossier_section@2`, `update_dossier_findings@2`, validate/finish/begin/discard `@1` with their shas; `max_output_tokens` 16384 | `v27` (role `account_research`) / `v27-person` (role `person_research`): tools `acquire_research_evidence@2`, `search_evidence@3`, `submit_brief@1`; skills governed-evidence **v5**, campaign-brief-account/v1 (account), campaign-brief-contact/v1 (person); `max_output_tokens` 16384 / 12288 | `profiles/head-of-abm/v71/profile.yaml`: prompt `v19` sha; skills = v70's minus `account-research-briefing`; tools unchanged |
| Prompts | `prompts/quality-account-research/v26/SYSTEM.md`, `quality-person-research/v26-person/SYSTEM.md` | `v27` / `v27-person` (self-contained, 03 §3.6.1) | `prompts/head-of-abm/v19/SYSTEM.md` |
| Resources | the skill folders above; `provider-requests/account-deep/v2/*`, `person-deep/v2/*` | `followups/v1/rules.json`; `extractors/candidates/v1/SYSTEM.md`; `plans/account/v1/{charter.md,searches.json}`, `plans/contact/v1/{charter.md,searches.json,brief.md}` | the manual (`platform/agents/catalog/manual/tool_notes.yaml:88` rewritten; `make manual`) |
| Recipe | `recipe-v26.json`: `version: 26`; `tool_allowlist` = the v26 pins (drop `record_research_finding@3`, never exposed since v19), mirrored under `compatibility.nodes.research_interactions` | `recipe-v27.json`: the three pinned tools + `finish_dossier@1` (called internally) | the conversation recipe is unchanged (no tool pin moves) |
| Launch map | `launch-v4-r26.json`: `recipe_version: 26`, sha of every file above incl. the recipe; keep the r25 historical entries | `launch-v4-r27.json` | — |
| Code | `quality_catalog.py:14` → 26; ladder at `qrw:312-349`; gates `>= 26` | `= 27`; ladder; gates `>= 27`; `C6_ACTIVE_PROFILE_VERSIONS` unchanged (research profiles are not in it) | `agent_registry_wiring.py:257` → `"v71"`; `docs/agents/skill-and-profile-authoring.md:24` |
| Commands | tool shas: `uv run python -c "from clue_api.quality_research_wiring import quality_tools; [print(d.name, d.version, d.input_schema_sha256, d.output_schema_sha256) for d in quality_tools(None, None, purge=False).all_descriptors()]"`; file shas `shasum -a 256`; then the §8.3 tests | same | `make manual && make manual-check`; `tests/agents/test_tool_authority_audit.py` |

Template commit for a research mint: `7559c9bca` (r25), 02 §5.6.

### 8.2 Pins that move

Profile `prompt.sha256` (×2 per mint), each `skills[].sha256`, each `tools[].input/output_schema_
sha256` for `@2`/`@3`/`submit_brief@1` (the `@1` ones are copied from `v25/profile.yaml:25-66`),
every `resources` entry of the launch map; for v71 the prompt sha and the skill shas minus one.

### 8.3 The five hard-coded tests (02 §5.6 step 7)

| Test | Today | Recipe 26 | Recipe 27 |
|---|---|---|---|
| `tests/arv2/test_quality_owned_narrative.py:64` `== 25` | 25 | 26 | 27 |
| `tests/arv2/test_quality_json_dossier.py:30` (`== 25`), `:40-52` (`n + "@1"` for save/update), `:63-69` (skill versions) | as listed | 26; save/update `@2`; v10/v6, v4, v5 | 27; the dossier-tool assertions become "not pinned, `submit_brief@1` pinned"; the brief skills |
| `tests/arv2/test_account_research_port.py:26-27` (newest `recipe-v*.json`) | derives | passes with `recipe-v26.json` | with `recipe-v27.json` |
| `tests/agents/test_skill_references.py:42-80` | byte-equivalence of v21 vs v20 | **new assertion (Q69)** for `(26, 25)`: the v26 prompt renders every `{{skills.*}}` placeholder, every rendered path is mounted, and no `{{` survives — the byte-equivalence case stays for v21/v20 only | the same for `(27, 26)` |
| DB: `tests/arv2/test_quality_driver_db.py:155`, `tests/arv2/test_quality_reconciliation_db.py:569` (`== CURRENT_RECIPE_VERSION`) | derives | passes | passes; the launch-side assertions re-point at `recipe_version_for(ws)` (03 §9.3) |

Plus `test_quality_json_dossier.py:86` (the `@1` strict case stays; a `@2` case is added) and the
`range(2, 20)` resource-load loops extended to the new current in both files.

---

## §9 Config parity sheet (R7: regenerated from 03 §10 — one sheet)

**03 §10 is the settings sheet.** Every name, default, unit, read site and `.env.example` line
lives there, once; this section is regenerated from it, row for row, and adds only the owning
item. A row here that disagrees with 03 §10 is a defect in this section, never a second value.
Every row is a `Settings` field **and** an `.env.example` line with the same default, added by the
item that introduces it. `CLUE_ARV2_V26_*` rows are read only on r27 paths (field
`arv2_v26_<lower>`); the others apply to every recipe. Defaults marked D4/D8/D9/D3 are the
founder's; the sheet ships the value shown. `…_` abbreviates `CLUE_ARV2_V26_`.

| 03 §10 group | Setting | Default | Item |
|---|---|---|---|
| C0 r26/W2 switches | `CLUE_ARV2_ACCOUNT_CLEAR_TRIGGER_TOKENS` / `CLUE_ARV2_PERSON_CLEAR_TRIGGER_TOKENS` / `CLUE_ARV2_CLEAR_KEEP_RESULTS` / `CLUE_ARV2_ACCOUNT_CONTEXT_WINDOW_TOKENS` / `CLUE_ARV2_PERSON_CONTEXT_WINDOW_TOKENS` | 100000 / 100000 / 6 / 200000 / 200000 | W1-1 |
| C0 | `CLUE_ARV2_VIEW_FORMAT` / `CLUE_ARV2_VIEW_MAX_CHARS` · `CLUE_AGENT_L1_AS_MESSAGE` · `CLUE_ARV2_DRAIN_OUTSIDE_SLOT` · `CLUE_ARV2_PAGE_GUIDE_VERSION` | text / 80000 · false · true · v2 | W1-4, W1-6, W1-7, W1-13 |
| C0 | `CLUE_ARV2_RECOVER_ON_SUCCESS` · `CLUE_ARV2_JOB_MAX_DB_CONNECTIONS` · `CLUE_ARV2_INDEX_LAZY` · (existing) `CLUE_DB_POOL_SIZE`/`CLUE_DB_MAX_OVERFLOW` comment · `CLUE_ARV2_PAGES_PER_SECTION` | false · 3 (0 = the kill switch) · true · sized by P3 · true | W2-17, W2-15, W2-19, P3, W3-25 |
| C1 recipe | `CLUE_ARV2_RECIPE_VERSION` / `CLUE_ARV2_RECIPE_PILOT_VERSION` / `CLUE_ARV2_RECIPE_PILOT_WORKSPACES` | blank / blank / blank | P5 |
| C1 | `CLUE_ARV2_MEDIA_ENABLED` · `CLUE_ARV2_V26_METRICS_ENABLED` · `CLUE_RELEASE` (existing; set by `deploy.sh`) | false · true · — | W1-12, W3-27 |
| C2 caps (R10 = 01b §6) | `…_CAP_TRIGGER` / `_INITIATIVE` / `_PAIN` / `_MOTION_PROOF` / `_STACK` / `_COMMITTEE` / `_WATCH_OUT` / `_NOT_FOUND` | 10 / 5 / 5 / 5 / **8** / **10** / **4** / 3 | W1-14, W3-24 |
| C2 caps | `…_CAP_REMIT` / `_PROBLEM_NOW` / `_OWN_WORDS` / `_PROUD_OF` / `_HOOK` / `_CAREER_ARC` / `_DO_NOT_MENTION` | 2 / **5** / **8** / **3** / **4** / 1 / 1 | W1-14, W3-24 |
| C2 minimums | `…_MIN_TRIGGER` / `_COMMITTEE` / `_INITIATIVE` / `_OWN_WORDS` / `_PROBLEM_NOW` / `_REMIT` | 3 / 4 / 1 / 2 / 1 / 1 | W3-22 |
| C3 compile/committee | `…_ROLE_TITLES_MAX` · `…_ROLE_SEARCH_SIZE` · `…_COMMITTEE_ALTERNATES_PER_ROLE` · `committee_cap` (launch input, not env) · (existing) `CLUE_ARV2_AI_ARK_MIN_GAP_S` | 12 · 5 · 3 · 5 · 10.5 | W3-21 |
| C4 acquisition | `…_ACCOUNT_SEARCH_NUM_RESULTS` 8 · `…_ACCOUNT_SEARCH_TEXT_MAX_CHARS` 1500 · `…_ACCOUNT_DEEP_NUM_RESULTS` 40 · `…_ACCOUNT_CITED_FETCH_MAX` 10 · **`…_ACCOUNT_SITE_PAGES_MAX` 4 (R10)** · `…_PERSON_SEARCH_NUM_RESULTS` 8 · `…_PERSON_SEARCH_TEXT_MAX_CHARS` 1500 · `…_PERSON_DEEP_NUM_RESULTS` 12 (D9) · `…_PERSON_DEEP_TEXT_MAX_CHARS` 4000 (D9) · `…_PERSON_DEEP_HIGHLIGHT_MAX_CHARS` 1000 · `…_PERSON_CITED_FETCH_MAX` 6 · **`…_PERSON_POST_PAGES_MAX` 4 (R10)** · `…_FETCH_MAX_CHARS` 8000 · `…_RECENCY_DAYS` 270 · `…_DEEP_SURFACE` search-deep-reasoning (D8) · `…_EXTRACT_DEEP_RESULT_TEXT` true · `…_ACQUIRE_WALL_S` 300 · `…_SUBJECT_LOCK_RETRY_S` 15 · `…_DRAIN_RETRIES` 1 · `…_ACQUISITION_PLAN_ENABLED` true · `…_AS_OF_DATE` blank (= today) · (existing) `CLUE_ARV2_ACCOUNT_PROVIDER_CONCURRENCY` 4 | as listed | W1-14, W3-22 |
| C5 follow-ups | `…_FOLLOWUP_ROUNDS_MAX` 2 · `…_FOLLOWUP_OPS_PER_ROUND_ACCOUNT` **11** · `…_FOLLOWUP_OPS_PER_ROUND_PERSON` **8** · `…_GAP_ROUNDS_MAX` 1 · `…_GAP_OPS_PER_CLASS` 2 · the rules file `followups/v1/rules.json` (resource, not env) | as listed | W0, W3-22 |
| C6 extraction | `RESEARCH_EXTRACT_AGENT_MODEL` google/gemini-3.8-flash (D4) · `RESEARCH_EXTRACT_AGENT_MODEL_EFFORT` low · `CLUE_AGENT_MODEL_CONTEXT_WINDOWS` += the D4 model · `…_EXTRACT_BATCH_SOURCES` 4 · `…_EXTRACT_BATCH_MAX_CHARS` 24000 · `…_EXTRACT_CHUNK_CHARS` 20000 · `…_EXTRACT_CHUNK_OVERLAP_CHARS` 500 · `…_EXTRACT_MIN_CHUNK_CHARS` 2000 · **`…_EXTRACT_MAX_OUTPUT_TOKENS` 2000 (R16(c))** · **`…_EXTRACT_MAX_CALLS_ACCOUNT` 120 / `…_EXTRACT_MAX_CALLS_PERSON` 60** · `…_EXTRACT_RETRIES` 1 · `…_EXTRACT_CONCURRENCY_PER_JOB` 6 · `…_EXTRACT_CONCURRENCY_PER_PROCESS` 16 · `…_EXTRACT_WALL_S` 180 · `…_QUOTE_ELISION_MIN_WORDS` 8 · `…_QUOTE_MAX_CHARS` 600 | as listed | W3-23 |
| C7 judges | `…_ACCOUNT_MAX_MODEL_ROUNDS` 20 · `…_PERSON_MAX_MODEL_ROUNDS` 12 · `…_ACCOUNT_MAX_OPERATIONS` 30 · `…_PERSON_MAX_OPERATIONS` 15 · `…_ACCOUNT_CONTEXT_CAP_TOKENS` 60000 · `…_PERSON_CONTEXT_CAP_TOKENS` 56000 · `…_ACCOUNT_CLEAR_TRIGGER_TOKENS` 45000 · `…_PERSON_CLEAR_TRIGGER_TOKENS` 42000 · `…_CLEAR_KEEP_RESULTS` 4 · **`…_JUDGE_RAW_READS` false (R16(a))** · **`…_FALLBACK_MODELS` blank (R16(b))** · `…_MODEL_RETRY_DELAY_S` 60 · `…_MODEL_RETRY_SUSPENDS` 3 · `…_BRIEF_RESUBMITS` 2 · `…_RECEIPT_CANDIDATES_MAX` 20 · `…_PEOPLE_SLICE_PER_CONTACT` 20 · `…_ACCOUNT_SLICE_MAX` 60 · `…_L7_MAX_TOKENS_ACCOUNT` 40000 · `…_L7_MAX_TOKENS_PERSON` 32000 · `…_PEOPLE_POOL_WAIT_S` 240 · `…_ACCOUNT_POOL_WAIT_S` 120 · `PERSON_RESEARCH_AGENT_MODEL` x-ai/grok-4.6 · `PERSON_RESEARCH_AGENT_MODEL_EFFORT` medium · profile `max_output_tokens` 16384 / 12288 (pin, not env) · (existing) `ARV2_ACCOUNT_AGENT_MODEL`, `ARV2_PERSON_AGENT_MODEL`, `ACCOUNT_RESEARCH_AGENT_MODEL_EFFORT`, `CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S` 0 unchanged; `ARV2_PERSON_AGENT_MODEL_EFFORT` comment corrected | as listed | W1-1, W3-24, W3-26 |
| C8 pages | `RESEARCH_NARRATIVE_AGENT_MODEL` / `RESEARCH_NARRATIVE_AGENT_MODEL_EFFORT` (existing; D4 value change) · (existing) `CLUE_ARV2_DISPLAY_MAX_PARALLEL` 30 · `…_PAGE_SECTION_TIMEOUT_S` 120 · `…_PAGE_SECTION_REPAIRS` 1 · **`…_PAGE_MAX_ATTEMPTS` 2 (R16(d))** · `…_PAGE_ACCOUNT_CONTEXT_ITEMS` 10 · `…_MISC_SECTION` off (D3) · `…_PAGE_WALL_S` 300 · (existing) `CLUE_ARV2_PAGE_WRITER_TIMEOUT_S` 900 | as listed | W1-13, P1, W3-25 |
| C9 orchestration | (existing) `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` 4 → 6 after W2-15; `CLUE_ARV2_QUALITY_RECONCILE_INTERVAL_S` 10; `CLUE_FLEET_*` unchanged | — | P3 |

Guard tests: `tests/arv2/test_settings.py` (every row parses from the example),
`tests/test_agent_model_context_windows_settings.py:62-67`. Deliberately absent (03 §10): a
per-provider money cap, a judge wall-clock, any count of words in prose, a committee approval
gate, an `ACCOUNT_REFRESH_SECTIONS` list.

---

## §10 Migration checklist

| Item | Migration (hash id from `uv run alembic revision -m "<slug>"`; `down_revision` = the head at the time) | Reversible by |
|---|---|---|
| W2-17 | `arv2 ledger job and evidence ledger indexes` — two `CREATE INDEX` | `DROP INDEX` ×2 |
| W3-26 | `research roles admit person_research` — re-create `agent_turn_role`, `agent_plan_role`, `agent_delegation_roles`, `agent_model_call_role` with the widened list and the `quality_execution_role` root predicate with `role IN ('account_research','person_research')` | refuse while any row carries `person_research`, else restore the exact previous bodies |
| W2-19 (after RC-2) | `arv2 evidence source lazy bytes` — drop two `NOT NULL`s, add `arv2_evidence_source_lazy` CHECK | refuse while lazy rows exist (production: run `scripts/arv2_materialize_lazy_sources.py` first), else restore |

No migration in W1 or P1–P6. Current head `4a94970221e9` (`uv run alembic heads`). Rules: one
head after each merge; `make db-smoke` on a per-branch throwaway database before each merge;
parallel branches that both add a migration are joined with `alembic merge`; every `upgrade()` has
a `downgrade()`; no new enum values; no domain-table rewrites. 03 §1.1 counts W3-26 as the
design's one migration; W2-17 and W2-19 are W2's own — three in all (review A C35).

---

## §11 What is explicitly NOT changed, and why

- **The governed runtime's middleware order and semantics** (`runtime.py:641-666`), the 10 repair
  rounds, finalize-alone, `_MAX_FINALIZE_REPAIRS`, the fuse. W1-1 appends a request-only edit
  through the bindings seam; W1-6 changes what the assembler seeds; W3-21 reorders
  `ResearchUnitRuntime.run` (research-only) — the graph is untouched.
- **The C5 journal, `validate_plan`, `invoker.py`, `runner.py`, the A9 key, `recover()`, the
  receipt shapes.** The pre-step bypasses them deliberately (03a §7.3), covered by operation rows,
  subject-bound derivation-linked artifacts and the markers; the judges' own calls go through them.
- **The claims import path**: `finish_dossier`'s body, `import_research_dossier`,
  `submit_proposal`, the claim writer, `mark_account_import_ready`. `submit_brief@1` and the r26
  dossier tools feed it; the only touches are `EntryV2`'s shape, the `claim_kind` mapping and the
  importer's `entry_model` by recipe.
- **DSAR and privacy machinery**: `stop_contact_jobs`, `erase_provider_evidence`, the derivation
  and media triggers, `job_available`, the expiries — **P6 fixes the filter, nothing else moves**;
  the pre-step and extractor artifacts are bound so the existing paths cover them.
- **The display contract**: `ResearchSection`/`pending`, the `display_block` shape, `read_page`'s
  payload, the Zod schemas, the `arv2_display_page` kind and handler, the Luna path. Positions
  (data), the r27 Miscellaneous setting, one more writer line and per-section publish inside one
  transaction are the whole of it; `context-only` stays.
- **`arv2_research_operation`'s job-keyed identity** (W2-18), **`arv2_quality_allowance`'s
  columns**, the **fleet kinds and priorities**, the **launch contract** (seam 1; W1-11 shortens
  the brief), the **provider ledger** shape, the **Head-of-ABM runtime** beyond W1-6 and v71.
- **Historical recipes v2–v25**: no file under their folders is edited; `@1`/`@2` tools and
  `v1` provider requests stay registered and loadable.
- *Changed since the first draft, so no longer on this list:* the person compliance floor (R15,
  r27 only, D11); the `profile_ref` privacy filter (P6).

---

## §12 Questions that remain for Aryan (R17)

All 70 of review A's questions are resolved in text above (the 13 blocking ones — Q9, Q20, Q23,
Q26, Q30, Q35, Q49, Q51, Q56, Q62, Q63, Q66, Q69 — at W1-9/W1-2/W1-4/W1-5/W1-8/W3-26/W3-23/W3-21/
W3-24/§8.3). The last one, Q39 (part), was open with a recommended answer; it is now **decided**
(coordinator ruling, re-check 2) and carried as W1-11 mint step (3):

| # | Question | Decision |
|---|---|---|
| Q39 (part) | Does a Head-of-ABM profile change with unchanged tool pins require a bump of the conversation recipe (`agent_registry_wiring.py:252-256` says the recipe "pins exact addresses" and moved 32 → 33 on the last HoA mint)? | **No bump**: the recipe pins tool **addresses**, and v71 changes none; the last bump coincided with a tool-version change. If `build_agent_profile_registry` or the recipe pin registry refuses v71 at boot, the fix is a recipe pin bump in the same branch — a one-file change, not a design change. |

Decisions that are the founder's, not Aryan's, are in §0.9 and 06.

---

## Appendix A — Acceptance tests → items → tests

| AT | Item(s) | Test (tier) |
|---|---|---|
| AT-1 candidate recall ≥ 95 % (both frozen person request shapes) | W3-23 | `tests/arv2/v26/test_extract_recall.py` (replay) |
| AT-2 class minimums fire the gap round | W3-22, W3-21 | `tests/arv2/test_followups.py` (offline); `tests/arv2/test_prestep_db.py` (DB) |
| AT-3 rule table pure function; every floor pair fires | W0, W3-22 | `tests/arv2/v26/test_fixtures.py`, `tests/arv2/test_followups.py` (offline) |
| AT-4 synthesis ≥ 2 distinct sources; not_found cites the ledger | W1-2, W3-24 | `tests/arv2/test_dossier_json.py` (offline); `test_quality_brief_tool_db.py` (DB) |
| AT-5 subject anchor | W3-23 | `tests/arv2/test_quality_extract.py` (offline); namesake injection (replay) |
| AT-6 nothing-lost list | W0, W1-14, W3-24 | `tests/arv2/v26/test_nothing_lost.py` (replay; account tuples committed) |
| AT-7 quote rule (01b §5) | W3-23 | `tests/arv2/test_text.py` (offline); 43-span regression (replay) |
| AT-8 account judge receives the people slice; org-sequence finding emitted | W3-21, W3-24 | `tests/arv2/test_prestep_db.py` (DB); replay |
| AT-9 floor reproduction = 1.0 (gating); chain recall ≥ 0.90 per account (gating); judge-only recall ≥ 0.75 (reported) | W0, W3-22, W3-24 | `tests/arv2/v26/test_followup_recall.py` (replay) |
| Zero error classes | W1-2, W1-3, W1-12, W1-4 | RC-1/RC-2 trace counts (replay) |

## Appendix B — New files

`arv2/candidates.py` (W1-5) · `arv2/quality_extract.py` (W3-23) · `arv2/acquisition_plan.py`,
`arv2/followups.py` (W3-22) · `arv2/committee_rank.py`, `arv2/prestep.py` (W3-21) ·
`arv2/quality_brief_tool.py` (W3-24) · `platform/agents/catalog/research-quality/followups/v1/
rules.json`, `extractors/candidates/v1/SYSTEM.md`, `plans/{account,contact}/v1/*` (W0, W3) ·
`scripts/arv2_v26_freeze_pool.py`, `scripts/arv2_clearing_simulation.py`,
`scripts/arv2_materialize_lazy_sources.py` · `tests/arv2/v26/{replay.py,conftest.py,fixtures/,test_*.py}`,
`tests/arv2/test_privacy_stop_v4_db.py`, `test_pool_read_db.py`, `test_prestep_db.py`,
`test_quality_brief_tool_db.py`, `test_quality_views_grep_db.py`,
`test_quality_acquisition_concurrency_db.py` · the catalog folders of §8.1 · three migrations (§10).
