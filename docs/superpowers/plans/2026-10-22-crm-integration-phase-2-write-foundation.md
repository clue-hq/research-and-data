# CRM integration Phase 2 — write foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Head of ABM agent can propose changes to the connected CRM; a person allows them on
one grouped permission card (or a standing permission covers them); a background executor writes
them safely and wakes the chat with per-record results; every write is logged and can be undone
through chat.

**Architecture:** A new tool `propose_crm_changes@1` takes the agent's chosen Composio write
actions (found by search, R-6.23), checks them against a write allowlist that carries our own data
per action, reads the current values, marks overwrites, and either queues them (covered by a
standing permission) or opens one `crm_write_permission` gate whose snapshot is the grouped card.
The gate answer (a normal gate-response turn) records the selection and any "Always allow", then
offers a `crm_write` fleet task. The executor logs each change before sending, re-checks for
conflicts, sends in batches with retries, throttling and the Salesforce budget, then queues a
`crm_writes_finished` wake turn. Two read tools (`crm_write_log@1`, `manage_crm_grants@1`) cover
"what did Clue change" and revoking permissions; undo is a new proposal of reverse changes.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async/asyncpg, Alembic (raw SQL), the governed
toolbelt (`clue_toolbelt`), the fleet work queue (`clue_fleet`), Composio REST v3.1 over `httpx`;
Next.js frontend (Zod models, repositories, `node:test`).

**Spec:** `docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md`
§6–§8 (reviewed 2026-10-22), the card spec
`docs/superpowers/specs/crm-integration/2026-10-22-crm-write-permission-card-design.md` (the current
card, R-6.22), and `docs/superpowers/specs/crm-integration/rulings.md` (R-6.x, R-7.x, R-8.x).

## Global Constraints

- Composio REST v3.1 only, pinned toolkit versions as in Phase 1 (`hubspot 20261020_01`,
  `salesforce 20261018_00`); user id `ws_<workspace_id>`.
- **Only allowlisted write actions can run** (R-6.23). Never allowlisted: merges, deletes (except
  removing what Clue itself created, per `crm_record_link`, R-6.25), `*_FROM_NL`, Composio GDPR
  erasure, consent fields (email opt-out, subscription status, do-not-call, GDPR legal basis, R-8.1).
- **Personal data (R-8.7):** person fields allowed: first/last name, job title, company link,
  **verified** work email, buying/committee role, LinkedIn URL. **Never:** phone fields, personal
  research details, sensitive data. Phase 2 enforces the field rules; the check that a person's
  values pass Clue's identity-binding and jurisdiction/use-class gates (and that the email is
  verified) belongs to Phase 3, where Clue first creates contacts — each change already carries
  `source_ref` (the claim) for it.
- **Overwriting a value a person set always asks** — never covered by a standing permission (R-6.5).
  When it cannot be shown that Clue set the current value, a person is assumed (R-6.25 call 11).
- Card: grouped by action + field with counts; overwrites listed one by one and unticked by default;
  no "Fully automatic" on the card; one live write card per chat (a newer proposal replaces an
  unanswered one); header shows the CRM's logo (R-6.21, R-6.22).
- No permission question at connect; the first card offers "Always allow" (R-6.24).
- Any workspace member can answer a card and revoke permissions (R-6.8); setting up Clue's own
  fields needs an owner/admin (R-6.25 call 7 — `clue_fields_setup` itself is Phase 4).
- Permissions belong to the current connection; a new connection starts with none (R-6.25).
- Retries: temporary failures (rate limit, timeout, CRM unavailable) automatically with back-off;
  refusals never retried as-is; expired connection pauses the batch (R-7.2).
- Salesforce: every call goes through `SalesforceBudget.take_call` (R-7.3–R-7.5).
- No new state that lives only on a worker's disk (AW-8): everything here is Postgres.
- Env parity: every new setting in `.env.example` with its default, and in the lane `.env`.
- Alembic: random-hash ids, `down_revision = "c87ba03cfc4e"` for the first new revision, raw
  `op.execute`, named CHECKs, reversible.
