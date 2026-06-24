# M11 — Tier-4 LLM Synthesis — implementation plan (WS-A · `m11/tier4-synthesis`)

**Base:** `integration/phase3-preflight-v1` @ `1902210` (frozen pre-flight). **Migrations: ZERO.**
**Owns:** `resolvers/grounded.py` (shared substrate), `resolvers/exa/`, `resolvers/parallel/`,
`synthesis/` (M11.3 wiring), `api/synthesis_wiring.py` (the PF-7 home).
**Must NOT touch:** `core/`, the `claim` DDL, `claimstore/packs.py` (PF-6 base), `compliance/`,
`narrative/`, `merge.py`. Must never write a `contact.facet.*` / `entity_type=contact` claim.

This is the **last** capability in the build order (substrate §11 step 6): the tier-4 resolvers
that fill the fields no deterministic/official/third-party source can answer — `account.operational_pain`,
`account.strategic_moves`, `account.resonance.*` — *behind* the verification layer M9 already built.
The resolvers implement only the `Resolver` seam (M0.2); every gate (pre-spend, faithfulness judge,
freshness, evals) wraps them uniformly without per-provider code.

---

## How M11 plugs into seams that already exist (nothing new in the engine)

| Seam (owner) | What M11 does with it |
|---|---|
| `core.Resolver` protocol — `tier:int` + `resolve(entity,field)->list[Claim]` (M0.2) | implement two tier-4 instances; **synchronous**, connection-less, like every resolver |
| Source registry `bind_resolver(source_key, r)` (M4.2) | bind to the **already-seeded** `exa_deep` / `parallel_task` manifests; resolver self-registers (`resolvers → sources`) |
| Waterfall `resolve_field` (M4.1) | dispatches through `get_resolver("exa_deep")`; `_finalize` stamps `source_key`/`run_id`/`research_mode`; `stamp_reuse` stamps the cross-tenant scope. M11 writes nothing else. |
| `account_claim(...)` factory (M0.2) | the only way claims are built — never a hand-built `Claim` |
| `resolvers/http.get_json` + `resolve_credential` (M4 decision 3b) | the shared sync HTTP transport + `auth_ref→secret`; Exa/Parallel use their **own** keys (`CLUE_EXA_API_KEY`/`CLUE_PARALLEL_API_KEY`), **not** the OpenRouter gateway (conventions §2 carve-out) |
| `resolvers/live.AccountLookup` (M4.4) | the `entity_id → AccountEntity` map (canonical domain/name/aliases/hq_geo) for **target-lock**; the orchestrator injects it |
| `obs.traced_step` (M0.5) | the waterfall already opens `resolve.<source_key>`; the resolver opens a nested provider span with retrieval count / citation count / outcome |
| `field_definition` rows for the synthesis fields (PF-6, already seeded) | `tier_plan=("exa_deep","parallel_task")` for pain/moves; `("exa_deep","parallel_task")` for `resonance.culture` — M11 binds the resolvers those keys name |

**Critical model facts (from `core/claim.py`) the resolver must honor**
- tier-4 ⟺ `extraction_method == llm_synthesis` (the model raises otherwise).
- `llm_synthesis` **requires** a `source_url` (URL-required methods).
- `evidence_span` is *optional at construction* but a tier-4 claim with no span **can never be
  promoted** (`can_be_promoted`). M11's contract is **stronger than the model**: the resolver
  emits a non-empty span **always**, and drops any candidate lacking one (empty is correct).
