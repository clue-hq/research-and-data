# 2026-08-03 — Tenant-local dynamic Client-KB fields

## Scope

- Implemented Part I of `Phase C Stage 0 — Tenant-Local Dynamic Client-KB Fields and Judged-Claim Verdict Attribution.md` on `platform/c8-context-card`.
- Part II (judged-claim verdict attribution) was deliberately not changed; pause requested after Part I.

## Delivered

- Added a separate immutable `workspace_field_definition` overlay, append-only retirement,
  materialization receipts, and versioned human-authored local readiness policy in Alembic revision
  `282b9c7278c2`.
- Added trusted-scope effective registry APIs and moved claim validation, merge freshness, and
  corroboration policy reads to the workspace-visible definition. Global seed/pack paths remain
  explicitly global-only.
- Dynamic `client.*` proposals now carry bounded schemas, candidate values, durable statement refs,
  and authority flags. Default mode is human confirmation; the optional safe-auto policy is
  supplemental-only, tenant-private, and records its policy actor/version.
- Promotion writes only the workspace overlay. The composition root reuses the artifact evidence
  reader and existing typed-value entailment judge to materialize one tenant-private claim. The
  operation is content-addressed, terminal-receipted, transaction-locked, and replay-safe.
- Split `CLIENT_BASELINE_FIELDS` from open effective Client-KB contents. Supplemental fields do not
  change baseline coverage; an explicit human policy can prospectively add local requirements.
- C8 project cards expose bounded extended field refs/counts, pending proposal refs/counts, retired
  status, and honest overflow omissions. A 200-field Postgres fixture stays under the card byte cap.
- Bumped the Head-of-ABM profile to v12, Stage-0 interview skill to v9, and Recipe 0 to v5 with
  `propose_field@2`. Exact v1 proposal tools remain installed only for historical recipe replay and
  cannot create/promote tenant-local dynamic fields or enter the current model surface.

## Verification

- New dynamic-field suite: 22 passed against isolated Postgres, including cross-workspace schemas,
  human/safe-auto authority, typed materialization, replay/version pinning, readiness separation,
  retirement, erasure/no-resurrection, governed reference-only tools, and 200-field card bounds.
- Broader affected registry/claim-store/Stage-0/proposal/projection/authority/recipe suite passed
  except two independently reproducible branch-baseline tests in untouched behavior:
  `test_recipe1_phase_spine_waits_and_resumes_without_reexecuting_gate` (checkpoint resume remains
  paused) and `test_one_conversation_is_one_source_however_its_values_earned_entry` (unordered
  claim selection can choose the same conversation source).
- Ruff and format checks passed for all touched Python files; mypy passed 463 source files; all 24
  import-linter contracts passed.
- Alembic has one head (`282b9c7278c2`); fresh isolated Postgres completed head -> parent -> head.
- The disposable `roseau-dckb-postgres-20260803` container was verified by exact name/port, stopped,
  and removed. No live model/provider canary was run; that would require separate spend authority.

## Close

Part I is implemented and locally verified. Preserve the unrelated working-tree edits and untracked
review/spec files. Do not begin Part II until the user resumes the work.
