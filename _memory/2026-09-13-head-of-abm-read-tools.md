# 2026-09-13 — the Head of ABM reads before it speaks (plan 4 of the context + ICP-authoring set)

Branch `research-streaming`, worktree `san-salvador`, lane DB `clue_san-salvador`. Plan
`docs/superpowers/plans/2026-09-12-head-of-abm-read-tools.md`; spec
`docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.4 (ruling R8).
SDD ledger and per-task reports: `.superpowers/sdd/2026-09-12-head-of-abm-read-tools/`
(git-ignored). Base `c1407823f` (plan 3's close-out). Commits `2509eca68`, `e9a4af9b6`,
`0024d8eb3`, `f6e2dc9ca`, `9619577f6`, and this close-out.

(The task-6 brief named this note `2026-09-12-head-of-abm-read-tools.md`; it is dated
**2026-09-13**, the day the close-out actually ran.)

## The problem it solves

The Head of ABM could *do* things to a project — discover accounts, launch research, author an ICP,
write the plan — but it could not **look at what it had done**. Everything it said about an account,
about how many accounts a project holds, or about whether discovery had already run came out of its
own conversation memory: fine inside one thread, wrong in the next one, and wrong again after a
fleet job finished behind its back. Three effect-free reads close that: the agent asks the rows.

Three deliberate properties, the same for all three: **effect-free** (they spend nothing, approve
nothing, launch nothing — `EFFECT_FREE`, `external_boundary=NONE`); **absence is a typed refusal**,
never an empty success (an unresearched account says so by name, so the agent cannot read silence as
"nothing to report"); and **scope is ambient** — the workspace comes from `ctx.workspace_id`, never
from the model, and a project or account or run outside it is *absent*, not refused differently.

## What shipped, per task

**T1 — `2509eca68` — `read_project_accounts@1`** and the module the other two extend,
`platform/api/clue_api/arv2/read_tools.py`. `Arv2ReadRefused(Arv2Error)` with a stable `code`;
`MAX_ACCOUNTS = 200`; `list_project_accounts(conn, *, workspace_id, project_id, limit)` —
`clue_spine.get_project` + an explicit workspace compare first (`project_not_found` covers both an
unknown id and another tenant's project), then the project's `project_account` rows joined to
`account_entity` (`merged_into IS NULL`) with a lateral join onto each account's **latest ARV2
account job** for `research_status` (`not_started` when there is none) and a `refreshing` flag (a
live job that post-dates a completed one — a first run is not a refresh). `Arv2ReadService`
Protocol + `DbArv2ReadService(conn_factory=transaction)` (one transaction per call, no storage, no
settings, so T4 can compose it unconditionally). Tool: `READ`, `pin_requirements=("project",)`,
`limit` 1…200 default 100.

**T2 — `e9a4af9b6` — `read_account_research@1`.** `section="overview"` reads the account's written
overview through `display.blocks.live_blocks` in the **page's own running order**
(`read_recipes(conn, "overview", workspace_id=…)`, so a workspace's section overrides are honoured;
an unrecognised section sorts after the known ones by `section_key`, which is also the whole order
when no recipes are seeded). `section="claims"` reads through
`claims_for_entities(conn, [id], scope=WorkspaceScope.for_workspace(ws))` — never a hand-written
`claim.workspace_id` predicate — with an optional `field_prefix` (≤80 chars), the first
`MAX_CLAIMS = 120` and `truncated`, each evidence span clipped to `EVIDENCE_CHARS = 240`. Refusals:
`account_not_found` (unknown, malformed, another workspace's, or a **merge loser** — ruling M),
`overview_not_written` (whose message points at `section='claims'`), `account_not_researched` (which
names the prefix when one was given). **Ruling O applied here**: `_COUNT_PROJECT_ACCOUNTS` gained the
same `merged_into IS NULL` join, so "showing N of `total`" is two measurements of one population.

**T3 — `0024d8eb3` — `read_discovery_run@1`.** The project's latest run (or a named `run_id`), its
status and window, `asked` / `found` (strict + relaxed counters, a missing counter reading `0`
rather than crashing), the three candidate tallies (`verified` = disposition decided,
`shown` = `SHOWN_DISPOSITIONS`, `approved` = `decision = 'approved'`, **every sub-select
workspace-scoped** because `arv2_discovery_candidate.run_id` is a single-column FK), and the
candidates themselves ordered shown-first then best-fit then name, with an unscored candidate sorting
*after* every scored one rather than as a zero. `candidate_limit` 0…50 default 25 (`0` is a
legitimate ask: the tallies without the company list); `candidate_total` is always the whole run.
The project is checked before the run, so a foreign project refuses `project_not_found` and a
sibling project's run refuses `discovery_run_not_found`; `no_discovery_run` is the honest answer for
a project that never ran discovery. `pass` is a Python keyword, so the field is `pass_` with
`serialization_alias="pass"` and the tool dumps `by_alias=True`.

**T4 — `f6e2dc9ca` — registration, ungranted.** `build_arv2_read_tools(service)` returns the three
in order; re-exported from `arv2/__init__` (142 → 169 names); registered in `toolbelt_wiring` behind
the new `arv2_reads: Arv2ReadService | None` argument **with no flag** (they read rows that already
exist and spend nothing); three `C6_AGENT_TOOL_AUTHORITY` rows granted to **nobody**;
`DbArv2ReadService()` composed unconditionally in `fleet_main._serve` and
`projections_main.build_application`. Registry 129 → **132** names, 147 → **150** addresses. An
uncomposed deployment refuses by name: `arv2_reads_not_composed`. The agent-registry manifest digest
did not move — nothing was granted yet, which is the point of splitting T4 from T5.

**T5 — `9619577f6` — the grant.** `stage0-interview@v25` (= v24 + three tool pins + §7b's new line
+ the whole new **§7c "Read before you speak about accounts"**), `head-of-abm@v48` (= v47 + the
skill pin + the three tool pins), `recipe0-stage0-v26.json` (= v25 + the three addresses at all four
sites);
`CONVERSATION_RECIPE_VERSION = 26`; `PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v48"`; the
three names joined `stage0_recipe._execution_project_pin` (**not** the presenting-turn branch — two
carry a model-authored `project_id` in the body and `read_account_research` names no project at all,
so the execution row is the trusted coordinate). v24 / v47 / v25.json are byte-untouched
(`git diff --stat` over the three paths is empty). All digests measured on this tree. The **trial
surface was deliberately not touched**: reads spend nothing, approve nothing and launch nothing, so
`STAGE0_CONVERSATION_TRIAL_SURFACE.withheld_tools` gains none of them.

