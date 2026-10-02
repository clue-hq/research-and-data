# Exa structured-output alias truncation — the short-alias cutover (2026-08-19)

Task 7 of the live-run repair wave. Closes the *upstream cause* left open by
`2026-08-19-exa-reserve-without-dispatch-settlement.md` ("Upstream cause not fixed. Exa truncated
the hex field aliases (~80 chars)"). No commit; no live-DB writes; services untouched.

## Root cause

`exa_field_alias` encoded a registry key as `f_` + hex of the ASCII key, so alias length was
`2 + 2×len(field_key)` — 52-74 characters for the resonance fields. The provider has to copy that
property name into its structured answer verbatim, and it does not reliably manage it.

Live evidence (read-only, `postgresql://clue:clue@localhost:5432/clue`), operation
`31b13c06-…` / job `04162ed5-…`, retained response
`ws_d98ab74cb0a943d4a483d1a3b4135ebd/abbb4354…`:

| requested alias | chars | returned key | chars | damage |
|---|---|---|---|---|
| `…7265736f6e616e63652e63756c74757265` (`account.resonance.culture`) | 52 | `…63756c7475` | 48 | dropped trailing `re` |
| `…627579696e675f63756c74757265` (`…buying_culture`) | 66 | `…627579696e675f63756c7475` | 62 | dropped trailing `re` |
| `…656d706c6f7965655f73656e74696d656e74` (`…employee_sentiment`) | 74 | `f_6163636f756e72616e63652e…` | 62 | dropped `t.reso` **mid-string** |

So it is not a hard length cap, it is transcription loss over a long meaningless token. **16 of the
20 `spend_outcome_unknown` attempts in the live DB are this one defect** (`structured output fields
do not match the request schema` ×14, `output content keys must be canonical Exa field aliases` ×2).

## The scheme

`deep_contract.py`:

* `exa_field_alias(key)` now returns `k_` + 8 base32 digits of a 40-bit `blake2s` digest —
  **`EXA_FIELD_ALIAS_CHARACTERS == 10`, independent of the field name**. The live bundle's copy
  burden goes from 192 characters to 30.
* `exa_field_aliases(field_keys)` is the bundle-level assignment: walks `sorted(keys)` and bumps a
  salt on an in-bundle digest collision, so the table depends only on membership, never on caller
  order. `_compile_output_schema` (the single generation site, account *and* contact) uses it.
* `legacy_exa_field_alias(key)` is the frozen v1 hex encoding, kept because persisted requests and
  retained responses still name their fields that way.

## Compatibility — resolution is per-request, not global

The alias table was always pinned in the request's own `systemPrompt` (`alias=field.key`, validated
against `outputSchema.properties` at construction). That pin is now the *resolver*:

* `exa_alias_field_keys(system_prompt=…, aliases=…)` recovers the exact table and proves it: a v1
  request is checked by decoding each hex alias, a v2 request by recompiling its bundle assignment.
  Mixed generations in one request are refused.
* `ExaDeepSearchRequest.field_key_by_alias` exposes it; every consumer that used to call the global
  `field_key_from_exa_alias(alias)` over `output_schema["properties"]` now reads the table —
  `normalize_exa_deep_snapshot`, the contact normalizer/target check, `normalize_exa_response`,
  `exa_contact_compiler`, `exa_deep_materialization`, `exa_contact_materialization`,
  `exa_entity_research_tools.bundle_field_keys` (which reads the raw stored `request_payload`, so it
  passes `systemPrompt` + `properties` straight into `exa_alias_field_keys`).
* `field_key_from_exa_alias` still decodes v1 and now *refuses* a v2 alias with a typed message.
  Standalone shape checks (`validate_exa_output_schema`, `ExaDeepOutput`) use
  `validate_exa_field_alias`, which keeps the full v1 round-trip and shape-checks v2.
* `_repair_uniquely_identifiable_exa_aliases` stays **v1-only** by design: salvaging a 10-character
  alias would mean prefix-matching 3-4 characters against ≤8 fields, i.e. mis-attributing a value.
* Request fingerprints change for new requests (they hash `wire_request_sha256`). That is expected;
  old operations keep their own fingerprints and stay replayable.

## Second defect found and fixed — normalization ordered by payload key order

`normalize_exa_deep_snapshot` iterated `response.output.content.items()`, so
`ExaDeepNormalization.citations` carried the *payload's* key order. E1 stores that value and
`exa_deep_materialization` recomputes it from the retained request/response, both read back out of
`jsonb`, **which does not preserve object key order** (confirmed on the live row: its `properties`
come back length-then-bytewise, not as written). Under v1 this never surfaced because hex encoding
is order-preserving, so sorted-by-alias == sorted-by-field-key. With hash aliases the two orders
diverge and the 5×3 harness failed with `stored Exa normalization differs from recomputation` →
`worker_error:ExaDeepSnapshotError` → every account suspended.

