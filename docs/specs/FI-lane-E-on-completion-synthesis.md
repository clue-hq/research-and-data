# FI Lane E — On-completion prose synthesis (`account.summary`, `contact.overview`) + the L1 fix

**Status: DRAFT — awaiting founder sign-off on §7 open decisions. Design grounded in two read-only Opus code studies (2026-08-08: M12-reuse study; finalization-trigger study); every baseline fact carries a file:line citation from them.**

Date: 2026-08-08. Branch: `platform/frontend-integration`.
Parent ruling: FI-1 §9, 2026-08-08 — **D-10 RESOLVED**: `summaryParagraphs` / contact `overviewParagraphs` render an honest empty state until the entity's deep research completes; on completion a genuine synthesis composes prose **claims** from the completed research's claims, reusing M12 machinery where it fits, never fabricated in an adapter.
Siblings: FI-2 (`docs/specs/FI-2-workspace-account-layer.md`) supplies `run_lineage`, `research_scope`, and the read layer this lane's outputs ride. Lane B owns D-4/CORS/error-envelope; Lane C owns the BFF; this lane must not build read endpoints.

---

## 0. Scope of this lane

1. **The synthesis seam itself** — the production trigger + composition unit that turns a completed entity-research job into prose claims. This is the seam M12's `Positioner` never got (it is built, tested, and has **zero production callers** — `platform/api/clue_api/narrative_wiring.py:45-55` registers only its field pack; every dependency it needs already exists at the api root).
2. **Two first tenants**: `account.summary` (persona-agnostic account prose → frontend `summaryParagraphs`) and `contact.overview` (per-contact prose → `overviewParagraphs`).
3. **The L1 fix** (`VALUE_NARRATIVE` missing from `ACCOUNT_SECTION_ORDER`) — not a dependency of the two tenants (they route to `SUMMARY`, see §1.3), but owned here because it lives in the same package and must land before *any* production narrative claim is written.
4. **Optional third tenant** (§7-D3): composing the M12.1 `Positioner` into production through the same seam.

Non-goals: read endpoints (Lane C), the D-4 absence vocabulary (Lane B — but it is a **shipping prerequisite**, §4.4), the R11 DEEP-phase bridge (fast-follow per the 2026-08-08 lifecycle ruling), any un-quarantining, scheduled/cadence refresh (M9.5 backlog item; refresh here is on-completion only).

---

## 1. Verified baseline (what the studies established)

### 1.1 Finalization: exactly one writer, one process, no existing hook

- The only writer moving `entity_research_job` to `state='terminal'` is `_record_finalization` (`platform/fleet/clue_fleet/entity_research.py:1148-1264`): receipt insert → wait-cancel → job UPDATE → task finish → one `entity_research_job_event('finalized')` (`:1247-1260`) → `_refresh_run_state` (`:1261`). **No `run_event`, no SSE, no NOTIFY, no callback seam.** `list_events`/`list_jobs` have zero production callers.
- It executes only in the **detached fleet worker** (`fleet_main`), inside `EntityResearchJobWorkHandler.handle` (`platform/fleet/clue_fleet/entity_research.py:1522-1600`), wrapped by `AccountResearchFleetWorkHandler.handle`, which already runs a synchronous post-finalize step: `fleets.reconcile(research_run_id)` at `platform/api/clue_api/account_research_fleet.py:1382`. A raising step there is caught at `:1371-1381` and **suspends the fleet** — the existing occupant of this slot defines the fail-soft discipline the synthesis step must follow. Contact twin: `ContactResearchFleetWorkHandler.handle` → `fleets.project(run_id)` (`platform/api/clue_api/contact_research_fleet.py:398-417`).
- **Process capability:** the fleet worker composes a real `LLMGateway` (`fleet_main.py:417`), the toolbelt with gateway (`:459-476`), a bound `tool_invoker` (`:494-501`), and the M9.3 judge (`run_composition.py:288-290`, `toolbelt_wiring.py:2620-2624`). The HTTP process composes **no gateway** (`projections_main.py:60-76`) — gateway tools 422 there. **Any LLM-touching synthesis must live in the fleet process.**
- The project-run phase machine never reaches DEEP-complete for M8D fleets (R1 quarantine; R11 is fast-follow), so the trigger **cannot** ride phase transitions.

### 1.2 What "complete" means

