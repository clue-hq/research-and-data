# FI-4 Slice 3 — Granular Truth: Path-B Events, Exa Fields, LLM Extractor, Honest Checklist

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every onboarding-checklist tick maps 1:1 to a real emitted recon event (REQ-08 verbatim): per-field in-flight events inside `reverse_profile`, two new Exa-search (tier-3) fields `client.competitor`/`client.buyer_profile`, the production LLM claim extractor so recon stops drafting zero facts, and the frontend's four ratified D-6 groups derived purely from those events.

**Architecture:** Per-field events ride the existing `run_event` outbox under a new named `payload.kind`, written by an injected emitter that uses an *autonomous* connection in production (the `DbSourceCallObserver`/pre-spend-gate precedent) and falls back to the lane connection when no separate factory is provided (keeps every existing test-harness conn-factory shape deadlock-free). The extractor and the Exa resolver are composition-root modules beside `claim_entailment.py`, injected `LLMGateway`, self-validating (drop, never raise). The frontend group mapping is data in the repository layer; the reduction is a pure model function; the setup transport finally gets its missing repository seam.

**Tech Stack:** Python 3.12 / SQLAlchemy async / Alembic (no migration needed) / pytest; Next.js App Router / TypeScript / Zod / `node:test` via `tsx`.

## Global Constraints

- Backend gate: `make check` (or at minimum: the stage0 + auth + api setup suites, `make lint`, mypy). Frontend gate: `npm run design-system:build && npm run lint && npm run build && npm test` in `apps/frontend/`.
- **No fake progress** (founder-ratified twice): every tick maps to a durable backend event; timers never advance lifecycle.
- **Visual freeze**: `components/setup-screen.tsx`, `onboarding.module.css`, and all imported screens are untouched. Only integration-owned files change (`live-setup-screen.tsx`, `model/setup-items.ts`, `data/*`, hooks).
- **Tier ceiling**: recon pre-confirmation is tier ≤3. Exa *search* only; `exa_deep` (tier 4) is forbidden here.
- **Discovery doctrine**: `client.buyer_profile`/`client.competitor` produce claims only — no `insert_account_entity` anywhere on the resolver path.
- **Tier-3 claim legality** (`clue_core/claim.py:193-208`): never `LLM_SYNTHESIS` at tier ≤3; `API`/`SCRAPE` require non-empty `source_url`.
- Claims with ungrounded spans or wrong-shaped values must be **dropped by the producer**, never allowed to escape (an escape = `AdaptError`/`ValueSchemaError` = whole-lane FAILED + savepoint rollback).
- Commits: local only, never push, no AI attribution, well-scoped messages.
- New migrations (none planned): hash revision ids off head `da5f3fe5a90f`.
- Alignment: `docs/specs/FI-onboarding-contract-gap-review.md` §9 ratifications (D-5 Path B, D-6 four groups, brand-kit dummy, Exa search not deep).

## Decisions taken by this plan (flagged to founder in the presentation, none blocking)

1. **Checklist geometry**: 5 rows (4 groups + brand-kit dummy). The frozen CSS grows naturally past its 212px `min-height` as rows complete — accepting that growth is the *only* option requiring zero frozen-file edits. Approved design never rendered its terminal state.
2. **Checklist copy**: group labels/details below are integration-authored data pending founder/co-founder review; swap is a one-file data edit.
3. **Fixture theatre preserved**: fixture mode keeps the co-founder's static walkthrough exactly (standing ruling, enforced twice). The new fixture event-stream source is fully built and test-driven; flipping dev mode to live motion is a one-line change offered to the founder, not made.
4. **Value shapes**: one claim per Exa record — `client.competitor` value `{"name": str, "domain"?: str}`, `client.buyer_profile` value `{"persona": str, "segment"?: str}` (object claims, own span + own source_url each; honest per-record grounding; `client.customer`'s single-list-claim shape doesn't fit independently-sourced records).
5. **Extractor LLM cost**: observable via `llm.gateway_call` spans, **not** charged to the 5¢/100¢ envelopes (no route exists without a frozen-core contract-delta; recorded residual, same posture as the M9.1 Lane-E items).
6. **Readiness denominators shift 9→11** (`DEEP_SPEND` 5-of-9 → 6-of-11): accepted; readiness gates are project-kickoff scope, not onboarding. Affected test literals updated.
7. **Per-field `failed` carries no reason string** (avoids inheriting the B-3 raw-classname defect); lane-level failure_code remains the diagnostic.

---

### Task 1: Event vocabulary — named kinds + field-progress status enum

**Files:**
- Modify: `subsystems/research/clue_research/durable/run_events.py` (add two constants near `NARRATIVE_EMIT_SKIPPED_KEY`, ~line 73)
- Modify: `subsystems/research/clue_research/stage0/types.py` (add `FieldProgressStatus`)
- Modify: `platform/api/clue_api/stage0_tools.py:103-123` (`_emit_recon_transition` uses the named constant)
- Test: `tests/stage0/test_stage0_static.py` (new test), `tests/stage0/test_phase_c4_governed.py` (existing event test must stay green)

**Interfaces:**
- Produces: `RECON_TRANSITION_KIND = "stage0.recon.transition"`, `RECON_FIELD_PROGRESS_KIND = "stage0.recon.field"` (in `run_events.py`); `class FieldProgressStatus(StrEnum): STARTED="started"; RESOLVED="resolved"; EMPTY="empty"; FAILED="failed"` (in `stage0/types.py`).

