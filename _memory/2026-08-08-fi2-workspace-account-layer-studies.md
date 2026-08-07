# 2026-08-08 — FI-2: workspace-global account layer — requirements + verification studies

Session context: follow-up to `docs/specs/FI-accounts-contacts-contract-gap-review.md` (FI-1). Founder stated the
intended scope model in chat; two Opus read-only studies verified the substrate. Design proposal presented for
discussion; **nothing ratified or implemented yet**.

## Founder requirements (stated 2026-08-08, in chat — supersedes the S1 "structural mismatch" framing)

1. **Workspace-global normalized account list is intended.** Every account added through any project must
   identity-resolve against existing workspace accounts; on match, append information; else create. (This is what
   the substrate was built for — the frontend's workspace-global `/accounts` is correct product intent, not a bug.)
2. **Two lenses on one account spine.**
   - *Global lens* (`/accounts/:id`): union of ALL projects' research on that account, each piece attributable to
     the producing project. Side-peek → full page from the global list.
   - *Project lens* (`/projects/:id` → target account): ONLY that project's research (its deep research, insights,
     committee, fit vs its ICP).
3. **Per-project re-research is intentional** (founder explicitly retracted the earlier "never re-research within
   TTL" blanket): project-RELATIVE fields (scoring, narrative, resonance angles, committee, campaign insights) are
   researched anew per project/campaign. Project-NEUTRAL facts (firmographics, tech stack, funding…) are governed
   by freshness TTL — a second project must NOT re-spend on a fresh neutral fact; a stale one it refreshes for
   everyone. **Founder confirmed this field-level split matches intent (chat, 2026-08-08).**

## Study 1 — identity/creation paths (verified, file:line cites in chat transcript)

- **The identity spine is real**: every production creation path funnels through `resolve → disposition`
  (admission gate, Exa Websets materialization, import, trial, stage-0). Domain-keyed convergence works:
  P1 discovers acme.com, P2 imports acme.com → same entity_id (via `account_entity_primary_domain_ws_key`).
- **Hole 1**: discovery/admission-created accounts are never embedded (`embed_account` called only from
  import/seeds/client_kb) → a later name-only re-encounter scores 0.40 (< 0.70 review floor) and silently
  duplicates instead of routing to review. Tests mask this (test seed helper embeds).
- **Hole 2**: "resolve to existing + append" is NOT implemented — no ingest caller passes `subject_entity_id`,
  so `update_account`/`plan_merge` (alias/registry/geo union) is unreachable; new aliases/DUNS from a match are
  discarded. Claims DO append; the entity row does not enrich.
- **Hole 3**: no account↔project junction (FI-1 D-3 confirmed). `import_accounts` takes NO project parameter at
  all — imported accounts are project-invisible everywhere. Discovery has a real trace only on the Websets path
  (`discovery_candidate_link` → `discovery_batch.project_run_id`); non-Websets discovery only via the uuid5
  forward-computable claim run_id.
- Minor: demo scripts 03–06 bypass identity (dev-only); `registrable_domain` does no public-suffix/subdomain
  folding (us.acme.com ≠ acme.com — documented deferral).
- No workspace-global account list SELECT exists anywhere (confirms FI-1 S2).

## Study 2 — claim scoping + TTL economics (verified)

- **Claim row has NO project/project_run/icp column** — only `run_id` (NOT NULL, one-way: can't SQL-join back to
  project) + `product_id` column. Project pinning is a per-family `value_json` convention + Python supersede
  predicates; DB enforces none of it.
- **Canonical merge (`current_value`/`current_values`) is workspace-global** — merges across all projects'
  claims. Global-lens semantics already exist; project-lens filtering exists ONLY in the C7 research-view read
  family (`context_scope='project_run_pinned'` + `allowed_run_ids=(project_run_id, account_run.id)`).
- **Cross-project collisions under the new model**: `account.value_narrative` supersede key is
  (product, ICP, persona) — P2 would SUPERSEDE P1's narrative; M6.4 tier claims supersede across project runs;
  committee claims (`contact.persona`/`role_on_committee`) append forever with no research_view_route (not
  lens-attributable). These must become project-scoped when the two-lens model lands.
- **TTL-gated no-respend is NOT implemented on the live M8D account path**: `account_entity_research.py` starts
  every admitted field unresolved (never reads `current_values`); Exa bundle prep includes every authorized field
  (no freshness skip); Exa operation reuse fingerprint includes `project_id`+directive sha → never crosses a
  project boundary. **The contact runtime HAS the check** (`contact_entity_research.py:331-370` fresh+evidence+
  no-conflict → completed, existing claim ids as coverage evidence) — the pattern to port.
- Pre-spend gate = authority gate (schema/identity/source/lock), no freshness knob. The freshness-gap components
  (`compute_gap_fields`, `_deep_account_gap_fields`) exist but are behind the M8D R1 quarantine (M8A path).
- Sumble gap tool refuses confidently-resolved fields but ignores `freshness_state` and raises (not skips);
  un-caught on the M8D path.
- Packs activate per-ICP (`icp_spec.enabled_packs`); field_key is a global PK; `current_values` takes an explicit
  key list from the compiled FieldPlan → no cross-pack contention; no per-project read filter needed for packs.
- M9.5 re-research cadence queue has no production drainer (only age-out is wired).

## Design proposal presented (awaiting founder discussion)

Five pillars: (P1) `project_account` membership junction; (P2) run-lineage join table (`run_id → workspace/
project/project_run/kind`) generalizing the C7 `allowed_run_ids` mechanism — RECOMMENDED over adding a
`claim.project_id` column (product_id-style contract delta = the fallback if DB enforcement is later wanted);
(P3) field species as registry data (`research_scope: project_neutral | project_relative` on field_definition);
(P4) economics: port contact-runtime fresh-skip to account runtime for neutral fields, shrink Exa bundle
accordingly, fix Sumble freshness/raise, make narrative+tier supersede predicates project-scoped;
(P5) two-lens read layer = FI-1 D-1 BFF with global lens (canonical merge + attribution) and project lens
(lineage-filtered). Plus identity repairs: embed-on-discovery-create, append-on-match (`update_account` wiring),
import gains project param. Resolves FI-1 D-2/D-3.

## Ratification + spec (closing entry, 2026-08-08)

- Founder RATIFIED (in chat): the five pillars, the run-lineage table (over a `claim.project_id` column), and the
  project-scoped supersede change. Field-species defaults to be enumerated in the spec for row-by-row sign-off.
- **Spec written: `docs/specs/FI-2-workspace-account-layer.md`** — full design + slice plan (slice 0 substrate/
  repairs → slice 1 global lens → slice 2 project lens + C7 lineage convergence → slice 3 economics), testing
  strategy (canonical two-project/one-account fixture), open items. FI-1 gained a §9 ratification log
  (D-2 + D-3 resolved by FI-2).
- **Still gating implementation: FI-2 §5.2 species table sign-off** (esp. the two ⚠ rows:
  `operational_pain`/`strategic_moves` and `account.resonance.*` — recommended neutral, founder may flip).
- No code changed this session; docs + memory only, committed locally.
