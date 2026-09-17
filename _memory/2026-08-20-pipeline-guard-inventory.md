# The complete pipeline guard inventory (2026-08-20)

**Question asked:** enumerate every mechanical guard from Stage-0 interview → account discovery →
account deep profiling → buying-committee discovery, and say which are necessary and which are not.

**Method:** five parallel read-only Opus audits (Stage-0/directive, discovery, deep-research engine,
committee, substrate), each verifying at `file:line` rather than grepping, plus orchestrator
spot-verification of the highest-stakes claims. HEAD at audit time: `53362c3b`.

**Scale:** roughly **500 distinct mechanical guards** on the pilot path. This note is the map; the
per-stage detail lives in the section tables below.

---

## 0. The posture that decides most verdicts (verified, not assumed)

| Fact | Proof |
|---|---|
| Live deployment is the pilot overlay | `.env`: `CLUE_PRODUCT_PATH=integration_pilot` |
| Pilot forces `budget_controls_enabled=False` | `libs/clue-config/clue_config/settings.py:94` |
| Pilot forces `verification_enabled=False` | `settings.py:93` — the M9.2/M9.3 corroboration + faithfulness phase is **off** |
| Record-only primitives | `durable/spend_posture.py:65` `cap_refusal_is_enforced`, `:105` `record_policy_refusal_skipped`, `:129` `policy_refusal_is_enforced` |

Consequence: **the money layer is already almost entirely record-only.** The guards that keep biting
are not spend caps.

---

## 1. The finding that matters most

The founder's experience — *"why these mechanical failures coming again and again"* — is real, but
the diagnosis is **not "too many guards."** Sorted by what actually stopped work:

| Class | Count (approx) | Verdict |
|---|---|---|
| (b) TRUTH/PROVENANCE floors | ~200 | **Keep.** Verbatim-span grounding, digest pinning, append-only triggers, provider-returned identity. These never once fired wrongly — every live firing was a genuine upstream bug. |
| (f) INFRA / replay / idempotency / tenancy | ~180 | **Keep.** Workspace scoping, operation identity, lease fencing, append-only. Invisible when healthy. |
| (a) HUMAN GATES | ~45 | **Keep.** Product selection (4 layers + DB trigger), ICP gate, directive confirmation, discovery seal, launch authority. |
| (e) MODEL-INPUT validation | ~50 | **Keep the rule, fix the species** on ~12 of them (see §3). |
| (c) MONEY | ~35 | **Already record-only**, with ~6 exceptions (see §4). |
| **(d) JUDGMENT encoded mechanically** | **~20** | **The actual problem.** These are the retirement candidates. |

**Three distinct diseases, not one:**

1. **Judgment gates** — the platform's quality opinion (a confidence threshold, a string match, a
   coverage ratio) deciding whether work may proceed. ~20 of ~500. This is what emptied the v8
   committee and excluded the two physician-executives.
2. **Wrong failure species** — a *correct* guard that kills the job instead of refusing recoverably.
   This caused most of the seven-fix night. The guard was right; the exit was wrong.
3. **Kill-switch inversions** — a flag meant to turn a quality gate *off* instead turns a *refusal*
   on. Two live instances found (§1a). This class is the most dangerous because the guard looks
   disabled on paper.

Everything else is the substrate doing its job.

---

## 1a. TWO LIVE INVERSIONS — found by the substrate audit, verified by me at HEAD

These are not theoretical. Both are firing on the pilot **right now**.

### Inversion 1 — `verification_enabled=False` makes every typed interview value UNWRITABLE

`platform/api/clue_api/toolbelt_wiring.py:2701-2707` (verified):

```
entailment_judge = (
    None
    if gateway is None or not resolved_settings.verification_enabled
    else FaithfulnessClaimEntailmentJudge(...)
)
```

The pilot overlay sets `verification_enabled=False` → **`entailment_judge is None`**. And
`stage0/interview.py:746-754` (verified) then does:

