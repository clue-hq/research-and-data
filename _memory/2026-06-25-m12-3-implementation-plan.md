# 2026-06-25 — M12.3 (Output / handoff API — the boundary to the content layer) — plan

**Branch:** `m12/value-narrative` (M12.1 `eb972cf`, M12.2 `d5e0a59`/`fd44ff4`; alembic head
**`9666e86a6e9a`** = M12.2 `account_handoff` materialization). Spec: `docs/specs/M12-…§M12.3`.
Pre-flight: WS-C M12 owns `narrative/`, the **`handoff_event` table** (hash-id migration), must NOT
touch `core/handoff.py` / `merge.py` / `compliance` / `synthesis`. Read post-tombstone merge; call
`is_outreach_promotable` never `Claim.is_promotable`.

## Decisions
- **FastAPI IS added** (`fastapi` + `httpx` for TestClient) — substrate §12 table names FastAPI; the
  spec & AC describe HTTP GET endpoints; `api/README` designates `api/` as the FastAPI app layer.
  HTTP routes live at the **api composition root** (only place that may import `durable`+`narrative`).
- **Transport-agnostic core lives in `narrative/`** (a worker; may import core/config/obs +
  claimstore/identity/icp/sources + db; may NOT import `durable`). The campaign-run phase
  (readiness) + per-account readiness reach the service via an **injected `HandoffReadinessReader`
  seam** (production impl reads `durable` at api root — deferred-injection pattern, like M12.1/M12.2).
- **No write path:** GET-only router; outbox is one-directional (research→content). Test asserts no
  POST/PUT/PATCH/DELETE routes.
- **Verification health computed at ASSEMBLE time** over the UNFILTERED committee (`hand_members`) +
  narrative citations (the only place with the true strong-binding denominator — the served handoff
  committee is post-filter so ≈100%). Stored as additive defaulted `verification_health` on the
  M12-owned `AssembledHandoff` wrapper (NOT core). Deterministic → AC5 stays byte-stable.
- **Readiness signal:** materialized `account_handoff` row ⟹ ready (assembly reads verified claims).
  Per-account readiness (durable): `account_run.status=DONE AND sub_phase=CONTACTS_COMPLETE`
  ("M12-ready", per the enum docstring). Run-level: `campaign_run.phase=HANDOFF`.
- **Schema version:** `HANDOFF_SCHEMA_VERSION` on responses (header `X-Handoff-Schema-Version` +
  envelope field) — additive evolution keeps pinned consumers working (AC5-version).

## Files
### narrative/ (transport-agnostic)
- `handoff_events.py` — outbox: `HandoffEventStatus`(pending/delivered/failed, text+CHECK not a DB
  enum), `HandoffEvent`(emit payload: campaign_run_id, account_entity_id, icp_spec_version, icp_key,
  client_id, handoff_ref, schema_version), `HandoffEventRow`, `handoff_ref_for(...)`,
  `emit_handoff_event(conn,event)->bool` (idempotent ON CONFLICT(campaign_run,account,icp,icp_key) DO
  NOTHING; True=newly emitted), `list_handoff_events`, `get_handoff_event`, `mark_handoff_event`.
- `publisher.py` — `HandoffPublisher` Protocol (`async publish(event)`), `OutboxHandoffPublisher`
  (no-op push — the outbox row is the pull signal = durable default), `RecordingHandoffPublisher`
  (test/push-sim). D2 seam: webhook publisher = same Protocol, no schema/producer change (AC8).
- `readiness.py` — `RunReadiness`(campaign_run_id, client_id, phase: core.CampaignPhase, is_terminal),
  `AccountReadiness`(account_entity_id, is_ready: bool, status: str, sub_phase: str|None),
  `HandoffReadinessReader` Protocol (`run_readiness`, `ready_accounts`), `InMemoryHandoffReadinessReader`.
- `health.py` — `VerificationHealth`(value_narrative_total, value_narrative_judged_faithful,
  tier4_judge_pass_rate|None, committee_contact_claims_total, committee_strong_binding,
  strong_binding_share|None) + `compute_verification_health(profile_claims, committee_members,
  narrative, citations)` pure (Doc C §6).
- `service.py` — `HandoffService`: `get_handoff`, `list_handoffs`(+run_phase via readiness),
  `resolve_provenance`, `emit_ready_handoffs`(assemble+materialize+emit+publish, idempotent).
  Response models `ServedHandoff`/`HandoffSummary`/`HandoffListPage`. `HANDOFF_SCHEMA_VERSION="1.0"`.
  Errors `HandoffNotFoundError`. Emits per-object verification-health gauge to the obs sink (M13.4).
- `handoff_store.py` — add `list_handoffs_for_run(conn,*,client_id,campaign_run_id)->list[AssembledHandoff]`.
- `handoff.py` — add `verification_health` to `AssembledHandoff`; compute in `assemble()` over
  unfiltered `hand_members` + citations.
- `__init__.py` — export the new surface.

### api/ (composition root, FastAPI)
- `handoff_app.py` — `create_handoff_router(service, readiness_reader,*,tenant_resolver)` (3 GET
  endpoints, tenancy dep from `X-Client-Id` header → injectable real-auth seam, schema-version
  header, error→HTTP mapping), `create_handoff_app(...)` (mounts router + `db_lifespan`).