- Skill wording is shown to the founder before it is written (standing rule); tool inputs never use
  raw-content names (`body`, `content`, `text`…, guard `tests/api/test_tool_input_names.py`).
- DB tests only on the throwaway DB `clue_nashville_crm_test`; never broad suites with live keys.
- Commits: no AI attribution; never push.

## Review Focus

1. **A record changes in the CRM between the card and "Allow"** → that change is skipped as
   `conflict`, nothing is written for it, the rest go through. (Task 6
   `test_a_record_changed_since_the_card_is_skipped_as_conflict`.)
2. **The executor dies mid-batch and the task is retried** → no change is sent twice; already-sent
   changes keep their stored result. (Task 6 `test_a_retried_task_never_sends_a_change_twice`.)
3. **The connection expires while sending** → the proposal pauses with what was done so far and
   resumes in order after a reconnect. (Task 6 `test_an_expired_connection_pauses_and_resumes`.)
4. **Two members answer the same card, or someone answers a replaced card** → one answer wins; the
   replaced card refuses with `GATE_REPLACED`. (Task 7
   `test_a_replaced_card_cannot_be_answered`, `test_a_card_is_answered_once`.)
5. **The agent proposes a forbidden write** (a consent or phone field, a merge, an action outside the
   allowlist) → refused before any card, with a reason the agent can act on. (Task 4
   `test_forbidden_writes_are_refused_before_the_card`.)

---

## File Structure

| File | Responsibility |
|---|---|
| `alembic/versions/<hash>_crm_write_foundation.py` | tables `crm_write_proposal`, `crm_write`, `crm_write_grant`, `crm_record_link`; gate kind `crm_write_permission` + answer-trigger branch; derivation `crm_writes_finished` |
| `alembic/versions/<hash>_crm_write_fleet_kind.py` | fleet kind `crm_write` |
| `platform/api/clue_api/crm/write_actions.py` | the write allowlist and its per-action data; forbidden-field rules |
| `platform/api/clue_api/crm/writes.py` | DAL: proposals, changes/log, grants, record links |
| `platform/api/clue_api/crm/write_prepare.py` | preparing a batch: parse, find-before-create, before-values, overwrite marker, scope, card groups |
| `platform/api/clue_api/crm/write_tools.py` | `propose_crm_changes@1`, `crm_write_log@1`, `manage_crm_grants@1` |
| `platform/api/clue_api/crm/write_executor.py` | the `crm_write` fleet handler |
| `platform/api/clue_api/crm/wake.py` | + `queue_crm_writes_finished_turn` |
| `platform/api/clue_api/agent_gate.py`, `chat/router.py`, `chat/schemas.py` | the new gate kind and its answer |
| `platform/api/clue_api/frontend_read/crm.py` | + `GET /crm/proposals/{proposal_id}` (card progress) |
| `apps/frontend/src/features/integrations/model/crm-write.ts` | card model: snapshot → groups, selection, answer body |
| `apps/frontend/src/features/projects/components/crm-write-permission-card.tsx` (+ `.module.css`) | the card (all six states) |
| catalog: `head-of-abm/v77`, skill `crm-writing/v1`, recipe 37, manual re-mint | the agent gets the tools |

---

### Task 1: Spike — the write actions we allow first

**Files:**
- Modify: `docs/superpowers/specs/crm-integration/composio-api-notes.md` (new section "Writes")

**Interfaces:**
- Produces: for each provider, the verified slug, argument shape, batch variant and response shape
  of: (a) update one/many company (HubSpot) / account (Salesforce) fields; (b) update contact fields;
  (c) add records to a HubSpot list / Salesforce campaign (and remove a member Clue added); (d)
  create contact; (e) create company/account; (f) read a record's current field values (for
  before-values). Also: how each CRM reports a validation rule, a required field, a duplicate rule,
  a permission refusal (the raw `ExecuteResult.error` text).

- [ ] **Step 1:** With the dev keys, `search_tools` on both pinned toolkits for each intent above;
  record candidate slugs and their input schemas (no writes yet).
- [ ] **Step 2:** On the two test CRMs only (HubSpot developer test account, Salesforce Developer
  Edition org), run one update of a harmless field on one test company/account, one invalid update
  (a non-existent picklist value) and one with a missing required field; record each raw response.
  Revert the harmless field afterwards.