```
if entailment_judge is None:
    raise InterviewEvidenceRefused(reason_code=VALUE_JUDGE_UNAVAILABLE, ...)
```

**Consequence:** on the live pilot, a Stage-0 interview statement carrying any *typed* value — a
bool, a number, a list, an object — is **refused outright**. Only values that are a literal
case-insensitive substring of the user's quote can be written. The kill switch that was supposed to
*relax* verification instead **narrowed what a human client is allowed to state about their own
company**. Nobody decided this; it is an emergent interaction between the overlay and a
fail-closed branch.

This is the same failure family as the empty-Client-KB incident of 2026-08-01, wearing a new costume,
and it sits directly upstream of every other stage.

### Inversion 2 — corroboration is "off" but still blocks field resolution

`platform/api/clue_api/sumble_claim_materialization.py:159-177` (verified) constructs
`Corroborator(...)` **unconditionally** — no `verification_enabled` check — and then:

```
if corroboration.conflict or (merged is not None and merged.conflict):
    return SumbleMaterializedField(disposition=CONFLICT,
        reason_code="authoritative_sources_disagree", ...)
```

The field is **not resolved**. This fired live on Millennium: `core.hq_location` settled as a
governed conflict rather than a value.

Two aggravating facts:
- The composed VERIFICATION phase builds `corroborator=None` under the same flag
  (`verification/composition.py:83-97`), so corroboration is genuinely off *there*. One toggle,
  two surfaces, opposite behaviour.
- `merge._conflict` is **deliberately conservative** — it over-flags on purpose, on the reasoning
  that over-flagging routes to review rather than shipping bad data. That reasoning was written when
  nothing consumed `CurrentValue.conflict`. Now something does, and it blocks. The CLAUDE.md backlog
  note "no consumer reads `CurrentValue.conflict` yet" is **stale**.

**Both inversions deserve a founder ruling before the next run**, because both silently shrink output
on a path that otherwise looks healthy.

---

## 2. RETIRE — judgment gates encoded mechanically, ranked by leverage

