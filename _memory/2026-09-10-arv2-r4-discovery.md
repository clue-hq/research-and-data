# ARV2 R4 — verified account discovery (close-out, 2026-09-10)

Branch `track-r4`, worktree `san-salvador`. Plan of action (the substance, rev 5, with the §9
rulings ledger) `docs/superpowers/plans/2026-09-10-arv2-r4-discovery-substance.md`; implementation
plan `docs/superpowers/plans/2026-09-10-arv2-r4-discovery.md`; SDD briefs and per-task reports in
`.superpowers/sdd/2026-09-10-arv2-r4-discovery/`. Nine tasks, executed by Opus implementers with
the controller reviewing every task first-hand.

R4 is where the account names come from. A cohort is discovered from the project's **pinned** ICP,
every candidate is verified gate by gate with a quote and a source, and the human approves on the
existing accounts table — after which the approved accounts launch into the R2/R3 lane and display
on the existing screens. The lane-facing documentation is
`platform/api/clue_api/arv2/README.md` § "R4 — verified account discovery". **The live exit gate
(a 20-account cohort end to end on the Clue ICP) has NOT run** — it is founder-triggered, and its
evidence path is `.context/arv2-r4-acceptance/`.

The shape, in one line: **Exa Websets finds, Exa Answer verifies, three code guards overturn what
the model got wrong, the ICP document is the program.** No gate is encoded in code; the verifier
asks each hard gate's own `rule` and `test` as a question.

## Commits (base `6fb3f4923`)

| commit | what |
| --- | --- |
| `fefddcbfb` | T1 — the eight `CLUE_ARV2_DISCOVERY_*` settings with `.env.example` parity |
| `9467da0bc` | T2 — fleet kind `arv2_discovery`, migration `2cd622be2da0` (`arv2_discovery_run` + `arv2_discovery_candidate`), the discovery store |
| `aa7fb5a90` | T3 — `ExaClient.answer` (+ `ANSWER_ESTIMATE_USD`, `ExaCitation`, `ExaAnswerResult`) and the thin `exa_websets_client.py`, both through the provider caller |
| `a4a5164f1` | T4 — `discovery_brief.py` (the ICP compiled into a brief) and `discovery_verifier.py` (prompts, schemas, the three guards, fit, disposition) |
| `5a5ff06bf` | T5 — `discovery_launch.py` (replay + lineage, the relaxed request, the service seam, the tool registered **ungranted**), the fleet-task names, `scripts/launch_arv2_discovery.py` |
| `d301c9582` | T6 — `discovery_driver.py`: the webset long list, per-gate Answer verification with the guards, candidate accounts with fit, strict then relaxed pass; composed in `fleet_main`/`fleet_wiring` |
| `8358cfa21` | T6 fix round — a recorded webset is never bought twice, a failing candidate is contained per candidate, the task's `work_id` is cross-checked against its run |
| `196f1812c` | T7 — `bulk_actions.add_accounts_to_project` stamps the discovered candidate `approved` in the same transaction as the membership |
| `3a2555a4e` | T8 — `head-of-abm@v45` grants `launch_arv2_discovery@1`; `stage0-interview@v22` §7b teaches it; `recipe0-stage0@23` admits it |
| this commit | T9 — the README R4 section, the master-plan row, this note, the standing-rule checklist |

## What landed, per module

`discovery_store.py` (the only SQL to the two R4 tables) · `exa_websets_client.py` (create / get /
items / add_search, `is_all_green`, `websets_items_cost`, `websets_halt_rule`) · `exa_client.answer`
· `discovery_brief.py` (`Gate`, `DiscoveryBrief`, `compile_brief`, `buyer_sentence`,
`parse_window_months`, `BriefError`) · `discovery_verifier.py` (`system_prompt(today)`,
`gate_question`, `website_question`, `OUTPUT_SCHEMA`/`WEBSITE_SCHEMA`, `apply_guards`, `fit_score`,
`disposition` — pure, no clock, no settings, no DB, no provider) · `discovery_launch.py` (seam 1) ·
`discovery_driver.py` (the fleet handler + `relaxed_criteria` / `revenue_band`) ·
`fleet_task.py` (`arv2-discovery:`, priority −90, `arv2_discovery_work_id`) ·
`scripts/launch_arv2_discovery.py` (launch / `--relaxed-pass` / `--report`).

