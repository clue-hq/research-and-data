# Lane D slice D0 — implementation brief: the durable thread shell

**Charter:** `docs/specs/FI-lane-D-production-chat-and-launch.md` (RATIFIED — read §1.1, §3-P1, slice D0, §5 before coding). **Scope law:** `docs/specs/FI-lane-demarcation.md` §2.4. **Identity law:** `docs/specs/FI-lane-B-authenticated-principal-contract.md` (read §§1–7).
Branch: current branch of this worktree. Alembic head to chain off: `870fe4f2af87`.

## Mission

Land REQ-21's durable shell: a real `agent_thread` table, turn/message pagination, the typed
object-ref vocabulary on message projections, thread CRUD as governed tools + HTTP endpoints, the
L6 context-truncation inversion, and the missing `get_onboarding_input_for_artifact` index.

## Verified baseline (do not re-derive)

- `agent_turn.thread_id` is a bare `text NOT NULL` column; `agent_turn` carries
  `UNIQUE (id, workspace_id, thread_id)` (`agent_turn_thread_anchor`) and an index on
  `(workspace_id, thread_id, requested_at, id)` — migration `7e9269ed8a81`. `agent_thread_message`
  FKs to `agent_turn (id, workspace_id, thread_id)` and is `UNIQUE (workspace_id, thread_id,
  sequence)`. The 13 agent-plane receipt tables are **append-only by DB trigger**.
- Pagination defect: `agent_turns_for_project`
  (`platform/projections/clue_projections/agents.py:205-229`) has no LIMIT/cursor.
- L6 truncation defect: the L6 history assembler in `platform/agents/clue_agents/context.py`
  (loader ~:434-455; budget stop ~:614-641) iterates ascending `sequence` and stops at budget —
  a long thread silently drops its **newest** messages.
- `get_onboarding_input_for_artifact` (`subsystems/research/clue_research/stage0/governed.py:282`)
  has no supporting index for its `(workspace_id, project_id, artifact_key, actor, kind)` lookup —
  verify the exact predicate in that function before writing the index.
- The frontend's authored thread contract is `apps/frontend/docs/api-contracts/projects.md`
  (~lines 140–215: `POST /api/v1/projects/:projectId/threads`, rename/pin/archive, hierarchy).
  It is a frontend-authored *proposal* — implement the semantics, note deviations, do NOT edit it.
- House patterns to copy: `platform/api/clue_api/frontend_read/` (flag-gated router package with
  its own app conventions, error envelope, CORS posture), `*_tools.py` + `*_wiring.py` (governed
  tools + registration at the composition root), `libs/clue-config/clue_config/settings.py`
  (flags, default-off).

## Deliverables

### 1. One Alembic migration (hash revision id, `down_revision='870fe4f2af87'`, reversible)