Fix: iterate in **sorted field-key order**. For any pre-existing v1 snapshot this is bit-identical
to the order it was stored in, so no stored normalization is invalidated.

## Does the live truncated response round-trip now?

**No, and it cannot** — proven by running the real stored request + the real retained bytes through
the current parser: the v1 request validates and resolves fine under the new contract, but the
response's keys are damaged (two lost `re`, one lost `t.reso`), so exact matching correctly refuses
it. The scheme *prevents* the corruption; it does not repair a corrupt artifact. That bundle stays
settled `spend_outcome_unknown` and its fields stay honest gaps.

## Tests

* `tests/resolvers/test_exa_deep_contract_a0.py` (+4): alias determinism/length/collision-freedom
  (asserts the live 66/52/74 → 10/10/10), a monkeypatched in-bundle digest collision resolving
  deterministically, the retained v1 fixture pair still parsing/exchanging/normalizing, and the two
  generations refusing to cross-resolve or mix.
* `tests/resolvers/test_exa_deep_wire_e0.py`: alias-shape test rewritten for the new scheme; the two
  repair tests re-pointed at v1 requests (`_as_legacy_alias_request`); new
  `test_a_corrupted_short_alias_fails_closed_and_is_never_repaired` and
  `test_normalization_orders_by_field_key_not_by_payload_key_order`.
* `tests/api/test_exa_deep_acquisition_e1.py`: `_as_legacy_alias_preflight` drives the whole durable
  path — dispatch, quarantine, replay and the **one-shot retained-response recovery** (slice-B
  ledger #10) — on a v1 request against the v1 response fixture.
* `tests/api/test_comprehensive_account_execution_db.py` (+1):
  `test_the_live_alias_truncation_budget_no_longer_corrupts_any_bundle`. `_TruncatingExaTransport`
  now models an *alias copy budget*; this drives it at `LIVE_ALIAS_CHAR_BUDGET = 62` (what the
  provider actually managed) and asserts the three live casualty fields complete. **Verified red**
  at HEAD's alias scheme with the same budget (`corrupted_field_keys` =
  `{operational_pain, resonance.attrition_signal, resonance.buying_culture, resonance.culture}`).
  The existing settlement test keeps corrupting via the default sub-alias-length budget.
* Fixtures: `tests/fixtures/providers/exa/search/{deep_request,deep_response}.json` regenerated to
  v2 (non-alias members proven byte-identical); the v1 pair retained **byte-identically** as
  `legacy_alias_deep_*.json` with their original checksums (`45a7ab41…`, `7cf7c23a…`) preserved in
  `checksums.json`. `tests/fixtures/contact_research/exa_c3/*` re-aliased + manifest re-hashed.

## Verification

Green: `tests/resolvers`, `tests/contact_research`,
`tests/integration/test_comprehensive_research_harness_db.py` (the 5×3 harness),
`tests/api/test_comprehensive_account_execution_db.py`, `tests/api/test_exa_deep_acquisition_e1.py`,
`tests/api/test_exa_deep_materialization_e2.py`, and the whole
`tests/api -k "exa or entity_research or account_deep or fi2 or comprehensive"` selection.
ruff + ruff-format clean on changed files; `uv run mypy` clean (732 files).

Whole-suite comparison: a clean solo run of `tests/api tests/fleet tests/durable` on this branch
fails 26; the same 17 files at HEAD (scratch worktree with **its own `uv sync`'d venv** — see the
trap below) fail 25, the identical set. The one difference,
`tests/fleet/test_b4_composed_run_db.py::test_composed_worker_drives_to_human_checkpoint_then_deep_quarantines`,
**passes in isolation on this branch**, so it is a suite-order flake, not a regression. No Exa,
comprehensive-execution, entity-research, account-deep, contact or durable test is in either set.

**Trap worth remembering:** `uv run --project <main-repo> --no-sync` from inside a scratch worktree
does *not* give you a baseline. The venv's `_editable_impl_*.pth` files point at the **main
workspace** paths, so you get HEAD's tests and fixtures against your **modified** source — which
manufactured ~15 phantom Exa failures and made HEAD look broken. Run `uv sync` inside the worktree
and set `VIRTUAL_ENV` to its own `.venv`. Also: never share one throwaway DB between two concurrent
pytest sessions — the lease/heartbeat/kill9 tests fail on contention and pollute the comparison.

Throwaway DBs `clue_alias_checks` and `clue_alias_checks_head` created, used, dropped; the scratch
worktree removed.

## Residuals

* No short-alias repair path. Deliberate (see above) — a corrupted 10-character alias fails closed.
* The 4 non-alias `spend_outcome_unknown` live attempts (duplicate citation URL, unretained
  grounding citation, dispatch-lease expiry) are untouched by this and remain their own questions.
* `EXA_FIELD_ALIAS_CHARACTERS` is 10 (40 bits). Global collisions across the whole registry are
  ~1e-8 and harmless (aliases only have to be unique inside one bundle, which is enforced); shrink
  further only with a reason.
