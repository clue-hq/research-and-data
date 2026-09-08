# ARV2 D4-b — ARV2-native reads, the FI-2 surface deleted, the Phase-6 inventory

Date: 2026-09-09. Branch `track-d4b`, worktree `managua`, stacked on `track-d4` @ `abba1fa5c`
(D4 PR #50 merged into the branch's base). Plan:
`docs/superpowers/plans/2026-09-09-arv2-d4b-arv2-native-reads-and-fi2-deletion.md`. SDD ledger:
`.superpowers/sdd/2026-09-09-arv2-d4b-arv2-native-reads-and-fi2-deletion/progress.md` with seven
task briefs and reports beside it. Spec: `ARV2-MASTER-PLAN.md` §2/§6/§9, `ARV2-DATA-SOURCE-MAP.md`
§1/§2.1/§3. Operating rule: implementers were Opus subagents; **every review was the controller's
own, first-hand**; never `git stash`; never `git checkout HEAD --` on an edited file.

D4 gave the backend its screens but left them reading the old research lane through the FI-2
payloads. **D4-b made every read ARV2-native and deleted the old surface.**

## The founder ruling this branch exists to serve (2026-09-09)

> **ARV2's own rows are the only truth. Nothing about the old research lane matters; it is deleted,
> never bridged.**

No fallback, no compatibility shim, no "until the ARV2 writer lands". If ARV2 has no row for
something, the honest answer is the empty one. Written into `ARV2-MASTER-PLAN.md` §2 as principle 0.

## Tasks → commits

| Task | What | Commit(s) |
|---|---|---|
| 1 | Research status from `arv2_research_job` | `ef273a666` (+ controller hygiene `959aec758`) |
| 2 | The committee = contacts with live claims, persona-ranked | `f06c5a3f6` |
| 3 | Persona as display text; revenue/funding labels from the registry objects | `14fd701f3` + fix `6e58459ad` |
| 4 | `core.work_email` carries the provider verdict | `18b092422` |
| 5 | Delete the FI-2 read surface and the `?contract` parameter | `f96f99530` + `c424b7827` + `182080915` |
| 6 | The D1 answer-key loader writes ARV2 rows only | `ceb82f841` |
| 7 | Phase-6 inventory, records, close-out | this commit |

## What each task actually built

**T1 — status.** `v1_shared.arv2_research_status_for(conn, workspace_id=, account_ids=)` → one
statement over `arv2_research_job`: `DISTINCT ON (account_entity_id) ORDER BY account_entity_id,
created_at DESC, job_id DESC`, workspace-scoped. `status` served **verbatim** (R2's `JobStatus` and
the wire's `ResearchStatus` are the same five strings — a pure test pins the vocabularies equal, so
no mapping exists to drift). `refreshing` = a non-terminal job (`not_started`/`in_progress`; a
`suspended` job is halted, not running) newer than a `completed` one on the same total order. An
account with no job is absent from the dict; callers spell `("not_started", False)`. Status is now
**per account, not per project** — the primary-project attribution and its `NOT_STARTED` fallback
are gone; the fit stays primary-project-scoped because a score is project-relative.
`_read_v1_research` / `_RESEARCH_JOBS_V1` deleted. New shared seeder
`tests/arv2/account_research_job_helpers.py::seed_arv2_job` drives `create_run` → `create_job` →
`begin_job` → `finish_job` through `account_research_store`, so every seeded row satisfies the same
CHECKs a driver's does.

**T2 — the committee.** `arv2/display/gather.committee_members` is one rule: contacts under the
account, same workspace, `merged_into IS NULL`, `EXISTS` a live claim under
`WorkspaceScope.for_workspace(ws).predicate()` (never `claim.workspace_id` alone), ordered
`(persona_rank(persona), name, id)`. `_COVERAGE_SQL` / `_MEMBERS_BY_ID_SQL` /
`_MEMBERS_WITH_CLAIMS_SQL` are gone — **no coverage-row branch survives**. The ordering moved into
`committee_members` so D2 and D3 share one order (the `id` tiebreak is new: two namesakes come back
the same way every read). New `arv2/display/personas.py` holds `PERSONA_RANK` / `PERSONA_LABELS` /
`persona_rank` / `persona_label` / `persona_display` — it lives in the display package because
`clue_api.arv2` may not import `clue_api.frontend_read`; `v1_shared` re-exports all four.
`_why_they_matter(claim, title=, persona=)` serves a researched rationale verbatim; a role claim
written by the derived path counts as having none (recognised by the `derived_role_from_persona`
write marker **or** the phrase `"role derived from the committee persona"`), and then the text is
`"{title} · {persona label}"`, else `"Committee member"`.

**T3 — labels.** `persona_display` at every wire site and only wire sites (E4 row, E5 head,
`reports[]`, E2 committee card, E2 rail chips, and the generated block `contactRefs[]`/`subject`);
internal uses keep the vocabulary value. `format_money` / `revenue_label` / `funding_label` /
`revenue_band_label` read the registry **objects** instead of `render_value_text`.
`scripts/rewrite_display_persona_labels.py` corrected the blocks already at rest.

**T4 — the email verdict.** `core.work_email` is registered an **object**
(`{address, status, checked_at?}`; `status` in
`verified_smtp | catch_all_valid | invalid | unknown | unverified`), with the reversible data-fix
migration `7332ac974920` (which updates `value_type`, `value_schema` **and** `description` — the
registry compares the whole definition). `answer_key.work_email_value(address, verification)` is the
one grader; an unrecognised provider verdict becomes `unknown`, never stored raw. `email_facts`
reads `checked_at` for `emailVerifiedAt`, falling back to `observed_at/collected_at`; a legacy bare
string short-circuits to `lookup` with the claim id kept.

**T5 — the deletion.** `/frontend/v1` serves one contract. Deleted outright: `prose.py` (115),
`account_activity.py` (314, the E6 route), `evidence.py` (215, its three E7 functions moved to the
new `evidence_stream.py`), `tests/integration/test_fi2_slice1_read_layer.py` (1,496),
`tests/api/test_frontend_read_account_activity.py` (535). Re-shaped: `committee.py` →
`project_run_context.py` (185 → 43; only `latest_project_run_context` survives, for
`agent_turn_fleet_wiring`), `accounts_list.py` (1,071 → 743), `account_detail.py` (1,098 → 496),
`contacts.py` (1,374 → 875), `bulk_actions.py` (773 → 512), `app.py` (`ContractMode` /
`contract_mode` / `ContractDep` gone). The v1 readers took the plain names. **39 files, −7,087 /
+891.** Frontend: nine `contract: "v1"` sites removed across five repositories and their tests.

**T6 — the loader.** `answer_key_loader._research_rows` no longer writes `entity_research_run` /
`_account_fleet` / `_job` / `_account_coverage`. It creates one `arv2_research_run` + one
`arv2_research_job` for Zafran through `account_research_store`, with a real pin (brand, project
run, `arv2-account/v1` profile ref + sha, `effort="full"`, `committee_cap=5`,
`product_selection_version=1`, a `request_sha256` over the whole manifest) and a fixed-bytes
stand-in ICP artifact. The other three accounts get **no** job — honestly `not_started`.

## Every ledger ruling and attribution (carried here in substance)

**Pre-flight (before Task 1).**
- T1 reads `arv2_research_job`; until T6 wrote one, the Zafran walk would show `not_started`. Ruled:
  relax T1's walk assertion to "a valid enum value", T6 restores `completed`. Both happened.
- T1's wire enum and R2's `_STATUSES` verified identical; pinned with a test rather than trusted.
- T5 must grep for importers of the governed committee reader and re-point or delete the contact
  bulk path (the frontend had already dropped it).
- The persona rewrite over stored blocks is a **one-shot script, idempotent, no model call** — a
  block is its own row, nothing cites it, so this is a display-copy correction, not a supersession
  that would mint a generation no model produced.
- Frontend Zafran fixtures keep raw personas: the frontend renders whatever is served; fixtures are
  fixture data. Only the contract doc's rule column changes.
- The registry change needs one Alembic **data-fix** migration (D1 precedent) or the pack reload
  raises `FieldRedefinitionError`.
- The email repair supersedes the four bare rows with the same provenance — claims are append-only.
- E6 is deleted **with** the FI-2 surface (the frontend reads `activity[]` off E2/E3).
- The loader must write run/job **through** `account_research_store`, reusing the R2 acceptance
  seed's stand-in for the ICP pin.
- Rubric finding: persona rank was duplicated in D2 gather and `display_pages.committee` → T2 moved
  the ordering into `committee_members`.

**Task rulings.**
- **T1 accepted deviation:** no join to `arv2_research_run`. The job row carries its own
  `workspace_id` and the composite FK pins `(account_entity_id, workspace_id)`; the run's
  `project_id` is deliberately not consulted (whichever project launched it, the account is
  researched).
- **T1 incident, recorded:** the implementer self-reported a careless
  `git checkout HEAD -- platform/api/clue_api/frontend_read tests/api` mid-task. All work was redone
  from scratch; the final tree was verified complete and green by the controller. The diff was
  rebuilt rather than continuously grown.
- **T2 ruling:** the two contacts tests that asserted a coverage-row exclusion were **rewritten to
  the new rule** (3 → 4 rows). Correct under the ARV2-only ruling — the brief's claim that the
  contacts v1 half already relied on contacts-with-claims was wrong, and the implementer said so.
- **T2 accepted:** the `"{title} · {persona}"` placeholder rule also covers a member with no role
  claim at all (so a member with a title reads `"Head of RevOps · Champion"`, not
  `"Committee member"`).
- **T3 fix round (controller rulings on the implementer's concerns):** (1) a funding round with no
  currency **borrows the sibling total's** (same account, same provider record) → Zafran reads
  `"Series C · $60M · $130.5M"`; a bare amount stays bare when neither half names a currency, since
  defaulting to `$` would turn an undenominated figure into a dollar figure on a card a marketer
  quotes. (2) E1's `revenueBand` enum strings are served as labels via `revenue_band_label`, which
  covers all seven `REVENUE_BAND_OPTIONS` members (a test refuses any member served as its own
  token); an unparseable value is served **as written**, never invented.
- **T4 accepted deviation:** `checked_at` is **omitted**, not written null, when the provider sent
  none — the registry validator has no union types (`{"type": ["string","null"]}` crashes
  `_validate_payload`), so the property is a plain optional and readers `.get` it.
- **T5 ruling, accepted:** the chat composer's contact context card is now a minimal typed summary
  from D2's committee rule instead of the serialised FI-2 profile. The FI-2 readers returned nobody
  on ARV2 rows, so the old path was already dead — this is a repair, and it also stops inlining an
  unbounded copy of one person's personal data into every turn that mentions them.
- **T5 decisions beyond the brief:** `safe_public_url` moved to a new dependency-free
  `clue_api/url_safety.py` (C7 re-exports it) because the read surface may no longer import a
  `research_view` module; and `contact_email_lookup`'s two `display_allowed` calls became
  `arv2_display_allowed` — C7's predicate demands a STRONG `identity_binding` the ARV2 lenient
  writer does not stamp, so it was hiding exactly the addresses the screens render.
- **T6 accepted deviations:** `requested_by_user_id` is free text (`"arv2-answer-key-loader"`) —
  checked in psql, no FK to `platform_user`, and `ANSWER_KEY_USER_ID` does not exist on a pre-D4-b
  database; a fixed-bytes **stand-in ICP artifact** rather than the confirmed `icp-definition`
  document (the worktree DB was loaded before the knowledge-document and product-set steps existed);
  and **no `run_lineage` row** for the ARV2 run — it carries no claims of its own.

## Repairs run on the worktree DB (`postgresql://clue:clue@localhost:55060/clue`)

| Repair | Result |
|---|---|
| `scripts/rewrite_display_persona_labels.py` | 37 blocks scanned, **7 rewritten, 26 personas**; second pass 0/0 |
| `scripts/load_arv2_answer_key.py --repair-emails` | `found 4, repaired 4`; second pass `found 0` |
| `scripts/load_arv2_answer_key.py --repair-research-rows` | `runs_created 1, jobs_created 1`, status `completed`, `claims_written 172`; second pass `0/0` |

All three are idempotent on live data, not only in a test.

## Deletion numbers

Task 5: **39 files, −7,087 / +891.** Whole branch (`84c442529..ceb82f841`): 64 files, +4,140 /
−7,774.

## The guard test

`tests/api/test_frontend_read_arv2_only_guard.py` — three tests. It greps
`platform/api/clue_api/{arv2,frontend_read}` for `entity_research_`, `account_run\b`,
`research_view`, `read_governed_committee`, `ContactEligibilityResolver` and
`(?<![\w.])display_allowed\b`, skipping comment/docstring lines; it has a "would actually fire"
test so a broken scanner cannot pass vacuously; and it asserts `contract_mode` / `ContractDep` /
`ContractMode` no longer exist on `frontend_read.app`. **The file allowlist is empty since Task 6.**
The one substring allowance is `entity_research_job_id` — a real **ARV2** column on
`provider_call_ledger` holding an `arv2_research_job.job_id` under an inherited name. Do not rename
it as part of any legacy sweep.

## The Phase-6 inventory (Task 7's first deliverable — a document, nothing deleted)

`docs/specs/ARV2-PHASE6-LEGACY-DELETION-INVENTORY.md`, built from evidence (`\dt`, the raw
`CREATE TABLE` statements in `alembic/versions/*.py`, per-table and per-module greps), not memory:
327 tables total; **36** touched by the ARV2 path; **83** Tier-A old-lane tables with row counts,
creating migration and reader/writer counts; ~70 Tier-B substrate tables that need an owner ruling
rather than a default drop; the modules (**40 files / 29,778 LOC** named for the lane, plus ~8,500
LOC behind the M8D R1 quarantine) with their importers, the flags that gate them and the four
bindings into live entrypoints; **19,419 LOC** of legacy-only tests; and an eight-step
stub-then-delete order with the blast radius and gate per step. Plus an explicit survive list.

Two findings worth carrying: `account_run` is the highest-blast-radius Tier-A table (**51**
production files), and `account_research_turn_wiring.py` is **not** an ARV2 module with a legacy
tail — it is a legacy module (it reads and asserts against the old lane's `account_run` row
throughout) with one ARV2 call, so Phase 6 must decide the production turn's run row rather than
mechanically deleting the file.

## Close-out gate — as run

Per-directory pytest, each to its own log, with
`set -a; source .env; set +a; unset CLUE_OPENROUTER_API_KEY OPENROUTER_API_KEY CLUE_AI_ARK_API_KEY
CLUE_GEMINI_API_KEY; export CLUE_EXA_API_KEY=dummy-for-collection` (four modules raise at import on
an empty Exa key; the real keys are unset because
`tests/api/test_onboarding_synthesis_wiring_db.py` drives a real synthesis turn and hangs — it is
`--ignore`d as well).

| directory | on the loaded worktree DB | attribution |
|---|---|---|
| `tests/api` | 1,784 passed / **35 failed** | all 35 fail identically at the base commit |
| `tests/arv2` | 589 passed / 2 skipped / **0 failed** | — |
| `tests/claimstore` | 135 passed / **2 failed** | 1 also fails at base on a clean DB; the other (`test_batch_scales_to_1k_entities`, `assert 1005 == 1000`) is the loaded DB's own `account.recent_funding` rows |
| `tests/db` | 31 passed / **3 failed** | all 3 fail identically at base; the cause is a legacy `entity_research_account_coverage` row violating its own CHECK on downgrade |
| `tests/integration` | 47 passed / **10 failed** | all 10 fail identically at base |
| `tests/agents` | 211 passed / **0 failed** | — |

**Attribution method — a clean-DB A/B, and it is the reliable one.** A worktree at the base commit
(`84c442529`) cannot open the loaded worktree database at all (`Can't locate revision
'7332ac974920'`), so the only honest comparison is two throwaway databases migrated to each side's
own head. Both sides then ran the identical command:

| directory | BASE failures | HEAD failures | diff |
|---|---|---|---|
| `tests/api` | 36 | 35 | **−1**, and it is a deletion: `test_frontend_bulk_actions.py::test_contact_batch_reuses_the_governed_email_service_and_replays_without_spend`, gone with its route |
| `tests/claimstore` | 1 | 1 | none |
| `tests/db` | 3 | 3 | none |
| `tests/integration` | 20 | 10 | **−10**, all of them the deleted `test_fi2_slice1_read_layer.py` (red at base too) |

**Zero failures appear only at HEAD, in any directory.** No D4-b-caused failure exists. `ruff check` 9 findings and `ruff format --check` 9 files, all in files D4-b never touched;
`mypy` 1 error (`ad_assets.py:149`, the documented baseline) over 791 files; `lint-imports` 26/0;
`alembic heads` = one head `7332ac974920`; `make db-smoke` on a clean throwaway DB; the frontend
gates; and the Zafran walk green with `Researched` from ARV2 rows, Nick's email `available`, persona
`"Economic buyer"` and `revenueLabel "$10M–25M"`.

**Method note for the next close-out:** attributing "is this failure ours?" against the *loaded*
worktree DB is unreliable — the answer key's own rows make `tests/db` downgrade tests and two
`tests/claimstore` merge tests fail, and a base-commit worktree cannot even open a database migrated
to D4-b's head. The reliable form is the **A/B on two clean throwaway databases** used above:
`createdb` two, `alembic upgrade head` each from its own worktree, run the identical command on both
sides, diff the FAILED lists, drop the databases. It took ~15 minutes and answered the question
exactly.

## Follow-ups (nothing here blocks D5)

1. **The Phase-6 PR**, from the inventory. Stub at `toolbelt_wiring` first, delete trees second,
   drop tables last in one reversible migration.
2. **R3 owes two things** the read surface now assumes: the person mapper writes the
   `core.work_email` **object** (calling `answer_key.work_email_value`, not re-deriving the
   grading), and the committee agent writes **its own** committee rows — it replaces
   `committee_members`' rule in that one function and may not resurrect
   `entity_research_account_coverage`.
3. `AccountContactDetailV1.linkedinUrl` should become **nullable** so the contact detail's
   site-root fallback can go away.
4. **`POST /frontend/v1/accounts` does not exist** — the frontend's create is a local
   non-optimistic draft.
5. **The CSS re-sync job** (master plan §9, unowned): bring every feature's CSS and the shared
   `Button` across from the design build, then delete `legacy-compat.css` and its extractor.
6. The hard-coded **`Aakash Shrivastava`** placeholder in
   `apps/frontend/src/components/shell/app-sidebar.tsx:119` — the shell prints it on every accounts
   page while the accounts feature resolves the profile correctly.
7. **Pre-existing reds, attributed, not ours:** `tests/api/test_frontend_bulk_actions.py` ×2
   (401/capability-shape, reproduce at `18b092422`);
   `tests/api/test_lane_d4_option_b_acceptance_db.py` ×2 (old-lane discovery-seal validation,
   `AccountResearchFleetLaunchError: … outside the exact sealed discovery membership`, reproduce at
   the merged base in a scratch worktree); `tests/db/test_db_migrations.py` downgrade tests fail on
   a **loaded** database (the D1-documented data-state class) and pass on a clean one;
   `tests/api/test_onboarding_synthesis_wiring_db.py` hangs with a real key (a real model turn).
8. Cosmetic, left alone: the loader DB test's `_skip_if_already_loaded` docstring still explains the
   skip via "the M8D coverage/finalization rows are append-only" — stale reason, correct skip.

## Tier-B rulings recorded (2026-09-09, after the D4-b close-out)

The founder ruled on every Tier-B family of `docs/specs/ARV2-PHASE6-LEGACY-DELETION-INVENTORY.md`
§1.2 (table pasted back as a screenshot, `.context/attachments/xagCCh/image.png`): drop verification/
eval, coverage, economics, discovery (17), official-site crawler, external research/enrichment/
channels (minus `contact_channel_suppression`), and the Stage-0 singletons; keep compliance and the
claim-store rings. The two requested checks were run: `tool_invocation` is the toolbelt's A9
idempotency ledger (`clue_toolbelt/idempotency.py`, migration `49911e6aac37`) → keep;
`review_session`/`review_action` are the M13.1 review surface (`c48ebe0a1e62`), wired at
`clue_api/__init__` + `fleet_wiring` → keep unowned, but its `account_handoff` join and
`conflict_flag` annotation must be unwound in Phase 6. Six more tables were misfiled as old-lane
singletons and are platform substrate: `ingestion_job/segment` (brand-kit ingestion),
`supervisor_diagnosis/observation` (execution supervisor), `account_entity_embedding` (identity
resolution). Net: 72 Tier-B drop + 83 Tier-A = 155 tables in ONE reversible migration; §3 step 7 is
folded into step 6; the couplings table in §1.2 lists the Tier-C readers (`claimstore/merge.py`,
`compliance/dsar.py`, `review/*`, `narrative/support.py`, `observability_wiring.py`) the plan
must edit before the drop. Next: write the Phase-6 deletion plan from the inventory.

## Rebase onto the moved base + the post-rebase gate (2026-09-09, before the PR)

`integration/design-improvement` had gained 60 commits (R2 close-out, O3/O4, the Alembic join
`0622104be021`) since D4 merged. Rebased the 13 D4-b commits onto it (`track-d4b-pre-rebase` keeps
the old tip). Two conflicts: the loader's import list (both `WORK_EMAIL_KEY` and the base's new
`ZAFRAN_ANSWER_KEY` are needed) and one appended line each in `_memory/README.md`. Two Alembic heads
after the rebase → empty join `63294c3ce019` (`7332ac974920` + `0622104be021`); one head.

Gate on the rebased tree: db-smoke up→down→up on a clean throwaway (`clue_d4b_gate`, 442 steps,
exit 0); frontend `design-system:build` + `lint` + `build` exit 0; `lint-imports` 26/0; mypy 2
errors, both base-only files (`ad_assets.py:149` baseline, `arv2/account_research_claims.py:962`
from the R2 close-out); ruff 9/9 all base-only files; Zafran walk 2 passed on the loaded DB (now at
`63294c3ce019`). Per-directory pytest on the clean throwaway (`--timeout=120`, live + the
real-model synthesis test excluded, real keys unset): arv2 699/0, claimstore 136/1, db 38/0
(the loaded-DB downgrade reds do not exist on a clean DB), agents 211/0, integration 47/10, api
1,796/36. **Clean-DB A/B against the base tip** (`/tmp/d4b-base-wt` @ `59b69292f`, DB
`clue_d4b_base`): api 36 vs 36 — 35 identical, base-only = the deleted bulk-email test, HEAD-only
(once) = `test_lane_d2_turn_submission_db.py::test_detached_research_work_does_not_block_a_new_chat_turn`,
a `MultipleResultsFound` inside `clue_fleet/queue.py::claim_next_task` over committed leftovers
from the r9/pilot legacy tests; passes alone and as a whole file ×3 on the same DB → order-dependent
flake in untouched code, recorded as a fleet-owner follow-up (claim SQL shape). integration+claimstore
21 vs 11: the 10 gone are `test_fi2_slice1_read_layer.py`, deleted here. **Zero HEAD-only
deterministic failures.**
