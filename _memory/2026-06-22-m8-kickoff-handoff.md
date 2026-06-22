# M8 — Deep Profiling — kickoff handoff for parallel implementation

**Date:** 2026-06-22 · **Branch base:** `m8/deep-profiling` (off `origin/main` @ 405409a — full M5/M6/M7/M9 integration) **after the tiny seed lands.**
**Note on naming:** the request said "m9 kickoff handoff" — **M9 (Verification) is already complete (100%)**; this whole thread is the **M8** parallel fan-out the seed unblocks, so this is the M8 kickoff. (If something M9-specific was actually meant, flag it.)

This is the M8 analogue of the Beat-0 → Beat-1 plan from the M5–M9 fan-out: **a tiny seed has frozen the shared field-class surface; the worker issues now fork from it and build in parallel.** Unlike Beat-1, **M8 adds no migrations** (every issue is "No new tables") — so the alembic-head-collision class is gone; the only true coordination point is the `api/` composition root.

---

## 0. What the tiny seed already shipped (so you don't redo it)

`src/clue_research/profiling/fields.py` + `load_deep_profiling_pack(conn)` register the two deep-pass field-classes as `field_definition` rows (see [[2026-06-22-m8-tiny-seed]]):
- **`account.resonance.*`** (5: `employee_sentiment`, `attrition_signal`, `eng_blog_tone`, `public_frustrations`, `buying_culture`) — pass=deep, `tier_plan=("exa_deep","parallel_task")`, `gate="deep-pass"`, each carrying the **sensitivity firewall** in `validation` (`{account_scoped, excludes_named_individual_special_category}`). **This is M8.2 part-1.**
- **`contact.facet.*`** (8: `nickname`, `stated_interests`, `communication_style`, `public_appearances`, `publications`, `causes`, `alma_mater`, `career_history`) — pass=deep, `gate="committee-gated"`, every facet `freshness_ttl` < 90d (graded 45–75d), each carrying a **`use_class_hint`** in `validation`. **This is essentially all of M8.5** (governance is structural — see below).
- Reuse-scope inherits the class default `TENANT_PRIVATE`; CORE_PACK's two proof rows (`account.resonance.culture`, `contact.facet.recent_post`) and the icp pack's `account.resonance.research_prestige` are left untouched (the class is federated).

**Net: M8.5 (ENG-154) is substantially DONE; M8.2's field-class half (ENG-136 part-1) is DONE.** What remains: the four worker issues + M8.2's collector half.

**Governance is structural, not per-field — every M8 worker must know this:** a `contact.facet.*` claim *cannot be constructed* without `identity_binding`+`use_class` (the `claim_contact_field_requires_governance` DB CHECK + `core.claim` validator); a WEAK binding never promotes (`core.can_be_promoted`); M10's use-gate reads `use_class`. So **M8.4 must stamp both tags on every facet claim before insert** — that is not optional plumbing, it is the only thing that makes the write legal.

---

## 1. The remaining work, as two independent axes

```
ACCOUNT AXIS                                   CONTACT AXIS
M8.1 Account Profiling (ENG-132)               M8.3 Committee Discovery (ENG-142)
  └─► M8.2 resonance collectors (ENG-136 pt2)    └─► M8.4 Contact Profiling (ENG-149)
                                                       (facet field-class M8.5 ✅ already seeded)
```
- **Account axis:** M8.1 is the trunk (the M2 converge worker); M8.2's resonance collector runs as an *aspect of M8.1's converge loop*, so it follows M8.1.
- **Contact axis:** M8.3 is the trunk + long pole (committee discovery; its spec raises priority to High within the milestone because M8.4 is blocked on it). M8.4 (contact profiling) needs M8.3's admitted committee **and** consumes the already-seeded `contact.facet.*` field-class.
- **The two axes are independent** — distinct worker families (`profile_account`/`collect_resonance` vs `discover_committee`/`profile_contact`), communicating only through the claim store. Build them in **two parallel workspaces.**

**Merge / unblock order:** start M8.1 and M8.3 together (day one); M8.2-collectors lands after M8.1; M8.4 lands after M8.3. Critical path = **M8.3 → M8.4** (contact axis).

---

## 2. Shared seams every branch codes against (all already in `main` + the seed)

