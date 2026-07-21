# PB-B3 — Scoped memory, slice 1 (Doc M)

**Lane:** B3 of Phase B (`docs/specs/PB-phase-b-platform-infra-core.md` §2) · **Branch:** `platform/b3-memory` (cut from `e615e81`)
**Architecture sources:** Doc M (`clue-hq-scoped-memory-and-context-assembly.md`) — authoritative; harness doc §5/REQ-08/REQ-12/REQ-15; treaty §2-B3/§3.
**Status:** open. Spec-first per the M0–M13 workflow; acceptance criteria = the treaty exit gate + Doc M §19 (minus the founder-ruled deferrals below).

---

## 0. Founder rulings for this slice (2026-07-21, this session)

1. **Q1 — claim-churn staleness deferred.** `memory_claim_ref` ships (indexed both directions) so
   reference-health / scope-churn are *computable*, but the live claim-reading signals land at
   integration/Phase C. Slice-1 staleness = **contradiction events + `cycles_since_confirmed`** only.
2. **Q2 — kill-switch is BOTH layers.** The real mechanism is a **per-workspace DB toggle +
   audit journal** enforced at both seams (Doc M §17a semantics); `CLUE_MEMORY_ENABLED`
   (settings, default on) is a deploy-level master default layered on top (treaty §3.2 flag).
3. **Q3 — seam contracts live in `clue_core/memory.py`** (new append-only file, contract-delta):
   enums, submission/bundle/label/outcome types, the two seam protocols, the typed
   `memory_disabled` no-op. Implementation stays in `clue_memory`; no subsystem ever imports it.
