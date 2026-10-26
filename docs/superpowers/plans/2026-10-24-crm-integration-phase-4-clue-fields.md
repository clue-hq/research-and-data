# CRM integration Phase 4 — Clue's own fields: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A workspace owner or admin approves, once, setting up Clue's own fields in the connected
CRM (HubSpot: a "Clue" property group; Salesforce: Clue custom fields, a "Clue fields" permission
set and an external-id field); after that the Head of ABM writes Clue's research into those fields,
and links possible duplicate people instead of creating them twice.

**Architecture:** Setup is one more change kind, `clue_fields_setup`, on the Phase 2 write path
(`propose` → card → executor → wake): the agent proposes it with a new tool, only an owner or admin
can answer the card, and the executor runs the CRM's setup calls in order, idempotently, and records
what exists in a new registry (`crm_clue_fields`). Writing values is an ordinary `field_update` on a
field the registry says exists, its value checked against `read_crm_targets` like every Phase 3 value.
Duplicate links are a `link_duplicate` kind that uses the label/field the setup made.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async + Alembic (Postgres), Composio REST v3.1,
Next.js/TypeScript (card), pytest + `node:test`.

**Spec:** `docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md`
(§6.2 kinds, §6.3 grants, §6.8 option B, §6.10 duplicates, §15 calls 5 and 7),
`docs/superpowers/specs/crm-integration/rulings.md` (R-6.1, R-6.7, R-6.13, R-6.14, R-8.7, R-12.4,
R-12.11, R-13.1), and `docs/superpowers/specs/crm-integration/composio-api-notes.md` "Phase 4 shapes"
(the spike: every Composio call below was run on the two test CRMs).

---

## Decisions for the founder (rule on these before Task 1 starts)

Each has my recommendation; the plan is written for it. Record each ruling as R-13.x.

| # | Question | Recommendation | Why |
|---|---|---|---|
| D-1 | **The starting field set.** The design (call 5) lists: company — Clue tier, Clue ABM stage, Clue research link, Clue committee status; contact — Clue committee role, Clue contact link; plus an external id. Clue has no engagement data yet, so "ABM stage" could only ever say "Targeted", and "committee status" has no defined meaning | **Start with what Clue can fill today:** company — **Clue tier** (Tier 1/2/3), **Clue research link** (URL); contact — **Clue committee role** (Champion, Budget holder, Influencer, Blocker, End user), **Clue contact link** (URL); both — **Clue id** (the Clue entity id; Salesforce external id, HubSpot unique property). Add ABM stage and committee status when Clue has the data | An empty or always-"Targeted" field misleads reps; fields are cheap to add later through the same setup |
| D-2 | **Who may approve setup** | **Workspace owner or admin only** (`role_key` in owner, admin); any member's agent may propose it; the card tells an operator to ask an admin. Never "Always allow" (§6.2) | Design §6.2 and call 7; it changes the customer's CRM schema |
| D-3 | **How setup is proposed** | **A new tool `propose_clue_fields_setup@1`** (no arguments beyond the project): it builds the one fixed change from code, so the agent cannot choose field names, types or access | The field set and the permission set are Clue's contract, not the agent's judgement |
| D-4 | **What counts as a duplicate** | **Only when Clue's find-before-create finds more than one CRM record for one Clue person** (two contacts with the same email, or a create skipped as existing while another record also matches). Clue then proposes `link_duplicate` between them; it never guesses from names alone | Fails closed; names alone produce false pairs, and R-6.13 says Clue leaves records alone |
| D-5 | **The link URLs** (research link, contact link) | **`CLUE_APP_ORIGIN` + the account/contact page path**; written only when the origin is not a localhost address (so dev runs write nothing and production writes the real link) | A link to localhost in a customer's CRM is useless |
| D-6 | **HubSpot "Clue id" uniqueness** | **Create it with `hasUniqueValue: true`** and use it as `idProperty` for updates when Clue has no CRM id linked | Same safety as the Salesforce external id; one setup call |

---

## Global Constraints