| # | Guard | file:line | Why it should go |
|---|---|---|---|
| 1 | **Interview entailment judge vetoes the write** | `stage0/interview.py:772-780`; threshold `claim_entailment.py:128-130` | An LLM with a numeric threshold vetoing the **client's own stated fact**. Convert to a stamp — the row already carries `source_key='client_interview_judged'` and a recomputable verdict id. |
| 2 | **Judge outage / judge-not-wired also refuse** | `interview.py:764-771`, `746-754` | Must change **with** #1 or every bool/number/list value becomes permanently unwritable. A gateway blip currently blocks a human's own fact. |
| 3 | **Same verdict burned into a permanent terminal receipt** | `platform/api/clue_api/dynamic_client_kb.py:99-110` | Worse than #1: not repairable. |
| 4 | **`_MIN_CONFIDENCE = 0.3`** on extracted Client-KB claims | `official_site/materialization.py:69`, enforced `:1381`; legacy twin `claim_extraction.py:161,552` | Silently discards a claim the model grounded in a **verbatim quote**, purely because it hedged. Record the confidence; admit the claim. |
| 5 | **`DISCOVERY_SPEND` coverage floor 0.25** blocks `start_confirmed_project_run@3` | `stage0_project_tools.py:1435-1436`; floors `libs/clue-config/clue_config/stage0.py:54-66` | Requires ≥3 of 9 `client.*` fields before a project run may start, via a bare `ValueError`. ICP_SYNTHESIS was already relaxed to 0.0 on 2026-08-19; DISCOVERY_SPEND and DEEP_SPEND were not. |
| 6 | **Consecutive zero-yield stop (limit 4)** | `platform/agents/clue_agents/entity_research_runtime.py:589-592`; value at `account_entity_research_composition.py:253` | Raw raise → **job suspended**. Zero yield is an *honest research outcome* (`confirmed_missing`, `unsupported`, `explicit_null` all yield 0). On a single-source waterfall this is the most likely spurious job-killer left. At minimum it must push to finalize, not raise. |
| 7 | **Sumble §6.3 freshness/quality ladder** | `sumble_account_gaps.py:630-663` | Five platform-owned predicates (missing / conflict / confidence<0.8 / stale / no-evidence) deciding whether the agent may buy. *Mild* — recoverable, zero-spend, and genuinely anti-re-buy — but the thresholds are our taste. |
| 8 | **Canary `needs_review fraction > 0.50`** | `account_research_fleet.py:1083`; policy `:101-102` | Engine grading research quality by ratio. **Qualifier I verified: it only evaluates when `canary_terminal and held` (`:1067`)** — with `canary_size=10`, a 1–2 account pilot launch has no held remainder, so it is currently *dead*. It becomes live the moment a launch exceeds 10 accounts. |
| 9 | **Exa waterfall-ordering guards** | `account_entity_research.py:1937-1940`, `:1941-1944` | Batching/ordering economics enforced as refusals against an agent that is supposed to plan. |
| 10 | **Fast-lane category quotas / `claims_per_field` cap** | `official_site/discovery.py:44-55`; `claim_extraction.py:139` | Platform editorial taste in a table. Ordering-only today, so low risk. |
| 11 | **Corroboration-delta taxonomy purity** | `entity_research_tools.py:2150-2161` | ACCEPTED-vs-CORROBORATING mislabelling **suspends a job** for zero product value. |
| 12 | **Enrichment-value closed vocabulary** | `exa_websets_materialization.py:466-500`; `exa_websets_lifecycle.py:245-280` | A provider-returned value outside our vocabulary **raises**. Directly contradicts "truth floor is provider-returned." Should degrade to `confirmed_missing` with a reason. |
| 13 | **All-criteria-YES before buying a required field** | `sumble_discovery_gaps.py:356-383` | Our quality opinion deciding whether to buy a *required* field. Terminalizes honestly (no raise), so it is a quiet judgment gate. |
| 14 | **Launch override-homogeneity** | `account_research_fleet_launch.py:358-370` | One per-account override fails the whole launch. Neither human gate nor truth floor. (The sweep lane flags this as *borderline*: silently skipping would apply account[0]'s envelope to the others — corrupting, not merely opinionated. Needs drop-the-account semantics, not a blanket conversion.) |

### Already retired (for the record)
- **Office-placement veto** — `addc8364`, now `_location_scope_match` returns `True` under
  `company_wide` (`sumble_entity_research_tools.py:381-382`). Cost: v8, 7 candidates → 0 admitted.
- **`sumble_people` grounding filter** — `f8b8e0ee`. Cost: v9, 4 of 7 candidates.
- **`target_functions` string match** — `f8b8e0ee`. Cost: v9, both physician-executives
  (`"Clinical"` vs Sumble's `"Physician"`).
- **`target_functions` mandatory** → advisory default `()`.
- **`roles.py` LLM leaf call + `plausible=false` clamp** — retired from this path; `plausible` is
  now hardcoded `True` at `account_entity_research.py:945`. **No seniority veto and no tag remains.**
- **Memory-seam `body_rule`** — `53362c3b` (see §5).
- **Our own spend caps** — `39fcdc13`.

---

## 3. FIX THE SPECIES — correct guards with the wrong exit

The ratified rule is *model-input failures refuse recoverably; money/truth failures suspend*. These
violate it in the dangerous direction:

| Guard | file:line | Problem |
|---|---|---|
| **`EntityResearchFinalizationRejected`** | `entity_research_runtime.py:1214-1228` | Raised **after** the graph returns, outside every tool-rendering path → suspend, no repair round. The recoverable mechanism already exists 150 lines above at `:1069-1077`. **The known parked defect.** |
| Runtime parallel-tool cap | `entity_research_runtime.py:620-621` | Duplicate of the *recoverable* check at `entity_research_parallel.py:579-580`; the runtime copy fires first and kills. |
| Provider concurrency exhaustion | `entity_research_parallel.py:785-788` | Transient resource pressure, explicitly "not money" (`:167`), suspends a job that should requeue. |
| Exa account request-shape check | `exa_entity_research_tools.py:906-914` | Raises the *suspending* species for model-shaped input. `account_entity_research.py:1853-1865` exists solely to intercept one of its cases upstream. |
| `_persist_scope` evidence-ref prefix | `sumble_entity_research_tools.py:1447-1496` | A malformed prefix — a pure typo — raises `EntityResearchResultIntegrityError` (suspending). Cases 2–4 (foreign refs) are genuinely truth-class and correctly suspend. |
| Product-scoped interview claim needs a confirmed product | `stage0/interview.py:496-501` | **Bare `ValueError` mid-write**, and the skill actively steers the model into it. |
| Correction-lineage mismatch / project-state statement | `interview.py:934-943`, `:460-464` | Same bare-`ValueError` shape. |
| Pin-layer "product not confirmed" | `stage0_recipe.py:197-200` | Hard `ExecutionConflict` at the pin layer but recoverable `product_not_confirmed` at the tool layer — same fact, two failure modes. |
| `Stage0CardTooLarge` | `product_context_compiler.py:217-218, 384-385` | Raises where the omission mechanism at `:181-199` could truncate. Can kill a turn on a large tenant. |
| Bad website input kills a fleet task | `official_site_crawl_wiring.py:545-550`; `official_site/lifecycle.py:214-216` | Bad *human* input raises `ValueError`; the setup screen stalls instead of saying "that website isn't crawlable". |
| Criterion-packing overflow | `exa_websets_acquisition.py:188-198` | Provider contract limit as a hard raise rather than a typed refusal the agent can act on. |
| `_MAX_GOVERNED_TOOL_FAILURES = 3` | `agent_runtime_wiring.py:92, 886` | On the 4th refused tool call the original exception is raised and the turn dies — the last place a repeated model typo kills a job. |

**Silent drops** (the opposite failure — no refusal at all, which is worse for debugging):
`stage0_setup.py:320-329` (swallowed `PreconditionFailed` → setup polls "running" forever);
`official_site_crawl_wiring.py:483-484` (non-allowlisted workspace skipped with no durable trace);
`interview.py:887-888` (a corrected value for the same key silently ignored);
`sumble_committee_source.py` org-unlocked candidates and `profiling/committee/admission.py:149-154`
strong-key-less candidates — both dropped with **no review item**.

---

## 4. MONEY — what is already record-only, and the six exceptions

**Record-only (breach computed, logged with exact amounts, call proceeds).** Every site routes
through `cap_refusal_is_enforced`: project-run hard cap (`durable/provider_spend.py:251-269` — the
shared chokepoint under every paid provider call), account-gap reserved units/cost/expected-value,
committee reserved units/cost, gap preflight ×2, **post-dispatch charge > authorized cap**
(`sumble_account_gaps.py:915-944` — the guard that threw away paid data on 2026-08-19), committee
wire-plan caps, R9 atomic batch budget, launcher economics ×3, agent-context job cap, result-store
fold guards. Plus, uncommitted in the tree: discovery, discovery-gap, targeted-enrichment,
contact-channel settlement.

**Still blocking — correctly** (money *truth*, not caps): provider 4xx folds,
`SumbleCreditContractViolation`, the `spend_outcome_unknown` quarantine, `spend_reconciled` in
finalization, DB `bounded_charge` CHECKs, anti-double-spend replay.

**Still blocking — the six worth a founder ruling:**

| # | Guard | file:line | Assessment |
|---|---|---|---|
| 1 | **Exa `provider_reported_cost > reserved` → quarantine + suspend** | `durable/external_research.py:678-686` | **Highest-value conversion.** Structurally identical to the `sumble_account_gaps.py:915` shape that `39fcdc13` converted — the money is already spent, and this **discards a paid Exa response** and kills the job. Not posture-gated. Verified by me directly. |
| 2 | Settled cost > reservation | `entity_research_parallel.py:396-402` | Raised in `completed()` **after** the result is durably persisted and folds written. Kills the job and strands an unreleased reservation. (Two readings exist — truth-about-money vs throw-away-paid-data. Founder call.) |
| 3 | `SumbleCreditBudget.authorize` cap | `resolvers/sumble/__init__.py:353-357` | Our own cap, in-process, pre-call, unconditional. Mostly masked by `_authorized_provider_credit_cap` raising the reservation. |
| 4 | Exa discovery `requested_count > 50` / credit + cost ceilings | `exa_websets_acquisition.py:243-246, 258-267` | Hard raises that do **not** route through `cap_refusal_is_enforced` — the only un-posture-gated caps on the discovery path. |
| 5 | `ValidatedPlan.estimated_cost > budget_limit` | `platform/agents/clue_agents/contracts.py:762-768` | The only money guard on the Stage-0/directive path that still refuses. It is a *token* budget, not a provider cap — arguably out of the ruling's scope. |
| 6 | `Field(gt=0)` on launch amounts | `entity_research_launch_tools.py:87-88` | A trap the pilot posture itself creates. Loosening changes a frozen tool-descriptor sha (replay identity), so it is not free. |

**Record discipline is non-uniform:** `spend_posture` emits `log.warning` +
`research.spend.cap_record_only`. But `agent_gate_tools.py:253` (amount withheld),
`chat/router.py:1708` (`GATE_AMOUNT_STALE` skipped) and `entity_research_contracts.py:163` skip
**silently**, and `account_research_fleet_launch.py:340-349` logs without a metric.

---

## 5. The live blocker from this session — FIXED

`ResearchDirectiveInvalid: … rejected by the memory seam: body_rule` (16:26 and 16:29 IST).

Root cause: `draft_research_directive` side-writes the human's instruction into project-scoped
memory and treated **any** `MemoryRejected` as fatal. The rejection came from an **LLM-judged
hygiene opinion** (`clue_memory/reconcile.py:103-110`, `judgment.body_ok`). The first directive
drafted under the committee co-definition contract cannot avoid person-adjacent words, so it fired
immediately — an advisory subsystem holding a veto over the primary flow, which contradicts Doc M §2
("memory is advisory; nothing authoritative lives in memory").

**Fixed and committed as `53362c3b`**, verified by me at `directives.py:853-867`: a rejection now
degrades exactly like `MemoryDisabled` already did — `memory_refs=()`, truthful
`memory_outcome="memory_rejected:<reason>"`, draft lands, loud record. **Deliberately unconditional,
not pilot-gated.** A second shape (`MemoryPreconditionFailed` — a verbatim email/phone in the
instruction) was found by the sweep and degraded the same way.

The sweep lane's own note is `_memory/2026-08-20-pilot-blocking-refusal-sweep.md` (uncommitted at
time of writing, along with the discovery / discovery-gap / targeted-enrichment / contact-channel
conversions).

---

## 6. Gaps found that nobody owns

1. **No account-subject stale-dispatch reaper.** Verified by me: both wake paths filter
   `subject_kind='contact'` — `external_research_wake.py:135-148` and
   `durable/external_research.py:1500-1521`. `registered_entity_research_wait_sources`
   (`external_research_wake.py:194-209`) registers committee, contact-external and contact-channel
   sources and **nothing for account Exa-deep**. An interrupted account deep dispatch has no
   automatic recovery path; it needs a human resume. Asymmetric with the contact lane, which has one.
2. **`Stage0RoutingReceiptGuard` is not armed in production.** `stage0-interview/v20/SKILL.md:243-245`
   tells the model the platform *refuses* a fabricated-capture finalization; production passes
   `completion_guard=None` (`conversation_turns.py:251, 331`). Arm it or delete the claim.
3. **`launch_account_research@1` is still on the pilot surface** (`agent_registry_wiring.py:171`)
   and bypasses the turn-set-equality and membership re-checks that
   `launch_selected_account_research@1` enforces. An invented amount enters `request_sha` and
   therefore the run/selection/job identities.
4. **Five live refusal codes are absent from the enforced steering manual**
   (`tests/api/test_entity_research_cutover_r10.py:281-294`): `account_gap_field_already_acquired`,
   `account_gap_ineligible`, `field_source_authority_mismatch`,
   `committee_request_authority_mismatch`, `semantic_tool_input_validation_failed`. The agent can
   receive refusals its manual never teaches.
5. **`assert_fuzzy_cannot_auto_merge` has no call site** (`identity/policy.py:119-135`). The
   invariant that stops two real companies collapsing into one is an opt-in function nobody calls.
6. **Fragile text coupling:** `durable/account_gap_enrichment.py:80-82` matches a trigger's
   `RAISE EXCEPTION` string **verbatim** (`bd0b7e62a2b4:356`). A migration reword silently reverts a
   recoverable refusal to a job-killing raw `DBAPIError` — the exact 2026-08-20 wedge.
7. **Three import-discipline static guards scan an empty file set** (post-monorepo path rot) and
   pass vacuously. Confirmed: `src/` does not exist; the package moved to
   `subsystems/research/clue_research`. Repointing `_SRC_ROOT` should surface real findings.
8. **`committee_office_candidates_ambiguous`** is now raised only by an organization-membership
   mismatch, never by geography — label drift after the office-gate retirement.
9. **Memory DSAR is unreachable.** `clue_memory/compliance.py:24-98` (`erase_subject`, `lock_memory`)
   is exported and wired nowhere; `memory_wiring.py` composes only Assembly/Judge/WriteSeam. Do not
   confuse with `AgentPrivacyService.erase_subject` — different subsystem.
10. **Memory cycle-aging is frozen.** `lifecycle.record_kickoff` has zero production callers, so
    `cycles_since_confirmed` never advances and dormancy never fires.
11. **Backlog status corrections** (verified against code, not trusted from the doc): the
    `[M9.2×M1.2]` merge/corroboration equality divergence is **RESOLVED**; "no consumer reads
    `CurrentValue.conflict`" is **STALE** (see §1a inversion 2). Still open:
    `[M9.5×M1.2/M10.5]` retention-unaware merge, `[M9.4×M1.2/M0.2]` NULL-binding contact claim,
    `[C7×core]` contact-view 404, `[C8§6c]` verdict recompute at `narrative/support.py` and
    `review/composition.py`, `[B1]` fence tokens, `[B2]` presign gate and cache re-cite race,
    `[M2]` `multi_lock` early expiry.

---

## 7. Committee-specific structural notes

- **The confirmed committee plan is now almost mechanically inert.** `functions` feeds only the
  narrow-not-widen check (`sumble_entity_research_tools.py:1407-1430`, which no-ops on an empty
  plan); `teams`/`functions` length feeds `team_limit`; **`levels` and `relationship_depth` have zero
  production consumers**; `personas` is consumed only downstream. Combined with "no wire filter is
  ever sent" (`sumble_committee_inputs.py:337-359` — Sumble v9 has no multi-value operator), the plan
  influences *what gets bought*, never *who gets admitted*. That is the ratified posture, but it
  means the `bfc24fc1` co-definition steering has **no mechanical backstop anywhere**.
- **The surviving employer floor is at normalization, not admission.** `normalize_teams` /
  `normalize_people` (`sumble_committee_source.py` via `teams.py:290-360`, `people.py:325-381`)
  silently drop anyone whose provider-asserted `current_employer.organization_id` isn't the exact
  matched organization. This is provider-returned fact, correctly placed, and should not retire.
- **Only surviving admission veto:** a declared non-null `business_unit`
  (`sumble_entity_research_tools.py:1624-1627`). `excluded` is now structurally unreachable. Risk: a
  scope naming a *geographic* business unit ("Fort Myers Campus") silently re-creates the retired
  office veto.
- **`_bounded_office`** (`platform/agents/clue_agents/account_entity_research.py:68-70`, verified)
  still forces every scope to declare a facility/locality/region/business-unit that `company_wide`
  never reads — a live model-input tax with no admission effect, *except* that declaring a business
  unit re-enables the one remaining veto. Cheapest simplification on the path.
- **Per-job operation identity forces a re-buy on every relaunch.** `entity_research_job_id` is
  inside `request_fingerprint` (`libs/clue-core/clue_core/committee_acquisition.py:117-127`), so the
  30-day fresh-reuse path can never fire across jobs. Three live relaunches = three × 72 units.

---

## 7a. Substrate layer — the guards every stage rides on

**Claim store.** `check_claim_writable` (`claimstore/registry.py:1216-1286`) is the unbypassable
write gate: value-schema validation, fail-closed reuse classification (a `tenant_private` claim with
no workspace, or a field with no resolvable scope, is refused), and product-scope binding. Below it,
the DB carries `claim_tier4_iff_synthesis`, `claim_tier4_verified_requires_span`,
`claim_external_research_lineage_shape` (all-or-none external refs, and they *require* an
`artifact_key` — the "evidence is durable, not just a URL" floor), `claim_reuse_scope_tenant`, and
`claim_artifact_scope_compatible`. The append-only triggers `claim_no_immutable_update` /
`claim_no_delete` make everything else possible. **All necessary.**

**The strongest single truth guard in the codebase** is `claim_sumble_professional_shape` +
`claim_sumble_professional_lineage_validate` (`alembic/versions/26eaa6262063:128-209`): every Sumble
professional claim must join *at the database* to a `ready` committee operation, a `succeeded`
snapshot, a live non-erased artifact, the right account subject, and the run's product — or the
insert raises. This is what makes "truth floor = provider-returned" structurally true at rest rather
than merely prompt-level. **Keep permanently.**

**Merge (read-side truth).** With `verification_enabled=False` the active policy drops
`require_verified_tier4` (`merge.py:121`), so unverified tier-4 claims do win the merge — the
ratified pilot posture. Only REJECTED and WEAK-binding exclusions remain live. Two backlog items
verified **still open**: the merge is retention-unaware (a 40-day `sensitive` facet claim is
retention-EXPIRED yet FRESH to the merge and can win), and a NULL-binding plain `contact.*` claim is
merge-eligible while the C7 `ResearchStatement` validator demands both-or-neither — which 404s the
whole contact view. Both latent today; the first must close before any `sensitive` claim is written.

**Tenancy.** Fail-closed everywhere and genuinely good: the toolbelt's `_load_account` returns the
same `account_not_found` shape for absent and cross-workspace ids (no existence leak) plus a logged
warning; `claims_for`/`current_value` have **no scopeless read** (scope is keyword-required, default
`PUBLIC_ONLY`); `read_verified_artifact` reconciles workspace *and* full content address;
`account_entity`/`contact_entity` are `NOT NULL workspace_id` with workspace-scoped strong keys and
within-workspace merge fences. One deliberate exception: the per-entity single-flight lock is **not**
workspace-namespaced (`durable/scheduler.py:70-79` omits the available `tenant=`), harmless today
because accounts are workspace-local.

**Idempotency.** `PROJECT_PHASE` is live and correct (single-statement claim, no read-then-write
race). **`ACCOUNT_STEP` is vacuous** — zero production callers; the docstring at `project.py:1009`
calling it "the airtight exactly-once charge" is stale, because M8's caller was quarantined and the
M8D fleet uses its own R9 reservation ledger instead. Not a risk (the R9 ledger and the
observation-window trigger cover the ground) but it will mislead the next reader.

**Lease fencing (B1).** Supervised heartbeat, `FIRST_COMPLETED` race, immediate mid-phase
cancellation, holder-guarded queue writes, construction-time refusal of an incoherent
heartbeat/TTL config. The `[B1×integration]` residual is **still open**: durable writes inside
`advance()` are un-fenced during the cancellation-latency window. Fine for one worker; must be
revisited before multi-worker production.

**Pre-spend gate — what is actually live.** The founder ruling kept the M9.1 *authority* gate on
while caps went record-only, and the code matches: it fires on the pilot's two real spend paths
(Sumble committee `committee_eligibility.py:370-387`, Exa deep `exa_deep_preparation.py:193`) plus
scoring and import. The M4 waterfall, M11 synthesis and Lane-E completions remain ungated, and the
asserting test from M9.1's AC-6 still does not exist.

**Use/appropriateness gate.** Composed and armed, with a hard floor that config cannot relax:
`UseClass.SENSITIVE` is never usable for outreach (`compliance/use_gate.py:281-284`), and a policy
that tried to make it usable is refused at construction. On today's committee output (role, persona,
organization-relationship — no `contact.facet.*`) it evaluates nothing; it arms the moment facets are
written. **Keep.**