4. **Q4 — reconciliation** = deterministic pre-checks first (no LLM for exact/normalized
   restatement), then LLM judgment through the injected `LLMGateway` protocol
   (`CLUE_MEMORY_RECONCILE_MODEL`); offline tests run a scripted stub. The eval golden set is
   **file-based fixtures + a memory-local eval module** (cannot import research's M9.6 harness — Rule S1).
5. **Q5 — `account` scope is DEFERRED** (see §7 note). The v1 `scope_type` vocabulary is
   `{workspace, brand, product, project}`; `account` is a later **append-only** addition (enum
   member + FK column + CHECK arm + spine-anchor) once the account⇄spine linkage question is
   settled. `project` from birth, never `campaign` (treaty binding).
6. **Q6 — caps/budgets shape lives in `clue-config` `schema.py`** (append-only, `MergePolicy`
   pattern), default-constructed + injectable; per-client `config_revision` plumbing rides at
   integration.

## 1. Goal & scope

The second substrate: the Doc M memory model on the spine's scope ids, the **two enforced
seams**, inject-only deterministic assembly with the ids-never-bodies bundle journal, the
workspace kill-switch, provenance-graded born trust, and write-time reconciliation with its eval
golden set.

**Owned surfaces** (treaty §2-B3): `subsystems/memory/clue_memory/**`, `tests/memory/**`, new
hash-id migration(s), `clue_core/memory.py` (+ `__init__` re-export — contract-delta),
`clue-config` appends (settings flag/model id; `MemoryCaps` shape), root `pyproject.toml`
append-only (one new import-linter contract; memory package deps). **Must not touch:**
`subsystems/research/**`, `platform/**`, `durable/`, storage code, `clue_api` wiring.

**Explicitly out of slice 1** (each with its owner):
- The kickoff-interview writer (Phase C step 4) — the seam + `record_kickoff` are ready for it.
- The `edit_distilled` distiller (content subsystem) — the seam accepts the provenance class;
  pattern-strength activation threshold is config with a v1 default, no producer yet.
- The `memory_review` human-review queue surface (treaty/frontend) — `agent_observed` records are
  born `proposed`; the queue UX is REQ-16/17 work.
- The DSAR cascade *from claim erasure* (compliance-side, integration) — memory ships its own
  `erase_subject` / `lock_memory` engine verbs; the cross-subsystem trigger wires at the api root
  with the Doc D backlog. Incidental-ref severance rides the same follow-up.
- Claim-churn staleness signals (ruling 1), `account` scope (ruling 5), run-manifest recording of
  the toggle state (fleet-owned, B1/Phase C), and everything in Doc M Part VII (search,
  consolidation, vectors, type→scope matrix, per-project kill-switch override, multi-brand).

## 2. Package layout (`clue_memory`)

```
clue_memory/
  __init__.py      — public surface: the two seam impls + lifecycle/compliance/switch verbs
  model.py         — row models (Memory, MemoryEvent, BundleJournalEntry…), mem_ id factory
  _store.py        — PRIVATE raw-SQL access (spine style, AsyncConnection); only in-package callers
  write.py         — MemoryWriteSeam impl: validation chain → born trust → reconciliation → persist
  reconcile.py     — deterministic pre-checks + ReconcileJudge protocol + LLM judge impl
  assembly.py      — ContextAssembly impl: gate → rank → assemble → label → journal
  lifecycle.py     — caps/dormancy/eviction/backfill, record_kickoff, confirmation/contradiction
  switch.py        — kill-switch: workspace toggle + audit, settings master default
  compliance.py    — erase_subject (tombstone + content redaction), lock_memory (Art. 21)
  evals/
    golden.py      — golden-set runner + scoreboard (memory-local; no research import)
    fixtures/*.json — reconciliation golden set (file-based)
```

Package deps: `clue-core`, `clue-db`, `clue-config` (+ pydantic/sqlalchemy). **No**
`clue_gateway` import — reconcile binds to the `LLMGateway` *protocol* (core); the concrete
client/stub is injected by the caller (api root later; tests inject a scripted fake). A new
import-linter contract enforces: `clue_memory` imports only core+db+config.

Seam-only access: Rule S1 + the agents contract already forbid every other package from importing
`clue_memory` at all; in-package, `_store` is private and a guard test asserts no module outside
`clue_memory` imports `clue_memory._store`.

## 3. Data model (column-level)

All hand-written reversible migrations, hash revision id off `98422adaaa38`. Spine style: text
status/enum columns with named CHECKs (+ parity tests against the `clue_core.memory` enums), text
PKs (`mem_` prefixed uuid4 hex), invalid states die at the schema.

**`memory`**
- `memory_id text PK`
- `workspace_id text NOT NULL REFERENCES workspace` — tenancy root, fail-closed at both seams
- `scope_type text NOT NULL CHECK IN ('workspace','brand','product','project')`
- `scope_brand_id / scope_product_id / scope_project_id` — nullable **composite FKs pinned to the
  memory's own `workspace_id`** via the spine anchors (`brand_workspace_anchor`,
  `product_workspace_anchor`, and a new `project_workspace_anchor UNIQUE (project_id, workspace_id)`
  added to `project` by this migration — append-only, mirrors the existing anchors). A
  cross-workspace scope reference is unrepresentable.
- `scope_check`: exactly the column matching `scope_type` is NOT NULL (`workspace` scope → all
  three NULL; the workspace itself is the scope instance).
- `scope_id text GENERATED ALWAYS AS (…CASE on scope_type…) STORED` — one canonical grouping key
  for reconciliation/assembly/indexing.
- `type text NOT NULL CHECK IN ('preference','behavioral_learning')`
- `trigger text NOT NULL` — applicability description (labeling in v1)
- `body text NOT NULL` — the learning; **never quoted personal-claim content** (write-seam rule)
- `provenance_class text NOT NULL CHECK IN ('user_stated','edit_distilled','agent_observed')`
- `trust_grade smallint NOT NULL CHECK (0..4)` — **ordinal, not blended**: born 3/2/1 by
  provenance class (user_stated/edit_distilled/agent_observed); +1 per confirmation (cap 4),
  −1 per contradiction (floor 0). Every change journaled.
- `creating_quote text NULL` — conversational/diff evidence pointer
- `status text NOT NULL CHECK IN ('proposed','active','dormant','superseded','invalidated','locked','tombstoned')`
- `superseded_by text NULL REFERENCES memory`
- `confirmation_count int NOT NULL DEFAULT 0`, `last_confirmed_at timestamptz NULL`,
  `cycles_since_confirmed int NOT NULL DEFAULT 0` — cycle-relative; **no wall-clock drives behavior**
- `subject_entity_id uuid NULL REFERENCES contact_entity(id)` — mandatory for person-adjacent
  content (write-seam `PreconditionFailed` if absent). DB-level FK only; no code import (Rule S1 intact).