- Every CRM call goes through the Phase 2 gateway, allowlist and executor; no new write path.
- `clue_fields_setup` is answered only by a workspace owner or admin, is never covered by a standing
  permission, and is never part of "Fully automatic" (§6.2, call 7).
- The card for setup says plainly what changes in the CRM, including, on Salesforce, that Clue creates
  a "Clue fields" permission set and assigns it to the connected user (R-13.1).
- Clue never deletes or archives a field, group, label or permission set it created; removing them is
  the customer admin's job.
- Values written into Clue fields follow R-8.7 / R-12.5 exactly as Phase 3 values: from
  `read_crm_targets` only, checked in prepare.
- Composio's outer `successful` is not trusted for schema calls: read the inner answer (the Salesforce
  "already a field named" trap, the HubSpot 409 `GROUP_EXISTS`).
- New Alembic revisions use hash ids, `down_revision` = the current single head (`31b850b308e6`),
  reversible, with a populated round-trip test.
- Every new flag goes in `.env.example` with its default (env parity rule).
- Agent-facing wording (skill, tool notes) is shown to the founder before it is written.

## Review Focus

1. **Setup half-done** (a crash, a refused call mid-way, a Salesforce user who is not a Salesforce admin)
   — a re-run finishes what is missing without duplicating anything, and the card says which part
   failed and why (Task 3).
2. **Fields deleted or renamed by the customer after setup** — a write to a Clue field the CRM no
   longer has is refused with a plain message, the registry marks it gone, and setup can be proposed
   again (Task 4).
3. **An operator answers the setup card** — refused with "Only a workspace owner or admin can set up
   Clue's fields"; nothing is sent (Task 2).
4. **A second connection / switched CRM** — the registry is per connection; the new connection starts
   with no Clue fields (Task 1).
5. **A duplicate pair where one record is not the person Clue researched** — `link_duplicate` needs both
   records to match the Clue entity's email/domain read before the write, like every Phase 3 person
   write (Task 5).

---

## File structure

| File | Responsibility |
|---|---|
| `alembic/versions/<hash>_crm_clue_fields.py` | `crm_clue_fields` (per connection: provider, state, the created field names/ids, permission set id, label type id, gone_at) |
| `platform/api/clue_api/crm/clue_fields.py` (new) | the fixed field set per provider (D-1), the registry DAL, `clue_field_names(connection)` |
| `platform/api/clue_api/crm/clue_fields_setup.py` (new) | the setup run: HubSpot group/properties/label; Salesforce fields/permission set/field permissions/assignment; idempotent, inner-answer checks |
| `platform/api/clue_api/crm/write_actions.py` | kinds `clue_fields_setup`, `link_duplicate`; Clue fields allowed in `field_update` only once set up |
| `platform/api/clue_api/crm/write_prepare.py` | values for Clue fields from the targets; duplicate pair checks |
| `platform/api/clue_api/crm/write_executor.py` | runs the setup kind and the duplicate link |
| `platform/api/clue_api/crm/write_answer.py` | owner/admin check for the setup card |
| `platform/api/clue_api/crm/targets.py` | offer `clue_tier`, `clue_research_link`, `clue_committee_role`, `clue_contact_link`, `clue_id` |
| `platform/api/clue_api/crm/write_tools.py` | `propose_clue_fields_setup@1` |
| `apps/frontend/src/features/integrations/model/crm-write.ts` + card | setup card wording; admin-only answer state; duplicate-link rows |
| catalog | crm-writing v5, Head of ABM next, recipe next, manual re-mint |

---

### Task 1: Clue-fields registry and the fixed field set

**Files:** Create `alembic/versions/<hash>_crm_clue_fields.py`, `platform/api/clue_api/crm/clue_fields.py`; Test `tests/db/test_crm_clue_fields_migration_db.py`, `tests/api/test_crm_clue_fields_db.py`