Money model, recorded because it is easy to get wrong later: Websets `create`/`add_search` reserve
`count × 10 × usd_per_credit` as the **estimate** and record a deliberate **zero** cost; the bill is
carried by `items`, priced per all-green row. An explicit zero reader (not "no reader") is
load-bearing — with no reader the wrapper falls back to the estimate and double-counts every match.
`is_all_green` counts an evaluation-less item as green because that is what Exa charges; it is never
used as a *qualification* test.

## Rulings honoured

From the spec's §9 ledger (all taken 2026-09-10 unless noted):

1. **Ruling 1** — the Clue ICP is the exit-gate target (owed live).
2. **Ruling 2** — the accounts table is the approval surface; no chat gate tool in R4. The approval
   *is* the existing "Add to project" bulk action.
3. **Ruling 3** — no spend caps of any kind; the ledger and the pre-spend estimate only. Costs are
   recorded on every hop and are never a gate.
4. **Ruling 4** — ask 35 for a target of 20 while precision is measured
   (`CLUE_ARV2_DISCOVERY_STRICT_COUNT=35`); partial matches are medium-fit, shown with an honestly
   weaker signal.
5. **Ruling 5** — unclear candidates are shown; no approval UI before a preview.
6. **Ruling (a)** — Overall fit vocabulary stays High / Medium / Low; an unclear account is a
   Medium by score. Fit = `(passes + ½ × unclears) / gates`, banded by the accounts list's own
   `CLUE_ARV2_FIT_*` thresholds.
7. **No frontend change** (rev 3) and **Overall fit + Fit score only, no custom variables, no notes
   column** (rev 4). Nothing under `apps/frontend` was touched.
8. **Relaxed pass: automatic when the strict pass is short *and* on request** — both triggers built
   (`arv2_discovery_relaxed_auto`, and `request_relaxed_pass` on a finished run).
9. **Ruling 1′** — unapproved is remembered per project and not re-surfaced, never labelled
   rejected (`unapproved_domains`, disposition `not_chosen_before`); local dedupe by verified domain
   always; the Websets `exclude` import waits for Exa's per-plan cap.
10. **Ruling 2′** — the paid plan is in place; proceed with Websets.
11. **Ruling 3′** — no per-run concurrency cap in R4; worker scheduling across job kinds is a
    separate follow-up discussion.
12. **Ruling 4′** — the Head-of-ABM profile bump lands **in R4**: profile v45, skill v22 §7b,
    recipe v23, the authority-map row.
13. **Ruling 5′** — aggregator job sites count as hiring and intent evidence.
14. **Ruling 6′ (deferred)** — what the future in-project target-accounts tab reads (candidate rows
    vs a pending membership) is the founder's later decision. R4 therefore writes **nothing** to the
    project until a human approves.

Taken during SDD execution (controller rulings, 2026-09-10):

15. **T5 registers the tool ungranted; T8 grants it.** `launch_arv2_discovery` entered
    `C6_AGENT_TOOL_AUTHORITY` as `()` at T5 (the R2 pattern: the write surface stays complete and
    auditable, the role decision lands with the profile version that teaches the tool) and became
    `(AgentRole.HEAD_OF_ABM,)` at T8 with v45.
16. **More than three criteria gate keys is a refusal, not a silent truncation.** `compile_brief`
    raises `BriefError("at most 3 criteria gate keys, got N")` rather than dropping a criterion the
    human configured. (Consequence recorded as a follow-up: `discovery_launch` maps *every*
    `BriefError` to the refusal code `unknown_criteria_gate_key`.)
17. **Per-candidate containment.** One candidate that fails is logged, named in the receipt's
    `candidate_failures` and left `pending` for the next attempt; its neighbours are still verified
    and the run lands `needs_review` keeping every counter. `ProviderHalted` and the wall clock end
    the run; a cancellation suspends under a shield.
18. **A recorded `webset_id` is never bought twice.** Any redelivery — a human's relaxed request, a
    stop, a lost lease, a worker restart — reads the recorded webset rather than creating a second
    one.
19. **`decided_by_user_id = actor_user_id or requested_by`** in the approval stamp — the fallback
    the rest of the lane already uses (`ctx.actor_id or ctx.actor`). In local-header auth
    `actor_user_id` is `None`, and recording the id that mode *does* carry beats recording no
    approver; with a real principal the two are the same string.