- [ ] **Step 3:** Write the "Writes" section: a table per provider (intent → slug, key arguments,
  batch limit, response, error text samples). Commit `Docs: Composio write actions (Phase 2 spike)`.

### Task 2: Schema — proposals, write log, permissions, record links, gate kind, wake, fleet kind

**Files:**
- Create: `alembic/versions/<hash>_crm_write_foundation.py`, `alembic/versions/<hash>_crm_write_fleet_kind.py`
- Modify: `platform/api/clue_api/agent_gate.py` (`CRM_WRITE_PERMISSION = "crm_write_permission"` in
  `GATE_KINDS`), `platform/api/clue_api/agent_turn_submission.py` (`DERIVATION_CRM_WRITES_FINISHED =
  "crm_writes_finished"`), `platform/fleet/clue_fleet/enums.py` (`CRM_WRITE = "crm_write"`, last)
- Test: `tests/db/test_crm_write_foundation_migration.py`

**Interfaces:**
- Produces tables:
  - `crm_write_proposal(proposal_id uuid pk, workspace_id, connection_id → workspace_integration_connection, project_id, thread_id, turn_id uuid, gate_id uuid null, status, created_at, answered_by_user_id null, answered_at null, finished_at null)`; `status` CHECK in `('prepared','awaiting_permission','queued','sending','paused','finished','declined','replaced')`.
  - `crm_write(write_id uuid pk, proposal_id fk, workspace_id, connection_id, ordinal int, slug, arguments jsonb, kind, object, record_ref text null (null = new), record_label, field null, before_value jsonb null, after_value jsonb null, overwrites_person boolean, reason text, source_ref text null, reverses_write_id uuid null, scope_key text, covered_by text null ('grant:<id>' | 'gate:<id>'), selected boolean, status, failure_kind null, crm_message null, retryable boolean null, crm_id null, idempotency_key text unique, attempts int default 0, sent_at null, finished_at null)`; `status` CHECK in `('proposed','queued','sending','succeeded','failed','skipped')`; `failure_kind` CHECK in `('validation_rule','required_field','duplicate_rule','permission','not_found','rate_limited','connection_expired','conflict','other')`.
  - `crm_write_grant(grant_id uuid pk, workspace_id, connection_id, scope_kind CHECK in ('field','kind','fully_automatic'), kind null, object null, field null, granted_by_user_id, granted_at, revoked_by_user_id null, revoked_at null)`; a partial unique index on live grants per `(connection_id, scope_kind, kind, object, field)`.
  - `crm_record_link(workspace_id, connection_id, crm_object, crm_id, clue_entity_id null, created_by_clue boolean, created_by_write_id uuid null, linked_at)`, primary key `(connection_id, crm_object, crm_id)`.
  - `agent_gate_kind` CHECK gains `crm_write_permission`; `agent_gate_answer_validate()` gains a branch that accepts, for this kind only, `decision_payload` jsonb `{"selected_write_ids": [uuid...], "always_allow": [scope_key...]}` (both arrays required for `approved`; empty object for `rejected`).
  - `agent_turn_submission_derivation_kind` CHECK gains `crm_writes_finished`.
  - `fleet_task_kind` gains `crm_write` (own migration, `ADD VALUE IF NOT EXISTS`; downgrade refuses while rows exist, per `fd8795c4fd5a`).

- [ ] **Step 1: Failing test** `test_crm_write_foundation_round_trips`: upgrade head; insert a
  proposal, a write, a grant, a record link; insert a `crm_write_permission` gate and an `approved`
  answer with the payload above (accepted) and one with an unknown key (refused); insert a
  submission with derivation `crm_writes_finished`; downgrade to `c87ba03cfc4e` (rows of the new kind
  and derivation are deleted first; tables gone); upgrade again. Plus
  `test_the_fleet_kind_enum_has_crm_write_last_and_matches_the_db`.
- [ ] **Step 2:** Run — FAIL (tables and values missing).
- [ ] **Step 3:** Write both migrations and the three constants.
- [ ] **Step 4:** Run the two tests and `tests/db/test_arv2_display_page_kind_migration.py` → PASS;
  `uv run alembic heads` → one head.
