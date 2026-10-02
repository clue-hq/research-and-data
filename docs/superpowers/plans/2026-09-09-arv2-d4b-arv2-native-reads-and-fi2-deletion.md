# ARV2 D4-b — ARV2-native reads, FI-2 deletion, and the three screen-data fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the accounts screens read only ARV2's own rows — research status from `arv2_research_run`/`arv2_research_job`, the committee from the claim store — delete the FI-2 read branches, the `?contract=` parameter and every legacy-table read on the ARV2 path, stop the D1 loader from writing legacy terminal rows, and fix the three facts R2 writes that the screens cannot yet show (the work-email verdict, revenue/funding labels, persona and "why they matter" text). No frontend component changes; the adapters just stop sending the parameter.

**Architecture:** The claim store is the only seam (master plan §2 principle 5). Everything the screens say about research comes from three ARV2 sources: the claims (facts), `display_block` (copy), and `arv2_research_run`/`arv2_research_job` (status). The committee is ARV2-native: until R3 defines committee rows, "the contacts under the account that hold live claims, ordered by persona rank" is the rule everywhere (display module and read surface share D2's `committee_members`, which loses its legacy branch). The FI-2 readers, their wire models and their tests are deleted; `contract_mode` goes; the v1 readers become the readers. The email verdict is carried in the claim value (`{"address", "status", "checked_at"}`), written by every writer that has one and read by the existing `email_facts`. Revenue/funding labels read the registry objects' keys the way `employee_band`/`location_label` already do. `persona` on the wire becomes served display text ("Economic buyer"); "why they matter" never prints a pipeline sentence.

**Tech Stack:** FastAPI + SQLAlchemy async (`text()` SQL), pydantic v2, the ARV2 display package, Alembic (one small data migration for the email value shape is **not** needed — claims are append-only; the loader re-writes its rows and readers accept both shapes), the `tests/profiling` DB harness, Zod oracle for the contract, `apps/frontend` for the one-line adapter change.

**Spec:** Founder rulings 2026-09-09: "ARV2's schema is the only truth; nothing about the old research lane matters" (recorded in the auto-memory `arv2-schema-is-the-only-truth`), the D4 follow-ups (`_memory/2026-09-09-arv2-d4-accounts-relift.md` §Follow-ups), `docs/specs/ARV2-DATA-SOURCE-MAP.md` §3.1/§3.3/§3.5/§3.6/§3.9 (the element rules, now sourced from ARV2 rows), `docs/specs/ARV2-MASTER-PLAN.md` §6 (contract v1 semantics), R2's own contract in `platform/api/clue_api/arv2/README.md` and `alembic/versions/a3602967bb73_arv2_r2_account_research_jobs.py` (the run/job tables and their `_STATUSES` vocabulary).

## Global Constraints

1. **ARV2 rows only on the ARV2 path.** After this plan, `grep -rn "entity_research_\|read_governed_committee\|ContactEligibilityResolver\|display_allowed\b" platform/api/clue_api/arv2 platform/api/clue_api/frontend_read/{accounts_list,account_detail,account_workspace,contacts,display_pages,v1_shared}.py` returns zero hits outside comments explaining the deletion. A test pins it.
2. **No bridge writes.** Nothing in ARV2 writes a legacy table (`entity_research_*`, `account_run`, `research_view_*`). The D1 loader's `_research_rows` is deleted, not kept "harmless".
3. **Contract v1 is unchanged in shape.** No field added or removed on the wire; two semantics change and are recorded in `apps/frontend/docs/api-contracts/accounts.md` and the parity doc tables' "rule" column: `persona` is served display text; `researchStatus` derives from ARV2 runs. The Zod oracle (`tests/api/contract_v1`) stays green.
4. **Legacy deletion scope in this PR = the FI-2 read surface** (the `read_*` FI-2 readers, their wire models, `contract_mode`/`ContractDep`, the FI-2 route tests, the FI-2 `committee.py` seam and `frontend_read/evidence.py`/`prose.py` if nothing else imports them) **plus every legacy read on the ARV2 path.** The old research lane's own tables and modules (M8D `entity_research_*`, C7, quarantined runtime) are **inventoried here (Task 7) and deleted in the next PR** — they are imported by the fleet, toolbelt and agents packages, and bundling that deletion would make this PR unreviewable. The founder may override.
5. **Email verdict shape:** `core.work_email` value is `{"address": str, "status": <verdict>, "checked_at": ISO | null}` with `status ∈ {verified_smtp, catch_all_valid, invalid, unknown, unverified}` (the provider's verdict vocabulary the D3 reader already keys on); a bare string remains readable (→ `lookup`) but no ARV2 writer produces one after this plan. The registry row `core.work_email` changes `value_type`/`value_schema` to the object (a pack edit + the existing "re-loaded pack" path; the lenient writer stores either shape regardless).
6. **Never `git stash`**; no secrets; no AI attribution; never push; implementers are Opus, reviews are the controller's own; DB = the worktree's `postgresql+asyncpg://clue:clue@localhost:55060/clue` (answer key + 37 display blocks + the dev identity rows); focused suites per task, one wider offline pass at close-out **per directory with `uv run --with pytest-timeout pytest … --timeout=120`** streaming to a log (the D3 lesson).
7. **Frontend gate** for the one adapter change: `cd apps/frontend && npm run lint && npm run build && npm test`.

---

## Decisions this plan takes (each overturnable; ledgered)

1. **Status mapping from ARV2 rows.** For an account: take the latest `arv2_research_job` for `(workspace, account)` by `created_at DESC, job_id DESC` (joined to its `arv2_research_run` for `project_id`). `researchStatus` = `not_started` when no job; otherwise the job's `status` **verbatim** — R2's `_STATUSES` is exactly the wire enum `('not_started', 'in_progress', 'needs_review', 'completed', 'suspended')`, so no mapping table exists to drift (a test pins the two vocabularies equal). `researchIsRefreshing` = a non-terminal job exists newer than a `completed` job for the same account. The FI-2 per-project attribution is gone: the row's status is the account's latest job, whichever project launched it (ARV2 runs pin `project_id`; the row shows the primary project's name as before). E2's detail status uses the same function.
2. **Committee = contacts under the account with ≥1 live claim**, ordered by `PERSONA_RANK` over their latest `contact.persona` claim, then name. D2's `committee_members` drops the coverage branch; `display_pages.committee` and the E4 rows already consume it. `insightSummary`'s `"{m} people"` counts the same set. When R3 lands it replaces this rule in one place.
3. **Persona is served display text.** `PERSONA_LABELS = {economic_buyer: "Economic buyer", champion: "Champion", technical_evaluator: "Technical evaluator", user: "User", blocker: "Blocker"}`; an unknown value is title-cased with underscores replaced. Applied to `AccountContactSummaryV1.persona`, `AccountContactDetailV1.persona`, `BuyingCommitteeMember.persona`, `ResearchContactReference.persona` (contact refs and `subject` inside display items — the display module writes those at generation time, so `runner.materialise` applies the label too, and the 37 stored blocks are **regenerated for their contact refs only by a one-shot script** that rewrites `persona` in stored `body_json` — no model call). `personaTone` and ordering keep using the vocabulary value internally.
4. **"Why they matter" never prints machinery.** In `display_pages._why_they_matter`: a role claim whose `write_markers` carry `derived_role_from_persona`, or whose rationale contains the loader's marker phrase, is treated as having no rationale → `"{title} · {persona label}"` when a title exists, else `"Committee member"`. The D1 loader's derived rows also get a human rationale going forward (`"{title} — {persona label}"`).
5. **Revenue and funding labels** (`v1_shared.revenue_label`, `funding_label`): `core.annual_revenue` object `{amount_min, amount_max, currency, as_of, estimate_kind}` → `"$10M–25M"` (compact units K/M/B, currency symbol for USD/EUR/GBP else the code prefix); a single `amount` → `"$130.5M"`; a string → itself; `core.revenue_band` string as today. `account.total_funding` object `{amount, currency, rounds, investors}` → `"$130.5M"`; `account.recent_funding` `{round, amount, currency, date, investors}` → `"Series C · $60M"` when both, `"Series C"` alone otherwise; `fundingLabel = f"{recent} · {total}"` when both. Add `format_money(amount, currency)` to `v1_shared`.
6. **Email verdict writers:** (a) the D1 answer-key loader maps the PoC row's `verification.verdict` (present on the four Zafran email rows: `verified_smtp`) into the object; the loader is one-shot per DB, so the four existing bare-string rows are **superseded** by a small idempotent script step `scripts/load_arv2_answer_key.py --repair-emails` (writes the object claim with the same provenance and supersedes the string claim); (b) the FI-2/ARV2 email-lookup writer (`contact_channel_enrichment.py`, the one `POST …/email-lookup` path the frontend keeps) writes the object with the provider's verdict and `checked_at`; (c) R2's deterministic mappers do not write emails today (people are R3's) — record that R3's mapper must use the object. The reader `email_facts` already handles the object; add `unknown`/`invalid` handling (→ `lookup`).
7. **`lastModifiedAt`** keeps its three sources (entity, claims, display blocks) — none is legacy.
8. **Activity** keeps `account_activity_event` (D1's table, ARV2-native). The FI-2 `account_activity.py` (E6, the `research_subject_activity` projection) is deleted with the FI-2 surface; the frontend's activity tab reads `activity[]` on E2/E3 already.
9. **Evidence stream (E7)** stays, authorising against the v1 page's citations only (the FI-2 half of the union goes with the FI-2 detail).
10. **The D1 loader's legacy terminal rows are gone;** its tests and the D2 seed (`tests/arv2/display/_seed.py`) drop the coverage-row fixtures; the loader still writes the ARV2-native facts (claims, artifacts, activity) and now also one `arv2_research_run` + one `arv2_research_job` (`completed`) for Zafran so the answer key shows `Researched` under the new status rule — written through R2's `account_research_store` functions, not raw SQL, with the run pinned to the answer-key project and ICP artifact the loader already creates (or an honest stand-in ICP artifact key it registers, as the R2 acceptance seed did — read `.context/arv2-r2-acceptance/` and `scripts/` for how Probook was seeded and reuse that).

---

## File structure

```
platform/api/clue_api/frontend_read/
  accounts_list.py     list_accounts_v1 → list_accounts (the reader); FI-2 reader/models/SQL deleted; status from arv2_research_job
  account_detail.py    read_account_detail_v1 → read_account_detail; FI-2 reader/models deleted; E7 authorises on v1 citations
  contacts.py          v1 readers become the readers; FI-2 readers/models/governed committee deleted
  account_workspace.py unchanged except ContractDep removal
  app.py               contract_mode/ContractDep deleted; registrars lose the FI-2 wiring
  v1_shared.py         + PERSONA_LABELS, persona_label, format_money, revenue/funding label rewrite, arv2 status helpers, email verdict handling
  display_pages.py     committee via D2 (no coverage), _why_they_matter rule
  committee.py, evidence.py, prose.py, account_activity.py   deleted if unreferenced after the FI-2 removal
platform/api/clue_api/arv2/display/gather.py     committee_members loses the coverage branch
platform/api/clue_api/arv2/display/runner.py     contact refs carry the persona label
platform/api/clue_api/arv2/answer_key_loader.py  _research_rows deleted; arv2 run/job written via the store; email objects; human derived-role rationale
platform/api/clue_api/arv2/catalog_seed.py / claimstore packs   core.work_email value schema → object
platform/api/clue_api/contact_channel_enrichment.py   email object with verdict
scripts/load_arv2_answer_key.py (--repair-emails), scripts/rewrite_display_persona_labels.py (one-shot)
apps/frontend/src/features/accounts/data/*.repository.ts   drop `contract: "v1"` (9 sites) + their tests
tests/api: FI-2 suites deleted (test_frontend_read_accounts_list/account_detail/contacts/account_activity.py FI-2 halves → the v1 halves become the suites), new tests for status mapping, committee rule, labels, email verdict; tests/arv2: loader + seed updated
docs: accounts.md (semantics), ARV2-DATA-SOURCE-MAP.md (§3 sources = ARV2 rows), master plan §9 note, arv2 README, memory note, Phase-6 inventory (Task 7)
```

---

### Task 1: Research status from ARV2 rows

**Files:** `frontend_read/v1_shared.py` (`arv2_research_status_for(conn, *, workspace_id, account_ids) -> dict[EntityId, tuple[ResearchStatus, bool]]`, one statement over `arv2_research_job JOIN arv2_research_run`), `accounts_list.py` (the v1 reader uses it; `_read_v1_research`, `_RESEARCH_JOBS_V1`, `AccountResearchStatusValue`'s M8D mapping deleted), `account_detail.py` (same), tests (`tests/api/test_frontend_read_accounts_list.py` v1 half: seed `arv2_research_run`/`arv2_research_job` rows through `account_research_store` — read it for the insert functions — for `completed`, `needs_review`, `suspended`, `running`, none, and the refresh case; the legacy `entity_research_job` seeds in the v1 tests are removed).
- [ ] RED (the status cases) → implement (decision 1) → GREEN; commit `feat(frontend-read): research status from arv2_research_run/job (ARV2 rows are the only truth)`.

### Task 2: The ARV2-native committee

**Files:** `arv2/display/gather.py::committee_members` (drop `_COVERAGE_SQL` and the branch; the rule = contacts with live claims, persona-ranked — move the persona-rank ordering here from `display_pages.committee` so D2 and D3 share one order), `display_pages.py` (`committee` becomes a thin call; `_why_they_matter` rule, decision 4), `tests/arv2/display/_seed.py` + `test_gather_db.py` + `test_page_db.py` (no coverage rows), `tests/api/test_frontend_read_display_pages_db.py`, `tests/arv2/test_answer_key_loader_db.py` (no committee-row assertions).
- [ ] RED → implement → GREEN; commit `feat(arv2 display, frontend-read): the committee is the contacts with live claims, persona-ranked — no coverage-row branch`.

### Task 3: Persona labels, "why they matter", revenue/funding labels

**Files:** `v1_shared.py` (`PERSONA_LABELS`, `persona_label`, `format_money`, `revenue_label`, `funding_label`), `contacts.py`/`display_pages.py`/`account_detail.py` (apply `persona_label` on every served `persona`), `arv2/display/runner.py` (contact refs/subject persona label), `scripts/rewrite_display_persona_labels.py` (one-shot over stored `display_block.body_json` `contactRefs[].persona`/`subject.persona`; idempotent; `--database-url` required; run it on the worktree DB and record counts), tests (pure label tests with the Zafran shapes: `{"amount_min": 10000000, "amount_max": 25000000, "currency": "USD", …}` → `"$10M–25M"`; `{"amount": 130500000, "currency": "USD", "rounds": 4, "investors": 9}` → `"$130.5M"`; `{"round": "Series C", "amount": 60000000, "currency": "USD"}` → `"Series C · $60M"`; persona labels; the derived-role rationale rule), `docs` rule column for `persona`.
- [ ] RED → implement → GREEN → run the one-shot on the worktree DB; commit `feat(frontend-read): persona and committee text served as display text; revenue and funding labels from the registry objects`.

### Task 4: The work-email verdict

**Files:** the `core.work_email` registry row (find where `CORE_PACK` defines it in `clue_research/claimstore/packs.py`; change `value_type`/`value_schema` to the object; the D1 migration precedent for a schema change on a registered row — a re-loaded pack raises `FieldRedefinitionError` — means a small Alembic data-fix migration updating `field_definition.value_schema`/`value_type` for that key, hash id, reversible), `arv2/answer_key.py`/`answer_key_loader.py` (map `verification.verdict` + `checked_at` into the object; derived rationale text), `scripts/load_arv2_answer_key.py --repair-emails` (supersede the four bare rows with object rows, idempotent), `contact_channel_enrichment.py` (write the object with the provider verdict), `v1_shared.email_facts` (`unknown`/`invalid` → `lookup`), tests (loader mapping; the repair script on the worktree DB; the lookup writer's value; `email_facts` matrix; the Zafran walk test now asserts Nick `emailStatus == "available"` and `buyingCommittee[].email` set for the four).
- [ ] RED → implement → migration (`uv run alembic revision -m "core.work_email carries the provider verdict"`, one head, `make db-smoke` on a clean throwaway DB) → run the repair on the worktree DB → GREEN; commit `feat(arv2, frontend-read): core.work_email carries the provider verdict; the loader and the lookup writer keep it; the screens show available addresses`.

### Task 5: Delete the FI-2 read surface and the `contract` parameter

**Files:** `frontend_read/app.py` (delete `contract_mode`, `ContractDep`; registrars), `accounts_list.py` / `account_detail.py` / `contacts.py` (delete the FI-2 readers, wire models, SQL and helpers; rename the v1 readers to the plain names; E7 authorises on the v1 page only), delete `committee.py`, `evidence.py`, `prose.py`, `account_activity.py` and the E6 route if nothing else imports them (grep `platform/` first; `bulk_actions.py`/`contact_email_lookup.py` may import `committee.py`'s governed reader — if so, re-point them at D2's committee rule, or delete the contact bulk email path outright since the frontend dropped it), delete the FI-2 halves of the four route suites and `test_frontend_read_account_activity.py`, `__init__.py` exports, `apps/frontend/src/features/accounts/data/*.repository.ts` (drop `contract: "v1"` at the 9 sites + tests; `readAccountsResult` likewise), `accounts.md` (the parameter paragraph → "removed 2026-09-09"; FI-2 sections deleted or marked historical), the standing-rule guard test from Global Constraint 1.
- [ ] RED (the guard test) → delete → GREEN (`tests/api` route suites + `tests/api/contract_v1` + Zafran walk; `apps/frontend` gates); commit `refactor(frontend-read, frontend): one contract — the FI-2 readers, models and the ?contract parameter are deleted`.

### Task 6: The D1 loader writes ARV2 rows only

**Files:** `answer_key_loader.py` (`_research_rows` deleted; write one `arv2_research_run` + one `arv2_research_job` (`completed`, `finished_at`, `finalization_json` with the claim count) for Zafran through `account_research_store`, pinned to the answer-key project + the stand-in ICP artifact the R2 acceptance seed used), `tests/arv2/test_answer_key_loader_db.py` (assert the ARV2 rows; no legacy rows), `README.md` D1 section (the "R2's finalization must produce the same rows" paragraph replaced by the ARV2-rows rule), the Zafran walk test (`researchStatus == "completed"` now comes from the ARV2 job — seed it in the worktree DB with a small idempotent `--repair-research-rows` step of the loader script, run and recorded).
- [ ] RED → implement → GREEN; commit `refactor(arv2 loader): the answer key writes ARV2 run/job rows, never legacy terminal rows`.

### Task 7: Phase-6 inventory, records, close-out

- [ ] **Inventory (document, no deletion):** `docs/specs/ARV2-PHASE6-LEGACY-DELETION-INVENTORY.md` — every legacy table (from `alembic/versions` + `\dt`), every module under the M8D/C7/quarantined lanes with LOC, who imports each (`grep`), the flags that gate them, and a proposed deletion order (stub-and-delete per the CLAUDE.md audit note). This is the next PR's plan input.
- [ ] Records: `docs/specs/ARV2-DATA-SOURCE-MAP.md` §2.1 (legacy tables struck from "tables the reads touch"), §3.1/§3.3/§3.5/§3.6/§3.9 sources = ARV2 rows; master plan §9 dated note + the ruling; `arv2/README.md`; `_memory/2026-09-09-arv2-d4b-arv2-native-reads.md` + index.
- [ ] Gate: per-directory wide passes with `pytest-timeout` streaming to logs (`tests/api`, `tests/arv2`, `tests/claimstore`, `tests/db`), attribution of every failure; `ruff`, `mypy`, `lint-imports`, one Alembic head, `make db-smoke` on a clean throwaway DB; `apps/frontend` gates; the Zafran walk test green with `Researched` from ARV2 rows and Nick's email `available`. Commit `docs(specs, memory): D4-b close-out — ARV2-native reads, FI-2 removed, Phase-6 inventory`.

---

## Self-review

- **Coverage:** the founder's three "research to screen" and three "data R2 writes" items → T1, T2, T3, T4; FI-2 deletion → T5; "cleanup of legacy tables / stale schema" → the ARV2-path reads and writes (T1, T2, T5, T6) now, the old lane's own tables and code inventoried in T7 and deleted next PR (Global Constraint 4, explicit for the founder).
- **Placeholders:** none; each task names files, the rule, the RED cases and the commit.
- **Type consistency:** `arv2_research_status_for` returns the same `(status, refreshing)` tuple the v1 readers consumed; `committee_members` keeps returning `list[SubjectRef]`; `email_facts` keeps `EmailFacts`; `persona` stays `str` on the wire.