**T6 (this note) — close-out.** Frontend labels + test, the stack restart and the v26 promotion
check, this note and its README row, `platform/api/clue_api/arv2/README.md` § "The three reads", and
one addendum line in `docs/specs/ARV2-ONBOARDING-PLAN.md` §8.

## Verification run

- T5's gate, run twice with identical results: `uv run pytest tests/arv2
  tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py
  tests/api/test_toolbelt_wiring.py tests/agents tests/api/test_c8_trial_surface.py
  tests/api/test_client_knowledge_privacy_s4e.py tests/api/test_comprehensive_research_contract.py
  --ignore-glob='*_live.py' -p no:cacheprovider -q` → **1380 collected, 4 failed**, the four being
  exactly the lane's known pre-existing reds (below).
- Per-task suites green: T1–T3 `tests/arv2/test_read_tools_db.py` + `tests/api/test_arv2_read_tools.py`
  + `tests/arv2/test_import_guard.py` → **36 passed** on the real lane DB (nothing skipped, so the DB
  tests really ran); T4 added the builder test and the three `_MATRIX` / authority-count flips.
- `uv run lint-imports` → **26 kept / 0 broken**; `tests/arv2/test_import_guard.py` → 4 passed;
  ruff format + check and mypy clean on every touched module.
- **Red-proofs (T1, mutation + revert):** dropping `subject_type = 'account'` from the lateral join
  makes a *person* job report as the account's status; dropping `AND j3.created_at < j2.created_at`
  from the `refreshing` EXISTS makes an abandoned earlier run plus a later completed one read as
  "refreshing". Both fail the DB tests.
- Frontend (T6): `npx tsx --test src/features/projects/model/chat-tool-presentation.test.ts` →
  **10 pass**; `npm run lint` → **0 errors** (the 2 pre-existing `canvasOperations.ts` warnings).
- **Known pre-existing reds, not this work** (unchanged from plan 3's note): the design profile's
  model assertion (`openai/x-ai/grok-4.6` from `.env` vs `openai/gpt-5.6-terra`);
  `tests/arv2/test_discovery_driver.py::…not_composed_without_the_flag…`;
  `tests/arv2/test_answer_key_loader_db.py` ×2 (leftover `arv2_research_job` rows on the lane DB).
  `tests/execution/test_recipes.py` stays red on this lane for its two unrelated reasons (the
  replay-only version gap and a stale `recipe0-stage0@2` row) — which is why promotion is verified
  against the live registry.
- No `make check`, no broad pytest with real keys (standing rule: live tests spend money).

## Stack restart and recipe promotion (2026-09-13, close-out)

```
$ ./scripts/dev_stack_san_salvador.sh restart-api    > /tmp/san-salvador_restart.log 2>&1
$ ./scripts/dev_stack_san_salvador.sh restart-workers >> …
$ ./scripts/dev_stack_san_salvador.sh status          >> …
  frontend (3020): UP     design-api (8010): UP
  platform-api (8020): UP     platform-api-2 (8030): UP
  fleet-worker: UP (4 process(es), 3 slot(s) each)