**Interfaces — Produces:**
- `CLUE_FIELDS: Mapping[CrmProvider, tuple[ClueField, ...]]` — `ClueField(key, object, crm_name, label, type, options)`; HubSpot names `clue_tier`, `clue_research_link`, `clue_committee_role`, `clue_contact_link`, `clue_id` in group `clue` ("Clue"); Salesforce `Clue_Tier__c`, `Clue_Research_Link__c`, `Clue_Committee_Role__c`, `Clue_Contact_Link__c`, `Clue_Id__c` (external id, unique), `Clue_Possible_Duplicate__c` (Contact lookup to Contact, for Task 5), permission set `Clue_Fields` ("Clue fields"). HubSpot's duplicate link is the contacts↔contacts association label "Possible duplicate", name `clue_possible_duplicate`.
- `async def clue_fields_state(conn, *, connection_id) -> ClueFieldsState | None` (status `ready` | `partial` | `gone`, created names, permission set id, duplicate label type id)
- `async def record_clue_fields(conn, *, connection_id, workspace_id, provider, created, permission_set_id, label_type_id, status) -> None`
- `async def mark_clue_field_gone(conn, *, connection_id, crm_name) -> None`

- [ ] **Step 1:** Failing tests: migration up/down/up with a populated row; the registry is per connection (a second connection sees none); `mark_clue_field_gone` flips state to `gone`.
- [ ] **Step 2:** Implement; run; commit `feat(crm): Clue-fields registry and the fixed field set (R-13.x)`.

### Task 2: `propose_clue_fields_setup@1`, the setup kind and the owner/admin card

**Files:** Modify `write_actions.py`, `write_tools.py`, `write_answer.py`, frontend `crm-write.ts` + card; Test `tests/api/test_crm_clue_fields_setup_propose_db.py`, `crm-write.test.ts`

**Interfaces — Consumes:** Task 1. **Produces:** kind `clue_fields_setup`; tool `propose_clue_fields_setup@1` input `{project_id}`, output the proposal id; answer refusal code `crm_setup_needs_admin`.

- [ ] **Step 1:** Failing tests: the tool proposes one change whose card lists every field of `CLUE_FIELDS[provider]` and, on Salesforce, the line "Creates a 'Clue fields' permission set and gives your connected Salesforce user access to these fields." (exact copy to be approved with the skill wording); no "Always allow" offered for it; an operator's Allow is refused `crm_setup_needs_admin` with "Only a workspace owner or admin can set up Clue's fields." and nothing is queued; an admin's Allow queues it; proposing again when state is `ready` is refused "Clue's fields are already set up in <CRM>."
- [ ] **Step 2:** Implement; run (CRM suites + `crm-write.test.ts` via `npx tsx --test`); commit.

### Task 3: The setup run (executor)

**Files:** Create `clue_fields_setup.py`; Modify `write_executor.py`; Test `tests/api/test_crm_clue_fields_setup_run_db.py`

**Interfaces — Consumes:** Tasks 1–2; the spike's call shapes (composio-api-notes "Phase 4 shapes"). **Produces:** `async def run_clue_fields_setup(crm, write) -> SetupOutcome` (per step: created / already there / failed with the CRM's message).

Order — HubSpot: property group `clue` on companies and contacts (409 `GROUP_EXISTS` = already there) → each property (409 = already there) → the contacts↔contacts association label "Possible duplicate" (keep its `typeId`). Salesforce: each custom field (inner `success: false` with "already a field named" = already there) → permission set `Clue_Fields` (look up by Name first) → one `FieldPermissions` row per field (read/edit; look up first) → `PermissionSetAssignment` to the connected user (`SALESFORCE_WHO_AM_I`; look up first) → read each field back with SOQL to prove access.

- [ ] **Step 1:** Failing tests with a fake CRM: a clean run creates everything in order and records `ready`; a re-run after everything exists sends no create that would duplicate and still records `ready`; a run that fails at the permission set (e.g. `INSUFFICIENT_ACCESS`) records `partial`, names the failed step in the change's message ("Salesforce refused the permission set: <CRM message>. The connected user needs to be a Salesforce admin."), and a later run resumes from it; the read-back proves access before `ready`.
- [ ] **Step 2:** Implement; run; commit.

### Task 4: Writing Clue fields

**Files:** Modify `targets.py`, `write_actions.py`, `write_prepare.py`, `write_executor.py`; Test `tests/api/test_crm_targets_db.py`, `tests/api/test_crm_write_prepare_db.py`, `tests/api/test_crm_write_executor_db.py`

