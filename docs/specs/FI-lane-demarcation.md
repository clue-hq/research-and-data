# FI lane demarcation registry — the FI-2 implementation agent's exclusive territory vs every other lane

**Status: AUTHORITATIVE for scope boundaries once founder-acked; amended 2026-08-10 for the R0 chat-integration join. Purpose: guarantee zero overlap between the FI-2 implementation agent (working in the primary worktree on `docs/specs/FI-2-workspace-account-layer.md`) and every other lane (A–G). Every lane charter defers to this registry on "who owns what"; a lane needing something inside FI-2's territory requests it from that agent, never builds it.**

Date: 2026-08-08. Compiled from: the FI-2 spec (§§2–9), the FI-2 agent's actual commit trail in this worktree (`74046e1a..4715756c`, 30+ commits), and its closing entries (`_memory/2026-08-08-fi2-slice0-complete.md`, `_memory/2026-08-08-fi2-slice1-backend-complete.md`).

---

## 1. The FI-2 agent's territory

### 1.1 Already shipped (do not touch, do not duplicate, do not "fix")

**Slice 0 (complete):** `project_account` membership table + writers at all entry sites (P1); `run_lineage` + registration at every production run-mint site (P2); `research_scope` field-species attribute + must-declare authoring guard (P3); identity repairs H1 (embed-at-creation + alias admission), H2 (strong-key auto-merge enrichment), H3 (import→project membership); backfills; the canonical two-projects-one-account fixture.

**Slice 1 backend + Task 6a (complete):** the entire **`platform/api/clue_api/frontend_read/`** package (`app.py`, `accounts_list.py`, `account_detail.py`, `contacts.py`, `committee.py`) behind `CLUE_FRONTEND_READ_ENABLED` — and with it, **items other lanes must now strike from their scope because they exist here**:
- The **FI-1 error envelope** (`{error:{code,message,requestId}}` + `X-Request-Id`) — built in `frontend_read/app.py`.
- **CORS** for the read surface (wildcard-refusing, GET/OPTIONS, 500-inside-CORS-layer) + the founder-ratified posture (same-origin proxy in prod; exact localhost origin in dev).
- The **L2 `subject_entity_id` index** (migration `870fe4f2af87` — current Alembic head).
- The `researchStatus` vocabulary on the wire (`not_started|in_progress|needs_review|completed|suspended`, `not_launchable` ratified in).
- The as-built contract section + **D-4..D-7 ratifications** recorded in `apps/frontend/docs/api-contracts/accounts.md` and FI-1 §9.

### 1.2 FI-2's remaining scope (reserved — no other lane may start any of it)

- **Slice 1 Task 6 — the accounts-flow frontend flip.** All D-4..D-7 Zod amendments and fixture→HTTP adapter flips for the accounts & contacts flow: `apps/frontend/src/features/accounts/**` (models, data adapters, and the components those force), plus `apps/frontend/docs/api-contracts/accounts.md`. **This means the former "Lane A" accounts scope belongs to the FI-2 agent — see §2.1.**
- **Slice 2 — C7 lineage convergence:** `platform/api/clue_api/research_view_readers.py` `allowed_run_ids` suppliers → `run_lineage`; the lens-isolation query tests; the deferred project-lens detail endpoints if a post-MVP surface asks.
- **Slice 3 — economics:** §6.1 fresh-skip in `platform/api/clue_api/account_entity_research.py`; §6.2 bundle shrink in `platform/api/clue_api/exa_deep_preparation.py` (+ launch-estimate netting in `account_research_fleet_launch.py`); §6.3 Sumble freshness/skip fixes in `sumble_account_gaps.py` + `sumble_entity_research_tools.py`; **§6.4 project-scoped supersede predicates** in `subsystems/research/clue_research/narrative/positioner.py` + `narrative/fields.py` (value-narrative payload), `discovery_scoring/tiering/engine.py::persist_tier`, and committee lineage reads.
- Its substrate modules: `clue_research/membership.py`, the `run_lineage` helpers in `claimstore/`, `frontend_read/**`, and its follow-up list (keyset index, score last-collected-wins with §6.4, surviving_id hardening, etc.).

---

## 2. Lane-by-lane exclusion audit