- **`agent_thread`** (NOT under the append-only trigger — it is mutable shell state, not a receipt):
  `id text PK` (`thr_`-prefixed opaque id, follow the platform's id-mint convention),
  `workspace_id text NOT NULL`, `project_id text NOT NULL` (FK to the project table, matching how
  existing tables reference projects), `created_by_user_id text NOT NULL`,
  `created_via_membership_id text NOT NULL`, `status text NOT NULL` CHECK `('active','archived')`,
  `pinned boolean NOT NULL DEFAULT false`, `title text NULL`, `created_at`/`updated_at
  timestamptz NOT NULL`, `UNIQUE (id, workspace_id)`, plus a listing index
  `(workspace_id, project_id, created_at, id)`. Non-empty-text CHECKs per house style.
  **No FK to `platform_user`/`workspace_membership`** — those tables are Lane B B1's and do not
  exist on this branch; the FK-addition migration is a later join slice. No provider (Clerk) value
  ever enters any column (Lane B ruling 3).
- **`agent_turn` additive ownership columns:** `submitted_by_user_id text NULL`,
  `submitted_via_membership_id text NULL` (nullable — legacy/trial turns have none; serves Lane B
  contract §7's "a human turn persists submitter identity before enqueue"; consumed by D1/D2).
  Confirm the append-only trigger permits ALTER TABLE ADD COLUMN (it guards row UPDATE/DELETE, not
  DDL) and that inserting new rows with these columns works.
- **Grandfathered FK:** `agent_turn (thread_id, workspace_id) REFERENCES agent_thread
  (id, workspace_id) NOT VALID` — new writes validate, legacy trial rows are never validated.
  Assess whether `agent_thread_message` needs its own (its thread integrity already rides the
  composite FK to `agent_turn`) — if redundant, say so in the report instead of adding it.
- **The onboarding-input lookup index** matching `get_onboarding_input_for_artifact`'s predicate.
- Any composite index the new paginated readers need (e.g. `(workspace_id, project_id,
  requested_at, id)` on `agent_turn` — check what exists first).
- Gate: `make db-smoke` green (up → down → up on the per-branch throwaway DB).

### 2. Thread CRUD as governed tools + endpoints

- Tools (flat modules per house convention: `platform/api/clue_api/thread_tools.py` +
  `thread_wiring.py`): `create_thread@1`, `rename_thread@1`, `set_thread_pinned@1`,
  `archive_thread@1` — semantics per the frontend contract. Follow toolbelt conventions exactly
  (typed input/output models, preconditions with stable reason codes, A9 idempotency keyed on
  `operation_id`, effect class per existing steering/write precedent). Not human-only — agents may
  manage threads later (REQ-21). Workspace-scoped: every read/write filters `workspace_id`;
  cross-workspace access is a typed refusal, never a 500.
- HTTP endpoints in a new package `platform/api/clue_api/chat/` (router + schemas +
  `principal.py`), mounted on the projections app behind a new default-off flag (`chat_enabled` /
  `CLUE_CHAT_ENABLED`) — registration call only at the composition root; do not restructure
  `projections_app.py`. Reuse `frontend_read/app.py`'s error-envelope + CORS pattern (adopt, never
  rewrite; if generalization is needed, copy locally and note it). Endpoints invoke the governed
  tools (Doc A: the toolbelt is the only mutation path) and include thread listing for a project.
- **Principal seam (`chat/principal.py`):** a frozen `RequestPrincipal` dataclass mirroring Lane B
  contract §4 (`principal_kind, user_id, membership_id, workspace_id, role_key, permissions`) + a
  FastAPI dependency that yields an **injected test/dev principal** only under an explicit
  local/test guard and **refuses at startup/request in production mode** (Lane B §4/§5.6). No
  user-identity headers in domain code — the principal arrives by dependency injection only.
  Mark it clearly as the placeholder Lane B's canonical seam replaces at the B2 join.
- `created_by_user_id`/`created_via_membership_id` come from the principal; thread ids are minted
  server-side.

### 3. Paginated readers

- `agent_turns_for_project`: add keyset pagination (`limit` + opaque cursor over
  `(requested_at, id)`), preserving the existing return shape per page.
- New thread-scoped readers (same module): paginated turns-for-thread and
  messages-for-thread (cold-load surface for charter §3.6) — keyset over the existing
  `(workspace_id, thread_id, …)` indexes.
- Message summaries expose **typed refs**: `refs[]` of `DomainObjectRef` + a closed flavor
  vocabulary, projected from the existing durable ref rows (`agent_artifact_ref`,
  `agent_finalization`). Define the flavor vocabulary in one module. If a ref kind the charter
  needs cannot be represented in the existing closed `owner_kind`/`ref_role` vocabularies, STOP
  and report — do not widen a closed vocabulary without review.

### 4. L6 truncation inversion

In `platform/agents/clue_agents/context.py`: when thread history exceeds the assembly budget,
retain the **newest** messages (drop oldest), output remaining in chronological order. Preserve
`stable_key` semantics and every existing invariant (workspace-boundary check, ordering).

## Acceptance criteria (charter D0)

Thread CRUD round-trips over HTTP with the injected test principal; no provider id enters any row;
turn/message lists paginate correctly (keyset boundary tests: exact-limit, mid-page cursor,
cross-workspace isolation); a 200-message thread keeps its newest messages in L6 (test this
number); `make db-smoke` green; `make lint typecheck` clean on touched packages; targeted pytest
suites green (write DB-gated tests per house fixture conventions).

## Hard exclusions

Never touch: `platform/api/clue_api/frontend_read/**`, `apps/frontend/**`,
`api-contracts/accounts.md` **or** `projects.md`, FI-2 files (`membership.py`, `run_lineage`,
`account_entity_research.py`, `exa_deep_preparation.py`, `sumble_*`,
`account_research_fleet_launch.py`, `narrative/*`), Lane B territory (`platform/auth/**`,
`auth_wiring`), `turn_binding.py` / `turn_action.py` / `executor.py` /
`agent_execution_wiring.py` (a parallel agent owns them in D1). Composition-root files:
registration calls only. One migration, chained off head — no renumbering.

## Process

Work test-first where practical. Commit locally at coherent checkpoints with descriptive messages;
**never push; no AI/Claude attribution anywhere.** A parallel agent (D1) is working in this same
worktree on the files excluded above — commit only your own files; leave any foreign uncommitted
changes alone. Finish with: a `_memory/` session entry (what/why/verification/follow-ups) and a
final report listing every file, every deviation from the frontend's authored contract (for
founder review — do not record them into `projects.md` yourself), test output, and anything you
had to leave open.