**Interfaces — Consumes:** Task 1 (`clue_fields_state`). **Produces:** targets offer `clue_tier` (from the fit band, R-12.1), `clue_research_link` / `clue_contact_link` (D-5), `clue_committee_role` (from the persona, R-12.6 mapping, on both CRMs), `clue_id` (the entity id).

- [ ] **Step 1:** Failing tests: a `field_update` on a Clue field is refused "Clue's fields are not set up in <CRM> yet." when state is not `ready`; a value that is not what the targets offer is refused (R-8.7 path); on Salesforce the write goes through `custom_fields`, on HubSpot through properties; a write that the CRM answers "No such column"/unknown property marks the field gone and fails with "Clue's field <label> no longer exists in <CRM>; set up Clue's fields again."; the links are not offered when `CLUE_APP_ORIGIN` is a localhost address; Salesforce creates of a person or account also set `Clue_Id__c`.
- [ ] **Step 2:** Implement; run; commit.

### Task 5: Duplicate links

**Files:** Modify `write_actions.py`, `write_prepare.py`, `write_executor.py`, frontend card; Test `tests/api/test_crm_link_duplicate_db.py`

**Interfaces — Consumes:** Tasks 1, 3 (label type id; Salesforce field `Clue_Possible_Duplicate__c`, a Contact lookup, added to `CLUE_FIELDS["salesforce"]` in Task 1). **Produces:** kind `link_duplicate` (HubSpot `HUBSPOT_CREATE_OBJECT_ASSOCIATION` with the label; Salesforce `field_update` of `Clue_Possible_Duplicate__c`).

- [ ] **Step 1:** Failing tests: when find-before-create sees two CRM contacts for one Clue person (D-4), prepare proposes nothing new itself but the create's refusal message names both ids and suggests `link_duplicate`; a `link_duplicate` between two records that both match the Clue entity's email passes and is sent; one where a record does not match is refused `crm_personal_data_not_allowed`; without setup `ready` (or on HubSpot without the label) it is refused "Clue can't link duplicates in <CRM> until Clue's fields are set up." and nothing is written (R-6.14); Clue never removes a link it did not make.
- [ ] **Step 2:** Implement; run; commit.

### Task 6: Skill, tool notes, catalog

**Files:** `platform/agents/catalog/skills/crm-writing/v5/SKILL.md`, `tool_notes.yaml`, the next Head of ABM / recipe / manual (pattern of commit `fe2a74822`)

- [ ] **Step 1: Show the founder the skill substance first:** when to propose setup (the person asks for Clue's own fields, or a write needs one), that only an owner/admin can approve it, what to say on Salesforce about the permission set, writing Clue fields from the targets, and linking duplicates only when Clue found two CRM records for one person. **Write only the approved wording.**
- [ ] **Step 2:** Mint; pinning tests; `manual_build --check`; commit.

### Task 7: Live check on both test CRMs

- [ ] HubSpot (Conduit): propose setup as an operator → refused; as admin → group, 5 properties and the label exist (read back); write Clue tier/role/id on records from the Phase 3 runs; link two contacts as possible duplicates.
- [ ] Salesforce (Garner): setup as admin → fields, permission set, field permissions and assignment exist; the fields are readable/writable without any by-hand Setup step; write Clue fields; update a contact by `Clue_Id__c`.
- [ ] Delete one Clue field by hand (founder) → the next write marks it gone and the agent proposes setup again; re-run setup creates only the missing field.
- [ ] Record findings, status, rulings and memory; commit `Docs: CRM Phase 4 live check`.

---

## Not in this plan (and why)

- **ABM stage and committee status fields** — no data to fill them yet (D-1).
- **Removing Clue's fields** — the customer admin's job; Clue never deletes schema.
- **Leads** — Salesforce people stay Contacts (R-6.17).
- **Production readiness** (own OAuth apps, ZDR, HubSpot listing) — the next phase; the managed
  Composio apps were enough for the spike.
- **L-14** (code check for Clue-written messages) — undecided by the founder; not part of Phase 4.
