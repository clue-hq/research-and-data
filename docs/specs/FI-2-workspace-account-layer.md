# FI-2 — The workspace-global account layer: one account spine, two lenses

**Status: design RATIFIED by founder 2026-08-08** — the five pillars (§2–§7), the run-lineage fork (§3, chosen over a `claim.project_id` column), and the project-scoped supersede change (§6.4) are approved. **The field-species default table (§5.2) awaits explicit founder sign-off row-by-row.** Implementation has not started; §9 is the build plan.

Date: 2026-08-08. Branch: `platform/frontend-integration`.
Parent: `docs/specs/FI-accounts-contacts-contract-gap-review.md` (FI-1). This spec **resolves FI-1 D-2** (the workspace-global scope rule) and **FI-1 D-3** (account↔project membership), and refines D-1 (the read layer now has a defined two-lens semantics). FI-1's other decisions (D-4…D-10) remain open and are not touched here.
Method: founder requirements stated 2026-08-08 in session, verified against code by two read-only studies (identity/creation paths; claim scoping + TTL economics). Every baseline fact in §1 carries a file:line citation from those studies. Study digests: `_memory/2026-08-08-fi2-workspace-account-layer-studies.md`.

---

## 0. Ratified requirements (the product model)

- **R1 — One normalized, workspace-global account spine.** Every account entering the system through *any* path (discovery, import, directive, manual) identity-resolves against the workspace's existing accounts before creation. On a match: reuse the existing `account_entity` and **append** new information (entity enrichment + claims). On a miss: create the account as a workspace-global entity. There is never a per-project copy of an account.
- **R2 — Two lenses over the one spine.**
  - **Global lens** (frontend `/accounts`, `/accounts/:id`): the workspace's full account list; an account's detail is the **union of every project's research** on it, each piece attributable to the project that produced it.
  - **Project lens** (project → target-account screens): only the research **this project** produced — its deep-research facts, its insights, its committee, its fit score against *its* ICP.
