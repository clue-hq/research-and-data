# 2026-06-24 — M12 (Value Narrative & Handoff) implementation plan + M12.1 build

**Branch:** `m12/value-narrative` (forked off frozen base `1902210` = `integration/phase3-preflight*`,
single alembic head `3df3b2f629fd`). WS-C of the phase-3 parallel kickoff (M10 ∥ M11 ∥ M12).
Spec: `docs/specs/M12-value-narrative-and-handoff.md`. Pre-flight overrides: `docs/specs/_phase3-preflight.md`.

## Import contract (verified against pyproject `[tool.importlinter]`, NOT the simplified README)
`narrative` is a *worker* under the **independence** contract: it may NOT import sibling workers
(`profiling`/M8, `verification`/M9, `compliance`/M10, `synthesis`/M11, `stage0`/M5, `durable`,
`discovery_scoring`, `review`, `adapters`). It MAY freely import the shared base (`core`/`config`/`obs`)
and the **M1–M4 services** (`claimstore`, `identity`, `icp`, `sources`) + `db`. Consequence:
- ✅ narrative → `identity.stamp_reuse` (reuse stamping in-package, like stage0).
- ✅ narrative → `claimstore` (read merge / write claims / register fields).
- ❌ narrative → `stage0` (so the stage0-backed `ClientKnowledgeRetriever` impl lives at the **api root**).
- ❌ narrative → `profiling`/`compliance` (so committee + use-gated facets arrive via an **injected seam**;
  the production reader — needs `compliance.use_decision` — is **api-root / integration**, deferred like
  the M9.4 binding-classifier injection precedent).
- `core` is frozen → M12 must NOT edit `core/` (handoff stamps, retrieval seam, compliance seam already
  landed in PF-1). `config/gateway.py` NOT edited: `PositioningPolicy.narrative_model` defaults to
  `DEFAULT_GATEWAY_CONFIG.synthesis_model` (positioning IS grounded synthesis).

## M12.1 — Positioning step (THIS milestone; pause after)
Pattern template = the M9.3 faithfulness judge (`verification/faithfulness.py`): injected `LLMGateway`
+ versioned policy-as-data + DB policy table + side table + spans + pure helpers.

Files under `src/clue_research/narrative/`:
- `fields.py` — `VALUE_NARRATIVE = "account.value_narrative"`; `NARRATIVE_PACK` (one `SeedField`,
  `FieldDef(value_type="object", pass_kind=DEEP, tier_plan=(), gate="faithfulness",
  freshness_ttl=90d, reuse_scope=TENANT_PRIVATE)` — MUST declare TENANT_PRIVATE: `FieldClass.ACCOUNT`
  default is PUBLIC_FOOTPRINT, leak hazard); `value_schema={persona, argument, angle_label}`;
  `single_source_sufficient=True`, `corroboration_min=1` (judge-gated, not corroborated);
  `load_narrative_pack(conn)`.
- `reuse.py` — `NARRATIVE_REUSE_POLICY = DEFAULT_REUSE_POLICY` + `account.value_narrative` prefix
  (mirrors stage0 `_extend`; `stamp_reuse` uses prefix heuristic, not declared_scope — verified).
- `policy.py` — `PositioningPolicy` (narrative_model, prompt_version, min_account_evidence=1,
  min_client_chunks=1, max_evidence_chars, field_relevance: dict[persona,tuple[field_key]]),
  `PROMPTS` (versioned system prompt + per-persona angle templates in code), `DEFAULT_FIELD_RELEVANCE`,
  `DEFAULT_POSITIONING_POLICY`, `load_positioning_policy(conn, *, client_id=None)` (most-specific→global,
  ORDER BY version DESC,created_at DESC,policy_id DESC; fail-soft to default).
- `seams.py` — `CommitteeReader` Protocol + `CommitteeContact`(contact_entity_id, persona,
  role_on_committee, facets) + `FacetHook`(claim, decision: UseDecision|None); in-memory fakes
  `InMemoryCommitteeReader`, `InMemoryClientKnowledgeRetriever` (no stage0 import) for tests/default.
- `support.py` — `write_claim_support(conn, claim_id, account_evidence_ids, client_knowledge_ids)`,
  `read_claim_support(conn, claim_id)` over the `claim_support` side table.
