# Phase-3 pre-flight — M10 ∥ M11 ∥ M12 parallel kickoff

**Status:** in progress · **Branch:** `integration/phase3-preflight` (off `main@18d7fab`, alembic head `3df3b2f629fd`) · **Owner:** integration owner

This is the binding pre-flight that must land on the shared base **before** the three milestone
worktrees fork. It neutralises the shared surfaces that would otherwise recreate the historical
M2×M3 `0005/0006/0007` collision — this time on `core/`, the `claim` immutable guard, and the merge.
It is the Beat-0 "freeze the shared surface in one window" move, repeated for phase 3.

Companion analysis: the feasibility verdict and dependency graph (M10/M11/M12 are machine-isolated by
the import-linter independence contract; the only cross-sibling edges are SOFT, store/seam-mediated;
M12←M11 is a one-direction producer relationship M12 builds against fixtures). See the reconciled
kickoff plan in the session record.

## Decisions locked

- **D-OBJ (objection, GDPR Art. 21) → merge/substrate exclusion.** A data-subject objection is NOT a
  use-gate reason. M10.5 supersedes/tombstones the objected contact's `contact.facet.*` claims before
  the merge read; the existing "winners drawn from the non-superseded set" filter excludes them, so
  both M10's gate and M12's assembler inherit the exclusion with **no `UseGate.evaluate` widening and
  no merge-ranking change**. `UseGate.evaluate(claim)` stays per-claim.
- **D-EXP (retention age-out) → M10.5 tombstone-before-read.** `FreshnessState.EXPIRED` is the
  *retention* age-out — **distinct from STALE**: a sensitive `contact.facet` claim can be FRESH by
  its 90d field TTL yet EXPIRED by a 30d retention horizon (Doc D §4). M10.5 finds expired claims via
  `core.Freshness.due_for_age_out` and tombstones them before the next merge/handoff read, so
  `current_value` and M12 stop seeing them. **M12 does NOT special-case EXPIRED.**
- **Unification:** D-OBJ and D-EXP collapse to **one substrate mechanism** — M10.5 supersedes
  (objected | retention-expired) claims before read; nothing in `merge` ranking or M12 changes.

## Branch topology

```
main @18d7fab (head 3df3b2f629fd)
  └── integration/phase3-preflight        ← PF-0..PF-8 land here; reviewed → merged to main
         ├── m11/tier4-synthesis  (WS-A)   synthesis/ + NEW resolvers/exa, resolvers/parallel · ZERO migrations
         ├── m10/compliance       (WS-B)   compliance/ + config/policy.py extensions + side-tables
         └── m12/value-narrative  (WS-C)   narrative/ + claim_support/handoff tables
```

Integrate sequentially **M11 → M10 → M12** (§ integration order). Build in parallel.

## Pre-flight checklist (PF-0 … PF-8)

### PF-0 — Green the shared base · ✅ DONE (`d683690`)
Fixed 3 ruff lint + 2 format nits on the `3df3b2f629fd` merge migration and the AC-6 gate-routing
test, so the three branches inherit a green base and none re-touches the load-bearing merge migration
(a guaranteed 3-way conflict). Base now green: ruff, mypy (203 files), 11/11 contracts.

### PF-1 — ONE `core` contract-delta · ✅ DONE (`fdcaa64`)
Signature-only, frozen value types, no migration, no behavior. Freezes the seams all three build
against so none co-edits `core` after the fork.
- **(a)** `core/compliance.py` (NEW): `UseGate.evaluate(claim) -> UseDecision` protocol +
  `UseDecision{claim_id, usable_for_outreach, reason, policy_version}` + `is_outreach_promotable`.
  **Design decision (review):** placed in a NEW module, NOT `core/verification.py`, because
  `verification.py`'s docstring states the use-gate is "deliberately not here (Doc D §5 — separately
  measurable)". A separate module honours that and keeps the two gates independently spannable.
- **(b)** `is_outreach_promotable(claim, decision) -> bool` = `identity_binding is STRONG AND
  decision.usable_for_outreach`. Named apart from the existing accuracy-only
  `core.claim.is_promotable`/`can_be_promoted` (real collision). **Design decision (review):** takes
  `(claim, decision)`, NOT `(claim)` as the draft implied — the use verdict lives in M10's
  `use_decision` SIDE TABLE (PF-2), not on the claim row, so it must be passed in.
- **(c)** `core.enums.UseReason` = `allowed / sensitive_locked / use_class_disallowed_for_regime`.
  **Design decision (review):** NO `objected` member — per D-OBJ objection is a substrate exclusion,
  never a gate reason, so the gate never emits it.
- **(d)** `core.verification.Freshness`: promoted `AgeOutCandidate` + `due_for_age_out` from the M9.5
  impl onto the frozen seam (M10.5 reads them via `core`; `verification` is import-forbidden to
  `compliance`). `verification/freshness.py` now imports the type from `core`; the package
  re-exports it. **Design decision (review):** `record_re_research_candidates` is NOT promoted — it
  takes an `AsyncConnection` and would pull a DB dependency into the pure `core` kernel; it stays
  impl-only (M7 calls it via the concrete impl at `api`).