- **R3 — Field-level research economics** (founder-confirmed split):
  - **Project-neutral facts** (firmographics, technographics, funding, HQ, …) are workspace truth governed by **freshness TTL**: a second project touching the account must **not re-spend** on a fresh neutral fact; if the fact is stale, whichever project hits it first refreshes it, and the refresh benefits every project.
  - **Project-relative fields** (fit/intent/tier vs an ICP, value narrative, committee targeting, campaign insights) are researched **anew per project** — that repetition is intentional, not waste; it is where campaign value lives.
  - (This supersedes the founder's earlier blanket "never re-research within TTL" statement, explicitly retracted 2026-08-08.)
- **R4 — Membership is real data.** Which projects target an account is first-class, queryable state — not derivable folklore.

---

## 1. Verified baseline (what the substrate does today)

### 1.1 The identity spine is real (R1 is ~90% built)

- Every production creation path funnels through the M2 identity seam (`resolve` → `disposition`) before minting an `account_entity`: discovery admission (`discovery_scoring/gate/admission.py:221-232`), Exa Websets materialization (`platform/api/clue_api/exa_websets_materialization.py:973-979`), CSV import (`stage0/import_accounts.py:193,327-334`), trial add-account (`trial/spine.py:307-346`), stage-0 client + seeds (`stage0/client_kb.py:335-355`, `stage0/seeds.py:401-421`). `account_entity` rows are minted by exactly one function (`identity/entities.py:148-184`).
- Domain-keyed convergence works: P1 discovers acme.com, P2 imports acme.com → **same `entity_id`**, via `_deterministic_account` (`identity/resolve.py:221-230`) against `account_entity_primary_domain_ws_key (workspace_id, primary_domain)` (`alembic 7f1868a127aa:62-68`), with `surviving_id` chain-following and race safety (Redis `(workspace, domain)` lock, `admission.py:278-292`).
- Only a deterministic strong-key hit can auto-merge — fuzzy tops out at 0.85 < the 0.95 auto-merge floor, enforced as data (`identity/policy.py:113-135`).

### 1.2 The identity holes (slice-0 repairs, §8)

- **H1 — discovery-created accounts are never embedded.** `embed_account` has exactly three call sites (import, seeds, client-KB); the admission/disposition new-entity path never embeds. A later *name-only* encounter of the same company scores 0.40 (cosine arm = 0, `resolve.py:184`) — below the 0.70 review floor — and **silently duplicates** instead of routing to review. The test that asserts mid-band behavior seeds embeddings itself (`tests/identity/test_review.py:59-63`), masking this.
- **H2 — "resolve-to-existing + append" is unimplemented at the entity layer.** No ingest caller passes `subject_entity_id`, so the `auto_merge → plan_merge → update_account` enrichment branch (alias union, registry-id union, fill missing domain/geo — `identity/entities.py:282-323`, `canonicalize.py:41-60`) is unreachable from ingest (`review.py:393-403`). Claims append; the entity row discards a match's new aliases/DUNS/geo.
- **H3 — no account↔project junction; imports are projectless.** Confirmed FI-1 D-3. `import_accounts` accepts **no project parameter at all** (`import_accounts.py:138-150`). The only real discovery→project trace is the Websets path (`discovery_candidate_link` → `discovery_batch.project_run_id`); non-Websets discovery is traceable only by forward-recomputing the uuid5 run id. There is also **no workspace-global account list SELECT anywhere** (confirms FI-1 S2).
- Minor/deferred: demo scripts 03–06 bypass identity (dev-only); `registrable_domain` does no public-suffix/subdomain folding (`us.acme.com` ≠ `acme.com`, documented deferral at `identity/normalize.py:112-113`).

### 1.3 Claim scoping: global lens is free; project lens is partial

- The claim row has **no project/project_run/icp column** — only `run_id uuid NOT NULL` (`0002_claim_table.py:104`; not SQL-joinable back to a project) and the `product_id` column (`1b71451d48cd:124-138`). Project pinning today is a per-family `value_json` convention (`icp_key`, `icp_version`, `project_run_id`) plus Python supersede predicates; the DB enforces none of it.
- The canonical merge (`claimstore/merge.py` — `current_value` :371, `current_values` :418) filters only on entity/field/live/retention/`WorkspaceScope` — **workspace-global by construction**. That *is* the global lens's value semantics.
- Project-scoped reading exists only in the C7 research-view read family: `context_scope='project_run_pinned'` keeps claims whose `run_id ∈ allowed_run_ids = (project_run_id, account_run.id)` (`claimstore/research_view_queries.py:230-235,321-327`; suppliers `research_view_readers.py:268-272,300-304`). It covers only routed fields.

### 1.4 Cross-project collisions the two-lens model must fix

- **Value narrative:** `_live_for_persona` keys on `(product_id, persona, icp_spec_version[, icp_key])` with **no run/project dimension** (`narrative/positioner.py:494-521`); P2 regenerating the narrative **supersedes P1's** — destroying P1's lens.
- **Tier (M6.4 path):** `persist_tier` payload carries no `project_run_id` (`discovery_scoring/tiering/engine.py:246-259`) → cross-project-run supersession. (The discovery-selection tier path *is* run-pinned, `:277-328`.)
- **Committee:** `contact.persona`/`contact.role_on_committee` are appended per run with no supersede and **no research_view_route** (`profiling/committee/fields.py:127-145`, `worker.py:168-216`) — not lens-attributable today.

### 1.5 The TTL economics are aspirational on the account path

- **The live M8D account runtime performs no freshness check before spending**: every admitted field starts `unresolved` regardless of existing fresh claims (`platform/api/clue_api/account_entity_research.py:191-195`; no `current_values` read anywhere in the file), and Exa bundle prep ships **every** authorized field to the provider (`exa_deep_preparation.py:137-193`).
- **The contact runtime already implements the intended behavior** (`contact_entity_research.py:331-370`): fresh + evidence-backed + conflict-free fields are born-`completed`, with the existing claim ids folded into coverage evidence (`:527-535`) and per-field reasons `existing_claim_stale` / `existing_claim_conflict` (`:480-485`). This is the pattern to port.
- Exa operation reuse never crosses a project boundary: `reuse_fingerprint` includes `project_id` + directive sha (`exa_deep_acquisition.py:940-954`; `durable/external_research.py:293-361`). Correct for relative research; irrelevant for neutral facts once §6.1 skips them pre-provider.
- The pre-spend gate is an *authority* gate (schema/source/identity/lock — `verification/pre_spend.py:453-613`), not an economics gate; no freshness knob exists. The components that do freshness-gap planning (`durable/planning.py:116-143`, `profiling/account.py:184-216`) are behind the M8D R1 quarantine.
- Sumble gap eligibility refuses confidently-resolved fields but **ignores `freshness_state`** and **raises** rather than skips (`sumble_account_gaps.py:349-393`); on the M8D path the error is uncaught (`sumble_entity_research_tools.py:448-455`).
- Packs need no per-project read filter: activation is per-ICP (`icp_spec.enabled_packs`, `0010_icp_spec.py:92-115`), `field_key` is a global PK, and `current_values` takes the compiled FieldPlan's explicit key list — pack-A and pack-B claims coexist on one account without contention (`icp/compiler.py:198-207`, `registry.py:57-58`).

---

## 2. Pillar P1 — `project_account` membership (RATIFIED)

A real junction table; the prerequisite for both lenses.

```sql
CREATE TABLE project_account (
    workspace_id       text        NOT NULL,
    project_id         text        NOT NULL,   -- project slug (id vocabulary per FI-1 §2)
    account_entity_id  uuid        NOT NULL,
    added_via          text        NOT NULL CHECK (added_via IN ('discovered','imported','manual','directive')),
    added_at           timestamptz NOT NULL,
    PRIMARY KEY (workspace_id, project_id, account_entity_id),
    FOREIGN KEY (account_entity_id, workspace_id) REFERENCES account_entity (id, workspace_id),
    FOREIGN KEY (project_id, workspace_id) REFERENCES project (id, workspace_id)  -- the composite b366c985ca12 pins
);
CREATE INDEX project_account_by_account ON project_account (workspace_id, account_entity_id);
```

Semantics and rules:

- **Write sites** (each wrapped in the same transaction as the admission/import it records): discovery admission (project derived from the batch/run's `project_run_id → project_id`), Websets materialization, `import_accounts` (gains a project parameter — §8.3), directive scoping (`account_research_directive_account` insert → membership upsert), and any future manual add. Idempotent upsert; the first row wins (`added_via`/`added_at` are the *first* add; later adds via other channels are no-ops on the row).
- **Merge handling:** when identity merges loser → survivor, membership rows re-point to the survivor (same transaction as `mark_merged`; `ON CONFLICT DO NOTHING` against an existing survivor row). Within-workspace only, like every merge (B3).
- **Stage-0 seeds and the client entity stay projectless by design** — they are workspace-level objects (lookalike seeds / the client itself), visible in the global list with zero memberships. Accepted consequence; the global list must render membership-less accounts gracefully.
- **Backfill** (one-shot, part of the migration's companion script, dev-data only per the B3 synthetic-data ruling): from `discovery_candidate_link` (admitted/merged → survivor entity, `discovery_batch.project_run_id → project_id`) and `account_research_directive_account` (directive → `project_id`). Legacy imports are unbackfillable (no project recorded) and are left membership-less.
- **Ownership:** the table and its writer helpers live in `clue_research` (identity-adjacent — proposed module `clue_research/membership.py`); call sites are wired at the api composition root per the established pattern. No milestone package imports another to write membership.

Resolves FI-1 D-3. `projects[]` and `primaryProjectId` on the frontend account row read from here (`primaryProjectId` = earliest `added_at`, a recorded policy, not `ORDER BY created_at DESC` folklore).

---

## 3. Pillar P2 — `run_lineage`, the claim→project join spine (RATIFIED — chosen over a `claim.project_id` column)

Every claim already carries `run_id NOT NULL`; what is missing is the back-join. One new table supplies it:

```sql
CREATE TABLE run_lineage (
    run_id          uuid        PRIMARY KEY,
    workspace_id    text        NOT NULL,
    project_id      text        NULL,       -- NULL = workspace-level run (stage-0, seeds, client-KB)
    project_run_id  uuid        NULL REFERENCES project_run (id),
    kind            text        NOT NULL CHECK (kind IN
        ('discovery','import','scoring','tiering','entity_research','committee','contact_research',
         'narrative','stage0','enrichment','manual')),
    created_at      timestamptz NOT NULL
);
CREATE INDEX run_lineage_by_project ON run_lineage (workspace_id, project_id);
```

Semantics and rules:

- **Registration is at run creation, not per claim.** Every run-id-minting path registers one row: the discovery run id (uuid5 over `project_run:icp` — `discovery_scoring/phases.py:111-124`), the import batch run id (`import_accounts.py:131-135`; `project_id` becomes known via §8.3), entity-research runs (`entity_research_job` creation already carries `project_run_id`), committee runs (either the account-deep run or the `project_run_id` per `c6d84aa84b79`), scoring/tiering runs, stage-0 (kind `stage0`, `project_id NULL`). Registration is an idempotent upsert (`ON CONFLICT (run_id) DO NOTHING`) so replays are safe.
- **The project lens read predicate** is: `claim.run_id IN (SELECT run_id FROM run_lineage WHERE workspace_id=:ws AND project_id=:project)`. This **generalizes** the C7 `allowed_run_ids` mechanism rather than competing with it: C7's suppliers (`research_view_readers.py:268-272,300-304`) migrate to sourcing their run sets from `run_lineage` (slice 2), so there is exactly one attribution mechanism.
- **Backfill:** discovery lineage is mechanically recomputable (uuid5 forward from each existing `project_run` × its `icp_key`/`icp_version`); `entity_research_job` rows carry `research_run_id` + `project_run_id`; `account_run` joins via `project_run_id`. Legacy import runs are unbackfillable → `kind='import', project_id NULL` if registered at all.
- **The rejected alternative, recorded:** adding a nullable `project_id` column to `claim` (precedent: `product_id`, `1b71451d48cd`). Rejected for now because it touches frozen `core` + the append-only claim table, requires threading project context through every writer, leaves history NULL, and buys nothing the lineage join doesn't — **revisit only if per-claim DB enforcement of project scope becomes a requirement.** If it ever lands, `run_lineage` remains as the run registry; the column would be stamped *from* it.
- **Ownership:** table + helpers in `clue_research/claimstore/` (it is a claim-adjacent join spine); registration calls wired at composition roots.

---

## 4. Pillar P3 — field species as registry data: `research_scope` (RATIFIED; defaults table §5.2 awaiting sign-off)

A new field-registry attribute, mirroring the `reuse_scope` design exactly (`82831d3fa4c5` pattern):

- `field_definition.research_scope text NULL CHECK (research_scope IN ('project_neutral','project_relative'))` — mirrored on `workspace_field_definition` (`client.*` fields default `project_neutral` per §5.2; not CHECK-forced, so a future declared-relative client field stays possible). `NULL` = class default resolved via a `core.default_research_scope(field_class, field_key)` helper; a `<pack>.*` field **must declare one** (no safe default), enforced the same way `reuse_scope` is (`registry.py:61-70` precedent).
- **`project_neutral`** ⇒ (a) readable in **every** lens regardless of which project's run produced the claim; (b) spend is TTL-governed: fresh ⇒ skip (§6.1); stale ⇒ refresh, benefiting all projects; (c) the canonical merge stays its read semantics (already correct).
- **`project_relative`** ⇒ (a) read through the lineage filter — the project lens shows only its own; the global lens shows all, grouped/attributed by project; (b) always researched per project (no cross-project skip, ever — even a "fresh" claim from P1 is *P1's* answer, not P2's); (c) supersede predicates must be project-scoped (§6.4).
- The attribute drives **both** economics and lens membership from one declaration — policy as data, per the platform's standing rule.

---

## 5. The species assignment

### 5.1 Decision rule

A field is **project_neutral** iff its true value is a fact about the account/contact in the world, invariant to which client product, ICP, or campaign is asking. A field is **project_relative** iff its value is defined *relative to* an ICP/product/campaign (a score, a targeting decision, an argument) — or is a synthesis whose angle is campaign-flavored.

### 5.2 Default table — **each row requires founder sign-off** (⚠ = judgment call, argued below)

| Field family | Default | Notes |
|---|---|---|
| `core.*` (name, domain, employee_count, revenue_band, hq_location, company_about, logo when it lands) | **neutral** | Firmographic world-facts. |
| `account.*` technographics / funding / leadership (`recent_funding`, tech-stack fields) | **neutral** | World-facts; TTLs already tuned per class (180d). |
| `account.operational_pain`, `account.strategic_moves` | **neutral** ⚠ | The *facts* (they migrated data centers; they're hiring SREs) are account truth any campaign can cite. The campaign-specific *use* of them lives in the narrative. Counter-argument: they are deep-synthesized (tier-4) and the research prompt is ICP-flavored, so P2's pass may surface different pains. Recommendation: neutral — P2's research still runs for its relative fields and may *add* pain claims (append, corroborate, or conflict-flag), which the merge already handles; we don't re-buy what's fresh merely to re-ask the same question. |
| `account.resonance.*` (culture, sentiment, frustrations) | **neutral** ⚠ | Same argument as operational_pain: the resonance *facts* are about the account; 90d TTL already reflects volatility. The campaign-relative "resonance angle" is narrative work. (The original FI-2 chat proposal listed resonance as relative; this table refines that to: facts neutral, angle relative. If you want each campaign to re-mine resonance from scratch, flip this row to relative.) |
| `account.scoring.fit` / `.intent` / `.tier` | **relative** | Definitionally ICP-relative; already pinned (product, ICP[, run]). |
| `account.value_narrative` | **relative** | The per-persona argument; product+ICP+campaign-flavored. |
| `contact.persona`, `contact.role_on_committee` | **relative** | The buying committee is a *targeting decision per campaign* (founder model: each project resolves its own committee). |
| `contact.current_title` / `job_function` / `job_level` and other professional facts | **neutral** | True regardless of project; 30d TTL already set. |
| `contact.facet.*` (recent_post, public_appearances, causes, …) | **neutral** | Personal world-facts; governance (binding/use-class/retention) already constrains them orthogonally — species does not weaken any gate. |
| `client.*` (workspace dynamic fields) | **neutral** | Workspace-scoped by construction. |
| `<industry-pack>.*` | **must declare** | Pack authors declare per field at registration, like `reuse_scope`. Most pack fields (registry facts, filings) will be neutral. |

### 5.3 Interaction with governance (unchanged)

Species is orthogonal to, and never overrides: `reuse_scope` (privacy classification), identity-binding + use-class gates, display governance, retention/EXPIRED age-out. A neutral fact still respects every gate; a relative claim still gets stamped/classified identically.

---

## 6. Pillar P4 — economics + write-behavior changes (RATIFIED)

### 6.1 Port the contact runtime's fresh-skip to the account runtime (the core no-respend mechanism)

In `account_entity_research.py`'s authorization/first-plan path, mirror `contact_entity_research.py:331-370`:

1. Read `current_values(conn, [subject], admitted_field_keys, scope=WorkspaceScope.for_workspace(ws))`.
2. A field is **born-complete** iff it is `project_neutral` AND its current value is `freshness_state == fresh` AND has an evidence span AND no open conflict. Project-relative fields are **never** born-complete (that is R3's second half).
3. Born-complete fields fold their existing claim ids into the coverage ledger as evidence (the contact pattern, `:527-535`), with per-field reasons (`existing_claim_fresh`; `existing_claim_stale` / `existing_claim_conflict` when not skipped) so the ledger explains *why* money was or wasn't spent.
4. `unresolved = admitted − completed` as today.

### 6.2 Shrink the provider bundle accordingly

`exa_deep_preparation.py` (and the M8D provider wiring's field selection) excludes born-complete fields from the bundle; if the account-axis bundle is empty, no provider operation is reserved at all. The launch estimate (`account_research_fleet_launch.py:234`) should be recomputed net of skips so the human approves an honest number — flagged as a should-have in §9 slice 3, not a blocker.

### 6.3 Fix the Sumble gap tool's freshness blindness

`sumble_account_gaps.py:349-393`: (a) a **stale** confidently-resolved field becomes eligible (consult `merged.freshness_state`, not just confidence/conflict); (b) an ineligible field becomes a governed *skip* (or `EntityResearchGovernedRejection`) on the M8D path instead of an uncaught raise (`sumble_entity_research_tools.py:448-455`).

### 6.4 Project-scope the supersede predicates (RATIFIED — write-behavior change)

- **Narrative:** `positioner._live_for_persona` adds the project dimension to its match key (payload gains `project_id`, mirroring how `icp_key` already rides `value_json` "because the claim row has no icp column" — `narrative/fields.py:62`); P2's narrative for the same (product, ICP, persona) now *coexists* with P1's instead of superseding it. Each lens reads its own via lineage.
- **Tier (M6.4 path):** `persist_tier` payload + supersede predicate gain `project_run_id`/project, aligning it with the discovery-selection tier path which already pins.
- **Committee:** stays append-per-run at the write layer (the run already identifies the project via lineage); reads become lineage-filtered. Optional refinement (open item §11): supersede *within* the same project's successive runs to keep the live set tidy.
- Within one project, supersession behaves exactly as today — the change only stops **cross-project** destruction.

### 6.5 Explicitly out of scope for P4

No new pre-spend-gate knob (the gate stays an authority gate); no un-quarantining of the M8A gap planners (the R1 quarantine ruling stands — the fresh-skip lives in the M8D runtime, not in resurrected M8A code); no M9.5 cadence drainer (separate backlog item; stale-refresh here is opportunistic-on-touch, not scheduled).

---

## 7. Pillar P5 — the two-lens read layer (RATIFIED; the FI-1 D-1 BFF, scope rule now defined)

> **MVP ruling (founder + co-founder, 2026-08-08 — amends this section):** for the MVP there is exactly **one account detail view — the workspace-global one**. Clicking an account inside a project's target-account list opens (in a new frontend tab) the global account view with the account **list filtered to that project's memberships**; it does not open a separate project-scoped detail page. The "project lens" therefore ships, for MVP, as a **membership filter on the global list** (`projectId` query param over `project_account`), while the detail view always serves the attributed union (R2's global lens). The dedicated project-scoped detail endpoints below are **deferred post-MVP** — kept in this spec because the substrate that powers them (lineage, species, project-scoped supersedes) is required regardless: it drives the per-project attribution *grouping inside* the one detail view, the economics, and cross-project write safety. Additional MVP requirement made explicit: **every global list row carries `projects[]`** — the projects using that account as a target — served from `project_account`.

Flag-gated, workspace-scoped, Band-2 semantic (enums/numbers/ISO timestamps/opaque ids — FI-1 D-4/D-5 vocabulary applies), one endpoint per screen need, composed at the api root over untouched mechanism surfaces:

**Global lens**
- `GET …/accounts` — `account_entity` workspace scan + `current_values` batch over the list-row neutral field set + `project_account` memberships + per-project research status (M8D job aggregation; needs the L2 `subject_entity_id` index) + **per-project attributed fit scores** (no representative-run fiction — FI-1 D-2 dissolves: ambiguity is shown, not guessed away).
- `GET …/accounts/:id` — the union detail: neutral facts from the canonical merge; relative sections **grouped by project** via `run_lineage` (each project's insights/score/narrative/committee block, labeled); membership-less accounts render with neutral facts only.
- `GET …/accounts/:id/contacts` — union of committees across projects, lineage-attributed, served through the governed reader (never `identity.contact_ids_for_account` — FI-1 §4.5 ruling stands).

**Project lens (MVP: a list filter; dedicated endpoints deferred)**
- MVP: `GET …/accounts?projectId=…` — the global list endpoint filtered by `project_account` membership; detail clicks resolve to the global detail view.
- Deferred post-MVP: `GET …/projects/:id/accounts/:aid` — neutral facts (merge) + **only this project's** relative claims (lineage filter); committee via `ContactEligibilityResolver.resolve_account` with the project context the URL carries (the FI-1 contacts-context problem resolves structurally: project_run/product derive from the project's latest run — a *recorded* rule, per project, not a global guess). The same rule serves the MVP detail view's per-project committee grouping.
- C7 research-view surfaces keep their contracts; in slice 2 their `allowed_run_ids` suppliers source from `run_lineage` so the two read families cannot drift.

Frontend contract consequences (recorded into `apps/frontend/docs/api-contracts/accounts.md` at implementation per the branch charter): the account detail schema gains the per-project grouping for relative sections; `projects[]`/`primaryProjectId` bind to membership; everything else rides FI-1 D-4/D-5/D-6 as already registered.

---

## 8. Identity repairs (slice 0 — small, independently valuable)

1. **H1 fix:** call `embed_account` on the admission/disposition new-entity path (the two `insert_account_entity` sites in `review.py:425,693`), + a one-shot backfill embedding every existing unembedded `account_entity`. Also populate `Observation.aliases` at admission (`admission.py:94-99` currently forfeits the alias-overlap arm). Regression test: discovery-created account, later name-only import → lands in the review band, not silent NEW_ENTITY.
2. **H2 fix:** on an `AUTO_MERGED` disposition where the observation carries information the survivor lacks, apply the existing `update_account` union (aliases ∪, registry_ids ∪ survivor-wins, fill missing domain/geo, better-name adoption) as a deliberate *enrich-survivor* step — **not** by routing ingest through `auto_merge` (no loser entity exists). Review-band behavior unchanged (mid-band still mutates nothing). This makes R1's "append further information" true at the entity layer.
3. **H3 fix (write side):** `import_accounts` (+ the `import_accounts@1` tool → `@2` contract) gains an optional `project_id`; when present, membership rows + run-lineage registration are written; when absent (workspace-level list load), the accounts are global-only — matching the founder model where an import *into a project* is the normal case.
4. **Deferred, tracked:** public-suffix/subdomain folding in `registrable_domain` (H5); demo-script bypasses (dev-only).

---

## 9. Implementation plan (slices, each independently landable; per-slice sign-off per the branch charter)

Migrations follow the adopted conventions (hash revision ids off current head; hand-written + reversible; one head; `make db-smoke` gate).

**Slice 0 — substrate: tables, attribute, repairs.**
- Migrations: `project_account` (§2), `run_lineage` (§3), `field_definition.research_scope` + `workspace_field_definition.research_scope` (§4). Companion backfills (§2, §3) as idempotent scripts.
- Writers: membership upserts at the four write sites; lineage registration at every run-mint site; merge re-pointing.
- Identity repairs §8.1–8.3.
- Field-species declarations for all shipped packs per §5.2 (blocked on the §5.2 sign-off).
- AC: (a) db-smoke green, single head; (b) every new claim written by any production path has a resolvable `run_lineage` row (integration test per path); (c) discovery/import convergence test extended to assert membership rows for both projects; (d) the H1 regression test; (e) an H2 test asserting alias/registry union on strong-key match; (f) enum-parity + no-domain-tables-at-M0 guards stay green.

**Slice 1 — global lens (unblocks the frontend `/accounts` flow; per the §7 MVP ruling this is the whole MVP read surface).**
- The §7 global endpoints, flag-gated, **including the `projectId` membership filter and `projects[]` on every list row**, + the L2 `subject_entity_id` index (FI-1 backend-fixes list).
- Frontend: repository HTTP adapters for the accounts list/detail flipped per FI-1 sequencing once D-4 (absence vocabulary) lands in the Zod schemas — that dependency is FI-1's, not new. The project→account click navigates to the global view with the filter applied (frontend routing decision, recorded in the contract doc).
- AC: list returns every workspace account incl. membership-less seeds; `projectId` filter returns exactly the membership set; every row's `projects[]` matches `project_account`; detail groups relative sections by project with correct attribution on a two-project fixture; no display strings on the wire.

**Slice 2 — C7 lineage convergence (project-lens detail endpoints deferred post-MVP per §7).**
- C7 `allowed_run_ids` suppliers migrate to `run_lineage`. The deferred `GET …/projects/:id/accounts/:aid` endpoints land only when a post-MVP frontend surface asks for them — the substrate is ready either way.
- AC: C7 views byte-identical before/after the supplier migration; a query-layer test proves the lineage predicate isolates P1's relative claims from P2's (the lens-isolation guarantee, asserted at the substrate even though no MVP endpoint exposes it).

**Slice 3 — economics (P4).**
- §6.1 fresh-skip, §6.2 bundle shrink (+ honest estimate), §6.3 Sumble fixes, §6.4 supersede predicates.
- AC: two-project fixture — P2's launch on a fresh-researched account spends zero on neutral fields (coverage ledger cites P1's claims as evidence), fully researches relative fields, and P1's narrative/tier/scores remain live and unchanged; a stale neutral fact is refreshed once and both lenses see the refresh.
- Ordering note: slice 3 only *matters* once a second project launches research on a shared account; it can trail the read slices without blocking frontend work, but §6.4 (supersede) should land **before** any production second-project research run to avoid lens destruction.

Non-goals of all slices: launch authority (FI-1 D-9), chat (FI-1 phase-2), the DEEP-phase bridge (M8D R11 — separate spec), any un-quarantining.

---

## 10. Testing strategy (cross-slice)

- **The canonical fixture is two projects, one account**: P1 discovers acme.com under ICP-A; P2 imports it under ICP-B. Every slice's AC runs against it. Extend with the name-only duplicate case (H1) and the merged-loser case (membership re-pointing).
- Lens isolation is asserted at the read layer (endpoint-level) *and* at the query layer (lineage predicate unit tests), so a BFF bug can't mask a substrate bug.
- Economics assertions are ledger-based (gate decisions + coverage evidence + provider-operation counts), not log-based — the spend trail is already append-only data.
- Migration backfills get before/after row-count + spot-check assertions in the companion scripts.

---

## 11. Open items (tracked, non-blocking)

1. **§5.2 row sign-offs** — especially the two ⚠ rows (`operational_pain`/`strategic_moves`, `resonance.*`).
2. Committee within-project supersede-vs-append refinement (§6.4).
3. Launch-estimate netting of fresh-skips (§6.2) — should-have.
4. `registrable_domain` public-suffix folding (§8.4) — improves R1 recall; separate small PR.
5. M9.5 cadence drainer (scheduled stale-refresh) — complements §6.1's opportunistic refresh; existing backlog item, unowned.
6. Whether the global account list needs a materialized read model for filterable claim-derived columns (FI-1 §3.1's `POST /accounts/query` finding) — defer until the plain list's performance is observed.

---

*Ratification log: 2026-08-08 — founder approved the five pillars, the run-lineage fork, and the project-scoped supersede change (session transcript). Same day, founder + co-founder amended §7 with the MVP ruling: one global account detail view; project lens ships as a membership filter on the global list; dedicated project-scoped detail endpoints deferred post-MVP; `projects[]` required on every list row. §5.2 signed off 2026-08-08 with the recommended defaults (founder's proceed-with-slice-0 instruction; the two ⚠ rows — `operational_pain`/`strategic_moves` and `account.resonance.*` — stand as **neutral**; flipping either later is a one-line registry change). Slice 0 implementation plan: `docs/specs/FI-2-slice0-implementation-plan.md`. resolutions get recorded into `apps/frontend/docs/api-contracts/accounts.md` as each slice lands, per the branch charter.*