- `positioner.py` — `Positioner` + `position(conn, account_entity_id, *, icp_spec_version, client_id,
  client_entity_id, run_id, campaign_run_id=None, kb_version=None) -> PositioningResult`. Per committee
  persona: gather persona-relevant account `current_values` (verified-only via `require_verified_tier4`),
  filter usable facets (`is_outreach_promotable(claim, decision)` — STRONG binding + use-allowed),
  retrieve client knowledge; if account-evidence OR client-knowledge empty → `CoverageGap` (no claim);
  else synthesize via gateway → build `account.value_narrative` claim (tier-4 llm_synthesis,
  evidence_span = capped account spans ⊕ client chunks), `stamp_reuse(... NARRATIVE_REUSE_POLICY)`,
  `insert_claim` (UNVERIFIED) + `write_claim_support` + `judge.judge(claim)` (promotes/rejects).
  Re-run supersedes prior live narrative claims for the same (account, icp, persona). Pure helpers:
  `build_positioning_messages`, `assemble_evidence_span`, angle selection.
- `__init__.py` — exports.

Migration `alembic/versions/<hash>_m12_1_value_narrative_tables.py` (down_revision=`3df3b2f629fd`):
- `claim_support` (claim_id uuid NOT NULL, account_evidence_ids uuid[] NOT NULL DEFAULT '{}',
  client_knowledge_ids text[] NOT NULL DEFAULT '{}', created_at) + UNIQUE(claim_id) + index. NO FK to
  claim(id) (M9 side-table convention: audit survives supersession).
- `positioning_policy` (policy_id text PK, client_id text NULL, narrative_model, prompt_version,
  min_client_chunks int, max_evidence_chars int, field_relevance jsonb CHECK object, version int,
  created_at) + UNIQUE(client_id, version) NULLS NOT DISTINCT.

api: `api/narrative_wiring.py::register_narrative_wiring()` → idempotently append `load_narrative_pack`
to `RESEARCH_PACK_LOADERS`. Positioner construction (production retriever/committee-reader/judge/use-gate
injection) is integration (needs M5 pgvector + M10 use_decision) — documented, deferred.

### Key design decisions (audit these)
1. **Committee via injected `CommitteeReader` seam** (not a param, not direct read): narrative can't
   import profiling/compliance and there's no `contacts_for_account` reachable. Production impl = api.
2. **Facets gate the prompt, not the provenance**: only usable (STRONG+allowed) facets are passed to the
   LLM (disallowed never seen → AC5). NOT cited in `supporting.account_evidence_ids` (that stays strictly
   verified ACCOUNT claims → clean AC4; `NarrativeSupport` has no facet slot and core is frozen).
3. **`supporting` in the `claim_support` side table** (PF-2), not value_json. value_json carries
   {persona, argument, angle_label} (persona keying).
4. **Coverage gaps are returned, not persisted** (derivable by M12.2 = committee persona with no
   narrative claim). Also emitted as a metric.
5. **reuse stamping via identity.stamp_reuse + NARRATIVE_REUSE_POLICY** (DRY; narrative may import identity).

### M12.1 Acceptance criteria → test mapping
AC1 ≥1 claim/persona w/ argument+span+≥1 account_evidence & ≥1 client_knowledge; AC2 tier-4 llm_synthesis
+ judge, ungrounded not promoted; AC3 econ vs tech differ (angle_label + cite different evidence via
field_relevance); AC4 every id resolves (referential integrity); AC5 weak+sensitive facet absent;
AC6 thin KB → coverage gap; AC7 re-run supersedes; AC8 prompt/templates/field-relevance from versioned
config (positioning_policy + PROMPTS).

## M12.2 (next, not now) — `account_handoff` assembler + provenance_index
Pure deterministic `assemble(conn, account_entity_id, *, icp_spec_version, ...) -> AccountHandoff`
over the store: scores (decomposed) + account_profile_claims + committee (via the same CommitteeReader
seam) + value_narrative (read `account.value_narrative` claims + `claim_support`) + provenance_index.
Sets PF-1 additive stamps. Materialize-on-assembly table (recompute on supersede). Reuses M12.1 seams.

## M12.3 (later) — Output/handoff API
FastAPI read API + emit/notify outbox (`handoff_event` table, idempotent on (campaign_run, account,
icp)). `HandoffPublisher` adapter seam (D2). Read/emit only — never a write-back path.

## M12.1 — DONE (audited, green)
Branch `m12/value-narrative`. Migration `a3f352f32954` (down_revision `3df3b2f629fd`): `claim_support`
+ `positioning_policy`. Full gate green: ruff/format, mypy (20 files), **11/11 import contracts**
(narrative import-clean), **26/26 tests** pass against the rome DB (55030) incl. the real M9.3 judge.
Change surface: `narrative/` (8 files), `api/narrative_wiring.py`, the migration, `tests/narrative/`,
`tests/api/test_narrative_wiring.py` — **no `core/`/`merge.py`/`packs.py`/`handoff.py` edits**.