- [ ] **Step 5:** Commit `feat(crm): schema for governed CRM writes`.

### Task 3: The write allowlist and its rules

**Files:**
- Create: `platform/api/clue_api/crm/write_actions.py`
- Modify: `platform/api/clue_api/crm/tools.py` (`FindCrmActionsTool` returns allowlisted writes too,
  each marked `"access": "write"`; `RunCrmActionTool` refuses a write slug with
  `crm_action_is_a_write` — "propose it with propose_crm_changes")
- Test: `tests/api/test_crm_write_actions.py`

**Interfaces:**
- Produces:
  ```python
  WriteKind = Literal["field_update", "list_membership", "list_removal", "create_contact", "create_company", "link_duplicate"]
  @dataclass(frozen=True)
  class ParsedChange:
      object: str                    # "company" | "contact" | "account" | ...
      record_ref: str | None         # CRM id; None = a new record
      fields: Mapping[str, object]   # field -> value the change sets (empty for membership)
      list_ref: str | None           # list/campaign id for membership kinds
      label: str                     # record name or email for the card
  @dataclass(frozen=True)
  class WriteActionSpec:
      provider: CrmProvider
      slug: str
      kind: WriteKind
      object: str
      parse: Callable[[Mapping[str, object]], ParsedChange]
      read_before: str | None         # read slug that returns the record's current fields
      find_existing: tuple[str, str] | None   # (read slug, key field) for find-before-create
      batch: BatchSpec | None         # (batch slug, max size, build(list[args]) -> args, split(result) -> per-item)
  WRITE_ACTIONS: Mapping[tuple[CrmProvider, str], WriteActionSpec]
  def write_spec(provider: CrmProvider, slug: str) -> WriteActionSpec | None
  def forbidden_fields(provider: CrmProvider, object: str) -> frozenset[str]   # consent + phone
  def scope_key(spec: WriteActionSpec, field: str | None) -> str   # "field:<object>.<field>" | "kind:<kind>"
  ```
  The allowlist holds the Task 1 slugs for: company/account field update, contact field update,
  list/campaign add and remove, contact create, company/account create. `link_duplicate` is
  declared but holds no slug until Phase 3 (needs option B / association labels).

- [ ] **Step 1: Failing tests:**
  - `test_no_allowlisted_write_merges_deletes_or_runs_an_llm` — no slug in `WRITE_ACTIONS` matches
    `MERGE|DELETE|_FROM_NL|GDPR|ERASE`, except `list_removal` slugs (removing a member).
  - `test_consent_and_phone_fields_are_forbidden` — for HubSpot contacts `hs_email_optout`,
    `phone`, `mobilephone`; for Salesforce contacts `HasOptedOutOfEmail`, `DoNotCall`, `Phone`,
    `MobilePhone`, `HomePhone` are in `forbidden_fields`.
  - `test_each_spec_parses_its_own_example` — every spec's `parse` turns the Task 1 example
    arguments into the expected `ParsedChange`.
  - `test_find_crm_actions_lists_writes_and_run_crm_action_refuses_them` (fake gateway).
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement the module from the Task 1 table; extend the two tools.
- [ ] **Step 4:** Run the file and `tests/api/test_crm_tools_db.py` → PASS.
- [ ] **Step 5:** Commit `feat(crm): write allowlist with forbidden actions and fields`.

### Task 4: Preparing a batch

**Files:**
- Create: `platform/api/clue_api/crm/writes.py`, `platform/api/clue_api/crm/write_prepare.py`
- Test: `tests/api/test_crm_write_prepare_db.py`