**Identity binding is a constant, not a verdict.** On the live M8D path
`identity_binding=STRONG` is hard-coded (`account_entity_research.py:955,970`) and *required* by the
schema CHECK — the M9.4 classifier is dead here. That is consistent with "provider-returned is the
floor", but `contact_eligibility.py:519-523` gates committee admission on STRONG **as if it were
evidence**. Worth naming: the field currently carries no independent evidentiary weight.

**Memory seam.** "Memory is never load-bearing" is mechanically enforced on the **write** side (no
claim-content column; `FACT_SHAPED` and `BODY_RULE` both degrade) but is **convention only** on the
read side — `context.py:376-391` injects bodies labelled `"Advisory body:"` with no mechanical check
that a consumer won't quote it as fact. Acceptable. Three memory functions are **dead**:
`erase_subject` and `lock_memory` (so memory DSAR is currently unreachable) and `record_kickoff` (so
memory cycle-aging never advances). Also: the scope-shape and person-adjacency preconditions are
caught and degraded in `directives.py` but **not** in `stage0/interview.py`, so they still block a
Stage-0 turn.

**Run/fleet.** `plan_replay` degrades rather than refuses (a bogus cursor resets to 0 rather than
producing a permanently dead stream) — correct. The SSE treaty guards do block, correctly: workspace
header required, cross-workspace run id 404s at token-mint time, single-use tenant-bound CAS on
consume with indistinguishable failure. The design-plane event pruner cannot touch project runs.