| Need | Seam (import path) | Owner |
|---|---|---|
| The field-classes to fill | `clue_research.profiling.fields` (`RESONANCE_FIELD_KEYS`, `FACET_FIELD_KEYS`, `load_deep_profiling_pack`) | **seed** |
| Run inside the per-account graph | implement `core.execution.AspectWorker` / `PhaseHandler` / `WorkerResult` (the frozen seams); per-tier depth/worker caps come from `core` config the graph passes in | M7 (`durable`, wired at `api/`) |
| Fill a field via the waterfall + planner | `core.resolver.Resolver`, `sources` waterfall + Source Planner (`exa_deep`/`parallel_task` are registered, resolver-absent until M11 → empty `no_resolver`, never a crash) | M4 (`sources`) |
| Gate spend / verify | `core.verification.PreSpendGate` / `FaithfulnessJudge` / `IdentityBindingGate`; `verification.classify_binding` | M9 (`verification`) |
| Resolve people under accounts | M2 identity service (`identity`) — the committee existence gate | M2 (`identity`) |
| Read/write truth | `claimstore.insert_claim` / `current_value`; stamp reuse via `identity.stamp_reuse` | M1 (`claimstore`) |
| Direct LLM calls (e.g. M8.3 role inference) | `gateway` (OpenRouter `LLMGateway`) — **never** a provider SDK directly | M0.4 (`gateway`) |

