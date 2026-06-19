The overall product is an AI-powered ABM orchestration platform. In the full product, agents help discover target accounts, enrich account/contact data, perform deep research, draft personalized campaign content, generate brand-aligned campaign artifacts, scale those artifacts across contacts/accounts, and export or publish the resulting assets.

This document covers only one subsystem of that platform: the **data & research subsystem** — the trustworthy data layer that turns a client's ICP into a prioritized, deeply-researched, *verifiable* view of target accounts and their buying committees, which everything downstream (content calibration, the design module, campaign artifacts) consumes. The design subsystem is already built and lives in its own repo; this repo does not touch it.

This file is high-level orientation only. The full architecture is the doc set in **`docs/architecture/`** — start with the overview, which is the map (the others are the territory):

1. `clue-hq-research-architecture-overview.md` — **read first.** The four required outputs, the end-to-end map, the output contract (where this subsystem ends), and the open-decisions register (D1–D8).
2. `clue-hq-research-layer-architecture.md` — **the substrate/spine.** Claim store, identity resolution, field registry + industry packs, trust-tiered source waterfall, per-account execution, verification layer, scoring, build order, stack.
3. `clue-hq-discovery-and-research-staged-architecture.md` — **the staged flow.** The 2×2 of research modes (M1–M4), Stage 0, the Source Intelligence Layer.
4. `clue-hq-stage0-client-and-icp.md` (Doc B) — the front edge: client reverse-profiling, ICP co-definition, the two entry scenarios.
5. `clue-hq-signal-execution-cost.md` (Doc C) — two-tier signal model, resonance/personal-facet field-classes, bounded fan-out, campaign-level orchestration, cost governance, observability.
6. `clue-hq-compliance-and-personal-data.md` (Doc D) — jurisdiction switch, use-class taxonomy, the appropriateness/use gate, lawful basis, the three deep-research postures.

## Session memory protocol
At the beginning of every agent session, read the files in `_memory/` before making architecture, implementation, or planning decisions. Start with `_memory/README.md` when present, then read the most recent session notes and any topic notes that match the task.

Treat `_memory/` as durable local context, not as unquestioned truth. Use it to recover prior progress, decisions, failures, and open questions, then verify against the current workspace before changing code or docs.

During every coding session or goal session, keep `_memory/` updated as work progresses. Record meaningful changes made, decisions taken, assumptions accepted, failures observed, commands/tests that failed, and unresolved follow-ups. At the end of the session, add a closing entry that summarizes the final state and verification performed.

Do not store secrets, private credentials, API keys, customer data, or raw proprietary source excerpts in `_memory/`. Keep entries concise and operational so another agent can continue the work without re-deriving context.