20. **The §7b skill passage was executed as written in the plan.** Founder edits to that wording
    land as a **new** skill version (v23) and a **new** profile version (v46) — an immutable
    resource is never rewritten in place.

## Standing-rule checklist (2026-09-10, R4)

Run against the current tree per `_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`.
**Verdict: 7/7 pass.**

1. **Profile grants — PASS.** The seventeen-name grep (readiness / Stage-0 / Client-KB / Product-KB
   / old-research-lane tools) over
   `platform/agents/catalog/profiles/head-of-abm/v45/profile.yaml` returns **nothing** (exit 1).
   v45's sixteen granted tools are: `stage0-interview` (skill), `draft_account_research_directive`,
   `get_research_view`, `inspect_statement_history`, `launch_arv2_account_research`,
   **`launch_arv2_discovery`**, `launch_arv2_person_research`, `open_design_leg`,
   `open_directive_confirmation_gate`, `open_icp_confirmation_gate`,
   `open_product_set_selection_gate`, `propose_field`, `propose_source`,
   `read_arv2_account_research_run`, `record_interview_answer`, `submit_ingestion`. The boot-time
   authority audit (`tests/agents/test_tool_authority_audit.py`) is green in both gate runs.
2. **Gate source — PASS.** `product_set_selection_gate_tools.py` greps clean for
   `compile_client_knowledge_card_v2` / `current_kb_version` / `load_pinned_client_knowledge`; it
   imports `clue_spine.{get_project, list_products, current_project_product_set}` and reads the
   catalog artifact. Its module docstring states the rule explicitly. R4 did not touch the file.
3. **Scope pin content — PASS.** `agent_turn_scope_pin.py`'s "a selected-product turn requires an
   established company Client-KB" refusal is still guarded by `if project.product_id is not None`,
   so a new-lane project (`product_id IS NULL`) can never raise it. R4 adds no pin code:
   `grep -cE "client_kb_version|readiness_decision|ClientKnowledgeCard|current_kb_version|stage0_pins|product_id"`
   over `discovery_launch.py`, `discovery_driver.py` and `discovery_store.py` returns **0, 0, 0**.
4. **Context composition — PASS.** R4's only edit to the composer is one line in
   `chat/composer_context.py` (`PROJECT_CONVERSATION_AGENT_PROFILE_ID` `head-of-abm@v44` →
   `@v45`); no Client-KB card compiler is added or composed, and `.env.example:117` still carries
   `CLUE_MEMORY_ENABLED=false`.
5. **Launch path — PASS.** `launch_arv2_discovery` needs a project in the workspace and the
   project's **ICP pin** (`current_project_icp_pin` → the verified artifact bytes) and nothing else;
   its refusal codes are `lane_disabled`, `target_count_invalid`, `project_not_found`,
   `project_icp_not_pinned`, `icp_artifact_not_found`, `icp_artifact_not_confirmed`,
   `icp_digest_mismatch`, `icp_front_matter_invalid`, `unknown_criteria_gate_key`. No
   `client_kb_version`, no `readiness_decision_id`, no `project.product_id` — see item 3's counts.
   R2's `launch_arv2_account_research` is unchanged.
6. **Static guard — PASS.** `tests/arv2/test_import_guard.py::test_the_arv2_package_imports_nothing_quarantined`
   walks the package's syntax tree and covers the six new R4 modules; green in both gate runs.
   `uv run lint-imports` → **Contracts: 26 kept, 0 broken.**
7. **`.env.example` posture — PASS (and one item that was failing at O6 is now fixed).**
   `git diff 6fb3f4923 HEAD -- .env.example` is **only** the `CLUE_ARV2_DISCOVERY_*` block (eight
   keys, each commented, `CLUE_ARV2_DISCOVERY_ENABLED=false`). Against the wider
   `git diff 3e1587f88 HEAD -- .env.example` the file also shows two changes made **between**
   3e1587f88 and R4's base 6fb3f4923, by other lanes, not by R4: the
   `CLUE_FLEET_WORKER_CONCURRENCY=1` block, and `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED` flipped
   `true` → `false` (founder ruling 2026-09-10 (O6): the legacy lane stays off everywhere). The
   posture keys today read `CLUE_SELF_SERVE_PROVISIONING_ENABLED=false`,
   `CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off`, `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false`
   (+ `CLUE_MEMORY_ENABLED=false`) — so the item-7 failure recorded in the O6 note is **closed**.