- `retention_class text NOT NULL DEFAULT 'standard' CHECK IN ('standard','person_adjacent')`
  + CHECK: `person_adjacent ⇔ subject_entity_id IS NOT NULL`
- `created_at timestamptz NOT NULL DEFAULT now()`
- Index: `(workspace_id, scope_type, scope_id, type, status)` — the gate/reconcile query.

**`memory_claim_ref`** — `(memory_id FK, claim_id uuid FK → claim(id))`, PK `(memory_id, claim_id)`
(forward), index on `claim_id` (reverse: DSAR cascade + reference health, both deferred consumers).

**`memory_event`** — every status transition / lifecycle event, journaled with actor+cause:
`event_id uuid PK`, `memory_id FK`, `workspace_id`, `event_type text CHECK IN ('created',
'activated','confirmed','contradicted','superseded','invalidated','reactivated','evicted',
'backfilled','locked','tombstoned','kickoff_cycle')`, `from_status/to_status text NULL`,
`actor text NOT NULL` (writer id or `'engine'`), `cause text NULL` — the auditable sentence
(losing comparison for evictions, reconcile verdict, …), `created_at`.

**`memory_bundle_journal`** — one row per assembly (REQ-12 extension): `journal_id uuid PK`,
`workspace_id`, `recipe text`, `requested_types jsonb`, `scope_stack jsonb` (ids only),
`included jsonb` — array of `{memory_id, scope_type, scope_id, type, provenance_class,
trust_grade, cycles_since_confirmed, confirmation_count, claim_ref_count}`, `excluded jsonb` —
array of `{memory_id, losing_comparison}`, `cross_branch_pairs jsonb` (§5), `bundle_hash text`
(canonical-bytes sha256 — the determinism witness), `created_at`.
**Ids-never-bodies is structural:** no body/trigger/quote text column exists in this table;
rendering dereferences live and erased memories render as tombstones.

**`memory_switch`** — `workspace_id text PK REFERENCES workspace`, `enabled bool NOT NULL`,
`updated_at`, `updated_by text NOT NULL`. Missing row = enabled.
**`memory_switch_audit`** — `audit_id uuid PK`, `workspace_id`, `enabled bool`, `actor text NOT NULL`,
`created_at` — who/when, the thing that makes "memory was off" verifiable.

## 4. The write seam

`clue_core.memory.MemoryWriteSeam.submit(MemorySubmission) -> SubmissionOutcome` — every writer
submits; no writer inserts rows. The enforcement chain, in order, identically for every writer:

1. **Kill-switch** (workspace toggle ∧ settings default) → typed **`MemoryDisabled`** outcome —
   a quiet no-op, *not* an error.
2. **Tenancy + scope validity** — `workspace_id` stamped fail-closed; the scope FK insert dies at
   the schema on a cross-workspace/dangling scope (IntegrityError = enforcement, spine style);
   an `account`-scope submission → `PreconditionFailed` naming the deferral.
3. **Subject binding** — person-adjacent content without `subject_entity_id` →
   **`PreconditionFailed`** (an *error*: the proposal is malformed). Person-adjacency in v1 =
   writer-declared (`subject_entity_id` present ⇒ `retention_class='person_adjacent'`) plus
   deterministic lexical guards (email/phone/handle in body ⇒ subject binding required).
4. **Species check + body rule** — deterministic lexical guards fail fast (fact-shape markers,
   verbatim-quote patterns, contact-data leakage); the reconciliation judge's verdict carries
   `species_ok`/`body_ok` as the semantic layer. A fact-shaped submission → **`Rejected`** with
   the CKB path named; a body-rule violation → `Rejected(body_rule)`.
5. **Born trust** — `user_stated` → born `active`; `edit_distilled` → born `proposed` (pattern
   threshold = versioned config, no producer in v1); `agent_observed` → born `proposed` (review
   queue is Phase C; born status is the poisoning defense *now*).
6. **Reconciliation** (§6) over `active ∪ dormant` of the same `(workspace, scope, type)`.
7. **Persist + journal** (`memory_event` rows for every transition), then **store-cap
   enforcement** (§7) if the write activated a record.