- **(e)** `core.handoff.AccountHandoff`: additive + defaulted `icp_spec_version`, `campaign_run_id`,
  `assembled_at`, `coverage_confidence`, `field_conflicts`. Added in `core` (not as M12 runtime
  extras) because the model is `frozen, extra="forbid"` and M12 must not edit `core`; M12's assembler
  sets the scope stamps.

### PF-2 — Make claim-provenance storage TOTAL side-tables · ☐ TODO (integration owner)
**Binding decision (overrides the M10 spec's "extend `claim` provenance / no new table" framing):**
EVERY M10 provenance addition AND the M12 narrative-support linkage go in SIDE TABLES keyed on
`claim_id` — the exact M9 pattern (`faithfulness_verdict`/`identity_binding_eval`/`conflict_flag`).
- M10: `use_decision{usable_for_outreach, reason, policy_version, evaluated_at}`,
  `lawful_basis_record{lawful_basis, lia_ref, third_party_collected, retention_until}`,
  `dsar_tombstone` marker, `outreach_objected` flag.
- M12: `claim_support{account_evidence_ids[], client_knowledge_ids[]}`.
- **Result:** no branch ALTERs `claim` or `CREATE OR REPLACE`s `claim_reject_immutable_update()`
  (two branches both replacing that plpgsql body is a collision `alembic merge` cannot reconcile).
  A use verdict is settable post-insert (a side-table row), which an immutable born-column would
  forbid anyway. **Escape hatch (avoid):** if a born-immutable claim column is ever truly needed,
  exactly ONE pre-flight migration owns the single guard `REPLACE`, other branches rebase, and a
  post-merge test asserts the guard lists every immutable column.

### PF-3 / PF-4 — The unified substrate exclusion (D-EXP + D-OBJ) · ☐ TODO (M1.2 + M10.5 seam owner)
Land on the base the mechanism that makes D-EXP and D-OBJ work, so M12 reads an already-correct merge:
- M10.5's tombstone sweep supersedes `(objected | retention-EXPIRED)` claims before merge read; the
  merge's non-superseded filter + `_is_eligible` already exclude them. **Preferred:** reuse the
  existing supersede mechanism (no `merge.py` ranking change). If a `dsar_tombstone` *table* is used
  instead of supersede, the merge READ query must LEFT-JOIN-exclude tombstoned claims (a small
  M1.2-owned change) — pick one and pin it.
- DSAR *erasure* (right-to-be-forgotten = redact/delete `value_json`, which is immutable) is a
  separate, harder M10.5 concern from mere exclusion; scope it explicitly, don't conflate with
  age-out/objection exclusion.
- Add the 40d-sensitive divergence fixture (FRESH by 90d TTL, EXPIRED by 30d retention) either way.

### PF-5 — Tombstone `extraction_method` = reuse `human` · ☐ TODO (record only)
M10 spec line 127 default; `ExtractionMethod.HUMAN` already exists — no `core`/DB-enum/parity change.

### PF-6 — Fix the tier-4 source-key mismatch in `claimstore/packs.py` · ☐ TODO (integration owner, M1-owned)
`account.operational_pain`/`account.strategic_moves` carry `tier_plan=("exa","parallel")` (packs.py
:220/:231) but the seeded tier-4 manifests are keyed `exa_deep`/`parallel_task` (provider `exa`/
`parallel` is a different column); `account.resonance.culture` (:244) already uses the correct keys.
Realign the two pain/moves rows to `("exa_deep","parallel_task")` **in the pre-flight commit** (so
`packs.py` leaves the feature-branch write set), else M11's resolvers never fire and M12 argues over
silently-empty claims. Also audit the other `"exa"` tier_plan entries (:121/:209/:254) — confirm an
`"exa"` search-resolver is separately registered, or those are latent mismatches too. Add an
integration test asserting a bound `exa_deep` resolver is reached for `account.operational_pain`.

### PF-7 — Split the `api` composition root by concern · ☐ TODO (integration owner)
Create `api/synthesis_wiring.py`, `api/compliance_wiring.py`, `api/narrative_wiring.py`, each
aggregated by a thin composition. Refactor `load_research_packs` (flat `await load_*` in
`api/composition.py:88-99`) to iterate a `RESEARCH_PACK_LOADERS` registry list — each milestone
appends its loader in its OWN wiring module, so three branches never co-edit the function body.
Freeze the verification-step ORDERING contract:
`pre_spend → resolve → corroboration → faithfulness (M9.3) → identity_binding (M9.4) → use_gate (M10.3)`.

### PF-8 — Tighten the personal-data firewall at the registry · ☐ TODO (M11-owned seed; freeze now)
`exa_deep` is `entity_scope=BOTH, yields=(…,"contact.facet")`; `parallel_task` is ALSO
`entity_scope=BOTH`. Tighten BOTH tier-4 synthesis manifests to `entity_scope=account` and drop
`exa_deep`'s `contact.facet` yield, so neither account-synthesis manifest is contact-capable. Guard
test asserts account-scope on every tier-4 synthesis manifest. (Contact-level personal synthesis
stays M10-governed.)

### Also pre-flight: freeze the M12←M5 retrieval seam · ☐ TODO (integration owner)
`stage0/client_kb.py` ships only `read_client_kb`/`read_client_kb_claims` — no similarity retrieval.
Freeze a thin `retrieve_client_knowledge(client_entity_id, query, kb_version) -> list[(client_knowledge_id, chunk)]`;
M12.1 stubs it over `read_client_kb_claims` + an in-memory relevance filter; the pgvector impl lands
later behind the same signature.

## Per-workspace ownership (must-not-touch is how collisions are prevented)

- **WS-A · M11:** owns `synthesis/` (M11.3 wiring/gating), NEW `resolvers/exa/` + `resolvers/parallel/`
  (the resolver classes + provider SDKs — must live under `resolvers/`, not `synthesis/`, per the
  forbidden-SDK contract), the `exa_deep`/`parallel_task` manifest rows. **ZERO migrations.** Must
  not touch `core/`, the `claim` DDL, `claimstore/packs.py` (PF-6 base), `compliance/`/`narrative/`,
  `merge.py`. Must not write any `contact.facet.*` / `entity_type=contact` claim.
- **WS-B · M10:** owns `compliance/`, `config/policy.py` EXTENSIONS (serialize M10.1→M10.4→M10.5
  within the one worktree — single 196-line module), the M10 side tables (hash-id migrations),
  `contact.jurisdiction` + shorter `contact.facet.*` TTL field rows. Must not touch `core/` (the
  UseGate seam + Freshness delta landed in PF-1), the `claim` immutable guard (verdicts are side
  tables), `merge.py` (D-EXP/D-OBJ is PF-3 base work), `synthesis/`/`narrative/`.
- **WS-C · M12:** owns `narrative/`, the `account.value_narrative` field-def (**MUST declare
  `reuse_scope=TENANT_PRIVATE`** + `identity.stamp_reuse` — `FieldClass.ACCOUNT` default is
  `PUBLIC_FOOTPRINT`; a client-tuned narrative leaking cross-tenant is the reuse-scope hazard; add a
  test), `claim_support` + `handoff_event` tables (hash-id migrations). Must not touch `core/handoff.py`
  (additive fields are PF-1), `merge.py`, `compliance/`/`synthesis/`. Must call **`is_outreach_promotable`**
  (never `Claim.is_promotable`) and read M10's `use_decision`; never re-gate.
- **Integration owner:** all PF base commits, the sequential `api`-root wiring, the deferred-backlog
  cluster (M9.1 AC-6 routing, M9.4 stamp, DSAR/retention sweep, `gather_scope` into M4.6, UseGate
  ordering, M9.6 regression-gate CLI), the `alembic merge` joins.

## Migration discipline

Hash revision ids; `down_revision = 3df3b2f629fd`; **M11 adds ZERO migrations** (manifest + field
rows are data). At integration, after merging each branch's code, `alembic merge` to one head; never
hand-renumber. Gate: `alembic heads`==1 + `make db-smoke` on a CLEAN per-branch throwaway DB. With
M11 at zero migrations the integration join is a **2-head M10+M12 merge** — the only multi-parent case
the repo has exercised (no 3-head precedent). During integration, run each branch's db-smoke on a
base that already contains the other's merged migrations (catches cross-sub-chain downgrade-order
assumptions).

