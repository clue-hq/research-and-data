# 2026-08-01 — Residual backend backlog beyond PC-C8 (prioritization session, no code changed)

Assessment session on `platform/c8-context-card`. Question: with the C8 context-card correction
(Slices 0–4) as the active plan, what other backend fixes does the CLI-trial experience demand?
Sources: `2026-08-01-stage0-acceptance-run.md`, `2026-08-01-sumble-gate-canary-status.md`,
`2026-08-01-f11-diagnosis.md`, `2026-08-01-l3-context-audit-and-c8-spec.md`,
`2026-07-31-phase-c-adversarial-review.md`, and the founder's troubleshooting transcript.
CLI-side items (raw-paste coalescing F13, `/confirm-product <arg>` dispatcher trap) are explicitly
out of scope per founder direction.

## Gaps inside/adjacent to C8 itself (fold into the slices)

1. Post-human-gate freshness: C8's event-driven card invalidation must carry an explicit
   acceptance test — turn N+1 after `/confirm-product` (or `/confirm-icp`) sees the confirmed
   state. The live transcript showed a one-turn-stale snapshot plus confirmation boilerplate.
2. Routing-time dedup of identical `(route_key, quote)` per project. Without it the card's
   40-statement cap fills with duplicates (the thrice-routed "three triggers" lines) and can evict
   material statements. Write-time fix, not just card-selection fix.
3. L6 overflow must degrade like L3 (omission + checkpoint), never 422 — Slice 4 scope, but the
   failure class is identical; don't let it become the next brick.
4. Slice 3 (long-lived Recipe #0) still has no repo-durable spec; needs the lease/checkpoint/
   idempotency design ruling written before implementation.

## Tier 1 — spend safety (before ANY further Sumble spend)

- Sumble credit-overage releases the idempotency ledger → unbounded repeat paid calls on retry
  (`trial/sumble.py:292`; adversarial review #6).
- Per-request `ClueTrialSpine` construction calls `clear_resolver_bindings()` on the process-global
  registry (incl. `/doctor`) — silently discards paid snapshot data mid-run; latent under any
  concurrency (`coordinator.py:198`; F11 side observation + review shortlist).
- 429/5xx misclassified as spend-unknown → permanent wedge; `retry_persistence` uncallable.
- 3-credit cap not aggregate/atomic/durable; server accepts arbitrary `sumble_credit_cap`.
- `/cost` non-cumulative/manifest-only → cumulative from Postgres.
- Acquisition ledger key `sumble-acquisition-v1` is body-independent (poisoned trial c1 replays a
  stale pre-F9 payload as hard drift) — version the key or fold in the select-list version.
- C6 agent model spend hardcoded `cost_millicredits=0` → delegation budget/canary cost gates vacuous.

## Tier 2 — agent-mintable authority (same family as the just-fixed honesty bugs)

- Readiness floor computed from MODEL-SUPPLIED metrics (`stage0/governed.py:739`) — the agent can
  mint READY and open discovery spend. Flagged twice (acceptance-run minors + review #3). Compute
  metrics system-side; at minimum mark rows by `created_by_actor` and refuse agent-authored metrics
  at spend gates.
- Interview grants tier-1 to any caller-nominated `client_entity_id`; stamps model-supplied
  immutable `identity_binding` (never calls `classify_binding`).
- C2 source promotion can silently redefine a live source manifest (no new-key guard on the source
  side); reachable autonomously with `auto_promote_tier3_sources=True`.

## Tier 3 — ICP ↔ source-portfolio coherence (the F11 structural finding)

- ICP synthesis/confirmation must validate rubric field keys + source priors against the registered
  `source_manifest`/bound resolvers; loud "rubric has no resolvable sources" at confirmation.
- `fit=0.0` over a wholly-unfillable rubric is indistinguishable from a real low score — add a
  typed zero-coverage marker (the only tell today is `components[].evidence_claim_ids == []`).
- Same class already latent elsewhere: ICP-synthesis proposals hardcode `tier_plan=("generic_web",)`
  but no generic_web resolver is registered → promoted fields permanently unfillable.
- NPPES/NPI resolver is the real build item for the healthcare vertical (F11 option B).

## Tier 4 — durability & product decisions surfaced live

- Trial spine drives with no lease + constant `worker_id`s defeat the C5 generation fence →
  concurrent duplicate phase drives possible.
- Server-side `TurnInput.message` bound (backend decision deferred from Task 6; CLI 16KB cap has no
  server counterpart).
- Entailment vs composite facts: verbatim `_exact_quote` lock means conversational KB stays at
  0 claims (lists/booleans can't pass). Founder decision needed: keep strict (KB fills via
  recon/research only), teach atomic single-span claims, or typed composite values. Do not weaken
  casually.
- `synthesize_icps@1` exposes only `proposal_count` — agent can't see grounded status.

## Tier 5 — compliance before go-live (not blocking synthetic-data trials)

- DSAR uncascaded: `AgentPrivacyService.erase_subject`/`clue_memory.erase_subject`/C3
  `IngestionEngine.erase` have no production callers; erased contact identity served verbatim by
  the owner-reference endpoint IDENTITY branch; agent artifacts mostly lack subject bindings.
- Retention-expired-cannot-win-merge vacuous in production (`record_lawful_basis` uncalled);
  retention sweep can permanently wedge HANDOFF; corroboration/conflict product-blind.
- Trial reads memory via raw SQL bypassing the Doc-M assembly gate (incl. objection-LOCKED).

## Hygiene — the gates are red

`make check` red on branch: memory import-contract violation (`trial/stage0_runtime.py:18` imports
`clue_memory` directly — a real boundary break, not test noise), repo-wide ruff format/check drift,
secret-scanner false positive from a Sumble test fixture literal. A red baseline hides new
regressions; fix before more implementation waves. Also: 2026-07-27 C5/C6 confirmed defects still
have zero fix commits; root CLAUDE.md `[C1×C6]` entry stale (resolved by C6-D11).