- claims are born `verification_status = unverified` (no self-promotion — the judge owns the verdict).
- `account.resonance.*` is `TENANT_PRIVATE` by default → the waterfall's `stamp_reuse` needs a
  `tenant_id` (engine concern, not the resolver's). `operational_pain`/`strategic_moves` are
  `ACCOUNT` class → `PUBLIC_FOOTPRINT`.

---

## Architecture: one shared substrate, two thin provider backends (mirrors tier-1)

Tier-1 is `DeterministicResolver` (provider-agnostic) over a per-provider `EnrichmentBackend`
(`resolvers/base.py` + `resolvers/live.py`). Tier-4 is the **same split**, one tier up:

```
resolvers/grounded.py   GroundedSynthesisResolver (tier=4, provider-agnostic)
                        + SynthesisBackend protocol + SynthesizedField/SynthesisResult shapes
                        + the tier-4 disciplines enforced ONCE (grounded-only, target-lock)
resolvers/exa/          Exa-specific build_request + normalize  (+ HttpSynthesisBackend over get_json)
resolvers/parallel/     [M11.2] Parallel-specific build_request + normalize — reuses grounded.py verbatim
```

DRY consequence: the swap test (Exa↔Parallel↔stub) and every tier-4 discipline live in
`grounded.py`; a new provider is just the two pure pieces + `register_*`. This is the literal
"providers are just resolvers; nothing downstream knows which" property made concrete one tier up.

### `resolvers/grounded.py` — the shared substrate (M11.1 ships it; M11.2 reuses it)

- **`SynthesizedField`** (frozen): `field_key`, `value`, `source_url` (min_length 1), `evidence_span`
  (min_length 1, the exact retrieved passage), `retrieved_text` (min_length 1, the source text the
  span was drawn from — so the substrate can *prove* grounded-only and target-lock), `confidence`.
  A backend that cannot produce a citation+span for a value **does not return that field** (the
  parametric-listing prohibition enforced at the type boundary).
- **`SynthesisResult`** (frozen): `fields: tuple[SynthesizedField,...]`, `cost_cents` (the realized
  per-call cost the budget engine M7.5 reads).
- **`SynthesisBackend`** Protocol: `synthesize(account, field) -> SynthesisResult`. The backend owns
  the entity-bound query construction (target-lock at the query level: `site:domain`, canonical
  name + `hq_geo`, `aliases[]`) and the provider call + normalization. Empty result = hard miss;
  transient fault raises `RetryableResolverError`.
- **`GroundedSynthesisResolver`** (`tier = 4`): the provider-agnostic resolver. `resolve`:
  1. account-only firewall — non-account entity / contact-class field ⇒ `[]` (contact synthesis is
     M10-governed; this resolver writes **account** claims only).
  2. `AccountLookup` → `AccountEntity` (None lookup ⇒ wiring `ResolverError`; unknown id ⇒ `[]`).
  3. `backend.synthesize(...)`.
  4. **grounded-only guard:** drop any field whose `evidence_span` is absent from its `retrieved_text`.
  5. **target-lock guard:** drop any field whose evidence is *off-entity* — keep iff the
     `source_url` host equals the account's registrable `primary_domain` **OR** the canonical name /
     an alias token appears in the retrieved text/span (the same-name-competitor trap → rejected,
     not blended). Reuses the host-normalization shape from `firecrawl` (DRY backlog: one
     `normalize_host` later — do **not** refactor `core`/siblings on this branch).
  6. build one tier-4 `account_claim` per **distinct value** (`source_tier=4`,
     `extraction_method=llm_synthesis`, the span, `confidence`, realized cost on the first claim
     only — the waterfall sums per-claim cost), `unverified`. Dedup of Exa-vs-Parallel and
     corroboration are M9.2's job, not the resolver's.
- **`register_synthesis_resolver(source_key, backend, *, accounts)`** — binds a
  `GroundedSynthesisResolver` to a `source_key` (the per-call default cost is read from the **seed
  manifest**, exactly like `register_deterministic_resolvers`, so realized cost never drifts from
  the budgeted manifest cost).

### `resolvers/exa/__init__.py` — M11.1 (the only NEW provider this turn)

- **`ExaDeepConfig`** (frozen, defaulted): `endpoint`, `model`, `num_results` (retrieval depth),
  `timeout_s`, `retries`, `highlights_per_result`, `min_confidence`, `default_cost_cents`. Policy as
  data — injected at the api root; swapping Exa for another grounded-synthesis provider is a
  config/registry change. Kept **local to `resolvers/exa/`** (not `config/schema.py`, which M10
  extends) to keep M11 self-contained.
- **`build_exa_request(account, field, token, cfg)`** — the entity-bound query (target-lock):
  `site:<primary_domain>` + canonical name + `hq_geo` disambiguators + `aliases` + a field-intent
  phrase; POST to the Exa research/answer endpoint with highlights on. Pure; unit-tested.
- **`normalize_exa_response(payload, field, cfg)`** — map each returned result/citation to a
  `SynthesizedField`: `value` = the highlighted passage (the grounded value), `evidence_span` = that
  highlight, `source_url` = the result url, `retrieved_text` = the result text/highlight context,
  `confidence` = the normalized Exa score. A result with no highlight/url (no grounding) is dropped.
  Pure; unit-tested against fixtures (the recorded-fixture path — finalized when live creds land).
- **`HttpSynthesisBackend`** — a generic `SynthesisBackend` over `get_json` (the network is the
  `# pragma: no cover` boundary; CI injects a backend double), parameterized by `build_request`/
  `normalize`/`source_key`/`auth_ref` — the tier-4 analogue of `HttpEnrichmentBackend`.
- **`register_exa_deep_resolver(*, accounts=None, backend=None, config=None)`** — wires the Exa
  backend (or an injected double) into `register_synthesis_resolver("exa_deep", …)`.

### `api/synthesis_wiring.py` (PF-7 home) — M11.1 fills the Exa binding

`register_synthesis_wiring()` calls `register_exa_deep_resolver(accounts=…)`. M11.2 adds the Parallel
binding; M11.3 adds the judge-gated synthesis workers + verification-health metric. Until then the
pack/field rows already exist (PF-6), so binding the resolver is all M11.1 needs at the root.

---

## Acceptance-criteria → test mapping (M11.1, `tests/resolvers/test_exa_deep.py` + `test_grounded.py`)

| AC (spec M11.1) | Test |
|---|---|
| satisfies `Resolver`, `tier==4`, registerable | `isinstance(r, Resolver)`, `r.tier==4`, bound + reached via the waterfall |
| tier-4 claim shape (span, url, conf∈[0,1], cost>0, method) | end-to-end resolve of `account.operational_pain` |
| evidence-span invariant + empty retrieval ⇒ `[]` | empty backend ⇒ `[]`; every claim's span non-empty |
| target-lock (same-name competitor) | off-domain record with no name match ⇒ excluded; on-domain ⇒ kept |
| grounded-only | span absent from `retrieved_text` ⇒ dropped; survivor's span ⊆ a retrieved source |
| swap | replace with a stub tier-4 backend/resolver — waterfall call-site unchanged |
| budget | realized `cost_cents` reported; budget envelope stops further tier-4 spend |
| no self-promotion | all claims `verification_status == unverified` |
| tracing | nested provider span with field_key/entity_id/cost/retrieval count/outcome |

All resolver tests are **hermetic** (a `SynthesisBackend` double — no live call, no key), exactly
like `tests/resolvers/test_firecrawl_site.py`. End-to-end tests skip without `CLUE_DATABASE_URL`.

---

## M11.2 (Parallel Task) — IMPLEMENTED

A *second*, independent tier-4 provider so the subsystem is not single-vendor for its least-trusted
source, and so two independently-grounded tier-4 values for one field give the faithfulness judge
(M9.3) a far stronger signal than a single-source guess (substrate §4/§12). Parallel Task is bound
behind the **same** `GroundedSynthesisResolver` seam as Exa — the concrete proof the tier-4 seam is
provider-agnostic.

### What M11.2 adds / changes

- **`resolvers/parallel/__init__.py`** (NEW) — the Parallel-only pure pieces, mirroring `exa/`:
  - `ParallelTaskConfig` (endpoint / `processor` quality-cost tier / timeout / retries /
    `min_confidence` / the categorical-confidence bands / `default_cost_cents`) — policy-as-data,
    injected at the api root. `CLUE_PARALLEL_API_KEY` (its own key), **not** the OpenRouter gateway.
  - `build_parallel_request` — POSTs the **shared** `entity_query(account, field)` as the task
    `input` with basis (citations + reasoning + confidence) enabled, key as `x-api-key`.
  - `normalize_parallel_response` — maps each **cited excerpt** to one `SynthesizedField`:
    `value ≡ evidence_span ≡ excerpt` (grounded-only *by construction* — a claim's value is always
    real, cited, retrieved text, exactly like an Exa highlight), `source_url` = the citation URL,
    confidence from the basis entry. Parallel's `reasoning` is collected onto
    `SynthesisResult.reasoning` (→ the trace span) and is **never** an evidence span.
  - `_coerce_confidence` — categorical (`high`/`medium`/`low` → configured bands) **or** numeric
    (via the shared `coerce_confidence`); `make_backend`; `register_parallel_task_resolver`.
- **`resolvers/grounded.py`** (the shared substrate, generalized to serve *both* providers — DRY):
  - `SynthesisResult.reasoning: tuple[str, …]` — a provider's synthesis *rationale*, surfaced on the
    resolver's `synthesis.<source_key>` span (capped) for audit and **structurally barred** from
    becoming an `evidence_span`: `_build_claims` reads only `SynthesizedField.evidence_span` (a
    cited passage), never `result.reasoning`. "Only cited source text qualifies as evidence; the
    LLM's reasoning never does" (substrate §1/§6) is now enforced by the *type*, not by discipline.
  - `entity_query` / `field_intent` / `_FIELD_INTENT` — the entity-bound (target-locked) query
    builder, **extracted from `exa/`** so Exa and Parallel issue the identical query (only the wire
    envelope differs). `as_list` (JSON-array guard), `dollars_to_cost_cents` (USD→cents math) and
    `cost_cents_from_cost_dollars` (the `costDollars.total` reader) — extracted so both providers'
    normalizers share one copy of the cost-parse + JSON-guard logic (no per-provider duplication).
- **`api/synthesis_wiring.py`** — `register_synthesis_wiring()` now also binds Parallel Task; running
  one, the other, or both (cross-provider convergence) is a registry/config choice, not code.
- **`resolvers/__init__.py`** — exports the `parallel` sub-package + its config/registration symbols.
- **`tests/resolvers/test_static.py`** — two new long Parallel public symbol names added to the
  secret-shape allowlist (`≥24`-char identifiers trip the opaque-token oracle, like the Exa names).

### Why "cited-excerpt-as-value" (not "synthesized-narrative-as-value")

The spec lists Parallel's output as *value + reasoning + citations + confidence* and says **each
citation becomes the claim's `source_url` + `evidence_span`** (mandatory-span rule), reasoning →
trace. Making the *cited excerpt* the claim value (rather than the LLM's free-hand narrative) is the
tightest reading of the architecture's core bet — *the LLM may plan/expand queries but may never be
the source; no value without a backing passage* (substrate §0/§4/§13). It keeps Exa and Parallel
**semantically uniform** (both emit grounded-passage claims), so the distinct-value dedup, target-
lock, and grounded-only guards in `grounded.py` apply unchanged, and the synthesized rationale is
relegated to the (un-promotable) trace where it cannot ground a claim.

### AC → test mapping (`tests/resolvers/test_parallel_task.py` + `test_grounded.py`)

| AC (spec M11.2) | Test |
|---|---|
| satisfies `Resolver`, `tier==4`, registers a valid manifest | `register_synthesis_wiring` binds `parallel_task` at tier 4; reached via the waterfall |
| claim shape (span from a citation, url, conf, cost, method) | e2e resolve of `account.strategic_moves` |
| **reasoning-vs-span** (reasoning → trace, never a span; reasoning-only → dropped) | `normalize_reasoning_is_captured_…`, `reasoning_only_entry_yields_no_field`, `reasoning_is_never_emitted_as_a_claim_through_resolve`, + grounded `reasoning_is_surfaced_on_the_span_but_never_becomes_a_claim` |
| **independence** (Exa + Parallel → 2 distinct claims, distinct `source_url`s, each own span) | `independence_exa_and_parallel_yield_distinct_grounded_claims` |
| **provider-agnostic swap** (call site unchanged whichever is bound) | bound behind the shared `GroundedSynthesisResolver`; the M11.1 e2e swap test covers the seam |
| grounded-only / target-lock / no-self-promotion / empty-on-miss | inherited from `grounded.py` (covered in `test_grounded.py`) + parallel normalize drop tests |
| budget (realized `cost_cents`; timeout/retry honored) | `make_backend_threads_timeout_and_retries`, `transient_http_fault_propagates`, e2e `budget_envelope_stops_tier4_spend` |
| categorical + numeric confidence | `normalize_categorical_confidence_bands`, `normalize_numeric_confidence_is_coerced_and_clamped` |
| tracing (provider, field_key, entity_id, citation count, reasoning, cost, outcome) | `parallel_span_records_reasoning_and_dims`, `…no_reasoning_attr_when_backend_returns_none` |

All resolver tests are **hermetic** (a `SynthesisBackend` double — no live call, no key); e2e tests
skip without `CLUE_DATABASE_URL`. The Parallel request/response shape is the documented assumed
contract (the recorded-fixture path), finalized against live fixtures when credentials land — kept
isolated in `build_parallel_request`/`normalize_parallel_response` so finalizing it is a normalize
edit, never a seam change.

### Deferred from M11.2 (unchanged from the M11.1 follow-ups)

`corroborations` is a tier-≤3 contract (conventions §4, substrate §1/§6) — cross-provider tier-4
convergence is a confidence/judge signal, **not** an increment to the tier-≤3 corroboration count
(M9.2 owns that decision). The resolver never dedups Exa vs Parallel — that is the merge/verification
path's job. D7 (default to one provider with the other as fallback, vs both) is a config/economics
choice; the wiring binds both, the Source Planner (M4.6) chooses.

## M11.3 (judge-gating glue) — deferred, lives in `synthesis/`

Field rows already seeded (PF-6). M11.3 adds: the mode-M2 synthesis aspect workers, the
`pre_spend → resolve → corroboration → faithfulness → promote` ordering (PF-7
`VERIFICATION_GATE_ORDER`), the Pass-B-only guard, the personal-data firewall assertion, the
"share of tier-4 claims passing the judge" metric (Doc C §6 → M13.4), and the M9.6 golden-set rows.

## Integration notes (carry to the M11→M10→M12 join)
- Wire `exa_deep`/`parallel_task` resolve through `PreSpendGate.check` at the api root (closes M9.1
  AC-6 for the tier-4 spend path).
- `exa_deep` stays `entity_scope=BOTH` (PF-8 dropped): contact-facet synthesis is a **separate**
  M10-governed resolver. M11's account-synthesis resolver returns `[]` for contact entities, so
  binding it to `exa_deep` cannot leak a contact claim. If contact synthesis must share the key, the
  integration owner reconciles the binding (last-write-wins) or splits the manifest key.
- DRY backlog (`normalize_host` ×3) is a post-integration cleanup PR — not on this branch.