**Import rule (machine-enforced, `make contracts`):** M8 (`profiling`) may import the shared base (`core/config/obs`) and the M1–M4 services (`claimstore/identity/icp/sources`). It may **not** import any sibling milestone package — `durable` (M7), `verification` (M9), `discovery_scoring` (M6), `stage0` (M5) are all in the independence set. So M8 codes against the **`core` contracts** (`core.execution.AspectWorker`, the `core.verification` gate protocols) and the concrete M7/M9 implementations are injected only at the **`api` composition root**. (The seed's `profiling/fields.py → claimstore` is the allowed shape — a service import, proven by `make contracts` 11/0.)

---

## 3. Per-issue kickoff briefs

### M8.1 — Account Profiling (ENG-132) — account-axis trunk
- **Build:** the M2 **converge worker family** — `profile_account(account_entity_id, icp_version, tier, run_id) -> AccountProfileResult`, run as aspect workers inside the M7 graph. Read `current_value` → compute deep gap-fields → fill via the M4 waterfall → re-check → stop on schema-complete OR sources-exhausted OR budget cap (the *opposite* of M6's open-ended expand).
- **Must enforce:** target-lock (every resolver query entity-scoped: `site:` primary_domain / canonical name+hq_geo / registry id); a target-lock validator rejects a tier-4 claim whose `evidence_span` doesn't bind to the resolved entity; aspect workers run in parallel, no cross-talk, **return claim-id references, not blobs**; per-tier depth from the M7 recursion knob.
- **Writes:** claims `research_mode=ACCOUNT_PROFILING (M2)`, `entity_type=account`, full provenance. Reads the seeded `account.resonance.*` + `account.*` deep fields.
- **Gotcha:** a new deep-pass field is auto-discovered via `list_fields(pass_kind=DEEP)` and clustered into its aspect — so the seed's 5 resonance fields will appear in the `account.resonance` aspect automatically; that's intended.

### M8.2 part-2 — resonance collectors (ENG-136) — follows M8.1
- **Build:** `collect_resonance(account_entity_id, icp_version, tier, run_id) -> list[claim_ref]`, invoked as M8.1's **resonance aspect worker**. Calls the Source Planner for the `account.resonance` field-class then the M4 waterfall (tier-3 review/news → tier-4 synthesis); reaches M11 synthesis behind the `Resolver` seam (until M11, tier-4 fields stay empty/flagged — a correct output).
- **Must enforce the seed's firewall at runtime:** reject a resonance value carrying a named individual's special-category attribute (the field-def `validation` *declares* it; the collector *enforces* it) — route such data to `contact.facet.*`/M10.
- **Out of scope (M3.3):** authoring per-pack source weights (Glassdoor-high for resonance). The seed only declares the field-class; weighting is a pack `source_profile` slot.

### M8.3 — Committee Discovery (ENG-142) — contact-axis trunk + LONG POLE
- **Build:** `discover_committee(account_entity_id, icp_version, tier, run_id) -> CommitteeResult` — bounded `expand` over **this company's people** (Apollo/ZoomInfo/LinkedIn-style + the account's own team pages, via the M4 `Resolver`/planner). Stop on marginal-yield drop OR committee budget cap.
- **Must enforce:** every candidate **resolves through the M2 identity service** under the account (LinkedIn URL / verified email) before admission (a fabricated person dies here); role inference via the **`gateway` LLM** (model as config) → `contact.role_on_committee` ∈ {champion, economic_buyer, technical_evaluator, blocker} with a **role-plausibility gate**; a `contact.persona` claim so `(account, persona)` keying exists; committee **coverage confidence** (estimate + named unsearched channels).
- **Writes:** `research_mode=COMMITTEE_DISCOVERY (M3)`, `entity_type=contact`, discovery-provenance. `role_on_committee`/`persona` are plain `contact.*` (NOT facet) → professional-public by construction, no facet governance.
- **Hands** admitted, role-tagged contacts to M8.4.

### M8.4 — Contact Profiling (ENG-149) — needs M8.3 + the seeded facet class
- **Build:** `profile_contact(contact_entity_id, account_entity_id, icp_version, tier, run_id) -> ContactProfileResult` on each admitted committee member; fill the seeded `contact.facet.*` (+ `contact.*`) deep fields via the M4 waterfall + long-tail modality adapters (video/audio→transcript). May spawn **facet sub-workers** (2nd recursion level, capped per tier by the M7 knob).
- **MUST (the make-or-break):** stamp **`identity_binding ∈ {strong, weak}`** (via `verification.classify_binding`) and **`use_class`** on *every* facet claim before insert — the field-class CHECK rejects the write otherwise. Use the seed's per-field `use_class_hint` (in `field_def.validation`) as the *starting point*, but compute the authoritative tag from evidence (a `causes` claim about a religious cause → `sensitive`, not just the default). Target-lock per person; tier-4 claims need a non-null `evidence_span` or stay `unverified`.
- **`profile_claims[]` shape must match** `account_handoff.committee[].profile_claims[]` (value, evidence_span, source_tier, identity_binding, use_class) so M12 assembles without translation.

---

## 4. Coordination points & follow-ups (carried from the seed's findings)

1. **`api/` composition root (the one real coordination point).** No branch touches `api/` during build. At integration, wire into `CampaignRun`/the M7 graph: the M8 `AspectWorker`s, `load_deep_profiling_pack(conn)` (alongside `load_core_pack`), and the deferred M9.1/M9.4 stamps (`PreSpendGate.check` before spend; `classify_binding` before facet insert — both deferred-to-M8 per the CLAUDE.md backlog). Do this once.
2. **M3.3 source-profile weights** for `account.resonance.*` / `contact.facet.*` (Glassdoor-high, podcasts/X-high) — author as pack `source_profile` slots; the seed only declared the classes.
3. **Latent eval gap (from the seed):** `verification/golden.py`/`eval_harness.py` reference UNREGISTERED keys `account.resonance.sentiment`, `contact.facet.{hobby,conference_talk,recent_award}`, and the singular `account.strategic_move` (registered field is plural `strategic_moves`). Harmless today (offline fixtures, no registry FK). When M8.4/M9.6 integrate: reconcile golden names to the canonical seed names OR load the profiling pack in the verification/eval conftests, and fix the strategic_move singular bug.
4. **No migrations expected** in any M8 issue — if a branch thinks it needs one, re-examine (the spec says "No new tables" for all five). If genuinely needed, hash-id + `alembic merge` at integration.

---

## 5. Rules while building in parallel
- **Don't touch** `core/*`, `pyproject.toml`, the seed's `profiling/fields.py` field contracts, or another milestone's package (independence is machine-checked: `make contracts`).
- Each branch: `make check` green before merge. DB tests `pytest.skip` without `CLUE_DATABASE_URL`; run with `postgresql+asyncpg://clue:clue@localhost:5432/clue` (the local `clue` DB, rollback-isolated) to actually exercise them.
- Workers **return references (claim ids), not blobs**; communicate only through the claim store.

See [[2026-06-22-m8-tiny-seed]] for the design rationale and the full reader-findings the seed was built from.
