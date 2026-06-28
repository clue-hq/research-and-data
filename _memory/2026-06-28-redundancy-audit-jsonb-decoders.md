# 2026-06-28 — Redundancy audit cleanup: jsonb decoders (#1 + #2)

Continuing the `.context/redundancy-audit-report.md` sweep (see also
[[2026-06-28-redundancy-audit-cost-coercion]], [[2026-06-28-redundancy-audit-connfactory]]).
#1+#2 = the hand-rolled jsonb decoder copies. Pure dedup (no behaviour change), with two strict
robustness widenings that are supersets of the old behaviour.

## The redundancy
Two distinct decode needs, each reimplemented per package under the import-independence contract:
- **structured columns** (object/array) — `core.decode_jsonb` already existed for this, but most
  readers shipped a local copy. `durable/budget_event.py` was the one already-migrated reference.
- **bare-scalar columns** (`claim.value_json`, where a decoded `"robotics"` *is* the value, not JSON
  text) — needs a **bytes-only** guard; `core` had no such sibling, so it was hand-written too.
  (Confirmed empirically: `parse_value_json("robotics")` raises — a bare scalar str must NOT be
  re-parsed, which is exactly why structured `decode_jsonb` is wrong for these columns.)

## Fix (in `core/factories.py` + exported from `core/__init__.py`)
1. Added `decode_jsonb_scalar(raw)` — the bytes-only sibling of `decode_jsonb` (parses
   `bytes`/`bytearray`, passes a decoded `str`/`int`/`dict`/`None` straight through).
2. Widened `decode_jsonb`'s guard `(str, bytes)` → `(str, bytes, bytearray)` and `parse_value_json`'s
   param type to `str | bytes | bytearray` (pydantic `validate_json` already accepts bytearray) —
   closes a latent bytearray gap the local copies had each patched independently.

### Sites routed to `decode_jsonb_scalar` (true scalar — bytes-only preserved, zero behaviour change)
- `claimstore/claims.py` (deleted local `_decode_jsonb`; `value_json` + `discovery_provenance`)
- `verification/eval_harness.py` (deleted local `_decode_jsonb`; dropped its `# type: ignore`)
- `verification/golden.py` (collapsed the inline `isinstance(...) else parse_value_json(...)`)
- `verification/identity_binding.py` — `signals` (was bytes-only `json.loads`)

### Sites routed to `decode_jsonb` (structured — str+bytes)
- `identity/entities.py` (deleted local `_decode_jsonb`, 3 call sites) **+ `identity/resolve.py`**,
  which *imported* `entities._decode_jsonb` — the audit missed this cross-module use; repointed to
  `core.decode_jsonb` (2 call sites). Must-fix: deleting the entities helper would otherwise break
  resolve's import.
- `durable/account_run.py`, `durable/campaign_run.py` (deleted local bytes-only `_decode_jsonb`;
  widened to str+bytes — a strict superset, asyncpg passthrough path unchanged)
- `narrative/support.py` `_decode_list`, `narrative/policy.py` `_parse_field_relevance` — both kept
  **fail-soft** (now `try: decode_jsonb(...) except ValueError`; pydantic `ValidationError ⊂
  ValueError`, verified). `import json` removed from policy.py (no longer used).
- `narrative/handoff_store.py` `_decode_payload`, `compliance/use_gate.py` `_as_object`/`_as_array`
  (fail-loud preserved). `import json` removed from use_gate.py.
- `verification/identity_binding.py` — `identifier_set` in `load_binding_policy` (was str+bytes
  `json.loads`). **Audit-undercount addition** (same finding; #2's list didn't enumerate it).

Net **−8 lines** counting the +25 new test lines; src alone is solidly negative (deleted ~7 local
helper defs/inline guards). `import json` stays in support/handoff_store/identity_binding (still used
by `json.dumps` on the write path).

## Tests
`tests/test_core_helpers.py` — `decode_jsonb` (passthrough of decoded object/array/None; parses
str/bytes/**bytearray**) and `decode_jsonb_scalar` (never re-parses a decoded scalar str; only
bytes/bytearray parsed). Pinned `test_parse_field_relevance_is_fail_soft` still green.

## Verification
`make lint typecheck contracts` green (import-linter **11/11 kept** — all new imports are from the
universally-importable `core` seam). `make test` (no DB) **1112 passed / 782 skipped**. Ran the
DB-gated tests for every touched module against a live local Postgres (head = `15b6b816abe4`):
`claimstore durable identity verification narrative compliance` → **732 passed / 1 skipped**, so the
real write→read→decode round-trips are exercised, not just the helper unit tests.

## Audit backlog status
- **#1 + #2** jsonb decoders: DONE this session. Resolves the CLAUDE.md **[M9.6 DRY]** "bytes-only
  jsonb scalar decoder written a 4th/5th time" item (it undercounted: ~11 sites, not 4–5, plus the
  resolve.py importer and the identity_binding identifier_set copy).
- Remaining `core`-primitives batch: #3 `utc_now`, #4 `clamp_unit`, #5 `normalize_host`,
  #6 `reference_time`, #7 `parse_json_object`, #9 enum coercion (contract-delta work).
