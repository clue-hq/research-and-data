# Structured research-view operations

**Applies to:** C7 account/contact research views, reference-only snapshots, evidence actions,
governed re-check, production handoff, and retained dossier aliases.

## Activation and rollback

All C7 capabilities default off and are independent:

| Capability | Environment setting |
|---|---|
| canonical read/status routes and `get_research_view@1` | `CLUE_C7_RESEARCH_VIEW_READ_ENABLED` |
| snapshot composition and `compose_dossier@1` | `CLUE_C7_SNAPSHOT_COMPOSE_ENABLED` |
| evidence actions | `CLUE_C7_EVIDENCE_ACTIONS_ENABLED` |
| governed re-check and `recheck_research_view@1` | `CLUE_C7_RECHECK_ENABLED` |
| real production committee/handoff handler | `CLUE_C7_PRODUCTION_HANDOFF_ENABLED` |
| deprecated `/dossier` aliases | `CLUE_C7_LEGACY_DOSSIER_ALIAS_ENABLED` |

Enable in this order: shadow-compose internal fixtures; read routes; snapshots; evidence actions;
re-check for canaries; production handoff; legacy aliases only where measured demand exists. The
legacy alias requires its canonical read/compose capability too.

Rollback sets the affected flag to `false` and restarts the process. Do not downgrade migrations,
delete receipts, rewrite claims, or restore a fake handoff handler. With production handoff off,
no HANDOFF handler is registered and the run fails closed at dispatch until re-enabled.

## Compose and read failures

- `404 research view not found`: verify workspace, project, latest project run, product pin,
  canonical subject, merge-survivor id, and account-run membership. The route intentionally gives
  not-found semantics for cross-tenant and wrong-subject-shape requests.
- `422 research_view_feature_disabled`: enable the exact capability flag. Do not bypass the tool
  precondition or call the snapshot store directly.
- `422` with `research_view_subject_not_found` or `research_view_snapshot_not_found`: the supplied
  ids do not form one authorized scope.
- `409 idempotency_conflict`: the caller reused an `Idempotency-Key` with different scope/body.
  Retry with the original request or a new key; never alter the existing receipt.
- A saved snapshot is not a copied dossier. It re-resolves reference rows under current claim,
  policy, retention, erasure, and artifact state.

## Stale sections and re-check

`research_view.section_stale` identifies affected section/item ids and bounded reason codes; it
contains no research body. Fetch the live view, inspect explicit stale/restricted/redacted states,
then invoke re-check with an `Idempotency-Key`.

Re-check may select section kinds and optionally request the existing governed research operation.
It cannot select a model/source, weaken evidence or policy gates, mutate claims, or run an
independent research loop. Replays must return the same report/snapshot/event set. Changed scope
under the same key is a conflict.

## Evidence denial

Evidence access reauthorizes the actor and exact workspace/project/subject/statement/claim/action
relation on every request. Common fail-closed reasons are:

- `action_not_found`, `action_mismatch`, `claim_mismatch`, `subject_mismatch`;
- `claim_unavailable` or `claim_erased`;
- `source_unavailable`, `artifact_unavailable`, or `artifact_erased`;
- policy/authorizer reason codes.

Responses contain an opaque, short-lived capability only. Storage keys, source locators, signed
URLs, spans, and bodies must never enter Postgres, receipts, events, or logs. C7 has no projection
body cache.

## DSAR and retention

Use the existing data-owner services: claim/derivation tombstoning, artifact erasure, legacy
rationale redaction, legacy `account_handoff.payload` purge, and C6 agent privacy purge. Verify the
10-surface executable map in `tests/fixtures/research_views/dsar_surface_map.json`.

After erasure:

1. direct personal current values are absent;
2. dependent derivations resolve redacted/unavailable;
3. faithfulness rationale and legacy handoff body are null;
4. evidence artifacts are erased/purged and old actions cannot renew access;
5. snapshots/re-checks/projections/events retain only nonrevealing references;
6. C6 history cannot replay an erased artifact and its isolated workspace is purged.

Reference/audit rows may remain only when they cannot resolve or reveal the erased body.

## Bounds and health checks

- Derivation resolver defaults: maximum depth 8 and maximum 128 nodes. Support edges are loaded
  once per breadth level; claims, audit state, TTLs, and conflicts are bulk-read.
- One 25-node/24-support regression is capped at seven SQL statements. A limit breach returns
  `dependency_depth_limit` or `dependency_node_limit`, never partial plausible prose.
- Detail pagination is stable and capped at 100 items; status pagination is capped at 100.
- Re-check section selection is bounded to valid view sections and writes additive rows only.
- Snapshot and event rows are reference-only; do not add a body cache to reduce latency.

## Migration and deployment checks

C7's current Alembic head is `677607ec1cd1`. Before activation:

1. confirm `alembic heads` returns exactly that single head;
2. run head → base → head against a clean throwaway database;
3. run the C7 adversarial and DSAR node sets;
4. run the DB-enabled full suite.

Operational rollback is flag-based. Schema downgrade exists for development smoke only and is not
the production rollback mechanism because immutable receipts and history may already reference C7
types.