## Verification (this commit)

The full offline gate, run **twice**, never `source .env`, never a `*_live.py` test, never
`make check`:

```
uv run pytest tests/arv2 tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py \
  tests/api/test_toolbelt_wiring.py tests/agents tests/api/test_frontend_read_accounts_list.py \
  tests/api/test_frontend_bulk_actions_discovery_db.py tests/db/test_arv2_r4_migration.py tests/fleet \
  --ignore-glob='*_live.py' -p no:cacheprovider -q
```

- **Run A — no env at all** (DB-gated tests skip): **1342 collected — 1155 passed, 186 skipped,
  1 failed.** The one failure is the recorded pre-existing red
  `tests/api/test_agent_registry_wiring.py::test_design_profile_resolves_with_the_full_granted_write_surface`
  (`'openai/x-ai/grok-4.6' != 'openai/gpt-5.6-terra'` — the design profile's model pin, unrelated to
  R4 and red at every task's baseline).
- **Run B — only the lane DSN exported** (`CLUE_DATABASE_URL` / `CLUE_TEST_DATABASE_URL` from
  `.env`, database `clue_san-salvador`): **1342 collected — 1334 passed, 5 skipped, 3 failed.** The
  same design-profile red, plus two **pre-existing lane-DB data conditions** in
  `tests/arv2/test_answer_key_loader_db.py`
  (`test_repair_gives_a_bare_work_email_claim_the_providers_verdict`,
  `test_repair_writes_the_research_rows_once_on_an_already_loaded_database`): the repair finds 15
  `core.work_email` claims where the test expects only the planted one, and skips 11 with
  `no_answer_key_row`, because the lane DB carries real rows from earlier live acceptance runs.
  Recorded identically by T2 and T5; the file is not touched by R4.

Other gates, all clean:

- `uv run ruff check` and `uv run ruff format --check` over every Python file R4 touched
  (`git diff --name-only 6fb3f4923 HEAD -- '*.py'` → 48 files): *All checks passed! / 48 files
  already formatted.*
- `uv run lint-imports` → **Contracts: 26 kept, 0 broken** (885 files, 8356 dependencies).
- `uv run alembic heads` → **one head, `2cd622be2da0`.**

*(zsh note for whoever repeats this: unquoted `$FILES` does **not** word-split in zsh — pipe the
file list through `tr '\n' '\0' | xargs -0`, or ruff sees one impossible filename.)*

## Pre-existing reds left alone (deliberately)

- `tests/api/test_agent_registry_wiring.py::test_design_profile_resolves_with_the_full_granted_write_surface`
  — the design profile's model pin (`grok-4.6` vs `gpt-5.6-terra`). Red at every R4 task's baseline;
  belongs to the model-config map, not this lane.
- `tests/execution/test_recipes.py` (four tests; not in the R4 gate command, checked by T8 against
  the lane DB) — the recipe0 seeding contracts.
  `test_latest_recipe0_is_the_only_promoted_executable_stage0_revision` asserts recipe0 revisions
  are **contiguous** (`versions == list(range(1, max+1))`) while `SYSTEM_RECIPE_FILENAMES` skips
  16–18 and 20–21, so it was already red and stays red; **v23 does not make it worse, but the gap
  grows by one at every bump**, and a fresh throwaway DB will not fix this one (it is a pure list
  assertion). The other three (`RecipeVersionConflict`, `InvalidRecipeTransition`,
  `test_c67_account_unit_is_preserved_as_replay_only_not_system_seeded`) are stale-lane-DB
  artefacts. Whoever owns that seeding contract should decide whether the contiguity rule or the
  filename list is wrong.
- `tests/api/test_pilot_budget_controls.py` (3) — `FieldRedefinitionError` on
  `contact.facet.career_history`, a lane-DB artefact of the R3 migration; verified at HEAD by T8 in
  a temp worktree.
- `tests/db/test_db_migrations.py` and `tests/db/test_arv2_onboarding_persona_step_migration.py`
  fail on the **lane** DB only (it holds 18 person research jobs, which the R3 downgrade guard
  refuses). Migration-shaped suites belong on a clean throwaway DB, which is where T2 ran them
  (`clue_r4_smoke_*`, created and dropped; up → down → up clean, one head).

## Follow-ups

1. **The Websets exclusion import** — import the workspace's existing account websites into the
   webset's own `exclude` list once Exa confirms the per-plan cap (ruling 1′). Local dedupe already
   catches the same companies, just after the long list rather than before it, so this is a cost
   saving, not a correctness gap.
2. **Worker scheduling across job kinds** — the discussion ruling 3′ deferred: how the per-process
   worker slots are shared between `arv2_account_research` and `arv2_discovery` (today discovery
   simply sits at priority −90 and yields to research at −100), and whether the AI Ark spacing rule
   becomes a shared limiter.
3. **The chat approval gate** — only after the founder designs the in-project target-accounts tab
   beside Gallery, and only once ruling 6′ decides what that tab reads (candidate rows vs a pending
   membership).
4. **The recall angles, if the pools prove short in practice** — Exa `/search` stays for the domain
   lock when a human names a company, and is the later recall angle (signal-first announcement and
   job-post queries). The run already records `asked` / `found_strict` / `found_relaxed` /
   `analyzed` / `recall_estimate`, so "the pool is short" will be a measured claim, not a guess.
5. **An `exa-pro` comparison** — `CLUE_ARV2_DISCOVERY_ANSWER_MODEL` is a one-key swap; the
   experiment measured `exa` only (24/26 agreement with hand-checked truth, ≈$0.005 and ~2 s per
   question). Worth measuring precision and cost per company on `exa-pro` before widening the ask.
6. **Split `unknown_criteria_gate_key`** — `discovery_launch` maps every `BriefError` to that one
   refusal code, but `compile_brief` raises it for three things (an unknown key, a document with no
   `hard_gates`, more than three keys). The message is always accurate; the code is a misnomer for
   two of them. Two-line change plus a test (`icp_has_no_hard_gates` /
   `too_many_criteria_gate_keys`).
7. **The ICP's exclusion questions (final review I3 — founder decision).** Spec §3 asks one
   `/answer` per hard gate *and per page-answerable exclusion*; R4 asks the gates only.
   `compile_brief` compiles `DiscoveryBrief.exclusions` and nothing reads it (the field is now
   documented as reserved, and the README's "what R4 deliberately does not build" names the gap).
   Two things need deciding before it is built: how an exclusion scores, given fit is
   `passes / gates` today and an exclusion is a disqualifier rather than a gate; and whether the
   cost is worth it — the confirmed Clue ICP states eight exclusions, so about eight more Answer
   calls, roughly **$0.04 per company**, on top of the four gate calls. Until then a company that
   clears every hard gate but sells to consumers can still land as a High-fit candidate.
8. **`exa_answer` cost readers, if Exa starts metering differently** — `ANSWER_ESTIMATE_USD` is a
   flat cent and the ledger reads Exa's own `costDollars.total`; `websets_items_cost` prices 10
   credits per all-green row at `CLUE_ARV2_DISCOVERY_WEBSETS_USD_PER_CREDIT`. Both are honest today
   and both are one place to change if the meter moves.

Carried, smaller, each recorded at its site: `_pre_spend_disposition` counts duplicates and
`not_chosen_before` as a side effect of answering "what is this company" (a query with a write, and
deliberate — one place decides and counts); `_REVENUE_BANDS` is spelled in the driver because the
registry's copy lives in `clue_research.discovery_scoring`, which the lane may not import (the DB
test pins one band end to end against the real `core.revenue_band` field, so drift fails loudly);
the tool's `relaxed_enabled` default of `True` means a model-initiated launch always requests the
relaxed pass regardless of `arv2_discovery_relaxed_auto` (only the CLI and direct callers fall
through to the setting); an account that was already a project member is not in `inserted`, so its
candidate row keeps `decision NULL` even if the human ticked it (benign — such a candidate is
normally `duplicate_of_existing`, and `unapproved_domains` only remembers `pass`/`partial`/
`unclear`); `websets_halt_rule`'s reason string is a message, not a short error code like the rest
of the ledger's.

---

## Final-review fix wave (2026-09-10, one commit on `track-r4`)

The whole-branch review (`.superpowers/sdd/2026-09-10-arv2-r4-discovery/final-review.md`) found
0 Critical / 4 Important / 12 Minor. I1, I2 and I4 are fixed; I3 is a recorded founder deferral;
M1, M6 and M12 are folded in. Nothing else on the review's minor list was touched.

- **I1 — the run verifies against its own pinned bytes.** `discovery_launch` gained a second
  public read, `read_icp_document(conn, storage, *, workspace_id, artifact_key, artifact_sha256)`,
  and the parsing/validation half both readers share moved into a private `_icp_document`.
  `read_pinned_icp` still resolves the project's *current* pin (that is the launch's question);
  the driver's `_compose` now reads the run row's own `icp_artifact_key` and refuses
  `icp_digest_mismatch` when the stored content sha is not the run's. `PinnedIcpDocument.brand_id`
  is documented as pin-path-only and defaults `""` on the by-key read — an artifact key is
  content-addressed, not brand-keyed, so resolving a brand from it would be a guess.
