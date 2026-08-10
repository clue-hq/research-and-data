# 2026-08-08 — FI-2 slice 0 COMPLETE (workspace-account substrate) — closing entry

Executed via subagent-driven development off `docs/specs/FI-2-slice0-implementation-plan.md`: 10 tasks, each
implemented by a fresh Opus agent, task-reviewed, fix-rounded (7 of 10 needed exactly one round), scoped
re-reviews, then a whole-branch final review (verdict: merge-worthy) + one final fix wave. All review artifacts
were in the gitignored `.superpowers/sdd/` workspace (deleted after this note per SDD protocol); the durable
record is git history + this note.

## What landed (commit range cecb2c09..a8d30e55 on `platform/frontend-integration`; 4 foreign docs commits interleaved)

- **Migrations (4, hash-chained, single head `9c8cbd79a0e7`):** `9a21734d9406` run_lineage; `61b00ee9c70a`
  project_account; `21552956dc51` research_scope on field_definition+workspace_field_definition;
  `9c8cbd79a0e7` identity_review_task.project_id.
- **P2 `run_lineage`** (`clue_research/claimstore/run_lineage.py`): claim→project join spine; registered at
  **19 production mint sites + C3 ingestion (final wave, kind=manual)**; key discovery — M8D claims carry
  per-tool-call derived run ids (Exa) or project_run_id itself (Sumble), both registered. Known exemption
  classes documented in the module docstring (redaction/tombstone runs; pre-FI-2 rows).
- **P1 `project_account`** (`clue_research/membership.py`): first-add-wins membership; writers at discovery
  admission (`added_via` via `membership_channel()`; trial passes explicit `manual`), websets replay/merge paths,
  directives, import (with new optional tool `project_id` — **stays `@1`**, ratified), review-resolution (new
  `identity_review_task.project_id` stamped at enqueue); merge re-point inside `mark_merged`; `split_merge` does
  NOT restore membership (documented; M2.4-owner deferral in spec §11).
- **P3 `research_scope`**: frozen-core contract-delta (`ResearchScope`, `FieldDef.research_scope`,
  `default_research_scope`/`resolve_research_scope` — key-rule total); must-declare guard at registration AND
  both authoring gates (proposal payload + pack validation) AND ingestion sink; §5.2 declarations landed
  (scoring/narrative/committee relative; all else neutral). **Forced a digest-only C6 re-pin:
  `stage0-interview@v10` + `head-of-abm@v22`** (verified byte-clean; first pure re-pin — mechanism: new
  immutable version dir + flip `C6_ACTIVE_PROFILE_VERSIONS`).
- **H1**: embed-at-creation (forwarding admit's existing `DEFAULT_EMBEDDER` into disposition + review-resolution
  create) + admission aliases → name-only re-encounter now review-bands at 0.775 (real pre-fix score was 0.325,
  not the spec's 0.40 — geo is dropped at mint). Backfill: `scripts/backfill_account_embeddings.py` (manual run).
- **H2**: `enrich_account`/`enrich_survivor` — strong-key AUTO_MERGE unions aliases(+observation name)/registry
  (survivor-wins)/fills missing domain+geo, collision-skips (never fails ingest; savepoint retry tested),
  never touches canonical_name; trigger-aware delta so canonical_version bumps iff changed.
- **Backfill**: `clue_research/project_lens_backfill.py` + `scripts/backfill_fi2_slice0.py` (five sources,
  idempotent, run-level lineage — see coverage boundary below).
- **Canonical fixture**: `tests/integration/test_fi2_slice0_two_projects.py` — two projects, one account,
  6 assertions through production paths; found zero integration bugs.
- Gate at close: db-smoke green; single head; `make check` red ONLY on pre-existing attributed items
  (22-file ruff-format drift; 3 no-DB pre-existing incl. clue-design guards; 31 shared-DB pollution failures,
  byte-identical to baseline).

## Founder-ack items (surfaced in chat close-out, awaiting explicit ack)

1. C6 digest-only re-pin (v10/v22) forced by the FieldDef contract-delta.
2. `workspace_field_definition.research_scope` = NOT NULL DEFAULT 'project_neutral' (spec said nullable;
   ratified as §4-consistent — CHECK still permits relative).
3. `import_accounts` stays `@1` (spec §8.3 amended with ratification note).
4. **hq_geo dropped at mint on EVERY creation path** — `compliance/jurisdiction.py:310` (GDPR jurisdiction
   switch), target_lock, resolver prompts all read NULL. Needs owner/PR (H2 partially heals via sightings).
   Spec §11 item.
5. Backfilled dev DBs: historical M8D per-tool-call runs + scoring/tiering/committee runs UNBACKFILLED
   (launch-level only; live-written data complete). Phase-2 must not assume claim-lens completeness on
   backfilled data. Spec §11 item.
6. Future C6 text bump should teach propose_field@2 the reuse/research-scope rules.

## Slice-1 handoff (load-bearing — the read-layer/BFF implementer must know)

- **NEVER scope claim reads by `claim.workspace_id`** — CHECK forces NULL on public_footprint claims (silent
  vacuous filter). Scope via `entity_id IN (SELECT id FROM account_entity WHERE workspace_id=…)` or
  `WorkspaceScope.predicate()`. Recorded in spec §7.
- Lineage filtering is **species-conditional**: apply run_lineage only to `project_relative` fields (via
  `resolve_research_scope`); neutral fields serve from the canonical merge in every lens.
- `run_lineage.run_id` is a mixed id space; `kind` is advisory first-writer-wins — dispatch on `project_id`.
  Hot predicate = SQL subselect on `run_lineage_by_project (workspace_id, project_id)`.
- `projects_for_accounts` element 0 IS primaryProjectId (recorded policy). Membership-less accounts (seeds,
  client entity, legacy imports, review-band pending) are expected — render them.
- `account.scoring.*` is relative BY PREFIX (no migration for new scoring fields). `client.*` species always
  non-NULL; global rows may be NULL → always `resolve_research_scope`, never the raw column.
- No repo-wide "every run registered" guard exists (exemption classes need an allow-list) — slice-1 candidate.
- FI-1 ratification state: D-9 (Option B — chat via deepagent, chat now MVP scope → Lane D), D-10 (Lane E
  synthesis), R11 bridge = fast-follow. **D-4…D-7 still open** — gates the FRONTEND schema/adapter tasks only.

## Follow-ups triaged FOLLOW-UP by the final review (owners TBD)

split_merge membership restoration (M2.4); Sumble committee runtime fixture + shared-DB pollution
workspace-scoping sweep (test-debt PR); `project_id_for_run` + `_join_enqueuing_project` surviving_id/workspace
hardenings; preserve_unmapped default_research_scope one-liner; admit production-call-site project assertion
(M9.1 shape); seed_phase_run brand_id; `make format` as own commit; clue-design exclusion for two guards;
import-retry same-batch-different-project attribution drift note; replay-re-add hazard once remove-from-project
exists; domain-conflict-as-veto scoring idea.