- `handoff_wiring.py` — `DurableHandoffReadinessReader` (reads `durable.get_campaign_run` +
  `account_run`), `build_handoff_service(...)`, `HandoffPhaseHandler`(phase=HANDOFF; emit on phase) +
  `register_handoff_phase_handler()`, production publisher choice.
- `__init__.py` — export.

### migration
- `<hash>_m12_3_handoff_event_outbox.py` (down_revision=`9666e86a6e9a`): `handoff_event` table,
  UNIQUE(campaign_run_id,account_entity_id,icp_spec_version,icp_key), idx (campaign_run_id,status) +
  (client_id); status text+CHECK; delivered_at iff delivered CHECK. Reversible.

### tests
- narrative: `test_handoff_events.py` (idempotency/list/status), `test_handoff_service.py`
  (get/list/provenance/readiness/health/tenant-isolation/schema-version/emit-idempotency/publisher-swap),
  `test_verification_health.py` (pure).
- api: `test_handoff_app.py` (TestClient: GET ok, cross-tenant 404, mid-run not-servable, no write
  routes, schema header, provenance), `test_handoff_wiring.py` (durable readiness + phase-handler emit).

### deps: `uv add fastapi httpx`

## AC mapping (M12.3 spec)
AC1 GET single handoff + resolvable provenance · AC2 list only ready (materialized); mid-run not
servable · AC3 durable idempotent event per account (outbox) on (run,account,icp) · AC4 no write
path · AC5 schema version, pinned consumer survives additive change · AC6 tenant-scoped (cross-tenant
denied) · AC7 verification-health per object · AC8 swap publisher pull→push no schema/producer change.

## Gate: ruff/format, mypy, import-linter (narrative stays clean — no durable/fastapi import; api may
import fastapi), pytest (rome DB on localhost:5432, container `clue-postgres`), db-smoke single head.

## STATUS — DONE (implemented + audited + green) 2026-06-25
Commits on `m12/value-narrative`: `18dfd03` (impl) + the audit-fix commit. Alembic head
**`ebba8073cc2a`** (m12_3 handoff_event outbox + the M12.2 account_handoff `tier` column + a
`(client_id, campaign_run_id)` list index — all in the one M12.3 migration). Gate green: ruff +
`format --check`, mypy 226 files, import-linter **11/11** (narrative transport-agnostic — no
durable/fastapi leak), db-smoke up→base→up single head. M12.3 suites (events/service/health/app/wiring)
+ narrative/api/durable/claimstore/verification all green.

### Adversarial audit (51-agent review→verify workflow) → 45 findings, 35 confirmed, actionable ones fixed
- **[HIGH] tier filter (spec deviation)** — the spec's list deliverable says "filterable by tier,
  persona, verification health"; only persona + pass-rate existed. FIXED: threaded `tier` through
  `AccountReadiness.tier` ← durable `account_run.tier` → emit `write_handoff(tier=…)` → an additive
  `account_handoff.tier` column (M12.3 migration ALTER) → `HandoffSummary.tier` → `list_handoffs(tier=…)`
  + `_passes_filters` + the HTTP `tier` query param. Tested (`test_list_filters_by_tier` + the wiring
  end-to-end tier assertion). `tier` is nullable (None when materialised outside the emit path).
- **[HIGH] list index** — added `account_handoff_client_run (client_id, campaign_run_id)` (the
  tenant-scoped list query filters both) in the M12.3 migration (the M12.2 single-col index is left).
- **[HIGH] AC5 forward-compat** — added `test_served_schema_is_forward_compatible_for_pinned_consumer`
  (an additive field is ignored by a pinned consumer reading by known keys). Kept the producer models
  `extra="forbid"` deliberately (AC5 is about the EXTERNAL consumer + the additive wire policy, not
  loosening our own validation — the verifier's "switch to extra=ignore" was declined with reasoning).
- **[HIGH] AC1 provenance depth** — strengthened the GET test to assert the provenance entry resolves
  to a real source_url/source_tier (not just key-present); the resolve-provenance tests already cover it.
- **[MED] AC2 mid-run** — added `test_list_excludes_unmaterialised_mid_run_account` (a run-member with
  no materialised handoff is absent from the list).
- **[NIT] DRY** — extracted `handoff_store._decode_payload` (was duplicated in read/list).

### Declined / non-issues (documented)
verification-health-uses-unfiltered-committee = intentional (honest denominator); independence-by-
absence = WRONG (import-linter IS the gate, 11/11); no-write-path-by-type = the GET-only router + the
no-write-route test is the structural AC4 guarantee; HandoffEventStatus drift = 2 tests already;
icp_spec_version-vs-version naming = pre-existing M12.2 convention (core handoff vs value_json).

## Cross-cutting note for the integration owner
M12.3 adds a read-only `durable.account_run.list_account_runs` (sanctioned repo helper) and an
additive `account_handoff.tier` column + `(client_id, campaign_run_id)` index in the M12.3 migration
(extends M12.2's table additively — never contradicts it). Collision-safe: M10/M11 touch neither
`account_run` readers nor `account_handoff`. M12 integrates last. fastapi+httpx added to deps
(substrate §12 names FastAPI; first HTTP surface in the repo).

## PAUSED after M12.3 (per the M12.2 cadence). Nothing pushed; awaiting go.
