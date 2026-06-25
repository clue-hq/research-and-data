# Topic note — Integrating M10 + M11 + M12 (the three-way join)

**Date:** 2026-06-25 · **Context:** advisory analysis (no code changed). M11 is on `m11/tier4-synthesis`
(`52e461c`); M10 and M12 are being built in separate worktrees off the same frozen preflight base
(`integration/phase3-preflight`).

## What "integration" actually is here
Not "merge three branches." It is: compose three independent packages at the **one import-linter-exempt
seam** (`api/`) and **prove the substrate's safety bet end-to-end** — the part each isolated branch
*could not* build because the independence contract forbids the cross-package wiring. PF-7 already
de-risked the *code seam* (three own `api/*_wiring.py` files; append-only `RESEARCH_PACK_LOADERS`; frozen
`VERIFICATION_GATE_ORDER` with `use_gate` last). It did **nothing** for migrations or the runtime spine.

## Sequencing (data-flow, NOT milestone number)
Produce → govern → read. **M12 lands LAST** regardless: it is the pure reader at the boundary and the
only branch that touches frozen `core` (the deferred M9.2 `EqualityMode` relocation) and shared
`api/__init__.py`. M11 (producer, already landed, 0 migrations) and M10 (the gate + governance layer)
feed the substrate/verification; M12 reads the post-judge, post-tombstone, use-gated merge.
Migration-merge order is independent of code order: a **2-head `alembic merge`** of M10's head + M12's
head (M11 contributes none) → single head → `make db-smoke`.

## Verified gap: the runtime spine does not exist yet
No `CampaignPhase.VERIFICATION` handler, no `HANDOFF` handler, no `HandoffAssembler` in `src/` — only
`DEEP` is registered, and `DEEP` only resolves/spends, leaving every tier-4 claim `unverified`. Because
`merge_claims` defaults `require_verified_tier4=True`, `current_value` returns **EMPTY** for every
synthesis field until something invokes the judge and promotes. So the worst failure is **silent**
(blank Output-2/Output-4, judge never runs) — not a crash.

## The most important part (sharpened by adversarial review)
Three layers, in this priority:
1. **Hard preconditions for any run to exist:** single `alembic head` + green `make db-smoke`
   (M10+M12 both add migrations off the same base — the M2/M3 collision scenario); and import-linter
   **11/11 KEPT** on the merged tree (the structural guarantee the whole parallel strategy rests on).