`SubmissionOutcome` is a closed union: `Accepted{verdict: added|updated|superseded|noop_confirmed|
reactivated, memory_id, status}` · `Rejected{reason: fact_shaped|body_rule, detail}` ·
`MemoryDisabled` · (`PreconditionFailed` raises — malformed, not unwelcome).

## 5. The read seam — deterministic assembly

`clue_core.memory.ContextAssembly.assemble(AssemblyRequest) -> MemoryBundle | None`:

1. **No-step short-circuits:** requested_types empty → `None` (a recipe declaring no memory types
   receives no memory step); kill-switch off → `None` (no phantom empty bundle; nothing journaled —
   the switch audit is the record).
2. **Gate (deterministic):** `workspace_id` fail-closed ∧ `scope ∈ request's scope stack`
   (workspace + brand + optional product + project) ∧ `type ∈ requested_types` ∧ `status='active'`.
3. **Rank:** one lexicographic sort — `trust_grade DESC, cycles_since_confirmed ASC,
   confirmation_count DESC, memory_id ASC` (total order ⇒ total determinism). Applied per scope
   under the per-scope-type **bundle budget** (`MemoryCaps`). Excluded records are journaled with
   the losing comparison; they stay `active`.
4. **Assemble in stability order** brand → product → project → workspace-passthrough content?
   No: `workspace → brand → product → project` in spine order — **cache semantics only, zero
   priority semantics** (labels carry all meaning; position means nothing).
5. **Label everything:** scope, type, trigger, provenance class, trust grade, cycle freshness,
   confirmation count, claim-ref ids. The label is the agent's reconciliation input.
6. **Cross-branch tension:** sibling-scope (product × project) entries of the same type are all
   included, labeled, and recorded as `cross_branch_pairs` in the journal — the engine never
   picks a winner across orthogonal axes; the journal is the future type→scope-matrix evidence.
7. **Journal** (§3 `memory_bundle_journal`) — ids + label metadata + excluded + hash; never bodies.

**Determinism contract:** `MemoryBundle.canonical_bytes()` — stable sorted-key JSON over
ids/bodies/labels, no wall-clock fields — same store state + same request ⇒ byte-identical, and
`bundle_hash` in the journal witnesses it.

## 6. Write-time reconciliation (+ golden set)

Order: **deterministic pre-checks** (same `(workspace, scope, type)`, normalized body equality →
NOOP-confirm without an LLM call) → **`ReconcileJudge` protocol** (LLM-assisted judgment,
engine-executed): candidates = `active ∪ dormant`, submission + candidate bodies fenced as
untrusted data (M9.3-style hardening), returns `{verdict: add|update(target)|supersede(target)|
noop(target), species_ok, body_ok, rationale}`. Unparseable/malformed judge output fails safe:
the submission is parked `proposed`, never silently activated.

Engine executes the verdict: ADD (new row) · UPDATE (supersession with `superseded_by` link,
successor inherits confirmations? **no** — successor is a new record; the trail carries history) ·
contradiction → supersede/invalidate with trust −1 on the loser, trail preserved · NOOP →
`confirmation_count+1`, freshness reset, trust +1 (cap). **Reactivation rule:** a NOOP/UPDATE
match against a **dormant** record promotes it back to `active` with history intact (zombie-twin
guard); the reactivation may evict the now-lowest active record (cap pressure signal).

**Golden set:** `clue_memory/evals/fixtures/*.json` — each fixture: existing store (rows),
submission, expected outcome (verdict/rejection/target). Covers: exact + normalized restatement
→ NOOP; refinement → UPDATE; contradiction → SUPERSEDE; genuinely-new → ADD; dormant restatement
→ REACTIVATE (never duplicate); fact-shaped → REJECT(CKB); quoted-personal-content → REJECT(body
rule); cross-type non-match → ADD. `evals/golden.py` runs the engine with a scripted judge and
scores; `make check` runs it offline (deterministic); swapping the judge model re-runs the same set.

## 7. Lifecycle, caps, kill-switch, compliance verbs

- **Store caps** (`MemoryCaps.store_caps` per scope type, versioned config shape in
  `clue-config/schema.py`; defaults small — the right numbers are empirical): activation beyond
  the cap evicts the lowest-ranked active record → `dormant`, journaled with the losing
  comparison. **Eviction order = bundle ranking inverted** — same sort, read from the other end.