```

Output redirected and read with `tail`, never piped. Semarang's process on **8070 is still alive**;
no other workspace's processes were touched. Both API logs and all four worker logs carry **zero**
`"level": "error"` / `Traceback` lines after the boot (`worker.start` + three `worker.slot_start`
each, no field-registry seed race — the stagger held).

**Recipe v26 is promoted on the lane DB**, seeded by the workers at this boot (19:25:34Z = the
restart above, local 00:55):

```sql
SELECT r.recipe_key, rv.version,
       (SELECT e.event_type FROM recipe_revision_event e
         WHERE e.recipe_revision_id = rv.id ORDER BY e.seq DESC LIMIT 1) AS latest_event,
       rv.created_at
  FROM recipe_revision rv JOIN recipe r ON r.id = rv.recipe_id
 WHERE r.recipe_key = 'recipe0-stage0' ORDER BY rv.version DESC LIMIT 4;

 recipe0-stage0 | 26 | promoted   | 2026-09-12 19:25:34.691127+00
 recipe0-stage0 | 25 | superseded | 2026-09-12 15:30:20.95027+00
 recipe0-stage0 | 24 | superseded | 2026-09-12 14:23:49.080414+00
 recipe0-stage0 | 23 | superseded | 2026-09-11 05:45:25.00541+00
```

(`recipe_revision` has no `recipe_key`/`status` column — promotion state lives in
`recipe_revision_event`, migration `128c83d5e151`. This is the working form.)

So `head-of-abm@v48` / `stage0-interview@v25` / recipe v26 are live on this lane.

## Rulings taken during execution (ledger)

- **M** — `read_account_research` **follows no lineage**. A merge loser is `account_not_found`, not
  a silent redirect to its survivor: the agent asked about an id this workspace no longer serves,
  and answering about a different row would be a quiet substitution. The rule this leaves behind:
  *any* lineage a read tool ever learns to follow must **re-check `workspace_id` on the row it lands
  on** — `merged_into` is not itself a tenancy guarantee.
- **N** — `stage0-interview@v25`'s front-matter `summary` had to be **rewritten**, not appended to:
  v24 sat at 505 of its 512-character cap. The replacement measures 416. One deviation forced by
  YAML and flagged in T5's report: the new text contains `": "`, which a plain YAML scalar cannot
  carry, so the scalar is **double-quoted** — the loaded value is byte-identical to the ruling.
- **O** — `list_project_accounts`'s `total` must count the rows the listing **can show**: the count
  SQL carries the same `JOIN account_entity … merged_into IS NULL` as the page. "Showing N of
  `total`" has to be two measurements of one population, or the remainder is unreachable.

Carried in from the earlier plans and still load-bearing: T1–T3 all use `get_project` + an explicit
workspace compare (consistency with the ARV2 launches), and registration-before-grant (plan 3's
ruling J) is why T4 and T5 are separate commits.

## OWED — the live walk (founder-triggered; not run by the implementing agent)

API twins and workers were restarted on this code and recipe v26 is promoted, so v48 / v25 / v26 are
live. On the founder's project (ICP confirmed and pinned, accounts discovered and at least one
account researched), in a **new thread** — new because the whole point is that the agent has no
memory of the earlier one:

- [ ] Ask **"what did we find about Goodman Campbell?"** → `read_account_research` appears in the
      transcript as **"Review an account's research"**, and the answer **cites the written
      overview** (or, if the overview is not written, refuses by name with `overview_not_written`
      and offers the claims — an invented summary is a defect).
- [ ] Ask **"how many accounts do we have and how many are researched?"** → `read_project_accounts`
      appears as **"Review the project's accounts"**, and the counts it states match the rows (see
      the SQL below). A number stated without the tool call in the transcript is a defect.
- [ ] Ask **"should we discover more?"** → `read_discovery_run` appears as **"Review the discovery
      run"** *before* any launch, and the agent answers from the run's tallies (asked / found /
      verified / shown / approved) rather than from the thread.
- [ ] The three calls are in the journal. `execution_node` is the authoritative record of what the
      agent actually called (`kind = 'tool'`, bare names):

```sql
SELECT n.tool_name, count(*) AS calls, max(n.created_at) AS latest
  FROM execution_node n
 WHERE n.kind = 'tool'
   AND n.tool_name IN ('read_project_accounts', 'read_account_research', 'read_discovery_run')
 GROUP BY n.tool_name ORDER BY 1;