## Integration / merge order — M11 → M10 → M12

1. **M11 first** — lowest blast radius (zero migrations, no core edit, disjoint `resolvers/`+`synthesis/`).
   Wire its tier-4 resolvers through `PreSpendGate.check` (closes M9.1 AC-6 for the tier-4 spend path).
   Makes the synthesized `account.*` claims real so M12 later argues over live data.
2. **M10 second** — ships the UseGate impl + the D-EXP/D-OBJ tombstone sweep M12 depends on. Register
   UseGate as a verification-layer member AFTER M9.4/M9.3 (the PF-7 order). Wire the DSAR/retention
   sweep (`due_for_age_out` → tombstone) and `ClientPolicy.gather_scope` into the M4.6 planner.
3. **M12 last** — soft-reads both siblings; on M13's critical path. Promotes against the real gate +
   real claims; keeps `AccountHandoff` + the assembler stable for M13.

## Residual risks (carry)

- D-EXP option (tombstone-before-read) makes the M10.5 sweep a runtime precondition for M12
  correctness — enforced only by the M11→M10→M12 ordering, no compile-time guard. A belt-and-braces
  `merge`-level EXPIRED exclusion (M1.2 touch) would remove the ordering dependency.
- The side-table decision (PF-2) must be socialised as BINDING to all three WS owners, or a branch
  quietly takes the escape-hatch born-column and reintroduces the immutable-guard collision.
- The `api`-root + deferred-backlog cluster is one sequential phase under one owner — budget it as its
  own work item, not "merge cleanup".
- DRY backlog (normalize_host ×3, reference_time ×2, decode_jsonb_scalar ×4-5, EqualityMode relocation)
  is deferred to a post-integration cleanup PR by the integration owner — NOT picked up ad hoc inside
  a feature branch (that reintroduces the divergence the independence contract prevents).