- **Backfill:** a freed active slot (supersession/invalidate/tombstone/lock) promotes the
  highest-ranked dormant record, deterministically, journaled.
- **Cycle freshness:** `record_kickoff(workspace, scope_stack)` increments
  `cycles_since_confirmed` on active ∪ dormant memories of those scopes — **only when memory is
  on** (off-cycles don't age memories, §17b). Wall-clock appears nowhere in ranking.
- **Kill-switch:** `set_memory_enabled(workspace, enabled, actor)` — instant, audit-logged;
  effective state = settings master default ∧ workspace toggle; enforced at the two seams and
  nowhere else. Off ≠ erasure: freeze-intact. DSAR verbs operate regardless of the switch.
- **Compliance verbs (in-package; cascade wiring deferred):**
  `erase_subject(workspace, subject_entity_id)` → tombstone every subject-bound memory —
  status→`tombstoned` **and content columns redacted to a sentinel** (body/trigger/quote), the
  sanctioned mutation exception, so no personal substring survives at rest (no
  `faithfulness_verdict.rationale` debt repeat); refs severed. `lock_memory(memory_id, actor)` →
  Art. 21 `locked`: row + content survive, excluded from every bundle (gate selects `active` only).

## 8. Acceptance criteria

Treaty exit gate + Doc M §19 minus deferrals — the test battery (`tests/memory/**`):

**Model & seams:** seam-only access (import guard on `_store` + Rule S1 already machine-checked) ·
fact-shaped submission rejected naming the CKB path · body-rule rejection · cross-tenant fuzz
matrix over workspaces ⇒ zero cross-tenant rows/bundles (fail-closed) · cross-workspace/dangling
scope dies at the schema (IntegrityError) · `account` scope → `PreconditionFailed` (deferral note).

**Write path:** born-trust matrix (provenance × born status) · reconciliation over active ∪
dormant · zombie-twin test (dormant restatement reactivates with history intact) · same-scope
contradiction ⇒ supersession with linked trail; the read path never serves both sides · malformed
judge output parks `proposed`.

**Read path:** byte-identical determinism on a golden store (same state + request ⇒ identical
`canonical_bytes` + `bundle_hash`) · journal lists included ids + labels and excluded ids +
losing comparison, contains no body text (structural: no such column) · no-declared-types ⇒ no
memory step · cross-branch conflict both-included-and-labeled + journaled pair.

**Lifecycle:** annual-campaign fixture — a once-cycle-old confirmed `user_stated` memory outranks
a week-old unconfirmed `agent_observed` record (no wall-clock; trust inversion impossible) ·
eviction order equals bundle ranking inverted (property test over generated stores) · backfill
promotes the highest-ranked dormant record.

**Compliance:** `erase_subject` leaves no personal substring at rest or in any rendered
bundle/journal view; subject-bound memories tombstoned; refs severed · objection lock excludes
from every subsequent bundle while preserving the row.

**Kill-switch:** write seam returns typed `MemoryDisabled` (not an error) · assembly emits no
memory step · audit row records who/when · off-cycles don't increment `cycles_since_confirmed` ·
toggle back on serves the store unchanged (freeze-intact) · settings master default off blanks
every workspace.

**Standing gates (treaty §5):** `make check` green · full DB suite fresh + rerun-idempotent ·
`make db-smoke` up→down→up, exactly one head · scripts/01–06 Recipe-#1 regression untouched and
green · `_memory/` session note.

## 9. Follow-ups recorded (integration / Phase C)

1. `account` scope: append enum member + `scope_account_entity_id uuid` FK + CHECK arm (+ decide
   the account⇄spine anchor); until then the write seam rejects it loudly.
2. Claim-churn staleness (reference health, scope churn) — needs a sanctioned read over `claim`;
   decide raw-SQL vs seam at integration.
3. DSAR cascade from claim erasure → `erase_subject`/ref-severance wiring at the api root
   (with the Doc D backlog); `memory_review` queue surface; run-manifest toggle recording (fleet).
4. Kickoff-interview writer (Phase C step 4) calls `submit` + `record_kickoff`; seeds/staleness
   surfacing per Doc M §13.