```

      The toolbelt's A9 idempotency ledger is the cross-check (`tool_invocation`, migration
      `49911e6aac37`; names there carry the version suffix and only keyed invocations land):

```sql
SELECT tool_name, count(*) FROM tool_invocation
 WHERE tool_name LIKE 'read\_%' GROUP BY tool_name ORDER BY 1;
```

- [ ] Reconcile the counts the agent stated against the rows:

```sql
SELECT count(*) AS accounts,
       count(*) FILTER (WHERE j.status = 'completed') AS researched
  FROM project_account pa
  JOIN account_entity a ON a.id = pa.account_entity_id AND a.merged_into IS NULL
  LEFT JOIN LATERAL (
    SELECT status FROM arv2_research_job j
     WHERE j.workspace_id = pa.workspace_id AND j.account_entity_id = a.id
       AND j.subject_type = 'account'
     ORDER BY j.created_at DESC, j.job_id DESC LIMIT 1
  ) j ON TRUE
 WHERE pa.workspace_id = '{workspace_id}' AND pa.project_id = '{project_id}';
```

- [ ] Record the transcript summary, the SQL output and **any refusal** back into this note. A
      refusal is not automatically a defect — `overview_not_written` / `account_not_researched` /
      `no_discovery_run` are the honest answers — but a refusal the agent **paraphrases into a
      confident claim**, a count that does not match the rows, or a fact stated with no read in the
      journal **is** a defect to fix, not to accept.
- [ ] Plans 1, 2 and 3's live proofs are still owed (`agent_turn_project_files`;
      `author_icp_document` + `request_persona_synthesis`; `write_project_document` + the human PUT).
      **The same walk can prove all four** — the plan and the reads sit in the same thread.

## Follow-ups carried out of the plan

- **Section ordering degrades silently.** `read_account_research`'s overview order comes from
  `display_section_recipe`; on a deployment where the recipes were never seeded, every block falls
  into the `section_key` fallback sort. That is the designed fallback, documented at the sort, but
  it is a degradation rather than a refusal.
- **`section` is `str` at the service seam**, so any value other than `"overview"` reads claims. The
  `Literal` on the tool input is what constrains the model; a future non-tool caller could pass
  anything and get claims.
- **Claim ordering is inherited, not re-asserted.** `claims_for_entities` orders by
  `(field_key, collected_at DESC, id)`, which is what makes "one field's newest value first" true.
  If that `ORDER BY` ever changes, this read's grouping changes with it; the DB test would catch a
  gross change but not a within-field one.
- `ReadProjectAccountsOutput.accounts` is `tuple[dict[str, Any], ...]`, so the typed
  `ProjectAccountView` schema is not visible in the tool's output JSON schema — the model sees
  untyped objects. Deliberate (it is the plan's shape), worth revisiting if the model mis-reads a
  field.
- `DbArv2ReadService()` is composed at the two process roots only. Any other `build_toolbelt` call
  site leaves `arv2_reads=None` and the three refuse `arv2_reads_not_composed` there — pinned by the
  `_MATRIX` entries, but it means a new root must remember to compose it.
- **T5's fixture-id deviation, flagged:** the brief asked for a Stage-0 quality fixture named
  `read_before_speaking`, but that id was already taken by §1's "read the files" fixture; the two new
  ids are `read_accounts_before_speaking` and `read_discovery_before_relaunching`.
- **The skill summary is now at 416 of 512** after ruling N's rewrite — room again, but the next
  grant should measure before it appends.
- The lane DB still carries committed rows from earlier walks behind several pre-existing reds; a
  reset clears them.

## Final-review fix wave — 2026-09-13 (`head-of-abm@v49` / `stage0-interview@v26`)

The review (`.superpowers/sdd/2026-09-12-head-of-abm-read-tools/final-review.md`, 0 Critical /
4 Important / 9 Minor / 4 Nit) was adjudicated in the ledger (rulings Q and R) and applied as one
wave. Report: `.superpowers/sdd/2026-09-12-head-of-abm-read-tools/fix-report.md`.

- **I1 / ruling Q** — `_account_claims` now mirrors `display/gather.py`'s gate exactly: SENSITIVE
  use-class dropped, tier-4 not-VERIFIED dropped under `settings.verification_enabled`,
  `outreach_safe=false` dropped. Counted in `excluded: {sensitive, unverified, outreach_unsafe}`;
  each claim carries `verification_status` + `outreach_safe`. `DbArv2ReadService(settings=…)` is
  the new constructor arg (composed from `settings` at `fleet_main`, `resolved` at
  `projections_main`). The description no longer says "verified".
- **I2 / ruling R** — `discovery_store.VERIFIED_PREDICATE = "jsonb_array_length(c.verdicts_json) > 0"`
  is the ONE definition, consumed by `read_tools._DISCOVERY_COUNTS`,
  `project_status._LATEST_DISCOVERY` and `frontend_read/discovery_status._LATEST_RUN`. "Not pending"
  counted the pre-spend dispositions, which are stamped before any gate is asked.
- **I3** — `read_project_accounts` gained `query` (ILIKE, metacharacters escaped) and `offset`;
  `total` counts the filtered set.
- **I4** — candidates filtered to the caller's workspace before sorting; `candidate_total` follows.
- **M1** — the `refreshing` tie-break is `v1_shared._ARV2_RESEARCH_STATUS`'s tuple compare, and the
  row order is the accounts screen's `created_at DESC, id DESC`. **Test-seeding note:**
  `account_entity.created_at` defaults to `now()` (TRANSACTION time), so accounts seeded in one
  `rollback_conn` share a timestamp and the order falls through to a random uuid — `_seed_account`
  in `tests/arv2/test_read_tools_db.py` now stamps an ascending `created_at`.
- **M2/M3/M4/M5** — `truncated` proven at 121 claims; clipped evidence ends `…` and carries
  `evidence_truncated`; overview `body` → `body_text` (JSON, 6000-char cap) + `body_truncated`;
  a prefix that matches nothing on a researched account refuses `no_claims_under_prefix`.
- **M8** — the trial surface **withholds** the three reads (it composes no read service).
- **M9** — the outputs carry typed rows; this moved all three output digests and
  `read_project_accounts`' INPUT digest, so `skills/stage0-interview/v26` and
  `profiles/head-of-abm/v49` were minted and `C6_ACTIVE_PROFILE_VERSIONS` /
  `PROJECT_CONVERSATION_AGENT_PROFILE_ID` flipped. **The recipe stays v26** — verified by reading
  the JSON: `recipe0-stage0-v26.json` carries zero `sha256` keys, it pins addresses only, and no
  address moved.
- **PARKED** (ledger): M6 (candidate jsonb decode at `candidate_limit=0`), M7 (no project-membership
  check on the account read), and the four nits.
- **Deviation from the brief, recorded:** the brief said skill v26 would be v25 "with only the three
  output digests updated"; `read_project_accounts`' *input* digest also moved (I3 added `query` and
  `offset`), so four digests changed. The skill's §7b/§7c prose is byte-identical to v25 — the
  `query`/`offset` teaching lives in the tool's own `model_description`, which is where the model
  reads it.

## Final review + fix wave (2026-09-13)

Opus whole-plan review: 0 Critical / 4 Important / 9 Minor / 4 Nit. Fix wave `abdc1a063`: the claims
read mirrors the display gate (sensitive, unverified tier-4 when verification is on, and
outreach-unsafe claims are held back and counted in `excluded`; each claim carries
`verification_status` and `outreach_safe`; the description no longer says "verified"); `verified`
means "has a verdict" — `discovery_store.VERIFIED_PREDICATE`, shared by `read_discovery_run`,
`status.md` and the Target accounts tab's read, so all three agree; `read_project_accounts` gains
`query` (name/domain) and `offset`; served candidates are filtered to the caller's workspace;
evidence clipping is marked; overview bodies are capped at 6000 chars; `no_claims_under_prefix`;
the trial surface withholds the reads; outputs use typed rows, which moved the schema digests →
skill `stage0-interview@v26` and profile `head-of-abm@v49` (recipe stays v26: it pins addresses
only). Parked: M6 (candidate deserialization at limit 0), M7 (the account read has no project
input; `ctx` carries no project), nits. Live walk owed (see the checklist above); the stack was
restarted on v49 afterwards. Note for tests: `account_entity.created_at` defaults to transaction
time, so rows seeded in one transaction tie — `_seed_account` stamps ascending timestamps.