---

## 8. What is unambiguously right, and should not be touched

The **verbatim-span chain**, end to end: captured bytes hash (`stage0_tools.py:1044`) → verbatim
quote substring (`interview.py:358-372`) → value entailed by its own quote (`interview.py:734-745`)
→ retained-artifact span cutting (`exa_websets_materialization.py:212-330`) → the anti-fabrication
guard (`entity_research_tools.py:2168-2179`) → admitted-projection span-hash reconciliation
(`sumble_entity_research_tools.py:214-223`). All deterministic, no LLM, no cost. Every live firing
was a genuine upstream defect.

The **existence gate**: `discovery_scoring/discovery/hypothesis.py:56-63` — "a candidate with no
grounding is a fabrication discovery never emits". This is the "LLM may plan queries but never *be*
the source" rule in code.

The **seal barrier**: 14 predicates at `durable/discovery.py:3480-3931`, including
`CANDIDATE_IDENTITY` (an item cannot vanish without a recorded disposition) and the honest-yield
coverage report (`discovery_seal.py:266-286`, `coverage_is_exhaustive: False`).

The **human gates**: product selection (four layers plus the DB trigger
`064ad0f43519:275-368`), the ICP gate, the directive confirmation gate, and the launch
authority chain — especially `entity_research_launch_tools.py:244-259`, exact ordered equality
between the accounts the human referenced and the accounts launched.

The **append-only triggers** across claims, gates, directives, results, coverage and scope pins.
These are what make replay, DSAR and provenance tractable.

The **`spend_outcome_unknown` quarantine** — it is what produced the correct v7 outcome (10 s teams
timeout → quarantine → terminal attempt → honest empty committee) rather than a double charge.