- **I2 — the search ids are persisted.** Migration `2cd622be2da0` was edited **in place** (it is
  unreleased; only the lane DB carried it) to add nullable `strict_search_id` / `relaxed_search_id`
  on `arv2_discovery_run`, and re-applied with `alembic downgrade 71e80c777cf6 && alembic upgrade
  head` (the downgrade's `arv2_discovery`-tasks refusal did not fire; one head after). The store
  round-trips both, `record_webset` takes the strict id, and `record_relaxed_search` is a new
  transition written the moment `add_search` returns. The driver looks the strict search up **by
  id** (a webset with two searches and no recorded strict id now refuses
  `webset_search_ambiguous` instead of taking `searches[0]`), and a run that already carries a
  `relaxed_search_id` polls and reads it rather than buying a second widening.
- **I3 — deferred by founder ruling, recorded three places.** `DiscoveryBrief.exclusions` is
  documented as reserved-and-unread, the README's "what R4 deliberately does not build" names the
  gap with its cost (~8 more Answer calls, ≈$0.04 per company), and follow-up 7 above carries it.
  The field is kept rather than deleted so the pass that will ask them has its input.
- **I4 — a webset row is priced once per run.** `ExaWebsetsClient.items` takes
  `priced_item_ids` and returns the ids it actually priced; `newly_priced` is the one predicate
  both the cost reader and the page loop use, so the ledger and the caller can never disagree.
  `_RunState.priced_item_ids` is seeded in `_compose` from each recorded candidate's
  `provider_snapshot["item"]["id"]` (the raw item is stored whole), so the set survives a restart,
  and the receipt states the assumption with `credits_priced_once: true`. A row Exa gave no id for
  is priced on every read — over-reporting one unidentifiable row is the safe direction.
- **M1** the items cursor is `urllib.parse.quote(cursor, safe="")`-encoded (a base64 `+` decodes
  server-side as a space). **M6** the fit claim's `markers` carry `icp_artifact_key` /
  `icp_artifact_sha256`. **M12** the two resume gaps are pinned by new offline tests.

Two things worth knowing next time:

- The receipt's `criteria_relaxed` is now null on an attempt that found the widening already
  bought (it states what *this* attempt sent), so `relaxed_search_id` was added beside it — the
  pair is never silent about whether a widening happened.
- M6 as the review wrote it was about the accounts list *grouping* discovery scores by
  `payload.icp_key` / `payload.icp_version`; the ruling put the two artifact pins in `markers`
  instead. The grouping half is untouched: a discovery `account.scoring.fit` still groups as an
  ICP-less score beside an M6.3 score for the same project. Left for whoever owns that list.

## Parked at the final review (controller ruling, 2026-09-10)

- **M6 residual — the fit payload carries no `icp_key`/`icp_version`.** `frontend_read.accounts_list`
  groups `account.scoring.fit` rows by `(project, payload.icp_key, payload.icp_version)`, so a
  discovery score groups as ICP-less beside any later M6.3 score for the same project. Parked: on
  ARV2 workspaces no other writer of that field exists today, so the list shows the discovery score.
  First follow-up: add `icp_key`/`icp_version` to the fit payload (the registered schema admits
  extra keys) — one line in `discovery_driver._write_claims` plus a test.
