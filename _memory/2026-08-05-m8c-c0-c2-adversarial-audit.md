# 2026-08-05 — M8C C0–C2 adversarial audit

## Scope

- Reviewed commits `60cccbe`, `8bf4636`, and `bd98cbd` against the M8C roadmap and C0/C1/C2 acceptance records.
- Used isolated PostgreSQL databases on the branch-specific container; the older named synthetic acceptance database was absent, so a provenance-complete sealed discovery/tier fixture was recreated for New Jersey Brain and Spine.
- Made real Exa Search and Sumble REST v9 calls. No contact-channel reveal was requested.

## Live evidence

- Exa account compatibility canary: one ready account-subject operation, one attempt, one immutable snapshot and receipt, provider request id retained, 1.500 cents settled, and three account claims materialized. This is inherited M8B account evidence, not contact-targeted Exa proof; C3/C4 own that capability.
- Broad Sumble canary: one ready committee operation, Teams succeeded for 15 credits, People went pending then succeeded for 48 credits, two content-addressed snapshots, six contacts, 30 professional claims, and 18 committee/provenance claims.
- Fresh-process Sumble preparation reused the same operation and two snapshots. Counts remained one operation, three attempts, 63 charged credits, and 30 professional claims.
- C0 focused tests passed 7/7; C1/C2 focused tests passed 9/9; clean-database E1/E2/O2 compatibility tests passed 12/12; Alembic reported sole head `9e3afe93b8e1`.
- A first compatibility run on a previously seeded audit database failed because durable discovery artifact rows pointed at an earlier pytest temporary storage root. A clean isolated database passed; this was test-state contamination, not a C2 regression.

## Findings

1. C0 selection/intent authority is incomplete: neither schema requires the directive account to equal the selected account, and `ContactResearchIntent` is not mechanically derived from or validated against the selected receipt. Deliberately mismatched objects validate.
2. C0 does not satisfy the roadmap's full provider error-shape freeze. Fixtures cover success/pending/running/generic failed but not auth, insufficient-credit, rate-limit, server-error, or dedicated parser behavior; tests mainly assert strings and paths exist.
3. C0 policy caps are configuration only. The receipt accepts up to 64 contacts and 32 fields while defaults promise 3 and 8, and no production consumer enforces the policy yet.
4. C0 describes an Exa contact wire contract but points at account-deep request/response fixtures; exact-contact compilation is correctly deferred to C3, so the C0 ownership/status wording overstates what is frozen.
5. C1 has a live org-chart selection defect. `SumbleCommitteeSource` appends People candidates before Teams-only candidates and truncates to the committee cap. When People fills the cap, paid Teams-only people and their team relations are always discarded. The live canary paid 15 Teams credits for six strong profiles but materialized zero team-membership claims because none overlapped the six People rows.
6. C1 professional lineage is application-trusted, not substrate-enforced. The fact model accepts arbitrary non-empty committee operation/snapshot/request strings and tests pass with nonexistent ledger references. Returned-versus-modeled provenance is durable only in evidence text/value structure, not a typed claim field.
7. C2 exact-subject rows, snapshots, use receipts, indexes, merge behavior, crash quarantine, fresh-process replay tests, and single-head migration passed.
8. C2's reserve function says it runs under the reuse lock but does not acquire the lock itself; correctness depends on every caller composing two public functions in the right order. Exa claim-lineage validation also runs only when `source_operation_ref` is non-null, so an `exa_deep` claim with no lineage refs bypasses the exact-subject trigger.

## Disposition

C0 should be reopened. C1 should be reopened for the Teams/People selection bias and durable lineage validation. C2's core exit gates pass, but the lock composition and all-or-none Exa lineage checks should be hardened before C4 relies on them. Do not claim contact-targeted Exa live acceptance until C3/C4 exist.