`finalization_outcome` is chosen deterministically at propose, never by the model: account `NEEDS_REVIEW if review_flags or unresolved else (COMPLETED if committee_status == 'complete')` (`platform/api/clue_api/account_entity_research.py:518-528`); contact `:677-686`. **`COMPLETED` ⟺ zero unresolved admitted fields ∧ zero review flags ∧ (account) committee complete** — no extra column needed. `NEEDS_REVIEW` = research finished, receipt accepted, spend reconciled, ≥1 unresolved field or open review item; its claims are durable and servable. The fleet tolerates up to 50% `needs_review` before suspending (`account_research_fleet.py:94`) — gating synthesis on `COMPLETED` only would skip most real jobs (§7-D1).

### 1.3 The read side is ready-made

- Account `SUMMARY` and contact `SUMMARY` sections are in **both** authority tables (`narrative/research_views.py:244,257`; `claimstore/research_view_routes.py:23,32`) with **zero routed fields** — today they render exactly the D-10 empty state: `availability=UNKNOWN, reason_codes=("unresearched",)` (`research_views.py:471-476,645-669`). Lane E registers the first routes into them; **no section-order change needed, so the two tenants do not depend on the L1 fix.**
- The live C7 view recomposes per request (no cache, no model — `research_views.py:401-402,427-575`); a new routed, merge-winning claim appears with zero frontend action. Snapshots are immutable — they need `compose_dossier`/`recheck_research_view` to refresh.
- The canonical merge serves a tier-4 claim only when `verification_status = VERIFIED` (`claimstore/merge.py:103,133-140`) and excludes weak-bound contact claims (`merge.py:141-146`). **An unjudged or judge-rejected prose claim is stored but invisible everywhere** — the honest empty state degrades gracefully with no adapter suppression.

### 1.4 L1, precisely

`account.value_narrative` routes to `ResearchSectionKind.VALUE_NARRATIVE` (`narrative/fields.py:103-109`), legal per `_ACCOUNT_SECTIONS` (`research_view_routes.py:21-29`) but absent from `ACCOUNT_SECTION_ORDER` (`research_views.py:241-251`); the composer raises `section_not_allowed_for_subject` (`:501-504`) → HTTP 404 for the **whole account view** (`research_view_api.py:262-266`), also killing the contact content-handoff bridge (`contact_content_handoff.py:139-152,522`). Trigger conditions: the first **VERIFIED** narrative for the requested product+run. The route table and the order table are two authorities that must agree and don't. The pack (and thus the route row) is registered in **both** production processes today (`fleet_main.py:401`, `projections_main.py:59`) — only the writer is missing, which is what makes L1 latent-but-armed.

### 1.5 M12 reuse verdicts (per component)

Reusable as-is: `claim_support` write/read + faithfulness citations (`narrative/support.py:58-158`); judge integration (two lines over the injected protocol, `positioner.py:442-443`); `assemble_evidence_span` (`:167-179`; empty client side is valid); prompt-as-data plumbing incl. untrusted-data fencing and the empty-beats-fabricated parser contract (`prompts.py:43-46,55,154-159,196-208`); `fact_to_text` (`:211-216`); the policy cascade (`policy.py:122-173`); the claim-write mechanics (insert-or-supersede in one txn, `positioner.py:406-440,455-492`).
Reusable with parameter changes: the batched `current_values` evidence read (`:246-255`) over a different field list; the coverage-gap discipline (`:338-344,384-387`).
Net-new: both prompts + parser (persona/angle machinery is meaningless here; `_SYSTEM_V1` hardcodes a 2-4-sentence single `argument`); the iteration shape (no committee loop); the supersede keys (§2.5); skipping the mandatory client-KB retrieval (`min_client_chunks ≥ 1` is wrong for neutral prose — and its absence is what makes the summary product-neutral); the trigger + composition root (nothing exists).

---

## 2. Design

### 2.1 Trigger — the post-finalize fleet slot (chosen over the alternatives)

A `ProseSynthesisStep`, composed at the fleet composition roots (`account_research_fleet_composition.py:203-215` / the contact equivalent), invoked from the fleet work handlers **immediately after** their existing post-finalize step (`reconcile` / `project`), only when the job reached `terminal` this handling cycle:

- **Fail-soft, absolutely.** Wrapped in catch-all + log + metric (`research.prose_synthesis.failed`), mirroring the emitter discipline (`run_events_wiring.py:119-125`). A synthesis failure must never travel the `:1371` suspend path; the job's terminality is already durable, and the next completion (or a manual re-run) retries.
- **Same process, after the finalize transaction commits** — never inside `_record_finalization` (pure-DB package, import-linter isolated, holds `FOR UPDATE` locks).
- Rejected alternatives, recorded: (a) inline-in-txn (locks + layering); (c) a new wake-source poller (R11.2's shape — more moving parts, a differently-typed waker seam, and the wake loop is gated behind provider flags; revisit if we ever need retry-with-backoff semantics); (d) opportunistic-on-read (the composer is model-free by contract and the HTTP process has no gateway); (e-pure) an agent-called tool only (no production chat surface yet — Lane D).
- **Invocation goes through the toolbelt**: the step calls a new governed tool `synthesize_entity_prose@1` via the bound `tool_invoker` (`fleet_main.py:494-501`), so every synthesis is journaled, A9-idempotent, and later invocable by the Lane-D deepagent or an operator with zero new plumbing.

### 2.2 Idempotency

A9 key = `uuid5(LANE_E_NAMESPACE, f"{job_id}:{field_key}")` — one job = one subject = one terminal receipt (`entity_research_job_finalization` is `UNIQUE(job_id)`), so replays, duplicate task delivery, and worker crash-rerun collapse to one synthesis. All M8D ids are content-addressed uuid5 (`account_research_fleet_launch.py:387-479`), so a *relaunch with the same request* is the same ids (same key — correctly deduped) and a *new research pass* is new ids (new synthesis — correctly superseding, §2.5).

### 2.3 Write engine — positioner-pattern field claims (chosen over `DerivedClaimService`)

The composition unit (proposed module: `subsystems/research/clue_research/narrative/prose.py`, same import boundary as the package) follows the positioner shape: evidence read → prompt → parse → claim + `claim_support` row in one txn → judge.

- **Claim shape:** tier-4 `FIELD_CLAIM`, `extraction_method=LLM_SYNTHESIS`, `tier_plan=()`, `gate="faithfulness"`, `single_source_sufficient=True`, `corroboration_min=1`, synthetic `source_url="clue://narrative/prose"`, `run_id` = the triggering job's `research_run_id` (already registered in `run_lineage` as `kind='entity_research'` by FI-2 slice 0 — attribution rides existing lineage, nothing new).
- **Why not `DerivedClaimService`** (`research_derivations.py:95-228` — built, judged, atomic, zero callers): DERIVED claims are visible only to the C7 derived-claim reader; the **MVP read surface is the FI-2 BFF over `current_values`**, which serves merge-winning *field* claims natively. A VERIFIED tier-4 field claim flows through the list/detail endpoints with zero extra read machinery; a DERIVED claim would need a second read path. Recorded as the alternative; its three-phase `(workspace_id, operation_id)` keying is superseded by §2.2's A9 key. The VERIFICATION-phase judge guard (`verification/handler.py:235` — tier-4 non-DERIVED) is compatible: verdicts are cached on `(claim_id, judge_model, prompt_version)`, so the inline judge call and any later phase pass cannot double-judge.
- **Judge inline, positioner-style** (`positioner.py:442-443`): verdict drives `verification_status`; `supported ≥ threshold` → VERIFIED → servable; anything else → invisible → empty state stands. Faithfulness citations for provenance display come from `read_faithfulness_citations` (`support.py:142-158`).

### 2.4 The two tenants — field registration (routes are immutable; get these right first time)

| | `account.summary` | `contact.overview` |
|---|---|---|
| `value_type` / schema | `object`: `{"paragraphs": [str, …] (minItems 1), "prompt_version": str, "synthesized_from_job_id": str, "research_outcome": str}`, `additionalProperties` open (the `fields.py:55-68` rationale) | same shape |
| `reuse_scope` | **TENANT_PRIVATE** (must be declared — `FieldClass.ACCOUNT` defaults PUBLIC_FOOTPRINT; post-B3 the classification is privacy-only, PUBLIC buys nothing and risks a leak) | TENANT_PRIVATE (contact default — correct) |
| `research_scope` | **PROJECT_NEUTRAL** ⚠ §7-D2 (persona-, product-, client-KB-free ⇒ a world-fact summary; matches the one-detail-view MVP ruling) | PROJECT_NEUTRAL (same argument) |
| `freshness_ttl` | 90d (narrative precedent, `fields.py:89`) | 90d |
| route | `ACCOUNT` / `SUMMARY`, `context_scope="subject_current"`, `product_mode="neutral_or_exact"` — deliberately the **opposite** of the narrative's pinned/exact route | `CONTACT` / `SUMMARY`, same |
| `product_id` on claim | `None` (product-neutral) | `None` |

### 2.5 Supersede keys (the hardest call — the FI-2 studies' collision warning applies)

The narrative's `(persona, icp_spec_version[, icp_key], product_id)` key (`positioner.py:509-521`) is wrong for both tenants. Being PROJECT_NEUTRAL, each keeps **exactly one live claim per `(entity, field, workspace)`** — no persona/product/ICP/project dimension. Any new completed research pass on the entity supersedes the prior prose (refresh-on-completion; the refresh benefits every project, per FI-2 R3). Cross-project coexistence concerns don't arise *because* the field is neutral; if §7-D2 flips either field to `project_relative`, the key must gain `project_id` (FI-2 §6.4 discipline) in the same change — flag this pairing in the code comment.

### 2.6 The two prompt shapes (prompt-as-data, versioned, fenced)

Both: system prompt with the positioner's GROUNDING-non-negotiable + SECURITY/untrusted-data clauses; output contract `{"paragraphs": ["…"]}`; **an empty `paragraphs` is the correct refusal**; parse failure ⇒ no claim + `research.prose_synthesis.coverage_gap` metric. New parser (the existing one looks only for `argument`).

- **`account_summary_v1`** — role: neutral company analyst. Input: `<<<ACCOUNT_FACTS>>>`-fenced `fact_to_text` renderings of the merge winners (with evidence spans) over the routed account field set — `ABOUT` fields (`core.account_name/industry/employee_count/hq_location/company_about/…`) + `INSIGHTS` fields (`account.recent_funding/operational_pain/strategic_moves/resonance.*`). **No client capabilities, no persona, no angle** — that absence is what makes the output neutral. Target: 2–4 paragraphs (what the company does; scale/footprint; recent trajectory/funding; operational context). Below `min_facts` (default 3) ⇒ refuse (gap, no claim).
- **`contact_overview_v1`** — role: neutral profile writer. Input: fenced `CONTACT_FACTS` (`contact.current_title/job_function/job_level`, career/education/publication facts, **eligible** facets per §4.1) + one fenced `ACCOUNT_CONTEXT` line (account name + one-line about). Target: 1–3 paragraphs. Below `min_facts` (default 2) ⇒ refuse.

Evidence span: `assemble_evidence_span(facts, chunks=[])` — reused unchanged.

### 2.7 Outcome gate

Synthesize when the job lands `terminal` with outcome ∈ **{`completed`, `needs_review`}** (recommendation — §7-D1), stamping `research_outcome` into `value_json` so the claim is honest about its basis. Never on `cancelled`. Rationale: `needs_review` claims are durable, verified, and servable; the judge gates the prose regardless; and completed-only would skip most real jobs (§1.2).

---

## 3. The L1 fix (rides slice E0)

Add `ResearchSectionKind.VALUE_NARRATIVE` to `ACCOUNT_SECTION_ORDER` (`research_views.py:241-251`), placed after `INSIGHTS`, before `COMMITTEE`. One tuple entry + a regression test asserting a routed-but-unordered section raises `section_not_allowed_for_subject` (no test covers this today) and that a VERIFIED `account.value_narrative` claim composes instead of 404ing. Chosen over re-routing: the route is already legal in the *other* authority table (`research_view_routes.py:21-29`), `DossierBlockKind.VALUE_NARRATIVE` is a frozen treaty enum (`clue_core/enums.py:217`), routes are immutable-by-registration (redefinition raises, `research_view_routes.py:118-124`), and the per-persona pinned narrative is semantically wrong for the persona-agnostic SUMMARY. **Visible contract change:** every account view gains an empty `VALUE_NARRATIVE` section (`UNKNOWN/unresearched`) — the frontend must tolerate it (D-4's vocabulary covers this; recorded into `apps/frontend/docs/api-contracts/accounts.md` at landing).

---

## 4. Governance constraints (standing rules, restated as build requirements)

1. **G6 — sensitive facets never enter the prompt.** The contact input set excludes SENSITIVE-use-class fields (`contact.facet.causes`, …) and any claim not display-eligible under the fail-closed gates; facet inclusion requires the M10 use-gate cleared (the positioner's `is_outreach_promotable` discipline, `positioner.py:346-351`, applied with display-eligibility semantics).
2. **Identity binding on `contact.overview`:** stamped STRONG only when *every* cited contact claim is STRONG-bound; otherwise WEAK — and the merge then correctly refuses to serve it (`merge.py:141-146`). Weakly-evidenced prose degrades to the empty state, never to unattributable prose.
3. **G7:** nothing in this lane counts signals; noted for the adjacent `recentSignalsLabel` mapping only.
4. **D-4 is a shipping prerequisite** (Lane B): the current Zod floors (`z.array(z.string().min(1)).min(1)` — `account-detail.ts:50`, `account-contact.ts:53`) cannot express the empty state this whole design produces. Lane E's backend slices can land first; the *frontend* rendering of either state waits on D-4.

---

## 5. Slices

**E0 — L1 fix + field packs + empty-state proof.** The §3 fix + regression tests; register both fields/routes (a `prose` pack loaded via `narrative_wiring` — PF-7 pattern); test: composed account & contact views render `SUMMARY` as `UNKNOWN/unresearched` with zero prose claims (the D-10 empty state, asserted at the composer).
AC: db-smoke green; route rows present in both processes; L1 regression red→green; no behavior change anywhere else.

**E1 — the seam + `account.summary`.** `prose.py` unit (evidence read → prompt → parse → claim+support → judge), `synthesize_entity_prose@1` tool, `ProseSynthesisStep` composed into the account fleet handler post-`reconcile`, A9 keying, fail-soft discipline, metrics.
AC (two-project fixture, per FI-2 §10): job → `completed` ⇒ one VERIFIED `account.summary` claim citing ≥3 support claim ids, visible in the live C7 view's SUMMARY section and in `current_values`; judge-rejected synthesis ⇒ zero visible change (empty state stands); handler exception injected into the step ⇒ job stays terminal, fleet **not** suspended, failure metric emitted; re-delivery of the same task ⇒ exactly one claim (A9); a second completed job on the same account ⇒ supersede, one live claim.

**E2 — `contact.overview`.** Same seam, contact fleet handler post-`project`, the §4.1 eligibility filter, the binding-stamp rule.
AC: SENSITIVE facet present on the contact ⇒ provably absent from the prompt payload and the evidence span; all-WEAK inputs ⇒ claim born WEAK and not served (merge test); otherwise as E1.

**E3 (§7-D3) — compose the Positioner.** Construct `Positioner` with the existing api-root seams (`build_client_knowledge_retriever`, `ProductionHandoffCommitteeReader`, `FaithfulnessJudgeImpl`) and invoke it from the same post-finalize step for account jobs, behind its own flag. Depends on E0 (L1). **In scope for this lane** (founder directive 2026-08-08: no MVP scope cuts; a built module ships end-to-end — speed comes from parallelization, not subtraction). Its one hard gate is a *correctness ordering*, not a cut: the narrative supersede predicate must gain `project_id` per FI-2 §6.4 **before** any production second-project narrative run — that change is FI-2 slice 3's, and E3 must not land ahead of it (parallelize the build; serialize only the landing).

---

## 6. Testing strategy

Ledger- and claim-based, never log-based: A9 rows + `claim_support` + verdict rows are the assertions. The canonical fixture extends FI-2's (two projects, one account) with: a `needs_review` finalization, a judge-refusal path (mock gateway returning ungrounded prose), a SENSITIVE-facet contact, an all-WEAK contact, and a crash-rerun (duplicate task delivery). Empty-state assertions run at the composer *and* (once Lane C lands) the BFF, so a read-layer bug can't mask a substrate bug.

---

## 7. Open decisions (founder)

- **D1 — outcome gate:** synthesize on {`completed`, `needs_review`} (recommended; `research_outcome` stamped) vs `completed` only (skips most real jobs today).
- **D2 — species:** `account.summary` and `contact.overview` as PROJECT_NEUTRAL (recommended: one live prose per entity, refreshed on any project's completion, serving every lens — matches the MVP one-detail-view ruling) vs PROJECT_RELATIVE (per-project prose, coexisting, lineage-grouped; flips §2.5's supersede key in the same change).
- **D3 — E3 in or out of MVP:** **recommend IN** (amended 2026-08-08 per the founder's no-shortcuts directive: the synthesis module ships end-to-end; the original "out" recommendation was MVP thrift, not architecture). E3 is built in parallel with E1/E2 and lands after FI-2 slice 3's project-scoped supersede change — a sequencing gate that protects the two-lens model, not a scope cut.
- **D4 — L1's visible contract change** (the empty VALUE_NARRATIVE section on every account view) — acknowledge.

---

*Ratification log: (pending).*
