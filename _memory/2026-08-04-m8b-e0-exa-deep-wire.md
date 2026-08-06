# 2026-08-04 — M8B E0 Exa Search Deep wire

## Scope and branch

- Branch: `codex/m8b-e0-exa-deep-wire`
- Parent roadmap: `docs/specs/M8B-exa-sumble-account-deep-integration-roadmap.md`, Slice E0.
- A2 is a parallel lane. E0 accepts plain bounded direction/query values and imports no A2 model,
  table or store.
- No migration, API composition edit, provider operation, live provider call or spend.

## Implemented

- Replaced the legacy Exa `type="neural"`, field-at-a-time unstructured highlight adapter with a
  deterministic Search Deep/Deep-Reasoning compiler.
- Added `ExaDeepFieldSpec` so the wire compiler receives an admitted registry field key plus its
  exact effective `value_schema`; no schema is guessed from `FieldDef.value_type`.
- Compiler enforces 1–8 unique fields, 1–50 results, 0–10 unique additional queries, bounded intent
  and prompts, canonical account target lock, a sorted closed output schema, text/highlights and
  non-streaming response.
- Directive-derived free text affects query strings only. It cannot enlarge the output schema.
- Null-on-evidence-miss preserves constrained schemas with `anyOf`; type-only schemas retain the A0
  frozen compact form. Input schemas are copied and not mutated.
- Additive response parsing validates exact requested/returned fields, request id, reported dollars,
  retained URLs and field grounding. Deprecated `resolvedSearchType`/`context` are ignored.
- Normalization emits provider-neutral candidates only for cited non-null values with a non-empty
  evidence highlight; when result text is present the span must occur in it. Missing spans are
  omitted; malformed/unsettleable successes do not become candidates.
- The temporary compatibility backend requires an explicit field schema, dispatches once with
  `retries=0`, and converts pre-dispatch schema/credential/request faults to typed `hard` failures.
  Transport ambiguity or malformed success after dispatch is `spend_unknown`.
- Updated Parallel's provider-independence test to construct the provider-neutral result directly;
  it no longer relies on Exa's removed legacy response shape.
- Added `docs/specs/M8B-E0-exa-deep-wire-acceptance.md` and marked E0 mechanically complete in M8B.

## Ownership retained for later slices

- E1: coalescing, request fingerprint, reservation, durable attempt, raw snapshot/artifact,
  request-id/cost receipt, settlement/reconciliation, quarantine, freshness and replay.
- E2: snapshot-backed materialization, account target-lock, field/source-plan authority,
  faithfulness/verification, claim provenance and production composition.
- A2: durable confirmed research directive and context binding.

## Verification

- Scoped Ruff format/check: pass.
- Whole-repo mypy: 501 source files, pass.
- Import-linter: 24 contracts, pass.
- Frozen A0 + E0 + Exa/Parallel + A1 + resolver-static DB suite: pass against isolated Postgres on
  port 55011; provider traffic used fixtures/doubles only.
- The disposable `clue-pg-roseau-e0` container was removed after verification.
- A full DB-backed pytest run reached completion. One E0 test literal initially triggered the
  repository's static secret-shape oracle; the literal was fixed and that static suite reran green.
  Eight unrelated baseline failures remain in agent tool-pin drift, logging capture, Recipe-1/fleet
  checkpoint fixtures, memory import boundary and toolbelt logging tests.
- Whole-repo Ruff format-check still reports 14 pre-existing unformatted files outside the E0 diff;
  the changed Python files pass scoped Ruff.

## Closing state

E0 is mechanically complete and mergeable independently of A2. No live-canary claim is made. The
next Exa slice is E1, which must consume this compiler without reintroducing resolver-time network
I/O or automatic retries.
