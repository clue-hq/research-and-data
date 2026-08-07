# 2026-08-08 — Lane E charter (on-completion prose synthesis) + D-9/D-10 rulings recorded

## Session outcome
- **Founder rulings recorded in FI-1 §9** (`docs/specs/FI-accounts-contacts-contract-gap-review.md`): D-9 → **Option B** (kickoff through the platform deepagent tool call; **production chat surface S6 enters MVP scope**); D-10 → empty-state until deep research completes, then real synthesis; M8D R11 DEEP-phase bridge demoted to **fast-follow** (MVP research must run + accumulate claims, not complete VERIFICATION/HANDOFF).
- **Wrote `docs/specs/FI-lane-E-on-completion-synthesis.md`** (DRAFT — §7 open decisions await founder: D1 outcome gate, D2 species, D3 Positioner-in-MVP, D4 L1 visible change). Input: two read-only Opus studies (M12-reuse; finalization-trigger), findings embedded with file:line citations in the charter §1.

## Load-bearing study facts (beyond what the charter cites)
- Positioner uncomposed but all seams exist at api root: `build_client_knowledge_retriever` (`narrative_wiring.py:58-102`), `ProductionHandoffCommitteeReader` implements both committee protocols (`contact_eligibility.py:366,402-422`), judge composed in fleet process (`run_composition.py:288-290`).
- Trigger menu evaluated: (a) in-finalize-txn — rejected (locks, import-linter isolation of `clue_fleet`); (b) post-finalize fleet slot — **chosen** (precedent: `reconcile` at `account_research_fleet.py:1382`; contact `project()` at `contact_research_fleet.py:407`); (c) wake-source poller (R11.2 shape) — rejected for now; (d) on-read — impossible (HTTP process has no gateway, composer model-free by contract); (e) `DerivedClaimService` (`research_derivations.py:95-228`, built, zero callers) — rejected as write engine because DERIVED claims don't flow through `current_values`/merge, which is the FI-2 BFF's read primitive; positioner-pattern tier-4 FIELD_CLAIM chosen instead.
- `SUMMARY` sections (account + contact) exist in both authority tables with zero routes → ready-made D-10 empty state; Lane E prose does NOT depend on the L1 fix. L1 fix (add VALUE_NARRATIVE to `ACCOUNT_SECTION_ORDER` after INSIGHTS) still owned by Lane E slice E0.
- `finalization_outcome=COMPLETED` ⟺ zero unresolved ∧ zero review flags ∧ committee complete (`account_entity_research.py:518-528`); fleet tolerates 50% needs_review → completed-only gating would skip most jobs.
- FI-2 slice-0 `research_scope` substrate HAS LANDED on this branch (enum `clue_core/enums.py:322-339`, migration `21552956dc51`) — charter declares species directly.
- L3 confirmed account-side only (contact projection DOES expose `unresolved_field_keys`, `contact_research_fleet.py:142-143,204-207`).

## Open / next
- Founder to rule on charter §7 D1–D4; then E0 can start.
- Lane-graph consequence of D-9=Option B not yet spec'd: Lane D becomes "deepagent launch tool + production chat surface" — the S6 chat surface (turn creation route, streaming story, typed parts) is now MVP scope and needs its own charter/contract-gap review. NOT yet written.
- FI-3 orchestration spec (lane graph, chokepoint owners) still pending — user asked about it earlier; not yet commissioned explicitly.
- Composition-wiring backlog surfaced to founder as an MVP-scope question (M11 `register_synthesis_wiring` resolvers, `stage0_scrape_binder`, deterministic resolvers — waterfall currently Exa+Sumble only). No ruling yet.