## Commits & version control
- **Commit locally, proactively and strategically.** Commit at natural checkpoints — a completed issue, a coherent unit of work, a green `make check` — rather than waiting to be asked. Keep each commit well-scoped and logically grouped (don't bundle unrelated changes), and write a clear, descriptive message that states *what* changed and *why*. You do **not** need to show or confirm a commit before making it.
- **Never push.** Do not `git push`, and do not open or update pull requests or otherwise publish to any remote, without an explicit instruction to do so. **Local commits only** — the user reviews the history and decides when, what, and where to push.
- Don't commit directly to the default branch (`main`); do the work on a feature branch.
- **No Claude / AI attribution.** Never credit Claude (or any AI assistant/tool) as a co-author or author. Do **not** add a `Co-Authored-By: Claude …` trailer (or any similar attribution) to commit messages, and do not add an AI-generated/"Generated with" footer to pull request descriptions. Commits and PRs are authored under the human committer only.

## Database migrations (Alembic) — conventions
Adopted after the M2/M3 parallel-branch revision-id collision (both branches independently produced `0005/0006/0007`). Goal: parallel milestones never collide on a migration id, and a merge has one clear join.
- **Use Alembic's default random-hash revision ids — never hand-pick zero-padded sequentials.** Create migrations with `alembic revision -m "<slug>"` (or `--autogenerate`) and let it assign the `revision`; set `down_revision` to the current head. Different branches then generate different ids, so concurrent work can't collide. (The legacy `0001`–`0011` chain keeps its sequential ids — do **not** rewrite it; new migrations just chain off `0011` with a hash id. Mixed id formats are fine.)
- **Parallel branches → `alembic merge`, never a hand-renumber.** If two branches each added migrations off the same head, after merging the code run `alembic merge -m "merge <a>+<b>" <head1> <head2>` to create a join revision (back to one head, both sub-chains preserved).
- **Exactly one head, always.** `alembic heads` must return a single revision; `make db-smoke` (up→down→up on a *clean, per-branch* throwaway DB — never a shared one) is the gate. Two heads = unmerged parallel branches → `alembic merge`.
- **Migrations stay hand-written and reversible:** every `upgrade()` has a matching `downgrade()`; named CHECKs/indexes/triggers; enums mirror `core.enums` (the enum-parity tests guard drift); the "no domain tables at M0 head" test stays green.

## What it does
End to end: reverse-profile the client from near-zero input (worst case: just name + website) into a versioned Client Knowledge Base → synthesize and co-confirm one or more versioned ICP specs → bring accounts in via either entry scenario (we discover them, or the client imports a list — or both) → cheaply score every account and assign tiers → run deep, source-grounded research only on high-tier accounts → resolve each account's buying committee → emit explainable fit/intent scores and a persona-keyed, fully-sourced claim bundle plus a grounded value narrative, with a human review surface over high-value accounts.

## The four required outputs (the output-first spine)
Everything in the subsystem exists to produce exactly four things; a component that serves none of them is overhead.
1. **Scored, ICP-fit account list** — every candidate (discovered or imported) carries a fit score, an intent score, the cheap deterministic signals behind those scores, and a provenance link behind every signal. No score without its evidence.
2. **Verified, fully-sourced account profile** per high-tier account — operational pain, strategic moves, and the *resonance layer* (culture, sentiment, frustrations), each claim target-locked to the exact entity and backed by an evidence span, or left blank.
3. **A buying committee** per high-tier account — champion / economic buyer / technical evaluator / blocker, each contact identity-resolved, persona-tagged, and *governed* (every personal claim carries an identity-binding strength and a use-class).
4. **A persona-keyed, evidence-backed claim bundle + grounded value narrative** — not raw facts but facts *plus the argument*, per persona, for why the client's product matters to this account, sourced on both sides (account evidence × client capability). This is the subsystem's actual product.

## Output contract — where this subsystem ends
Three output layers: **raw claims** (verified atomic facts, persona-agnostic) and the **value narrative** (the per-persona argument joining claims to client capabilities, itself a claim-with-provenance) are **owned here**; the **content schema / content** (artifact- and template-shaped output for mailers, landing pages, ads) is owned by a downstream content layer, **not this repo**. Research stops at *verified meaning* so one research output can feed every artifact type. (Recommended boundary — D1; the design subsystem's actual ingest interface is open — D2.)

## Core architectural bet
**Verifiability is a property of the data model, not a QA step bolted on at the end.** The atomic unit is a *typed claim with provenance* (value + source + evidence span + tier + confidence + freshness), never a free-text dossier. "Research" is the act of producing, corroborating, and scoring claims. A prior prototype did the opposite — an untyped dossier audited after the fact — and shipped fabricated facts; we do not repeat that.

## Patterns we follow
- **Claim-with-provenance store** as the shared substrate everything reads from and writes to.
- **Trust-tiered source waterfall per field** — deterministic APIs → official-source scrape → reputable third party → LLM synthesis (last resort); stop at the first confident hit.
- **Two entry scenarios, first-class and symmetric** — discovery (grounded, existence-gated; the LLM may plan/expand queries but never *be* the source of an entity) and import (bulk identity-resolution over messy free-text + ICP back-scoring); both converge at the Pass A scoring bridge. Import + existing customers are the strongest seeds for lookalike discovery (hybrid).
- **Two-pass execution** — score all accounts cheaply and assign tiers, then run expensive deep research only on high tiers.
- **Two-tier signal model** — every signal class has a *cheap deterministic proxy* (Pass A, all accounts) and a *deep synthesized narrative* (Pass B, high tier only). Signal-rich discovery lives in Pass A, not M1.
- **Orchestrator/worker per account** with a **bounded recursion knob** — a lead plans gap-fields and spawns parallel aspect workers; the richest aspects may spawn facet sub-workers. Depth and worker-count are capped per tier, in the prompt *and* as a hard runtime limit. Workers return references, not blobs.
- **Identity resolution as a service** — dedup → linkage → canonicalization; everything keys on a resolved `entity_id`, never a free-text name.
- **Verification layer** — pre-spend gates, corroboration rules, a faithfulness judge over synthesized claims, an **appropriateness/use gate** (distinct from accuracy), identity-binding, freshness TTLs, offline evals.
- **Buying-committee contact graph** — account truth plus the committee, keyed on `(account, persona)`.
- **Namespaced field registry + industry packs** — handles different deterministic fields per client industry without per-client schema changes; resonance (`account.resonance.*`) and personal-hook (`contact.facet.*`) field-classes are registered, not enumerated.
- **Durable execution at two levels** — per-account graphs (LangGraph + `AsyncPostgresSaver`) under a **campaign-run state machine** (`reverse_profiling → icp_confirmed → discovery → scoring → tier_checkpoint(human) → deep → verification → handoff`); checkpointed, resumable, pause/adjust mid-run, idempotent on both `(account, field, tier)` and `(campaign_run, phase)`.
- **Cost governance as a client-facing surface** — pre-run estimate, client-set per-campaign hard cap, live burn-down, per-source yield, verification health; the cost dial is fan-out-per-account × accounts-per-pass.

## Modularity & DRY (hard requirement)
Any one component must be replaceable — swap one system, feature, or sub-feature for another implementation — **without breaking its neighbours**, and no logic is written twice. This is structural, not aspirational, and is enforced by stable seams. Full rules and the seam contracts live in `docs/specs/_conventions.md §2`; the essentials:
- **The claim store is the only shared substrate.** Components communicate by reading/writing typed claims, never by calling each other; workers return references (claim ids), not blobs.
- **Hot-swappable resolvers behind one `Resolver` protocol** — Clay / Apollo / ZoomInfo / BuiltWith / registries / CRM / Firecrawl / Exa / Parallel are *just resolvers*; nothing downstream knows a specific provider exists, so swapping Clay → direct APIs is a registry/config change, not a rewrite.
- **Open by registration, not enumeration** — new fields = field-registry rows; new sources/modalities = a source manifest (+ adapter). Never fork the pipeline to add a vertical, a field, or a source.
- **Policy is data, not code** — merge policy, scoring rubric, source profiles, tier/budget caps, jurisdiction/use-class policy, and freshness TTLs are versioned config the engine reads, swappable per client/ICP without code changes.
- **Durable execution is Temporal-shaped** so the V1 Postgres state machine → Temporal migration stays mechanical.
- **DRY** — shared domain types, the `Resolver` protocol, provenance/claim helpers, the tracing wrapper, and config loaders live in one shared package; every component imports them and never re-implements them. Everything keys on a resolved `entity_id`, never a free-text name.
- **Enforced, not trusted** — package dependency rules are machine-checked: `core` imports nothing internal; resolvers/adapters/judges/scorers never import each other; no module outside a provider's own package may import that provider's SDK.

## Principles / non-negotiables
- LLM research is the **least-trusted** source: it runs **last**, only filling fields no deterministic/official source can answer.
- A claim with **no evidence span cannot be promoted**. An empty, flagged field is a *correct* output; fabrication is the only real failure.
- A personal claim drives outreach **only if it clears both gates**: strong identity-binding (it's true and it's *this* person) *and* an allowed use-class for its jurisdiction under the client's policy. A true, well-sourced, correctly-attributed fact can still be unlawful or tasteless to use — empty is correct; fabricated, misattributed, *or inappropriate* is the failure.
- **Design for the strict (GDPR-grade) case and switch down** — jurisdiction is a first-class per-client switch; lighter regimes are a relaxation of the same machinery, never a separate code path. `sensitive` (special-category) data is excluded from outreach by default.
- **Minimum-input, client-always-has-the-wheel** — a client who pastes only a URL must still reach a confirmed ICP and a running job. The platform always *suggests*; the client *confirms, edits, pauses, and adjusts*.
- **One constrained orchestrator/worker** — not a single mega-agent with many tools, not a brittle hardcoded workflow. Prefer giving workers tools over over-prompting them.
- **Never run uniform deep research on the whole list** — two passes, tier-gated depth, hard budget caps.
- **Account-level data is insufficient** — build the contact graph and persona keys here, not in a later phase.
- **Scores and facts are provenance-backed and explainable** — that traceability is the differentiator, not overhead; it is also what makes erasure (DSAR) tractable.
- **Coverage confidence, not a completeness guarantee** — open-ended discovery can't prove it found everyone; report estimated coverage and name the unsearched channels rather than implying exhaustiveness.
- **Postgres is the only source of truth.** No external tool (CRM, spreadsheet, Airtable-style store) sits in the write path.
- **Build the substrate before the agents** — the prototype did the reverse, which caused most of its pain.

## Backlog / known caveats (cross-milestone)
Tracked follow-ups surfaced during implementation/integration. None block current milestones, but address each before its relevant downstream work. Fuller context lives in `_memory/`.

- **[M2] Rate limiter requires Redis 7+ (version floor).** The token bucket reads the clock server-side via `redis.call('TIME')` to avoid cross-worker NTP skew. `TIME` is non-deterministic, so a write after it is rejected on Redis ≤6 unless the Lua script calls `redis.replicate_commands()`; Redis 7 (effects replication — what we compose/test) allows it, which is why tests pass. Correct for our stack but a hard floor. Fix is ~1 line (a `redis.replicate_commands()` guard for 6-compat) or revert to client-time if we'd rather not require 7. **Decision pending.**
- **[M2] `multi_lock` can let an early lock expire while blocking on a later one.** Acquisition is deadlock-free (sorted order), but locks it acquires *manually* don't auto-renew (only `async with` does), so under heavy contention with a short TTL, lock A can lapse while waiting on lock B. Mitigated today by the deterministic order + a sane TTL; the full fix is all-or-nothing acquire with retry. This is the one genuine soft spot.
- **[M2×M6/M8] Classify written claims for tenant reuse-scope.** M2's `claim` carries `reuse_scope{public_footprint|tenant_private}` + `tenant_id`, defaulting to `public_footprint`. M3 writes no claims, so nothing to fix now — but any component that writes claims from ICP-derived / scoring / client-knowledge data (M6 Pass-A scoring, M8 deep profiling) **must** classify them `tenant_private` (route through M2's `identity.classify_reuse_scope`, or set `reuse_scope`/`tenant_id` explicitly), or client-tuned claims leak into the cross-tenant *public* base. M3's `field_definition.signal_class` / namespace is a natural classifier input. (`icp_spec`/overrides are already client-scoped; `pack`/`source_profile` are intentionally shared.)
- **[tooling] Alembic revision-id scheme — RESOLVED (adopted).** The zero-padded sequential ids collided across parallel branches (M2 & M3 each produced `0005/0006/0007`; fixed at integration by renumbering M3 → `0009–0011`). Convention now adopted — see **Database migrations (Alembic) — conventions** above (hash ids + `alembic merge`).
- **[naming] `tenant_id` vs `client_id`.** M2 uses `tenant_id` (claim table); M3 uses `client_id` (`icp_spec` key, source-profile overrides) for the same concept. Harmonize at leisure (cosmetic; pick one term in a future cleanup).
