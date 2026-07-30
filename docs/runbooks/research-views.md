# Structured research-view operations

**Applies to:** C7 account/contact research views, reference-only snapshots, evidence actions,
governed re-check, production handoff, and retained dossier aliases.

## Activation and rollback

All C7 capabilities and developer diagnostic admissions default off and are independent:

| Capability | Environment setting |
|---|---|
| canonical read/status routes and `get_research_view@1` | `CLUE_C7_RESEARCH_VIEW_READ_ENABLED` |
| snapshot composition and `compose_dossier@1` | `CLUE_C7_SNAPSHOT_COMPOSE_ENABLED` |
| evidence actions | `CLUE_C7_EVIDENCE_ACTIONS_ENABLED` |
| governed re-check and `recheck_research_view@1` | `CLUE_C7_RECHECK_ENABLED` |
| real production committee/handoff handler | `CLUE_C7_PRODUCTION_HANDOFF_ENABLED` |
| deprecated `/dossier` aliases | `CLUE_C7_LEGACY_DOSSIER_ALIAS_ENABLED` |
| developer governance shadow comparison admission | `CLUE_C7_GOVERNANCE_SHADOW_COMPARE_ENABLED` |
| optional workspace admission after a global flag | `CLUE_C7_WORKSPACE_CANARY_IDS` |

Enable in this order: shadow-compose internal fixtures; read routes; snapshots; evidence actions;
re-check for canaries; production handoff; legacy aliases only where measured demand exists. The
legacy alias requires its canonical read/compose capability too.

`CLUE_C7_WORKSPACE_CANARY_IDS` is a JSON array, for example
`["trial-workspace"]`. Empty means that a globally enabled capability is available to every
authorized workspace, which is convenient locally but is not the recommended first deployment.

`CLUE_C7_GOVERNANCE_SHADOW_COMPARE_ENABLED` defaults off and is intentionally not a route,
governance bypass, or raw-value switch. It reserves admission for a developer-only aggregate
candidate-versus-governed diagnostic. The comparator/report is not implemented yet, so enabling
the setting alone has no runtime effect. Any future consumer must keep denied values out of normal
API responses and remain subject to local-development and workspace-admission guards.

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

## Exa-first manual quality trial

This sequence evaluates the research output before spending time on scraping or HTTP.

### 1. Prepare and migrate

Use an isolated local PostgreSQL database. Do not point migration smoke or a trial at a shared
developer database.

```bash
export CLUE_DATABASE_URL='postgresql+asyncpg://clue:clue@localhost:5432/clue'
uv run alembic upgrade head
```

Run the normal project/account research path with its source policy restricted to Exa/Exa Deep and
with Firecrawl/Scrapling disabled. C7 does not provide an alternate acquisition runner: the trial
must persist identity, project/account runs, claims, derivation edges, verdicts, score claims,
committee references, and coverage through the normal governed subsystem. That is what makes the
read a real quality test rather than a fixture demo.

Find the exact persisted scope without selecting claim values:

```sql
SELECT pr.workspace_id, pr.project_id, pr.id AS project_run_id, pr.product_id,
       ar.id AS account_run_id, ar.entity_id AS account_entity_id, ar.status
FROM project_run pr
JOIN account_run ar ON ar.project_run_id = pr.id
ORDER BY pr.created_at DESC, ar.updated_at DESC;
```

For a contact trial, use a contact ID actually admitted by the account-run references:

```sql
SELECT ce.id AS contact_entity_id, ce.account_entity_id
FROM contact_entity ce
WHERE ce.workspace_id = :'workspace_id'
  AND ce.account_entity_id = :'account_entity_id'
  AND ce.merged_into IS NULL
ORDER BY ce.id;
```

### 2. Compose directly through production readers

No C7 HTTP flag is needed for this command. It performs no acquisition/model call and has no
fixture-reader fallback.

```bash
uv run python scripts/07_research_view_trial.py \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --project-run-id "$PROJECT_RUN_ID" \
  --subject-entity-id "$ACCOUNT_ID" \
  --subject-entity-type account \
  > /tmp/c7-exa-account.json
```

Repeat with `--subject-entity-type contact` and an admitted contact ID. Inspect:

- visible statement values, field keys, claim IDs, support IDs, and availability;
- confidence/timestamps plus evidence action kinds and provider labels, without exposing locators;
- fit components resolved through the score owner;
- committee role/persona, coverage decisions, execution status, and identity owner values;
- explicit `unresearched`, `product_score_missing`, restricted/redacted, and coverage-gap states;
- whether outreach-denied public facts remain displayable but never enter personalization.

If this output is weak, stop here and improve upstream research. The C7 reader must not generate
filler to make it appear complete.

### 3. Scraper comparison

Enable the approved scraper in the normal source policy, rerun additively, and execute the same
command. Compare the two JSON files by source hash, statement/support IDs, coverage counts,
conflicts, confidence, and evidence-provider/action changes. The second run should add or
supersede claims through normal append-only history; it must not overwrite evidence.

## Local API and Postman trial

Only after the direct output is worth evaluating through HTTP:

```bash
export CLUE_C7_RESEARCH_VIEW_READ_ENABLED=true
export CLUE_C7_WORKSPACE_CANARY_IDS='["'"$WORKSPACE_ID"'"]'
export CLUE_PROJECTIONS_AUTH_MODE=local_header
export CLUE_PROJECTIONS_HOST=127.0.0.1
export CLUE_PROJECTIONS_PORT=8000
uv run python -m clue_api.projections_main
```

The application fails startup if the C7.9 migration, field routes, production collaborators, or
recheck binding required by enabled flags are missing.

Initial request:

```http
GET /v1/projects/{project_id}/accounts/{account_id}/research-view
X-Workspace-Id: {workspace_id}
X-Actor: human
```

Repeat it and require the same `ETag` and `X-Research-Source-State-Sha256` when authority state has
not changed. Pass the response's owner-reference objects to:

```http
POST /v1/projects/{project_id}/research-view-owner-references:resolve
X-Workspace-Id: {workspace_id}
Content-Type: application/json
```

The batch body supplies the exact project run, subject ID/type, product, and up to 100 emitted
references. Forged, stale, cross-product, or foreign references return opaque not-found semantics.

Import `docs/runbooks/postman/c7-research-view.postman_collection.json`. Populate only its
collection variables; the checked-in collection contains no IDs, tokens, evidence locators, or
customer values. Enable snapshot, evidence, and recheck flags one at a time only after read quality
is accepted.

## Migration and deployment checks

C7's current Alembic head is `6a7f8eed5b23`. Before activation:

1. confirm `alembic heads` returns exactly that single head;
2. run head → base → head against a clean throwaway database;
3. run the C7 adversarial and DSAR node sets;
4. run the DB-enabled full suite.

Operational rollback is flag-based. Schema downgrade exists for development smoke only and is not
the production rollback mechanism because immutable receipts and history may already reference C7
types.