2. **The load-bearing causal invariant:** the **M10.5 retention/objection tombstone sweep must run
   BEFORE every merge read** (`core.Freshness.due_for_age_out` → tombstone EXPIRED + `outreach_objected`).
   This closes the *documented live bug* `[M9.5×M1.2/M10.5]`: `RetentionTtls.sensitive_claim_ttl`=30d <
   `FreshnessTtls.contact.facet`=90d, so a 40-day sensitive facet is EXPIRED-to-retention but FRESH-to-
   merge → it WINS `current_value` and crosses the handoff unless tombstoned first. M12 is built to NOT
   special-case EXPIRED (PF-1 D-EXP) **on the assumption this sweep runs first** — if unwired, the
   assumption is false and ungoverned personal data reaches the content layer (a lawful-basis/Art.21
   breach, the architecture's one named real failure).
3. **The detector:** the end-to-end NEGATIVE proof (fabricated tier-4 → absent; weak-binding → absent;
   sensitive → not outreach-promotable under any posture; objected/erased/expired → tombstoned & absent).
   It only confirms (1)+(2) composed correctly; it does not *cause* correctness.

## Progress (integration branch `integration/m10-m11-m12`, PR #23)
- **DONE — merge + single alembic head + green gate** (commits `c26b06e`/`da6bb89`/`d3f9b27` merges,
  `8ff0117` alembic merge `05f66cc526ae`). `make check` green, import-linter 11/11, 1765 passed.
- **DONE — M10 compliance pack-loader wiring** (`086baf0`): `register_compliance_wiring` appends
  `load_compliance_pack`; three milestone wirings exported from `api`.
- **DONE — `CampaignPhase.VERIFICATION` handler** (the keystone): `api/verification/{handler,composition}.py`
  + 11 hermetic tests. Drives corroboration(M9.2)→faithfulness(M9.3)→use_gate(M10.3 **last**) over each
  high-tier account's claims, per-account isolated, records per-field `record_synthesis_health`.
  `register_verification_phase_handler` registers it into the M7 phase registry. **Production v1 sources
  account entities only** (account-level synthesis → `current_value` non-empty); the handler fully drives
  the use-gate leg over `contact.facet.*` claims (tested with fakes) — the immediate follow-on is sourcing
  committee *contact* entities into the loader (needs a contacts-under-account reader) + per-client UseGate.
  1777 passed / 14 skipped / 0 failed on a pristine DB.

## The deferred-wiring checklist (remaining — all at the api root)
- Contact-entity sourcing into the VERIFICATION loader + per-client `UseGateImpl` (lights up the use-gate
  leg in production); the handler already supports it.
- `synthesis.guard_synthesis_resolution` pre-resolution call site is a DEEP-phase concern (the resolve
  step), not VERIFICATION; wire it where M8 resolves tier-4 fields.
- `PreSpendGate.check` routing on the tier-4 spend path (exa_deep/parallel_task) + the AC-6 lint test
  (`[M9.1×M4/M8/M11]`).
- Inject `UseGate` impl into the `use_gate` slot; append M10 pack loader (`contact.jurisdiction` + short
  `contact.facet.*` TTLs). Promote `due_for_age_out`/`record_re_research_candidates`/`AgeOutCandidate`
  onto frozen `core.Freshness` so compliance/durable can call across the independence contract.
- `HANDOFF` handler + `HandoffAssembler` (pure fn over `current_value` + provenance_index + M10
  `use_decision` side table); filter committee hooks with `core.compliance.is_outreach_promotable`,
  **never** `Claim.is_promotable`; register `account.value_narrative` as `reuse_scope=TENANT_PRIVATE`
  + `identity.stamp_reuse`; set PF-1 additive `AccountHandoff` stamps.
- Born identity_binding = `verification.classify_binding` via `production_binding_classifier` into
  M8.4/M8.5 (`[M9.4×M8.4/M8.5]`); add `answering_model` column to `faithfulness_verdict`
  (`[M9.3×M12]`); land the M1.2 conflict-equality (`equality_mode`) fix before M12 reads conflict flags
  (`[M9.2×M1.2]`); pick ONE strong-binding metric surface (`[M9.4×M13.4]`); add M9.6 golden rows for the
  synthesis fields + wire the enforced regression CLI.
- Reconcile the `exa_deep` `entity_scope=BOTH` binding (M11 account-only firewall returns `[]` for
  contacts — safe; if M10 adds a contact-facet synth resolver on the same key, reconcile bind order).
- `api/__init__.py` export-list 2-way reconcile (M10 abstains; M12 adds handoff/narrative exports);
  keep M11's filled `synthesis_wiring.py` (M10/M12 carry stale-scaffold phantom diffs of it).

## Post-integration (scheduled, NOT mid-merge — would reintroduce the divergence the contract prevents)
DRY consolidations now legal once on one tree: `normalize_host` ×3, `reference_time` ×2,
`decode_jsonb_scalar` ×4–5, `ACCOUNT_SYNTHESIS_CLASSES` vs resolver `_ACCOUNT_SYNTHESIS_CLASSES`;
source `conflict_tier_threshold` from one `config/schema.py` constant.

> Caveat: specific migration revision hashes for M10/M12 are NOT visible from the M11 worktree — verify
> on the merged tree. The *structural* facts (M11=0 migrations; M10/M12 each branch off the same base →
> 2-head merge) are sound from the specs + conventions.