- [ ] **Step 1: Failing test** — in `tests/stage0/test_stage0_static.py`:
```python
def test_recon_event_kinds_are_named_constants() -> None:
    from clue_research.durable.run_events import RECON_FIELD_PROGRESS_KIND, RECON_TRANSITION_KIND
    from clue_research.stage0.types import FieldProgressStatus

    assert RECON_TRANSITION_KIND == "stage0.recon.transition"
    assert RECON_FIELD_PROGRESS_KIND == "stage0.recon.field"
    assert {s.value for s in FieldProgressStatus} == {"started", "resolved", "empty", "failed"}
```
- [ ] **Step 2:** `uv run pytest tests/stage0/test_stage0_static.py -k named_constants -x` → FAIL (ImportError).
- [ ] **Step 3:** Add the constants (with a comment noting `RECON_TRANSITION_KIND` names the previously-unnamed FI-4 B-4 discriminator) and the enum; switch `_emit_recon_transition`'s literal to `RECON_TRANSITION_KIND`.
- [ ] **Step 4:** Run the new test + `uv run pytest tests/stage0/test_phase_c4_governed.py -k evented -x` → PASS.
- [ ] **Step 5:** Commit `feat(stage0): name recon event kinds; add FieldProgressStatus vocabulary`.

---

### Task 2: Per-field emission inside `reverse_profile` (D-5 Path B core)

**Files:**
- Modify: `subsystems/research/clue_research/stage0/client_kb.py` (field loop L221-256, signature L131-143)
- Create: `platform/api/clue_api/stage0_field_events.py`
- Test: `tests/stage0/test_reverse_profile.py` (new tests), `tests/api/test_stage0_field_events_db.py` (new file)

**Interfaces:**
- Consumes: `FieldProgressStatus`, `RECON_FIELD_PROGRESS_KIND`, `emit_run_event` (Task 1).
- Produces:
  - `reverse_profile(..., on_field_progress: FieldProgress | None = None)` where `FieldProgress = Callable[[AsyncConnection, str, FieldProgressStatus], Awaitable[None]]` — receives the lane conn (so a factory-less emitter can write same-transaction), the field_key, the status.
  - `class ReconFieldProgressEmitter` in `stage0_field_events.py`:
    ```python
    class ReconFieldProgressEmitter:
        """Per-field recon progress → run_event outbox.

        With conn_factory (production: clue_db.transaction) events commit on an
        autonomous connection and are visible to concurrent pollers mid-lane —
        the DbSourceCallObserver / pre-spend-gate precedent. Without one, events
        ride the given lane connection (post-commit visibility; keeps every
        test conn-factory shape — locked, savepoint-per-acquisition — deadlock-free).
        Emission failures are swallowed with a log: observability never fails the lane.
        At-least-once: readers reduce last-writer-wins by seq per (lane, field_key).
        Events on the autonomous path survive a lane rollback by design; lane truth
        (recon_run status) supersedes on the read side.
        """
        def __init__(self, *, workspace_id: str, recon_run_id: UUID, lane: str,
                     conn_factory: ConnFactory | None = None) -> None: ...
        async def __call__(self, conn: AsyncConnection, field_key: str,
                           status: FieldProgressStatus) -> None:
            payload = {"kind": RECON_FIELD_PROGRESS_KIND,
                       "recon_run_id": str(self._recon_run_id),
                       "lane": self._lane, "field_key": field_key,
                       "status": status.value}
            try:
                if self._conn_factory is not None:
                    async with self._conn_factory() as own:
                        await emit_run_event(own, workspace_id=self._workspace_id,
                            run_id=ProjectRunId(self._recon_run_id),
                            topic=RunEventTopic.STEP_PROGRESS.value, payload=payload)
                else:
                    await emit_run_event(conn, ..., payload=payload)
            except Exception:
                logger.warning("stage0.recon.field_event_emit_failed", ...)
    ```

