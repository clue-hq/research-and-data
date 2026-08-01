# 2026-08-01 — PC-C8 task 1.1: `Stage0ProjectCard` + evidence port + size policy

Branch `platform/c8-context-card` (implemented in an isolated worktree off `3f82059`).
Spec: `docs/specs/PC-C8-stage0-context-card.md` §2–§5, §7, §11 task 1.1, §12 ACs 1/2/4/8/10.

## What landed

**`platform/projections/clue_projections/stage0.py`** (brownfield extension):
- `Stage0ProjectCard` + the §3 sub-models, all frozen/`extra="forbid"`, plus
  `canonical_bytes()` (sorted keys, `exclude_none`, `ensure_ascii=False`, no NaN) and
  `content_sha256()`. Media type `application/vnd.clue.stage0-project-card+json`.
- `compile_stage0_project_card(...)` — read-only, workspace-scoped, fail-closed on a foreign
  project (AC-10).
- `Stage0CardPolicy` / `STAGE0_CARD_POLICY_V1` = `stage0-card-policy-v1`: 40 statements (imported
  `MAX_PROJECT_STATEMENTS`, one number one rationale), 1,000 B/quote, 16,000 B aggregate quotes,
  256 B/KB brief, 4,000 B aggregate KB, 12 omissions, 24,000 B whole card. The version string is
  in the card bytes, so a policy change is a visible card change.
- `StatementEvidenceReader` protocol + `ResolvedQuote` / `ExcludedEvidence` (declared
  projection-side; the projection package may not import storage).
- `readiness_override_refs` / `effective_readiness_verdict` — the override join extracted from
  `stage0_readiness`, which now calls them (spec §4 "reuses, not re-derives").
- `encode_card_cursor` / `decode_card_cursor` — the opaque deterministic cursor the task-1.5
  inspection tools will accept. Omissions carry kind + count + cursor; never id lists, never tool
  names.

**`platform/api/clue_api/statement_evidence.py`** (new): `ArtifactStatementEvidenceReader` +
`resolve_statement_quotes` (the one implementation) + `StatementEvidenceCorrupt`.
`Stage0Trial._project_statements` (`stage0_trial.py`, the :1148–1220 region only) now calls it, so
ICP synthesis and the card can never disagree about what a statement says. Behaviour preserved:
missing/tombstoned evidence → `ExcludedEvidence`; a span that no longer hashes, or a
cross-workspace artifact, raises (`StatementEvidenceCorrupt` subclasses `RuntimeError`, so the
existing `_project_statements` tests still match).

**`clue_research/stage0/governed.py`**: added `read_readiness_decisions(conn, workspace_id,
project_id)` — the ledger read, ordered `(created_at, id)` — instead of copying
`_READINESS_COLUMNS`/`_readiness_row` into the projection. Task 1.5's readiness-history tool wants
the same function.

## Deviations from the spec (surfaced, not silent)

1. **The port declares a batch `resolve_quotes` beside the spec's single `resolve_quote`.** Purely
   additive — both are in the protocol and must agree (tested). The compiler uses the batch form so
   one card costs one connection and one body cache instead of 40 of each.
2. **The 24,000 B whole-card cap is enforced by construction, not by an assert.** The §3.1
   per-dimension caps do *not* by themselves bound the serialized card: 40 statements × ~250 B of
   envelope + a 16,000 B quote budget already exceeds 24,000 (the spec's arithmetic assumed a
   ~120 B envelope). The compiler therefore sheds the oldest included statement — then, if still
   over, the last Client-KB field — recounting `omissions` each round, until the canonical bytes
   fit. `Stage0CardTooLarge` remains for the genuine-bug case (nothing left to drop).
3. **Two extra typed omission kinds** beyond the three in the §3 example:
   `client_knowledge_over_cap` and `omissions_truncated` (the §3.1 table requires both behaviours
   but names no kinds).
4. **`readiness_spec_version` is a compiler parameter** (default: the workspace's newest
   `readiness_spec_revision`). A projection cannot know which policy hash the caller is running.
5. **Lineage-current ICP rule**: with no confirmed ICP, a decision that pinned none is current;
   once any ICP is confirmed, only decisions pinning a confirmed `(key, version)` are. Documented
   at `_lineage_is_current`.
6. **Confirmed-ICP scope**: active `icp_spec` rows for the workspace whose `product_id` is NULL or
   equals the project's confirmed product.

## Tests

- `tests/projections/test_stage0_card.py` (19) — determinism + policy-version-in-bytes; the AC-1
  breadth fixture (60 statements, max quotes, oversized KB → ≤24,000 B with correct omissions); the
  no-raw-row shape guard; every §3.1 cap and its overflow (per-quote UTF-8 truncation, aggregate
  quotes, per-KB brief, aggregate KB, omission collapse); dedup→supersession→newest-first + cursor;
  unmapped counting; missing evidence surfaced; latest-authoritative-per-gate; agent-authored row
  never shown; stale lineage → `not_evaluated_for_current_lineage`; override applied; ICP refs +
  caller-supplied booleans; unconfirmed product; cross-workspace raises.
- `tests/api/test_c8_statement_evidence.py` (6) — verbatim span (AC-4), erasure → exclusion,
  hash mismatch raises, cross-workspace raises, synthesis-and-card-agree (the DRY seam), card
  through the production reader + sha stable across freshly constructed objects (AC-8's
  restart half, approximated).

**Fixture gotcha for later slices:** inside one rolled-back transaction every row shares the same
`now()`, so `created_at` ties and `(created_at, id)` ordering is *not* insertion order. Tests that
care about "newest" must read the durable order first and speak in it (both suites do).

## Verification (with `CLUE_DATABASE_URL` from the workspace `.env`)
`tests/projections` · `tests/stage0` · `tests/api` · `tests/agents` · `tests/clue_trial` ·
`tests/test_{package_layout,structure_guards,dependency_contracts,seams,beat0_contracts}.py` —
green. `mypy` clean (455 files). `lint-imports` 24/24. `ruff check`/`format` clean on every touched
file. Without a DSN the new DB-gated tests skip cleanly.

**Pre-existing failure on this branch, NOT caused by this work** (reproduced with the change
stashed): `tests/api/test_agent_runtime_wiring_db.py::test_delegation_is_durable_before_fresh_
child_wake_and_rolls_up_reference_result` — `AgentCatalogError: tool 'evaluate_stage0_readiness@1'
schema digest changed`. A third one beyond the two the 1.0 note records.

## Handoff notes
- Task 1.3 wires `project_card_ref` into the constitution and `ProjectLayerSource`; the compiler is
  importable and tested but **nothing calls it in production yet**.
- Task 1.5's inspection tools should decode omission cursors with `decode_card_cursor` and read the
  ledger with `read_readiness_decisions`; its DSAR reverse bindings enumerate exactly
  `card.interview.current_effective_statements[*].statement_id`.