**Interfaces:**
- Consumes: Task 3 (`write_spec`, `forbidden_fields`, `scope_key`); `latest_connection`,
  `SalesforceBudget.take_call`, `ComposioGateway.execute`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class ProposedChange:          # one item of the tool input
      slug: str; arguments: Mapping[str, object]; reason: str
      source_ref: str | None = None; reverses_write_id: UUID | None = None
  @dataclass(frozen=True)
  class PreparedChange:
      write_id: UUID; spec: WriteActionSpec; parsed: ParsedChange; field: str | None
      before: object | None; after: object | None; overwrites_person: bool
      scope_key: str; covered_by: str | None; reason: str; source_ref: str | None
  class WriteRefused(Exception): reason_code: str   # crm_write_not_allowed | crm_field_forbidden | crm_write_not_parsable
  async def prepare_changes(conn, *, gateway, budget, connection: CrmConnection, proposal_id: UUID,
                            changes: Sequence[ProposedChange]) -> list[PreparedChange]
  def card_snapshot(prepared: Sequence[PreparedChange], *, provider, project_name) -> dict   # card spec §6 shape
  ```
  `writes.py`: `insert_proposal`, `insert_writes`, `live_grants(conn, *, connection_id)`,
  `covering_grant(grants, scope_key, kind) -> UUID | None`, `set_proposal_status`,
  `clue_wrote_current_value(conn, *, connection_id, record_ref, field, value) -> bool`,
  `insert_grant`, `revoke_grant`, `record_link`.
- Rules: one `PreparedChange` per (record, field) — a field update touching three fields is three
  changes; membership and create changes have `field=None`. Before-values come from `read_before`
  (one read per record, batched where the read allows). `overwrites_person` is true when the before
  value is non-empty, differs from the new value, and `clue_wrote_current_value` is false (R-6.25
  call 11). `covered_by` is a grant id only when `overwrites_person` is false. Create kinds run
  `find_existing` first: a match turns a create into a field update of the found record (or into a
  no-op when nothing would change). Person fields outside R-8.7's list are refused
  `crm_field_forbidden`.

- [ ] **Step 1: Failing tests** (fake gateway, test DB):
  - `test_forbidden_writes_are_refused_before_the_card` — a consent field, a phone field, a slug
    not in the allowlist → `WriteRefused` with the matching code; nothing inserted.
  - `test_a_filled_value_a_person_set_is_an_overwrite_and_a_value_clue_wrote_is_not`.
  - `test_an_empty_field_is_a_fill_not_an_overwrite`.
  - `test_a_create_that_finds_the_record_becomes_an_update`.
  - `test_a_grant_covers_fills_but_never_overwrites`.
  - `test_the_card_snapshot_groups_by_action_and_field_with_counts_and_lists_overwrites_alone` —
    48 list adds + 12 tier fills + 2 overwrites → 2 groups (48, 12; value summary "Empty today →
    Tier 1 (5), Tier 2 (7)") and 2 overwrite rows, unticked.
  - `test_salesforce_before_reads_take_from_the_budget`.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement `writes.py` and `write_prepare.py`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(crm): prepare a write batch (before-values, overwrites, scopes, card)`.

### Task 5: `propose_crm_changes@1`

**Files:**
- Create: `platform/api/clue_api/crm/write_tools.py`
- Modify: `platform/api/clue_api/crm/tools.py` (`build_crm_tools` adds the three new tools)
- Test: `tests/api/test_crm_propose_db.py`

**Interfaces:**
- Consumes: Task 4.
- Produces: `ProposeCrmChangesTool` — `name="propose_crm_changes"`, `effect_class=WRITE`,
  `replay=DOMAIN_IDEMPOTENT` (proposal id = uuid5 of the turn ref and the input digest),
  `pin_requirements=("project",)`; input `{changes: list[{slug, arguments, reason, source_ref?,
  reverses_write_id?}] (1–500), source_turn_ref (TRUSTED_TURN_FIELD)}`; output `{proposal_id,
  state: "queued" | "awaiting_permission", gate_id?, gate_ref?, gate_kind?, covered: int,
  needs_permission: int, groups: [...], overwrites: int}`. `gate_kind` in the output marks it
  gate-opening for the manual.