- [ ] **Step 1: Failing unit test** in `tests/stage0/test_reverse_profile.py` — a recording callback:
```python
async def test_per_field_progress_events_are_emitted_in_flight(rollback_conn) -> None:
    seen: list[tuple[str, FieldProgressStatus]] = []
    async def record(conn, field_key, status): seen.append((field_key, status))
    await reverse_profile(rollback_conn, ClientInput(name="Acme", website="https://acme.example"),
                          workspace_id=ws, on_field_progress=record)
    # every attempted field emits started then a terminal status
    starts = [k for k, s in seen if s is FieldProgressStatus.STARTED]
    assert starts == [k for k in CLIENT_BASELINE_FIELDS if k in starts]  # loop order
    for key in starts:
        terminals = [s for k, s in seen if k == key and s is not FieldProgressStatus.STARTED]
        assert len(terminals) == 1 and terminals[0] in (FieldProgressStatus.RESOLVED, FieldProgressStatus.EMPTY)
```
Plus: a raising `resolve_field` (monkeypatched) emits `FAILED` for that field before the exception propagates; a `None` callback changes nothing (all existing tests).
- [ ] **Step 2:** Run → FAIL (unexpected keyword `on_field_progress`).
- [ ] **Step 3:** Implement in `client_kb.py`: after `attempted_fields.add(field_key)` (L230) emit STARTED; wrap the `resolve_field` call in `try/except Exception: emit FAILED; raise`; after success emit RESOLVED if `result.claim_refs` else EMPTY. All emissions are `if on_field_progress is not None: await on_field_progress(conn, field_key, status)`. Fields skipped by `material_fields` or the budget break emit nothing (not attempted — honest absence).
- [ ] **Step 4:** `uv run pytest tests/stage0/test_reverse_profile.py -x` → all PASS (17 existing + new).
- [ ] **Step 5: Failing DB test** `tests/api/test_stage0_field_events_db.py` — the autonomous-visibility proof: open two real connections (engine-level, mirroring `tests/api/test_stage0_setup_db.py`'s harness); run the emitter with `conn_factory=transaction` from inside an open uncommitted transaction on conn A; assert conn B sees the `run_event` row **before** conn A commits; and after `ROLLBACK` on conn A the event row still exists (survives-rollback semantics documented). Also: emitter with `conn_factory=None` writes on the given conn (row visible only in-tx); an emitter whose factory raises does **not** propagate.
- [ ] **Step 6:** Implement `stage0_field_events.py` as specced. Run the DB test → PASS.
- [ ] **Step 7:** Commit `feat(stage0): per-field in-flight recon progress events (D-5 Path B)`.

---

### Task 3: Tool wiring + `GET /stage0/setup/current` serves per-field truth

**Files:**
- Modify: `platform/api/clue_api/stage0_tools.py` (constructor L535-557, `stage0_tools` factory L1340-1373, `invoke` L727-886)
- Modify: `platform/api/clue_api/toolbelt_wiring.py:2832-2846` (thread `field_progress_factory=conn_factory`… see step 3 note)
- Modify: `platform/api/clue_api/stage0_setup.py` (`SetupStatusResponse` L94-107, `_serve_lane_truth` L327-361)
- Test: `tests/api/test_stage0_setup_db.py` (extend), `tests/stage0/test_phase_c4_governed.py` (extend the evented test)

**Interfaces:**
- Consumes: `ReconFieldProgressEmitter`, `FieldProgressStatus`, `list_run_events`.
- Produces:
  - `_Stage0Tool.__init__(..., field_progress_factory: ConnFactory | None = None)`; `StartReconTool.invoke` builds a per-lane `ReconFieldProgressEmitter(workspace_id=..., recon_run_id=recon_id, lane="fast"|"background", conn_factory=self._field_progress_factory)` and passes it as `on_field_progress`.
  - `SetupStatusResponse` gains `fields: list[SetupFieldState] = []` (`SetupFieldState(BaseModel): field_key: str; lane: str; status: str`) and `fast_budget_exhausted: bool | None = None`, `background_budget_exhausted: bool | None = None`.
  - Transition events for COMPLETED lanes gain payload key `"budget_exhausted": bool` (additive; closes the B-2 discard for the progress surface — read from `result.budget_exhausted` at `stage0_tools.py:793-802`/`856-865`).

- [ ] **Step 1: Failing test** — extend `test_url_only_recon_is_two_speed_gated_snapshotted_and_evented` (`tests/stage0/test_phase_c4_governed.py:163`): after the existing transition assertions, filter `list_run_events` for `payload["kind"] == RECON_FIELD_PROGRESS_KIND` and assert ≥1 started+terminal pair per lane for `client.value_prop` (the test's extractor produces it), and that the fast lane's field events appear before its `completed` transition event by seq. (This harness's factory is same-conn reentrant, so pass `field_progress_factory=factory` in the tool construction — proves the same-conn fallback path.)
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Wire the tool: constructor + factory param threading (`stage0_tools(...)` and `build_toolbelt`/`toolbelt_wiring.py` pass `field_progress_factory=conn_factory` — **note:** in production `conn_factory` *is* `clue_db.transaction`, giving autonomous commits; in tests whatever the harness passes is same-object, giving the safe fallback only when the harness's factory is reentrant. Because locked test factories would deadlock, `stage0_tools()`'s default stays `None` → same-conn fallback via the emitter's `conn` argument; only `toolbelt_wiring` (production) passes the factory explicitly). Emit `budget_exhausted` in the two COMPLETED transition payloads.
- [ ] **Step 4:** Run the governed test suite → PASS. Then `uv run pytest tests/stage0/test_phase_c5_recipe0.py -x` → PASS (proves no deadlock under the Lock+savepoint factory: real tool built there gets `field_progress_factory=None`).
- [ ] **Step 5: Failing route test** — extend `tests/api/test_stage0_setup_db.py::test_setup_route_captures_drives_lanes_and_serves_lane_truth`: final `GET /stage0/setup/current` body has `fields` as a list where every entry has `field_key` starting `client.`, `lane in {"fast","background"}`, `status in {"started","resolved","empty","failed"}`, reduced to one entry per field (last-writer-wins by seq); and `fast_budget_exhausted is False`. (`_FakeStartReconTool` must now also emit a couple of field events + the budget flag so the read has material — extend the fake accordingly, keeping its 2-invocation contract.)
- [ ] **Step 6:** Implement the read: in `_serve_lane_truth`, after the progress read, `list_run_events(conn, workspace_id=..., run_id=ProjectRunId(recon_run_id))`, filter `RECON_FIELD_PROGRESS_KIND`, reduce `{field_key: (seq, lane, status)}` by max seq, sort by `CLIENT_BASELINE_FIELDS` order; read `budget_exhausted` off the latest COMPLETED transition payload per lane. Response additions are additive-with-defaults (`extra="forbid"` respected).
- [ ] **Step 7:** Full setup suite: `uv run pytest tests/api/test_stage0_setup_db.py -x` → PASS.
- [ ] **Step 8:** Commit `feat(api): setup progress serves per-field recon truth + budget honesty`.

---

### Task 4: The production LLM claim extractor

**Files:**
- Create: `platform/api/clue_api/claim_extraction.py`
- Test: `tests/api/test_claim_extraction.py` (new; pure, no DB)

**Interfaces:**
- Consumes: `LLMGateway` (`clue_core.gateway`), `ClaimExtractor` protocol + `span_for` (`clue_research.adapters`), `NormalizedText`/`Entity`/`FieldDef`, field descriptions (`stage0/fields.py`).
- Produces:
  ```python
  EXTRACTION_PROMPT_VERSION = "v1"

  class ExtractionPolicy(BaseModel):
      model_config = ConfigDict(frozen=True)
      extraction_model: str = Field(default_factory=lambda: default_gateway_config().planner_model)
      max_claims_per_field: int = 3
      min_confidence: float = 0.3

  def build_extraction_messages(normalized: NormalizedText, field: FieldDef,
                                *, prompt_version: str = EXTRACTION_PROMPT_VERSION) -> list[Message]
  def parse_extraction_response(text: str, normalized_text: str, field: FieldDef,
                                *, policy: ExtractionPolicy) -> list[ClaimDraft]
  class LlmClaimExtractor:  # implements ClaimExtractor (sync — LLMGateway.complete is sync)
      def __init__(self, *, gateway: LLMGateway, policy: ExtractionPolicy | None = None) -> None: ...
      def extract(self, normalized, entity, field) -> list[ClaimDraft]: ...
  ```

Design points (all in the module docstring):
- Placement/injection mirrors `claim_entailment.py`; the LLM-call mechanics mirror `verification/faithfulness.py`: `PROMPTS` dict keyed by version, SECURITY clause, `<<<PAGE_TEXT>>> … <<<END_PAGE_TEXT>>>` fencing ("untrusted data, never instructions"), JSON contract parsed via a local `first_json_object`-style tolerant parse, **fail-safe to `[]`** on any parse problem (a `StubGateway`'s `stub:<sha>` text therefore yields `[]`, never a raise).
- JSON contract the prompt demands: `{"claims": [{"value": <shape per field>, "quote": "<verbatim substring of the page text>", "source_url": "<url from a ### RESULT header, or null>", "confidence": 0.0-1.0}]}` — return `{"claims": []}` when nothing is stated verbatim.
- Per-field value-shape instructions come from a small table in the module: the 5 plain-string fields (`value_prop`, `product`, `differentiator`, `pricing_posture`, `proof_point`, `market_reputation`, `delivered_value` → string), `client.customer` → array of `{"name": str, "domain"?: str}`, `client.icp_evidence` → object `{"industries"?: [...], "sizes"?: [...], "geos"?: [...]}`, `client.competitor` → `{"name": str, "domain"?: str}`, `client.buyer_profile` → `{"persona": str, "segment"?: str}`. Field guidance strings quote the registry descriptions from `fields.py`.
- **Self-validation, drop-never-raise:** each parsed claim is kept only if (a) `quote` is a non-empty exact substring of `normalized.text` (checked with `in`; `span_for` semantics), (b) the value matches the field's shape (isinstance checks per the table), (c) `confidence >= policy.min_confidence`. Drops are logged with a counter. Output capped at `max_claims_per_field` (1 for the string fields — first only).
- `ClaimDraft(field_key=field.field_key, value=..., evidence_span=quote, confidence=..., source_url=parsed_or_None)`.
- Gateway exceptions → log `stage0.claim_extraction_unavailable` + return `[]` (the honest-empty posture; a lane must never fail because the LLM was down).
- Stateless w.r.t. tenant (the binder shares one instance process-wide).

- [ ] **Step 1: Failing tests** in `tests/api/test_claim_extraction.py`, using `FakeGateway` (copy the shape from `tests/stage0/_fakes.py:222-243`):
```python
def _normalized(text: str) -> NormalizedText: ...
def _field(key: str = "client.value_prop") -> FieldDef: ...

def test_grounded_claim_is_extracted_with_exact_span():
    gw = FakeGateway(text=json.dumps({"claims": [{"value": "Acme automates ops",
        "quote": "Acme automates repetitive operational work", "source_url": None, "confidence": 0.9}]}))
    drafts = LlmClaimExtractor(gateway=gw).extract(
        _normalized("… Acme automates repetitive operational work …"), _entity(), _field())
    assert len(drafts) == 1 and drafts[0].evidence_span in "… Acme automates repetitive operational work …"

def test_paraphrased_quote_is_dropped_never_raised():   # the anti-AdaptError guarantee
    gw = FakeGateway(text=json.dumps({"claims": [{"value": "x", "quote": "a paraphrase not in the page",
                                                  "confidence": 0.9}]}))
    assert LlmClaimExtractor(gateway=gw).extract(_normalized("real page text"), _entity(), _field()) == []

def test_malformed_json_and_stub_gateway_yield_empty(): ...
def test_wrong_value_shape_is_dropped():   # customer must be a list of objects
def test_prompt_fences_untrusted_text_and_names_the_field():
    # assert "<<<PAGE_TEXT>>>" in user message; field guidance text present; SECURITY clause in system
def test_gateway_error_yields_empty_not_lane_failure():
    assert LlmClaimExtractor(gateway=FakeGateway(raise_exc=True)).extract(...) == []
def test_low_confidence_dropped_and_cap_applies(): ...
```
- [ ] **Step 2:** Run → FAIL (module missing).
- [ ] **Step 3:** Implement `claim_extraction.py` per spec.
- [ ] **Step 4:** `uv run pytest tests/api/test_claim_extraction.py -x` → PASS. `make lint`, mypy clean.
- [ ] **Step 5:** Commit `feat(api): production LLM claim extractor (grounded, drop-never-raise)`.

---

### Task 5: Compose the extractor at both production roots

**Files:**
- Modify: `platform/api/clue_api/run_composition.py` (add `build_optional_platform_gateway`)
- Modify: `platform/api/clue_api/projections_main.py:75-86`, `platform/api/clue_api/fleet_main.py:556-564`
- Test: `tests/api/test_projections_app.py` or the existing composition-guard test file for these roots (extend where root wiring is already pinned; else new `tests/api/test_extractor_composition.py`)

**Interfaces:**
- Produces: `build_optional_platform_gateway(settings) -> LLMGateway | None` — returns `build_platform_gateway(settings)` when an OpenRouter key (or `CLUE_GATEWAY_ALLOW_STUB`) is configured, else `None` with a loud `structlog` warning `stage0.claim_extraction_disabled_no_gateway`. Both roots then compose:
  ```python
  gateway = build_optional_platform_gateway(resolved)   # fleet_main reuses its existing gateway
  extractor = (LlmClaimExtractor(gateway=gateway) if gateway is not None
               else CallableClaimExtractor(lambda normalized, entity, field: []))
  ```
  passed into `build_stage0_scrape_binder(extractor=extractor, ...)` (still flag-gated on `self_serve_provisioning_enabled`).

- [ ] **Step 1: Failing test** — pin that with a configured stub gateway the binder's extractor is an `LlmClaimExtractor`, and with no key/no stub-allow it remains the empty callable (import the composition functions directly; no HTTP needed).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; `fleet_main` reuses its existing `gateway` (line ~468) instead of building a second one.
- [ ] **Step 4:** Composition + setup suites green: `uv run pytest tests/api/test_stage0_setup_db.py tests/api/test_toolbelt_wiring.py -x`.
- [ ] **Step 5:** Commit `feat(api): compose LLM extractor at both roots (graceful no-gateway fallback)`.
- [ ] **Step 6:** Doc note: with a real extractor, `CLUE_SCRAPE_BACKEND=firecrawl` becomes viable again per deployment — record in `docs/api-contracts/onboarding.md` at Task 10, don't flip any default.

---

### Task 6: Register `client.competitor` + `client.buyer_profile`

**Files:**
- Modify: `subsystems/research/clue_research/stage0/fields.py` (constants L44-52 area, `CLIENT_BASELINE_FIELDS` L59-69 — **append at the end**, `CLIENT_KNOWLEDGE_PACK` L113-212, `SURFACE_CLASS_FIELDS` L228-242 — both fields join `THIRD_PARTY`)
- Modify: `platform/api/clue_api/composition.py:94-98` (append `load_client_knowledge_pack` to `RESEARCH_PACK_LOADERS` — the boot-order fix so manifests naming `client.*` yields validate on a fresh DB)
- Test updates (enumerated by the study; every one listed here must be touched):
  - `tests/api/test_discovery_stage0_fixture.py:168` `7/9` → `7/11`; `:119` stays 7
  - `tests/stage0/test_stage0_static.py` (pack/tuple/surface/tenant-private tests absorb the new fields automatically — verify, don't edit unless an explicit count exists)
  - `tests/stage0/test_reverse_profile.py:283-284` (surfaces still 4; new fields are attempted-but-NO_RESOLVER in both lanes until Task 7 — verify green)
  - `tests/api/test_stage0_routing_honesty.py:411-412` (sorted `available_field_keys` — verify `client.buyer_profile`/`client.competitor` don't intrude; they sort before `client.customer` but are absent from the fixture's claim map, so the list is unchanged — verify)
  - `tests/stage0/test_phase_c5_recipe0.py:719` fingerprint (readiness stays `not_ready` — verify)
  - `tests/projections/test_stage0_card.py` byte-cap literals (`:371,:512,:551,:680`) — run and adjust only if red

**Interfaces:**
- Produces: `CLIENT_COMPETITOR = "client.competitor"`, `CLIENT_BUYER_PROFILE = "client.buyer_profile"`; both `SeedField`s via `_seed(...)`: `value_type="object"`, `value_schema={"type": "object"}`, `pass_kind=SCORING`, `reuse_scope=TENANT_PRIVATE`, `freshness_ttl=90d`, `tier_plan=("exa_search",)`, descriptions:
  - competitor: `"Named competitor / alternative to the client (open-web comparison surfaces) — one claim per competitor, grounded in a record naming the client."`
  - buyer_profile: `"Likely-buyer persona / segment evidence (open-web) — persona claims only, never invented account entities (discovery doctrine)."`

- [ ] **Step 1: Failing test** — extend `tests/stage0/test_stage0_static.py`:
```python
def test_competitor_and_buyer_fields_are_baseline_tier3_only() -> None:
    assert CLIENT_BASELINE_FIELDS[-2:] == (CLIENT_COMPETITOR, CLIENT_BUYER_PROFILE)
    for key in (CLIENT_COMPETITOR, CLIENT_BUYER_PROFILE):
        seed = next(s for s in CLIENT_KNOWLEDGE_PACK if s.field_def.field_key == key)
        assert seed.field_def.tier_plan == ("exa_search",)
        assert seed.field_def.reuse_scope is ReuseScope.TENANT_PRIVATE
        assert key in SURFACE_CLASS_FIELDS[SurfaceClass.THIRD_PARTY]
```
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement fields.py changes + the `RESEARCH_PACK_LOADERS` append (comment: "client pack must precede seed_source_manifests — source yields validate against the field registry; mirrors tests/stage0/conftest ordering contract").
- [ ] **Step 4:** Run the full impact set: `uv run pytest tests/stage0/ tests/api/test_discovery_stage0_fixture.py tests/api/test_insight_health_browser_fixture.py tests/api/test_stage0_routing_honesty.py tests/projections/test_stage0_card.py -x`. Fix the enumerated literals (`7/9`→`7/11` etc.). The two new fields resolve `NO_RESOLVER`/empty everywhere (no manifest yet) — that is correct behavior at this commit (the `market_reputation` precedent).
- [ ] **Step 5:** Commit `feat(stage0): register client.competitor + client.buyer_profile (tier-3 plan, background-only via gate)`.

---

### Task 7: The tier-3 Exa search source + resolver

**Files:**
- Modify: `subsystems/research/clue_research/sources/seeds.py` (add the `exa_search` manifest)
- Create: `subsystems/research/clue_research/resolvers/exa_search/__init__.py`
- Modify: `platform/api/clue_api/projections_main.py`, `fleet_main.py` (register + bind, same flag gate)
- Test: `tests/resolvers/test_exa_search.py` (new), `tests/resolvers/test_static.py` (auth-ref test absorbs), `tests/sources/test_static_invariants.py` (verify)

**Interfaces:**
- Consumes: `ClaimExtractor` (the shared production extractor instance), `get_json`/`resolve_credential` (`resolvers/http.py`), `account_claim` factory, guards copied from `grounded.py` (`_names_present`-style whole-word matching, fail-closed on-entity).
- Produces:
  - Manifest in `SEED_MANIFESTS`: `source_key="exa_search"`, `tier=3`, `provider="exa"`, `cost_cents=Decimal(1)`, `auth_ref="CLUE_EXA_API_KEY"`, `modality=TEXT`, `yields=("client",)`, `identity_binding=IdentityBinding.WEAK`, `freshness_profile="snapshot"` (match neighboring seed shapes exactly at implementation).
  - ```python
    EXA_SEARCH_SOURCE_KEY = "exa_search"

    class ExaSearchConfig(BaseModel):
        endpoint: str = "https://api.exa.ai/search"
        search_type: str = "auto"          # NEVER "deep"/"deep-reasoning" (tier-4)
        num_results: int = 5
        query_templates: dict[str, str] = {
            "client.competitor": '"{name}" competitors alternatives comparison',
            "client.buyer_profile": 'who uses "{name}" buyers customer roles teams',
        }

    class ExaSearchResolver:  # implements clue_core.Resolver
        tier: int = 3
        def __init__(self, *, extractor: ClaimExtractor, accounts: AccountLookup,
                     config: ExaSearchConfig | None = None, secrets: Secrets | None = None) -> None: ...
        def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]: ...

    def register_exa_search_resolver(*, extractor, accounts, config=None) -> None
    ```
  - `resolve()` mechanics: entity must be ACCOUNT + present in `accounts` (else `[]`); no query template for the field → `[]`; POST `{query, type, numResults, contents:{"text": true}}` via `get_json` (transport errors → `RetryableResolverError` per http.py semantics; hard miss → `[]`); build one `NormalizedText` whose text is the concatenated records, each prefixed `### RESULT {n} | url: {url}` — the prompt's source_url vocabulary; call `extractor.extract`; **guards per draft**: span exact-substring (already extractor-guaranteed, re-checked), `source_url` must be one of the record urls (else drop), whole-word client-name-or-domain match in the record's own text (the `_names_present`/`_on_entity` posture, fail-closed when the account has neither a usable name token nor domain); construct `account_claim(entity_id=..., field_key=..., value_json=draft.value, source_tier=3, extraction_method=ExtractionMethod.API, confidence=..., run_id=..., research_mode=..., source_url=draft.source_url, evidence_span=draft.evidence_span, cost_cents=Decimal(1) on the first claim only, ...)`. **No `insert_account_entity` anywhere.**
  - Registration at both roots, inside the existing `self_serve_provisioning_enabled` block: `register_source(conn-at-boot via the existing seed path — the manifest is in SEED_MANIFESTS so `seed_source_manifests` handles the DB row)` + `register_exa_search_resolver(extractor=extractor, accounts=stage0_scrape_binder)` (the binder already implements the account-lookup shape; verify `Stage0ScrapeBinder` exposes lookup — it accumulates `{EntityId: AccountEntity}`; if its lookup method differs from `AccountLookup`, add a thin adapter, do not modify the binder).

- [ ] **Step 1: Failing tests** in `tests/resolvers/test_exa_search.py` (pure; fake `get_json` + `FakeGateway`-backed real extractor or a canned `CallableClaimExtractor`):
```python
def test_grounded_competitor_record_becomes_a_tier3_api_claim_with_source_url(): ...
def test_record_not_naming_the_client_is_dropped_fail_closed(): ...
def test_source_url_not_in_returned_records_is_dropped(): ...
def test_no_template_or_wrong_entity_type_yields_empty(): ...
def test_search_type_never_deep():  # config guard: constructing with search_type containing "deep" raises ValueError
def test_transport_failure_is_retryable_not_fabricated(): ...
def test_manifest_is_tier3_weak_binding_and_seeded():  # SEED_MANIFESTS entry assertions
```
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement resolver + manifest + registrations.
- [ ] **Step 4:** `uv run pytest tests/resolvers/ tests/sources/ -x` → PASS (incl. `test_every_seeded_auth_ref_resolves_to_a_secrets_field`, provider-branching invariant).
- [ ] **Step 5: Lane-level test** — extend a `tests/stage0/test_reverse_profile.py` case (or new): with the exa_search resolver bound and a canned extractor, the **fast** lane (max_source_tier=2) gate-skips it at zero spend while the **background** lane (max_source_tier=3) produces a `client.competitor` claim. Run → PASS.
- [ ] **Step 6:** Commit `feat(research): tier-3 exa_search resolver for competitors/buyers (grounded, fail-closed)`.

---

### Task 8: Frontend — four ratified groups, event-derived

**Files:**
- Modify: `apps/frontend/src/features/onboarding/data/setup.ts` (schema + `SetupFieldState`)
- Create: `apps/frontend/src/features/onboarding/data/setup-groups.ts`
- Modify: `apps/frontend/src/features/onboarding/model/setup-items.ts` (+ its test file)
- Modify: `apps/frontend/src/features/onboarding/components/live-setup-screen.tsx` (pass-through only)
- Test: `model/setup-items.test.ts` (rewrite the 6, add group-reduction cases), `data/setup.test.ts` (schema additions)

**Interfaces:**
- `setup.ts` additions (Zod discipline: `.catch` on closed enums, defaults, never `.strict()`):
  ```ts
  export const SetupFieldStateSchema = z.object({
    field_key: z.string().min(1),
    lane: z.string(),
    status: z.enum(["started", "resolved", "empty", "failed"]).catch("started"),
  });
  // on SetupStatusSchema:
  fields: z.array(SetupFieldStateSchema).optional().default([]),
  fast_budget_exhausted: z.boolean().nullable().optional().default(null),
  background_budget_exhausted: z.boolean().nullable().optional().default(null),
  ```
- `setup-groups.ts` — the D-6 mapping as frozen data (labels/details = integration-authored copy pending founder review; the ratified field partition is fixed):
  ```ts
  export interface SetupGroup { id: string; label: string; detail: string; fieldKeys: readonly string[] }
  export const SETUP_GROUPS: readonly SetupGroup[] = [
    { id: "product-value", label: "Understanding your product & value",
      detail: "Product, value proposition, and differentiators",
      fieldKeys: ["client.product", "client.value_prop", "client.differentiator"] },
    { id: "pricing-proof", label: "Pricing & proof",
      detail: "Pricing posture and proof points",
      fieldKeys: ["client.pricing_posture", "client.proof_point"] },
    { id: "customers-market", label: "Customers & market",
      detail: "Customers, ICP evidence, and market reputation",
      fieldKeys: ["client.customer", "client.icp_evidence", "client.market_reputation", "client.delivered_value"] },
    { id: "competitors-buyers", label: "Competitors & likely buyers",
      detail: "Competitor landscape and likely-buyer profiles",
      fieldKeys: ["client.competitor", "client.buyer_profile"] },
  ] as const;
  ```
- `setup-items.ts` — new pure reduction (keeps `laneItemStatus` for lane fallback; `deriveSetupItems` becomes group-aware):
  ```ts
  const TERMINAL = new Set(["resolved", "empty", "failed"]);
  export function groupStatus(fields: SetupFieldState[], group: SetupGroup,
                              overall: string): SetupItem["status"] {
    if (overall === "complete") return "complete";
    const member = group.fieldKeys.map(k => fields.find(f => f.field_key === k)?.status ?? null);
    if (member.some(s => s !== null)) {
      return member.every(s => s !== null && TERMINAL.has(s)) ? "complete" : "running";
    }
    return "queued";
  }
  export function deriveSetupItems(fixtureSetup, progress): SetupItem[]
  // → 5 items: SETUP_GROUPS mapped through groupStatus (with the slice-2 `starting`
  //   motion rule: status==="starting" renders group 1 as "running" when no events yet),
  //   plus the brand-kit fixture row forced "queued" (unchanged standing ruling).
  // Detail-line annotations (slice-2 precedent — never a new visual state):
  //   any member "failed"           → detail + " — part of this hit a problem"
  //   lane budget_exhausted & member never-started → detail + " — stopped at the research budget"
  ```
  The backend `fields` reduction is already one-entry-per-field; the frontend must not re-reduce by seq (it never sees seq).

- [ ] **Step 1: Failing tests** — rewrite `model/setup-items.test.ts`: 5-item length; all-queued when `progress === null`; group-1 running under `starting`; a group turns running on first member event and complete when all members terminal incl. `empty` and `failed`; `overall === "complete"` forces all groups complete (release consistency); brand-kit forced queued; failed-member and budget-exhausted detail annotations; stable ids across ticks. Extend `data/setup.test.ts`: `fields` default `[]` on a pre-slice-3 payload; unknown per-field status degrades to `"started"` not a parse failure.
- [ ] **Step 2:** `npx tsx --test src/features/onboarding/model/setup-items.test.ts` → FAIL.
- [ ] **Step 3:** Implement schema + groups + reduction; `live-setup-screen.tsx` only threads `status` through (no markup change; frozen `SetupScreen` renders whatever items arrive — 5 rows).
- [ ] **Step 4:** `npm test` → all green; `npm run lint && npm run build` → green.
- [ ] **Step 5:** Commit `feat(frontend): event-derived four-group setup checklist (D-6)`.

---

### Task 9: Frontend — the setup repository seam + fixture event-stream source

**Files:**
- Create: `apps/frontend/src/features/onboarding/data/setup-progress.repository.ts`
- Create: `apps/frontend/src/features/onboarding/data/setup-progress.fixture.ts`
- Modify: `apps/frontend/src/features/onboarding/hooks/use-setup-progress.ts` (consume the source; zero behavior change on the HTTP path)
- Test: `data/setup-progress.repository.test.ts` (new)

**Interfaces:**
```ts
export interface SetupProgressSource {
  start(): Promise<void>;
  read(): Promise<SetupStatus>;
}
export const httpSetupProgressSource: SetupProgressSource = {
  start: startWorkspaceSetup, read: readSetupStatus,   // existing functions, unmoved
};
export function createFixtureSetupProgressSource(
  script?: readonly SetupStatus[],
): SetupProgressSource
// Frame-per-read: each read() returns the next frame, sticking at the last.
// The default script walks the honest vocabulary: starting → fast-lane fields
// started/resolved per group in CLIENT_BASELINE_FIELDS order → complete with
// fact_count. Frames are wire-shaped SetupStatus objects validated through
// SetupStatusSchema — the chat-fixture rule verbatim: "nothing here advances a
// phase because time passed"; the poll tick is the transport, the frame is the state.
```
- `useSetupProgress(source: SetupProgressSource = httpSetupProgressSource)` — the hook's internals (channels, terminals, release, StrictMode refs, `MAX_PENDING_POLLS`, poll-stop rules) are **untouched**; only the two direct imports are replaced by `source.start`/`source.read`.
- **Fixture mode default remains the static designed theatre** (standing preserve-the-theatre ruling): `onboarding-screen.tsx`'s mode branch is not changed. The fixture source ships test-driven and ready; flipping dev mode to live motion is a founder-offered one-liner, not made here.

- [ ] **Step 1: Failing tests** — `data/setup-progress.repository.test.ts`: the fixture source replays its script frame-per-read and sticks at the last frame; every frame parses through `SetupStatusSchema`; the default script's final frame is `status: "complete"` with all 11 field terminals present; `httpSetupProgressSource` delegates to the existing functions (spy via `stubFetch` pattern from `data/setup.test.ts:10-16`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; refactor the hook's imports (behavior-identical — existing hook consumers compile unchanged since the param defaults).
- [ ] **Step 4:** Full frontend gate: `npm run design-system:build && npm run lint && npm run build && npm test` → green.
- [ ] **Step 5:** Commit `feat(frontend): setup transport behind repository seam + scripted fixture event-stream`.

---

### Task 10: Contracts, docs, close-out

**Files:**
- Modify: `apps/frontend/docs/api-contracts/onboarding.md` (the `fields`/budget additions to `GET /stage0/setup/current`, the four groups + mapping-as-frontend-data, the extractor's existence + scrape-backend note, the fixture-source decision)
- Modify: `docs/specs/FI-onboarding-contract-gap-review.md` (§9: record the slice-3 landings against D-5/D-6; note the plan-level decisions 1-7 for founder review)
- Create: `_memory/2026-08-12-slice3-granular-truth.md` (what landed, gotchas, residuals: LLM cost out-of-envelope, recon_brief fast-version-only gap for background facts, snapshot capture for exa records if deferred, fixture-mode motion offer)
- Test: full gates both halves

- [ ] **Step 1:** Backend full gate: `uv run pytest tests/stage0 tests/api tests/resolvers tests/sources tests/projections -x -q` + `make lint` + mypy.
- [ ] **Step 2:** Frontend full gate (all four commands).
- [ ] **Step 3:** Write the three docs; verify no stale claims (e.g. onboarding.md's superseded redirect note stays corrected).
- [ ] **Step 4:** Commit `docs: slice-3 close-out — contract + ratification log + memory`.

---

## Self-review notes

- **Spec coverage:** D-5 Path B (Tasks 1-3), Exa amendment fields (Tasks 6-7), extractor work item (Tasks 4-5), D-6 groups + fixture stream (Tasks 8-9), contract write-back (Task 10). Budget-exhausted honesty (B-2 subset) rides Task 3. Not in scope (recorded residuals): SSE transport (D-8 poll ratified), recon_brief background-version gap, scrape artifact cache (BE-m11 — untouched; the extractor makes firecrawl viable but scrapling stays the deployment default), G2 throttle.
- **Type consistency:** `FieldProgressStatus` values = wire strings = frontend Zod enum. `SetupFieldState` (Pydantic) mirrors `SetupFieldStateSchema` (Zod). `on_field_progress` passes the lane conn first-arg so the emitter's fallback path needs no factory.
- **Order matters:** Tasks 1→3 are sequential; Task 4 is independent of 1-3; Task 5 needs 4; Task 6 needs nothing but touches shared test literals (serialize with 7); Task 7 needs 4+6; Tasks 8-9 need 3's wire shape. Suggested execution order: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10.