### Pre-flight overrides honoured (ENG-158 comment + M12 spec callout)
- ✅ `account.value_narrative` declares `reuse_scope=TENANT_PRIVATE`; positioner stamps via
  `identity.stamp_reuse` + `NARRATIVE_REUSE_POLICY` (mirrors stage0 `_extend`). Tested: classifies
  private; written claim is private + tenant-bound; absent from PUBLIC_ONLY scope.
- ✅ filters hooks with `core.compliance.is_outreach_promotable(claim, use_decision)` (never
  `Claim.is_promotable`); weak/sensitive facets never reach the prompt.
- ✅ reads post-tombstone merge; **no EXPIRED special-case**.
- ✅ M12←M11 SOFT: builds against in-memory fixtures + real FaithfulnessJudge; zero change when M11
  binds resolvers to the same field_keys.
- ✅ **closed "the one genuine pre-flight gap"**: the `read_client_kb_claims`-backed
  `ClientKnowledgeRetriever` stub lives at the api root (`api/narrative_wiring.ClientKnowledgeRetrieverStub`
  + `build_client_knowledge_retriever`) — narrative can't import stage0; shared `rank_by_query_overlap`
  relevance with the in-memory fake. pgvector lands behind the same seam later (config swap).
- ✅ synthesis LLM call routes through the injected `LLMGateway` (M0.4); model/prompt are versioned config.

### Adversarial audit (22-agent workflow) → fixed
1. **`positioning_policy` omitted `min_account_evidence` + `retrieval_limit`** (declared policy fields,
   not persisted/loaded → un-overridable). FIXED: added both columns + CHECKs to the migration and the
   loader SELECT/constructor. (Migration amended in place — re-applied on dev DB via downgrade→upgrade.)
2. **`load_positioning_policy` untested** → added DB test (per-client→global→default precedence +
   stale-prompt_version fail-soft degrade) + a pure `_parse_field_relevance` test.
3. **`no_account_evidence` coverage-gap branch untested** → added test (account-side of AC1/AC6).
4. **referential-integrity test hardcoded one field** → made it field-agnostic (pain+moves, each cid
   resolves to a real live account claim).
5. **no D5 multi-ICP coexistence test** → added (two ICP versions → two live claims, neither superseded).

### Design decisions (audit these at integration)
- Committee + use-gated facets arrive via an injected narrative-local `CommitteeReader` seam; the
  production reader (reads `contact_entity` under account × persona/facet × M10 `use_decision`) is
  api-root integration work (needs M10) — in-memory fake for tests.
- `supporting` lives in the `claim_support` side table (PF-2); `value_json={persona, argument,
  angle_label, icp_spec_version}` (icp added for D5 supersession keying).
- Facets gate the *prompt* (disallowed never seen → AC5); NOT cited in `account_evidence_ids` (that
  stays strictly verified account claims → clean AC4; `NarrativeSupport` has no facet slot, core frozen).
- Coverage gaps are returned (not persisted) — derivable by M12.2 as a committee persona with no claim.
- Positioner uses an injected `conn_factory` (like the judge) so the judge sees the just-written claim
  (shared rollback conn in tests; committed-then-judged in prod).

## Backlog check (answer to "anything due before/while M12.1?")
NO unmet prerequisite for M12.1. Its prereqs were all handled in pre-flight (the frozen `core.retrieval`
seam, PF-1 compliance seam, PF-2 side-table decision, PF-6 tier_plan fix) + the M9.3/M5.1/M8 blockers
(done). The CLAUDE.md backlog items that mention M12 are **M12.2/handoff/M13** consumers, due before
**M12.2**, NOT M12.1: (a) `faithfulness_verdict.answering_model` (M12.2 provenance index cites the
judge model); (b) M9.2×M1.2 merge conflict-equality (M12.2 `field_conflicts`); (c) M9.5 retention-EXPIRED
merge exclusion (handoff consuming sensitive personal claims — handled by M10.5 tombstone-before-read,
which M12 reads after). PreSpendGate AC-6 routing names M4/M8/M11, not M12 (the positioner isn't a
resolver spend path — `account.value_narrative` has empty tier_plan).

## Next (M12.2, not now) — PAUSED after M12.1 per instruction.