- Behaviour: all changes covered → proposal `queued`, offer the `crm_write` task (dedup key
  `crm-write:<connection_id>`), output `state="queued"`. Otherwise → mark any open earlier
  `crm_write_permission` proposal of this thread `replaced`; insert the gate (`subject_snapshot` =
  `card_snapshot`, addressee = the turn's user, `permitted_decisions=("approved","rejected")`);
  covered changes wait with the rest. Refusals: `crm_not_connected`, `crm_connection_expired`, and
  Task 4's codes, as `PreconditionFailed`.

- [ ] **Step 1: Failing tests:** `test_covered_changes_are_queued_without_a_card`,
  `test_uncovered_changes_open_one_card_and_replace_an_open_one`,
  `test_a_replayed_call_returns_the_same_proposal`, plus the input-name guard still passing.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement and register.
- [ ] **Step 4:** Run with `tests/api/test_tool_input_names.py` → PASS.
- [ ] **Step 5:** Commit `feat(crm): propose_crm_changes opens one grouped permission card`.

### Task 6: The executor and the wake turn

**Files:**
- Create: `platform/api/clue_api/crm/write_executor.py`
- Modify: `platform/api/clue_api/crm/wake.py`, `platform/api/clue_api/fleet_wiring.py`,
  `platform/api/clue_api/fleet_main.py`, `libs/clue-config/clue_config/settings.py`, `.env.example`, `.env`
- Test: `tests/api/test_crm_write_executor_db.py`

**Interfaces:**
- Consumes: Tasks 2–5; `WorkHandler`/`WorkContext`/`WorkResult`; `SalesforceBudget`.
- Produces: `CrmWriteHandler(kind=FleetTaskKind.CRM_WRITE)` and `build_crm_write_handler(*,
  settings, secrets, conn_factory, artifacts) -> CrmWriteHandler | None`;
  `queue_crm_writes_finished_turn(conn, artifacts, *, proposal) -> UUID | None` (idempotency key
  `crm-writes-finished:<proposal_id>`, derived from the proposal's turn).
- Settings (defaults; also in `.env.example`): `CLUE_CRM_WRITE_MAX_ATTEMPTS=4`,
  `CLUE_CRM_WRITE_RETRY_BASE_S=30`, `CLUE_CRM_WRITE_MIN_INTERVAL_S=0.1`.
- Behaviour, per `queued` proposal of the connection (oldest first):
  1. Selected changes only; mark `sending`.
  2. **Conflict check:** re-read each record's current value; if it differs from `before_value`,
     the change is `skipped` / `conflict`.
  3. Group by slug; use the spec's `batch` when present, else one call per change; wait
     `MIN_INTERVAL_S` between calls; Salesforce calls go through `take_call`.
  4. Before sending, set `status='sending'`, `attempts += 1`, `sent_at`; a change whose status is
     already `succeeded`/`failed`/`skipped` is never sent again (idempotency key).
  5. Map results: success → `succeeded` + `crm_id` (+ `record_link(created_by_clue=True)` for
     creates and list adds); a refusal → `failed` with `failure_kind` from the CRM's message
     (Task 1 samples) and `crm_message` verbatim, `retryable=false`; `rate_limited`/`unavailable`
     → back to `queued`, `WorkResult(requeue=True, requeue_after=RETRY_BASE_S * 2**(attempt-1))`
     until `MAX_ATTEMPTS`, then `failed` `retryable=true`; `connection_expired` →
     `mark_expired`, proposal `paused`, task finishes; on reconnect the next `crm_write` task picks
     the paused proposal up again in order.
  6. Proposal `finished` → `queue_crm_writes_finished_turn` with a plain summary ("58 done, 2
     failed, 1 skipped — read the details with crm_write_log(proposal_id=…)").

- [ ] **Step 1: Failing tests** (fake gateway that can fail on chosen calls):
  `test_selected_changes_are_sent_and_logged_before_sending`,
  `test_a_record_changed_since_the_card_is_skipped_as_conflict`,
  `test_a_retried_task_never_sends_a_change_twice`,
  `test_a_rate_limit_requeues_with_backoff_and_a_refusal_is_not_retried`,
  `test_an_expired_connection_pauses_and_resumes`,
  `test_a_finished_proposal_wakes_its_chat_once`.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement the handler, the wake, the settings, and the fleet wiring (three edits
  per the interface map: `build_multi_work_worker` keyword, kind guard, `fleet_main` construction).
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(crm): write executor with conflict check, retries and wake turn`.

### Task 7: Answering the card, and its progress read

**Files:**
- Modify: `platform/api/clue_api/chat/schemas.py` (`GateResponseRequest.crm_write: CrmWriteAnswer | None`
  with `selected_write_ids: list[UUID]`, `always_allow: list[str]`), `platform/api/clue_api/chat/router.py`
  (`_checked_gate` allowlist + post-answer action), `platform/api/clue_api/frontend_read/crm.py`
  (`GET /crm/proposals/{proposal_id}`)
- Test: `tests/api/test_crm_write_answer_db.py`

**Interfaces:**
- Consumes: Tasks 2, 4, 6.
- Produces: post-answer action — `approved`: set `selected` per id (any id not in the proposal →
  422 `CRM_WRITE_UNKNOWN_CHANGE`), insert one grant per `always_allow` scope key (overwrite rows'
  scopes are never granted), proposal `queued`, `answered_by/at`, offer the `crm_write` task;
  `rejected`: proposal `declined`. A `replaced` proposal → 409 `GATE_REPLACED`. The gate-response
  message the agent receives names the counts ("Allowed 60 changes; always allow adding contacts to
  Clue lists"). Route `GET /crm/proposals/{id}` → `{state, provider, counts{done,failed,skipped,
  pending}, groups[...], failed[{label, field, crm_message}], skipped[{label, reason}],
  answeredBy, answeredAt}` (any workspace member; card spec §6 outcome).

- [ ] **Step 1: Failing tests:** `test_allow_queues_the_selected_changes_and_records_always_allow`,
  `test_dont_allow_declines_and_sends_nothing`, `test_a_replaced_card_cannot_be_answered`,
  `test_a_card_is_answered_once`, `test_an_overwrite_scope_is_never_granted`,
  `test_the_progress_read_reports_counts_and_crm_messages`.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run with `tests/api/test_lane_d4_agent_gate_db.py` → PASS.
- [ ] **Step 5:** Commit `feat(crm): answering the write card queues the selected changes`.

### Task 8: `crm_write_log@1` and `manage_crm_grants@1`

**Files:**
- Modify: `platform/api/clue_api/crm/write_tools.py`
- Test: `tests/api/test_crm_write_log_tools_db.py`

**Interfaces:**
- Produces: `CrmWriteLogTool` (`READ`, `EFFECT_FREE`) — input `{proposal_id?, record?, status?,
  since_days? (default 7), limit (≤200)}` → rows `{write_id, when, record_label, record_ref, field,
  before, after, status, failure_kind, crm_message, reason, proposal_id}`; the before values let the
  agent propose an undo (`reverses_write_id`). `ManageCrmGrantsTool` (`WRITE`, `DOMAIN_IDEMPOTENT`) —
  input `{action: "list" | "revoke", grant_id?}` → the live grants in plain words ("Always allow
  setting “ICP tier” on companies — by Aryan, 22 Oct"); revoking stamps `revoked_by/at`. Granting
  is only through the card (and later the settings page).

- [ ] **Step 1: Failing tests:** `test_the_log_answers_what_changed_this_week`,
  `test_an_undo_proposal_carries_the_before_values`, `test_grants_are_listed_and_revoked`,
  `test_a_new_connection_starts_with_no_grants`.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(crm): write log and permission tools`.

### Task 9: The permission card in the chat

**Files:**
- Create: `apps/frontend/src/features/integrations/model/crm-write.ts` (+ `crm-write.test.ts`),
  `apps/frontend/src/features/projects/components/crm-write-permission-card.tsx` (+ `.module.css`)
- Modify: `apps/frontend/src/features/projects/model/chat-gate.ts` (`SUPPORTED_GATE_KINDS`, title),
  `apps/frontend/src/features/projects/model/chat-turn.ts` (`GateResponseSchema.crm_write`),
  `apps/frontend/src/features/projects/components/chat-message-part.tsx` (render the card for this
  gate kind), `apps/frontend/src/features/integrations/data/crm.repository.ts`
  (`fetchCrmProposal`), `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts`
  (gate decision carries the `crm_write` answer)

**Interfaces:**
- Consumes: the gate snapshot (Task 4 `card_snapshot`), Task 7's answer body and progress route.
- Produces: `crmWriteCard(snapshot) -> CrmWriteCardModel`, `initialSelection(card)` (groups ticked,
  overwrites unticked), `toggleGroup/toggleRecord`, `selectedCount`, `crmWriteAnswer(card,
  selection, alwaysAllow) -> {selected_write_ids, always_allow}`, wording per card spec §5;
  `CrmWritePermissionCard` with the six states (asking, sending — polls `GET /crm/proposals/{id}`
  every 2 s while visible, done, not allowed, replaced, paused), frame and tokens as the connect card.

- [ ] **Step 1: Failing tests** (`crm-write.test.ts`): `groups default ticked and overwrites
  unticked`, `unticking a record makes its group partial`, `the answer lists exactly the ticked
  changes`, `wording follows the CRM (list vs campaign, company vs account, singular)`.
- [ ] **Step 2:** `npx tsx --test src/features/integrations/model/crm-write.test.ts` → FAIL.
- [ ] **Step 3:** Implement the model and the card; wire it into the chat.
- [ ] **Step 4:** Tests PASS; `npm run lint`; with the stack down `npm run design-system:build && npm run build` green.
- [ ] **Step 5:** Commit `feat(crm): the write permission card`.

### Task 10: The `crm-writing` skill and the catalog bump

**Files:**
- Create: `platform/agents/catalog/skills/crm-writing/v1/SKILL.md`, `platform/agents/catalog/profiles/head-of-abm/v77/profile.yaml`,
  `platform/execution/recipes/recipe0-stage0-v37.json`
- Modify: `agent_registry_wiring.py` (grants `propose_crm_changes`, `crm_write_log`,
  `manage_crm_grants` to HEAD_OF_ABM; active `v77`), `recipe_contracts.py`, `recipe_wiring.py`,
  `conversation_turns.py` (`CONVERSATION_RECIPE_VERSION = 37`), `stage0_recipe.py` (pins),
  `chat/composer_context.py`, `platform/agents/catalog/manual/tool_notes.yaml`; manual re-mint
  (`uv run python -m clue_api.manual_build --write`), and the pinning tests
- Test: `tests/api/test_agent_registry_wiring.py`, `tests/api/test_recipe_contracts.py`,
  `tests/agents/test_catalog.py`, `tests/agents/test_manual_builder.py`, `tests/agents/test_tool_authority_audit.py`

- [ ] **Step 1:** Draft the skill's substance (design §8.2 `crm-writing`: what Clue writes and why,
  finding a write action by search, one batch per decision with a reason per change, reading the
  card's answer, repairing failed rows from the CRM's message, never touching consent or phone
  fields, R-8.7's person fields only, undo through `crm_write_log`) and **show it to the founder;
  write only the approved wording.**
- [ ] **Step 2:** Bump the catalog (v77, recipe 37, manual, tool notes); update the pinning tests'
  expected values.
- [ ] **Step 3:** Run the five test files → PASS.
- [ ] **Step 4:** Commit `feat(crm): Head of ABM v77 can propose CRM writes`.

### Task 11: Live check on the test CRMs and the record

**Files:** `docs/superpowers/specs/crm-integration/status.md`, `rulings.md` (any new decision),
`_memory/2026-10-20-crm-integration-phase1.md`

- [ ] **Step 1:** Migrate the stack DB, restart workers and APIs.
- [ ] **Step 2 (Conduit, HubSpot):** in a chat, ask the agent to set a harmless field on two test
  companies; the card shows one group (and an overwrite row if a value exists); allow with "Always
  allow"; watch the executor, the wake turn and the values in HubSpot (read back); ask "what did
  Clue change today?" (`crm_write_log`); ask to undo; ask to stop the standing permission
  (`manage_crm_grants`).
- [ ] **Step 3 (Garner, Salesforce):** one field update on a test account, including one that the
  org refuses (a picklist value it doesn't have) — the done state shows Salesforce's message and the
  agent asks how to fix it.
- [ ] **Step 4:** Record results, any findings and cost in the status, the memory log and a findings
  note; commit `Docs: CRM Phase 2 live check`.