### 2.1 Lane A — RETIRED as a standalone lane
The accounts & contacts flow's contract amendments and adapter flips (its entire original scope) are FI-2 slice 1 Task 6, and D-4..D-7 are already ratified and recorded. **No Lane-A agent is spawned.** The only surviving Lane-A content — the *projects/chat* feature's contract amendments — is already Lane D pillar P6 and moves there wholly. Nobody but the FI-2 agent edits `apps/frontend/src/features/accounts/**` or `api-contracts/accounts.md`.

### 2.2 Lane B — authenticated-principal foundation + backend edge remainder
**Governing contract:** `docs/specs/FI-lane-B-authenticated-principal-contract.md` (founder-ratified 2026-08-08). The founder selected a real authenticated Clue user for `actor_id` and ruled that Clerk is an authentication/session adapter only: Clue Postgres owns canonical users, workspaces, memberships, roles/permissions, and audit identities; no Clerk value may be a primary key, foreign key, tenancy key, domain id, or authorization decision key.
**Keeps:** B0–B5 of that contract (internal user/auth-identity/workspace-membership substrate; provider-neutral authentication + authorization; frontend session/BFF; the generic principal→`ToolContext` seam; production cutover), defects **L3** (fleet projection columns), **L4** (suspend_failure event row), and the shared-surface generalization of the error envelope *only if/when a second surface needs it* (adopt `frontend_read/app.py`'s pattern; never rewrite it). Lane D owns the chat-turn derivation and resolution of `action_ref`; Lane B owns the authenticated internal principal it binds to.
**Strikes:** CORS (built + posture ratified; the one open CORS item — cross-origin POST widening/path split for phase-2 — belongs to **Lane D D2**, which owns the POST routes needing it); the error envelope for the read surface; the L2 index; **L1 is Lane E's** (slice E0, already chartered).
**Must never touch:** `frontend_read/**`, the L2 migration, FI-2 `project_account` membership/run-lineage/economics substrate, `apps/frontend/src/features/accounts/**`, or `api-contracts/accounts.md`. `workspace_membership` in Lane B is human access membership and is a different table/species from FI-2's account↔project `project_account` membership.

### 2.3 Lane C — is the FI-2 agent
Not a lane to staff. Coordination with it happens through this registry and the founder, not through parallel edits.

### 2.4 Lane D — production chat + Option-B launch
**No deliverable overlap with FI-2.** Explicit exclusions to keep it that way:
Lane D never touches `frontend_read/**`,
`apps/frontend/src/features/accounts/**`, `api-contracts/accounts.md`, FI-2
membership/lineage tables, or any slice-2/3 file in §1.2. Its frontend work is
`apps/frontend/src/features/projects/**` + `api-contracts/projects.md` only.
Touchpoints, read-only or additive: it consumes Lane B's closed
`RequestPrincipal` and internal user/membership ids, and owns the durable chat
turn/gate plus `turn-action:<turn_id>` derivation; it *consumes* FI-2's
`researchStatus` vocabulary (already ratified with `not_launchable` reserved
for exactly this lane); its D4 status read-back consumes the L2 index (done) and
Lane B's L3; its POST routes own their CORS posture per the ratified
same-origin-proxy decision; it registers its routers at the composition-root
chokepoint (§3).

**R0 chat-integration join amendment (founder-ratified 2026-08-10).** D5's
original exclusion of project lifecycle remains historically correct; it is
not retroactively widened. A bounded join slice in the Lane-D worktree now owns
the minimum project-side seams required to make Home chat real:

- `GET /api/v1/home`, atomic `POST /api/v1/projects`,
  `GET /api/v1/projects/sidebar`, and `GET /api/v1/projects/:projectId`;
- the project-workspace/Home/sidebar repositories and Zod models under
  `apps/frontend/src/features/projects/**`;
- the shared authenticated application shell and the project-header sidebar
  control, provided the edit stays within projects/shell files and does not
  enter `features/accounts/**`;
- adoption of Lane B's new internal `project.write` permission through a
  coordinated policy-version change; and
- consumption of Lane C's account/contact ids only through its published read
  contracts and typed refs, never by editing Lane C files.

The join slice explicitly does **not** own project rename/delete/project-pin,
project-wide archive, artifact generation/read/edit, design-subsystem mounting,
or Lane E synthesis. New projects return `artifacts: []` and render the empty
Gallery until the separately governed design/artifact integration lands. Lane
D still owns the stream-control-frame, terminal closure, queue-vs-running,
Stop, and transcript-recovery corrections. The exact executable contract is
`apps/frontend/docs/api-contracts/projects.md` § "Executable integration
contract".

### 2.5 Lane E — on-completion synthesis
**Exclusions (already in its charter, now binding via this registry):** never edits `narrative/positioner.py` / `narrative/fields.py` supersede predicates (§6.4 is FI-2 slice 3's — E3 lands only *after* it); never adds `run_lineage` registration (prose claims ride the triggering job's already-registered `research_run_id`); never touches `account_entity_research.py` (§6.1 is FI-2's), `current_values`/merge, or `frontend_read/**` (its prose claims reach that surface automatically through the merge — if the detail endpoint needs a `summary` field added, that is a *request to the FI-2 agent*, not a Lane E edit). Its own files: `narrative/prose.py` (new), `narrative/research_views.py` (the L1 tuple entry only), a new prose pack via `narrative_wiring`, the fleet-handler synthesis step + tool. File-disjoint from FI-2 by construction; the one shared *file* risk is `narrative/fields.py` if the prose pack were declared there — it must live in its own module instead.
**Awareness note:** the parallel `feat(verification): add temporary runtime bypass` commit (`784fb662`, `verification/handler.py`) — Lane E's judge integration must be validated with that toggle OFF.

### 2.6 Lane F — M8D R11 DEEP-phase bridge
No overlap: FI-2 names the bridge a non-goal, and its own closing entry *depends* on Lane F ("committee/contacts serve [] on live data until R11" — the read layer's committee sections are fixture-proven, waiting on the bridge; and R11's AC must re-run the contacts-suite shapes against real M8D output, per FI-2's follow-up list). This dependency **strengthens the case for promoting F to a parallel lane now** (founder confirmation still pending). Lane F's files (`durable/project*`, fleet wake sources, verification selector) are disjoint from every FI-2 file.

### 2.7 Lane G — resolver/waterfall composition
**Must never touch** `exa_deep_preparation.py`, `sumble_account_gaps.py`, `sumble_entity_research_tools.py`, or `account_research_fleet_launch.py` (all FI-2 slice 3). Its territory is the unwired registrations only: `synthesis_wiring.py`, `stage0_scrape_binder` at the `build_toolbelt` call sites, `register_deterministic_resolvers` + provider binders, at the composition roots per the chokepoint protocol.

---

## 3. Chokepoint protocol (unchanged, now with named holders)

1. **Api composition root** (`projections_app.py` / `projections_main.py` / `fleet_main.py` / `toolbelt_wiring.py`): the FI-2 agent has active edits (router mount). Other lanes add *registration calls only*, each in its own milestone-owned `*_wiring.py` module (the PF-7 pattern), and rebase around FI-2's edits — never restructure these files while FI-2 slices are in flight.
2. **Alembic single head:** current head is FI-2's `870fe4f2af87`, and FI-2 is the *active* minting lane in the primary worktree. Every other lane chains off head at branch time and expects an `alembic merge` at integration; nobody renumbers.
3. **`api-contracts/accounts.md` is FI-2's document.** Other lanes reference it; only the FI-2 agent (and founder) write it. `api-contracts/projects.md` is Lane D/the R0 chat-integration join's on the same terms; its 2026-08-10 executable section outranks its retained historical proposal.

## 4. Corrections to the standing decision queue

Because the FI-2 agent obtained ratifications in parallel: **D-4, D-5, D-6, D-7 are RATIFIED** (FI-1 §9 + the accounts contract doc; incl. `not_launchable`, no `overallFit`, D-7 fixture-only fields dropped as industry-pack placeholders, signals=type-count, CORS posture). **Lane D §6 is now FULLY RATIFIED (2026-08-08)**: D1 async worker-executed turns; D2 complete token streaming; D3 durable generic `agent_gate` (immutable gate + insert-once answer record); D4 `actor_id` is a real Clue-owned authenticated user id, authorized through a Clue-owned workspace membership per Lane B's contract — Clerk authenticates only and no Clerk value is a database foreign key; D5 estimate tool deferred post-V1 (server-derived maximum-spend stored on the gate, re-verified at launch); D6 trial kept dev-only. Still open for the founder: Lane E §7 (D1/D2/D4), **Lane F promotion**, the D-8 policy quartet, and FI-2's own standing acks (C6 re-pin, hq_geo-at-mint owner, workspace research_scope NOT NULL).

---

*Founder ack pending. On ack, each lane charter is read as amended by §2 of this registry.*
